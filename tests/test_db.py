from __future__ import annotations

import psycopg
import pytest

from siconfi_etl.config import get_settings
from siconfi_etl.db import get_connection, init_database


def test_settings_rate_limit_and_entes() -> None:
    cfg = get_settings()
    assert cfg.siconfi_rate_limit_seconds >= 1.0
    assert 3306305 in cfg.lista_entes
    assert len(cfg.lista_entes) >= 6
    assert cfg.ano_inicial_extracao == 2015


def test_init_db_idempotency_and_no_float_columns() -> None:
    cfg = get_settings()
    first_run = init_database(cfg)
    second_run = init_database(cfg)
    assert first_run == second_run
    assert len(first_run) == 6

    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            # Verifica proibicao absoluta de float / real / double precision / money
            cur.execute(
                """
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema IN ('bronze', 'silver', 'gold', 'bi')
                  AND data_type IN ('real', 'double precision', 'money');
                """
            )
            forbidden = cur.fetchall()
            assert forbidden == [], f"Colunas float/money proibidas encontradas: {forbidden}"

            # Verifica membros padrao (0 = Nao se aplica) e poderes
            cur.execute("SELECT count(*) FROM gold.d_poder;")
            assert cur.fetchone()[0] == 3

            cur.execute("SELECT sk_fonte_recurso FROM gold.d_fonte_recurso WHERE sk_fonte_recurso = 0;")
            assert cur.fetchone() == (0,)

            cur.execute("SELECT sk_funcao FROM gold.d_funcao WHERE sk_funcao = 0;")
            assert cur.fetchone() == (0,)

            cur.execute("SELECT sk_natureza FROM gold.d_natureza_despesa WHERE sk_natureza = 0;")
            assert cur.fetchone() == (0,)


def test_powerbi_ro_security_isolation() -> None:
    cfg = get_settings()
    with get_connection(cfg, readonly_bi=True) as ro_conn:
        with ro_conn.cursor() as cur:
            # Deve conseguir ler gold e bi
            cur.execute("SELECT count(*) FROM gold.d_poder;")
            assert cur.fetchone()[0] == 3

            cur.execute("SELECT count(*) FROM bi.vw_d_poder;")
            assert cur.fetchone()[0] == 3

            # Nao pode ler bronze nem silver
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SELECT count(*) FROM bronze.entes_bruto;")
        ro_conn.rollback()

        with ro_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SELECT count(*) FROM silver.siconfi_registro;")
        ro_conn.rollback()

        # Nao pode escrever em gold
        with ro_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM gold.d_poder;")
        ro_conn.rollback()
