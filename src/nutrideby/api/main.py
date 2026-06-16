
from __future__ import annotations
import hashlib
import hmac as _hmac
import json
import os
from datetime import datetime

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import psycopg
import psycopg.errors
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg.types.json import Json
from pydantic import BaseModel, Field

from nutrideby.clients.openai_embeddings import embed_single_query
from nutrideby.api.analyze import router as analyze_router
from nutrideby.api.onboarding_api import router as onboarding_router
from nutrideby.api.mobile_api import router as mobile_router
from nutrideby.api.stripe_router import router as stripe_router
from nutrideby.api.referral_router import router as referral_router
from nutrideby.api.gamification_router import router as gamification_router
from nutrideby.api.waitlist_router import router as waitlist_router
from nutrideby.api.clinical_router import router as clinical_router
from nutrideby.api.paciente_acesso_router import router as paciente_acesso_router
from nutrideby.api.nutricionista_router import router as nutri_router, _panel_router
from nutrideby.api.bodyscan_router import router as bodyscan_router
from nutrideby.api.bioimpedancia_router import router as bioimpedancia_router
from nutrideby.api.composicao_router import router as composicao_router
from nutrideby.api.content_assets_router import router as content_assets_router
from nutrideby.api.deps import get_settings, require_api_key
from nutrideby.config import Settings
from nutrideby.rag.patient_retrieve import patient_retrieve
from nutrideby.rag.retrieve_embedding_cache import (
    get_cached_query_embedding,
    normalize_query_for_embedding_cache,
    set_cached_query_embedding,
)
from nutrideby.persist.crm_persist import find_document_id_by_content_hash, insert_document_if_new
from nutrideby.persist.snapshots import (
    KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION,
    get_external_snapshot,
)
from nutrideby.persist.webhook_inbox import insert_webhook_inbox

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    s = Settings()
    if not (s.nutrideby_api_key and str(s.nutrideby_api_key).strip()):
        logger.warning(
            "NUTRIDEBY_API_KEY vazio — endpoints /v1/* públicos (só dev / rede confiável)."
        )
    yield


app = FastAPI(
    title="NutriDeby API leitura",
    version="0.4.4",
    description="Leitura Postgres, ingestão de documentos (texto), RAG retrieval (pgvector), análise LLM e hooks (ex.: Kiwify).",
    lifespan=lifespan,
)

@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    """Remove o campo 'input' dos erros de validação para não ecoar payload bruto."""
    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(analyze_router)
app.include_router(onboarding_router)
app.include_router(mobile_router)
app.include_router(stripe_router)
app.include_router(referral_router)
app.include_router(gamification_router)
app.include_router(waitlist_router)
app.include_router(clinical_router)
app.include_router(paciente_acesso_router)
app.include_router(nutri_router)
app.include_router(_panel_router)
app.include_router(bodyscan_router)
app.include_router(bioimpedancia_router)
app.include_router(composicao_router)
app.include_router(content_assets_router)



@app.get("/favicon.svg", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<circle cx="16" cy="16" r="16" fill="#059669"/>'
        '<text x="16" y="22" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="18" fill="white">N</text>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")

@app.on_event("startup")
def _startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    s = Settings()
    if not (s.nutrideby_api_key and str(s.nutrideby_api_key).strip()):
        logger.warning(
            "NUTRIDEBY_API_KEY vazio — endpoints /v1/* públicos (uso só em dev/trusted network)."
        )


class PatientListItem(BaseModel):
    id: str
    source_system: str
    external_id: str
    display_name: str | None
    updated_at: str


class PatientDetail(PatientListItem):
    metadata: dict[str, Any] = Field(default_factory=dict)
    documents_count: int = 0


class DocumentItem(BaseModel):
    id: str
    doc_type: str
    collected_at: str
    content_preview: str


class CreateDocumentRequest(BaseModel):
    """Texto bruto (ex.: OCR de análises). Depois: ``chunk_documents`` + ``embed_chunks`` + ``/retrieve``."""

    content_text: str = Field(..., min_length=1, max_length=500_000)
    doc_type: str = Field(
        default="lab_report",
        min_length=1,
        max_length=200,
        description="Por omissão lab_report; usar outro valor para outros fluxos.",
    )
    source_ref: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description='Ex.: {"discipline": "laboratory", "source": "patient_upload"}',
    )


class CreateDocumentResponse(BaseModel):
    document_id: str
    inserted: bool
    hint: str = (
        "Para RAG: python3 -m nutrideby.workers.chunk_documents --patient-id <uuid> "
        "--doc-type <tipo>; depois embed_chunks."
    )


class ChunkListItem(BaseModel):
    id: str
    document_id: str | None
    chunk_index: int
    text_preview: str
    embedding_model: str | None = None


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)
    k: int = Field(default=5, ge=1, le=20)
    exclude_prontuario_placeholder: bool = Field(
        default=True,
        description="Excluir chunks marcador de prontuário 204 (sem corpo útil).",
    )
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Opcional: só hits com score >= valor (score = 1/(1+distance)).",
    )


class RetrieveHit(BaseModel):
    chunk_id: str
    document_id: str | None
    chunk_index: int
    distance: float
    score: float
    text: str


class RetrieveResponse(BaseModel):
    query: str
    embedding_model: str
    hits: list[RetrieveHit]
    embedding_cache_hit: bool = Field(
        default=False,
        description="True se o vector da query veio do Redis (L1 exact-match), sem nova chamada OpenAI embeddings.",
    )


class PatientRagCoverageItem(BaseModel):
    """Contagens de chunks por paciente para diagnóstico RAG (embeddings vs marcador 204)."""

    patient_id: str
    source_system: str
    external_id: str
    display_name: str | None
    chunks_total: int
    chunks_embedded: int
    chunks_missing_embedding: int
    placeholder_prontuario_embedded: int
    usable_embedded_chunks: int


