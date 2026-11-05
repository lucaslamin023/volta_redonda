from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from siconfi_etl.config import PROJECT_ROOT
from siconfi_etl.silver.normalizer import normalize_text, template_coluna_origem

SEEDS_DIR = PROJECT_ROOT / "seeds"


@dataclass(frozen=True)
class ColunaMapEntry:
    fonte: str
    anexo_codigo: str
    coluna_origem: str
    coluna_padrao: str
    tipo_medida: str
    aditividade: str
    ordem_exibicao: int


@dataclass(frozen=True)
class SecaoMapEntry:
    fonte: str
    anexo_codigo: str
    rotulo_origem: str
    secao_codigo: str
    secao_nome: str
    ordem_exibicao: int


@dataclass(frozen=True)
class FonteRecursoSeedEntry:
    cod_fonte: str
    nome_fonte_origem: str
    exercicio_ini: int
    exercicio_fim: int
    cod_fonte_padrao: str
    nome_fonte: str
    grupo: str | None
    vinculada: int
    eh_total_anexo05: int


@dataclass(frozen=True)
class ContaEquivalenciaEntry:
    fonte: str
    anexo_codigo: str
    cod_conta_origem: str
    exercicio_ini: int
    exercicio_fim: int
    cod_conta_padrao: str


@dataclass(frozen=True)
class ContaHierarquiaEntry:
    fonte: str
    anexo_codigo: str
    cod_conta_padrao: str
    descricao: str
    cod_conta_pai: str | None
    nivel: int
    eh_folha: int
    eh_total: int
    grupo_analitico: str | None
    sinal_semantico: int


@dataclass(frozen=True)
class LimiteLrfSeedEntry:
    codigo_limite: str
    descricao: str
    percentual_limite: Decimal
    pct_alerta: Decimal | None
    pct_prudencial: Decimal | None
    tipo_limite: str
    base_calculo: str
    vigencia_ini: str
    vigencia_fim: str | None
    base_legal: str


@dataclass(frozen=True)
class IndicadorSeedEntry:
    codigo_indicador: str
    nome: str
    descricao: str
    formula_texto: str
    unidade: str
    sentido_bom: str
    valor_referencia: Decimal | None
    fonte_primaria: str
    grupo: str
    camada_calculo: str
    ordem_exibicao: int


@dataclass(frozen=True)
class ProfundidadeEntry:
    fonte: str
    anexo_codigo: str
    exercicio_inicial: int
    motivo: str


class ColunaResolver:
    """Resolve coluna_origem -> coluna_padrao usando match literal ou template {EX}/{EX_ANT}."""

    def __init__(self, entries: list[ColunaMapEntry]) -> None:
        self.entries = entries
        self._by_key: dict[tuple[str, str, str], ColunaMapEntry] = {
            (e.fonte, e.anexo_codigo, normalize_text(e.coluna_origem)): e for e in entries
        }

    def resolve(self, fonte: str, anexo_codigo: str, coluna_origem: str, exercicio: int) -> str | None:
        col_norm = normalize_text(coluna_origem)
        direct = self._by_key.get((fonte, anexo_codigo, col_norm))
        if direct is not None:
            return direct.coluna_padrao

        templated = template_coluna_origem(col_norm, exercicio)
        via_tpl = self._by_key.get((fonte, anexo_codigo, templated))
        if via_tpl is not None:
            return via_tpl.coluna_padrao
        return None


