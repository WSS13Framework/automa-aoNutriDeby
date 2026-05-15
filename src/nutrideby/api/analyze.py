"""POST /v1/patients/{patient_id}/analyze — RAG + LLM para o painel."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg.errors
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nutrideby.api.deps import get_settings, require_api_key
from nutrideby.config import Settings
from nutrideby.rag.analyze_patient import run_patient_analysis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analyze"])


class AnalyzeRequest(BaseModel):
    query: str = Field(
        default="Faça uma análise clínica completa deste paciente",
        min_length=1,
        max_length=8000,
    )
    use_genai: bool = Field(
        default=True,
        description="Se true e GENAI_* configurado, usa agente DO GenAI; senão OpenAI chat.",
    )
    persona: Literal["default", "clinical", "motor", "analyst"] = Field(
        default="clinical",
        description="analyst é alias de clinical (Analista Clínico).",
    )
    k: int = Field(default=5, ge=1, le=20)
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    exclude_prontuario_placeholder: bool = Field(
        default=True,
        description="Excluir chunks marcador prontuário 204.",
    )
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)


class AnalyzeHitSummary(BaseModel):
    chunk_id: str
    document_id: str | None
    chunk_index: int
    distance: float
    score: float
    text_preview: str


class AnalyzeResponse(BaseModel):
    analysis: str
    chunks_used: int
    embedding_model: str
    embedding_cache_hit: bool = False
    persona: str
    provider: str
    export_id: str | None = None
    spaces_url: str | None = None
    hits: list[AnalyzeHitSummary] = Field(default_factory=list)


@router.post(
    "/v1/patients/{patient_id}/analyze",
    dependencies=[Depends(require_api_key)],
    response_model=AnalyzeResponse,
)
def analyze_patient(
    patient_id: UUID,
    body: AnalyzeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalyzeResponse:
    """
  1. Busca semântica (RAG / pgvector) nos chunks do paciente.
  2. Monta prompt clínico (persona) com os trechos.
  3. Gera texto via GenAI agent (DO) ou OpenAI chat.
  4. Opcional: export JSON no Spaces + registo em ``genai_analysis_exports``.
    """
    try:
        result = run_patient_analysis(
            patient_id=patient_id,
            query=body.query,
            settings=settings,
            use_genai=body.use_genai,
            persona=body.persona,
            k=body.k,
            max_tokens=body.max_tokens,
            exclude_prontuario_placeholder=body.exclude_prontuario_placeholder,
            min_score=body.min_score,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        logger.warning("analyze: falha LLM: %s", e)
        raise HTTPException(status_code=502, detail=f"Falha ao gerar análise: {e!s}") from e
    except psycopg.errors.UndefinedColumn:
        raise HTTPException(
            status_code=503,
            detail="Coluna embedding em falta. Aplica infra/sql/004_pgvector_chunks_embedding.sql",
        ) from None
    except psycopg.errors.UndefinedFunction:
        raise HTTPException(
            status_code=503,
            detail="Extensão pgvector em falta. Usa imagem pgvector e migração 004.",
        ) from None

    hit_summaries: list[AnalyzeHitSummary] = []
    for h in result.get("hits") or []:
        raw = str(h.get("text") or "")
        preview = raw if len(raw) <= 500 else raw[:500] + "…"
        did = h.get("document_id")
        hit_summaries.append(
            AnalyzeHitSummary(
                chunk_id=str(h.get("chunk_id", "")),
                document_id=str(did) if did else None,
                chunk_index=int(h.get("chunk_index", 0)),
                distance=float(h.get("distance", 0.0)),
                score=float(h.get("score", 0.0)),
                text_preview=preview,
            )
        )

    return AnalyzeResponse(
        analysis=str(result["analysis"]),
        chunks_used=int(result["chunks_used"]),
        embedding_model=str(result["embedding_model"]),
        embedding_cache_hit=bool(result.get("embedding_cache_hit")),
        persona=str(result["persona"]),
        provider=str(result["provider"]),
        export_id=result.get("export_id"),
        spaces_url=result.get("spaces_url"),
        hits=hit_summaries,
    )
