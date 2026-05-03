"""Upsert de pacientes e inserção idempotente de documentos (Postgres)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Json

logger = logging.getLogger(__name__)


def _row_uuid(row: object | None) -> uuid.UUID | None:
    """Primeira coluna (``id``) com ``dict_row`` ou tupla."""
    if row is None:
        return None
    if isinstance(row, dict):
        v = row.get("id")
        if v is None:
            return None
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    return row[0]  # type: ignore[index]


def upsert_patient(
    conn: psycopg.Connection,
    *,
    source_system: str,
    external_id: str,
    display_name: str | None,
    metadata: dict[str, Any],
) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patients (source_system, external_id, display_name, metadata)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (source_system, external_id) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, patients.display_name),
                metadata = patients.metadata || EXCLUDED.metadata,
                updated_at = now()
            RETURNING id
            """,
            (source_system, external_id, display_name, Json(metadata)),
        )
        row = cur.fetchone()
        assert row is not None
        rid = _row_uuid(row)
        assert rid is not None
        return rid


def insert_document_if_new(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    doc_type: str,
    content_text: str,
    source_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    """Insere documento se o par (patient_id, doc_type, hash do texto) for novo. Requer coluna ``metadata`` (migração 002)."""
    sha = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    meta = metadata if metadata else {}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (patient_id, doc_type, content_text, content_sha256, source_ref, metadata)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (patient_id, doc_type, content_sha256) DO NOTHING
            RETURNING id
            """,
            (patient_id, doc_type, content_text, sha, source_ref, Json(meta)),
        )
        row = cur.fetchone()
        return _row_uuid(row)


def find_document_id_by_content_hash(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    doc_type: str,
    content_text: str,
) -> uuid.UUID | None:
    """Devolve ``id`` do documento existente com o mesmo hash de conteúdo, ou ``None``."""
    sha = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM documents
            WHERE patient_id = %s AND doc_type = %s AND content_sha256 = %s
            LIMIT 1
            """,
            (patient_id, doc_type, sha),
        )
        row = cur.fetchone()
        return _row_uuid(row)


def replace_document_chunks(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    texts: list[str],
    embedding_model: str | None = None,
) -> int:
    """Remove chunks antigos do documento e insere novos índices 0..n-1."""
    clean = [t.strip() for t in texts if t and t.strip()]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        for idx, t in enumerate(clean):
            cur.execute(
                """
                INSERT INTO chunks (patient_id, document_id, chunk_index, text, embedding_model)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (patient_id, document_id, idx, t, embedding_model),
            )
    return len(clean)
