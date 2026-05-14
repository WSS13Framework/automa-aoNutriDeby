#!/usr/bin/env python3
"""
NutriDeby — Extrator Dietbox
Extrai pacientes via API REST autenticada do Dietbox.
Uso: python3 dietbox_extractor.py --output pacientes_dietbox.json
Env vars: DIETBOX_EMAIL, DIETBOX_PASSWORD
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

import requests

from normalizer import normalize_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dietbox")

API_BASE = "https://api.dietbox.me"
API_V2   = f"{API_BASE}/v2"


def login(email: str, password: str) -> str:
    """Autentica e retorna o Bearer token."""
    resp = requests.post(
        f"{API_BASE}/v1/auth/login",
        json={"email": email, "senha": password},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        raise ValueError(f"Token não encontrado na resposta: {data}")
    log.info("Login OK — token obtido")
    return token


def get_patients(token: str, page: int = 1, per_page: int = 50) -> list[dict]:
    """Lista pacientes paginados."""
    headers = {"Authorization": f"Bearer {token}"}
    patients = []
    while True:
        resp = requests.get(
            f"{API_V2}/pacientes",
            headers=headers,
            params={"pagina": page, "itensPorPagina": per_page},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("itens") or data.get("data") or data.get("pacientes") or []
        if not items:
            break
        patients.extend(items)
        log.info(f"Página {page}: {len(items)} pacientes")
        total = data.get("total") or data.get("totalItens") or 0
        if len(patients) >= total or len(items) < per_page:
            break
        page += 1
        time.sleep(0.3)
    return patients


def get_patient_detail(token: str, patient_id: str) -> dict:
    """Busca detalhes completos de um paciente: prontuário, metas, antropometria."""
    headers = {"Authorization": f"Bearer {token}"}
    detail = {}

    endpoints = {
        "prontuario": f"{API_V2}/paciente/{patient_id}/prontuario",
        "metas_nutricionais": f"{API_V2}/paciente/{patient_id}/metas",
        "medidas_antropometricas": f"{API_V2}/paciente/{patient_id}/antropometria",
        "plano_alimentar": f"{API_V2}/paciente/{patient_id}/plano-alimentar",
        "historico_evolucao": f"{API_V2}/paciente/{patient_id}/evolucao",
        "exames": f"{API_V2}/paciente/{patient_id}/exames",
    }

    for key, url in endpoints.items():
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                detail[key] = resp.json()
            elif resp.status_code == 404:
                detail[key] = None
            else:
                log.warning(f"[{patient_id}] {key}: HTTP {resp.status_code}")
        except Exception as e:
            log.warning(f"[{patient_id}] {key}: {e}")
        time.sleep(0.1)

    return detail


def extract(email: str, password: str, limit: int = 0) -> dict:
    token = login(email, password)
    patients_list = get_patients(token)
    if limit:
        patients_list = patients_list[:limit]

    log.info(f"Total de pacientes: {len(patients_list)}")
    enriched = []
    for i, p in enumerate(patients_list, 1):
        pid = str(p.get("id") or p.get("codigo") or "")
        log.info(f"[{i}/{len(patients_list)}] Detalhando paciente {pid}")
        detail = get_patient_detail(token, pid)
        merged = {**p, **detail}
        enriched.append(merged)
        time.sleep(0.2)

    return normalize_batch(enriched, "dietbox")


def main():
    parser = argparse.ArgumentParser(description="Extrator Dietbox → schema NutriDeby")
    parser.add_argument("--output", default="pacientes_dietbox.json")
    parser.add_argument("--limit", type=int, default=0, help="Limitar número de pacientes (0=todos)")
    args = parser.parse_args()

    email = os.environ.get("DIETBOX_EMAIL")
    password = os.environ.get("DIETBOX_PASSWORD")
    if not email or not password:
        log.error("Defina DIETBOX_EMAIL e DIETBOX_PASSWORD como variáveis de ambiente")
        sys.exit(1)

    result = extract(email, password, args.limit)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"Exportados {result['total']} pacientes → {args.output}")


if __name__ == "__main__":
    main()
