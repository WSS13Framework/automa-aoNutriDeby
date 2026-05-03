-- Snapshots de integrações (ex.: JSON da API Dietbox) — aplicar em bases já existentes:
--   psql "$DATABASE_URL" -f infra/sql/002_external_snapshots.sql

CREATE TABLE IF NOT EXISTS external_snapshots (
    key             TEXT PRIMARY KEY,
    payload         JSONB NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_status     INT
);

CREATE INDEX IF NOT EXISTS idx_external_snapshots_fetched
    ON external_snapshots (fetched_at DESC);

COMMENT ON TABLE external_snapshots IS 'Última resposta persistida por chave estável (subscription, etc.).';
