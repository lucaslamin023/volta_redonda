from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg


def calculate_and_load_indicators(
    conn: psycopg.Connection,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> int:
    """
    Calcula e materializa os 10 indicadores legais da LRF e constitucionais em gold.f_indicador:
    - PESSOAL_RCL_EXEC (RGF-01, Executivo, limite 54%)
    - PESSOAL_RCL_LEG  (RGF-01, Legislativo, limite 6%)
    - PESSOAL_RCL_CONS (RGF-01, Consolidado, limite 60%)
    - DCL_RCL          (RGF-02, Dívida Consolidada Líquida / RCL Ajustada, limite 120%)
    - GARANTIAS_RCL    (RGF-03, Garantias Concedidas / RCL Ajustada, limite 22%)
    - OP_CREDITO_RCL   (RGF-04, Operações de Crédito / RCL Ajustada, limite 16%)
    - ARO_RCL          (RGF-04, Antecipação de Receita Orçamentária / RCL Ajustada, limite 7%)
    - EDUCACAO_MIN     (RREO-14, Aplicação Mínima MDE, piso 25%)
    - SAUDE_MIN        (RREO-14, Aplicação Mínima ASPS, piso 15%)
    - CAIXA_LIQ_LIVRE  (RGF-05, Disponibilidade Líquida Recursos Não Vinculados, piso R$ 0,00)
    """
    with conn.cursor() as cur:
        # Limpeza idempotente da partição
        cur.execute(
            """
            DELETE FROM gold.f_indicador
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )

        query = """
        WITH
        -- ---------------------------------------------------------------------
        -- 1. RGF-01: Pessoal Executivo, Legislativo e Consolidado
        -- ---------------------------------------------------------------------
        rgf01_base AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo,
                r.sk_poder,
                MAX(CASE
                    WHEN dc.cod_conta = 'DespesaComPessoalTotal' AND dcol.coluna_padrao = 'VALOR_UNICO'
                    THEN r.valor
                END) AS dtp_valor,
                MAX(CASE
                    WHEN dc.cod_conta = 'ReceitaCorrenteLiquidaAjustada' AND dcol.coluna_padrao = 'VALOR_UNICO'
                    THEN r.valor
                    WHEN dc.cod_conta IN ('ReceitaCorrenteLiquidaLimiteLegal', 'ReceitaCorrenteLiquida') AND dcol.coluna_padrao = 'VALOR_UNICO'
                    THEN r.valor
                END) AS rcl_valor,
                MAX(CASE
                    WHEN dc.cod_conta = 'DespesaComPessoalTotal' AND dcol.coluna_padrao IN ('PERCENTUAL_RCL_AJUSTADA', 'PERCENTUAL_DECLARADO')
                    THEN r.valor
                END) AS pct_declarado
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
            WHERE r.anexo_codigo = 'RGF-01'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_poder
        ),
        pessoal_exec_rcl AS (
            SELECT sk_ente, sk_data_fim_periodo, rcl_valor
            FROM rgf01_base
            WHERE sk_poder = 1
        ),
        pessoal_indicadores AS (
            -- Executivo
            SELECT
                b.sk_ente,
                b.sk_data_fim_periodo,
                b.sk_poder,
                'PESSOAL_RCL_EXEC' AS codigo_indicador,
                'PESSOAL_EXECUTIVO' AS codigo_limite,
                b.dtp_valor AS numerador,
                b.rcl_valor AS denominador,
                CASE
                    WHEN b.rcl_valor IS NOT NULL AND b.rcl_valor > 0 AND b.dtp_valor IS NOT NULL
                    THEN ROUND((b.dtp_valor / b.rcl_valor) * 100.0, 6)
                    ELSE b.pct_declarado
                END AS valor_indicador,
                b.pct_declarado AS valor_declarado
            FROM rgf01_base b
            WHERE b.sk_poder = 1

            UNION ALL

            -- Legislativo
            SELECT
                b.sk_ente,
                b.sk_data_fim_periodo,
                b.sk_poder,
                'PESSOAL_RCL_LEG' AS codigo_indicador,
                'PESSOAL_LEGISLATIVO' AS codigo_limite,
                b.dtp_valor AS numerador,
                COALESCE(b.rcl_valor, pe.rcl_valor) AS denominador,
                CASE
                    WHEN COALESCE(b.rcl_valor, pe.rcl_valor) IS NOT NULL
                     AND COALESCE(b.rcl_valor, pe.rcl_valor) > 0
                     AND b.dtp_valor IS NOT NULL
                    THEN ROUND((b.dtp_valor / COALESCE(b.rcl_valor, pe.rcl_valor)) * 100.0, 6)
                    ELSE b.pct_declarado
                END AS valor_indicador,
                b.pct_declarado AS valor_declarado
            FROM rgf01_base b
            LEFT JOIN pessoal_exec_rcl pe
              ON pe.sk_ente = b.sk_ente AND pe.sk_data_fim_periodo = b.sk_data_fim_periodo
            WHERE b.sk_poder = 2

            UNION ALL

            -- Consolidado
            SELECT
                b.sk_ente,
                b.sk_data_fim_periodo,
                3 AS sk_poder,
                'PESSOAL_RCL_CONS' AS codigo_indicador,
                'PESSOAL_TOTAL' AS codigo_limite,
                b.dtp_valor AS numerador,
                COALESCE(b.rcl_valor, pe.rcl_valor) AS denominador,
                CASE
                    WHEN COALESCE(b.rcl_valor, pe.rcl_valor) IS NOT NULL
                     AND COALESCE(b.rcl_valor, pe.rcl_valor) > 0
                     AND b.dtp_valor IS NOT NULL
                    THEN ROUND((b.dtp_valor / COALESCE(b.rcl_valor, pe.rcl_valor)) * 100.0, 6)
                    ELSE b.pct_declarado
                END AS valor_indicador,
                b.pct_declarado AS valor_declarado
            FROM rgf01_base b
            LEFT JOIN pessoal_exec_rcl pe
              ON pe.sk_ente = b.sk_ente AND pe.sk_data_fim_periodo = b.sk_data_fim_periodo
            WHERE b.sk_poder = 3
        ),

        -- ---------------------------------------------------------------------
        -- 2. RGF-02: Dívida Consolidada Líquida / RCL
        -- ---------------------------------------------------------------------
        rgf02_periodo_col AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo,
                r.sk_poder,
                c.coluna_padrao,
                MAX(CASE WHEN dc.cod_conta = 'DividaConsolidadaLiquida' THEN r.valor END) AS dcl_valor,
                MAX(CASE
                    WHEN dc.cod_conta IN (
                        'ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento',
                        'RGF2ReceitaCorrenteLiquida'
                    ) THEN r.valor
                END) AS rcl_valor,
                MAX(CASE WHEN dc.cod_conta = 'PercentualDaDCLSobreARCL' THEN r.valor END) AS pct_declarado
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna c ON c.sk_coluna = r.sk_coluna
            JOIN gold.d_calendario cal ON cal.sk_data = r.sk_data_fim_periodo
            WHERE r.anexo_codigo = 'RGF-02'
              AND r.sk_poder = 1
              AND c.coluna_padrao IN (
                  'ATE_1_QUADRIMESTRE', 'ATE_2_QUADRIMESTRE', 'ATE_3_QUADRIMESTRE',
                  'ATE_1_SEMESTRE', 'ATE_2_SEMESTRE', 'VALOR_UNICO'
              )
              AND (
                  (cal.quadrimestre = 1 AND c.coluna_padrao = 'ATE_1_QUADRIMESTRE') OR
                  (cal.quadrimestre = 2 AND c.coluna_padrao = 'ATE_2_QUADRIMESTRE') OR
                  (cal.quadrimestre = 3 AND c.coluna_padrao = 'ATE_3_QUADRIMESTRE') OR
                  (cal.semestre = 1 AND c.coluna_padrao = 'ATE_1_SEMESTRE') OR
                  (cal.semestre = 2 AND c.coluna_padrao = 'ATE_2_SEMESTRE') OR
                  (c.coluna_padrao = 'VALOR_UNICO')
              )
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_poder, c.coluna_padrao
        ),
        dcl_indicadores AS (
            SELECT
                p.sk_ente,
                p.sk_data_fim_periodo,
                p.sk_poder,
                'DCL_RCL' AS codigo_indicador,
                'DCL_RCL' AS codigo_limite,
                p.dcl_valor AS numerador,
                p.rcl_valor AS denominador,
                CASE
                    WHEN p.rcl_valor IS NOT NULL AND p.rcl_valor > 0 AND p.dcl_valor IS NOT NULL
                    THEN ROUND((p.dcl_valor / p.rcl_valor) * 100.0, 6)
                    ELSE p.pct_declarado
                END AS valor_indicador,
                p.pct_declarado AS valor_declarado
            FROM rgf02_periodo_col p
            WHERE p.dcl_valor IS NOT NULL OR p.pct_declarado IS NOT NULL
        ),

        -- ---------------------------------------------------------------------
        -- 3. RGF-03: Garantias Concedidas / RCL
        -- ---------------------------------------------------------------------
        rgf03_base AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo,
                r.sk_poder,
                COALESCE(MAX(CASE
                    WHEN dc.cod_conta NOT IN (
                        'RGF3ReceitaCorrenteLiquida',
                        'ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento',
                        'LimiteDeAlerta',
                        'LimiteDefinidoPorResolucaoDoSenadoFederal',
                        'TransferenciasObrigatoriasDaUniaoRelativasAsEmendasIndividuais'
                    ) THEN r.valor
                END), 0.00) AS garantias_valor,
                MAX(CASE
                    WHEN dc.cod_conta IN (
                        'ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento',
                        'RGF3ReceitaCorrenteLiquida'
                    ) THEN r.valor
                END) AS rcl_valor
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna c ON c.sk_coluna = r.sk_coluna
            JOIN gold.d_calendario cal ON cal.sk_data = r.sk_data_fim_periodo
            WHERE r.anexo_codigo = 'RGF-03'
              AND r.sk_poder = 1
              AND (
                  (cal.quadrimestre = 1 AND c.coluna_padrao = 'ATE_1_QUADRIMESTRE') OR
                  (cal.quadrimestre = 2 AND c.coluna_padrao = 'ATE_2_QUADRIMESTRE') OR
                  (cal.quadrimestre = 3 AND c.coluna_padrao = 'ATE_3_QUADRIMESTRE') OR
                  (c.coluna_padrao = 'VALOR_UNICO')
              )
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_poder
        ),
        garantias_indicadores AS (
            SELECT
                g.sk_ente,
                g.sk_data_fim_periodo,
                g.sk_poder,
                'GARANTIAS_RCL' AS codigo_indicador,
                'GARANTIAS_RCL' AS codigo_limite,
                g.garantias_valor AS numerador,
                g.rcl_valor AS denominador,
                CASE
                    WHEN g.rcl_valor IS NOT NULL AND g.rcl_valor > 0
                    THEN ROUND((g.garantias_valor / g.rcl_valor) * 100.0, 6)
                    ELSE 0.000000
                END AS valor_indicador,
                0.000000 AS valor_declarado
            FROM rgf03_base g
            WHERE g.rcl_valor IS NOT NULL
        ),

        -- ---------------------------------------------------------------------
        -- 4. RGF-04: Operações de Crédito e ARO
        -- ---------------------------------------------------------------------
        rgf04_base AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo,
                r.sk_poder,
                COALESCE(MAX(CASE
                    WHEN dc.cod_conta IN (
                        'TotalConsideradoParaFinsDaApuracaoDoCumprimentoDoLimiteOperacoesDeCredito',
                        'RGF4OperacoesDeCreditoTotal',
                        'TotalConsideradoParaConstratacaoDeNovasOperacoesDeCredito'
                    ) AND dcol.coluna_padrao IN ('VALOR_UNICO', 'VALOR_ATE_PERIODO')
                    THEN r.valor
                END), 0.00) AS op_credito_valor,
                COALESCE(MAX(CASE
                    WHEN dc.cod_conta = 'OperacoesDeCreditoPorAntecipacaoDaReceitaOrcamentaria'
                     AND dcol.coluna_padrao = 'VALOR_UNICO'
                    THEN r.valor
                END), 0.00) AS aro_valor,
                MAX(CASE
                    WHEN dc.cod_conta IN (
                        'ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento',
                        'RGF4ReceitaCorrenteLiquida'
                    ) AND dcol.coluna_padrao = 'VALOR_UNICO'
                    THEN r.valor
                END) AS rcl_valor,
                MAX(CASE
                    WHEN dc.cod_conta IN (
                        'TotalConsideradoParaFinsDaApuracaoDoCumprimentoDoLimiteOperacoesDeCredito',
                        'TotalConsideradoParaConstratacaoDeNovasOperacoesDeCredito'
                    ) AND dcol.coluna_padrao IN ('PERCENTUAL_RCL_AJUSTADA', 'PERCENTUAL_DECLARADO')
                    THEN r.valor
                END) AS op_credito_pct_decl,
                MAX(CASE
                    WHEN dc.cod_conta = 'OperacoesDeCreditoPorAntecipacaoDaReceitaOrcamentaria'
                     AND dcol.coluna_padrao IN ('PERCENTUAL_RCL_AJUSTADA', 'PERCENTUAL_DECLARADO')
                    THEN r.valor
                END) AS aro_pct_decl
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
            WHERE r.anexo_codigo = 'RGF-04'
              AND r.sk_poder = 1
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_poder
        ),
        operacoes_indicadores AS (
            -- OP_CREDITO_RCL
            SELECT
                o.sk_ente,
                o.sk_data_fim_periodo,
                o.sk_poder,
                'OP_CREDITO_RCL' AS codigo_indicador,
                'OP_CREDITO_RCL' AS codigo_limite,
                o.op_credito_valor AS numerador,
                o.rcl_valor AS denominador,
                CASE
                    WHEN o.rcl_valor IS NOT NULL AND o.rcl_valor > 0
                    THEN ROUND((o.op_credito_valor / o.rcl_valor) * 100.0, 6)
                    ELSE COALESCE(o.op_credito_pct_decl, 0.000000)
                END AS valor_indicador,
                o.op_credito_pct_decl AS valor_declarado
            FROM rgf04_base o
            WHERE o.rcl_valor IS NOT NULL

            UNION ALL

            -- ARO_RCL
            SELECT
                o.sk_ente,
                o.sk_data_fim_periodo,
                o.sk_poder,
                'ARO_RCL' AS codigo_indicador,
                'ARO_RCL' AS codigo_limite,
                o.aro_valor AS numerador,
                o.rcl_valor AS denominador,
                CASE
                    WHEN o.rcl_valor IS NOT NULL AND o.rcl_valor > 0
                    THEN ROUND((o.aro_valor / o.rcl_valor) * 100.0, 6)
                    ELSE COALESCE(o.aro_pct_decl, 0.000000)
                END AS valor_indicador,
                o.aro_pct_decl AS valor_declarado
            FROM rgf04_base o
            WHERE o.rcl_valor IS NOT NULL
        ),

        -- ---------------------------------------------------------------------
        -- 5. RREO-14: Educação (MDE) e Saúde (ASPS)
        -- ---------------------------------------------------------------------
        rreo14_base AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo,
                1 AS sk_poder,
                MAX(CASE
                    WHEN dc.cod_conta = 'MinimoAnualDasReceitasDeImpostosNaManutencaoEDesenvolvimentoDoEnsinoDemonstrativoSimplificado'
                     AND dcol.coluna_padrao = 'VALOR_APURADO_ATE_PERIODO'
                    THEN r.valor
                END) AS educacao_valor,
                MAX(CASE
                    WHEN dc.cod_conta = 'MinimoAnualDasReceitasDeImpostosNaManutencaoEDesenvolvimentoDoEnsinoDemonstrativoSimplificado'
                     AND dcol.coluna_padrao = 'PERCENTUAL_DECLARADO'
                    THEN r.valor
                END) AS educacao_pct,
                MAX(CASE
                    WHEN dc.cod_conta = 'AplicacaoTotalDasDespesasComAcoesEServicosPublicosDeSaude'
                     AND dcol.coluna_padrao = 'VALOR_APURADO_ATE_PERIODO'
                    THEN r.valor
                END) AS saude_valor,
                MAX(CASE
                    WHEN dc.cod_conta = 'AplicacaoTotalDasDespesasComAcoesEServicosPublicosDeSaude'
                     AND dcol.coluna_padrao = 'PERCENTUAL_DECLARADO'
                    THEN r.valor
                END) AS saude_pct
            FROM gold.f_rreo r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
            WHERE r.anexo_codigo = 'RREO-14'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo
        ),
        constitucional_indicadores AS (
            -- Educação
            SELECT
                b.sk_ente,
                b.sk_data_fim_periodo,
                b.sk_poder,
                'EDUCACAO_MIN' AS codigo_indicador,
                'EDUCACAO_MIN' AS codigo_limite,
                b.educacao_valor AS numerador,
                NULL::numeric(18,2) AS denominador,
                b.educacao_pct AS valor_indicador,
                b.educacao_pct AS valor_declarado
            FROM rreo14_base b
            WHERE b.educacao_pct IS NOT NULL OR b.educacao_valor IS NOT NULL

            UNION ALL

            -- Saúde
            SELECT
                b.sk_ente,
                b.sk_data_fim_periodo,
                b.sk_poder,
                'SAUDE_MIN' AS codigo_indicador,
                'SAUDE_MIN' AS codigo_limite,
                b.saude_valor AS numerador,
                NULL::numeric(18,2) AS denominador,
                b.saude_pct AS valor_indicador,
                b.saude_pct AS valor_declarado
            FROM rreo14_base b
            WHERE b.saude_pct IS NOT NULL OR b.saude_valor IS NOT NULL
        ),

        -- ---------------------------------------------------------------------
        -- 6. RGF-05: Disponibilidade de Caixa Líquida Recursos Livres
        -- ---------------------------------------------------------------------
        rgf05_base AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo,
                r.sk_poder,
                MAX(CASE
                    WHEN dc.cod_conta LIKE '%%DisponibilidadeDeCaixaLiquida::TOT_NAO_VINCULADOS%%'
                     AND dcol.coluna_padrao = 'CAIXA_LIQUIDA_ANTES_RPNP'
                    THEN r.valor
                    WHEN dc.cod_conta LIKE '%%DisponibilidadeDeCaixaLiquidaAposRP::TOT_NAO_VINCULADOS%%'
                     AND dcol.coluna_padrao = 'CAIXA_LIQUIDA_APOS_RPNP'
                    THEN r.valor
                END) AS caixa_liq_valor,
                MAX(CASE
                    WHEN dc.cod_conta LIKE '%%DisponibilidadeDeCaixaBruta%%TOT_NAO_VINCULADOS%%'
                     AND dcol.coluna_padrao = 'CAIXA_BRUTA'
                    THEN r.valor
                END) AS caixa_bruta_valor,
                MAX(CASE
                    WHEN dc.cod_conta LIKE '%%DemaisObrigacoesFinanceiras%%TOT_NAO_VINCULADOS%%'
                     AND dcol.coluna_padrao = 'DEMAIS_OBRIGACOES_FINANCEIRAS'
                    THEN r.valor
                END) AS obrigacoes_valor
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
            WHERE r.anexo_codigo = 'RGF-05'
              AND r.sk_poder = 1
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_poder
        ),
        caixa_indicadores AS (
            SELECT
                c.sk_ente,
                c.sk_data_fim_periodo,
                c.sk_poder,
                'CAIXA_LIQ_LIVRE' AS codigo_indicador,
                'CAIXA_LIQ_MIN' AS codigo_limite,
                c.caixa_bruta_valor AS numerador,
                c.obrigacoes_valor AS denominador,
                c.caixa_liq_valor AS valor_indicador,
                c.caixa_liq_valor AS valor_declarado
            FROM rgf05_base c
            WHERE c.caixa_liq_valor IS NOT NULL
        ),

        -- ---------------------------------------------------------------------
        -- 7. Consolidação de todos os indicadores calculados e cruzamento com limites
        -- ---------------------------------------------------------------------
        all_indicadores AS (
            SELECT * FROM pessoal_indicadores
            UNION ALL
            SELECT * FROM dcl_indicadores
            UNION ALL
            SELECT * FROM garantias_indicadores
            UNION ALL
            SELECT * FROM operacoes_indicadores
            UNION ALL
            SELECT * FROM constitucional_indicadores
            UNION ALL
            SELECT * FROM caixa_indicadores
        ),
        ranked_indicadores AS (
            SELECT
                ai.sk_ente,
                ai.sk_data_fim_periodo,
                ai.sk_poder,
                dind.sk_indicador,
                dlim.sk_limite,
                ai.numerador,
                ai.denominador,
                ai.valor_indicador,
                ai.valor_declarado,
                CASE
                    WHEN ai.valor_indicador IS NOT NULL AND ai.valor_declarado IS NOT NULL
                    THEN ROUND(ai.valor_indicador - ai.valor_declarado, 6)
                END AS diferenca_declarado,
                CASE
                    WHEN dlim.tipo_limite = 'MAXIMO' AND ai.valor_indicador IS NOT NULL
                    THEN ROUND(dlim.percentual_limite - ai.valor_indicador, 6)
                    WHEN dlim.tipo_limite = 'MINIMO' AND ai.valor_indicador IS NOT NULL
                    THEN ROUND(ai.valor_indicador - dlim.percentual_limite, 6)
                END AS margem_ao_limite,
                CASE
                    WHEN dlim.sk_limite IS NULL THEN 'NAO_APLICA'
                    WHEN dlim.tipo_limite = 'MAXIMO' THEN
                        CASE
                            WHEN ai.valor_indicador > dlim.percentual_limite THEN 'ACIMA_LIMITE'
                            WHEN dlim.pct_prudencial IS NOT NULL AND ai.valor_indicador > dlim.pct_prudencial THEN 'PRUDENCIAL'
                            WHEN dlim.pct_alerta IS NOT NULL AND ai.valor_indicador > dlim.pct_alerta THEN 'ALERTA'
                            ELSE 'OK'
                        END
                    WHEN dlim.tipo_limite = 'MINIMO' THEN
                        CASE
                            -- Para educação e saúde (RREO-14), avalia-se descumprimento definitivo no fechamento anual (bimestre 6)
                            WHEN ai.codigo_indicador IN ('EDUCACAO_MIN', 'SAUDE_MIN') THEN
                                CASE
                                    WHEN cal.bimestre = 6 AND ai.valor_indicador < dlim.percentual_limite THEN 'ACIMA_LIMITE'
                                    WHEN ai.valor_indicador >= dlim.percentual_limite THEN 'OK'
                                    ELSE 'OK' -- Acompanhamento parcial nos bimestres intermediários
                                END
                            -- Para caixa líquida, valor negativo representa déficit
                            WHEN ai.codigo_indicador = 'CAIXA_LIQ_LIVRE' THEN
                                CASE
                                    WHEN ai.valor_indicador < 0 THEN 'ACIMA_LIMITE'
                                    ELSE 'OK'
                                END
                            ELSE
                                CASE
                                    WHEN ai.valor_indicador < dlim.percentual_limite THEN 'ACIMA_LIMITE'
                                    ELSE 'OK'
                                END
                        END
                    ELSE 'NAO_APLICA'
                END AS status_limite,
                CASE
                    WHEN ai.numerador IS NOT NULL AND ai.denominador IS NOT NULL THEN 'RECALCULADO'
                    ELSE 'DECLARADO'
                END AS metodo,
                ROW_NUMBER() OVER (
                    PARTITION BY ai.sk_ente, ai.sk_data_fim_periodo, ai.sk_poder, dind.sk_indicador
                    ORDER BY (ai.valor_indicador IS NOT NULL) DESC
                ) AS rn
            FROM all_indicadores ai
            JOIN gold.d_indicador dind
              ON dind.codigo_indicador = ai.codigo_indicador
            JOIN gold.d_calendario cal
              ON cal.sk_data = ai.sk_data_fim_periodo
            LEFT JOIN gold.d_limite_lrf dlim
              ON dlim.codigo_limite = ai.codigo_limite
             AND cal.data >= dlim.vigencia_ini
             AND (dlim.vigencia_fim IS NULL OR cal.data <= dlim.vigencia_fim)
        )
        INSERT INTO gold.f_indicador (
            sk_ente,
            sk_data_fim_periodo,
            sk_poder,
            sk_indicador,
            sk_limite,
            numerador,
            denominador,
            valor_indicador,
            valor_declarado,
            diferenca_declarado,
            margem_ao_limite,
            status_limite,
            metodo
        )
        SELECT
            sk_ente,
            sk_data_fim_periodo,
            sk_poder,
            sk_indicador,
            sk_limite,
            numerador,
            denominador,
            valor_indicador,
            valor_declarado,
            diferenca_declarado,
            margem_ao_limite,
            status_limite,
            metodo
        FROM ranked_indicadores
        WHERE rn = 1
          AND valor_indicador IS NOT NULL
        ON CONFLICT (sk_ente, sk_data_fim_periodo, sk_poder, sk_indicador)
        DO UPDATE SET
            sk_limite = EXCLUDED.sk_limite,
            numerador = EXCLUDED.numerador,
            denominador = EXCLUDED.denominador,
            valor_indicador = EXCLUDED.valor_indicador,
            valor_declarado = EXCLUDED.valor_declarado,
            diferenca_declarado = EXCLUDED.diferenca_declarado,
            margem_ao_limite = EXCLUDED.margem_ao_limite,
            status_limite = EXCLUDED.status_limite,
            metodo = EXCLUDED.metodo;
        """

        # Executa com os parâmetros de partição
        params = (
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,  # rgf01
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,  # rgf02
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,  # rgf03
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,  # rgf04
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,  # rreo14
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,  # rgf05
        )
        cur.execute(query, params)

        cur.execute(
            """
            SELECT COUNT(*) FROM gold.f_indicador
            WHERE (%s::integer[] IS NULL OR sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR sk_data_fim_periodo / 10000 <= %s::integer);
            """,
            (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
        )
        total = int(cur.fetchone()[0])

    conn.commit()
    return total
