"""
NutriDeby — Platform Detector
Identifica a plataforma de nutrição a partir de texto livre (URL, nome, domínio).
Determinístico: regex + dicionário. Sem IA — rápido e sem custo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DetectionResult:
    platform: str                    # 'dietbox' | 'dietsmart' | 'nutrium' | 'nutricloud' | 'dietsystem' | 'generic'
    confidence: float                # 0.0 – 1.0
    display_name: str                # nome amigável
    rota: str                        # 'api' | 'csv' | 'pdf' | 'firebird'
    instructions: str                # instrução para o usuário
    requires_url: bool               # precisa de URL base?
    icon: str                        # emoji para UI


_PLATFORMS = [
    {
        "id": "dietbox",
        "display_name": "Dietbox",
        "patterns": [r"dietbox", r"dietbox\.me", r"app\.dietbox"],
        "rota": "api",
        "instructions": "Entre com seu e-mail e senha do Dietbox.",
        "requires_url": False,
        "icon": "🥗",
    },
    {
        "id": "dietsmart",
        "display_name": "DietSmart",
        "patterns": [r"dietsmart", r"diet\s*smart", r"\.fdb$", r"firebird"],
        "rota": "firebird",
        "instructions": "Informe o caminho do arquivo .FDB ou exporte um CSV pelo DietSmart.",
        "requires_url": False,
        "icon": "🧠",
    },
    {
        "id": "nutrium",
        "display_name": "Nutrium",
        "patterns": [r"nutrium", r"app\.nutrium\.com", r"nutrium\.com"],
        "rota": "pdf",
        "instructions": "Faça login no Nutrium, exporte o PDF do paciente e faça upload aqui.",
        "requires_url": False,
        "icon": "📄",
    },
    {
        "id": "nutricloud",
        "display_name": "NutriCloud",
        "patterns": [r"nutricloud", r"nutri\s*cloud", r"nutricloud\.com\.br"],
        "rota": "csv",
        "instructions": "Entre com seu e-mail e senha do NutriCloud.",
        "requires_url": False,
        "icon": "☁️",
    },
    {
        "id": "dietsystem",
        "display_name": "DietSystem",
        "patterns": [r"dietsystem", r"diet\s*system"],
        "rota": "csv",
        "instructions": "Exporte o CSV de pacientes pelo DietSystem e faça upload aqui.",
        "requires_url": False,
        "icon": "💊",
    },
    {
        "id": "dietpro",
        "display_name": "DietPro",
        "patterns": [r"dietpro", r"diet\s*pro", r"dietpro\.com\.br"],
        "rota": "csv",
        "instructions": "Exporte o CSV de pacientes pelo DietPro e faça upload aqui.",
        "requires_url": False,
        "icon": "🥦",
    },
]


def detect(text: str) -> DetectionResult:
    """
    Detecta a plataforma a partir de texto livre.
    Retorna DetectionResult com confidence 1.0 se match exato, 0.8 se parcial.
    Se não detectar, retorna 'generic' com confidence 0.0.
    """
    normalized = text.strip().lower()

    for p in _PLATFORMS:
        for pattern in p["patterns"]:
            if re.search(pattern, normalized, re.IGNORECASE):
                confidence = 1.0 if normalized in p["patterns"] else 0.85
                return DetectionResult(
                    platform=p["id"],
                    confidence=confidence,
                    display_name=p["display_name"],
                    rota=p["rota"],
                    instructions=p["instructions"],
                    requires_url=p["requires_url"],
                    icon=p["icon"],
                )

    return DetectionResult(
        platform="generic",
        confidence=0.0,
        display_name="Plataforma não identificada",
        rota="csv",
        instructions="Exporte um CSV ou XLSX da sua plataforma e faça upload aqui.",
        requires_url=False,
        icon="📁",
    )


def list_platforms() -> list[dict]:
    """Retorna lista de plataformas suportadas para exibição no wizard."""
    return [
        {
            "id": p["id"],
            "display_name": p["display_name"],
            "rota": p["rota"],
            "instructions": p["instructions"],
            "icon": p["icon"],
        }
        for p in _PLATFORMS
    ] + [
        {
            "id": "generic",
            "display_name": "Outro / Genérico",
            "rota": "csv",
            "instructions": "Exporte um CSV ou XLSX da sua plataforma e faça upload aqui.",
            "icon": "📁",
        }
    ]
