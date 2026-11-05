from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from siconfi_etl.silver.disambiguator import disambiguate_delivery_items
from siconfi_etl.silver.normalizer import (
    compute_data_fim_periodo,
    normalize_periodicidade,
    normalize_text,
)
from siconfi_etl.silver.seed_loader import (
    SEEDS_DIR,
    ColunaResolver,
    FonteRecursoResolver,
    load_coluna_map,
    load_fonte_recurso_seed,
    load_secao_map,
)
from siconfi_etl.silver.seeds_contas import enrich_conta_hierarquia_from_silver


@dataclass(frozen=True)
class SilverBuildStats:
    id_ente: int
    entregas_lidas: int
    entregas_vigentes: int
    entregas_retificadas: int
    celulas_inseridas: int
    celulas_vigentes: int


@dataclass(frozen=True)
class SilverAuditSummary:
    total_registros: int
    registros_vigentes: int
    registros_substituidos: int
    registros_versao_incerta: int
    colunas_sem_mapa: int
    secoes_sem_mapa: int
    rgf05_sem_fonte: int
    duplicatas_residuais_dup: int
    amostras_colunas_sem_mapa: list[tuple[str, str, str, int]]
    amostras_secoes_sem_mapa: list[tuple[str, str, str, int]]
    amostras_rgf05_sem_fonte: list[tuple[str, int]]


def _normalize_co_poder(fonte: str, raw_co_poder: str) -> str:
    f_u = normalize_text(fonte).upper()
    if f_u in {"DCA", "RREO"}:
        return "CONSOLIDADO"
    p_u = normalize_text(raw_co_poder).upper()
    if p_u == "L":
        return "L"
    if p_u == "CONSOLIDADO":
        return "CONSOLIDADO"
    return "E"


