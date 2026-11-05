from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from siconfi_etl.config import Settings
from siconfi_etl.gold.hierarchy import (
    build_account_hierarchy_catalog,
    classify_natureza_despesa,
    generate_calendar_rows,
    validate_limite_lrf_vigencia,
)
from siconfi_etl.silver.disambiguator import OFFICIAL_FUNCOES, OFFICIAL_SUBFUNCOES
from siconfi_etl.silver.normalizer import normalize_text
from siconfi_etl.silver.seeds_contas import enrich_conta_hierarquia_from_silver
from siconfi_etl.silver.seed_loader import (
    SEEDS_DIR,
    load_coluna_map,
    load_conta_equivalencia,
    load_conta_hierarquia,
    load_fonte_recurso_seed,
    load_indicador_seed,
    load_limite_lrf_seed,
    load_secao_map,
)

if TYPE_CHECKING:
    import psycopg

MANDATORY_GRUPOS_ANALITICOS: set[str] = {
    # Receita (§8 Guia Star Schema)
    "RECEITA_PROPRIA",
    "TRANSFERENCIAS_UNIAO",
    "TRANSFERENCIAS_ESTADO",
    "TRANSFERENCIAS_FUNDEB",
    "TRANSFERENCIAS_SUS",
    "OPERACOES_CREDITO",
    "OUTRAS",
    # Despesa (§8 Guia Star Schema)
    "PESSOAL",
    "JUROS_ENCARGOS_DIVIDA",
    "OUTRAS_CORRENTES",
    "INVESTIMENTOS",
    "INVERSOES_FINANCEIRAS",
    "AMORTIZACAO_DIVIDA",
    # Balanco Patrimonial & DVP (20 Quocientes Kohama / TCC)
    "ATIVO",
    "ATIVO_CIRCULANTE",
    "CAIXA_EQUIVALENTES",
    "ATIVO_NAO_CIRCULANTE",
    "REALIZAVEL_LP",
    "PASSIVO_PL",
    "PASSIVO_CIRCULANTE",
    "PASSIVO_NAO_CIRCULANTE",
    "PATRIMONIO_LIQUIDO",
    "ATIVO_FINANCEIRO",
    "ATIVO_PERMANENTE",
    "PASSIVO_FINANCEIRO",
    "PASSIVO_PERMANENTE",
    "VPA",
    "VPD",
    "RESULTADO_PATRIMONIAL",
}


@dataclass(frozen=True)
class GoldDimsSummary:
    d_calendario: int
    d_ente: int
    d_poder: int
    d_coluna: int
    d_secao: int
    d_fonte_recurso: int
    d_limite_lrf: int
    d_indicador: int
    d_funcao: int
    d_natureza_despesa: int
    d_conta: int
    t03_contas_sem_hierarquia: int


@dataclass(frozen=True)
class GoldDimsAudit:
    counts: dict[str, int]
    t14_vigencia_overlaps: int
    folha_and_total_violations: int
    parent_marked_folha_violations: int
    silver_accounts_missing_in_d_conta: int
    missing_grupos_analiticos: list[str]


