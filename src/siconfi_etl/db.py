from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg import sql

from siconfi_etl.config import PROJECT_ROOT, Settings, get_settings


SQL_DIR = PROJECT_ROOT / "sql"


@contextmanager
def get_connection(settings: Settings | None = None, readonly_bi: bool = False) -> Iterator[psycopg.Connection]:
    """Abre conexao PostgreSQL com suporte nativo a Decimal e timezone configurado."""
    cfg = settings or get_settings()
    conninfo = cfg.powerbi_ro_conninfo if readonly_bi else cfg.admin_conninfo
    conn = psycopg.connect(conninfo, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


def init_database(settings: Settings | None = None) -> list[str]:
    """Executa os scripts DDL (01 a 06) de forma idempotente e configura powerbi_ro."""
    cfg = settings or get_settings()
    sql_files = sorted(SQL_DIR.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"Nenhum script SQL encontrado em {SQL_DIR}")

    executed: list[str] = []
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            for sql_file in sql_files:
                script_text = sql_file.read_text(encoding="utf-8")
                cur.execute(script_text)
                executed.append(sql_file.name)

            # Configura login, senha e permissao de conexao para o usuario do Power BI
            ro_ident = sql.Identifier(cfg.powerbi_ro_user)
            db_ident = sql.Identifier(cfg.postgres_db)

            cur.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    ro_ident,
                    sql.Literal(cfg.powerbi_ro_password),
                )
            )
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db_ident, ro_ident))
            cur.execute(sql.SQL("REVOKE ALL ON SCHEMA bronze, silver FROM {}").format(ro_ident))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA gold, bi TO {}").format(ro_ident))
            cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA gold TO {}").format(ro_ident))
            cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA bi TO {}").format(ro_ident))

        conn.commit()
    return executed
