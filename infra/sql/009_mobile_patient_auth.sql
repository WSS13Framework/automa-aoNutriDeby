-- 009_mobile_patient_auth.sql

BEGIN;

ALTER TABLE patients
  ADD COLUMN IF NOT EXISTS email                 TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS cpf                   TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS hashed_password       TEXT,
  ADD COLUMN IF NOT EXISTS subscription_status   TEXT NOT NULL DEFAULT 'trial',
  ADD COLUMN IF NOT EXISTS trial_ends_at         TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS subscription_ends_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS daily_calories_target FLOAT NOT NULL DEFAULT 2000.0,
  ADD COLUMN IF NOT EXISTS daily_protein_target  FLOAT NOT NULL DEFAULT 130.0,
  ADD COLUMN IF NOT EXISTS daily_carbs_target    FLOAT NOT NULL DEFAULT 220.0,
  ADD COLUMN IF NOT EXISTS daily_fat_target      FLOAT NOT NULL DEFAULT 65.0,
  ADD COLUMN IF NOT EXISTS water_target_ml       FLOAT NOT NULL DEFAULT 2000.0;

CREATE TABLE IF NOT EXISTS food_logs (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id     UUID        NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  account_id     UUID        REFERENCES accounts(id) ON DELETE SET NULL,
  meal_type      TEXT        NOT NULL,
  logged_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  photo_url      TEXT,
  source         TEXT        NOT NULL DEFAULT 'app',
  foods          JSONB       NOT NULL DEFAULT '[]',
  total_calories FLOAT       NOT NULL DEFAULT 0.0,
  total_protein  FLOAT       NOT NULL DEFAULT 0.0,
  total_carbs    FLOAT       NOT NULL DEFAULT 0.0,
  total_fat      FLOAT       NOT NULL DEFAULT 0.0,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índice simples em logged_at (queries filtram por range de data)
CREATE INDEX IF NOT EXISTS idx_food_logs_patient_logged
  ON food_logs (patient_id, logged_at DESC);

CREATE INDEX IF NOT EXISTS idx_food_logs_account
  ON food_logs (account_id, logged_at DESC);

COMMIT;
