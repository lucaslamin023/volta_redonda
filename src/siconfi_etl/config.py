from __future__ import annotations

from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuracoes centralizadas do pipeline lidas do ambiente / .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "siconfi_dw"
    postgres_user: str = "etl_admin"
    postgres_password: str = "siconfi_etl_local_2026"

    powerbi_ro_user: str = "powerbi_ro"
    powerbi_ro_password: str = "siconfi_bi_ro_2026"

    siconfi_base_url: str = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
    siconfi_fallback_url: str = "https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt"
    siconfi_rate_limit_seconds: float = 1.10
    siconfi_timeout_seconds: float = 60.0

    ente_principal: int = 3306305
    entes_escopo: str = Field(default="3306305,3300407,3304201,3300100,3303906,3302403")

    ano_inicial_extracao: int = 2015
    ano_final_extracao: int = 2026

    @field_validator("siconfi_rate_limit_seconds")
    @classmethod
    def enforce_stn_rate_limit(cls, value: float) -> float:
        if value < 1.0:
            raise ValueError("SICONFI exige no maximo 1 requisicao por segundo (>= 1.0s).")
        return value

    @property
    def lista_entes(self) -> list[int]:
        codes = [int(item.strip()) for item in self.entes_escopo.split(",") if item.strip()]
        if self.ente_principal not in codes:
            codes.insert(0, self.ente_principal)
        return codes

    @property
    def admin_conninfo(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password}"
        )

    @property
    def powerbi_ro_conninfo(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.powerbi_ro_user} "
            f"password={self.powerbi_ro_password}"
        )


def get_settings() -> Settings:
    return Settings()
