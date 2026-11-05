from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from siconfi_etl.silver.normalizer import normalize_text, strip_accents_upper
from siconfi_etl.silver.seed_loader import (
    ContaEquivalenciaEntry,
    ContaHierarquiaEntry,
    LimiteLrfSeedEntry,
)

PT_MONTH_NAMES: dict[int, str] = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}

PT_MONTH_ABBR: dict[int, str] = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}

GND_NAMES: dict[str, str] = {
    "1": "1 - Pessoal e Encargos Sociais",
    "2": "2 - Juros e Encargos da Dívida",
    "3": "3 - Outras Despesas Correntes",
    "4": "4 - Investimentos",
    "5": "5 - Inversões Financeiras",
    "6": "6 - Amortização da Dívida",
    "9": "9 - Reserva de Contingência",
}

_DOTTED_RE = re.compile(r"^([A-Za-z]*)(\d+(?:\.\d+)+)$")


@dataclass(frozen=True)
class CalendarioRow:
    sk_data: int
    data: date
    ano: int
    semestre: int
    trimestre: int
    quadrimestre: int
    bimestre: int
    mes: int
    nome_mes: str
    mes_ano: str
    eh_fim_bimestre: int
    eh_fim_quadrimestre: int
    eh_fim_semestre: int
    eh_fim_exercicio: int
    label_periodo_rreo: str
    label_periodo_rgf: str


@dataclass(frozen=True)
class ContaDimRow:
    fonte: str
    anexo_codigo: str
    cod_conta: str
    cod_conta_padrao: str
    descricao: str
    cod_conta_pai: str | None
    nivel: int
    caminho: str
    eh_folha: int
    eh_total: int
    grupo_analitico: str
    sinal_semantico: int
    vigencia_ini: date
    vigencia_fim: date | None


def generate_calendar_rows(start_year: int = 2014, end_year: int = 2027) -> list[CalendarioRow]:
    """Gera a serie diaria continua para gold.d_calendario com flags fiscais RREO/RGF/DCA."""
    cur = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    rows: list[CalendarioRow] = []

    while cur <= end:
        y, m, d = cur.year, cur.month, cur.day
        sk_data = y * 10000 + m * 100 + d
        semestre = 1 if m <= 6 else 2
        trimestre = (m - 1) // 3 + 1
        quadrimestre = (m - 1) // 4 + 1
        bimestre = (m - 1) // 2 + 1
        nxt = cur + timedelta(days=1)
        is_month_end = nxt.month != m

        rows.append(
            CalendarioRow(
                sk_data=sk_data,
                data=cur,
                ano=y,
                semestre=semestre,
                trimestre=trimestre,
                quadrimestre=quadrimestre,
                bimestre=bimestre,
                mes=m,
                nome_mes=PT_MONTH_NAMES[m],
                mes_ano=f"{PT_MONTH_ABBR[m]}/{y}",
                eh_fim_bimestre=1 if (is_month_end and m in (2, 4, 6, 8, 10, 12)) else 0,
                eh_fim_quadrimestre=1 if (is_month_end and m in (4, 8, 12)) else 0,
                eh_fim_semestre=1 if (is_month_end and m in (6, 12)) else 0,
                eh_fim_exercicio=1 if (m == 12 and d == 31) else 0,
                label_periodo_rreo=f"{bimestre}º Bim/{y}",
                label_periodo_rgf=f"{quadrimestre}º Quad/{y}",
            )
        )
        cur = nxt

    return rows


