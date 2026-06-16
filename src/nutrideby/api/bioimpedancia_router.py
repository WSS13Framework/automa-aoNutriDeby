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

from datetime import datetime
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, field_validator

from nutrideby.api.deps import get_settings
from nutrideby.api.mobile_api import check_active_access
from nutrideby.config import Settings

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


# ── Cálculos ───────────────────────────────────────────────────────────────────

def _calcular(altura_cm: float, peso_kg: float, idade: int, sexo: str) -> dict:
    h = altura_cm / 100.0          # metros
    s = 1.0 if sexo == "M" else 0.0

    imc = peso_kg / (h ** 2)

    # Gallagher et al. (2000) — % gordura corporal
    if imc > 0:
        bf = (
            64.5
            - 848 * (1.0 / imc)
            + 0.079 * idade
            - 16.4 * s
            + 0.05 * s * idade
            + 39.0 * s * (1.0 / imc)
        )
    else:
        bf = 0.0
    bf = max(3.0, min(bf, 70.0))   # clamp fisiológico

    # Lee et al. (2000) — massa muscular esquelética
    smm = 0.244 * peso_kg + 7.8 * h + 6.6 * s - 0.098 * idade - 3.3
    smm = max(0.0, smm)

    massa_gorda  = round(peso_kg * bf / 100, 2)
    massa_magra  = round(peso_kg - massa_gorda, 2)
    smm_pct      = round((smm / peso_kg) * 100, 2) if peso_kg > 0 else 0.0

    return {
        "imc":                round(imc, 2),
        "gordura_pct":        round(bf, 2),
        "massa_muscular_kg":  round(smm, 2),
        "massa_muscular_pct": smm_pct,
        "massa_gorda_kg":     massa_gorda,
        "massa_magra_kg":     massa_magra,
        "classificacao_gordura": _classifica_gordura(bf, sexo),
        "classificacao_imc":     _classifica_imc(imc),
    }


def _classifica_gordura(bf: float, sexo: str) -> str:
    # Referências: American Council on Exercise (ACE)
    if sexo == "M":
        if bf < 6:   return "atlético essencial"
        if bf < 14:  return "atlético"
        if bf < 18:  return "bom"
        if bf < 25:  return "aceitável"
        if bf < 32:  return "obesidade leve"
        return "obesidade"
    else:
        if bf < 14:  return "atlético essencial"
        if bf < 21:  return "atlético"
        if bf < 25:  return "bom"
        if bf < 32:  return "aceitável"
        if bf < 39:  return "obesidade leve"
        return "obesidade"


def _classifica_imc(imc: float) -> str:
    if imc < 18.5: return "abaixo do peso"
    if imc < 25.0: return "peso normal"
    if imc < 30.0: return "sobrepeso"
    if imc < 35.0: return "obesidade grau I"
    if imc < 40.0: return "obesidade grau II"
    return "obesidade grau III"


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
    calc = _calcular(body.altura_cm, body.peso_kg, body.idade, body.sexo)

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
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__"):
            out[k] = float(v)
    out["id"] = str(out["id"])
    out["patient_id"] = str(out.get("patient_id", ""))
    return out
