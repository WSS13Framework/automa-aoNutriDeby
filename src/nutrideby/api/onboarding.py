"""
NutriDeby — API de Onboarding Multi-Plataforma
Endpoints: detect, connect, sync, status, revoke, platforms
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from nutrideby.onboarding.detector import DetectionResult, detect, list_platforms
from nutrideby.onboarding.vault import decrypt, encrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class DetectRequest(BaseModel):
    text: str = Field(..., description="URL, nome ou domínio da plataforma")


class DetectResponse(BaseModel):
    platform: str
    confidence: float
    display_name: str
    rota: str
    instructions: str
    icon: str


class ConnectRequest(BaseModel):
    nutritionist_id: str = Field(..., description="ID do nutricionista (UUID ou email)")
    platform: str
    username: str
    password: str
    extra_config: dict[str, Any] = Field(default_factory=dict)


class ConnectResponse(BaseModel):
    credential_id: str
    platform: str
    display_name: str
    message: str


class SyncRequest(BaseModel):
    nutritionist_id: str
    credential_id: str


class SyncResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    total_records: int
    processed: int
    inserted: int
    updated: int
    errors: list[str]
    started_at: str | None
    finished_at: str | None
    log: str | None


class RevokeResponse(BaseModel):
    message: str


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_db(settings) -> psycopg.Connection:
    try:
        return psycopg.connect(settings.database_url)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erro de conexão: {e}")


def _audit(conn: psycopg.Connection, nutritionist_id: str, platform: str,
           action: str, result: str, detail: str = "", request: Request | None = None) -> None:
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO onboarding_audit_log
                    (nutritionist_id, platform, action, ip_address, user_agent, result, detail)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                """,
                (nutritionist_id, platform, action, ip, ua, result, detail),
            )
        conn.commit()
    except Exception as e:
        logger.warning(f"Falha ao gravar audit log: {e}")


def _validate_credential(platform: str, username: str, password: str,
                          extra_config: dict) -> tuple[bool, str]:
    """
    Valida a credencial contra a plataforma.
    Retorna (is_valid, message).
    Por ora, valida apenas formato. Workers fazem validação real.
    """
    if not username or not password:
        return False, "Usuário e senha são obrigatórios."
    if len(password) < 4:
        return False, "Senha muito curta."
    # TODO: para Dietbox, fazer POST /auth/login e verificar 200
    # TODO: para NutriCloud, idem
    return True, "Credencial aceita (validação completa ocorre na primeira sincronização)."


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/platforms")
def get_platforms() -> list[dict]:
    """Lista todas as plataformas suportadas."""
    return list_platforms()


@router.post("/detect", response_model=DetectResponse)
def detect_platform(body: DetectRequest) -> DetectResponse:
    """Detecta a plataforma a partir de texto livre (URL, nome, domínio)."""
    result: DetectionResult = detect(body.text)
    return DetectResponse(
        platform=result.platform,
        confidence=result.confidence,
        display_name=result.display_name,
        rota=result.rota,
        instructions=result.instructions,
        icon=result.icon,
    )


