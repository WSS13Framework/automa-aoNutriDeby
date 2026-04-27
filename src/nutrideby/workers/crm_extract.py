"""
Stub do extrator CRM (Datebox) via Playwright.

Implementação real: login, paginação de pacientes, abertura de prontuário e
persistência em `patients` / `documents` (ver infra/sql).

Uso:
  python -m nutrideby.workers.crm_extract --dry-run
  python -m nutrideby.workers.crm_extract --check-db
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from playwright.sync_api import sync_playwright

from nutrideby.config import Settings
from nutrideby.db import check_connection

logger = logging.getLogger(__name__)


def _jitter_ms(low: int = 200, high: int = 800) -> None:
    """Pequena pausa para reduzir padrão totalmente determinístico (uso moderado)."""
    import random

    time.sleep(random.uniform(low / 1000.0, high / 1000.0))


def run_browser_smoke(*, headless: bool, storage_state: str | None) -> None:
    """Sobe Chromium, abre about:blank e encerra — valida ambiente Playwright."""
    with sync_playwright() as p:
        launch_kwargs: dict = {"headless": headless}
        browser = p.chromium.launch(**launch_kwargs)
        try:
            context_kwargs: dict = {}
            if storage_state:
                context_kwargs["storage_state"] = storage_state
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            _jitter_ms()
            page.goto("about:blank", wait_until="domcontentloaded", timeout=30_000)
            logger.info("Playwright OK (about:blank)")
        finally:
            browser.close()


def run_crm_navigation_stub(
    *,
    base_url: str,
    headless: bool,
    storage_state: str | None,
) -> None:
    """
    Navega até a URL base do CRM sem preencher credenciais reais.
    Substitua por fluxo de login e seletores reais quando o Datebox estiver mapeado.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            context_kwargs: dict = {}
            if storage_state:
                context_kwargs["storage_state"] = storage_state
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            _jitter_ms()
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            logger.info("Carregada URL base do CRM (stub): %s", base_url)
        finally:
            browser.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Extrator CRM (Playwright) — stub")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Não acessa o CRM; apenas smoke test do Chromium",
    )
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="Testa conexão com PostgreSQL (DATABASE_URL)",
    )
    args = parser.parse_args(argv)
    settings = Settings()

    if args.check_db:
        ok = check_connection(settings.database_url)
        return 0 if ok else 1

    if args.dry_run:
        run_browser_smoke(
            headless=settings.playwright_headless,
            storage_state=settings.playwright_storage_state,
        )
        return 0

    if not settings.crm_base_url:
        logger.error("Defina CRM_BASE_URL para execução sem --dry-run")
        return 2

    run_crm_navigation_stub(
        base_url=settings.crm_base_url,
        headless=settings.playwright_headless,
        storage_state=settings.playwright_storage_state,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
