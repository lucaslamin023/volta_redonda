from __future__ import annotations

from decimal import Decimal

from siconfi_etl.config import get_settings
from siconfi_etl.db import get_connection
from siconfi_etl.gold.facts_builder import (
    audit_gold_facts,
    build_gold_facts_accounting,
    load_gold_ipca,
    load_gold_populacao,
)
from siconfi_etl.gold.indicators_engine import calculate_and_load_indicators


def test_gold_ipca_mapping_and_invariants() -> None:
    """Valida carga e mapeamento de gold.f_ipca."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        load_gold_ipca(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH max_dias AS (
                    SELECT ano, mes, MAX(sk_data) AS max_sk_data
                    FROM gold.d_calendario
                    GROUP BY ano, mes
                )
                SELECT
                    count(*),
                    count(*) FILTER (WHERE f.sk_data = m.max_sk_data),
                    count(*) FILTER (WHERE f.indice > 0),
                    count(*) FILTER (WHERE f.variacao_mensal_pct IS NOT NULL)
                FROM gold.f_ipca f
                JOIN gold.d_calendario c ON c.sk_data = f.sk_data
                JOIN max_dias m ON m.ano = c.ano AND m.mes = c.mes;
                """
            )
            total, fim_mes, indices_pos, variacoes = cur.fetchone()

    assert total >= 140
    assert fim_mes == total
    assert indices_pos == total
    assert variacoes >= total - 1  # Primeiro mes da serie pode nao ter variacao


def test_gold_populacao_priority_and_fallback() -> None:
    """Valida carga de gold.f_populacao com prioridade Censo/Estimativa IBGE sobre SICONFI."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        load_gold_populacao(conn, cfg.lista_entes)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.id_ente,
                    count(DISTINCT p.exercicio),
                    count(*) FILTER (WHERE p.populacao > 0),
                    count(*) FILTER (WHERE p.fonte LIKE '%CENSO%' OR p.fonte LIKE '%ESTIMATIVA%')
                FROM gold.f_populacao p
                JOIN gold.d_ente e ON e.sk_ente = p.sk_ente
                GROUP BY e.id_ente
                ORDER BY e.id_ente;
                """
            )
            rows = cur.fetchall()

    assert len(rows) == len(cfg.lista_entes)
    for id_ente, num_exercicios, pop_positiva, ibge_oficial in rows:
        assert num_exercicios >= 10
        assert pop_positiva == num_exercicios
        assert ibge_oficial >= 8  # Maioria dos anos coberta por estimativa oficial