def classify_natureza_despesa(cod_natureza: str, raw_desc: str | None) -> tuple[str, str, str]:
    """
    Classifica um codigo de natureza de despesa (ex.: '3.1.90.11.00.00') em:
    (nome_natureza, categoria_economica, grupo_despesa).
    """
    cod_clean = normalize_text(cod_natureza)
    if cod_clean == "0" or not cod_clean:
        return ("Não se aplica", "NAO_APLICA", "Não se aplica")

    desc = normalize_text(raw_desc) or cod_clean
    # Remove prefixo repetido do codigo na descricao se houver
    desc = re.sub(r"^(?:DO|RO)?\d+(?:\.\d+)+\s*-\s*", "", desc).strip() or desc

    digits_part = re.sub(r"^[A-Za-z]+", "", cod_clean)
    parts = [p for p in digits_part.split(".") if p != ""]
    cat_digit = parts[0][0] if parts else ""
    gnd_digit = parts[1][0] if len(parts) >= 2 else (parts[0][1] if parts and len(parts[0]) >= 2 else "")
    modalidade = parts[2] if len(parts) >= 3 else ""

    if modalidade == "91" or cat_digit in ("7", "8"):
        categoria = "INTRA"
    elif cat_digit == "3":
        categoria = "CORRENTE"
    elif cat_digit == "4":
        categoria = "CAPITAL"
    elif cat_digit == "9":
        categoria = "CORRENTE"
    else:
        categoria = "CORRENTE"

    grupo = GND_NAMES.get(gnd_digit, "Outras Naturezas")
    return (desc, categoria, grupo)


def validate_limite_lrf_vigencia(entries: list[LimiteLrfSeedEntry]) -> list[str]:
    """
    Valida T14_VIGENCIA: garante que nao existam intervalos de vigencia sobrepostos
    para o mesmo codigo_limite em seed_limite_lrf.csv.
    """
    by_code: dict[str, list[tuple[date, date]]] = {}
    errors: list[str] = []

    for e in entries:
        ini = date.fromisoformat(e.vigencia_ini)
        fim = date.fromisoformat(e.vigencia_fim) if e.vigencia_fim else date(9999, 12, 31)
        if fim < ini:
            errors.append(f"{e.codigo_limite}: vigencia_fim ({fim}) < vigencia_ini ({ini})")
        for prev_ini, prev_fim in by_code.get(e.codigo_limite, []):
            if not (fim < prev_ini or ini > prev_fim):
                errors.append(
                    f"Sobreposicao de vigencia em {e.codigo_limite}: [{ini}, {fim}] vs [{prev_ini}, {prev_fim}]"
                )
        by_code.setdefault(e.codigo_limite, []).append((ini, fim))

    return errors


def _split_dotted_code(code: str) -> tuple[str, list[str]] | None:
    if "::" in code or "." not in code:
        return None
    m = _DOTTED_RE.match(code.strip())
    if not m:
        return None
    prefix, num_str = m.group(1), m.group(2)
    return (prefix, num_str.split("."))


def _is_zero_segment(seg: str) -> bool:
    return bool(seg) and all(ch == "0" for ch in seg)


def _compute_dotted_sig_len(segments: list[str]) -> int:
    sig_idx = 0
    for idx, seg in enumerate(segments):
        if idx == 0 or not _is_zero_segment(seg):
            sig_idx = idx
    return sig_idx + 1


def _find_dotted_parent(code: str, existing_codes: set[str]) -> tuple[str | None, int]:
    parsed = _split_dotted_code(code)
    if parsed is None:
        return (None, 1)
    prefix, segments = parsed
    sig_len = _compute_dotted_sig_len(segments)
    if sig_len <= 1:
        return (None, 1)

    # Tenta zerar do ultimo segmento significativo ate a raiz para achar o ancestral mais proximo
    for target_len in range(sig_len - 1, 0, -1):
        cand_segs = [
            segments[i] if i < target_len else ("0" * len(segments[i]))
            for i in range(len(segments))
        ]
        cand_code = prefix + ".".join(cand_segs)
        if cand_code in existing_codes and cand_code != code:
            return (cand_code, sig_len)

    # Se nenhum ancestral intermediario estiver materializado, aponta para o pai imediato canonico
    target_len = sig_len - 1
    cand_segs = [
        segments[i] if i < target_len else ("0" * len(segments[i]))
        for i in range(len(segments))
    ]
    cand_code = prefix + ".".join(cand_segs)
    return (cand_code if cand_code != code else None, sig_len)


