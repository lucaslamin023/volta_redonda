from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

QUANT_CENTS = Decimal("0.01")

# Mapeamento deterministico dos 28 nomes de anexos encontrados no SICONFI (2015-2026)
ANEXO_SLUG_MAP: dict[tuple[str, str], str] = {
    ("DCA", "DCA-Anexo I-AB"): "DCA-I-AB",
    ("DCA", "DCA-Anexo I-C"): "DCA-I-C",
    ("DCA", "DCA-Anexo I-D"): "DCA-I-D",
    ("DCA", "DCA-Anexo I-E"): "DCA-I-E",
    ("DCA", "DCA-Anexo I-F"): "DCA-I-F",
    ("DCA", "DCA-Anexo I-G"): "DCA-I-G",
    ("DCA", "DCA-Anexo I-HI"): "DCA-I-HI",
    ("RGF", "RGF-Anexo 01"): "RGF-01",
    ("RGF", "RGF-Anexo 02"): "RGF-02",
    ("RGF", "RGF-Anexo 03"): "RGF-03",
    ("RGF", "RGF-Anexo 04"): "RGF-04",
    ("RGF", "RGF-Anexo 05"): "RGF-05",
    ("RGF", "RGF-Anexo 06"): "RGF-06",
    ("RREO", "RREO-Anexo 01"): "RREO-01",
    ("RREO", "RREO-Anexo 02"): "RREO-02",
    ("RREO", "RREO-Anexo 03"): "RREO-03",
    ("RREO", "RREO-Anexo 04"): "RREO-04",
    ("RREO", "RREO-Anexo 04 - RPPS"): "RREO-04",
    ("RREO", "RREO-Anexo 04.1"): "RREO-04-1",
    ("RREO", "RREO-Anexo 04.2"): "RREO-04-2",
    ("RREO", "RREO-Anexo 05"): "RREO-05",
    ("RREO", "RREO-Anexo 06"): "RREO-06",
    ("RREO", "RREO-Anexo 07"): "RREO-07",
    ("RREO", "RREO-Anexo 08"): "RREO-08",
    ("RREO", "RREO-Anexo 09"): "RREO-09",
    ("RREO", "RREO-Anexo 10 - RPPS"): "RREO-10",
    ("RREO", "RREO-Anexo 10"): "RREO-10",
    ("RREO", "RREO-Anexo 11"): "RREO-11",
    ("RREO", "RREO-Anexo 12"): "RREO-12",
    ("RREO", "RREO-Anexo 13"): "RREO-13",
    ("RREO", "RREO-Anexo 14"): "RREO-14",
}

_YEAR_TOKEN_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_NON_ALNUM_SLUG_RE = re.compile(r"[^A-Z0-9]+")


def normalize_text(value: str | None) -> str:
    """Aplica Unicode NFC, strip e colapso de multiplos espacos internos."""
    if value is None:
        return ""
    nfc = unicodedata.normalize("NFC", str(value))
    return " ".join(nfc.strip().split())


def normalize_cod_conta(value: str | None) -> str:
    """Preserva caixa, pontos e zeros a esquerda de cod_conta, aplicando apenas NFC e strip."""
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip()


def normalize_rotulo(value: str | None) -> str:
    """Normaliza rotulo_origem preservando o texto original (default 'Padrão' quando nulo/vazio)."""
    cleaned = normalize_text(value)
    return cleaned if cleaned else "Padrão"


def strip_accents_upper(value: str) -> str:
    """Auxiliar para comparacoes e geracao de slugs ASCII deterministas."""
    nfkd = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return ascii_only.upper()


def slugify_token(value: str, max_len: int = 48) -> str:
    """Converte um texto livre em identificador ASCII maiusculo estavel."""
    base = strip_accents_upper(value)
    slug = _NON_ALNUM_SLUG_RE.sub("_", base).strip("_")
    return slug[:max_len].strip("_") or "ITEM"


def normalize_anexo_codigo(fonte: str, anexo: str | None) -> str:
    """Converte o nome do anexo do SICONFI para o slug controlado anexo_codigo."""
    fonte_clean = normalize_text(fonte).upper()
    anexo_clean = normalize_text(anexo)
    mapped = ANEXO_SLUG_MAP.get((fonte_clean, anexo_clean))
    if mapped is not None:
        return mapped

    # Fallback deterministico caso surja anexo novo em exercicios futuros
    cleaned = re.sub(r"^(DCA|RREO|RGF)\s*-\s*Anexo\s*", "", anexo_clean, flags=re.IGNORECASE)
    slug = slugify_token(cleaned).replace("_", "-")
    return f"{fonte_clean}-{slug}" if slug else fonte_clean


