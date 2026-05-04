"""Persistência de metadados de exportações GenAI → Spaces (URL na BD)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg


def insert_genai_analysis_export(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    spaces_url: str,
    persona: str | None = None,
    query_preview: str | None = None,
) -> uuid.UUID:
    """Insere registo com URL do JSON no Spaces. Requer migração ``005_genai_analysis_export.sql``."""
    qprev = (query_preview or "")[:2000] if query_preview else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO genai_analysis_exports (patient_id, spaces_url, persona, query_preview)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (patient_id, spaces_url, persona, qprev),
        )
        row = cur.fetchone()
        assert row is not None
        rid = row[0]
        if not isinstance(rid, uuid.UUID):
            rid = uuid.UUID(str(rid))
        return rid
