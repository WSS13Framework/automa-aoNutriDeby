-- 014: Google OAuth — adiciona google_id nos pacientes
ALTER TABLE patients ADD COLUMN IF NOT EXISTS google_id TEXT UNIQUE;
CREATE INDEX IF NOT EXISTS idx_patients_google_id ON patients(google_id) WHERE google_id IS NOT NULL;
