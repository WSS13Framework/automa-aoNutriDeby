"""Persistência de webhooks recebidos (Kiwify, etc.)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Json


def insert_webhook_inbox(
    conn: psycopg.Connection,
    *,
    source: str,
    payload: Any,
    headers_meta: dict[str, Any] | None = None,
) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO integration_webhook_inbox (source, payload, headers_meta)
            VALUES (%s, %s::jsonb, %s::jsonb)
            RETURNING id
            """,
            (source, Json(payload), Json(headers_meta or {})),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]
