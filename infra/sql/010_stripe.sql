-- 010_stripe.sql
BEGIN;
ALTER TABLE patients
  ADD COLUMN IF NOT EXISTS stripe_customer_id     TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT UNIQUE;
COMMIT;
