-- NutriDeby: schema inicial para extração CRM, chunks e rascunhos de campanha.
-- Dados sensíveis: aplicar controles de acesso, criptografia e política de retenção (LGPD).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Pacientes sincronizados do CRM (IDs externos + metadados mínimos).
CREATE TABLE patients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system   TEXT NOT NULL DEFAULT 'datebox',
    external_id     TEXT NOT NULL,
    display_name    TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_system, external_id)
);

CREATE INDEX idx_patients_updated ON patients (updated_at DESC);

-- Documentos / fatos clínicos em texto bruto (minimizar campos; preferir referência a storage se PDF).
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients (id) ON DELETE CASCADE,
    doc_type        TEXT NOT NULL,
    content_text    TEXT NOT NULL,
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_sha256  TEXT NOT NULL,
    source_ref      TEXT,
    UNIQUE (patient_id, doc_type, content_sha256)
);

CREATE INDEX idx_documents_patient ON documents (patient_id, collected_at DESC);

-- Chunks para embeddings / FAISS (faiss_id preenchido após ingestão no índice).
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients (id) ON DELETE CASCADE,
    document_id     UUID REFERENCES documents (id) ON DELETE SET NULL,
    chunk_index     INT NOT NULL,
    text            TEXT NOT NULL,
    embedding_model TEXT,
    faiss_id        BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX idx_chunks_patient ON chunks (patient_id);
CREATE INDEX idx_chunks_faiss ON chunks (faiss_id) WHERE faiss_id IS NOT NULL;

-- Controle de execuções do extrator (retomada / auditoria).
CREATE TABLE extraction_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running',
    cursor_state    JSONB NOT NULL DEFAULT '{}',
    error_message   TEXT,
    stats           JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_extraction_runs_started ON extraction_runs (started_at DESC);

-- Rascunhos gerados por LLM (revisão humana antes de envio).
CREATE TABLE campaign_drafts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients (id) ON DELETE CASCADE,
    channel         TEXT NOT NULL DEFAULT 'message',
    model           TEXT,
    prompt_version  TEXT,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_campaign_drafts_patient ON campaign_drafts (patient_id, created_at DESC);

COMMENT ON TABLE patients IS 'Titulares sincronizados do CRM; PII — acesso restrito.';
COMMENT ON TABLE documents IS 'Conteúdo clínico/administrativo em texto; minimização.';
COMMENT ON TABLE chunks IS 'Segmentos para embedding; faiss_id liga ao índice FAISS em disco.';
COMMENT ON TABLE extraction_runs IS 'Jobs de automação web; cursor_state para retomada idempotente.';
COMMENT ON TABLE campaign_drafts IS 'Saída DeepSeek/LLM; exige validação e base legal para disparo.';
