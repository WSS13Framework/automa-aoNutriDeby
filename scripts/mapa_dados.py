#!/usr/bin/env python3
"""
mapa_dados.py — Diagnóstico completo da infra NutriDeby

Uso (dentro do container api ou diretamente no servidor):
  python3 scripts/mapa_dados.py

Mostra onde cada dado está, quantos registros, e o que ainda falta.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nutrideby:nutrideby_dev@postgres:5432/nutrideby")

SEP  = "=" * 60
SEP2 = "-" * 60

def banner(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def section(title: str) -> None:
    print(f"\n{SEP2}")
    print(f"  {title}")
    print(SEP2)

def ok(msg: str)   -> None: print(f"  ✅  {msg}")
def warn(msg: str) -> None: print(f"  ⚠️   {msg}")
def err(msg: str)  -> None: print(f"  ❌  {msg}")
def info(msg: str) -> None: print(f"      {msg}")


# ── PostgreSQL ────────────────────────────────────────────────────────────────

def pg_query(sql: str) -> list[tuple]:
    try:
        import psycopg
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()
    except Exception as e:
        return [("ERRO", str(e))]


def check_postgres() -> None:
    banner("POSTGRESQL — banco principal")

    rows = pg_query("""
        SELECT tablename,
               (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name = t.tablename AND table_schema = 'public') AS ncols
        FROM pg_tables t
        WHERE schemaname = 'public'
        ORDER BY tablename
    """)
    section("Tabelas existentes")
    for r in rows:
        info(f"{r[0]:<35} ({r[1]} colunas)")

    section("Contagem de registros por tabela")
    tables = [
        "patients", "documents", "chunks", "patient_phones",
        "dietbox_medidas", "dietbox_prescricoes", "dietbox_qpc",
        "dietbox_gasto_energetico", "clinical_records",
        "inbound_messages", "food_logs", "extraction_runs",
        "accounts", "waitlist_users", "campaign_drafts",
    ]
    for t in tables:
        rows2 = pg_query(f"SELECT COUNT(*) FROM {t}")
        n = rows2[0][0] if rows2 else "?"
        icon = ok if isinstance(n, int) and n > 0 else warn
        icon(f"{t:<35} {n:>6} registros")

    section("Pacientes — completude")
    rows3 = pg_query("""
        SELECT
          COUNT(*)                                                          AS total,
          COUNT(*) FILTER (WHERE metadata->>'MobilePhone' IS NOT NULL)     AS com_phone_meta,
          COUNT(*) FILTER (WHERE goal_statement IS NOT NULL
                             AND goal_statement <> '')                      AS com_goal,
          COUNT(*) FILTER (WHERE metadata->>'dietbox_paciente_id' IS NOT NULL) AS com_dietbox_id,
          COUNT(*) FILTER (WHERE last_logged_date IS NOT NULL)             AS com_last_logged
        FROM patients
    """)
    if rows3:
        r = rows3[0]
        ok  (f"Total de pacientes:              {r[0]}")
        info(f"Com telefone (metadata):         {r[1]}")
        info(f"Com goal_statement:              {r[2]}")
        info(f"Com dietbox_paciente_id:         {r[3]}")
        info(f"Com last_logged_date:            {r[4]}")

    rows4 = pg_query("SELECT COUNT(DISTINCT patient_id) FROM patient_phones")
    info(f"Com telefone validado (phones):  {rows4[0][0] if rows4 else '?'}")

    section("Documents — qualidade do conteúdo")
    rows5 = pg_query("""
        SELECT
          COUNT(*)                                                              AS total,
          COUNT(*) FILTER (WHERE content_text NOT LIKE '[Prontuário: API 204%'
                             AND content_text NOT LIKE '<!DOCTYPE%'
                             AND content_text NOT LIKE '<html%')               AS texto_limpo,
          COUNT(*) FILTER (WHERE content_text LIKE '<!DOCTYPE%'
                             OR  content_text LIKE '<html%')                   AS html_bruto,
          COUNT(*) FILTER (WHERE content_text LIKE '[Prontuário: API 204%')   AS placeholder_vazio
        FROM documents
    """)
    if rows5:
        r = rows5[0]
        ok  (f"Total documentos:     {r[0]}")
        ok  (f"Texto limpo (útil):   {r[1]}")
        warn(f"HTML bruto (token?):  {r[2]}")
        warn(f"Placeholder vazio:    {r[3]}")

    section("Banco vetorial (chunks/embeddings)")
    rows6 = pg_query("""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE embedding IS NOT NULL)
        FROM chunks
    """)
    if rows6:
        total, com_emb = rows6[0]
        fn = ok if com_emb > 0 else err
        fn(f"Chunks total:    {total}")
        fn(f"Com embedding:   {com_emb}")
        if com_emb == 0:
            err("RAG VAZIO — rodar: chunk_documents + embed_chunks")

    section("Extraction runs (histórico sync Dietbox)")
    rows7 = pg_query("""
        SELECT status, started_at::date, stats
        FROM extraction_runs
        ORDER BY started_at DESC LIMIT 5
    """)
    for r in rows7:
        icon = ok if r[0] == "completed" else err
        icon(f"{r[0]:<12}  {r[1]}  stats={r[2]}")

    section("Pacientes com dados clínicos ricos")
    rows8 = pg_query("""
        SELECT p.display_name,
               COUNT(DISTINCT m.id) AS medidas,
               COUNT(DISTINCT q.id) AS qpc,
               COUNT(DISTINCT pr.id) AS prescricoes
        FROM patients p
        LEFT JOIN dietbox_medidas    m  ON m.patient_id  = p.id
        LEFT JOIN dietbox_qpc        q  ON q.patient_id  = p.id
        LEFT JOIN dietbox_prescricoes pr ON pr.patient_id = p.id
        WHERE m.id IS NOT NULL OR q.id IS NOT NULL OR pr.id IS NOT NULL
        GROUP BY p.id, p.display_name
        ORDER BY (COUNT(DISTINCT m.id) + COUNT(DISTINCT q.id) + COUNT(DISTINCT pr.id)) DESC
        LIMIT 10
    """)
    info(f"{'Paciente':<35} {'Med':>4} {'QPC':>4} {'Presc':>5}")
    info("-" * 50)
    for r in rows8:
        info(f"{(r[0] or 'N/A'):<35} {r[1]:>4} {r[2]:>4} {r[3]:>5}")


# ── SQLite ────────────────────────────────────────────────────────────────────

def check_sqlite() -> None:
    banner("SQLITE — bancos locais")

    dbs = [
        "/opt/dietbox.db",
        "/opt/dietbox_completo.db",
    ]
    for path in dbs:
        p = Path(path)
        if not p.exists():
            warn(f"{path} — NÃO EXISTE")
            continue
        size = p.stat().st_size
        conn = sqlite3.connect(path)
        cur  = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        info(f"\n{path}  ({size//1024}KB)")
        for t in tables:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            n = cur.fetchone()[0]
            fn = ok if n > 0 else warn
            fn(f"  {t:<25} {n} registros")
        conn.close()


# ── Arquivos de dados ─────────────────────────────────────────────────────────

def check_files() -> None:
    banner("ARQUIVOS DE DADOS")

    files = [
        ("/root/todos_pacientes_prontuarios.csv",       "CSV IDs pacientes (prontuário vazio)"),
        ("/root/pacientes.csv.backup-2026-05-01-1719",  "Backup CSV 430 pacientes Dietbox"),
        ("/opt/automa-aoNutriDeby/data/pacientes.csv",  "Template CSV importação"),
        ("/opt/automa-aoNutriDeby/data/pacientes_teste.csv", "CSV teste 51 pacientes"),
        ("/opt/automa-aoNutriDeby/data/taco_completo.json",  "Tabela TACO completa"),
        ("/opt/automa-aoNutriDeby/data/taco_correlacionado.json", "TACO correlacionada"),
    ]
    for path, desc in files:
        p = Path(path)
        if p.exists():
            lines = sum(1 for _ in open(path, errors="ignore")) if path.endswith(".csv") else None
            size  = p.stat().st_size // 1024
            line_info = f"  {lines} linhas" if lines else ""
            ok(f"{desc}")
            info(f"  {path}  ({size}KB){line_info}")
        else:
            warn(f"{desc} — NÃO ENCONTRADO")
            info(f"  {path}")


# ── Scripts de extração ───────────────────────────────────────────────────────

def check_extractors() -> None:
    banner("SCRIPTS DE EXTRAÇÃO")

    scripts = [
        ("/opt/extrator_completo.py",          "Extrai todos pacientes + anamneses → SQLite"),
        ("/opt/extrator_anamneses.py",          "Extrai anamneses do CSV → SQLite"),
        ("/opt/extrair_prontuarios.py",         "Extrai prontuários via API"),
        ("/opt/extrair_prontuarios_selenium.py","Extrai prontuários via Selenium"),
        ("/opt/extrator_final.py",              "Versão final extração"),
        ("/root/dietbox-extractor/scraper_nutri.py", "Scraper Doctoralia"),
        ("/root/dietbox-extractor/webhook_nutri.py", "Webhook Flask campanha"),
    ]
    for path, desc in scripts:
        fn = ok if Path(path).exists() else warn
        fn(f"{desc}")
        info(f"  {path}")


# ── Containers Docker ─────────────────────────────────────────────────────────

def check_docker() -> None:
    banner("DOCKER — containers em execução")

    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            text=True,
        )
        for line in out.strip().splitlines():
            parts = line.split("\t")
            ok(f"{parts[0]:<45} {parts[2]}")
    except Exception as e:
        err(f"docker ps falhou: {e}")


# ── Variáveis de ambiente ─────────────────────────────────────────────────────

def check_env() -> None:
    banner("VARIÁVEIS DE AMBIENTE (.env)")

    keys = [
        ("ANTHROPIC_API_KEY",    "Claude LLM"),
        ("OPENAI_API_KEY",       "OpenAI embeddings/GPT"),
        ("DIETBOX_BEARER_TOKEN", "Dietbox API sync"),
        ("DATABASE_URL",         "PostgreSQL"),
        ("REDIS_URL",            "Redis/Celery"),
        ("OPENSEARCH_URL",       "OpenSearch vetorial"),
        ("GENAI_AGENT_URL",      "DigitalOcean GenAI"),
        ("TWILIO_ACCOUNT_SID",   "Twilio WhatsApp"),
        ("OPENCLAW_API_KEY",     "OpenClaw WhatsApp"),
        ("STRIPE_SECRET_KEY",    "Stripe pagamentos"),
        ("RESEND_API_KEY",       "Resend e-mails"),
        ("KIWIFY_CHECKOUT_URL",  "Kiwify checkout"),
        ("JWT_SECRET",           "JWT auth"),
    ]
    for key, desc in keys:
        val = os.getenv(key, "")
        if val and len(val) > 4:
            ok(f"{desc:<28}  {key} ✓  ({val[:6]}…)")
        else:
            err(f"{desc:<28}  {key} — NÃO CONFIGURADA")


# ── Resumo e próximos passos ──────────────────────────────────────────────────

def print_summary() -> None:
    banner("RESUMO — PRÓXIMOS PASSOS")

    print("""
  DADOS DISPONÍVEIS:
    • 864 pacientes importados da Dietbox (via metadata JSONB)
    • 430 com cadastro completo (nome, phone, ocupação, datas)
    • 43 com telefone validado em patient_phones
    • 73 avaliações físicas (dietbox_medidas)
    • 46 questionários pré-consulta (dietbox_qpc)
    • 19 prescrições (dietbox_prescricoes)
    • 16 documentos com texto limpo (exames laboratoriais)

  O QUE FALTA:
    ❌ Chunks/embeddings vazios → RAG não funciona
    ⚠️  65 prontuários como HTML bruto (DIETBOX_BEARER_TOKEN expirado?)
    ⚠️  Anamneses nos SQLite vazias (extração não concluiu)

  PARA POPULAR O RAG:
    1. Renovar DIETBOX_BEARER_TOKEN em .env
    2. docker compose exec api python3 -m nutrideby.workers.dietbox_sync --sync-prontuario-all
    3. docker compose exec api python3 -m nutrideby.workers.chunk_documents
    4. docker compose exec api python3 -m nutrideby.workers.embed_chunks

  ESTRUTURA DO PROJETO:
    /opt/automa-aoNutriDeby/        → App principal (Docker Compose)
    /opt/automa-aoNutriDeby/src/    → Código Python (FastAPI + workers + agents)
    /opt/automa-aoNutriDeby/data/   → CSVs e JSONs de referência (TACO etc)
    /opt/automa-aoNutriDeby/infra/  → SQLs de migração
    /opt/dietbox.db                 → SQLite backup extração (36 pacientes)
    /opt/dietbox_completo.db        → SQLite backup extração (50 pacientes)
    /root/todos_pacientes_prontuarios.csv → IDs Dietbox dos pacientes principais
    /root/dietbox-extractor/        → Scripts Playwright/Flask antigos
""")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{'#' * 60}")
    print(f"  MAPA DE DADOS — NutriDeby")
    print(f"  Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#' * 60}")

    check_postgres()
    check_sqlite()
    check_files()
    check_extractors()
    check_docker()
    check_env()
    print_summary()

    print(f"\n{'#' * 60}\n")


if __name__ == "__main__":
    main()
