#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sqlite3
import pandas as pd
import os
import sys

def migrar():
    csv_path = "data/pacientes.csv"
    db_path = "data/pacientes.db"
    
    if not os.path.exists(csv_path):
        print(f"❌ Arquivo CSV não encontrado: {csv_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    df = pd.read_csv(csv_path, sep='|', encoding='utf-8', on_bad_lines='skip', skiprows=1)
    df.columns = df.columns.str.strip()
    df.to_sql('pacientes', conn, if_exists='replace', index=False)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ativo ON pacientes(Ativo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nome ON pacientes(Nome)")
    
    conn.commit()
    conn.close()
    
    print(f"✅ Banco de dados criado em {db_path}")
    print(f"   Total de registros: {len(df)}")
    print(f"   Colunas: {list(df.columns)}")

if __name__ == "__main__":
    migrar()
