"""
Pré-processamento opcional de hits RAG para extrair linhas tipo exame laboratorial.

Objetivo: gerar um bloco de texto que **ancora** o pedido ao LLM (valores + comparação
com metas), sem substituir a leitura dos trechos brutos — **regex é frágil** (datas,
abreviaturas, tabelas).

Formato de ``metas`` (JSON, mesmo esquema que o exemplo original):

    {"Hemoglobina": {"min": 12.0, "max": 15.0}, "Glicemia": {"min": null, "max": 100.0}}

Hits aceites: chaves ``text`` (NutriDeby), ``page_content`` ou ``content`` (LangChain).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping, Sequence

# ISO e data brasileira comum em relatórios
_DATE_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DATE_BR = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
# Nome : valor unidade (linha relativamente simples)
_EXAM_COLON = re.compile(
    r"^\s*([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9.\s\-]{0,48}?)\s*:\s*([\d.,]+)\s*([a-zA-Z/%µ·./]+)\s*$",
    re.MULTILINE,
)


def _hit_text(hit: Mapping[str, Any]) -> str:
    for key in ("text", "page_content", "content"):
        v = hit.get(key)
        if v:
            return str(v)
    return ""


def _parse_date_to_iso(fragment: str) -> str | None:
    m = _DATE_ISO.search(fragment)
    if m:
        return m.group(1)
    m = _DATE_BR.search(fragment)
    if m:
        try:
            d = datetime.strptime(m.group(1), "%d/%m/%Y")
            return d.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _normalize_metas(metas: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for name, bounds in metas.items():
        if not isinstance(bounds, dict):
            continue
        key = str(name).strip().lower()
        lo = bounds.get("min")
        hi = bounds.get("max")
        out[key] = {
            "min": float(lo) if lo is not None else None,
            "max": float(hi) if hi is not None else None,
        }
    return out


def _format_exam_vs_meta(ex: Mapping[str, Any], meta_map: Mapping[str, dict[str, float | None]]) -> str:
    goal = dict(meta_map.get(str(ex["exam_key"]).lower(), {}) or {})
    gmin = goal.get("min")
    gmax = goal.get("max")
    status = "OK"
    if gmin is not None and float(ex["value"]) < float(gmin):
        status = "LOW"
    elif gmax is not None and float(ex["value"]) > float(gmax):
        status = "HIGH"
    if gmin is not None and gmax is not None:
        gr = f"{gmin}-{gmax}"
    elif gmin is not None:
        gr = f"≥{gmin}"
    elif gmax is not None:
        gr = f"≤{gmax}"
    else:
        gr = "N/A"
    return f"{ex['exam']}: {ex['value']} {ex['unit']} ({status}, meta: {gr})"


def extract_and_compare_exams(
    rag_hits: Sequence[Mapping[str, Any]],
    metas: Mapping[str, Any],
) -> str:
    """
    Percorre o texto dos hits, tenta extrair pares (data contextual + exame : valor unidade),
    compara com ``metas`` e devolve um bloco Markdown para prefixar ao pedido ao LLM.

    Limitações: só linhas com ``:`` no formato nome : número unidade; a data é a
    **última** data ISO ou BR encontrada **antes** dessa linha no mesmo chunk (por linha).
    """
    meta_map = _normalize_metas(metas)
    # iso_date -> list of {exam, value, unit}
    by_iso: dict[str, list[dict[str, Any]]] = {}

    for hit in rag_hits:
        content = _hit_text(hit)
        if not content.strip():
            continue
        current_iso: str | None = None
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            iso = _parse_date_to_iso(line)
            if iso:
                current_iso = iso
            m = _EXAM_COLON.match(line)
            if not m:
                continue
            exam_raw = m.group(1).strip()
            value_str = m.group(2).replace(",", ".")
            unit = (m.group(3) or "").strip()
            try:
                value = float(value_str)
            except ValueError:
                continue
            exam_key = exam_raw.lower()
            bucket_iso = current_iso or "sem_data"
            by_iso.setdefault(bucket_iso, []).append(
                {
                    "exam": exam_raw,
                    "exam_key": exam_key,
                    "value": value,
                    "unit": unit,
                }
            )

    if not by_iso:
        return ""

    lines_out: list[str] = []
    for iso in sorted(by_iso.keys(), reverse=True):
        if iso == "sem_data":
            continue
        try:
            label = datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            label = iso
        parts = [_format_exam_vs_meta(ex, meta_map) for ex in by_iso[iso]]
        if parts:
            lines_out.append(f"**{label}:** {' | '.join(parts)}")

    if "sem_data" in by_iso:
        parts = [_format_exam_vs_meta(ex, meta_map) for ex in by_iso["sem_data"]]
        if parts:
            lines_out.append(f"**sem data explícita:** {' | '.join(parts)}")

    if not lines_out:
        return ""

    body = "\n".join(lines_out)
    return f"""Resumo automático (regex) dos exames detectados nos hits vs metas:

{body}

Instrução: cruza isto com os trechos brutos [chunk_id=…]; se discordar, prevalece o texto original. Identifica valores fora de meta (LOW/HIGH) e sugere ajustes alimentares alinhados ao plano NutriDeby (evidência nos documentos)."""
