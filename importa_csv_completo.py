#!/usr/bin/env python3
"""Importa CSV do Dietbox para SQLite, limpando números de telefone."""
import csv, re, sqlite3, io, sys

CSV_PATH = "/opt/automa-aoNutriDeby/data/Pacientes.csv"
DB_PATH  = "/opt/automa-aoNutriDeby/data/pacientes.db"

def limpar_fone(raw):
    if not raw:
        return None
    # Remove formato Excel ="+5521..." ou ="21..."
    s = re.sub(r'^=?"?\+?', '', raw.strip().strip('"'))
    s = re.sub(r'"$', '', s)
    # Remove espaços, hífens, parênteses, underscores
    s = re.sub(r'[\s\-\(\)_]', '', s)
    # Só dígitos
    digits = re.sub(r'\D', '', s)
    if not digits or len(digits) < 8:
        return None
    # Adiciona 55 se não tiver DDI
    if not digits.startswith('55'):
        digits = '55' + digits
    # Valida: 55 + DD (2) + número (8 ou 9) = 12 ou 13 dígitos
    if len(digits) < 12 or len(digits) > 13:
        return None
    return digits

conn = sqlite3.connect(DB_PATH)
conn.execute("""CREATE TABLE IF NOT EXISTS pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT, email TEXT, ativo TEXT, nascimento TEXT,
    sexo TEXT, celular TEXT, cadastro TEXT, ocupacao TEXT,
    local TEXT, enviado INTEGER DEFAULT 0
)""")
conn.commit()

with open(CSV_PATH, encoding='utf-8-sig') as f:
    # Pula linha "sep=|"
    primeira = f.readline()
    if not primeira.startswith('sep'):
        f.seek(0)
    reader = csv.DictReader(f, delimiter='|')
    inseridos = 0
    sem_fone = 0
    for row in reader:
        nome = (row.get('Nome') or '').strip()
        if not nome:
            continue
        email    = (row.get('Email') or '').strip()
        ativo    = (row.get('Ativo') or '').strip()
        nasc     = (row.get('Data de nascimento') or '').strip()
        sexo     = (row.get('Sexo') or '').strip()
        celular  = limpar_fone(row.get('Celular') or '')
        telefone = limpar_fone(row.get('Telefone') or '')
        fone     = celular or telefone
        cadastro = (row.get('Data de cadastro') or '').strip()
        ocupacao = (row.get('Ocupação') or '').strip()
        local    = (row.get('Local de atendimento') or '').strip()

        if not fone:
            sem_fone += 1

        conn.execute("""
            INSERT OR IGNORE INTO pacientes (nome,email,ativo,nascimento,sexo,celular,cadastro,ocupacao,local)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (nome, email, ativo, nasc, sexo, fone, cadastro, ocupacao, local))
        inseridos += 1

conn.commit()

total = conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]
com_fone = conn.execute("SELECT COUNT(*) FROM pacientes WHERE celular IS NOT NULL").fetchone()[0]
inativos_com_fone = conn.execute(
    "SELECT COUNT(*) FROM pacientes WHERE ativo LIKE 'N%' AND celular IS NOT NULL"
).fetchone()[0]
conn.close()

print(f"✅ Importados : {inseridos}")
print(f"📱 Com telefone: {com_fone} / {total}")
print(f"🎯 Inativos com fone (alvo da campanha): {inativos_com_fone}")
