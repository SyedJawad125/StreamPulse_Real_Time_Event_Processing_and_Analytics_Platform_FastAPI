-- Run as the PostgreSQL superuser (postgres) ONCE, e.g. in PowerShell:
--   psql -U postgres -h localhost -f scripts/setup_database.sql
-- Then edit the password below BEFORE running (and use the same one in .env).

-- 1. Dedicated, non-superuser application role (no CREATEROLE/SUPERUSER).
CREATE ROLE streampulse_app LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- 2. Application database owned by that role (owner can run Alembic migrations).
CREATE DATABASE streampulse_db OWNER streampulse_app ENCODING 'UTF8';

-- 3. Separate database for the automated tests (name MUST end with _test; tests refuse anything else).
CREATE DATABASE streampulse_test OWNER streampulse_app ENCODING 'UTF8';

-- 4. Nobody else gets in by default.
REVOKE ALL ON DATABASE streampulse_db FROM PUBLIC;
REVOKE ALL ON DATABASE streampulse_test FROM PUBLIC;
GRANT CONNECT ON DATABASE streampulse_db TO streampulse_app;
GRANT CONNECT ON DATABASE streampulse_test TO streampulse_app;

-- 5. Keep the public schema usable by the owner only.
\connect streampulse_db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO streampulse_app;
\connect streampulse_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO streampulse_app;
