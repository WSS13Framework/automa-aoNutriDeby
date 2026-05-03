"""FastAPI — leitura de `patients` / `documents` para agentes e integrações."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import psycopg
import psycopg.errors
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from nutrideby.config import Settings
from nutrideby.persist.snapshots import (
    KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION,
    get_external_snapshot,
)

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


def get_settings() -> Settings:
    return Settings()


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    expected = settings.nutrideby_api_key
    if not (expected and str(expected).strip()):
        return
    if not x_api_key or x_api_key.strip() != str(expected).strip():
        raise HTTPException(status_code=401, detail="X-API-Key inválida ou em falta")


app = FastAPI(
    title="NutriDeby API leitura",
    version="0.2.0",
    description="Leitura do espelho Postgres (pacientes, documentos).",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
            detail="Sem snapshot; correr: python -m nutrideby.workers.dietbox_sync --sync-subscription",
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
