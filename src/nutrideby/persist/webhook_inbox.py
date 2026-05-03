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


def fetch_pending_webhooks(
    conn: psycopg.Connection,
    *,
    source: str,
    limit: int,
) -> list[tuple[uuid.UUID, dict[str, Any]]]:
    """``(id, payload)`` com ``status = pending``."""
    limit = max(1, limit)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, payload
            FROM integration_webhook_inbox
            WHERE source = %s AND status = 'pending'
            ORDER BY received_at ASC
            LIMIT %s
            """,
            (source, limit),
        )
        rows = cur.fetchall()
    out: list[tuple[uuid.UUID, dict[str, Any]]] = []
    for r in rows:
        rid, pl = r[0], r[1]
        if not isinstance(pl, dict):
            pl = {}
        out.append((rid, pl))
    return out


def finalize_webhook_inbox(
    conn: psycopg.Connection,
    *,
    row_id: uuid.UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    """Marca linha como processada ou erro (``status`` + ``processed_at``)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE integration_webhook_inbox
            SET status = %s, processed_at = now(), error_message = %s
            WHERE id = %s
            """,
            (status, error_message, row_id),
        )
