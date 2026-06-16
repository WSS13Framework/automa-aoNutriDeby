"""
bioimpedancia_router.py — Estimativa de composição corporal por fórmulas validadas.

Fórmulas:
  % Gordura  : Gallagher et al. (2000) — validada contra DEXA, R²=0.85
  Massa Musc.: Lee et al. (2000)       — validada contra MRI,  R²=0.87

Rotas:
  POST /patients/{patient_id}/bioimpedancia      → calcula e salva
  GET  /patients/{patient_id}/bioimpedancia      → histórico (últimas 50)
"""
from __future__ import annotations

from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, field_validator

from nutrideby.api.deps import get_settings
from nutrideby.api.mobile_api import check_active_access
from nutrideby.config import Settings
from nutrideby.services.body_composition import calcular_bioimpedancia, serialize_row

router = APIRouter(prefix="/patients", tags=["bioimpedancia"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class BioimpedanciaInput(BaseModel):
    altura_cm: float = Field(..., gt=50, lt=250, description="Altura em centímetros")
    peso_kg: float   = Field(..., gt=10, lt=300, description="Peso em quilogramas")
    idade: int       = Field(..., ge=18, le=100, description="Idade em anos")
    sexo: Literal["M", "F"]

    @field_validator("altura_cm", "peso_kg")
    @classmethod
    def duas_casas(cls, v: float) -> float:
        return round(v, 2)


class BioimpedanciaResult(BaseModel):
    id: str
    created_at: str
    altura_cm: float
    peso_kg: float
    idade: int
    sexo: str
    imc: float
    gordura_pct: float
    massa_muscular_kg: float
    massa_muscular_pct: float
    massa_gorda_kg: float
    massa_magra_kg: float
    classificacao_gordura: str
    classificacao_imc: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/{patient_id}/bioimpedancia",
    response_model=BioimpedanciaResult,
    status_code=status.HTTP_201_CREATED,
    summary="Avaliação de composição corporal (Gallagher 2000 + Lee 2000)",
)
def create_bioimpedancia(
    patient_id: str,
    body: BioimpedanciaInput,
    settings: Annotated[Settings, Depends(get_settings)],
    _access: dict = Depends(check_active_access),
):
    calc = calcular_bioimpedancia(body.altura_cm, body.peso_kg, body.idade, body.sexo)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bioimpedancia_logs
                   (patient_id, altura_cm, peso_kg, idade, sexo,
                    imc, gordura_pct, massa_muscular_kg, massa_muscular_pct,
                    massa_gorda_kg, massa_magra_kg,
                    classificacao_gordura, classificacao_imc)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING *""",
                (
                    patient_id,
                    body.altura_cm, body.peso_kg, body.idade, body.sexo,
                    calc["imc"],
                    calc["gordura_pct"],
                    calc["massa_muscular_kg"],
                    calc["massa_muscular_pct"],
                    calc["massa_gorda_kg"],
                    calc["massa_magra_kg"],
                    calc["classificacao_gordura"],
                    calc["classificacao_imc"],
                ),
            )
            row = cur.fetchone()

    return _serialize(row)


@router.get(
    "/{patient_id}/bioimpedancia",
    response_model=list[BioimpedanciaResult],
    summary="Histórico de avaliações de bioimpedância",
)
def list_bioimpedancia(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    _access: dict = Depends(check_active_access),
):
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM bioimpedancia_logs
                   WHERE patient_id = %s
                   ORDER BY created_at DESC
                   LIMIT 50""",
                (patient_id,),
            )
            rows = cur.fetchall()
    return [_serialize(r) for r in rows]


def _serialize(row: dict) -> dict:
    # bioimpedancia_logs.id é bigint serial → precisa str() explícito
    out = serialize_row(row)
    out["id"] = str(out["id"])
    out["patient_id"] = str(out.get("patient_id", ""))
    return out