def test_gold_facts_accounting_idempotence_and_sums() -> None:
    """Valida idempotencia estrita e conservacao monetaria exata em duas execucoes de particao."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        # Executa primeira vez sobre ano 2023 de Volta Redonda
        build_gold_facts_accounting(conn, entes=[cfg.ente_principal], ano_ini=2023, ano_fim=2023)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT count(*) FROM gold.f_rreo WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT coalesce(sum(valor), 0.00) FROM gold.f_rreo WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT count(*) FROM gold.f_rgf WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT coalesce(sum(valor), 0.00) FROM gold.f_rgf WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT count(*) FROM gold.f_dca WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT coalesce(sum(valor), 0.00) FROM gold.f_dca WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023)
                """,
                (cfg.ente_principal, cfg.ente_principal, cfg.ente_principal, cfg.ente_principal, cfg.ente_principal, cfg.ente_principal),
            )
            cnt_rreo_1, sum_rreo_1, cnt_rgf_1, sum_rgf_1, cnt_dca_1, sum_dca_1 = cur.fetchone()

        # Reexecuta exatamente a mesma particao
        build_gold_facts_accounting(conn, entes=[cfg.ente_principal], ano_ini=2023, ano_fim=2023)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT count(*) FROM gold.f_rreo WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT coalesce(sum(valor), 0.00) FROM gold.f_rreo WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT count(*) FROM gold.f_rgf WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT coalesce(sum(valor), 0.00) FROM gold.f_rgf WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT count(*) FROM gold.f_dca WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023),
                    (SELECT coalesce(sum(valor), 0.00) FROM gold.f_dca WHERE sk_ente = (SELECT sk_ente FROM gold.d_ente WHERE id_ente = %s) AND sk_data_fim_periodo / 10000 = 2023)
                """,
                (cfg.ente_principal, cfg.ente_principal, cfg.ente_principal, cfg.ente_principal, cfg.ente_principal, cfg.ente_principal),
            )
            cnt_rreo_2, sum_rreo_2, cnt_rgf_2, sum_rgf_2, cnt_dca_2, sum_dca_2 = cur.fetchone()

    assert cnt_rreo_1 > 0 and cnt_rreo_1 == cnt_rreo_2
    assert sum_rreo_1 == sum_rreo_2
    assert cnt_rgf_1 > 0 and cnt_rgf_1 == cnt_rgf_2
    assert sum_rgf_1 == sum_rgf_2
    assert cnt_dca_1 > 0 and cnt_dca_1 == cnt_dca_2
    assert sum_dca_1 == sum_dca_2


def test_rgf01_consolidation_poder_3() -> None:
    """Valida se RGF-01 possui linhas consolidadas sk_poder = 3 onde DTP(Cons) = DTP(E) + DTP(L)."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH vr_dtp AS (
                    SELECT
                        r.sk_data_fim_periodo,
                        r.sk_poder,
                        r.valor AS dtp
                    FROM gold.f_rgf r
                    JOIN gold.d_ente e ON e.sk_ente = r.sk_ente
                    JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
                    JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
                    WHERE e.id_ente = %s
                      AND r.anexo_codigo = 'RGF-01'
                      AND dc.cod_conta = 'DespesaComPessoalTotal'
                      AND dcol.coluna_padrao = 'VALOR_UNICO'
                      AND r.sk_data_fim_periodo / 10000 = 2023
                )
                SELECT
                    sk_data_fim_periodo,
                    MAX(CASE WHEN sk_poder = 1 THEN dtp END) AS dtp_exec,
                    MAX(CASE WHEN sk_poder = 2 THEN dtp END) AS dtp_leg,
                    MAX(CASE WHEN sk_poder = 3 THEN dtp END) AS dtp_cons
                FROM vr_dtp
                GROUP BY sk_data_fim_periodo
                ORDER BY sk_data_fim_periodo;
                """,
                (cfg.ente_principal,),
            )
            rows = cur.fetchall()

    assert len(rows) > 0
    for sk_data, dtp_e, dtp_l, dtp_cons in rows:
        assert dtp_e is not None
        assert dtp_l is not None
        assert dtp_cons is not None
        assert dtp_cons == dtp_e + dtp_l


def test_rgf05_fonte_recurso_assignment() -> None:
    """Valida se o RGF-05 atribui sk_fonte_recurso <> 0 nas linhas de detalhe e 0 nos demais anexos."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        audit = audit_gold_facts(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM gold.f_rgf
                WHERE anexo_codigo <> 'RGF-05' AND sk_fonte_recurso <> 0;
                """
            )
            outros_com_fonte = int(cur.fetchone()[0])

    assert audit.rgf05_com_fonte > 0
    assert audit.rgf05_sem_fonte_detalhe == 0
    assert outros_com_fonte == 0


def test_indicators_engine_all_10_indicators() -> None:
    """Valida se os 10 indicadores estao materializados em gold.f_indicador com limites e status validos."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        calculate_and_load_indicators(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ind.codigo_indicador,
                    count(*),
                    count(f.sk_limite),
                    count(*) FILTER (WHERE f.status_limite IN ('OK', 'ALERTA', 'PRUDENCIAL', 'ACIMA_LIMITE', 'NAO_APLICA')),
                    count(*) FILTER (WHERE f.metodo IN ('RECALCULADO', 'DECLARADO'))
                FROM gold.f_indicador f
                JOIN gold.d_indicador ind ON ind.sk_indicador = f.sk_indicador
                GROUP BY ind.codigo_indicador
                ORDER BY ind.codigo_indicador;
                """
            )
            rows = cur.fetchall()

    expected_indicators = {
        "ARO_RCL",
        "CAIXA_LIQ_LIVRE",
        "DCL_RCL",
        "EDUCACAO_MIN",
        "GARANTIAS_RCL",
        "OP_CREDITO_RCL",
        "PESSOAL_RCL_CONS",
        "PESSOAL_RCL_EXEC",
        "PESSOAL_RCL_LEG",
        "SAUDE_MIN",
    }
    found_indicators = {r[0] for r in rows}
    assert expected_indicators.issubset(found_indicators)

    for cod_ind, total_rows, with_limite, valid_status, valid_metodo in rows:
        assert total_rows > 0
        assert with_limite == total_rows, f"Indicador {cod_ind} possui registros sem sk_limite!"
        assert valid_status == total_rows, f"Indicador {cod_ind} possui status_limite invalido!"
        assert valid_metodo == total_rows, f"Indicador {cod_ind} possui metodo invalido!"


def test_zero_fk_orphans_in_gold_facts() -> None:
    """Garante que nao ha nenhuma FK orfa em todas as tabelas fato (T12)."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        audit = audit_gold_facts(conn)

    assert audit.fk_orfas_total == 0
