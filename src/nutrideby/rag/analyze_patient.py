"""
Análise clínica por paciente: RAG (pgvector) + LLM (GenAI agent ou OpenAI chat).

Usado pela API ``POST /v1/patients/{id}/analyze`` e alinhado ao fluxo ``rag_demo --with-agent``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

import psycopg
import psycopg.errors
from psycopg.rows import dict_row

from nutrideby.clients.genai_agent import assistant_content_from_completion, chat_completion
from nutrideby.clients.openai_chat import assistant_content_from_chat, chat_completion as openai_chat
from nutrideby.clients.spaces import upload_json_analysis_if_configured
from nutrideby.config import Settings
from nutrideby.persist.analysis_export import insert_genai_analysis_export
from nutrideby.rag.clinical_analyst_prompts import build_system_prompt
from nutrideby.rag.retrieve_with_cache import retrieve_patient_chunks

logger = logging.getLogger(__name__)

PersonaChoice = Literal["default", "clinical", "motor", "analyst"]


def _context_block(hits: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for h in hits:
        cid = h.get("chunk_id", "")
        txt = str(h.get("text") or "")
        parts.append(f"[chunk_id={cid}]\n{txt}")
    return "\n\n---\n\n".join(parts)


def _normalize_persona(persona: str) -> str:
    p = (persona or "clinical").strip().lower()
    if p == "analyst":
        return "clinical"
    if p in ("default", "clinical", "motor"):
        return p
    return "clinical"


def _patient_exists(conn: psycopg.Connection, patient_id: uuid.UUID) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM patients WHERE id = %s LIMIT 1", (patient_id,))
        return cur.fetchone() is not None


def run_patient_analysis(
    *,
    patient_id: uuid.UUID,
    query: str,
    settings: Settings,
    use_genai: bool = True,
    persona: PersonaChoice = "clinical",
    k: int = 5,
    max_tokens: int = 1024,
    exclude_prontuario_placeholder: bool = True,
    min_score: float | None = None,
) -> dict[str, Any]:
    """
    Executa retrieve + LLM + persistência opcional (Spaces + ``genai_analysis_exports``).

    Levanta ``ValueError`` (config), ``RuntimeError`` (LLM), ``LookupError`` (paciente inexistente).
    """
    persona_norm = _normalize_persona(persona)
    q = query.strip()
    if not q:
        raise ValueError("query vazia")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        if not _patient_exists(conn, patient_id):
            raise LookupError(f"Paciente não encontrado: {patient_id}")

        embedding_model, hits, embedding_cache_hit = retrieve_patient_chunks(
            conn,
            patient_id=patient_id,
            query=q,
            k=k,
            settings=settings,
            exclude_prontuario_placeholder=exclude_prontuario_placeholder,
            min_score=min_score,
        )

        block = _context_block(hits) if hits else "(nenhum trecho recuperado da base)"
        system = build_system_prompt(persona_norm, block)
        user_payload = f"{system}\n\n---\n\n**Pergunta do operador:**\n\n{q}"
        messages: list[dict[str, str]] = [{"role": "user", "content": user_payload}]

        telemetry_context: dict[str, Any] = {
            "patient_id": str(patient_id),
            "query": q,
            "persona": persona_norm,
            "embedding_model": embedding_model,
            "rag_hit_scores": [
                {
                    "chunk_id": str(h.get("chunk_id", "")),
                    "score": float(h["score"]),
                    "distance": float(h["distance"]),
                }
                for h in hits
            ],
        }

        provider: str
        raw: str
        path_used: str | None = None
        http_status: int

        genai_url = settings.genai_agent_url
        genai_key = settings.genai_agent_access_key
        use_do = bool(
            use_genai
            and genai_url
            and str(genai_url).strip()
            and genai_key
            and str(genai_key).strip()
        )

        if use_do:
            http_status, raw, path_used = chat_completion(
                str(genai_url).strip(),
                str(genai_key).strip(),
                messages,
                max_tokens=max_tokens,
                telemetry_context=telemetry_context,
            )
            provider = "genai"
            analysis = assistant_content_from_completion(raw)
        else:
            okey = settings.openai_api_key
            if not (okey and str(okey).strip()):
                raise ValueError(
                    "LLM indisponível: defina GENAI_AGENT_URL+ACCESS_KEY (use_genai=true) "
                    "ou OPENAI_API_KEY (fallback OpenAI chat)"
                )
            http_status, raw = openai_chat(
                api_base=settings.openai_api_base,
                api_key=str(okey).strip(),
                model=settings.openai_chat_model,
                messages=messages,
                max_tokens=max_tokens,
            )
            provider = "openai"
            analysis = assistant_content_from_chat(raw)

        export_id: str | None = None
        spaces_url: str | None = upload_json_analysis_if_configured(
            access_key_id=settings.spaces_access_key_id,
            secret_access_key=settings.spaces_secret_access_key,
            bucket=settings.spaces_bucket,
            region=settings.spaces_region,
            endpoint_url=settings.spaces_endpoint,
            payload={
                "patient_id": str(patient_id),
                "query": q,
                "persona": persona_norm,
                "embedding_model": embedding_model,
                "provider": provider,
                "hits": hits,
                "raw_completion": raw,
                "assistant_markdown": analysis,
                "http_status": http_status,
                "agent_path": path_used,
            },
        )
        if spaces_url:
            try:
                rid = insert_genai_analysis_export(
                    conn,
                    patient_id=patient_id,
                    spaces_url=spaces_url,
                    persona=persona_norm,
                    query_preview=q[:500],
                )
                export_id = str(rid)
                conn.commit()
            except psycopg.errors.UndefinedTable:
                logger.warning(
                    "genai_analysis_exports em falta — aplica infra/sql/005_genai_analysis_export.sql"
                )
            except Exception:
                logger.exception("analyze: falha ao gravar export no Postgres")
        else:
            conn.rollback()

    return {
        "analysis": analysis,
        "chunks_used": len(hits),
        "embedding_model": embedding_model,
        "embedding_cache_hit": embedding_cache_hit,
        "persona": persona_norm,
        "provider": provider,
        "export_id": export_id,
        "spaces_url": spaces_url,
        "hits": hits,
    }
