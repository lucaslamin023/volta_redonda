from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from siconfi_etl.config import get_settings
from siconfi_etl.db import get_connection, init_database
from siconfi_etl.extract.http_client import SiconfiHttpClient
from siconfi_etl.extract.ibge_extractor import extract_ibge_ipca, extract_ibge_populacao
from siconfi_etl.extract.siconfi_extractor import (
    extract_ente_siconfi,
    sync_anexos_catalogo,
    sync_entes,
)
from siconfi_etl.gold.dims_builder import audit_gold_dimensions, build_gold_dimensions
from siconfi_etl.gold.facts_builder import audit_gold_facts, build_gold_facts_all
from siconfi_etl.pipeline import run_pipeline
from siconfi_etl.quality.suite import run_quality_suite
from siconfi_etl.silver.builder import audit_silver, build_silver_all
from siconfi_etl.silver.profiler import run_historical_profiling
from siconfi_etl.silver.seeds_catalog import generate_all_seeds

app = typer.Typer(
    name="siconfi-etl",
    help="Pipeline Medallion SICONFI + IBGE -> PostgreSQL -> Power BI.",
    no_args_is_help=True,
)
console = Console()


@app.command("init-db")
def cmd_init_db() -> None:
    """Inicializa ou atualiza de forma idempotente os schemas bronze, silver, gold e bi."""
    cfg = get_settings()
    console.print(
        f"[bold cyan]Inicializando banco[/bold cyan] "
        f"{cfg.postgres_host}:{cfg.postgres_port}/{cfg.postgres_db}..."
    )
    executed = init_database(cfg)
    for filename in executed:
        console.print(f"  [green]OK[/green] {filename}")
    console.print("[bold green]Banco inicializado e permissoes de powerbi_ro aplicadas com sucesso![/bold green]")


@app.command("status-db")
def cmd_status_db() -> None:
    """Exibe contagem de tabelas por schema e valida tipos monetarios/permissoes."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_schema, table_type, count(*)
                FROM information_schema.tables
                WHERE table_schema IN ('bronze', 'silver', 'gold', 'bi')
                GROUP BY table_schema, table_type
                ORDER BY table_schema, table_type;
                """
            )
            rows = cur.fetchall()

    table = Table(title="Inventario do Data Warehouse PostgreSQL")
    table.add_column("Schema", style="cyan")
    table.add_column("Tipo", style="magenta")
    table.add_column("Quantidade", justify="right", style="green")
    for schema_name, table_type, qty in rows:
        table.add_row(str(schema_name), str(table_type), str(qty))
    console.print(table)


