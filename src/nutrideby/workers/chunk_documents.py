"""
Segmenta ``documents.content_text`` na tabela ``chunks`` (sem embeddings / FAISS).

  python3 -m nutrideby.workers.chunk_documents --limit 20
  python3 -m nutrideby.workers.chunk_documents --doc-type dietbox_prontuario --limit 50
  python3 -m nutrideby.workers.chunk_documents --patient-id UUID --force

Requer ``DATABASE_URL``. Por omissão ignora documentos que já têm linhas em ``chunks``
(a menos que ``--force``).
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

import psycopg

from nutrideby.config import Settings
from nutrideby.persist.crm_persist import replace_document_chunks
from nutrideby.text_chunking import chunk_text

logger = logging.getLogger(__name__)


def _select_documents(
    conn: psycopg.Connection,
    *,
    limit: int,
    doc_type: str | None,
    patient_id: uuid.UUID | None,
    force: bool,
) -> list[tuple[uuid.UUID, uuid.UUID, str, str]]:
    parts = [
        "SELECT d.id, d.patient_id, d.content_text, d.doc_type",
        "FROM documents d",
        "WHERE 1=1",
    ]
    params: list[object] = []
    if not force:
        parts.append("AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.id)")
    if doc_type:
        parts.append("AND d.doc_type = %s")
        params.append(doc_type)
    if patient_id is not None:
        parts.append("AND d.patient_id = %s")
        params.append(patient_id)
    parts.append("ORDER BY d.collected_at DESC")
    parts.append("LIMIT %s")
    params.append(limit)
    q = " ".join(parts)
    with conn.cursor() as cur:
        cur.execute(q, params)
        rows = cur.fetchall()
    out: list[tuple[uuid.UUID, uuid.UUID, str, str]] = []
    for r in rows:
        out.append((r[0], r[1], str(r[2] or ""), str(r[3] or "")))
    return out


def run(
    *,
    limit: int,
    doc_type: str | None,
    patient_id: uuid.UUID | None,
    max_chars: int,
    force: bool,
    dry_run: bool,
) -> int:
    max_chars = max(200, max_chars)
    settings = Settings()
    total_chunks = 0
    docs = 0
    with psycopg.connect(settings.database_url) as conn:
        dt = doc_type.strip() if doc_type and doc_type.strip() else None
        rows = _select_documents(
            conn,
            limit=max(1, limit),
            doc_type=dt,
            patient_id=patient_id,
            force=force,
        )
        logger.info("chunk_documents: documentos_na_fila=%s", len(rows))
        for doc_id, pat_id, content, dt in rows:
            pieces = chunk_text(content, max_chars=max_chars)
            if not pieces:
                logger.info("doc=%s tipo=%s sem segmentos (vazio após trim)", doc_id, dt)
                continue
            if dry_run:
                logger.info(
                    "dry-run doc=%s tipo=%s segmentos=%s",
                    doc_id,
                    dt,
                    len(pieces),
                )
                docs += 1
                total_chunks += len(pieces)
                continue
            n = replace_document_chunks(
                conn,
                patient_id=pat_id,
                document_id=doc_id,
                texts=pieces,
                embedding_model=None,
            )
            docs += 1
            total_chunks += n
            logger.info("doc=%s tipo=%s chunks=%s", doc_id, dt, n)
    logger.info(
        "chunk_documents concluído: documentos=%s chunks=%s dry_run=%s",
        docs,
        total_chunks,
        dry_run,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Segmentar documents → chunks (sem embeddings)")
    p.add_argument("--limit", type=int, default=50, help="Máximo de documentos a processar")
    p.add_argument("--doc-type", type=str, default=None, help="Filtrar por doc_type")
    p.add_argument(
        "--patient-id",
        type=uuid.UUID,
        default=None,
        help="Filtrar por UUID do paciente (internal id)",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=1200,
        help="Tamanho alvo por chunk (mínimo interno 200)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Reprocessar mesmo se já existirem chunks (apaga e regrava)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Só contar segmentos; não grava na base",
    )
    args = p.parse_args(argv)
    return run(
        limit=args.limit,
        doc_type=args.doc_type,
        patient_id=args.patient_id,
        max_chars=args.max_chars,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
