from __future__ import annotations

import csv
from pathlib import Path

from siconfi_etl.silver.normalizer import normalize_text

# Metadados globais unicos por coluna_padrao (respeitando UNIQUE e CHECK em gold.d_coluna)
# Formato: coluna_padrao -> (tipo_medida, aditividade, ordem_exibicao)
COLUNA_PADRAO_META: dict[str, tuple[str, str, int]] = {
    "PREVISAO_INICIAL": ("PREVISAO", "SEMIADITIVA", 10),
    "PREVISAO_ATUALIZADA": ("PREVISAO", "SEMIADITIVA", 20),
    "PREVISAO_ORCAMENTARIA_RPPS": ("PREVISAO", "SEMIADITIVA", 25),
    "VALOR_CORRENTE": ("PREVISAO", "SEMIADITIVA", 28),
    "META_FISCAL_LDO": ("PREVISAO", "SEMIADITIVA", 29),
    "RECEITA_BRUTA_REALIZADA": ("FLUXO_ACUMULADO", "ADITIVA", 30),
    "DEDUCAO_TRANSF_CONST": ("FLUXO_ACUMULADO", "ADITIVA", 31),
    "DEDUCAO_FUNDEB": ("FLUXO_ACUMULADO", "ADITIVA", 32),
    "OUTRAS_DEDUCOES_RECEITA": ("FLUXO_ACUMULADO", "ADITIVA", 33),
    "RECEITA_NO_PERIODO": ("FLUXO_PERIODO", "ADITIVA", 34),
    "PCT_RECEITA_NO_PERIODO": ("PERCENTUAL", "NAO_ADITIVA", 35),
    "RECEITA_ATE_PERIODO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 40),
    "RECEITA_ATE_PERIODO_EX_ANT": ("FLUXO_ACUMULADO", "SEMIADITIVA", 41),
    "PCT_RECEITA_ATE_PERIODO": ("PERCENTUAL", "NAO_ADITIVA", 45),
    "SALDO_A_REALIZAR": ("SALDO", "SEMIADITIVA", 50),
    "SALDO_NAO_REALIZADO": ("SALDO", "SEMIADITIVA", 52),
    "SALDO_A_PAGAR": ("SALDO", "SEMIADITIVA", 53),
    "DOTACAO_INICIAL": ("PREVISAO", "SEMIADITIVA", 60),
    "DOTACAO_ATUALIZADA": ("PREVISAO", "SEMIADITIVA", 70),
    "DESPESA_EMPENHADA": ("FLUXO_ACUMULADO", "ADITIVA", 75),
    "DESPESA_EMPENHADA_NO_PERIODO": ("FLUXO_PERIODO", "ADITIVA", 80),
    "DESPESA_EMPENHADA_ATE_PERIODO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 90),
    "DESPESA_EMPENHADA_ATE_PERIODO_EX_ANT": ("FLUXO_ACUMULADO", "SEMIADITIVA", 91),
    "PCT_EMPENHADA_TOTAL": ("PERCENTUAL", "NAO_ADITIVA", 92),
    "PCT_EMPENHADA_III": ("PERCENTUAL", "NAO_ADITIVA", 93),
    "SALDO_DOTACAO_EMPENHADA": ("SALDO", "SEMIADITIVA", 95),
    "DESPESA_LIQUIDADA": ("FLUXO_ACUMULADO", "ADITIVA", 98),
    "DESPESA_LIQUIDADA_NO_PERIODO": ("FLUXO_PERIODO", "ADITIVA", 100),
    "DESPESA_LIQUIDADA_ATE_PERIODO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 110),
    "DESPESA_LIQUIDADA_ATE_PERIODO_EX_ANT": ("FLUXO_ACUMULADO", "SEMIADITIVA", 111),
    "PCT_LIQUIDADA_TOTAL": ("PERCENTUAL", "NAO_ADITIVA", 112),
    "PCT_LIQUIDADA_III": ("PERCENTUAL", "NAO_ADITIVA", 113),
    "SALDO_DOTACAO_LIQUIDADA": ("SALDO", "SEMIADITIVA", 115),
    "DESPESA_PAGA": ("FLUXO_ACUMULADO", "ADITIVA", 118),
    "DESPESA_PAGA_ATE_PERIODO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 120),
    "INSCRICAO_RP_NAO_PROCESSADOS": ("FLUXO_ACUMULADO", "ADITIVA", 122),
    "INSCRICAO_RP_PROCESSADOS": ("FLUXO_ACUMULADO", "ADITIVA", 124),
    "MOVIMENTO_NO_PERIODO": ("FLUXO_PERIODO", "ADITIVA", 125),
    "VALOR_ATE_PERIODO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 126),
    "VALOR_APURADO_ATE_PERIODO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 127),
    "VALOR_APURADO_EXERCICIO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 128),
    "VALOR_INCORRIDO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 129),
    "VALOR_UNICO": ("ESTOQUE", "SEMIADITIVA", 130),
    "VALOR_APURADO_RGF": ("ESTOQUE", "SEMIADITIVA", 131),
    "VALOR_EXERCICIO_ATUAL": ("FLUXO_ACUMULADO", "ADITIVA", 132),
    "VALOR_EXERCICIO_ANTERIOR": ("FLUXO_ACUMULADO", "ADITIVA", 133),
    "APORTES_REALIZADOS": ("FLUXO_ACUMULADO", "SEMIADITIVA", 134),
    "RESULTADO_NO_PERIODO": ("FLUXO_PERIODO", "ADITIVA", 135),
    "RESULTADO_ATE_PERIODO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 136),
    "SALDO_EXERCICIO_ANTERIOR": ("ESTOQUE", "SEMIADITIVA", 140),
    "SALDO_PERIODO_ANTERIOR": ("ESTOQUE", "SEMIADITIVA", 141),
    "SALDO_FINAL": ("ESTOQUE", "SEMIADITIVA", 142),
    "ESTOQUE_EM_EX": ("ESTOQUE", "SEMIADITIVA", 143),
    "ESTOQUE_EM_EX_ANT": ("ESTOQUE", "SEMIADITIVA", 144),
    "ATE_1_QUADRIMESTRE": ("ESTOQUE", "SEMIADITIVA", 145),
    "ATE_2_QUADRIMESTRE": ("ESTOQUE", "SEMIADITIVA", 146),
    "ATE_3_QUADRIMESTRE": ("ESTOQUE", "SEMIADITIVA", 147),
    "ATE_1_SEMESTRE": ("ESTOQUE", "SEMIADITIVA", 148),
    "ATE_2_SEMESTRE": ("ESTOQUE", "SEMIADITIVA", 149),
    "MES_REF_MENOS_11": ("FLUXO_PERIODO", "ADITIVA", 151),
    "MES_REF_MENOS_10": ("FLUXO_PERIODO", "ADITIVA", 152),
    "MES_REF_MENOS_09": ("FLUXO_PERIODO", "ADITIVA", 153),
    "MES_REF_MENOS_08": ("FLUXO_PERIODO", "ADITIVA", 154),
    "MES_REF_MENOS_07": ("FLUXO_PERIODO", "ADITIVA", 155),
    "MES_REF_MENOS_06": ("FLUXO_PERIODO", "ADITIVA", 156),
    "MES_REF_MENOS_05": ("FLUXO_PERIODO", "ADITIVA", 157),
    "MES_REF_MENOS_04": ("FLUXO_PERIODO", "ADITIVA", 158),
    "MES_REF_MENOS_03": ("FLUXO_PERIODO", "ADITIVA", 159),
    "MES_REF_MENOS_02": ("FLUXO_PERIODO", "ADITIVA", 160),
    "MES_REF_MENOS_01": ("FLUXO_PERIODO", "ADITIVA", 161),
    "MES_REF_ATUAL": ("FLUXO_PERIODO", "ADITIVA", 162),
    "TOTAL_ULTIMOS_12_MESES": ("FLUXO_ACUMULADO", "SEMIADITIVA", 165),
    "PERCENTUAL_DECLARADO": ("PERCENTUAL", "NAO_ADITIVA", 170),
    "PERCENTUAL_RCL_AJUSTADA": ("PERCENTUAL", "NAO_ADITIVA", 171),
    "PCT_MINIMO_EXERCICIO": ("PERCENTUAL", "NAO_ADITIVA", 172),
    "PCT_META_FISCAL": ("PERCENTUAL", "NAO_ADITIVA", 173),
    "RPNP_INSCRITOS_EX_ANTERIORES": ("ESTOQUE", "SEMIADITIVA", 180),
    "RPNP_INSCRITOS_31DEZ_EX_ANT": ("ESTOQUE", "SEMIADITIVA", 181),
    "RPNP_LIQUIDADOS": ("FLUXO_ACUMULADO", "ADITIVA", 182),
    "RPNP_PAGOS": ("FLUXO_ACUMULADO", "ADITIVA", 183),
    "RPNP_CANCELADOS": ("FLUXO_ACUMULADO", "ADITIVA", 184),
    "RPNP_SALDO_FINAL": ("SALDO", "SEMIADITIVA", 185),
    "RPP_INSCRITOS_EX_ANTERIORES": ("ESTOQUE", "SEMIADITIVA", 186),
    "RPP_INSCRITOS_31DEZ_EX_ANT": ("ESTOQUE", "SEMIADITIVA", 187),
    "RPP_PAGOS": ("FLUXO_ACUMULADO", "ADITIVA", 188),
    "RPP_CANCELADOS": ("FLUXO_ACUMULADO", "ADITIVA", 189),
    "RPP_SALDO_FINAL": ("SALDO", "SEMIADITIVA", 190),
    "RP_SALDO_TOTAL": ("SALDO", "SEMIADITIVA", 191),
    "RP_INSCRICAO_SIMPLIFICADO": ("ESTOQUE", "SEMIADITIVA", 192),
    "RP_CANCELADOS_SIMPLIFICADO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 193),
    "RP_PAGOS_SIMPLIFICADO": ("FLUXO_ACUMULADO", "SEMIADITIVA", 194),
    "CAIXA_BRUTA": ("ESTOQUE", "SEMIADITIVA", 200),
    "RP_LIQUIDADOS_NAO_PAGOS_EX_ANT": ("ESTOQUE", "SEMIADITIVA", 201),
    "RP_LIQUIDADOS_NAO_PAGOS_EXERCICIO": ("ESTOQUE", "SEMIADITIVA", 202),
    "RPNP_EXERCICIOS_ANTERIORES": ("ESTOQUE", "SEMIADITIVA", 203),
    "DEMAIS_OBRIGACOES_FINANCEIRAS": ("ESTOQUE", "SEMIADITIVA", 204),
    "INSUFICIENCIA_CONSORCIO": ("ESTOQUE", "SEMIADITIVA", 205),
    "CAIXA_LIQUIDA_ANTES_RPNP": ("SALDO", "SEMIADITIVA", 206),
    "RPNP_DO_EXERCICIO": ("ESTOQUE", "SEMIADITIVA", 207),
    "EMPENHOS_NAO_LIQ_CANCELADOS_INSUF": ("FLUXO_ACUMULADO", "ADITIVA", 208),
    "CAIXA_LIQUIDA_APOS_RPNP": ("SALDO", "SEMIADITIVA", 209),
    "TRAJ_LIMITE_MAXIMO_A": ("PERCENTUAL", "NAO_ADITIVA", 220),
    "TRAJ_PCT_APURADO_B": ("PERCENTUAL", "NAO_ADITIVA", 221),
    "TRAJ_PCT_EXCEDENTE_C": ("PERCENTUAL", "NAO_ADITIVA", 222),
    "TRAJ_REDUTOR_MINIMO_D": ("PERCENTUAL", "NAO_ADITIVA", 223),
    "TRAJ_LIMITE_E": ("PERCENTUAL", "NAO_ADITIVA", 224),
    "TRAJ_PCT_APURADO_F": ("PERCENTUAL", "NAO_ADITIVA", 225),
    "TRAJ_REDUTOR_RESIDUAL_G": ("PERCENTUAL", "NAO_ADITIVA", 226),
    "TRAJ_LIMITE_H": ("PERCENTUAL", "NAO_ADITIVA", 227),
    "TRAJ_PCT_APURADO_I": ("PERCENTUAL", "NAO_ADITIVA", 228),
    "TRAJ_REDUTOR_RESIDUAL_J": ("PERCENTUAL", "NAO_ADITIVA", 229),
    "TRAJ_LIMITE_K": ("PERCENTUAL", "NAO_ADITIVA", 230),
    "TRAJ_PCT_APURADO_L": ("PERCENTUAL", "NAO_ADITIVA", 231),
    "TRAJ_EXERCICIO_REF": ("ESTOQUE", "SEMIADITIVA", 232),
    "REGRA_OURO_DOTACAO_PREVISAO": ("SALDO", "SEMIADITIVA", 240),
    "REGRA_OURO_EXECUCAO": ("SALDO", "SEMIADITIVA", 241),
    "REGRA_OURO_SALDO": ("SALDO", "SEMIADITIVA", 242),
    "RECEITA_PREVIDENCIARIA_PROJ": ("PREVISAO", "ADITIVA", 250),
    "DESPESA_PREVIDENCIARIA_PROJ": ("PREVISAO", "ADITIVA", 251),
    "RESULTADO_PREVIDENCIARIO_PROJ": ("SALDO", "ADITIVA", 252),
    "SALDO_FINANCEIRO_RPPS_PROJ": ("ESTOQUE", "SEMIADITIVA", 253),
    "PPP_EXERCICIO_ANTERIOR": ("FLUXO_ACUMULADO", "SEMIADITIVA", 260),
    "PPP_EXERCICIO_CORRENTE": ("PREVISAO", "SEMIADITIVA", 261),
    "PPP_EC_MAIS_01": ("PREVISAO", "SEMIADITIVA", 262),
    "PPP_EC_MAIS_02": ("PREVISAO", "SEMIADITIVA", 263),
    "PPP_EC_MAIS_03": ("PREVISAO", "SEMIADITIVA", 264),
    "PPP_EC_MAIS_04": ("PREVISAO", "SEMIADITIVA", 265),
    "PPP_EC_MAIS_05": ("PREVISAO", "SEMIADITIVA", 266),
    "PPP_EC_MAIS_06": ("PREVISAO", "SEMIADITIVA", 267),
    "PPP_EC_MAIS_07": ("PREVISAO", "SEMIADITIVA", 268),
    "PPP_EC_MAIS_08": ("PREVISAO", "SEMIADITIVA", 269),
    "PPP_EC_MAIS_09": ("PREVISAO", "SEMIADITIVA", 270),
    "PROJ_ATUARIAL_EX_ATUAL": ("PREVISAO", "SEMIADITIVA", 280),
    "PROJ_ATUARIAL_EX_10": ("PREVISAO", "SEMIADITIVA", 281),
    "PROJ_ATUARIAL_EX_20": ("PREVISAO", "SEMIADITIVA", 282),
    "PROJ_ATUARIAL_EX_35": ("PREVISAO", "SEMIADITIVA", 283),
}

