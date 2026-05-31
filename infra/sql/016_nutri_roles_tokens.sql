-- 016: roles, permissões e tokens de senha para nutricionistas

ALTER TABLE professional_nutricionistas
  ADD COLUMN IF NOT EXISTS role                   VARCHAR(20)  NOT NULL DEFAULT 'nutricionista',
  ADD COLUMN IF NOT EXISTS permissions            JSONB        NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS password_set           BOOLEAN      NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS invite_token           TEXT         UNIQUE,
  ADD COLUMN IF NOT EXISTS invite_token_expires_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS reset_token            TEXT         UNIQUE,
  ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP WITH TIME ZONE;

-- nutri já cadastrada com senha → marcar password_set
UPDATE professional_nutricionistas
   SET password_set = true
 WHERE hashed_password IS NOT NULL;
