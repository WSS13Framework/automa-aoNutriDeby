"""
dashboard.py — NutriDeby Mission Control
Central de monitoramento de agentes, RAG, Hermes e saúde do sistema.
"""
import os
import subprocess
from datetime import datetime, timedelta

import pandas as pd
import psycopg2
import streamlit as st

st.set_page_config(
    page_title="NutriDeby Mission Control",
    layout="wide",
    page_icon="🚀",
)

# ── Autenticação básica ───────────────────────────────────────────────────────
OPS_USER     = os.getenv("OPS_USER", "admin")
OPS_PASSWORD = os.getenv("OPS_PASSWORD", "")

def _check_auth() -> bool:
    if not OPS_PASSWORD:
        return True  # dev: sem senha configurada, libera
    if "authenticated" in st.session_state and st.session_state.authenticated:
        return True
    st.title("🔒 NutriDeby Mission Control")
    with st.form("login"):
        user = st.text_input("Usuário")
        pwd  = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if user == OPS_USER and pwd == OPS_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Credenciais inválidas")
    return False

if not _check_auth():
    st.stop()

# ── Conexão DB ────────────────────────────────────────────────────────────────

@st.cache_resource(ttl=30)
def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        dbname=os.getenv("DB_NAME", "nutrideby"),
        user=os.getenv("DB_USER", "nutrideby"),
        password=os.getenv("DB_PASSWORD", "nutrideby_dev"),
        port=int(os.getenv("DB_PORT", "5432")),
    )

