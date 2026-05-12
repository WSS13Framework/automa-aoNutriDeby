"""FastAPI — leitura de `patients` / `documents` para agentes e integrações."""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import psycopg
import psycopg.errors
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from nutrideby.clients.openai_embeddings import embed_single_query
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
    version="0.4.3",
    description="Leitura Postgres, ingestão de documentos (texto), RAG retrieval (pgvector) e hooks (ex.: Kiwify).",
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
                WHERE (%s IS NULL OR p.source_system = %s)
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


def _kiwify_path_secret_ok(settings: Settings, secret: str) -> bool:
    expected = settings.kiwify_webhook_path_secret
    if not (expected and str(expected).strip()):
        return False
    a, b = str(secret).strip(), str(expected).strip()
    if len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


@app.post("/hooks/kiwify/{secret}")
async def kiwify_webhook(
    secret: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """
    Receptor Kiwify (MVP): grava JSON bruto em ``integration_webhook_inbox``.

    Configura ``KIWIFY_WEBHOOK_PATH_SECRET`` e na Kiwify usa a URL
    ``https://<teu-host>/hooks/kiwify/<mesmo_segredo>``.
    """
    if not (settings.kiwify_webhook_path_secret and str(settings.kiwify_webhook_path_secret).strip()):
        raise HTTPException(
            status_code=503,
            detail="Webhook Kiwify desactivado: defina KIWIFY_WEBHOOK_PATH_SECRET no .env",
        )
    if not _kiwify_path_secret_ok(settings, secret):
        raise HTTPException(status_code=401, detail="Segredo do path inválido")
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corpo JSON inválido") from None
    headers_meta: dict[str, Any] = {}
    for key in ("user-agent", "x-forwarded-for", "content-type"):
        if key in request.headers:
            headers_meta[key] = request.headers[key]
    try:
        with psycopg.connect(settings.database_url) as conn:
            wid = insert_webhook_inbox(
                conn,
                source="kiwify",
                payload=body if isinstance(body, (dict, list)) else {"_value": body},
                headers_meta=headers_meta,
            )
    except psycopg.errors.UndefinedTable as e:
        raise HTTPException(
            status_code=503,
            detail="Tabela integration_webhook_inbox em falta. Aplica infra/sql/003_integration_webhook_inbox.sql",
        ) from e
    logger.info("kiwify webhook gravado id=%s", wid)
    return {"received": True, "id": str(wid)}
