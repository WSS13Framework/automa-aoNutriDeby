"""
Agente de Engajamento — WSS+13 Content Activation Engine
Verifica ativos no banco, analisa performance e gera recomendações via Claude.

Uso:
  python -m nutrideby.workers.engagement_agent --listar
  python -m nutrideby.workers.engagement_agent --listar --status gerado
  python -m nutrideby.workers.engagement_agent --analisar <asset_id>
  python -m nutrideby.workers.engagement_agent --acervo
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

import httpx

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    def pg_connect(url): return psycopg2.connect(url)
    DICT_CURSOR = RealDictCursor
except ImportError:
    import psycopg
    from psycopg.rows import dict_row
    def pg_connect(url): return psycopg.connect(url, row_factory=dict_row)
    DICT_CURSOR = None

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
DATABASE_URL      = os.environ.get("DATABASE_URL", "")

# ── Consultas ao banco ────────────────────────────────────────────────────────

def listar_ativos(status: str | None = None, grupo: str | None = None, limit: int = 20) -> list[dict]:
    conn = pg_connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            filtros = []
            params  = []
            if status:
                filtros.append("status = %s")
                params.append(status)
            if grupo:
                filtros.append("grupo = %s")
                params.append(grupo)

            where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
            cur.execute(f"""
                SELECT id, grupo, tipo, status, titulo, plataformas,
                       created_at, publicado_em, metricas,
                       learnings->>'tema' AS tema
                FROM content_assets
                {where}
                ORDER BY created_at DESC
                LIMIT %s
            """, params + [limit])

            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def buscar_ativo(asset_id: str) -> dict | None:
    conn = pg_connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM content_assets WHERE id = %s
            """, (asset_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def atualizar_metricas(asset_id: str, metricas: dict):
    conn = pg_connect(DATABASE_URL)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE content_assets
                    SET metricas = %s, updated_at = now()
                    WHERE id = %s
                """, (json.dumps(metricas), asset_id))
    finally:
        conn.close()


# ── Claude analisa engajamento ────────────────────────────────────────────────

def claude_analisar_engajamento(ativo: dict) -> str:
    slides = ativo.get("slides", [])
    if isinstance(slides, str):
        slides = json.loads(slides)

    metricas = ativo.get("metricas", {})
    if isinstance(metricas, str):
        metricas = json.loads(metricas)

    prompt = f"""Você é o agente de engajamento do WSS+13 Content Activation Engine.

Analise este ativo de conteúdo e forneça um relatório de performance:

ATIVO:
- ID: {ativo['id']}
- Grupo: {ativo['grupo']}
- Tema: {ativo.get('tema') or ativo.get('titulo', 'N/A')}
- Status: {ativo['status']}
- Criado em: {ativo['created_at']}
- Publicado em: {ativo.get('publicado_em', 'Ainda não publicado')}
- Plataformas: {ativo['plataformas']}

SLIDES ({len(slides)} slides):
{json.dumps([{'slide': s.get('indice'), 'papel': s.get('papel'), 'texto': s.get('texto_principal', 'N/A')} for s in slides], ensure_ascii=False, indent=2)}

MÉTRICAS:
{json.dumps(metricas, ensure_ascii=False, indent=2) if metricas else 'Nenhuma métrica registrada ainda.'}

Forneça:
1. **Status do ativo**: avaliação do estágio atual (gerado/aprovado/publicado/arquivado)
2. **Análise dos slides**: qualidade do hook, estrutura narrativa, potencial de engajamento
3. **Recomendações**: o que melhorar antes de publicar (se ainda não publicado)
4. **Score de potencial**: nota de 1-10 com justificativa
5. **Próximo passo**: ação recomendada (aprovar, revisar slide X, publicar agora, arquivar)

Seja direto e específico."""

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


# ── Acervo completo ───────────────────────────────────────────────────────────

def exibir_acervo():
    conn = pg_connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    grupo,
                    COUNT(*) FILTER (WHERE status = 'gerado')    AS gerados,
                    COUNT(*) FILTER (WHERE status = 'aprovado')  AS aprovados,
                    COUNT(*) FILTER (WHERE status = 'publicado') AS publicados,
                    COUNT(*) FILTER (WHERE status = 'arquivado') AS arquivados,
                    COUNT(*) AS total
                FROM content_assets
                GROUP BY grupo
                ORDER BY grupo
            """)
            rows = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'gerado')    AS gerados,
                       COUNT(*) FILTER (WHERE status = 'aprovado')  AS aprovados,
                       COUNT(*) FILTER (WHERE status = 'publicado') AS publicados
                FROM content_assets
            """)
            totais = dict(cur.fetchone())

        return rows, totais
    finally:
        conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_listar(args):
    ativos = listar_ativos(status=args.status, grupo=args.grupo, limit=args.limit)

    if not ativos:
        print("Nenhum ativo encontrado.")
        return

    print(f"\n{'='*65}")
    print(f"  ACERVO DE ATIVOS — {len(ativos)} encontrados")
    print(f"{'='*65}")
    for a in ativos:
        pub = str(a.get("publicado_em", "—"))[:10]
        print(f"\n  [{a['status'].upper():10}] {a['grupo'].upper()}")
        print(f"  ID    : {a['id']}")
        print(f"  Tema  : {a.get('tema') or a.get('titulo', 'N/A')[:55]}")
        print(f"  Criado: {str(a['created_at'])[:16]}  Publicado: {pub}")
        print(f"  Plats : {', '.join(a['plataformas'])}")
        metricas = a.get("metricas") or {}
        if isinstance(metricas, str):
            metricas = json.loads(metricas)
        if metricas:
            print(f"  Métr. : {json.dumps(metricas, ensure_ascii=False)}")
    print(f"\n{'='*65}\n")


def cmd_analisar(args):
    ativo = buscar_ativo(args.analisar)
    if not ativo:
        print(f"[ERRO] Ativo {args.analisar} não encontrado.")
        return

    print(f"\n📊 Analisando ativo {args.analisar[:8]}... com Claude {ANTHROPIC_MODEL}\n")
    analise = claude_analisar_engajamento(ativo)
    print(analise)
    print()


def cmd_acervo(args):
    grupos, totais = exibir_acervo()

    print(f"\n{'='*55}")
    print(f"  ACERVO WSS+13 — VISÃO GERAL")
    print(f"{'='*55}")
    print(f"  {'GRUPO':<15} {'GERADO':>7} {'APROV':>7} {'PUBLIC':>7} {'TOTAL':>7}")
    print(f"  {'-'*50}")
    for g in grupos:
        print(f"  {g['grupo']:<15} {g['gerados']:>7} {g['aprovados']:>7} {g['publicados']:>7} {g['total']:>7}")
    print(f"  {'-'*50}")
    print(f"  {'TOTAL':<15} {totais['gerados']:>7} {totais['aprovados']:>7} {totais['publicados']:>7} {totais['total']:>7}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente de Engajamento — WSS+13")
    parser.add_argument("--listar",   action="store_true",      help="Lista ativos do banco")
    parser.add_argument("--acervo",   action="store_true",      help="Visão geral do acervo por grupo")
    parser.add_argument("--analisar", metavar="ASSET_ID",       help="Analisa um ativo específico com Claude")
    parser.add_argument("--status",   default=None,             help="Filtrar por status: gerado|aprovado|publicado|arquivado")
    parser.add_argument("--grupo",    default=None,             help="Filtrar por grupo")
    parser.add_argument("--limit",    type=int, default=20,     help="Máx de resultados (padrão: 20)")
    args = parser.parse_args()

    if args.acervo:
        cmd_acervo(args)
    elif args.analisar:
        cmd_analisar(args)
    elif args.listar:
        cmd_listar(args)
    else:
        parser.print_help()
