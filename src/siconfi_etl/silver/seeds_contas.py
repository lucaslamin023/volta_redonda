from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import TYPE_CHECKING

from siconfi_etl.silver.normalizer import normalize_text, strip_accents_upper

if TYPE_CHECKING:
    import psycopg

# Equivalencias longitudinais de cod_conta entre mudancas de leiaute da STN (2015-2026)
# Tupla: (fonte, anexo_codigo, cod_conta_origem, ex_ini, ex_fim, cod_conta_padrao)
CONTA_EQUIVALENCIA_ROWS: list[tuple[str, str, str, int, int, str]] = [
    # RREO-03 (RCL: prefixo RREO3 introduzido em 2018+)
    ("RREO", "RREO-03", "RREO3ReceitaCorrenteLiquida", 2015, 2099, "ReceitaCorrenteLiquida"),
    ("RREO", "RREO-03", "RREO3CotaParteDoFPM", 2015, 2099, "CotaParteDoFPM"),
    ("RREO", "RREO-03", "RREO3CotaParteDoICMS", 2015, 2099, "CotaParteDoICMS"),
    ("RREO", "RREO-03", "RREO3CotaParteDoIPVA", 2015, 2099, "CotaParteDoIPVA"),
    ("RREO", "RREO-03", "RREO3CotaParteDoITR", 2015, 2099, "CotaParteDoITR"),
    ("RREO", "RREO-03", "RREO3TransferenciasDoFUNDEB", 2015, 2099, "TransferenciasDoFUNDEB"),
    ("RREO", "RREO-03", "RREO3TransferenciasDaLC871996", 2015, 2099, "TransferenciasDaLC871996"),
    ("RREO", "RREO-03", "RREO3TransferenciasDaLC611989", 2015, 2099, "TransferenciasDaLC611989"),
    ("RREO", "RREO-03", "RREO3OutrasTransferenciasCorrentes", 2015, 2099, "OutrasTransferenciasCorrentes"),
    # RREO-01 (Balanco Orcamentario)
    ("RREO", "RREO-01", "RREO1OutrasReceitasDeCapital", 2015, 2099, "OutrasReceitasDeCapital"),
    ("RREO", "RREO-01", "ReceitasIntraOrcamentariasTotal", 2015, 2099, "ReceitasIntraOrcamentarias"),
    ("RREO", "RREO-01", "DespesasIntraOrcamentariasTotal", 2015, 2099, "DespesasIntraOrcamentarias"),
    # RGF-02 (Divida Consolidada Liquida)
    ("RGF", "RGF-02", "DisponibilidadeDeCaixaBrutaAnexo02", 2015, 2099, "DisponibilidadeDeCaixaBruta"),
    ("RGF", "RGF-02", "RGF2DisponibilidadeDeCaixaBruta", 2015, 2099, "DisponibilidadeDeCaixaBruta"),
    ("RGF", "RGF-02", "RGF2DemaisDividasContratuais", 2015, 2099, "DemaisDividasContratuais"),
    ("RGF", "RGF-02", "RGF2ParcelamentoERenegociacaoDeDividas", 2015, 2099, "ParcelamentoDeDividas"),
    ("RGF", "RGF-02", "RestosAPagarProcessadosExcetoPrecatorios", 2015, 2099, "RestosAPagarProcessados"),
    # RGF-05 (Disponibilidade de Caixa - unificacao dos totais entre leiautes 2015-2026)
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBrutaAnexo05::TOT_GERAL_III", 2015, 2099, "DisponibilidadeDeCaixaBruta::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBruta::TOT_GERAL_III", 2015, 2099, "DisponibilidadeDeCaixaBruta::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBruta::TOT_GERAL_IV", 2015, 2099, "DisponibilidadeDeCaixaBruta::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBruta::TOT_GERAL_SIMPLES", 2015, 2099, "DisponibilidadeDeCaixaBruta::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquida::TOT_GERAL_III", 2015, 2099, "DisponibilidadeDeCaixaLiquida::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquida::TOT_GERAL_IV", 2015, 2099, "DisponibilidadeDeCaixaLiquida::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquida::TOT_GERAL_SIMPLES", 2015, 2099, "DisponibilidadeDeCaixaLiquida::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquidaAposRP::TOT_GERAL_III", 2015, 2099, "DisponibilidadeDeCaixaLiquidaAposRP::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquidaAposRP::TOT_GERAL_IV", 2015, 2099, "DisponibilidadeDeCaixaLiquidaAposRP::TOT_GERAL"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBruta::TOT_NAO_VINCULADOS_I", 2015, 2099, "DisponibilidadeDeCaixaBruta::TOT_NAO_VINCULADOS"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBruta::TOT_NAO_VINCULADOS_II", 2015, 2099, "DisponibilidadeDeCaixaBruta::TOT_NAO_VINCULADOS"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBrutaAnexo05::TOT_NAO_VINCULADOS_II", 2015, 2099, "DisponibilidadeDeCaixaBruta::TOT_NAO_VINCULADOS"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquida::TOT_NAO_VINCULADOS_I", 2015, 2099, "DisponibilidadeDeCaixaLiquida::TOT_NAO_VINCULADOS"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquida::TOT_NAO_VINCULADOS_II", 2015, 2099, "DisponibilidadeDeCaixaLiquida::TOT_NAO_VINCULADOS"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquidaAposRP::TOT_NAO_VINCULADOS_I", 2015, 2099, "DisponibilidadeDeCaixaLiquidaAposRP::TOT_NAO_VINCULADOS"),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquidaAposRP::TOT_NAO_VINCULADOS_II", 2015, 2099, "DisponibilidadeDeCaixaLiquidaAposRP::TOT_NAO_VINCULADOS"),
    # RGF-06 (Demonstrativo Simplificado)
    ("RGF", "RGF-06", "RGF6DespesaTotalComPessoalDemonstrativoSimplificado", 2015, 2099, "DespesaTotalComPessoalDemonstrativoSimplificado"),
    ("RGF", "RGF-06", "RGF6LimiteMaximoDespesaComPessoalDemonstrativoSimplificado", 2015, 2099, "LimiteMaximoDespesaComPessoalDemonstrativoSimplificado"),
    ("RGF", "RGF-06", "RGF6LimitePrudencialDespesaComPessoalDemonstrativoSimplificado", 2015, 2099, "LimitePrudencialDespesaComPessoalDemonstrativoSimplificado"),
    # DCA-I-C (Ementario da Receita: codificacao 2015-2017 e 2018-2021 -> padrao 2022+)
    ("DCA", "DCA-I-C", "RO1.1.1.2.02.0.0", 2015, 2017, "RO1.1.1.2.50.0.0"),
    ("DCA", "DCA-I-C", "RO1.1.1.8.01.1.0", 2018, 2021, "RO1.1.1.2.50.0.0"),
    ("DCA", "DCA-I-C", "RO1.1.1.2.04.0.0", 2015, 2017, "RO1.1.1.3.03.1.0"),
    ("DCA", "DCA-I-C", "RO1.1.1.2.08.0.0", 2015, 2017, "RO1.1.1.2.53.0.0"),
    ("DCA", "DCA-I-C", "RO1.1.1.8.01.4.0", 2018, 2021, "RO1.1.1.2.53.0.0"),
    ("DCA", "DCA-I-C", "RO1.1.1.3.05.0.0", 2015, 2017, "RO1.1.1.4.51.1.0"),
    ("DCA", "DCA-I-C", "RO1.1.1.8.02.3.0", 2018, 2021, "RO1.1.1.4.51.1.0"),
    ("DCA", "DCA-I-C", "RO1.7.2.1.01.02.00", 2015, 2017, "RO1.7.1.1.51.1.0"),
    ("DCA", "DCA-I-C", "RO1.7.1.8.01.2.0", 2018, 2021, "RO1.7.1.1.51.1.0"),
    ("DCA", "DCA-I-C", "RO1.7.2.1.01.05.00", 2015, 2017, "RO1.7.1.1.52.0.0"),
    ("DCA", "DCA-I-C", "RO1.7.1.8.01.5.0", 2018, 2021, "RO1.7.1.1.52.0.0"),
    ("DCA", "DCA-I-C", "RO1.7.2.2.01.01.00", 2015, 2017, "RO1.7.2.1.50.0.0"),
    ("DCA", "DCA-I-C", "RO1.7.2.8.01.1.0", 2018, 2021, "RO1.7.2.1.50.0.0"),
    ("DCA", "DCA-I-C", "RO1.7.2.2.01.02.00", 2015, 2017, "RO1.7.2.1.51.0.0"),
    ("DCA", "DCA-I-C", "RO1.7.2.8.01.2.0", 2018, 2021, "RO1.7.2.1.51.0.0"),
    ("DCA", "DCA-I-C", "RO1.7.2.4.01.00.00", 2015, 2017, "RO1.7.5.1.50.0.0"),
    ("DCA", "DCA-I-C", "RO1.7.5.8.01.1.0", 2018, 2021, "RO1.7.5.1.50.0.0"),
]

