#!/usr/bin/env python3
"""
NutriDeby — Extrator NutriCloud
Extrai dados via CSV exportado nativamente pelo NutriCloud.
Uso: python3 nutricloud_extractor.py --csv pacientes.csv --output pacientes_nutricloud.json
"""
import argparse
import csv
import json
import logging
import sys

from normalizer import normalize_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("nutricloud")

# Mapeamento de colunas NutriCloud → schema interno
COLUMN_MAP = {
    "id": "id",
    "codigo": "id",
    "nome": "nome",
    "nome_completo": "nome",
    "email": "email",
    "telefone": "telefone",
    "celular": "celular",
    "data_nascimento": "data_nascimento",
    "nascimento": "data_nascimento",
    "sexo": "sexo",
    "genero": "sexo",
    "peso": "peso",
    "altura": "altura",
    "imc": "imc",
    "objetivo": "objetivo",
    "calorias": "calorias",
    "proteinas": "proteinas",
    "carboidratos": "carboidratos",
    "gorduras": "gorduras",
    "fibras": "fibras",
    "observacoes": "observacoes",
    "profissao": "profissao",
    "cidade": "cidade",
    "estado": "estado",
}


def read_csv(path: str, delimiter: str = ";") -> list[dict]:
    patients = []
    encodings = ["utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(path, encoding=enc) as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                for row in reader:
                    normalized_row = {}
                    for k, v in row.items():
                        key = k.strip().lower().replace(" ", "_").replace("-", "_")
                        mapped = COLUMN_MAP.get(key, key)
                        normalized_row[mapped] = v.strip() if v else None
                    patients.append(normalized_row)
            log.info(f"CSV lido com encoding {enc}: {len(patients)} pacientes")
            return patients
        except UnicodeDecodeError:
            continue
    log.error("Não foi possível ler o CSV com nenhum encoding")
    sys.exit(1)


def map_to_schema(row: dict) -> dict:
    return {
        "id": row.get("id") or row.get("codigo"),
        "nome": row.get("nome"),
        "dados_cadastrais": {
            "email": row.get("email"),
            "telefone": row.get("telefone") or row.get("celular"),
            "data_nascimento": row.get("data_nascimento"),
            "sexo": row.get("sexo"),
            "profissao": row.get("profissao"),
            "objetivo": row.get("objetivo"),
            "cidade": row.get("cidade"),
            "estado": row.get("estado"),
        },
        "medidas_antropometricas": {
            "peso_kg": row.get("peso"),
            "altura_m": row.get("altura"),
            "imc": row.get("imc"),
        },
        "metas_nutricionais": {
            "calorias": row.get("calorias"),
            "proteinas_g": row.get("proteinas"),
            "carboidratos_g": row.get("carboidratos"),
            "gorduras_g": row.get("gorduras"),
            "fibras_g": row.get("fibras"),
        },
        "prontuario": {
            "texto": row.get("observacoes"),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Extrator NutriCloud CSV → schema NutriDeby")
    parser.add_argument("--csv", required=True, help="Caminho para o CSV exportado do NutriCloud")
    parser.add_argument("--delimiter", default=";", help="Delimitador do CSV (padrão: ;)")
    parser.add_argument("--output", default="pacientes_nutricloud.json")
    args = parser.parse_args()

    raw_rows = read_csv(args.csv, args.delimiter)
    mapped = [map_to_schema(r) for r in raw_rows]
    result = normalize_batch(mapped, "nutricloud")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"Exportados {result['total']} pacientes → {args.output}")


if __name__ == "__main__":
    main()