def _conn(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/dietbox/subscription", dependencies=[Depends(require_api_key)])
def dietbox_subscription_snapshot(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Última subscription Dietbox persistida (``--sync-subscription``)."""
    try:
        with psycopg.connect(settings.database_url) as conn:
            row = get_external_snapshot(
                conn,
                key=KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION,
            )
    except psycopg.errors.UndefinedTable as e:
        raise HTTPException(
            status_code=503,
            detail="Tabela external_snapshots em falta. Aplica infra/sql/002_external_snapshots.sql",
        ) from e
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Sem snapshot; correr: python3 -m nutrideby.workers.dietbox_sync --sync-subscription (ou via Docker: worker python -m …)",
        )
    payload, fetched_at, http_status = row
    return {
        "key": KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION,
        "fetched_at": fetched_at,
        "http_status": http_status,
        "payload": payload,
    }


@app.get("/v1/patients", dependencies=[Depends(require_api_key)])
def list_patients(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source_system: str | None = Query(None, description="Filtrar por source_system, ex. dietbox"),
) -> list[PatientListItem]:
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            if source_system:
                cur.execute(
                    """
                    SELECT id, source_system, external_id, display_name, updated_at
                    FROM patients
                    WHERE source_system = %s
                    ORDER BY updated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (source_system, limit, offset),
                )
            else:
                cur.execute(
                    """
                    SELECT id, source_system, external_id, display_name, updated_at
                    FROM patients
                    ORDER BY updated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
            rows = cur.fetchall()
    out: list[PatientListItem] = []
    for r in rows:
        out.append(
            PatientListItem(
                id=str(r["id"]),
                source_system=r["source_system"],
                external_id=r["external_id"],
                display_name=r.get("display_name"),
                updated_at=r["updated_at"].isoformat() if r.get("updated_at") else "",
            )
        )
    return out


@app.get(
    "/v1/patients/rag-coverage",
    dependencies=[Depends(require_api_key)],
    response_model=list[PatientRagCoverageItem],
)
def list_patients_rag_coverage(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    source_system: str | None = Query(None, description="Filtrar por source_system, ex. dietbox"),
    min_usable_embedded: int = Query(
        0,
        ge=0,
        description="Só pacientes com pelo menos N chunks embedded e não marcador 204.",
    ),
) -> list[PatientRagCoverageItem]:
    """
    Lista pacientes com contagens de chunks: total, com embedding, sem embedding,
    marcador de prontuário 204 (ainda embedded mas inútil para RAG), e ``usable``
    (embedded e texto diferente do marcador 204).
    """
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id AS patient_id,
                       p.source_system,
                       p.external_id,
                       p.display_name,
                       COUNT(c.id)::int AS chunks_total,
                       COUNT(c.id) FILTER (WHERE c.embedding IS NOT NULL)::int AS chunks_embedded,
                       COUNT(c.id) FILTER (WHERE c.embedding IS NULL)::int AS chunks_missing_embedding,
                       COUNT(c.id) FILTER (
                         WHERE c.embedding IS NOT NULL
                           AND coalesce(c.text, '') LIKE '[Prontuário: API 204%%'
                       )::int AS placeholder_prontuario_embedded,
                       COUNT(c.id) FILTER (
                         WHERE c.embedding IS NOT NULL
                           AND coalesce(c.text, '') NOT LIKE '[Prontuário: API 204%%'
                       )::int AS usable_embedded_chunks
                FROM patients p
                LEFT JOIN chunks c ON c.patient_id = p.id
                WHERE (%s::text IS NULL OR p.source_system = %s)
                GROUP BY p.id, p.source_system, p.external_id, p.display_name
                HAVING COUNT(c.id) FILTER (
                         WHERE c.embedding IS NOT NULL
                           AND coalesce(c.text, '') NOT LIKE '[Prontuário: API 204%%'
                       ) >= %s
                ORDER BY usable_embedded_chunks DESC, chunks_embedded DESC
                LIMIT %s OFFSET %s
                """,
                (source_system, source_system, min_usable_embedded, limit, offset),
            )
            rows = cur.fetchall()
    out: list[PatientRagCoverageItem] = []
    for r in rows:
        out.append(
            PatientRagCoverageItem(
                patient_id=str(r["patient_id"]),
                source_system=r["source_system"],
                external_id=r["external_id"],
                display_name=r.get("display_name"),
                chunks_total=int(r.get("chunks_total") or 0),
                chunks_embedded=int(r.get("chunks_embedded") or 0),
                chunks_missing_embedding=int(r.get("chunks_missing_embedding") or 0),
                placeholder_prontuario_embedded=int(
                    r.get("placeholder_prontuario_embedded") or 0
                ),
                usable_embedded_chunks=int(r.get("usable_embedded_chunks") or 0),
            )
        )
    return out


@app.get("/v1/patients/by-external/{source_system}/{external_id}", dependencies=[Depends(require_api_key)])
def get_patient_by_external(
    source_system: str,
    external_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PatientDetail:
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.source_system, p.external_id, p.display_name, p.updated_at, p.metadata,
                       (SELECT COUNT(*)::int FROM documents d WHERE d.patient_id = p.id) AS documents_count
                FROM patients p
                WHERE p.source_system = %s AND p.external_id = %s
                """,
                (source_system, external_id),
            )
            r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    meta = r.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    return PatientDetail(
        id=str(r["id"]),
        source_system=r["source_system"],
        external_id=r["external_id"],
        display_name=r.get("display_name"),
        updated_at=r["updated_at"].isoformat() if r.get("updated_at") else "",
        metadata=meta,
        documents_count=int(r.get("documents_count") or 0),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Gestão de pacientes (Sprint unificação): stats, PATCH, reactivation-stage,
# notes e timeline. Inseridos ANTES de GET /v1/patients/{patient_id} para que a
# rota estática /v1/patients/stats seja resolvida antes do parâmetro UUID.
# ──────────────────────────────────────────────────────────────────────────────

_REACTIVATION_TRANSITIONS: dict[str | None, list[str]] = {
    None: ["responded"],
    "responded": ["scheduled"],
    "scheduled": ["reactivated"],
}
_REACTIVATION_TS_COL = {
    "responded": "reactivation_responded_at",
    "scheduled": "reactivation_scheduled_at",
    "reactivated": "reactivation_reactivated_at",
}
_PATCH_PATIENT_ALLOWED = {"display_name", "email", "metadata", "goal_statement", "reactivation_notes"}


class PatientStats(BaseModel):
    total: int
    active: int
    trial: int
    inactive: int
    expired: int
    reactivation_responded: int
    reactivation_scheduled: int
    reactivation_reactivated: int


class ReactivationStageBody(BaseModel):
    stage: str = Field(description="responded | scheduled | reactivated")
    notes: str | None = None


class NoteBody(BaseModel):
    note: str
    author: str | None = None


@app.get("/v1/patients/stats", dependencies=[Depends(require_api_key)], response_model=PatientStats)
def patients_stats(settings: Annotated[Settings, Depends(get_settings)]) -> PatientStats:
    """Contadores por subscription_status e por estágio de reativação."""
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  COUNT(*)::int AS total,
                  COUNT(*) FILTER (WHERE subscription_status = 'active')::int   AS active,
                  COUNT(*) FILTER (WHERE subscription_status = 'trial')::int    AS trial,
                  COUNT(*) FILTER (WHERE subscription_status = 'inactive')::int AS inactive,
                  COUNT(*) FILTER (WHERE subscription_status IN ('expired','canceled'))::int AS expired,
                  COUNT(*) FILTER (WHERE reactivation_stage = 'responded')::int   AS r_responded,
                  COUNT(*) FILTER (WHERE reactivation_stage = 'scheduled')::int   AS r_scheduled,
                  COUNT(*) FILTER (WHERE reactivation_stage = 'reactivated')::int AS r_reactivated
                FROM patients
                """
            )
            r = cur.fetchone()
    return PatientStats(
        total=r["total"], active=r["active"], trial=r["trial"],
        inactive=r["inactive"], expired=r["expired"],
        reactivation_responded=r["r_responded"],
        reactivation_scheduled=r["r_scheduled"],
        reactivation_reactivated=r["r_reactivated"],
    )


@app.patch("/v1/patients/{patient_id}", dependencies=[Depends(require_api_key)])
def update_patient(
    patient_id: UUID,
    payload: dict[str, Any],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Atualização parcial de paciente (campos em allowlist)."""
    fields = {k: v for k, v in (payload or {}).items() if k in _PATCH_PATIENT_ALLOWED}
    if not fields:
        raise HTTPException(
            status_code=422,
            detail=f"Nenhum campo válido. Permitidos: {sorted(_PATCH_PATIENT_ALLOWED)}",
        )
    set_parts: list[str] = []
    values: list[Any] = []
    for k, v in fields.items():
        if k == "metadata":
            set_parts.append("metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb")
            values.append(Json(v))
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)
    set_sql = ", ".join(set_parts) + ", updated_at = NOW()"
    values.append(patient_id)
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE patients SET {set_sql} WHERE id = %s "
                "RETURNING id, display_name, email, subscription_status, reactivation_stage, updated_at",
                values,
            )
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")
            conn.commit()
    return {
        "id": str(r["id"]),
        "display_name": r.get("display_name"),
        "email": r.get("email"),
        "subscription_status": r.get("subscription_status"),
        "reactivation_stage": r.get("reactivation_stage"),
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


@app.patch("/v1/patients/{patient_id}/reactivation-stage", dependencies=[Depends(require_api_key)])
def update_reactivation_stage(
    patient_id: UUID,
    body: ReactivationStageBody,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Avança o estágio de reativação (responded → scheduled → reactivated)."""
    stage = (body.stage or "").strip()
    if stage not in _REACTIVATION_TS_COL:
        raise HTTPException(status_code=422, detail="stage inválido (responded|scheduled|reactivated)")
    ts_col = _REACTIVATION_TS_COL[stage]
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT reactivation_stage FROM patients WHERE id = %s", (patient_id,))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")
            current = r["reactivation_stage"]
            allowed = _REACTIVATION_TRANSITIONS.get(current, [])
            if stage not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=f"Transição inválida: {current} → {stage}. Permitidas: {allowed}",
                )
            cur.execute(
                f"""
                UPDATE patients
                SET reactivation_stage = %s,
                    {ts_col} = NOW(),
                    reactivation_date = NOW(),
                    reactivation_notes = COALESCE(%s, reactivation_notes)
                WHERE id = %s
                RETURNING id, reactivation_stage, {ts_col} AS stage_at
                """,
                (stage, body.notes, patient_id),
            )
            updated = cur.fetchone()
            conn.commit()
    return {
        "status": "ok",
        "patient_id": str(updated["id"]),
        "stage": updated["reactivation_stage"],
        "stage_at": updated["stage_at"].isoformat() if updated.get("stage_at") else None,
    }


