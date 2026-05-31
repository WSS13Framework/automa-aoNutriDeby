"""
Importa telefones do CSV exportado pelo Dietbox → patient_phones.

Uso:
  python3 -m nutrideby.workers.import_phones --csv data/pacientes_teste.csv [--dry-run]

Formato esperado: sep=| na 1ª linha, delimitador |, colunas Nome / Celular / Telefone.
Faz match por nome normalizado contra display_name no banco.
Normaliza para E.164 (+55...).
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import unicodedata
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from nutrideby.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_DDD = "21"


def _norm_name(name: str) -> str:
    """Normaliza nome para comparação: lowercase, sem acentos, espaços extras."""
    s = unicodedata.normalize("NFD", name.lower().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _parse_phone_raw(raw: str) -> str:
    """Remove Excel ="" wrapper e limpa espaços."""
    s = raw.strip()
    # Excel: ="21999999999"
    m = re.match(r'^="?(.*?)"?$', s)
    if m:
        s = m.group(1)
    return s.strip()


def _normalize_e164(raw: str, default_ddd: str = DEFAULT_DDD) -> str | None:
    """Converte número brasileiro para E.164 (+55DDNNNNNNNNN)."""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None

    # Já E.164 com + (ex: +5521999999999)
    if raw.strip().startswith("+"):
        if digits.startswith("55") and len(digits) >= 12:
            return "+" + digits
        return None

    # Com código país 55
    if digits.startswith("55") and len(digits) >= 12:
        return "+" + digits

    # Com DDD (10 ou 11 dígitos)
    if len(digits) in (10, 11):
        return "+55" + digits

    # Sem DDD (8 ou 9 dígitos) — usa DDD padrão
    if len(digits) in (8, 9):
        return "+55" + default_ddd + digits

    return None


def import_phones(settings: Settings, path: Path, *, dry_run: bool = False) -> int:
    if not path.is_file():
        logger.error("Arquivo não encontrado: %s", path)
        return 1

    with path.open(encoding="utf-8", newline="") as f:
        lines = [l for l in f if not l.startswith("sep=")]

    reader = list(csv.DictReader(io.StringIO("".join(lines)), delimiter="|"))
    logger.info("CSV: %d linhas lidas", len(reader))

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        # Carrega todos os pacientes indexados por nome normalizado
        with conn.cursor() as cur:
            cur.execute("SELECT id, display_name FROM patients WHERE display_name IS NOT NULL")
            patients = cur.fetchall()

        name_index: dict[str, list[str]] = {}
        for p in patients:
            key = _norm_name(p["display_name"])
            name_index.setdefault(key, []).append(str(p["id"]))

        inserted = 0
        skipped_no_phone = 0
        skipped_no_match = 0
        skipped_invalid = 0
        skipped_duplicate = 0

        for row in reader:
            nome = (row.get("Nome") or "").strip()
            if not nome:
                continue

            cel_raw = _parse_phone_raw(row.get("Celular") or "")
            tel_raw = _parse_phone_raw(row.get("Telefone") or "")
            raw_phone = cel_raw or tel_raw

            if not raw_phone:
                skipped_no_phone += 1
                continue

            phone = _normalize_e164(raw_phone)
            if not phone:
                logger.warning("Telefone inválido ignorado — nome=%s raw=%s", nome, raw_phone)
                skipped_invalid += 1
                continue

            key = _norm_name(nome)
            patient_ids = name_index.get(key)
            if not patient_ids:
                logger.warning("Paciente não encontrado — nome=%s", nome)
                skipped_no_match += 1
                continue

            for pid in patient_ids:
                if dry_run:
                    logger.info("[DRY-RUN] %s → %s → %s", nome, pid, phone)
                    inserted += 1
                    continue

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO patient_phones (patient_id, phone, source)
                        VALUES (%s, %s, 'csv_import')
                        ON CONFLICT (phone) DO NOTHING
                        """,
                        (pid, phone),
                    )
                    if cur.rowcount:
                        inserted += 1
                        logger.info("Inserido: %s → %s", nome, phone)
                    else:
                        skipped_duplicate += 1

        if not dry_run:
            conn.commit()

    logger.info(
        "Resultado: inseridos=%d sem_telefone=%d sem_match=%d invalido=%d duplicado=%d",
        inserted, skipped_no_phone, skipped_no_match, skipped_invalid, skipped_duplicate,
    )
    return 0


def _cli() -> int:
    global DEFAULT_DDD
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    p = argparse.ArgumentParser(description="Importa telefones do CSV Dietbox → patient_phones")
    p.add_argument("--csv", type=Path, required=True, metavar="ARQUIVO")
    p.add_argument("--dry-run", action="store_true", help="Simula sem gravar no banco")
    p.add_argument("--ddd", default=DEFAULT_DDD, help="DDD padrão para números sem código de área (default: 21)")
    args = p.parse_args()
    DEFAULT_DDD = args.ddd
    return import_phones(Settings(), args.csv, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(_cli())
