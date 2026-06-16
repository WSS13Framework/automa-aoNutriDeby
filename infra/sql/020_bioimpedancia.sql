-- 020_bioimpedancia.sql — Histórico de avaliações por bioimpedância digital

CREATE TABLE IF NOT EXISTS bioimpedancia_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Entradas
    altura_cm           NUMERIC(5,1) NOT NULL,
    peso_kg             NUMERIC(6,2) NOT NULL,
    idade               SMALLINT NOT NULL,
    sexo                CHAR(1) NOT NULL CHECK (sexo IN ('M','F')),

    -- Resultados calculados
    imc                 NUMERIC(5,2) NOT NULL,
    gordura_pct         NUMERIC(5,2) NOT NULL,   -- Gallagher 2000
    massa_muscular_kg   NUMERIC(6,2) NOT NULL,   -- Lee 2000
    massa_muscular_pct  NUMERIC(5,2) NOT NULL,
    massa_gorda_kg      NUMERIC(6,2) NOT NULL,
    massa_magra_kg      NUMERIC(6,2) NOT NULL,
    classificacao_gordura TEXT NOT NULL,
    classificacao_imc   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bioimpedancia_patient ON bioimpedancia_logs(patient_id, created_at DESC);
