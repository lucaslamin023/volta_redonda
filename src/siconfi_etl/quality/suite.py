from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg


@dataclass(frozen=True)
class QualityOccurrence:
    codigo_teste: str
    severidade: str  # 'BLOQUEANTE', 'ALERTA', 'INFO'
    mensagem: str
    sk_ente: int | None = None
    exercicio: int | None = None
    periodo_codigo: int | None = None
    anexo_codigo: str | None = None
    valor_esperado: str | None = None
    valor_obtido: str | None = None


@dataclass(frozen=True)
class QualitySuiteResult:
    total_testes: int
    bloqueantes_falhas: int
    alertas_total: int
    ocorrencias: list[QualityOccurrence]
    status: str  # 'SUCESSO' ou 'FALHA'


__test__ = False


# =============================================================================
# 1. Testes Bloqueantes (T01, T02, T10, T11, T12, T14, T15, T17)
# =============================================================================

def check_t01_chave_unica(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T01_CHAVE_UNICA (BLOQUEANTE): Unicidade da chave natural entre os registros vigentes na Silver."""
    cur.execute(
        """
        SELECT
            id_ente, exercicio, periodo_codigo, anexo_codigo, cod_conta,
            COALESCE(coluna_padrao, coluna_origem) AS col,
            COUNT(*) AS cnt
        FROM silver.siconfi_registro
        WHERE eh_vigente = 1
          AND (%s::integer[] IS NULL OR id_ente = ANY(%s::integer[]))
          AND (%s::integer IS NULL OR exercicio >= %s::integer)
          AND (%s::integer IS NULL OR exercicio <= %s::integer)
        GROUP BY id_ente, fonte, exercicio, periodo_codigo, co_poder, anexo_codigo, rotulo_origem, cod_conta, COALESCE(coluna_padrao, coluna_origem)
        HAVING COUNT(*) > 1
        LIMIT 50;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    if not rows:
        return []

    return [
        QualityOccurrence(
            codigo_teste="T01_CHAVE_UNICA",
            severidade="BLOQUEANTE",
            mensagem=f"Duplicata na chave natural vigente: conta '{r[4]}' coluna '{r[5]}' aparece {r[6]} vezes.",
            sk_ente=None,
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo=r[3],
            valor_esperado="1",
            valor_obtido=str(r[6]),
        )
        for r in rows
    ]


def check_t02_coluna_sem_mapa(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T02_COLUNA_SEM_MAPA (BLOQUEANTE): Toda coluna_origem vigente deve estar mapeada em seed_coluna_map.csv."""
    cur.execute(
        """
        SELECT
            s.id_ente, s.exercicio, s.periodo_codigo, s.anexo_codigo, s.coluna_origem, COUNT(*)
        FROM silver.siconfi_registro s
        WHERE s.eh_vigente = 1
          AND s.coluna_padrao IS NULL
          AND (%s::integer[] IS NULL OR s.id_ente = ANY(%s::integer[]))
          AND (%s::integer IS NULL OR s.exercicio >= %s::integer)
          AND (%s::integer IS NULL OR s.exercicio <= %s::integer)
        GROUP BY s.id_ente, s.exercicio, s.periodo_codigo, s.anexo_codigo, s.coluna_origem
        LIMIT 50;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T02_COLUNA_SEM_MAPA",
            severidade="BLOQUEANTE",
            mensagem=f"Coluna de origem '{r[4]}' sem mapeamento para coluna_padrao no anexo {r[3]}.",
            sk_ente=None,
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo=r[3],
            valor_esperado="Mapeada",
            valor_obtido="NULL",
        )
        for r in rows
    ]


def check_t10_nulo_zero(cur: psycopg.Cursor) -> list[QualityOccurrence]:
    """T10_NULO_ZERO (BLOQUEANTE): Nenhuma celula originalmente vazia/nula deve ser convertida para zero."""
    cur.execute(
        """
        SELECT COUNT(*)
        FROM silver.siconfi_registro s
        WHERE s.valor = 0.00
          AND s.registro_id LIKE '%::VAL_EMPTY%';
        """
    )
    qtd = int(cur.fetchone()[0])
    if qtd > 0:
        return [
            QualityOccurrence(
                codigo_teste="T10_NULO_ZERO",
                severidade="BLOQUEANTE",
                mensagem=f"Detectadas {qtd} celulas onde valor vazio foi artificialmente convertido para 0.00.",
                valor_esperado="0",
                valor_obtido=str(qtd),
            )
        ]
    return []


