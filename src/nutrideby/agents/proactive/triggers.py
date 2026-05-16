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

    def get_inactive_patients(self, days=7):
        """
        Busca pacientes que não tiveram atualização nos últimos X dias.
        Lógica: patients.updated_at < (now - days)
        """
        logger.info(f"Buscando pacientes inativos (> {days} dias)...")
        query = """
            SELECT id, display_name, external_id, source_system, updated_at 
            FROM patients 
            WHERE updated_at < %s
            ORDER BY updated_at ASC
        """
        threshold_date = datetime.now() - timedelta(days=days)
        
        with self.db.cursor() as cur:
            cur.execute(query, (threshold_date,))
            results = cur.fetchall()
            
        logger.info(f"Encontrados {len(results)} pacientes inativos.")
        return results

    def check_inactivity(self, days=7):
        """
        Gatilho: Paciente não envia dados ou interage há X dias.
        Ação: Retorna lista para processamento.
        """
        return self.get_inactive_patients(days=days)

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
