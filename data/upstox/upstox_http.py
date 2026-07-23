"""
Rate-limited HTTP helper for Upstox REST calls.

Upstox enforces strict per-endpoint rate limits (e.g. ~20 req/min on the
historical-candle endpoint). This helper wraps ``requests`` and transparently
retries on HTTP 429 (honouring the ``Retry-After`` header) and on transport
errors with exponential backoff, so a transient rate-limit never silently
kills a data fetch / order placement.
"""

from __future__ import annotations

import time

import requests

_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds


def upstox_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    json: dict | None = None,
    params: dict | None = None,
    timeout: int = 15,
    max_retries: int = _MAX_RETRIES,
) -> requests.Response:
    """Perform an Upstox REST call with retry / backoff on 429 and transport errors.

    Raises the last ``requests.RequestException`` after exhausting retries so
    callers' existing ``except Exception`` fallbacks behave as before. Returns
    the :class:`requests.Response` on a non-429, non-error path (callers still
    inspect ``status_code``).
    """
    last_exc: Exception | None = None
    resp: requests.Response | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(
                method, url, headers=headers, json=json, params=params, timeout=timeout
            )
        except requests.RequestException as exc:
            last_exc = exc
            wait = _BASE_BACKOFF * (2 ** attempt)
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else _BASE_BACKOFF * (2 ** attempt)
            except (TypeError, ValueError):
                wait = _BASE_BACKOFF * (2 ** attempt)
            time.sleep(wait)
            last_exc = RuntimeError(f"Upstox 429 after attempt {attempt + 1}")
            continue

        return resp

    if resp is not None:
        return resp
    raise last_exc or RuntimeError("upstox_request failed")


def upstox_get(url: str, **kw) -> requests.Response:
    return upstox_request("GET", url, **kw)


def upstox_post(url: str, **kw) -> requests.Response:
    return upstox_request("POST", url, **kw)
