from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from rich.console import Console

from siconfi_etl.extract.http_client import (
    SiconfiHttpClient,
    dumps_json_decimal,
    sha256_text,
)

console = Console()


def _strip_accents_lower(text: str | None) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return ascii_str.lower().strip()


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


@dataclass(frozen=True)
class DeliverableTarget:
    fonte: str  # DCA | RREO | RGF
    id_ente: int
    exercicio: int
    periodo_codigo: int
    periodicidade: str  # ANUAL | BIMESTRAL | QUADRIMESTRAL | SEMESTRAL
    in_periodicidade_api: str  # A | B | Q | S
    co_tipo_demonstrativo: str
    co_poder: str  # E | L | CONSOLIDADO
    data_status: datetime | None
    data_status_str: str


def classify_extrato_item(item: dict[str, Any]) -> DeliverableTarget | None:
    """Converte um item do /extrato_entregas em uma especificacao de coleta de demonstrativo."""
    entregavel_norm = _strip_accents_lower(str(item.get("entregavel") or ""))
    inst_norm = _strip_accents_lower(str(item.get("instituicao") or ""))
    periodicidade_raw = str(item.get("periodicidade") or "").strip().upper()
    tipo_rel = str(item.get("tipo_relatorio") or "P").strip().upper()
    id_ente = int(item["cod_ibge"])
    exercicio = int(item["exercicio"])
    periodo_raw = int(item.get("periodo") or 0)
    data_status_str = str(item.get("data_status") or "").strip()
    data_status_dt = _parse_iso_ts(data_status_str)

    # Ignora matrizes MSC (fora do escopo v1 conforme arquitetura)
    if "msc" in entregavel_norm or "matriz" in entregavel_norm:
        return None

    if "dca" in entregavel_norm or "balanco anual" in entregavel_norm:
        return DeliverableTarget(
            fonte="DCA",
            id_ente=id_ente,
            exercicio=exercicio,
            periodo_codigo=0,
            periodicidade="ANUAL",
            in_periodicidade_api="A",
            co_tipo_demonstrativo="DCA",
            co_poder="CONSOLIDADO",
            data_status=data_status_dt,
            data_status_str=data_status_str,
        )

    if "resumido" in entregavel_norm or "rreo" in entregavel_norm:
        co_tipo = "RREO Simplificado" if tipo_rel == "S" else "RREO"
        return DeliverableTarget(
            fonte="RREO",
            id_ente=id_ente,
            exercicio=exercicio,
            periodo_codigo=periodo_raw,
            periodicidade="BIMESTRAL",
            in_periodicidade_api="B",
            co_tipo_demonstrativo=co_tipo,
            co_poder="CONSOLIDADO",
            data_status=data_status_dt,
            data_status_str=data_status_str,
        )

    if "gestao fiscal" in entregavel_norm or "rgf" in entregavel_norm:
        # Identifica poder pela instituicao declarante no extrato municipal
        if any(tok in inst_norm for tok in ("camara", "vereador", "legislat")):
            co_poder = "L"
        elif any(tok in inst_norm for tok in ("tribunal", "judici")):
            return None
        else:
            co_poder = "E"

        is_semestral = periodicidade_raw == "S"
        co_tipo = "RGF Simplificado" if (tipo_rel == "S" or is_semestral) else "RGF"
        return DeliverableTarget(
            fonte="RGF",
            id_ente=id_ente,
            exercicio=exercicio,
            periodo_codigo=periodo_raw,
            periodicidade="SEMESTRAL" if is_semestral else "QUADRIMESTRAL",
            in_periodicidade_api="S" if is_semestral else "Q",
            co_tipo_demonstrativo=co_tipo,
            co_poder=co_poder,
            data_status=data_status_dt,
            data_status_str=data_status_str,
        )

    return None


def deduplicate_deliverables(extrato_items: list[dict[str, Any]]) -> list[DeliverableTarget]:
    """Agrupa entregas/retificacoes mantendo apenas o alvo mais recente por particao."""
    best: dict[tuple[str, int, int, int, str], DeliverableTarget] = {}
    for item in extrato_items:
        target = classify_extrato_item(item)
        if target is None:
            continue
        key = (target.fonte, target.id_ente, target.exercicio, target.periodo_codigo, target.co_poder)
        existing = best.get(key)
        if existing is None:
            best[key] = target
        else:
            # Escolhe maior data_status
            if target.data_status and (existing.data_status is None or target.data_status > existing.data_status):
                best[key] = target
    return sorted(
        best.values(),
        key=lambda t: (t.exercicio, t.fonte, t.periodo_codigo, t.co_poder),
    )


