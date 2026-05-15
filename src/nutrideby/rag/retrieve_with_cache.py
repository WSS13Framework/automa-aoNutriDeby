"""RAG por paciente com cache L1 Redis do embedding da query (partilhado com a API)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from nutrideby.clients.openai_embeddings import embed_single_query
from nutrideby.config import Settings
from nutrideby.rag.patient_retrieve import patient_retrieve
from nutrideby.rag.retrieve_embedding_cache import (
    get_cached_query_embedding,
    normalize_query_for_embedding_cache,
    set_cached_query_embedding,
)


def retrieve_patient_chunks(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    query: str,
    k: int,
    settings: Settings,
    exclude_prontuario_placeholder: bool = True,
    min_score: float | None = None,
) -> tuple[str, list[dict[str, Any]], bool]:
    """
    ``(embedding_model, hits, embedding_cache_hit)``.
    ``hits`` no formato de ``patient_retrieve`` (chunk_id, text, score, …).
    """
    normalized = normalize_query_for_embedding_cache(query)
    cached_vec: list[float] | None = None
    embedding_cache_hit = False
    if settings.retrieve_embedding_cache_enabled:
        cached_vec = get_cached_query_embedding(
            redis_url=settings.redis_url,
            patient_id=patient_id,
            normalized_query=normalized,
        )
        if cached_vec is not None:
            embedding_cache_hit = True

    if cached_vec is not None:
        model, hits = patient_retrieve(
            conn,
            patient_id=patient_id,
            query=query,
            k=k,
            settings=settings,
            exclude_prontuario_placeholder=exclude_prontuario_placeholder,
            min_score=min_score,
            precomputed_query_embedding=cached_vec,
        )
        return model, hits, embedding_cache_hit

    if settings.retrieve_embedding_cache_enabled:
        key = settings.openai_api_key
        if not (key and str(key).strip()):
            raise ValueError("OPENAI_API_KEY em falta")
        fresh_vec = embed_single_query(
            api_base=settings.openai_api_base,
            api_key=str(key).strip(),
            model=settings.openai_embedding_model,
            text=query,
        )
        model, hits = patient_retrieve(
            conn,
            patient_id=patient_id,
            query=query,
            k=k,
            settings=settings,
            exclude_prontuario_placeholder=exclude_prontuario_placeholder,
            min_score=min_score,
            precomputed_query_embedding=fresh_vec,
        )
        set_cached_query_embedding(
            redis_url=settings.redis_url,
            patient_id=patient_id,
            normalized_query=normalized,
            embedding=fresh_vec,
            ttl_seconds=settings.retrieve_embedding_cache_ttl_seconds,
        )
        return model, hits, False

    model, hits = patient_retrieve(
        conn,
        patient_id=patient_id,
        query=query,
        k=k,
        settings=settings,
        exclude_prontuario_placeholder=exclude_prontuario_placeholder,
        min_score=min_score,
    )
    return model, hits, embedding_cache_hit