@app.post("/v1/patients/{patient_id}/notes", dependencies=[Depends(require_api_key)])
def add_patient_note(
    patient_id: UUID,
    body: NoteBody,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Adiciona uma nota livre da nutricionista ao paciente."""
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="note vazio")
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM patients WHERE id = %s", (patient_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Paciente não encontrado")
            cur.execute(
                "INSERT INTO patient_notes (patient_id, author, note) VALUES (%s, %s, %s) "
                "RETURNING id, author, note, created_at",
                (patient_id, body.author, note),
            )
            r = cur.fetchone()
            conn.commit()
    return {
        "id": str(r["id"]),
        "author": r.get("author"),
        "note": r["note"],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@app.get("/v1/patients/{patient_id}/notes", dependencies=[Depends(require_api_key)])
def list_patient_notes(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Lista as notas da nutricionista (mais recentes primeiro)."""
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, author, note, created_at FROM patient_notes "
                "WHERE patient_id = %s ORDER BY created_at DESC LIMIT %s",
                (patient_id, limit),
            )
            rows = cur.fetchall()
    return [
        {
            "id": str(r["id"]),
            "author": r.get("author"),
            "note": r["note"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        for r in rows
    ]


@app.get("/v1/patients/{patient_id}/timeline", dependencies=[Depends(require_api_key)])
def patient_timeline(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Timeline unificada: mensagens, notas, sabatinas e mudanças de reativação."""
    pid = patient_id
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts, kind, summary FROM (
                    SELECT received_at AS ts, 'message_in' AS kind,
                           left(coalesce(body, ''), 160) AS summary
                      FROM inbound_messages
                     WHERE patient_id = %s AND received_at IS NOT NULL
                    UNION ALL
                    SELECT replied_at, 'message_out', left(coalesce(reply_body, ''), 160)
                      FROM inbound_messages
                     WHERE patient_id = %s AND replied_at IS NOT NULL AND reply_body IS NOT NULL
                    UNION ALL
                    SELECT created_at, 'note', left(coalesce(note, ''), 160)
                      FROM patient_notes WHERE patient_id = %s
                    UNION ALL
                    SELECT created_at, 'symptom_survey',
                           'Sabatina: ' || burden_level || ' (' || total_score || '/' || max_score || ')'
                      FROM patient_symptom_surveys WHERE patient_id = %s
                    UNION ALL
                    SELECT reactivation_responded_at, 'reactivation:responded', NULL
                      FROM patients WHERE id = %s AND reactivation_responded_at IS NOT NULL
                    UNION ALL
                    SELECT reactivation_scheduled_at, 'reactivation:scheduled', NULL
                      FROM patients WHERE id = %s AND reactivation_scheduled_at IS NOT NULL
                    UNION ALL
                    SELECT reactivation_reactivated_at, 'reactivation:reactivated', NULL
                      FROM patients WHERE id = %s AND reactivation_reactivated_at IS NOT NULL
                ) t
                ORDER BY ts DESC NULLS LAST
                LIMIT %s
                """,
                (pid, pid, pid, pid, pid, pid, pid, limit),
            )
            rows = cur.fetchall()
    return [
        {
            "ts": r["ts"].isoformat() if r.get("ts") else None,
            "kind": r["kind"],
            "summary": r.get("summary"),
        }
        for r in rows
    ]


@app.get("/v1/patients/{patient_id}", dependencies=[Depends(require_api_key)])
def get_patient(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PatientDetail:
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.source_system, p.external_id, p.display_name, p.updated_at, p.metadata,
                       (SELECT COUNT(*)::int FROM documents d WHERE d.patient_id = p.id) AS documents_count
                FROM patients p
                WHERE p.id = %s
                """,
                (patient_id,),
            )
            r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    meta = r.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    return PatientDetail(
        id=str(r["id"]),
        source_system=r["source_system"],
        external_id=r["external_id"],
        display_name=r.get("display_name"),
        updated_at=r["updated_at"].isoformat() if r.get("updated_at") else "",
        metadata=meta,
        documents_count=int(r.get("documents_count") or 0),
    )


@app.get("/v1/patients/{patient_id}/documents", dependencies=[Depends(require_api_key)])
def list_documents(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(20, ge=1, le=100),
) -> list[DocumentItem]:
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.doc_type, d.collected_at, d.content_text
                FROM documents d
                WHERE d.patient_id = %s
                ORDER BY d.collected_at DESC
                LIMIT %s
                """,
                (patient_id, limit),
            )
            rows = cur.fetchall()
    out: list[DocumentItem] = []
    for r in rows:
        text = r.get("content_text") or ""
        preview = text if len(text) <= 400 else text[:400] + "…"
        out.append(
            DocumentItem(
                id=str(r["id"]),
                doc_type=r["doc_type"],
                collected_at=r["collected_at"].isoformat() if r.get("collected_at") else "",
                content_preview=preview,
            )
        )
    return out


@app.post(
    "/v1/patients/{patient_id}/documents",
    dependencies=[Depends(require_api_key)],
    response_model=CreateDocumentResponse,
)
def create_patient_document(
    patient_id: UUID,
    body: CreateDocumentRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreateDocumentResponse:
    """
    Cria documento de texto para o paciente (idempotente pelo hash do conteúdo).

    Requer migração ``002_documents_metadata.sql`` (coluna ``metadata`` em ``documents``).
    Não corre chunking/embeddings automaticamente.
    """
    doc_type = body.doc_type.strip()
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM patients WHERE id = %s", (patient_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")
        try:
            new_id = insert_document_if_new(
                conn,
                patient_id=patient_id,
                doc_type=doc_type,
                content_text=body.content_text,
                source_ref=body.source_ref.strip() if body.source_ref else None,
                metadata=body.metadata,
            )
        except psycopg.errors.UndefinedColumn as e:
            raise HTTPException(
                status_code=503,
                detail="Coluna metadata em falta em documents. Aplica infra/sql/002_documents_metadata.sql",
            ) from e
        if new_id is not None:
            return CreateDocumentResponse(document_id=str(new_id), inserted=True)
        existing = find_document_id_by_content_hash(
            conn,
            patient_id=patient_id,
            doc_type=doc_type,
            content_text=body.content_text,
        )
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail="Documento duplicado mas id não encontrado (estado inconsistente).",
            )
        return CreateDocumentResponse(document_id=str(existing), inserted=False)


@app.get("/v1/patients/{patient_id}/chunks", dependencies=[Depends(require_api_key)])
def list_patient_chunks(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(100, ge=1, le=500),
) -> list[ChunkListItem]:
    with _conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.document_id, c.chunk_index, c.text, c.embedding_model
                FROM chunks c
                WHERE c.patient_id = %s
                ORDER BY c.document_id NULLS LAST, c.chunk_index ASC
                LIMIT %s
                """,
                (patient_id, limit),
            )
            rows = cur.fetchall()
    out: list[ChunkListItem] = []
    for r in rows:
        raw = r.get("text") or ""
        preview = raw if len(raw) <= 400 else raw[:400] + "…"
        did = r.get("document_id")
        out.append(
            ChunkListItem(
                id=str(r["id"]),
                document_id=str(did) if did else None,
                chunk_index=int(r["chunk_index"]),
                text_preview=preview,
                embedding_model=r.get("embedding_model"),
            )
        )
    return out


@app.post(
    "/v1/patients/{patient_id}/retrieve",
    dependencies=[Depends(require_api_key)],
    response_model=RetrieveResponse,
)
def retrieve_chunks(
    patient_id: UUID,
    body: RetrieveRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RetrieveResponse:
    """
    Busca semântica por paciente: embedding da ``query`` + ordem por distância coseno (pgvector).
    Requer migração 004, chunks com ``embedding`` preenchido (``embed_chunks``) e ``OPENAI_API_KEY``.

    Com ``RETRIEVE_EMBEDDING_CACHE_ENABLED`` (default) + Redis, reutiliza o vector da query
    quando o texto normalizado é idêntico ao de um pedido anterior (menos chamadas OpenAI).
    """
    normalized = normalize_query_for_embedding_cache(body.query)
    cached_vec: list[float] | None = None
    embedding_cache_hit = False
    if settings.retrieve_embedding_cache_enabled:
        cached_vec = get_cached_query_embedding(
            redis_url=settings.redis_url,
            patient_id=patient_id,
            normalized_query=normalized,
        )
        if cached_vec is not None:
            embedding_cache_hit = True

    try:
        with _conn(settings) as conn:
            if cached_vec is not None:
                model, row_dicts = patient_retrieve(
                    conn,
                    patient_id=patient_id,
                    query=body.query,
                    k=body.k,
                    settings=settings,
                    exclude_prontuario_placeholder=body.exclude_prontuario_placeholder,
                    min_score=body.min_score,
                    precomputed_query_embedding=cached_vec,
                )
            elif settings.retrieve_embedding_cache_enabled:
                key = settings.openai_api_key
                if not (key and str(key).strip()):
                    raise ValueError("OPENAI_API_KEY em falta")
                fresh_vec = embed_single_query(
                    api_base=settings.openai_api_base,
                    api_key=str(key).strip(),
                    model=settings.openai_embedding_model,
                    text=body.query,
                )
                model, row_dicts = patient_retrieve(
                    conn,
                    patient_id=patient_id,
                    query=body.query,
                    k=body.k,
                    settings=settings,
                    exclude_prontuario_placeholder=body.exclude_prontuario_placeholder,
                    min_score=body.min_score,
                    precomputed_query_embedding=fresh_vec,
                )
                set_cached_query_embedding(
                    redis_url=settings.redis_url,
                    patient_id=patient_id,
                    normalized_query=normalized,
                    embedding=fresh_vec,
                    ttl_seconds=settings.retrieve_embedding_cache_ttl_seconds,
                )
            else:
                model, row_dicts = patient_retrieve(
                    conn,
                    patient_id=patient_id,
                    query=body.query,
                    k=body.k,
                    settings=settings,
                    exclude_prontuario_placeholder=body.exclude_prontuario_placeholder,
                    min_score=body.min_score,
                )
    except ValueError as e:
        raise HTTPException(
            status_code=503,
            detail=str(e) or "Embeddings desactivados: defina OPENAI_API_KEY no .env",
        ) from e
    except RuntimeError as e:
        logger.warning("retrieve: falha ao embeddar query: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao gerar embedding da query: {e!s}",
        ) from e
    except psycopg.errors.UndefinedColumn:
        raise HTTPException(
            status_code=503,
            detail="Coluna embedding em falta. Aplica infra/sql/004_pgvector_chunks_embedding.sql",
        ) from None
    except psycopg.errors.UndefinedFunction:
        raise HTTPException(
            status_code=503,
            detail="Extensão pgvector em falta ou operador inválido. Usa imagem com pgvector e migração 004.",
        ) from None
    hits = [
        RetrieveHit(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            chunk_index=r["chunk_index"],
            distance=r["distance"],
            score=r["score"],
            text=r["text"],
        )
        for r in row_dicts
    ]
    return RetrieveResponse(
        query=body.query,
        embedding_model=model,
        hits=hits,
        embedding_cache_hit=embedding_cache_hit,
    )




@app.post("/hooks/twilio/inbound")
async def twilio_inbound(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """Recebe mensagens WhatsApp dos pacientes — texto ou imagem — e aciona RAG."""
    import asyncio
    form = await request.form()
    from_raw   = str(form.get("From", ""))
    body       = str(form.get("Body", ""))
    num_media  = int(form.get("NumMedia", 0) or 0)
    media_url  = str(form.get("MediaUrl0", "")) or None
    media_type = str(form.get("MediaContentType0", "")) or None

    logger.info("Twilio inbound: from=%s type=%s body=%s", from_raw, "image" if num_media else "text", body[:80])
    # Ignora callbacks vazios do Sandbox (evita loop To==From)
    if from_raw == "whatsapp:+14155238886" and not body.strip() and num_media == 0:
        logger.info("Ignorando callback vazio do Sandbox")
        return {"status": "ignored"}

    # Processa em background para Twilio não reenviar por timeout
    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        None,
        _process_inbound_bg,
        from_raw, body, num_media, media_url, media_type, settings,
    )
    return {"status": "queued"}


def _process_inbound_bg(from_raw, body, num_media, media_url, media_type, settings):
    """Executa o inbound_processor em thread separada (não bloqueia o event loop)."""
    try:
        from nutrideby.agents.inbound_processor import process_inbound
        process_inbound(
            from_raw=from_raw,
            body=body,
            num_media=num_media,
            media_url=media_url,
            media_type=media_type,
            settings=settings,
        )
    except Exception as exc:
        logger.error("inbound_bg error: %s", exc, exc_info=True)



_META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "nutrideby_webhook_2026")
_META_APP_SECRET   = os.getenv("META_APP_SECRET", "")


@app.get("/hooks/whatsapp/inbound")
async def meta_whatsapp_verify(request: Request) -> Response:
    """Verificação do webhook Meta WhatsApp Business API."""
    mode      = request.query_params.get("hub.mode")
    token     = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")

    if mode == "subscribe" and token == _META_VERIFY_TOKEN:
        logger.info("Meta WhatsApp webhook verificado com sucesso")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("Meta WhatsApp webhook: token inválido ou mode errado — mode=%s", mode)
    raise HTTPException(status_code=403, detail="Token de verificação inválido")


@app.post("/hooks/whatsapp/inbound")
async def meta_whatsapp_inbound(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """Recebe mensagens WhatsApp Business da Meta e aciona RAG."""
    import asyncio
    raw_body = await request.body()

    # HMAC-SHA256 — valida assinatura Meta quando META_APP_SECRET está configurado
    if _META_APP_SECRET:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected   = "sha256=" + _hmac.new(_META_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, sig_header):
            logger.warning("Meta WhatsApp: assinatura HMAC-SHA256 inválida")
            raise HTTPException(status_code=401, detail="Assinatura inválida")

    try:
        payload = json.loads(raw_body)
    except Exception:
        payload = {}

    # Extrai mensagem do envelope Meta
    from_raw   = ""
    body       = ""
    num_media  = 0
    media_url  = None
    media_type = None

    try:
        entry    = (payload.get("entry") or [{}])[0]
        changes  = (entry.get("changes") or [{}])[0]
        value    = changes.get("value") or {}
        messages = value.get("messages") or []
        if messages:
            msg        = messages[0]
            from_raw   = msg.get("from", "")
            msg_type   = msg.get("type", "text")
            if msg_type == "text":
                body = (msg.get("text") or {}).get("body", "")
            elif msg_type in ("image", "audio", "video", "document"):
                num_media  = 1
                media_info = msg.get(msg_type) or {}
                media_url  = media_info.get("link") or media_info.get("url") or media_info.get("id")
                media_type = f"{msg_type}/*"
    except Exception as exc:
        logger.warning("Meta WhatsApp: erro ao parsear payload — %s", exc)

    if not from_raw:
        return {"status": "ignored", "reason": "no_message"}

    logger.info("Meta WhatsApp inbound: from=%s type=%s body=%s", from_raw, "image" if num_media else "text", body[:80])

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        None,
        _process_inbound_bg,
        from_raw, body, num_media, media_url, media_type, settings,
    )
    return {"status": "ok"}

@app.get("/v1/conversas")
async def listar_conversas(settings: Annotated[Settings, Depends(get_settings)]) -> list:
    """Lista respostas dos pacientes para o dashboard."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    id,
                    payload->>'from' as telefone,
                    payload->>'body' as mensagem,
                    payload->>'received_at' as recebido_em,
                    received_at as created_at
                FROM integration_webhook_inbox
                WHERE source = 'twilio_inbound'
                ORDER BY received_at DESC
                LIMIT 100
            """)
            return cur.fetchall()



# ── Tenant white-label config (dinâmico — banco de dados) ────────────────────

@app.get("/tenant/{tenant_id}/config")
def get_tenant_config(
    tenant_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, tenant_slug, nome_agente,
                       cor_primaria, cor_secundaria, logo_url,
                       mensagem_boas_vindas, numero_whatsapp
                FROM professional_nutricionistas
                WHERE tenant_slug = %s AND is_active = true
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' não encontrado")
    return {
        "tenant_id":            row["tenant_slug"],
        "nutricionista_nome":   row["name"],
        "nome_agente":          row["nome_agente"] or f"Assistente da {row['name']}",
        "cor_primaria":         row["cor_primaria"] or "#2ECC71",
        "cor_secundaria":       row["cor_secundaria"] or "#1A5C3A",
        "logo_url":             row["logo_url"],
        "mensagem_boas_vindas": row["mensagem_boas_vindas"] or f"Olá! Sou a assistente da {row['name']}.",
        "numero_whatsapp":      row["numero_whatsapp"],
    }


# ── /v1/chat models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    patient_id: str
    message: str
    message_type: str = Field(default="text", pattern="^(text|image|audio)$")


class ChatResponse(BaseModel):
    reply: str
    updated_at: str


class ChatHistoryItem(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    created_at: str


# ── POST /v1/chat ─────────────────────────────────────────────────────────────

@app.post("/v1/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: str | None = Header(None),
) -> ChatResponse:
    from nutrideby.api.mobile_api import _get_patient_from_token
    from nutrideby.agents import patient_engine

    token_data = _get_patient_from_token(authorization, settings)
    if token_data["sub"] != body.patient_id:
        raise HTTPException(status_code=403, detail="Acesso negado")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name, metadata FROM patients WHERE id = %s",
                (body.patient_id,),
            )
            patient = cur.fetchone()
        if not patient:
            raise HTTPException(status_code=404, detail="Paciente não encontrado")

        patient_dict = {
            "id": str(patient["id"]),
            "display_name": patient.get("display_name"),
            "metadata": patient.get("metadata") or {},
        }

        try:
            reply_text, _ = patient_engine.route(
                patient=patient_dict,
                phone=f"app:{body.patient_id}",
                body=body.message,
                msg_type=body.message_type,
                media_url=None,
                media_type=None,
                conn=conn,
                settings=settings,
            )
        except Exception as exc:
            logger.error("chat route error: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Erro ao processar mensagem: {exc}") from exc

        now = datetime.now()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inbound_messages
                  (patient_id, phone, message_type, body, reply_body, replied_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (body.patient_id, f"app:{body.patient_id}", body.message_type,
                 body.message, reply_text, now),
            )
            conn.commit()

    return ChatResponse(reply=reply_text, updated_at=now.isoformat())


# ── GET /v1/chat/history/{patient_id} ─────────────────────────────────────────

@app.get("/v1/chat/history/{patient_id}", response_model=list[ChatHistoryItem])
def chat_history(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: str | None = Header(None),
) -> list[ChatHistoryItem]:
    from nutrideby.api.mobile_api import _get_patient_from_token

    token_data = _get_patient_from_token(authorization, settings)
    if token_data["sub"] != patient_id:
        raise HTTPException(status_code=403, detail="Acesso negado")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT body, reply_body, received_at
                FROM inbound_messages
                WHERE patient_id = %s
                ORDER BY received_at DESC
                LIMIT 20
                """,
                (patient_id,),
            )
            rows = cur.fetchall()

    history: list[ChatHistoryItem] = []
    for r in reversed(rows):
        ts = r["received_at"].isoformat() if r.get("received_at") else ""
        if r.get("body"):
            history.append(ChatHistoryItem(role="user", content=r["body"], created_at=ts))
        if r.get("reply_body"):
            history.append(ChatHistoryItem(role="assistant", content=r["reply_body"], created_at=ts))
    return history

