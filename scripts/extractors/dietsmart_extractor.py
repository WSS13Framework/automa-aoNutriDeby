#!/usr/bin/env python3
"""
NutriDeby — Extrator DietSmart
================================
Três modos de extração:

  Modo 1 — Firebird local (.FDB)
    Lê o banco Firebird diretamente (DietSmart desktop instalado no PC).
    Requer: firebird-driver + arquivo DIETSMART.FDB acessível.

  Modo 2 — CSV exportado
    Processa CSV exportado pelo DietSmart (Arquivo → Exportar).
    Requer: --csv /caminho/export.csv

  Modo 3 — Login Web (app.dietsmart.com.br) via Playwright  ← NOVO
    Autentica via Blazor WebAssembly, captura token JWT do localStorage,
    e extrai dados dos pacientes via API REST interna ou DOM scraping.
    Requer: playwright + --username EMAIL --password SENHA

Uso:
    python3 dietsmart_extractor.py --mode web --username EMAIL --password SENHA
    python3 dietsmart_extractor.py --mode csv --csv /path/to/export.csv
    python3 dietsmart_extractor.py --mode firebird --db /path/to/DIETSMART.FDB
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from normalizer import normalize_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dietsmart")

BASE_URL = "https://app.dietsmart.com.br"

# Localização padrão do banco DietSmart por OS
DEFAULT_DB_PATHS = [
    r"C:\DietSmart\dados\DIETSMART.FDB",
    os.path.expanduser("~/DietSmart/dados/DIETSMART.FDB"),
    "/opt/DietSmart/dados/DIETSMART.FDB",
]


# ─── MODO 3: Login Web via Playwright ────────────────────────────────────────

def extract_web(username: str, password: str, headless: bool = True) -> list[dict]:
    """
    Autentica no DietSmart Web (app.dietsmart.com.br) via Playwright,
    captura o token JWT e extrai pacientes via API REST interna.
    Fallback: DOM scraping se a API não responder.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.error("playwright não instalado. Execute: pip install playwright && playwright install chromium")
        sys.exit(1)

    pacientes_raw = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        # Interceptar requests para descobrir endpoints internos
        captured_api_urls: list[str] = []

        def _on_request(req):
            url = req.url
            if any(k in url.lower() for k in ["api", "paciente", "patient", "usuario"]):
                if url not in captured_api_urls:
                    captured_api_urls.append(url)
                    log.debug("API request capturada: %s", url)

        page = context.new_page()
        page.on("request", _on_request)

        try:
            # ── Passo 1: Navegar para login ──
            log.info("Navegando para %s", BASE_URL)
            page.goto(BASE_URL, wait_until="networkidle", timeout=30_000)

            # ── Passo 2: Preencher credenciais ──
            log.info("Preenchendo credenciais: %s", username)
            page.wait_for_selector("#login", timeout=15_000)
            page.fill("#login", username)
            page.fill("#pass", password)

            # ── Passo 3: Submeter login ──
            page.click("#entrar")
            log.info("Login submetido. Aguardando Blazor carregar...")

            # Aguardar redirecionamento pós-login
            try:
                page.wait_for_url(lambda url: "login" not in url.lower(), timeout=20_000)
                log.info("Login OK. URL atual: %s", page.url)
            except PWTimeout:
                # Verificar se ainda está na tela de login (credenciais erradas)
                if page.query_selector("#login"):
                    raise ValueError(
                        f"Falha no login DietSmart para '{username}'. "
                        "Verifique as credenciais (usuário/senha)."
                    )
                log.warning("Timeout no redirect, mas não está no login. Continuando...")

            # Aguardar Blazor WASM inicializar completamente
            page.wait_for_load_state("networkidle", timeout=30_000)
            time.sleep(4)  # Blazor precisa de tempo extra para hidratação

            # ── Passo 4: Capturar token JWT ──
            token = page.evaluate("""() => {
                const keys = ['token', 'authToken', 'jwt', 'access_token', 'dietsmartToken',
                              'Token', 'AuthToken', 'JWT'];
                for (const key of keys) {
                    const val = localStorage.getItem(key);
                    if (val && val.length > 20) return val;
                }
                // Buscar qualquer chave com 'token' no nome
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    if (k && k.toLowerCase().includes('token')) {
                        const v = localStorage.getItem(k);
                        if (v && v.length > 20) return v;
                    }
                }
                return null;
            }""")

            if token:
                log.info("Token JWT capturado do localStorage (%d chars)", len(token))
            else:
                log.warning("Token não encontrado no localStorage. Usando cookies de sessão.")

            # Capturar cookies da sessão
            cookies = context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}

            # ── Passo 5: Tentar API REST interna ──
            pacientes_raw = _try_api(token, cookie_dict, captured_api_urls)

            if not pacientes_raw:
                log.info("API REST não respondeu. Tentando navegação + DOM scraping...")
                pacientes_raw = _scrape_dom(page)

        except Exception as e:
            log.error("Erro durante extração web: %s", e)
            try:
                page.screenshot(path="/tmp/dietsmart_debug.png")
                log.info("Screenshot de debug salvo em /tmp/dietsmart_debug.png")
            except Exception:
                pass
            raise
        finally:
            browser.close()

    log.info("Total extraído via web: %d pacientes", len(pacientes_raw))
    return pacientes_raw