def infer_dotted_grupo_analitico(anexo_codigo: str, cod_conta_padrao: str, descricao: str) -> str:
    """Atribui grupo_analitico deterministico para contas pontuadas da DCA/RREO."""
    cod_u = strip_accents_upper(cod_conta_padrao)
    desc_u = strip_accents_upper(descricao)

    # 1. Balanco Patrimonial (DCA-I-AB)
    if cod_u == "P1.0.0.0.0.00.00":
        return "ATIVO"
    if cod_u == "P1.1.0.0.0.00.00":
        return "ATIVO_CIRCULANTE"
    if cod_u.startswith("P1.1.1"):
        return "CAIXA_EQUIVALENTES"
    if cod_u.startswith("P1.1."):
        return "ATIVO_CIRCULANTE"
    if cod_u == "P1.2.0.0.0.00.00":
        return "ATIVO_NAO_CIRCULANTE"
    if cod_u.startswith("P1.2.1"):
        return "REALIZAVEL_LP"
    if cod_u.startswith("P1.2."):
        return "ATIVO_NAO_CIRCULANTE"
    if cod_u.startswith("P1."):
        return "ATIVO"
    if cod_u == "P2.0.0.0.0.00.00":
        return "PASSIVO_PL"
    if cod_u.startswith("P2.1."):
        return "PASSIVO_CIRCULANTE"
    if cod_u.startswith("P2.2."):
        return "PASSIVO_NAO_CIRCULANTE"
    if cod_u.startswith("P2.3."):
        return "PATRIMONIO_LIQUIDO"
    if cod_u.startswith("P2."):
        return "PASSIVO_PL"

    # 2. DVP (DCA-I-HI)
    if cod_u.startswith("P3."):
        return "VPD"
    if cod_u.startswith("P4."):
        return "VPA"

    # 3. Receitas Orcamentarias (DCA-I-C / RREO)
    digits = re.sub(r"^[A-Z]+", "", cod_u)
    if cod_u.startswith(("RO", "RD")) or anexo_codigo == "DCA-I-C":
        if "FUNDEB" in desc_u or digits.startswith(("1.7.5", "1.7.2.4", "9.1.7.5")):
            return "TRANSFERENCIAS_FUNDEB"
        if (
            "SISTEMA UNICO DE SAUDE" in desc_u
            or "SUS" in re.findall(r"[A-Z0-9]+", desc_u)
            or digits.startswith(("1.7.1.3", "1.7.2.3", "1.7.1.8.03", "1.7.2.1.33"))
        ):
            return "TRANSFERENCIAS_SUS"
        if digits.startswith(("1.1", "1.2", "1.3", "1.6", "7.1", "7.2", "7.3", "7.6")):
            return "RECEITA_PROPRIA"
        if digits.startswith(("1.7.2", "2.4.2")) or any(
            k in desc_u for k in ("ICMS", "IPVA", "ESTADOS", "ESTADO")
        ):
            return "TRANSFERENCIAS_ESTADO"
        if digits.startswith(("1.7", "2.4")):
            return "TRANSFERENCIAS_UNIAO"
        if digits.startswith(("2.1", "8.1")):
            return "OPERACOES_CREDITO"
        return "OUTRAS"

    # 4. Despesas por Natureza (DCA-I-D, DCA-I-F, RREO-01, RREO-07)
    if cod_u.startswith("DO") or anexo_codigo in ("DCA-I-D", "DCA-I-F"):
        if digits.startswith("3.1"):
            return "PESSOAL"
        if digits.startswith("3.2"):
            return "JUROS_ENCARGOS_DIVIDA"
        if digits.startswith("3.3"):
            return "OUTRAS_CORRENTES"
        if digits.startswith("4.4"):
            return "INVESTIMENTOS"
        if digits.startswith("4.5"):
            return "INVERSOES_FINANCEIRAS"
        if digits.startswith("4.6"):
            return "AMORTIZACAO_DIVIDA"
        return "OUTRAS_CORRENTES"

    return "OUTRAS"


