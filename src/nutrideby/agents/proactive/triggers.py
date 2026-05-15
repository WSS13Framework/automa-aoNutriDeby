"""
Motor de Gatilhos Proativos (NutriDeby - Agente de Execução)

Este módulo define os gatilhos que a IA monitora para agir proativamente.
O nutricionista (Diretor) define as regras, e a IA (Gerente de Operações) executa.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class ProactiveTriggers:
    def __init__(self, db_conn):
        self.db = db_conn

    def check_inactivity(self, days=1):
        """
        Gatilho: Paciente não envia dados ou interage há X dias.
        Ação: IA envia mensagem de incentivo/cobrança no WhatsApp.
        """
        logger.info(f"Verificando inatividade de pacientes (> {days} dias)...")
        # TODO: Implementar query SQL para buscar pacientes sem logs recentes
        pass

    def check_dietary_deviation(self, threshold=0.2):
        """
        Gatilho: IA detecta desvio calórico ou de macros acima do limite.
        Ação: IA notifica o nutricionista e questiona o paciente.
        """
        logger.info(f"Verificando desvios dietéticos (> {threshold*100}%)...")
        # TODO: Implementar lógica de comparação plano vs real
        pass

    def check_clinical_risks(self):
        """
        Gatilho: Novos exames ou sintomas indicam risco clínico.
        Ação: Alerta imediato ao nutricionista (Diretor).
        """
        logger.info("Verificando riscos clínicos em novos dados...")
        # TODO: Implementar análise de exames via LLM
        pass
