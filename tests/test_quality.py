from __future__ import annotations

import siconfi_etl.quality.suite as q_suite
from siconfi_etl.config import get_settings
from siconfi_etl.db import get_connection
from siconfi_etl.pipeline import run_pipeline


def test_quality_suite_blocking_tests_pass_with_zero_violations() -> None:
    """Valida se todos os 8 testes BLOQUEANTES da suíte passam com zero violações."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            assert q_suite.check_t01_chave_unica(cur) == []
            assert q_suite.check_t02_coluna_sem_mapa(cur) == []
            assert q_suite.check_t10_nulo_zero(cur) == []
            assert q_suite.check_t11_tipos(cur) == []
            assert q_suite.check_t12_fk_orfa(cur) == []
            assert q_suite.check_t14_vigencia(cur) == []
            assert q_suite.check_t15_secao_sem_mapa(cur) == []
            assert q_suite.check_t17_fonte_sem_mapa(cur) == []


def test_quality_suite_full_run_and_persistence() -> None:
    """Executa os 19 testes da suíte e valida persistência de alertas em gold.f_qualidade."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        res = q_suite.run_quality_suite(conn, entes=cfg.lista_entes, persistir=True)

        assert res.total_testes == 19
        assert res.bloqueantes_falhas == 0
        assert res.status == "SUCESSO"

        # Valida que as ocorrências foram gravadas no banco
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM gold.f_qualidade;")
            total_gravado = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM gold.f_qualidade WHERE severidade = 'BLOQUEANTE';")
            bloqueantes_gravados = int(cur.fetchone()[0])

        assert total_gravado >= len(res.ocorrencias)
        assert bloqueantes_gravados == 0


def test_bi_views_existence_and_queryable() -> None:
    """Valida se todas as views semânticas do schema bi estão criadas e respondem a queries."""
    cfg = get_settings()
    bi_views = [
        "d_calendario", "d_ente", "d_poder", "d_coluna", "d_secao", "d_conta",
        "d_funcao", "d_natureza_despesa", "d_fonte_recurso", "d_limite_lrf", "d_indicador",
        "f_rreo", "f_rgf", "f_dca", "f_ipca", "f_populacao", "f_indicador", "f_qualidade", "etl_controle",
    ]
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            for view_name in bi_views:
                cur.execute(f"SELECT count(*) FROM bi.{view_name};")
                cnt = cur.fetchone()[0]
                assert cnt >= 0, f"View bi.{view_name} não respondeu à consulta!"


def test_pipeline_run_all_and_etl_controle() -> None:
    """Valida orquestração unificada run_pipeline com rastreabilidade em gold.etl_controle."""
    cfg = get_settings()
    # Executa pipeline sem repetir extração HTTP externa (usa Bronze já carregada)
    res = run_pipeline(
        cfg=cfg,
        entes=[cfg.ente_principal],
        ano_ini=2023,
        ano_fim=2023,
        skip_extract=True,
    )

    assert res.status == "SUCESSO"
    assert res.linhas_gold > 0
    assert res.bloqueantes_falhas == 0

    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id_execucao, status, linhas_gold, inicio, fim, observacao
                FROM gold.etl_controle
                WHERE id_execucao = %s;
                """,
                (res.id_execucao,),
            )
            row = cur.fetchone()

    assert row is not None
    assert row[1] == "SUCESSO"
    assert row[2] == res.linhas_gold
    assert row[3] is not None
    assert row[4] is not None
    assert "SUCESSO" in row[5]