def build_gold_dimensions(
    conn: psycopg.Connection,
    cfg: Settings,
    seeds_dir: Path = SEEDS_DIR,
) -> GoldDimsSummary:
    """
    Popula de forma deterministica e idempotente todas as 11 dimensoes do schema gold (d_*).
    """
    enrich_conta_hierarquia_from_silver(conn, seeds_dir)
    col_entries = load_coluna_map(seeds_dir)
    sec_entries = load_secao_map(seeds_dir)
    fr_entries = load_fonte_recurso_seed(seeds_dir)
    eq_entries = load_conta_equivalencia(seeds_dir)
    hier_entries = load_conta_hierarquia(seeds_dir)
    lim_entries = load_limite_lrf_seed(seeds_dir)
    ind_entries = load_indicador_seed(seeds_dir)

    vig_errors = validate_limite_lrf_vigencia(lim_entries)
    if vig_errors:
        raise ValueError(f"Violacao bloqueante T14_VIGENCIA em seed_limite_lrf.csv: {vig_errors}")

    start_cal_year = min(2014, cfg.ano_inicial_extracao - 1)
    end_cal_year = max(2027, cfg.ano_final_extracao + 1)
    cal_rows = generate_calendar_rows(start_cal_year, end_cal_year)

    with conn.cursor() as cur:
        # 1. gold.d_calendario
        cur.executemany(
            """
            INSERT INTO gold.d_calendario (
                sk_data, data, ano, semestre, trimestre, quadrimestre, bimestre,
                mes, nome_mes, mes_ano, eh_fim_bimestre, eh_fim_quadrimestre,
                eh_fim_semestre, eh_fim_exercicio, label_periodo_rreo, label_periodo_rgf
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (sk_data) DO UPDATE SET
                data = EXCLUDED.data,
                ano = EXCLUDED.ano,
                semestre = EXCLUDED.semestre,
                trimestre = EXCLUDED.trimestre,
                quadrimestre = EXCLUDED.quadrimestre,
                bimestre = EXCLUDED.bimestre,
                mes = EXCLUDED.mes,
                nome_mes = EXCLUDED.nome_mes,
                mes_ano = EXCLUDED.mes_ano,
                eh_fim_bimestre = EXCLUDED.eh_fim_bimestre,
                eh_fim_quadrimestre = EXCLUDED.eh_fim_quadrimestre,
                eh_fim_semestre = EXCLUDED.eh_fim_semestre,
                eh_fim_exercicio = EXCLUDED.eh_fim_exercicio,
                label_periodo_rreo = EXCLUDED.label_periodo_rreo,
                label_periodo_rgf = EXCLUDED.label_periodo_rgf;
            """,
            [
                (
                    r.sk_data, r.data, r.ano, r.semestre, r.trimestre, r.quadrimestre, r.bimestre,
                    r.mes, r.nome_mes, r.mes_ano, r.eh_fim_bimestre, r.eh_fim_quadrimestre,
                    r.eh_fim_semestre, r.eh_fim_exercicio, r.label_periodo_rreo, r.label_periodo_rgf,
                )
                for r in cal_rows
            ],
        )

        # 2. gold.d_ente (a partir dos entes ativos na Silver + configurados em ENTES_ESCOPO)
        cur.execute(
            """
            SELECT
                e.cod_ibge,
                e.ente,
                COALESCE(e.uf, 'RJ') AS uf,
                e.regiao,
                CASE
                    WHEN e.esfera = 'M' THEN 'Municipal'
                    WHEN e.esfera = 'E' THEN 'Estadual'
                    WHEN e.esfera = 'U' THEN 'União'
                    WHEN e.esfera = 'D' THEN 'Distrital'
                    ELSE COALESCE(e.esfera, 'Municipal')
                END AS esfera_txt,
                COALESCE(e.capital, 0) AS capital,
                e.co_cnpj,
                e.populacao,
                e.an_exercicio
            FROM bronze.entes_bruto e
            WHERE e.cod_ibge = ANY(%s)
               OR e.cod_ibge IN (SELECT DISTINCT id_ente FROM silver.siconfi_registro)
            ORDER BY e.cod_ibge;
            """,
            (cfg.lista_entes,),
        )
        entes_rows = cur.fetchall()
        for (
            id_ente, nome_ente, uf, regiao, esfera_txt, capital, co_cnpj, pop_ref, ano_ref
        ) in entes_rows:
            eh_princ = 1 if int(id_ente) == int(cfg.ente_principal) else 0
            cur.execute(
                """
                INSERT INTO gold.d_ente (
                    id_ente, nome_ente, uf, regiao, esfera, capital,
                    co_cnpj, populacao_ref, ano_ref_populacao, eh_ente_principal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_ente) DO UPDATE SET
                    nome_ente = EXCLUDED.nome_ente,
                    uf = EXCLUDED.uf,
                    regiao = EXCLUDED.regiao,
                    esfera = EXCLUDED.esfera,
                    capital = EXCLUDED.capital,
                    co_cnpj = EXCLUDED.co_cnpj,
                    populacao_ref = EXCLUDED.populacao_ref,
                    ano_ref_populacao = EXCLUDED.ano_ref_populacao,
                    eh_ente_principal = EXCLUDED.eh_ente_principal;
                """,
                (
                    int(id_ente),
                    normalize_text(nome_ente),
                    normalize_text(uf)[:2],
                    normalize_text(regiao)[:2] if regiao else None,
                    esfera_txt,
                    int(capital) if capital is not None else 0,
                    normalize_text(co_cnpj) or None,
                    int(pop_ref) if pop_ref is not None else None,
                    int(ano_ref) if ano_ref is not None else None,
                    eh_princ,
                ),
            )

        # 3. gold.d_poder
        cur.executemany(
            """
            INSERT INTO gold.d_poder (sk_poder, co_poder, nome_poder)
            VALUES (%s, %s, %s)
            ON CONFLICT (sk_poder) DO UPDATE SET
                co_poder = EXCLUDED.co_poder,
                nome_poder = EXCLUDED.nome_poder;
            """,
            [
                (1, "E", "Poder Executivo"),
                (2, "L", "Poder Legislativo"),
                (3, "CONSOLIDADO", "Ente Consolidado"),
            ],
        )

        # 4. gold.d_coluna
        col_by_padrao: dict[str, tuple[str, str, str, int]] = {}
        for c in col_entries:
            if c.coluna_padrao not in col_by_padrao:
                col_by_padrao[c.coluna_padrao] = (
                    c.coluna_origem,
                    c.tipo_medida,
                    c.aditividade,
                    c.ordem_exibicao,
                )
        cur.executemany(
            """
            INSERT INTO gold.d_coluna (
                coluna_padrao, coluna_origem_exemplo, tipo_medida, aditividade, ordem_exibicao
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (coluna_padrao) DO UPDATE SET
                coluna_origem_exemplo = EXCLUDED.coluna_origem_exemplo,
                tipo_medida = EXCLUDED.tipo_medida,
                aditividade = EXCLUDED.aditividade,
                ordem_exibicao = EXCLUDED.ordem_exibicao;
            """,
            [
                (padrao, orig_ex, tipo_med, adit, ordem)
                for padrao, (orig_ex, tipo_med, adit, ordem) in sorted(col_by_padrao.items())
            ],
        )

        # 5. gold.d_secao
        sec_by_key: dict[tuple[str, str, str], tuple[str, int]] = {}
        for s in sec_entries:
            k = (s.fonte, s.anexo_codigo, s.secao_codigo)
            if k not in sec_by_key or s.ordem_exibicao < sec_by_key[k][1]:
                sec_by_key[k] = (s.secao_nome, s.ordem_exibicao)
        cur.executemany(
            """
            INSERT INTO gold.d_secao (fonte, anexo_codigo, secao_codigo, secao_nome, ordem_exibicao)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (fonte, anexo_codigo, secao_codigo) DO UPDATE SET
                secao_nome = EXCLUDED.secao_nome,
                ordem_exibicao = EXCLUDED.ordem_exibicao;
            """,
            [
                (f, a, sc, sn, ord_ex)
                for (f, a, sc), (sn, ord_ex) in sorted(sec_by_key.items())
            ],
        )

        # 6. gold.d_fonte_recurso (garantindo sk=0 + todas as fontes de detalhe)
        cur.execute(
            """
            INSERT INTO gold.d_fonte_recurso (
                sk_fonte_recurso, cod_fonte, cod_fonte_padrao, nome_fonte, grupo, vinculada
            ) VALUES (0, '0', '0', 'Não se aplica', NULL, 0)
            ON CONFLICT (sk_fonte_recurso) DO UPDATE SET
                cod_fonte = EXCLUDED.cod_fonte,
                cod_fonte_padrao = EXCLUDED.cod_fonte_padrao,
                nome_fonte = EXCLUDED.nome_fonte,
                grupo = EXCLUDED.grupo,
                vinculada = EXCLUDED.vinculada;
            """
        )
        detail_sources = [fr for fr in fr_entries if fr.eh_total_anexo05 == 0 and fr.cod_fonte != "0"]
        cur.executemany(
            """
            INSERT INTO gold.d_fonte_recurso (
                cod_fonte, cod_fonte_padrao, nome_fonte, grupo, vinculada
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cod_fonte) DO UPDATE SET
                cod_fonte_padrao = EXCLUDED.cod_fonte_padrao,
                nome_fonte = EXCLUDED.nome_fonte,
                grupo = EXCLUDED.grupo,
                vinculada = EXCLUDED.vinculada;
            """,
            [
                (fr.cod_fonte, fr.cod_fonte_padrao, fr.nome_fonte, fr.grupo, fr.vinculada)
                for fr in detail_sources
            ],
        )

        # 7. gold.d_limite_lrf
        cur.executemany(
            """
            INSERT INTO gold.d_limite_lrf (
                codigo_limite, descricao, percentual_limite, pct_alerta, pct_prudencial,
                tipo_limite, base_calculo, vigencia_ini, vigencia_fim, base_legal
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (codigo_limite, vigencia_ini) DO UPDATE SET
                descricao = EXCLUDED.descricao,
                percentual_limite = EXCLUDED.percentual_limite,
                pct_alerta = EXCLUDED.pct_alerta,
                pct_prudencial = EXCLUDED.pct_prudencial,
                tipo_limite = EXCLUDED.tipo_limite,
                base_calculo = EXCLUDED.base_calculo,
                vigencia_fim = EXCLUDED.vigencia_fim,
                base_legal = EXCLUDED.base_legal;
            """,
            [
                (
                    lim.codigo_limite,
                    lim.descricao,
                    lim.percentual_limite,
                    lim.pct_alerta,
                    lim.pct_prudencial,
                    lim.tipo_limite,
                    lim.base_calculo,
                    date.fromisoformat(lim.vigencia_ini),
                    date.fromisoformat(lim.vigencia_fim) if lim.vigencia_fim else None,
                    lim.base_legal,
                )
                for lim in lim_entries
            ],
        )

        # 8. gold.d_indicador
        cur.executemany(
            """
            INSERT INTO gold.d_indicador (
                codigo_indicador, nome, descricao, formula_texto, unidade,
                sentido_bom, valor_referencia, fonte_primaria, grupo, camada_calculo, ordem_exibicao
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (codigo_indicador) DO UPDATE SET
                nome = EXCLUDED.nome,
                descricao = EXCLUDED.descricao,
                formula_texto = EXCLUDED.formula_texto,
                unidade = EXCLUDED.unidade,
                sentido_bom = EXCLUDED.sentido_bom,
                valor_referencia = EXCLUDED.valor_referencia,
                fonte_primaria = EXCLUDED.fonte_primaria,
                grupo = EXCLUDED.grupo,
                camada_calculo = EXCLUDED.camada_calculo,
                ordem_exibicao = EXCLUDED.ordem_exibicao;
            """,
            [
                (
                    ind.codigo_indicador,
                    ind.nome,
                    ind.descricao,
                    ind.formula_texto,
                    ind.unidade,
                    ind.sentido_bom,
                    ind.valor_referencia,
                    ind.fonte_primaria,
                    ind.grupo,
                    ind.camada_calculo,
                    ind.ordem_exibicao,
                )
                for ind in ind_entries
            ],
        )

        # 9. gold.d_funcao (sk=0 + funcoes oficiais + pares (cod_funcao, cod_subfuncao) da Silver)
        cur.execute(
            """
            INSERT INTO gold.d_funcao (sk_funcao, cod_funcao, nome_funcao, cod_subfuncao, nome_subfuncao, nivel)
            VALUES (0, '00', 'Não se aplica', '', 'Não se aplica', 'NAO_APLICA')
            ON CONFLICT (sk_funcao) DO UPDATE SET
                cod_funcao = EXCLUDED.cod_funcao,
                nome_funcao = EXCLUDED.nome_funcao,
                cod_subfuncao = EXCLUDED.cod_subfuncao,
                nome_subfuncao = EXCLUDED.nome_subfuncao,
                nivel = EXCLUDED.nivel;
            """
        )
        cur.execute(
            """
            SELECT DISTINCT
                cod_funcao,
                COALESCE(cod_subfuncao, '') AS cod_subfuncao
            FROM silver.siconfi_registro
            WHERE eh_vigente = 1
              AND cod_funcao IS NOT NULL
              AND cod_funcao <> '';
            """
        )
        silver_funcoes = cur.fetchall()
        func_rows_map: dict[tuple[str, str], tuple[str, str | None, str]] = {}
        for f_code, f_name in OFFICIAL_FUNCOES.items():
            func_rows_map[(f_code, "")] = (f_name, None, "FUNCAO")
        for f_code, sf_code in silver_funcoes:
            f_name = OFFICIAL_FUNCOES.get(f_code, f"Função {f_code}")
            func_rows_map.setdefault((f_code, ""), (f_name, None, "FUNCAO"))
            if sf_code:
                sf_name = OFFICIAL_SUBFUNCOES.get(sf_code, f"Subfunção {sf_code}")
                func_rows_map[(f_code, sf_code)] = (f_name, sf_name, "SUBFUNCAO")

        cur.executemany(
            """
            INSERT INTO gold.d_funcao (cod_funcao, nome_funcao, cod_subfuncao, nome_subfuncao, nivel)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cod_funcao, cod_subfuncao) DO UPDATE SET
                nome_funcao = EXCLUDED.nome_funcao,
                nome_subfuncao = EXCLUDED.nome_subfuncao,
                nivel = EXCLUDED.nivel;
            """,
            [
                (fc, fn, sfc, sfn, niv)
                for (fc, sfc), (fn, sfn, niv) in sorted(func_rows_map.items())
            ],
        )

        # 10. gold.d_natureza_despesa (sk=0 + naturezas extraidas da Silver)
        cur.execute(
            """
            INSERT INTO gold.d_natureza_despesa (
                sk_natureza, cod_natureza, nome_natureza, categoria_economica, grupo_despesa
            ) VALUES (0, '0', 'Não se aplica', 'NAO_APLICA', 'Não se aplica')
            ON CONFLICT (sk_natureza) DO UPDATE SET
                cod_natureza = EXCLUDED.cod_natureza,
                nome_natureza = EXCLUDED.nome_natureza,
                categoria_economica = EXCLUDED.categoria_economica,
                grupo_despesa = EXCLUDED.grupo_despesa;
            """
        )
        cur.execute(
            """
            SELECT DISTINCT ON (cod_natureza)
                cod_natureza,
                COALESCE(conta_descricao, cod_natureza) AS desc_nat
            FROM silver.siconfi_registro
            WHERE eh_vigente = 1
              AND cod_natureza IS NOT NULL
              AND cod_natureza <> ''
              AND cod_natureza <> '0'
            ORDER BY cod_natureza, exercicio DESC;
            """
        )
        nat_silver = cur.fetchall()
        nat_params = []
        for cod_nat, desc_nat in nat_silver:
            nome_n, cat_econ, grp_desp = classify_natureza_despesa(cod_nat, desc_nat)
            nat_params.append((cod_nat, nome_n, cat_econ, grp_desp))
        cur.executemany(
            """
            INSERT INTO gold.d_natureza_despesa (
                cod_natureza, nome_natureza, categoria_economica, grupo_despesa
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (cod_natureza) DO UPDATE SET
                nome_natureza = EXCLUDED.nome_natureza,
                categoria_economica = EXCLUDED.categoria_economica,
                grupo_despesa = EXCLUDED.grupo_despesa;
            """,
            nat_params,
        )

        # 11. gold.d_conta (Motor de Plano de Contas Unificado)
        cur.execute(
            """
            SELECT DISTINCT ON (fonte, anexo_codigo, cod_conta)
                fonte,
                anexo_codigo,
                cod_conta,
                COALESCE(conta_descricao, cod_conta) AS descricao
            FROM silver.siconfi_registro
            WHERE eh_vigente = 1
            ORDER BY fonte, anexo_codigo, cod_conta, exercicio DESC;
            """
        )
        silver_accounts = cur.fetchall()
        conta_rows, t03_orphans = build_account_hierarchy_catalog(
            silver_accounts, eq_entries, hier_entries
        )

        cur.executemany(
            """
            INSERT INTO gold.d_conta (
                fonte, anexo_codigo, cod_conta, cod_conta_padrao, descricao,
                cod_conta_pai, nivel, caminho, eh_folha, eh_total,
                grupo_analitico, sinal_semantico, vigencia_ini, vigencia_fim
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (fonte, anexo_codigo, cod_conta, vigencia_ini) DO UPDATE SET
                cod_conta_padrao = EXCLUDED.cod_conta_padrao,
                descricao = EXCLUDED.descricao,
                cod_conta_pai = EXCLUDED.cod_conta_pai,
                nivel = EXCLUDED.nivel,
                caminho = EXCLUDED.caminho,
                eh_folha = EXCLUDED.eh_folha,
                eh_total = EXCLUDED.eh_total,
                grupo_analitico = EXCLUDED.grupo_analitico,
                sinal_semantico = EXCLUDED.sinal_semantico,
                vigencia_fim = EXCLUDED.vigencia_fim;
            """,
            [
                (
                    c.fonte,
                    c.anexo_codigo,
                    c.cod_conta,
                    c.cod_conta_padrao,
                    c.descricao,
                    c.cod_conta_pai,
                    c.nivel,
                    c.caminho,
                    c.eh_folha,
                    c.eh_total,
                    c.grupo_analitico,
                    c.sinal_semantico,
                    c.vigencia_ini,
                    c.vigencia_fim,
                )
                for c in conta_rows
            ],
        )

    conn.commit()
    audit = audit_gold_dimensions(conn)
    return GoldDimsSummary(
        d_calendario=audit.counts["d_calendario"],
        d_ente=audit.counts["d_ente"],
        d_poder=audit.counts["d_poder"],
        d_coluna=audit.counts["d_coluna"],
        d_secao=audit.counts["d_secao"],
        d_fonte_recurso=audit.counts["d_fonte_recurso"],
        d_limite_lrf=audit.counts["d_limite_lrf"],
        d_indicador=audit.counts["d_indicador"],
        d_funcao=audit.counts["d_funcao"],
        d_natureza_despesa=audit.counts["d_natureza_despesa"],
        d_conta=audit.counts["d_conta"],
        t03_contas_sem_hierarquia=t03_orphans,
    )


