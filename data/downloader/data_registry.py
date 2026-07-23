"""
Central read API — single ``get_bars()`` call for backtesting and live trading.

Lookup order:
  1.  Parquet cache (fastest — zero API calls)
  2.  Live WebSocket merge for today's candle (if ``live=True``)
  3.  Falls back to Upstox REST (cold cache — caller falls through to
      existing ``fetch_data()`` logic)
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from data.downloader.watched_symbols import key_for

_log = logging.getLogger(__name__)

_CACHE_DIR = Path("data/cache")


@contextlib.contextmanager
def override_cache_dir(path):
    """Temporarily point the registry's cache root at ``path``.

    Restores the previous root on exit (even on exception), so callers can
    redirect ``get_bars`` at a scratch directory without permanently mutating
    global state. Re-entrant-safe (uses a stack via the ``finally`` restore).
    """
    global _CACHE_DIR
    saved = _CACHE_DIR
    _CACHE_DIR = Path(path)
    try:
        yield
    finally:
        _CACHE_DIR = saved

_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "1d",
}


def _cache_path(symbol: str, timeframe: str) -> Path:
    tf_dir = _INTERVAL_MAP.get(timeframe, timeframe)
    return _CACHE_DIR / tf_dir / f"{symbol}.parquet"


def _try_yfinance_native(symbol: str, timeframe: str, lookback_days: int) -> pd.DataFrame | None:
    """Fetch native higher-timeframe intraday bars from yfinance.

    Falls back to resampling if yfinance fails (no API key needed).
    Caches result so subsequent calls are instant.
    """
    try:
        import yfinance as yf

        yf_interval = {"1h": "1h", "2h": "1h", "4h": "1d"}.get(timeframe, "1h")
        period = f"{min(lookback_days, 60)}d"
        ticker = yf.Ticker(f"{symbol}.NS")
        native = ticker.history(period=period, interval=yf_interval)
        if native is None or native.empty:
            return None

        native = native.reset_index()
        native.columns = [c.lower().replace(" ", "_") for c in native.columns]
        native = native.rename(columns={"datetime": "timestamp", "date": "timestamp"})
        for drop_col in ["dividends", "stock_splits"]:
            if drop_col in native.columns:
                native.drop(columns=[drop_col], inplace=True)
        native["timestamp"] = pd.to_datetime(native["timestamp"]).dt.tz_localize(None)

        # Cache for future use
        cache_dir = _CACHE_DIR / timeframe
        cache_dir.mkdir(parents=True, exist_ok=True)
        native.to_parquet(cache_dir / f"{symbol}.parquet", index=False)

        _log.info("Cached native %s bars for %s (%d rows)", timeframe, symbol, len(native))
        return native
    except Exception as e:
        _log.debug("yfinance native %s failed for %s: %s", timeframe, symbol, e)
        return None


def get_bars(
    symbol: str,
    timeframe: str,
    lookback_days: int,
    live: bool = True,
) -> pd.DataFrame | None:
    """
    Read historical bars from local Parquet cache.

    Parameters
    ----------
    symbol : str
        NSE trading symbol (e.g. ``"TATACONSUM"``) or Upstox instrument key.
    timeframe : str
        ``"1m"``, ``"15m"``, ``"30m"``, ``"1h"``, ``"1d"``.
    lookback_days : int
        How many days of data to return.
    live : bool
        If *True*, merge today's WebSocket candle for the last incomplete bar.

    Returns
    -------
    pd.DataFrame or None
        Columns: ``timestamp, open, high, low, close, volume``.
    """
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        if live and timeframe == "1d":
            return _read_today_only(symbol, lookback_days)
        # Try native yfinance for HTF intraday before resampling fallback
        if timeframe in ("1h", "2h", "4h"):
            native = _try_yfinance_native(symbol, timeframe, lookback_days)
            if native is not None:
                return native
        # Fallback: resample from source timeframe cache
        src_tf = {"1h": "30m", "2h": "30m"}.get(timeframe)
        if src_tf:
            src_path = _cache_path(symbol, src_tf)
            if src_path.exists():
                df = pd.read_parquet(src_path)
                if not df.empty:
                    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
                    df = _resample_bars(df, timeframe, lookback_days)
                    if df is not None:
                        return df
        return None

    df = pd.read_parquet(path)
    if df.empty:
        return None

    # Normalise to tz-naive for consistent output
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)

    # Resample if cached timeframe differs from requested timeframe
    cached_tf = _INTERVAL_MAP.get(timeframe, timeframe)
    if cached_tf != timeframe:
        df = _resample_bars(df, timeframe, lookback_days)
        if df is None:
            return None

    # Overlay today's WS candle on 1d data when live
    if live and timeframe == "1d":
        df = _overlay_today_candle(df, symbol)

    # Filter to lookback window (only for live — backtest manages its own window)
    if live and lookback_days > 0:
        cutoff = pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=lookback_days)
        cutoff = cutoff.tz_localize(None)
        df = df[df["timestamp"] >= cutoff]

    # Tail cap: keep enough bars to cover `lookback_days` calendar days. The
    # base *10 heuristic under-sizes fine-grained intraday timeframes (5m has
    # ~75 bars/day, 1m ~375), so those get a larger multiplier. 15m/1h/1d keep
    # the original *10 so previously-validated results are unchanged.
    _tail_mult = {"1m": 400, "5m": 80}.get(timeframe, 10)
    return df.tail(lookback_days * _tail_mult + 100).reset_index(drop=True) if not df.empty else None


def _today_path(symbol: str) -> Path:
    return Path("data/cache/today") / f"{symbol}.parquet"


def _read_today_only(symbol: str, lookback_days: int) -> pd.DataFrame | None:
    """Read only the today overlay (used when no 1d base cache exists yet)."""
    path = _today_path(symbol)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    # Convert WS UTC to IST
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    if lookback_days > 0:
        cutoff = pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=lookback_days)
        cutoff = cutoff.tz_localize(None)
        df = df[df["timestamp"] >= cutoff]
    return df.reset_index(drop=True) if not df.empty else None


def _resample_bars(df: pd.DataFrame, timeframe: str, lookback_days: int) -> pd.DataFrame | None:
    df = df.sort_values("timestamp").set_index("timestamp")
    rule_map = {"5m": "5min", "1h": "1h", "2h": "2h"}
    rule = rule_map.get(timeframe, timeframe)
    resampled = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"]).reset_index()
    resampled["volume"] = resampled["volume"].fillna(0).astype(int)
    return resampled if not resampled.empty else None


def _overlay_today_candle(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Replace or append today's WS candle onto the 1d DataFrame."""
    path = _today_path(symbol)
    if not path.exists():
        return df

    try:
        today_df = pd.read_parquet(path)
        if today_df.empty:
            return df
        today_df["timestamp"] = pd.to_datetime(today_df["timestamp"])
        # WS timestamps are UTC — convert to IST for date comparison
        today_ist = today_df["timestamp"].dt.tz_convert("Asia/Kolkata")
        today_date = today_ist.iloc[0].date()
        today_df["timestamp"] = today_ist.dt.tz_localize(None)

        # Remove any existing row for today in base cache
        mask = df["timestamp"].dt.date == today_date
        if mask.any():
            df = df[~mask]

        # Append today's candle
        df = pd.concat([df, today_df], ignore_index=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
    except Exception as e:
        _log.debug("Failed to overlay today candle for %s: %s", symbol, e)

    return df


def _fetch_live_today(symbol: str, timeframe: str) -> pd.DataFrame | None:
    """Fetch today's aggregated candle via WebSocket (no REST calls)."""
    try:
        from config.daemon_config import UPSTOX
        from data.upstox.upstox_live_feed import UpstoxLiveFeed

        token = UPSTOX.get("access_token", "")
        if not token:
            return None

        # Resolve to instrument key if needed
        inst_key = key_for(symbol)
        if not inst_key:
            from scripts.backtest import resolve_upstox_key
            inst_key = resolve_upstox_key(f"{symbol}.NS", "upstox")
        if not inst_key or inst_key == f"{symbol}.NS":
            return None

        feed = UpstoxLiveFeed(access_token=token)
        return feed.fetch_today_data(instrument_key=inst_key)
    except Exception as e:
        _log.debug("WS live merge failed for %s: %s", symbol, e)
        return None


def get_live_price(symbol: str) -> dict | None:
    """Fetch today's live snapshot via WebSocket (``full`` mode).

    Returns ``{ltp, open, high, low, close, volume}`` or *None*.
    """
    try:
        from config.daemon_config import UPSTOX
        from data.upstox.upstox_live_feed import UpstoxLiveFeed

        token = UPSTOX.get("access_token", "")
        if not token:
            return None

        inst_key = key_for(symbol)
        if not inst_key:
            from scripts.backtest import resolve_upstox_key
            inst_key = resolve_upstox_key(f"{symbol}.NS", "upstox")
        if not inst_key or inst_key == f"{symbol}.NS":
            return None

        feed = UpstoxLiveFeed(access_token=token)
        batch = feed.get_live_batch([inst_key], mode="full", timeout=10)
        ohlc = batch.get(inst_key)
        if ohlc is None:
            return None

        intervals = ohlc.get("_intervals") or {}
        daily = intervals.get("1d") or ohlc
        return {
            "ltp": float(daily.get("close", 0)),
            "open": float(daily.get("open", 0)),
            "high": float(daily.get("high", 0)),
            "low": float(daily.get("low", 0)),
            "close": float(daily.get("close", 0)),
            "volume": int(daily.get("vol", 0)),
        }
    except Exception as e:
        _log.debug("get_live_price failed for %s: %s", symbol, e)
        return None


def available_range(symbol: str, timeframe: str) -> dict[str, Any]:
    """Return cache coverage info for a symbol+timeframe."""
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return {"exists": False, "bars": 0, "start": None, "end": None}

    df = pd.read_parquet(path)
    if df.empty:
        return {"exists": True, "bars": 0, "start": None, "end": None}

    return {
        "exists": True,
        "bars": len(df),
        "start": str(df["timestamp"].min()),
        "end": str(df["timestamp"].max()),
    }
