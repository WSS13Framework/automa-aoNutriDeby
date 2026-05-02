"""Sprint 1 — Conector Dietbox (MVP).

  python -m nutrideby.workers.dietbox_sync --probe PACIENTE_ID
  python -m nutrideby.workers.dietbox_sync --sync-one PACIENTE_ID

Requer .env: DATABASE_URL, DIETBOX_BEARER_TOKEN; opcional DIETBOX_API_BASE.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import psycopg

from nutrideby.clients.dietbox_api import DietboxClient
from nutrideby.config import Settings
from nutrideby.persist.crm_persist import insert_document_if_new, upsert_patient

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Conector Dietbox — Sprint 1 MVP")
    p.add_argument("--probe", metavar="PACIENTE_ID", help="Testa GET prontuário")
    p.add_argument("--sync-one", metavar="PACIENTE_ID", help="Grava paciente + prontuário")
    args = p.parse_args(argv)
    settings = Settings()

    if args.probe:
        if not settings.dietbox_bearer_token:
            logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
            return 2
        c = DietboxClient(settings.dietbox_api_base, settings.dietbox_bearer_token)
        st, body = c.get_prontuario(args.probe)
        logger.info("probe paciente=%s HTTP=%s bytes=%s", args.probe, st, len(body))
        return 0 if st in (200, 204) else 1

    if args.sync_one:
        if not settings.dietbox_bearer_token:
            logger.error("Defina DIETBOX_BEARER_TOKEN")
            return 2
        c = DietboxClient(settings.dietbox_api_base, settings.dietbox_bearer_token)
        st, body = c.get_prontuario(args.sync_one)
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
        meta = {"dietbox_paciente_id": args.sync_one, "prontuario_http_status": st}
        with psycopg.connect(settings.database_url) as conn:
            pid = upsert_patient(
                conn,
                source_system="dietbox",
                external_id=args.sync_one,
                display_name=f"Dietbox #{args.sync_one}",
                metadata=meta,
            )
            ref = f"{settings.dietbox_api_base.rstrip('/')}/v2/paciente/{args.sync_one}/prontuario"
            new = insert_document_if_new(
                conn,
                patient_id=pid,
                doc_type="dietbox_prontuario",
                content_text=text,
                source_ref=ref,
            )
            logger.info("sync internal_id=%s doc_novo=%s", pid, new is not None)
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
