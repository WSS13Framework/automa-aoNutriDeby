"""
nutricionista_router.py — Painel B2B da nutricionista.
Rotas:
  POST /api/nutri/login                         → JWT
  POST /api/nutri/forgot-password               → envia e-mail de reset
  POST /api/nutri/reset-password                → define nova senha via token
  POST /api/nutri/accept-invite                 → primeiro acesso via token de convite
  GET  /api/nutri/pending                       → prontuários pendentes
  POST /api/nutri/initiate-signing/{record_id}  → dispara D4Sign
  GET  /api/nutri/records                       → todos os prontuários
  POST /api/nutri/d4sign-webhook                → callback D4Sign
  POST /api/nutri/setup                         → configura nutri + envia convite
  GET  /painel                                  → HTML do painel
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from psycopg.rows import dict_row
from pydantic import BaseModel

from nutrideby.api.deps import get_settings
from nutrideby.clients.d4sign_client import add_signer, send_to_sign, upload_document
from nutrideby.clients.resend_client import (
    invite_email_html,
    reset_email_html,
    send_email,
)
from nutrideby.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nutri", tags=["nutricionista-painel"])

_JWT_ALG      = "HS256"
_JWT_EXP_H    = 12
_INVITE_EXP_H = 48
_RESET_EXP_H  = 1

ROLES = {"admin", "nutricionista", "viewer"}


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 260_000)
    return salt.hex() + ":" + dk.hex()


def _verify_password(plain: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), bytes.fromhex(salt_hex), 260_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _make_jwt(nutri_id: int, role: str, secret: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=_JWT_EXP_H)
    return jwt.encode({"sub": str(nutri_id), "role": role, "exp": exp}, secret, algorithm=_JWT_ALG)


def _decode_jwt(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[_JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado — faça login novamente")
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")


def _auth(request: Request, settings: Settings) -> dict:
    """Decodifica Bearer JWT e retorna payload {sub, role}."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header ausente")
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="JWT_SECRET não configurado")
    return _decode_jwt(auth.removeprefix("Bearer ").strip(), str(settings.jwt_secret))


def _require_role(payload: dict, *roles: str) -> None:
    if payload.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Sem permissão para esta ação")


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class AcceptInviteRequest(BaseModel):
    token: str
    password: str


class SetupRequest(BaseModel):
    name: str
    crn: str
    email: str
    role: str = "nutricionista"
    d4sign_token_api: str = ""
    d4sign_crypt_key: str = ""
    d4sign_safe_uuid: str = ""
    send_invite: bool = True


class UpdateD4SignRequest(BaseModel):
    nutri_id: int
    d4sign_token_api: str
    d4sign_crypt_key: str
    d4sign_safe_uuid: str


class StartConsultationRequest(BaseModel):
    patient_id: str
    patient_phone: str
    patient_name: str


class ConfirmReactivationRequest(BaseModel):
    patient_id: str


class ConfirmScheduledRequest(BaseModel):
    patient_id: str


# ── Endpoints de autenticação ─────────────────────────────────────────────────

@router.post("/login")
def login(body: LoginRequest, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="JWT_SECRET não configurado")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, crn, role, hashed_password, password_set "
                "FROM professional_nutricionistas WHERE email = %s AND is_active = true",
                (body.email.lower().strip(),),
            )
            nutri = cur.fetchone()

    if not nutri:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    if not nutri.get("password_set") or not nutri.get("hashed_password"):
        raise HTTPException(
            status_code=403,
            detail="Senha não definida. Verifique seu e-mail de convite.",
        )

    if not _verify_password(body.password, nutri["hashed_password"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    role = nutri.get("role") or "nutricionista"
    token = _make_jwt(nutri["id"], role, str(settings.jwt_secret))
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": _JWT_EXP_H * 3600,
        "nutricionista": {
            "id": nutri["id"],
            "name": nutri["name"],
            "crn": nutri["crn"],
            "role": role,
        },
    }


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Gera token de reset e envia e-mail. Sempre retorna 200 (não revela se e-mail existe)."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, email FROM professional_nutricionistas "
                "WHERE email = %s AND is_active = true",
                (body.email.lower().strip(),),
            )
            nutri = cur.fetchone()

        if nutri:
            token = str(uuid.uuid4())
            expires = datetime.now(timezone.utc) + timedelta(hours=_RESET_EXP_H)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE professional_nutricionistas "
                    "SET reset_token = %s, reset_token_expires_at = %s WHERE id = %s",
                    (token, expires, nutri["id"]),
                )
                conn.commit()

            base = (settings.app_base_url or "https://api.nutrideby.com").rstrip("/")
            reset_url = f"{base}/painel?action=reset&token={token}"
            send_email(
                api_key=settings.resend_api_key or "",
                from_email=settings.resend_from_email,
                to=nutri["email"],
                subject="Redefinir senha — NutriDeby",
                html=reset_email_html(nutri["name"], reset_url),
            )
            logger.info("Reset token gerado para nutri_id=%s", nutri["id"])

    return {"message": "Se este e-mail estiver cadastrado, você receberá as instruções em breve."}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Senha deve ter no mínimo 8 caracteres")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM professional_nutricionistas "
                "WHERE reset_token = %s AND reset_token_expires_at > now() AND is_active = true",
                (body.token,),
            )
            nutri = cur.fetchone()

        if not nutri:
            raise HTTPException(status_code=400, detail="Token inválido ou expirado")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE professional_nutricionistas "
                "SET hashed_password = %s, password_set = true, "
                "    reset_token = NULL, reset_token_expires_at = NULL "
                "WHERE id = %s",
                (_hash_password(body.new_password), nutri["id"]),
            )
            conn.commit()

    return {"message": "Senha redefinida com sucesso. Faça login."}


@router.post("/accept-invite")
def accept_invite(
    body: AcceptInviteRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Primeiro acesso — define senha via token de convite."""
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Senha deve ter no mínimo 8 caracteres")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM professional_nutricionistas "
                "WHERE invite_token = %s AND invite_token_expires_at > now() AND is_active = true",
                (body.token,),
            )
            nutri = cur.fetchone()

        if not nutri:
            raise HTTPException(status_code=400, detail="Convite inválido ou expirado")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE professional_nutricionistas "
                "SET hashed_password = %s, password_set = true, "
                "    invite_token = NULL, invite_token_expires_at = NULL "
                "WHERE id = %s",
                (_hash_password(body.password), nutri["id"]),
            )
            conn.commit()

    return {"message": f"Senha criada! Bem-vinda, {nutri['name']}. Faça login."}


# ── Setup / gestão de nutris ──────────────────────────────────────────────────

@router.post("/setup")
def setup_nutri(
    body: SetupRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Cria ou atualiza uma nutricionista.
    Se send_invite=true, envia e-mail de convite para criar senha.
    """
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail=f"Role inválido. Use: {', '.join(ROLES)}")

    invite_token = str(uuid.uuid4())
    invite_expires = datetime.now(timezone.utc) + timedelta(hours=_INVITE_EXP_H)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Upsert por CRN
            cur.execute(
                """
                INSERT INTO professional_nutricionistas
                    (name, crn, email, role, is_active,
                     d4sign_token_api, d4sign_crypt_key, d4sign_safe_uuid,
                     invite_token, invite_token_expires_at)
                VALUES (%s, %s, %s, %s, true, %s, %s, %s, %s, %s)
                ON CONFLICT (crn) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    role = EXCLUDED.role,
                    d4sign_token_api = EXCLUDED.d4sign_token_api,
                    d4sign_crypt_key = EXCLUDED.d4sign_crypt_key,
                    d4sign_safe_uuid = EXCLUDED.d4sign_safe_uuid,
                    invite_token = EXCLUDED.invite_token,
                    invite_token_expires_at = EXCLUDED.invite_token_expires_at
                RETURNING id, name, email
                """,
                (
                    body.name, body.crn, body.email.lower().strip(), body.role,
                    body.d4sign_token_api or None,
                    body.d4sign_crypt_key or None,
                    body.d4sign_safe_uuid or None,
                    invite_token, invite_expires,
                ),
            )
            nutri = cur.fetchone()
            conn.commit()

    sent = False
    if body.send_invite:
        base = (settings.app_base_url or "https://api.nutrideby.com").rstrip("/")
        invite_url = f"{base}/painel?action=invite&token={invite_token}"
        sent = send_email(
            api_key=settings.resend_api_key or "",
            from_email=settings.resend_from_email,
            to=nutri["email"],
            subject="Convite NutriDeby — Crie sua senha",
            html=invite_email_html(nutri["name"], invite_url),
        )
        logger.info("Convite enviado=%s para nutri_id=%s email=%s", sent, nutri["id"], nutri["email"])

    return {
        "ok": True,
        "nutri_id": nutri["id"],
        "invite_sent": sent,
        "invite_token": invite_token if not sent else None,  # devolve token se email falhou
    }