def sync_entes(
    conn: psycopg.Connection,
    client: SiconfiHttpClient,
    force_refresh: bool = False,
) -> int:
    """Sincroniza cadastro nacional /entes na camada Bronze."""
    if not force_refresh:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM bronze.entes_bruto;")
            existing_count = cur.fetchone()[0]
            if existing_count >= 5500:
                return existing_count

    items, _ = client.fetch_all_pages(conn, "/entes", timeout=60.0)
    rows = []
    for item in items:
        item_txt = dumps_json_decimal(item)
        rows.append(
            (
                int(item["cod_ibge"]),
                str(item.get("ente") or ""),
                str(item.get("uf") or "")[:2] or None,
                str(item.get("esfera") or "")[:1] or None,
                str(item.get("regiao") or "")[:2] or None,
                int(item["capital"]) if item.get("capital") is not None else None,
                int(item["an_exercicio"]) if item.get("an_exercicio") is not None else None,
                int(item["populacao"]) if item.get("populacao") is not None else None,
                str(item["co_cnpj"]) if item.get("co_cnpj") is not None else None,
                item_txt,
                sha256_text(item_txt),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bronze.entes_bruto (
                cod_ibge, ente, uf, esfera, regiao, capital,
                an_exercicio, populacao, co_cnpj, payload_texto, hash_sha256, dt_ingestao
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (cod_ibge) DO UPDATE SET
                ente = EXCLUDED.ente,
                uf = EXCLUDED.uf,
                esfera = EXCLUDED.esfera,
                regiao = EXCLUDED.regiao,
                capital = EXCLUDED.capital,
                an_exercicio = EXCLUDED.an_exercicio,
                populacao = EXCLUDED.populacao,
                co_cnpj = EXCLUDED.co_cnpj,
                payload_texto = EXCLUDED.payload_texto,
                hash_sha256 = EXCLUDED.hash_sha256,
                dt_ingestao = now();
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def sync_anexos_catalogo(
    conn: psycopg.Connection,
    client: SiconfiHttpClient,
    force_refresh: bool = False,
) -> int:
    """Tenta sincronizar /anexos-relatorios com tolerancia a lentidao da view ORDS da STN."""
    if not force_refresh:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM bronze.anexos_bruto;")
            cnt = cur.fetchone()[0]
            if cnt > 0:
                return cnt

    try:
        items, _ = client.fetch_all_pages(
            conn,
            "/anexos-relatorios",
            timeout=90.0,
            max_attempts_override=1,
        )
    except Exception as exc:
        console.print(
            f"[yellow]Aviso nao-bloqueante:[/yellow] /anexos-relatorios indisponivel/timeout na STN ({exc}). "
            "Prosseguindo pois as coletas /dca, /rreo e /rgf buscam todos os anexos sem filtro."
        )
        return 0

    rows = [
        (
            str(it.get("esfera") or ""),
            str(it.get("demonstrativo") or ""),
            str(it.get("anexo") or ""),
            dumps_json_decimal(it),
        )
        for it in items
        if it.get("esfera") and it.get("demonstrativo") and it.get("anexo")
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bronze.anexos_bruto (esfera, demonstrativo, anexo, payload_texto, dt_ingestao)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (esfera, demonstrativo, anexo) DO UPDATE SET
                payload_texto = EXCLUDED.payload_texto,
                dt_ingestao = now();
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def _upsert_extrato_items(conn: psycopg.Connection, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    rows = []
    for it in items:
        txt = dumps_json_decimal(it)
        ds_str = str(it.get("data_status") or "").strip()
        rows.append(
            (
                int(it["cod_ibge"]),
                int(it["exercicio"]),
                str(it.get("entregavel") or ""),
                int(it.get("periodo") or 0),
                str(it.get("periodicidade") or "").strip(),
                str(it.get("status_relatorio") or "").strip(),
                _parse_iso_ts(ds_str),
                ds_str,
                str(it["forma_envio"]) if it.get("forma_envio") is not None else None,
                str(it["tipo_relatorio"]) if it.get("tipo_relatorio") is not None else None,
                str(it.get("instituicao") or "").strip(),
                int(it["populacao"]) if it.get("populacao") is not None else None,
                txt,
                sha256_text(txt),
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bronze.extrato_entregas_bruto (
                cod_ibge, exercicio, entregavel, periodo, periodicidade,
                status_relatorio, data_status, data_status_chave, forma_envio,
                tipo_relatorio, instituicao, populacao, payload_texto, hash_sha256
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                cod_ibge, exercicio, entregavel, periodo,
                periodicidade, instituicao, status_relatorio, data_status_chave
            ) DO UPDATE SET
                populacao = EXCLUDED.populacao,
                payload_texto = EXCLUDED.payload_texto,
                hash_sha256 = EXCLUDED.hash_sha256,
                dt_ingestao = now();
            """,
            rows,
        )
    conn.commit()


def _is_deliverable_up_to_date(conn: psycopg.Connection, target: DeliverableTarget) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(data_status_extrato), COUNT(*)
            FROM bronze.demonstrativo_bruto
            WHERE fonte = %s
              AND id_ente = %s
              AND exercicio = %s
              AND periodo_codigo = %s
              AND co_poder = %s;
            """,
            (
                target.fonte,
                target.id_ente,
                target.exercicio,
                target.periodo_codigo,
                target.co_poder,
            ),
        )
        max_dt, cnt = cur.fetchone()

    if not cnt:
        return False
    if target.data_status is None:
        return True
    if max_dt is None:
        return False
    return max_dt >= target.data_status


def _fetch_target_demonstrativo(
    conn: psycopg.Connection,
    client: SiconfiHttpClient,
    target: DeliverableTarget,
) -> tuple[list[dict[str, Any]], str]:
    if target.fonte == "DCA":
        params: dict[str, Any] = {
            "an_exercicio": target.exercicio,
            "id_ente": target.id_ente,
        }
        return client.fetch_all_pages(conn, "/dca", params=params)

    if target.fonte == "RREO":
        params = {
            "an_exercicio": target.exercicio,
            "nr_periodo": target.periodo_codigo,
            "co_tipo_demonstrativo": target.co_tipo_demonstrativo,
            "id_ente": target.id_ente,
        }
        return client.fetch_all_pages(conn, "/rreo", params=params)

    if target.fonte == "RGF":
        params = {
            "an_exercicio": target.exercicio,
            "in_periodicidade": target.in_periodicidade_api,
            "nr_periodo": target.periodo_codigo,
            "co_tipo_demonstrativo": target.co_tipo_demonstrativo,
            "co_poder": target.co_poder,
            "id_ente": target.id_ente,
        }
        return client.fetch_all_pages(conn, "/rgf", params=params)

    raise ValueError(f"Fonte desconhecida: {target.fonte}")


@dataclass
class ExtractionStats:
    id_ente: int
    extratos_lidos: int = 0
    alvos_identificados: int = 0
    demonstrativos_baixados: int = 0
    demonstrativos_em_cache: int = 0
    registros_celulas: int = 0


def extract_ente_siconfi(
    conn: psycopg.Connection,
    client: SiconfiHttpClient,
    id_ente: int,
    ano_ini: int,
    ano_fim: int,
    force_refresh: bool = False,
) -> ExtractionStats:
    """Executa extracao incremental guiada por /extrato_entregas para um municipio."""
    stats = ExtractionStats(id_ente=id_ente)

    for ano in range(ano_ini, ano_fim + 1):
        extrato_items, _ = client.fetch_all_pages(
            conn,
            "/extrato_entregas",
            params={"id_ente": id_ente, "an_referencia": ano},
        )
        stats.extratos_lidos += len(extrato_items)
        _upsert_extrato_items(conn, extrato_items)

        targets = deduplicate_deliverables(extrato_items)
        stats.alvos_identificados += len(targets)
        ano_baixados = 0
        ano_cache = 0
        ano_celulas = 0

        for target in targets:
            if not force_refresh and _is_deliverable_up_to_date(conn, target):
                stats.demonstrativos_em_cache += 1
                ano_cache += 1
                continue

            items, digest = _fetch_target_demonstrativo(conn, client, target)
            payload_txt = dumps_json_decimal(items)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bronze.demonstrativo_bruto (
                        fonte, id_ente, exercicio, periodo_codigo, periodicidade,
                        co_tipo_demonstrativo, co_poder, data_status_extrato,
                        qtd_itens, hash_sha256, payload_itens_texto
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (fonte, id_ente, exercicio, periodo_codigo, co_poder, hash_sha256)
                    DO UPDATE SET
                        data_status_extrato = GREATEST(
                            bronze.demonstrativo_bruto.data_status_extrato,
                            EXCLUDED.data_status_extrato
                        ),
                        dt_ingestao = now();
                    """,
                    (
                        target.fonte,
                        target.id_ente,
                        target.exercicio,
                        target.periodo_codigo,
                        target.periodicidade,
                        target.co_tipo_demonstrativo,
                        target.co_poder,
                        target.data_status,
                        len(items),
                        digest,
                        payload_txt,
                    ),
                )
            conn.commit()
            stats.demonstrativos_baixados += 1
            stats.registros_celulas += len(items)
            ano_baixados += 1
            ano_celulas += len(items)

        print(
            f"    [{id_ente}] Exercicio {ano}: {ano_baixados} baixados, "
            f"{ano_cache} em cache ({ano_celulas:,} celulas)",
            flush=True,
        )

    return stats
