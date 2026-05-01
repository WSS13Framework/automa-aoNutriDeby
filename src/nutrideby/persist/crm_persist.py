from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

import psycopg

logger = logging.getLogger(__name__)


def upsert_patient(
    conn: psycopg.Connection,
    *,
    source_system: str,
    external_id: str,
    display_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID:
    meta = json.dumps(metadata or {})
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patients (source_system, external_id, display_name, metadata)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (source_system, external_id) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, patients.display_name),
                metadata = COALESCE(patients.metadata, '{}'::jsonb)
                    || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
                updated_at = now()
            RETURNING id
            """,
            (source_system, external_id, display_name, meta),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def insert_document_if_new(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    doc_type: str,
    content_text: str,
    source_ref: str | None = None,
) -> uuid.UUID | None:
    h = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (patient_id, doc_type, content_text, content_sha256, source_ref)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (patient_id, doc_type, content_sha256) DO NOTHING
            RETURNING id
            """,
            (patient_id, doc_type, content_text, h, source_ref),
        )
        row = cur.fetchone()
        if row is None:
            logger.info(
                "Documento duplicado ignorado (patient=%s doc_type=%s sha=%s…)",
                patient_id,
                doc_type,
                h[:12],
            )
            return None
        return row[0]