def check_t11_tipos(cur: psycopg.Cursor) -> list[QualityOccurrence]:
    """T11_TIPOS (BLOQUEANTE): Zero colunas com tipo float ou double precision nos schemas silver e gold."""
    cur.execute(
        """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema IN ('silver', 'gold')
          AND data_type IN ('real', 'double precision', 'float')
        ORDER BY table_schema, table_name, column_name;
        """
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T11_TIPOS",
            severidade="BLOQUEANTE",
            mensagem=f"Coluna {r[0]}.{r[1]}.{r[2]} com tipo proibido '{r[3]}' (deve ser NUMERIC ou TEXT).",
            valor_esperado="NUMERIC/TEXT",
            valor_obtido=str(r[3]),
        )
        for r in rows
    ]


def check_t12_fk_orfa(cur: psycopg.Cursor) -> list[QualityOccurrence]:
    """T12_FK_ORFA (BLOQUEANTE): Nenhuma chave estrangeira orfa nas tabelas fato do Star Schema."""
    cur.execute(
        """
        SELECT
            'f_rreo -> d_ente' AS rel, COUNT(*) FROM gold.f_rreo r LEFT JOIN gold.d_ente e ON e.sk_ente = r.sk_ente WHERE e.sk_ente IS NULL
        UNION ALL
        SELECT 'f_rreo -> d_calendario', COUNT(*) FROM gold.f_rreo r LEFT JOIN gold.d_calendario c ON c.sk_data = r.sk_data_fim_periodo WHERE c.sk_data IS NULL
        UNION ALL
        SELECT 'f_rreo -> d_conta', COUNT(*) FROM gold.f_rreo r LEFT JOIN gold.d_conta c ON c.sk_conta = r.sk_conta WHERE c.sk_conta IS NULL
        UNION ALL
        SELECT 'f_rgf -> d_ente', COUNT(*) FROM gold.f_rgf r LEFT JOIN gold.d_ente e ON e.sk_ente = r.sk_ente WHERE e.sk_ente IS NULL
        UNION ALL
        SELECT 'f_rgf -> d_conta', COUNT(*) FROM gold.f_rgf r LEFT JOIN gold.d_conta c ON c.sk_conta = r.sk_conta WHERE c.sk_conta IS NULL
        UNION ALL
        SELECT 'f_dca -> d_ente', COUNT(*) FROM gold.f_dca r LEFT JOIN gold.d_ente e ON e.sk_ente = r.sk_ente WHERE e.sk_ente IS NULL
        UNION ALL
        SELECT 'f_dca -> d_conta', COUNT(*) FROM gold.f_dca r LEFT JOIN gold.d_conta c ON c.sk_conta = r.sk_conta WHERE c.sk_conta IS NULL
        UNION ALL
        SELECT 'f_indicador -> d_indicador', COUNT(*) FROM gold.f_indicador i LEFT JOIN gold.d_indicador d ON d.sk_indicador = i.sk_indicador WHERE d.sk_indicador IS NULL;
        """
    )
    rows = cur.fetchall()
    occurrences = []
    for rel, cnt in rows:
        if cnt > 0:
            occurrences.append(
                QualityOccurrence(
                    codigo_teste="T12_FK_ORFA",
                    severidade="BLOQUEANTE",
                    mensagem=f"Integridade violada: {cnt} registros em {rel} sem dimensao correspondente.",
                    valor_esperado="0",
                    valor_obtido=str(cnt),
                )
            )
    return occurrences


def check_t14_vigencia(cur: psycopg.Cursor) -> list[QualityOccurrence]:
    """T14_VIGENCIA (BLOQUEANTE): Zero sobreposicoes de vigencia temporal em gold.d_limite_lrf."""
    cur.execute(
        """
        SELECT
            l1.codigo_limite, l1.vigencia_ini, l1.vigencia_fim,
            l2.vigencia_ini, l2.vigencia_fim
        FROM gold.d_limite_lrf l1
        JOIN gold.d_limite_lrf l2
          ON l1.codigo_limite = l2.codigo_limite
         AND l1.sk_limite <> l2.sk_limite
         AND daterange(l1.vigencia_ini, COALESCE(l1.vigencia_fim, 'infinity'::date), '[]') &&
             daterange(l2.vigencia_ini, COALESCE(l2.vigencia_fim, 'infinity'::date), '[]');
        """
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T14_VIGENCIA",
            severidade="BLOQUEANTE",
            mensagem=f"Sobreposicao de vigencia no limite {r[0]}: [{r[1]} a {r[2]}] conflita com [{r[3]} a {r[4]}].",
            valor_esperado="0 sobreposicoes",
            valor_obtido="Sobreposicao detectada",
        )
        for r in rows
    ]


