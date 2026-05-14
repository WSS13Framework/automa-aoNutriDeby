#!/usr/bin/env python3
"""
NutriDeby — Extrator Genérico CSV/XLSX
Aceita qualquer CSV ou XLSX e tenta mapear automaticamente as colunas.
Uso: python3 generic_csv_extractor.py --file dados.csv --platform dietsystem --output saida.json
Dependências: pip install openpyxl
"""
import argparse
import csv
import json
import logging
import os
import sys

from normalizer import normalize_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("generic")

# Palavras-chave para auto-detecção de colunas
FIELD_KEYWORDS = {
    "id": ["id", "codigo", "code", "patient_id"],
    "nome": ["nome", "name", "paciente", "cliente", "patient"],
    "email": ["email", "e-mail", "mail"],
    "telefone": ["telefone", "phone", "celular", "fone", "tel"],
    "data_nascimento": ["nascimento", "birth", "data_nasc", "dob"],
    "sexo": ["sexo", "genero", "gender", "sex"],
    "peso": ["peso", "weight", "kg"],
    "altura": ["altura", "height", "cm", "metro"],
    "imc": ["imc", "bmi"],
    "calorias": ["calorias", "kcal", "energia", "calories", "energy"],
    "proteinas": ["proteina", "protein", "prot"],
    "carboidratos": ["carboidrato", "carb", "cho"],
    "gorduras": ["gordura", "lipid", "fat"],
    "fibras": ["fibra", "fiber"],
    "observacoes": ["observ", "notas", "notes", "anamnese", "prontuario", "historico"],
    "objetivo": ["objetivo", "goal", "meta"],
}


def detect_column(header: str) -> str | None:
    h = header.lower().strip()
    for field, keywords in FIELD_KEYWORDS.items():
        for kw in keywords:
            if kw in h:
                return field
    return None


def read_file(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(h or "").strip() for h in rows[0]]
            return [dict(zip(headers, [str(v or "").strip() for v in row])) for row in rows[1:]]
        except ImportError:
            log.error("openpyxl não instalado. Execute: pip install openpyxl")
            sys.exit(1)
    else:
        for enc in ["utf-8", "latin-1", "cp1252"]:
            try:
                with open(path, encoding=enc) as f:
                    for delim in [";", ",", "\t"]:
                        f.seek(0)
                        sample = f.read(1024)
                        if sample.count(delim) > 2:
                            f.seek(0)
                            reader = csv.DictReader(f, delimiter=delim)
                            rows = list(reader)
                            log.info(f"CSV lido: enc={enc}, delim='{delim}', {len(rows)} linhas")
                            return rows
            except UnicodeDecodeError:
                continue
    return []


def auto_map(row: dict) -> dict:
    mapped = {}
    for header, value in row.items():
        field = detect_column(header)
        if field:
            mapped[field] = value
        else:
            mapped[header.lower()] = value
    return {
        "id": mapped.get("id"),
        "nome": mapped.get("nome"),
        "dados_cadastrais": {
            "email": mapped.get("email"),
            "telefone": mapped.get("telefone"),
            "data_nascimento": mapped.get("data_nascimento"),
            "sexo": mapped.get("sexo"),
            "objetivo": mapped.get("objetivo"),
        },
        "medidas_antropometricas": {
            "peso_kg": mapped.get("peso"),
            "altura_m": mapped.get("altura"),
            "imc": mapped.get("imc"),
        },
        "metas_nutricionais": {
            "calorias": mapped.get("calorias"),
            "proteinas_g": mapped.get("proteinas"),
            "carboidratos_g": mapped.get("carboidratos"),
            "gorduras_g": mapped.get("gorduras"),
            "fibras_g": mapped.get("fibras"),
        },
        "prontuario": {"texto": mapped.get("observacoes")},
    }


def main():
    parser = argparse.ArgumentParser(description="Extrator Genérico CSV/XLSX → schema NutriDeby")
    parser.add_argument("--file", required=True, help="Caminho para CSV ou XLSX")
    parser.add_argument("--platform", default="generic", help="Nome da plataforma de origem")
    parser.add_argument("--output", default="pacientes_generic.json")
    args = parser.parse_args()

    raw = read_file(args.file)
    if not raw:
        log.error("Nenhum dado encontrado no arquivo")
        sys.exit(1)

    mapped = [auto_map(r) for r in raw]
    result = normalize_batch(mapped, args.platform)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"Exportados {result['total']} pacientes → {args.output}")


if __name__ == "__main__":
    main()
