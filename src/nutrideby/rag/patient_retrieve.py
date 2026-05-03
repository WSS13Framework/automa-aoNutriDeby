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

_SQL = """
    SELECT c.id, c.document_id, c.chunk_index, c.text,
           (c.embedding <=> %s::vector)::float AS distance
    FROM chunks c
    WHERE c.patient_id = %s
      AND c.embedding IS NOT NULL
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
) -> tuple[str, list[dict[str, Any]]]:
    """
    Devolve ``(embedding_model, hits)`` onde cada hit tem
    chunk_id, document_id, chunk_index, distance, score, text.
    """
    key = settings.openai_api_key
    if not (key and str(key).strip()):
        raise ValueError("OPENAI_API_KEY em falta")
    model = settings.openai_embedding_model
    vec = embed_single_query(
        api_base=settings.openai_api_base,
        api_key=str(key),
        model=model,
        text=query,
    )
    lit = format_vector_for_pg(vec)
    with conn.cursor() as cur:
        cur.execute(_SQL, (lit, patient_id, lit, k))
        rows = cur.fetchall()
    hits: list[dict[str, Any]] = []
    for r in rows:
        dist = float(r.get("distance") or 0.0)
        score = 1.0 / (1.0 + dist) if dist >= 0 else 0.0
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
    return model, hits
