"""
Demo Plano B: retrieval por paciente (Postgres + pgvector) e, opcionalmente,
resposta via agente DigitalOcean GenAI com contexto citável.

  python3 -m nutrideby.workers.rag_demo --patient-id UUID --query "pergunta"
  python3 -m nutrideby.workers.rag_demo --patient-id UUID --query "..." --json
  python3 -m nutrideby.workers.rag_demo --patient-id UUID --query "..." --with-agent

Requer ``DATABASE_URL``, ``OPENAI_API_KEY``, migração 004 e chunks com ``embedding``.
``--with-agent`` requer ``GENAI_AGENT_URL`` e ``GENAI_AGENT_ACCESS_KEY``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid

import psycopg
import psycopg.errors
from psycopg.rows import dict_row

from nutrideby.clients.genai_agent import assistant_content_from_completion, chat_completion
from nutrideby.config import Settings
from nutrideby.rag.patient_retrieve import patient_retrieve

logger = logging.getLogger(__name__)


def _context_block(hits: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for h in hits:
        cid = h.get("chunk_id", "")
        txt = str(h.get("text") or "")
        parts.append(f"[chunk_id={cid}]\n{txt}")
    return "\n\n---\n\n".join(parts)


def run(
    *,
    patient_id: uuid.UUID,
    query: str,
    k: int,
    as_json: bool,
    with_agent: bool,
    max_tokens: int,
) -> int:
    settings = Settings()
    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            model, hits = patient_retrieve(
                conn,
                patient_id=patient_id,
                query=query,
                k=k,
                settings=settings,
            )
    except ValueError as e:
        logger.error("%s", e)
        return 1
    except RuntimeError as e:
        logger.error("Embedding / API: %s", e)
        return 1
    except psycopg.errors.UndefinedColumn:
        logger.error(
            "Coluna embedding em falta — aplica infra/sql/004_pgvector_chunks_embedding.sql"
        )
        return 1
    except psycopg.errors.UndefinedFunction:
        logger.error("Extensão pgvector em falta ou operador inválido na base")
        return 1

    if as_json:
        print(json.dumps({"embedding_model": model, "hits": hits}, ensure_ascii=False, indent=2))
    else:
        print(f"embedding_model={model} hits={len(hits)}\n")
        for h in hits:
            print(
                f"--- chunk_id={h['chunk_id']} score={float(h['score']):.4f} "
                f"distance={float(h['distance']):.4f}"
            )
            txt = str(h.get("text") or "")
            print(txt if len(txt) <= 2000 else txt[:2000] + "…\n")

    if not with_agent:
        return 0

    url = settings.genai_agent_url
    key = settings.genai_agent_access_key
    if not (url and str(url).strip() and key and str(key).strip()):
        logger.error("GENAI_AGENT_URL / GENAI_AGENT_ACCESS_KEY em falta para --with-agent")
        return 1
    if not hits:
        logger.warning("Sem hits — pedido ao agente só com a pergunta (sem contexto da base)")
    block = _context_block(hits) if hits else "(nenhum trecho recuperado da base)"
    system = (
        "És um assistente de apoio à nutrição. Usa **apenas** o contexto abaixo "
        "(trechos da ficha / documentos do paciente) para fundamentar a resposta. "
        "Se o contexto não bastar, diz-o explicitamente. Quando citares factos, "
        "indica o chunk_id correspondente.\n\n"
        f"Contexto:\n\n{block}"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
    ]
    try:
        status, raw, path = chat_completion(
            str(url).strip(),
            str(key).strip(),
            messages,
            max_tokens=max_tokens,
        )
    except RuntimeError as e:
        logger.error("Agente GenAI: %s", e)
        return 1
    logger.info("rag_demo: agente HTTP %s path=%s", status, path)
    if not as_json:
        print("\n========== RESPOSTA AGENTE ==========\n")
    print(assistant_content_from_completion(raw))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Demo RAG: retrieve + opcional GenAI agent")
    p.add_argument("--patient-id", type=uuid.UUID, required=True, help="UUID interno do paciente")
    p.add_argument("--query", type=str, required=True, help="Pergunta em linguagem natural")
    p.add_argument("--k", type=int, default=5, help="Top-k chunks")
    p.add_argument("--json", action="store_true", help="Saída só JSON dos hits")
    p.add_argument(
        "--with-agent",
        action="store_true",
        help="Após retrieval, envia contexto + pergunta ao agente DO GenAI",
    )
    p.add_argument("--max-tokens", type=int, default=512, help="Com --with-agent")
    args = p.parse_args(argv)
    return run(
        patient_id=args.patient_id,
        query=args.query.strip(),
        k=max(1, min(args.k, 20)),
        as_json=args.json,
        with_agent=args.with_agent,
        max_tokens=max(64, args.max_tokens),
    )


if __name__ == "__main__":
    sys.exit(main())
