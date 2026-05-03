"""
Preenche ``chunks.embedding`` via API OpenAI-compatible (``/v1/embeddings``).

  python3 -m nutrideby.workers.embed_chunks --limit 50
  python3 -m nutrideby.workers.embed_chunks --patient-id UUID --limit 200
  python3 -m nutrideby.workers.embed_chunks --force --limit 20

Requer ``DATABASE_URL``, migração ``004_pgvector_chunks_embedding.sql`` e ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

import psycopg
import psycopg.errors

from nutrideby.clients.openai_embeddings import embed_texts, format_vector_for_pg
from nutrideby.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 32


def _select_chunk_rows(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID | None,
    force: bool,
    limit: int,
) -> list[tuple[uuid.UUID, str]]:
    q = """
        SELECT c.id, c.text
        FROM chunks c
        WHERE (%s::uuid IS NULL OR c.patient_id = %s::uuid)
          AND (c.embedding IS NULL OR %s = true)
        ORDER BY c.created_at ASC NULLS LAST, c.id ASC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(q, (patient_id, patient_id, force, limit))
        rows = cur.fetchall()
    out: list[tuple[uuid.UUID, str]] = []
    for r in rows:
        out.append((r[0], str(r[1] or "")))
    return out


def run(
    *,
    limit: int,
    patient_id: uuid.UUID | None,
    batch_size: int,
    force: bool,
    dry_run: bool,
) -> int:
    settings = Settings()
    key = settings.openai_api_key
    if not (key and str(key).strip()):
        logger.error("OPENAI_API_KEY em falta — define no .env para embeddings")
        return 1
    batch_size = max(1, min(batch_size, 128))
    limit = max(1, limit)

    with psycopg.connect(settings.database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT embedding FROM chunks LIMIT 0")
        except psycopg.errors.UndefinedColumn:
            logger.error(
                "Coluna chunks.embedding em falta — aplica infra/sql/004_pgvector_chunks_embedding.sql"
            )
            return 1
        except psycopg.errors.UndefinedTable:
            logger.error("Tabela chunks em falta")
            return 1

        rows = _select_chunk_rows(
            conn, patient_id=patient_id, force=force, limit=limit
        )
        if not rows:
            logger.info("embed_chunks: nada na fila (todos com embedding ou fila vazia)")
            return 0
        logger.info("embed_chunks: fila=%s batch=%s dry_run=%s", len(rows), batch_size, dry_run)
        if dry_run:
            logger.info("embed_chunks: dry-run — não chama API")
            return 0

        processed = 0
        model = settings.openai_embedding_model
        base = settings.openai_api_base
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            ids = [r[0] for r in batch]
            texts = [r[1] for r in batch]
            try:
                vectors = embed_texts(
                    api_base=base,
                    api_key=str(key),
                    model=model,
                    inputs=texts,
                )
            except Exception:
                logger.exception("embed_chunks: falha API no batch offset=%s", i)
                return 1
            with conn.cursor() as cur:
                for cid, vec in zip(ids, vectors, strict=True):
                    lit = format_vector_for_pg(vec)
                    cur.execute(
                        """
                        UPDATE chunks
                        SET embedding = %s::vector, embedding_model = %s
                        WHERE id = %s
                        """,
                        (lit, model, cid),
                    )
                    processed += 1
            conn.commit()
            logger.info("embed_chunks: batch %s-%s gravado", i, i + len(batch))

    logger.info("embed_chunks concluído: chunks=%s", processed)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Embeddings OpenAI-compatible → chunks.embedding")
    p.add_argument("--limit", type=int, default=100, help="Máximo de linhas chunks a processar")
    p.add_argument(
        "--patient-id",
        type=uuid.UUID,
        default=None,
        help="Só chunks deste paciente (UUID interno)",
    )
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH, help="Textos por pedido à API")
    p.add_argument(
        "--force",
        action="store_true",
        help="Recalcular mesmo quando embedding já existe",
    )
    p.add_argument("--dry-run", action="store_true", help="Só contar fila; não chama API")
    args = p.parse_args(argv)
    return run(
        limit=args.limit,
        patient_id=args.patient_id,
        batch_size=args.batch_size,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
