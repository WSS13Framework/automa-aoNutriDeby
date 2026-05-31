"""
mobile_api.py — Endpoints do app NutriDeby (paciente-facing).

Rotas:
  POST /patients/register         → cadastro + trial 7 dias
  POST /patients/auth             → login JWT
  POST /patients/{id}/food-log    → registrar refeição [paywall]
  GET  /patients/{id}/daily-summary → resumo do dia [paywall]
  GET  /patients/{id}/week-summary  → gráfico semanal [paywall]
"""
from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, field_validator

from nutrideby.api.deps import get_settings
from nutrideby.config import Settings

router = APIRouter(prefix="/patients", tags=["mobile"])

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30


# ── Schemas ────────────────────────────────────────────────────────────────────

class PatientRegisterRequest(BaseModel):
    name: str
    email: str
    cpf: str
    password: str = Field(min_length=6)
    phone_number: str  # E.164 ex: +5511999999999

    @field_validator("cpf")
    @classmethod
    def only_digits(cls, v: str) -> str:
        return re.sub(r"\D", "", v)

    @field_validator("phone_number")
    @classmethod
    def e164(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if not digits.startswith("55"):
            digits = "55" + digits
        return digits


class PatientAuthRequest(BaseModel):
    login: str  # email ou CPF
    password: str


class FoodItem(BaseModel):
    name: str
    amount: str = ""
    calories: float = 0.0
    protein: float = 0.0
    carbs: float = 0.0
    fat: float = 0.0


class FoodLogCreate(BaseModel):
    meal_type: str  # cafe_da_manha | almoco | lanche | jantar | ceia
    foods: list[FoodItem]
    photo_url: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = b"nutrideby_salt_v1"
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260000).hex()


def _verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(_hash_password(password), hashed)


