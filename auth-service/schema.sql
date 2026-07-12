-- Auth Service schema (database: auth_db)
-- Apply once against a fresh database with psql (see README, Getting started
-- step 2). The app never creates or alters tables itself.

CREATE TYPE user_role AS ENUM ('customer', 'admin', 'super_admin');

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(100) NOT NULL,
    role            user_role    NOT NULL DEFAULT 'customer',
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    is_verified     BOOLEAN      NOT NULL DEFAULT false,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX ix_users_email ON users (email);

-- Keep updated_at fresh on every UPDATE (spec 2.2)
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_set_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
