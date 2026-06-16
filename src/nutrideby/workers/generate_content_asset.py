"""
Pipeline de geração de conteúdo WSS+13:
  1. Claude (Anthropic) analisa o tema e gera prompts inteligentes para cada slide
  2. Gemini gera as imagens com base nos prompts do Claude
  3. Salva no banco como ativo com status 'gerado' (aguarda aprovação)

Uso:
  python -m nutrideby.workers.generate_content_asset --grupo nutrideby --tema "reativação de pacientes inativos"
  python -m nutrideby.workers.generate_content_asset --grupo nutrideby --tema "benefícios do acompanhamento nutricional" --dry-run
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import httpx

try:
    import psycopg2
    from psycopg2.extras import Json as PgJson
    def pg_connect(url): return psycopg2.connect(url)
    def pg_json(v): return PgJson(v)
except ImportError:
    import psycopg
    from psycopg.types.json import Jsonb
    def pg_connect(url): return psycopg.connect(url)
    def pg_json(v): return Jsonb(v)

# ── Configuração ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
DATABASE_URL      = os.environ.get("DATABASE_URL", "")
GEMINI_MODEL      = "gemini-3.1-flash-image-preview"
OUTPUT_DIR        = Path("/tmp/content_assets")

GRUPOS = {
    "nutrideby": {
        "nome":      "NutriDeby",
        "descricao": "Plataforma de IA para nutricionistas que gerenciam pacientes via Dietbox. O nutricionista é o Diretor, a IA é o Gerente de Operações.",
        "audiencia": "Nutricionistas brasileiros cadastrados na plataforma Dietbox",
        "tom":       "Clínico, empático, confiável e profissional",
        "cores":     "#4CAF50 (verde saúde), #FFFFFF (branco), #1B5E20 (verde escuro)",
        "plataformas": ["instagram", "tiktok"],
    },
    "defesaauto": {
        "nome":      "DefesaAuto",
        "descricao": "Proteção e automação inteligente para defesa do veículo e do condutor brasileiro.",
        "audiencia": "Proprietários de veículos, condutores e seguradoras",
        "tom":       "Protetor, urgente, direto e confiável",
        "cores":     "#1565C0 (azul forte), #FFFFFF (branco), #0D47A1 (azul escuro)",
        "plataformas": ["instagram", "tiktok"],
    },
    "vigilai": {
        "nome":      "VigilAI",
        "descricao": "Vigilância inteligente com IA para ambientes corporativos e residenciais.",
        "audiencia": "Empresas, gestores de segurança e síndicos de condomínios",
        "tom":       "Corporativo, técnico, confiável e autoritativo",
        "cores":     "#212121 (preto), #FF6F00 (laranja), #FFFFFF (branco)",
        "plataformas": ["linkedin", "instagram"],
    },
    "monetabot": {
        "nome":      "MonetaBot Pro",
        "descricao": "Bot de trading autônomo com sinais precisos e execução automatizada no mercado financeiro.",
        "audiencia": "Traders, investidores e entusiastas do mercado financeiro brasileiro",
        "tom":       "Assertivo, técnico, data-driven e confiante",
        "cores":     "#0A0A0A (preto), #00E676 (verde neon), #FFFFFF (branco)",
        "plataformas": ["tiktok", "instagram"],
    },
}

ESTRUTURA_SLIDES = [
    {"indice": 1, "papel": "Hook",     "objetivo": "Parar o scroll. Pergunta provocativa ou afirmação ousada. Máx 8 palavras em destaque."},
    {"indice": 2, "papel": "Problema", "objetivo": "Mostrar a dor real da audiência. Tom empático. Fazer o leitor se identificar."},
    {"indice": 3, "papel": "Agitação", "objetivo": "Agravar o problema. Mostrar o custo de não resolver. Criar urgência emocional."},
    {"indice": 4, "papel": "Solução",  "objetivo": "Apresentar o produto como a saída clara e inevitável. Direto ao ponto."},
    {"indice": 5, "papel": "Feature",  "objetivo": "Destacar a funcionalidade mais diferenciada. Mostrar prova ou dado concreto."},
    {"indice": 6, "papel": "CTA",      "objetivo": "Chamada para ação irresistível. Link na bio, trial gratuito ou próximo passo."},
]

# ── Estágio 1: Claude gera os prompts ────────────────────────────────────────

def claude_gerar_prompts(grupo_cfg: dict, tema: str) -> list[dict]:
    """Claude analisa o tema e cria prompts detalhados para cada slide."""

    system = f"""Você é um especialista em marketing de conteúdo para redes sociais, com foco em carousels virais para Instagram e TikTok.

