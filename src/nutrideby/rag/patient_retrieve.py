"""
Recuperação semântica por ``patient_id`` (embedding da query + pgvector ``<=>``).
Usado pela API e pelo worker ``rag_demo``.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from nutrideby.clients.openai_embeddings import embed_single_query, format_vector_for_pg
from nutrideby.config import Settings

# Chunks com texto ``[Prontuário: API 204%`` vêm de resposta Dietbox 204 sem corpo.


def _sql_retrieve(exclude_prontuario_placeholder: bool) -> str:
    ph = (
        " AND (coalesce(c.text, '') NOT LIKE '[Prontuário: API 204%') "
        if exclude_prontuario_placeholder
        else ""
    )
    return f"""
    SELECT c.id, c.document_id, c.chunk_index, c.text,
           (c.embedding <=> %s::vector)::float AS distance
    FROM chunks c
    WHERE c.patient_id = %s
      AND c.embedding IS NOT NULL
      {ph}
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
"""


def patient_retrieve(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    query: str,
    k: int,
    settings: Settings,
    exclude_prontuario_placeholder: bool = True,
    min_score: float | None = None,
    precomputed_query_embedding: list[float] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Devolve ``(embedding_model, hits)`` onde cada hit tem
    chunk_id, document_id, chunk_index, distance, score, text.

    ``exclude_prontuario_placeholder``: remove da candidatura chunks cujo texto
    é o marcador de prontuário 204 (sem corpo útil para RAG).

    ``min_score``: filtra por ``1/(1+distance)``; quando definido, lê mais linhas
    da base até preencher ``k`` hits ou esgotar o limite interno.

    ``precomputed_query_embedding``: se definido, não volta a chamar a API de
    embeddings (útil para lote ``--all-dietbox`` com a mesma pergunta).
    """
    if min_score is not None and not (0.0 <= min_score <= 1.0):
        raise ValueError("min_score deve estar entre 0 e 1")
    model = settings.openai_embedding_model
    if precomputed_query_embedding is not None:
        vec = precomputed_query_embedding
    else:
        key = settings.openai_api_key
        if not (key and str(key).strip()):
            raise ValueError("OPENAI_API_KEY em falta")
        vec = embed_single_query(
            api_base=settings.openai_api_base,
            api_key=str(key),
            model=model,
            text=query,
        )
    lit = format_vector_for_pg(vec)
    fetch_limit = k
    if min_score is not None:
        fetch_limit = min(500, max(50, k * 20))
    sql = _sql_retrieve(exclude_prontuario_placeholder)
    with conn.cursor() as cur:
        cur.execute(sql, (lit, patient_id, lit, fetch_limit))
        rows = cur.fetchall()
    hits: list[dict[str, Any]] = []
    for r in rows:
        dist = float(r.get("distance") or 0.0)
        score = 1.0 / (1.0 + dist) if dist >= 0 else 0.0
        if min_score is not None and score < min_score:
            continue
        raw = r.get("text") or ""
        if len(raw) > 8000:
            raw = raw[:8000] + "…"
        did = r.get("document_id")
        hits.append(
            {
                "chunk_id": str(r["id"]),
                "document_id": str(did) if did else None,
                "chunk_index": int(r["chunk_index"]),
                "distance": dist,
                "score": score,
                "text": raw,
            }
        )
        if len(hits) >= k:
            break
    return model, hits
