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


def fetch_pending_webhooks(conn: psycopg.Connection, *, source: str, limit: int) -> list[tuple]:
    """Retorna lista de tuplas (id, payload) de webhooks pendentes."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, payload FROM integration_webhook_inbox WHERE source=%s AND status=%s ORDER BY received_at ASC LIMIT %s",
            [source, "pending", limit],
        )
        # Converte cada linha em tupla explícita
        result = []
        for row in cur.fetchall():
            if isinstance(row, (list, tuple)):
                result.append((row[0], row[1]))
            else:
                # Se for Row object, acessa como dict
                result.append((row['id'], row['payload']))
        return result

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
