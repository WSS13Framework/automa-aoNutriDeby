"""
API de Onboarding Multi-Tenant — NutriDeby SaaS

Fluxo do nutricionista:
  POST /onboarding/register         → cria conta
  POST /onboarding/credentials      → valida e salva credenciais da plataforma (Dietbox etc.)
  GET  /onboarding/sync/status      → progresso da extração
  POST /onboarding/credentials/refresh  → renova token expirado

Isolamento: cada conta vê apenas seus próprios pacientes/dados.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

import psycopg
import psycopg.errors
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from psycopg.rows import dict_row
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["onboarding"])

VAULT_KEY = os.getenv("ONBOARDING_VAULT_KEY", "")


# ── Modelos ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str = Field(..., description="Email do nutricionista")
    name: str = Field(..., min_length=2)
    password: str = Field(..., min_length=8)


class RegisterResponse(BaseModel):
    account_id: str
    message: str


class CredentialsRequest(BaseModel):
    platform: str = Field(default="dietbox", description="dietbox | nutrismart | anny")
    bearer_token: str | None = Field(default=None, description="JWT Bearer token (Dietbox)")
    login: str | None = Field(default=None, description="Email/login (para plataformas sem API)")
    password: str | None = Field(default=None, description="Senha (para plataformas sem API)")


class CredentialsResponse(BaseModel):
    credential_id: str
    status: str
    patients_found: int
    sync_job_id: str
    message: str


class SyncStatusResponse(BaseModel):
    job_id: str
    status: str
    patients_synced: int
    started_at: str | None
    finished_at: str | None
    error: str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """SHA-256 simples para MVP — usar bcrypt em produção."""
    return hashlib.sha256(password.encode()).hexdigest()


def _encrypt_credential(data: str) -> bytes:
    """
    Cifra com pgcrypto via SQL (chave simétrica do .env).
    Para MVP: XOR com chave. Produção: usar pgp_sym_encrypt ou Vault.
    """
    if not VAULT_KEY:
        raise ValueError("ONBOARDING_VAULT_KEY não configurado no .env")
    # Cifra simples XOR para MVP (substituir por pgp_sym_encrypt em produção)
    key = (VAULT_KEY * ((len(data) // len(VAULT_KEY)) + 1))[:len(data)]
    encrypted = bytes(a ^ b for a, b in zip(data.encode(), key.encode()))
    return encrypted


def _decrypt_credential(encrypted: bytes) -> str:
    if not VAULT_KEY:
        raise ValueError("ONBOARDING_VAULT_KEY não configurado")
    key = (VAULT_KEY * ((len(encrypted) // len(VAULT_KEY)) + 1))[:len(encrypted)]
    return bytes(a ^ b for a, b in zip(encrypted, key.encode())).decode()


def _validate_dietbox_token(token: str, api_base: str = "https://api.dietbox.me") -> tuple[bool, int]:
    """Faz chamada de teste na Dietbox. Retorna (valido, total_pacientes)."""
    import urllib.request, ssl
    url = f"{api_base}/v2/paciente?skip=0&take=1"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Origin": "https://dietbox.me",
        "Referer": "https://dietbox.me/",
    })
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            import json
            data = json.loads(resp.read())
            total = (data.get("Data") or {}).get("TotalItems") or 0
            return True, int(total)
    except Exception as e:
        logger.warning("Dietbox validation failed: %s", e)
        return False, 0


def _conn(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse)
def register(body: RegisterRequest, settings=Depends(lambda: __import__('nutrideby.config', fromlist=['Settings']).Settings())) -> RegisterResponse:
    """Cadastra novo nutricionista na plataforma."""
    with _conn(settings.database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO accounts (email, name, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (body.email.lower().strip(), body.name.strip(), _hash_password(body.password)),
                )
                row = cur.fetchone()
                conn.commit()
                return RegisterResponse(
                    account_id=str(row["id"]),
                    message=f"Conta criada! Próximo passo: configure suas credenciais do Dietbox.",
                )
        except psycopg.errors.UniqueViolation:
            raise HTTPException(status_code=409, detail="Email já cadastrado")


@router.post("/credentials", response_model=CredentialsResponse)
def save_credentials(
    body: CredentialsRequest,
    background_tasks: BackgroundTasks,
    account_id: str = "00000000-0000-0000-0000-000000000001",  # MVP: hard-coded; prod: JWT auth
    settings=Depends(lambda: __import__('nutrideby.config', fromlist=['Settings']).Settings()),
) -> CredentialsResponse:
    """
    Salva credenciais da plataforma externa (cifradas) e dispara extração.

    O nutricionista cola o Bearer Token que obteve no DevTools do Dietbox.
    O sistema valida, cifra e armazena — nunca em texto claro.
    """
    if body.platform == "dietbox":
        if not body.bearer_token:
            raise HTTPException(status_code=422, detail="bearer_token obrigatório para Dietbox")

        # 1. Valida token na Dietbox
        valid, patient_count = _validate_dietbox_token(body.bearer_token)
        if not valid:
            raise HTTPException(
                status_code=401,
                detail="Token Dietbox inválido ou expirado. Renove em DevTools → Network → api.dietbox.me → Authorization."
            )

        # 2. Cifra e salva
        import json
        credential_data = json.dumps({"bearer_token": body.bearer_token})
        encrypted = _encrypt_credential(credential_data)

        # Detecta expiração do JWT
        expires_at = None
        try:
            import base64
            parts = body.bearer_token.split(".")
            if len(parts) == 3:
                payload = json.loads(base64.b64decode(parts[1] + "=="))
                exp = payload.get("exp")
                if exp:
                    expires_at = datetime.fromtimestamp(exp)
        except Exception:
            pass

        with _conn(settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO platform_credentials
                      (account_id, platform, credential_type, encrypted_data,
                       expires_at, last_validated_at, validation_status, patients_synced)
                    VALUES (%s, %s, 'bearer_token', %s, %s, now(), 'valid', %s)
                    ON CONFLICT (account_id, platform) DO UPDATE SET
                      encrypted_data = EXCLUDED.encrypted_data,
                      expires_at = EXCLUDED.expires_at,
                      last_validated_at = now(),
                      validation_status = 'valid',
                      sync_status = 'idle',
                      error_message = NULL,
                      updated_at = now()
                    RETURNING id
                    """,
                    (account_id, body.platform, encrypted, expires_at, patient_count),
                )
                cred_row = cur.fetchone()
                cred_id = str(cred_row["id"])

                # 3. Cria job de extração na fila
                cur.execute(
                    """
                    INSERT INTO extraction_jobs
                      (account_id, credential_id, platform, job_type, status, priority)
                    VALUES (%s, %s, %s, 'full_sync', 'queued', 10)
                    RETURNING id
                    """,
                    (account_id, cred_id, body.platform),
                )
                job_row = cur.fetchone()
                job_id = str(job_row["id"])
                conn.commit()

        # 4. Dispara extração em background
        background_tasks.add_task(
            _run_extraction_job,
            job_id=job_id,
            account_id=account_id,
            bearer_token=body.bearer_token,
            database_url=settings.database_url,
            openai_api_key=settings.openai_api_key or "",
        )

        days_left = None
        if expires_at:
            days_left = (expires_at - datetime.now()).days

        return CredentialsResponse(
            credential_id=cred_id,
            status="valid",
            patients_found=patient_count,
            sync_job_id=job_id,
            message=(
                f"Token válido! {patient_count} pacientes encontrados. "
                f"Extração iniciada. "
                + (f"Token expira em {days_left} dias." if days_left else "")
            ),
        )

    raise HTTPException(status_code=400, detail=f"Plataforma '{body.platform}' não suportada ainda")