@app.command("extract")
def cmd_extract(
    entes: str | None = typer.Option(
        None,
        "--entes",
        help="Lista CSV de codigos IBGE (padrao: ENTES_ESCOPO do .env).",
    ),
    only_principal: bool = typer.Option(
        False,
        "--only-principal",
        help="Extrai apenas o municipio principal (Volta Redonda = 3306305).",
    ),
    ano_ini: int | None = typer.Option(None, "--ano-ini", help="Ano inicial (padrao: ANO_INICIAL_EXTRACAO)."),
    ano_fim: int | None = typer.Option(None, "--ano-fim", help="Ano final (padrao: ANO_FINAL_EXTRACAO)."),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Reconsulta demonstrativos mesmo sem mudanca de data_status no extrato.",
    ),
    skip_anexos: bool = typer.Option(
        False,
        "--skip-anexos",
        help="Pula sincronizacao opcional do catalogo /anexos-relatorios.",
    ),
) -> None:
    """Executa a Fase 1: extracao incremental SICONFI + IBGE SIDRA para a camada Bronze."""
    cfg = get_settings()
    init_database(cfg)

    if only_principal:
        target_entes = [cfg.ente_principal]
    elif entes:
        target_entes = [int(x.strip()) for x in entes.split(",") if x.strip()]
    else:
        target_entes = cfg.lista_entes

    start_year = ano_ini if ano_ini is not None else cfg.ano_inicial_extracao
    end_year = ano_fim if ano_fim is not None else cfg.ano_final_extracao

    console.print(
        f"[bold cyan]Fase 1 - Extracao Bronze[/bold cyan] | "
        f"Entes={target_entes} | Janela={start_year}-{end_year}"
    )

    with get_connection(cfg) as conn:
        console.print("[cyan]1/4 Coletando serie mensal do IPCA (IBGE SIDRA Tab. 1737)...[/cyan]")
        qtd_ipca = extract_ibge_ipca(conn, start_year, end_year)
        console.print(f"  [green]OK[/green] {qtd_ipca} meses de IPCA sincronizados em bronze.ibge_ipca_bruto.")

        console.print("[cyan]2/4 Coletando populacao municipal (IBGE SIDRA Tab. 6579 + Censo 4714)...[/cyan]")
        qtd_pop = extract_ibge_populacao(conn, target_entes)
        console.print(f"  [green]OK[/green] {qtd_pop} registros populacionais em bronze.ibge_populacao_bruto.")

        with SiconfiHttpClient(cfg) as siconfi_client:
            base_url = siconfi_client.resolve_base_url()
            console.print(f"[cyan]3/4 Sincronizando cadastros SICONFI ({base_url})...[/cyan]")
            qtd_entes = sync_entes(conn, siconfi_client, force_refresh=force_refresh)
            console.print(f"  [green]OK[/green] {qtd_entes} entes da federacao em bronze.entes_bruto.")

            if not skip_anexos:
                qtd_anexos = sync_anexos_catalogo(conn, siconfi_client, force_refresh=force_refresh)
                console.print(f"  [green]OK[/green] {qtd_anexos} anexos em bronze.anexos_bruto.")

            console.print("[cyan]4/4 Extraindo Extratos e Demonstrativos (DCA, RREO, RGF)...[/cyan]")
            summary = Table(title=f"Resumo de Extracao SICONFI ({start_year}-{end_year})")
            summary.add_column("IBGE", style="cyan")
            summary.add_column("Extratos", justify="right")
            summary.add_column("Alvos Unicos", justify="right")
            summary.add_column("Baixados Agora", justify="right", style="green")
            summary.add_column("Em Cache (Skip)", justify="right", style="yellow")
            summary.add_column("Linhas Brutas Novas", justify="right", style="magenta")

            for cod_ente in target_entes:
                console.print(f"  -> Processando ente [bold]{cod_ente}[/bold]...")
                st = extract_ente_siconfi(
                    conn=conn,
                    client=siconfi_client,
                    id_ente=cod_ente,
                    ano_ini=start_year,
                    ano_fim=end_year,
                    force_refresh=force_refresh,
                )
                summary.add_row(
                    str(st.id_ente),
                    str(st.extratos_lidos),
                    str(st.alvos_identificados),
                    str(st.demonstrativos_baixados),
                    str(st.demonstrativos_em_cache),
                    str(st.registros_celulas),
                )

            console.print(summary)
            console.print(
                f"[bold green]Extracao concluida![/bold green] "
                f"Total de requisicoes HTTP ao SICONFI nesta execucao: {siconfi_client.request_count}"
            )


@app.command("status-bronze")
def cmd_status_bronze() -> None:
    """Mostra inventario detalhado dos dados ja armazenados na camada Bronze."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.id_ente,
                    COALESCE(e.ente, 'Desconhecido') AS nome_ente,
                    d.fonte,
                    COUNT(*) AS entregas,
                    MIN(d.exercicio) AS min_ano,
                    MAX(d.exercicio) AS max_ano,
                    SUM(d.qtd_itens) AS total_celulas
                FROM bronze.demonstrativo_bruto d
                LEFT JOIN bronze.entes_bruto e ON e.cod_ibge = d.id_ente
                GROUP BY d.id_ente, e.ente, d.fonte
                ORDER BY d.id_ente, d.fonte;
                """
            )
            dem_rows = cur.fetchall()

            cur.execute("SELECT COUNT(*), MIN(ano_mes), MAX(ano_mes) FROM bronze.ibge_ipca_bruto;")
            ipca_cnt, ipca_min, ipca_max = cur.fetchone()

            cur.execute("SELECT COUNT(DISTINCT id_ente), COUNT(*) FROM bronze.ibge_populacao_bruto;")
            pop_entes, pop_rows = cur.fetchone()

    table = Table(title="Camada Bronze - Demonstrativos SICONFI por Municipio")
    table.add_column("IBGE", style="cyan")
    table.add_column("Municipio", style="white")
    table.add_column("Fonte", style="magenta")
    table.add_column("Entregas", justify="right", style="green")
    table.add_column("Janela", justify="center")
    table.add_column("Celulas Brutas", justify="right", style="yellow")

    for id_ente, nome, fonte, entregas, min_ano, max_ano, total_celulas in dem_rows:
        table.add_row(
            str(id_ente),
            str(nome),
            str(fonte),
            str(entregas),
            f"{min_ano}-{max_ano}",
            f"{total_celulas:,}",
        )
    console.print(table)
    console.print(
        f"[cyan]IPCA Bronze:[/cyan] {ipca_cnt} meses ({ipca_min} a {ipca_max}) | "
        f"[cyan]Populacao IBGE Bronze:[/cyan] {pop_rows} linhas em {pop_entes} entes."
    )


