-- 015: auth + D4Sign por nutricionista (B2B) + campos de assinatura em clinical_records

ALTER TABLE professional_nutricionistas
  ADD COLUMN IF NOT EXISTS email            VARCHAR(255) UNIQUE,
  ADD COLUMN IF NOT EXISTS hashed_password  TEXT,
  ADD COLUMN IF NOT EXISTS d4sign_token_api TEXT,
  ADD COLUMN IF NOT EXISTS d4sign_crypt_key TEXT,
  ADD COLUMN IF NOT EXISTS d4sign_safe_uuid TEXT;

ALTER TABLE clinical_records
  ADD COLUMN IF NOT EXISTS d4sign_document_uuid TEXT,
  ADD COLUMN IF NOT EXISTS d4sign_status         VARCHAR(50) DEFAULT 'NONE',
  ADD COLUMN IF NOT EXISTS signing_initiated_at  TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS d4sign_signed_pdf_url TEXT;
