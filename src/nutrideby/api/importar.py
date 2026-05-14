"""
NutriDeby — Endpoint POST /api/importar
Recebe o JSON unificado gerado pelos extratores e persiste no PostgreSQL.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["importar"])


# ─── Schemas de entrada ──────────────────────────────────────────────────────

class DadosCadastrais(BaseModel):
    email: str | None = None
    telefone: str | None = None
    data_nascimento: str | None = None
    sexo: str | None = None
    cpf: str | None = None
    endereco: str | None = None
    cidade: str | None = None
    estado: str | None = None
    profissao: str | None = None
    objetivo: str | None = None


class Prontuario(BaseModel):
    texto: str | None = None
    medicamentos: list[str] = []
    condicoes: list[str] = []
    alergias: list[str] = []
    historico_familiar: str | None = None
    queixa_principal: str | None = None


class MetasNutricionais(BaseModel):
    calorias: float | None = None
    proteinas_g: float | None = None
    carboidratos_g: float | None = None
    gorduras_g: float | None = None
    fibras_g: float | None = None
    agua_ml: float | None = None
    sodio_mg: float | None = None


class MedidasAntropometricas(BaseModel):
    peso_kg: float | None = None
    altura_m: float | None = None
    imc: float | None = None
    circunferencia_abdominal_cm: float | None = None
    percentual_gordura: float | None = None
    massa_muscular_kg: float | None = None
    data_medicao: str | None = None


class PacienteImport(BaseModel):
    external_id: str | None = None
    source_platform: str
    nome: str | None = None
    dados_cadastrais: DadosCadastrais = Field(default_factory=DadosCadastrais)
    prontuario: Prontuario = Field(default_factory=Prontuario)
    metas_nutricionais: MetasNutricionais = Field(default_factory=MetasNutricionais)
    medidas_antropometricas: MedidasAntropometricas = Field(default_factory=MedidasAntropometricas)
    plano_alimentar: dict[str, Any] = Field(default_factory=dict)
    exames: list[Any] = []
    historico_evolucao: list[Any] = []


class ImportarRequest(BaseModel):
    source_platform: str = Field(..., description="Ex: dietbox, dietsmart, nutrium")
    data_exportacao: str | None = None
    total: int | None = None
    pacientes: list[PacienteImport]


class ImportarResult(BaseModel):
    source_platform: str
    total_recebidos: int
    inseridos: int
    atualizados: int
    ignorados: int
    erros: list[str]
    duracao_ms: int


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _build_metadata(p: PacienteImport) -> dict:
    """Monta o JSONB metadata que vai para a tabela patients."""
    return {
        "dados_cadastrais": p.dados_cadastrais.model_dump(exclude_none=True),
        "prontuario": p.prontuario.model_dump(exclude_none=True),
        "metas_nutricionais": p.metas_nutricionais.model_dump(exclude_none=True),
        "medidas_antropometricas": p.medidas_antropometricas.model_dump(exclude_none=True),
        "plano_alimentar": p.plano_alimentar,
        "exames": p.exames,
        "historico_evolucao": p.historico_evolucao,
        "importado_em": datetime.now(timezone.utc).isoformat(),
    }


def _build_document_text(p: PacienteImport) -> str | None:
    """Monta texto para indexação RAG a partir do prontuário + metas."""
    parts = []
    if p.nome:
        parts.append(f"Paciente: {p.nome}")
    dc = p.dados_cadastrais
    if dc.objetivo:
        parts.append(f"Objetivo: {dc.objetivo}")
    if dc.data_nascimento:
        parts.append(f"Data de nascimento: {dc.data_nascimento}")
    if dc.sexo:
        parts.append(f"Sexo: {dc.sexo}")
    pr = p.prontuario
    if pr.queixa_principal:
        parts.append(f"Queixa principal: {pr.queixa_principal}")
    if pr.texto:
        parts.append(f"Prontuário: {pr.texto[:3000]}")
    if pr.medicamentos:
        parts.append(f"Medicamentos: {', '.join(str(m) for m in pr.medicamentos)}")
    if pr.condicoes:
        parts.append(f"Condições: {', '.join(str(c) for c in pr.condicoes)}")
    if pr.alergias:
        parts.append(f"Alergias: {', '.join(str(a) for a in pr.alergias)}")
    mn = p.metas_nutricionais
    metas_parts = []
    if mn.calorias:
        metas_parts.append(f"{mn.calorias} kcal")
    if mn.proteinas_g:
        metas_parts.append(f"proteínas {mn.proteinas_g}g")
    if mn.carboidratos_g:
        metas_parts.append(f"carboidratos {mn.carboidratos_g}g")
    if mn.gorduras_g:
        metas_parts.append(f"gorduras {mn.gorduras_g}g")
    if metas_parts:
        parts.append(f"Metas nutricionais: {', '.join(metas_parts)}")
    ma = p.medidas_antropometricas
    if ma.peso_kg:
        parts.append(f"Peso: {ma.peso_kg} kg")
    if ma.altura_m:
        parts.append(f"Altura: {ma.altura_m} m")
    if ma.imc:
        parts.append(f"IMC: {ma.imc}")
    return "\n".join(parts) if parts else None


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/importar", response_model=ImportarResult)
def importar_pacientes(
    body: ImportarRequest,
    settings=Depends(lambda: __import__("nutrideby.config", fromlist=["Settings"]).Settings()),
) -> ImportarResult:
    """
    Importa pacientes no schema unificado NutriDeby.
    Faz upsert em `patients` (source_system + external_id) e insere documento RAG.
    """
    t0 = datetime.now(timezone.utc)
    inseridos = 0
    atualizados = 0
    ignorados = 0
    erros: list[str] = []

    try:
        conn = psycopg.connect(settings.database_url)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erro de conexão com banco: {e}")

    with conn:
        with conn.cursor() as cur:
            for p in body.pacientes:
                try:
                    external_id = p.external_id or hashlib.md5(
                        (p.nome or "unknown").encode()
                    ).hexdigest()[:12]
                    source_system = p.source_platform
                    display_name = p.nome
                    metadata = _build_metadata(p)

                    # Upsert em patients
                    cur.execute(
                        """
                        INSERT INTO patients (source_system, external_id, display_name, metadata, updated_at)
                        VALUES (%s, %s, %s, %s::jsonb, NOW())
                        ON CONFLICT (source_system, external_id)
                        DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            metadata     = patients.metadata || EXCLUDED.metadata,
                            updated_at   = NOW()
                        RETURNING (xmax = 0) AS inserted, id
                        """,
                        (source_system, external_id, display_name, json.dumps(metadata, ensure_ascii=False)),
                    )
                    row = cur.fetchone()
                    was_inserted = row[0] if row else False
                    patient_id = row[1] if row else None

                    if was_inserted:
                        inseridos += 1
                    else:
                        atualizados += 1

                    # Inserir documento RAG se tiver texto
                    doc_text = _build_document_text(p)
                    if doc_text and patient_id:
                        content_sha256 = hashlib.sha256(doc_text.encode()).hexdigest()
                        cur.execute(
                            """
                            INSERT INTO documents (patient_id, doc_type, content_text, content_sha256, source_ref, metadata, collected_at)
                            VALUES (%s, 'import', %s, %s, %s, %s::jsonb, NOW())
                            ON CONFLICT (content_sha256) DO NOTHING
                            """,
                            (
                                patient_id,
                                doc_text,
                                content_sha256,
                                f"import:{source_system}:{external_id}",
                                json.dumps({"source_platform": source_system, "import": True}, ensure_ascii=False),
                            ),
                        )

                except Exception as e:
                    erros.append(f"{p.nome or p.external_id}: {e}")
                    ignorados += 1
                    logger.warning(f"Erro ao importar paciente {p.nome}: {e}")

    conn.close()

    duracao_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    logger.info(
        f"Importação {body.source_platform}: inseridos={inseridos} "
        f"atualizados={atualizados} ignorados={ignorados} erros={len(erros)} "
        f"duração={duracao_ms}ms"
    )

    return ImportarResult(
        source_platform=body.source_platform,
        total_recebidos=len(body.pacientes),
        inseridos=inseridos,
        atualizados=atualizados,
        ignorados=ignorados,
        erros=erros,
        duracao_ms=duracao_ms,
    )
