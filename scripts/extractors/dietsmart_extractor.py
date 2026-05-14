#!/usr/bin/env python3
"""
NutriDeby — Extrator DietSmart
Lê diretamente o banco Firebird local do DietSmart.
Uso: python3 dietsmart_extractor.py --db /caminho/DIETSMART.FDB --output pacientes_dietsmart.json
Dependências: pip install firebird-driver
Nota: Requer Firebird Client instalado na máquina (fbclient.dll / libfbclient.so)
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

from normalizer import normalize_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dietsmart")

# Localização padrão do banco DietSmart por OS
DEFAULT_DB_PATHS = [
    r"C:\DietSmart\dados\DIETSMART.FDB",
    r"C:\Users\{user}\DietSmart\dados\DIETSMART.FDB",
    os.path.expanduser("~/DietSmart/dados/DIETSMART.FDB"),
    "/opt/DietSmart/dados/DIETSMART.FDB",
]


def find_db() -> str | None:
    for path in DEFAULT_DB_PATHS:
        if os.path.exists(path):
            return path
    return None


def connect(db_path: str, user: str = "SYSDBA", password: str = "masterkey"):
    try:
        import firebird.driver as fdb
        con = fdb.connect(database=db_path, user=user, password=password)
        log.info(f"Conectado ao banco Firebird: {db_path}")
        return con
    except ImportError:
        log.error("firebird-driver não instalado. Execute: pip install firebird-driver")
        sys.exit(1)
    except Exception as e:
        log.error(f"Erro ao conectar ao banco Firebird: {e}")
        sys.exit(1)


def fetch_patients(con) -> list[dict]:
    cur = con.cursor()
    cur.execute("""
        SELECT
            c.ID_CLIENTE,
            c.NOME,
            c.EMAIL,
            c.TELEFONE,
            c.CELULAR,
            c.DATA_NASCIMENTO,
            c.SEXO,
            c.CPF,
            c.ENDERECO,
            c.CIDADE,
            c.ESTADO,
            c.PROFISSAO,
            c.OBJETIVO
        FROM CLIENTE c
        ORDER BY c.NOME
    """)
    cols = [d[0].lower() for d in cur.description]
    patients = []
    for row in cur.fetchall():
        p = dict(zip(cols, row))
        pid = str(p["id_cliente"])

        # Prontuário / Anamnese
        try:
            cur2 = con.cursor()
            cur2.execute("""
                SELECT TEXTO_LIVRE, QUEIXA_PRINCIPAL, HISTORICO_FAMILIAR,
                       MEDICAMENTOS, PATOLOGIAS, ALERGIAS
                FROM ANAMNESE WHERE ID_CLIENTE = ?
                ORDER BY DATA_ANAMNESE DESC ROWS 1
            """, (p["id_cliente"],))
            row2 = cur2.fetchone()
            if row2:
                cols2 = [d[0].lower() for d in cur2.description]
                p["prontuario"] = dict(zip(cols2, row2))
        except Exception:
            pass

        # Metas nutricionais
        try:
            cur3 = con.cursor()
            cur3.execute("""
                SELECT CALORIAS, PROTEINAS, CARBOIDRATOS, GORDURAS, FIBRAS, AGUA
                FROM PLANO_ALIMENTAR WHERE ID_CLIENTE = ?
                ORDER BY DATA_PLANO DESC ROWS 1
            """, (p["id_cliente"],))
            row3 = cur3.fetchone()
            if row3:
                cols3 = [d[0].lower() for d in cur3.description]
                p["metas_nutricionais"] = dict(zip(cols3, row3))
        except Exception:
            pass

        # Antropometria
        try:
            cur4 = con.cursor()
            cur4.execute("""
                SELECT PESO, ALTURA, IMC, CIRCUNFERENCIA_ABDOMINAL,
                       PERCENTUAL_GORDURA, MASSA_MUSCULAR, DATA_CONSULTA
                FROM CONSULTA WHERE ID_CLIENTE = ?
                ORDER BY DATA_CONSULTA DESC ROWS 1
            """, (p["id_cliente"],))
            row4 = cur4.fetchone()
            if row4:
                cols4 = [d[0].lower() for d in cur4.description]
                p["medidas_antropometricas"] = dict(zip(cols4, row4))
        except Exception:
            pass

        # Histórico de evolução
        try:
            cur5 = con.cursor()
            cur5.execute("""
                SELECT DATA_CONSULTA, PESO, OBSERVACOES
                FROM CONSULTA WHERE ID_CLIENTE = ?
                ORDER BY DATA_CONSULTA DESC ROWS 20
            """, (p["id_cliente"],))
            rows5 = cur5.fetchall()
            cols5 = [d[0].lower() for d in cur5.description]
            p["historico_evolucao"] = [dict(zip(cols5, r)) for r in rows5]
        except Exception:
            pass

        patients.append(p)
        log.info(f"Paciente: {p.get('nome', pid)}")

    return patients


def extract_from_csv(csv_path: str) -> list[dict]:
    """Fallback: extrai dados básicos de CSV exportado pelo DietSmart."""
    import csv
    patients = []
    with open(csv_path, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            patients.append({k.lower(): v for k, v in row.items()})
    log.info(f"CSV: {len(patients)} pacientes lidos")
    return patients


def main():
    parser = argparse.ArgumentParser(description="Extrator DietSmart → schema NutriDeby")
    parser.add_argument("--db", help="Caminho para DIETSMART.FDB")
    parser.add_argument("--csv", help="Fallback: caminho para CSV exportado pelo DietSmart")
    parser.add_argument("--output", default="pacientes_dietsmart.json")
    parser.add_argument("--fb-user", default="SYSDBA")
    parser.add_argument("--fb-password", default="masterkey")
    args = parser.parse_args()

    if args.csv:
        raw = extract_from_csv(args.csv)
        result = normalize_batch(raw, "dietsmart")
    else:
        db_path = args.db or find_db()
        if not db_path:
            log.error("Banco DietSmart não encontrado. Use --db /caminho/DIETSMART.FDB")
            sys.exit(1)
        con = connect(db_path, args.fb_user, args.fb_password)
        raw = fetch_patients(con)
        con.close()
        result = normalize_batch(raw, "dietsmart")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"Exportados {result['total']} pacientes → {args.output}")


if __name__ == "__main__":
    main()
