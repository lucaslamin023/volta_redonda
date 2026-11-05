from __future__ import annotations

from pathlib import Path

from siconfi_etl.silver.seed_loader import SEEDS_DIR
from siconfi_etl.silver.seeds_colunas import write_seed_coluna_map
from siconfi_etl.silver.seeds_contas import write_account_seeds
from siconfi_etl.silver.seeds_dominios import write_domain_seeds


def generate_all_seeds(
    seeds_dir: Path = SEEDS_DIR,
    overwrite_profundidade: bool = False,
) -> dict[str, int]:
    """Gera de forma deterministica os 8 arquivos CSV curados em seeds/."""
    counts: dict[str, int] = {}
    counts["seed_coluna_map.csv"] = write_seed_coluna_map(seeds_dir)
    counts.update(write_domain_seeds(seeds_dir, overwrite_profundidade=overwrite_profundidade))
    counts.update(write_account_seeds(seeds_dir))
    return counts
