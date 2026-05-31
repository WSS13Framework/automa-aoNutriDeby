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

@router.get("/metrics")
def get_metrics(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Métricas reais do painel: ativos, inativos 14d, padrões, feed de atividade."""
    _auth(request, settings)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:

            # Pacientes ativos: tiveram mensagem respondida nos últimos 30 dias
            cur.execute("""
                SELECT COUNT(DISTINCT patient_id) AS cnt
                FROM inbound_messages
                WHERE replied_at > NOW() - INTERVAL '30 days'
                  AND patient_id IS NOT NULL
            """)
            active_count = (cur.fetchone() or {}).get("cnt") or 0

            # Inativos 14+: já tiveram contato mas não nos últimos 14 dias
            cur.execute("""
                SELECT COUNT(DISTINCT p.id) AS cnt
                FROM patients p
                WHERE p.display_name IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM inbound_messages im
                      WHERE im.patient_id = p.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM inbound_messages im
                      WHERE im.patient_id = p.id
                        AND im.replied_at > NOW() - INTERVAL '14 days'
                  )
            """)
            inactive_14 = (cur.fetchone() or {}).get("cnt") or 0

            # Padrões detectados (pacientes únicos com padrão)
            cur.execute("SELECT COUNT(DISTINCT patient_id) AS cnt FROM padroes_alimentares")
            patterns_count = (cur.fetchone() or {}).get("cnt") or 0

            # Reativação por stage
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE reactivation_stage = 'responded')   AS responded,
                    COUNT(*) FILTER (WHERE reactivation_stage = 'scheduled')   AS scheduled,
                    COUNT(*) FILTER (WHERE reactivation_stage = 'reactivated') AS reactivated
                FROM patients
            """)
            react = cur.fetchone() or {}

            # Lista de pacientes inativos 14+ dias para a aba Atenção
            cur.execute("""
                SELECT
                    p.id,
                    p.display_name,
                    p.reactivation_stage,
                    pp.phone,
                    MAX(im.replied_at)                                        AS last_contact,
                    EXTRACT(DAY FROM NOW() - MAX(im.replied_at))::int         AS days_inactive,
                    pa.fase                                                    AS padrao_fase
                FROM patients p
                LEFT JOIN LATERAL (
                    SELECT phone FROM patient_phones
                    WHERE patient_id = p.id ORDER BY created_at LIMIT 1
                ) pp ON true
                LEFT JOIN inbound_messages im ON im.patient_id = p.id
                LEFT JOIN LATERAL (
                    SELECT fase FROM padroes_alimentares
                    WHERE patient_id = p.id ORDER BY data_deteccao DESC LIMIT 1
                ) pa ON true
                WHERE p.display_name IS NOT NULL
                  AND EXISTS (SELECT 1 FROM inbound_messages im2 WHERE im2.patient_id = p.id)
                GROUP BY p.id, p.display_name, p.reactivation_stage, pp.phone, pa.fase
                HAVING MAX(im.replied_at) < NOW() - INTERVAL '14 days'
                    OR MAX(im.replied_at) IS NULL
                ORDER BY MAX(im.replied_at) ASC NULLS LAST
                LIMIT 60
            """)
            inactive_rows = cur.fetchall()

            # Feed de atividade: últimas 10 respostas da IA
            cur.execute("""
                SELECT im.patient_id, p.display_name, im.replied_at, im.reply_body
                FROM inbound_messages im
                LEFT JOIN patients p ON p.id = im.patient_id
                WHERE im.reply_body IS NOT NULL AND im.replied_at IS NOT NULL
                ORDER BY im.replied_at DESC
                LIMIT 10
            """)
            feed_rows = cur.fetchall()

    return {
        "active_count":   int(active_count),
        "inactive_14":    int(inactive_14),
        "patterns_count": int(patterns_count),
        "reactivation": {
            "responded":   int(react.get("responded")   or 0),
            "scheduled":   int(react.get("scheduled")   or 0),
            "reactivated": int(react.get("reactivated") or 0),
        },
        "inactive_patients": [
            {
                "id":                str(r["id"]),
                "nome":              r.get("display_name") or "Paciente",
                "phone":             r.get("phone") or "",
                "days_inactive":     int(r.get("days_inactive") or 999),
                "padrao_fase":       r.get("padrao_fase"),
                "reactivation_stage": r.get("reactivation_stage"),
                "last_contact":      r["last_contact"].isoformat() if r.get("last_contact") else None,
            }
            for r in inactive_rows
        ],
        "activity_feed": [
            {
                "patient_name": r.get("display_name") or "Paciente",
                "replied_at":   r["replied_at"].isoformat() if r.get("replied_at") else None,
                "preview":      (r.get("reply_body") or "")[:100],
            }
            for r in feed_rows
        ],
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
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --brand:#1B7A4E;
  --sidebar-bg:#1A3527;
  --sidebar-width:220px;
  --topbar-h:56px;
  --font-heading:'Montserrat',system-ui,sans-serif;
  --font-body:'Inter',system-ui,sans-serif;
  --bg:#F0F2F0;
  --card:#FFFFFF;
  --border:#E2E8E4;
  --text:#1A1A1A;
  --muted:#637068;
  --red:#C0392B;
  --amber:#D4850A;
  --safe:#1B7A4E;
}
body{font-family:var(--font-body);background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}

