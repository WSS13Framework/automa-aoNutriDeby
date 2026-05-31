-- Mapeamento telefone WhatsApp → patient_id
-- Permite identificar o paciente quando ele envia mensagem inbound

CREATE TABLE IF NOT EXISTS patient_phones (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id  UUID NOT NULL REFERENCES patients (id) ON DELETE CASCADE,
    phone       TEXT NOT NULL,           -- formato E.164 sem +, ex: 5521999990000
    source      TEXT NOT NULL DEFAULT 'dietbox',
    verified    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (phone)
);

CREATE INDEX IF NOT EXISTS idx_patient_phones_patient ON patient_phones (patient_id);
CREATE INDEX IF NOT EXISTS idx_patient_phones_phone   ON patient_phones (phone);

-- Histórico de mensagens inbound (texto + imagem)
CREATE TABLE IF NOT EXISTS inbound_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID REFERENCES patients (id) ON DELETE SET NULL,
    phone           TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'twilio_whatsapp',  -- twilio_whatsapp | evolution
    message_type    TEXT NOT NULL DEFAULT 'text',             -- text | image | audio
    body            TEXT,
    media_url       TEXT,
    media_type      TEXT,
    ocr_text        TEXT,           -- texto extraído da imagem (Vision API)
    analysis_id     UUID,           -- genai_analysis_exports.id se disparou análise
    replied_at      TIMESTAMPTZ,
    reply_body      TEXT,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inbound_phone      ON inbound_messages (phone, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_inbound_patient    ON inbound_messages (patient_id, received_at DESC);
