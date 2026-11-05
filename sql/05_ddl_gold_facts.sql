-- ============================================================================
-- 05_ddl_gold_facts.sql
-- Camada Gold - Tabelas Fato, Indicadores Materializados e Auditoria de Qualidade
-- Regra absoluta: valores monetarios NUMERIC(18,2), percentuais/razoes NUMERIC(12,6).
-- ============================================================================

CREATE TABLE IF NOT EXISTS gold.f_rreo (
    sk_ente             integer         NOT NULL REFERENCES gold.d_ente(sk_ente),
    sk_data_fim_periodo integer         NOT NULL REFERENCES gold.d_calendario(sk_data),
    sk_poder            integer         NOT NULL REFERENCES gold.d_poder(sk_poder),
    sk_secao            integer         NOT NULL REFERENCES gold.d_secao(sk_secao),
    sk_conta            integer         NOT NULL REFERENCES gold.d_conta(sk_conta),
    sk_coluna           integer         NOT NULL REFERENCES gold.d_coluna(sk_coluna),
    sk_funcao           integer         NOT NULL DEFAULT 0 REFERENCES gold.d_funcao(sk_funcao),
    anexo_codigo        text            NOT NULL,
    valor               numeric(18,2),
    eh_vigente          smallint        NOT NULL DEFAULT 1 CHECK (eh_vigente = 1),
    data_homologacao    timestamp,
    PRIMARY KEY (sk_ente, sk_data_fim_periodo, sk_poder, sk_secao, sk_conta, sk_coluna, sk_funcao)
);

CREATE TABLE IF NOT EXISTS gold.f_rgf (
    sk_ente             integer         NOT NULL REFERENCES gold.d_ente(sk_ente),
    sk_data_fim_periodo integer         NOT NULL REFERENCES gold.d_calendario(sk_data),
    sk_poder            integer         NOT NULL REFERENCES gold.d_poder(sk_poder),
    sk_secao            integer         NOT NULL REFERENCES gold.d_secao(sk_secao),
    sk_conta            integer         NOT NULL REFERENCES gold.d_conta(sk_conta),
    sk_coluna           integer         NOT NULL REFERENCES gold.d_coluna(sk_coluna),
    sk_fonte_recurso    integer         NOT NULL DEFAULT 0 REFERENCES gold.d_fonte_recurso(sk_fonte_recurso),
    anexo_codigo        text            NOT NULL,
    valor               numeric(18,2),
    eh_vigente          smallint        NOT NULL DEFAULT 1 CHECK (eh_vigente = 1),
    data_homologacao    timestamp,
    PRIMARY KEY (sk_ente, sk_data_fim_periodo, sk_poder, sk_secao, sk_conta, sk_coluna, sk_fonte_recurso)
);

CREATE TABLE IF NOT EXISTS gold.f_dca (
    sk_ente             integer         NOT NULL REFERENCES gold.d_ente(sk_ente),
    sk_data_fim_periodo integer         NOT NULL REFERENCES gold.d_calendario(sk_data),
    sk_poder            integer         NOT NULL REFERENCES gold.d_poder(sk_poder),
    sk_secao            integer         NOT NULL REFERENCES gold.d_secao(sk_secao),
    sk_conta            integer         NOT NULL REFERENCES gold.d_conta(sk_conta),
    sk_coluna           integer         NOT NULL REFERENCES gold.d_coluna(sk_coluna),
    sk_funcao           integer         NOT NULL DEFAULT 0 REFERENCES gold.d_funcao(sk_funcao),
    sk_natureza         integer         NOT NULL DEFAULT 0 REFERENCES gold.d_natureza_despesa(sk_natureza),
    sk_fonte_recurso    integer         NOT NULL DEFAULT 0 REFERENCES gold.d_fonte_recurso(sk_fonte_recurso),
    anexo_codigo        text            NOT NULL,
    valor               numeric(18,2),
    eh_vigente          smallint        NOT NULL DEFAULT 1 CHECK (eh_vigente = 1),
    data_homologacao    timestamp,
    PRIMARY KEY (
        sk_ente, sk_data_fim_periodo, sk_poder, sk_secao, sk_conta,
        sk_coluna, sk_funcao, sk_natureza, sk_fonte_recurso
    )
);

