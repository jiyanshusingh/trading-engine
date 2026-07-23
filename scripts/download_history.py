"""
Bulk historical data downloader (yfinance, tokenless) — Phase 0.4.

Extends the local Parquet cache to the maximum history yfinance allows per
interval, for every symbol in the watched list. This gives the backtester a
long enough window that 1d/longer-warmup timeframes stop producing 0 trades and
walk-forward / out-of-sample validation becomes trustworthy.

yfinance interval limits (approx):
    1h  -> 730 days
    15m -> 60 days
    1d  -> years (we request 5y)

Existing cache rows are merged (dedup on timestamp), never lost.

Usage
-----
    .venv/bin/python scripts/download_history.py                 # all TFs, all symbols
    .venv/bin/python scripts/download_history.py --tf 1h 1d      # specific TFs
    .venv/bin/python scripts/download_history.py --symbols RELIANCE TCS
"""

from __future__ import annotations

import argparse
import logging
import sys as _sys
import time
from pathlib import Path

_sys.path.insert(0, ".")

import pandas as pd

from data.downloader.watched_symbols import SYMBOLS, YF_SUFFIX

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_log = logging.getLogger("download_history")

_CACHE_DIR = Path("data/cache")

# interval -> (yfinance period, cache sub-dir, upstox native interval)
_TF_CONFIG = {
    "1m": ("7d", "1m", "1m"),      # yfinance caps 1m @ 7d; Upstox native 1m (no resample)
    "5m": ("60d", "5m", "1m"),     # yfinance caps 5m @ 60d; Upstox uses 1m -> resample
    "15m": ("60d", "15m", "1m"),   # yfinance caps 15m @ 60d; Upstox uses 1m -> resample
    "1h": ("730d", "1h", "1h"),    # Upstox native 1h
    "1d": ("5y", "1d", "1d"),
}

_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

# Upstox historical fetch window (days) — Upstox allows ~729d of 1m/1h.
_UPSTOX_DAYS = {"1m": 365, "5m": 729, "15m": 729, "1h": 729, "1d": 730}