/* ── Login ── */
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:100vh;background:var(--sidebar-bg)}
.login-card{background:#fff;border-radius:10px;padding:40px;width:100%;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,.25)}
.login-logo{font-family:var(--font-heading);font-size:22px;font-weight:700;color:var(--brand);margin-bottom:6px}
.login-sub{font-size:13px;color:var(--muted);margin-bottom:28px}
.field-label{display:block;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px}
.field-input{width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:7px;font-size:14px;font-family:var(--font-body);outline:none;color:var(--text);transition:border-color .15s}
.field-input:focus{border-color:var(--brand)}
.field-group{margin-bottom:16px}
.btn-login{width:100%;padding:11px;background:var(--brand);color:#fff;border:none;border-radius:7px;font-size:14px;font-weight:600;font-family:var(--font-heading);cursor:pointer;transition:background .15s;margin-top:4px}
.btn-login:hover{background:#155e3c}
.btn-login:disabled{background:#9CA3AF;cursor:not-allowed}
.btn-link-sm{background:none;border:none;color:var(--brand);font-size:13px;cursor:pointer;font-family:var(--font-body);text-decoration:underline;display:block;text-align:center;margin-top:14px}
.err-text{font-size:12px;color:var(--red);margin-top:8px}
.ok-text{font-size:12px;color:var(--safe);margin-top:8px}

/* ── Sidebar ── */
#sidebar{
  position:fixed;top:0;left:0;width:var(--sidebar-width);height:100vh;
  background:var(--sidebar-bg);
  display:flex;flex-direction:column;
  z-index:200;overflow-y:auto;
  transition:transform .25s;
}
.sidebar-brand{
  padding:18px 20px 16px;
  border-bottom:1px solid rgba(255,255,255,.08);
}
.sidebar-brand-name{font-family:var(--font-heading);font-size:17px;font-weight:700;color:#fff;letter-spacing:-.3px}
.sidebar-brand-tag{font-size:10px;color:rgba(255,255,255,.45);margin-top:1px;text-transform:uppercase;letter-spacing:.5px}
.sidebar-user{
  padding:14px 20px;
  display:flex;align-items:center;gap:10px;
  border-bottom:1px solid rgba(255,255,255,.08);
}
.sidebar-avatar{
  width:34px;height:34px;border-radius:50%;
  background:rgba(255,255,255,.15);
  color:#fff;font-size:13px;font-weight:600;font-family:var(--font-heading);
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
}
.sidebar-user-name{font-size:13px;color:rgba(255,255,255,.85);font-weight:500;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sidebar-user-role{font-size:10px;color:rgba(255,255,255,.4)}

.sidebar-nav{flex:1;padding:8px 0}
.sidebar-divider{height:1px;background:rgba(255,255,255,.08);margin:6px 0}
.sidebar-subtitle{
  padding:8px 20px 4px;
  font-size:10px;font-weight:600;color:rgba(255,255,255,.35);
  text-transform:uppercase;letter-spacing:.6px;
}
.sidebar-item a,.sidebar-item button{
  display:flex;align-items:center;gap:11px;
  padding:9px 20px;width:100%;
  color:rgba(255,255,255,.65);font-size:13px;font-family:var(--font-body);
  text-decoration:none;border:none;background:none;cursor:pointer;
  transition:all .12s;text-align:left;
}
.sidebar-item a:hover,.sidebar-item button:hover{color:#fff;background:rgba(255,255,255,.07)}
.sidebar-item a.active,.sidebar-item button.active{color:#fff;background:rgba(255,255,255,.13);font-weight:600}
.sidebar-item i{width:16px;text-align:center;font-size:13px;opacity:.85}
.sidebar-item a.active i,.sidebar-item button.active i{opacity:1}
.nav-badge{
  margin-left:auto;background:var(--red);color:#fff;
  border-radius:20px;font-size:10px;font-weight:700;
  padding:1px 7px;line-height:1.5;
}
.sidebar-footer{padding:12px 20px;border-top:1px solid rgba(255,255,255,.08)}
.sidebar-footer-text{font-size:10px;color:rgba(255,255,255,.3)}

/* ── Wrapper ── */
#wrapper{margin-left:var(--sidebar-width);min-height:100vh;display:flex;flex-direction:column}

/* ── Topbar ── */
.topbar{
  height:var(--topbar-h);background:#fff;
  border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:100;
  display:flex;align-items:center;
  padding:0 24px;gap:16px;
}
.topbar-hamburger{
  background:none;border:none;cursor:pointer;
  display:none;flex-direction:column;gap:4px;padding:4px;
}
.topbar-hamburger span{display:block;width:20px;height:2px;background:var(--text);border-radius:2px}
.topbar-logo{font-family:var(--font-heading);font-size:16px;font-weight:700;color:var(--brand);letter-spacing:-.2px}
.topbar-sep{width:1px;height:18px;background:var(--border)}
.topbar-page{font-size:13px;color:var(--muted)}
.topbar-right{margin-left:auto;display:flex;align-items:center;gap:16px}
.topbar-nutri{font-size:13px;color:var(--muted)}
.topbar-nutri strong{color:var(--text);font-weight:600}
.topbar-notif{position:relative}
.topbar-notif-btn{background:none;border:none;cursor:pointer;color:var(--muted);font-size:16px;padding:4px;position:relative}
.notif-dot{position:absolute;top:2px;right:2px;width:8px;height:8px;border-radius:50%;background:var(--red);border:1.5px solid #fff}

/* ── Content ── */
.content{flex:1;padding:24px}
.content-header{margin-bottom:20px}
.content-title{font-family:var(--font-heading);font-size:20px;font-weight:700;color:var(--text);margin-bottom:3px}
.content-sub{font-size:13px;color:var(--muted)}

/* ── Widget card ── */
.widget{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:16px}
.widget-header{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--border)}
.widget-icon{
  width:32px;height:32px;border-radius:8px;
  background:rgba(27,122,78,.1);color:var(--brand);
  display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;
}
.widget-icon.red{background:rgba(192,57,43,.1);color:var(--red)}
.widget-icon.amber{background:rgba(212,133,10,.1);color:var(--amber)}
.widget-title{font-family:var(--font-heading);font-size:14px;font-weight:600;color:var(--text)}
.widget-action{margin-left:auto;font-size:12px;color:var(--brand);text-decoration:none;font-weight:500;cursor:pointer;background:none;border:none}
.widget-body{padding:0}

/* ── Stats row ── */
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 18px}
.stat-card.clickable{cursor:pointer;transition:border-color .15s}
.stat-card.clickable:hover{border-color:var(--brand)}
.stat-value{font-family:var(--font-heading);font-size:28px;font-weight:700;color:var(--text);line-height:1;letter-spacing:-.5px}
.stat-value.amber{color:var(--amber)}
.stat-value.red{color:var(--red)}
.stat-label{font-size:12px;color:var(--muted);margin-top:4px}

/* ── Patient items (like schedule-widget__appointment) ── */
.patient-list{display:flex;flex-direction:column}
.patient-item{
  display:flex;align-items:center;gap:14px;
  padding:14px 18px;border-bottom:1px solid #F5F7F5;
  transition:background .12s;
}
.patient-item:last-child{border-bottom:none}
.patient-item:hover{background:#F8FAF8}
.patient-item-accent{width:3px;height:40px;border-radius:2px;flex-shrink:0}
.patient-avatar{
  width:38px;height:38px;border-radius:50%;
  background:rgba(27,122,78,.12);color:var(--brand);
  font-size:14px;font-weight:700;font-family:var(--font-heading);
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
}
.patient-avatar.red{background:rgba(192,57,43,.12);color:var(--red)}
.patient-avatar.amber{background:rgba(212,133,10,.12);color:var(--amber)}
.patient-info{flex:1;min-width:0}
.patient-name{font-family:var(--font-heading);font-size:14px;font-weight:600;color:var(--text);margin-bottom:2px}
.patient-desc{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.patient-meta{font-size:11px;color:var(--muted);margin-top:3px}
.patient-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}
.btn-action{
  padding:6px 13px;border:none;border-radius:6px;
  font-size:12px;font-weight:600;font-family:var(--font-body);
  cursor:pointer;white-space:nowrap;transition:all .12s;
}
.btn-action-primary{background:var(--brand);color:#fff}
.btn-action-primary:hover{background:#155e3c}
.btn-action-secondary{background:#fff;color:var(--text);border:1px solid var(--border)}
.btn-action-secondary:hover{border-color:var(--brand);color:var(--brand)}
.btn-action-ghost{background:none;color:var(--muted);border:none;padding:6px 10px}
.btn-action-ghost:hover{color:var(--text)}

/* ── Pattern badges ── */
.phase-badge{
  display:inline-flex;align-items:center;gap:5px;
  padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;
}
.phase-escape{background:#FFF3E0;color:#E65100}
.phase-confronto{background:#FCE8E8;color:var(--red)}
.phase-retorno{background:#E8EFF8;color:#2563EB}
.phase-culpa{background:#F0ECFC;color:#6D28D9}
.trigger-tag{display:inline-block;background:#F0F2F0;border-radius:4px;padding:2px 7px;font-size:11px;color:var(--muted);margin:2px 2px 2px 0}

/* ── Patterns grid (like cards-widget) ── */
.pattern-summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}
.pattern-sum{
  background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:14px 16px;display:flex;align-items:center;gap:12px;
  cursor:pointer;transition:border-color .12s;
}
.pattern-sum:hover{border-color:var(--text)}
.pattern-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.dot-escape{background:#E65100}
.dot-confronto{background:var(--red)}
.dot-retorno{background:#2563EB}
.dot-culpa{background:#6D28D9}
.pattern-sum-num{font-family:var(--font-heading);font-size:22px;font-weight:700;color:var(--text);line-height:1}
.pattern-sum-lbl{font-size:11px;color:var(--muted);margin-top:2px}

.filter-bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.filter-pill{
  padding:5px 14px;background:#fff;border:1px solid var(--border);
  border-radius:20px;font-size:12px;font-weight:500;color:var(--muted);
  cursor:pointer;font-family:var(--font-body);display:flex;align-items:center;gap:5px;
  transition:all .12s;
}
.filter-pill:hover{border-color:var(--text);color:var(--text)}
.filter-pill.active{background:var(--text);color:#fff;border-color:var(--text)}

/* ── Documents table ── */
.doc-table{width:100%;border-collapse:collapse}
.doc-table th{
  background:#F8FAF8;font-size:11px;font-weight:600;color:var(--muted);
  text-transform:uppercase;letter-spacing:.4px;padding:10px 16px;
  text-align:left;border-bottom:1px solid var(--border);
}
.doc-table td{padding:12px 16px;font-size:13px;border-bottom:1px solid #F5F7F5;vertical-align:middle}
.doc-table tr:last-child td{border-bottom:none}
.doc-table tr:hover td{background:#F8FAF8}
.status-badge{display:inline-block;padding:3px 9px;border-radius:5px;font-size:11px;font-weight:600}
.status-pend{background:#FEF9EC;color:#92600A}
.status-ok{background:#ECFDF5;color:var(--safe)}
.status-wait{background:#EEF2FF;color:#4338CA}
.btn-sign{padding:5px 12px;background:var(--brand);color:#fff;border:none;border-radius:5px;font-size:11px;font-weight:600;cursor:pointer;font-family:var(--font-body)}
.btn-sign:disabled{background:#D1D5DB;cursor:not-allowed}

/* ── Empty state ── */
.empty-state{text-align:center;padding:56px 20px}
.empty-icon{font-size:42px;color:#D1D5DB;margin-bottom:14px}
.empty-title{font-family:var(--font-heading);font-size:15px;font-weight:600;color:var(--text);margin-bottom:6px}
.empty-sub{font-size:13px;color:var(--muted)}

/* ── Jitsi modal ── */
.jitsi-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:500;align-items:center;justify-content:center;flex-direction:column;gap:12px}
.jitsi-bg.open{display:flex}
.jitsi-bar{display:flex;align-items:center;justify-content:space-between;width:92vw}
.jitsi-title{font-family:var(--font-heading);font-size:14px;font-weight:600;color:#fff}
.jitsi-close{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);color:#fff;width:34px;height:34px;border-radius:8px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;font-family:var(--font-body)}
.jitsi-frame{width:92vw;height:88vh;border:none;border-radius:10px}

/* ── Drawer (patient detail — like Dietbox's drawer) ── */
.drawer-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:300;align-items:flex-end;justify-content:center}
.drawer-bg.open{display:flex}
.drawer{
  background:#fff;border-radius:14px 14px 0 0;
  width:100%;max-width:700px;
  padding:28px 28px 36px;max-height:80vh;overflow-y:auto;
}
.drawer-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}
.drawer-name{font-family:var(--font-heading);font-size:18px;font-weight:700;color:var(--text)}
.drawer-sub{font-size:13px;color:var(--muted);margin-top:3px}
.drawer-close{background:none;border:none;cursor:pointer;font-size:20px;color:var(--muted);font-family:var(--font-body);padding:0;line-height:1}
.drawer-section{margin-bottom:18px;padding-bottom:18px;border-bottom:1px solid #F0F2F0}
.drawer-section:last-of-type{border-bottom:none;margin-bottom:0;padding-bottom:0}
.drawer-label{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:5px}
.drawer-value{font-size:14px;color:var(--text)}
.drawer-footer{display:flex;gap:10px;margin-top:20px;padding-top:16px;border-top:1px solid #F0F2F0}
.drawer-footer .btn-action{flex:1;padding:10px;text-align:center;font-size:13px}

/* ── Toast ── */
#toast{position:fixed;bottom:24px;right:24px;background:#1A1A1A;color:#fff;padding:11px 18px;border-radius:8px;font-size:13px;display:none;z-index:999;max-width:320px;line-height:1.4;box-shadow:0 4px 20px rgba(0,0,0,.2)}
#toast.ok{background:#1B7A4E}
#toast.err{background:var(--red)}

/* ── Progress bar (loading) ── */
.progress-loading{height:3px;background:rgba(27,122,78,.15);overflow:hidden;border-radius:2px}
.indeterminate{height:100%;background:var(--brand);animation:indeterminate 1.4s infinite}
@keyframes indeterminate{0%{transform:translateX(-100%);width:50%}100%{transform:translateX(200%);width:50%}}

/* ── Overlay mobile ── */
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:199}

/* ── Responsive ── */
@media(max-width:768px){
  #sidebar{transform:translateX(-100%)}
  #sidebar.open{transform:translateX(0)}
  .overlay.show{display:block}
  #wrapper{margin-left:0}
  .topbar-hamburger{display:flex}
  .stats-row{grid-template-columns:repeat(2,1fr)}
  .pattern-summary-grid{grid-template-columns:repeat(2,1fr)}
  .patient-actions{flex-direction:column}
}
</style>
</head>
<body>

<!-- ── LOGIN ── -->
<div class="login-wrap" id="vLogin">
  <div id="fLogin" class="login-card">
    <div class="login-logo">NutriDeby</div>
    <div class="login-sub">Painel Clínico — Acesso exclusivo para profissionais</div>
    <div class="field-group"><label class="field-label" for="lEmail">E-mail profissional</label><input class="field-input" type="email" id="lEmail" placeholder="dra@clinica.com.br" autocomplete="email"/></div>
    <div class="field-group"><label class="field-label" for="lPass">Senha</label><input class="field-input" type="password" id="lPass" placeholder="••••••••" autocomplete="current-password"/></div>
    <button class="btn-login" id="btnLogin" onclick="doLogin()">Entrar</button>
    <button class="btn-link-sm" onclick="showForgot()">Esqueci minha senha</button>
    <div class="err-text" id="lErr"></div>
  </div>

  <div id="fForgot" class="login-card" style="display:none">
    <div class="login-logo">NutriDeby</div>
    <div class="login-sub">Vamos enviar um link de redefinição para o seu e-mail.</div>
    <div class="field-group"><label class="field-label" for="fEmail">E-mail</label><input class="field-input" type="email" id="fEmail" placeholder="dra@clinica.com.br"/></div>
    <button class="btn-login" onclick="doForgot()">Enviar link</button>
    <button class="btn-link-sm" onclick="showLogin()">Voltar ao login</button>
    <div id="fMsg" style="font-size:12px;margin-top:8px"></div>
  </div>

  <div id="fSetPass" class="login-card" style="display:none">
    <div class="login-logo">NutriDeby</div>
    <div class="login-sub" id="spSub">Crie sua senha de acesso.</div>
    <div class="field-group"><label class="field-label" for="spA">Nova senha (mín. 8 caracteres)</label><input class="field-input" type="password" id="spA" placeholder="••••••••"/></div>
    <div class="field-group"><label class="field-label" for="spB">Confirmar senha</label><input class="field-input" type="password" id="spB" placeholder="••••••••"/></div>
    <button class="btn-login" onclick="doSetPass()">Salvar senha</button>
    <div class="err-text" id="spErr"></div>
  </div>
</div>

<!-- ── PAINEL PRINCIPAL ── -->
<div id="vMain" style="display:none">

  <div class="overlay" id="overlay" onclick="closeSidebar()"></div>

  <!-- SIDEBAR -->
  <nav id="sidebar">
    <div class="sidebar-brand">
      <div class="sidebar-brand-name">NutriDeby</div>
      <div class="sidebar-brand-tag">Painel Clínico</div>
    </div>

    <div class="sidebar-user">
      <div class="sidebar-avatar" id="sAvatar"></div>
      <div>
        <div class="sidebar-user-name" id="sName"></div>
        <div class="sidebar-user-role">Nutricionista</div>
      </div>
    </div>

    <ul class="sidebar-nav" id="sidebarNav">
      <li class="sidebar-item">
        <a href="#" data-view="atencao" onclick="showView('atencao',event)" class="active">
          <i class="fa-solid fa-house"></i>
          <span>Início</span>
          <span class="nav-badge" id="badgeAtencao" style="display:none"></span>
        </a>
      </li>
      <li class="sidebar-item">
        <a href="#" data-view="todos" onclick="showView('todos',event)">
          <i class="fa-solid fa-user-group"></i>
          <span>Pacientes</span>
        </a>
      </li>
      <li class="sidebar-divider"></li>
      <li class="sidebar-subtitle">Clínico</li>
      <li class="sidebar-item">
        <a href="#" data-view="padroes" onclick="showView('padroes',event)">
          <i class="fa-solid fa-chart-line"></i>
          <span>Padrões</span>
        </a>
      </li>
      <li class="sidebar-item">
        <a href="#" data-view="docs" onclick="showView('docs',event)">
          <i class="fa-solid fa-file-signature"></i>
          <span>Documentos</span>
        </a>
      </li>
      <li class="sidebar-divider"></li>
      <li class="sidebar-item">
        <button onclick="doLogout()">
          <i class="fa-solid fa-right-from-bracket"></i>
          <span>Sair</span>
        </button>
      </li>
    </ul>

    <div class="sidebar-footer">
      <div class="sidebar-footer-text">NutriDeby v2.0 · Painel Clínico</div>
    </div>
  </nav>

  <!-- WRAPPER -->
  <div id="wrapper">

    <!-- TOPBAR -->
    <nav class="topbar">
      <button class="topbar-hamburger" onclick="toggleSidebar()">
        <span></span><span></span><span></span>
      </button>
      <span class="topbar-logo">NutriDeby</span>
      <span class="topbar-sep"></span>
      <span class="topbar-page" id="topbarPage">Painel Clínico</span>
      <div class="topbar-right">
        <div class="topbar-nutri">Bem-vinda, <strong id="tNome"></strong></div>
        <div class="topbar-notif">
          <button class="topbar-notif-btn" id="notifBtn" title="Alertas">
            <i class="fa-solid fa-bell"></i>
            <span class="notif-dot" id="notifDot" style="display:none"></span>
          </button>
        </div>
      </div>
    </nav>

    <!-- CONTENT -->
    <div class="content">

      <!-- Indicador de carregamento -->
      <div id="loadingBar" style="display:none;margin-bottom:16px">
        <div class="progress-loading"><div class="indeterminate"></div></div>
      </div>

      <!-- Vista: Início / Atenção -->
      <div id="viewAtencao">
        <div class="content-header">
          <div class="content-title" id="ctxTitle">Carregando...</div>
          <div class="content-sub" id="ctxSub"></div>
        </div>

        <!-- Stats row -->
        <div class="stats-row">
          <div class="stat-card">
            <div class="stat-value" id="mTotal">—</div>
            <div class="stat-label">Pacientes ativos</div>
          </div>
          <div class="stat-card clickable" onclick="showView('atencao',null,'filtro7')">
            <div class="stat-value amber" id="mInativos">—</div>
            <div class="stat-label">Inativos 7+ dias</div>
          </div>
          <div class="stat-card clickable" onclick="showView('padroes',null)">
            <div class="stat-value" id="mPadroes">—</div>
            <div class="stat-label">Padrões detectados</div>
          </div>
          <div class="stat-card clickable" onclick="showView('docs',null)">
            <div class="stat-value" id="mDocs">—</div>
            <div class="stat-label">Prontuários esta semana</div>
          </div>
        </div>

        <div class="widget">
          <div class="widget-header">
            <div class="widget-icon red"><i class="fa-solid fa-triangle-exclamation"></i></div>
            <div class="widget-title">Precisam de atenção agora</div>
          </div>
          <div class="widget-body" id="listAtencao">
            <div class="empty-state">
              <div class="empty-icon"><i class="fa-solid fa-spinner fa-spin"></i></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Vista: Todos os pacientes -->
      <div id="viewTodos" style="display:none">
        <div class="content-header">
          <div class="content-title">Todos os pacientes</div>
          <div class="content-sub" id="todosSub"></div>
        </div>
        <div class="widget">
          <div class="widget-header">
            <div class="widget-icon"><i class="fa-solid fa-users"></i></div>
            <div class="widget-title">Lista completa</div>
          </div>
          <div class="widget-body" id="listTodos">
            <div class="empty-state">
              <div class="empty-icon"><i class="fa-solid fa-spinner fa-spin"></i></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Vista: Padrões -->
      <div id="viewPadroes" style="display:none">
        <div class="content-header">
          <div class="content-title">Padrões comportamentais</div>
          <div class="content-sub">Comportamentos alimentares detectados pelo sistema</div>
        </div>
        <div class="pattern-summary-grid" id="patternSummary"></div>
        <div class="filter-bar" id="patternFilters">
          <button class="filter-pill active" data-fase="todos" onclick="filterPadroes('todos')">Todos</button>
          <button class="filter-pill" data-fase="ESCAPE" onclick="filterPadroes('ESCAPE')"><span class="pattern-dot dot-escape"></span>Escape alimentar</button>
          <button class="filter-pill" data-fase="CONFRONTO" onclick="filterPadroes('CONFRONTO')"><span class="pattern-dot dot-confronto"></span>Confronto</button>
          <button class="filter-pill" data-fase="RETORNO" onclick="filterPadroes('RETORNO')"><span class="pattern-dot dot-retorno"></span>Retorno ao padrao</button>
          <button class="filter-pill" data-fase="CULPA" onclick="filterPadroes('CULPA')"><span class="pattern-dot dot-culpa"></span>Culpa emocional</button>
        </div>
        <div class="widget">
          <div class="widget-body" id="listPadroes"></div>
        </div>
      </div>

      <!-- Vista: Documentos -->
      <div id="viewDocs" style="display:none">
        <div class="content-header">
          <div class="content-title">Documentos</div>
          <div class="content-sub">Prontuarios e assinaturas</div>
        </div>

        <div class="widget" style="margin-bottom:20px">
          <div class="widget-header">
            <div class="widget-icon amber"><i class="fa-solid fa-pen-to-square"></i></div>
            <div class="widget-title">Aguardando assinatura</div>
          </div>
          <div class="widget-body" id="docsPendentes">
            <div class="empty-state" style="padding:32px"><div class="empty-sub">Carregando...</div></div>
          </div>
        </div>

        <div class="widget">
          <div class="widget-header">
            <div class="widget-icon"><i class="fa-solid fa-file-lines"></i></div>
            <div class="widget-title">Historico de prontuarios</div>
          </div>
          <div class="widget-body" id="docsHistorico">
            <div class="empty-state" style="padding:32px"><div class="empty-sub">Carregando...</div></div>
          </div>
        </div>
      </div>

    </div><!-- /.content -->
  </div><!-- /#wrapper -->
</div><!-- /#vMain -->

<!-- JITSI MODAL -->
<div class="jitsi-bg" id="modalJitsi">
  <div class="jitsi-bar">
    <div class="jitsi-title" id="jTitle">Consulta ao vivo</div>
    <button class="jitsi-close" onclick="closeJitsi()">&#xD7;</button>
  </div>
  <iframe class="jitsi-frame" id="jFrame" src="" allow="camera;microphone;fullscreen;display-capture" allowfullscreen></iframe>
</div>

<!-- DRAWER (patient detail — like Dietbox drawer) -->
<div class="drawer-bg" id="drawerBg" onclick="closeDrawer(event)">
  <div class="drawer">
    <div class="drawer-header">
      <div>
        <div class="drawer-name" id="dName"></div>
        <div class="drawer-sub" id="dSub"></div>
      </div>
      <button class="drawer-close" onclick="closeDrawerBtn()">&#xD7;</button>
    </div>
    <div id="dBody"></div>
    <div class="drawer-footer">
      <button class="btn-action btn-action-primary" id="dBtnChamar" style="flex:1">
        <i class="fa-solid fa-video"></i> Iniciar consulta
      </button>
      <button class="btn-action btn-action-secondary" id="dBtnMsg" style="flex:1">
        <i class="fa-brands fa-whatsapp"></i> Mensagem
      </button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
'use strict';
var _tok=localStorage.getItem('nt');
var _me=null;
var _grid=[];
var _records=[];
var _pending=[];
var _currentView='atencao';
try{_me=JSON.parse(localStorage.getItem('nm')||'null');}catch(e){}

var _qp=new URLSearchParams(location.search);
var _act=_qp.get('action'),_tkn=_qp.get('token');

if(_act==='invite'&&_tkn) setPassMode('Bem-vinda! Crie sua senha para acessar o painel.','invite');
else if(_act==='reset'&&_tkn) setPassMode('Digite sua nova senha.','reset');
else if(_tok&&_me) showMain();

/* ── Sidebar / mobile ── */
function toggleSidebar(){
  var s=$('sidebar'),o=$('overlay');
  s.classList.toggle('open');
  o.classList.toggle('show');
}
function closeSidebar(){
  $('sidebar').classList.remove('open');
  $('overlay').classList.remove('show');
}

/* ── Auth UI ── */
function showLogin(){hide('fForgot');hide('fSetPass');show('fLogin');show('vLogin');hide('vMain');}
function showForgot(){hide('fLogin');hide('fSetPass');show('fForgot');}
function setPassMode(txt,mode){
  $('spSub').textContent=txt;
  hide('fLogin');hide('fForgot');show('fSetPass');
  show('vLogin');hide('vMain');
  document.body.dataset.spMode=mode;
}

async function doLogin(){
  var btn=$('btnLogin');
  btn.disabled=true;btn.textContent='Entrando...';$('lErr').textContent='';
  try{
    var r=await post('/api/nutri/login',{email:$v('lEmail'),password:$v('lPass')});
    _tok=r.access_token;_me=r.nutricionista;
    localStorage.setItem('nt',_tok);localStorage.setItem('nm',JSON.stringify(_me));
    showMain();
  }catch(e){$('lErr').textContent=e.message;}
  btn.disabled=false;btn.textContent='Entrar';
}

async function doForgot(){
  var el=$('fMsg');el.textContent='';
  try{
    var r=await post('/api/nutri/forgot-password',{email:$v('fEmail')});
    el.className='ok-text';el.textContent='Link enviado! Verifique seu e-mail.';
  }catch(e){el.className='err-text';el.textContent=e.message;}
}

async function doSetPass(){
  var a=$v('spA'),b=$v('spB');
  if(a!==b){$('spErr').textContent='As senhas nao coincidem';return;}
  if(a.length<8){$('spErr').textContent='Minimo 8 caracteres';return;}
  var mode=document.body.dataset.spMode;
  var ep=mode==='invite'?'/api/nutri/accept-invite':'/api/nutri/reset-password';
  var body=mode==='invite'?{token:_tkn,password:a}:{token:_tkn,new_password:a};
  try{
    var r=await post(ep,body);toast(r.message,'ok');
    setTimeout(function(){history.replaceState({},'','/painel');showLogin();},2000);
  }catch(e){$('spErr').textContent=e.message;}
}

function showMain(){
  hide('vLogin');show('vMain');
  var firstName=(_me.name||'').split(' ')[0];
  $('sName').textContent=_me.name;
  $('tNome').textContent=firstName;
  $('sAvatar').textContent=firstName.charAt(0).toUpperCase();
  carregar();
}
function doLogout(){localStorage.removeItem('nt');localStorage.removeItem('nm');location.reload();}

/* ── Data ── */
function showLoading(){show('loadingBar');}
function hideLoading(){hide('loadingBar');}

async function carregar(){
  showLoading();
  try{
    var res=await Promise.all([authGet('/api/nutri/grid-padroes'),authGet('/api/nutri/records'),authGet('/api/nutri/pending')]);
    _grid=res[0].pacientes||[];
    _records=res[1].records||[];
    _pending=res[2].records||[];
    updateStats(res[0]);
    renderAtencao();
    renderPatternSummary();
  }catch(e){if(e.status===401)doLogout();}
  finally{hideLoading();}
}

function updateStats(g){
  var inat7=_grid.filter(function(p){return diasSem(p)>=7;}).length;
  var inat14=_grid.filter(function(p){return diasSem(p)>=14;}).length;
  var semana=new Date(Date.now()-7*86400000).toISOString();
  var docs7=_records.filter(function(r){return r.created_at&&r.created_at>semana;}).length;

  $('mTotal').textContent=g.total||0;
  $('mInativos').textContent=inat7;
  $('mPadroes').textContent=g.com_padrao||0;
  $('mDocs').textContent=docs7;

  var h=new Date().getHours();
  var saud=h<12?'Bom dia':h<18?'Boa tarde':'Boa noite';
  var nome=(_me.name||'').split(' ')[0];

  var urgentes=_grid.filter(function(p){return diasSem(p)>=7;});
  var n=urgentes.length;
  $('ctxTitle').textContent=n>0?(n===1?'1 paciente precisa de voce hoje.':n+' pacientes precisam de voce hoje.'):'Tudo em ordem por enquanto.';
  $('ctxSub').textContent=saud+', '+nome+'.';

  // badge sidebar
  if(inat14>0){
    var b=$('badgeAtencao');b.textContent=inat14;show('badgeAtencao');
    show('notifDot');
  }

  $('todosSub').textContent=(_grid.length||0)+' pacientes cadastrados';
}

/* ── Navigation ── */
function showView(view,e,extra){
  if(e) e.preventDefault();
  _currentView=view;

  // Update sidebar active
  document.querySelectorAll('#sidebarNav a[data-view]').forEach(function(a){
    a.classList.toggle('active',a.dataset.view===view);
  });

  // Page titles for topbar
  var titles={atencao:'Inicio',todos:'Pacientes',padroes:'Padroes Comportamentais',docs:'Documentos'};
  $('topbarPage').textContent=titles[view]||'';

  // Show/hide content panels
  ['atencao','todos','padroes','docs'].forEach(function(v){
    var el=$('view'+cap(v));
    if(el) el.style.display=(v===view)?'':'none';
  });

  if(view==='todos') renderTodos();
  if(view==='padroes') renderPadroes();
  if(view==='docs') renderDocs();

  closeSidebar();
}

/* ── Patient rendering ── */
function renderAtencao(){
  var lista=_grid
    .filter(function(p){return diasSem(p)>=7||(p.padrao&&p.padrao.fase==='CONFRONTO');})
    .sort(function(a,b){return diasSem(b)-diasSem(a);});
  var el=$('listAtencao');
  if(!lista.length){
    el.innerHTML='<div class="empty-state"><div class="empty-icon"><i class="fa-solid fa-circle-check" style="color:var(--safe)"></i></div><div class="empty-title">Tudo em ordem</div><div class="empty-sub">Nenhuma paciente precisa de atencao agora.</div></div>';
    return;
  }
  el.innerHTML='<div class="patient-list">'+lista.map(function(p){return patientRow(p);}).join('')+'</div>';
}

function renderTodos(){
  var el=$('listTodos');
  if(!_grid.length){
    el.innerHTML='<div class="empty-state"><div class="empty-title">Nenhuma paciente cadastrada</div></div>';
    return;
  }
  var sorted=_grid.slice().sort(function(a,b){return diasSem(b)-diasSem(a);});
  el.innerHTML='<div class="patient-list">'+sorted.map(function(p){return patientRow(p);}).join('')+'</div>';
}

function renderPatternSummary(){
  var resumo={ESCAPE:0,CONFRONTO:0,RETORNO:0,CULPA:0};
  _grid.filter(function(p){return p.padrao;}).forEach(function(p){
    if(resumo[p.padrao.fase]!==undefined)resumo[p.padrao.fase]++;
  });
  var phases=[
    {fase:'ESCAPE',label:'Escape alimentar',dot:'dot-escape'},
    {fase:'CONFRONTO',label:'Confronto',dot:'dot-confronto'},
    {fase:'RETORNO',label:'Retorno ao padrao',dot:'dot-retorno'},
    {fase:'CULPA',label:'Culpa emocional',dot:'dot-culpa'},
  ];
  $('patternSummary').innerHTML=phases.map(function(c){
    return '<div class="pattern-sum" onclick="filterPadroes(\''+c.fase+'\')">'
      +'<span class="pattern-dot '+c.dot+'"></span>'
      +'<div><div class="pattern-sum-num">'+(resumo[c.fase]||0)+'</div><div class="pattern-sum-lbl">'+c.label+'</div></div>'
      +'</div>';
  }).join('');
}

function renderPadroes(){
  renderPatternList('todos');
}

var _padFiltro='todos';
function filterPadroes(fase){
  _padFiltro=fase;
  document.querySelectorAll('#patternFilters .filter-pill').forEach(function(b){
    b.classList.toggle('active',b.dataset.fase===fase);
  });
  renderPatternList(fase);
}

function renderPatternList(filtro){
  var rows=_grid.filter(function(p){
    return p.padrao&&(filtro==='todos'||p.padrao.fase===filtro);
  });
  var el=$('listPadroes');
  if(!rows.length){
    el.innerHTML='<div class="empty-state"><div class="empty-title">Nenhum padrao detectado nesta categoria</div></div>';
    return;
  }
  el.innerHTML='<div class="patient-list">'+rows.map(function(p){return patientRow(p,true);}).join('')+'</div>';
}

function patientRow(p,showPhase){
  var di=diasSem(p);
  var accentColor=di>=14?'#C0392B':di>=7?'#D4850A':(p.padrao&&p.padrao.fase==='CONFRONTO'?'#C0392B':'#1B7A4E');
  var avatarClass=di>=14?'red':di>=7?'amber':'';
  var inicial=titleCase(p.nome||'?').charAt(0);
  var dname=esc(titleCase(p.nome||'Paciente'));
  var desc=descricao(p,di);
  var ph=esc(p.phone||''),nm=escq(titleCase(p.nome||'')),pid=esc(p.id||'');

  var phaseBadge='';
  if(showPhase&&p.padrao){
    var phaseMap={ESCAPE:'phase-escape',CONFRONTO:'phase-confronto',RETORNO:'phase-retorno',CULPA:'phase-culpa'};
    var phaseLabel={ESCAPE:'Escape alimentar',CONFRONTO:'Confronto',RETORNO:'Retorno ao padrao',CULPA:'Culpa emocional'};
    var dotMap={ESCAPE:'dot-escape',CONFRONTO:'dot-confronto',RETORNO:'dot-retorno',CULPA:'dot-culpa'};
    phaseBadge='<span class="phase-badge '+phaseMap[p.padrao.fase]+'" style="margin-top:4px">'
      +'<span class="pattern-dot '+dotMap[p.padrao.fase]+'"></span>'
      +esc(phaseLabel[p.padrao.fase]||p.padrao.fase)+'</span>';
  }

  var gatilhos='';
  if(p.padrao&&(p.padrao.gatilhos||[]).length){
    gatilhos=(p.padrao.gatilhos||[]).slice(0,4).map(function(g){return '<span class="trigger-tag">'+esc(g)+'</span>';}).join('');
  }

  return '<div class="patient-item">'
    +'<div class="patient-item-accent" style="background:'+accentColor+'"></div>'
    +'<div class="patient-avatar '+avatarClass+'">'+esc(inicial)+'</div>'
    +'<div class="patient-info" onclick="openDrawer(\''+pid+'\')" style="cursor:pointer;flex:1;min-width:0">'
    +'<div class="patient-name">'+dname+'</div>'
    +'<div class="patient-desc">'+desc+'</div>'
    +(phaseBadge?'<div style="margin-top:5px">'+phaseBadge+'</div>':'')
    +(gatilhos?'<div style="margin-top:4px">'+gatilhos+'</div>':'')
    +'</div>'
    +'<div class="patient-actions">'
    +(p.phone?'<button class="btn-action btn-action-primary" data-id="'+pid+'" data-name="'+nm+'" data-phone="'+ph+'" onclick="doConsult(this.dataset.id,this.dataset.name,this.dataset.phone)"><i class="fa-solid fa-video"></i> Chamar</button>':'')
    +(p.phone?'<button class="btn-action btn-action-secondary" data-phone="'+ph+'" onclick="openWA(this.dataset.phone)"><i class="fa-brands fa-whatsapp"></i></button>':'')
    +'<button class="btn-action btn-action-ghost" data-id="'+pid+'" onclick="openDrawer(this.dataset.id)"><i class="fa-solid fa-folder-open"></i></button>'
    +'</div>'
    +'</div>';
}

function descricao(p,di){
  if(di>=14)return 'Sem registro ha '+di+' dias — pode estar precisando de apoio';
  if(di>=7)return 'Nao aparece ha '+di+' dias';
  if(p.padrao){
    var fase=p.padrao.fase;
    var gat=(p.padrao.gatilhos||[]).slice(0,3).join(', ');
    var d='';
    if(fase==='CONFRONTO')d='Em conflito com a dieta';
    else if(fase==='ESCAPE')d='Evitando os compromissos';
    else if(fase==='RETORNO')d='Voltando ao ritmo';
    else if(fase==='CULPA')d='Sentindo culpa pos refeicao';
    return d+(gat?' — '+gat:'');
  }
  if((p.streak||0)>=7)return 'Indo muito bem — '+p.streak+' dias seguidos';
  return di===0?'Registrou hoje':'Ultimo registro ha '+(di===1?'1 dia':di+' dias');
}

function renderDocs(){
  // Pendentes
  var pEl=$('docsPendentes');
  if(!_pending.length){
    pEl.innerHTML='<div class="empty-state" style="padding:28px"><div class="empty-sub">Nenhum prontuario pendente.</div></div>';
  }else{
    var ph='<table class="doc-table"><thead><tr><th>Paciente</th><th>Data</th><th>Status D4Sign</th><th>Acao</th></tr></thead><tbody>';
    _pending.forEach(function(r){
      var dt=r.created_at?new Date(r.created_at).toLocaleDateString('pt-BR'):'—';
      var canSign=r.can_sign&&r.d4sign_status==='NONE';
      ph+='<tr>'
        +'<td><strong>'+esc(titleCase(r.patient_name))+'</strong></td>'
        +'<td style="color:var(--muted)">'+dt+'</td>'
        +'<td>'+d4badge(r.d4sign_status)+'</td>'
        +'<td>'
        +'<button class="btn-sign" '+(canSign?'':'disabled')+' onclick="assinar('+r.id+',this)">'+(canSign?'Enviar para assinatura':'Aguardando')+'</button>'
        +' <button class="btn-action btn-action-secondary" style="font-size:11px;padding:5px 10px;margin-left:4px" data-id="'+esc(r.patient_id)+'" data-name="'+escq(titleCase(r.patient_name))+'" data-phone="'+esc(r.patient_phone||'')+'" onclick="doConsult(this.dataset.id,this.dataset.name,this.dataset.phone)"><i class="fa-solid fa-video"></i></button>'
        +'</td></tr>';
    });
    ph+='</tbody></table>';
    pEl.innerHTML=ph;
  }

  // Historico
  var hEl=$('docsHistorico');
  if(!_records.length){
    hEl.innerHTML='<div class="empty-state" style="padding:28px"><div class="empty-sub">Nenhum registro.</div></div>';
  }else{
    var hh='<table class="doc-table"><thead><tr><th>Paciente</th><th>Nutricionista</th><th>Data</th><th>Status</th><th>PDF</th></tr></thead><tbody>';
    _records.slice(0,60).forEach(function(r){
      var dt=r.created_at?new Date(r.created_at).toLocaleDateString('pt-BR'):'—';
      var sb=r.status==='ASSINADO'?'<span class="status-badge status-ok">Assinado</span>':'<span class="status-badge status-pend">Pendente</span>';
      var pdf=r.d4sign_signed_pdf_url?'<a href="'+r.d4sign_signed_pdf_url+'" target="_blank" style="color:var(--brand);font-size:12px">Download</a>':r.pdf_url?'<a href="'+r.pdf_url+'" target="_blank" style="color:var(--brand);font-size:12px">PDF</a>':'—';
      hh+='<tr><td><strong>'+esc(titleCase(r.patient_name))+'</strong></td><td style="color:var(--muted)">'+esc(r.nutricionista||'—')+'</td><td style="color:var(--muted)">'+dt+'</td><td>'+sb+'</td><td>'+pdf+'</td></tr>';
    });
    hh+='</tbody></table>';
    hEl.innerHTML=hh;
  }
}

/* ── Actions ── */
async function doConsult(pid,nome,phone){
  try{
    var d=await authPost('/api/nutri/start-consultation',{patient_id:pid,patient_name:titleCase(nome),patient_phone:phone||''});
    if(phone)toast('Mensagem enviada para '+titleCase(nome),'ok');
    openJitsi(d.room_url,titleCase(nome));
  }catch(e){toast('Nao foi possivel iniciar a chamada: '+e.message,'err');}
}

function openJitsi(url,nome){
  $('jTitle').textContent='Consulta ao vivo — '+nome;
  $('jFrame').src=url;
  $('modalJitsi').classList.add('open');
}
function closeJitsi(){$('jFrame').src='';$('modalJitsi').classList.remove('open');}

function openWA(phone){
  if(!phone){toast('Paciente sem telefone cadastrado','err');return;}
  window.open('https://wa.me/'+phone.replace(/\\D/g,''),'_blank');
}

function openDrawer(pid){
  var p=_grid.find(function(x){return x.id===pid;});
  if(!p)return;
  var di=diasSem(p);
  $('dName').textContent=titleCase(p.nome);
  $('dSub').textContent=descricao(p,di);

  var html='';
  if(p.streak>0){
    html+='<div class="drawer-section"><div class="drawer-label">Engajamento atual</div>'
      +'<div class="drawer-value">'+p.streak+' dia'+(p.streak===1?'':'s')+' seguidos de registro</div></div>';
  }
  if(p.padrao){
    var phaseLabel={ESCAPE:'Escape alimentar',CONFRONTO:'Confronto',RETORNO:'Retorno ao padrao',CULPA:'Culpa emocional'};
    var lb=phaseLabel[p.padrao.fase]||p.padrao.fase;
    var gat=p.padrao.gatilhos||[];
    var da=p.padrao.dias_atras;
    var detTxt=da===0?'hoje':(da===1?'ha 1 dia':(da!=null?'ha '+da+' dias':''));
    html+='<div class="drawer-section"><div class="drawer-label">Padrao comportamental</div>'
      +'<div class="drawer-value">'+esc(lb)+' — Ciclo '+(p.padrao.ciclo||1)+'</div>'
      +(gat.length?'<div style="margin-top:8px">'+gat.map(function(g){return '<span class="trigger-tag">'+esc(g)+'</span>';}).join('')+'</div>':'')
      +(detTxt?'<div style="font-size:12px;color:var(--muted);margin-top:6px">Detectado '+detTxt+'</div>':'')
      +'</div>';
    if(p.padrao.acao_recomendada){
      html+='<div class="drawer-section"><div class="drawer-label">Recomendacao clinica</div>'
        +'<div class="drawer-value">'+esc(p.padrao.acao_recomendada)+'</div></div>';
    }
  }
  if(p.phone){
    html+='<div class="drawer-section"><div class="drawer-label">Telefone</div><div class="drawer-value">'+esc(p.phone)+'</div></div>';
  }
  if(!html){html='<div class="drawer-section" style="color:var(--muted);font-size:14px">Nenhuma informacao clinica adicional disponivel.</div>';}
  $('dBody').innerHTML=html;

  $('dBtnChamar').style.display=p.phone?'':'none';
  $('dBtnMsg').style.display=p.phone?'':'none';
  $('dBtnChamar').onclick=function(){closeDrawerBtn();doConsult(p.id,p.nome,p.phone||'');};
  $('dBtnMsg').onclick=function(){closeDrawerBtn();openWA(p.phone||'');};
  $('drawerBg').classList.add('open');
}
function closeDrawerBtn(){$('drawerBg').classList.remove('open');}
function closeDrawer(e){if(e.target===$('drawerBg'))closeDrawerBtn();}

async function assinar(id,btn){
  btn.disabled=true;btn.textContent='Enviando...';
  try{
    await authPost('/api/nutri/initiate-signing/'+id,{});
    toast('Documento enviado para assinatura','ok');
    var res=await Promise.all([authGet('/api/nutri/records'),authGet('/api/nutri/pending')]);
    _records=res[0].records||[];_pending=res[1].records||[];
    renderDocs();
  }catch(e){toast('Erro: '+e.message,'err');btn.disabled=false;btn.textContent='Enviar para assinatura';}
}

/* ── Helpers ── */
function diasSem(p){
  if(!p.ultimo_registro)return 999;
  return Math.floor((Date.now()-new Date(p.ultimo_registro).getTime())/86400000);
}
function titleCase(s){
  if(!s)return'';
  return s.toLowerCase().replace(/\\b\\w/g,function(c){return c.toUpperCase();});
}
function d4badge(s){
  if(!s||s==='NONE')return'<span style="color:var(--muted)">—</span>';
  if(s==='PENDING_SIGNATURE')return'<span class="status-badge status-wait">Aguardando</span>';
  if(s==='SIGNED')return'<span class="status-badge status-ok">Assinado</span>';
  return'<span class="status-badge">'+esc(s)+'</span>';
}
function cap(s){return s.charAt(0).toUpperCase()+s.slice(1);}
function $(id){return document.getElementById(id);}
function $v(id){return $(id).value.trim();}
function show(id){$(id).style.display='';}
function hide(id){$(id).style.display='none';}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escq(s){return String(s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

async function post(url,body){
  var r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  var d=await r.json();
  if(!r.ok){var e=new Error(d.detail||'Erro');e.status=r.status;throw e;}
  return d;
}
async function authGet(url){
  var r=await fetch(url,{headers:{Authorization:'Bearer '+_tok}});
  var d=await r.json();
  if(!r.ok){var e=new Error(d.detail||'Erro');e.status=r.status;throw e;}
  return d;
}
async function authPost(url,body){
  var r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+_tok},body:JSON.stringify(body)});
  var d=await r.json();
  if(!r.ok){var e=new Error(d.detail||'Erro');e.status=r.status;throw e;}
  return d;
}

var _tt=null;
function toast(msg,type){
  var t=$('toast');t.textContent=msg;t.className=type||'';
  t.style.display='block';clearTimeout(_tt);
  _tt=setTimeout(function(){t.style.display='none';},4500);
}

document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){closeJitsi();closeDrawerBtn();}
  if(e.key==='Enter'){
    if($('fLogin')&&$('fLogin').style.display!=='none')doLogin();
    if($('fForgot')&&$('fForgot').style.display!=='none')doForgot();
    if($('fSetPass')&&$('fSetPass').style.display!=='none')doSetPass();
  }
});
</script>
</body>
</html>
"""
