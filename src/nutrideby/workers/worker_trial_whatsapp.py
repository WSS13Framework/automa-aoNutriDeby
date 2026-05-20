"""Worker para disparo de mensagens WhatsApp trial NutriDeby"""
import argparse
import logging
import sys
from typing import Optional, List, Tuple
import psycopg
from twilio.rest import Client
from nutrideby.config import Settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Config Twilio
TWILIO_ACCOUNT_SID = 'AC93dd6712677973ba2cd6db053099c365'
TWILIO_AUTH_TOKEN = '8ac1ecb44ead0fa3d539288d61f661f4'
TWILIO_WHATSAPP_FROM = 'whatsapp:+14155238886'

# Config Planos
PLAN_CONFIG = {
    'basico': {
        'price': 'R$ 97',
        'duration': '30 dias',
        'analyses': '5 análises/dia',
        'kiwify_link': 'https://pay.kiwify.com.br/nutrideby-basico'
    },
    'intermediario': {
        'price': 'R$ 197',
        'duration': '60 dias',
        'analyses': '15 análises/dia',
        'kiwify_link': 'https://pay.kiwify.com.br/nutrideby-intermediario'
    },
    'premium': {
        'price': 'R$ 397',
        'duration': 'Ilimitado',
        'analyses': 'Ilimitado',
        'kiwify_link': 'https://pay.kiwify.com.br/nutrideby-premium'
    }
}

def get_inactive_patients(conn: psycopg.Connection, limit: int) -> List[Tuple]:
    """Busca pacientes inativos com MobilePhone válido"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                id,
                display_name,
                metadata->>'MobilePhone' as phone
            FROM patients
            WHERE source_system='dietbox'
              AND metadata->>'IsActive' = 'false'
              AND metadata->>'MobilePhone' IS NOT NULL
              AND metadata->>'MobilePhone' ~ '^\+55[0-9]{10,11}$'
            ORDER BY created_at DESC
            LIMIT %s
        """, [limit])
        return cur.fetchall()

def format_message(patient_name: str, plan: str) -> str:
    """Formata mensagem WhatsApp por plano"""
    config = PLAN_CONFIG[plan]
    return f"""🤖 *Plano NutriDeby IA 24/7*

📸 Foto do Alimento → Macros em Tempo Real
✅ {config['analyses']}
💡 Sugestões Personalizadas 24/7

💰 {config['price']} - {config['duration']}

🔗 Clique para ativar:
{config['kiwify_link']}

Abraços,
NutriDeby 🌱"""

def send_whatsapp(
    client: Client,
    to_phone: str,
    patient_name: str,
    message: str,
    dry_run: bool = True
) -> Optional[str]:
    """Dispara mensagem WhatsApp via Twilio"""
    try:
        if dry_run:
            logger.info(f"[DRY-RUN] {to_phone} | {patient_name}")
            return f"dry_{patient_name}"
        
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=message,
            to=to_phone
        )
        logger.info(f"[ENVIADO] {to_phone} | SID: {msg.sid} | Status: {msg.status}")
        return msg.sid
        
    except Exception as e:
        logger.error(f"[ERRO] {to_phone} | {str(e)}")
        return None

def run(*, limit: int, plan: str, dry_run: bool) -> int:
    """Executa disparo para inativos"""
    if plan not in PLAN_CONFIG:
        logger.error(f"Plano inválido: {plan}")
        return 1
    
    settings = Settings()
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    
    try:
        with psycopg.connect(settings.database_url) as conn:
            patients = get_inactive_patients(conn, limit)
            logger.info(f"Encontrados {len(patients)} inativos | plano={plan.upper()} | dry_run={dry_run}")
            
            success = 0
            errors = 0
            
            for p_id, name, phone in patients:
                to_phone = f'whatsapp:{phone}' if not phone.startswith('+') else f'whatsapp:{phone}'
                message = format_message(name or f'Paciente {p_id}', plan)
                
                result = send_whatsapp(client, to_phone, name or f'Paciente {p_id}', message, dry_run)
                
                if result:
                    success += 1
                else:
                    errors += 1
            
            logger.info(f"RESUMO: {success} enviados | {errors} erros | total={len(patients)}")
            return 0 if errors == 0 else 1
            
    except Exception as e:
        logger.error(f"Erro fatal: {e}", exc_info=True)
        return 1

def main(argv=None):
    p = argparse.ArgumentParser(description="Worker Trial WhatsApp - NutriDeby")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--plan", default='basico', choices=['basico', 'intermediario', 'premium'])
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--activate", action="store_true")
    
    args = p.parse_args(argv)
    dry_run = not args.activate
    
    return run(limit=args.limit, plan=args.plan, dry_run=dry_run)

if __name__ == "__main__":
    sys.exit(main())