def _try_api(token: str | None, cookies: dict, captured_urls: list[str]) -> list[dict]:
    """Tenta chamar a API REST interna do DietSmart com o token capturado."""
    try:
        import requests
    except ImportError:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 Chrome/120.0.0.0",
        "Accept": "application/json",
        "Referer": BASE_URL,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Endpoints candidatos (descobertos via inspeção + padrões comuns Blazor/.NET)
    endpoints = [
        f"{BASE_URL}/api/paciente",
        f"{BASE_URL}/api/pacientes",
        f"{BASE_URL}/api/Paciente",
        f"{BASE_URL}/api/Paciente/GetAll",
        f"{BASE_URL}/api/Paciente/Listar",
        f"{BASE_URL}/api/v1/paciente",
        f"{BASE_URL}/Paciente/GetAll",
    ] + captured_urls

    session = requests.Session()
    session.headers.update(headers)
    session.cookies.update(cookies)

    for url in endpoints:
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    log.info("API funcionou: %s — %d registros", url, len(data))
                    return data
                if isinstance(data, dict):
                    for key in ("pacientes", "data", "items", "result"):
                        items = data.get(key)
                        if items and isinstance(items, list):
                            log.info("API funcionou: %s — %d registros", url, len(items))
                            return items
        except Exception as e:
            log.debug("Endpoint %s: %s", url, e)

    return []


