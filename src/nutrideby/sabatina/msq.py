"""
MSQ ultra-curto (sabatina de sintomas) — NutriDeby.

12 sintomas-chave agrupados em 6 sistemas corporais, escala 0-4 cada.
Gera score por sistema (0-8) e burden total (0-48).

Mantido sem dependências externas para ser fácil de testar/importar.
"""
from __future__ import annotations

SCALE_HELP = "0 = nunca · 1 = leve/raro · 2 = moderado · 3 = frequente · 4 = intenso/diário"

# Ordem da lista = ordem das perguntas no WhatsApp.
ITEMS: list[dict[str, str]] = [
    {"key": "dig_inchaco",   "system": "Digestivo",    "label": "Inchaço, gases ou estufamento"},
    {"key": "dig_azia",      "system": "Digestivo",    "label": "Azia, má digestão ou refluxo"},
    {"key": "ene_fadiga",    "system": "Energia",      "label": "Cansaço ou fadiga ao longo do dia"},
    {"key": "ene_pos_refei", "system": "Energia",      "label": "Sonolência/queda de energia após comer"},
    {"key": "son_adormecer", "system": "Sono",         "label": "Dificuldade para adormecer"},
    {"key": "son_reparador", "system": "Sono",         "label": "Acordar cansado (sono não reparador)"},
    {"key": "hum_ansiedade", "system": "Humor/Mental", "label": "Ansiedade, irritabilidade ou estresse"},
    {"key": "hum_concentr",  "system": "Humor/Mental", "label": "Dificuldade de concentração ou memória"},
    {"key": "dor_cabeca",    "system": "Dor",          "label": "Dores de cabeça"},
    {"key": "dor_articular", "system": "Dor",          "label": "Dores musculares ou nas articulações"},
    {"key": "pel_pele",      "system": "Pele/Imune",   "label": "Problemas de pele (acne, coceira, manchas)"},
    {"key": "pel_infec",     "system": "Pele/Imune",   "label": "Resfriados ou infecções frequentes"},
]

MAX_PER_ITEM = 4
MAX_TOTAL = len(ITEMS) * MAX_PER_ITEM  # 48


def systems() -> list[str]:
    """Sistemas na ordem em que aparecem nos itens (sem repetir)."""
    out: list[str] = []
    for it in ITEMS:
        if it["system"] not in out:
            out.append(it["system"])
    return out


def score_by_system(scores: list[int]) -> dict[str, int]:
    agg: dict[str, int] = {s: 0 for s in systems()}
    for it, val in zip(ITEMS, scores):
        agg[it["system"]] += int(val)
    return agg


def max_per_system() -> dict[str, int]:
    agg: dict[str, int] = {s: 0 for s in systems()}
    for it in ITEMS:
        agg[it["system"]] += MAX_PER_ITEM
    return agg


def total_score(scores: list[int]) -> int:
    return sum(int(v) for v in scores)


def burden_level(total: int) -> str:
    """Faixas para escala 0-48."""
    if total <= 8:
        return "baixo"
    if total <= 20:
        return "moderado"
    return "alto"


def render_survey_text(scores: list[int]) -> str:
    """Bloco textual que vira documento + chunk no RAG (fonte citável)."""
    by_sys = score_by_system(scores)
    maxs = max_per_system()
    total = total_score(scores)
    lines = ["SABATINA DE SINTOMAS (MSQ ultra-curto)", "", "Itens (escala 0-4):"]
    for it, val in zip(ITEMS, scores):
        lines.append(f"- [{it['system']}] {it['label']}: {int(val)}/4")
    lines += ["", "Score por sistema:"]
    for s in systems():
        lines.append(f"- {s}: {by_sys[s]}/{maxs[s]}")
    lines += ["", f"Burden total: {total}/{MAX_TOTAL} (nível {burden_level(total)})"]
    return "\n".join(lines)


def render_summary_whatsapp(scores: list[int]) -> str:
    """Resumo curto para responder ao paciente no WhatsApp."""
    by_sys = score_by_system(scores)
    maxs = max_per_system()
    total = total_score(scores)
    ordered = sorted(systems(), key=lambda s: by_sys[s], reverse=True)
    lines = ["📋 *Sua grade de sintomas:*"]
    for s in ordered:
        lines.append(f"• {s}: {by_sys[s]}/{maxs[s]}")
    lines.append(f"\n*Burden total:* {total}/{MAX_TOTAL} ({burden_level(total)})")
    return "\n".join(lines)