def _make_jwt(patient_id: str, name: str, secret: str) -> str:
    payload = {
        "sub": patient_id,
        "name": name,
        "exp": datetime.now(tz=timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def _get_patient_from_token(
    authorization: str | None,
    settings: Settings,
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente ou inválido")
    token = authorization.removeprefix("Bearer ").strip()
    secret = settings.jwt_secret or "nutrideby_jwt_dev_secret"
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado. Faça login novamente.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")
    return payload


# ── Dependency: paywall ────────────────────────────────────────────────────────

def check_active_access(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: str | None = Header(None),
) -> dict:
    """Verifica autenticação JWT e status de assinatura (trial ou ativa)."""
    token_data = _get_patient_from_token(authorization, settings)

    if token_data["sub"] != patient_id:
        raise HTTPException(status_code=403, detail="Acesso negado")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name, subscription_status, trial_ends_at, "
                "subscription_ends_at FROM patients WHERE id = %s",
                (patient_id,),
            )
            patient = cur.fetchone()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    now = datetime.now(tz=timezone.utc)
    sub_status = patient["subscription_status"]

    if sub_status == "trial":
        trial_end = patient["trial_ends_at"]
        if trial_end and now > trial_end:
            # Expira o trial automaticamente
            with psycopg.connect(settings.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE patients SET subscription_status = 'expired' WHERE id = %s",
                        (patient_id,),
                    )
                    conn.commit()
            raise HTTPException(
                status_code=402,
                detail="Seu período de teste de 7 dias expirou. Ative sua assinatura para continuar.",
            )

    elif sub_status == "expired":
        raise HTTPException(
            status_code=402,
            detail="Assinatura expirada. Realize o pagamento para continuar.",
        )

    elif sub_status == "canceled":
        end = patient["subscription_ends_at"]
        if end and now > end:
            raise HTTPException(
                status_code=402,
                detail="Sua assinatura foi cancelada e o período de acesso expirou.",
            )

    return patient


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
def register_patient(
    payload: PatientRegisterRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    now = datetime.now(tz=timezone.utc)
    trial_ends = now + timedelta(days=7)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Verifica duplicatas
            cur.execute(
                "SELECT id FROM patients WHERE email = %s OR cpf = %s",
                (payload.email, payload.cpf),
            )
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Email ou CPF já cadastrado")

            # Insere paciente
            cur.execute(
                """
                INSERT INTO patients
                  (source_system, external_id, display_name, email, cpf,
                   hashed_password, subscription_status, trial_ends_at, created_at, updated_at)
                VALUES ('app', %s, %s, %s, %s, %s, 'trial', %s, %s, %s)
                RETURNING id
                """,
                (
                    f"app:{payload.cpf}",
                    payload.name,
                    payload.email,
                    payload.cpf,
                    _hash_password(payload.password),
                    trial_ends,
                    now,
                    now,
                ),
            )
            new_id = cur.fetchone()["id"]

            # Registra telefone
            cur.execute(
                """
                INSERT INTO patient_phones (patient_id, phone, source)
                VALUES (%s, %s, 'app_register')
                ON CONFLICT (phone) DO NOTHING
                """,
                (new_id, payload.phone_number),
            )
            conn.commit()

    secret = settings.jwt_secret or "nutrideby_jwt_dev_secret"
    token = _make_jwt(str(new_id), payload.name, secret)
    return {
        "message": "Cadastro realizado! Trial de 7 dias ativo.",
        "patient_id": str(new_id),
        "token": token,
        "trial_ends_at": trial_ends.isoformat(),
    }


@router.post("/auth")
def auth_patient(
    payload: PatientAuthRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    login = payload.login.strip()
    is_cpf = re.sub(r"\D", "", login).isdigit() and len(re.sub(r"\D", "", login)) >= 11

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if is_cpf:
                cur.execute(
                    "SELECT id, display_name, hashed_password, subscription_status "
                    "FROM patients WHERE cpf = %s",
                    (re.sub(r"\D", "", login),),
                )
            else:
                cur.execute(
                    "SELECT id, display_name, hashed_password, subscription_status "
                    "FROM patients WHERE email = %s",
                    (login,),
                )
            patient = cur.fetchone()

    if not patient or not patient["hashed_password"]:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    if not _verify_password(payload.password, patient["hashed_password"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    secret = settings.jwt_secret or "nutrideby_jwt_dev_secret"
    token = _make_jwt(str(patient["id"]), patient["display_name"] or "", secret)
    return {
        "token": token,
        "patient_id": str(patient["id"]),
        "name": patient["display_name"],
        "subscription_status": patient["subscription_status"],
    }


def _update_gamification(conn: psycopg.Connection, patient_id: str) -> None:
    """Atualiza streak, XP, level e liga após um registro de refeição."""
    from datetime import date as _date
    today = _date.today()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT current_streak, longest_streak, last_logged_date, "
            "deby_level, deby_xp, league_points FROM patients WHERE id = %s",
            (patient_id,),
        )
        row = cur.fetchone()
    if not row:
        return

    last = row["last_logged_date"]
    streak = row["current_streak"] or 0
    if last is None:
        streak = 1
    elif last == today:
        return  # já registrou hoje, não conta streak duplo
    elif (today - last).days == 1:
        streak += 1
    else:
        streak = 1

    xp_bonus = 5 if streak >= 7 else (3 if streak >= 3 else 0)
    new_xp = (row["deby_xp"] or 0) + 10 + xp_bonus
    level = row["deby_level"] or 1
    while new_xp >= level * 100:
        new_xp -= level * 100
        level += 1

    new_league_pts = (row["league_points"] or 0) + 5
    longest = max(row["longest_streak"] or 0, streak)

    league = "Bronze"
    for threshold, name in [(1000, "Diamante"), (600, "Platina"), (300, "Ouro"), (100, "Prata"), (0, "Bronze")]:
        if new_league_pts >= threshold:
            league = name
            break

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE patients SET current_streak = %s, longest_streak = %s,
               last_logged_date = %s, deby_level = %s, deby_xp = %s,
               league_points = %s, league_name = %s WHERE id = %s""",
            (streak, longest, today, level, new_xp, new_league_pts, league, patient_id),
        )
        conn.commit()



@router.post("/{patient_id}/food-log", status_code=201)
def create_food_log(
    patient_id: str,
    payload: FoodLogCreate,
    settings: Annotated[Settings, Depends(get_settings)],
    patient: Annotated[dict, Depends(check_active_access)],
) -> dict:
    total_cal = sum(f.calories for f in payload.foods)
    total_prot = sum(f.protein for f in payload.foods)
    total_carb = sum(f.carbs for f in payload.foods)
    total_fat = sum(f.fat for f in payload.foods)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO food_logs
                  (patient_id, meal_type, photo_url, source, foods,
                   total_calories, total_protein, total_carbs, total_fat)
                VALUES (%s, %s, %s, 'app', %s::jsonb, %s, %s, %s, %s)
                RETURNING id, logged_at
                """,
                (
                    patient_id,
                    payload.meal_type,
                    payload.photo_url,
                    psycopg.types.json.Jsonb([f.model_dump() for f in payload.foods]),
                    total_cal,
                    total_prot,
                    total_carb,
                    total_fat,
                ),
            )
            row = cur.fetchone()
            conn.commit()
        _update_gamification(conn, patient_id)

    # Detecção de padrão comportamental
    padrao_detectado = None
    try:
        from nutrideby.api.padrao_detector import detectar_e_salvar
        descricao = " ".join(f.name for f in payload.foods if f.name)
        if descricao:
            with psycopg.connect(settings.database_url, row_factory=dict_row) as conn2:
                padrao_detectado = detectar_e_salvar(conn2, patient_id, str(row["id"]), descricao)
    except Exception as _e:
        pass  # não quebra o registro

    resp = {
        "id": str(row["id"]),
        "logged_at": row["logged_at"].isoformat(),
        "total_calories": total_cal,
        "total_protein": total_prot,
        "total_carbs": total_carb,
        "total_fat": total_fat,
    }
    if padrao_detectado:
        resp["padrao_detectado"] = padrao_detectado
    return resp


@router.get("/{patient_id}/daily-summary")
def get_daily_summary(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    patient: Annotated[dict, Depends(check_active_access)],
    target_date: str | None = None,  # YYYY-MM-DD, default hoje
) -> dict:
    day = date.fromisoformat(target_date) if target_date else date.today()
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Metas do paciente
            cur.execute(
                """
                SELECT daily_calories_target, daily_protein_target,
                       daily_carbs_target, daily_fat_target, water_target_ml
                FROM patients WHERE id = %s
                """,
                (patient_id,),
            )
            targets = cur.fetchone()

            # Logs do dia
            cur.execute(
                """
                SELECT meal_type,
                       SUM(total_calories) AS cal,
                       SUM(total_protein)  AS prot,
                       SUM(total_carbs)    AS carb,
                       SUM(total_fat)      AS fat
                FROM food_logs
                WHERE patient_id = %s AND logged_at >= %s AND logged_at < %s
                GROUP BY meal_type
                """,
                (patient_id, day_start, day_end),
            )
            meal_rows = cur.fetchall()

            # Streak: dias consecutivos com pelo menos 1 log
            cur.execute(
                """
                WITH days AS (
                  SELECT DISTINCT (logged_at AT TIME ZONE 'America/Sao_Paulo')::date AS d
                  FROM food_logs WHERE patient_id = %s AND logged_at < %s
                  ORDER BY d DESC
                ),
                streaks AS (
                  SELECT d, d - (ROW_NUMBER() OVER (ORDER BY d DESC))::int AS grp
                  FROM days
                )
                SELECT COUNT(*) AS streak FROM streaks
                WHERE grp = (SELECT grp FROM streaks ORDER BY d DESC LIMIT 1)
                """,
                (patient_id, day_end),
            )
            streak_row = cur.fetchone()

    cal_consumed = sum(r["cal"] or 0 for r in meal_rows)
    prot_consumed = sum(r["prot"] or 0 for r in meal_rows)
    carb_consumed = sum(r["carb"] or 0 for r in meal_rows)
    fat_consumed = sum(r["fat"] or 0 for r in meal_rows)

    return {
        "date": day.isoformat(),
        "calories_goal": targets["daily_calories_target"] if targets else 2000.0,
        "calories_consumed": round(cal_consumed, 1),
        "protein_goal": targets["daily_protein_target"] if targets else 130.0,
        "protein_consumed": round(prot_consumed, 1),
        "carbs_goal": targets["daily_carbs_target"] if targets else 220.0,
        "carbs_consumed": round(carb_consumed, 1),
        "fat_goal": targets["daily_fat_target"] if targets else 65.0,
        "fat_consumed": round(fat_consumed, 1),
        "water_goal_ml": targets["water_target_ml"] if targets else 2000.0,
        "meals_logged": [r["meal_type"] for r in meal_rows],
        "streak_days": int(streak_row["streak"]) if streak_row else 0,
    }


@router.get("/{patient_id}/week-summary")
def get_week_summary(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    patient: Annotated[dict, Depends(check_active_access)],
) -> dict:
    today = date.today()
    week_start = today - timedelta(days=6)
    start_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    end_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT (logged_at AT TIME ZONE 'America/Sao_Paulo')::date AS day,
                       SUM(total_calories) AS calories
                FROM food_logs
                WHERE patient_id = %s AND logged_at >= %s AND logged_at < %s
                GROUP BY day ORDER BY day
                """,
                (patient_id, start_dt, end_dt),
            )
            rows = cur.fetchall()

    by_day = {r["day"]: round(r["calories"] or 0, 1) for r in rows}
    days_range = [week_start + timedelta(days=i) for i in range(7)]
    return {
        "week": [
            {"date": d.isoformat(), "calories": by_day.get(d, 0.0)}
            for d in days_range
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE AUTH
# ─────────────────────────────────────────────────────────────────────────────

class GoogleAuthRequest(BaseModel):
    access_token: str


@router.post("/auth/google")
def auth_google(
    payload: GoogleAuthRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    import json as _json
    import urllib.request

    try:
        req = urllib.request.urlopen(
            f"https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={payload.access_token}",
            timeout=5,
        )
        user_info = _json.loads(req.read())
    except Exception:
        raise HTTPException(status_code=401, detail="Token Google inválido")

    google_id = user_info.get("sub")
    email = user_info.get("email")
    name = user_info.get("name") or email

    if not google_id or not email:
        raise HTTPException(status_code=401, detail="Token Google sem dados de usuário")

    now = datetime.now(tz=timezone.utc)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name, subscription_status FROM patients WHERE google_id = %s OR email = %s LIMIT 1",
                (google_id, email),
            )
            patient = cur.fetchone()

            if patient:
                cur.execute(
                    "UPDATE patients SET google_id = %s WHERE id = %s AND google_id IS NULL",
                    (google_id, patient["id"]),
                )
                conn.commit()
            else:
                trial_ends = now + timedelta(days=7)
                cur.execute(
                    """
                    INSERT INTO patients
                      (source_system, external_id, display_name, email, cpf,
                       hashed_password, subscription_status, trial_ends_at, created_at, updated_at, google_id)
                    VALUES ('google', %s, %s, %s, NULL, '', 'trial', %s, %s, %s, %s)
                    RETURNING id, display_name, subscription_status
                    """,
                    (f"google:{google_id}", name, email, trial_ends, now, now, google_id),
                )
                patient = cur.fetchone()
                conn.commit()

    secret = settings.jwt_secret or "nutrideby_jwt_dev_secret"
    token = _make_jwt(str(patient["id"]), patient["display_name"] or name, secret)
    return {
        "token": token,
        "patient_id": str(patient["id"]),
        "name": patient["display_name"] or name,
        "subscription_status": patient["subscription_status"],
    }