# ── Evolução do Paciente ───────────────────────────────────────────────────────

class WeeklyCalories(BaseModel):
    week: str
    days_logged: int
    avg_calories: float
    avg_protein: float


class BodyScanSummary(BaseModel):
    id: str
    created_at: str
    body_fat_pct: float | None
    muscle_mass_pct: float | None
    lean_mass_kg: float | None
    analysis_notes: str | None


class MedidaSummary(BaseModel):
    descricao: str | None
    data: str | None
    peso_kg: float | None
    imc: float | None


class PatientEvolution(BaseModel):
    patient_id: str
    display_name: str | None
    streak: int
    longest_streak: int
    deby_level: int
    deby_xp: int
    calories_target: float | None
    protein_target: float | None
    weekly_calories: list[WeeklyCalories]
    body_scans: list[BodyScanSummary]
    medidas: list[MedidaSummary]
    total_food_logs_30d: int


@app.get(
    "/v1/patients/{patient_id}/evolution",
    dependencies=[Depends(require_api_key)],
    response_model=PatientEvolution,
)
def get_patient_evolution(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    days: int = Query(90, ge=7, le=365),
):
    """Dados de evolução do paciente: food logs semanais, body scans e medidas."""
    with _conn(settings) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Perfil do paciente
            cur.execute(
                """
                SELECT display_name, current_streak, longest_streak,
                       deby_level, deby_xp, daily_calories_target, daily_protein_target
                FROM patients WHERE id = %s
                """,
                (patient_id,),
            )
            p = cur.fetchone()
            if not p:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")

            # Food logs — agregação semanal
            cur.execute(
                """
                SELECT
                    to_char(date_trunc('week', logged_at), 'IYYY-"W"IW') AS week,
                    COUNT(DISTINCT logged_at::date)::int AS days_logged,
                    ROUND(AVG(total_calories)::numeric, 1) AS avg_calories,
                    ROUND(AVG(total_protein)::numeric, 1) AS avg_protein
                FROM food_logs
                WHERE patient_id = %s
                  AND logged_at >= NOW() - make_interval(days => %s)
                GROUP BY date_trunc('week', logged_at)
                ORDER BY date_trunc('week', logged_at)
                """,
                (patient_id, days),
            )
            weekly = cur.fetchall()

            # Total logs últimos 30 dias
            cur.execute(
                "SELECT COUNT(*)::int AS n FROM food_logs WHERE patient_id = %s AND logged_at >= NOW() - INTERVAL '30 days'",
                (patient_id,),
            )
            total_30d = (cur.fetchone() or {}).get("n", 0)

            # Body scans
            cur.execute(
                """
                SELECT id, created_at, body_fat_pct, muscle_mass_pct, lean_mass_kg, analysis_notes
                FROM body_scans
                WHERE patient_id = %s AND status = 'done'
                ORDER BY created_at DESC LIMIT 10
                """,
                (patient_id,),
            )
            scans = cur.fetchall()

            # Medidas Dietbox
            cur.execute(
                """
                SELECT descricao, data_avaliacao, payload
                FROM dietbox_medidas
                WHERE patient_id = %s
                ORDER BY data_avaliacao DESC LIMIT 6
                """,
                (patient_id,),
            )
            medidas_raw = cur.fetchall()

    import json as _json

    def _parse_medida(m: dict) -> MedidaSummary:
        payload = m.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}
        peso = payload.get("Peso") or payload.get("peso") or payload.get("weight")
        imc = payload.get("IMC") or payload.get("imc") or payload.get("bmi")
        return MedidaSummary(
            descricao=m.get("descricao"),
            data=m["data_avaliacao"].isoformat() if m.get("data_avaliacao") else None,
            peso_kg=float(peso) if peso is not None else None,
            imc=float(imc) if imc is not None else None,
        )

    return PatientEvolution(
        patient_id=str(patient_id),
        display_name=p.get("display_name"),
        streak=p.get("current_streak") or 0,
        longest_streak=p.get("longest_streak") or 0,
        deby_level=p.get("deby_level") or 1,
        deby_xp=p.get("deby_xp") or 0,
        calories_target=p.get("daily_calories_target"),
        protein_target=p.get("daily_protein_target"),
        weekly_calories=[
            WeeklyCalories(
                week=w["week"],
                days_logged=w["days_logged"],
                avg_calories=float(w["avg_calories"] or 0),
                avg_protein=float(w["avg_protein"] or 0),
            )
            for w in weekly
        ],
        body_scans=[
            BodyScanSummary(
                id=str(s["id"]),
                created_at=s["created_at"].isoformat() if s.get("created_at") else "",
                body_fat_pct=float(s["body_fat_pct"]) if s.get("body_fat_pct") is not None else None,
                muscle_mass_pct=float(s["muscle_mass_pct"]) if s.get("muscle_mass_pct") is not None else None,
                lean_mass_kg=float(s["lean_mass_kg"]) if s.get("lean_mass_kg") is not None else None,
                analysis_notes=s.get("analysis_notes"),
            )
            for s in scans
        ],
        medidas=[_parse_medida(m) for m in medidas_raw],
        total_food_logs_30d=int(total_30d or 0),
    )


