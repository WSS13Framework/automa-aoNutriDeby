"""
Importação de pacientes e documentos para Postgres (Datebox / exportações).

Formatos suportados:
  - JSON: ver data/exemplo_import.json
  - CSV: mesmo layout que data/pacientes_export_template.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import psycopg

from nutrideby.config import Settings
from nutrideby.persist.crm_persist import insert_document_if_new, upsert_patient

logger = logging.getLogger(__name__)


def _external_id_from_csv_row(row: dict[str, str], row_index: int) -> str:
    url = (row.get("url_perfil") or "").strip()
    if url:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()
    nome = (row.get("nome") or "").strip()
    return hashlib.sha256(f"{nome}|{row_index}".encode("utf-8")).hexdigest()


def import_patients_csv(settings: Settings, path: Path) -> int:
    """Importa CSV; devolve código de saída (0 ok, 1 erro)."""
    if not path.is_file():
        logger.error("Ficheiro não encontrado: %s", path)
        return 1
    patients_upserted = 0
    docs_inserted = 0
    docs_skipped = 0
    try:
        with path.open(encoding="utf-8", newline="") as f, psycopg.connect(
            settings.database_url,
        ) as conn:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                logger.error("CSV sem cabeçalho")
                return 1
            for idx, row in enumerate(reader):
                nome = (row.get("nome") or "").strip()
                if not nome and not (row.get("url_perfil") or "").strip():
                    continue
                ext_id = _external_id_from_csv_row(row, idx)
                meta: dict[str, Any] = {
                    k: (row.get(k) or "").strip()
                    for k in ("url_perfil", "idade", "contato", "objetivos")
                    if (row.get(k) or "").strip()
                }
                pid = upsert_patient(
                    conn,
                    source_system="datebox",
                    external_id=ext_id,
                    display_name=nome or None,
                    metadata=meta,
                )
                patients_upserted += 1
                field_map = (
                    ("datebox_historico", row.get("historico")),
                    ("datebox_prontuarios", row.get("prontuarios")),
                    ("datebox_mensagens", row.get("mensagens")),
                )
                for doc_type, raw in field_map:
                    text = (raw or "").strip()
                    if not text:
                        continue
                    ref = meta.get("url_perfil")
                    new_id = insert_document_if_new(
                        conn,
                        patient_id=pid,
                        doc_type=doc_type,
                        content_text=text,
                        source_ref=ref,
                    )
                    if new_id is not None:
                        docs_inserted += 1
                    else:
                        docs_skipped += 1
    except OSError:
        logger.exception("Erro ao ler CSV")
        return 1
    except Exception:
        logger.exception("Erro ao importar CSV")
        return 1
    logger.info(
        "CSV importado: pacientes(upsert)=%s documentos_novos=%s duplicados_ignorados=%s",
        patients_upserted,
        docs_inserted,
        docs_skipped,
    )
    return 0


def import_patients_json(settings: Settings, path: Path) -> int:
    """Importa JSON com lista `patients`; devolve código de saída."""
    if not path.is_file():
        logger.error("Ficheiro não encontrado: %s", path)
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Erro ao ler JSON")
        return 1
    patients_list = data.get("patients")
    if not isinstance(patients_list, list):
        logger.error("JSON inválido: falta chave 'patients' (lista)")
        return 1
    patients_upserted = 0
    docs_inserted = 0
    docs_skipped = 0
    try:
        with psycopg.connect(settings.database_url) as conn:
            for item in patients_list:
                if not isinstance(item, dict):
                    continue
                ext_id = (item.get("external_id") or "").strip()
                if not ext_id:
                    logger.warning("Entrada sem external_id ignorada: %s", item)
                    continue
                display = (item.get("display_name") or "").strip() or None
                meta = item.get("metadata")
                if meta is not None and not isinstance(meta, dict):
                    meta = {}
                pid = upsert_patient(
                    conn,
                    source_system=str(item.get("source_system") or "datebox"),
                    external_id=ext_id,
                    display_name=display,
                    metadata=meta or {},
                )
                patients_upserted += 1
                docs = item.get("documents") or []
                if not isinstance(docs, list):
                    continue
                for doc in docs:
                    if not isinstance(doc, dict):
                        continue
                    dtype = (doc.get("doc_type") or "").strip()
                    content = (doc.get("content_text") or "").strip()
                    if not dtype or not content:
                        continue
                    sref = doc.get("source_ref")
                    sref = sref.strip() if isinstance(sref, str) else sref
                    new_id = insert_document_if_new(
                        conn,
                        patient_id=pid,
                        doc_type=dtype,
                        content_text=content,
                        source_ref=sref,
                    )
                    if new_id is not None:
                        docs_inserted += 1
                    else:
                        docs_skipped += 1
    except Exception:
        logger.exception("Erro ao importar JSON")
        return 1
    logger.info(
        "JSON importado: pacientes(upsert)=%s documentos_novos=%s duplicados_ignorados=%s",
        patients_upserted,
        docs_inserted,
        docs_skipped,
    )
    return 0


def _cli() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Importação CSV/JSON → Postgres")
    p.add_argument("--csv", type=Path, metavar="FICHEIRO")
    p.add_argument("--json", type=Path, metavar="FICHEIRO")
    args = p.parse_args()
    settings = Settings()
    if args.csv:
        return import_patients_csv(settings, args.csv)
    if args.json:
        return import_patients_json(settings, args.json)
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
