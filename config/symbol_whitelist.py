"""
Phase 1 — Per-symbol / per-timeframe expectancy whitelist.

Loads and queries the strict whitelist produced by scripts/build_whitelist.py.
A symbol only trades on a given (timeframe, mode) when it demonstrated a real
edge in backtest: PF >= MIN_PF over >= MIN_TRADES trades.

Storage: data/symbol_whitelist.json
    { "15m_intraday": ["ONGC", ...], "1h_swing": [...] }

If a bucket is missing/empty, is_whitelisted() returns True (fail-open) so the
filter never silently blocks an unconfigured mode — callers opt in explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

MIN_PF = 1.5          # strict: require a real edge, not break-even
MIN_TRADES = 5        # strict: enough sample to trust the PF

_PATH = Path("data/symbol_whitelist.json")


def bucket_key(timeframe: str, intraday: bool) -> str:
    return f"{timeframe}_{'intraday' if intraday else 'swing'}"


def load() -> dict[str, list[str]]:
    if _PATH.exists():
        try:
            return json.loads(_PATH.read_text())
        except Exception:
            return {}
    return {}


def whitelist_for(timeframe: str, intraday: bool) -> list[str]:
    return load().get(bucket_key(timeframe, intraday), [])


def is_whitelisted(symbol: str, timeframe: str, intraday: bool) -> bool:
    wl = whitelist_for(timeframe, intraday)
    if not wl:
        return True  # fail-open for unconfigured buckets
    return symbol in wl
