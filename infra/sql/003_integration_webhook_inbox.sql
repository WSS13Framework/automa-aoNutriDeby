-- Inbox de webhooks (Kiwify, etc.) — aplicar em bases já existentes:
--   psql "$DATABASE_URL" -f infra/sql/003_integration_webhook_inbox.sql

CREATE TABLE IF NOT EXISTS integration_webhook_inbox (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL,
    payload         JSONB NOT NULL,
    headers_meta    JSONB NOT NULL DEFAULT '{}',
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_integration_webhook_inbox_received
    ON integration_webhook_inbox (received_at DESC);

CREATE INDEX IF NOT EXISTS idx_integration_webhook_inbox_status
    ON integration_webhook_inbox (status, received_at DESC);

COMMENT ON TABLE integration_webhook_inbox IS 'POSTs brutos de integrações externas; processamento assíncrono em sprints seguintes.';
