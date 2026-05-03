"""CRUD mínimo para extraction_runs (auditoria e retomada de jobs)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Json

JOB_DIETBOX_PRONTUARIO_BULK = "dietbox_prontuario_bulk"


def create_run(
    conn: psycopg.Connection,
    *,
    cursor_state: dict[str, Any],
    stats: dict[str, Any] | None = None,
) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO extraction_runs (status, cursor_state, stats)
            VALUES ('running', %s::jsonb, %s::jsonb)
            RETURNING id
            """,
            (Json(cursor_state), Json(stats or {})),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def update_run(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    *,
    cursor_state: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    parts: list[str] = []
    vals: list[Any] = []
    if cursor_state is not None:
        parts.append("cursor_state = %s::jsonb")
        vals.append(Json(cursor_state))
    if stats is not None:
        parts.append("stats = extraction_runs.stats || %s::jsonb")
        vals.append(Json(stats))
    if not parts:
        return
    vals.append(run_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE extraction_runs SET {', '.join(parts)} WHERE id = %s",
            vals,
        )


def finish_run(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    *,
    status: str,
    error_message: str | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        if stats:
            cur.execute(
                """
                UPDATE extraction_runs
                SET finished_at = now(),
                    status = %s,
                    error_message = %s,
                    stats = extraction_runs.stats || %s::jsonb
                WHERE id = %s
                """,
                (status, error_message, Json(stats), run_id),
            )
        else:
            cur.execute(
                """
                UPDATE extraction_runs
                SET finished_at = now(),
                    status = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (status, error_message, run_id),
            )


def get_run(conn: psycopg.Connection, run_id: uuid.UUID) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, cursor_state, stats, error_message,
                   started_at::text, finished_at::text
            FROM extraction_runs
            WHERE id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "status": row[1],
            "cursor_state": row[2],
            "stats": row[3],
            "error_message": row[4],
            "started_at": row[5],
            "finished_at": row[6],
        }