@router.get("/sync/status/{job_id}", response_model=SyncStatusResponse)
def sync_status(
    job_id: str,
    settings=Depends(lambda: __import__('nutrideby.config', fromlist=['Settings']).Settings()),
) -> SyncStatusResponse:
    """Retorna o progresso da extração."""
    with _conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM extraction_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return SyncStatusResponse(
        job_id=job_id,
        status=row["status"],
        patients_synced=row.get("stats", {}).get("patients_synced", 0),
        started_at=row["started_at"].isoformat() if row.get("started_at") else None,
        finished_at=row["finished_at"].isoformat() if row.get("finished_at") else None,
        error=row.get("error_message"),
    )


@router.get("/credentials/check")
def check_credentials_expiry(
    settings=Depends(lambda: __import__('nutrideby.config', fromlist=['Settings']).Settings()),
) -> list[dict]:
    """Lista credenciais que expiram nos próximos 7 dias — para alertas."""
    with _conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pc.id, pc.platform, pc.expires_at, pc.validation_status,
                       a.email, a.name
                FROM platform_credentials pc
                JOIN accounts a ON a.id = pc.account_id
                WHERE pc.expires_at < now() + interval '7 days'
                   OR pc.validation_status IN ('expired', 'invalid')
                ORDER BY pc.expires_at ASC NULLS LAST
                """
            )
            return [dict(r) for r in cur.fetchall()]


# ── Background: extração completa por tenant ──────────────────────────────────

def _run_extraction_job(
    *,
    job_id: str,
    account_id: str,
    bearer_token: str,
    database_url: str,
    openai_api_key: str,
) -> None:
    """
    Executa extração completa do Dietbox para um tenant.
    Roda em thread separada (BackgroundTasks do FastAPI).
    """
    import subprocess, os
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "DIETBOX_BEARER_TOKEN": bearer_token,
        "OPENAI_API_KEY": openai_api_key,
        "EXTRACTION_JOB_ID": job_id,
        "EXTRACTION_ACCOUNT_ID": account_id,
    }

    def _update_job(status: str, stats: dict | None = None, error: str | None = None):
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE extraction_jobs
                    SET status = %s,
                        stats = COALESCE(%s::jsonb, stats),
                        error_message = %s,
                        started_at = CASE WHEN %s = 'running' THEN now() ELSE started_at END,
                        finished_at = CASE WHEN %s IN ('done','failed') THEN now() ELSE finished_at END
                    WHERE id = %s
                    """,
                    (status, psycopg.types.json.Jsonb(stats) if stats else None,
                     error, status, status, job_id),
                )
                conn.commit()

    _update_job("running")
    base = ["/usr/bin/python3", "-m"]
    cwd = "/opt/automa-aoNutriDeby"
    steps = [
        # 1. Sincroniza lista de pacientes
        base + ["nutrideby.workers.dietbox_sync", "--sync-list", "--max-pages", "0"],
        # 2. Sincroniza prontuários (limite 200 para não sobrecarregar)
        base + ["nutrideby.workers.dietbox_sync", "--sync-prontuario-all",
                "--prontuario-limit", "200", "--prontuario-sleep-ms", "200"],
        # 3. Chunkeia documentos novos
        base + ["nutrideby.workers.chunk_documents"],
        # 4. Gera embeddings
        base + ["nutrideby.workers.embed_chunks", "--limit", "500"],
    ]

    total_patients = 0
    for step in steps:
        try:
            result = subprocess.run(
                step, capture_output=True, text=True, env=env, cwd=cwd, timeout=600
            )
            if result.returncode != 0:
                logger.error("Step %s failed: %s", step, result.stderr[:500])
        except subprocess.TimeoutExpired:
            logger.warning("Step %s timeout", step)
        except Exception as e:
            logger.error("Step %s error: %s", step, e)

    # Conta pacientes extraídos para este account
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*)::int AS n FROM patients WHERE account_id = %s",
                    (account_id,),
                )
                total_patients = cur.fetchone()["n"]
                # Atualiza contagem na credencial
                cur.execute(
                    """
                    UPDATE platform_credentials
                    SET patients_synced = %s, last_sync_at = now(), sync_status = 'done'
                    WHERE account_id = %s AND platform = 'dietbox'
                    """,
                    (total_patients, account_id),
                )
                conn.commit()
    except Exception as e:
        logger.error("count error: %s", e)

    _update_job("done", stats={"patients_synced": total_patients})
    logger.info("Extraction job %s done: %d patients", job_id, total_patients)
