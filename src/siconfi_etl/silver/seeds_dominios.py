from __future__ import annotations

import csv
from pathlib import Path

from siconfi_etl.silver.normalizer import ANEXO_SLUG_MAP

# Fontes de recursos do RGF-05 observadas nos 6 municipios (2015-2026)
# Tupla: (cod_fonte, nome_fonte_origem, ex_ini, ex_fim, cod_fonte_padrao, nome_fonte, grupo, vinculada, eh_total)
FONTE_RECURSO_ROWS: list[tuple[str, str, int, int, str, str, str, int, int]] = [
    # Totais / Subtotais (cod_fonte='0', eh_total_anexo05=1)
    ("0", "INSUFICIÊNCIA DE CAIXA DO CONSÓRCIO PÚBLICO (VI) = (IV + V)", 2015, 2099, "TOT_INSUF_CONSORCIO_VI", "Insuficiência de Caixa do Consórcio Público", "", 0, 1),
    ("0", "TOTAL (III) = (I + II)", 2015, 2099, "TOT_GERAL_III", "Total Geral de Disponibilidade de Caixa", "", 0, 1),
    ("0", "TOTAL (IV) = (I + II + III)", 2015, 2099, "TOT_GERAL_IV", "Total Geral de Disponibilidade de Caixa", "", 0, 1),
    ("0", "TOTAL DO ENTE MAIS CONSÓRCIO PÚBLICO (VII) = (III + IV)", 2015, 2099, "TOT_ENTE_MAIS_CONSORCIO_VII", "Total do Ente mais Consórcio Público", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS NÃO VINCULADOS (I)", 2015, 2099, "TOT_NAO_VINCULADOS_I", "Total dos Recursos Não Vinculados", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS NÃO VINCULADOS (II)", 2015, 2099, "TOT_NAO_VINCULADOS_II", "Total dos Recursos Não Vinculados", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS NÃO VINCULADOS (V)", 2015, 2099, "TOT_NAO_VINCULADOS_V", "Total dos Recursos Não Vinculados (Consórcio)", "", 0, 1),
    ("0", "Total dos Recursos Não Vinculados", 2015, 2099, "TOT_NAO_VINCULADOS", "Total dos Recursos Não Vinculados", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS VINCULADOS (EXCETO AO RPPS) (II)", 2015, 2099, "TOT_VINCULADOS_EXC_RPPS_II", "Total dos Recursos Vinculados (Exceto RPPS)", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS VINCULADOS (I)", 2015, 2099, "TOT_VINCULADOS_I", "Total dos Recursos Vinculados", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS VINCULADOS (II)", 2015, 2099, "TOT_VINCULADOS_II", "Total dos Recursos Vinculados", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS VINCULADOS (IV)", 2015, 2099, "TOT_VINCULADOS_IV", "Total dos Recursos Vinculados (Consórcio)", "", 0, 1),
    ("0", "TOTAL DOS RECURSOS VINCULADOS AO RPPS (III)", 2015, 2099, "TOT_VINCULADOS_RPPS_III", "Total dos Recursos Vinculados ao RPPS", "", 0, 1),
    ("0", "Total dos Recursos", 2015, 2099, "TOT_GERAL_SIMPLES", "Total Geral de Recursos", "", 0, 1),
    ("0", "Total dos Recursos Vinculados", 2015, 2099, "TOT_VINCULADOS", "Total dos Recursos Vinculados", "", 0, 1),
    # Recursos Livres (vinculada=0)
    ("1500.00", "Recursos Não Vinculados de Impostos", 2015, 2099, "FR_LIVRE", "Recursos Não Vinculados (Ordinários / Impostos)", "LIVRE", 0, 0),
    ("1500.01", "ORDINÁRIO", 2015, 2099, "FR_LIVRE", "Recursos Ordinários", "LIVRE", 0, 0),
    ("1500.02", "ORDINÁRIO/PRÓPRIO", 2015, 2099, "FR_LIVRE", "Recursos Ordinários / Próprios", "LIVRE", 0, 0),
    ("1500.03", "PROPRIO", 2015, 2099, "FR_LIVRE", "Recursos Próprios", "LIVRE", 0, 0),
    ("1500.04", "PRÓPRIO/ORDINÁRIO", 2015, 2099, "FR_LIVRE", "Recursos Próprios / Ordinários", "LIVRE", 0, 0),
    ("1500.05", "PRÓPRIOS", 2015, 2099, "FR_LIVRE", "Recursos Próprios", "LIVRE", 0, 0),
    ("1500.06", "Recursos Ordinários - Tesouro", 2015, 2099, "FR_LIVRE", "Recursos Ordinários - Tesouro", "LIVRE", 0, 0),
    ("1500.07", "Recursos Ordinários", 2015, 2099, "FR_LIVRE", "Recursos Ordinários", "LIVRE", 0, 0),
    ("1501.00", "Outros Recursos não Vinculados", 2015, 2099, "FR_OUTROS_LIVRES", "Outros Recursos Não Vinculados", "LIVRE", 0, 0),
    # Educacao (vinculada=1)
    ("1500.1001", "Receitas de Impostos e de Transferência de Impostos - Educação", 2015, 2099, "FR_MDE_IMPOSTOS", "Impostos e Transferências - Educação (MDE)", "EDUCACAO", 1, 0),
    ("1540.00", "Transferências do FUNDEB", 2015, 2099, "FR_FUNDEB", "Transferências do FUNDEB", "EDUCACAO", 1, 0),
    ("1540.60", "Transferências do FUNDEB 60%", 2015, 2099, "FR_FUNDEB", "Transferências do FUNDEB (Magistério 60%)", "EDUCACAO", 1, 0),
    ("1540.40", "Transferências do FUNDEB 40%", 2015, 2099, "FR_FUNDEB", "Transferências do FUNDEB (Demais 40%)", "EDUCACAO", 1, 0),
    ("1550.00", "Recursos Vinculados à Educação", 2015, 2099, "FR_OUTROS_EDUCACAO", "Recursos Vinculados à Educação", "EDUCACAO", 1, 0),
    ("1550.01", "Outros Recursos Vinculados à Educação", 2015, 2099, "FR_OUTROS_EDUCACAO", "Outros Recursos Vinculados à Educação", "EDUCACAO", 1, 0),
    ("1550.02", "Outros Recursos Destinados à Educação", 2015, 2099, "FR_OUTROS_EDUCACAO", "Outros Recursos Destinados à Educação", "EDUCACAO", 1, 0),
    # Saude (vinculada=1)
    ("1500.1002", "Receitas de Impostos e de Transferência de Impostos - Saúde", 2015, 2099, "FR_ASPS_IMPOSTOS", "Impostos e Transferências - Saúde (ASPS)", "SAUDE", 1, 0),
    ("1600.00", "Transferências Fundo a Fundo de Recursos do SUS", 2015, 2099, "FR_SUS", "Transferências Fundo a Fundo do SUS", "SAUDE", 1, 0),
    ("1600.01", "Recursos Vinculados à Saúde", 2015, 2099, "FR_OUTROS_SAUDE", "Recursos Vinculados à Saúde", "SAUDE", 1, 0),
    ("1600.02", "Outros Recursos Vinculados à Saúde", 2015, 2099, "FR_OUTROS_SAUDE", "Outros Recursos Vinculados à Saúde", "SAUDE", 1, 0),
    ("1600.03", "Outros Recursos Destinados à Saúde", 2015, 2099, "FR_OUTROS_SAUDE", "Outros Recursos Destinados à Saúde", "SAUDE", 1, 0),
    # Previdencia (vinculada=1)
    ("1800.00", "Recursos Vinculados ao RPPS", 2015, 2099, "FR_RPPS", "Recursos Vinculados ao RPPS", "PREVIDENCIA", 1, 0),
    ("1800.01", "REGIME PRÓPRIO DE PREVIDÊNCIA DOS SERVIDORES¹", 2015, 2099, "FR_RPPS", "Regime Próprio de Previdência dos Servidores (RPPS)", "PREVIDENCIA", 1, 0),
    ("1800.10", "Recursos Vinculados ao RPPS - Fundo em Capitalização (Plano Previdenciário)", 2015, 2099, "FR_RPPS_PREV", "RPPS - Fundo em Capitalização (Plano Previdenciário)", "PREVIDENCIA", 1, 0),
    ("1800.11", "Recursos destinados ao RPPS - Plano Previdenciário", 2015, 2099, "FR_RPPS_PREV", "RPPS - Plano Previdenciário", "PREVIDENCIA", 1, 0),
    ("1800.12", "Recursos Destinados ao RPPS - Plano Previdenciário", 2015, 2099, "FR_RPPS_PREV", "RPPS - Plano Previdenciário", "PREVIDENCIA", 1, 0),
    ("1800.13", "Recursos Vinculados ao RPPS - Plano Previdenciário", 2015, 2099, "FR_RPPS_PREV", "RPPS - Plano Previdenciário", "PREVIDENCIA", 1, 0),
    ("1801.10", "Recursos Vinculados ao RPPS - Fundo em Repartição (Plano Financeiro)", 2015, 2099, "FR_RPPS_FIN", "RPPS - Fundo em Repartição (Plano Financeiro)", "PREVIDENCIA", 1, 0),
    ("1801.11", "Recursos Destinados ao RPPS - Plano Financeiro", 2015, 2099, "FR_RPPS_FIN", "RPPS - Plano Financeiro", "PREVIDENCIA", 1, 0),
    ("1801.12", "Recursos Vinculados ao RPPS - Plano Financeiro", 2015, 2099, "FR_RPPS_FIN", "RPPS - Plano Financeiro", "PREVIDENCIA", 1, 0),
    ("1802.00", "Recursos Vinculados ao RPPS - Taxa de Administração", 2015, 2099, "FR_RPPS_TAXA_ADM", "RPPS - Taxa de Administração", "PREVIDENCIA", 1, 0),
    ("1803.00", "Recursos Vinculados à Previdência Social (Exceto ao RPPS)", 2015, 2099, "FR_PREV_EXCETO_RPPS", "Previdência Social (Exceto RPPS)", "PREVIDENCIA", 1, 0),
    # Outras Vinculadas (vinculada=1)
    ("1660.00", "Recursos Vinculados à Assistência Social", 2015, 2099, "FR_ASSISTENCIA_SOCIAL", "Recursos Vinculados à Assistência Social", "OUTRAS_VINCULADAS", 1, 0),
    ("1660.01", "Recursos Destinados à Assistência Social", 2015, 2099, "FR_ASSISTENCIA_SOCIAL", "Recursos Destinados à Assistência Social", "OUTRAS_VINCULADAS", 1, 0),
    ("1700.00", "Transferências de Convênios e Instrumentos Congêneres (exceto Educação, Saúde e Assistência)", 2015, 2099, "FR_CONVENIOS", "Transferências de Convênios e Congêneres", "OUTRAS_VINCULADAS", 1, 0),
    ("1754.00", "Recursos de Operações de Crédito (exceto vinculados à Educação e à Saúde)", 2015, 2099, "FR_OP_CREDITO", "Recursos de Operações de Crédito", "OUTRAS_VINCULADAS", 1, 0),
    ("1754.01", "Recursos de Operações de Crédito (exceto destinados à Educação e à Saúde)", 2015, 2099, "FR_OP_CREDITO", "Recursos de Operações de Crédito", "OUTRAS_VINCULADAS", 1, 0),
    ("1755.00", "Recursos de Alienação de Bens/Ativos", 2015, 2099, "FR_ALIENACAO_ATIVOS", "Recursos de Alienação de Bens/Ativos", "OUTRAS_VINCULADAS", 1, 0),
    ("1759.01", "Demais Vinculações Legais", 2015, 2099, "FR_OUTRAS_VINC_LEGAIS", "Demais Vinculações Legais", "OUTRAS_VINCULADAS", 1, 0),
    ("1759.02", "Outras Vinculações Legais", 2015, 2099, "FR_OUTRAS_VINC_LEGAIS", "Outras Vinculações Legais", "OUTRAS_VINCULADAS", 1, 0),
    ("1759.10", "Recursos Vinculados a Fundos", 2015, 2099, "FR_FUNDOS_ESPECIAIS", "Recursos Vinculados a Fundos", "OUTRAS_VINCULADAS", 1, 0),
    ("1759.11", "Recursos Vinculados a Fundos (exceto Educação, Saúde, Assistência e Previdência)", 2015, 2099, "FR_FUNDOS_ESPECIAIS", "Recursos Vinculados a Fundos (Exceto Sociais/Prev.)", "OUTRAS_VINCULADAS", 1, 0),
    ("1799.01", "Demais Vinculações Decorrentes de Transferências", 2015, 2099, "FR_OUTRAS_TRANSF_VINC", "Demais Vinculações Decorrentes de Transferências", "OUTRAS_VINCULADAS", 1, 0),
    ("1799.02", "Outras Vinculações Decorrentes de Transferências", 2015, 2099, "FR_OUTRAS_TRANSF_VINC", "Outras Vinculações Decorrentes de Transferências", "OUTRAS_VINCULADAS", 1, 0),
    ("1799.10", "Outras Destinações Vinculadas de Recursos", 2015, 2099, "FR_OUTRAS_VINC", "Outras Destinações Vinculadas de Recursos", "OUTRAS_VINCULADAS", 1, 0),
    ("1799.11", "Outras Vinculações", 2015, 2099, "FR_OUTRAS_VINC", "Outras Vinculações", "OUTRAS_VINCULADAS", 1, 0),
    ("1799.12", "Outros Recursos Vinculados", 2015, 2099, "FR_OUTRAS_VINC", "Outros Recursos Vinculados", "OUTRAS_VINCULADAS", 1, 0),
    ("1899.00", "Recursos Extraorçamentários", 2015, 2099, "FR_EXTRAORCAMENTARIO", "Recursos Extraorçamentários", "OUTRAS_VINCULADAS", 1, 0),
    ("1899.01", "Outros Recursos Extraorçamentários", 2015, 2099, "FR_EXTRAORCAMENTARIO", "Outros Recursos Extraorçamentários", "OUTRAS_VINCULADAS", 1, 0),
]

LIMITE_LRF_ROWS: list[tuple[str, str, str, str, str, str, str, str, str, str]] = [
    ("PESSOAL_EXECUTIVO", "Despesa Total com Pessoal - Poder Executivo Municipal", "54.000000", "48.600000", "51.300000", "MAXIMO", "RCL_AJUSTADA", "2000-05-05", "", "LRF arts. 19, III, 20, III, b, 22, par. unico e 59, par. 1, II"),
    ("PESSOAL_LEGISLATIVO", "Despesa Total com Pessoal - Poder Legislativo Municipal", "6.000000", "5.400000", "5.700000", "MAXIMO", "RCL_AJUSTADA", "2000-05-05", "", "LRF arts. 19, III, 20, III, a, 22, par. unico e 59, par. 1, II"),
    ("PESSOAL_TOTAL", "Despesa Total com Pessoal - Ente Municipal Consolidado", "60.000000", "54.000000", "57.000000", "MAXIMO", "RCL_AJUSTADA", "2000-05-05", "", "LRF arts. 19, III e 20, III"),
    ("DCL_RCL", "Dívida Consolidada Líquida sobre a RCL Ajustada", "120.000000", "108.000000", "", "MAXIMO", "RCL_AJUSTADA", "2001-12-21", "", "Resolucao SF n. 40/2001, art. 3, II; LRF art. 59, par. 1, III"),
    ("GARANTIAS_RCL", "Garantias Concedidas sobre a RCL Ajustada", "22.000000", "19.800000", "", "MAXIMO", "RCL_AJUSTADA", "2001-12-26", "", "Resolucao SF n. 43/2001, art. 9; LRF art. 59, par. 1, III"),
    ("OP_CREDITO_RCL", "Operações de Crédito Internas e Externas no Exercício sobre a RCL Ajustada", "16.000000", "14.400000", "", "MAXIMO", "RCL_AJUSTADA", "2001-12-26", "", "Resolucao SF n. 43/2001, art. 7, I; LRF art. 59, par. 1, III"),
    ("ARO_RCL", "Operações de Crédito por Antecipação de Receita Orçamentária (ARO) sobre a RCL Ajustada", "7.000000", "6.300000", "", "MAXIMO", "RCL_AJUSTADA", "2001-12-26", "", "Resolucao SF n. 43/2001, art. 10"),
    ("EDUCACAO_MIN", "Aplicação Mínima Constitucional em Manutenção e Desenvolvimento do Ensino (MDE)", "25.000000", "", "", "MINIMO", "RECEITA_IMPOSTOS", "1988-10-05", "", "CF/88, art. 212, caput"),
    ("SAUDE_MIN", "Aplicação Mínima Constitucional em Ações e Serviços Públicos de Saúde (ASPS)", "15.000000", "", "", "MINIMO", "RECEITA_IMPOSTOS", "2012-01-13", "", "CF/88, art. 198, par. 2, III; LC n. 141/2012, art. 7"),
    ("CAIXA_LIQ_MIN", "Disponibilidade de Caixa Líquida (Suficiência Financeira antes da Inscrição de RPNP)", "0.000000", "", "", "MINIMO", "CAIXA_LIQUIDA", "2000-05-05", "", "LRF art. 42 e art. 55, III, a"),
]

# Catalogo completo de 37 indicadores:
# - 10 GOLD_MATERIALIZADO (LRF + Minimos Constitucionais)
# - 20 DAX (Quocientes Kohama do TCC Aguiar 2025: Q01-Q20, com Q09-Q11 via proxies RGF-05/DCA-I-AB)
# - 7 DAX (Indicadores complementares de gestao fiscal - Secao 8 do Guia)
INDICADOR_ROWS: list[tuple[str, str, str, str, str, str, str, str, str, str, int]] = [
    # 1. GOLD_MATERIALIZADO (10)
    ("PESSOAL_RCL_EXEC", "Despesa com Pessoal / RCL (Executivo)", "Comprometimento da RCL Ajustada com pessoal do Poder Executivo.", "DTP Executivo / RCL Ajustada * 100", "PERCENTUAL", "MENOR_MELHOR", "54.000000", "RGF-01", "LRF_PESSOAL", "GOLD_MATERIALIZADO", 1),
    ("PESSOAL_RCL_LEG", "Despesa com Pessoal / RCL (Legislativo)", "Comprometimento da RCL Ajustada com pessoal do Poder Legislativo.", "DTP Legislativo / RCL Ajustada * 100", "PERCENTUAL", "MENOR_MELHOR", "6.000000", "RGF-01", "LRF_PESSOAL", "GOLD_MATERIALIZADO", 2),
    ("PESSOAL_RCL_CONS", "Despesa com Pessoal / RCL (Consolidado)", "Comprometimento consolidado da RCL Ajustada com pessoal do Município.", "(DTP Executivo + DTP Legislativo) / RCL Ajustada * 100", "PERCENTUAL", "MENOR_MELHOR", "60.000000", "RGF-01", "LRF_PESSOAL", "GOLD_MATERIALIZADO", 3),
    ("DCL_RCL", "Dívida Consolidada Líquida / RCL", "Relação entre a Dívida Consolidada Líquida e a RCL Ajustada.", "DCL / RCL Ajustada * 100", "PERCENTUAL", "MENOR_MELHOR", "120.000000", "RGF-02", "LRF_DIVIDA", "GOLD_MATERIALIZADO", 4),
    ("GARANTIAS_RCL", "Garantias Concedidas / RCL", "Saldo de garantias concedidas em proporção à RCL Ajustada.", "Garantias Concedidas / RCL Ajustada * 100", "PERCENTUAL", "MENOR_MELHOR", "22.000000", "RGF-03", "LRF_DIVIDA", "GOLD_MATERIALIZADO", 5),
    ("OP_CREDITO_RCL", "Operações de Crédito / RCL", "Operações de crédito sujeitas ao limite em relação à RCL Ajustada.", "Operacoes de Credito / RCL Ajustada * 100", "PERCENTUAL", "MENOR_MELHOR", "16.000000", "RGF-04", "LRF_DIVIDA", "GOLD_MATERIALIZADO", 6),
    ("ARO_RCL", "Operações de Crédito ARO / RCL", "Operações por Antecipação de Receita Orçamentária sobre a RCL Ajustada.", "ARO / RCL Ajustada * 100", "PERCENTUAL", "MENOR_MELHOR", "7.000000", "RGF-04", "LRF_DIVIDA", "GOLD_MATERIALIZADO", 7),
    ("EDUCACAO_MIN", "Aplicação Constitucional em Educação (MDE)", "Percentual aplicado na Manutenção e Desenvolvimento do Ensino (mínimo 25%).", "Despesas MDE / Receita Resultante de Impostos * 100", "PERCENTUAL", "MAIOR_MELHOR", "25.000000", "RREO-14", "MINIMO_CONSTITUCIONAL", "GOLD_MATERIALIZADO", 8),
    ("SAUDE_MIN", "Aplicação Constitucional em Saúde (ASPS)", "Percentual aplicado em Ações e Serviços Públicos de Saúde (mínimo 15%).", "Despesas ASPS / Receita de Impostos e Transferencias * 100", "PERCENTUAL", "MAIOR_MELHOR", "15.000000", "RREO-14", "MINIMO_CONSTITUCIONAL", "GOLD_MATERIALIZADO", 9),
    ("CAIXA_LIQ_LIVRE", "Disponibilidade de Caixa Líquida (Recursos Livres)", "Saldo líquido de caixa dos recursos não vinculados antes/após RPNP.", "Caixa Bruta Livre - Obrigacoes Financeiras Livres", "REAIS", "MAIOR_MELHOR", "0.000000", "RGF-05", "CAIXA_LIQUIDEZ", "GOLD_MATERIALIZADO", 10),
    # 2. Quocientes Kohama do TCC (Q01-Q20 em DAX)
    ("Q01_EQUILIBRIO_ORC", "Q01 - Equilíbrio Orçamentário", "Verifica se a Receita Prevista comporta a Despesa Fixada (Kohama / TCC).", "Receita Prevista Atualizada / Dotacao Atualizada", "RAZAO", "MAIOR_MELHOR", "1.000000", "RREO-01", "TCC_BALANCO_ORCAMENTARIO", "DAX", 101),
    ("Q02_EXEC_RECEITA", "Q02 - Execução da Receita", "Grau de realização da receita orçamentária frente à previsão atualizada.", "Receita Realizada / Previsao Atualizada", "RAZAO", "MAIOR_MELHOR", "1.000000", "RREO-01", "TCC_BALANCO_ORCAMENTARIO", "DAX", 102),
    ("Q03_DESEMPENHO_ARREC", "Q03 - Desempenho da Arrecadação Corrente", "Cobertura das despesas correntes empenhadas pelas receitas correntes arrecadadas.", "Receita Corrente Realizada / Despesa Corrente Empenhada", "RAZAO", "MAIOR_MELHOR", "1.000000", "RREO-01", "TCC_BALANCO_ORCAMENTARIO", "DAX", 103),
    ("Q04_EXEC_DESPESA", "Q04 - Execução da Despesa", "Utilização dos créditos orçamentários autorizados pelo empenho.", "Despesa Empenhada / Dotacao Atualizada", "RAZAO", "MENOR_MELHOR", "1.000000", "RREO-01", "TCC_BALANCO_ORCAMENTARIO", "DAX", 104),
    ("Q05_RESULTADO_ORC", "Q05 - Execução Orçamentária (Resultado)", "Quociente de resultado orçamentário (>1 indica superávit orçamentário).", "Receita Realizada / Despesa Empenhada", "RAZAO", "MAIOR_MELHOR", "1.000000", "RREO-01", "TCC_BALANCO_ORCAMENTARIO", "DAX", 105),
    ("Q06_EXEC_CORRENTE", "Q06 - Execução Orçamentária Corrente (Poupança)", "Capacidade de geração de poupança corrente orçamentária.", "Receita Corrente / Despesa Corrente", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-C / DCA-I-D", "TCC_BALANCO_ORCAMENTARIO", "DAX", 106),
    ("Q07_CAPITAL_SOBRE_SUPERAVIT", "Q07 - Cobertura de Capital pelo Superávit Corrente", "Proporção das despesas de capital financiadas por superávit corrente + receitas de capital.", "(Superavit Corrente + Receita de Capital) / Despesa de Capital", "RAZAO", "MAIOR_MELHOR", "1.000000", "RREO-01", "TCC_BALANCO_ORCAMENTARIO", "DAX", 107),
    ("Q08_FIN_REAL_EXEC_ORC", "Q08 - Resultado Financeiro da Execução Orçamentária", "Relação entre arrecadação orçamentária efetiva e despesa orçamentária paga no exercício.", "Receita Orcamentaria Liquida Realizada / Despesa Orcamentaria Paga", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-C / DCA-I-D", "TCC_BALANCO_FINANCEIRO", "DAX", 108),
    ("Q09_COBERTURA_CAIXA_TOTAL", "Q09 - Cobertura de Obrigações Financeiras Totais (Proxy BF)", "Proxy SICONFI (API /dca não publica Balanço Financeiro): cobertura das obrigações financeiras pela caixa bruta total no RGF-05.", "Disponibilidade de Caixa Bruta Total / Obrigacoes Financeiras Totais (RGF-05)", "RAZAO", "MAIOR_MELHOR", "1.000000", "RGF-05 (Proxy BF)", "TCC_BALANCO_FINANCEIRO", "DAX", 109),
    ("Q10_COBERTURA_RESTOS_PAGAR", "Q10 - Cobertura de Restos a Pagar e Extraorçamentário (Proxy BF)", "Proxy SICONFI (sem BF na API /dca): relação entre caixa e equivalentes (DCA-I-AB) e obrigações de RP + depósitos/demais obrigações (RGF-05).", "Caixa e Equivalentes (P1.1.1) / (RP Liquidados Nao Pagos + Demais Obrigacoes RGF-05)", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB / RGF-05 (Proxy BF)", "TCC_BALANCO_FINANCEIRO", "DAX", 110),
    ("Q11_EVOLUCAO_SALDO_CAIXA", "Q11 - Evolução das Disponibilidades de Caixa (Proxy BF)", "Proxy SICONFI (sem BF na API /dca): evolução do estoque de Caixa e Equivalentes em relação ao encerramento do exercício anterior.", "Caixa e Equivalentes Final (t) / Caixa e Equivalentes Inicial (t-1)", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB (Proxy BF)", "TCC_BALANCO_FINANCEIRO", "DAX", 111),
    ("Q12_LIQUIDEZ_FINANCEIRA", "Q12 - Situação Financeira (Lei 4.320/64)", "Quociente entre Ativo Financeiro e Passivo Financeiro (>1 indica superávit financeiro para créditos adicionais).", "Ativo Financeiro / Passivo Financeiro", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB", "TCC_BALANCO_PATRIMONIAL", "DAX", 112),
    ("Q13_COBERTURA_PERMANENTE", "Q13 - Situação Permanente (Lei 4.320/64)", "Relação entre Ativo Permanente e Passivo Permanente.", "Ativo Permanente / Passivo Permanente", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB", "TCC_BALANCO_PATRIMONIAL", "DAX", 113),
    ("Q14_SOLVENCIA_GERAL", "Q14 - Solvência Patrimonial Geral", "Capacidade do Ativo Total cobrir o Passivo Exigível (Circulante + Não Circulante).", "Ativo Total / (Passivo Circulante + Passivo Nao Circulante)", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB", "TCC_BALANCO_PATRIMONIAL", "DAX", 114),
    ("Q15_COMP_ENDIVIDAMENTO", "Q15 - Composição do Endividamento", "Fração do passivo exigível que vence no curto prazo (Passivo Circulante).", "Passivo Circulante / (Passivo Circulante + Passivo Nao Circulante)", "RAZAO", "MENOR_MELHOR", "0.500000", "DCA-I-AB", "TCC_BALANCO_PATRIMONIAL", "DAX", 115),
    ("Q16_LIQUIDEZ_IMEDIATA", "Q16 - Liquidez Imediata (PCASP)", "Cobertura imediata do Passivo Circulante por Caixa e Equivalentes de Caixa.", "Caixa e Equivalentes (P1.1.1) / Passivo Circulante (P2.1)", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB", "TCC_BALANCO_PATRIMONIAL", "DAX", 116),
    ("Q17_LIQUIDEZ_CORRENTE", "Q17 - Liquidez Corrente (PCASP)", "Capacidade de pagamento no curto prazo (Ativo Circulante / Passivo Circulante).", "Ativo Circulante (P1.1) / Passivo Circulante (P2.1)", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB", "TCC_BALANCO_PATRIMONIAL", "DAX", 117),
    ("Q18_LIQUIDEZ_GERAL", "Q18 - Liquidez Geral (PCASP)", "Capacidade de pagamento de curto e longo prazo frente ao exigível total.", "(Ativo Circulante + Realizavel a LP) / (Passivo Circulante + Passivo Nao Circulante)", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-AB", "TCC_BALANCO_PATRIMONIAL", "DAX", 118),
    ("Q19_RESULTADO_VPA_VPD", "Q19 - Resultado Patrimonial (VPA / VPD)", "Quociente econômico entre Variações Patrimoniais Aumentativas e Diminutivas na DVP.", "Total VPA (P4) / Total VPD (P3)", "RAZAO", "MAIOR_MELHOR", "1.000000", "DCA-I-HI", "TCC_DVP", "DAX", 119),
    ("Q20_IMPACTO_PATRIMONIAL", "Q20 - Evolução Relativa do Patrimônio Líquido", "Variação relativa do Patrimônio Líquido provocada pelo resultado patrimonial do exercício.", "Resultado Patrimonial do Periodo / ABS(Patrimonio Liquido Anterior)", "PERCENTUAL", "MAIOR_MELHOR", "0.000000", "DCA-I-HI / DCA-I-AB", "TCC_DVP", "DAX", 120),
    # 3. Indicadores Complementares de Gestao Fiscal - Secao 8 do Guia (7)
    ("TX_EXEC_RECEITA_ATU", "Taxa de Realização da Receita (%)", "Percentual acumulado de realização da receita orçamentária sobre a previsão atualizada.", "Receita Ate o Periodo / Previsao Atualizada * 100", "PERCENTUAL", "MAIOR_MELHOR", "100.000000", "RREO-01", "GESTAO_ORCAMENTARIA", "DAX", 201),
    ("GRAU_LIQUIDACAO", "Grau de Liquidação da Despesa (%)", "Percentual da despesa empenhada que já foi efetivamente liquidada.", "Despesa Liquidada / Despesa Empenhada * 100", "PERCENTUAL", "MAIOR_MELHOR", "90.000000", "RREO-01", "GESTAO_ORCAMENTARIA", "DAX", 202),
    ("GRAU_PAGAMENTO", "Grau de Pagamento sobre Liquidação (%)", "Percentual da despesa liquidada efetivamente paga até o período.", "Despesa Paga / Despesa Liquidada * 100", "PERCENTUAL", "MAIOR_MELHOR", "95.000000", "RREO-01", "GESTAO_ORCAMENTARIA", "DAX", 203),
    ("RESULTADO_ORCAMENTARIO", "Resultado Orçamentário (R$)", "Diferença absoluta entre Receita Realizada e Despesa Empenhada.", "Receita Realizada - Despesa Empenhada", "REAIS", "MAIOR_MELHOR", "0.000000", "RREO-01", "GESTAO_ORCAMENTARIA", "DAX", 204),
    ("AUTONOMIA_FISCAL", "Autonomia Fiscal / Arrecadação Própria (%)", "Participação das receitas tributárias e próprias na receita corrente líquida.", "Receita Propria / RCL * 100", "PERCENTUAL", "MAIOR_MELHOR", "25.000000", "RREO-03", "ESTRUTURA_FISCAL", "DAX", 205),
    ("DEPENDENCIA_TRANSF", "Dependência de Transferências (%)", "Participação das transferências intergovernamentais correntes na receita corrente.", "Transferencias Correntes / Receitas Correntes * 100", "PERCENTUAL", "MENOR_MELHOR", "70.000000", "RREO-01 / RREO-03", "ESTRUTURA_FISCAL", "DAX", 206),
    ("INVESTIMENTO_PER_CAPITA", "Investimento Público per Capita (R$/hab)", "Despesa de investimentos liquidada por habitante.", "Investimentos Liquidados / Populacao IBGE", "REAIS_PER_CAPITA", "MAIOR_MELHOR", "", "RREO-01 / IBGE", "ESTRUTURA_FISCAL", "DAX", 207),
]


def build_secao_map_rows() -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(fonte: str, anexo_cod: str, rotulo: str, sec_cod: str, sec_nome: str, ordem: int) -> None:
        key = (fonte, anexo_cod, rotulo)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "fonte": fonte,
                "anexo_codigo": anexo_cod,
                "rotulo_origem": rotulo,
                "secao_codigo": sec_cod,
                "secao_nome": sec_nome,
                "ordem_exibicao": ordem,
            }
        )

    # Garante Padrao e Padrão para todos os anexos normalizados conhecidos
    all_anexos = sorted({(f, slug) for (f, _), slug in ANEXO_SLUG_MAP.items()})
    for fonte, anexo_cod in all_anexos:
        add(fonte, anexo_cod, "Padrão", "PADRAO", "Quadro Principal", 1)
        add(fonte, anexo_cod, "Padrao", "PADRAO", "Quadro Principal", 1)

    # Secoes especificas observadas nos 6 municipios (rotulos_all6.tsv)
    add("DCA", "DCA-I-E", "Total Geral da Despesa por Função", "TOTAL_GERAL_FUNCAO", "Total Geral da Despesa por Função", 2)
    add("DCA", "DCA-I-G", "Total Geral da Despesa por Função", "TOTAL_GERAL_FUNCAO", "Total Geral de Restos a Pagar por Função", 2)
    add("RREO", "RREO-02", "Total das Despesas Exceto Intra-Orçamentárias", "TOTAL_EXCETO_INTRA", "Total das Despesas Exceto Intra-Orçamentárias", 2)
    add("RREO", "RREO-02", "Total das Despesas Intra-Orçamentárias", "TOTAL_INTRA", "Total das Despesas Intra-Orçamentárias", 3)
    add("RREO", "RREO-02", "Total de Despesas", "TOTAL_DESPESAS", "Total Geral de Despesas", 4)
    add("RREO", "RREO-13", "Do Ente Federado, exceto estatais não dependentes - Contratadas (I.1)", "PPP_ENTE_CONTRATADAS_I1", "PPP do Ente Federado - Contratadas (I.1)", 2)
    add("RREO", "RREO-13", "RECEITA CORRENTE LÍQUIDA (RCL) (III)", "PPP_RCL_III", "Receita Corrente Líquida (III)", 3)
    add("RREO", "RREO-13", "RECEITA CORRENTE LÍQUIDA (RCL) (IV)", "PPP_RCL_IV", "Receita Corrente Líquida (IV)", 4)
    add("RREO", "RREO-13", "RECEITA CORRENTE LÍQUIDA (RCL) (V)", "PPP_RCL_V", "Receita Corrente Líquida (V)", 5)
    add("RREO", "RREO-13", "TOTAL DAS DESPESAS", "PPP_TOTAL_DESPESAS", "Total das Despesas de PPP", 6)
    add("RREO", "RREO-13", "TOTAL DAS DESPESAS CONSIDERADAS PARA O LIMITE = (I)", "PPP_TOTAL_LIMITE_I", "Total das Despesas Consideradas para o Limite (I)", 7)
    add("RREO", "RREO-13", "TOTAL DAS DESPESAS DE PPP (III) = (I + II)", "PPP_TOTAL_III", "Total das Despesas de PPP (III)", 8)
    add("RREO", "RREO-13", "TOTAL DAS DESPESAS DE PPP DAS ESTATAIS NÃO-DEPENDENTES (II) = (II.1 + II.2)", "PPP_TOTAL_ESTATAIS_II", "Total das Despesas de PPP das Estatais Não-Dependentes (II)", 9)
    add("RREO", "RREO-13", "TOTAL DAS DESPESAS DE PPP DO ENTE FEDERADO (I) = (I.1 + I.2)", "PPP_TOTAL_ENTE_I", "Total das Despesas de PPP do Ente Federado (I)", 10)
    return rows


def write_domain_seeds(seeds_dir: Path, overwrite_profundidade: bool = False) -> dict[str, int]:
    seeds_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    # 1. seed_secao_map.csv
    secao_rows = build_secao_map_rows()
    with (seeds_dir / "seed_secao_map.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["fonte", "anexo_codigo", "rotulo_origem", "secao_codigo", "secao_nome", "ordem_exibicao"])
        w.writeheader()
        w.writerows(secao_rows)
    counts["seed_secao_map.csv"] = len(secao_rows)

    # 2. seed_fonte_recurso.csv
    with (seeds_dir / "seed_fonte_recurso.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cod_fonte", "nome_fonte_origem", "exercicio_ini", "exercicio_fim", "cod_fonte_padrao", "nome_fonte", "grupo", "vinculada", "eh_total_anexo05"])
        w.writerows(FONTE_RECURSO_ROWS)
    counts["seed_fonte_recurso.csv"] = len(FONTE_RECURSO_ROWS)

    # 3. seed_limite_lrf.csv
    with (seeds_dir / "seed_limite_lrf.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["codigo_limite", "descricao", "percentual_limite", "pct_alerta", "pct_prudencial", "tipo_limite", "base_calculo", "vigencia_ini", "vigencia_fim", "base_legal"])
        w.writerows(LIMITE_LRF_ROWS)
    counts["seed_limite_lrf.csv"] = len(LIMITE_LRF_ROWS)

    # 4. seed_indicador.csv
    with (seeds_dir / "seed_indicador.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["codigo_indicador", "nome", "descricao", "formula_texto", "unidade", "sentido_bom", "valor_referencia", "fonte_primaria", "grupo", "camada_calculo", "ordem_exibicao"])
        w.writerows(INDICADOR_ROWS)
    counts["seed_indicador.csv"] = len(INDICADOR_ROWS)

    # 5. seed_profundidade.csv (inicializado com baseline 2015, atualizado empiricamente pelo profiler)
    prof_path = seeds_dir / "seed_profundidade.csv"
    if overwrite_profundidade or not prof_path.exists():
        all_anexos = sorted({(f, slug) for (f, _), slug in ANEXO_SLUG_MAP.items()})
        with prof_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["fonte", "anexo_codigo", "exercicio_inicial", "motivo"])
            for fonte, slug in all_anexos:
                motivo = (
                    "Anexo transitório do exercício de 2016 (RPPS subdividido)"
                    if slug in {"RREO-04-1", "RREO-04-2"}
                    else "Série histórica completa a partir de 2015 (sujeita a confirmação empírica no profiling)"
                )
                ano_ini = 2016 if slug in {"RREO-04-1", "RREO-04-2"} else 2015
                w.writerow([fonte, slug, ano_ini, motivo])
        counts["seed_profundidade.csv"] = len(all_anexos)
    else:
        with prof_path.open("r", encoding="utf-8", newline="") as fh:
            counts["seed_profundidade.csv"] = max(0, sum(1 for _ in fh) - 1)

    return counts