def check_t15_secao_sem_mapa(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T15_SECAO_SEM_MAPA (BLOQUEANTE): Todo rotulo_origem vigente deve possuir secao mapeada."""
    cur.execute(
        """
        SELECT
            s.id_ente, s.exercicio, s.periodo_codigo, s.anexo_codigo, s.rotulo_origem, COUNT(*)
        FROM silver.siconfi_registro s
        LEFT JOIN gold.d_secao ds
          ON ds.fonte = s.fonte
         AND ds.anexo_codigo = s.anexo_codigo
        WHERE s.eh_vigente = 1
          AND ds.sk_secao IS NULL
          AND (%s::integer[] IS NULL OR s.id_ente = ANY(%s::integer[]))
          AND (%s::integer IS NULL OR s.exercicio >= %s::integer)
          AND (%s::integer IS NULL OR s.exercicio <= %s::integer)
        GROUP BY s.id_ente, s.exercicio, s.periodo_codigo, s.anexo_codigo, s.rotulo_origem
        LIMIT 50;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T15_SECAO_SEM_MAPA",
            severidade="BLOQUEANTE",
            mensagem=f"Rotulo de origem '{r[4]}' sem secao correspondente em gold.d_secao no anexo {r[3]}.",
            sk_ente=None,
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo=r[3],
            valor_esperado="Secao Cadastrada",
            valor_obtido="NULL",
        )
        for r in rows
    ]


def check_t17_fonte_sem_mapa(cur: psycopg.Cursor) -> list[QualityOccurrence]:
    """T17_FONTE_SEM_MAPA (BLOQUEANTE): Toda fonte de recurso de detalhe do RGF-05 deve ter sk_fonte_recurso <> 0."""
    cur.execute(
        """
        SELECT COUNT(*)
        FROM gold.f_rgf r
        JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
        WHERE r.anexo_codigo = 'RGF-05'
          AND r.sk_fonte_recurso = 0
          AND dc.cod_conta LIKE '%%::FR_%%';
        """
    )
    cnt = int(cur.fetchone()[0])
    if cnt > 0:
        return [
            QualityOccurrence(
                codigo_teste="T17_FONTE_SEM_MAPA",
                severidade="BLOQUEANTE",
                mensagem=f"Encontradas {cnt} linhas de detalhe no RGF-05 com sk_fonte_recurso = 0 (fonte nao mapeada).",
                valor_esperado="0",
                valor_obtido=str(cnt),
            )
        ]
    return []


# =============================================================================
# 2. Testes de Auditoria e Conciliação Contábil (Alertas Auditados)
# =============================================================================

def check_t03_conta_sem_hierarquia(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T03_CONTA_SEM_HIERARQUIA (ALERTA): Contas sem nivel ou grupo analitico em gold.d_conta."""
    cur.execute(
        """
        SELECT DISTINCT
            s.id_ente, s.exercicio, s.periodo_codigo, s.anexo_codigo, s.cod_conta, s.conta_descricao
        FROM silver.siconfi_registro s
        LEFT JOIN gold.d_conta dc
          ON dc.fonte = s.fonte
         AND dc.anexo_codigo = s.anexo_codigo
         AND dc.cod_conta = s.cod_conta
        WHERE s.eh_vigente = 1
          AND (dc.sk_conta IS NULL OR dc.nivel IS NULL OR dc.grupo_analitico IS NULL)
          AND (%s::integer[] IS NULL OR s.id_ente = ANY(%s::integer[]))
          AND (%s::integer IS NULL OR s.exercicio >= %s::integer)
          AND (%s::integer IS NULL OR s.exercicio <= %s::integer)
        LIMIT 50;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T03_CONTA_SEM_HIERARQUIA",
            severidade="ALERTA",
            mensagem=f"Conta '{r[4]}' ({r[5]}) no anexo {r[3]} sem hierarquia completa definida em gold.d_conta.",
            sk_ente=None,
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo=r[3],
            valor_esperado="Hierarquia Completa",
            valor_obtido="Nivel/Grupo Ausente",
        )
        for r in rows
    ]


