"""
US-02 (MVP): processa ``integration_webhook_inbox`` com ``source=kiwify``.

  python3 -m nutrideby.workers.process_kiwify_inbox --limit 20 --dry-run
  python3 -m nutrideby.workers.process_kiwify_inbox --limit 50

Para cada linha ``pending``:
- se o JSON for reconhecido como ``compra_aprovada`` com ``order_id`` (ver
  ``nutrideby.integrations.kiwify_payload``) → ``upsert_patient`` com
  ``source_system=kiwify`` e ``external_id=order_id``;
- caso contrário → marca ``processed`` com nota em ``error_message`` (skip);
- erro de base → ``status=error``.

Requer ``DATABASE_URL``, migração ``003``, payloads reais da Kiwify para validar
o mapeamento de campos.
"""

from __future__ import annotations

import argparse
import logging
import sys

import psycopg
import psycopg.errors
from psycopg.rows import dict_row

from nutrideby.config import Settings
from nutrideby.integrations.kiwify_payload import parse_kiwify_purchase
from nutrideby.persist.crm_persist import upsert_patient
from nutrideby.persist.webhook_inbox import fetch_pending_webhooks, finalize_webhook_inbox

logger = logging.getLogger(__name__)

SOURCE_INBOX = "kiwify"
SOURCE_PATIENT = "kiwify"


def run(*, limit: int, dry_run: bool) -> int:
    settings = Settings()
    handled = 0
    upserts = 0
    skipped = 0
    errors = 0
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        try:
            rows = fetch_pending_webhooks(conn, source=SOURCE_INBOX, limit=limit)
        except psycopg.errors.UndefinedTable:
            logger.error(
                "Tabela integration_webhook_inbox em falta — aplica infra/sql/003_integration_webhook_inbox.sql"
            )
            return 1
        logger.info("process_kiwify_inbox: fila pending=%s dry_run=%s", len(rows), dry_run)
        for row_id, payload in rows:
            parsed = parse_kiwify_purchase(payload)
            if parsed is None:
                skipped += 1
                note = "skip:evento_nao_e_compra_aprovada_ou_sem_order_id"
                logger.info("inbox_id=%s %s", row_id, note)
                if not dry_run:
                    finalize_webhook_inbox(
                        conn,
                        row_id=row_id,
                        status="processed",
                        error_message=note,
                    )
                    conn.commit()
                handled += 1
                continue
            oid = parsed["order_id"]
            meta: dict = {
                "kiwify": True,
                "kiwify_event": parsed["event"],
                "kiwify_order_id": oid,
                "kiwify_inbox_row_id": str(row_id),
            }
            if parsed.get("email"):
                meta["email"] = parsed["email"]
            if parsed.get("phone"):
                meta["phone"] = parsed["phone"]
            if parsed.get("product_id"):
                meta["kiwify_product_id"] = parsed["product_id"]
            display = parsed.get("display_name") or f"Kiwify {oid}"
            logger.info(
                "inbox_id=%s order_id=%s nome=%r dry_run=%s",
                row_id,
                oid,
                display,
                dry_run,
            )
            if dry_run:
                handled += 1
                upserts += 1
                continue
            try:
                upsert_patient(
                    conn,
                    source_system=SOURCE_PATIENT,
                    external_id=str(oid),
                    display_name=display[:500] if display else None,
                    metadata=meta,
                )
                finalize_webhook_inbox(conn, row_id=row_id, status="processed", error_message=None)
                conn.commit()
            except Exception as e:
                errors += 1
                logger.exception("inbox_id=%s erro ao gravar paciente", row_id)
                try:
                    finalize_webhook_inbox(
                        conn,
                        row_id=row_id,
                        status="error",
                        error_message=str(e)[:2000],
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                handled += 1
                continue
            handled += 1
            upserts += 1
    logger.info(
        "process_kiwify_inbox concluído: tratadas=%s upserts=%s skips=%s errors=%s dry_run=%s",
        handled,
        upserts,
        skipped,
        errors,
        dry_run,
    )
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Processar inbox Kiwify → patients (US-02 MVP)")
    p.add_argument("--limit", type=int, default=50, help="Máximo de linhas pending a tratar")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Só logs; não grava patients nem actualiza inbox",
    )
    args = p.parse_args(argv)
    return run(limit=max(1, args.limit), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
