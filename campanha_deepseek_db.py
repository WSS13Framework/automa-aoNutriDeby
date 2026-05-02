#!/usr/bin/env python3
import sqlite3, os, time, logging, re
from datetime import datetime

DB_PATH          = "data/pacientes.db"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENCLAW_URL     = os.getenv("OPENCLAW_URL", "http://localhost:3000/api/send")
DRY_RUN          = os.getenv("DRY_RUN", "true").lower() == "true"
LIMITE           = int(os.getenv("LIMITE", "3"))
DELAY            = int(os.getenv("DELAY", "3"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

def calcular_idade(nasc):
    try:
        ano = int(nasc.strip().split('/')[-1])
        return datetime.now().year - ano if ano > 1900 else None
    except:
        return None

def gerar_mensagem(nome, idade, ocupacao):
    if not DEEPSEEK_API_KEY:
        primeiro = nome.split()[0]
        return (f"Oi {primeiro}! 😊 Aqui é a Dra. Débora Oliver, nutricionista. "
                f"Faz um tempinho que não nos falamos e gostaria de saber como você está. "
                f"Estou com agenda aberta para retomada de acompanhamento nutricional. "
                f"Posso te ajudar? 🥗")
    from openai import OpenAI
    client   = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
    primeiro = nome.split()[0]
    idade_s  = f"{idade} anos" if idade else "paciente"
    ocup_s   = f", {ocupacao}" if ocupacao else ""
    prompt   = (
        f"Você é a nutricionista Dra. Débora Oliver. Escreva uma mensagem de WhatsApp "
        f"curta (máximo 80 palavras) para reativar o paciente {primeiro} ({idade_s}{ocup_s}). "
        f"Mencione que está com agenda disponível para nova consulta. "
        f"Tom humano e acolhedor. Sem diagnóstico médico. Assine como Dra. Débora."
    )
    try:
        r = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role":"user","content":prompt}],
            temperature=0.7, max_tokens=200
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"DeepSeek: {e}")
        return None

def enviar_whatsapp(numero, mensagem):
    import requests
    try:
        r = requests.post(OPENCLAW_URL, json={"phone": numero, "message": mensagem}, timeout=15)
        return r.status_code == 200
    except Exception as e:
        log.error(f"WhatsApp: {e}")
        return False

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()
cur.execute("""
    SELECT id, nome, nascimento, ocupacao, celular
    FROM pacientes
    WHERE (ativo LIKE 'N%') AND celular IS NOT NULL AND enviado = 0
    LIMIT ?
""", (LIMITE,))
pacientes = cur.fetchall()

log.info(f"DRY_RUN={DRY_RUN} | Selecionados: {len(pacientes)} | Limite: {LIMITE}")

for pid, nome, nasc, ocup, celular in pacientes:
    idade = calcular_idade(nasc)
    msg   = gerar_mensagem(nome, idade, ocup)
    if not msg:
        log.warning(f"[SKIP] {nome}")
        continue
    log.info(f"\n{'='*50}\nPara  : {nome}\nFone  : {celular}\nMsg   :\n{msg}\n{'='*50}")
    if not DRY_RUN:
        ok = enviar_whatsapp(celular, msg)
        status = "ENVIADO" if ok else "FALHA"
        if ok:
            cur.execute("UPDATE pacientes SET enviado=1 WHERE id=?", (pid,))
            conn.commit()
    else:
        status = "DRY_RUN"
    log.info(f"[{status}] {nome}")
    time.sleep(DELAY)

conn.close()
log.info("Campanha finalizada.")