# ── Q&A com IA sobre o Paciente ───────────────────────────────────────────────

class AskPatientRequest(BaseModel):
    question: str


class AskPatientResponse(BaseModel):
    answer: str


@app.post(
    "/v1/patients/{patient_id}/ask",
    dependencies=[Depends(require_api_key)],
    response_model=AskPatientResponse,
)
def ask_patient(
    patient_id: UUID,
    body: AskPatientRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Responde perguntas da nutricionista sobre um paciente usando Claude Vision + contexto."""
    import json as _json
    import ssl as _ssl
    import urllib.error as _uerr
    import urllib.request as _ureq

    with _conn(settings) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Perfil
            cur.execute(
                """
                SELECT display_name, current_streak, longest_streak, deby_level,
                       daily_calories_target, daily_protein_target, subscription_status,
                       daily_carbs_target, daily_fat_target
                FROM patients WHERE id = %s
                """,
                (patient_id,),
            )
            patient = cur.fetchone()
            if not patient:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")

            # Últimos 14 dias de food logs (diário)
            cur.execute(
                """
                SELECT
                    logged_at::date AS dia,
                    COUNT(*)::int AS refeicoes,
                    ROUND(SUM(total_calories)::numeric, 0) AS calorias,
                    ROUND(SUM(total_protein)::numeric, 1) AS proteina
                FROM food_logs
                WHERE patient_id = %s AND logged_at >= NOW() - INTERVAL '14 days'
                GROUP BY logged_at::date
                ORDER BY dia DESC
                """,
                (patient_id,),
            )
            food_dias = cur.fetchall()

            # Body scan mais recente
            cur.execute(
                """
                SELECT body_fat_pct, muscle_mass_pct, lean_mass_kg, analysis_notes, created_at
                FROM body_scans
                WHERE patient_id = %s AND status = 'done'
                ORDER BY created_at DESC LIMIT 1
                """,
                (patient_id,),
            )
            ultimo_scan = cur.fetchone()

            # Última medida Dietbox
            cur.execute(
                """
                SELECT descricao, data_avaliacao, payload
                FROM dietbox_medidas
                WHERE patient_id = %s
                ORDER BY data_avaliacao DESC LIMIT 1
                """,
                (patient_id,),
            )
            ultima_medida = cur.fetchone()

            # Documentos clínicos (resumo)
            cur.execute(
                """
                SELECT doc_type, LEFT(content_text, 300) AS snippet, collected_at
                FROM documents
                WHERE patient_id = %s
                ORDER BY collected_at DESC LIMIT 5
                """,
                (patient_id,),
            )
            docs = cur.fetchall()

    # Constrói contexto
    nome = patient.get("display_name") or "Paciente"
    streak = patient.get("current_streak") or 0
    meta_cal = patient.get("daily_calories_target")
    meta_prot = patient.get("daily_protein_target")

    food_summary = ""
    if food_dias:
        for d in food_dias:
            dia_str = d["dia"].isoformat() if hasattr(d["dia"], "isoformat") else str(d["dia"])
            food_summary += f"  {dia_str}: {d['refeicoes']} refeições, {d['calorias']} kcal, {d['proteina']}g proteína\n"
    else:
        food_summary = "  Nenhum registro de alimentação nos últimos 14 dias.\n"

    scan_ctx = ""
    if ultimo_scan:
        scan_dt = ultimo_scan["created_at"].isoformat() if ultimo_scan.get("created_at") else "?"
        scan_ctx = (
            f"Último bodyscan ({scan_dt}): "
            f"{ultimo_scan.get('body_fat_pct')}% gordura, "
            f"{ultimo_scan.get('muscle_mass_pct')}% músculo. "
            f"Notas: {ultimo_scan.get('analysis_notes') or 'Sem notas'}"
        )
    else:
        scan_ctx = "Nenhum bodyscan realizado."

    medida_ctx = ""
    if ultima_medida:
        payload = ultima_medida.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}
        peso = payload.get("Peso") or payload.get("peso")
        medida_ctx = f"Última medida ({ultima_medida.get('descricao')}): peso {peso} kg" if peso else ""

    docs_ctx = ""
    for d in docs:
        docs_ctx += f"[{d.get('doc_type')}] {d.get('snippet', '')}\n"

    context_prompt = f"""Você é uma assistente de nutrição especializada auxiliando a nutricionista Dra. Débora.
Responda de forma clara, objetiva e profissional. Use no máximo 3-4 parágrafos.
Baseia-se SOMENTE nos dados fornecidos. Se não houver dados suficientes, diga isso explicitamente.

=== DADOS DO PACIENTE: {nome} ===
Sequência atual: {streak} dias
Metas diárias: {meta_cal or '—'} kcal / {meta_prot or '—'}g proteína
Subscription: {patient.get('subscription_status')}

=== ALIMENTAÇÃO ÚLTIMOS 14 DIAS ===
{food_summary}
=== COMPOSIÇÃO CORPORAL ===
{scan_ctx}
{medida_ctx}

=== DOCUMENTOS CLÍNICOS RECENTES ===
{docs_ctx or 'Sem documentos clínicos.'}

=== PERGUNTA DA NUTRICIONISTA ===
{body.question}"""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY não configurada")

    req_body = _json.dumps({
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": context_prompt}],
    }).encode("utf-8")

    req = _ureq.Request("https://api.anthropic.com/v1/messages", data=req_body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    ctx = _ssl.create_default_context()

    try:
        with _ureq.urlopen(req, timeout=60, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        answer = _json.loads(raw)["content"][0]["text"].strip()
    except _uerr.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise HTTPException(status_code=502, detail=f"Claude API {e.code}: {detail[:200]}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro IA: {exc}")

    return AskPatientResponse(answer=answer)


# ── Sistema de Retenção de Pacientes ─────────────────────────────────────────


# ── Sistema de Retenção de Pacientes ─────────────────────────────────────────

class PatientRetentionStatus(BaseModel):
    patient_id: str
    display_name: Optional[str]
    risk_level: str
    days_without_log: int
    streak: int
    logs_30d: int
    last_logged_at: Optional[str]


class SendIncentiveResponse(BaseModel):
    patient_id: str
    message: str
    injected: bool


@app.get("/v1/patients/retention/at-risk", dependencies=[Depends(require_api_key)])
def get_at_risk_patients(
    limit: int = 50,
    settings: Annotated[Settings, Depends(get_settings)] = ...,
):
    with _conn(settings) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    p.id,
                    p.display_name,
                    COALESCE(p.current_streak, 0) AS streak,
                    MAX(fl.logged_at) AS last_log,
                    EXTRACT(DAY FROM NOW() - MAX(fl.logged_at)) AS days_without
                FROM patients p
                LEFT JOIN food_logs fl ON fl.patient_id = p.id
                GROUP BY p.id, p.display_name, p.current_streak
                HAVING MAX(fl.logged_at) IS NULL
                    OR MAX(fl.logged_at) < NOW() - INTERVAL '1 day'
                ORDER BY last_log ASC NULLS FIRST
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

    result = []
    for r in rows:
        days = int(r["days_without"] or 999)
        risk = "yellow" if days <= 4 else "red"
        result.append({
            "patient_id": str(r["id"]),
            "display_name": r["display_name"],
            "streak": r["streak"],
            "days_without_log": days,
            "risk_level": risk,
            "last_logged_at": r["last_log"].isoformat() if r["last_log"] else None,
        })
    return result


@app.get(
    "/v1/patients/{patient_id}/retention",
    response_model=PatientRetentionStatus,
    dependencies=[Depends(require_api_key)],
)
def get_patient_retention(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)] = ...,
):
    with _conn(settings) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT MAX(logged_at) AS last_log,
                       COUNT(*) FILTER (WHERE logged_at >= NOW() - INTERVAL '30 days') AS logs_30d
                FROM food_logs WHERE patient_id = %s
            """, (patient_id,))
            log_row = cur.fetchone()

            cur.execute("""
                SELECT current_streak, display_name FROM patients WHERE id = %s
            """, (patient_id,))
            patient = cur.fetchone()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    last_log = log_row["last_log"] if log_row else None
    if last_log:
        days_without = (datetime.now(tz=last_log.tzinfo) - last_log).days
    else:
        days_without = 999

    risk_level = "green" if days_without <= 1 else ("yellow" if days_without <= 4 else "red")

    return PatientRetentionStatus(
        patient_id=str(patient_id),
        display_name=patient["display_name"],
        risk_level=risk_level,
        days_without_log=min(days_without, 999),
        streak=patient["current_streak"] or 0,
        logs_30d=log_row["logs_30d"] if log_row else 0,
        last_logged_at=last_log.isoformat() if last_log else None,
    )


