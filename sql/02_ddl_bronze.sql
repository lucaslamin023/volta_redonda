-- ============================================================================
-- 02_ddl_bronze.sql
-- Camada Bronze: imutavel, auditoria HTTP e payloads JSON em texto puro
-- para garantir reprocessamento via Decimal sem jamais passar por float.
-- ============================================================================

CREATE TABLE IF NOT EXISTS bronze.ingestao_requisicao (
    id_req          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    endpoint        text        NOT NULL,
    parametros      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    url_chamada     text        NOT NULL,
    status_http     smallint    NOT NULL,
    qtd_itens       integer     NOT NULL DEFAULT 0,
    hash_sha256     text        NOT NULL,
    payload_texto   text        NOT NULL,
    dt_ingestao     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_bronze_req_endpoint_dt
    ON bronze.ingestao_requisicao (endpoint, dt_ingestao DESC);

CREATE TABLE IF NOT EXISTS bronze.entes_bruto (
    cod_ibge        integer     PRIMARY KEY,
    ente            text        NOT NULL,
    uf              char(2),
    esfera          char(1),
    regiao          char(2),
    capital         smallint,
    an_exercicio    smallint,
    populacao       integer,
    co_cnpj         text,
    payload_texto   text        NOT NULL,
    hash_sha256     text        NOT NULL,
    dt_ingestao     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bronze.anexos_bruto (
    esfera          text        NOT NULL,
    demonstrativo   text        NOT NULL,
    anexo           text        NOT NULL,
    payload_texto   text        NOT NULL,
    dt_ingestao     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (esfera, demonstrativo, anexo)
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'bronze' AND table_name = 'extrato_entregas_bruto'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'bronze'
          AND table_name = 'extrato_entregas_bruto'
          AND column_name = 'data_status_chave'
    ) THEN
        DROP TABLE bronze.extrato_entregas_bruto;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS bronze.extrato_entregas_bruto (
    id_extrato          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cod_ibge            integer     NOT NULL,
    exercicio           smallint    NOT NULL,
    entregavel          text        NOT NULL,
    periodo             smallint    NOT NULL,
    periodicidade       text        NOT NULL DEFAULT '',
    status_relatorio    text        NOT NULL DEFAULT '',
    data_status         timestamptz,
    data_status_chave   text        NOT NULL DEFAULT '',
    forma_envio         text,
    tipo_relatorio      text,
    instituicao         text        NOT NULL DEFAULT '',
    populacao           integer,
    payload_texto       text        NOT NULL,
    hash_sha256         text        NOT NULL,
    dt_ingestao         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (
        cod_ibge, exercicio, entregavel, periodo,
        periodicidade, instituicao, status_relatorio, data_status_chave
    )
);

CREATE INDEX IF NOT EXISTS ix_bronze_extrato_busca
    ON bronze.extrato_entregas_bruto (cod_ibge, exercicio, entregavel, periodo);

CREATE TABLE IF NOT EXISTS bronze.demonstrativo_bruto (
    id_entrega_bronze       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte                   text        NOT NULL CHECK (fonte IN ('DCA', 'RREO', 'RGF')),
    id_ente                 integer     NOT NULL,
    exercicio               smallint    NOT NULL,
    periodo_codigo          smallint    NOT NULL,
    periodicidade           text        NOT NULL,
    co_tipo_demonstrativo   text        NOT NULL,
    co_poder                text        NOT NULL,
    data_status_extrato     timestamptz,
    qtd_itens               integer     NOT NULL,
    hash_sha256             text        NOT NULL,
    payload_itens_texto     text        NOT NULL,
    dt_ingestao             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fonte, id_ente, exercicio, periodo_codigo, co_poder, hash_sha256)
);

CREATE INDEX IF NOT EXISTS ix_bronze_dem_particao
    ON bronze.demonstrativo_bruto (id_ente, fonte, exercicio, periodo_codigo, co_poder);

CREATE TABLE IF NOT EXISTS bronze.ibge_ipca_bruto (
    ano_mes                 integer     PRIMARY KEY, -- YYYYMM
    indice_texto            text        NOT NULL,
    variacao_mensal_texto   text,
    payload_texto           text        NOT NULL,
    dt_ingestao             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bronze.ibge_populacao_bruto (
    id_ente         integer     NOT NULL,
    exercicio       smallint    NOT NULL,
    fonte_ibge      text        NOT NULL,
    populacao       integer     NOT NULL CHECK (populacao > 0),
    payload_texto   text        NOT NULL,
    dt_ingestao     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id_ente, exercicio, fonte_ibge)
);
