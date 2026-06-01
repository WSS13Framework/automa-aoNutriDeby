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

# ── Autenticação Google OAuth ────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
OPS_ALLOWED_EMAILS   = [
    e.strip() for e in
    os.getenv("OPS_ALLOWED_EMAILS", "wss13.framework@gmail.com,nutrideboraoliver@gmail.com").split(",")
    if e.strip()
]
REDIRECT_URI = os.getenv("OPS_REDIRECT_URI", "https://ops.nutrideby.com/")


def _google_auth_url() -> str:
    import urllib.parse
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "online",
        "prompt":        "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def _exchange_code(code: str) -> dict | None:
    import urllib.parse, urllib.request, json
    data = urllib.parse.urlencode({
        "code":          code,
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        st.error(f"Erro ao trocar código: {e}")
        return None


def _get_userinfo(access_token: str) -> dict | None:
    import urllib.request, json
    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _check_auth() -> bool:
    # Já autenticado nesta sessão
    if st.session_state.get("google_email"):
        return True

    # Sem Google configurado — libera (dev)
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        st.session_state["google_email"] = "dev@local"
        return True

    # Retorno do OAuth com ?code=...
    params = st.query_params
    code = params.get("code")
    if code:
        tokens = _exchange_code(code)
        if tokens and "access_token" in tokens:
            info = _get_userinfo(tokens["access_token"])
            email = (info or {}).get("email", "")
            if email in OPS_ALLOWED_EMAILS:
                st.session_state["google_email"] = email
                st.session_state["google_name"]  = (info or {}).get("name", email)
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"❌ Acesso negado para {email}")
                st.query_params.clear()
        return False

    # Tela de login
    st.markdown("""
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
                height:70vh;gap:24px;font-family:sans-serif;">
      <div style="font-size:2.5rem;">🚀</div>
      <div style="font-size:1.6rem;font-weight:700;color:#1a1a2e;">NutriDeby Mission Control</div>
      <div style="color:#666;font-size:1rem;">Acesso restrito à equipe autorizada</div>
    </div>
    """, unsafe_allow_html=True)

    auth_url = _google_auth_url()
    st.markdown(f"""
    <div style="display:flex;justify-content:center;margin-top:-40px;">
      <a href="{auth_url}" target="_self" style="
        background:#4285F4;color:white;padding:12px 28px;border-radius:8px;
        text-decoration:none;font-size:1rem;font-weight:600;
        display:flex;align-items:center;gap:10px;box-shadow:0 2px 8px rgba(0,0,0,.15);">
        <svg width="20" height="20" viewBox="0 0 48 48">
          <path fill="#fff" d="M44.5 20H24v8.5h11.8C34.7 33.9 30.1 37 24 37c-7.2 0-13-5.8-13-13s5.8-13 13-13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 5.1 29.6 3 24 3 12.4 3 3 12.4 3 24s9.4 21 21 21c10.5 0 20-7.6 20-21 0-1.4-.1-2.7-.5-4z"/>
        </svg>
        Entrar com Google
      </a>
    </div>
    """, unsafe_allow_html=True)
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

user_name = st.session_state.get("google_name") or st.session_state.get("google_email", "")
col_title, col_user = st.columns([5, 1])
with col_title:
    st.title("🚀 NutriDeby — Mission Control")
with col_user:
    if user_name:
        st.caption(f"👤 {user_name}")
        if st.button("Sair", key="logout"):
            st.session_state.clear()
            st.rerun()
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


# ═══════════════════════════════════════════════════════
# MÓDULO 9 — PAINEL DE CONTROLE DE WORKERS
# ═══════════════════════════════════════════════════════
st.divider()
st.subheader("⚙️ Controle de Workers")

def run_docker(cmd: list[str]) -> tuple[bool, str]:
    """Executa comando Docker via socket montado."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        ok  = result.returncode == 0
        out = (result.stdout + result.stderr).strip()
        return ok, out[:800]
    except FileNotFoundError:
        return False, "Docker CLI não disponível no container. Verifique a montagem do socket."
    except subprocess.TimeoutExpired:
        return False, "Timeout — comando demorou mais de 60s."
    except Exception as e:
        return False, str(e)

WORKERS = {
    "🔄 Worker Kiwify":         ("restart", "automa-aonutrideby-worker-kiwify-1"),
    "🤖 API (FastAPI)":         ("restart", "automa-aonutrideby-api-1"),
    "📦 Chunk Documents":       ("exec",    "chunk_documents"),
    "🧠 Embed Chunks (RAG)":    ("exec",    "embed_chunks"),
    "🌿 Hermes dry-run":        ("hermes_dry", "inativo_30"),
    "📨 Dietbox Sync (meta)":   ("exec",    "dietbox_meta"),
}

cols = st.columns(3)
results_placeholder = st.empty()

for idx, (label, (action, target)) in enumerate(WORKERS.items()):
    col = cols[idx % 3]
    with col:
        if st.button(label, use_container_width=True, key=f"btn_{idx}"):
            with st.spinner(f"Executando {label}..."):
                if action == "restart":
                    ok, out = run_docker(["docker", "restart", target])
                    msg = f"✅ `{target}` reiniciado" if ok else f"❌ Erro: {out}"

                elif action == "exec" and target == "chunk_documents":
                    ok, out = run_docker([
                        "docker", "exec", "automa-aonutrideby-api-1",
                        "python3", "-m", "nutrideby.workers.chunk_documents"
                    ])
                    msg = f"✅ chunk_documents concluído" if ok else f"❌ {out}"

                elif action == "exec" and target == "embed_chunks":
                    ok, out = run_docker([
                        "docker", "exec", "automa-aonutrideby-api-1",
                        "python3", "-m", "nutrideby.workers.embed_chunks"
                    ])
                    msg = f"✅ embed_chunks concluído" if ok else f"❌ {out}"

                elif action == "exec" and target == "dietbox_meta":
                    ok, out = run_docker([
                        "docker", "exec", "automa-aonutrideby-api-1",
                        "python3", "-m", "nutrideby.workers.dietbox_sync",
                        "--sync-all-clinical", "--clinical-limit", "50"
                    ])
                    msg = f"✅ Sync Dietbox iniciado" if ok else f"❌ {out}"

                elif action == "hermes_dry":
                    ok, out = run_docker([
                        "docker", "exec", "automa-aonutrideby-api-1",
                        "python3", "-m", "nutrideby.agents.hermes_agent",
                        "--profile", target, "--limit", "3", "--dry-run"
                    ])
                    msg = f"✅ Hermes dry-run OK" if ok else f"❌ {out}"
                    if ok:
                        st.code(out[:600], language="bash")
                else:
                    msg, ok = "Ação desconhecida", False

            if ok:
                st.success(msg)
            else:
                st.error(msg)

st.divider()
st.subheader("🚀 Hermes — Disparo Manual")

with st.form("hermes_manual"):
    col_a, col_b, col_c = st.columns(3)
    perfil  = col_a.selectbox("Perfil", ["inativo_30", "inativo_14", "inativo_7", "ativo"])
    limite  = col_b.number_input("Limite", min_value=1, max_value=50, value=5)
    dry_run = col_c.checkbox("Dry-run (não envia)", value=True)

    if st.form_submit_button("▶️ Disparar Hermes", use_container_width=True):
        flags = ["--dry-run"] if dry_run else ["--send"]
        cmd = [
            "docker", "exec", "automa-aonutrideby-api-1",
            "python3", "-m", "nutrideby.agents.hermes_agent",
            "--profile", perfil, "--limit", str(int(limite)),
        ] + flags
        with st.spinner(f"Hermes {perfil} limit={limite} {'dry-run' if dry_run else 'ENVIANDO'}..."):
            ok, out = run_docker(cmd)
        if ok:
            st.success(f"✅ Hermes concluído — {perfil}")
        else:
            st.error(f"❌ Erro: {out[:300]}")
        st.code(out, language="bash")

st.caption("NutriDeby Mission Control • auto-refresh: clique Atualizar")
