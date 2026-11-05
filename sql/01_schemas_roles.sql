-- ============================================================================
-- 01_schemas_roles.sql
-- Criacao idempotente dos schemas Medallion (bronze, silver, gold, bi)
-- e configuracao base da role somente-leitura do Power BI.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS bi;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'powerbi_ro') THEN
        CREATE ROLE powerbi_ro NOLOGIN;
    END IF;
END
$$;

-- Garantir isolamento: powerbi_ro jamais acessa bronze ou silver
REVOKE ALL ON SCHEMA bronze FROM PUBLIC, powerbi_ro;
REVOKE ALL ON SCHEMA silver FROM PUBLIC, powerbi_ro;

GRANT USAGE ON SCHEMA gold TO powerbi_ro;
GRANT USAGE ON SCHEMA bi TO powerbi_ro;

ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO powerbi_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA bi GRANT SELECT ON TABLES TO powerbi_ro;
