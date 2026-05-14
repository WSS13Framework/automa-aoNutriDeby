-- Tabela para armazenar os itens da TACO (Tabela Brasileira de Composição de Alimentos)

CREATE TABLE IF NOT EXISTS taco_items (
    id SERIAL PRIMARY KEY,
    codigo TEXT UNIQUE NOT NULL,
    descricao TEXT NOT NULL,
    categoria TEXT,
    calorias_kcal NUMERIC,
    proteina_g NUMERIC,
    lipideos_g NUMERIC,
    carboidrato_g NUMERIC,
    fibra_g NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_taco_items_descricao ON taco_items USING gin (to_tsvector('portuguese', descricao));
