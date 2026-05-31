-- 013_waitlist.sql
CREATE TABLE IF NOT EXISTS waitlist_users (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT        NOT NULL,
  phone         TEXT        NOT NULL,
  email         TEXT        UNIQUE NOT NULL,
  referral_code TEXT        UNIQUE NOT NULL,
  referred_by   TEXT,
  points        INT         NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_waitlist_points ON waitlist_users (points DESC, created_at ASC);
