from __future__ import annotations

from datetime import date
from decimal import Decimal
import pytest

from siconfi_etl.config import PROJECT_ROOT
from siconfi_etl.silver.disambiguator import disambiguate_delivery_items
from siconfi_etl.silver.normalizer import (
    compute_data_fim_periodo,
    extract_cod_natureza,
    normalize_anexo_codigo,
    parse_valor_decimal,
    template_coluna_origem,
)
from siconfi_etl.silver.seed_loader import (
    ColunaResolver,
    FonteRecursoResolver,
    load_coluna_map,
    load_conta_equivalencia,
    load_conta_hierarquia,
    load_fonte_recurso_seed,
    load_indicador_seed,
    load_limite_lrf_seed,
    load_profundidade_seed,
    load_secao_map,
)


def test_normalizer_decimal_strictness_and_dates() -> None:
    assert parse_valor_decimal(None) is None
    assert parse_valor_decimal("") is None
    assert parse_valor_decimal("-") is None
    assert parse_valor_decimal(Decimal("1234.567")) == Decimal("1234.57")
    assert parse_valor_decimal("9876543,21") == Decimal("9876543.21")

    with pytest.raises(TypeError):
        parse_valor_decimal(123.45)  # float proibido (Principio #2)
    with pytest.raises(TypeError):
        parse_valor_decimal(True)

    # Ano bissexto 2016 vs ano comum 2015 no 1o bimestre RREO
    assert compute_data_fim_periodo("RREO", 2016, 1, "BIMESTRAL") == date(2016, 2, 29)
    assert compute_data_fim_periodo("RREO", 2015, 1, "BIMESTRAL") == date(2015, 2, 28)
    assert compute_data_fim_periodo("RGF", 2024, 3, "QUADRIMESTRAL") == date(2024, 12, 31)
    assert compute_data_fim_periodo("DCA", 2024, 0, "ANUAL") == date(2024, 12, 31)

    assert template_coluna_origem("Em 31 de Dezembro de 2023 (b)", 2024) == "Em 31 de Dezembro de {EX_ANT} (b)"
    assert template_coluna_origem("31/12/2024", 2024) == "31/12/{EX}"
    assert normalize_anexo_codigo("RREO", "RREO-Anexo 04 - RPPS") == "RREO-04"
    assert extract_cod_natureza("DCA", "DCA-I-D", "DO3.1.90.11.00.00") == "3.1.90.11.00.00"


def test_all_eight_seeds_valid_against_gold_constraints() -> None:
    col_entries = load_coluna_map()
    sec_entries = load_secao_map()
    fr_entries = load_fonte_recurso_seed()
    eq_entries = load_conta_equivalencia()
    hier_entries = load_conta_hierarquia()
    lim_entries = load_limite_lrf_seed()
    ind_entries = load_indicador_seed()
    prof_entries = load_profundidade_seed()

    assert len(col_entries) >= 390
    assert len(sec_entries) >= 60
    assert len(fr_entries) == 64
    assert len(eq_entries) >= 40
    assert len(hier_entries) >= 100
    assert len(lim_entries) == 10
    assert len(ind_entries) == 37
    assert len(prof_entries) >= 20

    # Consistencia global de gold.d_coluna
    valid_tipo = {"FLUXO_PERIODO", "FLUXO_ACUMULADO", "PREVISAO", "ESTOQUE", "PERCENTUAL", "SALDO"}
    valid_adit = {"ADITIVA", "SEMIADITIVA", "NAO_ADITIVA"}
    meta_by_col: dict[str, tuple[str, str, int]] = {}
    for e in col_entries:
        assert e.tipo_medida in valid_tipo
        assert e.aditividade in valid_adit
        prev = meta_by_col.get(e.coluna_padrao)
        cur = (e.tipo_medida, e.aditividade, e.ordem_exibicao)
        if prev is not None:
            assert prev == cur, f"Inconsistencia em {e.coluna_padrao}: {prev} != {cur}"
        meta_by_col[e.coluna_padrao] = cur

    # Unicidade de cod_fonte em gold.d_fonte_recurso para linhas de detalhe
    valid_grupos = {"LIVRE", "SAUDE", "EDUCACAO", "PREVIDENCIA", "OUTRAS_VINCULADAS"}
    seen_cod_fonte: set[str] = set()
    for fr in fr_entries:
        if fr.eh_total_anexo05 == 1:
            assert fr.cod_fonte == "0"
            assert fr.grupo is None
        else:
            assert fr.cod_fonte != "0"
            assert fr.cod_fonte not in seen_cod_fonte
            seen_cod_fonte.add(fr.cod_fonte)
            assert fr.grupo in valid_grupos

    # T10: eh_folha e eh_total nunca ambos 1 em seed_conta_hierarquia.csv
    for h in hier_entries:
        assert not (h.eh_folha == 1 and h.eh_total == 1)
        assert h.sinal_semantico in (-1, 1)

    # CHECK constraints de gold.d_indicador
    valid_unidades = {"PERCENTUAL", "RAZAO", "REAIS", "REAIS_PER_CAPITA"}
    valid_sentidos = {"MAIOR_MELHOR", "MENOR_MELHOR", "FAIXA"}
    for ind in ind_entries:
        assert ind.unidade in valid_unidades
        assert ind.sentido_bom in valid_sentidos
        assert ind.camada_calculo in {"GOLD_MATERIALIZADO", "DAX"}


