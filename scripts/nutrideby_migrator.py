"""
NutriDeby Migrator — Extração e Sincronização de Dados (Windows)
Foco: DietSmart Desktop (.FDB) -> NutriDeby API

Este script localiza o banco de dados do DietSmart, extrai pacientes e prontuários,
e envia para a API NutriDeby de forma segura.
"""
import os
import sys
import json
import hashlib
import sqlite3
import requests
import platform
from datetime import datetime
from pathlib import Path

# Configurações da API
API_URL = "https://seu-servidor.com/api/importar"
API_KEY = "SUA_API_KEY_AQUI"

# Caminhos padrão do DietSmart no Windows
DIETSMART_PATHS = [
    r"C:\DietSmart\Dados\DIETSMART.FDB",
    r"D:\DietSmart\Dados\DIETSMART.FDB",
    os.path.expanduser(r"~\Documents\DietSmart\Dados\DIETSMART.FDB")
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def find_dietsmart_db():
    for path in DIETSMART_PATHS:
        if os.path.exists(path):
            return path
    return None

def extract_from_fdb(db_path):
    """
    Extrai dados do Firebird (.FDB).
    Nota: Requer fdb (pip install fdb).
    """
    try:
        import fdb
    except ImportError:
        log("Erro: Biblioteca 'fdb' não instalada. Use 'pip install fdb'.")
        return []

    log(f"Conectando ao banco: {db_path}")
    try:
        # DietSmart padrão: user=SYSDBA, password=masterkey
        conn = fdb.connect(database=db_path, user='SYSDBA', password='masterkey', charset='WIN1252')
        cur = conn.cursor()
        
        # 1. Extrair Pacientes
        log("Extraindo pacientes...")
        cur.execute("SELECT ID, NOME, EMAIL, TELEFONE, CPF, DATA_NASC FROM PACIENTES")
        pacientes = []
        for row in cur.fetchall():
            pacientes.append({
                "id_externo": str(row[0]),
                "nome": row[1],
                "email": row[2],
                "telefone": row[3],
                "cpf": row[4],
                "data_nascimento": row[5].isoformat() if row[5] else None,
                "source_platform": "dietsmart_desktop"
            })
        
        # 2. Extrair Prontuários (Consultas/Evoluções)
        log(f"Extraindo prontuários de {len(pacientes)} pacientes...")
        for p in pacientes:
            cur.execute("SELECT DATA, TEXTO FROM CONSULTAS WHERE ID_PACIENTE = ?", (p["id_externo"],))
            prontuarios = []
            for row in cur.fetchall():
                content = row[1]
                if content:
                    prontuarios.append({
                        "data": row[0].isoformat() if row[0] else None,
                        "texto": content,
                        "hash": hashlib.sha256(content.encode('utf-8')).hexdigest()
                    })
            p["prontuarios"] = prontuarios
            
        conn.close()
        return pacientes
    except Exception as e:
        log(f"Erro na extração: {e}")
        return []

def send_to_api(data):
    if not data:
        log("Nenhum dado para enviar.")
        return
    
    log(f"Enviando {len(data)} pacientes para a API...")
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "source_platform": "dietsmart_desktop",
        "pacientes": data
    }
    
    try:
        r = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            log("Sincronização concluída com sucesso!")
            print(json.dumps(r.json(), indent=2))
        else:
            log(f"Erro na API ({r.status_code}): {r.text}")
    except Exception as e:
        log(f"Erro de conexão: {e}")

def main():
    print("="*60)
    print(" NutriDeby Migrator v1.0 ")
    print("="*60)
    
    if platform.system() != "Windows":
        log("Aviso: Este script foi projetado para Windows (DietSmart Desktop).")
    
    db_path = find_dietsmart_db()
    if not db_path:
        log("Erro: Banco de dados DIETSMART.FDB não encontrado nos caminhos padrão.")
        db_path = input("Por favor, digite o caminho completo do arquivo .FDB: ").strip('"')
        if not os.path.exists(db_path):
            log("Caminho inválido. Abortando.")
            return

    pacientes = extract_from_fdb(db_path)
    if pacientes:
        log(f"Total extraído: {len(pacientes)} pacientes.")
        confirm = input("Deseja iniciar a sincronização com a nuvem? (s/n): ")
        if confirm.lower() == 's':
            send_to_api(pacientes)
    else:
        log("Nenhum dado extraído.")

    input("\nPressione Enter para sair...")

if __name__ == "__main__":
    main()
