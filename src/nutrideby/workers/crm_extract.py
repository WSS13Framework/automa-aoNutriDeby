"""
Stub do extrator CRM (Datebox) via Playwright.

Implementação real: login, paginação de pacientes, abertura de prontuário e
persistência em `patients` / `documents` (ver infra/sql).

Uso:
  python3 -m nutrideby.workers.crm_extract --dry-run
  python3 -m nutrideby.workers.crm_extract --check-db
  python3 -m nutrideby.workers.crm_extract --check-agent
  python3 -m nutrideby.workers.crm_extract --import-csv data/export.csv
  python3 -m nutrideby.workers.crm_extract --import-json data/exemplo_import.json

RAG (retrieve + demo com agente): ``python3 -m nutrideby.workers.rag_demo --help``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from nutrideby.clients.genai_agent import check_agent_inference
from nutrideby.config import Settings
from nutrideby.db import check_connection
from nutrideby.workers.data_import import import_patients_csv, import_patients_json

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


def try_crm_login(page: Page, settings: Settings) -> None:
    """Preenche formulário de login se credenciais e seletores CSS estiverem definidos."""
    u, pw = settings.crm_username, settings.crm_password
    su, sp, btn = (
        settings.crm_login_user_selector,
        settings.crm_login_password_selector,
        settings.crm_login_submit_selector,
    )
    if not all([u, pw, su, sp, btn]):
        logger.info(
            "Login CRM omitido: defina CRM_USERNAME, CRM_PASSWORD e os três "
            "CRM_LOGIN_*_SELECTOR no .env para login automático.",
        )
        return
    _jitter_ms()
    page.fill(su, u)
    page.fill(sp, pw)
    page.click(btn)
    page.wait_for_load_state("domcontentloaded", timeout=60_000)
    logger.info("Login CRM: credenciais enviadas (revisa seletores se falhar).")


def run_crm_navigation_stub(
    *,
    base_url: str,
    headless: bool,
    storage_state: str | None,
    settings: Settings,
) -> None:
    """
    Navega até a URL base do CRM; opcionalmente executa login com seletores do .env.
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
            logger.info("Carregada URL base do CRM: %s", base_url)
            try_crm_login(page, settings)
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
    parser.add_argument(
        "--check-agent",
        action="store_true",
        help="Testa POST ao agente DO GenAI (GENAI_AGENT_URL + GENAI_AGENT_ACCESS_KEY)",
    )
    parser.add_argument(
        "--import-csv",
        metavar="FILE",
        help="Importa export CSV (template em data/pacientes_export_template.csv) para Postgres",
    )
    parser.add_argument(
        "--import-json",
        metavar="FILE",
        help="Importa pacientes/documentos a partir de JSON (ver data/exemplo_import.json)",
    )
    args = parser.parse_args(argv)
    settings = Settings()

    if args.import_csv and args.import_json:
        logger.error("Use apenas um de --import-csv ou --import-json")
        return 2

    if args.check_db:
        ok = check_connection(settings.database_url)
        return 0 if ok else 1

    if args.check_agent:
        if not settings.genai_agent_url or not settings.genai_agent_access_key:
            logger.error(
                "Defina GENAI_AGENT_URL e GENAI_AGENT_ACCESS_KEY para --check-agent",
            )
            return 2
        ok = check_agent_inference(
            settings.genai_agent_url,
            settings.genai_agent_access_key,
        )
        return 0 if ok else 1

    if args.import_csv:
        return import_patients_csv(settings, Path(args.import_csv))

    if args.import_json:
        return import_patients_json(settings, Path(args.import_json))

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
        settings=settings,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
