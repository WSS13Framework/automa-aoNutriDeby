"""
NutriDeby — Normalizador Unificado de Dados
Converte qualquer formato de entrada para o schema unificado NutriDeby.
"""
from __future__ import annotations
import re
import unicodedata
from datetime import datetime, date
from typing import Any


def _str(v: Any) -> str | None:
    return str(v).strip() if v not in (None, "", "null", "NULL") else None


def _float(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(str(v).replace(",", ".").split(".")[0])
    except (TypeError, ValueError):
        return None


def _date(v: Any) -> str | None:
    if not v:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return _str(v)


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_]", "_", text.lower()).strip("_")


def normalize_patient(raw: dict, source_platform: str) -> dict:
    """
    Normaliza um paciente de qualquer plataforma para o schema unificado NutriDeby.
    """
    dados = raw.get("dados_cadastrais") or raw.get("cadastro") or {}
    prontuario = raw.get("prontuario") or raw.get("anamnese") or {}
    metas = raw.get("metas_nutricionais") or raw.get("metas") or {}
    medidas = raw.get("medidas_antropometricas") or raw.get("antropometria") or {}
    plano = raw.get("plano_alimentar") or raw.get("plano") or {}
    exames = raw.get("exames") or raw.get("laboratorio") or []
    historico = raw.get("historico_evolucao") or raw.get("evolucao") or []

    return {
        "external_id": _str(raw.get("id") or raw.get("external_id") or raw.get("codigo")),
        "source_platform": source_platform,
        "data_exportacao": datetime.utcnow().isoformat() + "Z",
        "nome": _str(raw.get("nome") or dados.get("nome")),
        "dados_cadastrais": {
            "email": _str(dados.get("email") or raw.get("email")),
            "telefone": _str(dados.get("telefone") or raw.get("telefone") or dados.get("celular")),
            "data_nascimento": _date(dados.get("data_nascimento") or dados.get("nascimento") or raw.get("data_nascimento")),
            "sexo": _str(dados.get("sexo") or dados.get("genero") or raw.get("sexo")),
            "cpf": _str(dados.get("cpf")),
            "endereco": _str(dados.get("endereco") or dados.get("logradouro")),
            "cidade": _str(dados.get("cidade")),
            "estado": _str(dados.get("estado") or dados.get("uf")),
            "profissao": _str(dados.get("profissao")),
            "objetivo": _str(dados.get("objetivo") or raw.get("objetivo")),
        },
        "prontuario": {
            "texto": _str(prontuario.get("texto") or prontuario.get("descricao") or prontuario.get("observacoes")),
            "medicamentos": prontuario.get("medicamentos") or [],
            "condicoes": prontuario.get("condicoes") or prontuario.get("patologias") or [],
            "alergias": prontuario.get("alergias") or [],
            "historico_familiar": _str(prontuario.get("historico_familiar")),
            "queixa_principal": _str(prontuario.get("queixa_principal") or prontuario.get("queixa")),
        },
        "metas_nutricionais": {
            "calorias": _float(metas.get("calorias") or metas.get("kcal") or metas.get("energia")),
            "proteinas_g": _float(metas.get("proteinas") or metas.get("proteinas_g")),
            "carboidratos_g": _float(metas.get("carboidratos") or metas.get("carboidratos_g") or metas.get("cho")),
            "gorduras_g": _float(metas.get("gorduras") or metas.get("lipidios") or metas.get("gorduras_g")),
            "fibras_g": _float(metas.get("fibras") or metas.get("fibras_g")),
            "agua_ml": _float(metas.get("agua") or metas.get("agua_ml") or metas.get("hidratacao")),
            "sodio_mg": _float(metas.get("sodio") or metas.get("sodio_mg")),
        },
        "medidas_antropometricas": {
            "peso_kg": _float(medidas.get("peso") or medidas.get("peso_kg")),
            "altura_m": _float(medidas.get("altura") or medidas.get("altura_m")),
            "imc": _float(medidas.get("imc")),
            "circunferencia_abdominal_cm": _float(medidas.get("circunferencia_abdominal") or medidas.get("ca")),
            "percentual_gordura": _float(medidas.get("percentual_gordura") or medidas.get("gordura_corporal")),
            "massa_muscular_kg": _float(medidas.get("massa_muscular") or medidas.get("massa_magra")),
            "data_medicao": _date(medidas.get("data") or medidas.get("data_medicao")),
        },
        "plano_alimentar": plano if isinstance(plano, dict) else {"descricao": _str(plano)},
        "exames": exames if isinstance(exames, list) else [],
        "historico_evolucao": historico if isinstance(historico, list) else [],
    }


def normalize_batch(patients: list[dict], source_platform: str) -> dict:
    """Normaliza uma lista de pacientes e retorna o envelope padrão."""
    return {
        "data_exportacao": datetime.utcnow().isoformat() + "Z",
        "source_platform": source_platform,
        "total": len(patients),
        "pacientes": [normalize_patient(p, source_platform) for p in patients],
    }