def _scrape_dom(page) -> list[dict]:
    """Fallback: extrai pacientes via DOM do Blazor renderizado."""
    pacientes = []
    try:
        # Aguardar tabela ou lista de pacientes renderizar
        page.wait_for_load_state("networkidle", timeout=10_000)

        # Tentar clicar no menu de pacientes se existir
        for selector in ["a[href*='paciente']", "a[href*='Paciente']", ".nav-link"]:
            try:
                links = page.query_selector_all(selector)
                for link in links:
                    text = (link.inner_text() or "").lower()
                    if "paciente" in text or "cliente" in text:
                        link.click()
                        page.wait_for_load_state("networkidle", timeout=10_000)
                        time.sleep(2)
                        break
            except Exception:
                pass

        # Extrair linhas de tabela
        rows = page.query_selector_all("table tbody tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if not cells:
                continue
            p = {
                "id": row.get_attribute("data-id") or row.get_attribute("data-paciente-id") or "",
                "nome": cells[0].inner_text().strip() if len(cells) > 0 else "",
                "email": cells[1].inner_text().strip() if len(cells) > 1 else "",
                "telefone": cells[2].inner_text().strip() if len(cells) > 2 else "",
            }
            if p["nome"]:
                pacientes.append(p)

        log.info("DOM scraping: %d pacientes encontrados", len(pacientes))
    except Exception as e:
        log.error("DOM scraping falhou: %s", e)

    return pacientes


# ─── MODO 2: CSV exportado ────────────────────────────────────────────────────

def extract_csv(csv_path: str) -> list[dict]:
    """Processa CSV exportado pelo DietSmart (Arquivo → Exportar Pacientes)."""
    import csv
    patients = []
    for encoding in ["utf-8-sig", "latin-1", "cp1252"]:
        try:
            with open(csv_path, encoding=encoding, newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    patients.append({k.strip().lower(): (v or "").strip() for k, v in row.items()})
            log.info("CSV lido com encoding %s: %d pacientes", encoding, len(patients))
            return patients
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Não foi possível decodificar o CSV: {csv_path}")


# ─── MODO 1: Firebird local ───────────────────────────────────────────────────

def find_db() -> str | None:
    for path in DEFAULT_DB_PATHS:
        if os.path.exists(path):
            return path
    return None


def extract_firebird(db_path: str, user: str = "SYSDBA", password: str = "masterkey") -> list[dict]:
    """Lê o banco Firebird local do DietSmart desktop."""
    try:
        import firebird.driver as fdb
    except ImportError:
        try:
            import fdb
        except ImportError:
            log.error("Instale firebird-driver: pip install firebird-driver")
            sys.exit(1)

    con = fdb.connect(database=db_path, user=user, password=password, charset="WIN1252")
    cur = con.cursor()
    cur.execute("""
        SELECT c.ID_CLIENTE, c.NOME, c.EMAIL, c.TELEFONE, c.CELULAR,
               c.DATA_NASCIMENTO, c.SEXO, c.CPF, c.OBJETIVO
        FROM CLIENTE c ORDER BY c.NOME
    """)
    cols = [d[0].lower() for d in cur.description]
    patients = []
    for row in cur.fetchall():
        p = dict(zip(cols, row))
        pid = p["id_cliente"]

        for table, field, key in [
            ("ANAMNESE", "ID_CLIENTE", "prontuario"),
            ("PLANO_ALIMENTAR", "ID_CLIENTE", "metas_nutricionais"),
        ]:
            try:
                c2 = con.cursor()
                c2.execute(f"SELECT * FROM {table} WHERE {field}=? ORDER BY 1 DESC ROWS 1", (pid,))
                r2 = c2.fetchone()
                if r2:
                    p[key] = dict(zip([d[0].lower() for d in c2.description], r2))
            except Exception:
                pass

        patients.append(p)
        log.info("Paciente: %s", p.get("nome", pid))

    con.close()
    log.info("Firebird: %d pacientes lidos", len(patients))
    return patients


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extrator DietSmart → schema NutriDeby")
    parser.add_argument("--mode", choices=["web", "csv", "firebird"], default="web",
                        help="Modo de extração (default: web)")
    parser.add_argument("--username", help="E-mail DietSmart Web (modo web)")
    parser.add_argument("--password", help="Senha DietSmart Web (modo web)")
    parser.add_argument("--no-headless", action="store_true",
                        help="Abrir browser visível para debug (modo web)")
    parser.add_argument("--csv", help="Caminho do CSV exportado (modo csv)")
    parser.add_argument("--db", help="Caminho do arquivo .FDB (modo firebird)")
    parser.add_argument("--fb-user", default="SYSDBA")
    parser.add_argument("--fb-password", default="masterkey")
    parser.add_argument("--output", default="pacientes_dietsmart.json")
    args = parser.parse_args()

    if args.mode == "web":
        if not args.username or not args.password:
            parser.error("--username e --password são obrigatórios no modo web")
        raw = extract_web(args.username, args.password, headless=not args.no_headless)
        result = normalize_batch(raw, "dietsmart_web")

    elif args.mode == "csv":
        if not args.csv:
            parser.error("--csv é obrigatório no modo csv")
        raw = extract_csv(args.csv)
        result = normalize_batch(raw, "dietsmart_csv")

    elif args.mode == "firebird":
        db_path = args.db or find_db()
        if not db_path:
            log.error("Banco DietSmart não encontrado. Use --db /caminho/DIETSMART.FDB")
            sys.exit(1)
        raw = extract_firebird(db_path, args.fb_user, args.fb_password)
        result = normalize_batch(raw, "dietsmart_firebird")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info("Exportados %d pacientes → %s", result["total"], args.output)
    print(json.dumps({"total": result["total"], "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
