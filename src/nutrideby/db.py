from __future__ import annotations

import logging

import psycopg

logger = logging.getLogger(__name__)


def check_connection(dsn: str) -> bool:
    """Retorna True se o PostgreSQL responde; loga erro e retorna False em falha."""
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        logger.exception("Falha ao conectar ao PostgreSQL")
        return False
