import pywhatkit as kit
import time
import pandas as pd
import sqlite3
import os

# Configurações
DB_PATH = "data/pacientes.db"
DRY_RUN = False          # Mude para False para enviar de verdade
LIMITE = 2

def enviar_mensagem(numero, mensagem):
    # pywhatkit espera número no formato: "55DDDnumero" (sem +)
    # Delay de 15 segundos para abrir o WhatsApp Web
    kit.sendwhatmsg_instantly(numero, mensagem, 15, True, 3)
    time.sleep(20)  # aguarda envio

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT nome, celular FROM pacientes WHERE ativo LIKE 'N%' AND celular IS NOT NULL LIMIT ?", (LIMITE,))
    pacientes = cursor.fetchall()
    conn.close()

    for nome, cel in pacientes:
        numero = cel.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not numero.startswith("55"):
            numero = "55" + numero
        print(f"Enviando para {nome} ({numero})...")
        if not DRY_RUN:
            try:
                enviar_mensagem(numero, f"Olá {nome}, aqui é a nutricionista Débora. Gostaria de saber como você está. Estou com agenda aberta para retomada de acompanhimento. 🥗")
                print("✅ Enviado")
            except Exception as e:
                print(f"❌ Erro: {e}")
        else:
            print("🔧 [DRY RUN] - não enviado")
        time.sleep(5)

if __name__ == "__main__":
    main()
