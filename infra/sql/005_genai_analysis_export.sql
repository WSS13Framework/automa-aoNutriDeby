-- Exportações de análise GenAI+RAG: URL do objecto no DigitalOcean Spaces (data lake).
-- Aplicar em bases existentes: psql "$DATABASE_URL" -f infra/sql/005_genai_analysis_export.sql

CREATE TABLE IF NOT EXISTS genai_analysis_exports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients (id) ON DELETE CASCADE,
    spaces_url      TEXT NOT NULL,
    persona         TEXT,
    query_preview   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_genai_analysis_exports_patient
    ON genai_analysis_exports (patient_id, created_at DESC);

COMMENT ON TABLE genai_analysis_exports IS 'URL do JSON de análise no Spaces; corpo completo só no object storage.';
