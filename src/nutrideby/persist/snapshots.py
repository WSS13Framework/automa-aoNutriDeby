"""Persistência de snapshots JSON por chave (subscription Dietbox, etc.)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION = "dietbox_nutritionist_subscription"


def upsert_external_snapshot(
    conn: psycopg.Connection,
    *,
    key: str,
    payload: Any,
    http_status: int | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO external_snapshots (key, payload, fetched_at, http_status)
            VALUES (%s, %s::jsonb, now(), %s)
            ON CONFLICT (key) DO UPDATE SET
                payload = EXCLUDED.payload,
                fetched_at = now(),
                http_status = EXCLUDED.http_status
            """,
            (key, Json(payload), http_status),
        )


def get_external_snapshot(
    conn: psycopg.Connection,
    *,
    key: str,
) -> tuple[Any, str | None, int | None] | None:
    """Devolve (payload, fetched_at iso, http_status) ou None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT payload, fetched_at::text, http_status
            FROM external_snapshots
            WHERE key = %s
            """,
            (key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return row[0], row[1], row[2]
