-- ============================================================================
-- 06_views_bi.sql
-- Camada Semantica de Apresentacao para o Power BI (Schema bi)
-- Garante desacoplamento fisico e permissao estrita de leitura ao powerbi_ro.
-- ============================================================================

-- Views principais sem prefixo para conexao direta do Power BI
CREATE OR REPLACE VIEW bi.d_calendario       AS SELECT * FROM gold.d_calendario;
CREATE OR REPLACE VIEW bi.d_ente             AS SELECT * FROM gold.d_ente;
CREATE OR REPLACE VIEW bi.d_poder            AS SELECT * FROM gold.d_poder;
CREATE OR REPLACE VIEW bi.d_coluna           AS SELECT * FROM gold.d_coluna;
CREATE OR REPLACE VIEW bi.d_secao            AS SELECT * FROM gold.d_secao;
CREATE OR REPLACE VIEW bi.d_conta            AS SELECT * FROM gold.d_conta;
CREATE OR REPLACE VIEW bi.d_funcao           AS SELECT * FROM gold.d_funcao;
CREATE OR REPLACE VIEW bi.d_natureza_despesa AS SELECT * FROM gold.d_natureza_despesa;
CREATE OR REPLACE VIEW bi.d_fonte_recurso    AS SELECT * FROM gold.d_fonte_recurso;
CREATE OR REPLACE VIEW bi.d_limite_lrf       AS SELECT * FROM gold.d_limite_lrf;
CREATE OR REPLACE VIEW bi.d_indicador        AS SELECT * FROM gold.d_indicador;

CREATE OR REPLACE VIEW bi.f_rreo             AS SELECT * FROM gold.f_rreo;
CREATE OR REPLACE VIEW bi.f_rgf              AS SELECT * FROM gold.f_rgf;
CREATE OR REPLACE VIEW bi.f_dca              AS SELECT * FROM gold.f_dca;
CREATE OR REPLACE VIEW bi.f_ipca             AS SELECT * FROM gold.f_ipca;
CREATE OR REPLACE VIEW bi.f_populacao        AS SELECT * FROM gold.f_populacao;
CREATE OR REPLACE VIEW bi.f_indicador        AS SELECT * FROM gold.f_indicador;
CREATE OR REPLACE VIEW bi.f_qualidade        AS SELECT * FROM gold.f_qualidade;
CREATE OR REPLACE VIEW bi.etl_controle       AS SELECT * FROM gold.etl_controle;

-- Views com prefixo vw_ mantidas por compatibilidade
CREATE OR REPLACE VIEW bi.vw_d_calendario       AS SELECT * FROM gold.d_calendario;
CREATE OR REPLACE VIEW bi.vw_d_ente             AS SELECT * FROM gold.d_ente;
CREATE OR REPLACE VIEW bi.vw_d_poder            AS SELECT * FROM gold.d_poder;
CREATE OR REPLACE VIEW bi.vw_d_coluna           AS SELECT * FROM gold.d_coluna;
CREATE OR REPLACE VIEW bi.vw_d_secao            AS SELECT * FROM gold.d_secao;
CREATE OR REPLACE VIEW bi.vw_d_conta            AS SELECT * FROM gold.d_conta;
CREATE OR REPLACE VIEW bi.vw_d_funcao           AS SELECT * FROM gold.d_funcao;
CREATE OR REPLACE VIEW bi.vw_d_natureza_despesa AS SELECT * FROM gold.d_natureza_despesa;
CREATE OR REPLACE VIEW bi.vw_d_fonte_recurso    AS SELECT * FROM gold.d_fonte_recurso;
CREATE OR REPLACE VIEW bi.vw_d_limite_lrf       AS SELECT * FROM gold.d_limite_lrf;
CREATE OR REPLACE VIEW bi.vw_d_indicador        AS SELECT * FROM gold.d_indicador;

CREATE OR REPLACE VIEW bi.vw_f_rreo             AS SELECT * FROM gold.f_rreo;
CREATE OR REPLACE VIEW bi.vw_f_rgf              AS SELECT * FROM gold.f_rgf;
CREATE OR REPLACE VIEW bi.vw_f_dca              AS SELECT * FROM gold.f_dca;
CREATE OR REPLACE VIEW bi.vw_f_ipca             AS SELECT * FROM gold.f_ipca;
CREATE OR REPLACE VIEW bi.vw_f_populacao        AS SELECT * FROM gold.f_populacao;
CREATE OR REPLACE VIEW bi.vw_f_indicador        AS SELECT * FROM gold.f_indicador;
CREATE OR REPLACE VIEW bi.vw_f_qualidade        AS SELECT * FROM gold.f_qualidade;
CREATE OR REPLACE VIEW bi.vw_etl_controle       AS SELECT * FROM gold.etl_controle;

GRANT USAGE ON SCHEMA gold TO powerbi_ro;
GRANT USAGE ON SCHEMA bi TO powerbi_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO powerbi_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA bi TO powerbi_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO powerbi_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA bi GRANT SELECT ON TABLES TO powerbi_ro;
