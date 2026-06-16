-- 022: ativos de conteúdo gerados por IA (carousels, vídeos, shorts).
-- Armazena slides gerados pelo Gemini antes de publicar nas redes sociais.
-- ADITIVO e IDEMPOTENTE.

CREATE TABLE IF NOT EXISTS content_assets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grupo           TEXT NOT NULL,                          -- nutrideby | defesaauto | vigilai | monetabot
    tipo            TEXT NOT NULL DEFAULT 'carousel',       -- carousel | short | video | reel
    status          TEXT NOT NULL DEFAULT 'gerado',         -- gerado | aprovado | publicado | arquivado
    titulo          TEXT,
    caption         TEXT,
    plataformas     TEXT[] NOT NULL DEFAULT '{}',           -- tiktok | instagram | youtube | linkedin
    slides          JSONB NOT NULL DEFAULT '[]',            -- array com prompts e metadata de cada slide
    slides_paths    TEXT[] NOT NULL DEFAULT '{}',           -- caminhos dos arquivos de imagem no servidor
    learnings       JSONB NOT NULL DEFAULT '{}',            -- hook usado, estilo visual, horário recomendado
    publicado_em    TIMESTAMPTZ,
    request_id      TEXT,                                   -- ID retornado pelo Upload-Post após publicação
    metricas        JSONB NOT NULL DEFAULT '{}',            -- views, likes, comments, shares após publicação
    gerado_por      TEXT NOT NULL DEFAULT 'gemini',
    modelo_gemini   TEXT,
    url_fonte       TEXT,                                   -- URL analisada para gerar o conteúdo
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_content_assets_grupo   ON content_assets(grupo, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_assets_status  ON content_assets(status);
CREATE INDEX IF NOT EXISTS idx_content_assets_tipo    ON content_assets(tipo);

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_content_assets_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_content_assets_updated_at ON content_assets;
CREATE TRIGGER trg_content_assets_updated_at
    BEFORE UPDATE ON content_assets
    FOR EACH ROW EXECUTE FUNCTION update_content_assets_updated_at();

-- Privilégios
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_nutrideby') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON content_assets TO app_nutrideby;
    END IF;
END $$;
