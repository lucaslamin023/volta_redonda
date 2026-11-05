-- ============================================================================
-- 03_ddl_silver.sql
-- Camada Silver: registros tipados, normalizados (Unicode NFC), sem float,
-- com versao vigente identificada e cod_conta desambiguado.
-- ============================================================================

CREATE TABLE IF NOT EXISTS silver.siconfi_registro (
    registro_id         text        PRIMARY KEY,
    fonte               text        NOT NULL CHECK (fonte IN ('DCA', 'RREO', 'RGF')),
    id_ente             integer     NOT NULL,
    exercicio           smallint    NOT NULL,
    periodo_codigo      smallint    NOT NULL,
    periodicidade       text        NOT NULL CHECK (periodicidade IN ('ANUAL', 'BIMESTRAL', 'QUADRIMESTRAL', 'SEMESTRAL')),
    data_fim_periodo    date        NOT NULL,
    co_poder            text        NOT NULL CHECK (co_poder IN ('E', 'L', 'CONSOLIDADO')),
    anexo               text        NOT NULL,
    anexo_codigo        text        NOT NULL,
    rotulo_origem       text        NOT NULL,
    cod_conta_original  text        NOT NULL,
    cod_conta           text        NOT NULL,
    conta_descricao     text,
    coluna_origem       text        NOT NULL,
    coluna_padrao       text,
    cod_funcao          text,
    cod_subfuncao       text,
    cod_natureza        text,
    cod_fonte           text,
    valor               numeric(18,2),
    populacao           integer,
    data_homologacao    timestamp,
    versao_incerta      smallint    NOT NULL DEFAULT 0 CHECK (versao_incerta IN (0, 1)),
    derivado            smallint    NOT NULL DEFAULT 0 CHECK (derivado IN (0, 1)),
    eh_vigente          smallint    NOT NULL CHECK (eh_vigente IN (0, 1)),
    dt_carga            timestamptz NOT NULL DEFAULT now()
);

-- Chave natural unica estrita entre os registros vigentes
CREATE UNIQUE INDEX IF NOT EXISTS ux_silver_registro_vigente
    ON silver.siconfi_registro (
        id_ente,
        fonte,
        exercicio,
        periodo_codigo,
        co_poder,
        anexo_codigo,
        rotulo_origem,
        cod_conta,
        COALESCE(coluna_padrao, coluna_origem)
    )
    WHERE eh_vigente = 1;

CREATE INDEX IF NOT EXISTS ix_silver_particao
    ON silver.siconfi_registro (id_ente, fonte, exercicio, periodo_codigo)
    WHERE eh_vigente = 1;

CREATE INDEX IF NOT EXISTS ix_silver_anexo_conta
    ON silver.siconfi_registro (fonte, anexo_codigo, cod_conta)
    WHERE eh_vigente = 1;