Produto: {grupo_cfg['nome']}
Descrição: {grupo_cfg['descricao']}
Audiência: {grupo_cfg['audiencia']}
Tom de voz: {grupo_cfg['tom']}
Paleta de cores: {grupo_cfg['cores']}

Seu trabalho é criar prompts detalhados de geração de imagem para cada slide de um carousel de 6 slides no formato 9:16 (768x1376px).

Regras obrigatórias para cada prompt:
- Especificar o texto exato que deve aparecer na imagem (curto, impactante)
- Descrever o layout visual detalhadamente (fundo, elementos gráficos, posição do texto)
- Usar as cores da marca informadas
- NUNCA colocar texto nos últimos 20% inferiores (área reservada aos controles do TikTok)
- Manter coerência visual entre os slides (slide 1 define o estilo de todos)
- Formato vertical 9:16, mobile-first, legível em tela pequena"""

    user = f"""Tema do carousel: {tema}

Crie prompts de imagem para os 6 slides com esta estrutura:
{json.dumps([{"slide": s["indice"], "papel": s["papel"], "objetivo": s["objetivo"]} for s in ESTRUTURA_SLIDES], ensure_ascii=False, indent=2)}

Responda SOMENTE com um JSON válido no formato:
[
  {{
    "indice": 1,
    "papel": "Hook",
    "texto_principal": "texto que aparece na imagem",
    "prompt_imagem": "prompt detalhado em inglês para geração de imagem com Gemini",
    "caption_trecho": "trecho da legenda para este slide"
  }},
  ...
]"""

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=60,
    )
    resp.raise_for_status()

    content = resp.json()["content"][0]["text"].strip()

    # Extrai JSON mesmo se vier com markdown
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]

    return json.loads(content)


# ── Estágio 2: Gemini gera as imagens ────────────────────────────────────────

def gemini_gerar_imagem(prompt: str, slide_referencia: bytes | None = None) -> bytes:
    """Gemini gera uma imagem com base no prompt do Claude."""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    parts = [{"text": prompt}]
    if slide_referencia:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(slide_referencia).decode(),
            }
        })

    resp = httpx.post(
        url,
        json={
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()

    for part in data["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])

    raise ValueError(f"Gemini não retornou imagem. Resposta: {data}")


# ── Estágio 3: Salva no banco ─────────────────────────────────────────────────

def salvar_ativo(ativo: dict) -> str:
    conn = pg_connect(DATABASE_URL)
    try:
        with conn:
            with conn.cursor() as cur:
                asset_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO content_assets
                        (id, grupo, tipo, status, titulo, caption, plataformas,
                         slides, slides_paths, learnings, gerado_por, modelo_gemini, url_fonte)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    asset_id,
                    ativo["grupo"],
                    ativo["tipo"],
                    "gerado",
                    ativo["titulo"],
                    ativo["caption"],
                    ativo["plataformas"],
                    pg_json(ativo["slides"]),
                    ativo["slides_paths"],
                    pg_json(ativo["learnings"]),
                    "claude+gemini",
                    GEMINI_MODEL,
                    ativo.get("tema", ""),
                ))
                return asset_id
    finally:
        conn.close()


# ── Pipeline principal ────────────────────────────────────────────────────────

def executar(grupo: str, tema: str, dry_run: bool = False):
    if grupo not in GRUPOS:
        print(f"[ERRO] Grupo inválido: {grupo}. Opções: {list(GRUPOS.keys())}")
        sys.exit(1)

    cfg    = GRUPOS[grupo]
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    dir_out = OUTPUT_DIR / grupo / run_id
    dir_out.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*55}")
    print(f"  WSS+13 Content Activation Engine")
    print(f"  Grupo : {cfg['nome']}")
    print(f"  Tema  : {tema}")
    print(f"  Mode  : {'DRY-RUN' if dry_run else 'PRODUÇÃO'}")
    print(f"{'='*55}\n")

    # ── Estágio 1: Claude ────────────────────────────────────
    print("📋 Estágio 1/3 — Claude analisando tema e gerando prompts...")
    if dry_run:
        prompts_slides = [
            {
                "indice": s["indice"],
                "papel": s["papel"],
                "texto_principal": f"[DRY-RUN] Texto do slide {s['indice']} — {s['papel']}",
                "prompt_imagem": f"[DRY-RUN] Prompt para slide {s['indice']}",
                "caption_trecho": f"Trecho {s['indice']} da legenda",
            }
            for s in ESTRUTURA_SLIDES
        ]
        print("   → (dry-run) Prompts simulados\n")
    else:
        prompts_slides = claude_gerar_prompts(cfg, tema)
        print(f"   → ✅ {len(prompts_slides)} prompts gerados pelo Claude\n")
        for p in prompts_slides:
            print(f"   Slide {p['indice']} [{p['papel']}]: {p['texto_principal'][:60]}")
        print()

    # ── Estágio 2: Gemini ────────────────────────────────────
    print("🎨 Estágio 2/3 — Gemini gerando imagens...")
    slides_paths   = []
    slides_dados   = []
    slide_1_bytes  = None

    for p in prompts_slides:
        print(f"   → Slide {p['indice']}/6 [{p['papel']}]...", end=" ", flush=True)

        path = dir_out / f"slide-{p['indice']}.jpg"

        if dry_run:
            path.write_bytes(b"PLACEHOLDER")
            print("(dry-run)")
        else:
            ref    = slide_1_bytes if p["indice"] > 1 else None
            img    = gemini_gerar_imagem(p["prompt_imagem"], ref)
            path.write_bytes(img)
            if p["indice"] == 1:
                slide_1_bytes = img
            print(f"✅ {len(img)//1024}KB")

        slides_paths.append(str(path))
        slides_dados.append({**p, "path": str(path)})

    print()

    # ── Estágio 3: Banco ─────────────────────────────────────
    caption = "\n".join(p.get("caption_trecho", "") for p in prompts_slides if p.get("caption_trecho"))
    caption += f"\n\n#{cfg['nome'].lower().replace(' ', '')} #ia #nutricionista #saude"

    ativo = {
        "grupo":        grupo,
        "tipo":         "carousel",
        "titulo":       f"{cfg['nome']} — {tema[:50]} [{run_id}]",
        "caption":      caption,
        "plataformas":  cfg["plataformas"],
        "slides":       slides_dados,
        "slides_paths": slides_paths,
        "learnings":    {
            "run_id":   run_id,
            "tema":     tema,
            "modelo_claude": ANTHROPIC_MODEL,
            "modelo_gemini": GEMINI_MODEL,
        },
        "tema": tema,
    }

    print("💾 Estágio 3/3 — Salvando no banco de dados...")

    if dry_run:
        print("\n[DRY-RUN] Ativo que seria salvo:")
        print(json.dumps({k: v for k, v in ativo.items() if k != "slides"}, indent=2, ensure_ascii=False))
        print(f"\n[DRY-RUN] Slides em: {dir_out}")
        return

    asset_id = salvar_ativo(ativo)

    print(f"\n{'='*55}")
    print(f"  ✅ Ativo criado e salvo no banco!")
    print(f"  ID     : {asset_id}")
    print(f"  Grupo  : {cfg['nome']}")
    print(f"  Status : gerado (aguardando aprovação)")
    print(f"  Slides : {dir_out}")
    print(f"{'='*55}")
    print(f"\n  Para aprovar:")
    print(f"  UPDATE content_assets SET status='aprovado' WHERE id='{asset_id}';\n")


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Pipeline Claude → Gemini → Banco de dados")
    p.add_argument("--grupo",   required=True,  help=f"Grupo: {list(GRUPOS.keys())}")
    p.add_argument("--tema",    required=True,  help="Tema do carousel (ex: 'reativação de pacientes inativos')")
    p.add_argument("--dry-run", action="store_true", help="Simula sem chamar APIs nem salvar no banco")
    args = p.parse_args()

    executar(args.grupo, args.tema, dry_run=args.dry_run)
