from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from siconfi_etl.silver.normalizer import (
    extract_cod_natureza,
    normalize_anexo_codigo,
    normalize_cod_conta,
    normalize_rotulo,
    normalize_text,
    parse_valor_decimal,
    slugify_token,
    strip_accents_upper,
)
from siconfi_etl.silver.seed_loader import ColunaResolver, FonteRecursoResolver

# Tabela oficial de Funcoes (Portaria MOG n. 42/1999 + Reservas)
OFFICIAL_FUNCOES: dict[str, str] = {
    "01": "Legislativa",
    "02": "Judiciária",
    "03": "Essencial à Justiça",
    "04": "Administração",
    "05": "Defesa Nacional",
    "06": "Segurança Pública",
    "07": "Relações Exteriores",
    "08": "Assistência Social",
    "09": "Previdência Social",
    "10": "Saúde",
    "11": "Trabalho",
    "12": "Educação",
    "13": "Cultura",
    "14": "Direitos da Cidadania",
    "15": "Urbanismo",
    "16": "Habitação",
    "17": "Saneamento",
    "18": "Gestão Ambiental",
    "19": "Ciência e Tecnologia",
    "20": "Agricultura",
    "21": "Organização Agrária",
    "22": "Indústria",
    "23": "Comércio e Serviços",
    "24": "Comunicações",
    "25": "Energia",
    "26": "Transporte",
    "27": "Desporto e Lazer",
    "28": "Encargos Especiais",
    "97": "Reserva do RPPS",
    "99": "Reserva de Contingência",
}

# Tabela oficial de Subfuncoes (Portaria MOG n. 42/1999 + atualizacoes STN)
OFFICIAL_SUBFUNCOES: dict[str, str] = {
    "031": "Ação Legislativa",
    "032": "Controle Externo",
    "061": "Ação Judiciária",
    "062": "Defesa do Interesse Público no Processo Judiciário",
    "091": "Defesa da Ordem Jurídica",
    "092": "Representação Judicial e Extrajudicial",
    "121": "Planejamento e Orçamento",
    "122": "Administração Geral",
    "123": "Administração Financeira",
    "124": "Controle Interno",
    "125": "Normatização e Fiscalização",
    "126": "Tecnologia da Informação",
    "127": "Ordenamento Territorial",
    "128": "Formação de Recursos Humanos",
    "129": "Administração de Receitas",
    "130": "Administração de Concessões",
    "131": "Comunicação Social",
    "151": "Defesa Aérea",
    "152": "Defesa Naval",
    "153": "Defesa Terrestre",
    "181": "Policiamento",
    "182": "Defesa Civil",
    "183": "Informação e Inteligência",
    "211": "Relações Diplomáticas",
    "212": "Cooperação Internacional",
    "241": "Assistência à Pessoa Idosa",
    "242": "Assistência à Pessoa com Deficiência",
    "243": "Assistência à Criança e ao Adolescente",
    "244": "Assistência Comunitária",
    "245": "Serviços Socioassistenciais",
    "271": "Previdência Básica",
    "272": "Previdência do Regime Estatutário",
    "273": "Previdência Complementar",
    "274": "Previdência Especial",
    "301": "Atenção Básica",
    "302": "Assistência Hospitalar e Ambulatorial",
    "303": "Suporte Profilático e Terapêutico",
    "304": "Vigilância Sanitária",
    "305": "Vigilância Epidemiológica",
    "306": "Alimentação e Nutrição",
    "331": "Proteção e Benefícios ao Trabalhador",
    "332": "Relações de Trabalho",
    "333": "Empregabilidade",
    "334": "Fomento ao Trabalho",
    "361": "Ensino Fundamental",
    "362": "Ensino Médio",
    "363": "Ensino Profissional",
    "364": "Ensino Superior",
    "365": "Educação Infantil",
    "366": "Educação de Jovens e Adultos",
    "367": "Educação Especial",
    "368": "Educação Básica",
    "391": "Patrimônio Histórico, Artístico e Arqueológico",
    "392": "Difusão Cultural",
    "421": "Custódia e Reintegração Social",
    "422": "Direitos Individuais, Coletivos e Difusos",
    "423": "Assistência aos Povos Indígenas",
    "451": "Infraestrutura Urbana",
    "452": "Serviços Urbanos",
    "453": "Transportes Coletivos Urbanos",
    "481": "Habitação Rural",
    "482": "Habitação Urbana",
    "511": "Saneamento Básico Rural",
    "512": "Saneamento Básico Urbano",
    "541": "Preservação e Conservação Ambiental",
    "542": "Controle Ambiental",
    "543": "Recuperação de Áreas Degradadas",
    "544": "Recursos Hídricos",
    "545": "Meteorologia",
    "571": "Desenvolvimento Científico",
    "572": "Desenvolvimento Tecnológico e Engenharia",
    "573": "Difusão do Conhecimento Científico e Tecnológico",
    "601": "Promoção da Produção Vegetal",
    "602": "Promoção da Produção Animal",
    "603": "Defesa Sanitária Animal",
    "604": "Defesa Sanitária Vegetal",
    "605": "Abastecimento",
    "606": "Extensão Rural",
    "607": "Irrigação",
    "608": "Promoção da Produção Agropecuária",
    "609": "Defesa Agropecuária",
    "631": "Reforma Agrária",
    "632": "Colonização",
    "661": "Promoção Industrial",
    "662": "Produção Industrial",
    "663": "Mineração",
    "664": "Propriedade Industrial",
    "665": "Normalização e Qualidade",
    "691": "Promoção Comercial",
    "692": "Comercialização",
    "693": "Comércio Exterior",
    "694": "Serviços Financeiros",
    "695": "Turismo",
    "721": "Comunicações Postais",
    "722": "Telecomunicações",
    "751": "Conservação de Energia",
    "752": "Energia Elétrica",
    "753": "Combustíveis Minerais",
    "754": "Biocombustíveis",
    "781": "Transporte Aéreo",
    "782": "Transporte Rodoviário",
    "783": "Transporte Ferroviário",
    "784": "Transporte Aquaviário",
    "785": "Transportes Especiais",
    "811": "Desporto de Rendimento",
    "812": "Desporto Comunitário",
    "813": "Lazer",
    "841": "Refinanciamento da Dívida Interna",
    "842": "Refinanciamento da Dívida Externa",
    "843": "Serviço da Dívida Interna",
    "844": "Serviço da Dívida Externa",
    "845": "Outras Transferências",
    "846": "Outros Encargos Especiais",
    "847": "Transferências para a Educação Básica",
    "999": "Demais Subfunções",
}


