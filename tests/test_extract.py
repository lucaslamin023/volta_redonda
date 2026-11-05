from __future__ import annotations

from decimal import Decimal

from siconfi_etl.extract.http_client import dumps_json_decimal, parse_json_decimal
from siconfi_etl.extract.ibge_extractor import parse_sidra_ipca_rows, parse_sidra_populacao_rows
from siconfi_etl.extract.siconfi_extractor import classify_extrato_item, deduplicate_deliverables


def test_parse_and_dumps_decimal_never_uses_float() -> None:
    raw = '{"valor": 3971382693.83, "taxa": 0.10, "outro": 0.20, "nulo": null}'
    parsed = parse_json_decimal(raw)
    assert isinstance(parsed["valor"], Decimal)
    assert parsed["valor"] == Decimal("3971382693.83")
    assert parsed["taxa"] + parsed["outro"] == Decimal("0.30")
    assert parsed["nulo"] is None

    serialized = dumps_json_decimal(parsed)
    reparsed = parse_json_decimal(serialized)
    assert Decimal(str(reparsed["valor"])) == Decimal("3971382693.83")


def test_classify_and_deduplicate_extrato_items() -> None:
    sample_extrato = [
        {
            "exercicio": 2024,
            "cod_ibge": 3306305,
            "instituicao": "Prefeitura Municipal de Volta Redonda - RJ",
            "entregavel": "Balanço Anual (DCA)",
            "periodo": 1,
            "periodicidade": "A",
            "status_relatorio": "HO",
            "data_status": "2025-04-10T12:00:00Z",
            "tipo_relatorio": "P",
        },
        {
            "exercicio": 2024,
            "cod_ibge": 3306305,
            "instituicao": "Prefeitura Municipal de Volta Redonda - RJ",
            "entregavel": "Balanço Anual (DCA)",
            "periodo": 1,
            "periodicidade": "A",
            "status_relatorio": "RE",
            "data_status": "2025-06-15T18:30:00Z",
            "tipo_relatorio": "P",
        },
        {
            "exercicio": 2024,
            "cod_ibge": 3306305,
            "instituicao": "Câmara de Vereadores de Volta Redonda - RJ",
            "entregavel": "Relatório de Gestão Fiscal",
            "periodo": 3,
            "periodicidade": "Q",
            "status_relatorio": "HO",
            "data_status": "2025-01-28T10:00:00Z",
            "tipo_relatorio": "P",
        },
        {
            "exercicio": 2024,
            "cod_ibge": 3306305,
            "instituicao": "Prefeitura Municipal de Volta Redonda - RJ",
            "entregavel": "MSC Agregada",
            "periodo": 12,
            "periodicidade": "M",
            "status_relatorio": None,
            "data_status": "2025-01-30T10:00:00Z",
            "tipo_relatorio": None,
        },
    ]

    assert classify_extrato_item(sample_extrato[3]) is None  # MSC ignorada
    dedup = deduplicate_deliverables(sample_extrato)
    assert len(dedup) == 2

    dca = next(d for d in dedup if d.fonte == "DCA")
    assert dca.periodo_codigo == 0
    assert dca.co_poder == "CONSOLIDADO"
    assert dca.data_status_str == "2025-06-15T18:30:00Z"  # Retificacao escolhida

    rgf_leg = next(d for d in dedup if d.fonte == "RGF")
    assert rgf_leg.co_poder == "L"
    assert rgf_leg.periodo_codigo == 3
    assert rgf_leg.in_periodicidade_api == "Q"


def test_parse_sidra_ipca_and_populacao() -> None:
    ipca_mock = [
        {"NC": "Nível Territorial (Código)"},
        {"D2C": "2266", "D3C": "202401", "V": "6801.7200000000000"},
        {"D2C": "63", "D3C": "202401", "V": "0.42"},
        {"D2C": "2266", "D3C": "202612", "V": "..."},
    ]
    ipca_rows = parse_sidra_ipca_rows(ipca_mock)
    assert len(ipca_rows) == 1
    assert ipca_rows[0][0] == 202401
    assert ipca_rows[0][1] == "6801.7200000000000"
    assert ipca_rows[0][2] == "0.42"

    pop_mock = [
        {"NC": "Nível Territorial (Código)"},
        {"D1C": "3306305", "D3C": "2022", "V": "261563"},
        {"D1C": "3306305", "D3C": "2023", "V": "..."},
    ]
    pop_rows = parse_sidra_populacao_rows(pop_mock, "IBGE_CENSO_4714")
    assert len(pop_rows) == 1
    assert pop_rows[0][:4] == (3306305, 2022, "IBGE_CENSO_4714", 261563)


def test_bronze_loaded_integrity() -> None:
    from siconfi_etl.config import get_settings
    from siconfi_etl.db import get_connection

    cfg = get_settings()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT id_ente), COUNT(*), SUM(qtd_itens) FROM bronze.demonstrativo_bruto;")
            entes_cnt, entregas_cnt, celulas_sum = cur.fetchone()
            assert entes_cnt == 6
            assert entregas_cnt >= 850
            assert celulas_sum >= 1_000_000

            cur.execute("SELECT COUNT(*) FROM bronze.demonstrativo_bruto WHERE hash_sha256 IS NULL OR hash_sha256 = '';")
            assert cur.fetchone()[0] == 0

            cur.execute("SELECT COUNT(*) FROM bronze.ibge_ipca_bruto;")
            assert cur.fetchone()[0] >= 130

            cur.execute("SELECT COUNT(DISTINCT id_ente) FROM bronze.ibge_populacao_bruto;")
            assert cur.fetchone()[0] == 6

            cur.execute(
                """
                SELECT payload_itens_texto
                FROM bronze.demonstrativo_bruto
                WHERE id_ente = 3306305 AND fonte = 'DCA' AND exercicio = 2024
                LIMIT 1;
                """
            )
            row = cur.fetchone()
            assert row is not None
            items = parse_json_decimal(row[0])
            assert len(items) > 100
            non_null_vals = [Decimal(str(it["valor"])) for it in items if it.get("valor") is not None]
            assert len(non_null_vals) > 50
            assert all(isinstance(v, Decimal) for v in non_null_vals)

