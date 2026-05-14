-- ============================================================
-- NutriDeby — Schema inicial do banco de dados
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Usuários (nutricionistas)
CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    nome VARCHAR(255) NOT NULL,
    senha_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'nutricionista',
    ativo BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Pacientes
CREATE TABLE IF NOT EXISTS pacientes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    telefone VARCHAR(20) NOT NULL,
    foto_url TEXT,
    data_nascimento DATE,
    idade INTEGER,
    sexo CHAR(1) CHECK (sexo IN ('M', 'F')),
    altura_cm NUMERIC(5,1),
    peso_kg NUMERIC(5,1),
    imc NUMERIC(4,1),
    objetivo TEXT,
    restricoes_alimentares TEXT[] DEFAULT '{}',
    patologias TEXT[] DEFAULT '{}',
    medicamentos TEXT[] DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Metas nutricionais
CREATE TABLE IF NOT EXISTS metas_nutricionais (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paciente_id UUID NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    descricao VARCHAR(255) NOT NULL,
    valor_atual NUMERIC(10,2) DEFAULT 0,
    valor_meta NUMERIC(10,2) NOT NULL,
    unidade VARCHAR(50) NOT NULL,
    progresso NUMERIC(5,1) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Alertas clínicos
CREATE TABLE IF NOT EXISTS alertas_clinicos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paciente_id UUID NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    tipo VARCHAR(50) NOT NULL,
    mensagem TEXT NOT NULL,
    severidade VARCHAR(10) NOT NULL CHECK (severidade IN ('baixa', 'media', 'alta')),
    lido BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Mensagens WhatsApp
CREATE TABLE IF NOT EXISTS mensagens_whatsapp (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paciente_id UUID NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    direcao VARCHAR(10) NOT NULL CHECK (direcao IN ('entrada', 'saida')),
    conteudo TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Consultas de vídeo
CREATE TABLE IF NOT EXISTS consultas_video (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paciente_id UUID NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    nutricionista_id UUID NOT NULL REFERENCES usuarios(id),
    link TEXT NOT NULL,
    provider VARCHAR(20) NOT NULL DEFAULT 'google_meet',
    status VARCHAR(20) NOT NULL DEFAULT 'agendada',
    inicio TIMESTAMP WITH TIME ZONE,
    fim TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Sugestões de conduta (IA)
CREATE TABLE IF NOT EXISTS sugestoes_conduta (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paciente_id UUID NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    nutricionista_id UUID NOT NULL REFERENCES usuarios(id),
    texto TEXT NOT NULL,
    baseado_em TEXT,
    gerado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    aprovado BOOLEAN NOT NULL DEFAULT false,
    editado BOOLEAN NOT NULL DEFAULT false
);

-- Tabela TACO (alimentos)
CREATE TABLE IF NOT EXISTS taco_alimentos (
    id SERIAL PRIMARY KEY,
    descricao TEXT NOT NULL,
    energia_kcal NUMERIC(8,2),
    proteina_g NUMERIC(8,2),
    lipideos_g NUMERIC(8,2),
    carboidrato_g NUMERIC(8,2),
    fibra_g NUMERIC(8,2),
    calcio_mg NUMERIC(8,2),
    ferro_mg NUMERIC(8,2),
    sodio_mg NUMERIC(8,2)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_pacientes_nome ON pacientes USING gin(to_tsvector('portuguese', nome));
CREATE INDEX IF NOT EXISTS idx_metas_paciente ON metas_nutricionais(paciente_id);
CREATE INDEX IF NOT EXISTS idx_alertas_paciente ON alertas_clinicos(paciente_id);
CREATE INDEX IF NOT EXISTS idx_mensagens_paciente ON mensagens_whatsapp(paciente_id);
CREATE INDEX IF NOT EXISTS idx_mensagens_timestamp ON mensagens_whatsapp(timestamp);
CREATE INDEX IF NOT EXISTS idx_consultas_paciente ON consultas_video(paciente_id);
CREATE INDEX IF NOT EXISTS idx_sugestoes_paciente ON sugestoes_conduta(paciente_id);
CREATE INDEX IF NOT EXISTS idx_taco_descricao ON taco_alimentos USING gin(to_tsvector('portuguese', descricao));

-- Usuário admin padrão (senha: nutrideby2024)
-- Hash bcrypt de 'nutrideby2024' com 12 rounds
INSERT INTO usuarios (email, nome, senha_hash, role)
VALUES (
    'admin@nutrideby.com.br',
    'Deby Nutricionista',
    '$2a$12$LJ3m4ys8Kqxl5Bf0GhMrNOKwDjEJGFF3dO1Xv0bBqLzJxKqP5Kq2y',
    'admin'
) ON CONFLICT (email) DO NOTHING;