@app.post(
    "/v1/patients/{patient_id}/send-incentive",
    response_model=SendIncentiveResponse,
    dependencies=[Depends(require_api_key)],
)
def send_patient_incentive(
    patient_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)] = ...,
):
    import json as _json
    import ssl as _ssl
    import urllib.request as _ureq

    with _conn(settings) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT display_name, current_streak, longest_streak, deby_level
                FROM patients WHERE id = %s
            """, (patient_id,))
            patient = cur.fetchone()
            if not patient:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")

            cur.execute("""
                SELECT MAX(logged_at) AS last_log,
                       COUNT(*) FILTER (WHERE logged_at >= NOW() - INTERVAL '30 days') AS logs_30d
                FROM food_logs WHERE patient_id = %s
            """, (patient_id,))
            log_row = cur.fetchone()

            cur.execute("""
                SELECT content_text AS content_preview FROM documents
                WHERE patient_id = %s AND doc_type = 'dietbox_meta_export'
                ORDER BY collected_at DESC LIMIT 1
            """, (patient_id,))
            goal_doc = cur.fetchone()

    nome = patient["display_name"] or "paciente"
    primeiro_nome = nome.split()[0]
    streak = patient["current_streak"] or 0
    longest = patient["longest_streak"] or 0
    nivel = patient["deby_level"] or 1
    logs_30d = log_row["logs_30d"] if log_row else 0

    dias_sem = 0
    if log_row and log_row["last_log"]:
        ll = log_row["last_log"]
        dias_sem = (datetime.now(tz=ll.tzinfo) - ll).days

    goal_snippet = ""
    if goal_doc:
        try:
            meta = _json.loads(goal_doc["content_preview"])
            items = meta.get("items", [])
            if items:
                goal_snippet = f"Meta principal: {items[0].get('nome', '')}"
        except Exception:
            pass

    prompt = (
        f"Você é a assistente nutricional da Dra. Débora. Escreva UMA mensagem de incentivo "
        f"personalizada para {nome}, que está há {dias_sem} dia(s) sem registrar refeições.\n\n"
        f"Contexto:\n"
        f"- Maior sequência já alcançada: {longest} dias\n"
        f"- Sequência atual: {streak} dias\n"
        f"- Registros nos últimos 30 dias: {logs_30d}\n"
        f"- Nível no app: {nivel}\n"
        f"{goal_snippet}\n\n"
        f"Regras: máximo 3 frases curtas, tom caloroso e motivador sem julgamento, "
        f"comece com o primeiro nome, não cite marcas, máximo 1 emoji."
    )

    api_key_ai = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()

    fallback = (
        f"{primeiro_nome}, sentimos sua falta! "
        + (f"Você já ficou {longest} dias em sequência — isso prova que você consegue. " if longest > 3 else "")
        + "Que tal retomar hoje com um registro simples?"
    )

    if api_key_ai:
        req_body = _json.dumps({
            "model": model,
            "max_tokens": 150,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req_obj = _ureq.Request("https://api.anthropic.com/v1/messages", data=req_body, method="POST")
        req_obj.add_header("Content-Type", "application/json")
        req_obj.add_header("x-api-key", api_key_ai)
        req_obj.add_header("anthropic-version", "2023-06-01")
        ctx = _ssl.create_default_context()
        try:
            with _ureq.urlopen(req_obj, timeout=30, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            message = _json.loads(raw)["content"][0]["text"].strip()
        except Exception:
            message = fallback
    else:
        message = fallback

    with _conn(settings) as conn:
        conn.execute("""
            INSERT INTO inbound_messages (patient_id, phone, channel, message_type, reply_body)
            VALUES (%s, 'incentive', 'incentive', 'text', %s)
        """, (str(patient_id), message))
        conn.commit()

    return SendIncentiveResponse(patient_id=str(patient_id), message=message, injected=True)
