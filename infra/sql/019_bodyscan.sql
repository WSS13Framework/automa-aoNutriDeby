-- 019_bodyscan.sql — Tabela de scans corporais (até 5 fotos, análise IA)

CREATE TABLE IF NOT EXISTS body_scans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    photo_urls      TEXT[]     NOT NULL DEFAULT '{}',  -- até 5 URLs no Spaces
    status          TEXT       NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','done','error')),

    body_fat_pct    NUMERIC(5,2),   -- % gordura corporal (0–100)
    muscle_mass_pct NUMERIC(5,2),   -- % massa muscular   (0–100)
    lean_mass_kg    NUMERIC(6,2),   -- massa magra estimada em kg (opcional)
    analysis_notes  TEXT,           -- texto livre do modelo
    error_detail    TEXT,           -- detalhe se status=error

    model_used      TEXT            -- ex: gpt-4o
);

CREATE INDEX IF NOT EXISTS idx_body_scans_patient ON body_scans(patient_id, created_at DESC);
