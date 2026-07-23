"""
Capture today's daily candle from WebSocket and persist to cache.

Usage
-----
    python -m data.downloader.nse_data_downloader --capture-today
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data.downloader.watched_symbols import SYMBOLS, load_key_cache

_log = logging.getLogger(__name__)

_TODAY_DIR = Path("data/cache/today")
_1D_DIR = Path("data/cache/1d")


def _instrument_keys() -> list[str]:
    """Return cached instrument keys for all watched symbols."""
    cache = load_key_cache()
    return [cache[s] for s in SYMBOLS if s in cache]


def capture_today() -> dict[str, int]:
    """Fetch today's ``"1d"`` WS candle for all 30 symbols and save to ``today/``.

    Returns ``{symbol: bar_count}`` (bar_count is 0 or 1 per symbol).
    """
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_live_feed import UpstoxLiveFeed

    token = UPSTOX.get("access_token", "")
    if not token:
        _log.warning("No Upstox token — cannot capture today's data")
        return {}

    keys = _instrument_keys()
    if not keys:
        _log.warning("No cached instrument keys")
        return {}

    feed = UpstoxLiveFeed(access_token=token)
    batch = feed.get_live_batch(keys, mode="full", timeout=20)

    _TODAY_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}

    for sym in SYMBOLS:
        cache = load_key_cache()
        inst_key = cache.get(sym)
        if not inst_key or inst_key not in batch:
            continue

        ohlc = batch[inst_key]
        intervals = ohlc.get("_intervals") or {}
        daily = intervals.get("1d") or ohlc

        ts_ms = daily.get("ts", 0)
        try:
            ts = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC")
        except (ValueError, OSError):
            continue

        df = pd.DataFrame([{
            "timestamp": ts,
            "open": float(daily.get("open", 0)),
            "high": float(daily.get("high", 0)),
            "low": float(daily.get("low", 0)),
            "close": float(daily.get("close", 0)),
            "volume": int(daily.get("vol", 0)),
        }])

        if df["volume"].iloc[0] == 0:
            continue

        path = _TODAY_DIR / f"{sym}.parquet"
        df.to_parquet(path, index=False)
        results[sym] = 1

    _log.info("Captured today candles for %d/%d symbols", len(results), len(SYMBOLS))
    return results


def merge_today_to_1d() -> dict[str, int]:
    """Append captured today candles into the permanent 1d cache.

    Reads ``today/`` files, merges into ``1d/``, then deletes ``today/`` file.

    Returns ``{symbol: total_bars_in_1d}``.
    """
    if not _TODAY_DIR.exists():
        return {}

    stats: dict[str, int] = {}
    for path in sorted(_TODAY_DIR.glob("*.parquet")):
        symbol = path.stem

        today_df = pd.read_parquet(path)
        if today_df.empty:
            path.unlink(missing_ok=True)
            continue

        today_df["timestamp"] = pd.to_datetime(today_df["timestamp"])
        # WS timestamps are UTC — convert to IST for date comparison
        if today_df["timestamp"].dt.tz is None:
            today_ist = today_df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata")
        else:
            today_ist = today_df["timestamp"].dt.tz_convert("Asia/Kolkata")
        today_date = today_ist.iloc[0].date()
        today_df["timestamp"] = today_ist.dt.tz_localize(None)

        # Read existing 1d cache
        one_d_path = _1D_DIR / f"{symbol}.parquet"
        if one_d_path.exists():
            existing = pd.read_parquet(one_d_path)
            existing["timestamp"] = pd.to_datetime(existing["timestamp"])

            # Check if we already have a bar for today
            mask = existing["timestamp"].dt.date == today_date
            if mask.any():
                existing = existing[~mask]

            merged = pd.concat([existing, today_df], ignore_index=True)
            # Keep the LATEST snapshot for a given timestamp — WebSocket
            # candles update throughout the day, so an earlier (stale) bar
            # must not overwrite a later, more complete one.
            merged = merged.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp").reset_index(drop=True)
        else:
            merged = today_df

        merged.to_parquet(one_d_path, index=False)
        path.unlink(missing_ok=True)
        stats[symbol] = len(merged)

    _log.info("Merged today candles: %d symbols", len(stats))
    return stats