@router.post("/connect", response_model=ConnectResponse)
def connect_platform(
    body: ConnectRequest,
    request: Request,
    settings=Depends(lambda: __import__("nutrideby.config", fromlist=["Settings"]).Settings()),
) -> ConnectResponse:
    """
    Valida e armazena credencial criptografada no vault.
    Credencial é criptografada com AES-256-GCM antes de persistir.
    """
    # Validação básica
    is_valid, msg = _validate_credential(
        body.platform, body.username, body.password, body.extra_config
    )
    if not is_valid:
        raise HTTPException(status_code=422, detail=msg)

    # Criptografar senha
    try:
        cred_enc, cred_nonce = encrypt(body.password)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    conn = _get_db(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO onboarding_credentials
                    (nutritionist_id, platform, username, cred_enc, cred_nonce, extra_config)
                VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (nutritionist_id, platform)
                DO UPDATE SET
                    username     = EXCLUDED.username,
                    cred_enc     = EXCLUDED.cred_enc,
                    cred_nonce   = EXCLUDED.cred_nonce,
                    extra_config = EXCLUDED.extra_config,
                    is_valid     = TRUE,
                    updated_at   = NOW()
                RETURNING id
                """,
                (
                    body.nutritionist_id,
                    body.platform,
                    body.username,
                    cred_enc,
                    cred_nonce,
                    json.dumps(body.extra_config, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
            credential_id = str(row[0]) if row else str(uuid.uuid4())
        conn.commit()

        _audit(conn, body.nutritionist_id, body.platform, "connect", "ok",
               f"username={body.username}", request)

        # Detectar display_name
        det = detect(body.platform)
        return ConnectResponse(
            credential_id=credential_id,
            platform=body.platform,
            display_name=det.display_name,
            message=msg,
        )

    except HTTPException:
        raise
    except Exception as e:
        _audit(conn, body.nutritionist_id, body.platform, "connect", "error", str(e), request)
        raise HTTPException(status_code=500, detail=f"Erro ao salvar credencial: {e}")
    finally:
        conn.close()


@router.post("/sync", response_model=SyncResponse)
def sync_platform(
    body: SyncRequest,
    request: Request,
    settings=Depends(lambda: __import__("nutrideby.config", fromlist=["Settings"]).Settings()),
) -> SyncResponse:
    """
    Enfileira job de importação no Redis Queue.
    Retorna job_id para polling de status.
    """
    conn = _get_db(settings)
    job_id = str(uuid.uuid4())

    try:
        # Verificar que credencial existe e é válida
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, platform FROM onboarding_credentials WHERE id = %s::uuid AND is_valid = TRUE",
                (body.credential_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Credencial não encontrada ou inválida.")

            platform = row[1]

            # Criar registro do job
            cur.execute(
                """
                INSERT INTO onboarding_jobs
                    (id, credential_id, nutritionist_id, platform, status)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, 'queued')
                """,
                (job_id, body.credential_id, body.nutritionist_id, platform),
            )
        conn.commit()

        # Enfileirar no Redis Queue
        try:
            import redis
            from rq import Queue as RQueue
            redis_url = getattr(settings, "redis_url", "redis://localhost:6379/0")
            r = redis.from_url(redis_url)
            q = RQueue("onboarding", connection=r)
            q.enqueue(
                "nutrideby.onboarding.workers.run_import_job",
                job_id=job_id,
                credential_id=body.credential_id,
                nutritionist_id=body.nutritionist_id,
                platform=platform,
                database_url=settings.database_url,
                job_timeout=3600,
            )
            queue_status = "queued"
        except ImportError:
            # RQ não instalado ainda — marca como queued, worker vai pegar via polling
            logger.warning("RQ não instalado — job criado no banco, worker deve pegar via polling")
            queue_status = "queued_db"

        _audit(conn, body.nutritionist_id, platform, "sync", "ok", f"job_id={job_id}", request)

        return SyncResponse(
            job_id=job_id,
            status=queue_status,
            message=f"Importação enfileirada. Acompanhe em /api/onboarding/status/{job_id}",
        )

    except HTTPException:
        raise
    except Exception as e:
        _audit(conn, body.nutritionist_id, "", "sync", "error", str(e), request)
        raise HTTPException(status_code=500, detail=f"Erro ao enfileirar job: {e}")
    finally:
        conn.close()


@router.get("/status/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    settings=Depends(lambda: __import__("nutrideby.config", fromlist=["Settings"]).Settings()),
) -> JobStatusResponse:
    """Retorna o status atual de um job de importação."""
    conn = _get_db(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, progress, total_records, processed,
                       inserted, updated, errors, started_at, finished_at, log
                FROM onboarding_jobs
                WHERE id = %s::uuid
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job não encontrado.")

            return JobStatusResponse(
                job_id=str(row[0]),
                status=row[1],
                progress=row[2] or 0,
                total_records=row[3] or 0,
                processed=row[4] or 0,
                inserted=row[5] or 0,
                updated=row[6] or 0,
                errors=row[7] if row[7] else [],
                started_at=row[8].isoformat() if row[8] else None,
                finished_at=row[9].isoformat() if row[9] else None,
                log=row[10],
            )
    finally:
        conn.close()


@router.delete("/revoke/{credential_id}", response_model=RevokeResponse)
def revoke_credential(
    credential_id: str,
    request: Request,
    settings=Depends(lambda: __import__("nutrideby.config", fromlist=["Settings"]).Settings()),
) -> RevokeResponse:
    """Revoga uma credencial (marca como inválida e apaga os bytes criptografados)."""
    conn = _get_db(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE onboarding_credentials
                SET is_valid = FALSE, cred_enc = '', cred_nonce = '', updated_at = NOW()
                WHERE id = %s::uuid
                RETURNING nutritionist_id, platform
                """,
                (credential_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Credencial não encontrada.")
            nutritionist_id, platform = str(row[0]), row[1]
        conn.commit()
        _audit(conn, nutritionist_id, platform, "revoke", "ok", f"credential_id={credential_id}", request)
        return RevokeResponse(message=f"Credencial {platform} revogada com sucesso.")
    finally:
        conn.close()
