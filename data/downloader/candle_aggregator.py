"""
Aggregate 1-minute Parquet data into higher timeframes (15m, 30m, 1h).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

_log = logging.getLogger(__name__)

_CACHE_DIR = Path("data/cache")

_OHLC_AGGS: dict[str, dict] = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def _read_1m(symbol: str) -> pd.DataFrame | None:
    path = _CACHE_DIR / "1m" / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if not df.empty and not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def _write_aggregated(df: pd.DataFrame, symbol: str, tf: str) -> int:
    path = _CACHE_DIR / tf / f"{symbol}.parquet"
    df = df.sort_values("timestamp").reset_index(drop=True)
    df.to_parquet(path, index=False)
    return len(df)


def aggregate_1m_to(
    symbol: str,
    target_minutes: int,
    tf_dir: str,
) -> int:
    """
    Read 1-minute Parquet, resample to ``target_minutes``, write to ``tf_dir/``.

    Returns bar count written, or 0 on failure.
    """
    df = _read_1m(symbol)
    if df is None or df.empty:
        _log.debug("No 1m data for %s", symbol)
        return 0

    df = df.set_index("timestamp")
    # Anchor buckets to market open (09:15 IST) so the first bucket is 09:15→09:30
    market_open = pd.Timestamp("09:15", tz="Asia/Kolkata")
    resampled = df.resample(f"{target_minutes}min", origin=market_open, label="right", closed="right")
    agg = resampled.agg(_OHLC_AGGS).dropna(subset=["open"])
    agg = agg.reset_index()
    # Ensure all required columns exist
    for c in ["timestamp", "open", "high", "low", "close", "volume"]:
        if c not in agg.columns:
            agg[c] = np.nan if c != "volume" else 0

    n = _write_aggregated(agg, symbol, tf_dir)
    _log.info("Aggregated %s 1m→%sm → %d bars", symbol, target_minutes, n)
    return n


def build_all() -> dict[str, int]:
    """Loop all symbols with 1m cache, build 15m and 30m."""
    results: dict[str, int] = {}
    for path in sorted((_CACHE_DIR / "1m").glob("*.parquet")):
        symbol = path.stem
        results[f"{symbol}_15m"] = aggregate_1m_to(symbol, 15, "15m")
        results[f"{symbol}_30m_from1m"] = aggregate_1m_to(symbol, 30, "30m")
    return results