def build_account_hierarchy_catalog(
    silver_accounts: list[tuple[str, str, str, str]],
    equiv_entries: list[ContaEquivalenciaEntry],
    hier_entries: list[ContaHierarquiaEntry],
) -> tuple[list[ContaDimRow], int]:
    """
    Constroi o catalogo unificado para gold.d_conta combinando:
    1. Mapa de equivalencia (seed_conta_equivalencia.csv)
    2. Derivacao algoritmica para contas pontuadas (DCA PCASP, Receita, Despesa)
    3. Curadoria hibrida (seed_conta_hierarquia.csv)
    Retorna (lista_de_ContaDimRow, qtd_contas_orfas_T03).
    """
    equiv_map: dict[tuple[str, str, str], str] = {
        (e.fonte, e.anexo_codigo, e.cod_conta_origem): e.cod_conta_padrao for e in equiv_entries
    }
    hier_by_padrao: dict[tuple[str, str, str], ContaHierarquiaEntry] = {
        (h.fonte, h.anexo_codigo, h.cod_conta_padrao): h for h in hier_entries
    }

    # Uniao das contas observadas na Silver com as contas canonicas do seed_conta_hierarquia
    raw_by_key: dict[tuple[str, str, str], tuple[str, str]] = {}
    for h in hier_entries:
        raw_by_key[(h.fonte, h.anexo_codigo, h.cod_conta_padrao)] = (h.cod_conta_padrao, h.descricao)

    for fonte, anexo_codigo, cod_conta, desc in silver_accounts:
        cod_pad = equiv_map.get((fonte, anexo_codigo, cod_conta), cod_conta)
        clean_desc = normalize_text(desc) or cod_conta
        # Se houver descricao curada no seed para o codigo padrao, preserva-a
        seed_hit = hier_by_padrao.get((fonte, anexo_codigo, cod_pad))
        if seed_hit is not None and seed_hit.descricao:
            clean_desc = seed_hit.descricao
        raw_by_key[(fonte, anexo_codigo, cod_conta)] = (cod_pad, clean_desc)

    # Agrupa codigos pontuados por (fonte, anexo_codigo) para derivar arvore e folhas
    dotted_by_anexo: dict[tuple[str, str], set[str]] = {}
    for (fonte, anexo_codigo, cod_conta), (cod_pad, _) in raw_by_key.items():
        if _split_dotted_code(cod_pad) is not None:
            dotted_by_anexo.setdefault((fonte, anexo_codigo), set()).add(cod_pad)

    # Passo 1: determinar pai preliminar, nivel, grupo e sinal para cada (fonte, anexo, cod_conta)
    prelim: dict[tuple[str, str, str], dict[str, object]] = {}
    t03_orphans = 0

    for (fonte, anexo_codigo, cod_conta), (cod_pad, desc) in raw_by_key.items():
        seed_hit = hier_by_padrao.get((fonte, anexo_codigo, cod_pad)) or hier_by_padrao.get(
            (fonte, anexo_codigo, cod_conta)
        )
        is_dotted = _split_dotted_code(cod_pad) is not None

        if is_dotted:
            anexo_dotted_set = dotted_by_anexo.get((fonte, anexo_codigo), set())
            pai_auto, nivel_auto = _find_dotted_parent(cod_pad, anexo_dotted_set)
            if seed_hit is not None:
                pai = seed_hit.cod_conta_pai or pai_auto
                nivel = seed_hit.nivel or nivel_auto
                grupo = seed_hit.grupo_analitico or infer_dotted_grupo_analitico(anexo_codigo, cod_pad, desc)
                sinal = seed_hit.sinal_semantico
                eh_folha = seed_hit.eh_folha
                eh_total = seed_hit.eh_total
            else:
                pai = pai_auto
                nivel = nivel_auto
                grupo = infer_dotted_grupo_analitico(anexo_codigo, cod_pad, desc)
                sinal = -1 if (desc.startswith("(-)") or cod_pad.startswith("RD")) else 1
                eh_total = 1 if nivel == 1 else 0
                eh_folha = 0 if eh_total == 1 else 1

            prelim[(fonte, anexo_codigo, cod_conta)] = {
                "cod_pad": cod_pad,
                "desc": desc,
                "pai": pai,
                "nivel": int(nivel),
                "eh_folha": int(eh_folha),
                "eh_total": int(eh_total),
                "grupo": str(grupo),
                "sinal": int(sinal),
            }
        elif seed_hit is not None:
            prelim[(fonte, anexo_codigo, cod_conta)] = {
                "cod_pad": cod_pad,
                "desc": desc,
                "pai": seed_hit.cod_conta_pai,
                "nivel": int(seed_hit.nivel),
                "eh_folha": int(seed_hit.eh_folha),
                "eh_total": int(seed_hit.eh_total),
                "grupo": str(seed_hit.grupo_analitico or "OUTRAS"),
                "sinal": int(seed_hit.sinal_semantico),
            }
        else:
            # Conta sem hierarquia em seed e nao-pontuada: T03_CONTA_SEM_HIERARQUIA (eh_folha=0 seguro)
            t03_orphans += 1
            prelim[(fonte, anexo_codigo, cod_conta)] = {
                "cod_pad": cod_pad,
                "desc": desc,
                "pai": None,
                "nivel": 1,
                "eh_folha": 0,
                "eh_total": 0,
                "grupo": "OUTRAS",
                "sinal": 1,
            }

    # Passo 2: Qualquer conta que seja pai de outra conta no mesmo (fonte, anexo) NUNCA pode ser eh_folha=1
    parents_by_anexo: dict[tuple[str, str], set[str]] = {}
    for (fonte, anexo_codigo, _), info in prelim.items():
        pai_val = info["pai"]
        if isinstance(pai_val, str) and pai_val:
            parents_by_anexo.setdefault((fonte, anexo_codigo), set()).add(pai_val)

    for (fonte, anexo_codigo, cod_conta), info in prelim.items():
        anexo_parents = parents_by_anexo.get((fonte, anexo_codigo), set())
        cod_pad = str(info["cod_pad"])
        if cod_conta in anexo_parents or cod_pad in anexo_parents:
            info["eh_folha"] = 0
            info["eh_total"] = 1
        elif int(info["eh_total"]) == 1:
            info["eh_folha"] = 0

    # Passo 3: Construir caminho hierarquico ("Raiz > Subtotal > Conta")
    parent_lookup: dict[tuple[str, str, str], str | None] = {}
    for (fonte, anexo_codigo, cod_conta), info in prelim.items():
        pai_str = str(info["pai"]) if info["pai"] else None
        parent_lookup[(fonte, anexo_codigo, cod_conta)] = pai_str
        parent_lookup[(fonte, anexo_codigo, str(info["cod_pad"]))] = pai_str

    rows: list[ContaDimRow] = []
    for (fonte, anexo_codigo, cod_conta), info in sorted(prelim.items()):
        cod_pad = str(info["cod_pad"])
        chain = [cod_pad]
        visited = {cod_conta, cod_pad}
        curr_parent = str(info["pai"]) if info["pai"] else None
        depth = 0
        while curr_parent and curr_parent not in visited and depth < 12:
            chain.append(curr_parent)
            visited.add(curr_parent)
            curr_parent = parent_lookup.get((fonte, anexo_codigo, curr_parent))
            depth += 1
        chain.reverse()
        caminho = " > ".join(chain)

        rows.append(
            ContaDimRow(
                fonte=fonte,
                anexo_codigo=anexo_codigo,
                cod_conta=cod_conta,
                cod_conta_padrao=cod_pad,
                descricao=str(info["desc"]),
                cod_conta_pai=str(info["pai"]) if info["pai"] else None,
                nivel=int(info["nivel"]),
                caminho=caminho,
                eh_folha=int(info["eh_folha"]),
                eh_total=int(info["eh_total"]),
                grupo_analitico=str(info["grupo"]),
                sinal_semantico=int(info["sinal"]),
                vigencia_ini=date(1900, 1, 1),
                vigencia_fim=None,
            )
        )

    return (rows, t03_orphans)
