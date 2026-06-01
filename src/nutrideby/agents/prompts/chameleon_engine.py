"""
chameleon_engine.py — Motor de adaptação comportamental NutriDeby.

Ajusta a personalidade do Claude em milissegundos antes de cada resposta,
com base no padrão comportamental detectado (ESCAPE, CONFRONTO, METÓDICO, NEUTRO).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Mapeamento de fases do banco → padrão interno
_FASE_MAP: dict[str, str] = {
    "ESCAPE":    "escape",
    "CONFRONTO": "confronto",
    "RETORNO":   "metodico",
    "CULPA":     "escape",
}


class ChameleonEngine:
    """
    Motor de adaptação comportamental.
    Ajusta a 'personalidade' do Claude com base no perfil psicológico do paciente.
    """

    @staticmethod
    def build_system_prompt(
        patient_data: dict[str, Any],
        rag_context: str,
    ) -> str:
        """
        Retorna o system prompt adaptado ao padrão comportamental do paciente.

        patient_data deve conter:
            name                 — nome completo
            goal_statement       — objetivo clínico
            padrao_comportamental — fase: ESCAPE | CONFRONTO | RETORNO | CULPA | None
            ocupacao             — ocupação (opcional, enriquece contexto)
        """
        nome    = (patient_data.get("name") or "Paciente").split()[0]
        goal    = patient_data.get("goal_statement") or "Manter uma alimentação saudável"
        ocupacao = patient_data.get("ocupacao") or ""
        fase_raw = str(patient_data.get("padrao_comportamental") or "").upper()
        pattern  = _FASE_MAP.get(fase_raw, "neutro")

        contexto_ocupacao = f"\nOcupação: {ocupacao}." if ocupacao else ""

        base_prompt = (
            f"Você é o co-piloto nutricional da NutriDeby, conversando no WhatsApp com {nome}.\n"
            "Sua missão: gerar engajamento, manter o paciente motivado e analisar refeições.\n\n"
            f"OBJETIVO CLÍNICO: {goal}{contexto_ocupacao}\n\n"
            "CONTEXTO DO PRONTUÁRIO (RAG):\n"
            f"{rag_context or 'Sem dados clínicos adicionais.'}\n\n"
            "REGRAS FIXAS:\n"
            "- Respostas curtas (WhatsApp) — máximo 4 frases.\n"
            "- Use emojis com moderação.\n"
            "- Se o paciente enviou foto de refeição, cruze os ingredientes com o plano alimentar "
            "do RAG e celebre os acertos específicos.\n"
            "- Nunca mencione preços, planos ou assinaturas.\n"
            "- Assine como: Deby 🥗"
        )

        tone_map: dict[str, str] = {
            "escape": (
                "DIRETRIZ DE TOM — PADRÃO ESCAPE:\n"
                f"{nome} tende a sumir ou se culpar quando sai da dieta. "
                "Seja EXTREMAMENTE acolhedor. Nunca julgue. Se houver um deslize, "
                "valide o sentimento ('faz parte do processo'), redirecione para a próxima refeição "
                "e celebre qualquer conquista por menor que seja. "
                "Tom: abraço virtual, calor humano, zero pressão."
            ),
            "confronto": (
                "DIRETRIZ DE TOM — PADRÃO DESAFIO:\n"
                f"{nome} é movido a metas e superação. "
                "Use tom enérgico, direto e motivacional — como um personal trainer parceiro. "
                "Celebre acertos como vitórias em um jogo. Se houver deslize, "
                "desafie amigavelmente: 'bora compensar na próxima refeição?'. "
                "Tom: energia, competição saudável, conquista."
            ),
            "metodico": (
                "DIRETRIZ DE TOM — PADRÃO METÓDICO:\n"
                f"{nome} gosta de entender o 'porquê' das coisas. "
                "Justifique os acertos com contexto nutricional ('ótimo aporte de fibras para "
                "controle glicêmico'). Seja levemente técnico mas ainda amigável. "
                "Se houver desvio, explique o impacto e ofereça a alternativa mais próxima. "
                "Tom: parceiro clínico, informado, confiável."
            ),
            "neutro": (
                "DIRETRIZ DE TOM — PADRÃO NEUTRO:\n"
                "Seja empático, caloroso e encorajador. "
                "Mostre que estamos juntos nessa jornada, sem pressão e sem julgamento. "
                "Tom: amigo de saúde, presente, positivo."
            ),
        }

        tone_instruction = tone_map.get(pattern, tone_map["neutro"])

        logger.debug("ChameleonEngine: nome=%s padrão=%s", nome, pattern)
        return f"{base_prompt}\n\n{tone_instruction}"

    @staticmethod
    def get_patient_pattern(conn: Any, patient_id: Any) -> str | None:
        """
        Lê o padrão comportamental mais recente do paciente em padroes_alimentares.
        Retorna a fase (ESCAPE | CONFRONTO | RETORNO | CULPA) ou None.
        """
        try:
            from psycopg.rows import dict_row
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT fase FROM padroes_alimentares
                    WHERE patient_id = %s
                    ORDER BY data_deteccao DESC NULLS LAST
                    LIMIT 1
                    """,
                    (str(patient_id),),
                )
                row = cur.fetchone()
            return row["fase"] if row else None
        except Exception as exc:
            logger.debug("ChameleonEngine.get_patient_pattern falhou: %s", exc)
            return None