_MR_COLS: list[tuple[str, str]] = [
    ("<MR-11>", "MES_REF_MENOS_11"),
    ("<MR-10>", "MES_REF_MENOS_10"),
    ("<MR-9>", "MES_REF_MENOS_09"),
    ("<MR-8>", "MES_REF_MENOS_08"),
    ("<MR-7>", "MES_REF_MENOS_07"),
    ("<MR-6>", "MES_REF_MENOS_06"),
    ("<MR-5>", "MES_REF_MENOS_05"),
    ("<MR-4>", "MES_REF_MENOS_04"),
    ("<MR-3>", "MES_REF_MENOS_03"),
    ("<MR-2>", "MES_REF_MENOS_02"),
    ("<MR-1>", "MES_REF_MENOS_01"),
    ("<MR>", "MES_REF_ATUAL"),
]

_DCA_DESP_COLS: list[tuple[str, str]] = [
    ("Despesas Empenhadas", "DESPESA_EMPENHADA"),
    ("Despesas Liquidadas", "DESPESA_LIQUIDADA"),
    ("Despesas Pagas", "DESPESA_PAGA"),
    ("Inscrição de RP Não Processados", "INSCRICAO_RP_NAO_PROCESSADOS"),
    ("Inscrição de RP Processados", "INSCRICAO_RP_PROCESSADOS"),
    ("Inscrição de Restos a Pagar Não Processados", "INSCRICAO_RP_NAO_PROCESSADOS"),
    ("Inscrição de Restos a Pagar Processados", "INSCRICAO_RP_PROCESSADOS"),
]

