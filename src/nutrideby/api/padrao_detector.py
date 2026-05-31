"""
padrao_detector.py — Detecta fase comportamental alimentar.
Fases: ESCAPE · CONFRONTO · RETORNO · CULPA
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# ── Gatilhos por categoria ────────────────────────────────────────────────────
_GATILHOS = {
    "fast_food":    ["coxinha","hamburguer","hambúrguer","big mac","mcdonalds","mc donalds",
                     "burguer","burger","frango frito","nugget","pizza","hotdog","hot dog",
                     "cachorro quente","pastel","esfiha","esfirra","coxão","batata frita"],
    "doce":         ["sorvete","chocolate","brigadeiro","bolo","pudim","torta","doce",
                     "biscoito recheado","oreo","bolacha recheada","nutella","waffle",
                     "donuts","donut","açúcar","açaí com granola","açaí"],
    "bebida":       ["refrigerante","coca","pepsi","guaraná","fanta","suco de caixinha",
                     "energético","red bull","monster","cerveja","vinho","caipirinha",
                     "vodka","uísque","whisky"],
    "ultraprocessado":["salgadinho","chips","doritos","ruffles","cheetos","miojo",
                       "macarrão instantâneo","nissin","yakisoba instantâneo"],
    "compulsao":    ["comi muito","comi demais","exagerei","não consegui parar",
                     "descontrolei","compulsão","gula","ataque"],
}

_TODOS_GATILHOS = [t for lista in _GATILHOS.values() for t in lista]


def _detectar_gatilhos(descricao: str) -> list[str]:
    desc = descricao.lower()
    return [t for t in _TODOS_GATILHOS if t in desc]


def _historico_paciente(conn, patient_id: str) -> dict:
    """Busca padrões recentes e streak do paciente."""
    with conn.cursor() as cur:
        # Padrões nos últimos 30 dias
        cur.execute(
            """
            SELECT fase, ciclo_numero, degradacao_nivel, data_deteccao
            FROM padroes_alimentares
            WHERE patient_id = %s AND data_deteccao > now() - interval '30 days'
            ORDER BY data_deteccao DESC
            LIMIT 20
            """,
            (patient_id,),
        )
        padroes_recentes = cur.fetchall()

        # Dias seguidos SEM gatilhos (streak limpo)
        cur.execute(
            """
            SELECT COUNT(DISTINCT logged_at::date) as dias_limpos
            FROM food_logs
            WHERE patient_id = %s
              AND logged_at > now() - interval '14 days'
              AND id NOT IN (
                  SELECT food_log_id FROM padroes_alimentares
                  WHERE patient_id = %s AND food_log_id IS NOT NULL
              )
            """,
            (patient_id, patient_id),
        )
        streak = cur.fetchone()

        # Total de ciclos do paciente
        cur.execute(
            "SELECT COALESCE(MAX(ciclo_numero), 0) as max_ciclo FROM padroes_alimentares WHERE patient_id = %s",
            (patient_id,),
        )
        ciclos = cur.fetchone()

    return {
        "padroes_recentes": padroes_recentes or [],
        "dias_limpos": (streak or {}).get("dias_limpos") or 0,
        "max_ciclo": (ciclos or {}).get("max_ciclo") or 0,
    }


def _classificar_fase(historico: dict, gatilhos: list[str], hora: int) -> tuple[str, int, int]:
    """
    Retorna (fase, ciclo_numero, degradacao_nivel).
    Lógica:
      ESCAPE   → primeira ocorrência ou início de novo ciclo
      RETORNO  → voltou após streak limpo ≥ 7 dias
      CULPA    → segundo gatilho no mesmo dia ou horário tardio (>22h)
      CONFRONTO → múltiplos ciclos, padrão recorrente dentro de 7 dias
    """
    recentes = historico["padroes_recentes"]
    dias_limpos = historico["dias_limpos"]
    ciclo = historico["max_ciclo"]
    degradacao = 0

    hoje = datetime.now(timezone.utc).date()

    # Gatilho no mesmo dia → CULPA
    gatilho_hoje = any(
        p["data_deteccao"].date() == hoje for p in recentes
    )
    if gatilho_hoje or hora >= 22:
        fase = "CULPA"
        degradacao = min(len(recentes), 3)
        return fase, max(ciclo, 1), degradacao

    # Voltou após período limpo → RETORNO
    if dias_limpos >= 7:
        ciclo += 1
        degradacao = 0
        return "RETORNO", ciclo, degradacao

    # Padrão recorrente na semana → CONFRONTO
    recentes_semana = [
        p for p in recentes
        if p["data_deteccao"] > datetime.now(timezone.utc) - timedelta(days=7)
    ]
    if len(recentes_semana) >= 2:
        degradacao = min(len(recentes_semana), 3)
        return "CONFRONTO", max(ciclo, 1), degradacao

    # Primeiro gatilho → ESCAPE
    if not recentes:
        ciclo = 1
    return "ESCAPE", max(ciclo, 1), degradacao


# ── Respostas prescritivas por fase ──────────────────────────────────────────

_PRESCRICOES = {
    "ESCAPE": {
        "mensagem": "Você está buscando conforto. Isso é humano.",
        "acao": "Beba 300ml de água agora + prepare um chá de camomila.\nSente-se por 5 minutos sem tela.",
        "timer_min": 30,
        "cor": "#f59e0b",
        "emoji": "🌊",
    },
    "CONFRONTO": {
        "mensagem": "Você está aqui de novo — e você reconhece isso. Isso já é progresso.",
        "acao": "Antes da próxima garfada: respire fundo 3x.\nPergunte: 'Estou com fome ou com sentimento?'",
        "timer_min": 15,
        "cor": "#ef4444",
        "emoji": "⚡",
    },
    "RETORNO": {
        "mensagem": "O retorno faz parte. Você foi longe antes — pode ir de novo.",
        "acao": "Anote: o que aconteceu hoje que te trouxe aqui?\nAmanhã: café da manhã proteico antes das 9h.",
        "timer_min": 0,
        "cor": "#8b5cf6",
        "emoji": "🔄",
    },
    "CULPA": {
        "mensagem": "Para. A culpa não vai desfazer — só vai pesar mais.",
        "acao": "Nada de compensação. Beba água.\nNa próxima refeição: proteína + verde. Só isso.",
        "timer_min": 0,
        "cor": "#6366f1",
        "emoji": "💙",
    },
}


def detectar_e_salvar(
    conn,
    patient_id: str,
    food_log_id: str | None,
    descricao_refeicao: str,
) -> dict | None:
    """
    Detecta padrão na refeição registrada.
    Retorna None se não há gatilho.
    Retorna dict com fase, prescrição e timer se detectado.
    """
    gatilhos = _detectar_gatilhos(descricao_refeicao)
    if not gatilhos:
        return None

    hora = datetime.now(timezone.utc).hour
    historico = _historico_paciente(conn, patient_id)
    fase, ciclo, degradacao = _classificar_fase(historico, gatilhos, hora)
    prescricao = _PRESCRICOES[fase]

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO padroes_alimentares
                (patient_id, food_log_id, fase, ciclo_numero,
                 degradacao_nivel, alimentos_gatilho, acao_prescrita, timer_minutos)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                patient_id, food_log_id, fase, ciclo,
                degradacao, gatilhos,
                prescricao["acao"], prescricao["timer_min"],
            ),
        )
        conn.commit()

    logger.info("Padrão detectado patient=%s fase=%s ciclo=%s", patient_id, fase, ciclo)

    return {
        "fase": fase,
        "ciclo_numero": ciclo,
        "degradacao_nivel": degradacao,
        "alimentos_gatilho": gatilhos,
        "resposta": {
            "mensagem": prescricao["mensagem"],
            "acao": prescricao["acao"],
            "timer_minutos": prescricao["timer_min"],
            "cor": prescricao["cor"],
            "emoji": prescricao["emoji"],
        },
    }
