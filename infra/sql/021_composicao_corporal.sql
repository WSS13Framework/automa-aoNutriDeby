-- 021_composicao_corporal.sql — Motor unificado de composição corporal

CREATE TABLE IF NOT EXISTS composicao_corporal (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Entradas antropométricas (sempre presentes)
    altura_cm           NUMERIC(5,1) NOT NULL,
    peso_kg             NUMERIC(6,2) NOT NULL,
    idade               SMALLINT NOT NULL,
    sexo                CHAR(1) NOT NULL CHECK (sexo IN ('M','F')),

    -- Fotos (opcional)
    foto_count          SMALLINT NOT NULL DEFAULT 0,
    photo_urls          TEXT[] NOT NULL DEFAULT '{}',

    -- Fonte da análise
    fonte               TEXT NOT NULL CHECK (fonte IN ('bioimpedancia','fusao')),

    -- Resultados fundidos (output final)
    imc                 NUMERIC(5,2) NOT NULL,
    gordura_pct         NUMERIC(5,2) NOT NULL,
    massa_muscular_kg   NUMERIC(6,2) NOT NULL,
    massa_muscular_pct  NUMERIC(5,2) NOT NULL,
    massa_gorda_kg      NUMERIC(6,2) NOT NULL,
    massa_magra_kg      NUMERIC(6,2) NOT NULL,
    classificacao_gordura TEXT NOT NULL,
    classificacao_imc   TEXT NOT NULL,
    notas_clinicas      TEXT,

    -- Rastreio dos motores individuais
    gordura_pct_bio     NUMERIC(5,2),  -- Gallagher puro
    gordura_pct_visao   NUMERIC(5,2),  -- GPT-4o Vision (null se sem fotos)
    muscular_pct_bio    NUMERIC(5,2),  -- Lee puro
    muscular_pct_visao  NUMERIC(5,2),  -- GPT-4o Vision
    notas_visao         TEXT,

    -- FKs opcionais para rastreabilidade
    bioimpedancia_id    UUID REFERENCES bioimpedancia_logs(id),
    bodyscan_id         UUID REFERENCES body_scans(id)
);

CREATE INDEX IF NOT EXISTS idx_composicao_patient ON composicao_corporal(patient_id, created_at DESC);