_DCA_RP_COLS: list[tuple[str, str]] = [
    ("Restos a Pagar Não Processados Cancelados", "RPNP_CANCELADOS"),
    (
        "Restos a Pagar Não Processados Inscritos em 31 de Dezembro do Exercício Anterior",
        "RPNP_INSCRITOS_31DEZ_EX_ANT",
    ),
    ("Restos a Pagar Não Processados Inscritos em Exercícios Anteriores", "RPNP_INSCRITOS_EX_ANTERIORES"),
    ("Restos a Pagar Não Processados Liquidados", "RPNP_LIQUIDADOS"),
    ("Restos a Pagar Não Processados Pagos", "RPNP_PAGOS"),
    ("Restos a Pagar Processados Cancelados", "RPP_CANCELADOS"),
    (
        "Restos a Pagar Processados Inscritos em 31 de Dezembro do Exercício Anterior",
        "RPP_INSCRITOS_31DEZ_EX_ANT",
    ),
    ("Restos a Pagar Processados Inscritos em Exercícios Anteriores", "RPP_INSCRITOS_EX_ANTERIORES"),
    ("Restos a Pagar Processados Pagos", "RPP_PAGOS"),
]

_RREO04_COLS: list[tuple[str, str]] = [
    ("APORTES REALIZADOS", "APORTES_REALIZADOS"),
    ("Aportes Realizados", "APORTES_REALIZADOS"),
    ("Até o Bimestre / {EX_ANT}", "RECEITA_ATE_PERIODO_EX_ANT"),
    ("Até o Bimestre / {EX}", "RECEITA_ATE_PERIODO"),
    ("DESPESAS EMPENHADAS ATÉ O BIMESTRE (d)", "DESPESA_EMPENHADA_ATE_PERIODO"),
    ("DESPESAS EMPENHADAS ATÉ O BIMESTRE / {EX_ANT}", "DESPESA_EMPENHADA_ATE_PERIODO_EX_ANT"),
    ("DESPESAS EMPENHADAS ATÉ O BIMESTRE / {EX}", "DESPESA_EMPENHADA_ATE_PERIODO"),
    ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE (e)", "DESPESA_LIQUIDADA_ATE_PERIODO"),
    ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE / {EX_ANT}", "DESPESA_LIQUIDADA_ATE_PERIODO_EX_ANT"),
    ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE / {EX}", "DESPESA_LIQUIDADA_ATE_PERIODO"),
    ("DESPESAS PAGAS ATÉ O BIMESTRE (f)", "DESPESA_PAGA_ATE_PERIODO"),
    ("DOTAÇÃO ATUALIZADA", "DOTACAO_ATUALIZADA"),
    ("DOTAÇÃO ATUALIZADA (c)", "DOTACAO_ATUALIZADA"),
    ("DOTAÇÃO INICIAL", "DOTACAO_INICIAL"),
    ("Em {EX_ANT}", "ESTOQUE_EM_EX_ANT"),
    ("Em {EX}", "ESTOQUE_EM_EX"),
    ("INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS NO EXERCÍCIO (g)", "INSCRICAO_RP_NAO_PROCESSADOS"),
    ("PREVISÃO ATUALIZADA", "PREVISAO_ATUALIZADA"),
    ("PREVISÃO ATUALIZADA (a)", "PREVISAO_ATUALIZADA"),
    ("PREVISÃO INICIAL", "PREVISAO_INICIAL"),
    ("PREVISÃO ORÇAMENTÁRIA", "PREVISAO_ORCAMENTARIA_RPPS"),
    ("Previsão Orçamentária", "PREVISAO_ORCAMENTARIA_RPPS"),
    ("RECEITAS REALIZADAS ATÉ O BIMESTRE (b)", "RECEITA_ATE_PERIODO"),
    ("SALDO ATUAL", "SALDO_FINAL"),
    ("{EX_ANT}", "VALOR_EXERCICIO_ANTERIOR"),
    ("{EX}", "VALOR_EXERCICIO_ATUAL"),
]


