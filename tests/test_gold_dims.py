from __future__ import annotations

from datetime import date
from decimal import Decimal

from siconfi_etl.config import get_settings
from siconfi_etl.db import get_connection
from siconfi_etl.gold.dims_builder import audit_gold_dimensions, build_gold_dimensions
from siconfi_etl.gold.hierarchy import (
    build_account_hierarchy_catalog,
    classify_natureza_despesa,
    generate_calendar_rows,
    validate_limite_lrf_vigencia,
)
from siconfi_etl.silver.seed_loader import (
    LimiteLrfSeedEntry,
    load_conta_equivalencia,
    load_conta_hierarquia,
    load_limite_lrf_seed,
)


def test_calendar_generation_and_fiscal_flags() -> None:
    rows = generate_calendar_rows(2014, 2027)
    assert len(rows) == 5113  # 2014..2027 (inclui bissextos 2016, 2020, 2024)
    by_sk = {r.sk_data: r for r in rows}

    # Ano bissexto 2016: 28/02 nao encerra 1o bimestre; 29/02 encerra
    assert by_sk[20160228].eh_fim_bimestre == 0
    assert by_sk[20160229].eh_fim_bimestre == 1
    assert by_sk[20160229].label_periodo_rreo == "1º Bim/2016"

    # Ano comum 2015: 28/02 encerra 1o bimestre
    assert by_sk[20150228].eh_fim_bimestre == 1

    # Fechamento anual 31/12/2024
    dec31 = by_sk[20241231]
    assert dec31.eh_fim_bimestre == 1
    assert dec31.eh_fim_quadrimestre == 1
    assert dec31.eh_fim_semestre == 1
    assert dec31.eh_fim_exercicio == 1
    assert dec31.label_periodo_rreo == "6º Bim/2024"
    assert dec31.label_periodo_rgf == "3º Quad/2024"


def test_natureza_despesa_and_limite_lrf_vigencia() -> None:
    nome1, cat1, grp1 = classify_natureza_despesa(
        "3.1.90.11.00.00", "3.1.90.11.00.00 - Vencimentos e Vantagens Fixas"
    )
    assert nome1 == "Vencimentos e Vantagens Fixas"
    assert cat1 == "CORRENTE"
    assert grp1 == "1 - Pessoal e Encargos Sociais"

    _, cat2, grp2 = classify_natureza_despesa("4.4.90.51.00.00", "Obras e Instalações")
    assert cat2 == "CAPITAL"
    assert grp2 == "4 - Investimentos"

    _, cat3, _ = classify_natureza_despesa("3.1.91.13.00.00", "Obrigações Patronais Intra")
    assert cat3 == "INTRA"

    # T14_VIGENCIA sobre seed real
    lim_entries = load_limite_lrf_seed()
    assert validate_limite_lrf_vigencia(lim_entries) == []

    # Simulacao de sobreposicao invalida deve acusar erro T14
    overlapping = [
        LimiteLrfSeedEntry(
            codigo_limite="DCL_RCL",
            descricao="Teste 1",
            percentual_limite=Decimal("120.0"),
            pct_alerta=Decimal("108.0"),
            pct_prudencial=None,
            tipo_limite="MAXIMO",
            base_calculo="RCL",
            vigencia_ini="2015-01-01",
            vigencia_fim="2022-12-31",
            base_legal="Teste",
        ),
        LimiteLrfSeedEntry(
            codigo_limite="DCL_RCL",
            descricao="Teste 2",
            percentual_limite=Decimal("120.0"),
            pct_alerta=Decimal("108.0"),
            pct_prudencial=None,
            tipo_limite="MAXIMO",
            base_calculo="RCL",
            vigencia_ini="2020-01-01",
            vigencia_fim=None,
            base_legal="Teste",
        ),
    ]
    assert len(validate_limite_lrf_vigencia(overlapping)) == 1


def test_dotted_and_hybrid_account_hierarchy_engine() -> None:
    eq_entries = load_conta_equivalencia()
    hier_entries = load_conta_hierarquia()

    sample_silver = [
        ("DCA", "DCA-I-AB", "P1.0.0.0.0.00.00", "Ativo"),
        ("DCA", "DCA-I-AB", "P1.1.0.0.0.00.00", "Ativo Circulante"),
        ("DCA", "DCA-I-AB", "P1.1.1.0.0.00.00", "Caixa e Equivalentes de Caixa"),
        ("DCA", "DCA-I-AB", "P1.1.1.1.1.00.00", "Caixa e Equivalentes - Consolidação"),
        ("DCA", "DCA-I-C", "RO1.1.1.2.02.0.0", "IPTU 2016"),
    ]
    rows, orphans = build_account_hierarchy_catalog(sample_silver, eq_entries, hier_entries)
    assert orphans == 0
    by_key = {(r.fonte, r.anexo_codigo, r.cod_conta): r for r in rows}

    # P1.1.1.0.0.00.00 tem filho (P1.1.1.1.1.00.00), logo deve ser eh_total=1 e eh_folha=0
    caixa_sub = by_key[("DCA", "DCA-I-AB", "P1.1.1.0.0.00.00")]
    assert caixa_sub.eh_total == 1
    assert caixa_sub.eh_folha == 0
    assert caixa_sub.grupo_analitico == "CAIXA_EQUIVALENTES"

    # P1.1.1.1.1.00.00 nao tem filhos na amostra, logo e folha
    caixa_leaf = by_key[("DCA", "DCA-I-AB", "P1.1.1.1.1.00.00")]
    assert caixa_leaf.eh_folha == 1
    assert caixa_leaf.eh_total == 0
    assert caixa_leaf.cod_conta_pai == "P1.1.1.0.0.00.00"
    assert (
        caixa_leaf.caminho
        == "P1.0.0.0.0.00.00 > P1.1.0.0.0.00.00 > P1.1.1.0.0.00.00 > P1.1.1.1.1.00.00"
    )

    # Equivalencia intertemporal em DCA-I-C
    iptu_2016 = by_key[("DCA", "DCA-I-C", "RO1.1.1.2.02.0.0")]
    assert iptu_2016.cod_conta_padrao == "RO1.1.1.2.50.0.0"
    assert iptu_2016.grupo_analitico == "RECEITA_PROPRIA"


def test_gold_dimensions_loaded_idempotent_and_invariants() -> None:
    cfg = get_settings()
    with get_connection(cfg) as conn:
        first_summary = build_gold_dimensions(conn, cfg)
        second_summary = build_gold_dimensions(conn, cfg)
        audit = audit_gold_dimensions(conn)

    # Idempotencia estrita entre duas execucoes consecutivas
    assert first_summary == second_summary

    assert audit.counts["d_calendario"] == 5113
    assert audit.counts["d_ente"] == 6
    assert audit.counts["d_poder"] == 3
    assert audit.counts["d_coluna"] >= 35
    assert audit.counts["d_secao"] >= 40
    assert audit.counts["d_fonte_recurso"] == 50  # 1 (sk=0) + 49 fontes de detalhe
    assert audit.counts["d_limite_lrf"] == 10
    assert audit.counts["d_indicador"] == 37
    assert audit.counts["d_funcao"] >= 100
    assert audit.counts["d_natureza_despesa"] >= 140
    assert audit.counts["d_conta"] >= 3000

    # Critérios de aceite da Fase 3
    assert first_summary.t03_contas_sem_hierarquia == 0
    assert audit.t14_vigencia_overlaps == 0
    assert audit.folha_and_total_violations == 0
    assert audit.parent_marked_folha_violations == 0
    assert audit.silver_accounts_missing_in_d_conta == 0
    assert audit.missing_grupos_analiticos == []
