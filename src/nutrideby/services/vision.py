"""
Chamadas às APIs de visão IA para análise de composição corporal.
Extraído de bodyscan_router._call_claude_vision e composicao_router._call_vision.
"""
from __future__ import annotations

import base64
import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_CLAUDE_PROMPT = (
    "Você é um especialista em avaliação física e composição corporal para nutrição clínica.\n"
    "Analise as fotos enviadas do paciente e estime os parâmetros abaixo com base em características "
    "visuais (silhueta, distribuição de gordura, definição muscular, postura).\n\n"
    "Retorne SOMENTE um JSON válido, sem texto extra, sem markdown, no formato:\n"
    '{\n'
    '  "body_fat_pct": <número 0-100, uma casa decimal>,\n'
    '  "muscle_mass_pct": <número 0-100, uma casa decimal>,\n'
    '  "lean_mass_kg": <número ou null>,\n'
    '  "analysis_notes": "<parágrafo em português com observações clínicas sobre composição corporal, '
    'postura e recomendações nutricionais. Seja encorajador e profissional.>"\n'
    "}\n\n"
    "Diretrizes:\n"
    "- body_fat_pct: percentual de gordura corporal total estimado visualmente\n"
    "- muscle_mass_pct: percentual de massa muscular esquelética estimado\n"
    "- lean_mass_kg: massa magra em kg (use null se não tiver referência de peso)\n"
    "- analysis_notes: 3-4 frases em português úteis para planejamento nutricional\n"
    "- Nunca faça diagnósticos médicos\n"
    "- Seja conservador e realista nas estimativas\n"
    "- Sempre responda em português"
)

_GPT4O_PROMPT = """Você é especialista em avaliação física e composição corporal.
Analise as fotos do paciente e estime com base em silhueta, distribuição de gordura e definição muscular.

Retorne SOMENTE JSON válido, sem texto extra:
{
  "body_fat_pct": <número 0-100, uma casa decimal>,
  "muscle_mass_pct": <número 0-100, uma casa decimal>,
  "notas": "<observações clínicas em português, 2-3 frases>"
}

Seja conservador. Se as fotos forem insuficientes, estime com o que for possível e indique nas notas.
Responda sempre em português."""


def call_claude_vision(
    image_sources: list[dict], api_key: str, model: str
) -> dict[str, Any]:
    """Chama Claude Vision (Anthropic) para análise de composição corporal."""
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada")

    content: list[dict] = []
    for src in image_sources:
        if src["type"] == "url":
            with urllib.request.urlopen(src["data"], timeout=30) as r:
                img_data = r.read()
            b64 = base64.b64encode(img_data).decode("ascii")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })
        else:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": src["mime"], "data": src["data"]},
            })
    content.append({"type": "text", "text": _CLAUDE_PROMPT})

    body = json.dumps({
        "model": model,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"Claude API HTTP {e.code}: {raw[:400]}")

    resp_json = json.loads(raw)
    text = resp_json["content"][0]["text"].strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].rstrip()
    return json.loads(text)


def call_gpt4o_vision(
    sources: list[dict], api_key: str, api_base: str
) -> dict[str, Any]:
    """Chama GPT-4o Vision (OpenAI) para análise de composição corporal."""
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não configurada")

    content: list[dict] = [{"type": "text", "text": _GPT4O_PROMPT}]
    for src in sources:
        img_url = (
            f"data:{src['mime']};base64,{src['data']}"
            if src["type"] == "base64"
            else src["data"]
        )
        content.append({"type": "image_url", "image_url": {"url": img_url, "detail": "high"}})

    body = json.dumps({
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    url = f"{api_base.rstrip('/')}/v1/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"Vision HTTP {e.code}: {raw[:300]}")

    return json.loads(json.loads(raw)["choices"][0]["message"]["content"])