# Curadoria manual explicita das contas-nucleo (Decisao Hibrida A1)
# Tupla: (fonte, anexo_codigo, cod_conta_padrao, descricao, cod_conta_pai, nivel, eh_folha, eh_total, grupo_analitico, sinal_semantico)
MANUAL_CONTA_HIERARQUIA: list[tuple[str, str, str, str, str, int, int, int, str, int]] = [
    # DCA-I-AB (Quadro Lei 4.320/64 e raizes PCASP)
    ("DCA", "DCA-I-AB", "P1.0.0.0.0.00.00", "Ativo Total", "", 1, 0, 1, "ATIVO", 1),
    ("DCA", "DCA-I-AB", "P1.1.0.0.0.00.00", "Ativo Circulante", "P1.0.0.0.0.00.00", 2, 0, 1, "ATIVO_CIRCULANTE", 1),
    ("DCA", "DCA-I-AB", "P1.1.1.0.0.00.00", "Caixa e Equivalentes de Caixa", "P1.1.0.0.0.00.00", 3, 0, 0, "CAIXA_EQUIVALENTES", 1),
    ("DCA", "DCA-I-AB", "P1.2.0.0.0.00.00", "Ativo Não Circulante", "P1.0.0.0.0.00.00", 2, 0, 1, "ATIVO_NAO_CIRCULANTE", 1),
    ("DCA", "DCA-I-AB", "P1.2.1.0.0.00.00", "Ativo Realizável a Longo Prazo", "P1.2.0.0.0.00.00", 3, 0, 0, "REALIZAVEL_LP", 1),
    ("DCA", "DCA-I-AB", "P2.0.0.0.0.00.00", "Passivo e Patrimônio Líquido", "", 1, 0, 1, "PASSIVO_PL", 1),
    ("DCA", "DCA-I-AB", "P2.1.0.0.0.00.00", "Passivo Circulante", "P2.0.0.0.0.00.00", 2, 0, 1, "PASSIVO_CIRCULANTE", 1),
    ("DCA", "DCA-I-AB", "P2.2.0.0.0.00.00", "Passivo Não Circulante", "P2.0.0.0.0.00.00", 2, 0, 1, "PASSIVO_NAO_CIRCULANTE", 1),
    ("DCA", "DCA-I-AB", "P2.3.0.0.0.00.00", "Patrimônio Líquido", "P2.0.0.0.0.00.00", 2, 0, 1, "PATRIMONIO_LIQUIDO", 1),
    ("DCA", "DCA-I-AB", "AtivoFinanceiro", "Ativo Financeiro (Lei 4.320/64)", "", 1, 1, 0, "ATIVO_FINANCEIRO", 1),
    ("DCA", "DCA-I-AB", "AtivoPermanente", "Ativo Permanente (Lei 4.320/64)", "", 1, 1, 0, "ATIVO_PERMANENTE", 1),
    ("DCA", "DCA-I-AB", "PassivoFinanceiro", "Passivo Financeiro (Lei 4.320/64)", "", 1, 1, 0, "PASSIVO_FINANCEIRO", 1),
    ("DCA", "DCA-I-AB", "PassivoPermanente", "Passivo Permanente (Lei 4.320/64)", "", 1, 1, 0, "PASSIVO_PERMANENTE", 1),
    ("DCA", "DCA-I-AB", "SaldoPatrimonial", "Saldo Patrimonial (Lei 4.320/64)", "", 1, 0, 1, "PATRIMONIO_LIQUIDO", 1),
    # DCA-I-C / I-D / I-F / I-HI
    ("DCA", "DCA-I-C", "TotalReceitas", "Total das Receitas Orçamentárias", "", 1, 0, 1, "OUTRAS", 1),
    ("DCA", "DCA-I-C", "ReceitasExcetoIntraOrcamentarias", "Receitas (Exceto Intra-Orçamentárias)", "TotalReceitas", 2, 0, 1, "OUTRAS", 1),
    ("DCA", "DCA-I-C", "ReceitasIntraOrcamentarias", "Receitas (Intra-Orçamentárias)", "TotalReceitas", 2, 0, 1, "OUTRAS", 1),
    ("DCA", "DCA-I-D", "TotalDespesas", "Total Geral da Despesa Orçamentária", "", 1, 0, 1, "OUTRAS", 1),
    ("DCA", "DCA-I-F", "TotalDespesas", "Total Geral de Restos a Pagar", "", 1, 0, 1, "OUTRAS", 1),
    ("DCA", "DCA-I-HI", "P4.0.0.0.0.00.00", "Total das Variações Patrimoniais Aumentativas (VPA)", "", 1, 0, 1, "VPA", 1),
    ("DCA", "DCA-I-HI", "P3.0.0.0.0.00.00", "Total das Variações Patrimoniais Diminutivas (VPD)", "", 1, 0, 1, "VPD", 1),
    ("DCA", "DCA-I-HI", "ResultadoPatrimonialDoPeriodo", "Resultado Patrimonial do Período", "", 1, 0, 1, "RESULTADO_PATRIMONIAL", 1),
    # RREO-01 (Balanco Orcamentario)
    ("RREO", "RREO-01", "TotalReceitas", "Total das Receitas", "", 1, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "SubtotalDasReceitas", "Subtotal das Receitas (I + II)", "TotalReceitas", 2, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "ReceitasExcetoIntraOrcamentarias", "Receitas (Exceto Intra-Orçamentárias) (I)", "SubtotalDasReceitas", 3, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "ReceitasIntraOrcamentarias", "Receitas (Intra-Orçamentárias) (II)", "SubtotalDasReceitas", 3, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "ReceitasCorrentes", "Receitas Correntes", "ReceitasExcetoIntraOrcamentarias", 4, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "ReceitaTributaria", "Impostos, Taxas e Contribuições de Melhoria", "ReceitasCorrentes", 5, 0, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-01", "Impostos", "Impostos", "ReceitaTributaria", 6, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-01", "Taxas", "Taxas", "ReceitaTributaria", 6, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-01", "ContribuicaoDeMelhoria", "Contribuição de Melhoria", "ReceitaTributaria", 6, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-01", "ReceitaDeContribuicoes", "Receita de Contribuições", "ReceitasCorrentes", 5, 0, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-01", "ReceitaPatrimonial", "Receita Patrimonial", "ReceitasCorrentes", 5, 0, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-01", "ReceitaDeServicos", "Receita de Serviços", "ReceitasCorrentes", 5, 0, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-01", "TransferenciasCorrentes", "Transferências Correntes", "ReceitasCorrentes", 5, 0, 0, "TRANSFERENCIAS_UNIAO", 1),
    ("RREO", "RREO-01", "TransferenciasCorrentesDaUniaoEDeSuasEntidades", "Transferências Correntes da União", "TransferenciasCorrentes", 6, 1, 0, "TRANSFERENCIAS_UNIAO", 1),
    ("RREO", "RREO-01", "TransferenciasCorrentesDosEstadosEDoDistritoFederalEDeSuasEntidades", "Transferências Correntes do Estado", "TransferenciasCorrentes", 6, 1, 0, "TRANSFERENCIAS_ESTADO", 1),
    ("RREO", "RREO-01", "OutrasReceitasCorrentes", "Outras Receitas Correntes", "ReceitasCorrentes", 5, 0, 0, "OUTRAS", 1),
    ("RREO", "RREO-01", "ReceitasDeCapital", "Receitas de Capital", "ReceitasExcetoIntraOrcamentarias", 4, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "ReceitasDeOperacoesDeCredito", "Operações de Crédito", "ReceitasDeCapital", 5, 0, 0, "OPERACOES_CREDITO", 1),
    ("RREO", "RREO-01", "AlienacaoDeBens", "Alienação de Bens", "ReceitasDeCapital", 5, 0, 0, "OUTRAS", 1),
    ("RREO", "RREO-01", "TransferenciasDeCapital", "Transferências de Capital", "ReceitasDeCapital", 5, 0, 0, "TRANSFERENCIAS_UNIAO", 1),
    ("RREO", "RREO-01", "OutrasReceitasDeCapital", "Outras Receitas de Capital", "ReceitasDeCapital", 5, 0, 0, "OUTRAS", 1),
    ("RREO", "RREO-01", "Deficit", "Déficit Orçamentário (VI)", "TotalReceitas", 2, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "TotalDespesas", "Total das Despesas", "", 1, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "SubtotalDasDespesas", "Subtotal das Despesas (VIII + IX)", "TotalDespesas", 2, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "DespesasExcetoIntraOrcamentarias", "Despesas (Exceto Intra-Orçamentárias) (VIII)", "SubtotalDasDespesas", 3, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "DespesasIntraOrcamentarias", "Despesas (Intra-Orçamentárias) (IX)", "SubtotalDasDespesas", 3, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-01", "DespesasCorrentes", "Despesas Correntes", "DespesasExcetoIntraOrcamentarias", 4, 0, 1, "OUTRAS_CORRENTES", 1),
    ("RREO", "RREO-01", "PessoalEEncargosSociais", "Pessoal e Encargos Sociais", "DespesasCorrentes", 5, 1, 0, "PESSOAL", 1),
    ("RREO", "RREO-01", "JurosEEncargosDaDivida", "Juros e Encargos da Dívida", "DespesasCorrentes", 5, 1, 0, "JUROS_ENCARGOS_DIVIDA", 1),
    ("RREO", "RREO-01", "OutrasDespesasCorrentes", "Outras Despesas Correntes", "DespesasCorrentes", 5, 1, 0, "OUTRAS_CORRENTES", 1),
    ("RREO", "RREO-01", "DespesasDeCapital", "Despesas de Capital", "DespesasExcetoIntraOrcamentarias", 4, 0, 1, "INVESTIMENTOS", 1),
    ("RREO", "RREO-01", "Investimentos", "Investimentos", "DespesasDeCapital", 5, 1, 0, "INVESTIMENTOS", 1),
    ("RREO", "RREO-01", "InversoesFinanceiras", "Inversões Financeiras", "DespesasDeCapital", 5, 1, 0, "INVERSOES_FINANCEIRAS", 1),
    ("RREO", "RREO-01", "AmortizacaoDaDivida", "Amortização da Dívida", "DespesasDeCapital", 5, 1, 0, "AMORTIZACAO_DIVIDA", 1),
    ("RREO", "RREO-01", "ReservaDeContingencia", "Reserva de Contingência", "DespesasExcetoIntraOrcamentarias", 4, 1, 0, "OUTRAS", 1),
    ("RREO", "RREO-01", "Superavit", "Superávit Orçamentário (XIII)", "TotalDespesas", 2, 0, 1, "OUTRAS", 1),
    # RREO-03 (Receita Corrente Liquida)
    ("RREO", "RREO-03", "ReceitaCorrenteLiquida", "Receita Corrente Líquida (RCL) (III) = (I - II)", "", 1, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-03", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", "Receitas Correntes Brutas da RCL (I)", "ReceitaCorrenteLiquida", 2, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-03", "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB", "Receita Tributária", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", 3, 0, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-03", "IPTULiquidoExcetoTransferenciasEFUNDEB", "IPTU", "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB", 4, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-03", "ISSLiquidoExcetoTransferenciasEFUNDEB", "ISS", "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB", 4, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-03", "ITBILiquidoExcetoTransferenciasEFUNDEB", "ITBI", "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB", 4, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-03", "IRRFLiquidoExcetoTransferenciasEFUNDEB", "IRRF", "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB", 4, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-03", "OutrasReceitasTributarias", "Outras Receitas Tributárias", "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB", 4, 1, 0, "RECEITA_PROPRIA", 1),
    ("RREO", "RREO-03", "CotaParteDoFPM", "Cota-Parte do FPM", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", 4, 1, 0, "TRANSFERENCIAS_UNIAO", 1),
    ("RREO", "RREO-03", "CotaParteDoITR", "Cota-Parte do ITR", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", 4, 1, 0, "TRANSFERENCIAS_UNIAO", 1),
    ("RREO", "RREO-03", "CotaParteDoICMS", "Cota-Parte do ICMS", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", 4, 1, 0, "TRANSFERENCIAS_ESTADO", 1),
    ("RREO", "RREO-03", "CotaParteDoIPVA", "Cota-Parte do IPVA", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", 4, 1, 0, "TRANSFERENCIAS_ESTADO", 1),
    ("RREO", "RREO-03", "TransferenciasDoFUNDEB", "Transferências do FUNDEB", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", 4, 1, 0, "TRANSFERENCIAS_FUNDEB", 1),
    ("RREO", "RREO-03", "OutrasTransferenciasCorrentes", "Outras Transferências Correntes", "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB", 4, 1, 0, "TRANSFERENCIAS_UNIAO", 1),
    ("RREO", "RREO-03", "DeducoesDaReceitaCorrenteLiquida", "Deduções da RCL (II)", "ReceitaCorrenteLiquida", 2, 0, 1, "OUTRAS", -1),
    ("RREO", "RREO-03", "DeducaoDeReceitaParaFormacaoDoFUNDEB", "Dedução de Receita para Formação do FUNDEB", "DeducoesDaReceitaCorrenteLiquida", 3, 1, 0, "TRANSFERENCIAS_FUNDEB", -1),
    ("RREO", "RREO-03", "ContribuicaoDoServidorParaOPlanoDePrevidencia", "Contribuição do Servidor para o Plano de Previdência", "DeducoesDaReceitaCorrenteLiquida", 3, 1, 0, "OUTRAS", -1),
    ("RREO", "RREO-03", "CompensacaoFinanceiraEntreRegimesPrevidencia", "Compensação Financeira entre Regimes de Previdência", "DeducoesDaReceitaCorrenteLiquida", 3, 1, 0, "OUTRAS", -1),
    ("RREO", "RREO-03", "RREO3ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento", "RCL Ajustada para Limites de Endividamento", "", 1, 0, 1, "OUTRAS", 1),
    ("RREO", "RREO-03", "RREO3ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDaDespesaComPessoal", "RCL Ajustada para Limites da Despesa com Pessoal", "", 1, 0, 1, "OUTRAS", 1),
    # RREO-14 (Educacao e Saude - Minimos Constitucionais)
    ("RREO", "RREO-14", "MinimoAnualDasReceitasDeImpostosNaManutencaoEDesenvolvimentoDoEnsinoDemonstrativoSimplificado", "Aplicação Constitucional em Educação (MDE - Mínimo 25%)", "", 1, 1, 0, "OUTRAS_CORRENTES", 1),
    ("RREO", "RREO-14", "AplicacaoTotalDasDespesasComAcoesEServicosPublicosDeSaude", "Aplicação Constitucional em Saúde (ASPS - Mínimo 15%)", "", 1, 1, 0, "OUTRAS_CORRENTES", 1),
    # RGF-01 (Despesa com Pessoal)
    ("RGF", "RGF-01", "DespesaComPessoalTotal", "Despesa Total com Pessoal (DTP)", "", 1, 0, 1, "PESSOAL", 1),
    ("RGF", "RGF-01", "DespesaComPessoalLiquida", "Despesa Líquida com Pessoal (III) = (I - II)", "DespesaComPessoalTotal", 2, 0, 1, "PESSOAL", 1),
    ("RGF", "RGF-01", "DespesaComPessoalBruta", "Despesa Bruta com Pessoal (I)", "DespesaComPessoalLiquida", 3, 0, 1, "PESSOAL", 1),
    ("RGF", "RGF-01", "DespesaComPessoalAtivoBruta", "Pessoal Ativo", "DespesaComPessoalBruta", 4, 0, 0, "PESSOAL", 1),
    ("RGF", "RGF-01", "VencimentosVantagensEOutrasDespesasVariaveis", "Vencimentos, Vantagens e Outras Despesas Variáveis", "DespesaComPessoalAtivoBruta", 5, 1, 0, "PESSOAL", 1),
    ("RGF", "RGF-01", "ObrigacoesPatronais", "Obrigações Patronais", "DespesaComPessoalAtivoBruta", 5, 1, 0, "PESSOAL", 1),
    ("RGF", "RGF-01", "DespesaComPessoalInativoEPensionistasBruta", "Pessoal Inativo e Pensionistas", "DespesaComPessoalBruta", 4, 0, 0, "PESSOAL", 1),
    ("RGF", "RGF-01", "DespesaComPessoalDecorrenteDeTerceirizacaoPorSubstituicaoBruta", "Contratos de Terceirização (art. 18, §1º LRF)", "DespesaComPessoalBruta", 4, 1, 0, "PESSOAL", 1),
    ("RGF", "RGF-01", "DespesaComPessoalNaoComputada", "Despesas Não Computadas (II) (art. 19, §1º LRF)", "DespesaComPessoalLiquida", 3, 0, 1, "PESSOAL", -1),
    ("RGF", "RGF-01", "ReceitaCorrenteLiquidaLimiteLegal", "Receita Corrente Líquida - RCL (IV)", "", 1, 0, 1, "OUTRAS", 1),
    ("RGF", "RGF-01", "ReceitaCorrenteLiquidaAjustada", "RCL Ajustada para Limite de Pessoal", "", 1, 0, 1, "OUTRAS", 1),
    ("RGF", "RGF-01", "LimiteMaximoDespesaComPessoalTotal", "Limite Máximo Legal de Pessoal", "", 1, 0, 1, "PESSOAL", 1),
    ("RGF", "RGF-01", "LimitePrudencialDespesaComPessoalTotal", "Limite Prudencial de Pessoal (95%)", "", 1, 0, 1, "PESSOAL", 1),
    ("RGF", "RGF-01", "LimiteDeAlertaDespesaComPessoalTotal", "Limite de Alerta de Pessoal (90%)", "", 1, 0, 1, "PESSOAL", 1),
    # RGF-02 (Divida Consolidada Liquida)
    ("RGF", "RGF-02", "DividaConsolidadaLiquida", "Dívida Consolidada Líquida (DCL) (III) = (I - II)", "", 1, 0, 1, "AMORTIZACAO_DIVIDA", 1),
    ("RGF", "RGF-02", "DividaConsolidada", "Dívida Consolidada - DC (I)", "DividaConsolidadaLiquida", 2, 0, 1, "AMORTIZACAO_DIVIDA", 1),
    ("RGF", "RGF-02", "DeducoesDaDividaConsolidada", "Deduções da Dívida Consolidada (II)", "DividaConsolidadaLiquida", 2, 0, 1, "OUTRAS", -1),
    ("RGF", "RGF-02", "DisponibilidadeDeCaixaBruta", "Disponibilidade de Caixa Bruta", "DeducoesDaDividaConsolidada", 3, 1, 0, "CAIXA_EQUIVALENTES", 1),
    ("RGF", "RGF-02", "RestosAPagarProcessados", "(-) Restos a Pagar Processados", "DeducoesDaDividaConsolidada", 3, 1, 0, "PASSIVO_FINANCEIRO", -1),
    ("RGF", "RGF-02", "RGF2ReceitaCorrenteLiquida", "Receita Corrente Líquida - RCL", "", 1, 0, 1, "OUTRAS", 1),
    ("RGF", "RGF-02", "ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento", "RCL Ajustada para Limites de Endividamento", "", 1, 0, 1, "OUTRAS", 1),
    ("RGF", "RGF-02", "PercentualDaDCLSobreARCL", "% da DCL sobre a RCL / RCL Ajustada", "", 1, 0, 1, "AMORTIZACAO_DIVIDA", 1),
    # RGF-03 (Garantias) e RGF-04 (Operacoes de Credito)
    ("RGF", "RGF-03", "RGF3ReceitaCorrenteLiquida", "Receita Corrente Líquida - RCL", "", 1, 0, 1, "OUTRAS", 1),
    ("RGF", "RGF-03", "ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento", "RCL Ajustada para Limites de Endividamento", "", 1, 0, 1, "OUTRAS", 1),
    ("RGF", "RGF-04", "OperacoesDeCreditoSujeitasAoLimiteParaFinsDeContratacao", "Operações de Crédito Sujeitas ao Limite (I)", "", 1, 0, 1, "OPERACOES_CREDITO", 1),
    ("RGF", "RGF-04", "OperacoesDeCreditoPorAntecipacaoDaReceitaOrcamentaria", "Operações de Crédito por Antecipação da Receita Orçamentária (ARO)", "", 1, 1, 0, "OPERACOES_CREDITO", 1),
    ("RGF", "RGF-04", "RGF4ReceitaCorrenteLiquida", "Receita Corrente Líquida - RCL", "", 1, 0, 1, "OUTRAS", 1),
    ("RGF", "RGF-04", "ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento", "RCL Ajustada para Limites de Endividamento", "", 1, 0, 1, "OUTRAS", 1),
    # RGF-05 (Totais padronizados)
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBruta::TOT_GERAL", "Disponibilidade de Caixa Bruta - Total Geral", "", 1, 0, 1, "CAIXA_EQUIVALENTES", 1),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquida::TOT_GERAL", "Disponibilidade de Caixa Líquida (Antes de RPNP) - Total Geral", "", 1, 0, 1, "CAIXA_EQUIVALENTES", 1),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquidaAposRP::TOT_GERAL", "Disponibilidade de Caixa Líquida (Após RPNP) - Total Geral", "", 1, 0, 1, "CAIXA_EQUIVALENTES", 1),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaBruta::TOT_NAO_VINCULADOS", "Disponibilidade de Caixa Bruta - Recursos Não Vinculados", "", 1, 0, 1, "CAIXA_EQUIVALENTES", 1),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquida::TOT_NAO_VINCULADOS", "Disponibilidade de Caixa Líquida (Antes de RPNP) - Recursos Não Vinculados", "", 1, 0, 1, "CAIXA_EQUIVALENTES", 1),
    ("RGF", "RGF-05", "DisponibilidadeDeCaixaLiquidaAposRP::TOT_NAO_VINCULADOS", "Disponibilidade de Caixa Líquida (Após RPNP) - Recursos Não Vinculados", "", 1, 0, 1, "CAIXA_EQUIVALENTES", 1),
]


def classify_secondary_account(
    fonte: str,
    anexo_codigo: str,
    cod_conta_padrao: str,
    descricao: str,
) -> tuple[str, int, int, int, str, int]:
    """
    Classificador deterministico para subcontas secundarias/desambiguadas (Curadoria Hibrida).
    Retorna (cod_conta_pai, nivel, eh_folha, eh_total, grupo_analitico, sinal_semantico).
    """
    desc_u = strip_accents_upper(descricao)
    cod_u = strip_accents_upper(cod_conta_padrao)

    sinal = -1 if (
        descricao.strip().startswith("(-)")
        or descricao.strip().startswith("( - )")
        or "DEDUCOES" in cod_u
        or "DEDUCAO" in cod_u
        or "NAOCOMPUTADA" in cod_u
    ) else 1

    # 1. Linhas desambiguadas de Funcao / Subfuncao (DCA-I-E, DCA-I-G, RREO-02)
    if "::F" in cod_conta_padrao:
        base, suffix = cod_conta_padrao.split("::", 1)
        if "." in suffix:
            fu_part = suffix.split(".", 1)[0]  # Fxx
            return (f"{base}::{fu_part}", 3, 1, 0, "OUTRAS_CORRENTES", 1)
        return (f"{base}::EXCETO_INTRA", 2, 0, 1, "OUTRAS_CORRENTES", 1)

    if cod_conta_padrao.endswith(("::TOTAL_GERAL", "::EXCETO_INTRA", "::INTRA")):
        return ("", 1, 0, 1, "OUTRAS", 1)

    # 2. Linhas desambiguadas por Fonte de Recurso no RGF-05
    if anexo_codigo == "RGF-05" and "::" in cod_conta_padrao:
        _, suffix = cod_conta_padrao.split("::", 1)
        if suffix.startswith("FR_"):
            return ("", 2, 1, 0, "CAIXA_EQUIVALENTES", sinal)
        return ("", 1, 0, 1, "CAIXA_EQUIVALENTES", sinal)

    # 3. Linhas desambiguadas por Poder/Orgao no RREO-07
    if anexo_codigo == "RREO-07" and "::" in cod_conta_padrao:
        if cod_conta_padrao.endswith(("::TOTAL_GERAL", "::EXCETO_INTRA", "::INTRA")):
            return ("", 1, 0, 1, "PASSIVO_FINANCEIRO", 1)
        return ("", 2, 1, 0, "PASSIVO_FINANCEIRO", 1)

    # 4. Contas pontuadas (PCASP / Receita / Despesa)
    if "." in cod_conta_padrao and "::" not in cod_conta_padrao:
        parts = [p for p in cod_conta_padrao.split(".") if p != ""]
        sig_parts = [p for p in parts if any(ch not in "0" for ch in p)]
        nivel = max(1, min(len(sig_parts), len(parts)))
        eh_total = 1 if nivel <= 2 else 0
        eh_folha = 0 if eh_total == 1 else 1
        grupo = _infer_grupo_from_code_or_desc(anexo_codigo, cod_u, desc_u)
        return ("", nivel, eh_folha, eh_total, grupo, sinal)

    # 5. Demais contas nao-pontuadas
    is_tot = any(
        tok in cod_u or tok in desc_u
        for tok in ("TOTAL", "SUBTOTAL", "RESULTADO", "SUPERAVIT", "DEFICIT", "LIMITE", "RECEITACORRENTELIQUIDA")
    )
    eh_total = 1 if is_tot else 0
    eh_folha = 0 if eh_total == 1 else 1
    nivel = 1 if eh_total == 1 else 3
    grupo = _infer_grupo_from_code_or_desc(anexo_codigo, cod_u, desc_u)
    return ("", nivel, eh_folha, eh_total, grupo, sinal)


def _infer_grupo_from_code_or_desc(anexo_codigo: str, cod_u: str, desc_u: str) -> str:
    if cod_u.startswith("P1"):
        return "ATIVO"
    if cod_u.startswith("P2"):
        return "PASSIVO_PL"
    if cod_u.startswith("P3"):
        return "VPD"
    if cod_u.startswith("P4"):
        return "VPA"
    if "PESSOAL" in cod_u or "VENCIMENTOS" in cod_u or "PATRONAIS" in cod_u:
        return "PESSOAL"
    if "JUROS" in cod_u:
        return "JUROS_ENCARGOS_DIVIDA"
    if "INVESTIMENTO" in cod_u:
        return "INVESTIMENTOS"
    if "INVERSOES" in cod_u:
        return "INVERSOES_FINANCEIRAS"
    if "AMORTIZACAO" in cod_u or "DIVIDA" in cod_u:
        return "AMORTIZACAO_DIVIDA"
    if "OPERACOESDECREDITO" in cod_u or "EMPRESTIMO" in cod_u or "FINANCIAMENTO" in cod_u:
        return "OPERACOES_CREDITO"
    if "FUNDEB" in cod_u or "FUNDEB" in desc_u:
        return "TRANSFERENCIAS_FUNDEB"
    if "SUS" in cod_u:
        return "TRANSFERENCIAS_SUS"
    if "FPM" in cod_u or "ITR" in cod_u or "UNIAO" in cod_u:
        return "TRANSFERENCIAS_UNIAO"
    if "ICMS" in cod_u or "IPVA" in cod_u or "ESTADOS" in cod_u:
        return "TRANSFERENCIAS_ESTADO"
    if any(k in cod_u for k in ("IPTU", "ISS", "ITBI", "IRRF", "TRIBUTARIA", "TAXAS", "IMPOSTOS")):
        return "RECEITA_PROPRIA"
    if anexo_codigo in {"DCA-I-D", "DCA-I-E", "RREO-02"}:
        return "OUTRAS_CORRENTES"
    return "OUTRAS"


def write_account_seeds(seeds_dir: Path) -> dict[str, int]:
    seeds_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    with (seeds_dir / "seed_conta_equivalencia.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fonte", "anexo_codigo", "cod_conta_origem", "exercicio_ini", "exercicio_fim", "cod_conta_padrao"])
        w.writerows(CONTA_EQUIVALENCIA_ROWS)
    counts["seed_conta_equivalencia.csv"] = len(CONTA_EQUIVALENCIA_ROWS)

    hier_path = seeds_dir / "seed_conta_hierarquia.csv"
    with hier_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "fonte", "anexo_codigo", "cod_conta_padrao", "descricao",
            "cod_conta_pai", "nivel", "eh_folha", "eh_total", "grupo_analitico", "sinal_semantico",
        ])
        w.writerows(MANUAL_CONTA_HIERARQUIA)
    counts["seed_conta_hierarquia.csv"] = len(MANUAL_CONTA_HIERARQUIA)
    return counts


def enrich_conta_hierarquia_from_silver(conn: psycopg.Connection, seeds_dir: Path) -> int:
    """
    Expande seed_conta_hierarquia.csv de forma deterministica com todas as contas
    nao-pontuadas e desambiguadas presentes em silver.siconfi_registro, preservando
    integralmente a curadoria manual das contas-nucleo.
    """
    equiv_map: dict[tuple[str, str, str], str] = {
        (f, a, orig): pad for (f, a, orig, _, _, pad) in CONTA_EQUIVALENCIA_ROWS
    }

    rows_by_key: dict[tuple[str, str, str], tuple[str, str, str, str, str, int, int, int, str, int]] = {}
    for row in MANUAL_CONTA_HIERARQUIA:
        rows_by_key[(row[0], row[1], row[2])] = row

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (fonte, anexo_codigo, cod_conta)
                fonte,
                anexo_codigo,
                cod_conta,
                COALESCE(conta_descricao, cod_conta) AS descricao
            FROM silver.siconfi_registro
            WHERE eh_vigente = 1
            ORDER BY fonte, anexo_codigo, cod_conta, exercicio DESC;
            """
        )
        silver_accounts = cur.fetchall()

    for fonte, anexo_cod, cod_conta, desc_raw in silver_accounts:
        cod_pad = equiv_map.get((fonte, anexo_cod, cod_conta), cod_conta)
        key = (fonte, anexo_cod, cod_pad)
        if key in rows_by_key:
            continue
        # Contas pontuadas puras (PCASP/Ementario) tem arvore inferida nativamente na Gold,
        # exceto as raizes ja registradas manualmente; catalogamos 100% das nao-pontuadas/desambiguadas
        if re.match(r"^[A-Za-z]*\d+(?:\.\d+)+$", cod_pad):
            continue
        desc = normalize_text(desc_raw) or cod_pad
        pai, nivel, eh_folha, eh_total, grupo, sinal = classify_secondary_account(
            fonte, anexo_cod, cod_pad, desc
        )
        rows_by_key[key] = (
            fonte,
            anexo_cod,
            cod_pad,
            desc,
            pai,
            nivel,
            eh_folha,
            eh_total,
            grupo,
            sinal,
        )

    sorted_rows = sorted(rows_by_key.values(), key=lambda r: (r[0], r[1], r[5], r[2]))
    hier_path = seeds_dir / "seed_conta_hierarquia.csv"
    with hier_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "fonte", "anexo_codigo", "cod_conta_padrao", "descricao",
            "cod_conta_pai", "nivel", "eh_folha", "eh_total", "grupo_analitico", "sinal_semantico",
        ])
        w.writerows(sorted_rows)
    return len(sorted_rows)