@app.command("generate-seeds")
def cmd_generate_seeds(
    overwrite_profundidade: bool = typer.Option(
        False,
        "--overwrite-profundidade",
        help="Reescreve tambem seed_profundidade.csv com baseline padrao.",
    ),
) -> None:
    """Fase 2: Gera e atualiza os 8 arquivos CSV de curadoria em seeds/."""
    counts = generate_all_seeds(overwrite_profundidade=overwrite_profundidade)
    table = Table(title="Arquivos Curados Gerados em seeds/")
    table.add_column("Arquivo CSV", style="cyan")
    table.add_column("Linhas", justify="right", style="green")
    for name, qty in sorted(counts.items()):
        table.add_row(name, str(qty))
    console.print(table)


@app.command("build-silver")
def cmd_build_silver(
    entes: str | None = typer.Option(
        None,
        "--entes",
        help="Lista CSV de codigos IBGE (padrao: ENTES_ESCOPO do .env).",
    ),
    only_principal: bool = typer.Option(
        False,
        "--only-principal",
        help="Processa apenas o municipio principal (Volta Redonda = 3306305).",
    ),
    ano_ini: int | None = typer.Option(None, "--ano-ini", help="Ano inicial."),
    ano_fim: int | None = typer.Option(None, "--ano-fim", help="Ano final."),
) -> None:
    """Fase 2: Executa transformacao Bronze -> Silver com desambiguacao e auditoria."""
    cfg = get_settings()
    init_database(cfg)

    if only_principal:
        target_entes = [cfg.ente_principal]
    elif entes:
        target_entes = [int(x.strip()) for x in entes.split(",") if x.strip()]
    else:
        target_entes = cfg.lista_entes

    start_year = ano_ini if ano_ini is not None else cfg.ano_inicial_extracao
    end_year = ano_fim if ano_fim is not None else cfg.ano_final_extracao

    generate_all_seeds(overwrite_profundidade=False)

    console.print(
        f"[bold cyan]Fase 2 - Transformacao Silver[/bold cyan] | "
        f"Entes={target_entes} | Janela={start_year}-{end_year}"
    )

    with get_connection(cfg) as conn:
        stats_list = build_silver_all(conn, target_entes, start_year, end_year)
        audit = audit_silver(conn)

    table = Table(title="Resumo de Carga Camada Silver")
    table.add_column("IBGE", style="cyan")
    table.add_column("Entregas Lidas", justify="right")
    table.add_column("Vigentes", justify="right", style="green")
    table.add_column("Retificadas", justify="right", style="yellow")
    table.add_column("Celulas Totais", justify="right")
    table.add_column("Celulas Vigentes", justify="right", style="magenta")

    for st in stats_list:
        table.add_row(
            str(st.id_ente),
            str(st.entregas_lidas),
            str(st.entregas_vigentes),
            str(st.entregas_retificadas),
            f"{st.celulas_inseridas:,}",
            f"{st.celulas_vigentes:,}",
        )
    console.print(table)
    console.print(
        f"[bold]Auditoria Silver:[/bold] "
        f"T02(colunas sem mapa)={audit.colunas_sem_mapa} | "
        f"T15(secoes sem mapa)={audit.secoes_sem_mapa} | "
        f"T17(RGF-05 sem fonte)={audit.rgf05_sem_fonte} | "
        f"DUP_residual={audit.duplicatas_residuais_dup}"
    )
    if audit.amostras_colunas_sem_mapa:
        console.print(f"[red]Colunas sem mapa:[/red] {audit.amostras_colunas_sem_mapa}")
    if audit.amostras_secoes_sem_mapa:
        console.print(f"[red]Secoes sem mapa:[/red] {audit.amostras_secoes_sem_mapa}")
    if audit.amostras_rgf05_sem_fonte:
        console.print(f"[red]RGF-05 sem fonte:[/red] {audit.amostras_rgf05_sem_fonte}")