def _make_registro_id(
    id_entrega_bronze: int,
    anexo_codigo: str,
    rotulo_origem: str,
    cod_conta: str,
    col_effective: str,
) -> str:
    raw = f"{id_entrega_bronze}|{anexo_codigo}|{rotulo_origem}|{cod_conta}|{col_effective}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_naive_ts(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def build_silver_for_ente(
    conn: psycopg.Connection,
    id_ente: int,
    ano_ini: int,
    ano_fim: int,
    coluna_resolver: ColunaResolver,
    fonte_recurso_resolver: FonteRecursoResolver,
) -> SilverBuildStats:
    """
    Processa todas as entregas Bronze de um municipio na janela [ano_ini, ano_fim],
    resolve retificacoes (eh_vigente / versao_incerta), desambigua contas e carrega
    silver.siconfi_registro de forma idempotente e transacional via COPY.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id_entrega_bronze,
                fonte,
                id_ente,
                exercicio,
                periodo_codigo,
                periodicidade,
                co_poder,
                data_status_extrato,
                dt_ingestao
            FROM bronze.demonstrativo_bruto
            WHERE id_ente = %s
              AND exercicio BETWEEN %s AND %s
            ORDER BY exercicio, fonte, periodo_codigo, co_poder, id_entrega_bronze;
            """,
            (id_ente, ano_ini, ano_fim),
        )
        headers = cur.fetchall()

    # Agrupa por particao logica de entrega para ranquear versoes/retificacoes
    by_delivery_slot: dict[tuple[str, int, int, str], list[tuple]] = defaultdict(list)
    for row in headers:
        _, fonte, _, exercicio, periodo_codigo, _, raw_poder, _, _ = row
        co_poder = _normalize_co_poder(fonte, raw_poder)
        by_delivery_slot[(fonte, int(exercicio), int(periodo_codigo), co_poder)].append(row)

    # Mapeia id_entrega_bronze -> (co_poder_norm, eh_vigente, versao_incerta)
    version_meta: dict[int, tuple[str, int, int]] = {}
    entregas_vigentes = 0
    entregas_retificadas = 0

    for (_, _, _, co_poder), slot_rows in by_delivery_slot.items():
        ranked = sorted(
            slot_rows,
            key=lambda r: (
                r[7] is not None,
                r[7] or datetime.min.replace(tzinfo=r[8].tzinfo),
                r[8],
                r[0],
            ),
            reverse=True,
        )
        top_status = ranked[0][7]
        tied_top = len(ranked) > 1 and top_status is not None and ranked[1][7] == top_status
        for idx, r in enumerate(ranked):
            id_ent = int(r[0])
            eh_vig = 1 if idx == 0 else 0
            incerta = 1 if (r[7] is None or tied_top) else 0
            version_meta[id_ent] = (co_poder, eh_vig, incerta)
            if eh_vig == 1:
                entregas_vigentes += 1
            else:
                entregas_retificadas += 1

    # Agrupa entregas por (fonte, exercicio) para carga atomica por exercicio
    by_fonte_ano: dict[tuple[str, int], list[int]] = defaultdict(list)
    for row in headers:
        by_fonte_ano[(row[1], int(row[3]))].append(int(row[0]))

    celulas_inseridas = 0
    celulas_vigentes = 0

    copy_sql = """
        COPY silver.siconfi_registro (
            registro_id,
            fonte,
            id_ente,
            exercicio,
            periodo_codigo,
            periodicidade,
            data_fim_periodo,
            co_poder,
            anexo,
            anexo_codigo,
            rotulo_origem,
            cod_conta_original,
            cod_conta,
            conta_descricao,
            coluna_origem,
            coluna_padrao,
            cod_funcao,
            cod_subfuncao,
            cod_natureza,
            cod_fonte,
            valor,
            populacao,
            data_homologacao,
            versao_incerta,
            derivado,
            eh_vigente
        ) FROM STDIN
    """

    for (fonte, exercicio), delivery_ids in sorted(by_fonte_ano.items()):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id_entrega_bronze,
                    periodo_codigo,
                    periodicidade,
                    data_status_extrato,
                    payload_itens_texto
                FROM bronze.demonstrativo_bruto
                WHERE id_entrega_bronze = ANY(%s)
                ORDER BY id_entrega_bronze;
                """,
                (delivery_ids,),
            )
            payload_rows = cur.fetchall()

            cur.execute(
                """
                DELETE FROM silver.siconfi_registro
                WHERE id_ente = %s AND fonte = %s AND exercicio = %s;
                """,
                (id_ente, fonte, exercicio),
            )

            with cur.copy(copy_sql) as copy:
                for id_ent_raw, per_cod_raw, per_str_raw, dt_status, payload_txt in payload_rows:
                    id_ent = int(id_ent_raw)
                    periodo_codigo = int(per_cod_raw)
                    periodicidade = normalize_periodicidade(fonte, per_str_raw)
                    data_fim = compute_data_fim_periodo(fonte, exercicio, periodo_codigo, periodicidade)
                    co_poder, eh_vigente, versao_incerta = version_meta[id_ent]
                    dt_homolog = _to_naive_ts(dt_status)

                    # Regra absoluta Principio #2: parse_float=Decimal (zero float!)
                    raw_items = json.loads(payload_txt, parse_float=Decimal)
                    disambiguated = disambiguate_delivery_items(
                        fonte=fonte,
                        exercicio=exercicio,
                        raw_items=raw_items,
                        coluna_resolver=coluna_resolver,
                        fonte_recurso_resolver=fonte_recurso_resolver,
                    )

                    for rec in disambiguated:
                        col_eff = rec.coluna_padrao or rec.coluna_origem
                        reg_id = _make_registro_id(
                            id_ent,
                            rec.anexo_codigo,
                            rec.rotulo_origem,
                            rec.cod_conta,
                            col_eff,
                        )
                        copy.write_row(
                            (
                                reg_id,
                                fonte,
                                id_ente,
                                exercicio,
                                periodo_codigo,
                                periodicidade,
                                data_fim,
                                co_poder,
                                rec.anexo,
                                rec.anexo_codigo,
                                rec.rotulo_origem,
                                rec.cod_conta_original,
                                rec.cod_conta,
                                rec.conta_descricao,
                                rec.coluna_origem,
                                rec.coluna_padrao,
                                rec.cod_funcao,
                                rec.cod_subfuncao,
                                rec.cod_natureza,
                                rec.cod_fonte,
                                rec.valor,
                                rec.populacao,
                                dt_homolog,
                                versao_incerta,
                                0,
                                eh_vigente,
                            )
                        )
                        celulas_inseridas += 1
                        if eh_vigente == 1:
                            celulas_vigentes += 1

        conn.commit()

    return SilverBuildStats(
        id_ente=id_ente,
        entregas_lidas=len(headers),
        entregas_vigentes=entregas_vigentes,
        entregas_retificadas=entregas_retificadas,
        celulas_inseridas=celulas_inseridas,
        celulas_vigentes=celulas_vigentes,
    )


def build_silver_all(
    conn: psycopg.Connection,
    entes: list[int],
    ano_ini: int,
    ano_fim: int,
    seeds_dir: Path = SEEDS_DIR,
) -> list[SilverBuildStats]:
    """Executa a transformacao Bronze -> Silver para todos os entes informados e sincroniza hierarquia."""
    col_resolver = ColunaResolver(load_coluna_map(seeds_dir))
    fr_resolver = FonteRecursoResolver(load_fonte_recurso_seed(seeds_dir))

    stats_list: list[SilverBuildStats] = []
    for cod_ente in entes:
        st = build_silver_for_ente(
            conn=conn,
            id_ente=cod_ente,
            ano_ini=ano_ini,
            ano_fim=ano_fim,
            coluna_resolver=col_resolver,
            fonte_recurso_resolver=fr_resolver,
        )
        stats_list.append(st)

    # Sincroniza seed_conta_hierarquia.csv com 100% das contas nao-pontuadas/desambiguadas observadas
    enrich_conta_hierarquia_from_silver(conn, seeds_dir)
    return stats_list


def audit_silver(conn: psycopg.Connection, seeds_dir: Path = SEEDS_DIR) -> SilverAuditSummary:
    """Executa auditoria completa dos invariantes T02, T15, T17 e unicidade na camada Silver."""
    secao_keys = {
        (e.fonte, e.anexo_codigo, e.rotulo_origem)
        for e in load_secao_map(seeds_dir)
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(CASE WHEN eh_vigente = 1 THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN eh_vigente = 0 THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN eh_vigente = 1 AND versao_incerta = 1 THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN eh_vigente = 1 AND coluna_padrao IS NULL THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN eh_vigente = 1 AND anexo_codigo = 'RGF-05' AND cod_fonte IS NULL THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN eh_vigente = 1 AND cod_conta LIKE '%::DUP%' THEN 1 ELSE 0 END), 0)
            FROM silver.siconfi_registro;
            """
        )
        (
            tot,
            vig,
            sub,
            inc,
            col_null,
            rgf05_null,
            dup_cnt,
        ) = cur.fetchone()

        cur.execute(
            """
            SELECT fonte, anexo_codigo, coluna_origem, COUNT(*)
            FROM silver.siconfi_registro
            WHERE eh_vigente = 1 AND coluna_padrao IS NULL
            GROUP BY fonte, anexo_codigo, coluna_origem
            ORDER BY COUNT(*) DESC
            LIMIT 20;
            """
        )
        unmapped_cols = [(r[0], r[1], r[2], int(r[3])) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT fonte, anexo_codigo, rotulo_origem, COUNT(*)
            FROM silver.siconfi_registro
            WHERE eh_vigente = 1
            GROUP BY fonte, anexo_codigo, rotulo_origem;
            """
        )
        all_rotulos = cur.fetchall()

        cur.execute(
            """
            SELECT COALESCE(conta_descricao, '<NULL>'), COUNT(*)
            FROM silver.siconfi_registro
            WHERE eh_vigente = 1 AND anexo_codigo = 'RGF-05' AND cod_fonte IS NULL
            GROUP BY COALESCE(conta_descricao, '<NULL>')
            ORDER BY COUNT(*) DESC
            LIMIT 20;
            """
        )
        unmapped_rgf05 = [(r[0], int(r[1])) for r in cur.fetchall()]

    unmapped_sec_samples: list[tuple[str, str, str, int]] = []
    unmapped_sec_total = 0
    for f, a, rot, cnt in all_rotulos:
        if (f, a, normalize_text(rot)) not in secao_keys:
            c_int = int(cnt)
            unmapped_sec_total += c_int
            unmapped_sec_samples.append((f, a, rot, c_int))

    return SilverAuditSummary(
        total_registros=int(tot),
        registros_vigentes=int(vig),
        registros_substituidos=int(sub),
        registros_versao_incerta=int(inc),
        colunas_sem_mapa=int(col_null),
        secoes_sem_mapa=unmapped_sec_total,
        rgf05_sem_fonte=int(rgf05_null),
        duplicatas_residuais_dup=int(dup_cnt),
        amostras_colunas_sem_mapa=unmapped_cols,
        amostras_secoes_sem_mapa=unmapped_sec_samples[:20],
        amostras_rgf05_sem_fonte=unmapped_rgf05,
    )
