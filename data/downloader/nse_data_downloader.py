"""
Incremental NSE data downloader — refresh local Parquet cache from Upstox REST.

Usage
-----
    python -m data.downloader.nse_data_downloader --refresh-1m
    python -m data.downloader.nse_data_downloader --refresh-30m
    python -m data.downloader.nse_data_downloader --refresh-1d
    python -m data.downloader.nse_data_downloader --resolve-keys
    python -m data.downloader.nse_data_downloader --refresh-all
    python -m data.downloader.nse_data_downloader --aggregate
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from data.downloader.watched_symbols import SYMBOLS, resolve_symbols, key_for

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
)
_log = logging.getLogger(__name__)

_CACHE_DIR = Path("data/cache")
_UPSTOX_MAX_DAYS = {
    "1minute": 30,
    "30minute": 60,
    "day": 730,
}

_INTERVAL_TO_UPSTOX = {
    "1m": "1minute",
    "5m": "1minute",
    "15m": "30minute",
    "30m": "30minute",
    "1h": "30minute",
    "1d": "day",
}


def _load_cached(symbol: str, tf_dir: str) -> pd.DataFrame:
    """Load existing Parquet cache, or empty DataFrame."""
    path = _CACHE_DIR / tf_dir / f"{symbol}.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        if not df.empty:
            return df
    return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


def _validate_data(df: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    """Basic sanity checks.  Returns cleaned DataFrame or None if corrupt."""
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    for c in required:
        if c not in df.columns:
            _log.warning("%s: missing column %s in download — discarding data", symbol, c)
            return None

    clean = df[required].copy()
    # Coerce to numeric, drop rows with NaN/inf in OHLC
    for c in ["open", "high", "low", "close"]:
        clean[c] = pd.to_numeric(clean[c], errors="coerce")
    clean = clean.dropna(subset=["open", "high", "low", "close"])
    for c in ["open", "high", "low", "close"]:
        clean = clean[~np.isinf(clean[c])]
    clean["volume"] = pd.to_numeric(clean["volume"], errors="coerce").fillna(0).astype(int)

    # Price sanity
    clean = clean[clean["open"] > 0]
    clean = clean[clean["high"] >= clean["low"]]
    clean = clean[clean["high"] > 0]

    # Duplicate / out-of-order timestamps
    clean = clean.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

    if clean.empty:
        _log.warning("%s: all rows invalid after validation", symbol)
        return None

    dropped = len(df) - len(clean)
    if dropped:
        _log.debug("%s: dropped %d invalid rows", symbol, dropped)
    return clean


def _write_cache(df: pd.DataFrame, symbol: str, tf_dir: str) -> int:
    path = _CACHE_DIR / tf_dir / f"{symbol}.parquet"
    valid = _validate_data(df, symbol)
    if valid is None or valid.empty:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    valid.to_parquet(path, index=False)
    _log.info("  → %d bars saved to %s", len(valid), path)
    return len(valid)


def _fetch_incremental(
    symbol: str,
    timeframe: str,
    lookback_days: int,
) -> pd.DataFrame | None:
    """Fetch from Upstox REST.  No local cache involvement — pure API."""
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider

    token = UPSTOX.get("access_token", "")
    if not token:
        _log.warning("No Upstox token")
        return None

    inst_key = key_for(symbol)
    if not inst_key:
        _log.warning("No instrument key for %s", symbol)
        return None

    provider = UpstoxMarketDataProvider(access_token=token)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    try:
        df = provider.load_historical_data(
            symbol=inst_key,
            timeframe=timeframe,
            start_date=start,
            end_date=end,
        )
        return df
    except Exception as e:
        _log.warning("Fetch failed for %s: %s", symbol, e)
        return None


def refresh_timeframe(
    timeframe: str,
    upstox_interval: str,
    tf_dir: str,
    max_days: int,
    symbols: list[str] | None = None,
) -> dict[str, int]:
    """
    Incremental refresh: read existing Parquet, fetch only newer bars, merge.
    """
    targets = symbols or SYMBOLS
    stats: dict[str, int] = {}

    for sym in targets:
        cached = _load_cached(sym, tf_dir)

        # Determine start date for incremental fetch
        if not cached.empty:
            last_ts = cached["timestamp"].max()
            # Fetch from 1 day before last to ensure no gap
            start = last_ts - timedelta(days=1)
            effective_days = min(max_days, (datetime.now(timezone.utc) - pd.Timestamp(start).to_pydatetime().replace(tzinfo=timezone.utc)).days + 1)
            if effective_days <= 0:
                stats[sym] = len(cached)
                continue
        else:
            effective_days = max_days

        new_df = _fetch_incremental(sym, timeframe, effective_days)
        if new_df is None or new_df.empty:
            stats[sym] = len(cached)
            continue

        # Merge
        if not cached.empty:
            merged = pd.concat([cached, new_df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        else:
            merged = new_df.sort_values("timestamp").reset_index(drop=True)

        written = _write_cache(merged, sym, tf_dir)
        stats[sym] = written
        _log.info("  %s: cached %d, new %d, total %d", sym, len(cached), len(new_df), written)

    return stats


def refresh_1m(symbols: list[str] | None = None) -> dict[str, int]:
    return refresh_timeframe("1m", "1minute", "1m", 30, symbols)


def refresh_1d(symbols: list[str] | None = None) -> dict[str, int]:
    return refresh_timeframe("1d", "day", "1d", 730, symbols)


def refresh_all(symbols: list[str] | None = None) -> None:
    _log.info("=== Refreshing 1-minute data ===")
    refresh_1m(symbols)
    _log.info("=== Refreshing daily data ===")
    refresh_1d(symbols)
    _log.info("=== Building 15m/30m from 1m cache ===")
    from data.downloader.candle_aggregator import build_all
    build_all()


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="NSE data cache manager")
    parser.add_argument("--refresh-1m", action="store_true", help="Refresh 1m cache")
    parser.add_argument("--refresh-30m", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--refresh-1d", action="store_true", help="Refresh 1d cache")
    parser.add_argument("--refresh-all", action="store_true", help="Refresh 1m + 1d + aggregate")
    parser.add_argument("--resolve-keys", action="store_true", help="Resolve & cache instrument keys")
    parser.add_argument("--aggregate", action="store_true", help="Build 15m/30m from 1m cache")
    parser.add_argument("--capture-today", action="store_true", help="Capture today's WS daily candle to today/ cache")
    parser.add_argument("--merge-today", action="store_true", help="Merge today/ candles into 1d cache")
    parser.add_argument("--symbols", nargs="*", help="Restrict to specific symbols")
    args = parser.parse_args()

    syms = args.symbols if args.symbols else None

    # Always ensure keys are available
    resolve_symbols(force=args.resolve_keys or args.refresh_all)

    if args.resolve_keys:
        return

    if args.refresh_1m:
        refresh_1m(syms)
    if args.refresh_30m:
        _log.warning("--refresh-30m is deprecated; use --aggregate instead")
    if args.refresh_1d:
        refresh_1d(syms)
    if args.refresh_all:
        refresh_all(syms)

    if args.aggregate:
        from data.downloader.candle_aggregator import build_all
        build_all()

    if args.capture_today:
        from data.downloader.today_cache import capture_today
        capture_today()

    if args.merge_today:
        from data.downloader.today_cache import merge_today_to_1d
        merge_today_to_1d()

    if not any(vars(args).values()):
        parser.print_help()


if __name__ == "__main__":
    main()
