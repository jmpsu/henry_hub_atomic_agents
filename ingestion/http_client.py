from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

import ingest

DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 0.25
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
USER_AGENT = "henry-hub-pit/1"


class HTTPClientError(RuntimeError):
    def __init__(self, message: str, url: str, attempts: int, status_code: int | None = None):
        super().__init__(f"{message} url={url} attempts={attempts} status={status_code}")
        self.url = url
        self.attempts = attempts
        self.status_code = status_code


@dataclass(frozen=True)
class FetchResult:
    status_code: int
    content: bytes
    content_type: str
    url: str
    final_url: str
    attempts: int
    retrieved_timestamp: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def as_tuple(self) -> tuple[int, bytes, str]:
        return self.status_code, self.content, self.content_type

    def json(self) -> Any:
        return json.loads(self.content)


def _response_url(response: httpx.Response, fallback: str) -> str:
    try:
        return str(response.url)
    except RuntimeError:
        return fallback


def _timestamp(now: datetime | str | None) -> str:
    if now is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(now, str):
        return ingest.utc_iso(now)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT,
          retries: int = DEFAULT_RETRIES, backoff: float = DEFAULT_BACKOFF, client: httpx.Client | None = None,
          sleep=time.sleep, now: datetime | str | None = None, raise_for_status: bool = False,
          expected_status: set[int] | None = None) -> FetchResult:
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    attempts = 0
    last_error: Exception | None = None
    last_result: FetchResult | None = None

    def request(active_client) -> httpx.Response:
        return active_client.get(url, params=params, headers=request_headers, timeout=timeout, follow_redirects=True)

    if client is not None:
        clients = [client]
        own_client = False
    else:
        clients = []
        own_client = True

    try:
        active = clients[0] if clients else httpx.Client(timeout=timeout)
        while attempts <= retries:
            attempts += 1
            try:
                response = request(active)
                last_result = FetchResult(
                    status_code=response.status_code,
                    content=response.content,
                    content_type=response.headers.get("content-type", ""),
                    url=url,
                    final_url=_response_url(response, url),
                    attempts=attempts,
                    retrieved_timestamp=_timestamp(now),
                )
                last_error = None
                if last_result.status_code not in RETRYABLE_STATUS:
                    break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                last_result = None
            if attempts <= retries and backoff > 0:
                sleep(backoff * (2 ** (attempts - 1)))
    finally:
        if own_client:
            active.close()

    if last_error is not None:
        raise HTTPClientError(f"HTTP transport failed: {last_error}", url, attempts)
    assert last_result is not None
    if expected_status is not None and last_result.status_code not in expected_status:
        if raise_for_status:
            raise HTTPClientError("unexpected HTTP status", url, attempts, last_result.status_code)
        return last_result
    if raise_for_status and not last_result.ok:
        raise HTTPClientError("HTTP error status", url, attempts, last_result.status_code)
    return last_result


def fetch_tuple(url: str, **kwargs) -> tuple[int, bytes, str]:
    return fetch(url, **kwargs).as_tuple()


def fetch_json(url: str, **kwargs) -> Any:
    result = fetch(url, expected_status={200}, raise_for_status=True, **kwargs)
    return result.json()


def archive(conn, result: FetchResult, source_id: str, source_url: str | None = None) -> str:
    return ingest.archive_payload(conn, result.content, source_id, source_url or result.final_url,
                                  result.status_code, result.retrieved_timestamp, result.content_type)
