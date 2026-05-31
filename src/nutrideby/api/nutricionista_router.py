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
                       cr.extracted_biochemistry
                FROM clinical_records cr
                LEFT JOIN patients p ON p.id = cr.patient_id
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
                       pn.name AS nutricionista_name
                FROM clinical_records cr
                LEFT JOIN patients p ON p.id = cr.patient_id
                LEFT JOIN professional_nutricionistas pn ON pn.id = cr.nutricionista_id
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
                    pa.acao_prescrita
                FROM patients p
                LEFT JOIN LATERAL (
                    SELECT fase, ciclo_numero, degradacao_nivel,
                           alimentos_gatilho, data_deteccao, acao_prescrita
                    FROM padroes_alimentares
                    WHERE patient_id = p.id
                    ORDER BY data_deteccao DESC
                    LIMIT 1
                ) pa ON true
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
            "streak": r["current_streak"] or 0,
            "ultimo_registro": r["last_logged_date"].isoformat() if r.get("last_logged_date") else None,
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
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="alternate icon" href="/favicon.ico">
<title>NutriDeby — Painel</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f0fdf4;color:#1e293b;min-height:100vh}
header{background:#059669;color:#fff;padding:16px 24px;display:flex;align-items:center;gap:12px}
header h1{font-size:1.3rem;font-weight:700}
#hname{font-size:.85rem;opacity:.85;margin-left:auto}
#hrole{font-size:.75rem;background:rgba(255,255,255,.2);padding:2px 10px;border-radius:20px;margin-left:8px}
.wrap{display:flex;align-items:center;justify-content:center;min-height:90vh}
.card{background:#fff;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.08);padding:32px;width:100%;max-width:400px}
.card h2{font-size:1.1rem;color:#059669;margin-bottom:4px}
.card p.sub{font-size:.82rem;color:#94a3b8;margin-bottom:20px}
label{display:block;font-size:.78rem;color:#64748b;margin-bottom:4px;margin-top:12px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
input{width:100%;padding:10px 12px;border:1.5px solid #e2e8f0;border-radius:8px;font-size:.95rem;outline:none;transition:border .2s}
input:focus{border-color:#059669}
.btn{width:100%;margin-top:18px;padding:12px;background:#059669;color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;transition:background .2s}
.btn:hover{background:#047857}
.btn:disabled{background:#94a3b8;cursor:not-allowed}
.btn-sm{padding:6px 14px;border-radius:6px;border:none;cursor:pointer;font-size:.8rem;font-weight:600}
.btn-outline{background:#f1f5f9;color:#475569;padding:8px 16px;border-radius:8px;border:none;cursor:pointer;font-size:.85rem;font-weight:600}
.btn-outline:hover{background:#e2e8f0}
.err{color:#dc2626;font-size:.82rem;margin-top:8px}
.link{color:#059669;font-size:.82rem;cursor:pointer;background:none;border:none;text-decoration:underline;margin-top:10px;display:block;text-align:center}
#main{padding:24px;max-width:1040px;margin:0 auto}
.nutri-bar{background:#ecfdf5;border:1px solid #6ee7b7;border-radius:10px;padding:10px 16px;margin-bottom:18px;display:flex;align-items:center;gap:8px}
.nutri-bar strong{color:#065f46}
.tabs{display:flex;gap:8px;margin-bottom:16px}
.tab{padding:8px 18px;border-radius:8px;border:none;cursor:pointer;font-size:.85rem;font-weight:600;background:#e2e8f0;color:#475569}
.tab.active{background:#059669;color:#fff}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.06)}
th{background:#ecfdf5;color:#065f46;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;padding:10px 14px;text-align:left}
td{padding:10px 14px;border-top:1px solid #f1f5f9;font-size:.88rem;vertical-align:middle}
tr:hover td{background:#f8fffe}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.73rem;font-weight:700}
.b-pend{background:#fef9c3;color:#854d0e}
.b-sign{background:#dbeafe;color:#1e40af}
.b-ok{background:#dcfce7;color:#166534}
.flag-a{color:#dc2626;font-size:.75rem;font-weight:700}
.flag-b{color:#d97706;font-size:.75rem;font-weight:700}
.empty{text-align:center;padding:48px;color:#94a3b8;font-size:.95rem}
.grid-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.sum-card{border-radius:10px;padding:14px 16px;text-align:center;border:1px solid transparent;cursor:pointer;transition:transform .15s}
.sum-card:hover{transform:translateY(-2px)}
.sum-card .num{font-size:2rem;font-weight:800;line-height:1}
.sum-card .lbl{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-top:4px}
.sum-card .sub{font-size:.7rem;color:#64748b;margin-top:2px}
.sc-escape{background:#fffbeb;border-color:#fcd34d}.sc-escape .num{color:#d97706}
.sc-confronto{background:#fef2f2;border-color:#fca5a5}.sc-confronto .num{color:#dc2626}
.sc-retorno{background:#f5f3ff;border-color:#c4b5fd}.sc-retorno .num{color:#7c3aed}
.sc-culpa{background:#eef2ff;border-color:#a5b4fc}.sc-culpa .num{color:#4f46e5}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.pcard{background:#fff;border-radius:10px;border:1.5px solid #e2e8f0;padding:14px 14px 14px 18px;transition:box-shadow .15s;position:relative;overflow:hidden}
.pcard:hover{box-shadow:0 4px 16px rgba(0,0,0,.08)}
.pcard .fase-bar{position:absolute;top:0;left:0;width:4px;height:100%}
.pcard .pnome{font-weight:700;font-size:.92rem;color:#1e293b;margin-bottom:6px}
.pcard .pfase{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:.72rem;font-weight:700;margin-bottom:8px}
.pcard .pinfo{font-size:.78rem;color:#64748b;line-height:1.6}
.pcard .pacao{margin-top:8px;padding:6px 8px;border-radius:6px;font-size:.75rem;font-weight:600;background:#f8fafc;color:#475569;border-left:3px solid #e2e8f0}
.pcard .pciclo{font-size:.7rem;color:#94a3b8;margin-top:6px}
.fase-escape  .fase-bar{background:#f59e0b}
.fase-confronto .fase-bar{background:#ef4444}
.fase-retorno .fase-bar{background:#8b5cf6}
.fase-culpa   .fase-bar{background:#6366f1}
.fase-sem     .fase-bar{background:#e2e8f0}
.pfase-escape{background:#fffbeb;color:#b45309}
.pfase-confronto{background:#fef2f2;color:#b91c1c}
.pfase-retorno{background:#f5f3ff;color:#6d28d9}
.pfase-culpa{background:#eef2ff;color:#4338ca}
.grid-filter{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;align-items:center}
.gf-btn{padding:5px 14px;border-radius:20px;border:1.5px solid #e2e8f0;background:#fff;font-size:.78rem;font-weight:600;cursor:pointer;color:#64748b;transition:all .15s}
.gf-todos.on{color:#059669;background:#ecfdf5;border-color:#059669}
.gf-escape.on{color:#d97706;background:#fffbeb;border-color:#fcd34d}
.gf-confronto.on{color:#dc2626;background:#fef2f2;border-color:#fca5a5}
.gf-retorno.on{color:#7c3aed;background:#f5f3ff;border-color:#c4b5fd}
.gf-culpa.on{color:#4f46e5;background:#eef2ff;border-color:#a5b4fc}
.empty-grid{text-align:center;padding:48px;color:#94a3b8;grid-column:1/-1}
.deg-dot{font-size:.65rem;letter-spacing:1px}

#toast{position:fixed;bottom:24px;right:24px;background:#1e293b;color:#fff;padding:12px 20px;border-radius:8px;font-size:.88rem;display:none;z-index:999;box-shadow:0 4px 16px rgba(0,0,0,.2)}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:100;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:12px;padding:28px;width:100%;max-width:360px;box-shadow:0 8px 32px rgba(0,0,0,.15)}
.modal h3{font-size:1rem;color:#1e293b;margin-bottom:16px}
.sec-title{font-size:1.05rem;font-weight:700;color:#065f46;margin-bottom:12px}
</style>
</head>
<body>

<header>
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
  <h1>NutriDeby</h1>
  <span id="hname"></span><span id="hrole"></span>
</header>

<!-- ── LOGIN ── -->
<div class="wrap" id="vLogin">
  <div class="card" id="formLogin">
    <h2>Entrar no Painel</h2>
    <p class="sub">Acesso exclusivo para nutricionistas</p>
    <label>E-mail profissional</label>
    <input type="email" id="lEmail" placeholder="dra@clinica.com.br" autocomplete="email"/>
    <label>Senha</label>
    <input type="password" id="lPass" placeholder="••••••••" autocomplete="current-password"/>
    <button class="btn" id="btnLogin" onclick="doLogin()">Entrar</button>
    <button class="link" onclick="showForgot()">Esqueci minha senha</button>
    <p class="err" id="lErr"></p>
  </div>

  <!-- Esqueci senha -->
  <div class="card" id="formForgot" style="display:none">
    <h2>Esqueci minha senha</h2>
    <p class="sub">Enviaremos um link de redefinição para seu e-mail</p>
    <label>E-mail profissional</label>
    <input type="email" id="fEmail" placeholder="dra@clinica.com.br"/>
    <button class="btn" onclick="doForgot()">Enviar link</button>
    <button class="link" onclick="showLogin()">← Voltar ao login</button>
    <p class="err" id="fMsg"></p>
  </div>

  <!-- Criar senha (convite ou reset) -->
  <div class="card" id="formSetPass" style="display:none">
    <h2 id="setPassTitle">Criar senha</h2>
    <p class="sub" id="setPassSub">Defina sua senha para acessar o painel</p>
    <label>Nova senha (mín. 8 caracteres)</label>
    <input type="password" id="spPass" placeholder="••••••••"/>
    <label>Confirmar senha</label>
    <input type="password" id="spPass2" placeholder="••••••••"/>
    <button class="btn" onclick="doSetPass()">Salvar senha</button>
    <p class="err" id="spErr"></p>
  </div>
</div>

<!-- ── PAINEL PRINCIPAL ── -->
<div id="main" style="display:none">
  <div class="nutri-bar">
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
    <span>Bem-vinda, <strong id="mName"></strong></span>
    <button class="btn-outline" style="margin-left:auto" onclick="doLogout()">Sair</button>
  </div>

  <div class="tabs">
    <button class="tab active" id="tabBtnPend" onclick="showTab('pend')">Pendentes</button>
    <button class="tab" id="tabBtnAll"  onclick="showTab('all')">Todos</button>
    <button class="tab" id="tabBtnPad" onclick="showTab('pad')">🧠 Padrões</button>
  </div>

  <div id="tabPend">
    <p class="sec-title">Prontuários aguardando assinatura</p>
    <div id="tblPend"></div>
  </div>
  <div id="tabAll" style="display:none">
    <p class="sec-title">Todos os prontuários</p>
    <div id="tblAll"></div>
  </div>

  <div id="tabPad" style="display:none">
    <p class="sec-title">Padrões Comportamentais — Visão Clínica</p>
    <div id="gridSummary" class="grid-summary"></div>
    <div class="grid-filter">
      <button class="gf-btn gf-todos on" onclick="filterGrid('todos')">Todos</button>
      <button class="gf-btn gf-escape" onclick="filterGrid('ESCAPE')">🌊 Escape</button>
      <button class="gf-btn gf-confronto" onclick="filterGrid('CONFRONTO')">⚡ Confronto</button>
      <button class="gf-btn gf-retorno" onclick="filterGrid('RETORNO')">🔄 Retorno</button>
      <button class="gf-btn gf-culpa" onclick="filterGrid('CULPA')">💙 Culpa</button>
    </div>
    <div id="gridPadroes" class="pgrid"></div>
  </div>
</div>

<div id="toast"></div>

<script>
let _tok = localStorage.getItem('nt'), _me = JSON.parse(localStorage.getItem('nm')||'null');
const p = new URLSearchParams(location.search);
const action = p.get('action'), token = p.get('token');

if (action === 'invite' && token) {
  showSetPass('Criar senha', 'Bem-vinda! Defina sua senha para acessar o painel.', 'invite');
} else if (action === 'reset' && token) {
  showSetPass('Redefinir senha', 'Digite sua nova senha abaixo.', 'reset');
} else if (_tok && _me) {
  showMain();
}

function showLogin() {
  hide('formForgot'); hide('formSetPass'); show('formLogin'); show('vLogin'); hide('main');
}
function showForgot() { hide('formLogin'); hide('formSetPass'); show('formForgot'); }
function showSetPass(title, sub, mode) {
  hide('formLogin'); hide('formForgot');
  $('setPassTitle').textContent = title;
  $('setPassSub').textContent = sub;
  show('vLogin'); show('formSetPass'); hide('formLogin'); hide('formForgot');
  document.body.dataset.spMode = mode;
}

async function doLogin() {
  const btn = $('btnLogin'); btn.disabled = true; btn.textContent = 'Entrando…';
  $('lErr').textContent = '';
  try {
    const r = await api('/api/nutri/login', {email:$v('lEmail'), password:$v('lPass')});
    _tok = r.access_token; _me = r.nutricionista;
    localStorage.setItem('nt', _tok); localStorage.setItem('nm', JSON.stringify(_me));
    showMain();
  } catch(e) { $('lErr').textContent = e.message; }
  btn.disabled=false; btn.textContent='Entrar';
}

async function doForgot() {
  $('fMsg').textContent='';
  try {
    const r = await api('/api/nutri/forgot-password', {email:$v('fEmail')});
    $('fMsg').style.color='#059669';
    $('fMsg').textContent = r.message;
  } catch(e) { $('fMsg').textContent = e.message; }
}

async function doSetPass() {
  const pw=$v('spPass'), pw2=$v('spPass2');
  if (pw !== pw2) { $('spErr').textContent='As senhas não coincidem'; return; }
  if (pw.length < 8) { $('spErr').textContent='Mínimo 8 caracteres'; return; }
  const mode = document.body.dataset.spMode;
  const endpoint = mode==='invite' ? '/api/nutri/accept-invite' : '/api/nutri/reset-password';
  const body = mode==='invite' ? {token, password:pw} : {token, new_password:pw};
  try {
    const r = await api(endpoint, body);
    toast('✓ ' + r.message);
    setTimeout(() => { history.replaceState({}, '', '/painel'); showLogin(); }, 1500);
  } catch(e) { $('spErr').textContent = e.message; }
}

function showMain() {
  hide('vLogin'); show('main');
  $('mName').textContent = _me.name;
  $('hname').textContent = _me.name;
  $('hrole').textContent = _me.role === 'admin' ? 'Admin' : _me.role === 'viewer' ? 'Visualizador' : 'Nutricionista';
  loadPend();
}

function doLogout() {
  localStorage.removeItem('nt'); localStorage.removeItem('nm'); location.reload();
}

function showTab(t) {
  ['Pend','All','Pad'].forEach(id => {
    $('tab'+id).style.display = t===id.toLowerCase() ? '' : 'none';
    $('tabBtn'+id).className = 'tab'+(t===id.toLowerCase()?' active':'');
  });
  if (t==='all') loadAll();
  if (t==='pad') loadGrid();
}

async function loadPend() {
  try {
    const d = await authGet('/api/nutri/pending');
    $('tblPend').innerHTML = renderPend(d.records, d.role);
  } catch(e) { if(e.status===401) doLogout(); }
}

async function loadAll() {
  try {
    const d = await authGet('/api/nutri/records');
    $('tblAll').innerHTML = renderAll(d.records);
  } catch(e) { if(e.status===401) doLogout(); }
}

function renderPend(rows, role) {
  if (!rows.length) return '<div class="empty">✓ Nenhum prontuário pendente</div>';
  const canSign = role !== 'viewer';
  let h = `<table><thead><tr><th>#</th><th>Paciente</th><th>Data</th><th>Marcadores alterados</th><th>D4Sign</th><th>Ação</th></tr></thead><tbody>`;
  for (const r of rows) {
    const dt = r.created_at ? new Date(r.created_at).toLocaleDateString('pt-BR') : '—';
    const flags = r.flags.map(f=>`<span class="flag-${f.type==='ALTO'?'a':'b'}">${f.marker} ${f.type==='ALTO'?'↑':'↓'}</span>`).join(' ') || '<span style="color:#94a3b8">—</span>';
    const d4 = d4b(r.d4sign_status);
    const ok = canSign && r.d4sign_status==='NONE';
    h += `<tr><td><b>#${r.id}</b></td><td>${esc(r.patient_name)}</td><td>${dt}</td>
      <td><small>${flags}</small></td><td>${d4}</td>
      <td><button class="btn-sm" style="background:${ok?'#059669':'#94a3b8'};color:#fff" ${ok?'':'disabled'} onclick="sign(${r.id},this)">
        ${ok?'📨 Assinar':'⏳ Aguardando'}</button></td></tr>`;
  }
  return h+'</tbody></table>';
}

function renderAll(rows) {
  if (!rows.length) return '<div class="empty">Sem registros</div>';
  let h = `<table><thead><tr><th>#</th><th>Paciente</th><th>Nutricionista</th><th>Data</th><th>Status</th><th>D4Sign</th><th>PDF</th></tr></thead><tbody>`;
  for (const r of rows) {
    const dt = r.created_at ? new Date(r.created_at).toLocaleDateString('pt-BR') : '—';
    const sb = r.status==='ASSINADO' ? '<span class="badge b-ok">Assinado</span>' : '<span class="badge b-pend">Pendente</span>';
    const pdf = r.d4sign_signed_pdf_url ? `<a href="${r.d4sign_signed_pdf_url}" target="_blank" style="color:#059669">D4Sign</a>`
              : r.pdf_url ? `<a href="${r.pdf_url}" target="_blank" style="color:#059669">PDF</a>` : '—';
    h += `<tr><td>#${r.id}</td><td>${esc(r.patient_name)}</td><td>${esc(r.nutricionista)}</td><td>${dt}</td><td>${sb}</td><td>${d4b(r.d4sign_status)}</td><td>${pdf}</td></tr>`;
  }
  return h+'</tbody></table>';
}

async function sign(id, btn) {
  btn.disabled=true; btn.textContent='⏳ Enviando…';
  try {
    await authPost('/api/nutri/initiate-signing/'+id, {});
    toast('✉ E-mail D4Sign enviado!'); loadPend();
  } catch(e) { toast('Erro: '+e.message, true); btn.disabled=false; btn.textContent='📨 Assinar'; }
}

function d4b(s) {
  if (!s||s==='NONE') return '<span class="badge" style="background:#f1f5f9;color:#64748b">—</span>';
  if (s==='PENDING_SIGNATURE') return '<span class="badge b-sign">Aguardando</span>';
  if (s==='SIGNED') return '<span class="badge b-ok">Assinado</span>';
  return `<span class="badge">${s}</span>`;
}

// ── utils ──
function $(id){return document.getElementById(id)}
function $v(id){return $(id).value.trim()}
function show(id){$(id).style.display=''}
function hide(id){$(id).style.display='none'}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

async function api(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const d = await r.json();
  if (!r.ok) { const e = new Error(d.detail||'Erro'); e.status=r.status; throw e; }
  return d;
}
async function authGet(url) {
  const r = await fetch(url, {headers:{Authorization:'Bearer '+_tok}});
  const d = await r.json();
  if (!r.ok) { const e = new Error(d.detail||'Erro'); e.status=r.status; throw e; }
  return d;
}
async function authPost(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+_tok}, body:JSON.stringify(body)});
  const d = await r.json();
  if (!r.ok) { const e = new Error(d.detail||'Erro'); e.status=r.status; throw e; }
  return d;
}

function toast(msg, isErr=false) {
  const t=$('toast'); t.textContent=msg;
  t.style.background=isErr?'#dc2626':'#059669';
  t.style.display='block'; setTimeout(()=>t.style.display='none',4000);
}

let _gridData = [], _gridFiltro = 'todos';

async function loadGrid() {
  try {
    const d = await authGet('/api/nutri/grid-padroes');
    _gridData = d.pacientes;
    renderSummary(d.resumo);
    renderGrid(_gridData, _gridFiltro);
  } catch(e) { if(e.status===401) doLogout(); }
}

function renderSummary(r) {
  $("gridSummary").innerHTML = "";
  var cards = [
    {f:"ESCAPE",    l:"Escape",    s:"1a tentativa",    c:"sc-escape",    e:"🌊"},
    {f:"CONFRONTO", l:"Confronto", s:"Precisa atencao", c:"sc-confronto", e:"⚡"},
    {f:"RETORNO",   l:"Retorno",   s:"Voltou ao padrao",c:"sc-retorno",   e:"🔄"},
    {f:"CULPA",     l:"Culpa",     s:"Check-in emoc.",  c:"sc-culpa",     e:"💙"},
  ];
  for (var i = 0; i < cards.length; i++) {
    var c = cards[i];
    var div = document.createElement("div");
    div.className = "sum-card " + c.c;
    (function(fase){ div.addEventListener("click", function(){ filterGrid(fase); }); })(c.f);
    div.innerHTML = "<div class='num'>" + (r[c.f]||0) + "</div>"
      + "<div class='lbl'>" + c.e + " " + c.l + "</div>"
      + "<div class='sub'>" + c.s + "</div>";
    $("gridSummary").appendChild(div);
  }
}

function filterGrid(fase) {
  _gridFiltro = fase;
  document.querySelectorAll('.gf-btn').forEach(b => b.classList.remove('on'));
  const cls = fase==='todos' ? 'gf-todos' : 'gf-'+fase.toLowerCase();
  const el = document.querySelector('.'+cls);
  if (el) el.classList.add('on');
  renderGrid(_gridData, fase);
}

function renderGrid(data, filtro) {
  var el = $("gridPadroes");
  var rows = filtro === "todos" ? data.filter(function(p){ return p.padrao; })
           : data.filter(function(p){ return p.padrao && p.padrao.fase === filtro; });
  if (!rows.length) {
    el.innerHTML = "<div class='empty-grid'>Nenhum paciente nesta fase ainda.<br/>Os padroes aparecem quando os pacientes registram refeicoes.</div>";
    return;
  }
  var html = "";
  for (var i = 0; i < rows.length; i++) {
    var p = rows[i];
    var pad = p.padrao;
    var fl = pad.fase.toLowerCase();
    var dias = pad.dias_atras === 0 ? "hoje" : pad.dias_atras === 1 ? "ontem" : pad.dias_atras + "d atras";
    var gat = (pad.gatilhos || []).slice(0, 3).join(", ");
    var deg = Math.min(pad.degradacao || 0, 3);
    var dots = "";
    for (var d = 0; d < 3; d++) dots += d < deg ? "●" : "○";
    html += "<div class='pcard fase-" + fl + "'>";
    html += "<div class='fase-bar'></div>";
    html += "<div class='pnome'>" + esc(p.nome) + "</div>";
    html += "<span class='pfase pfase-" + fl + "'>" + pad.emoji + " " + pad.fase + "</span>";
    html += "<div class='pinfo'>" + (gat ? "<b>Gatilhos:</b> " + esc(gat) + "<br/>" : "");
    html += "<b>Detectado:</b> " + dias + " · Streak: " + p.streak + "d</div>";
    html += "<div class='pacao'>→ " + esc(pad.acao_recomendada) + "</div>";
    html += "<div class='pciclo'>Ciclo #" + (pad.ciclo || 1) + " · " + dots + "</div>";
    html += "</div>";
  }
  el.innerHTML = html;
}

document.addEventListener('keydown', e => {
  if (e.key==='Enter') {
    if (!$('formLogin').style.display) doLogin();
    else if (!$('formForgot').style.display) doForgot();
    else if (!$('formSetPass').style.display) doSetPass();
  }
});
</script>
</body>
</html>
"""
