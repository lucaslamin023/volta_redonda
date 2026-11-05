from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from siconfi_etl.config import Settings
from siconfi_etl.silver.seed_loader import SEEDS_DIR, load_profundidade_seed, load_secao_map

if TYPE_CHECKING:
    from pathlib import Path
    import psycopg


@dataclass(frozen=True)
class GoldFactsSummary:
    f_ipca: int
    f_populacao: int
    f_rreo: int
    f_rgf: int
    f_dca: int
    f_indicador: int
    rgf05_detalhe_com_fonte: int
    rgf_anexos_sem_fonte: int


@dataclass(frozen=True)
class GoldFactsAudit:
    counts: dict[str, int]
    rgf05_com_fonte: int
    rgf05_sem_fonte_detalhe: int
    fk_orfas_total: int


def load_gold_ipca(conn: psycopg.Connection) -> int:
    """
    Popula gold.f_ipca a partir de bronze.ibge_ipca_bruto, mapeando cada mês (YYYYMM)
    para o último dia do mês em gold.d_calendario (sk_data).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH ipca_parsed AS (
                SELECT
                    (ano_mes / 100)::smallint AS ano,
                    (ano_mes % 100)::smallint AS mes,
                    NULLIF(TRIM(indice_texto), '')::numeric(18,6) AS indice,
                    NULLIF(TRIM(variacao_mensal_texto), '')::numeric(10,6) AS variacao_mensal_pct,
                    'IBGE_SIDRA_1737' AS fonte
                FROM bronze.ibge_ipca_bruto
            ),
            ipca_with_data AS (
                SELECT
                    cal.max_sk_data AS sk_data,
                    ip.indice,
                    ip.variacao_mensal_pct,
                    ip.fonte
                FROM ipca_parsed ip
                JOIN (
                    SELECT ano, mes, MAX(sk_data) AS max_sk_data
                    FROM gold.d_calendario
                    GROUP BY ano, mes
                ) cal ON cal.ano = ip.ano AND cal.mes = ip.mes
                WHERE ip.indice IS NOT NULL
            )
            INSERT INTO gold.f_ipca (sk_data, indice, variacao_mensal_pct, fonte)
            SELECT sk_data, indice, variacao_mensal_pct, fonte
            FROM ipca_with_data
            ON CONFLICT (sk_data) DO UPDATE SET
                indice = EXCLUDED.indice,
                variacao_mensal_pct = EXCLUDED.variacao_mensal_pct,
                fonte = EXCLUDED.fonte;
            """
        )
        cur.execute("SELECT COUNT(*) FROM gold.f_ipca;")
        total = int(cur.fetchone()[0])
    conn.commit()
    return total


def load_gold_populacao(conn: psycopg.Connection, entes: list[int] | None = None) -> int:
    """
    Consolida população municipal anual em gold.f_populacao priorizando Censo/Estimativas
    oficiais IBGE e usando a população reportada no SICONFI como fallback auditado.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH ibge_pop AS (
                SELECT
                    e.sk_ente,
                    p.exercicio,
                    p.populacao,
                    p.fonte_ibge AS fonte,
                    CASE
                        WHEN p.fonte_ibge LIKE '%%CENSO%%' THEN make_date(p.exercicio, 8, 1)
                        ELSE make_date(p.exercicio, 7, 1)
                    END AS data_referencia
                FROM bronze.ibge_populacao_bruto p
                JOIN gold.d_ente e ON e.id_ente = p.id_ente
                WHERE (%s::integer[] IS NULL OR e.id_ente = ANY(%s::integer[]))
            ),
            siconfi_fallback AS (
                SELECT DISTINCT ON (e.sk_ente, s.exercicio)
                    e.sk_ente,
                    s.exercicio,
                    s.populacao,
                    'SICONFI' AS fonte,
                    make_date(s.exercicio, 12, 31) AS data_referencia
                FROM silver.siconfi_registro s
                JOIN gold.d_ente e ON e.id_ente = s.id_ente
                WHERE s.eh_vigente = 1
                  AND s.populacao IS NOT NULL
                  AND s.populacao > 0
                  AND (%s::integer[] IS NULL OR e.id_ente = ANY(%s::integer[]))
                  AND NOT EXISTS (
                      SELECT 1 FROM ibge_pop ip
                      WHERE ip.sk_ente = e.sk_ente AND ip.exercicio = s.exercicio
                  )
                ORDER BY e.sk_ente, s.exercicio, s.populacao DESC
            )
            INSERT INTO gold.f_populacao (sk_ente, exercicio, populacao, fonte, data_referencia)
            SELECT sk_ente, exercicio, populacao, fonte, data_referencia FROM ibge_pop
            UNION ALL
            SELECT sk_ente, exercicio, populacao, fonte, data_referencia FROM siconfi_fallback
            ON CONFLICT (sk_ente, exercicio) DO UPDATE SET
                populacao = EXCLUDED.populacao,
                fonte = EXCLUDED.fonte,
                data_referencia = EXCLUDED.data_referencia;
            """,
            (entes, entes, entes, entes),
        )
        cur.execute(
            """
            SELECT COUNT(*) FROM gold.f_populacao
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])));
            """,
            (entes, entes),
        )
        total = int(cur.fetchone()[0])
    conn.commit()
    return total


