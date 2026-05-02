#!/usr/bin/env python3
import csv, sqlite3, re

CSV_PATH = "data/pacientes.csv"
DB_PATH  = "data/pacientes.db"

def limpar_numero(raw):
    if not raw:
        return None
    d = re.sub(r'\D', '', str(raw))
    if len(d) < 8:
        return None
    if not d.startswith('55'):
        d = '55' + d
    return d

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()
cur.execute("""
CREATE TABLE pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT, email TEXT, ativo TEXT, nascimento TEXT,
    sexo TEXT, celular TEXT, cadastro TEXT, ocupacao TEXT,
    local TEXT, enviado INTEGER DEFAULT 0
)
""")
conn.commit()

with open(CSV_PATH, encoding='utf-8', errors='replace') as f:
    reader = csv.reader(f, delimiter='|')
    ok = False
    n  = 0
    for row in reader:
        if not ok:
            if 'Nome' in row:
                ok = True
            continue
        if len(row) < 6:
            continue
        nome     = row[0].strip()
        email    = row[1].strip()
        ativo    = row[2].strip()
        nasc     = row[3].strip()
        sexo     = row[4].strip()
        celular  = limpar_numero(row[5])
        cadastro = row[7].strip()  if len(row) > 7  else ''
        ocupacao = row[8].strip()  if len(row) > 8  else ''
        local    = row[18].strip() if len(row) > 18 else ''
        if not nome:
            continue
        cur.execute(
            "INSERT INTO pacientes (nome,email,ativo,nascimento,sexo,celular,cadastro,ocupacao,local) VALUES (?,?,?,?,?,?,?,?,?)",
            (nome,email,ativo,nasc,sexo,celular,cadastro,ocupacao,local)
        )
        n += 1

conn.commit()

cur.execute("SELECT COUNT(*) FROM pacientes WHERE ativo='Nao' OR ativo LIKE 'N%'")
inativos = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM pacientes WHERE (ativo='Nao' OR ativo LIKE 'N%') AND celular IS NOT NULL")
alvo = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM pacientes WHERE ativo LIKE 'S%'")
ativos = cur.fetchone()[0]

conn.close()
print(f"Importados : {n}")
print(f"Ativos     : {ativos}")
print(f"Inativos   : {inativos}")
print(f"Inativos c/ celular: {alvo}  <- alvo campanha")