@router.post("/start-consultation")
def start_consultation(
    body: StartConsultationRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    payload = _auth(request, settings)
    nutri_id = int(payload["sub"])

    slug = re.sub(r"[^a-z0-9]+", "-", body.patient_name.lower()).strip("-")[:30]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))
    room_name = f"nd-{slug}-{ts}-{suffix}"
    room_url = f"https://meet.nutrideby.com/{room_name}"

    nutri_name = "Nutricionista"
    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM professional_nutricionistas WHERE id = %s", (nutri_id,))
                row = cur.fetchone()
                if row:
                    nutri_name = row["name"]
    except Exception:
        pass

    if settings.twilio_account_sid and settings.twilio_auth_token and body.patient_phone:
        try:
            from twilio.rest import Client as TwilioClient  # noqa: PLC0415
            twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
            phone = body.patient_phone if body.patient_phone.startswith("whatsapp:") else f"whatsapp:{body.patient_phone}"
            twilio.messages.create(
                from_=settings.twilio_from_number,
                body=f"Sua consulta com a Dra. {nutri_name} está começando. Acesse: {room_url}",
                to=phone,
            )
            logger.info("WhatsApp consulta enviado para %s room=%s", body.patient_phone, room_name)
        except Exception as exc:
            logger.warning("Falha ao enviar WhatsApp consulta: %s", exc)

    return {"room_url": room_url, "room_name": room_name}


@router.post("/confirm-reactivation")
def confirm_reactivation(
    body: ConfirmReactivationRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    payload = _auth(request, settings)
    _require_role(payload, "admin", "nutricionista")
    nutri_id = int(payload["sub"])

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM professional_nutricionistas WHERE id = %s",
                (nutri_id,),
            )
            nutri = cur.fetchone()
            nutri_name = nutri["name"] if nutri else "Nutricionista"

            cur.execute(
                "SELECT display_name FROM patients WHERE id = %s",
                (body.patient_id,),
            )
            patient = cur.fetchone()
            if not patient:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")

            now = datetime.now(timezone.utc)
            cur.execute(
                """UPDATE patients SET
                       reactivation_stage = 'reactivated',
                       reactivation_date = %s,
                       reactivation_confirmed_by = %s,
                       subscription_status = 'active',
                       updated_at = NOW()
                   WHERE id = %s""",
                (now, nutri_name, body.patient_id),
            )
            conn.commit()

    logger.info("Reativação confirmada: patient=%s por nutri=%s", body.patient_id, nutri_name)
    return {
        "success": True,
        "patient_name": patient["display_name"],
        "reactivation_date": now.isoformat(),
    }


