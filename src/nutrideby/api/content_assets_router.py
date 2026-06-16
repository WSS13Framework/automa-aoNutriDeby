"""Router de ativos de conteúdo — WSS+13 Content Activation Engine."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from psycopg.rows import dict_row

from nutrideby.api.deps import get_settings, require_api_key
from nutrideby.config import Settings

router = APIRouter(prefix="/v1/content", tags=["content-assets"])

# ── DB helper ─────────────────────────────────────────────────────────────────

async def get_db(settings: Annotated[Settings, Depends(get_settings)]):
    async with await psycopg.AsyncConnection.connect(
        str(settings.database_url), row_factory=dict_row
    ) as conn:
        yield conn


def _sync_conn(settings: Settings):
    import psycopg as _pg
    return _pg.connect(str(settings.database_url), row_factory=dict_row)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/assets", dependencies=[Depends(require_api_key)])
def listar_ativos(
    settings: Annotated[Settings, Depends(get_settings)],
    status: str | None = Query(None, description="gerado|aprovado|publicado|arquivado"),
    grupo: str | None = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    """Lista ativos de conteúdo com filtros."""
    with _sync_conn(settings) as conn:
        with conn.cursor() as cur:
            filtros, params = [], []
            if status:
                filtros.append("status = %s"); params.append(status)
            if grupo:
                filtros.append("grupo = %s"); params.append(grupo)
            where = f"WHERE {' AND '.join(filtros)}" if filtros else ""

            cur.execute(f"""
                SELECT id, grupo, tipo, status, titulo, caption, plataformas,
                       slides_paths, learnings, metricas,
                       created_at, publicado_em, modelo_gemini, url_fonte
                FROM content_assets
                {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            rows = cur.fetchall()

            cur.execute(f"SELECT COUNT(*) AS total FROM content_assets {where}", params)
            total = cur.fetchone()["total"]

    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/assets/acervo", dependencies=[Depends(require_api_key)])
def acervo_resumo(settings: Annotated[Settings, Depends(get_settings)]):
    """Visão geral do acervo por grupo e status."""
    with _sync_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT grupo,
                    COUNT(*) FILTER (WHERE status='gerado')    AS gerados,
                    COUNT(*) FILTER (WHERE status='aprovado')  AS aprovados,
                    COUNT(*) FILTER (WHERE status='publicado') AS publicados,
                    COUNT(*) FILTER (WHERE status='arquivado') AS arquivados,
                    COUNT(*) AS total
                FROM content_assets
                GROUP BY grupo ORDER BY grupo
            """)
            grupos = cur.fetchall()

            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status='gerado')    AS gerados,
                    COUNT(*) FILTER (WHERE status='aprovado')  AS aprovados,
                    COUNT(*) FILTER (WHERE status='publicado') AS publicados
                FROM content_assets
            """)
            totais = cur.fetchone()

    return {"grupos": grupos, "totais": totais}


@router.get("/assets/{asset_id}", dependencies=[Depends(require_api_key)])
def detalhar_ativo(
    asset_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Retorna todos os dados de um ativo incluindo slides e prompts."""
    with _sync_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM content_assets WHERE id = %s", (str(asset_id),))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")
    return row


@router.patch("/assets/{asset_id}/status", dependencies=[Depends(require_api_key)])
def atualizar_status(
    asset_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    status: str = Query(..., description="aprovado|arquivado|publicado"),
):
    """Aprova, arquiva ou marca como publicado um ativo."""
    VALIDOS = {"aprovado", "arquivado", "publicado", "gerado"}
    if status not in VALIDOS:
        raise HTTPException(status_code=400, detail=f"Status inválido. Opções: {VALIDOS}")

    with _sync_conn(settings) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE content_assets
                    SET status = %s,
                        publicado_em = CASE WHEN %s = 'publicado' THEN now() ELSE publicado_em END,
                        updated_at = now()
                    WHERE id = %s
                    RETURNING id, status
                """, (status, status, str(asset_id)))
                row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")
    return {"id": row["id"], "status": row["status"]}


