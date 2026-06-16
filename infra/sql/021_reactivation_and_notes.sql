-- 021: reativação em 3 estágios (timestamps por etapa) + notas da nutricionista.
-- ADITIVO e IDEMPOTENTE. Não remove/renomeia nada existente
-- (reactivation_stage, reactivation_date, reactivation_confirmed_by permanecem).

-- Timestamps por estágio (complementam reactivation_stage já existente).
ALTER TABLE patients ADD COLUMN IF NOT EXISTS reactivation_responded_at   TIMESTAMPTZ;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS reactivation_scheduled_at   TIMESTAMPTZ;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS reactivation_reactivated_at TIMESTAMPTZ;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS reactivation_notes          TEXT;

CREATE INDEX IF NOT EXISTS idx_patients_reactivation_stage
    ON patients(reactivation_stage);

-- Notas livres da nutricionista (POST/GET /v1/patients/{id}/notes).
CREATE TABLE IF NOT EXISTS patient_notes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id  UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    author      TEXT,
    note        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patient_notes_patient
    ON patient_notes(patient_id, created_at DESC);

-- Privilégios para a role da aplicação (idempotente; ignora se a role não existir).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_nutrideby') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON patient_notes TO app_nutrideby;
    END IF;
END $$;