def normalize_periodicidade(fonte: str, raw_periodicidade: str | None) -> str:
    """Padroniza periodicidade para ANUAL, BIMESTRAL, QUADRIMESTRAL ou SEMESTRAL."""
    fonte_u = normalize_text(fonte).upper()
    if fonte_u == "DCA":
        return "ANUAL"
    raw_u = normalize_text(raw_periodicidade).upper()
    mapping = {
        "A": "ANUAL",
        "ANUAL": "ANUAL",
        "B": "BIMESTRAL",
        "BIMESTRAL": "BIMESTRAL",
        "Q": "QUADRIMESTRAL",
        "QUADRIMESTRAL": "QUADRIMESTRAL",
        "S": "SEMESTRAL",
        "SEMESTRAL": "SEMESTRAL",
    }
    if raw_u in mapping:
        return mapping[raw_u]
    if fonte_u == "RREO":
        return "BIMESTRAL"
    raise ValueError(f"Periodicidade invalida: fonte={fonte!r}, raw={raw_periodicidade!r}")


def compute_data_fim_periodo(
    fonte: str,
    exercicio: int,
    periodo_codigo: int,
    periodicidade: str,
) -> date:
    """Calcula a data exata de fechamento do periodo conforme Secao 6.1 do guia."""
    per_norm = normalize_periodicidade(fonte, periodicidade)
    if per_norm == "ANUAL":
        return date(exercicio, 12, 31)

    if per_norm == "BIMESTRAL":
        if not 1 <= periodo_codigo <= 6:
            raise ValueError(f"Bimestre invalido para RREO: {periodo_codigo}")
        month = periodo_codigo * 2
        last_day = calendar.monthrange(exercicio, month)[1]
        return date(exercicio, month, last_day)

    if per_norm == "QUADRIMESTRAL":
        if not 1 <= periodo_codigo <= 3:
            raise ValueError(f"Quadrimestre invalido para RGF: {periodo_codigo}")
        month = periodo_codigo * 4
        last_day = calendar.monthrange(exercicio, month)[1]
        return date(exercicio, month, last_day)

    if per_norm == "SEMESTRAL":
        if not 1 <= periodo_codigo <= 2:
            raise ValueError(f"Semestre invalido para RGF: {periodo_codigo}")
        month = periodo_codigo * 6
        last_day = calendar.monthrange(exercicio, month)[1]
        return date(exercicio, month, last_day)

    raise ValueError(f"Combinacao de tempo nao suportada: {fonte}/{exercicio}/{periodo_codigo}/{periodicidade}")


def parse_valor_decimal(raw_val: object) -> Decimal | None:
    """
    Converte valor monetario/percentual para Decimal(18,2) sem jamais passar por float.
    Celulas nulas ou vazias retornam None (NULL != 0).
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, bool):
        raise TypeError("Booleano nao permitido em campo monetario.")
    if isinstance(raw_val, float):
        raise TypeError("Proibido uso de float em campo monetario (Principio #2).")

    if isinstance(raw_val, Decimal):
        dec = raw_val
    elif isinstance(raw_val, int):
        dec = Decimal(raw_val)
    elif isinstance(raw_val, str):
        cleaned = raw_val.strip()
        if cleaned == "" or cleaned.lower() in {"null", "none", "-"}:
            return None
        # Suporta string com virgula decimal apenas se nao houver ponto decimal padrao
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"Valor decimal invalido: {raw_val!r}") from exc
    else:
        raise TypeError(f"Tipo nao suportado para valor monetario: {type(raw_val).__name__}")

    return dec.quantize(QUANT_CENTS, rounding=ROUND_HALF_UP)


def template_coluna_origem(coluna_origem: str, exercicio: int) -> str:
    """
    Substitui anos dinamicos no cabecalho da coluna por placeholders relativos ao exercicio:
      exercicio     -> {EX}
      exercicio - 1 -> {EX_ANT}
      exercicio - 2 -> {EX_ANT2}
      exercicio + 1 -> {EX_MAIS_1}
    Tambem normaliza '29/02/{EX}' em anos bissextos para '28/02/{EX}' apenas se necessario via mapa,
    mantendo o texto original intacto em coluna_origem.
    """
    col_norm = normalize_text(coluna_origem)

    def _repl(match: re.Match[str]) -> str:
        yr = int(match.group(1))
        diff = yr - exercicio
        if diff == 0:
            return "{EX}"
        if diff == -1:
            return "{EX_ANT}"
        if diff == -2:
            return "{EX_ANT2}"
        if diff == 1:
            return "{EX_MAIS_1}"
        return match.group(1)

    return _YEAR_TOKEN_RE.sub(_repl, col_norm)


def extract_cod_natureza(fonte: str, anexo_codigo: str, cod_conta_original: str) -> str | None:
    """Extrai codigo estruturado de natureza de despesa em DCA-I-D e DCA-I-F."""
    if fonte == "DCA" and anexo_codigo in {"DCA-I-D", "DCA-I-F"}:
        if cod_conta_original.startswith("DO") and "." in cod_conta_original:
            return cod_conta_original[2:]
    return None
