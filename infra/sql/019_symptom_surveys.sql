-- 019: sabatina de sintomas (MSQ ultra-curto) — grade por sistema + burden total.
-- Cada resposta gera: documento doc_type='symptom_survey' (entra no pgvector) +
-- uma linha aqui com os scores estruturados para o dashboard.

CREATE TABLE IF NOT EXISTS patient_symptom_surveys (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id    UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    instrument    VARCHAR(40) NOT NULL DEFAULT 'msq_ultra_curto',
    total_score   INTEGER NOT NULL,
    max_score     INTEGER NOT NULL,
    burden_level  VARCHAR(20) NOT NULL,
    system_scores JSONB NOT NULL DEFAULT '{}',
    items         JSONB NOT NULL DEFAULT '[]',
    document_id   UUID REFERENCES documents(id) ON DELETE SET NULL,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_symptom_surveys_patient
    ON patient_symptom_surveys(patient_id, created_at DESC);

-- Privilégios para a role da aplicação (idempotente; ignora se a role não existir).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_nutrideby') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON patient_symptom_surveys TO app_nutrideby;
    END IF;
END $$;