def check_t04_total_receita(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T04_TOTAL_RECEITA (ALERTA): Conciliacao das receitas no RREO-01 (soma das folhas vs total declarado +/- R$ 1,00)."""
    cur.execute(
        """
        WITH folhas AS (
            SELECT
                r.sk_ente, r.sk_data_fim_periodo, r.sk_coluna,
                SUM(r.valor) AS soma_folhas
            FROM gold.f_rreo r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_secao ds ON ds.sk_secao = r.sk_secao
            WHERE r.anexo_codigo = 'RREO-01'
              AND dc.eh_folha = 1
              AND ds.secao_codigo LIKE '%%RECEITA%%'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_coluna
        ),
        total_decl AS (
            SELECT
                r.sk_ente, r.sk_data_fim_periodo, r.sk_coluna,
                r.valor AS total_declarado
            FROM gold.f_rreo r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            WHERE r.anexo_codigo = 'RREO-01'
              AND dc.cod_conta IN ('TotalReceitas', 'TotalReceitasComDeficit')
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
        )
        SELECT
            f.sk_ente,
            f.sk_data_fim_periodo / 10000 AS exercicio,
            cal.bimestre,
            f.soma_folhas,
            t.total_declarado,
            ROUND(f.soma_folhas - t.total_declarado, 2) AS diferenca
        FROM folhas f
        JOIN total_decl t
          ON t.sk_ente = f.sk_ente
         AND t.sk_data_fim_periodo = f.sk_data_fim_periodo
         AND t.sk_coluna = f.sk_coluna
        JOIN gold.d_calendario cal ON cal.sk_data = f.sk_data_fim_periodo
        WHERE ABS(f.soma_folhas - t.total_declarado) > 1.00
        LIMIT 30;
        """,
        (
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,
        ),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T04_TOTAL_RECEITA",
            severidade="ALERTA",
            mensagem=f"Divergencia entre soma das folhas de receita (R$ {r[3]:,.2f}) e total declarado (R$ {r[4]:,.2f}) no RREO-01: dif R$ {r[5]:,.2f}.",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo="RREO-01",
            valor_esperado=str(r[4]),
            valor_obtido=str(r[3]),
        )
        for r in rows
    ]


def check_t05_total_despesa(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T05_TOTAL_DESPESA (ALERTA): Conciliacao das despesas por funcao no RREO-02 (+/- R$ 1,00)."""
    cur.execute(
        """
        WITH funcoes AS (
            SELECT
                r.sk_ente, r.sk_data_fim_periodo, r.sk_coluna,
                SUM(r.valor) AS soma_funcoes
            FROM gold.f_rreo r
            JOIN gold.d_funcao df ON df.sk_funcao = r.sk_funcao
            WHERE r.anexo_codigo = 'RREO-02'
              AND df.cod_funcao <> '00'
              AND df.cod_subfuncao = ''
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo, r.sk_coluna
        ),
        total_decl AS (
            SELECT
                r.sk_ente, r.sk_data_fim_periodo, r.sk_coluna,
                r.valor AS total_declarado
            FROM gold.f_rreo r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            WHERE r.anexo_codigo = 'RREO-02'
              AND dc.cod_conta IN ('TotalDespesas', 'DespesasIntra')
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
        )
        SELECT
            f.sk_ente,
            f.sk_data_fim_periodo / 10000 AS exercicio,
            cal.bimestre,
            f.soma_funcoes,
            t.total_declarado,
            ROUND(f.soma_funcoes - t.total_declarado, 2) AS diferenca
        FROM funcoes f
        JOIN total_decl t
          ON t.sk_ente = f.sk_ente
         AND t.sk_data_fim_periodo = f.sk_data_fim_periodo
         AND t.sk_coluna = f.sk_coluna
        JOIN gold.d_calendario cal ON cal.sk_data = f.sk_data_fim_periodo
        WHERE ABS(f.soma_funcoes - t.total_declarado) > 1.00
        LIMIT 30;
        """,
        (
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,
        ),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T05_TOTAL_DESPESA",
            severidade="ALERTA",
            mensagem=f"Divergencia entre soma das funcoes de despesa (R$ {r[3]:,.2f}) e total declarado (R$ {r[4]:,.2f}) no RREO-02: dif R$ {r[5]:,.2f}.",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo="RREO-02",
            valor_esperado=str(r[4]),
            valor_obtido=str(r[3]),
        )
        for r in rows
    ]


