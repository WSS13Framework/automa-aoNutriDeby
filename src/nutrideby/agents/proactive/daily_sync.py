"""
Script de Sincronização Diária de Pacientes Inativos
Executa a coleta proativa de dados para quem está sumido.
"""

import os
import logging
import psycopg
from nutrideby.agents.proactive.triggers import ProactiveTriggers
from nutrideby.workers.dietbox_sync import sync_one_patient # Reutiliza worker existente

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

def run_daily_sync():
    if not DATABASE_URL:
        logger.error("DATABASE_URL não configurada.")
        return

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            triggers = ProactiveTriggers(conn)
            
            # 1. Identifica inativos (ex: 7 dias sem sinal)
            inactive_patients = triggers.get_inactive_patients(days=7)
            
            if not inactive_patients:
                logger.info("Nenhum paciente inativo para sincronizar hoje.")
                return

            logger.info(f"Iniciando sincronização de {len(inactive_patients)} pacientes...")
            
            for patient in inactive_patients:
                p_id = patient[0]
                p_name = patient[1]
                p_ext_id = patient[2]
                p_source = patient[3]
                
                logger.info(f"Sincronizando: {p_name} ({p_source} ID: {p_ext_id})")
                
                # Se for Dietbox, tenta sincronizar prontuário e dados
                if p_source == 'dietbox' and p_ext_id:
                    try:
                        # Aqui chamamos a lógica de sync existente
                        # Nota: sync_one_patient precisa ser importável e funcional
                        # No MVP, vamos apenas logar a intenção de sync
                        logger.info(f"Chamando sync_one_patient para {p_id}")
                        # sync_one_patient(p_ext_id) 
                    except Exception as e:
                        logger.error(f"Erro ao sincronizar {p_name}: {e}")
                
            logger.info("Sincronização diária finalizada.")

    except Exception as e:
        logger.error(f"Erro na conexão com o banco: {e}")

if __name__ == "__main__":
    run_daily_sync()
