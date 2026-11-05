from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import psycopg
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from siconfi_etl.extract.http_client import (
    dumps_json_decimal,
    log_http_request,
    parse_json_decimal,
)


SIDRA_BASE_URL = "https://apisidra.ibge.gov.br/values"


def _is_valid_decimal_text(value: str | None) -> bool:
    if value is None:
        return False
    cleaned = value.strip().replace(",", ".")
    if cleaned in ("", "...", "-", "X", ".."):
        return False
    try:
        Decimal(cleaned)
        return True
    except InvalidOperation:
        return False


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError)),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _sidra_get(client: httpx.Client, url: str) -> httpx.Response:
    resp = client.get(url, timeout=45.0)
    resp.raise_for_status()
    return resp


def parse_sidra_ipca_rows(data: list[dict[str, Any]]) -> list[tuple[int, str, str | None, str]]:
    """Converte resposta JSON da Tabela 1737 SIDRA (var 2266 e 63) em tuplas por ano_mes."""
    by_month: dict[int, dict[str, Any]] = {}
    for row in data[1:]:  # linha 0 e cabecalho descritivo do SIDRA
        ano_mes_raw = str(row.get("D3C") or "").strip()
        var_code = str(row.get("D2C") or "").strip()
        val_raw = str(row.get("V") or "").strip()

        if not (ano_mes_raw.isdigit() and len(ano_mes_raw) == 6):
            continue
        if not _is_valid_decimal_text(val_raw):
            continue

        ano_mes = int(ano_mes_raw)
        entry = by_month.setdefault(ano_mes, {"raw_rows": []})
        entry["raw_rows"].append(row)
        if var_code == "2266":
            entry["indice"] = val_raw.replace(",", ".")
        elif var_code == "63":
            entry["variacao"] = val_raw.replace(",", ".")

    result: list[tuple[int, str, str | None, str]] = []
    for ano_mes in sorted(by_month.keys()):
        entry = by_month[ano_mes]
        if "indice" not in entry:
            continue
        result.append(
            (
                ano_mes,
                entry["indice"],
                entry.get("variacao"),
                dumps_json_decimal(entry["raw_rows"]),
            )
        )
    return result


def parse_sidra_populacao_rows(
    data: list[dict[str, Any]],
    fonte_label: str,
) -> list[tuple[int, int, str, int, str]]:
    """Converte resposta JSON das Tabelas 6579 / 4714 SIDRA em tuplas (id_ente, exercicio, fonte, pop, payload)."""
    rows: list[tuple[int, int, str, int, str]] = []
    for row in data[1:]:
        cod_mun = str(row.get("D1C") or "").strip()
        ano_str = str(row.get("D3C") or "").strip()
        val_str = str(row.get("V") or "").strip()

        if not (cod_mun.isdigit() and ano_str.isdigit() and val_str.isdigit()):
            continue
        pop = int(val_str)
        if pop <= 0:
            continue
        rows.append(
            (
                int(cod_mun),
                int(ano_str),
                fonte_label,
                pop,
                dumps_json_decimal(row),
            )
        )
    return rows


def extract_ibge_ipca(conn: psycopg.Connection, ano_ini: int, ano_fim: int) -> int:
    """Extrai serie mensal do IPCA (Numero-indice 2266 e Variacao mensal 63) na Tabela 1737 SIDRA."""
    periodo_ini = f"{ano_ini - 1}12"
    periodo_fim = f"{ano_fim}12"
    url = f"{SIDRA_BASE_URL}/t/1737/n1/all/v/2266,63/p/{periodo_ini}-{periodo_fim}"

    with httpx.Client(follow_redirects=True) as client:
        resp = _sidra_get(client, url)

    parsed_json = parse_json_decimal(resp.text)
    items = parsed_json if isinstance(parsed_json, list) else []
    log_http_request(
        conn=conn,
        endpoint="ibge_sidra/t1737_ipca",
        params={"periodo": f"{periodo_ini}-{periodo_fim}"},
        url_chamada=str(resp.url),
        status_http=resp.status_code,
        qtd_itens=max(0, len(items) - 1),
        payload_texto=resp.text,
    )

    rows = parse_sidra_ipca_rows(items)
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bronze.ibge_ipca_bruto (
                ano_mes, indice_texto, variacao_mensal_texto, payload_texto, dt_ingestao
            )
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (ano_mes) DO UPDATE SET
                indice_texto = EXCLUDED.indice_texto,
                variacao_mensal_texto = EXCLUDED.variacao_mensal_texto,
                payload_texto = EXCLUDED.payload_texto,
                dt_ingestao = now();
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def extract_ibge_populacao(conn: psycopg.Connection, entes: list[int]) -> int:
    """Extrai serie historica de populacao municipal (Estimativas Tab. 6579 + Censo Tab. 4714)."""
    entes_csv = ",".join(str(e) for e in entes)
    sources = [
        ("IBGE_ESTIMATIVA_6579", f"{SIDRA_BASE_URL}/t/6579/n6/{entes_csv}/v/9324/p/all"),
        ("IBGE_CENSO_4714", f"{SIDRA_BASE_URL}/t/4714/n6/{entes_csv}/v/93/p/all"),
    ]

    total_saved = 0
    with httpx.Client(follow_redirects=True) as client:
        for fonte_label, url in sources:
            resp = _sidra_get(client, url)
            parsed_json = parse_json_decimal(resp.text)
            items = parsed_json if isinstance(parsed_json, list) else []

            log_http_request(
                conn=conn,
                endpoint=f"ibge_sidra/{fonte_label.lower()}",
                params={"entes": entes_csv},
                url_chamada=str(resp.url),
                status_http=resp.status_code,
                qtd_itens=max(0, len(items) - 1),
                payload_texto=resp.text,
            )

            rows = parse_sidra_populacao_rows(items, fonte_label)
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO bronze.ibge_populacao_bruto (
                        id_ente, exercicio, fonte_ibge, populacao, payload_texto, dt_ingestao
                    )
                    VALUES (%s, %s, %s, %s, %s, now())
                    ON CONFLICT (id_ente, exercicio, fonte_ibge) DO UPDATE SET
                        populacao = EXCLUDED.populacao,
                        payload_texto = EXCLUDED.payload_texto,
                        dt_ingestao = now();
                    """,
                    rows,
                )
            conn.commit()
            total_saved += len(rows)

    return total_saved