def test_rreo02_and_rgf05_disambiguation_longitudinal() -> None:
    col_res = ColunaResolver(load_coluna_map())
    fr_res = FonteRecursoResolver(load_fonte_recurso_seed())

    # RREO-02 2016 (sem prefixo FUxx) vs 2024 (com prefixo FU10) devem gerar o mesmo cod_conta!
    items_2016 = [
        {"anexo": "RREO-Anexo 02", "rotulo": "Padrão", "cod_conta": "RREO2TotalDespesas", "conta": "Saúde", "coluna": "DOTAÇÃO INICIAL", "valor": Decimal("100.00")},
        {"anexo": "RREO-Anexo 02", "rotulo": "Padrão", "cod_conta": "RREO2TotalDespesas", "conta": "Administração Geral", "coluna": "DOTAÇÃO INICIAL", "valor": Decimal("30.00")},
        {"anexo": "RREO-Anexo 02", "rotulo": "Padrão", "cod_conta": "RREO2TotalDespesas", "conta": "Atenção Básica", "coluna": "DOTAÇÃO INICIAL", "valor": Decimal("70.00")},
    ]
    items_2024 = [
        {"anexo": "RREO-Anexo 02", "rotulo": "Padrão", "cod_conta": "RREO2TotalDespesas", "conta": "Saúde", "coluna": "DOTAÇÃO INICIAL", "valor": Decimal("200.00")},
        {"anexo": "RREO-Anexo 02", "rotulo": "Padrão", "cod_conta": "RREO2TotalDespesas", "conta": "FU10 - Administração Geral", "coluna": "DOTAÇÃO INICIAL", "valor": Decimal("50.00")},
        {"anexo": "RREO-Anexo 02", "rotulo": "Padrão", "cod_conta": "RREO2TotalDespesas", "conta": "Atenção Básica", "coluna": "DOTAÇÃO INICIAL", "valor": Decimal("150.00")},
    ]
    d16 = disambiguate_delivery_items("RREO", 2016, items_2016, col_res, fr_res)
    d24 = disambiguate_delivery_items("RREO", 2024, items_2024, col_res, fr_res)

    assert [r.cod_conta for r in d16] == [
        "RREO2TotalDespesas::F10",
        "RREO2TotalDespesas::F10.122",
        "RREO2TotalDespesas::F10.301",
    ]
    assert [r.cod_conta for r in d24] == [r.cod_conta for r in d16]
    assert d24[1].cod_funcao == "10" and d24[1].cod_subfuncao == "122"

    # RGF-05 desambiguacao por fonte de recursos vs linha de total
    rgf05_items = [
        {"anexo": "RGF-Anexo 05", "rotulo": "Padrão", "cod_conta": "DisponibilidadeDeCaixaBruta", "conta": "Recursos Não Vinculados de Impostos", "coluna": "DISPONIBILIDADE DE CAIXA BRUTA (a)", "valor": Decimal("500.00")},
        {"anexo": "RGF-Anexo 05", "rotulo": "Padrão", "cod_conta": "DisponibilidadeDeCaixaBruta", "conta": "TOTAL (III) = (I + II)", "coluna": "DISPONIBILIDADE DE CAIXA BRUTA (a)", "valor": Decimal("900.00")},
    ]
    dr5 = disambiguate_delivery_items("RGF", 2024, rgf05_items, col_res, fr_res)
    assert dr5[0].cod_fonte == "1500.00"
    assert dr5[0].cod_conta == "DisponibilidadeDeCaixaBruta::FR_1500.00"
    assert dr5[1].cod_fonte == "0"
    assert dr5[1].cod_conta == "DisponibilidadeDeCaixaBruta::TOT_GERAL_III"


def test_silver_loaded_and_invariants() -> None:
    from siconfi_etl.config import get_settings
    from siconfi_etl.db import get_connection
    from siconfi_etl.silver.builder import audit_silver

    cfg = get_settings()
    with get_connection(cfg) as conn:
        audit = audit_silver(conn)
        assert audit.total_registros >= 1_000_000
        assert audit.registros_vigentes >= 1_000_000
        assert audit.colunas_sem_mapa == 0
        assert audit.secoes_sem_mapa == 0
        assert audit.rgf05_sem_fonte == 0

    report_path = PROJECT_ROOT / "docs" / "relatorio_profiling_3306305.md"
    assert report_path.exists()
    assert report_path.stat().st_size > 2_000
