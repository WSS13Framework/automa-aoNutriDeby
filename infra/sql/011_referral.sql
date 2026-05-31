-- 011_referral.sql
BEGIN;
ALTER TABLE patients
  ADD COLUMN IF NOT EXISTS referral_code  TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS referred_by_id UUID REFERENCES patients(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS referral_rewards (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  referrer_id UUID        NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  referred_id UUID        NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  rewarded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  days_awarded INT        NOT NULL DEFAULT 3,
  UNIQUE(referred_id)
);
COMMIT;
