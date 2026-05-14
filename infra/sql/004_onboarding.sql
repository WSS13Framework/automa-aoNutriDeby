-- ============================================================
-- Migration 004: Onboarding multi-plataforma
-- Vault de credenciais criptografadas + rastreamento de jobs
-- ============================================================

-- Tabela de credenciais criptografadas por nutricionista/plataforma
CREATE TABLE IF NOT EXISTS onboarding_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nutritionist_id UUID NOT NULL,                      -- FK para users (quando existir)
    platform        TEXT NOT NULL,                      -- 'dietbox' | 'dietsmart' | 'nutrium' | 'nutricloud' | 'generic'
    username        TEXT,                               -- usuário (plaintext — não sensível)
    cred_enc        BYTEA NOT NULL,                     -- credencial criptografada AES-256-GCM
    cred_nonce      BYTEA NOT NULL,                     -- nonce do AES-GCM (96 bits)
    extra_config    JSONB DEFAULT '{}',                 -- config extra: base_url, instance_id, etc.
    is_valid        BOOLEAN DEFAULT TRUE,               -- false = credencial revogada ou inválida
    last_sync_at    TIMESTAMPTZ,                        -- última sincronização bem-sucedida
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (nutritionist_id, platform)                  -- 1 credencial por nutricionista por plataforma
);

CREATE INDEX IF NOT EXISTS idx_onboarding_cred_nutritionist
    ON onboarding_credentials (nutritionist_id);

CREATE INDEX IF NOT EXISTS idx_onboarding_cred_platform
    ON onboarding_credentials (platform);

-- Tabela de jobs de importação (rastreamento de progresso)
CREATE TABLE IF NOT EXISTS onboarding_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id   UUID REFERENCES onboarding_credentials(id) ON DELETE CASCADE,
    nutritionist_id UUID NOT NULL,
    platform        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',     -- queued | running | done | error | cancelled
    progress        INTEGER DEFAULT 0,                  -- 0-100
    total_records   INTEGER DEFAULT 0,
    processed       INTEGER DEFAULT 0,
    inserted        INTEGER DEFAULT 0,
    updated         INTEGER DEFAULT 0,
    errors          JSONB DEFAULT '[]',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    log             TEXT                                -- log resumido do job
);

CREATE INDEX IF NOT EXISTS idx_onboarding_jobs_nutritionist
    ON onboarding_jobs (nutritionist_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_onboarding_jobs_status
    ON onboarding_jobs (status)
    WHERE status IN ('queued', 'running');

-- Tabela de log de auditoria (LGPD)
CREATE TABLE IF NOT EXISTS onboarding_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nutritionist_id UUID NOT NULL,
    platform        TEXT NOT NULL,
    action          TEXT NOT NULL,                      -- 'connect' | 'sync' | 'revoke' | 'detect'
    ip_address      TEXT,
    user_agent      TEXT,
    result          TEXT,                               -- 'ok' | 'error'
    detail          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_audit_nutritionist
    ON onboarding_audit_log (nutritionist_id, created_at DESC);

COMMENT ON TABLE onboarding_credentials IS
    'Vault de credenciais de plataformas externas. Criptografia AES-256-GCM. Chave em ONBOARDING_VAULT_KEY (env var).';

COMMENT ON TABLE onboarding_jobs IS
    'Rastreamento de jobs de importação assíncronos via Redis Queue.';

COMMENT ON TABLE onboarding_audit_log IS
    'Log de auditoria LGPD: toda ação de connect/sync/revoke é registrada.';
