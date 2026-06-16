"""
Classificações, fórmulas e serialização de composição corporal.
Extraído dos routers bioimpedancia + composicao para eliminar duplicação.
"""
from __future__ import annotations

import uuid
from datetime import datetime


def classifica_gordura(bf: float, sexo: str) -> str:
    """Classificação ACE (American Council on Exercise)."""
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


def classifica_imc(imc: float) -> str:
    if imc < 18.5: return "abaixo do peso"
    if imc < 25.0: return "peso normal"
    if imc < 30.0: return "sobrepeso"
    if imc < 35.0: return "obesidade grau I"
    if imc < 40.0: return "obesidade grau II"
    return "obesidade grau III"


def calcular_bioimpedancia(
    altura_cm: float, peso_kg: float, idade: int, sexo: str
) -> dict:
    """
    Estimativa por fórmulas validadas:
    % Gordura  : Gallagher et al. (2000) — R²=0.85 contra DEXA
    Massa Musc.: Lee et al. (2000)       — R²=0.87 contra MRI
    """
    h = altura_cm / 100.0
    s = 1.0 if sexo == "M" else 0.0
    imc = peso_kg / (h ** 2)

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
    bf = max(3.0, min(bf, 70.0))

    smm = 0.244 * peso_kg + 7.8 * h + 6.6 * s - 0.098 * idade - 3.3
    smm = max(0.0, smm)

    massa_gorda = round(peso_kg * bf / 100, 2)
    massa_magra = round(peso_kg - massa_gorda, 2)
    smm_pct     = round((smm / peso_kg) * 100, 2) if peso_kg > 0 else 0.0

    return {
        "imc":                round(imc, 2),
        "gordura_pct":        round(bf, 2),
        "massa_muscular_kg":  round(smm, 2),
        "massa_muscular_pct": smm_pct,
        "massa_gorda_kg":     massa_gorda,
        "massa_magra_kg":     massa_magra,
        "classificacao_gordura": classifica_gordura(bf, sexo),
        "classificacao_imc":     classifica_imc(imc),
    }


def serialize_row(row: dict) -> dict:
    """Serializa linha do banco para JSON (datetime→ISO, UUID→str, Decimal→float)."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif hasattr(v, "__float__") and not isinstance(v, (bool, int)):
            out[k] = float(v)
        else:
            out[k] = v
    return out