def build_gold_facts_accounting(
    conn: psycopg.Connection,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
    seeds_dir: Path = SEEDS_DIR,
) -> dict[str, int]:
    """
    Executa a carga particionada de gold.f_rreo, gold.f_dca e gold.f_rgf com resolução estrita de FKs,
    respeitando seed_profundidade.csv e aplicando a consolidação do Poder Executivo + Legislativo (RGF-01).
    """
    secao_entries = load_secao_map(seeds_dir)
    sec_map_tuples = [
        (s.fonte, s.anexo_codigo, s.rotulo_origem, s.secao_codigo) for s in secao_entries
    ]
    prof_entries = load_profundidade_seed(seeds_dir)
    prof_tuples = [(p.fonte, p.anexo_codigo, p.exercicio_inicial) for p in prof_entries]

    counts: dict[str, int] = {}

    with conn.cursor() as cur:
        # Tabelas temporárias indexadas para mapeamento de seções e profundidade histórica
        cur.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS _tmp_sec_map (
                fonte text,
                anexo_codigo text,
                rotulo_origem text,
                secao_codigo text,
                PRIMARY KEY (fonte, anexo_codigo, rotulo_origem)
            ) ON COMMIT DROP;
            """
        )
        cur.execute("TRUNCATE _tmp_sec_map;")
        cur.executemany("INSERT INTO _tmp_sec_map VALUES (%s, %s, %s, %s);", sec_map_tuples)

        cur.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS _tmp_profundidade (
                fonte text,
                anexo_codigo text,
                exercicio_inicial smallint,
                PRIMARY KEY (fonte, anexo_codigo)
            ) ON COMMIT DROP;
            """
        )
        cur.execute("TRUNCATE _tmp_profundidade;")
        cur.executemany("INSERT INTO _tmp_profundidade VALUES (%s, %s, %s);", prof_tuples)

        # ---------------------------------------------------------------------
        # 1. gold.f_rreo
        # ---------------------------------------------------------------------
        cur.execute(
            """
            DELETE FROM gold.f_rreo
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )

        cur.execute(
            """
            INSERT INTO gold.f_rreo (
                sk_ente,
                sk_data_fim_periodo,
                sk_poder,
                sk_secao,
                sk_conta,
                sk_coluna,
                sk_funcao,
                anexo_codigo,
                valor,
                eh_vigente,
                data_homologacao
            )
            SELECT
                e.sk_ente,
                cal.sk_data AS sk_data_fim_periodo,
                pod.sk_poder,
                ds.sk_secao,
                dc.sk_conta,
                dcol.sk_coluna,
                df.sk_funcao,
                s.anexo_codigo,
                s.valor,
                1 AS eh_vigente,
                s.data_homologacao
            FROM silver.siconfi_registro s
            JOIN _tmp_profundidade pr
              ON pr.fonte = s.fonte
             AND pr.anexo_codigo = s.anexo_codigo
            JOIN gold.d_ente e
              ON e.id_ente = s.id_ente
            JOIN gold.d_calendario cal
              ON cal.data = s.data_fim_periodo
            JOIN gold.d_poder pod
              ON pod.co_poder = s.co_poder
            JOIN _tmp_sec_map tsm
              ON tsm.fonte = s.fonte
             AND tsm.anexo_codigo = s.anexo_codigo
             AND tsm.rotulo_origem = s.rotulo_origem
            JOIN gold.d_secao ds
              ON ds.fonte = s.fonte
             AND ds.anexo_codigo = s.anexo_codigo
             AND ds.secao_codigo = tsm.secao_codigo
            JOIN gold.d_conta dc
              ON dc.fonte = s.fonte
             AND dc.anexo_codigo = s.anexo_codigo
             AND dc.cod_conta = s.cod_conta
            JOIN gold.d_coluna dcol
              ON dcol.coluna_padrao = s.coluna_padrao
            JOIN gold.d_funcao df
              ON df.cod_funcao = COALESCE(s.cod_funcao, '00')
             AND df.cod_subfuncao = COALESCE(s.cod_subfuncao, '')
            WHERE s.eh_vigente = 1
              AND s.fonte = 'RREO'
              AND s.exercicio >= pr.exercicio_inicial
              AND (%s::integer[] IS NULL OR s.id_ente = ANY(%s::integer[]))
              AND (%s::integer IS NULL OR s.exercicio >= %s::integer)
              AND (%s::integer IS NULL OR s.exercicio <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )
        cur.execute(
            """
            SELECT COUNT(*) FROM gold.f_rreo
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )
        counts["f_rreo"] = int(cur.fetchone()[0])

        # ---------------------------------------------------------------------
        # 2. gold.f_dca
        # ---------------------------------------------------------------------
        cur.execute(
            """
            DELETE FROM gold.f_dca
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )

        cur.execute(
            """
            INSERT INTO gold.f_dca (
                sk_ente,
                sk_data_fim_periodo,
                sk_poder,
                sk_secao,
                sk_conta,
                sk_coluna,
                sk_funcao,
                sk_natureza,
                sk_fonte_recurso,
                anexo_codigo,
                valor,
                eh_vigente,
                data_homologacao
            )
            SELECT
                e.sk_ente,
                cal.sk_data AS sk_data_fim_periodo,
                pod.sk_poder,
                ds.sk_secao,
                dc.sk_conta,
                dcol.sk_coluna,
                df.sk_funcao,
                dn.sk_natureza,
                dfr.sk_fonte_recurso,
                s.anexo_codigo,
                s.valor,
                1 AS eh_vigente,
                s.data_homologacao
            FROM silver.siconfi_registro s
            JOIN _tmp_profundidade pr
              ON pr.fonte = s.fonte
             AND pr.anexo_codigo = s.anexo_codigo
            JOIN gold.d_ente e
              ON e.id_ente = s.id_ente
            JOIN gold.d_calendario cal
              ON cal.data = s.data_fim_periodo
            JOIN gold.d_poder pod
              ON pod.co_poder = s.co_poder
            JOIN _tmp_sec_map tsm
              ON tsm.fonte = s.fonte
             AND tsm.anexo_codigo = s.anexo_codigo
             AND tsm.rotulo_origem = s.rotulo_origem
            JOIN gold.d_secao ds
              ON ds.fonte = s.fonte
             AND ds.anexo_codigo = s.anexo_codigo
             AND ds.secao_codigo = tsm.secao_codigo
            JOIN gold.d_conta dc
              ON dc.fonte = s.fonte
             AND dc.anexo_codigo = s.anexo_codigo
             AND dc.cod_conta = s.cod_conta
            JOIN gold.d_coluna dcol
              ON dcol.coluna_padrao = s.coluna_padrao
            JOIN gold.d_funcao df
              ON df.cod_funcao = COALESCE(s.cod_funcao, '00')
             AND df.cod_subfuncao = COALESCE(s.cod_subfuncao, '')
            JOIN gold.d_natureza_despesa dn
              ON dn.cod_natureza = COALESCE(s.cod_natureza, '0')
            JOIN gold.d_fonte_recurso dfr
              ON dfr.cod_fonte = COALESCE(s.cod_fonte, '0')
            WHERE s.eh_vigente = 1
              AND s.fonte = 'DCA'
              AND s.exercicio >= pr.exercicio_inicial
              AND (%s::integer[] IS NULL OR s.id_ente = ANY(%s::integer[]))
              AND (%s::integer IS NULL OR s.exercicio >= %s::integer)
              AND (%s::integer IS NULL OR s.exercicio <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )
        cur.execute(
            """
            SELECT COUNT(*) FROM gold.f_dca
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )
        counts["f_dca"] = int(cur.fetchone()[0])

        # ---------------------------------------------------------------------
        # 3. gold.f_rgf (linhas originais E e L)
        # ---------------------------------------------------------------------
        cur.execute(
            """
            DELETE FROM gold.f_rgf
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )

        cur.execute(
            """
            INSERT INTO gold.f_rgf (
                sk_ente,
                sk_data_fim_periodo,
                sk_poder,
                sk_secao,
                sk_conta,
                sk_coluna,
                sk_fonte_recurso,
                anexo_codigo,
                valor,
                eh_vigente,
                data_homologacao
            )
            SELECT
                e.sk_ente,
                cal.sk_data AS sk_data_fim_periodo,
                pod.sk_poder,
                ds.sk_secao,
                dc.sk_conta,
                dcol.sk_coluna,
                dfr.sk_fonte_recurso,
                s.anexo_codigo,
                s.valor,
                1 AS eh_vigente,
                s.data_homologacao
            FROM silver.siconfi_registro s
            JOIN _tmp_profundidade pr
              ON pr.fonte = s.fonte
             AND pr.anexo_codigo = s.anexo_codigo
            JOIN gold.d_ente e
              ON e.id_ente = s.id_ente
            JOIN gold.d_calendario cal
              ON cal.data = s.data_fim_periodo
            JOIN gold.d_poder pod
              ON pod.co_poder = s.co_poder
            JOIN _tmp_sec_map tsm
              ON tsm.fonte = s.fonte
             AND tsm.anexo_codigo = s.anexo_codigo
             AND tsm.rotulo_origem = s.rotulo_origem
            JOIN gold.d_secao ds
              ON ds.fonte = s.fonte
             AND ds.anexo_codigo = s.anexo_codigo
             AND ds.secao_codigo = tsm.secao_codigo
            JOIN gold.d_conta dc
              ON dc.fonte = s.fonte
             AND dc.anexo_codigo = s.anexo_codigo
             AND dc.cod_conta = s.cod_conta
            JOIN gold.d_coluna dcol
              ON dcol.coluna_padrao = s.coluna_padrao
            JOIN gold.d_fonte_recurso dfr
              ON dfr.cod_fonte = COALESCE(s.cod_fonte, '0')
            WHERE s.eh_vigente = 1
              AND s.fonte = 'RGF'
              AND s.exercicio >= pr.exercicio_inicial
              AND (%s::integer[] IS NULL OR s.id_ente = ANY(%s::integer[]))
              AND (%s::integer IS NULL OR s.exercicio >= %s::integer)
              AND (%s::integer IS NULL OR s.exercicio <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )

        # ---------------------------------------------------------------------
        # 3.1 Consolidação RGF-01 (sk_poder = 3: CONSOLIDADO)
        # ---------------------------------------------------------------------
        cur.execute(
            """
            INSERT INTO gold.f_rgf (
                sk_ente,
                sk_data_fim_periodo,
                sk_poder,
                sk_secao,
                sk_conta,
                sk_coluna,
                sk_fonte_recurso,
                anexo_codigo,
                valor,
                eh_vigente,
                data_homologacao
            )
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo,
                3 AS sk_poder,
                r.sk_secao,
                r.sk_conta,
                r.sk_coluna,
                0 AS sk_fonte_recurso,
                'RGF-01' AS anexo_codigo,
                CASE
                    -- Para RCL e limites percentuais, mantem o valor do Executivo
                    WHEN dc.cod_conta IN (
                        'ReceitaCorrenteLiquidaAjustada',
                        'ReceitaCorrenteLiquidaLimiteLegal',
                        'ReceitaCorrenteLiquida'
                    ) THEN MAX(CASE WHEN r.sk_poder = 1 THEN r.valor END)
                    -- Para contas monetarias aditivas de pessoal, soma Executivo + Legislativo
                    ELSE SUM(r.valor)
                END AS valor,
                1 AS eh_vigente,
                MAX(r.data_homologacao) AS data_homologacao
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            WHERE r.anexo_codigo = 'RGF-01'
              AND r.sk_poder IN (1, 2)
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_secao, r.sk_conta, r.sk_coluna, dc.cod_conta
            ON CONFLICT (sk_ente, sk_data_fim_periodo, sk_poder, sk_secao, sk_conta, sk_coluna, sk_fonte_recurso)
            DO UPDATE SET
                valor = EXCLUDED.valor,
                data_homologacao = EXCLUDED.data_homologacao;
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )

        cur.execute(
            """
            SELECT COUNT(*) FROM gold.f_rgf
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )
        counts["f_rgf"] = int(cur.fetchone()[0])

    conn.commit()
    return counts


def audit_gold_facts(conn: psycopg.Connection) -> GoldFactsAudit:
    """Verifica volumetria, fontes em RGF-05 e integridade referencial das tabelas fato."""
    counts: dict[str, int] = {}
    fact_tables = ["f_rreo", "f_rgf", "f_dca", "f_ipca", "f_populacao", "f_indicador"]

    with conn.cursor() as cur:
        for tbl in fact_tables:
            cur.execute(f"SELECT COUNT(*) FROM gold.{tbl};")
            counts[tbl] = int(cur.fetchone()[0])

        # RGF-05 com fonte de detalhe vs totais
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE sk_fonte_recurso <> 0),
                COUNT(*) FILTER (WHERE sk_fonte_recurso = 0)
            FROM gold.f_rgf
            WHERE anexo_codigo = 'RGF-05';
            """
        )
        rgf05_com_f, rgf05_tot = cur.fetchone()

        # Invariante T17: linhas de detalhe do RGF-05 sem fonte
        cur.execute(
            """
            SELECT COUNT(*)
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            WHERE r.anexo_codigo = 'RGF-05'
              AND r.sk_fonte_recurso = 0
              AND dc.cod_conta LIKE '%::FR_%';
            """
        )
        rgf05_sem_fonte_det = int(cur.fetchone()[0])

        # Verificação de FKs órfãs (T12)
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM gold.f_rreo r LEFT JOIN gold.d_ente e ON e.sk_ente = r.sk_ente WHERE e.sk_ente IS NULL) +
                (SELECT COUNT(*) FROM gold.f_rreo r LEFT JOIN gold.d_calendario c ON c.sk_data = r.sk_data_fim_periodo WHERE c.sk_data IS NULL) +
                (SELECT COUNT(*) FROM gold.f_rreo r LEFT JOIN gold.d_conta c ON c.sk_conta = r.sk_conta WHERE c.sk_conta IS NULL) +
                (SELECT COUNT(*) FROM gold.f_rgf r LEFT JOIN gold.d_ente e ON e.sk_ente = r.sk_ente WHERE e.sk_ente IS NULL) +
                (SELECT COUNT(*) FROM gold.f_rgf r LEFT JOIN gold.d_conta c ON c.sk_conta = r.sk_conta WHERE c.sk_conta IS NULL) +
                (SELECT COUNT(*) FROM gold.f_dca r LEFT JOIN gold.d_ente e ON e.sk_ente = r.sk_ente WHERE e.sk_ente IS NULL) +
                (SELECT COUNT(*) FROM gold.f_dca r LEFT JOIN gold.d_conta c ON c.sk_conta = r.sk_conta WHERE c.sk_conta IS NULL);
            """
        )
        fk_orfas = int(cur.fetchone()[0])

    return GoldFactsAudit(
        counts=counts,
        rgf05_com_fonte=int(rgf05_com_f or 0),
        rgf05_sem_fonte_detalhe=rgf05_sem_fonte_det,
        fk_orfas_total=fk_orfas,
    )