@router.get("/assets/{asset_id}/slide/{numero}", dependencies=[Depends(require_api_key)])
def servir_slide(
    asset_id: UUID,
    numero: int,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Serve o arquivo JPG de um slide específico."""
    with _sync_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT slides_paths FROM content_assets WHERE id = %s",
                (str(asset_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")

    paths = row["slides_paths"]
    if not paths or numero < 1 or numero > len(paths):
        raise HTTPException(status_code=404, detail=f"Slide {numero} não existe")

    path = Path(paths[numero - 1])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Arquivo do slide não encontrado: {path}")

    return FileResponse(str(path), media_type="image/jpeg")


# ── Dashboard visual (HTML) ───────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: str | None = None,
    status: str | None = None,
    grupo: str | None = None,
):
    """Dashboard visual para revisão e aprovação de ativos."""
    api_key = x_api_key or ""

    with _sync_conn(settings) as conn:
        with conn.cursor() as cur:
            filtros, params = [], []
            if status:
                filtros.append("status = %s"); params.append(status)
            if grupo:
                filtros.append("grupo = %s"); params.append(grupo)
            where = f"WHERE {' AND '.join(filtros)}" if filtros else ""

            cur.execute(f"""
                SELECT id, grupo, tipo, status, titulo, slides_paths,
                       learnings, created_at, plataformas
                FROM content_assets
                {where}
                ORDER BY created_at DESC
                LIMIT 50
            """, params)
            ativos = cur.fetchall()

            cur.execute("""
                SELECT grupo,
                    COUNT(*) FILTER (WHERE status='gerado')    AS gerados,
                    COUNT(*) FILTER (WHERE status='aprovado')  AS aprovados,
                    COUNT(*) FILTER (WHERE status='publicado') AS publicados,
                    COUNT(*) AS total
                FROM content_assets GROUP BY grupo ORDER BY grupo
            """)
            acervo = cur.fetchall()

    STATUS_COR = {
        "gerado":    "#F59E0B",
        "aprovado":  "#10B981",
        "publicado": "#3B82F6",
        "arquivado": "#6B7280",
    }

    cards_html = ""
    for a in ativos:
        sid      = str(a["id"])
        sid_curto = sid[:8]
        st       = a["status"]
        cor      = STATUS_COR.get(st, "#6B7280")
        paths    = a["slides_paths"] or []
        n_slides = len(paths)
        learn    = a["learnings"] or {}
        if isinstance(learn, str): learn = json.loads(learn)
        tema     = learn.get("tema", a["titulo"] or "—")[:60]
        plats    = ", ".join(a["plataformas"] or [])
        criado   = str(a["created_at"])[:16]

        # miniaturas dos slides
        thumbs = ""
        for i in range(1, n_slides + 1):
            thumbs += f"""
            <img src="/v1/content/assets/{sid}/slide/{i}?x_api_key={api_key}"
                 style="width:60px;height:107px;object-fit:cover;border-radius:6px;border:1px solid #333;"
                 title="Slide {i}" onerror="this.style.display='none'">"""

        botoes = ""
        if st == "gerado":
            botoes = f"""
            <button onclick="mudarStatus('{sid}','aprovado',this)"
                style="background:#10B981;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;">
                ✅ Aprovar
            </button>
            <button onclick="mudarStatus('{sid}','arquivado',this)"
                style="background:#6B7280;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;margin-left:6px;">
                🗄 Arquivar
            </button>"""
        elif st == "aprovado":
            botoes = f"""
            <button onclick="mudarStatus('{sid}','publicado',this)"
                style="background:#3B82F6;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;">
                🚀 Marcar Publicado
            </button>
            <button onclick="mudarStatus('{sid}','arquivado',this)"
                style="background:#6B7280;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;margin-left:6px;">
                🗄 Arquivar
            </button>"""

        cards_html += f"""
        <div style="background:#1E1E2E;border-radius:12px;padding:18px;margin-bottom:16px;border-left:4px solid {cor};">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
                <div>
                    <span style="background:{cor};color:#000;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:bold;">{st.upper()}</span>
                    <span style="color:#9CA3AF;font-size:12px;margin-left:10px;">{a['grupo'].upper()} · {plats} · {criado}</span>
                    <br><span style="color:#F3F4F6;font-weight:600;font-size:15px;margin-top:6px;display:block;">{tema}</span>
                    <span style="color:#6B7280;font-size:12px;">ID: {sid_curto}... · {n_slides} slides</span>
                </div>
            </div>
            <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">{thumbs}</div>
            <div>{botoes}</div>
        </div>"""

    acervo_html = ""
    for g in acervo:
        acervo_html += f"""
        <div style="background:#1E1E2E;border-radius:8px;padding:12px;text-align:center;min-width:120px;">
            <div style="color:#9CA3AF;font-size:11px;text-transform:uppercase;">{g['grupo']}</div>
            <div style="color:#F59E0B;font-size:20px;font-weight:bold;">{g['gerados']}</div>
            <div style="color:#9CA3AF;font-size:10px;">gerados</div>
            <div style="color:#10B981;font-size:16px;font-weight:bold;">{g['aprovados']}</div>
            <div style="color:#9CA3AF;font-size:10px;">aprovados</div>
            <div style="color:#3B82F6;font-size:16px;font-weight:bold;">{g['publicados']}</div>
            <div style="color:#9CA3AF;font-size:10px;">publicados</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WSS+13 · Acervo de Conteúdo</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0F0F1A; color: #F3F4F6; font-family: system-ui, sans-serif; padding: 24px; }}
  select, button {{ font-family: inherit; }}
  .filtros {{ display:flex; gap:10px; margin-bottom:20px; flex-wrap:wrap; align-items:center; }}
  .filtros select {{
    background:#1E1E2E; color:#F3F4F6; border:1px solid #374151;
    padding:8px 12px; border-radius:8px; font-size:13px; cursor:pointer;
  }}
  .filtros button {{
    background:#4F46E5; color:#fff; border:none;
    padding:8px 16px; border-radius:8px; cursor:pointer; font-size:13px;
  }}
  h1 {{ font-size:22px; margin-bottom:6px; }}
  .subtitle {{ color:#9CA3AF; font-size:13px; margin-bottom:24px; }}
</style>
</head>
<body>
<h1>🚀 WSS+13 · Acervo de Conteúdo</h1>
<div class="subtitle">Revisão e aprovação de ativos gerados pelo Content Activation Engine</div>

<div style="display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap;">
  {acervo_html}
</div>

<div class="filtros">
  <select id="filtroStatus" onchange="filtrar()">
    <option value="">Todos os status</option>
    <option value="gerado" {'selected' if status=='gerado' else ''}>🟡 Gerado</option>
    <option value="aprovado" {'selected' if status=='aprovado' else ''}>🟢 Aprovado</option>
    <option value="publicado" {'selected' if status=='publicado' else ''}>🔵 Publicado</option>
    <option value="arquivado" {'selected' if status=='arquivado' else ''}>⚫ Arquivado</option>
  </select>
  <select id="filtroGrupo" onchange="filtrar()">
    <option value="">Todos os grupos</option>
    <option value="nutrideby" {'selected' if grupo=='nutrideby' else ''}>NutriDeby</option>
    <option value="defesaauto" {'selected' if grupo=='defesaauto' else ''}>DefesaAuto</option>
    <option value="vigilai" {'selected' if grupo=='vigilai' else ''}>VigilAI</option>
    <option value="monetabot" {'selected' if grupo=='monetabot' else ''}>MonetaBot Pro</option>
  </select>
  <span style="color:#9CA3AF;font-size:13px;">{len(ativos)} ativos</span>
</div>

<div id="cards">
  {cards_html if cards_html else '<div style="color:#6B7280;padding:40px;text-align:center;">Nenhum ativo encontrado.</div>'}
</div>

<script>
const API_KEY = '{api_key}';

function filtrar() {{
  const st = document.getElementById('filtroStatus').value;
  const gr = document.getElementById('filtroGrupo').value;
  const params = new URLSearchParams(window.location.search);
  if (st) params.set('status', st); else params.delete('status');
  if (gr) params.set('grupo', gr); else params.delete('grupo');
  if (API_KEY) params.set('x_api_key', API_KEY);
  window.location.href = '/v1/content/dashboard?' + params.toString();
}}

async function mudarStatus(id, novoStatus, btn) {{
  btn.disabled = true;
  btn.textContent = 'Aguarde...';
  try {{
    const resp = await fetch(
      `/v1/content/assets/${{id}}/status?status=${{novoStatus}}`,
      {{ method: 'PATCH', headers: {{ 'X-API-Key': API_KEY }} }}
    );
    if (resp.ok) {{
      location.reload();
    }} else {{
      const err = await resp.json();
      alert('Erro: ' + (err.detail || resp.status));
      btn.disabled = false;
      btn.textContent = 'Tentar novamente';
    }}
  }} catch(e) {{
    alert('Erro de rede: ' + e.message);
    btn.disabled = false;
  }}
}}
</script>
</body>
</html>"""

    return HTMLResponse(content=html)
