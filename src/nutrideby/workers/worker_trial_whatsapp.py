"""Worker de Disparo Trial WhatsApp + CookHero"""
import argparse, logging, json, sys, psycopg
from nutrideby.config import Settings

logger = logging.getLogger(__name__)

def get_patients_for_trial(conn: psycopg.Connection, limit: int = 50, include_active: bool = True) -> list:
    """Busca pacientes DietBox para trial"""
    query = "SELECT id, display_name, metadata->>'MobilePhone' as phone, metadata->>'email' as email, source_system FROM patients WHERE source_system='dietbox'"
    if not include_active:
        query += " AND (metadata->>'IsActive' = 'false' OR metadata->>'IsActive' IS NULL)"
    query += f" ORDER BY created_at DESC LIMIT {limit}"
    
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()

def format_whatsapp_message(patient_name: str) -> str:
    """Formata mensagem WhatsApp trial com CookHero (5%)"""
    return f"""👋 Oi {patient_name or 'Amigo'}!

🍱 *Receita do Dia - CookHero*
Frango com Abóbora ao Forno

📸 Envie uma foto da sua refeição
Vamos analisar juntos!

💰 Desbloqueie análise premium
R$ 97 - Análise 100% completa

🔗 Clique para ativar
https://kiwify.app/JzslLqX

NutriDeby 🌱"""

def run(*, limit: int, dry_run: bool, include_active: bool = True) -> int:
    settings = Settings()
    try:
        with psycopg.connect(settings.database_url) as conn:
            patients = get_patients_for_trial(conn, limit=limit, include_active=include_active)
            logger.info(f"worker_trial_whatsapp: encontrados {len(patients)} pacientes dry_run={dry_run}")
            
            for p_id, name, phone, email, source in patients:
                if not phone:
                    logger.warning(f"patient_id={p_id} sem phone — pulando")
                    continue
                
                msg = format_whatsapp_message(name)
                logger.info(f"patient_id={p_id} name={name} phone={phone}\nMENSAGEM:\n{msg}\n---")
                
                if not dry_run:
                    logger.info(f"✓ Disparando para {phone}")
            
            logger.info(f"worker_trial_whatsapp concluído: processadas={len([p for p in patients if p[2]])} dry_run={dry_run}")
            return 0
    except Exception as e:
        logger.error(f"Erro: {e}")
        return 1

def main(argv=None):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--dry-run", action="store_true", default=False)
    p.add_argument("--include-active", action="store_true", default=True)
    args = p.parse_args(argv)
    return run(limit=args.limit, dry_run=args.dry_run, include_active=args.include_active)

if __name__ == "__main__":
    sys.exit(main())