def build_gold_facts_all(
    conn: psycopg.Connection,
    cfg: Settings,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
    seeds_dir: Path = SEEDS_DIR,
) -> GoldFactsSummary:
    """
    Constrói e atualiza integralmente a camada fato do Star Schema:
    f_ipca, f_populacao, f_rreo, f_dca, f_rgf e f_indicador.
    """
    from siconfi_etl.gold.indicators_engine import calculate_and_load_indicators

    target_entes = entes or cfg.lista_entes
    start_year = ano_ini if ano_ini is not None else cfg.ano_inicial_extracao
    end_year = ano_fim if ano_fim is not None else cfg.ano_final_extracao

    load_gold_ipca(conn)
    load_gold_populacao(conn, target_entes)
    build_gold_facts_accounting(conn, target_entes, start_year, end_year, seeds_dir)
    calculate_and_load_indicators(conn, target_entes, start_year, end_year)

    audit = audit_gold_facts(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM gold.f_rgf
            WHERE anexo_codigo <> 'RGF-05' AND sk_fonte_recurso <> 0;
            """
        )
        anexos_sem_f = int(cur.fetchone()[0])

    return GoldFactsSummary(
        f_ipca=audit.counts["f_ipca"],
        f_populacao=audit.counts["f_populacao"],
        f_rreo=audit.counts["f_rreo"],
        f_rgf=audit.counts["f_rgf"],
        f_dca=audit.counts["f_dca"],
        f_indicador=audit.counts["f_indicador"],
        rgf05_detalhe_com_fonte=audit.rgf05_com_fonte,
        rgf_anexos_sem_fonte=anexos_sem_f,
    )