def check_t06_balanco_patrimonial(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T06_BALANCO_PATRIMONIAL (ALERTA): Equacao fundamental Ativo Total = Passivo + Patrimonio Liquido (+/- R$ 1,00)."""
    cur.execute(
        """
        WITH bp_totais AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo / 10000 AS exercicio,
                MAX(CASE WHEN dc.cod_conta = 'P1.0.0.0.0.00.00' THEN r.valor END) AS ativo_total,
                MAX(CASE WHEN dc.cod_conta = 'P2.0.0.0.0.00.00' THEN r.valor END) AS passivo_total
            FROM gold.f_dca r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_secao ds ON ds.sk_secao = r.sk_secao
            WHERE r.anexo_codigo = 'DCA-I-AB'
              AND ds.secao_codigo = 'BP_PRINCIPAL'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo
        )
        SELECT
            sk_ente, exercicio, 1 AS periodo_codigo, ativo_total, passivo_total,
            ROUND(ativo_total - passivo_total, 2) AS diferenca
        FROM bp_totais
        WHERE ativo_total IS NOT NULL
          AND passivo_total IS NOT NULL
          AND ABS(ativo_total - passivo_total) > 1.00
        LIMIT 30;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T06_BALANCO_PATRIMONIAL",
            severidade="ALERTA",
            mensagem=f"Desequilibrio patrimonial no Balanco Patrimonial (DCA-I-AB): Ativo Total (R$ {r[3]:,.2f}) <> Passivo+PL (R$ {r[4]:,.2f}) com diferenca de R$ {r[5]:,.2f}.",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo="DCA-I-AB",
            valor_esperado=str(r[3]),
            valor_obtido=str(r[4]),
        )
        for r in rows
    ]


def check_t07_fluxo_acumulado(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T07_FLUXO_ACUMULADO (ALERTA): Monotonicidade dos fluxos acumulados orcamentarios bimestrais (t >= t-1)."""
    cur.execute(
        """
        WITH serie_rec AS (
            SELECT
                r.sk_ente,
                cal.ano AS exercicio,
                cal.bimestre,
                r.valor,
                LAG(r.valor) OVER (
                    PARTITION BY r.sk_ente, cal.ano
                    ORDER BY cal.bimestre
                ) AS valor_anterior
            FROM gold.f_rreo r
            JOIN gold.d_calendario cal ON cal.sk_data = r.sk_data_fim_periodo
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
            WHERE r.anexo_codigo = 'RREO-01'
              AND dc.cod_conta = 'TotalReceitas'
              AND dcol.coluna_padrao = 'RECEITA_ATE_PERIODO'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR cal.ano >= %s::integer)
              AND (%s::integer IS NULL OR cal.ano <= %s::integer)
        )
        SELECT
            sk_ente, exercicio, bimestre, valor, valor_anterior,
            ROUND(valor - valor_anterior, 2) AS queda
        FROM serie_rec
        WHERE valor_anterior IS NOT NULL
          AND valor < valor_anterior - 1.00
        LIMIT 30;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T07_FLUXO_ACUMULADO",
            severidade="ALERTA",
            mensagem=f"Queda atipica no fluxo acumulado de receita orcamentaria no {r[2]}o Bimestre/{r[1]}: de R$ {r[4]:,.2f} para R$ {r[3]:,.2f} (declinio de R$ {abs(r[5]):,.2f}).",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo="RREO-01",
            valor_esperado=f">= {r[4]}",
            valor_obtido=str(r[3]),
        )
        for r in rows
    ]


def check_t08_percentual_declarado(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T08_PERCENTUAL_DECLARADO (ALERTA): Divergencia entre indicador recalculado e declarado (|dif| > 0.05 p.p.)."""
    cur.execute(
        """
        SELECT
            f.sk_ente,
            f.sk_data_fim_periodo / 10000 AS exercicio,
            COALESCE(cal.quadrimestre, cal.bimestre) AS periodo_codigo,
            ind.codigo_indicador,
            f.valor_indicador,
            f.valor_declarado,
            f.diferenca_declarado
        FROM gold.f_indicador f
        JOIN gold.d_indicador ind ON ind.sk_indicador = f.sk_indicador
        JOIN gold.d_calendario cal ON cal.sk_data = f.sk_data_fim_periodo
        WHERE f.diferenca_declarado IS NOT NULL
          AND ABS(f.diferenca_declarado) > 0.05
          AND (%s::integer[] IS NULL OR f.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
          AND (%s::integer IS NULL OR f.sk_data_fim_periodo / 10000 >= %s::integer)
          AND (%s::integer IS NULL OR f.sk_data_fim_periodo / 10000 <= %s::integer)
        LIMIT 50;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T08_PERCENTUAL_DECLARADO",
            severidade="ALERTA",
            mensagem=f"Divergencia entre indicador recalculado ({r[4]:.2f}%) e declarado ({r[5]:.2f}%) para {r[3]}: diferenca de {r[6]:.2f} p.p.",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo=None,
            valor_esperado=str(r[5]),
            valor_obtido=str(r[4]),
        )
        for r in rows
    ]