def build_coluna_map_rows() -> list[dict[str, str | int]]:
    pairs: list[tuple[str, str, str, str]] = []

    def add(fonte: str, anexo_cod: str, items: list[tuple[str, str]]) -> None:
        for col_orig, col_pad in items:
            pairs.append((fonte, anexo_cod, col_orig, col_pad))

    # DCA
    add("DCA", "DCA-I-AB", [("31/12/{EX}", "SALDO_FINAL")])
    add(
        "DCA",
        "DCA-I-C",
        [
            ("Deduções - FUNDEB", "DEDUCAO_FUNDEB"),
            ("Deduções - Transferências Constitucionais", "DEDUCAO_TRANSF_CONST"),
            ("Outras Deduções da Receita", "OUTRAS_DEDUCOES_RECEITA"),
            ("Receitas Brutas Realizadas", "RECEITA_BRUTA_REALIZADA"),
        ],
    )
    add("DCA", "DCA-I-D", _DCA_DESP_COLS)
    add("DCA", "DCA-I-E", _DCA_DESP_COLS)
    add("DCA", "DCA-I-F", _DCA_RP_COLS)
    add("DCA", "DCA-I-G", _DCA_RP_COLS)
    add("DCA", "DCA-I-HI", [("31/12/{EX}", "VALOR_EXERCICIO_ATUAL")])

    # RGF
    add(
        "RGF",
        "RGF-01",
        _MR_COLS
        + [
            ("% DTP (b)", "TRAJ_PCT_APURADO_B"),
            ("% DTP (f)", "TRAJ_PCT_APURADO_F"),
            ("% DTP (i)", "TRAJ_PCT_APURADO_I"),
            ("% Excedente (c) = (b-a)", "TRAJ_PCT_EXCEDENTE_C"),
            ("% sobre a RCL", "PERCENTUAL_DECLARADO"),
            ("% sobre a RCL Ajustada", "PERCENTUAL_RCL_AJUSTADA"),
            ("DESPESAS INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS (b)", "INSCRICAO_RP_NAO_PROCESSADOS"),
            ("DESPESAS LIQUIDADAS (a)", "TOTAL_ULTIMOS_12_MESES"),
            ("INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS (b)", "INSCRICAO_RP_NAO_PROCESSADOS"),
            ("LIQUIDADAS (a)", "TOTAL_ULTIMOS_12_MESES"),
            ("Limite (e) = (b-d)", "TRAJ_LIMITE_E"),
            ("Limite (h) = (a)", "TRAJ_LIMITE_H"),
            ("Limite Máximo (a)", "TRAJ_LIMITE_MAXIMO_A"),
            ("Redutor Mínimo de 1/3 do Excedente (d) = (1/3*c)", "TRAJ_REDUTOR_MINIMO_D"),
            ("Redutor Residual (g) = (f-a)", "TRAJ_REDUTOR_RESIDUAL_G"),
            ("TOTAL (ÚLTIMOS 12 MESES) (a)", "TOTAL_ULTIMOS_12_MESES"),
            ("Valor", "VALOR_UNICO"),
            ("VALOR", "VALOR_UNICO"),
            ("{EX}", "TRAJ_EXERCICIO_REF"),
        ],
    )
    _rgf_quad_cols = [
        ("SALDO DO EXERCÍCIO ANTERIOR", "SALDO_EXERCICIO_ANTERIOR"),
        ("Até o 1º Quadrimestre", "ATE_1_QUADRIMESTRE"),
        ("Até o 2º Quadrimestre", "ATE_2_QUADRIMESTRE"),
        ("Até o 3º Quadrimestre", "ATE_3_QUADRIMESTRE"),
        ("Até o 1º Semestre", "ATE_1_SEMESTRE"),
        ("Até o 2º Semestre", "ATE_2_SEMESTRE"),
    ]
    add(
        "RGF",
        "RGF-02",
        _rgf_quad_cols
        + [
            ("% DCL (b)", "TRAJ_PCT_APURADO_B"),
            ("% DCL (f)", "TRAJ_PCT_APURADO_F"),
            ("% DCL (i)", "TRAJ_PCT_APURADO_I"),
            ("% DCL (l)", "TRAJ_PCT_APURADO_L"),
            ("% Excedente (c) = (b-a)", "TRAJ_PCT_EXCEDENTE_C"),
            ("Limite (e) = (b-d)", "TRAJ_LIMITE_E"),
            ("Limite (h) = (e)", "TRAJ_LIMITE_H"),
            ("Limite (k) = (a)", "TRAJ_LIMITE_K"),
            ("Limite Máximo (a)", "TRAJ_LIMITE_MAXIMO_A"),
            ("Redutor Residual (g) = (f-a)", "TRAJ_REDUTOR_RESIDUAL_G"),
            ("Redutor Residual (j) = (i-a)", "TRAJ_REDUTOR_RESIDUAL_J"),
            ("Redutor mínimo de 25% do Excedente (d) = (0,25*c)", "TRAJ_REDUTOR_MINIMO_D"),
        ],
    )
    add("RGF", "RGF-03", _rgf_quad_cols)
    add(
        "RGF",
        "RGF-04",
        [
            ("% SOBRE A RCL", "PERCENTUAL_DECLARADO"),
            ("% SOBRE A RCL AJUSTADA", "PERCENTUAL_RCL_AJUSTADA"),
            ("Até o Quadrimestre de Referência (a)", "VALOR_ATE_PERIODO"),
            ("No Quadrimestre de Referência", "MOVIMENTO_NO_PERIODO"),
            ("VALOR", "VALOR_UNICO"),
        ],
    )
    add(
        "RGF",
        "RGF-05",
        [
            ("DISPONIBILIDADE DE CAIXA BRUTA (a)", "CAIXA_BRUTA"),
            ("Disponibilidade de Caixa Bruta", "CAIXA_BRUTA"),
            (
                "DISPONIBILIDADE DE CAIXA LÍQUIDA (ANTES DA INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO) (f)=(a-(b+c+d+e))",
                "CAIXA_LIQUIDA_ANTES_RPNP",
            ),
            (
                "DISPONIBILIDADE DE CAIXA LÍQUIDA (ANTES DA INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO) (g)=(a-(b+c+d+e)-f)",
                "CAIXA_LIQUIDA_ANTES_RPNP",
            ),
            ("Disponibilidade de Caixa Líquida", "CAIXA_LIQUIDA_ANTES_RPNP"),
            (
                "DISPONIBILIDADE DE CAIXA LÍQUIDA (APÓS A INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO) (h) = (f - g)",
                "CAIXA_LIQUIDA_APOS_RPNP",
            ),
            (
                "DISPONIBILIDADE DE CAIXA LÍQUIDA (APÓS A INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO) (i) = (g - h)",
                "CAIXA_LIQUIDA_APOS_RPNP",
            ),
            ("De Exercícios Anteriores (b)", "RP_LIQUIDADOS_NAO_PAGOS_EX_ANT"),
            ("Restos a Pagar Liquidados e Não Pagos de Exercícios Anteriores", "RP_LIQUIDADOS_NAO_PAGOS_EX_ANT"),
            ("Do Exercício (c)", "RP_LIQUIDADOS_NAO_PAGOS_EXERCICIO"),
            ("Restos a Pagar Liquidados e Não Pagos do Exercício", "RP_LIQUIDADOS_NAO_PAGOS_EXERCICIO"),
            ("Demais Obrigações Financeiras", "DEMAIS_OBRIGACOES_FINANCEIRAS"),
            ("Demais Obrigações Financeiras (e)", "DEMAIS_OBRIGACOES_FINANCEIRAS"),
            (
                "EMPENHOS NÃO LIQUIDADOS CANCELADOS (NÃO INSCRITOS POR INSUFICIÊNCIA FINANCEIRA)",
                "EMPENHOS_NAO_LIQ_CANCELADOS_INSUF",
            ),
            (
                "Empenhos Não Liquidados Cancelados (Não Inscritos por Insuficiência Financeira)",
                "EMPENHOS_NAO_LIQ_CANCELADOS_INSUF",
            ),
            ("INSUFICIÊNCIA FINANCEIRA VERIFICADA NO CONSÓRCIO PÚBLICO (f)", "INSUFICIENCIA_CONSORCIO"),
            ("RESTOS A PAGAR EMPENHADOS E NÃO LIQUIDADOS DO EXERCÍCIO", "RPNP_DO_EXERCICIO"),
            ("RESTOS A PAGAR EMPENHADOS E NÃO LIQUIDADOS DO EXERCÍCIO (g)", "RPNP_DO_EXERCICIO"),
            ("RESTOS A PAGAR EMPENHADOS E NÃO LIQUIDADOS DO EXERCÍCIO (h)", "RPNP_DO_EXERCICIO"),
            ("Restos a Pagar Empenhados e Não Liquidados do Exercício", "RPNP_DO_EXERCICIO"),
            ("Restos a Pagar Empenhados e Não Liquidados de Exercícios Anteriores", "RPNP_EXERCICIOS_ANTERIORES"),
            ("Restos a Pagar Empenhados e Não Liquidados de Exercícios Anteriores (d)", "RPNP_EXERCICIOS_ANTERIORES"),
        ],
    )
    add(
        "RGF",
        "RGF-06",
        [
            ("% SOBRE A RCL", "PERCENTUAL_DECLARADO"),
            ("% SOBRE A RCL AJUSTADA", "PERCENTUAL_RCL_AJUSTADA"),
            ("Apuração do Valor", "VALOR_APURADO_RGF"),
            ("Até o 1º Quadrimestre", "ATE_1_QUADRIMESTRE"),
            ("Até o 2º Quadrimestre", "ATE_2_QUADRIMESTRE"),
            ("Até o 3º Quadrimestre", "ATE_3_QUADRIMESTRE"),
            (
                "DISPONIBILIDADE DE CAIXA LÍQUIDA (ANTES DA INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO)",
                "CAIXA_LIQUIDA_ANTES_RPNP",
            ),
            (
                "DISPONIBILIDADE DE CAIXA LÍQUIDA (APÓS A INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO)",
                "CAIXA_LIQUIDA_APOS_RPNP",
            ),
            ("INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO", "INSCRICAO_RP_NAO_PROCESSADOS"),
            ("RESTOS A PAGAR EMPENHADOS E NÃO LIQUIDADOS DO EXERCÍCIO", "RPNP_DO_EXERCICIO"),
            ("VALOR", "VALOR_UNICO"),
            ("VALOR ATÉ O QUADRIMESTRE DE REFERÊNCIA", "VALOR_ATE_PERIODO"),
            ("Valor Até o Quadrimestre", "VALOR_ATE_PERIODO"),
            ("Valor até o Bimestre/Semestre", "VALOR_ATE_PERIODO"),
        ],
    )

    # RREO
    add(
        "RREO",
        "RREO-01",
        [
            ("% (b/a)", "PCT_RECEITA_NO_PERIODO"),
            ("% (c/a)", "PCT_RECEITA_ATE_PERIODO"),
            ("Até o Bimestre (c)", "RECEITA_ATE_PERIODO"),
            ("Até o Bimestre (f)", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("Até o Bimestre (h)", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DESPESAS EMPENHADAS ATÉ O BIMESTRE (f)", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("DESPESAS EMPENHADAS NO BIMESTRE", "DESPESA_EMPENHADA_NO_PERIODO"),
            ("DESPESAS LIQUIDADAS ATÉ O BIMESTR", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DESPESAS LIQUIDADAS NO BIMESTRE", "DESPESA_LIQUIDADA_NO_PERIODO"),
            ("DESPESAS PAGAS ATÉ O BIMESTRE (j)", "DESPESA_PAGA_ATE_PERIODO"),
            ("DOTAÇÃO ATUALIZADA (e)", "DOTACAO_ATUALIZADA"),
            ("DOTAÇÃO INICIAL (d)", "DOTACAO_INICIAL"),
            ("INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS (k)", "INSCRICAO_RP_NAO_PROCESSADOS"),
            ("No Bimestre (b)", "RECEITA_NO_PERIODO"),
            ("PREVISÃO ATUALIZADA (a)", "PREVISAO_ATUALIZADA"),
            ("PREVISÃO INICIAL", "PREVISAO_INICIAL"),
            ("SALDO (a-c)", "SALDO_A_REALIZAR"),
            ("SALDO (g) = (e-f)", "SALDO_DOTACAO_EMPENHADA"),
            ("SALDO (i) = (e-h)", "SALDO_DOTACAO_LIQUIDADA"),
        ],
    )
    add(
        "RREO",
        "RREO-02",
        [
            ("% (b/III b)", "PCT_EMPENHADA_III"),
            ("% (b/total b)", "PCT_EMPENHADA_TOTAL"),
            ("% (d/III d)", "PCT_LIQUIDADA_III"),
            ("% (d/Total d)", "PCT_LIQUIDADA_TOTAL"),
            ("% (d/total d)", "PCT_LIQUIDADA_TOTAL"),
            ("Até o Bimestre (b)", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("DESPESAS EMPENHADAS ATÉ O BIMESTRE (b)", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("DESPESAS EMPENHADAS NO BIMESTRE", "DESPESA_EMPENHADA_NO_PERIODO"),
            ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DESPESAS LIQUIDADAS NO BIMESTRE", "DESPESA_LIQUIDADA_NO_PERIODO"),
            ("DOTAÇÃO ATUALIZADA (a)", "DOTACAO_ATUALIZADA"),
            ("DOTAÇÃO INICIAL", "DOTACAO_INICIAL"),
            ("INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS (f)", "INSCRICAO_RP_NAO_PROCESSADOS"),
            ("No Bimestre", "MOVIMENTO_NO_PERIODO"),
            ("SALDO (c) = (a-b)", "SALDO_DOTACAO_EMPENHADA"),
            ("SALDO (e) = (a-d)", "SALDO_DOTACAO_LIQUIDADA"),
        ],
    )
    add(
        "RREO",
        "RREO-03",
        _MR_COLS
        + [
            ("PREVISÃO ATUALIZADA {EX}", "PREVISAO_ATUALIZADA"),
            ("TOTAL (ÚLTIMOS 12 MESES)", "TOTAL_ULTIMOS_12_MESES"),
        ],
    )
    add("RREO", "RREO-04", _RREO04_COLS)
    add("RREO", "RREO-04-1", _RREO04_COLS)
    add("RREO", "RREO-04-2", _RREO04_COLS)
    add(
        "RREO",
        "RREO-05",
        [
            ("Até o Bimestre (VIc - VIa)", "RESULTADO_ATE_PERIODO"),
            ("Até o Bimestre (c-a)", "RESULTADO_ATE_PERIODO"),
            ("Em 31/Dez/{EX_ANT} (a)", "SALDO_EXERCICIO_ANTERIOR"),
            ("No Bimestre (VIc - VIb)", "RESULTADO_NO_PERIODO"),
            ("No Bimestre (c)", "SALDO_FINAL"),
            ("No Bimestre (c-b)", "RESULTADO_NO_PERIODO"),
            ("No Bimestre Anterior (b)", "SALDO_PERIODO_ANTERIOR"),
            ("Valor Corrente", "VALOR_CORRENTE"),
        ],
    )
    add(
        "RREO",
        "RREO-06",
        [
            ("Até o Bimestre (VIc - VIa)", "RESULTADO_ATE_PERIODO"),
            ("Até o Bimestre (b)", "SALDO_FINAL"),
            ("Até o Bimestre / {EX_ANT}", "RECEITA_ATE_PERIODO_EX_ANT"),
            ("Até o Bimestre / {EX}", "RECEITA_ATE_PERIODO"),
            ("Até o Bimestre {EX} (b)", "SALDO_FINAL"),
            ("DESPESAS EMPENHADAS", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("DESPESAS EMPENHADAS ATÉ O BIMESTRE / {EX_ANT}", "DESPESA_EMPENHADA_ATE_PERIODO_EX_ANT"),
            ("DESPESAS EMPENHADAS ATÉ O BIMESTRE / {EX}", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("DESPESAS LIQUIDADAS", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE / {EX_ANT}", "DESPESA_LIQUIDADA_ATE_PERIODO_EX_ANT"),
            ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE / {EX}", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DESPESAS PAGAS (a)", "DESPESA_PAGA_ATE_PERIODO"),
            ("DOTAÇÃO ATUALIZADA", "DOTACAO_ATUALIZADA"),
            ("Despesas Empenhadas Até o Bimestre / {EX_ANT}", "DESPESA_EMPENHADA_ATE_PERIODO_EX_ANT"),
            ("Despesas Empenhadas Até o Bimestre / {EX}", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("Despesas Liquidadas Até o Bimestre / {EX_ANT}", "DESPESA_LIQUIDADA_ATE_PERIODO_EX_ANT"),
            ("Despesas Liquidadas Até o Bimestre / {EX}", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("Em 31/12/{EX_ANT} (a)", "SALDO_EXERCICIO_ANTERIOR"),
            ("Em {EX_ANT}", "ESTOQUE_EM_EX_ANT"),
            ("Em {EX}", "ESTOQUE_EM_EX"),
            ("LIQUIDADOS", "RPNP_LIQUIDADOS"),
            ("No Bimestre (VIc -VIb)", "RESULTADO_NO_PERIODO"),
            ("PAGOS (c)", "RPNP_PAGOS"),
            ("PREVISÃO ATUALIZADA", "PREVISAO_ATUALIZADA"),
            ("PREVISÃO ORÇAMENTÁRIA", "PREVISAO_ORCAMENTARIA_RPPS"),
            ("RECEITAS REALIZADAS (a)", "RECEITA_ATE_PERIODO"),
            ("RESTOS A PAGAR PROCESSADOS PAGOS (b)", "RPP_PAGOS"),
            ("VALOR", "VALOR_UNICO"),
            ("VALOR CORRENTE", "VALOR_CORRENTE"),
            ("VALOR INCORRIDO", "VALOR_INCORRIDO"),
            ("Valor Corrente", "VALOR_CORRENTE"),
        ],
    )
    add(
        "RREO",
        "RREO-07",
        [
            ("Cancelados (d)", "RPP_CANCELADOS"),
            ("Cancelados (j)", "RPNP_CANCELADOS"),
            ("Em 31 de Dezembro de {EX_ANT} (b)", "RPP_INSCRITOS_31DEZ_EX_ANT"),
            ("Em 31 de Dezembro de {EX_ANT} (g)", "RPNP_INSCRITOS_31DEZ_EX_ANT"),
            ("Em 31 de dezembro de {EX_ANT} (b)", "RPP_INSCRITOS_31DEZ_EX_ANT"),
            ("Em 31 de dezembro de {EX_ANT} (g)", "RPNP_INSCRITOS_31DEZ_EX_ANT"),
            ("Em Exercícios Anteriores (a)", "RPP_INSCRITOS_EX_ANTERIORES"),
            ("Em Exercícios Anteriores (f)", "RPNP_INSCRITOS_EX_ANTERIORES"),
            ("Liquidados (h)", "RPNP_LIQUIDADOS"),
            ("Pagos (c)", "RPP_PAGOS"),
            ("Pagos (i)", "RPNP_PAGOS"),
            ("RPNP - Cancelados", "RPNP_CANCELADOS"),
            ("RPNP - Inscritos Em 31 de Dezembro de {EX_ANT}", "RPNP_INSCRITOS_31DEZ_EX_ANT"),
            ("RPNP - Inscritos Em Exercícios Anteriores", "RPNP_INSCRITOS_EX_ANTERIORES"),
            ("RPNP - Liquidados", "RPNP_LIQUIDADOS"),
            ("RPNP - Pagos", "RPNP_PAGOS"),
            ("RPP e RPNP Liquidados Em Exercícios Anteriores - Cancelados", "RPP_CANCELADOS"),
            ("RPP e RPNP Liquidados Em Exercícios Anteriores - Pagos", "RPP_PAGOS"),
            (
                "RPP e RPNP Liquidados em Exercícios Anteriores - Inscritos Em 31 de Dezembro de {EX_ANT}",
                "RPP_INSCRITOS_31DEZ_EX_ANT",
            ),
            (
                "RPP e RPNP Liquidados em Exercícios Anteriores - Inscritos Em Exercícios Anteriores",
                "RPP_INSCRITOS_EX_ANTERIORES",
            ),
            ("Saldo (a)", "RPP_SALDO_FINAL"),
            ("Saldo (b)", "RPNP_SALDO_FINAL"),
            ("Saldo Total (a+b)", "RP_SALDO_TOTAL"),
            ("Saldo Total L = (e + k)", "RP_SALDO_TOTAL"),
            ("Saldo e = (a + b) - (c + d)", "RPP_SALDO_FINAL"),
            ("Saldo e = (a+ b) - (c + d)", "RPP_SALDO_FINAL"),
            ("Saldo k = (f + g) - (i + j)", "RPNP_SALDO_FINAL"),
        ],
    )
    add(
        "RREO",
        "RREO-09",
        [
            ("(a - d)", "REGRA_OURO_DOTACAO_PREVISAO"),
            ("(b - e)", "REGRA_OURO_EXECUCAO"),
            ("(c - f)", "REGRA_OURO_SALDO"),
            ("(d - a)", "REGRA_OURO_DOTACAO_PREVISAO"),
            ("(e - b)", "REGRA_OURO_EXECUCAO"),
            ("(f - c)", "REGRA_OURO_SALDO"),
            ("DESPESAS EMPENHADAS (e)", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("DESPESAS INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS", "INSCRICAO_RP_NAO_PROCESSADOS"),
            ("DESPESAS LIQUIDADAS", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DOTAÇÃO ATUALIZADA (d)", "DOTACAO_ATUALIZADA"),
            ("PREVISÃO ATUALIZADA (a)", "PREVISAO_ATUALIZADA"),
            ("RECEITAS REALIZADAS (b)", "RECEITA_ATE_PERIODO"),
            ("SALDO NÃO EXECUTADO (f) = (d - e)", "SALDO_DOTACAO_EMPENHADA"),
            ("SALDO NÃO REALIZADO (c) = (a - b)", "SALDO_NAO_REALIZADO"),
        ],
    )
    add(
        "RREO",
        "RREO-10",
        [
            ("DESPESAS PREVIDENCIÁRIAS (b)", "DESPESA_PREVIDENCIARIA_PROJ"),
            ("RECEITAS PREVIDENCIÁRIAS (a)", "RECEITA_PREVIDENCIARIA_PROJ"),
            ("RESULTADO PREVIDENCIÁRIO (c) = (a - b)", "RESULTADO_PREVIDENCIARIO_PROJ"),
            ('SALDO FINANCEIRO DO EXERCÍCIO (d) = ("d" exercício Anterior) + (c)', "SALDO_FINANCEIRO_RPPS_PROJ"),
        ],
    )
    add(
        "RREO",
        "RREO-11",
        [
            ("DESPESAS EMPENHADAS", "DESPESA_EMPENHADA_ATE_PERIODO"),
            ("DESPESAS INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS", "INSCRICAO_RP_NAO_PROCESSADOS"),
            ("DESPESAS LIQUIDADAS", "DESPESA_LIQUIDADA_ATE_PERIODO"),
            ("DESPESAS PAGAS (e)", "DESPESA_PAGA_ATE_PERIODO"),
            ("DOTAÇÃO ATUALIZADA (d)", "DOTACAO_ATUALIZADA"),
            ("PREVISÃO ATUALIZADA (a)", "PREVISAO_ATUALIZADA"),
            ("RECEITAS REALIZADAS (b)", "RECEITA_ATE_PERIODO"),
            ("SALDO (c) = (a - b)", "SALDO_A_REALIZAR"),
            ("SALDO (h) = (d-e)", "SALDO_A_PAGAR"),
            ("SALDO A PAGAR (g) = (d-e)", "SALDO_A_PAGAR"),
            ("SALDO A REALIZAR (c) = (a - b)", "SALDO_A_REALIZAR"),
            ("SALDO ATUAL (j) = (IIIh + IIIi)", "SALDO_FINAL"),
            ("SALDO ATUAL (k) = (IIIi + IIIj)", "SALDO_FINAL"),
            ("{EX_ANT} (h)", "SALDO_EXERCICIO_ANTERIOR"),
            ("{EX_ANT} (i)", "SALDO_EXERCICIO_ANTERIOR"),
            ("{EX} (i) = (Ib - (IIe + IIf))", "RESULTADO_ATE_PERIODO"),
            ("{EX} (j) = (Ib - (IIf + IIg))", "RESULTADO_ATE_PERIODO"),
        ],
    )
    add(
        "RREO",
        "RREO-13",
        [
            ("<EC + 1>", "PPP_EC_MAIS_01"),
            ("<EC + 2>", "PPP_EC_MAIS_02"),
            ("<EC + 3>", "PPP_EC_MAIS_03"),
            ("<EC + 4>", "PPP_EC_MAIS_04"),
            ("<EC + 5>", "PPP_EC_MAIS_05"),
            ("<EC + 6>", "PPP_EC_MAIS_06"),
            ("<EC + 7>", "PPP_EC_MAIS_07"),
            ("<EC + 8>", "PPP_EC_MAIS_08"),
            ("<EC + 9>", "PPP_EC_MAIS_09"),
            ("Até o Bimestre", "VALOR_ATE_PERIODO"),
            ("EXERCÍCIO ANTERIOR", "PPP_EXERCICIO_ANTERIOR"),
            ("EXERCÍCIO CORRENTE (EC)", "PPP_EXERCICIO_CORRENTE"),
            ("No Bimestre", "MOVIMENTO_NO_PERIODO"),
            ("SALDO FINAL ATÉ O BIMESTRE", "SALDO_FINAL"),
            ("SALDO TOTAL EM 31 DE DEZEMBRO DO EXERCÍCIO ANTERIOR", "SALDO_EXERCICIO_ANTERIOR"),
        ],
    )
    add(
        "RREO",
        "RREO-14",
        [
            ("% Aplicado Até o Bimestre", "PERCENTUAL_DECLARADO"),
            ("% Mínimo a Aplicar no Exercício", "PCT_MINIMO_EXERCICIO"),
            ("% em Relação à Meta (b/a)", "PCT_META_FISCAL"),
            ("10º Exercício", "PROJ_ATUARIAL_EX_10"),
            ("20º Exercício", "PROJ_ATUARIAL_EX_20"),
            ("28/02/{EX}", "SALDO_FINAL"),
            ("29/02/{EX}", "SALDO_FINAL"),
            ("30/04/{EX}", "SALDO_FINAL"),
            ("30/06/{EX}", "SALDO_FINAL"),
            ("31/08/{EX}", "SALDO_FINAL"),
            ("31/10/{EX}", "SALDO_FINAL"),
            ("31/12/{EX}", "SALDO_FINAL"),
            ("35º Exercício", "PROJ_ATUARIAL_EX_35"),
            ("Até o Bimestre", "VALOR_ATE_PERIODO"),
            ("Cancelamento Até o Bimestre", "RP_CANCELADOS_SIMPLIFICADO"),
            ("Exercício", "PROJ_ATUARIAL_EX_ATUAL"),
            ("Inscrição", "RP_INSCRICAO_SIMPLIFICADO"),
            ("Meta Fixada no Anexo de Metas Fiscais da LDO (a)", "META_FISCAL_LDO"),
            ("Pagamento Até o Bimestre", "RP_PAGOS_SIMPLIFICADO"),
            ("Resultado Apurado até o Bimestre (b)", "RESULTADO_ATE_PERIODO"),
            ("Saldo Não Realizado", "SALDO_NAO_REALIZADO"),
            ("Saldo a Pagar", "SALDO_A_PAGAR"),
            ("Saldo a Realizar", "SALDO_A_REALIZAR"),
            ("Valor Apurado Até o Bimestre", "VALOR_APURADO_ATE_PERIODO"),
            ("Valor Apurado no Exercício", "VALOR_APURADO_EXERCICIO"),
            ("Valor Apurado no Exercício Corrente", "VALOR_APURADO_EXERCICIO"),
        ],
    )

    seen: set[tuple[str, str, str]] = set()
    rows: list[dict[str, str | int]] = []
    for fonte, anexo_cod, col_orig, col_pad in pairs:
        col_norm = normalize_text(col_orig)
        key = (fonte, anexo_cod, col_norm)
        if key in seen:
            continue
        seen.add(key)
        tipo_medida, aditividade, ordem = COLUNA_PADRAO_META[col_pad]
        rows.append(
            {
                "fonte": fonte,
                "anexo_codigo": anexo_cod,
                "coluna_origem": col_norm,
                "coluna_padrao": col_pad,
                "tipo_medida": tipo_medida,
                "aditividade": aditividade,
                "ordem_exibicao": ordem,
            }
        )
    return rows


def write_seed_coluna_map(seeds_dir: Path) -> int:
    seeds_dir.mkdir(parents=True, exist_ok=True)
    rows = build_coluna_map_rows()
    out = seeds_dir / "seed_coluna_map.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "fonte",
                "anexo_codigo",
                "coluna_origem",
                "coluna_padrao",
                "tipo_medida",
                "aditividade",
                "ordem_exibicao",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