@router.post("/confirm-scheduled")
def confirm_scheduled(
    body: ConfirmScheduledRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    payload = _auth(request, settings)
    _require_role(payload, "admin", "nutricionista")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE patients SET reactivation_stage = 'scheduled', updated_at = NOW() WHERE id = %s",
                (body.patient_id,),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")
            conn.commit()

    return {"success": True}


@router.post("/update-d4sign")
def update_d4sign(
    body: UpdateD4SignRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Atualiza credenciais D4Sign de uma nutricionista."""
    payload = _auth(request, settings)
    _require_role(payload, "admin")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE professional_nutricionistas "
                "SET d4sign_token_api=%s, d4sign_crypt_key=%s, d4sign_safe_uuid=%s WHERE id=%s",
                (body.d4sign_token_api, body.d4sign_crypt_key, body.d4sign_safe_uuid, body.nutri_id),
            )
            conn.commit()
    return {"ok": True}


# ── Prontuários ───────────────────────────────────────────────────────────────

@router.get("/pending")
def list_pending(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    payload = _auth(request, settings)
    nutri_id = int(payload["sub"])
    role = payload.get("role", "nutricionista")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # admin vê todos; nutricionista/viewer vê todos os pendentes (sem dono ainda)
            cur.execute(
                """
                SELECT cr.id, cr.patient_id, cr.status, cr.d4sign_status,
                       cr.created_at, cr.signing_initiated_at,
                       p.display_name AS patient_name,
                       cr.extracted_biochemistry,
                       pp.phone AS patient_phone
                FROM clinical_records cr
                LEFT JOIN patients p ON p.id = cr.patient_id
                LEFT JOIN LATERAL (
                    SELECT phone FROM patient_phones
                    WHERE patient_id = p.id ORDER BY created_at LIMIT 1
                ) pp ON true
                WHERE cr.status = 'PENDENTE'
                ORDER BY cr.created_at DESC
                """,
            )
            rows = cur.fetchall()

    records = []
    for r in rows:
        bio = r.get("extracted_biochemistry") or {}
        if isinstance(bio, str):
            bio = json.loads(bio)
        records.append({
            "id": r["id"],
            "patient_id": str(r["patient_id"]),
            "patient_name": r.get("patient_name") or "Paciente",
            "patient_phone": r.get("patient_phone") or "",
            "status": r["status"],
            "d4sign_status": r.get("d4sign_status") or "NONE",
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "signing_initiated_at": r["signing_initiated_at"].isoformat() if r.get("signing_initiated_at") else None,
            "markers_total": len(bio),
            "markers_altered": len(_bio_flags(bio)),
            "flags": _bio_flags(bio),
            "can_sign": role in ("admin", "nutricionista"),
        })

    return {"total": len(records), "records": records, "role": role}


@router.get("/records")
def list_all_records(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    status: str | None = None,
) -> dict:
    payload = _auth(request, settings)
    role = payload.get("role", "nutricionista")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            q = """
                SELECT cr.id, cr.patient_id, cr.status, cr.d4sign_status,
                       cr.created_at, cr.signed_at, cr.pdf_url, cr.d4sign_signed_pdf_url,
                       p.display_name AS patient_name,
                       pn.name AS nutricionista_name,
                       pp.phone AS patient_phone
                FROM clinical_records cr
                LEFT JOIN patients p ON p.id = cr.patient_id
                LEFT JOIN professional_nutricionistas pn ON pn.id = cr.nutricionista_id
                LEFT JOIN LATERAL (
                    SELECT phone FROM patient_phones
                    WHERE patient_id = p.id ORDER BY created_at LIMIT 1
                ) pp ON true
                {where}
                ORDER BY cr.created_at DESC LIMIT 100
            """
            if status:
                cur.execute(q.format(where="WHERE cr.status = %s"), (status.upper(),))
            else:
                cur.execute(q.format(where=""))
            rows = cur.fetchall()

    return {
        "total": len(rows),
        "role": role,
        "records": [
            {
                "id": r["id"],
                "patient_id": str(r["patient_id"]),
                "patient_name": r.get("patient_name") or "Paciente",
                "patient_phone": r.get("patient_phone") or "",
                "nutricionista": r.get("nutricionista_name") or "—",
                "status": r["status"],
                "d4sign_status": r.get("d4sign_status") or "NONE",
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "signed_at": r["signed_at"].isoformat() if r.get("signed_at") else None,
                "pdf_url": r.get("pdf_url"),
                "d4sign_signed_pdf_url": r.get("d4sign_signed_pdf_url"),
            }
            for r in rows
        ],
    }


@router.post("/initiate-signing/{record_id}")
def initiate_signing(
    record_id: int,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    payload = _auth(request, settings)
    _require_role(payload, "admin", "nutricionista")
    nutri_id = int(payload["sub"])

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clinical_records WHERE id = %s", (record_id,))
            record = cur.fetchone()
            if not record:
                raise HTTPException(status_code=404, detail="Prontuário não encontrado")
            if record["status"] == "ASSINADO":
                raise HTTPException(status_code=400, detail="Prontuário já assinado")
            if record.get("d4sign_status") == "PENDING_SIGNATURE":
                raise HTTPException(status_code=400, detail="Assinatura D4Sign já iniciada")

            cur.execute(
                "SELECT * FROM professional_nutricionistas WHERE id = %s AND is_active = true",
                (nutri_id,),
            )
            nutri = cur.fetchone()
            if not nutri:
                raise HTTPException(status_code=403, detail="Nutricionista inativa")

            d4_token  = nutri.get("d4sign_token_api")
            d4_crypt  = nutri.get("d4sign_crypt_key")
            d4_safe   = nutri.get("d4sign_safe_uuid")
            nutri_email = nutri.get("email")

            if not all([d4_token, d4_crypt, d4_safe, nutri_email]):
                raise HTTPException(
                    status_code=422,
                    detail="Credenciais D4Sign não configuradas. Use POST /api/nutri/update-d4sign.",
                )

            pdf_filename = record.get("pdf_url", "").lstrip("/")
            pdf_path = f"/app/{pdf_filename}" if pdf_filename else None
            if not pdf_path or not os.path.exists(pdf_path):
                raise HTTPException(status_code=404, detail="PDF não encontrado. Gere o prontuário primeiro.")

            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

    base = (settings.app_base_url or "https://api.nutrideby.com").rstrip("/")
    try:
        doc_uuid = upload_document(d4_token, d4_crypt, d4_safe, pdf_bytes, f"prontuario_{record_id}.pdf")
        add_signer(d4_token, d4_crypt, doc_uuid, nutri_email, nutri["name"])
        send_to_sign(
            d4_token, d4_crypt, doc_uuid,
            message=f"NutriDeby — Prontuário #{record_id}. Assine para homologar.",
            callback_url=f"{base}/api/nutri/d4sign-webhook",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Erro D4Sign: {exc}") from exc

    now = datetime.now(timezone.utc)
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE clinical_records
                   SET d4sign_document_uuid=%s, d4sign_status='PENDING_SIGNATURE',
                       signing_initiated_at=%s, nutricionista_id=%s
                   WHERE id=%s""",
                (doc_uuid, now, nutri_id, record_id),
            )
            conn.commit()

    return {
        "message": "Assinatura D4Sign iniciada. E-mail enviado.",
        "record_id": record_id,
        "d4sign_document_uuid": doc_uuid,
        "status": "PENDING_SIGNATURE",
    }


@router.get("/patients")
def list_patients(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    status: str | None = None,
    q: str | None = None,
) -> dict:
    """Lista todos os pacientes com dados reais para o painel da nutricionista."""
    _auth(request, settings)

    filters = ["p.display_name IS NOT NULL"]
    params: list = []

    if status and status != "todos":
        filters.append("p.subscription_status = %s")
        params.append(status)

    if q:
        filters.append("(p.display_name ILIKE %s OR p.email ILIKE %s OR pp.phone LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])

    where = "WHERE " + " AND ".join(filters)

    sql = f"""
        SELECT
            p.id,
            p.display_name,
            p.email,
            p.subscription_status,
            p.current_streak,
            p.longest_streak,
            p.last_logged_date,
            p.deby_level,
            p.deby_xp,
            p.goal_statement,
            p.created_at,
            p.reactivation_stage,
            p.reactivation_date,
            p.reactivation_confirmed_by,
            pp.phone,
            (SELECT COUNT(*) FROM food_logs fl WHERE fl.patient_id = p.id) AS logs_total,
            (SELECT COUNT(*) FROM clinical_records cr WHERE cr.patient_id = p.id) AS prontuarios,
            (SELECT COUNT(*) FROM inbound_messages im WHERE im.patient_id = p.id) AS mensagens,
            (SELECT fase FROM padroes_alimentares pa WHERE pa.patient_id = p.id ORDER BY pa.data_deteccao DESC LIMIT 1) AS padrao_fase
        FROM patients p
        LEFT JOIN LATERAL (
            SELECT phone FROM patient_phones
            WHERE patient_id = p.id ORDER BY created_at LIMIT 1
        ) pp ON true
        {where}
        ORDER BY
            CASE p.subscription_status
                WHEN 'active' THEN 1
                WHEN 'trial'  THEN 2
                ELSE 3
            END,
            p.last_logged_date DESC NULLS LAST,
            p.display_name
        LIMIT 500
    """

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    _STATUS_LABEL = {
        "active": "Ativo", "trial": "Trial", "inactive": "Inativo",
        "cancelled": "Cancelado", "pending": "Pendente",
    }
    _FASE_COR = {
        "ESCAPE": "#f59e0b", "CONFRONTO": "#ef4444",
        "RETORNO": "#8b5cf6", "CULPA": "#6366f1",
    }

    pacientes = []
    for r in rows:
        st = r.get("subscription_status") or "inactive"
        fase = r.get("padrao_fase")
        pacientes.append({
            "id": str(r["id"]),
            "nome": r.get("display_name") or "—",
            "email": r.get("email") or "",
            "phone": r.get("phone") or "",
            "status": st,
            "status_label": _STATUS_LABEL.get(st, st.title()),
            "streak": r.get("current_streak") or 0,
            "longest_streak": r.get("longest_streak") or 0,
            "last_logged": r["last_logged_date"].isoformat() if r.get("last_logged_date") else None,
            "level": r.get("deby_level") or 1,
            "xp": r.get("deby_xp") or 0,
            "goal": r.get("goal_statement") or "",
            "logs": r.get("logs_total") or 0,
            "prontuarios": r.get("prontuarios") or 0,
            "mensagens": r.get("mensagens") or 0,
            "fase": fase,
            "fase_cor": _FASE_COR.get(fase, "") if fase else "",
            "criado_em": r["created_at"].isoformat() if r.get("created_at") else None,
            "reactivation_stage": r.get("reactivation_stage"),
            "reactivation_date": r["reactivation_date"].isoformat() if r.get("reactivation_date") else None,
            "reactivation_confirmed_by": r.get("reactivation_confirmed_by"),
        })

    resumo = {
        "total": len(pacientes),
        "ativos": sum(1 for p in pacientes if p["status"] == "active"),
        "trial": sum(1 for p in pacientes if p["status"] == "trial"),
        "inativos": sum(1 for p in pacientes if p["status"] not in ("active", "trial")),
        "com_telefone": sum(1 for p in pacientes if p["phone"]),
        "responded_count": sum(1 for p in pacientes if p["reactivation_stage"] == "responded"),
        "scheduled_count": sum(1 for p in pacientes if p["reactivation_stage"] == "scheduled"),
        "reactivated_count": sum(1 for p in pacientes if p["reactivation_stage"] == "reactivated"),
    }

    return {"resumo": resumo, "pacientes": pacientes}


@router.post("/d4sign-webhook")
async def d4sign_webhook(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}

    doc_uuid = body.get("uuid") or body.get("uuidDoc")
    if not doc_uuid or str(body.get("type", "")) != "1":
        return {"ok": True, "ignored": True}

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status FROM clinical_records WHERE d4sign_document_uuid = %s",
                (doc_uuid,),
            )
            record = cur.fetchone()

        if not record or record["status"] == "ASSINADO":
            return {"ok": True, "ignored": True}

        now = datetime.now(timezone.utc)
        signed_url = f"https://secure.d4sign.com.br/api/v1/documents/{doc_uuid}/download"
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE clinical_records
                   SET status='ASSINADO', d4sign_status='SIGNED',
                       signed_at=%s, d4sign_signed_pdf_url=%s
                   WHERE id=%s""",
                (now, signed_url, record["id"]),
            )
            conn.commit()

    logger.info("D4Sign webhook: prontuário #%s assinado", record["id"])
    return {"ok": True, "record_id": record["id"]}


# ── Painel HTML ───────────────────────────────────────────────────────────────



@router.get("/grid-padroes")
def grid_padroes(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Grid de todos os pacientes com status de padrão atual.
    Usado no painel da Débora para visão comportamental.
    """
    _auth(request, settings)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.id,
                    p.display_name,
                    p.current_streak,
                    p.last_logged_date,
                    pa.fase,
                    pa.ciclo_numero,
                    pa.degradacao_nivel,
                    pa.alimentos_gatilho,
                    pa.data_deteccao,
                    pa.acao_prescrita,
                    pp.phone,
                    p.reactivation_stage,
                    p.reactivation_confirmed_by
                FROM patients p
                LEFT JOIN LATERAL (
                    SELECT fase, ciclo_numero, degradacao_nivel,
                           alimentos_gatilho, data_deteccao, acao_prescrita
                    FROM padroes_alimentares
                    WHERE patient_id = p.id
                    ORDER BY data_deteccao DESC
                    LIMIT 1
                ) pa ON true
                LEFT JOIN LATERAL (
                    SELECT phone FROM patient_phones
                    WHERE patient_id = p.id ORDER BY created_at LIMIT 1
                ) pp ON true
                WHERE p.display_name IS NOT NULL
                ORDER BY
                    CASE pa.fase
                        WHEN 'CONFRONTO' THEN 1
                        WHEN 'RETORNO'   THEN 2
                        WHEN 'CULPA'     THEN 3
                        WHEN 'ESCAPE'    THEN 4
                        ELSE 5
                    END,
                    pa.data_deteccao DESC NULLS LAST,
                    p.display_name
                LIMIT 200
                """
            )
            rows = cur.fetchall()

    _ACOES = {
        "ESCAPE":    "Deixar fluir — monitorar próxima refeição",
        "CONFRONTO": "Agendar consulta de realinhamento",
        "RETORNO":   "Enviar mensagem de acolhimento no WhatsApp",
        "CULPA":     "Check-in emocional — perguntar como está",
    }
    _CORES = {
        "ESCAPE": "#f59e0b",
        "CONFRONTO": "#ef4444",
        "RETORNO": "#8b5cf6",
        "CULPA": "#6366f1",
    }
    _EMOJIS = {
        "ESCAPE": "🌊",
        "CONFRONTO": "⚡",
        "RETORNO": "🔄",
        "CULPA": "💙",
    }

    pacientes = []
    for r in rows:
        fase = r.get("fase")
        dias_atras = None
        if r.get("data_deteccao"):
            from datetime import datetime, timezone
            diff = datetime.now(timezone.utc) - r["data_deteccao"]
            dias_atras = diff.days

        pacientes.append({
            "id": str(r["id"]),
            "nome": r["display_name"],
            "phone": r.get("phone") or "",
            "streak": r["current_streak"] or 0,
            "ultimo_registro": r["last_logged_date"].isoformat() if r.get("last_logged_date") else None,
            "reactivation_stage": r.get("reactivation_stage"),
            "reactivation_confirmed_by": r.get("reactivation_confirmed_by"),
            "padrao": {
                "fase": fase,
                "ciclo": r.get("ciclo_numero"),
                "degradacao": r.get("degradacao_nivel", 0),
                "gatilhos": r.get("alimentos_gatilho") or [],
                "dias_atras": dias_atras,
                "acao_recomendada": _ACOES.get(fase, "Acompanhar evolução"),
                "cor": _CORES.get(fase, "#94a3b8"),
                "emoji": _EMOJIS.get(fase, "👤"),
            } if fase else None,
        })

    com_padrao = [p for p in pacientes if p["padrao"]]
    sem_padrao  = [p for p in pacientes if not p["padrao"]]

    return {
        "total": len(pacientes),
        "com_padrao": len(com_padrao),
        "sem_padrao": len(sem_padrao),
        "resumo": {
            fase: sum(1 for p in com_padrao if p["padrao"]["fase"] == fase)
            for fase in ["ESCAPE", "CONFRONTO", "RETORNO", "CULPA"]
        },
        "reativacao": {
            "responded": sum(1 for p in pacientes if p["reactivation_stage"] == "responded"),
            "scheduled": sum(1 for p in pacientes if p["reactivation_stage"] == "scheduled"),
            "reactivated": sum(1 for p in pacientes if p["reactivation_stage"] == "reactivated"),
        },
        "pacientes": pacientes,
    }

_panel_router = APIRouter(tags=["nutricionista-painel"])


@_panel_router.get("/painel", response_class=HTMLResponse)
def painel_html() -> str:
    return _PANEL_HTML


def _bio_flags(bio: dict) -> list[dict]:
    _REF = {
        "glicose": (70, 99), "colesterol_total": (0, 199), "hdl": (40, 999),
        "ldl": (0, 129), "triglicerideos": (0, 149), "vitamina_d": (30, 100),
        "ferro_serico": (60, 170), "ferritina": (15, 150),
        "tsh": (0.4, 4.0), "t3": (2.3, 4.2), "t4": (0.8, 1.8),
    }
    flags = []
    for k, v in bio.items():
        try:
            fv = float(v)
        except (ValueError, TypeError):
            continue
        ref = _REF.get(k)
        if ref and fv < ref[0]:
            flags.append({"marker": k, "value": v, "type": "BAIXO"})
        elif ref and fv > ref[1]:
            flags.append({"marker": k, "value": v, "type": "ALTO"})
    return flags


_PANEL_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>NutriDeby — Painel Clínico</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#F7F6F3;color:#1C1C1A;min-height:100vh;font-size:14px;line-height:1.5}

/* ── Login ── */
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}
.login-card{background:#fff;border:1px solid #E8E5DF;border-radius:12px;padding:40px;width:100%;max-width:380px;box-shadow:0 1px 6px rgba(0,0,0,.05)}
.login-brand{margin-bottom:28px}
.login-brand-name{font-size:18px;font-weight:700;color:#1A5C35;letter-spacing:-.3px}
.login-brand-sub{font-size:13px;color:#6B6860;margin-top:2px}
.login-title{font-size:18px;font-weight:700;color:#1C1C1A;margin-bottom:4px}
.login-sub{font-size:13px;color:#6B6860;margin-bottom:24px}
.form-field{margin-bottom:14px}
.form-field label{display:block;font-size:11px;font-weight:600;color:#6B6860;letter-spacing:.4px;margin-bottom:5px;text-transform:uppercase}
.form-field input{width:100%;padding:9px 12px;border:1px solid #E8E5DF;border-radius:7px;font-size:14px;font-family:inherit;outline:none;color:#1C1C1A;background:#fff;transition:border-color .15s}
.form-field input:focus{border-color:#1A5C35;box-shadow:0 0 0 3px rgba(26,92,53,.08)}
.btn-primary{width:100%;padding:10px;background:#1A5C35;color:#fff;border:none;border-radius:7px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;transition:background .15s;margin-top:4px}
.btn-primary:hover{background:#154e2e}
.btn-primary:disabled{background:#9CA3AF;cursor:not-allowed}
.btn-link{background:none;border:none;color:#1A5C35;font-size:13px;cursor:pointer;font-family:inherit;padding:0;text-decoration:underline;display:block;text-align:center;margin-top:14px}
.err-msg{font-size:12px;color:#C0392B;margin-top:8px}

/* ── App shell ── */
.app-header{background:#fff;border-bottom:1px solid #E8E5DF;padding:0 28px;height:56px;display:flex;align-items:center;position:sticky;top:0;z-index:50}
.header-brand{display:flex;align-items:center;gap:0}
.header-wordmark{font-size:15px;font-weight:700;color:#1A5C35;letter-spacing:-.2px}
.header-sep{width:1px;height:16px;background:#E8E5DF;margin:0 12px}
.header-sub{font-size:13px;color:#6B6860}
.header-right{margin-left:auto;display:flex;align-items:center;gap:16px}
.header-nutri-name{font-size:13px;color:#1C1C1A;font-weight:500}
.btn-session{padding:6px 14px;background:none;border:1px solid #E8E5DF;border-radius:6px;font-size:12px;font-family:inherit;color:#6B6860;cursor:pointer;transition:all .15s}
.btn-session:hover{border-color:#C0392B;color:#C0392B}

/* ── Alert bar ── */
.alert-bar{background:#FEF9EC;border-bottom:1px solid #F5DFA0;padding:10px 28px;display:flex;align-items:center;gap:12px}
.alert-dot{width:7px;height:7px;border-radius:50%;background:#D4850A;flex-shrink:0}
.alert-text{font-size:13px;color:#8A5C00;flex:1;font-weight:500}
.alert-dismiss{background:none;border:none;color:#8A5C00;cursor:pointer;font-size:20px;line-height:1;padding:0 4px;opacity:.6;font-family:inherit}
.alert-dismiss:hover{opacity:1}

/* ── Body ── */
.app-body{padding:24px 28px;max-width:1120px;margin:0 auto}

/* ── Metrics ── */
.metrics-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
.metric-card{background:#fff;border:1px solid #E8E5DF;border-radius:10px;padding:16px 18px}
.metric-card.clickable{cursor:pointer;transition:border-color .15s,box-shadow .15s}
.metric-card.clickable:hover{border-color:#1A5C35;box-shadow:0 0 0 3px rgba(26,92,53,.06)}
.metric-value{font-size:28px;font-weight:700;color:#1C1C1A;letter-spacing:-.8px;line-height:1}
.metric-value.amber{color:#D4850A}
.metric-value.red{color:#C0392B}
.metric-label{font-size:12px;color:#6B6860;margin-top:5px}

/* ── Tabs ── */
.tabs-bar{display:flex;gap:0;border-bottom:1px solid #E8E5DF;margin-bottom:24px}
.tab-btn{padding:10px 18px;background:none;border:none;border-bottom:2px solid transparent;font-size:13px;font-weight:500;font-family:inherit;color:#6B6860;cursor:pointer;margin-bottom:-1px;transition:all .15s;white-space:nowrap}
.tab-btn:hover{color:#1C1C1A}
.tab-btn.active{color:#1A5C35;border-bottom-color:#1A5C35;font-weight:600}

/* ── Patient list & cards ── */
.patient-list{display:flex;flex-direction:column;gap:8px}
.patient-card{background:#fff;border:1px solid #E8E5DF;border-radius:10px;display:flex;align-items:stretch;overflow:hidden;transition:box-shadow .15s}
.patient-card:hover{box-shadow:0 2px 10px rgba(0,0,0,.07)}
.pc-accent{width:3px;flex-shrink:0}
.pc-accent.red{background:#C0392B}
.pc-accent.amber{background:#D4850A}
.pc-accent.safe{background:#2D7A4A}
.pc-accent.blue{background:#4A6FA5}
.pc-body{flex:1;padding:14px 18px;min-width:0}
.pc-actions{padding:14px 16px;display:flex;flex-direction:column;gap:6px;justify-content:center;border-left:1px solid #F0EDE8;flex-shrink:0}
.pc-name{font-size:14px;font-weight:600;color:#1C1C1A;margin-bottom:5px}
.pc-meta{font-size:12px;color:#6B6860;line-height:1.9}
.pc-meta span{display:block}

/* ── Action buttons ── */
.btn-consult{padding:7px 14px;background:#1A5C35;color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:600;font-family:inherit;cursor:pointer;white-space:nowrap;transition:background .15s}
.btn-consult:hover{background:#154e2e}
.btn-msg{padding:7px 14px;background:#fff;color:#1C1C1A;border:1px solid #E8E5DF;border-radius:6px;font-size:12px;font-weight:500;font-family:inherit;cursor:pointer;white-space:nowrap;transition:all .15s}
.btn-msg:hover{border-color:#1A5C35;color:#1A5C35}
.btn-ghost{padding:7px 14px;background:none;color:#6B6860;border:none;border-radius:6px;font-size:12px;font-weight:500;font-family:inherit;cursor:pointer;white-space:nowrap;transition:color .15s}
.btn-ghost:hover{color:#1C1C1A}

/* ── Padroes tab ── */
.pattern-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}
.pat-sum{background:#fff;border:1px solid #E8E5DF;border-radius:10px;padding:14px 16px;display:flex;align-items:center;gap:12px;cursor:pointer;transition:border-color .15s}
.pat-sum:hover{border-color:#1C1C1A}
.pat-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.dot-escape{background:#D4850A}
.dot-confronto{background:#C0392B}
.dot-retorno{background:#4A6FA5}
.dot-culpa{background:#6B6860}
.pat-sum .ps-num{font-size:22px;font-weight:700;color:#1C1C1A;line-height:1}
.pat-sum .ps-lbl{font-size:11px;color:#6B6860;margin-top:3px}
.patterns-filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.filter-btn{padding:5px 14px;background:#fff;border:1px solid #E8E5DF;border-radius:20px;font-size:12px;font-weight:500;font-family:inherit;color:#6B6860;cursor:pointer;display:flex;align-items:center;gap:6px;transition:all .15s}
.filter-btn:hover{border-color:#1C1C1A;color:#1C1C1A}
.filter-btn.active{background:#1C1C1A;color:#fff;border-color:#1C1C1A}
.filter-btn .fd{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.trigger-tag{display:inline-block;padding:2px 7px;background:#F0EDE8;border-radius:4px;font-size:11px;color:#6B6860;margin:2px 2px 2px 0}

/* ── Consultas tab ── */
.section-label{font-size:11px;font-weight:600;color:#6B6860;text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px}
.rec-table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #E8E5DF;border-radius:10px;overflow:hidden;margin-bottom:24px}
.rec-table th{background:#F7F6F3;font-size:11px;font-weight:600;color:#6B6860;text-transform:uppercase;letter-spacing:.4px;padding:10px 14px;text-align:left;border-bottom:1px solid #E8E5DF}
.rec-table td{padding:11px 14px;font-size:13px;border-bottom:1px solid #F7F6F3;vertical-align:middle}
.rec-table tr:last-child td{border-bottom:none}
.rec-table tr:hover td{background:#FAFAF8}
.badge{display:inline-block;padding:3px 9px;border-radius:5px;font-size:11px;font-weight:600}
.badge-pend{background:#FEF9EC;color:#8A5C00}
.badge-ok{background:#F0FAF4;color:#1A5C35}
.badge-wait{background:#EEF2FF;color:#4A6FA5}
.rec-btn{padding:5px 12px;background:#1A5C35;color:#fff;border:none;border-radius:5px;font-size:11px;font-weight:600;font-family:inherit;cursor:pointer}
.rec-btn:disabled{background:#D1D5DB;cursor:not-allowed}

/* ── Reactivation badges ── */
.rbadge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;margin-bottom:5px}
.rb-responded{background:#FEF9EC;color:#8A5C00;border:1px solid #F9D27D}
.rb-scheduled{background:#EEF2FF;color:#3B54A8;border:1px solid #A5B4FC}
.rb-reactivated{background:#F0FAF4;color:#1A5C35;border:1px solid #6EE7B7}
.btn-sched{padding:7px 14px;background:#3B54A8;color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:600;font-family:inherit;cursor:pointer;white-space:nowrap;transition:background .15s}
.btn-sched:hover{background:#2D3F85}
.btn-react{padding:7px 14px;background:#2D7A4A;color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:600;font-family:inherit;cursor:pointer;white-space:nowrap;transition:background .15s}
.btn-react:hover{background:#1A5C35}

/* ── Jitsi modal ── */
.jitsi-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:200;align-items:center;justify-content:center;flex-direction:column;gap:14px}
.jitsi-bg.open{display:flex}
.jitsi-hdr{display:flex;align-items:center;justify-content:space-between;width:92vw}
.jitsi-title{font-size:14px;font-weight:600;color:#fff;letter-spacing:-.1px}
.jitsi-close{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.15);color:#fff;width:32px;height:32px;border-radius:7px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;line-height:1;font-family:inherit;transition:background .15s}
.jitsi-close:hover{background:rgba(255,255,255,.22)}
.jitsi-frame{width:92vw;height:88vh;border:none;border-radius:10px}

/* ── Prontuario modal ── */
.pron-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:150;align-items:center;justify-content:center}
.pron-bg.open{display:flex}
.pron-modal{background:#fff;border-radius:12px;padding:28px;width:100%;max-width:480px;max-height:82vh;overflow-y:auto;box-shadow:0 8px 40px rgba(0,0,0,.14)}
.pron-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px}
.pron-close{background:none;border:none;cursor:pointer;font-size:20px;color:#6B6860;padding:0;line-height:1;font-family:inherit}
.pron-section{margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid #F0EDE8}
.pron-section:last-of-type{border-bottom:none;margin-bottom:0;padding-bottom:0}
.pron-label{font-size:11px;font-weight:600;color:#6B6860;text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px}
.pron-value{font-size:14px;color:#1C1C1A}

/* ── Empty state ── */
.empty-state{text-align:center;padding:56px 24px}
.empty-title{font-size:15px;font-weight:600;color:#1C1C1A;margin-bottom:6px}
.empty-sub{font-size:13px;color:#6B6860}

/* ── Toast ── */
#toast{position:fixed;bottom:24px;right:24px;background:#1C1C1A;color:#fff;padding:11px 18px;border-radius:8px;font-size:13px;display:none;z-index:999;box-shadow:0 4px 20px rgba(0,0,0,.18);max-width:340px;line-height:1.4}
#toast.err{background:#C0392B}
#toast.ok{background:#2D7A4A}
</style>
</head>
<body>

<!-- ── LOGIN ── -->
<div class="login-wrap" id="vLogin">
  <div id="frmLogin" class="login-card">
    <div class="login-brand">
      <div class="login-brand-name">NutriDeby</div>
      <div class="login-brand-sub">Painel Clínico</div>
    </div>
    <div class="login-title">Entrar</div>
    <div class="login-sub">Acesso exclusivo para profissionais</div>
    <div class="form-field"><label>E-mail profissional</label><input type="email" id="lEmail" placeholder="dra@clinica.com.br" autocomplete="email"/></div>
    <div class="form-field"><label>Senha</label><input type="password" id="lPass" placeholder="••••••••" autocomplete="current-password"/></div>
    <button class="btn-primary" id="btnLogin" onclick="doLogin()">Entrar</button>
    <button class="btn-link" onclick="showForgot()">Esqueci minha senha</button>
    <div class="err-msg" id="lErr"></div>
  </div>

  <div id="frmForgot" class="login-card" style="display:none">
    <div class="login-brand"><div class="login-brand-name">NutriDeby</div><div class="login-brand-sub">Painel Clínico</div></div>
    <div class="login-title">Redefinir senha</div>
    <div class="login-sub">Enviaremos um link de redefinição para seu e-mail</div>
    <div class="form-field"><label>E-mail profissional</label><input type="email" id="fEmail" placeholder="dra@clinica.com.br"/></div>
    <button class="btn-primary" onclick="doForgot()">Enviar link</button>
    <button class="btn-link" onclick="showLogin()">Voltar ao login</button>
    <div class="err-msg" id="fMsg"></div>
  </div>

  <div id="frmSetPass" class="login-card" style="display:none">
    <div class="login-brand"><div class="login-brand-name">NutriDeby</div><div class="login-brand-sub">Painel Clínico</div></div>
    <div class="login-title" id="setPassTitle">Criar senha</div>
    <div class="login-sub" id="setPassSub">Defina sua senha para acessar o painel</div>
    <div class="form-field"><label>Nova senha (mín. 8 caracteres)</label><input type="password" id="spPass" placeholder="••••••••"/></div>
    <div class="form-field"><label>Confirmar senha</label><input type="password" id="spPass2" placeholder="••••••••"/></div>
    <button class="btn-primary" onclick="doSetPass()">Salvar senha</button>
    <div class="err-msg" id="spErr"></div>
  </div>
</div>

<!-- ── PAINEL PRINCIPAL ── -->
<div id="vMain" style="display:none">

  <header class="app-header">
    <div class="header-brand">
      <div class="header-wordmark">NutriDeby</div>
      <div class="header-sep"></div>
      <div class="header-sub">Painel Clínico</div>
    </div>
    <div class="header-right">
      <div class="header-nutri-name" id="hNutriName"></div>
      <button class="btn-session" onclick="doLogout()">Encerrar sessão</button>
    </div>
  </header>

  <div class="alert-bar" id="alertBar" style="display:none">
    <div class="alert-dot"></div>
    <div class="alert-text" id="alertText"></div>
    <button class="alert-dismiss" onclick="this.closest('.alert-bar').style.display='none'">&#xD7;</button>
  </div>

  <div class="app-body">

    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-value" id="mTotal">—</div>
        <div class="metric-label">Pacientes ativos</div>
      </div>
      <div class="metric-card clickable" onclick="switchTab('atencao')">
        <div class="metric-value amber" id="mInativos">—</div>
        <div class="metric-label">Inativos 7+ dias</div>
      </div>
      <div class="metric-card">
        <div class="metric-value" id="mPadroes">—</div>
        <div class="metric-label">Padrões detectados</div>
      </div>
      <div class="metric-card">
        <div class="metric-value" id="mSemana">—</div>
        <div class="metric-label">Prontuários esta semana</div>
      </div>
      <div class="metric-card clickable" onclick="switchTab('todos')">
        <div class="metric-value amber" id="mResponded">—</div>
        <div class="metric-label">Responderam (aguard. agendamento)</div>
      </div>
      <div class="metric-card clickable" onclick="switchTab('todos')">
        <div class="metric-value" style="color:#3B54A8" id="mScheduled">—</div>
        <div class="metric-label">Consulta agendada</div>
      </div>
      <div class="metric-card clickable" onclick="switchTab('todos')">
        <div class="metric-value" style="color:#2D7A4A" id="mReactivated">—</div>
        <div class="metric-label">Retorno confirmado</div>
      </div>
    </div>

    <div class="tabs-bar">
      <button class="tab-btn active" data-tab="atencao" onclick="switchTab('atencao')">Atenção</button>
      <button class="tab-btn" data-tab="todos" onclick="switchTab('todos')">Todos os pacientes</button>
      <button class="tab-btn" data-tab="padroes" onclick="switchTab('padroes')">Padrões clínicos</button>
      <button class="tab-btn" data-tab="consultas" onclick="switchTab('consultas')">Consultas</button>
    </div>

    <div id="tabAtencao"></div>
    <div id="tabTodos" style="display:none"></div>
    <div id="tabPadroes" style="display:none"></div>
    <div id="tabConsultas" style="display:none"></div>

  </div>
</div>

<!-- ── JITSI MODAL ── -->
<div class="jitsi-bg" id="modalJitsi">
  <div class="jitsi-hdr">
    <div class="jitsi-title" id="jitsiTitle">Consulta ao vivo</div>
    <button class="jitsi-close" onclick="closeJitsi()">&#xD7;</button>
  </div>
  <iframe class="jitsi-frame" id="jitsiFrame" src="" allow="camera;microphone;fullscreen;display-capture" allowfullscreen></iframe>
</div>

<!-- ── PRONTUARIO MODAL ── -->
<div class="pron-bg" id="modalPron">
  <div class="pron-modal">
    <div class="pron-header">
      <div>
        <div style="font-size:16px;font-weight:700;color:#1C1C1A" id="pName"></div>
        <div style="font-size:12px;color:#6B6860;margin-top:3px" id="pSub"></div>
      </div>
      <button class="pron-close" onclick="closePron()">&#xD7;</button>
    </div>
    <div id="pContent"></div>
    <div style="display:flex;gap:8px;margin-top:20px;padding-top:16px;border-top:1px solid #F0EDE8">
      <button class="btn-consult" id="pBtnConsult" style="flex:1">Iniciar consulta</button>
      <button class="btn-msg" id="pBtnMsg" style="flex:1">Mensagem</button>
      <button class="btn-ghost" onclick="closePron()">Fechar</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
'use strict';
var _tok = localStorage.getItem('nt');
var _me = null;
try { _me = JSON.parse(localStorage.getItem('nm') || 'null'); } catch(e) {}
var _grid = [];
var _records = [];
var _pending = [];
var _currentTab = 'atencao';

var _qp = new URLSearchParams(location.search);
var _action = _qp.get('action'), _token = _qp.get('token');

if (_action === 'invite' && _token) {
  showSetPass('Criar senha', 'Bem-vinda! Defina sua senha para acessar o painel.', 'invite');
} else if (_action === 'reset' && _token) {
  showSetPass('Redefinir senha', 'Digite sua nova senha abaixo.', 'reset');
} else if (_tok && _me) {
  showMain();
}

/* ── Auth UI ─────────────────────────────────── */
function showLogin() {
  hide('frmForgot'); hide('frmSetPass'); show('frmLogin');
  show('vLogin'); hide('vMain');
}
function showForgot() { hide('frmLogin'); hide('frmSetPass'); show('frmForgot'); }
function showSetPass(title, sub, mode) {
  $('setPassTitle').textContent = title;
  $('setPassSub').textContent = sub;
  hide('frmLogin'); hide('frmForgot'); show('frmSetPass');
  show('vLogin'); hide('vMain');
  document.body.dataset.spMode = mode;
}

async function doLogin() {
  var btn = $('btnLogin');
  btn.disabled = true; btn.textContent = 'Entrando...';
  $('lErr').textContent = '';
  try {
    var r = await apiPost('/api/nutri/login', {email: $v('lEmail'), password: $v('lPass')});
    _tok = r.access_token; _me = r.nutricionista;
    localStorage.setItem('nt', _tok);
    localStorage.setItem('nm', JSON.stringify(_me));
    showMain();
  } catch(e) { $('lErr').textContent = e.message; }
  btn.disabled = false; btn.textContent = 'Entrar';
}

async function doForgot() {
  $('fMsg').textContent = '';
  try {
    var r = await apiPost('/api/nutri/forgot-password', {email: $v('fEmail')});
    $('fMsg').style.color = '#2D7A4A';
    $('fMsg').textContent = r.message;
  } catch(e) { $('fMsg').style.color = '#C0392B'; $('fMsg').textContent = e.message; }
}

async function doSetPass() {
  var pw = $v('spPass'), pw2 = $v('spPass2');
  if (pw !== pw2) { $('spErr').textContent = 'As senhas nao coincidem'; return; }
  if (pw.length < 8) { $('spErr').textContent = 'Minimo 8 caracteres'; return; }
  var mode = document.body.dataset.spMode;
  var ep = mode === 'invite' ? '/api/nutri/accept-invite' : '/api/nutri/reset-password';
  var body = mode === 'invite' ? {token: _token, password: pw} : {token: _token, new_password: pw};
  try {
    var r = await apiPost(ep, body);
    toast(r.message, 'ok');
    setTimeout(function() { history.replaceState({}, '', '/painel'); showLogin(); }, 1800);
  } catch(e) { $('spErr').textContent = e.message; }
}

function showMain() {
  hide('vLogin'); show('vMain');
  $('hNutriName').textContent = _me.name;
  loadData();
}

function doLogout() {
  localStorage.removeItem('nt'); localStorage.removeItem('nm');
  location.reload();
}

/* ── Data ─────────────────────────────────────── */
async function loadData() {
  try {
    var results = await Promise.all([
      authGet('/api/nutri/grid-padroes'),
      authGet('/api/nutri/records'),
      authGet('/api/nutri/pending'),
    ]);
    var gridResp = results[0], recsResp = results[1], pendResp = results[2];
    _grid    = gridResp.pacientes || [];
    _records = recsResp.records   || [];
    _pending = pendResp.records   || [];
    updateMetrics(gridResp);
    renderAtencao();
  } catch(e) {
    if (e.status === 401) doLogout();
  }
}

function updateMetrics(g) {
  var inat7  = _grid.filter(function(p){ return daysInactive(p) >= 7; }).length;
  var inat14 = _grid.filter(function(p){ return daysInactive(p) >= 14; }).length;
  var weekAgo = new Date(Date.now() - 7 * 86400000).toISOString();
  var semana  = _records.filter(function(r){ return r.created_at && r.created_at > weekAgo; }).length;
  var react   = g.reativacao || {};

  $('mTotal').textContent      = g.total || 0;
  $('mInativos').textContent   = inat7;
  $('mPadroes').textContent    = g.com_padrao || 0;
  $('mSemana').textContent     = semana;
  $('mResponded').textContent  = react.responded  || 0;
  $('mScheduled').textContent  = react.scheduled  || 0;
  $('mReactivated').textContent = react.reactivated || 0;

  if (inat14 > 0) {
    $('alertText').textContent = inat14 + ' paciente' + (inat14 > 1 ? 's' : '') + ' sem contato ha mais de 14 dias.';
    show('alertBar');
  }
}

/* ── Tabs ─────────────────────────────────────── */
function switchTab(tab) {
  _currentTab = tab;
  document.querySelectorAll('.tab-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  var tabs = ['atencao','todos','padroes','consultas'];
  tabs.forEach(function(t) {
    var el = $('tab' + cap(t));
    if (el) el.style.display = (t === tab) ? '' : 'none';
  });
  if (tab === 'atencao')  renderAtencao();
  if (tab === 'todos')    renderTodos();
  if (tab === 'padroes')  renderPadroes();
  if (tab === 'consultas') renderConsultas();
}

/* ── Rendering ────────────────────────────────── */
function renderAtencao() {
  var urgent = _grid
    .filter(function(p) { return daysInactive(p) >= 7 || (p.padrao && p.padrao.fase === 'CONFRONTO'); })
    .sort(function(a, b) { return daysInactive(b) - daysInactive(a); });
  if (!urgent.length) {
    $('tabAtencao').innerHTML = '<div class="empty-state"><div class="empty-title">Nenhuma atencao necessaria agora</div><div class="empty-sub">Todas as pacientes registraram atividade nos ultimos 7 dias.</div></div>';
    return;
  }
  $('tabAtencao').innerHTML = '<div class="patient-list">' + urgent.map(patientCard).join('') + '</div>';
}

function renderTodos() {
  if (!_grid.length) {
    $('tabTodos').innerHTML = '<div class="empty-state"><div class="empty-title">Nenhuma paciente cadastrada</div></div>';
    return;
  }
  var sorted = _grid.slice().sort(function(a, b) { return daysInactive(b) - daysInactive(a); });
  $('tabTodos').innerHTML = '<div class="patient-list">' + sorted.map(patientCard).join('') + '</div>';
}

function renderPadroes() {
  var resumo = {ESCAPE:0, CONFRONTO:0, RETORNO:0, CULPA:0};
  _grid.filter(function(p){ return p.padrao; }).forEach(function(p) {
    if (resumo[p.padrao.fase] !== undefined) resumo[p.padrao.fase]++;
  });

  var phases = [
    {fase:'ESCAPE',    label:'Escape alimentar', dc:'dot-escape'},
    {fase:'CONFRONTO', label:'Confronto',         dc:'dot-confronto'},
    {fase:'RETORNO',   label:'Retorno ao padrao', dc:'dot-retorno'},
    {fase:'CULPA',     label:'Culpa emocional',   dc:'dot-culpa'},
  ];

  var sumHtml = phases.map(function(c) {
    return '<div class="pat-sum" onclick="filterPadroes(\'' + c.fase + '\')">'
      + '<div class="pat-dot ' + c.dc + '"></div>'
      + '<div><div class="ps-num">' + (resumo[c.fase]||0) + '</div><div class="ps-lbl">' + c.label + '</div></div>'
      + '</div>';
  }).join('');

  var filterHtml = '<div class="patterns-filters" id="pfFilters">'
    + '<button class="filter-btn active" data-fase="todos" onclick="filterPadroes(\'todos\')">Todos</button>'
    + phases.map(function(c) {
        return '<button class="filter-btn" data-fase="' + c.fase + '" onclick="filterPadroes(\'' + c.fase + '\')">'
          + '<span class="fd ' + c.dc + '"></span>' + c.label + '</button>';
      }).join('')
    + '</div>';

  $('tabPadroes').innerHTML = '<div class="pattern-summary">' + sumHtml + '</div>' + filterHtml
    + '<div id="padGrid" class="patient-list"></div>';

  renderPadGrid('todos');
}

var _padFiltro = 'todos';
function filterPadroes(fase) {
  _padFiltro = fase;
  document.querySelectorAll('#pfFilters .filter-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.fase === fase);
  });
  renderPadGrid(fase);
}

function renderPadGrid(filtro) {
  var rows = _grid.filter(function(p) {
    return p.padrao && (filtro === 'todos' || p.padrao.fase === filtro);
  });
  var el = $('padGrid');
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-title">Nenhum padrao detectado nesta categoria</div></div>';
    return;
  }
  el.innerHTML = rows.map(patientCard).join('');
}

function patientCard(p) {
  var di = daysInactive(p);
  var accent = di >= 14 ? 'red' : di >= 7 ? 'amber' : (p.padrao && p.padrao.fase === 'CONFRONTO') ? 'red' : 'safe';
  var contactTxt = di === 0 ? 'Ultimo contato: hoje'
    : di === 1 ? 'Ultimo contato: ha 1 dia'
    : di < 999 ? 'Ultimo contato: ha ' + di + ' dias'
    : 'Ultimo contato: nao registrado';

  var patternTxt = '';
  if (p.padrao) {
    var pl = phaseLabel(p.padrao.fase);
    var gat = (p.padrao.gatilhos || []).slice(0, 4).join(', ');
    patternTxt = '<span>Padrao: ' + pl + (gat ? ' — gatilhos: ' + esc(gat) : '') + '</span>';
  }

  var streakTxt = '<span>Sequencia: ' + (p.streak || 0) + (p.streak === 1 ? ' dia' : ' dias') + '</span>';
  var ph  = esc(p.phone || '');
  var nm  = escq(titleCase(p.nome || 'Paciente'));
  var pid = esc(p.id || '');
  var dname = esc(titleCase(p.nome || 'Paciente'));

  var stage     = p.reactivation_stage || '';
  var stageBadge = '';
  var stageActions = '';

  if (stage === 'responded') {
    stageBadge = '<div class="rbadge rb-responded">Respondeu — aguarda agendamento</div>';
    stageActions = '<button class="btn-sched" data-id="' + pid + '" onclick="confirmScheduled(this.dataset.id)">Confirmar agendamento</button>'
      + '<button class="btn-ghost" data-id="' + pid + '" onclick="openPron(this.dataset.id)">Prontuario</button>';
  } else if (stage === 'scheduled') {
    stageBadge = '<div class="rbadge rb-scheduled">Consulta agendada</div>';
    stageActions = '<button class="btn-react" data-id="' + pid + '" onclick="confirmReactivation(this.dataset.id)">Confirmar retorno</button>'
      + '<button class="btn-consult" data-id="' + pid + '" data-name="' + nm + '" data-phone="' + ph + '" onclick="doConsult(this.dataset.id,this.dataset.name,this.dataset.phone)">Iniciar consulta</button>'
      + '<button class="btn-ghost" data-id="' + pid + '" onclick="openPron(this.dataset.id)">Prontuario</button>';
  } else if (stage === 'reactivated') {
    stageBadge = '<div class="rbadge rb-reactivated">Retorno confirmado</div>';
    stageActions = '<button class="btn-ghost" data-id="' + pid + '" onclick="openPron(this.dataset.id)">Ver prontuario</button>';
  } else {
    stageActions = '<button class="btn-consult" data-id="' + pid + '" data-name="' + nm + '" data-phone="' + ph + '" onclick="doConsult(this.dataset.id,this.dataset.name,this.dataset.phone)">Iniciar consulta</button>'
      + '<button class="btn-msg" data-phone="' + ph + '" data-name="' + nm + '" onclick="openWA(this.dataset.phone,this.dataset.name)">Mensagem</button>'
      + '<button class="btn-ghost" data-id="' + pid + '" onclick="openPron(this.dataset.id)">Prontuario</button>';
  }

  return '<div class="patient-card">'
    + '<div class="pc-accent ' + accent + '"></div>'
    + '<div class="pc-body">'
    + '<div class="pc-name">' + dname + '</div>'
    + (stageBadge ? '<div>' + stageBadge + '</div>' : '')
    + '<div class="pc-meta"><span>' + contactTxt + '</span>' + patternTxt + streakTxt + '</div>'
    + '</div>'
    + '<div class="pc-actions">' + stageActions + '</div>'
    + '</div>';
}

function renderConsultas() {
  var html = '';

  html += '<div class="section-label">Prontuarios pendentes de assinatura</div>';
  if (!_pending.length) {
    html += '<div class="empty-state" style="padding:32px"><div class="empty-sub">Nenhum prontuario pendente no momento.</div></div>';
  } else {
    html += '<table class="rec-table"><thead><tr><th>Paciente</th><th>Data</th><th>D4Sign</th><th>Acao</th></tr></thead><tbody>';
    _pending.forEach(function(r) {
      var dt = r.created_at ? new Date(r.created_at).toLocaleDateString('pt-BR') : '—';
      var canSign = r.can_sign && r.d4sign_status === 'NONE';
      html += '<tr>'
        + '<td><strong>' + esc(titleCase(r.patient_name)) + '</strong></td>'
        + '<td style="color:#6B6860">' + dt + '</td>'
        + '<td>' + d4badge(r.d4sign_status) + '</td>'
        + '<td><button class="rec-btn" ' + (canSign ? '' : 'disabled') + ' onclick="signRecord(' + r.id + ',this)">'
        + (canSign ? 'Enviar para assinatura' : 'Aguardando') + '</button>'
        + '&nbsp;<button class="btn-msg" style="font-size:11px;padding:5px 10px" data-id="' + esc(r.patient_id) + '" data-name="' + escq(titleCase(r.patient_name)) + '" data-phone="' + esc(r.patient_phone||'') + '" onclick="doConsult(this.dataset.id,this.dataset.name,this.dataset.phone)">Consulta</button>'
        + '</td></tr>';
    });
    html += '</tbody></table>';
  }

  html += '<div class="section-label" style="margin-top:8px">Historico de prontuarios</div>';
  if (!_records.length) {
    html += '<div class="empty-state" style="padding:32px"><div class="empty-sub">Nenhum registro.</div></div>';
  } else {
    html += '<table class="rec-table"><thead><tr><th>Paciente</th><th>Nutricionista</th><th>Data</th><th>Status</th><th>PDF</th></tr></thead><tbody>';
    _records.slice(0, 60).forEach(function(r) {
      var dt  = r.created_at ? new Date(r.created_at).toLocaleDateString('pt-BR') : '—';
      var sb  = r.status === 'ASSINADO' ? '<span class="badge badge-ok">Assinado</span>' : '<span class="badge badge-pend">Pendente</span>';
      var pdf = r.d4sign_signed_pdf_url ? '<a href="' + r.d4sign_signed_pdf_url + '" target="_blank" style="color:#1A5C35;font-size:12px">Download</a>'
              : r.pdf_url ? '<a href="' + r.pdf_url + '" target="_blank" style="color:#1A5C35;font-size:12px">PDF</a>' : '—';
      html += '<tr><td><strong>' + esc(titleCase(r.patient_name)) + '</strong></td>'
        + '<td style="color:#6B6860">' + esc(r.nutricionista||'—') + '</td>'
        + '<td style="color:#6B6860">' + dt + '</td>'
        + '<td>' + sb + '</td>'
        + '<td>' + pdf + '</td></tr>';
    });
    html += '</tbody></table>';
  }

  $('tabConsultas').innerHTML = html;
}

/* ── Actions ──────────────────────────────────── */
async function doConsult(patientId, patientName, patientPhone) {
  try {
    var d = await authPost('/api/nutri/start-consultation', {
      patient_id: patientId,
      patient_name: titleCase(patientName),
      patient_phone: patientPhone || '',
    });
    if (patientPhone) toast('Mensagem enviada para ' + titleCase(patientName), 'ok');
    openJitsi(d.room_url, titleCase(patientName));
  } catch(e) {
    toast('Erro: ' + e.message, 'err');
  }
}

function openJitsi(url, name) {
  $('jitsiTitle').textContent = 'Consulta — ' + name;
  $('jitsiFrame').src = url;
  $('modalJitsi').classList.add('open');
}

function closeJitsi() {
  $('jitsiFrame').src = '';
  $('modalJitsi').classList.remove('open');
}

function openWA(phone, name) {
  if (!phone) { toast('Paciente sem telefone cadastrado', 'err'); return; }
  window.open('https://wa.me/' + phone.replace(/\\D/g, ''), '_blank');
}

function openPron(patientId) {
  var p = _grid.find(function(x) { return x.id === patientId; });
  if (!p) return;
  var di = daysInactive(p);
  $('pName').textContent = titleCase(p.nome);
  $('pSub').textContent  = di < 999 ? 'Ultimo contato ha ' + di + ' dia' + (di === 1 ? '' : 's') : 'Sem registros de refeicao';

  var html = '';

  html += '<div class="pron-section"><div class="pron-label">Engajamento</div>'
    + '<div class="pron-value">Sequencia atual: ' + (p.streak || 0) + ' dia' + ((p.streak||0) === 1 ? '' : 's') + '</div></div>';

  if (p.padrao) {
    var lb  = phaseLabel(p.padrao.fase);
    var gat = (p.padrao.gatilhos || []);
    var tags = gat.map(function(g) { return '<span class="trigger-tag">' + esc(g) + '</span>'; }).join('');
    var da  = p.padrao.dias_atras;
    var detTxt = (da === 0) ? 'hoje' : (da === 1) ? 'ha 1 dia' : (da != null ? 'ha ' + da + ' dias' : '');
    html += '<div class="pron-section"><div class="pron-label">Padrao comportamental</div>'
      + '<div class="pron-value">' + esc(lb) + ' — Ciclo ' + (p.padrao.ciclo || 1) + '</div>'
      + (tags ? '<div style="margin-top:7px">' + tags + '</div>' : '')
      + (detTxt ? '<div style="font-size:12px;color:#6B6860;margin-top:6px">Detectado ' + detTxt + '</div>' : '')
      + '</div>';

    if (p.padrao.acao_recomendada) {
      html += '<div class="pron-section"><div class="pron-label">Recomendacao clinica</div>'
        + '<div class="pron-value">' + esc(p.padrao.acao_recomendada) + '</div></div>';
    }
  } else {
    html += '<div class="pron-section"><div class="pron-label">Padrao comportamental</div>'
      + '<div class="pron-value" style="color:#6B6860">Nenhum padrao detectado ainda</div></div>';
  }

  if (p.phone) {
    html += '<div class="pron-section"><div class="pron-label">Contato</div>'
      + '<div class="pron-value">' + esc(p.phone) + '</div></div>';
  }

  $('pContent').innerHTML = html;
  $('pBtnConsult').onclick = function() { closePron(); doConsult(p.id, p.nome, p.phone||''); };
  $('pBtnMsg').onclick     = function() { closePron(); openWA(p.phone||'', p.nome); };
  $('modalPron').classList.add('open');
}

function closePron() { $('modalPron').classList.remove('open'); }

async function signRecord(id, btn) {
  btn.disabled = true; btn.textContent = 'Enviando...';
  try {
    await authPost('/api/nutri/initiate-signing/' + id, {});
    toast('E-mail D4Sign enviado com sucesso', 'ok');
    var res = await Promise.all([authGet('/api/nutri/records'), authGet('/api/nutri/pending')]);
    _records = res[0].records || []; _pending = res[1].records || [];
    renderConsultas();
  } catch(e) {
    toast('Erro: ' + e.message, 'err');
    btn.disabled = false; btn.textContent = 'Enviar para assinatura';
  }
}

/* ── Reactivation actions ─────────────────────── */
async function confirmScheduled(patientId) {
  try {
    await authPost('/api/nutri/confirm-scheduled', {patient_id: patientId});
    toast('Agendamento confirmado', 'ok');
    var p = _grid.find(function(x){ return x.id === patientId; });
    if (p) p.reactivation_stage = 'scheduled';
    if (_currentTab === 'atencao') renderAtencao();
    else if (_currentTab === 'todos') renderTodos();
  } catch(e) { toast('Erro: ' + e.message, 'err'); }
}

async function confirmReactivation(patientId) {
  try {
    var d = await authPost('/api/nutri/confirm-reactivation', {patient_id: patientId});
    toast('Retorno confirmado para ' + titleCase(d.patient_name), 'ok');
    var p = _grid.find(function(x){ return x.id === patientId; });
    if (p) p.reactivation_stage = 'reactivated';
    if (_currentTab === 'atencao') renderAtencao();
    else if (_currentTab === 'todos') renderTodos();
  } catch(e) { toast('Erro: ' + e.message, 'err'); }
}

/* ── Helpers ──────────────────────────────────── */
function daysInactive(p) {
  if (!p.ultimo_registro) return 999;
  return Math.floor((Date.now() - new Date(p.ultimo_registro).getTime()) / 86400000);
}

function phaseLabel(fase) {
  var m = {ESCAPE:'Escape alimentar', CONFRONTO:'Confronto', RETORNO:'Retorno ao padrao', CULPA:'Culpa emocional'};
  return m[fase] || fase;
}

function titleCase(s) {
  if (!s) return '';
  return s.toLowerCase().replace(/\\b\\w/g, function(c) { return c.toUpperCase(); });
}

function d4badge(s) {
  if (!s || s === 'NONE') return '<span style="color:#6B6860">—</span>';
  if (s === 'PENDING_SIGNATURE') return '<span class="badge badge-wait">Aguardando</span>';
  if (s === 'SIGNED') return '<span class="badge badge-ok">Assinado</span>';
  return '<span class="badge">' + esc(s) + '</span>';
}

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
function $(id) { return document.getElementById(id); }
function $v(id) { return $(id).value.trim(); }
function show(id) { $(id).style.display = ''; }
function hide(id) { $(id).style.display = 'none'; }
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escq(s) { return String(s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

async function apiPost(url, body) {
  var r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  var d = await r.json();
  if (!r.ok) { var e = new Error(d.detail||'Erro'); e.status = r.status; throw e; }
  return d;
}
async function authGet(url) {
  var r = await fetch(url, {headers:{Authorization:'Bearer ' + _tok}});
  var d = await r.json();
  if (!r.ok) { var e = new Error(d.detail||'Erro'); e.status = r.status; throw e; }
  return d;
}
async function authPost(url, body) {
  var r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+_tok}, body:JSON.stringify(body)});
  var d = await r.json();
  if (!r.ok) { var e = new Error(d.detail||'Erro'); e.status = r.status; throw e; }
  return d;
}

var _toastT = null;
function toast(msg, type) {
  var t = $('toast'); t.textContent = msg;
  t.className = type === 'err' ? 'err' : type === 'ok' ? 'ok' : '';
  t.style.display = 'block';
  clearTimeout(_toastT);
  _toastT = setTimeout(function() { t.style.display = 'none'; }, 4500);
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') { closeJitsi(); closePron(); }
  if (e.key === 'Enter') {
    if ($('frmLogin')   && $('frmLogin').style.display   !== 'none') doLogin();
    if ($('frmForgot')  && $('frmForgot').style.display  !== 'none') doForgot();
    if ($('frmSetPass') && $('frmSetPass').style.display !== 'none') doSetPass();
  }
});
$('modalPron').addEventListener('click', function(e) { if (e.target === this) closePron(); });
</script>
</body>
</html>
"""
