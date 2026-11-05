from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from siconfi_etl.config import Settings, get_settings
from siconfi_etl.db import get_connection, init_database
from siconfi_etl.extract.http_client import SiconfiHttpClient
from siconfi_etl.extract.ibge_extractor import extract_ibge_ipca, extract_ibge_populacao
from siconfi_etl.extract.siconfi_extractor import (
    extract_ente_siconfi,
    sync_anexos_catalogo,
    sync_entes,
)
from siconfi_etl.gold.dims_builder import build_gold_dimensions
from siconfi_etl.gold.facts_builder import audit_gold_facts, build_gold_facts_all
from siconfi_etl.quality.suite import QualitySuiteResult, run_quality_suite
from siconfi_etl.silver.builder import build_silver_all
from siconfi_etl.silver.seeds_catalog import generate_all_seeds

if TYPE_CHECKING:
    import psycopg


@dataclass(frozen=True)
class PipelineExecutionResult:
    id_execucao: int
    status: str  # 'SUCESSO' ou 'FALHA'
    linhas_gold: int
    bloqueantes_falhas: int
    alertas_total: int
    observacao: str


def run_pipeline(
    cfg: Settings | None = None,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
    force_refresh: bool = False,
    skip_anexos: bool = False,
    skip_extract: bool = False,
) -> PipelineExecutionResult:
    """
    Executa o pipeline Medallion ponta a ponta (Bronze -> Silver -> Gold Dims -> Gold Facts -> Qualidade)
    com rastreabilidade em gold.etl_controle e fail-fast em testes bloqueantes.
    """
    settings = cfg or get_settings()
    init_database(settings)

    target_entes = entes or settings.lista_entes
    start_year = ano_ini if ano_ini is not None else settings.ano_inicial_extracao
    end_year = ano_fim if ano_fim is not None else settings.ano_final_extracao

    escopo_str = f"Entes={target_entes} | Janela={start_year}-{end_year}"

    # 1. Abre registro de execucao em gold.etl_controle
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gold.etl_controle (inicio, status, escopo, observacao)
                VALUES (now(), 'EM_ANDAMENTO', %s, 'Execucao iniciada via pipeline.run_all')
                RETURNING id_execucao;
                """,
                (escopo_str,),
            )
            id_execucao = int(cur.fetchone()[0])
        conn.commit()

    # 2. Extracao Incremental Bronze (se nao explicitamente pulada)
    if not skip_extract:
        with SiconfiHttpClient(settings) as client:
            with get_connection(settings) as conn:
                sync_entes(client, conn)
                if not skip_anexos:
                    sync_anexos_catalogo(client, conn)
                extract_ibge_ipca(client, conn)
                extract_ibge_populacao(client, conn, target_entes)

                for id_ente in target_entes:
                    extract_ente_siconfi(
                        client,
                        conn,
                        id_ente,
                        ano_ini=start_year,
                        ano_fim=end_year,
                        force_refresh=force_refresh,
                    )

    # 3. Geracao de Seeds e Camada Silver
    generate_all_seeds(overwrite_profundidade=False)
    with get_connection(settings) as conn:
        build_silver_all(conn, target_entes, start_year, end_year)

    # 4. Camada Gold: Dimensoes e Fatos
    with get_connection(settings) as conn:
        build_gold_dimensions(conn, settings)
        build_gold_facts_all(conn, settings, target_entes, start_year, end_year)

    # 5. Suite de Qualidade Contabil (T01 a T19)
    with get_connection(settings) as conn:
        suite_res = run_quality_suite(
            conn,
            id_execucao=id_execucao,
            entes=target_entes,
            ano_ini=start_year,
            ano_fim=end_year,
            persistir=True,
        )

        audit = audit_gold_facts(conn)
        total_linhas_gold = sum(audit.counts.values())

        # 6. Atualizacao de encerramento em gold.etl_controle
        final_status = "SUCESSO" if suite_res.bloqueantes_falhas == 0 else "FALHA"
        obs = (
            f"Concluido com SUCESSO: {total_linhas_gold:,} linhas Gold publicadas, "
            f"{suite_res.alertas_total} alertas contabeis registrados."
            if final_status == "SUCESSO"
            else f"ABORTADO COM FALHA: {suite_res.bloqueantes_falhas} testes bloqueantes falharam."
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE gold.etl_controle
                SET fim = now(),
                    status = %s,
                    linhas_gold = %s,
                    observacao = %s
                WHERE id_execucao = %s;
                """,
                (final_status, total_linhas_gold, obs, id_execucao),
            )
        conn.commit()

    if suite_res.bloqueantes_falhas > 0:
        raise RuntimeError(
            f"Pipeline abortado com falhas bloqueantes (id_execucao={id_execucao}): "
            f"{suite_res.bloqueantes_falhas} testes bloqueantes violados."
        )

    return PipelineExecutionResult(
        id_execucao=id_execucao,
        status=final_status,
        linhas_gold=total_linhas_gold,
        bloqueantes_falhas=suite_res.bloqueantes_falhas,
        alertas_total=suite_res.alertas_total,
        observacao=obs,
    )
