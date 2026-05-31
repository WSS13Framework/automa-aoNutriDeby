-- Multi-tenancy: accounts (nutricionistas) + vault de credenciais
-- Cada nutricionista é uma conta isolada com seus próprios pacientes/dados

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Contas dos nutricionistas ─────────────────────────────────────────────
CREATE TABLE accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    password_hash   TEXT NOT NULL,              -- bcrypt
    plan            TEXT NOT NULL DEFAULT 'trial',  -- trial | starter | pro
    plan_expires_at TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'active', -- active | suspended | churned
    onboarding_done BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_accounts_email ON accounts (email);

-- ── Vault de credenciais das plataformas externas ─────────────────────────
-- Armazena tokens/senhas cifrados — nunca em texto claro fora desta tabela
CREATE TABLE platform_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,              -- dietbox | nutrismart | anny | etc.
    credential_type TEXT NOT NULL DEFAULT 'bearer_token', -- bearer_token | login_password | oauth2
    -- dados cifrados via pgp_sym_encrypt (chave vem de ONBOARDING_VAULT_KEY no .env)
    encrypted_data  BYTEA NOT NULL,
    -- metadados não-sensíveis
    expires_at      TIMESTAMPTZ,               -- NULL = sem expiração conhecida
    last_validated_at TIMESTAMPTZ,
    last_sync_at    TIMESTAMPTZ,
    validation_status TEXT NOT NULL DEFAULT 'pending', -- pending | valid | expired | invalid
    sync_status     TEXT NOT NULL DEFAULT 'idle',      -- idle | running | done | failed
    patients_synced INT NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, platform)
);

CREATE INDEX idx_platform_creds_account ON platform_credentials (account_id);
CREATE INDEX idx_platform_creds_validation ON platform_credentials (validation_status, expires_at);

-- ── Fila de jobs de extração ──────────────────────────────────────────────
CREATE TABLE extraction_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    credential_id   UUID NOT NULL REFERENCES platform_credentials (id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    job_type        TEXT NOT NULL DEFAULT 'full_sync', -- full_sync | incremental | prontuario | embed
    status          TEXT NOT NULL DEFAULT 'queued',    -- queued | running | done | failed
    priority        INT NOT NULL DEFAULT 5,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    stats           JSONB NOT NULL DEFAULT '{}',
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_extraction_jobs_account ON extraction_jobs (account_id, created_at DESC);
CREATE INDEX idx_extraction_jobs_queued  ON extraction_jobs (status, priority DESC, created_at)
    WHERE status = 'queued';

-- ── Adiciona account_id nas tabelas existentes (nullable → backward compat) ──
ALTER TABLE patients        ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts (id) ON DELETE CASCADE;
ALTER TABLE documents       ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts (id) ON DELETE CASCADE;
ALTER TABLE chunks          ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts (id) ON DELETE CASCADE;
ALTER TABLE inbound_messages ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts (id) ON DELETE SET NULL;
ALTER TABLE patient_phones  ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts (id) ON DELETE CASCADE;

-- Índices de isolamento por tenant
CREATE INDEX IF NOT EXISTS idx_patients_account   ON patients   (account_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_account  ON documents  (account_id);
CREATE INDEX IF NOT EXISTS idx_chunks_account     ON chunks     (account_id);

-- Conta demo padrão para a Dra. Débora (dados legados sem account_id ficam associados)
INSERT INTO accounts (id, email, name, password_hash, plan, onboarding_done)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'nutrideboraoliver@gmail.com',
    'Dra. Débora Oliver',
    '$2b$12$placeholder_hash_debora',   -- será substituído no onboarding
    'pro',
    true
) ON CONFLICT (email) DO NOTHING;

-- Vincula dados legados à conta da Débora
UPDATE patients         SET account_id = '00000000-0000-0000-0000-000000000001' WHERE account_id IS NULL;
UPDATE documents        SET account_id = '00000000-0000-0000-0000-000000000001' WHERE account_id IS NULL;
UPDATE chunks           SET account_id = '00000000-0000-0000-0000-000000000001' WHERE account_id IS NULL;
UPDATE patient_phones   SET account_id = '00000000-0000-0000-0000-000000000001' WHERE account_id IS NULL;
UPDATE inbound_messages SET account_id = '00000000-0000-0000-0000-000000000001' WHERE account_id IS NULL;

COMMENT ON TABLE accounts IS 'Nutricionistas cadastrados na plataforma NutriDeby SaaS';
COMMENT ON TABLE platform_credentials IS 'Vault de credenciais externas cifradas por nutricionista';
COMMENT ON TABLE extraction_jobs IS 'Fila de jobs de extração/sync por tenant';