def _fetch_yf(symbol: str, period: str, interval: str) -> pd.DataFrame | None:
    import yfinance as yf

    try:
        raw = yf.Ticker(f"{symbol}{YF_SUFFIX}").history(period=period, interval=interval)
    except Exception as e:
        _log.warning("  %s %s: fetch error %s", symbol, interval, e)
        return None
    if raw is None or raw.empty:
        return None

    df = raw.reset_index()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns={"datetime": "timestamp", "date": "timestamp"})
    for drop_col in ("dividends", "stock_splits", "capital_gains"):
        if drop_col in df.columns:
            df.drop(columns=[drop_col], inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    missing = [c for c in _COLS if c not in df.columns]
    if missing:
        _log.warning("  %s %s: missing cols %s", symbol, interval, missing)
        return None
    return df[_COLS]


def _resample_1m_to(df: pd.DataFrame, minutes: int) -> pd.DataFrame | None:
    """Resample 1m bars to ``minutes``. Mirrors scripts.backtest._resample_1m_to."""
    from scripts.backtest import _resample_1m_to as _r
    try:
        out = _r(df, minutes)
        if out is None or out.empty:
            return None
        return out[_COLS]
    except Exception as e:
        _log.warning("  resample failed: %s", e)
        return None


def _upstox_key(symbol: str) -> str | None:
    """Resolve a watched symbol to an Upstox instrument key."""
    from scripts.backtest import resolve_upstox_key
    key = resolve_upstox_key(f"{symbol}.NS", "upstox")
    return key if key and key != f"{symbol}.NS" else None


def _fetch_upstox(symbol: str, tf: str, days: int) -> pd.DataFrame | None:
    """Fetch ``days`` of history from Upstox and resample to ``tf``.

    Upstox has no native 15m interval, so 15m is built by resampling 1m (the
    same path used by the live paper trader). Requires a data-scoped Upstox
    token in .env (order placement needs a separate trading scope).

    Upstox caps intraday (1m) history to ~30 days per request, so the window is
    fetched in <=28-day chunks and concatenated before resampling.
    """
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider
    from datetime import datetime, timedelta

    token = UPSTOX.get("access_token", "")
    if not token:
        _log.warning("  no Upstox token in .env — skipping %s", symbol)
        return None
    key = _upstox_key(symbol)
    if not key:
        _log.warning("  %s: no Upstox instrument key — skipping", symbol)
        return None
    native = _TF_CONFIG[tf][2]
    try:
        provider = UpstoxMarketDataProvider(token)
        end = datetime.now()
        start = end - timedelta(days=days)
        # Chunk the range (Upstox 1m history is capped at ~30d/request).
        chunk_days = 28 if native == "1m" else days
        pieces = []
        cur_end = end
        while cur_end > start:
            cur_start = max(start, cur_end - timedelta(days=chunk_days))
            try:
                df = provider.load_historical_data(
                    key, native, start_date=cur_start, end_date=cur_end)
                if df is not None and not df.empty:
                    pieces.append(df)
            except Exception as e:
                _log.warning("  %s: chunk %s..%s skipped (%s)",
                             symbol, cur_start.date(), cur_end.date(), e)
            cur_end = cur_start
            time.sleep(0.5)  # polite pause between paginated requests
        if not pieces:
            _log.warning("  %s: Upstox returned no bars — skipping", symbol)
            return None
        df = pd.concat(pieces, ignore_index=True)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        if df["timestamp"].dt.tz is not None:
            df["timestamp"] = df["timestamp"].dt.tz_localize(None)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        if native == "1m" and tf != "1m":
            minutes = int(tf[:-1])
            df = _resample_1m_to(df, minutes)
            if df is None:
                return None
        return df
    except Exception as e:
        _log.warning("  %s: Upstox fetch error %s", symbol, e)
        return None


def _merge_write(new_df: pd.DataFrame, symbol: str, tf_dir: str) -> int:
    path = _CACHE_DIR / tf_dir / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            old = pd.read_parquet(path)
            old["timestamp"] = pd.to_datetime(old["timestamp"]).dt.tz_localize(None)
            new_df = pd.concat([old[_COLS], new_df], ignore_index=True)
        except Exception as e:
            _log.debug("  %s: could not merge old cache (%s) — overwriting", symbol, e)
    merged = (
        new_df.dropna(subset=["open", "high", "low", "close"])
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    merged["volume"] = pd.to_numeric(merged["volume"], errors="coerce").fillna(0).astype(int)
    merged.to_parquet(path, index=False)
    return len(merged)


def run(timeframes: list[str], symbols: list[str], use_upstox: bool = False) -> None:
    for tf in timeframes:
        if tf not in _TF_CONFIG:
            _log.warning("Unsupported timeframe %s (skip)", tf)
            continue
        period, tf_dir, _ = _TF_CONFIG[tf]
        _log.info("=== %s (%s) ===", tf, "upstox" if use_upstox else f"yfinance period={period}")
        for sym in symbols:
            df = (_fetch_upstox(sym, tf, _UPSTOX_DAYS.get(tf, 365))
                  if use_upstox else _fetch_yf(sym, period, tf))
            if df is None or df.empty:
                _log.warning("  %s: no data", sym)
                continue
            total = _merge_write(df, sym, tf_dir)
            _log.info("  %s: +%d fetched -> %d total bars", sym, len(df), total)


def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk historical data downloader")
    ap.add_argument("--tf", nargs="*", default=list(_TF_CONFIG.keys()),
                    help="Timeframes to download (default: 15m 1h 1d)")
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="Restrict to specific symbols (default: full watchlist)")
    ap.add_argument("--upstox", action="store_true",
                    help="Fetch from Upstox instead of yfinance (needs data-scoped "
                         "token; unlocks 729d of 15m via 1m resampling)")
    args = ap.parse_args()
    syms = args.symbols if args.symbols else SYMBOLS
    run(args.tf, syms, use_upstox=args.upstox)


if __name__ == "__main__":
    main()
