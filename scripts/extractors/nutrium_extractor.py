#!/usr/bin/env python3
"""
NutriDeby — Extrator Nutrium
Extrai dados de PDFs exportados pelo Nutrium usando pdfplumber + regex.
Uso: python3 nutrium_extractor.py --pdf-dir /caminho/pdfs/ --output pacientes_nutrium.json
Dependências: pip install pdfplumber
"""
import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from normalizer import normalize_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("nutrium")


def extract_from_pdf(pdf_path: str) -> dict:
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber não instalado. Execute: pip install pdfplumber")
        sys.exit(1)

    patient = {}
    full_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

    # Nome do paciente
    m = re.search(r"(?:Paciente|Cliente|Nome)[:\s]+([A-ZÀ-Ú][a-zA-ZÀ-ú\s]+)", full_text)
    if m:
        patient["nome"] = m.group(1).strip()

    # Data de nascimento
    m = re.search(r"(?:Nascimento|Data de nascimento)[:\s]+(\d{2}/\d{2}/\d{4})", full_text)
    if m:
        patient["dados_cadastrais"] = patient.get("dados_cadastrais", {})
        patient["dados_cadastrais"]["data_nascimento"] = m.group(1)

    # Sexo
    m = re.search(r"(?:Sexo|Gênero)[:\s]+(Masculino|Feminino|M|F)", full_text, re.IGNORECASE)
    if m:
        patient.setdefault("dados_cadastrais", {})["sexo"] = m.group(1)

    # Peso
    m = re.search(r"(?:Peso)[:\s]+([\d,\.]+)\s*kg", full_text, re.IGNORECASE)
    if m:
        patient.setdefault("medidas_antropometricas", {})["peso_kg"] = m.group(1).replace(",", ".")

    # Altura
    m = re.search(r"(?:Altura)[:\s]+([\d,\.]+)\s*(?:m|cm)", full_text, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(",", "."))
        if val > 3:
            val = val / 100  # cm → m
        patient.setdefault("medidas_antropometricas", {})["altura_m"] = str(val)

    # IMC
    m = re.search(r"(?:IMC|Índice de Massa Corporal)[:\s]+([\d,\.]+)", full_text, re.IGNORECASE)
    if m:
        patient.setdefault("medidas_antropometricas", {})["imc"] = m.group(1).replace(",", ".")

    # Metas calóricas
    m = re.search(r"(?:Calorias|Energia|VET)[:\s]+([\d,\.]+)\s*(?:kcal|cal)", full_text, re.IGNORECASE)
    if m:
        patient.setdefault("metas_nutricionais", {})["calorias"] = m.group(1).replace(",", ".")

    # Macronutrientes
    for macro, pattern in [
        ("proteinas_g", r"Proteínas?[:\s]+([\d,\.]+)\s*g"),
        ("carboidratos_g", r"Carboidratos?[:\s]+([\d,\.]+)\s*g"),
        ("gorduras_g", r"(?:Gorduras?|Lipídios?)[:\s]+([\d,\.]+)\s*g"),
        ("fibras_g", r"Fibras?[:\s]+([\d,\.]+)\s*g"),
    ]:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            patient.setdefault("metas_nutricionais", {})[macro] = m.group(1).replace(",", ".")

    # Prontuário — texto livre
    m = re.search(r"(?:Observações|Anamnese|Histórico)[:\s]+(.+?)(?:\n\n|\Z)", full_text, re.DOTALL | re.IGNORECASE)
    if m:
        patient["prontuario"] = {"texto": m.group(1).strip()[:2000]}

    # External ID baseado no nome do arquivo
    patient["external_id"] = Path(pdf_path).stem
    patient["source_file"] = os.path.basename(pdf_path)

    log.info(f"PDF processado: {os.path.basename(pdf_path)} → {patient.get('nome', 'desconhecido')}")
    return patient


def main():
    parser = argparse.ArgumentParser(description="Extrator Nutrium PDF → schema NutriDeby")
    parser.add_argument("--pdf-dir", required=True, help="Diretório com PDFs exportados do Nutrium")
    parser.add_argument("--output", default="pacientes_nutrium.json")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.exists():
        log.error(f"Diretório não encontrado: {pdf_dir}")
        sys.exit(1)

    pdfs = list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*.PDF"))
    if not pdfs:
        log.error(f"Nenhum PDF encontrado em {pdf_dir}")
        sys.exit(1)

    log.info(f"Processando {len(pdfs)} PDFs...")
    raw = [extract_from_pdf(str(p)) for p in pdfs]
    result = normalize_batch(raw, "nutrium")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"Exportados {result['total']} pacientes → {args.output}")


if __name__ == "__main__":
    main()
