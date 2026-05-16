"""
Agendador de Tarefas Proativas (NutriDeby - Agente de Execução)

Responsável por rodar os gatilhos periodicamente.
"""

import time
import logging
from nutrideby.agents.proactive.triggers import ProactiveTriggers

logger = logging.getLogger(__name__)

def run_proactive_cycle():
    """
    Executa um ciclo completo de verificação proativa.
    Pode ser chamado via Cron ou rodar como um daemon.
    """
    logger.info("Iniciando ciclo de execução proativa...")
    
    # TODO: Obter conexão com o banco
    triggers = ProactiveTriggers(db_conn=None)
    
    # 1. Verifica inatividade
    triggers.check_inactivity(days=1)
    
    # 2. Verifica desvios
    triggers.check_dietary_deviation(threshold=0.2)
    
    # 3. Verifica riscos
    triggers.check_clinical_risks()
    
    logger.info("Ciclo de execução proativa finalizado.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_proactive_cycle()