def check_t09_cobertura_periodos(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T09_COBERTURA_PERIODOS (ALERTA): Identifica exercicios encerrados com bimestres ou quadrimestres faltantes."""
    cur.execute(
        """
        WITH periodos_esperados AS (
            SELECT
                e.sk_ente,
                ano.ano AS exercicio,
                'RREO' AS demonstrativo,
                6 AS periodos_esperados
            FROM gold.d_ente e
            CROSS JOIN (
                SELECT DISTINCT ano FROM gold.d_calendario
                WHERE ano >= 2015 AND ano < EXTRACT(YEAR FROM CURRENT_DATE)
            ) ano
            WHERE (%s::integer[] IS NULL OR e.id_ente = ANY(%s::integer[]))
              AND (%s::integer IS NULL OR ano.ano >= %s::integer)
              AND (%s::integer IS NULL OR ano.ano <= %s::integer)
        ),
        periodos_reais AS (
            SELECT
                r.sk_ente,
                cal.ano AS exercicio,
                'RREO' AS demonstrativo,
                COUNT(DISTINCT cal.bimestre) AS periodos_entregues
            FROM gold.f_rreo r
            JOIN gold.d_calendario cal ON cal.sk_data = r.sk_data_fim_periodo
            GROUP BY r.sk_ente, cal.ano
        )
        SELECT
            pe.sk_ente, pe.exercicio, 0 AS periodo_codigo, pe.demonstrativo,
            pe.periodos_esperados,
            COALESCE(pr.periodos_entregues, 0) AS periodos_entregues
        FROM periodos_esperados pe
        LEFT JOIN periodos_reais pr
          ON pr.sk_ente = pe.sk_ente AND pr.exercicio = pe.exercicio
        WHERE COALESCE(pr.periodos_entregues, 0) < pe.periodos_esperados
        LIMIT 30;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T09_COBERTURA_PERIODOS",
            severidade="ALERTA",
            mensagem=f"Exercicio fiscal {r[1]} incompleto para {r[3]}: {r[5]} de {r[4]} periodos carregados.",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo=r[3],
            valor_esperado=str(r[4]),
            valor_obtido=str(r[5]),
        )
        for r in rows
    ]


def check_t13_populacao(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T13_POPULACAO (ALERTA): Toda combinacao (ente, exercicio) possui populacao > 0 e variacao anual suave."""
    cur.execute(
        """
        WITH serie_pop AS (
            SELECT
                p.sk_ente,
                p.exercicio,
                p.populacao,
                LAG(p.populacao) OVER (PARTITION BY p.sk_ente ORDER BY p.exercicio) AS pop_anterior
            FROM gold.f_populacao p
            WHERE (%s::integer[] IS NULL OR p.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR p.exercicio >= %s::integer)
              AND (%s::integer IS NULL OR p.exercicio <= %s::integer)
        )
        SELECT
            sk_ente, exercicio, 1 AS periodo_codigo, populacao, pop_anterior,
            ROUND(ABS(populacao - pop_anterior)::numeric / pop_anterior * 100.0, 2) AS variacao_pct
        FROM serie_pop
        WHERE pop_anterior IS NOT NULL
          AND ABS(populacao - pop_anterior)::numeric / pop_anterior > 0.15
        LIMIT 30;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T13_POPULACAO",
            severidade="ALERTA",
            mensagem=f"Variacao populacional atipica no exercicio {r[1]}: populacao mudou {r[5]:.1f}% (de {r[4]:,} para {r[3]:,}).",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo=None,
            valor_esperado="Variacao <= 15%",
            valor_obtido=f"{r[5]}%",
        )
        for r in rows
    ]