def query(sql: str, params=None) -> pd.DataFrame:
    try:
        conn = get_conn()
        return pd.read_sql(sql, conn, params=params)
    except Exception as e:
        st.error(f"DB error: {e}")
        return pd.DataFrame()

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🚀 NutriDeby — Mission Control")
st.caption(f"Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

col_r, _ = st.columns([1, 5])
with col_r:
    if st.button("🔄 Atualizar"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ═══════════════════════════════════════════════════════
# MÓDULO 1 — VISÃO GERAL DOS PACIENTES
# ═══════════════════════════════════════════════════════
st.subheader("👥 Pacientes")

df_pac = query("""
    SELECT
        COUNT(*)                                                              AS total,
        COUNT(*) FILTER (WHERE source_system = 'dietbox')                    AS dietbox,
        COUNT(*) FILTER (WHERE source_system = 'csv_import')                 AS csv_import,
        COUNT(*) FILTER (WHERE source_system = 'app')                        AS app,
        COUNT(*) FILTER (WHERE subscription_status = 'trial')                AS trial,
        COUNT(*) FILTER (WHERE subscription_status = 'active')               AS ativos,
        COUNT(*) FILTER (WHERE goal_statement IS NOT NULL AND goal_statement != '') AS com_goal,
        COUNT(DISTINCT pp.patient_id)                                         AS com_telefone
    FROM patients p
    LEFT JOIN patient_phones pp ON pp.patient_id = p.id
""")

if not df_pac.empty:
    r = df_pac.iloc[0]
    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
    c1.metric("Total",       int(r["total"]))
    c2.metric("Dietbox",     int(r["dietbox"]))
    c3.metric("CSV Import",  int(r["csv_import"]))
    c4.metric("App",         int(r["app"]))
    c5.metric("Trial",       int(r["trial"]))
    c6.metric("Ativos",      int(r["ativos"]))
    c7.metric("Com Goal",    int(r["com_goal"]))
    c8.metric("Com Telefone",int(r["com_telefone"]))

# ═══════════════════════════════════════════════════════
# MÓDULO 2 — BANCO VETORIAL (RAG)
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("🧠 Banco Vetorial (RAG)")

df_rag = query("""
    SELECT
        COUNT(*)                                                    AS total_chunks,
        COUNT(*) FILTER (WHERE embedding IS NOT NULL)               AS vetorizados,
        COALESCE(
            (COUNT(*) FILTER (WHERE embedding IS NOT NULL))::float
            / NULLIF(COUNT(*), 0) * 100, 0
        )                                                           AS progresso
    FROM chunks
""")

df_docs = query("""
    SELECT doc_type, COUNT(*) AS qtd,
           AVG(LENGTH(content_text))::int AS media_chars
    FROM documents
    GROUP BY doc_type ORDER BY qtd DESC
""")

c1, c2, c3 = st.columns(3)
if not df_rag.empty:
    r = df_rag.iloc[0]
    prog = float(r["progresso"] or 0)
    c1.metric("Chunks Totais",  int(r["total_chunks"]))
    c2.metric("Com Embedding",  int(r["vetorizados"]))
    c3.metric("Progresso",      f"{prog:.1f}%")
    st.progress(prog / 100)
    if prog == 0:
        st.warning("⚠️ Embeddings zerados — rodar: `chunk_documents` + `embed_chunks`")

if not df_docs.empty:
    st.dataframe(df_docs, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════
# MÓDULO 3 — HERMES AGENT
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("📨 Hermes Agent — Envios")

df_hermes = query("""
    SELECT
        im.received_at::date                   AS data,
        COUNT(*)                               AS envios,
        COUNT(DISTINCT im.patient_id)          AS pacientes_unicos
    FROM inbound_messages im
    WHERE im.message_type = 'hermes_outbound'
    GROUP BY im.received_at::date
    ORDER BY data DESC
    LIMIT 14
""")

df_hermes_total = query("""
    SELECT
        COUNT(*)                               AS total_enviados,
        COUNT(DISTINCT patient_id)             AS pacientes_alcancados,
        MAX(received_at)::text                 AS ultimo_envio
    FROM inbound_messages
    WHERE message_type = 'hermes_outbound'
""")

if not df_hermes_total.empty:
    r = df_hermes_total.iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Enviado",        int(r["total_enviados"] or 0))
    c2.metric("Pacientes Alcançados", int(r["pacientes_alcancados"] or 0))
    c3.metric("Último Envio",         str(r["ultimo_envio"] or "—")[:16])

if not df_hermes.empty:
    st.bar_chart(df_hermes.set_index("data")["envios"])
    st.dataframe(df_hermes, use_container_width=True, hide_index=True)
else:
    st.info("Nenhum envio Hermes registrado ainda.")

# ═══════════════════════════════════════════════════════
# MÓDULO 4 — EXTRACTION RUNS (sync Dietbox)
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("🔄 Sincronização Dietbox")

df_runs = query("""
    SELECT
        id::text,
        status,
        started_at::text,
        finished_at::text,
        stats
    FROM extraction_runs
    ORDER BY started_at DESC
    LIMIT 10
""")

if not df_runs.empty:
    def status_icon(s):
        return {"completed": "✅", "failed": "❌", "running": "⏳"}.get(s, "❓")
    df_runs["status"] = df_runs["status"].apply(lambda s: f"{status_icon(s)} {s}")
    st.dataframe(df_runs, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════
# MÓDULO 5 — PADRÕES COMPORTAMENTAIS
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("🧬 Padrões Comportamentais (ChameleonEngine)")

df_padroes = query("""
    SELECT
        fase,
        COUNT(*)               AS pacientes,
        AVG(degradacao_nivel)  AS degradacao_media,
        MAX(data_deteccao)     AS ultimo_detectado
    FROM padroes_alimentares
    GROUP BY fase
    ORDER BY pacientes DESC
""")

if not df_padroes.empty:
    tone_map = {
        "ESCAPE": "🏃 Fuga / Acolhimento",
        "CONFRONTO": "💪 Desafio / Energia",
        "RETORNO": "🔬 Metódico / Técnico",
        "CULPA": "💙 Culpa / Suporte",
    }
    df_padroes["tom_ativado"] = df_padroes["fase"].map(tone_map).fillna("🤝 Neutro")
    st.dataframe(df_padroes, use_container_width=True, hide_index=True)
else:
    st.info("Nenhum padrão comportamental detectado ainda.")

# ═══════════════════════════════════════════════════════
# MÓDULO 6 — MENSAGENS INBOUND (WhatsApp)
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("💬 Mensagens WhatsApp Inbound")

df_msg = query("""
    SELECT
        message_type,
        COUNT(*)                   AS total,
        MAX(received_at)::text     AS ultima
    FROM inbound_messages
    GROUP BY message_type
    ORDER BY total DESC
""")

df_msg_daily = query("""
    SELECT
        received_at::date   AS data,
        COUNT(*)            AS mensagens
    FROM inbound_messages
    WHERE received_at >= NOW() - INTERVAL '30 days'
      AND message_type NOT IN ('system_alert', 'hermes_outbound')
    GROUP BY data ORDER BY data
""")

if not df_msg.empty:
    st.dataframe(df_msg, use_container_width=True, hide_index=True)
if not df_msg_daily.empty:
    st.line_chart(df_msg_daily.set_index("data")["mensagens"])

# ═══════════════════════════════════════════════════════
# MÓDULO 7 — LOGS DO HERMES (arquivo)
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("📋 Logs Hermes (tail)")

log_path = os.getenv("HERMES_LOG", "/var/log/nutrideby/hermes.log")
try:
    result = subprocess.run(
        ["tail", "-n", "30", log_path],
        capture_output=True, text=True, timeout=3
    )
    log_data = result.stdout or "Log vazio."
except Exception as e:
    log_data = f"Log não disponível: {e}"

st.code(log_data, language="bash")

# ═══════════════════════════════════════════════════════
# MÓDULO 8 — SAÚDE DO SISTEMA
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("🖥️ Saúde do Sistema")

c1, c2, c3 = st.columns(3)

# API health
try:
    import urllib.request
    with urllib.request.urlopen("http://api:8080/health", timeout=3) as r:
        api_ok = r.status == 200
except Exception:
    api_ok = False
c1.metric("API", "✅ Online" if api_ok else "❌ Offline")

# Contagem de food_logs
df_fl = query("SELECT COUNT(*) AS total FROM food_logs")
c2.metric("Food Logs", int(df_fl.iloc[0]["total"]) if not df_fl.empty else 0)

# Clinical records
df_cr = query("SELECT COUNT(*) AS total FROM clinical_records WHERE status = 'ASSINADO'")
c3.metric("Records Assinados", int(df_cr.iloc[0]["total"]) if not df_cr.empty else 0)

st.caption("NutriDeby Mission Control • auto-refresh: clique Atualizar")