def _lookup_key(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", strip_accents_upper(text))


_FUNCAO_BY_NAME: dict[str, str] = {_lookup_key(name): code for code, name in OFFICIAL_FUNCOES.items()}

_SUBFUNCAO_BY_NAME: dict[str, str] = {
    _lookup_key(name): code for code, name in OFFICIAL_SUBFUNCOES.items()
}
# Variantes historicas de grafia observadas nos payloads reais de 2015-2026
_SUBFUNCAO_ALIASES: dict[str, str] = {
    "ASSISTENCIAAOIDOSO": "241",
    "ASSISTENCIAAOPORTADORDEDEFICIENCIA": "242",
    "INFRAESTRUTURAURBANA": "451",
    "TRANSPORTEAEREO": "781",
    "TRANSPORTEAREO": "781",
    "TRANSPORTEHIDROVIARIO": "784",
    "TRANSPORTEAQUAVIARIO": "784",
    "PATRIMONIOHISTORICOARTISTICOEARQUEOLOGICO": "391",
    "DIREITOSINDIVIDUAISCOLETIVOSEDIFUSOS": "422",
}
_SUBFUNCAO_BY_NAME.update(_SUBFUNCAO_ALIASES)

# Subfuncoes especificas cujo codigo implica univocamente a funcao pai caso necessario
_DEFAULT_PARENT_FUNCAO_FOR_SUB: dict[str, str] = {
    "031": "01",
    "032": "01",
    "061": "02",
    "062": "02",
    "091": "03",
    "092": "03",
    "121": "04",
    "123": "04",
    "124": "04",
    "125": "04",
    "126": "04",
    "127": "04",
    "128": "04",
    "129": "04",
    "130": "04",
    "131": "04",
    "151": "05",
    "152": "05",
    "153": "05",
    "181": "06",
    "182": "06",
    "183": "06",
    "211": "07",
    "212": "07",
    "241": "08",
    "242": "08",
    "243": "08",
    "244": "08",
    "245": "08",
    "271": "09",
    "272": "09",
    "273": "09",
    "274": "09",
    "301": "10",
    "302": "10",
    "303": "10",
    "304": "10",
    "305": "10",
    "306": "10",
    "331": "11",
    "332": "11",
    "333": "11",
    "334": "11",
    "361": "12",
    "362": "12",
    "363": "12",
    "364": "12",
    "365": "12",
    "366": "12",
    "367": "12",
    "368": "12",
    "391": "13",
    "392": "13",
    "421": "14",
    "422": "14",
    "423": "14",
    "451": "15",
    "452": "15",
    "453": "15",
    "481": "16",
    "482": "16",
    "511": "17",
    "512": "17",
    "541": "18",
    "542": "18",
    "543": "18",
    "544": "18",
    "545": "18",
    "571": "19",
    "572": "19",
    "573": "19",
    "601": "20",
    "602": "20",
    "603": "20",
    "604": "20",
    "605": "20",
    "606": "20",
    "607": "20",
    "608": "20",
    "609": "20",
    "631": "21",
    "632": "21",
    "661": "22",
    "662": "22",
    "663": "22",
    "664": "22",
    "665": "22",
    "691": "23",
    "692": "23",
    "693": "23",
    "694": "23",
    "695": "23",
    "721": "24",
    "722": "24",
    "751": "25",
    "752": "25",
    "753": "25",
    "754": "25",
    "781": "26",
    "782": "26",
    "783": "26",
    "784": "26",
    "785": "26",
    "811": "27",
    "812": "27",
    "813": "27",
    "841": "28",
    "842": "28",
    "843": "28",
    "844": "28",
    "845": "28",
    "846": "28",
    "847": "28",
}

_DCA_FUNC_RE = re.compile(r"^(\d{2})\s*-\s*(.+)$")
_DCA_SUBFUNC_RE = re.compile(r"^(\d{2})\.(\d{3})\s*-\s*(.+)$")
_FU_PREFIX_RE = re.compile(r"^FU(\d{2})\s*-\s*(.+)$", flags=re.IGNORECASE)
_YEAR_ONLY_RE = re.compile(r"^(19\d{2}|20\d{2}|21\d{2})$")


@dataclass(frozen=True)
class DisambiguatedRecord:
    anexo: str
    anexo_codigo: str
    rotulo_origem: str
    cod_conta_original: str
    cod_conta: str
    conta_descricao: str | None
    coluna_origem: str
    coluna_padrao: str | None
    cod_funcao: str | None
    cod_subfuncao: str | None
    cod_natureza: str | None
    cod_fonte: str | None
    valor: Decimal | None
    populacao: int | None


def _disambiguate_dca_funcao(
    cod_conta_orig: str,
    conta_desc: str,
) -> tuple[str, str | None, str | None]:
    """Desambigua linhas de DCA-I-E e DCA-I-G (Despesas e RP por Funcao/Subfuncao)."""
    m_sub = _DCA_SUBFUNC_RE.match(conta_desc)
    if m_sub:
        fu, sub = m_sub.group(1), m_sub.group(2)
        return f"{cod_conta_orig}::F{fu}.{sub}", fu, sub

    m_fu_pref = _FU_PREFIX_RE.match(conta_desc)
    if m_fu_pref:
        fu = m_fu_pref.group(1)
        rest_key = _lookup_key(m_fu_pref.group(2))
        sub = _SUBFUNCAO_BY_NAME.get(rest_key, "999")
        return f"{cod_conta_orig}::F{fu}.{sub}", fu, sub

    m_fu = _DCA_FUNC_RE.match(conta_desc)
    if m_fu:
        fu = m_fu.group(1)
        return f"{cod_conta_orig}::F{fu}", fu, ""

    key = _lookup_key(conta_desc)
    if "EXCETOINTR" in key:
        return f"{cod_conta_orig}::EXCETO_INTRA", None, None
    if "INTRAORCAMENT" in key:
        return f"{cod_conta_orig}::INTRA", None, None

    return f"{cod_conta_orig}::{slugify_token(conta_desc)}", None, None


def _disambiguate_rreo02_row(
    cod_conta_orig: str,
    conta_desc: str,
    current_funcao: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    """
    Desambigua linhas de RREO-02 preservando continuidade longitudinal entre 2015-2017 e 2018+.
    Retorna (cod_conta, cod_funcao, cod_subfuncao, next_current_funcao).
    """
    key = _lookup_key(conta_desc)

    # Linhas sinteticas de totalizacao da tabela
    if "DESPESASEXCETOINTR" in key:
        return f"{cod_conta_orig}::EXCETO_INTRA", None, None, None
    if "DESPESASINTRAORCAMENT" in key:
        return f"{cod_conta_orig}::INTRA", None, None, None
    if key.startswith("TOTALIII") or key == "TOTAL":
        return f"{cod_conta_orig}::TOTAL_GERAL", None, None, None

    # Subfuncoes prefixadas com FUxx (padrao 2018+)
    m_fu = _FU_PREFIX_RE.match(conta_desc)
    if m_fu:
        fu = m_fu.group(1)
        sub_name_key = _lookup_key(m_fu.group(2))
        sub = _SUBFUNCAO_BY_NAME.get(sub_name_key, "999")
        return f"{cod_conta_orig}::F{fu}.{sub}", fu, sub, fu

    # Linha de Funcao (01..28, 97, 99)
    if key in _FUNCAO_BY_NAME:
        fu = _FUNCAO_BY_NAME[key]
        return f"{cod_conta_orig}::F{fu}", fu, "", fu

    # Linha de Subfuncao sem prefixo FUxx (2015-2017 ou subfuncoes especificas em 2018+)
    if key in _SUBFUNCAO_BY_NAME:
        sub = _SUBFUNCAO_BY_NAME[key]
        fu = current_funcao or _DEFAULT_PARENT_FUNCAO_FOR_SUB.get(sub, "00")
        return f"{cod_conta_orig}::F{fu}.{sub}", fu, sub, current_funcao

    # Fallback defensivo caso surja nova rubrica futura
    return f"{cod_conta_orig}::{slugify_token(conta_desc)}", None, None, current_funcao


def _disambiguate_rreo07(cod_conta_orig: str, conta_desc: str) -> str:
    key = _lookup_key(conta_desc)
    if "EXCETOINTR" in key:
        return f"{cod_conta_orig}::EXCETO_INTRA"
    if "INTRAORCAMENT" in key:
        return f"{cod_conta_orig}::INTRA"
    if key.startswith("TOTALIII") or key == "TOTAL":
        return f"{cod_conta_orig}::TOTAL_GERAL"
    if key == "PODEREXECUTIVO":
        return f"{cod_conta_orig}::EXEC"
    if key == "PODERLEGISLATIVO":
        return f"{cod_conta_orig}::LEG"
    if key == "PODERJUDICIARIO":
        return f"{cod_conta_orig}::JUD"
    if key == "MINISTERIOPUBLICO":
        return f"{cod_conta_orig}::MP"
    if key == "DEFENSORIAPUBLICA":
        return f"{cod_conta_orig}::DP"
    if key == "CAMARAMUNICIPAL":
        return f"{cod_conta_orig}::CAMARA_MUNICIPAL"
    return f"{cod_conta_orig}::ORG_{slugify_token(conta_desc)}"


def disambiguate_delivery_items(
    fonte: str,
    exercicio: int,
    raw_items: list[dict[str, Any]],
    coluna_resolver: ColunaResolver,
    fonte_recurso_resolver: FonteRecursoResolver,
) -> list[DisambiguatedRecord]:
    """
    Normaliza e desambigua todos os itens de uma entrega Bronze, garantindo
    chave natural estritamente unica dentro da entrega.
    """
    fonte_clean = normalize_text(fonte).upper()
    records: list[DisambiguatedRecord] = []

    # Estado posicional por (rotulo_origem, coluna_origem) para o RREO-02
    rreo02_func_state: dict[tuple[str, str], str | None] = {}
    # Controle de chave natural vista dentro da entrega para evitar colisao residual
    seen_natural_keys: Counter[tuple[str, str, str, str]] = Counter()

    for item in raw_items:
        anexo = normalize_text(item.get("anexo"))
        anexo_codigo = normalize_anexo_codigo(fonte_clean, anexo)
        rotulo_origem = normalize_rotulo(item.get("rotulo"))
        cod_conta_orig = normalize_cod_conta(item.get("cod_conta"))
        conta_desc_raw = normalize_text(item.get("conta"))
        conta_desc = conta_desc_raw if conta_desc_raw else None
        coluna_origem = normalize_text(item.get("coluna")) or "VALOR"

        valor = parse_valor_decimal(item.get("valor"))
        pop_raw = item.get("populacao")
        populacao = int(pop_raw) if pop_raw is not None and str(pop_raw).strip() != "" else None

        cod_conta = cod_conta_orig
        cod_funcao: str | None = None
        cod_subfuncao: str | None = None
        cod_natureza = extract_cod_natureza(fonte_clean, anexo_codigo, cod_conta_orig)
        cod_fonte: str | None = None

        if anexo_codigo in {"DCA-I-E", "DCA-I-G"} and cod_conta_orig == "TotalDespesas" and conta_desc:
            cod_conta, cod_funcao, cod_subfuncao = _disambiguate_dca_funcao(cod_conta_orig, conta_desc)

        elif anexo_codigo == "RREO-02" and conta_desc:
            state_key = (rotulo_origem, coluna_origem)
            cur_fu = rreo02_func_state.get(state_key)
            cod_conta, cod_funcao, cod_subfuncao, next_fu = _disambiguate_rreo02_row(
                cod_conta_orig, conta_desc, cur_fu
            )
            rreo02_func_state[state_key] = next_fu

        elif anexo_codigo == "RGF-05" and conta_desc:
            fr_entry = fonte_recurso_resolver.resolve(conta_desc, exercicio)
            if fr_entry is not None:
                if fr_entry.eh_total_anexo05 == 1:
                    cod_fonte = "0"
                    cod_conta = f"{cod_conta_orig}::{fr_entry.cod_fonte_padrao}"
                else:
                    cod_fonte = fr_entry.cod_fonte
                    cod_conta = f"{cod_conta_orig}::FR_{fr_entry.cod_fonte}"
            else:
                # Fonte desconhecida: cod_fonte fica None para acionar T17_FONTE_SEM_MAPA
                cod_fonte = None
                cod_conta = f"{cod_conta_orig}::FR_UNMAPPED_{slugify_token(conta_desc)}"

        elif anexo_codigo == "RREO-07" and conta_desc:
            cod_conta = _disambiguate_rreo07(cod_conta_orig, conta_desc)

        elif anexo_codigo == "RREO-10" and conta_desc and _YEAR_ONLY_RE.match(conta_desc):
            cod_conta = f"{cod_conta_orig}::ANO_{conta_desc}"

        elif anexo_codigo == "RREO-13" and cod_conta_orig == "DespesasPPPEnteFederado" and conta_desc:
            if _lookup_key(conta_desc) not in {"PADRAO", ""}:
                cod_conta = f"{cod_conta_orig}::PPP_{slugify_token(conta_desc)}"

        coluna_padrao = coluna_resolver.resolve(fonte_clean, anexo_codigo, coluna_origem, exercicio)
        col_effective = coluna_padrao or coluna_origem

        # Garantia de unicidade intra-entrega (ex.: segundo quadro atuarial de RREO-10 em 2015-2017)
        nat_key = (anexo_codigo, rotulo_origem, cod_conta, col_effective)
        seen_natural_keys[nat_key] += 1
        occ = seen_natural_keys[nat_key]
        if occ > 1:
            if anexo_codigo == "RREO-10":
                cod_conta = f"{cod_conta}_PLANO{occ}"
            else:
                cod_conta = f"{cod_conta}::DUP{occ}"

        records.append(
            DisambiguatedRecord(
                anexo=anexo,
                anexo_codigo=anexo_codigo,
                rotulo_origem=rotulo_origem,
                cod_conta_original=cod_conta_orig,
                cod_conta=cod_conta,
                conta_descricao=conta_desc,
                coluna_origem=coluna_origem,
                coluna_padrao=coluna_padrao,
                cod_funcao=cod_funcao,
                cod_subfuncao=cod_subfuncao,
                cod_natureza=cod_natureza,
                cod_fonte=cod_fonte,
                valor=valor,
                populacao=populacao,
            )
        )

    return records
