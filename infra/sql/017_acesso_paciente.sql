-- 017: sistema de convite por código único (6 dígitos) para pacientes

CREATE TABLE IF NOT EXISTS acesso_paciente (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paciente_id         UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    codigo_unico        CHAR(6) NOT NULL UNIQUE,
    status_acesso       VARCHAR(20) NOT NULL DEFAULT 'pendente',
    data_convite        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    data_primeiro_acesso TIMESTAMP WITH TIME ZONE,
    tentativas          INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate       TIMESTAMP WITH TIME ZONE,
    CONSTRAINT chk_status CHECK (status_acesso IN ('pendente', 'ativo', 'bloqueado'))
);

CREATE INDEX IF NOT EXISTS idx_acesso_paciente_id    ON acesso_paciente(paciente_id);
CREATE INDEX IF NOT EXISTS idx_acesso_codigo         ON acesso_paciente(codigo_unico);