def audit_gold_dimensions(conn: psycopg.Connection) -> GoldDimsAudit:
    """Executa as verificacoes de integridade das dimensoes Gold (Fase 3)."""
    dim_tables = [
        "d_calendario",
        "d_ente",
        "d_poder",
        "d_coluna",
        "d_secao",
        "d_fonte_recurso",
        "d_limite_lrf",
        "d_indicador",
        "d_funcao",
        "d_natureza_despesa",
        "d_conta",
    ]
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for tbl in dim_tables:
            cur.execute(f"SELECT COUNT(*) FROM gold.{tbl};")
            counts[tbl] = int(cur.fetchone()[0])

        # T14_VIGENCIA no banco
        cur.execute(
            """
            SELECT COUNT(*)
            FROM gold.d_limite_lrf a
            JOIN gold.d_limite_lrf b
              ON a.codigo_limite = b.codigo_limite
             AND a.sk_limite < b.sk_limite
             AND a.vigencia_ini <= COALESCE(b.vigencia_fim, DATE '9999-12-31')
             AND b.vigencia_ini <= COALESCE(a.vigencia_fim, DATE '9999-12-31');
            """
        )
        t14_overlaps = int(cur.fetchone()[0])

        # Violacoes eh_folha = 1 AND eh_total = 1
        cur.execute("SELECT COUNT(*) FROM gold.d_conta WHERE eh_folha = 1 AND eh_total = 1;")
        folha_total_viol = int(cur.fetchone()[0])

        # Violacoes de conta pai marcada como eh_folha = 1 no mesmo (fonte, anexo_codigo)
        cur.execute(
            """
            SELECT COUNT(*)
            FROM gold.d_conta p
            WHERE p.eh_folha = 1
              AND EXISTS (
                  SELECT 1
                  FROM gold.d_conta c
                  WHERE c.fonte = p.fonte
                    AND c.anexo_codigo = p.anexo_codigo
                    AND (c.cod_conta_pai = p.cod_conta OR c.cod_conta_pai = p.cod_conta_padrao)
              );
            """
        )
        parent_folha_viol = int(cur.fetchone()[0])

        # Contas vigentes na Silver sem correspondencia em gold.d_conta
        cur.execute(
            """
            SELECT COUNT(DISTINCT (s.fonte, s.anexo_codigo, s.cod_conta))
            FROM silver.siconfi_registro s
            LEFT JOIN gold.d_conta d
              ON d.fonte = s.fonte
             AND d.anexo_codigo = s.anexo_codigo
             AND d.cod_conta = s.cod_conta
            WHERE s.eh_vigente = 1
              AND d.sk_conta IS NULL;
            """
        )
        missing_silver_accounts = int(cur.fetchone()[0])

        # Grupos analiticos presentes em gold.d_conta
        cur.execute("SELECT DISTINCT grupo_analitico FROM gold.d_conta WHERE grupo_analitico IS NOT NULL;")
        present_grupos = {str(r[0]) for r in cur.fetchall()}

    missing_grupos = sorted(MANDATORY_GRUPOS_ANALITICOS - present_grupos)
    return GoldDimsAudit(
        counts=counts,
        t14_vigencia_overlaps=t14_overlaps,
        folha_and_total_violations=folha_total_viol,
        parent_marked_folha_violations=parent_folha_viol,
        silver_accounts_missing_in_d_conta=missing_silver_accounts,
        missing_grupos_analiticos=missing_grupos,
    )
