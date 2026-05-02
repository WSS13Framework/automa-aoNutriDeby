"""
Conector Dietbox (API v2) — Sprint 1 / MVP.

  python -m nutrideby.workers.dietbox_sync --probe PACIENTE_ID
  python -m nutrideby.workers.dietbox_sync --sync-one PACIENTE_ID   # prontuário → documents
  python -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 1

Requer .env: DATABASE_URL, DIETBOX_BEARER_TOKEN; opcional DIETBOX_API_BASE.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.parse

import psycopg

from nutrideby.clients.dietbox_api import (
    DietboxClient,
    extract_list_payload,
    parse_json_body,
    patient_record_from_item,
)
from nutrideby.config import Settings
from nutrideby.persist.crm_persist import insert_document_if_new, upsert_patient

logger = logging.getLogger(__name__)

SOURCE = "dietbox"


def _client(settings: Settings) -> DietboxClient:
    base = settings.dietbox_api_base or "https://api.dietbox.me"
    return DietboxClient(base, settings.dietbox_bearer_token or "")


def probe_prontuario(settings: Settings, patient_id: str) -> int:
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    st, body = c.get_prontuario(patient_id)
    logger.info("probe paciente=%s HTTP=%s bytes=%s", patient_id, st, len(body))
    return 0 if st in (200, 204) else 1


def sync_one_prontuario(settings: Settings, patient_id: str) -> int:
    """Grava paciente + conteúdo do prontuário (200 JSON ou 204 marcador)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN")
        return 2
    c = _client(settings)
    st, body = c.get_prontuario(patient_id)
    if st not in (200, 204):
        logger.error("HTTP %s", st)
        return 1
    if st == 204 or not body:
        text = "[Prontuário: API 204 sem corpo]"
    else:
        try:
            text = json.dumps(
                json.loads(body.decode("utf-8")),
                ensure_ascii=False,
                indent=2,
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = body.decode("utf-8", errors="replace")
    meta = {"dietbox_paciente_id": patient_id, "prontuario_http_status": st}
    base = (settings.dietbox_api_base or "https://api.dietbox.me").rstrip("/")
    with psycopg.connect(settings.database_url) as conn:
        pid = upsert_patient(
            conn,
            source_system=SOURCE,
            external_id=patient_id,
            display_name=f"Dietbox #{patient_id}",
            metadata=meta,
        )
        ref = f"{base}/v2/paciente/{patient_id}/prontuario"
        new = insert_document_if_new(
            conn,
            patient_id=pid,
            doc_type="dietbox_prontuario",
            content_text=text,
            source_ref=ref,
        )
        logger.info("sync-one prontuário internal_id=%s doc_novo=%s", pid, new is not None)
    return 0


def sync_one_patient_detail(settings: Settings, patient_id: str) -> int:
    """GET /v2/paciente/{id} e upsert em patients (metadados da API)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    path = f"v2/paciente/{urllib.parse.quote(patient_id, safe='')}"
    status, raw = c.get_path(path)
    if status == 404:
        logger.error("Paciente não encontrado: %s", patient_id)
        return 1
    if status != 200:
        logger.error("GET paciente HTTP=%s corpo=%r", status, raw[:300])
        return 1
    data = parse_json_body(raw)
    item: dict | None = None
    if isinstance(data, dict):
        if patient_record_from_item(data) is not None:
            item = data
        else:
            found = extract_list_payload(data)
            if len(found) == 1:
                item = found[0]
    if item is None:
        logger.error("Resposta inesperada para paciente=%s tipo=%s", patient_id, type(data).__name__)
        return 1
    rec = patient_record_from_item(item)
    if rec is None:
        logger.error("Não foi possível extrair id/nome do JSON para paciente=%s", patient_id)
        return 1
    ext_id, display, meta = rec
    with psycopg.connect(settings.database_url) as conn:
        upsert_patient(
            conn,
            source_system=SOURCE,
            external_id=ext_id,
            display_name=display,
            metadata=meta,
        )
    logger.info("sync-patient-detail OK external_id=%s", ext_id)
    return 0


def sync_patient_list(
    settings: Settings,
    *,
    take: int = 10,
    max_pages: int = 1,
    is_active: bool | None = True,
) -> int:
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    total_upsert = 0
    skip = 0
    pages = 0
    while pages < max_pages:
        q: dict[str, str | int | bool] = {
            "skip": skip,
            "take": take,
            "order": "name",
        }
        if is_active is not None:
            q["IsActive"] = str(is_active).lower()
        qs = urllib.parse.urlencode(q)
        path = f"v2/paciente?{qs}"
        status, raw = c.get_path(path)
        if status != 200:
            logger.error("Lista pacientes HTTP=%s path=%s corpo=%r", status, path, raw[:300])
            return 1
        data = parse_json_body(raw)
        items = extract_list_payload(data)
        if not items:
            logger.info("sync-list: skip=%s sem itens (fim ou formato inesperado)", skip)
            if isinstance(data, dict):
                logger.info("Chaves no topo do JSON: %s", list(data.keys()))
            elif data is not None:
                logger.info("Tipo do JSON raiz: %s", type(data).__name__)
            break
        with psycopg.connect(settings.database_url) as conn:
            for item in items:
                rec = patient_record_from_item(item)
                if rec is None:
                    continue
                ext_id, display, meta = rec
                upsert_patient(
                    conn,
                    source_system=SOURCE,
                    external_id=ext_id,
                    display_name=display,
                    metadata=meta,
                )
                total_upsert += 1
        pages += 1
        if len(items) < take:
            break
        skip += take
    logger.info("sync-list concluído: upserts=%s páginas=%s", total_upsert, pages)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Conector Dietbox — API v2")
    p.add_argument("--probe", metavar="PACIENTE_ID", help="Testa GET prontuário")
    p.add_argument(
        "--sync-one",
        metavar="PACIENTE_ID",
        help="Grava prontuário (200/204) em documents + paciente",
    )
    p.add_argument(
        "--sync-patient",
        metavar="PACIENTE_ID",
        help="GET /v2/paciente/{id} e upsert só em patients (nome/metadata)",
    )
    p.add_argument(
        "--sync-list",
        action="store_true",
        help="Lista paginada GET /v2/paciente → patients",
    )
    p.add_argument("--take", type=int, default=10)
    p.add_argument("--max-pages", type=int, default=1)
    p.add_argument(
        "--include-inactive",
        action="store_true",
        help="Sem filtro IsActive na lista",
    )
    args = p.parse_args(argv)
    settings = Settings()

    if args.probe:
        return probe_prontuario(settings, args.probe)
    if args.sync_one:
        return sync_one_prontuario(settings, args.sync_one)
    if args.sync_patient:
        return sync_one_patient_detail(settings, args.sync_patient)
    if args.sync_list:
        return sync_patient_list(
            settings,
            take=args.take,
            max_pages=args.max_pages,
            is_active=None if args.include_inactive else True,
        )
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
