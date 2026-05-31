-- 018: detecção de padrões alimentares comportamentais

CREATE TABLE IF NOT EXISTS padroes_alimentares (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id        UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    food_log_id       UUID REFERENCES food_logs(id) ON DELETE SET NULL,
    fase              VARCHAR(20) NOT NULL,
    ciclo_numero      INTEGER NOT NULL DEFAULT 1,
    degradacao_nivel  INTEGER NOT NULL DEFAULT 0,
    alimentos_gatilho TEXT[]  NOT NULL DEFAULT '{}',
    acao_prescrita    TEXT,
    timer_minutos     INTEGER DEFAULT 30,
    data_deteccao     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT chk_fase CHECK (fase IN ('ESCAPE','CONFRONTO','RETORNO','CULPA'))
);

CREATE INDEX IF NOT EXISTS idx_padroes_patient    ON padroes_alimentares(patient_id, data_deteccao DESC);
CREATE INDEX IF NOT EXISTS idx_padroes_fase        ON padroes_alimentares(fase);
