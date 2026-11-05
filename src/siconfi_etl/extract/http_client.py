from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal
from typing import Any

import httpx
import psycopg
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from siconfi_etl.config import Settings, get_settings


class RetryableHttpError(RuntimeError):
    """Erro HTTP transiente (429 ou 5xx) elegivel a retry com backoff."""


class _DecimalEncoder(json.JSONEncoder):
    """Serializa Decimal como string exata, impedindo qualquer conversao para float."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def parse_json_decimal(raw_text: str) -> Any:
    """Parseia texto JSON usando exclusivamente decimal.Decimal para numeros fracionarios."""
    return json.loads(raw_text, parse_float=Decimal)


def dumps_json_decimal(obj: Any) -> str:
    """Serializa estrutura Python preservando Decimal sem perda de precisao."""
    return json.dumps(obj, cls=_DecimalEncoder, ensure_ascii=False, sort_keys=True)


def sha256_text(text: str) -> str:
    """Retorna hash SHA-256 hexadecimal UTF-8 do texto informado."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def log_http_request(
    conn: psycopg.Connection,
    endpoint: str,
    params: dict[str, Any] | None,
    url_chamada: str,
    status_http: int,
    qtd_itens: int,
    payload_texto: str,
) -> str:
    """Registra auditoria imutavel da requisicao HTTP em bronze.ingestao_requisicao."""
    digest = sha256_text(payload_texto)
    params_json = dumps_json_decimal(params or {})
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bronze.ingestao_requisicao (
                endpoint, parametros, url_chamada, status_http,
                qtd_itens, hash_sha256, payload_texto
            )
            VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s);
            """,
            (endpoint, params_json, url_chamada, status_http, qtd_itens, digest, payload_texto),
        )
    conn.commit()
    return digest


class SiconfiHttpClient:
    """Cliente HTTP para a API SICONFI/STN com rate limit estrito (<= 1 req/s) e paginacao ORDS."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.min_interval = max(1.05, float(self.settings.siconfi_rate_limit_seconds))
        self._last_request_ts: float = 0.0
        self._active_base_url: str | None = None
        self._client = httpx.Client(
            timeout=self.settings.siconfi_timeout_seconds,
            follow_redirects=True,
            headers={
                "Accept": "application/json",
                "User-Agent": "siconfi-etl-municipal-dw/0.1.0",
            },
        )
        self.request_count: int = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SiconfiHttpClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if self._last_request_ts > 0.0 and elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    def resolve_base_url(self) -> str:
        """Executa smoke test leve para fixar a URL base ativa do SICONFI."""
        if self._active_base_url:
            return self._active_base_url

        candidates = [
            self.settings.siconfi_base_url.rstrip("/"),
            self.settings.siconfi_fallback_url.rstrip("/"),
        ]
        probe_params = {"id_ente": self.settings.ente_principal, "an_referencia": 2024}

        last_err: Exception | None = None
        for base in candidates:
            self._throttle()
            try:
                resp = self._client.get(f"{base}/extrato_entregas", params=probe_params, timeout=25.0)
                self.request_count += 1
                if resp.status_code == 200:
                    parsed = parse_json_decimal(resp.text)
                    if isinstance(parsed, dict) and "items" in parsed:
                        self._active_base_url = base
                        return base
            except Exception as exc:
                last_err = exc

        raise RuntimeError(f"Nao foi possivel validar conectividade com a API SICONFI: {last_err}")

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException, RetryableHttpError)),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get_single_page(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        self._throttle()
        resp = self._client.get(
            url,
            params=params,
            timeout=timeout or self.settings.siconfi_timeout_seconds,
        )
        self.request_count += 1

        if resp.status_code == 429 or resp.status_code >= 500:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(min(int(retry_after), 30))
            raise RetryableHttpError(f"HTTP {resp.status_code} em {resp.url}")

        resp.raise_for_status()
        return resp

    def fetch_all_pages(
        self,
        conn: psycopg.Connection,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        max_attempts_override: int | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Busca todas as paginas ORDS (limit=5000, hasMore) sem perder precisao Decimal."""
        base_url = self.resolve_base_url()
        clean_ep = endpoint.lstrip("/")
        url = f"{base_url}/{clean_ep}"

        all_items: list[dict[str, Any]] = []
        offset = 0
        limit = 5000

        while True:
            page_params = dict(params or {})
            if offset > 0:
                page_params["offset"] = offset
                page_params["limit"] = limit

            if max_attempts_override == 1:
                self._throttle()
                resp = self._client.get(
                    url,
                    params=page_params,
                    timeout=timeout or self.settings.siconfi_timeout_seconds,
                )
                self.request_count += 1
                resp.raise_for_status()
            else:
                resp = self._get_single_page(url, params=page_params, timeout=timeout)

            payload_data = parse_json_decimal(resp.text)
            page_items = payload_data.get("items", []) if isinstance(payload_data, dict) else []

            log_http_request(
                conn=conn,
                endpoint=f"siconfi/{clean_ep}",
                params=page_params,
                url_chamada=str(resp.url),
                status_http=resp.status_code,
                qtd_itens=len(page_items),
                payload_texto=resp.text,
            )

            all_items.extend(page_items)

            has_more = bool(payload_data.get("hasMore")) if isinstance(payload_data, dict) else False
            page_limit = int(payload_data.get("limit", limit)) if isinstance(payload_data, dict) else limit
            if not has_more or not page_items:
                break
            offset += page_limit

        canonical_items_text = dumps_json_decimal(all_items)
        return all_items, sha256_text(canonical_items_text)