class FonteRecursoResolver:
    """Resolve a descricao da fonte no RGF-05 para cod_fonte e flags de totalizacao."""

    def __init__(self, entries: list[FonteRecursoSeedEntry]) -> None:
        self.entries = entries
        self._by_name: dict[str, list[FonteRecursoSeedEntry]] = {}
        for entry in entries:
            key = normalize_text(entry.nome_fonte_origem)
            self._by_name.setdefault(key, []).append(entry)

    def resolve(self, nome_fonte_origem: str, exercicio: int) -> FonteRecursoSeedEntry | None:
        key = normalize_text(nome_fonte_origem)
        candidates = self._by_name.get(key)
        if not candidates:
            return None
        for cand in candidates:
            if cand.exercicio_ini <= exercicio <= cand.exercicio_fim:
                return cand
        return candidates[-1]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo seed obrigatorio nao encontrado: {path}")
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_coluna_map(seeds_dir: Path = SEEDS_DIR) -> list[ColunaMapEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_coluna_map.csv")
    return [
        ColunaMapEntry(
            fonte=normalize_text(r["fonte"]),
            anexo_codigo=normalize_text(r["anexo_codigo"]),
            coluna_origem=normalize_text(r["coluna_origem"]),
            coluna_padrao=normalize_text(r["coluna_padrao"]),
            tipo_medida=normalize_text(r["tipo_medida"]),
            aditividade=normalize_text(r["aditividade"]),
            ordem_exibicao=int(r["ordem_exibicao"]),
        )
        for r in rows
    ]


def load_secao_map(seeds_dir: Path = SEEDS_DIR) -> list[SecaoMapEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_secao_map.csv")
    return [
        SecaoMapEntry(
            fonte=normalize_text(r["fonte"]),
            anexo_codigo=normalize_text(r["anexo_codigo"]),
            rotulo_origem=normalize_text(r["rotulo_origem"]),
            secao_codigo=normalize_text(r["secao_codigo"]),
            secao_nome=normalize_text(r["secao_nome"]),
            ordem_exibicao=int(r["ordem_exibicao"]),
        )
        for r in rows
    ]


def load_fonte_recurso_seed(seeds_dir: Path = SEEDS_DIR) -> list[FonteRecursoSeedEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_fonte_recurso.csv")
    return [
        FonteRecursoSeedEntry(
            cod_fonte=normalize_text(r["cod_fonte"]),
            nome_fonte_origem=normalize_text(r["nome_fonte_origem"]),
            exercicio_ini=int(r["exercicio_ini"]),
            exercicio_fim=int(r["exercicio_fim"]),
            cod_fonte_padrao=normalize_text(r["cod_fonte_padrao"]),
            nome_fonte=normalize_text(r["nome_fonte"]),
            grupo=normalize_text(r["grupo"]) or None,
            vinculada=int(r["vinculada"]),
            eh_total_anexo05=int(r["eh_total_anexo05"]),
        )
        for r in rows
    ]


def load_conta_equivalencia(seeds_dir: Path = SEEDS_DIR) -> list[ContaEquivalenciaEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_conta_equivalencia.csv")
    return [
        ContaEquivalenciaEntry(
            fonte=normalize_text(r["fonte"]),
            anexo_codigo=normalize_text(r["anexo_codigo"]),
            cod_conta_origem=normalize_text(r["cod_conta_origem"]),
            exercicio_ini=int(r["exercicio_ini"]),
            exercicio_fim=int(r["exercicio_fim"]),
            cod_conta_padrao=normalize_text(r["cod_conta_padrao"]),
        )
        for r in rows
    ]


def load_conta_hierarquia(seeds_dir: Path = SEEDS_DIR) -> list[ContaHierarquiaEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_conta_hierarquia.csv")
    return [
        ContaHierarquiaEntry(
            fonte=normalize_text(r["fonte"]),
            anexo_codigo=normalize_text(r["anexo_codigo"]),
            cod_conta_padrao=normalize_text(r["cod_conta_padrao"]),
            descricao=normalize_text(r["descricao"]),
            cod_conta_pai=normalize_text(r["cod_conta_pai"]) or None,
            nivel=int(r["nivel"]),
            eh_folha=int(r["eh_folha"]),
            eh_total=int(r["eh_total"]),
            grupo_analitico=normalize_text(r["grupo_analitico"]) or None,
            sinal_semantico=int(r["sinal_semantico"]),
        )
        for r in rows
    ]


def load_limite_lrf_seed(seeds_dir: Path = SEEDS_DIR) -> list[LimiteLrfSeedEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_limite_lrf.csv")
    return [
        LimiteLrfSeedEntry(
            codigo_limite=normalize_text(r["codigo_limite"]),
            descricao=normalize_text(r["descricao"]),
            percentual_limite=Decimal(r["percentual_limite"].strip()),
            pct_alerta=Decimal(r["pct_alerta"].strip()) if r["pct_alerta"].strip() else None,
            pct_prudencial=Decimal(r["pct_prudencial"].strip()) if r["pct_prudencial"].strip() else None,
            tipo_limite=normalize_text(r["tipo_limite"]),
            base_calculo=normalize_text(r["base_calculo"]),
            vigencia_ini=normalize_text(r["vigencia_ini"]),
            vigencia_fim=normalize_text(r["vigencia_fim"]) or None,
            base_legal=normalize_text(r["base_legal"]),
        )
        for r in rows
    ]


def load_indicador_seed(seeds_dir: Path = SEEDS_DIR) -> list[IndicadorSeedEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_indicador.csv")
    return [
        IndicadorSeedEntry(
            codigo_indicador=normalize_text(r["codigo_indicador"]),
            nome=normalize_text(r["nome"]),
            descricao=normalize_text(r["descricao"]),
            formula_texto=normalize_text(r["formula_texto"]),
            unidade=normalize_text(r["unidade"]),
            sentido_bom=normalize_text(r["sentido_bom"]),
            valor_referencia=Decimal(r["valor_referencia"].strip()) if r["valor_referencia"].strip() else None,
            fonte_primaria=normalize_text(r["fonte_primaria"]),
            grupo=normalize_text(r["grupo"]),
            camada_calculo=normalize_text(r["camada_calculo"]),
            ordem_exibicao=int(r["ordem_exibicao"]),
        )
        for r in rows
    ]


def load_profundidade_seed(seeds_dir: Path = SEEDS_DIR) -> list[ProfundidadeEntry]:
    rows = _read_csv_rows(seeds_dir / "seed_profundidade.csv")
    return [
        ProfundidadeEntry(
            fonte=normalize_text(r["fonte"]),
            anexo_codigo=normalize_text(r["anexo_codigo"]),
            exercicio_inicial=int(r["exercicio_inicial"]),
            motivo=normalize_text(r["motivo"]),
        )
        for r in rows
    ]