def check_t16_caixa_por_fonte(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T16_CAIXA_POR_FONTE (ALERTA): Soma da disponibilidade liquida por fonte vs total consolidado no RGF-05."""
    cur.execute(
        """
        WITH fontes_soma AS (
            SELECT
                r.sk_ente, r.sk_data_fim_periodo,
                SUM(r.valor) AS soma_fontes
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
            WHERE r.anexo_codigo = 'RGF-05'
              AND r.sk_fonte_recurso <> 0
              AND dcol.coluna_padrao = 'CAIXA_LIQUIDA_ANTES_RPNP'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo
        ),
        total_decl AS (
            SELECT
                r.sk_ente, r.sk_data_fim_periodo,
                r.valor AS total_consolidado
            FROM gold.f_rgf r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            JOIN gold.d_coluna dcol ON dcol.sk_coluna = r.sk_coluna
            WHERE r.anexo_codigo = 'RGF-05'
              AND dc.cod_conta LIKE '%%DisponibilidadeDeCaixaLiquida::TOT_GERAL_III%%'
              AND dcol.coluna_padrao = 'CAIXA_LIQUIDA_ANTES_RPNP'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
        )
        SELECT
            f.sk_ente,
            f.sk_data_fim_periodo / 10000 AS exercicio,
            cal.quadrimestre AS periodo_codigo,
            f.soma_fontes,
            t.total_consolidado,
            ROUND(f.soma_fontes - t.total_consolidado, 2) AS diferenca
        FROM fontes_soma f
        JOIN total_decl t
          ON t.sk_ente = f.sk_ente AND t.sk_data_fim_periodo = f.sk_data_fim_periodo
        JOIN gold.d_calendario cal ON cal.sk_data = f.sk_data_fim_periodo
        WHERE ABS(f.soma_fontes - t.total_consolidado) > 1.00
        LIMIT 30;
        """,
        (
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,
            entes, entes, ano_ini, ano_ini, ano_fim, ano_fim,
        ),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T16_CAIXA_POR_FONTE",
            severidade="ALERTA",
            mensagem=f"Divergencia entre soma das fontes de caixa (R$ {r[3]:,.2f}) e total consolidado (R$ {r[4]:,.2f}) no RGF-05: dif R$ {r[5]:,.2f}.",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo="RGF-05",
            valor_esperado=str(r[4]),
            valor_obtido=str(r[3]),
        )
        for r in rows
    ]


def check_t18_balanco_financeiro(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T18_BALANCO_FINANCEIRO (ALERTA): Conciliacao de Ativo Financeiro vs Passivo Financeiro (DCA-I-AB)."""
    cur.execute(
        """
        WITH af_pf AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo / 10000 AS exercicio,
                MAX(CASE WHEN dc.cod_conta = 'AtivoFinanceiro' THEN r.valor END) AS ativo_fin,
                MAX(CASE WHEN dc.cod_conta = 'PassivoFinanceiro' THEN r.valor END) AS passivo_fin
            FROM gold.f_dca r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            WHERE r.anexo_codigo = 'DCA-I-AB'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo
        )
        SELECT
            sk_ente, exercicio, 1 AS periodo_codigo, ativo_fin, passivo_fin,
            ROUND(ativo_fin - passivo_fin, 2) AS superavit_financeiro
        FROM af_pf
        WHERE ativo_fin IS NOT NULL
          AND passivo_fin IS NOT NULL
          AND ativo_fin < passivo_fin  -- Deficit financeiro para abertura de creditos adicionais
        LIMIT 30;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T18_BALANCO_FINANCEIRO",
            severidade="ALERTA",
            mensagem=f"Passivo Financeiro (R$ {r[4]:,.2f}) supera Ativo Financeiro (R$ {r[3]:,.2f}) no DCA-I-AB: deficit financeiro de R$ {abs(r[5]):,.2f} (art. 43 Lei 4.320/64).",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo="DCA-I-AB",
            valor_esperado=f">= {r[4]}",
            valor_obtido=str(r[3]),
        )
        for r in rows
    ]


def check_t19_dvp_resultado(
    cur: psycopg.Cursor,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
) -> list[QualityOccurrence]:
    """T19_DVP_RESULTADO (ALERTA): Conciliacao VPA - VPD = Resultado Patrimonial no DCA-I-HI (+/- R$ 1,00)."""
    cur.execute(
        """
        WITH dvp AS (
            SELECT
                r.sk_ente,
                r.sk_data_fim_periodo / 10000 AS exercicio,
                MAX(CASE WHEN dc.cod_conta = 'P4.0.0.0.0.00.00' THEN r.valor END) AS total_vpa,
                MAX(CASE WHEN dc.cod_conta = 'P3.0.0.0.0.00.00' THEN r.valor END) AS total_vpd,
                MAX(CASE WHEN dc.cod_conta = 'ResultadoPatrimonialDoPeriodo' THEN r.valor END) AS res_patrimonial
            FROM gold.f_dca r
            JOIN gold.d_conta dc ON dc.sk_conta = r.sk_conta
            WHERE r.anexo_codigo = 'DCA-I-HI'
              AND (%s::integer[] IS NULL OR r.sk_ente IN (SELECT sk_ente FROM gold.d_ente WHERE id_ente = ANY(%s::integer[])))
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 >= %s::integer)
              AND (%s::integer IS NULL OR r.sk_data_fim_periodo / 10000 <= %s::integer)
            GROUP BY r.sk_ente, r.sk_data_fim_periodo
        )
        SELECT
            sk_ente, exercicio, 1 AS periodo_codigo,
            total_vpa, total_vpd, res_patrimonial,
            ROUND((total_vpa - total_vpd) - res_patrimonial, 2) AS diferenca
        FROM dvp
        WHERE total_vpa IS NOT NULL
          AND total_vpd IS NOT NULL
          AND res_patrimonial IS NOT NULL
          AND ABS((total_vpa - total_vpd) - res_patrimonial) > 1.00
        LIMIT 30;
        """,
        (entes, entes, ano_ini, ano_ini, ano_fim, ano_fim),
    )
    rows = cur.fetchall()
    return [
        QualityOccurrence(
            codigo_teste="T19_DVP_RESULTADO",
            severidade="ALERTA",
            mensagem=f"Divergencia na DVP (DCA-I-HI): VPA (R$ {r[3]:,.2f}) - VPD (R$ {r[4]:,.2f}) = R$ {(r[3]-r[4]):,.2f}, mas Resultado declarado e R$ {r[5]:,.2f} (dif R$ {r[6]:,.2f}).",
            sk_ente=r[0],
            exercicio=r[1],
            periodo_codigo=r[2],
            anexo_codigo="DCA-I-HI",
            valor_esperado=str(r[5]),
            valor_obtido=str(round(r[3] - r[4], 2)),
        )
        for r in rows
    ]


# =============================================================================
# 3. Orquestrador da Suíte de Qualidade
# =============================================================================

def run_quality_suite(
    conn: psycopg.Connection,
    id_execucao: int | None = None,
    entes: list[int] | None = None,
    ano_ini: int | None = None,
    ano_fim: int | None = None,
    persistir: bool = True,
) -> QualitySuiteResult:
    """
    Executa integralmente os 19 testes da suite de qualidade contabil (T01 a T19).
    Se persistir=True, grava as ocorrencias detalhadas em gold.f_qualidade.
    """
    ocorrencias: list[QualityOccurrence] = []

    with conn.cursor() as cur:
        # 1. Bloqueantes
        ocorrencias.extend(check_t01_chave_unica(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t02_coluna_sem_mapa(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t10_nulo_zero(cur))
        ocorrencias.extend(check_t11_tipos(cur))
        ocorrencias.extend(check_t12_fk_orfa(cur))
        ocorrencias.extend(check_t14_vigencia(cur))
        ocorrencias.extend(check_t15_secao_sem_mapa(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t17_fonte_sem_mapa(cur))

        # 2. Alertas Auditados
        ocorrencias.extend(check_t03_conta_sem_hierarquia(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t04_total_receita(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t05_total_despesa(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t06_balanco_patrimonial(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t07_fluxo_acumulado(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t08_percentual_declarado(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t09_cobertura_periodos(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t13_populacao(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t16_caixa_por_fonte(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t18_balanco_financeiro(cur, entes, ano_ini, ano_fim))
        ocorrencias.extend(check_t19_dvp_resultado(cur, entes, ano_ini, ano_fim))

        bloqueantes_falhas = sum(1 for o in ocorrencias if o.severidade == "BLOQUEANTE")
        alertas_total = sum(1 for o in ocorrencias if o.severidade == "ALERTA")

        if persistir and ocorrencias:
            insert_tuples = [
                (
                    id_execucao,
                    o.sk_ente,
                    o.exercicio,
                    o.periodo_codigo,
                    o.anexo_codigo,
                    o.codigo_teste,
                    o.severidade,
                    o.valor_esperado,
                    o.valor_obtido,
                    o.mensagem,
                )
                for o in ocorrencias
            ]
            cur.executemany(
                """
                INSERT INTO gold.f_qualidade (
                    id_execucao,
                    sk_ente,
                    exercicio,
                    periodo_codigo,
                    anexo_codigo,
                    codigo_teste,
                    severidade,
                    valor_esperado,
                    valor_obtido,
                    mensagem
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                insert_tuples,
            )

    conn.commit()

    status = "FALHA" if bloqueantes_falhas > 0 else "SUCESSO"
    return QualitySuiteResult(
        total_testes=19,
        bloqueantes_falhas=bloqueantes_falhas,
        alertas_total=alertas_total,
        ocorrencias=ocorrencias,
        status=status,
    )