@app.command("profile")
def cmd_profile(
    ente: int = typer.Option(3306305, "--ente", help="Codigo IBGE do municipio foco para profiling."),
) -> None:
    """Fase 2 (Secao 16 / Decisao 5): Gera relatorio de profiling historico e seed_profundidade.csv."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        res = run_historical_profiling(conn, id_ente=ente)
    console.print(
        f"[bold green]Profiling historico concluido![/bold green]\n"
        f"  Anexos avaliados: {res.anexos_avaliados}\n"
        f"  Rupturas Jaccard < 0.50 (bruto -> padronizado): "
        f"{res.rupturas_brutas_detectadas} -> {res.rupturas_pos_padronizacao}\n"
        f"  Relatorio: {res.report_path}\n"
        f"  Seed atualizado: {res.profundidade_path}"
    )


@app.command("status-silver")
def cmd_status_silver() -> None:
    """Exibe volumetria e auditoria de mapeamento da camada Silver."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        audit = audit_silver(conn)
    console.print(
        f"[cyan]Total Silver:[/cyan] {audit.total_registros:,} | "
        f"[green]Vigentes:[/green] {audit.registros_vigentes:,} | "
        f"[yellow]Substituidos:[/yellow] {audit.registros_substituidos:,} | "
        f"T02={audit.colunas_sem_mapa} | T15={audit.secoes_sem_mapa} | T17={audit.rgf05_sem_fonte}"
    )


@app.command("build-gold-dims")
def cmd_build_gold_dims() -> None:
    """Fase 3: Popula de forma deterministica e idempotente todas as dimensoes gold.d_*."""
    cfg = get_settings()
    init_database(cfg)
    console.print("[bold cyan]Fase 3 - Construcao das Dimensoes Gold (gold.d_*)[/bold cyan]")

    with get_connection(cfg) as conn:
        summary = build_gold_dimensions(conn, cfg)
        audit = audit_gold_dimensions(conn)

    table = Table(title="Resumo das Dimensoes Gold Carregadas")
    table.add_column("Dimensao (gold.*)", style="cyan")
    table.add_column("Registros", justify="right", style="green")
    for tbl, cnt in audit.counts.items():
        table.add_row(f"gold.{tbl}", f"{cnt:,}")
    console.print(table)
    console.print(
        f"[bold]Auditoria Dimensoes Gold:[/bold] "
        f"T14_VIGENCIA={audit.t14_vigencia_overlaps} | "
        f"Folha&Total={audit.folha_and_total_violations} | "
        f"PaiMarcadoFolha={audit.parent_marked_folha_violations} | "
        f"ContasSilverSemDConta={audit.silver_accounts_missing_in_d_conta} | "
        f"T03_Orfas={summary.t03_contas_sem_hierarquia} | "
        f"GruposAnaliticosFaltantes={len(audit.missing_grupos_analiticos)}"
    )


