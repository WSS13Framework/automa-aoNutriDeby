"""
Cache L1 (exact-match) do vetor de embedding da *query* para ``/v1/patients/.../retrieve``.

Chave: paciente + texto normalizado (strip, minúsculas, espaços colapsados).
Valor: JSON do vector OpenAI (mesmo modelo dos chunks) — reutiliza ``precomputed_query_embedding``.

Não mistura com modelo leve (MiniLM): isso seria L2 / cache semântico (futuro).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_RE_WS = re.compile(r"\s+")

# Uma ligação por processo (uvicorn worker); URL tipicamente fixa no .env
_redis_conn: Any | None = None
_redis_conn_url: str | None = None


def _redis_singleton(url: str) -> Any | None:
    global _redis_conn, _redis_conn_url
    if not url or not str(url).strip():
        return None
    if _redis_conn is not None and _redis_conn_url == url:
        return _redis_conn
    try:
        import redis as redis_lib
    except ImportError:
        logger.warning("pacote redis não instalado — cache de embedding desactivado")
        return None
    try:
        _redis_conn = redis_lib.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2.0
        )
        _redis_conn_url = url
        _redis_conn.ping()
        return _redis_conn
    except Exception as e:
        _redis_conn = None
        _redis_conn_url = None
        logger.warning("Redis indisponível (%s) — cache de embedding desactivado", e)
        return None


def normalize_query_for_embedding_cache(query: str) -> str:
    """Normalização conservadora para hits exact-match entre variações triviais."""
    s = (query or "").strip().lower()
    return _RE_WS.sub(" ", s).strip()


def cache_key_embedding(patient_id: UUID, normalized_query: str) -> str:
    h = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
    return f"nutrideby:retrieve:emb:{patient_id}:{h}"


def get_cached_query_embedding(
    *,
    redis_url: str,
    patient_id: UUID,
    normalized_query: str,
) -> list[float] | None:
    r = _redis_singleton(redis_url)
    if r is None:
        return None
    key = cache_key_embedding(patient_id, normalized_query)
    try:
        raw = r.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, list):
            return None
        return [float(x) for x in data]
    except Exception as e:
        logger.warning("retrieve cache read falhou: %s", e)
        return None


def set_cached_query_embedding(
    *,
    redis_url: str,
    patient_id: UUID,
    normalized_query: str,
    embedding: list[float],
    ttl_seconds: int,
) -> None:
    if ttl_seconds <= 0:
        return
    r = _redis_singleton(redis_url)
    if r is None:
        return
    key = cache_key_embedding(patient_id, normalized_query)
    try:
        payload = json.dumps(embedding)
        r.setex(key, ttl_seconds, payload)
    except Exception as e:
        logger.warning("retrieve cache write falhou: %s", e)
