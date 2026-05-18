"""
US-02: processa ``integration_webhook_inbox`` com ``source=kiwify``.

  python3 -m nutrideby.workers.process_kiwify_inbox --limit 20 --dry-run
  python3 -m nutrideby.workers.process_kiwify_inbox --limit 50

Para cada linha ``pending``:
- Cria/actualiza patient source_system=kiwify (sempre)
- Se telefone bater com DietBox existente → activa IsActive + cria transaction
- Caso contrário → skip silencioso
- Erro de base → status=error
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from typing import Any

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


def _activate_dietbox_patient(
    conn: psycopg.Connection,
    *,
    phone_digits: str,
    parsed: dict[str, Any],
    raw_payload: Any,
    inbox_row_id: Any,
) -> bool:
    """
    Busca paciente DietBox pelo MobilePhone (últimos 11 dígitos).
    Se achar: ativa IsActive=true + cria transação.
    Retorna True se activou.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, display_name FROM patients
            WHERE source_system = 'dietbox'
              AND right(regexp_replace(
                    coalesce(metadata->>'MobilePhone', ''),
                    '[^0-9]', '', 'g'
                  ), 11) = right(%s, 11)
            LIMIT 1
            """,
            [phone_digits[-11:]],
        )
        row = cur.fetchone()
        if not row:
            logger.info(
                "inbox_id=%s phone=%s nao encontrado no DietBox — paciente novo",
                inbox_row_id,
                phone_digits,
            )
            return False

        pid = row["id"]

        # Activa paciente
        cur.execute(
            """
            UPDATE patients
            SET metadata   = metadata || '{"IsActive": true}'::jsonb,
                updated_at = now()
            WHERE id = %s
            """,
            [pid],
        )

        # Cria transação (idempotente pelo external_transaction_id)
        cur.execute(
            """
            INSERT INTO transactions
                (patient_id, external_transaction_id, product_name,
                 value, status, payment_method, raw_webhook, kiwify_transaction_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                pid,
                parsed.get("order_id", ""),
                parsed.get("product_id") or "kiwify_purchase",
                None,
                "approved",
                "kiwify",
                json.dumps(raw_payload),
                parsed.get("order_id", ""),
            ],
        )

        logger.info(
            "DietBox activado: patient_id=%s nome=%r order_id=%s",
            pid,
            row["display_name"],
            parsed.get("order_id"),
        )
        return True


def run(*, limit: int, dry_run: bool) -> int:
    settings = Settings()
    handled = upserts = skipped = errors = activated = 0

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
                    finalize_webhook_inbox(conn, row_id=row_id, status="processed", error_message=note)
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
            logger.info("inbox_id=%s order_id=%s nome=%r dry_run=%s", row_id, oid, display, dry_run)

            if dry_run:
                handled += 1
                upserts += 1
                continue

            try:
                # 1. Cria/actualiza patient kiwify (sempre)
                upsert_patient(
                    conn,
                    source_system=SOURCE_PATIENT,
                    external_id=str(oid),
                    display_name=display[:500] if display else None,
                    metadata=meta,
                )

                # 2. Tenta activar DietBox pelo telefone
                raw_phone = parsed.get("phone") or ""
                phone_digits = re.sub(r"\D", "", raw_phone)
                if phone_digits:
                    ok = _activate_dietbox_patient(
                        conn,
                        phone_digits=phone_digits,
                        parsed=parsed,
                        raw_payload=payload,
                        inbox_row_id=row_id,
                    )
                    if ok:
                        activated += 1

                finalize_webhook_inbox(conn, row_id=row_id, status="processed", error_message=None)
                conn.commit()

            except Exception as e:
                errors += 1
                logger.exception("inbox_id=%s erro ao processar", row_id)
                try:
                    finalize_webhook_inbox(conn, row_id=row_id, status="error", error_message=str(e)[:2000])
                    conn.commit()
                except Exception:
                    conn.rollback()
                handled += 1
                continue

            handled += 1
            upserts += 1

    logger.info(
        "process_kiwify_inbox concluído: tratadas=%s upserts=%s activated=%s skips=%s errors=%s",
        handled, upserts, activated, skipped, errors,
    )
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Processar inbox Kiwify → patients")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    return run(limit=max(1, args.limit), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