@app.command("status-gold-dims")
def cmd_status_gold_dims() -> None:
    """Exibe contagem e invariantes das dimensoes Gold (Fase 3)."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        audit = audit_gold_dimensions(conn)

    table = Table(title="Status Dimensoes Gold (Fase 3)")
    table.add_column("Dimensao", style="cyan")
    table.add_column("Linhas", justify="right", style="green")
    for tbl, cnt in audit.counts.items():
        table.add_row(f"gold.{tbl}", f"{cnt:,}")
    console.print(table)
    console.print(
        f"T14_VIGENCIA={audit.t14_vigencia_overlaps} | "
        f"Folha&Total={audit.folha_and_total_violations} | "
        f"PaiMarcadoFolha={audit.parent_marked_folha_violations} | "
        f"ContasSilverSemDConta={audit.silver_accounts_missing_in_d_conta} | "
        f"GruposFaltantes={audit.missing_grupos_analiticos}"
    )


@app.command("build-gold-facts")
def cmd_build_gold_facts(
    entes: str | None = typer.Option(
        None,
        "--entes",
        help="Lista CSV de codigos IBGE (padrao: ENTES_ESCOPO do .env).",
    ),
    only_principal: bool = typer.Option(
        False,
        "--only-principal",
        help="Carrega apenas o municipio principal (Volta Redonda = 3306305).",
    ),
    ano_ini: int | None = typer.Option(None, "--ano-ini", help="Ano inicial."),
    ano_fim: int | None = typer.Option(None, "--ano-fim", help="Ano final."),
) -> None:
    """Fase 4: Constroi e materializa todas as tabelas fato (f_ipca, f_populacao, f_rreo, f_dca, f_rgf, f_indicador)."""
    cfg = get_settings()
    init_database(cfg)

    if only_principal:
        target_entes = [cfg.ente_principal]
    elif entes:
        target_entes = [int(x.strip()) for x in entes.split(",") if x.strip()]
    else:
        target_entes = cfg.lista_entes

    start_year = ano_ini if ano_ini is not None else cfg.ano_inicial_extracao
    end_year = ano_fim if ano_fim is not None else cfg.ano_final_extracao

    console.print(
        f"[bold cyan]Fase 4 - Construcao dos Fatos Gold e Indicadores[/bold cyan] | "
        f"Entes={target_entes} | Janela={start_year}-{end_year}"
    )

    with get_connection(cfg) as conn:
        summary = build_gold_facts_all(conn, cfg, target_entes, start_year, end_year)
        audit = audit_gold_facts(conn)

    table = Table(title="Resumo das Tabelas Fato Gold (Fase 4)")
    table.add_column("Tabela Fato (gold.*)", style="cyan")
    table.add_column("Registros", justify="right", style="green")
    for tbl, cnt in audit.counts.items():
        table.add_row(f"gold.{tbl}", f"{cnt:,}")
    console.print(table)

    console.print(
        f"[bold]Auditoria Fatos Gold:[/bold] "
        f"FK_Orfas_Total={audit.fk_orfas_total} | "
        f"RGF05_Com_Fonte={audit.rgf05_com_fonte} | "
        f"RGF05_Sem_Fonte_Detalhe={audit.rgf05_sem_fonte_detalhe} | "
        f"RGF_Outros_Sem_Fonte={summary.rgf_anexos_sem_fonte}"
    )


@app.command("status-gold-facts")
def cmd_status_gold_facts() -> None:
    """Exibe volumetria, auditoria de fontes e integridade referencial das tabelas fato."""
    cfg = get_settings()
    with get_connection(cfg) as conn:
        audit = audit_gold_facts(conn)

    table = Table(title="Status Tabelas Fato Gold (Fase 4)")
    table.add_column("Tabela Fato", style="cyan")
    table.add_column("Linhas", justify="right", style="green")
    for tbl, cnt in audit.counts.items():
        table.add_row(f"gold.{tbl}", f"{cnt:,}")
    console.print(table)
    console.print(
        f"FK_Orfas={audit.fk_orfas_total} | "
        f"RGF05_Com_Fonte={audit.rgf05_com_fonte} | "
        f"RGF05_Sem_Fonte_Detalhe={audit.rgf05_sem_fonte_detalhe}"
    )


@app.command("quality-check")
def cmd_quality_check(
    entes: str | None = typer.Option(
        None,
        "--entes",
        help="Lista CSV de codigos IBGE (padrao: ENTES_ESCOPO do .env).",
    ),
    only_principal: bool = typer.Option(
        False,
        "--only-principal",
        help="Audita apenas o municipio principal (Volta Redonda = 3306305).",
    ),
    ano_ini: int | None = typer.Option(None, "--ano-ini", help="Ano inicial."),
    ano_fim: int | None = typer.Option(None, "--ano-fim", help="Ano final."),
) -> None:
    """Fase 5: Executa a suite de qualidade contabil (T01 a T19) e grava ocorrencias em gold.f_qualidade."""
    cfg = get_settings()
    init_database(cfg)

    if only_principal:
        target_entes = [cfg.ente_principal]
    elif entes:
        target_entes = [int(x.strip()) for x in entes.split(",") if x.strip()]
    else:
        target_entes = cfg.lista_entes

    start_year = ano_ini if ano_ini is not None else cfg.ano_inicial_extracao
    end_year = ano_fim if ano_fim is not None else cfg.ano_final_extracao

    console.print(
        f"[bold cyan]Fase 5 - Suite de Qualidade Contabil (T01 a T19)[/bold cyan] | "
        f"Entes={target_entes} | Janela={start_year}-{end_year}"
    )

    with get_connection(cfg) as conn:
        res = run_quality_suite(
            conn,
            entes=target_entes,
            ano_ini=start_year,
            ano_fim=end_year,
            persistir=True,
        )

    table = Table(title="Resultado da Suite de Qualidade (Fase 5)")
    table.add_column("Metrica", style="cyan")
    table.add_column("Valor", justify="right")
    table.add_row("Total de Testes Executados", str(res.total_testes))
    table.add_row(
        "Erros Bloqueantes (Fail-Fast)",
        f"[bold red]{res.bloqueantes_falhas}[/bold red]" if res.bloqueantes_falhas > 0 else "[green]0[/green]",
    )
    table.add_row(
        "Alertas Contabeis Auditados",
        f"[yellow]{res.alertas_total}[/yellow]" if res.alertas_total > 0 else "[green]0[/green]",
    )
    table.add_row(
        "Status Geral",
        "[bold green]SUCESSO (Aceite Aprovado)[/bold green]" if res.status == "SUCESSO" else "[bold red]FALHA[/bold red]",
    )
    console.print(table)

    if res.ocorrencias:
        det_table = Table(title="Detalhamento das Ocorrencias de Qualidade")
        det_table.add_column("Teste", style="cyan")
        det_table.add_column("Sev.", style="magenta")
        det_table.add_column("Ente", justify="right")
        det_table.add_column("Exercicio", justify="right")
        det_table.add_column("Mensagem")
        for o in res.ocorrencias[:25]:
            sev_style = "bold red" if o.severidade == "BLOQUEANTE" else "yellow"
            det_table.add_row(
                o.codigo_teste,
                f"[{sev_style}]{o.severidade}[/{sev_style}]",
                str(o.sk_ente or "-"),
                str(o.exercicio or "-"),
                o.mensagem,
            )
        console.print(det_table)
        if len(res.ocorrencias) > 25:
            console.print(f"[dim]... e mais {len(res.ocorrencias) - 25} ocorrencias gravadas em gold.f_qualidade.[/dim]")

    if res.bloqueantes_falhas > 0:
        raise typer.Exit(code=1)


@app.command("run-all")
def cmd_run_all(
    entes: str | None = typer.Option(
        None,
        "--entes",
        help="Lista CSV de codigos IBGE (padrao: ENTES_ESCOPO do .env).",
    ),
    only_principal: bool = typer.Option(
        False,
        "--only-principal",
        help="Executa pipeline apenas para o municipio principal (Volta Redonda = 3306305).",
    ),
    ano_ini: int | None = typer.Option(None, "--ano-ini", help="Ano inicial."),
    ano_fim: int | None = typer.Option(None, "--ano-fim", help="Ano final."),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Reconsulta demonstrativos da STN mesmo em cache.",
    ),
    skip_anexos: bool = typer.Option(
        False,
        "--skip-anexos",
        help="Pula catalogo de anexos.",
    ),
    skip_extract: bool = typer.Option(
        False,
        "--skip-extract",
        help="Pula extracao HTTP (usa bronze ja carregada no banco).",
    ),
) -> None:
    """Fase 5: Executa o pipeline Medallion completo ponta a ponta com rastreabilidade em gold.etl_controle."""
    cfg = get_settings()

    if only_principal:
        target_entes = [cfg.ente_principal]
    elif entes:
        target_entes = [int(x.strip()) for x in entes.split(",") if x.strip()]
    else:
        target_entes = cfg.lista_entes

    start_year = ano_ini if ano_ini is not None else cfg.ano_inicial_extracao
    end_year = ano_fim if ano_fim is not None else cfg.ano_final_extracao

    console.print(
        f"[bold green]Executando Pipeline SICONFI DW (run-all)[/bold green] | "
        f"Entes={target_entes} | Janela={start_year}-{end_year}"
    )

    res = run_pipeline(
        cfg=cfg,
        entes=target_entes,
        ano_ini=start_year,
        ano_fim=end_year,
        force_refresh=force_refresh,
        skip_anexos=skip_anexos,
        skip_extract=skip_extract,
    )

    console.print(
        f"[bold green]Pipeline concluido com sucesso![/bold green]\n"
        f"  ID Execucao: [cyan]{res.id_execucao}[/cyan]\n"
        f"  Linhas Gold Publicadas: [green]{res.linhas_gold:,}[/green]\n"
        f"  Falhas Bloqueantes: [green]{res.bloqueantes_falhas}[/green]\n"
        f"  Alertas Contabeis: [yellow]{res.alertas_total}[/yellow]\n"
        f"  Observacao: {res.observacao}"
    )


if __name__ == "__main__":
    app()
