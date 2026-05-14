#!/usr/bin/env python3
"""
Popula chunks e embeddings para TODOS os documentos do banco.

Uso (no host, fora do Docker):
  cd /opt/automa-aoNutriDeby
  set -a; source .env; set +a
  export PYTHONPATH=/opt/automa-aoNutriDeby/src
  python3 scripts/populate_chunks.py

Uso (dentro do container api):
  docker compose --profile api exec api python3 scripts/populate_chunks.py

O script chama os mesmos workers que já existem:
  1. chunk_documents.run() — segmenta documents.content_text → chunks
  2. embed_chunks.run()   — gera embeddings via OpenAI → chunks.embedding
"""
import sys
import os
import logging

# Garante que src está no PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from nutrideby.workers.chunk_documents import run as run_chunks
from nutrideby.workers.embed_chunks import run as run_embeds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("populate_chunks")


def main() -> int:
    # 1. Chunking — processar até 5000 documentos
    logger.info("=== Etapa 1/2: Gerando chunks ===")
    rc = run_chunks(
        limit=5000,
        doc_type=None,
        patient_id=None,
        max_chars=1200,
        force=False,
        dry_run=False,
    )
    if rc != 0:
        logger.error("chunk_documents falhou (rc=%s)", rc)
        return rc

    # 2. Embeddings — processar até 5000 chunks sem embedding
    logger.info("=== Etapa 2/2: Gerando embeddings ===")
    rc = run_embeds(
        limit=5000,
        patient_id=None,
        batch_size=32,
        force=False,
        dry_run=False,
        http_timeout=120,
    )
    if rc != 0:
        logger.error("embed_chunks falhou (rc=%s)", rc)
        return rc

    logger.info("=== Concluído com sucesso ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