CREATE TABLE IF NOT EXISTS gold.f_ipca (
    sk_data                 integer         PRIMARY KEY REFERENCES gold.d_calendario(sk_data),
    indice                  numeric(18,6)   NOT NULL,
    variacao_mensal_pct     numeric(10,6),
    fonte                   text            NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.f_populacao (
    sk_ente         integer     NOT NULL REFERENCES gold.d_ente(sk_ente),
    exercicio       smallint    NOT NULL,
    populacao       integer     NOT NULL CHECK (populacao > 0),
    fonte           text        NOT NULL,
    data_referencia date,
    PRIMARY KEY (sk_ente, exercicio)
);

CREATE TABLE IF NOT EXISTS gold.f_indicador (
    sk_ente             integer         NOT NULL REFERENCES gold.d_ente(sk_ente),
    sk_data_fim_periodo integer         NOT NULL REFERENCES gold.d_calendario(sk_data),
    sk_poder            integer         NOT NULL REFERENCES gold.d_poder(sk_poder),
    sk_indicador        integer         NOT NULL REFERENCES gold.d_indicador(sk_indicador),
    sk_limite           integer         REFERENCES gold.d_limite_lrf(sk_limite),
    numerador           numeric(18,2),
    denominador         numeric(18,2),
    valor_indicador     numeric(18,6),
    valor_declarado     numeric(18,6),
    diferenca_declarado numeric(18,6),
    margem_ao_limite    numeric(18,6),
    status_limite       text            NOT NULL CHECK (status_limite IN (
                            'OK', 'ALERTA', 'PRUDENCIAL', 'ACIMA_LIMITE', 'NAO_APLICA'
                        )),
    metodo              text            NOT NULL CHECK (metodo IN ('RECALCULADO', 'DECLARADO')),
    PRIMARY KEY (sk_ente, sk_data_fim_periodo, sk_poder, sk_indicador)
);

CREATE TABLE IF NOT EXISTS gold.f_qualidade (
    id_ocorrencia   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_execucao     bigint,
    dt_execucao     timestamptz NOT NULL DEFAULT now(),
    sk_ente         integer     REFERENCES gold.d_ente(sk_ente),
    exercicio       smallint,
    periodo_codigo  smallint,
    anexo_codigo    text,
    codigo_teste    text        NOT NULL,
    severidade      text        NOT NULL CHECK (severidade IN ('BLOQUEANTE', 'ALERTA', 'INFO')),
    valor_esperado  text,
    valor_obtido    text,
    mensagem        text
);

CREATE TABLE IF NOT EXISTS gold.etl_controle (
    id_execucao     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inicio          timestamptz NOT NULL DEFAULT now(),
    fim             timestamptz,
    status          text        NOT NULL CHECK (status IN ('EM_ANDAMENTO', 'SUCESSO', 'FALHA')),
    escopo          text,
    linhas_gold     bigint      DEFAULT 0,
    observacao      text
);

CREATE INDEX IF NOT EXISTS ix_f_rreo_data      ON gold.f_rreo (sk_data_fim_periodo);
CREATE INDEX IF NOT EXISTS ix_f_rreo_conta     ON gold.f_rreo (sk_conta);
CREATE INDEX IF NOT EXISTS ix_f_rgf_data       ON gold.f_rgf  (sk_data_fim_periodo);
CREATE INDEX IF NOT EXISTS ix_f_rgf_conta      ON gold.f_rgf  (sk_conta);
CREATE INDEX IF NOT EXISTS ix_f_dca_data       ON gold.f_dca  (sk_data_fim_periodo);
CREATE INDEX IF NOT EXISTS ix_f_dca_conta      ON gold.f_dca  (sk_conta);
CREATE INDEX IF NOT EXISTS ix_f_qualidade_exec ON gold.f_qualidade (dt_execucao DESC, severidade);
