"""
Demo Plano B: retrieval por paciente (Postgres + pgvector) e, opcionalmente,
resposta via agente DigitalOcean GenAI com contexto citável.

  python3 -m nutrideby.workers.rag_demo --patient-id UUID --query "pergunta"
  python3 -m nutrideby.workers.rag_demo --patient-id UUID --query "..." --json
  python3 -m nutrideby.workers.rag_demo --patient-id UUID --query "..." --with-agent
  python3 -m nutrideby.workers.rag_demo --all-dietbox --query "..." --k 3 --json

Requer ``DATABASE_URL``, ``OPENAI_API_KEY``, migração 004 e chunks com ``embedding``.
``--with-agent`` requer ``GENAI_AGENT_URL`` e ``GENAI_AGENT_ACCESS_KEY``.
O pedido ao agente DO GenAI usa **só** ``role=user`` (instruções + pergunta no mesmo
corpo): a API do agente **rejeita** ``role=system``.

Personas (só com ``--with-agent``): ``--persona default`` (comportamento original),
``--persona clinical`` (Analista Clínico + TACO), ``--persona motor`` (motor de
inteligência — Resumo / Análise / Conduta). Ver ``nutrideby.rag.clinical_analyst_prompts``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg
import psycopg.errors
from psycopg.rows import dict_row

from nutrideby.clients.genai_agent import assistant_content_from_completion, chat_completion
from nutrideby.clients.openai_embeddings import embed_single_query
from nutrideby.config import Settings
from nutrideby.rag.clinical_analyst_prompts import build_system_prompt
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
    persona: str,
    exam_metas: dict[str, Any] | None,
    max_tokens: int,
    exclude_prontuario_placeholder: bool,
    min_score: float | None,
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
                exclude_prontuario_placeholder=exclude_prontuario_placeholder,
                min_score=min_score,
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
    system = build_system_prompt(persona, block)
    if exam_metas is not None:
        extra = extract_and_compare_exams(hits, exam_metas)
        if extra.strip():
            system = (
                f"{system}\n\n### Pré-resumo automático (regex; validar no texto bruto)\n\n{extra}"
            )
    # DigitalOcean GenAI Agent (OpenAI-compatible) devolve 400 se existir mensagem
    # role=system — instruções vêm da configuração do agente ou embutidas aqui no user.
    user_payload = f"{system}\n\n---\n\n**Pergunta do operador:**\n\n{query}"
    messages: list[dict[str, str]] = [{"role": "user", "content": user_payload}]
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


def run_all_dietbox(
    *,
    query: str,
    k: int,
    as_json: bool,
    limit: int,
    exclude_prontuario_placeholder: bool,
    min_score: float | None,
) -> int:
    """
    Corre ``patient_retrieve`` para todos os ``patients`` com ``source_system=dietbox``.
    Um único embedding da pergunta; depois só consultas pgvector por paciente.
    Uma linha por paciente (texto) ou JSONL se ``as_json``.
    """
    settings = Settings()
    key = settings.openai_api_key
    if not (key and str(key).strip()):
        logger.error("OPENAI_API_KEY em falta")
        return 1
    try:
        query_vec = embed_single_query(
            api_base=settings.openai_api_base,
            api_key=str(key),
            model=settings.openai_embedding_model,
            text=query,
        )
    except RuntimeError as e:
        logger.error("embedding da query: %s", e)
        return 1

    src = "dietbox"
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, external_id, display_name
                FROM patients
                WHERE source_system = %s
                ORDER BY external_id ASC
                """,
                (src,),
            )
            rows = cur.fetchall()
        if limit > 0:
            rows = rows[:limit]
        logger.info("rag_demo --all-dietbox: pacientes=%s", len(rows))
        worst = 0
        for row in rows:
            pid = row["id"]
            if not isinstance(pid, uuid.UUID):
                pid = uuid.UUID(str(pid))
            ext = str(row.get("external_id") or "")
            name = row.get("display_name") or ""
            try:
                model, hits = patient_retrieve(
                    conn,
                    patient_id=pid,
                    query=query,
                    k=k,
                    settings=settings,
                    exclude_prontuario_placeholder=exclude_prontuario_placeholder,
                    min_score=min_score,
                    precomputed_query_embedding=query_vec,
                )
            except ValueError as e:
                worst = 1
                logger.error("paciente=%s: %s", pid, e)
                if as_json:
                    print(
                        json.dumps(
                            {
                                "patient_id": str(pid),
                                "external_id": ext,
                                "display_name": name,
                                "error": str(e),
                                "hits": [],
                            },
                            ensure_ascii=False,
                        )
                    )
                else:
                    print(f"ERR patient_id={pid} external_id={ext} {e}")
                continue
            except RuntimeError as e:
                worst = 1
                logger.error("paciente=%s embedding/API: %s", pid, e)
                if as_json:
                    print(
                        json.dumps(
                            {
                                "patient_id": str(pid),
                                "external_id": ext,
                                "display_name": name,
                                "error": str(e),
                                "hits": [],
                            },
                            ensure_ascii=False,
                        )
                    )
                else:
                    print(f"ERR patient_id={pid} external_id={ext} API {e}")
                continue
            except psycopg.errors.UndefinedColumn:
                logger.error(
                    "Coluna embedding em falta — aplica infra/sql/004_pgvector_chunks_embedding.sql"
                )
                return 1
            except psycopg.errors.UndefinedFunction:
                logger.error("Extensão pgvector em falta ou operador inválido na base")
                return 1

            best = max((float(h["score"]) for h in hits), default=None)
            if as_json:
                print(
                    json.dumps(
                        {
                            "patient_id": str(pid),
                            "external_id": ext,
                            "display_name": name,
                            "embedding_model": model,
                            "hit_count": len(hits),
                            "top_score": best,
                            "hits": hits,
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                print(
                    f"patient_id={pid} external_id={ext} name={name!r} "
                    f"hits={len(hits)} top_score={best if best is not None else 'n/a'}"
                )
        return worst


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Demo RAG: retrieve + opcional GenAI agent")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--patient-id",
        type=uuid.UUID,
        help="UUID interno do paciente (formato xxxxxxxx-xxxx-…; não uses texto tipo SEU_UUID)",
    )
    mode.add_argument(
        "--all-dietbox",
        action="store_true",
        help="Todos os pacientes source_system=dietbox (sem --with-agent)",
    )
    p.add_argument("--query", type=str, required=True, help="Pergunta em linguagem natural")
    p.add_argument(
        "--all-limit",
        type=int,
        default=0,
        metavar="N",
        help="Com --all-dietbox: máximo de pacientes (0 = todos)",
    )
    p.add_argument("--k", type=int, default=5, help="Top-k chunks")
    p.add_argument(
        "--no-exclude-placeholder",
        action="store_true",
        help="Incluir chunks marcador prontuário 204 (por defeito são excluídos)",
    )
    p.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Só hits com score >= valor (0–1); score = 1/(1+distance)",
    )
    p.add_argument("--json", action="store_true", help="Saída só JSON dos hits")
    p.add_argument(
        "--with-agent",
        action="store_true",
        help="Após retrieval, envia contexto + pergunta ao agente DO GenAI",
    )
    p.add_argument(
        "--persona",
        choices=("default", "clinical", "motor"),
        default="default",
        help="Com --with-agent: prompt de sistema (default | clinical | motor)",
    )
    p.add_argument("--max-tokens", type=int, default=512, help="Com --with-agent")
    p.add_argument(
        "--exam-metas-json",
        metavar="PATH",
        default=None,
        help="Ficheiro JSON metas exame→{min,max}; pré-resumo regex antes do agente (só com --with-agent)",
    )
    args = p.parse_args(argv)
    min_s = args.min_score
    if min_s is not None and not (0.0 <= min_s <= 1.0):
        p.error("--min-score deve estar entre 0 e 1")
    if args.persona != "default" and not args.with_agent:
        p.error("--persona clinical|motor só faz sentido com --with-agent")
    if args.exam_metas_json and not args.with_agent:
        p.error("--exam-metas-json requer --with-agent")
    exam_metas: dict[str, Any] | None = None
    if args.exam_metas_json:
        mp = Path(args.exam_metas_json)
        if not mp.is_file():
            p.error(f"--exam-metas-json: ficheiro não encontrado: {mp}")
        try:
            raw = json.loads(mp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            p.error(f"--exam-metas-json: JSON inválido: {e}")
        if not isinstance(raw, dict):
            p.error("--exam-metas-json: raiz tem de ser um objecto JSON")
        exam_metas = raw
    if args.all_dietbox and args.with_agent:
        p.error("--with-agent não pode ser usado com --all-dietbox")
    if args.all_dietbox:
        return run_all_dietbox(
            query=args.query.strip(),
            k=max(1, min(args.k, 20)),
            as_json=args.json,
            limit=max(0, args.all_limit),
            exclude_prontuario_placeholder=not args.no_exclude_placeholder,
            min_score=min_s,
        )
    if args.patient_id is None:
        p.error("indica --patient-id ou --all-dietbox")
    return run(
        patient_id=args.patient_id,
        query=args.query.strip(),
        k=max(1, min(args.k, 20)),
        as_json=args.json,
        with_agent=args.with_agent,
        persona=args.persona,
        exam_metas=exam_metas,
        max_tokens=max(64, args.max_tokens),
        exclude_prontuario_placeholder=not args.no_exclude_placeholder,
        min_score=min_s,
    )


if __name__ == "__main__":
    sys.exit(main())
