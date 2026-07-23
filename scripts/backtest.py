"""
Walk-Forward Backtest Engine

Downloads historical data (Upstox for MCX/NSE, yfinance for COMEX)
and runs the ICT pipeline in walk-forward mode to evaluate trading
performance. Integrates DayTypeEngine, StockTypeEngine, and
StrategySelector to classify market conditions and apply
strategy-specific tuning parameters per trade.

Usage:
    cd /Users/jiyanshusingh/Institutional-Trading-AI
    .venv/bin/python scripts/backtest.py
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import zoneinfo

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
_log = logging.getLogger("backtest")


# ── Backtest Symbols ────────────────────────────────────────

BACKTEST_SYMBOLS = [
    ("ASIANPAINT.NS", "Asian Paints", "upstox"),
    ("BSE.NS", "BSE Ltd", "upstox"),
    ("OIL.NS", "Oil India", "upstox"),
    ("ACUTAAS.NS", "Acutaas Chemicals", "upstox"),
    ("POWERINDIA.NS", "Power India", "upstox"),
    ("FORCEMOT.NS", "Force Motors", "upstox"),
    ("ZEEL.NS", "Zee Entertainment", "upstox"),
    ("MCX_FO|555922", "Gold MCX Mini", "upstox"),
    ("MCX_FO|471726", "Silver MCX Mini", "upstox"),
    ("MCX_FO|520702", "Crude Oil MCX", "upstox"),
    ("MCX_FO|562048", "Copper MCX", "upstox"),
    ("MCX.NS", "MCX India (Stock)", "yfinance"),
    ("GC=F", "Gold COMEX", "yfinance"),
    ("SI=F", "Silver COMEX", "yfinance"),
    ("CL=F", "Crude Oil COMEX", "yfinance"),
    ("NG=F", "Natural Gas COMEX", "yfinance"),
]

TIMEFRAMES = ["15m", "1h", "1d"]

WINDOW_SIZE = 100
MAX_HOLD_BARS = 200

# Acceptance thresholds — single source of truth lives in the engine so the
# backtester and any direct engine use (e.g. live/forward scanning) stay in sync.
from engines.institutional_probability_engine import LONG_MIN_SCORE, SHORT_MIN_SCORE
MIN_PROB = LONG_MIN_SCORE                # minimum ranking score (0-100) to accept a LONG
SHORT_MIN_PROB = SHORT_MIN_SCORE         # minimum bearish score to accept a SHORT

INTRADAY_LAST_BARS = 2       # skip entries in last N bars of the day (2 = last 30m)

# Phase 24 bar-confirmation + mid-range gate. ON by default; set INST_CONFIRM_GATE=0
# to disable (for A/B baseline comparison).
_CONFIRM_GATE = os.environ.get("INST_CONFIRM_GATE", "1") != "0"

# ── Account / risk model (real capital-based sizing) ─────────
# Sizing is now based on a real account balance and a fixed % risk per trade,
# routed through engines.position_engine.PositionEngine. This replaces the old
# behaviour where RISK_PER_TRADE_PCT was (incorrectly) used as an absolute
# currency risk budget with no reference to capital.
# Capital model (account size, per-trade risk, sizing) is shared with the paper
# trader via scripts/capital_model so simulation and live never diverge.
from scripts.capital_model import (
    INITIAL_CAPITAL,
    MAX_RISK_PCT,
    MAX_TRADES_PER_DAY,
    RISK_PER_TRADE_PCT,
    calendar_conviction_multiplier,
    conviction_multiplier,
    drawdown_risk_scaler,
    ml_proba_multiplier,
    position_size_for,
)

# ── Cost model ──────────────────────────────────────────────
# All costs are OPT-IN via the environment (default = realistic discount-broker
# values). Set INST_SLIPPAGE_PCT / INST_STT_PCT / INST_BROKERAGE / INST_GST_PCT
# / INST_EXCHANGE_FEE_PCT to override, or INST_COSTS=0 to disable costs entirely
# (gross PnL, for sensitivity testing). These are module-level so a caller can
# also reassign them directly (see scripts/run_backtest_portfolio.py --slippage).
_COSTS_ENABLED = os.environ.get("INST_COSTS", "1") != "0"
SLIPPAGE_PCT = float(os.environ.get("INST_SLIPPAGE_PCT", "0.05"))      # 0.05 % per side
BROKERAGE_PER_TRADE = float(os.environ.get("INST_BROKERAGE", "20.0"))  # ₹20 flat per executed order
STT_PCT = float(os.environ.get("INST_STT_PCT", "0.025"))              # 0.025 % STT on sell (intraday equity)
GST_PCT = float(os.environ.get("INST_GST_PCT", "18.0"))               # 18 % GST on (brokerage + exchange)
EXCHANGE_FEE_PCT = float(os.environ.get("INST_EXCHANGE_FEE_PCT", "0.0001"))  # NSE + SEBI turnover fee


@dataclass
class BacktestTrade:
    symbol: str
    timeframe: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_idx: int
    entry_timestamp: str = ""
    exit_idx: int | None = None
    exit_timestamp: str | None = None
    exit_price: float | None = None
    result: str | None = None
    pnl_percent: float | None = None
    pnl_amount: float | None = None
    r_multiple: float | None = None
    reasoning: str = ""
    day_type: str = ""
    stock_type: str = ""
    strategy: str = ""
    score: int = 0
    cost_total: float = 0.0
    pnl_net: float | None = None
    pnl_net_pct: float | None = None
    is_benchmark: bool = False
    risk_pct: float | None = None
    entry_notional: float = 0.0
    features: dict = field(default_factory=dict)
    # Trailing-stop state (Daily Trend Breakout). trail_atr_mult>0 activates a
    # close-based chandelier stop: stop = max(stop, high_water_close - k*ATR);
    # the fixed take_profit is ignored so winners can run. trail_high tracks the
    # highest close since entry. max_hold_bars overrides the global time stop.
    trail_atr_mult: float = 0.0
    trail_high: float = 0.0
    max_hold_bars: int | None = None


@dataclass
class BacktestSummary:
    symbol: str
    timeframe: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl_pct: float = 0.0
    avg_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)


# ── Data Fetching ──────────────────────────────────────────────────

UPSTOX_CACHE: dict[str, pd.DataFrame] = {}
YF_CACHE: dict[str, pd.DataFrame] = {}


def _fetch_upstox(symbol: str, timeframe: str, lookback_days: int) -> pd.DataFrame | None:
    """Fetch from Upstox with a simple in-memory cache."""
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider

    token = UPSTOX.get("access_token", "")
    if not token:
        _log.warning("UPSTOX_ACCESS_TOKEN not set — skipping Upstox symbols")
        return None

    cache_key = f"upstox:{symbol}:{timeframe}:{lookback_days}"
    if cache_key in UPSTOX_CACHE:
        return UPSTOX_CACHE[cache_key]

    provider = UpstoxMarketDataProvider(access_token=token)
    interval = provider._map_timeframe(timeframe) if hasattr(provider, '_map_timeframe') else timeframe
    max_days = 60 if interval in ("30minute", "1minute") else 400
    effective_days = min(lookback_days, max_days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=effective_days)
    try:
        df = provider.load_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start,
            end_date=end,
        )
        _log.info(f"Upstox: {len(df)} candles for {symbol} @ {timeframe}")
        UPSTOX_CACHE[cache_key] = df
        return df
    except Exception as e:
        _log.warning(f"Upstox fetch failed for {symbol} ({effective_days}d): {e}")
        return None


def _fetch_upstox_with_live(symbol: str, timeframe: str, lookback_days: int) -> pd.DataFrame | None:
    """Fetch from Upstox REST for historical bars + WebSocket for today's snapshot.

    Returns a DataFrame of 30m bars (REST history only).  The WS live data is
    available separately via :func:`get_live_prices` for dashboard / live SL
    monitoring without polluting the bar DataFrame.
    """
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider

    token = UPSTOX.get("access_token", "")
    if not token:
        _log.warning("UPSTOX_ACCESS_TOKEN not set — skipping WS live fetch")
        return None

    cache_key = f"upstox+live:{symbol}:{timeframe}:{lookback_days}"
    if cache_key in UPSTOX_CACHE:
        return UPSTOX_CACHE[cache_key]

    provider = UpstoxMarketDataProvider(access_token=token)
    interval = provider._map_timeframe(timeframe) if hasattr(provider, '_map_timeframe') else timeframe
    max_days = 60 if interval in ("30minute", "1minute") else 400
    effective_days = min(lookback_days, max_days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=effective_days)
    try:
        df = provider.load_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start,
            end_date=end,
        )
    except Exception as e:
        _log.warning(f"Upstox REST failed for {symbol}: {e}")
        df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    _log.info("Upstox+WS: %d hist candles for %s @ %s", len(df), symbol, timeframe)
    UPSTOX_CACHE[cache_key] = df
    return df if not df.empty else None


# ── Upstox REST Today Intraday (1m) ────────────────────────────────

_TODAY_1M_CACHE: dict[str, pd.DataFrame] = {}

def _fetch_upstox_today_1m(instr_key: str, symbol: str) -> pd.DataFrame | None:
    """Fetch today's completed 1minute candles from Upstox REST.

    Caches to ``data/cache/today_intraday/{symbol}.parquet`` so repeated
    calls within the same day avoid API hits.

    Returns all 1m candles from 09:15 up to the current completed minute,
    or *None* on failure.
    """
    import os as _os
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from config.daemon_config import UPSTOX

    _TODAY_1M_CACHE_KEY = f"upstox_today_1m:{instr_key}"

    # In-memory cache
    if _TODAY_1M_CACHE_KEY in _TODAY_1M_CACHE:
        return _TODAY_1M_CACHE[_TODAY_1M_CACHE_KEY]

    # Disk cache (check if from today)
    cache_dir = "data/cache/today_intraday"
    cache_path = f"{cache_dir}/{symbol}.parquet"
    _os.makedirs(cache_dir, exist_ok=True)
    if _os.path.exists(cache_path):
        try:
            df = pd.read_parquet(cache_path)
            if not df.empty:
                last_ts = df["timestamp"].max()
                today = _dt.now(_tz.utc).astimezone(zoneinfo.ZoneInfo("Asia/Kolkata")).date()
                if pd.Timestamp(last_ts).date() == today:
                    _TODAY_1M_CACHE[_TODAY_1M_CACHE_KEY] = df
                    return df
        except Exception:
            pass

    token = UPSTOX.get("access_token", "")
    if not token:
        return None

    today_str = _dt.now(_tz.utc).astimezone(zoneinfo.ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    import requests as _req
    from urllib.parse import quote as _quote

    encoded = _quote(instr_key, safe="")
    url = (
        "https://api.upstox.com/v2/historical-candle/"
        f"{encoded}/1minute/{today_str}/{today_str}"
    )
    try:
        resp = _req.get(url, headers={"Accept": "application/json"}, timeout=15)
        if resp.status_code != 200:
            _log.warning("Upstox today 1m failed for %s: HTTP %d", symbol, resp.status_code)
            return None
        body = resp.json()
        candles = body.get("data", {}).get("candles", [])
        if not candles:
            _log.debug("No intraday candles yet for %s (market may be closed)", symbol)
            return None

        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
        df = df.drop(columns=["open_interest"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Cache to disk
        df.to_parquet(cache_path, index=False)
        _TODAY_1M_CACHE[_TODAY_1M_CACHE_KEY] = df
        _log.info("Upstox today 1m: %d bars for %s", len(df), symbol)
        return df
    except Exception as e:
        _log.warning("Upstox today 1m fetch failed for %s: %s", symbol, e)
        return None


def _resample_1m_to(df_1m: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    """Resample 1-minute DataFrame to higher timeframe.

    Anchors buckets to market open (09:15 IST) for consistency with
    ``candle_aggregator``.
    """
    if df_1m is None or df_1m.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df_1m.set_index("timestamp")
    # Anchor buckets to market open (09:15). Match the index tz so pandas
    # doesn't warn / misalign when the source bars are tz-aware.
    market_open = pd.Timestamp("09:15")
    if df.index.tz is not None:
        market_open = market_open.tz_localize(df.index.tz)
    resampled = df.resample(
        f"{target_minutes}min", origin=market_open, label="right", closed="right",
    )
    agg = resampled.agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open"])
    agg = agg.reset_index()
    for c in ["timestamp", "open", "high", "low", "close", "volume"]:
        if c not in agg.columns:
            from pandas import NA
            agg[c] = NA if c != "volume" else 0
    return agg


# ── WebSocket Live Price Fetch ──────────────────────────────────────

_LIVE_FEED_INSTANCE: dict[str, Any] = {}
"""Reusable singleton per token to avoid reconnect churn."""


def get_live_prices(
    symbol: str,
    timeout: float = 10.0,
) -> dict | None:
    """
    Fetch today's live OHLC snapshot via WebSocket (``full`` mode).

    Returns
    -------
    dict or None
        ``{"ltp", "open", "high", "low", "close", "volume"}`` or *None*.
    """
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_live_feed import UpstoxLiveFeed

    token = UPSTOX.get("access_token", "")
    if not token:
        return None

    try:
        feed = UpstoxLiveFeed(access_token=token)
        batch = feed.get_live_batch([symbol], mode="full", timeout=timeout)
        ohlc = batch.get(symbol)
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
        _log.debug("get_live_prices failed for %s: %s", symbol, e)
        return None


def get_live_ltp(
    symbol: str,
    timeout: float = 10.0,
) -> float | None:
    """Fetch last traded price via WebSocket (``ltpc`` mode)."""
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_live_feed import UpstoxLiveFeed

    token = UPSTOX.get("access_token", "")
    if not token:
        return None

    try:
        feed = UpstoxLiveFeed(access_token=token)
        batch = feed.get_live_batch([symbol], mode="ltpc", timeout=timeout)
        ltpc = batch.get(symbol)
        if ltpc is None:
            return None
        return float(ltpc.get("ltp", 0))
    except Exception as e:
        _log.debug("get_live_ltp failed for %s: %s", symbol, e)
        return None


def _yf_period_for(timeframe: str, lookback_days: int | None) -> str:
    """Map a timeframe + requested lookback to a yfinance ``period`` string.

    yfinance caps intraday history at fixed windows (15m ~60d, 60m/1h ~730d)
    regardless of ``lookback_days``; for daily we size the period so the
    lookback is actually honoured (e.g. 1825 days -> 5y). The default
    ``period_map`` previously forced daily to a 6-month window even when the
    caller asked for 5 years, silently starving the 200-bar EMA lookback.
    """
    if timeframe == "15m":
        return "60d"
    if timeframe == "1h":
        return "730d"
    lb = lookback_days or 180
    for limit, p in ((30, "1mo"), (90, "3mo"), (180, "6mo"), (365, "1y"), (730, "2y")):
        if lb <= limit:
            return p
    return "5y"


def _fetch_yfinance(symbol: str, timeframe: str, lookback_days: int | None = None) -> pd.DataFrame | None:
    """Fetch from yfinance with caching.

    The cache key includes the resolved yfinance period so a 5y daily request
    does not collide with (and get served by) a previously cached 6mo request
    for the same symbol+timeframe.
    """
    import yfinance as yf

    interval_map = {"15m": "15m", "1h": "60m", "1d": "1d"}
    interval = interval_map.get(timeframe, "1d")
    period = _yf_period_for(timeframe, lookback_days)

    cache_key = f"yf:{symbol}:{timeframe}:{period}"
    if cache_key in YF_CACHE:
        return YF_CACHE[cache_key]

    try:
        tk = yf.Ticker(symbol)
        df = tk.history(period=period, interval=interval, auto_adjust=False)
        if df.empty:
            return None
        df = df.reset_index()
        rename = {"Datetime": "timestamp", "Date": "timestamp",
                   "Open": "open", "High": "high", "Low": "low",
                   "Close": "close", "Volume": "volume"}
        df = df.rename(columns={c: rename[c] for c in df.columns if c in rename})
        for c in ["timestamp", "open", "high", "low", "close", "volume"]:
            if c not in df.columns:
                df[c] = None
        _log.info(f"yfinance: {len(df)} candles for {symbol} @ {timeframe} (period={period})")
        YF_CACHE[cache_key] = df
        return df
    except Exception as e:
        _log.warning(f"yfinance fetch failed for {symbol}: {e}")
        return None


def _should_use_yfinance_for_intraday(symbol: str, provider_type: str, timeframe: str) -> bool:
    """Use yfinance for NSE stock intraday because Upstox maps 15m/1h → 30minute."""
    if provider_type != "upstox":
        return False
    if timeframe == "1d":
        return False
    # NSE equity symbols end with .NS
    if symbol.endswith(".NS"):
        return True
    return False


def _warn_stale_data(df: pd.DataFrame, symbol: str, timeframe: str) -> None:
    """Warn if the backtest runs on stale data during a live trading session.

    Historical/off-hours runs legitimately use cached data, so this only fires
    when the market is currently OPEN but the last available bar is more than a
    day old — a sign the cache failed to refresh and results rest on old prices.
    """
    try:
        from data.utils.market_hours import is_market_open
        now = pd.Timestamp.now(tz="Asia/Kolkata")
        open_flag, _, _ = is_market_open(now)
        if not open_flag:
            return
        last_ts = df["timestamp"].max()
        if pd.isna(last_ts):
            return
        if getattr(last_ts, "tzinfo", None) is None:
            last_ts = last_ts.tz_localize("Asia/Kolkata")
        else:
            last_ts = last_ts.tz_convert("Asia/Kolkata")
        age_days = (now - last_ts).total_seconds() / 86400.0
        if age_days > 1.0:
            _log.warning(
                "STALE DATA: %s @ %s last bar is %.1f days old but market is OPEN — "
                "results may be based on old prices.", symbol, timeframe, age_days)
    except Exception:
        pass


def _normalize_timestamp_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize every source to IST wall-clock, then strip tz for alignment.

    yfinance returns UTC-stamped bars while Upstox returns IST-stamped bars.
    Left as-is, the two sources are misaligned by 5h30m, so a yfinance 15m bar
    labelled ``09:15`` (UTC) actually represents 14:45 IST and would not line up
    with an Upstox 15m bar anchored at 09:15 IST. Converting to IST first makes
    every source consistent. Daily bars at 00:00 UTC map to 05:30 IST on the
    SAME calendar date, so all date-based lookups are unaffected.
    """
    if df is not None and not df.empty:
        ts = df["timestamp"]
        if pd.api.types.is_datetime64_any_dtype(ts):
            if ts.dt.tz is not None:
                df = df.copy()
                df["timestamp"] = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
            else:
                df = df.copy()
                df["timestamp"] = pd.to_datetime(ts, errors="coerce")
    return df


def _nse_symbol_for_cache(symbol: str) -> str | None:
    """Extract NSE trading symbol for cache lookup, or *None* if unknown."""
    base = symbol.upper()
    if base.endswith(".NS"):
        base = base[:-3]
    # NIFTY index — cached under the ^NSEI parquet file (downloaded via Upstox
    # for the full ~729d history; yfinance caps 15m at 60 days).
    if base in ("^NSEI", "NSEI", "NIFTY", "NSE_INDEX|NIFTY 50",
                "NSE_INDEX|NIFTY50", "NSE_INDEX|Nifty 50"):
        return "^NSEI"
    # BANKNIFTY index — cached under the ^NSEBANK parquet file. 1d from yfinance
    # (^NSEBANK ticker); 15m from Upstox (resolves to NSE_INDEX|Nifty Bank).
    if base in ("^NSEBANK", "NSEBANK", "BANKNIFTY", "NSE_INDEX|NIFTY BANK",
                "NSE_INDEX|NIFTYBANK", "NSE_INDEX|Nifty Bank"):
        return "^NSEBANK"
    # India VIX — cached under the ^INDIAVIX parquet file (yfinance 1d only;
    # Upstox does not serve index-VIX data).
    if base in ("^INDIAVIX", "INDIAVIX"):
        return "^INDIAVIX"
    from data.downloader.watched_symbols import SYMBOLS
    if base in SYMBOLS:
        return base
    # Try reverse lookup from instrument key cache
    from data.downloader.watched_symbols import load_key_cache
    rev = {v: k for k, v in load_key_cache().items()}
    if base in rev:
        return rev[base]
    # Expansion-universe names (Nifty-100+ beyond the core SYMBOLS list) are not
    # in SYMBOLS or the key cache, but their 15m/1h/1d parquet was downloaded
    # (Phase 13). Resolve them so cache-only backtests can find their data.
    try:
        from data.downloader.watched_symbols import expansion_universe
        if base in expansion_universe():
            return base
    except Exception:
        pass
    return None


def _fetch_today_intraday_for_live(
    cache_sym: str,
    instr_key: str,
    timeframe: str,
    cached: pd.DataFrame,
) -> pd.DataFrame | None:
    """Merge historical cache with today's Upstox REST 1m data for live scanning.

    Tries Upstox REST 1m first, falls back to yfinance.
    """
    today_1m = _fetch_upstox_today_1m(instr_key, cache_sym)
    if today_1m is not None and not today_1m.empty:
        if timeframe == "1m":
            today_tf = today_1m
        else:
            target_min = {"15m": 15, "30m": 30, "1h": 60}.get(timeframe)
            if target_min:
                today_tf = _resample_1m_to(today_1m, target_min)
            else:
                today_tf = today_1m

        if today_tf is not None and not today_tf.empty:
            today_tf = _normalize_timestamp_tz(today_tf)

            # Merge: remove any existing rows for today from cache, append today
            today_date = today_tf["timestamp"].iloc[0].date() if hasattr(today_tf["timestamp"].iloc[0], "date") else None
            if today_date and not cached.empty:
                cached_tz = _normalize_timestamp_tz(cached.copy())
                mask = cached_tz["timestamp"].dt.date != today_date
                merged = pd.concat([cached_tz[mask], today_tf], ignore_index=True)
            else:
                merged = pd.concat([cached, today_tf], ignore_index=True)
            merged = merged.sort_values("timestamp").reset_index(drop=True)
            _log.info("Live data: %s @ %s = %d hist + %d today = %d bars",
                      cache_sym, timeframe, len(cached), len(today_tf), len(merged))
            return merged

    # Fallback: yfinance
    _log.debug("Upstox today 1m failed for %s, trying yfinance", cache_sym)
    yf_df = _fetch_yfinance(cache_sym, timeframe)
    if yf_df is not None:
        return yf_df
    _log.warning("Both Upstox and yfinance failed for %s @ %s", cache_sym, timeframe)
    return cached if not cached.empty else None


def _try_upstox_intraday_fallback(
    cache_sym: str,
    instr_key: str,
    timeframe: str,
) -> pd.DataFrame | None:
    """Try Upstox REST 1m when yfinance path was the old default.

    Used when the symbol is NSE and the timeframe is intraday.
    """
    today_1m = _fetch_upstox_today_1m(instr_key, cache_sym)
    if today_1m is not None and not today_1m.empty:
        if timeframe == "1m":
            return today_1m
        target_min = {"15m": 15, "30m": 30, "1h": 60}.get(timeframe)
        if target_min:
            return _resample_1m_to(today_1m, target_min)
    return None


def fetch_data(
    symbol: str,
    timeframe: str,
    provider_type: str,
    lookback_days: int = 120,
    original_symbol: str | None = None,
    *,
    live: bool = False,
    cache_only: bool = False,
) -> pd.DataFrame | None:
    check_symbol = original_symbol or symbol

    # Resolve Upstox instrument key (needed for today intraday fetch). Index
    # symbols (^NSEI, ^NSEBANK) and .NS equities both resolve via the index
    # key map in resolve_upstox_key; everything else falls back to raw symbol.
    instr_key = None
    if provider_type == "upstox":
        instr_key = resolve_upstox_key(symbol, "upstox")
    else:
        instr_key = symbol

    # ── Try local Parquet cache first (zero API calls) ───────────
    cache_sym = _nse_symbol_for_cache(check_symbol)
    if cache_sym:
        from data.downloader.data_registry import get_bars
        cached = get_bars(cache_sym, timeframe, lookback_days, live=False)
        if cached is not None and not cached.empty:
            if live:
                now = pd.Timestamp.now(tz="Asia/Kolkata")
                today = now.date()
                last_ts = cached["timestamp"].max()
                if hasattr(last_ts, "tz"):
                    last_ts = last_ts.tz_localize(None)
                last_date = pd.Timestamp(last_ts).date()
                if last_date == today or (now.hour < 9 and last_date >= today - pd.Timedelta(days=1)):
                    _log.debug("Cache hit (live): %s @ %s (%d bars)", cache_sym, timeframe, len(cached))
                    return _normalize_timestamp_tz(cached)
                # Cache stale — try to extend with today's intraday data
                merged = _fetch_today_intraday_for_live(cache_sym, instr_key, timeframe, cached)
                if merged is not None:
                    return merged
            else:
                _log.debug("Cache hit: %s @ %s (%d bars)", cache_sym, timeframe, len(cached))
                return _normalize_timestamp_tz(cached)

    # ── Cache-only mode: no network fallbacks ─────────────────────
    if cache_only:
        _log.warning("Cache miss (cache-only): %s @ %s — no data available", check_symbol, timeframe)
        return None

    # ── Provider fallback ─────────────────────────────────────────
    # For NSE intraday with live=True, try Upstox REST 1m first
    if live and provider_type == "upstox" and timeframe != "1d":
        upstox_df = _try_upstox_intraday_fallback(cache_sym or check_symbol.replace(".NS", ""),
                                                   instr_key, timeframe)
        if upstox_df is not None:
            return _normalize_timestamp_tz(upstox_df)

    if provider_type == "upstox+ws":
        df = _fetch_upstox_with_live(symbol, timeframe, lookback_days)
    elif _should_use_yfinance_for_intraday(check_symbol, provider_type, timeframe):
        df = _fetch_yfinance(check_symbol, timeframe)
        if df is None:
            _log.warning(f"yfinance has no data for {check_symbol}, falling back to Upstox for {symbol}")
            df = _fetch_upstox(symbol, timeframe, lookback_days)
    elif provider_type == "upstox":
        df = _fetch_upstox(instr_key, timeframe, lookback_days)
    elif provider_type == "yfinance":
        df = _fetch_yfinance(symbol, timeframe, lookback_days)
    else:
        _log.warning(f"Unknown provider: {provider_type}")
        return None

    if df is None:
        return None
    return _normalize_timestamp_tz(df)


# ── Upstox NSE key resolution ────────────────────────────

def search_upstox_instrument(symbol: str) -> str | None:
    """Resolve an NSE symbol to an Upstox instrument key via the Search API."""
    from config.daemon_config import UPSTOX
    token = UPSTOX.get("access_token", "")
    if not token:
        _log.warning("No Upstox access token available for instrument search")
        return None
    url = f"https://api.upstox.com/v2/instruments/search?query={symbol}&exchanges=NSE"
    try:
        from data.upstox.upstox_http import upstox_get
        resp = upstox_get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code != 200:
            _log.warning(f"Upstox search API error {resp.status_code} for {symbol}")
            return None
        data = resp.json().get("data", [])
        for item in data:
            if item.get("trading_symbol", "").upper() == symbol.upper():
                return item["instrument_key"]
        if data:
            return data[0]["instrument_key"]
        _log.warning(f"No instrument found for {symbol}")
        return None
    except Exception as exc:
        _log.warning(f"Upstox search API request failed for {symbol}: {exc}")
        return None


def resolve_upstox_key(symbol: str, provider: str) -> str:
    """Resolve a yfinance-style NSE symbol to an Upstox instrument key."""
    if provider in ("upstox", "upstox+ws"):
        from config.daemon_config import UPSTOX_NSE_KEYS
        base = symbol.replace(".NS", "")
        # Index symbols use yfinance tickers (^NSEI, ^NSEBANK) but need their
        # Upstox index instrument keys (NSE_INDEX|...). Map these explicitly so
        # the search API (which returns the wrong NSE_EQ stock for ^NSEBANK)
        # is bypassed.
        _INDEX_KEYS = {
            "^NSEI": "NSE_INDEX|Nifty 50",
            "NSEI": "NSE_INDEX|Nifty 50",
            "^NSEBANK": "NSE_INDEX|Nifty Bank",
            "NSEBANK": "NSE_INDEX|Nifty Bank",
            "BANKNIFTY": "NSE_INDEX|Nifty Bank",
        }
        if base in _INDEX_KEYS:
            return _INDEX_KEYS[base]
        if base in UPSTOX_NSE_KEYS:
            return UPSTOX_NSE_KEYS[base]
        key = search_upstox_instrument(base)
        if key:
            UPSTOX_NSE_KEYS[base] = key
            return key
        _log.warning(f"Could not resolve {symbol} — falling back to raw symbol")
        return symbol
    return symbol


# ── Shared decision + multi-timeframe helpers ────────────────────
# Module-level so the walk-forward backtest AND the live/forward scanner
# apply exactly the same acceptance logic (threshold, regime context, HTF
# context, intraday filters). This is the single decision path — no
# duplicated logic between backtest and live scanning.

@dataclass
class TradeDecision:
    """Outcome of a single-bar strategy decision, before trade accounting."""
    strategy_name: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    score: float
    rationale: str
    htf_ctx: dict
    htf_pass: bool
    htf_reason: str
    tuning: dict
    trail_atr_mult: float = 0.0        # >0 → trailing stop, take_profit ignored
    max_hold_bars: int | None = None   # per-trade time-stop override


def build_htf_context(
    stock_30m: pd.DataFrame | None,
    stock_daily: pd.DataFrame | None,
    ts: pd.Timestamp,
) -> dict:
    """Higher-timeframe context for a bar timestamp (strictly no look-ahead).

    Only data at or before ``ts`` is used. Returns dict with 30m and 1d trend
    metrics, or an empty dict if the higher-timeframe data is unavailable.
    """
    ctx: dict = {}
    if stock_30m is not None and not stock_30m.empty:
        mask = stock_30m["timestamp"] <= ts
        recent_30m = stock_30m[mask].tail(5)
        if len(recent_30m) >= 3:
            first = recent_30m.iloc[0]
            last = recent_30m.iloc[-1]
            ret_3 = (last["close"] - first["close"]) / first["close"] * 100
            atr_val = (recent_30m["high"] - recent_30m["low"]).mean()
            ctx["30m_return_3"] = round(ret_3, 2)
            ctx["30m_atr"] = round(atr_val, 2)
            ctx["30m_trend"] = "UP" if ret_3 > 0.5 else ("DOWN" if ret_3 < -0.5 else "FLAT")
    if stock_daily is not None and not stock_daily.empty:
        mask = stock_daily["timestamp"].dt.date < ts.date()
        recent_1d = stock_daily[mask].tail(5)
        if len(recent_1d) >= 2:
            prev_close = recent_1d.iloc[-2]["close"]
            curr_close = recent_1d.iloc[-1]["close"]
            daily_ret = (curr_close - prev_close) / prev_close * 100
            ctx["1d_return"] = round(daily_ret, 2)
            ctx["1d_trend"] = "UP" if daily_ret > 0.5 else ("DOWN" if daily_ret < -0.5 else "FLAT")
    return ctx


def htf_check(direction: str, htf: dict) -> tuple[bool, str]:
    """Return (pass, reason) for HTF trend alignment with the trade direction."""
    if not htf:
        return True, "no HTF data"

    reasons = []
    # 1d check
    td = htf.get("1d_trend", "FLAT")
    dr = htf.get("1d_return", 0)
    if direction == "LONG":
        if td == "DOWN" and dr < -1.0:
            reasons.append(f"1d strongly down ({dr:+.1f}%)")
    else:
        if td == "UP" and dr > 1.0:
            reasons.append(f"1d strongly up ({dr:+.1f}%)")

    # 30m check
    t30 = htf.get("30m_trend", "FLAT")
    r30 = htf.get("30m_return_3", 0)
    if direction == "LONG":
        if t30 == "DOWN" and r30 < -1.5:
            reasons.append(f"30m sharply down ({r30:+.1f}%)")
    else:
        if t30 == "UP" and r30 > 1.5:
            reasons.append(f"30m sharply up ({r30:+.1f}%)")

    if reasons:
        return False, "; ".join(reasons)
    return True, "HTF aligned"


# ── Bar confirmation + mid-range gate (Phase 24) ──────────────────────

def _confirmation_gate(window, entry_price, direction, strategy_name):
    """Return True if the signal bar passes the confirmation filter.

    Applies ONLY to Manual Institutional (time-gated), which enters on time
    windows regardless of bar quality — the gate filters out its low-quality
    bearish / low-volume signal bars. Validated on the full 22,022-trade set:
      - deployed watchlist net PnL: -Rs184,193 -> +Rs44,313 (gate flips it POSITIVE)
      - bearish signal bars alone: 6.6% WR / -0.682R -> correctly skipped

    RSM Swing / Combined Swing are momentum-breakout strategies whose entries
    are ALREADY bullish + volume-expanding + near range highs, so the gate is
    redundant and REMOVES winners (RSM deployed net PnL +Rs26,745 -> -Rs41,604
    with the gate). They pass through unfiltered.

    The signal bar is the LAST completed bar in `window`. LONG-only gate.
    """
    if window is None or len(window) < 3:
        return True  # not enough data -> don't block
    if direction != "LONG":
        return True  # gate calibrated on LONG entries only

    sl = strategy_name.lower()

    # ── Manual Institutional — bullish bar + volume expansion ──
    if "manual" in sl:
        last = window.iloc[-1]
        prev = window.iloc[-2]
        is_bullish = last["close"] > last["open"]
        vol_exp = last["volume"] > prev["volume"] * 1.3
        return bool(is_bullish and vol_exp)

    # ── RSM / Combined / everything else — no gate (redundant/harmful) ──
    return True


def decide_trade(
    window_df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    day_type: str,
    stock_type: str,
    nifty_intraday: pd.DataFrame | None,
    stock_daily: pd.DataFrame | None,
    stock_30m: pd.DataFrame | None,
    ts: pd.Timestamp,
    nifty_daily: pd.DataFrame | None = None,
    *,
    banknifty_df: pd.DataFrame | None = None,
    vix_daily: pd.DataFrame | None = None,
    force_strategy: str | None = None,
    tuning_override: dict | None = None,
    tuning_override_is_default: bool = False,
    multi_tf_filter: bool = True,
    intraday_mode: bool = False,
    intraday_remaining_bars: int | None = None,
    max_day_bar: int | None = None,
    day_bar: int | None = None,
    htf_ctx: dict | None = None,
    original_symbol: str | None = None,
) -> TradeDecision | None:
    """Run the regime/HTF-aware strategy decision for a single bar.

    This is the one decision path shared by the walk-forward backtest and the
    live/forward scanner. It selects (or forces) a strategy from the regime,
    builds the multi-timeframe context, runs the strategy, and applies the
    acceptance gate (score threshold), the intraday last-bar filter, and the
    HTF alignment filter.

    Returns a :class:`TradeDecision` for the first candidate that clears all
    gates, or ``None`` if no trade is taken this bar.
    """
    strategy_name = force_strategy or "ICT"
    tuning = {"sl_mult": 3.0, "tp_mult": 4.0, "atr_period": 14}
    try:
        from strategies.selector import select, get_executable
        from strategies.registry import STRATEGIES
        if tuning_override is not None:
            tuning = tuning_override
        elif not force_strategy:
            strat, _ = select(day_type, stock_type)
            if strat is not None:
                strategy_name = strat.name
                tuning = strat.tuning
        else:
            reg_strat = STRATEGIES.get(strategy_name)
            if reg_strat is not None:
                tuning = reg_strat.tuning
    except Exception as e:
        _log.warning(f"Strategy selector failed: {e}")
        return None

    try:
        executable = get_executable(strategy_name, **tuning)
    except Exception as e:
        _log.warning(f"Could not instantiate strategy {strategy_name}: {e}")
        return None

    if multi_tf_filter and htf_ctx is None:
        htf_ctx = build_htf_context(stock_30m, stock_daily, ts)
    htf_ctx = htf_ctx or {}

    if executable is None:
        return None

    strategy_result = executable.run(
        window_df, symbol, timeframe,
        day_type=day_type, stock_type=stock_type,
        nifty_df=nifty_intraday, stock_daily=stock_daily,
        nifty_daily=nifty_daily, htf_ctx=htf_ctx,
        banknifty_df=banknifty_df, vix_daily=vix_daily,
        original_symbol=original_symbol,
        tuning_override=tuning_override,
        force_override=(tuning_override is not None) and (not tuning_override_is_default),
    )

    for tc in strategy_result.trade_candidates:
        if not tc.is_executable:
            continue
        if tc.direction not in ("LONG", "SHORT"):
            continue
        if tc.entry_price is None or tc.stop_loss is None or tc.take_profit is None:
            continue

        score = tc.ranking_score
        strat_min_long = getattr(executable, 'min_score', MIN_PROB) if executable else MIN_PROB
        if tc.direction == "LONG" and score < strat_min_long:
            return None
        if tc.direction == "SHORT" and score < SHORT_MIN_PROB:
            return None

        if intraday_mode:
            if intraday_remaining_bars is not None and intraday_remaining_bars <= INTRADAY_LAST_BARS:
                return None
            if max_day_bar is not None and day_bar is not None and day_bar >= max_day_bar:
                return None

        htf_pass, htf_reason = htf_check(tc.direction, htf_ctx)
        if multi_tf_filter and not htf_pass:
            return None

        # ── Bar confirmation + mid-range gate (Phase 24) ──
        if _CONFIRM_GATE and not _confirmation_gate(
                window_df, tc.entry_price, tc.direction, strategy_name):
            return None

        return TradeDecision(
            strategy_name=strategy_name,
            direction=tc.direction,
            entry_price=tc.entry_price,
            stop_loss=tc.stop_loss,
            take_profit=tc.take_profit,
            score=score,
            rationale=getattr(tc, "rationale", "") or "",
            htf_ctx=htf_ctx,
            htf_pass=htf_pass,
            htf_reason=htf_reason,
            tuning=tuning,
            trail_atr_mult=float(getattr(tc, "trail_atr_mult", 0.0) or 0.0),
            max_hold_bars=getattr(tc, "max_hold_bars", None),
        )

    return None


# ── Backtest Engine ────────────────────────────────────────────────

class WalkForwardBacktest:
    def __init__(self, symbol: str, name: str, timeframe: str, provider_type: str,
                 intraday_mode: bool = False, max_day_bar: int | None = None,
                 nifty_symbol: str = "^NSEI", benchmark_mode: bool = False,
                 force_strategy: str | None = None,
                 multi_tf_filter: bool = True,
                 tuning_override: dict | None = None,
                 nifty_intraday: pd.DataFrame | None = None,
                 nifty_daily: pd.DataFrame | None = None,
                 banknifty_intraday: pd.DataFrame | None = None,
                 banknifty_daily: pd.DataFrame | None = None,
                 vix_daily: pd.DataFrame | None = None,
                 cache_only: bool = False):
        self.symbol = symbol
        self.name = name
        self.timeframe = timeframe
        self.provider_type = provider_type
        self.cache_only = cache_only
        self.intraday_mode = intraday_mode
        self.max_day_bar = max_day_bar
        self.nifty_symbol = nifty_symbol
        self.benchmark_mode = benchmark_mode
        self.force_strategy = force_strategy
        self.multi_tf_filter = multi_tf_filter
        self.tuning_override = tuning_override
        # Lookback window fed to the strategy each bar. Daily strategies need
        # >=200 bars for SMA200 (Daily Trend Breakout) so daily uses a larger
        # window; all other timeframes keep the validated WINDOW_SIZE=100.
        # The Intraday Trend Breakout strategy also needs >=200 bars for its
        # SMA200 trend filter on 15m, so it gets a larger window too (this only
        # applies when it is the forced strategy — other 15m strategies keep 100).
        if timeframe == "1d":
            self.window_size = 250
        elif force_strategy == "Intraday Trend Breakout":
            self.window_size = 300
        else:
            self.window_size = WINDOW_SIZE
        # Pre-fetched NIFTY series (optional). When supplied the walk-forward
        # caller fetches these OUTSIDE its scratch-cache override so the
        # historical day-type classification works for any window. If None,
        # run() fetches them itself (yfinance 15m is capped at 60 days, so only
        # recent windows get a correct day_type).
        self._nifty_intraday = nifty_intraday
        self._nifty_daily = nifty_daily
        # Pre-fetched BANKNIFTY + VIX series (optional), same rationale as
        # NIFTY — used for richer regime classification in historical windows.
        self._banknifty_intraday = banknifty_intraday
        self._banknifty_daily = banknifty_daily
        self._vix_daily = vix_daily

        # Track original symbol if it was resolved to Upstox key
        self._original_symbol = symbol
        if provider_type == "upstox":
            from config.daemon_config import UPSTOX_NSE_KEYS
            for orig, resolved in UPSTOX_NSE_KEYS.items():
                if resolved == symbol:
                    self._original_symbol = f"{orig}.NS"
                    break

        # Pre-fetched NIFTY + daily stock data (set in run())
        self._nifty_intraday: pd.DataFrame | None = None
        self._nifty_daily: pd.DataFrame | None = None
        self._stock_daily: pd.DataFrame | None = None

    # ── Forward costs ──────────────────────────────────────────────

    @staticmethod
    def _compute_costs(entry_price: float, exit_price: float, direction: str,
                       position_value: float) -> dict:
        if not _COSTS_ENABLED:
            return {"slippage_entry": 0.0, "slippage_exit": 0.0,
                    "brokerage": 0.0, "stt": 0.0, "gst": 0.0,
                    "exchange_fees": 0.0, "total": 0.0}
        slippage_entry = position_value * (SLIPPAGE_PCT / 100.0)
        slippage_exit = position_value * (SLIPPAGE_PCT / 100.0)
        brokerage = BROKERAGE_PER_TRADE
        # STT only on sell
        if direction == "LONG":
            stt = exit_price * (position_value / entry_price) * (STT_PCT / 100.0) if entry_price > 0 else 0
        else:
            stt = entry_price * (position_value / entry_price) * (STT_PCT / 100.0) if entry_price > 0 else 0
        # Exchange + SEBI turnover fee on the full round-trip turnover
        turnover = position_value * 2  # entry + exit notionals are ~equal
        exchange_fees = turnover * (EXCHANGE_FEE_PCT / 100.0)
        # GST on (brokerage + exchange fees)
        gst = (brokerage + exchange_fees) * (GST_PCT / 100.0)
        total = slippage_entry + slippage_exit + brokerage + stt + exchange_fees + gst
        return {
            "slippage_entry": round(slippage_entry, 2),
            "slippage_exit": round(slippage_exit, 2),
            "brokerage": round(brokerage, 2),
            "stt": round(stt, 2),
            "gst": round(gst, 2),
            "exchange_fees": round(exchange_fees, 2),
            "total": round(total, 2),
        }

    # ── Feature computation for ML training ────────────────────────

    @staticmethod
    def _compute_entry_features(df: pd.DataFrame) -> dict:
        """Compute feature vector from window_df at trade entry time.

        All features are computed without lookahead using data up to and
        including the entry bar.
        """
        if df is None or len(df) < 50:
            return {}

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        open_ = df["open"].values if "open" in df.columns else close
        vol = df["volume"].values if "volume" in df.columns else np.ones(len(df))

        # RSI(14)
        def _rsi(series, period=14):
            delta = np.diff(series)
            gain = np.where(delta > 0, delta, 0.0)
            loss = np.where(delta < 0, -delta, 0.0)
            avg_gain_series = pd.Series(gain).rolling(window=period, min_periods=period).mean()
            avg_loss_series = pd.Series(loss).rolling(window=period, min_periods=period).mean()
            avg_gain_v = avg_gain_series.values
            avg_loss_v = avg_loss_series.values
            rs = avg_gain_v / np.where(avg_loss_v == 0, 1e-10, avg_loss_v)
            vals = 100.0 - (100.0 / (1.0 + rs))
            return float(vals[-1]) if len(vals) > 0 else 50.0

        # ATR(14)
        def _atr(h, l, c, period=14):
            tr = np.maximum(
                h[1:] - l[1:],
                np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
            )
            tr = np.insert(tr, 0, h[0] - l[0])
            return float(pd.Series(tr).rolling(period).mean().iloc[-1])

        # EMA
        def _ema(s, period):
            return float(pd.Series(s).ewm(span=period, adjust=False).mean().iloc[-1])

        features: dict[str, float] = {}

        features["rsi_14"] = _rsi(close)
        atr_val = _atr(high, low, close)
        features["atr_pct"] = atr_val / max(close[-1], 0.01) * 100.0
        avg_vol = float(np.mean(vol[-21:-1])) if len(vol) > 21 else float(np.mean(vol))
        features["volume_ratio"] = float(vol[-1]) / max(avg_vol, 1e-10)
        # BB width
        bb_mid = float(pd.Series(close).rolling(20).mean().iloc[-1])
        bb_std = float(pd.Series(close).rolling(20).std().iloc[-1])
        features["bb_width"] = (bb_std * 4.0) / max(bb_mid, 0.01) * 100.0 if bb_mid > 0 else 0.0
        features["recent_high_dist_pct"] = float((np.max(high[-20:]) - close[-1])) / max(close[-1], 0.01) * 100.0
        features["recent_low_dist_pct"] = float((close[-1] - np.min(low[-20:]))) / max(close[-1], 0.01) * 100.0
        features["ema20_dist_pct"] = (close[-1] - _ema(close, 20)) / max(close[-1], 0.01) * 100.0
        features["ema50_dist_pct"] = (close[-1] - _ema(close, 50)) / max(close[-1], 0.01) * 100.0

        # Overnight gap: current bar open vs previous bar close (gap continuation/reversal)
        if len(open_) >= 2 and len(close) >= 3:
            prev_close = close[-2]
            cur_open = open_[-1]
            features["overnight_gap_pct"] = (cur_open - prev_close) / max(prev_close, 0.01) * 100.0
        else:
            features["overnight_gap_pct"] = 0.0

        # Recent drawdown: distance of close from 20-bar high (overbought context)
        features["max_drawdown_recent"] = (close[-1] - np.max(high[-20:])) / max(close[-1], 0.01) * 100.0

        return features

    # ── Main run loop ──────────────────────────────────────────────

    def run(self, days: int = 120) -> BacktestSummary:

        # ── 1. Fetch primary data ──────────────────────────────
        df = fetch_data(self.symbol, self.timeframe, self.provider_type, days,
                        original_symbol=self._original_symbol,
                        cache_only=self.cache_only)
        if df is None or len(df) < self.window_size + 20:
            _log.warning(f"Not enough data for {self.symbol} @ {self.timeframe}")
            return BacktestSummary(symbol=self.symbol, timeframe=self.timeframe)

        _warn_stale_data(df, self.symbol, self.timeframe)

        # ── 2. Pre-fetch NIFTY data for correct historical classification ──
        _log.info("Pre-fetching NIFTY data for day/stock type classification ...")
        # NIFTY intraday at the same timeframe as the stock. Prefer the cached
        # Upstox series (full ~729d history, covers historical windows) and
        # fall back to yfinance (60-day 15m cap → only recent windows). If the
        # caller supplied pre-fetched NIFTY (e.g. fetched outside a scratch-cache
        # override), reuse it directly.
        if self._nifty_intraday is None:
            nifty_intra = fetch_data(self.nifty_symbol, self.timeframe, "upstox", days,
                                     cache_only=self.cache_only)
            if nifty_intra is None and not self.cache_only:
                nifty_intra = fetch_data(self.nifty_symbol, self.timeframe, "yfinance", days,
                                         cache_only=self.cache_only)
            if nifty_intra is not None:
                nifty_intra = _normalize_timestamp_tz(nifty_intra)
            self._nifty_intraday = nifty_intra

        if self._nifty_daily is None:
            nifty_daily = fetch_data(self.nifty_symbol, "1d", "yfinance", 1825,
                                     cache_only=self.cache_only)
            if nifty_daily is not None:
                nifty_daily = _normalize_timestamp_tz(nifty_daily)
            self._nifty_daily = nifty_daily

        # ── 2b. Pre-fetch BANKNIFTY + VIX for richer regime classification ──
        # Same pattern as NIFTY: prefer the caller-supplied series (fetched
        # outside the walk-forward scratch-cache override) else fetch here.
        # BANKNIFTY uses the yfinance ticker ^NSEBANK / Upstox index key
        # NSE_INDEX|Nifty Bank (mapped in resolve_upstox_key). VIX is yfinance
        # ^INDIAVIX (no Upstox equivalent).
        if self._banknifty_intraday is None:
            bnk_intra = fetch_data("^NSEBANK", self.timeframe, "upstox", days,
                                   cache_only=self.cache_only)
            if bnk_intra is None and not self.cache_only:
                bnk_intra = fetch_data("^NSEBANK", self.timeframe, "yfinance", days,
                                       cache_only=self.cache_only)
            if bnk_intra is not None:
                bnk_intra = _normalize_timestamp_tz(bnk_intra)
            self._banknifty_intraday = bnk_intra

        if self._banknifty_daily is None:
            bnk_daily = fetch_data("^NSEBANK", "1d", "yfinance", 1825,
                                   cache_only=self.cache_only)
            if bnk_daily is not None:
                bnk_daily = _normalize_timestamp_tz(bnk_daily)
            self._banknifty_daily = bnk_daily

        if self._vix_daily is None:
            vix_daily = fetch_data("^INDIAVIX", "1d", "yfinance", 1825,
                                   cache_only=self.cache_only)
            if vix_daily is not None:
                vix_daily = _normalize_timestamp_tz(vix_daily)
            self._vix_daily = vix_daily

        # ── 3. Pre-fetch stock daily ──
        # Load FULL history (cache ~5yr) so the point-in-time slice always has
        # 200+ days of lookback for the historical-performance factor.
        stock_daily = fetch_data(self.symbol, "1d", self.provider_type, 1825,
                                 original_symbol=self._original_symbol,
                                 cache_only=self.cache_only)
        if stock_daily is not None:
            stock_daily = _normalize_timestamp_tz(stock_daily)
        self._stock_daily = stock_daily

        # ── 3b. Build 30m series for multi-TF context ─────────
        # yfinance does not serve a true 30m series for NSE (the "30m" fetch
        # falls back to daily bars), so derive a real 30m series by resampling
        # the primary intraday bars. This is the higher-timeframe context the
        # engine actually consumes (htf_ctx["30m_trend"]).
        self._stock_30m: pd.DataFrame | None = None
        if self.multi_tf_filter and self.timeframe in ("15m", "1m", "5m") and df is not None and len(df):
            try:
                self._stock_30m = _resample_1m_to(df, 30)
            except Exception as e:
                _log.warning(f"30m resample failed for {self.symbol}: {e}")
                self._stock_30m = None

        # ── 4. Align data lengths ──────────────────────────────
        # Slice the index series (NIFTY / BANKNIFTY intraday) to the SAME date
        # range as the stock window. Index-based truncation would misalign them
        # whenever the stock df is a sub-window of the cached index history (as
        # in the walk-forward, where the stock is sliced to [train/test] while
        # the index history is the full ~729d cache) — leaving every bar's
        # day-type classification UNKNOWN. Date-slicing keeps them aligned.
        if self._nifty_intraday is not None and not df.empty:
            lo, hi = df["timestamp"].min(), df["timestamp"].max()
            self._nifty_intraday = self._nifty_intraday[
                (self._nifty_intraday["timestamp"] >= lo)
                & (self._nifty_intraday["timestamp"] <= hi)
            ].reset_index(drop=True)
        if self._banknifty_intraday is not None and not df.empty:
            lo, hi = df["timestamp"].min(), df["timestamp"].max()
            self._banknifty_intraday = self._banknifty_intraday[
                (self._banknifty_intraday["timestamp"] >= lo)
                & (self._banknifty_intraday["timestamp"] <= hi)
            ].reset_index(drop=True)

        _log.info(f"Running backtest on {len(df)} candles for {self.name} ({self.timeframe})"
                  f"{' [INTRADAY]' if self.intraday_mode else ''}")

        # ── 5. Intraday preprocessing ──────────────────────────
        last_of_day: set[int] = set()
        if self.intraday_mode:
            df["_date"] = df["timestamp"].dt.date
            df["_day_bar_idx"] = df.groupby("_date").cumcount()
            for _, grp in df.groupby("_date"):
                if len(grp) > 0:
                    last_of_day.add(grp.index[-1])

        trades: list[BacktestTrade] = []
        open_trades: list[BacktestTrade] = []
        benchmark_queue: list[BacktestTrade] = []
        equity = [INITIAL_CAPITAL]
        capital = INITIAL_CAPITAL
        locked_cash = 0.0  # sum of notional of all open positions
        position_size = INITIAL_CAPITAL
        # Per-day new-entry counter to enforce MAX_TRADES_PER_DAY.
        entries_per_day: dict = {}

        # ── Precompute true ATR(14) for trailing stops (Daily Trend Breakout).
        # _atr_trail[j] = mean true-range over bars ending at j (no look-ahead;
        # only used to trail a stop AFTER entry). NaN for the first 14 bars.
        try:
            _h = df["high"].to_numpy(dtype=float)
            _l = df["low"].to_numpy(dtype=float)
            _c = df["close"].to_numpy(dtype=float)
            if len(_c) > 1:
                _tr = np.maximum(
                    _h[1:] - _l[1:],
                    np.maximum(np.abs(_h[1:] - _c[:-1]), np.abs(_l[1:] - _c[:-1])),
                )
                _atr = pd.Series(_tr).rolling(14).mean().to_numpy()
                df["_atr_trail"] = np.concatenate([[np.nan], _atr])
            else:
                df["_atr_trail"] = np.nan
        except Exception:
            df["_atr_trail"] = np.nan

        total_slices = len(df) - self.window_size
        for i in range(self.window_size, len(df)):
            window_df = df.iloc[:i].tail(self.window_size).reset_index(drop=True)
            current_ts = df.iloc[i]["timestamp"]
            current_date = current_ts.date() if hasattr(current_ts, "date") else current_ts

            # ── Evaluate bar: classify + execute strategy ──
            try:
                day_type = "UNKNOWN"
                stock_type = "UNKNOWN"
                strategy_name = "ICT"

                # Build NIFTY intraday slice for the same date as the current bar
                nifty_today = None
                if self._nifty_intraday is not None:
                    try:
                        nifty_today = self._nifty_intraday[
                            self._nifty_intraday["timestamp"].dt.date == current_date
                        ].copy()
                    except Exception as e:
                        _log.debug(f"Could not slice NIFTY intraday for {current_date}: {e}")

                # Build NIFTY daily prev-day data
                nifty_prev_day = None
                if self._nifty_daily is not None:
                    try:
                        mask = self._nifty_daily["timestamp"].dt.date < current_date
                        nifty_prev_day = self._nifty_daily[mask].tail(5).copy()
                    except Exception as e:
                        _log.debug(f"Could not slice NIFTY daily for {current_date}: {e}")

                try:
                    from engines.day_type_engine import DayTypeEngine
                    _bn_prev = None
                    if self._banknifty_daily is not None:
                        _bn_prev = self._banknifty_daily[
                            self._banknifty_daily["timestamp"].dt.date < current_date
                        ]
                    day_res = DayTypeEngine.classify_historical(
                        timestamp=current_ts,
                        nifty_intraday=nifty_today,
                        nifty_daily=nifty_prev_day,
                        banknifty_daily=_bn_prev,
                    )
                    day_type = day_res.get("type", "UNKNOWN")
                except Exception as e:
                    _log.warning(f"DayTypeEngine failed at index {i}: {e}")

                # ── Stock type classification ───────────────
                try:
                    if self._nifty_intraday is not None and i < len(self._nifty_intraday):
                        from engines.stock_type_engine import StockTypeEngine
                        stock_up = window_df.rename(columns={
                            "open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume",
                        })
                        nifty_win = self._nifty_intraday.iloc[:i].tail(self.window_size).reset_index(drop=True)
                        nifty_up = nifty_win.rename(columns={
                            "open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume",
                        })
                        daily_slice = None
                        if self._stock_daily is not None:
                            # Point-in-time: exclude the in-progress day's bar
                            # (its close is not finalised at intraday bar i).
                            daily_slice = self._stock_daily[
                                self._stock_daily["timestamp"].dt.date < current_date
                            ].tail(25).copy()
                            if not daily_slice.empty:
                                daily_slice = daily_slice.rename(columns={
                                    "open": "Open", "high": "High", "low": "Low",
                                    "close": "Close", "volume": "Volume",
                                })
                        stk_res = StockTypeEngine.classify(stock_up, nifty_up, stock_daily=daily_slice)
                        stock_type = stk_res.get("type", "UNKNOWN")
                except Exception as e:
                    _log.warning(f"StockTypeEngine failed at index {i}: {e}")

                # ── Strategy selection + execution (shared decision path) ──
                # HTF context + strategy kwargs are computed once per bar and
                # reused by both the primary decision and the benchmark loop.
                # ── Point-in-time daily slices (NO look-ahead) ──
                # The engine's Market Regime, Historical Performance and
                # short_context factors must NOT see the future. Slice the daily
                # series to STRICTLY before the current date so the signal cannot
                # leak end-of-series state. (nifty_intraday is handled inside
                # DayTypeEngine which clips to current_ts.)
                _stock_daily_pit = None
                if self._stock_daily is not None:
                    _stock_daily_pit = self._stock_daily[
                        self._stock_daily["timestamp"].dt.date < current_date
                    ].copy()
                _nifty_daily_pit = None
                if self._nifty_daily is not None:
                    _nifty_daily_pit = self._nifty_daily[
                        self._nifty_daily["timestamp"].dt.date < current_date
                    ].copy()
                # nifty intraday must also be point-in-time: market_regime
                # scores it, so clip to <= current bar to avoid future leak.
                _nifty_intraday_pit = None
                if self._nifty_intraday is not None:
                    _nifty_intraday_pit = self._nifty_intraday[
                        self._nifty_intraday["timestamp"] <= current_ts
                    ].copy()
                # BANKNIFTY intraday PIT slice (market_regime scores it alongside
                # nifty for relative-strength comparison).
                _banknifty_intraday_pit = None
                if self._banknifty_intraday is not None:
                    _banknifty_intraday_pit = self._banknifty_intraday[
                        self._banknifty_intraday["timestamp"] <= current_ts
                    ].copy()
                # VIX daily PIT slice (only daily data available for VIX).
                _vix_daily_pit = None
                if self._vix_daily is not None:
                    _vix_daily_pit = self._vix_daily[
                        self._vix_daily["timestamp"].dt.date < current_date
                    ].copy()

                # HTF context (strictly point-in-time): built from the PIT daily
                # slice so the 1d trend does not peek at today's unfinished daily
                # bar. build_htf_context itself also excludes the current date.
                htf_ctx: dict = {}
                if self.multi_tf_filter:
                    htf_ctx = build_htf_context(self._stock_30m, _stock_daily_pit, current_ts)

                strategy_kwargs = dict(
                    nifty_df=_nifty_intraday_pit,
                    stock_daily=_stock_daily_pit,
                    nifty_daily=_nifty_daily_pit,
                    htf_ctx=htf_ctx,
                    banknifty_df=_banknifty_intraday_pit,
                    vix_daily=_vix_daily_pit,
                )

                # Intraday timing inputs for the acceptance gate
                intraday_remaining = None
                day_bar_idx = None
                if self.intraday_mode:
                    intraday_remaining = self._bars_until_day_end(i, df, last_of_day)
                    day_bar_idx = int(df.iloc[i]["_day_bar_idx"])

                decision = decide_trade(
                    window_df, self.symbol, self.timeframe,
                    day_type, stock_type,
                    _nifty_intraday_pit, _stock_daily_pit, self._stock_30m,
                    current_ts,
                    nifty_daily=_nifty_daily_pit,
                    banknifty_df=_banknifty_intraday_pit,
                    vix_daily=_vix_daily_pit,
                    force_strategy=self.force_strategy,
                    tuning_override=self.tuning_override,
                    tuning_override_is_default=False,
                    multi_tf_filter=self.multi_tf_filter,
                    intraday_mode=self.intraday_mode,
                    intraday_remaining_bars=intraday_remaining,
                    max_day_bar=self.max_day_bar,
                    day_bar=day_bar_idx,
                    htf_ctx=htf_ctx,
                    original_symbol=self._original_symbol.replace(".NS", ""),
                )

                if decision is not None:
                    score = decision.score
                    features = self._compute_entry_features(window_df)
                    features["day_type"] = day_type
                    features["stock_type"] = stock_type
                    features["strategy"] = decision.strategy_name
                    features["direction"] = decision.direction
                    features["timeframe"] = self.timeframe
                    # Session bucket (IST): opening 09:15-10:00, morning 10:00-11:30,
                    # midday 11:30-14:00, afternoon 14:00-15:30. Intraday patterns
                    # are session-dependent (Phase 2 / Phase 18).
                    entry_ts = df.iloc[i]["timestamp"]
                    if isinstance(entry_ts, pd.Timestamp):
                        hr = entry_ts.hour + entry_ts.minute / 60.0
                        if hr < 10.0:
                            features["session"] = "opening"
                        elif hr < 11.5:
                            features["session"] = "morning"
                        elif hr < 14.0:
                            features["session"] = "midday"
                        else:
                            features["session"] = "afternoon"
                    features.update(decision.htf_ctx)
                    features["htf_pass"] = 1 if decision.htf_pass else 0
                    features["htf_reason"] = decision.htf_reason

                    entry_ts = df.iloc[i]["timestamp"]
                    if isinstance(entry_ts, pd.Timestamp):
                        entry_ts = entry_ts.isoformat()
                    bt = BacktestTrade(
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        direction=decision.direction,
                        entry_price=decision.entry_price,
                        stop_loss=decision.stop_loss,
                        take_profit=decision.take_profit,
                        entry_idx=i,
                        entry_timestamp=str(entry_ts),
                        score=score,
                        reasoning=decision.rationale,
                        day_type=day_type,
                        stock_type=stock_type,
                        strategy=decision.strategy_name,
                        features=features,
                        trail_atr_mult=decision.trail_atr_mult,
                        trail_high=decision.entry_price,
                        max_hold_bars=decision.max_hold_bars,
                    )
                    # ── Phase 0 gates: daily cap + account feasibility ──
                    # Max N new entries per calendar day (quality over quantity).
                    day_count = entries_per_day.get(current_date, 0)
                    if day_count >= MAX_TRADES_PER_DAY:
                        pass  # daily cap reached — skip this signal
                    else:
                        # Phase B: calendar conviction — amplify risk on
                        # high-edge calendar days (pre/post-holiday, monthly
                        # expiry, direction-specific weekday). Stored on the
                        # trade so settlement uses the same risk budget.
                        try:
                            _edt = pd.to_datetime(bt.entry_timestamp)
                            if bt.strategy == "ML Standalone":
                                # Phase B: proba-band sizing (score is proba*100;
                                # conviction_multiplier would map all to 1.5x flat).
                                _cal_mult = (calendar_conviction_multiplier(
                                    _edt, bt.direction, strategy=bt.strategy)
                                    * ml_proba_multiplier(score / 100.0))
                            else:
                                _cal_mult = (calendar_conviction_multiplier(
                                    _edt, bt.direction, strategy=bt.strategy)
                                    * conviction_multiplier(score))
                        except Exception:
                            _cal_mult = 1.0
                        # Drawdown circuit breaker: scale (or halt) entries when
                        # equity is in a drawdown, mirroring paper_trade.py.
                        _peak = max(equity) if equity else INITIAL_CAPITAL
                        _dd_scaler = drawdown_risk_scaler(capital, _peak)
                        if _dd_scaler == 0.0:
                            pos_notional = 0.0  # halted — no new entries in deep drawdown
                        else:
                            _cal_risk = min(RISK_PER_TRADE_PCT * _cal_mult, MAX_RISK_PCT) * _dd_scaler
                            bt.risk_pct = _cal_risk
                            pos_notional = self._position_size_for(bt.entry_price, bt.stop_loss,
                                                                     risk_pct=_cal_risk)
                        if pos_notional <= 0.0:
                            # Trade does not fit the account at the configured risk
                            # (share price / stop distance too large for ₹50k @ 1%).
                            _log.debug(
                                "Skip %s @ %.2f (SL %.2f): infeasible on ₹%.0f account",
                                self.symbol, bt.entry_price, bt.stop_loss, INITIAL_CAPITAL,
                            )
                        else:
                            # Cash-aware sizing: cap notional at free cash so concurrent
                            # positions cannot double-count the same capital (mirrors
                            # paper_trade.py:512).
                            if self.timeframe != "1d":
                                free_cash = max(0.0, capital - locked_cash)
                                if pos_notional > free_cash:
                                    pos_notional = free_cash
                            if pos_notional <= 0.0:
                                pass
                            else:
                                bt.entry_notional = pos_notional
                                locked_cash += pos_notional
                                entries_per_day[current_date] = day_count + 1
                                open_trades.append(bt)

                # ── Benchmark: run ALL registered strategies ──────
                if self.benchmark_mode:
                    from strategies.selector import EXECUTABLE_MAP as _emap
                    for _bname, _bcls in _emap.items():
                        if _bname == strategy_name:
                            continue
                        try:
                            _btuning = get_recommended_tuning(day_type, stock_type)
                            _bexe = _bcls(**_btuning)
                            _bres = _bexe.run(window_df, self.symbol, self.timeframe,
                                              day_type=day_type, stock_type=stock_type,
                                              **strategy_kwargs)
                            for _btc in _bres.trade_candidates:
                                if not _btc.is_executable:
                                    continue
                                if _btc.direction not in ("LONG", "SHORT"):
                                    continue
                                if _btc.entry_price is None or _btc.stop_loss is None or _btc.take_profit is None:
                                    continue
                                _min_for_dir = SHORT_MIN_SCORE if _btc.direction == "SHORT" else LONG_MIN_SCORE
                                if _btc.ranking_score < _min_for_dir:
                                    continue
                                # Multi-TF check for benchmark trades
                                htfp, _ = htf_check(_btc.direction, htf_ctx)
                                if self.multi_tf_filter and not htfp:
                                    continue

                                _bfeatures = dict(features) if features else {}
                                _bfeatures["day_type"] = day_type
                                _bfeatures["stock_type"] = stock_type
                                _bfeatures["strategy"] = _bname
                                _bfeatures["direction"] = _btc.direction
                                _bfeatures["timeframe"] = self.timeframe
                                _bfeatures.update(htf_ctx)
                                _bfeatures["htf_pass"] = 1 if htfp else 0

                                _entry_ts = df.iloc[i]["timestamp"]
                                if isinstance(_entry_ts, pd.Timestamp):
                                    _entry_ts = _entry_ts.isoformat()
                                _bbt = BacktestTrade(
                                    symbol=self.symbol, timeframe=self.timeframe,
                                    direction=_btc.direction,
                                    entry_price=_btc.entry_price,
                                    stop_loss=_btc.stop_loss,
                                    take_profit=_btc.take_profit,
                                    entry_idx=i, entry_timestamp=str(_entry_ts),
                                    score=_btc.ranking_score,
                                    reasoning=getattr(_btc, "rationale", "") or "",
                                    day_type=day_type, stock_type=stock_type,
                                    strategy=_bname, is_benchmark=True,
                                    features=_bfeatures,
                                )
                                # Apply intraday filter same as primary trades
                                if self.intraday_mode:
                                    remaining = self._bars_until_day_end(i, df, last_of_day)
                                    if remaining is not None and remaining <= INTRADAY_LAST_BARS:
                                        continue
                                benchmark_queue.append(_bbt)
                        except Exception as _e:
                            _log.warning("Benchmark strategy %s failed at bar %d: %s",
                                         _bname, i, _e)

            except Exception as e:
                _log.warning(f"Bar evaluation error at index {i}: {e}")

            # ── Check exits for all open trades ─────────────────
            settled: list[BacktestTrade] = []
            for ot in open_trades:
                result = self._check_exit(ot, df, i)
                if result is not None:
                    self._settle_trade(ot, result)
                    capital += (ot.pnl_amount or 0.0)
                    equity.append(capital)
                    trades.append(ot)
                    settled.append(ot)

            for s in settled:
                locked_cash -= s.entry_notional
                open_trades.remove(s)

            # ── Intraday: force-close at end of day ─────────────
            if self.intraday_mode and i in last_of_day:
                for ot in list(open_trades):
                    ot.exit_idx = i
                    ot.exit_timestamp = df.iloc[i]["timestamp"]
                    if isinstance(ot.exit_timestamp, pd.Timestamp):
                        ot.exit_timestamp = ot.exit_timestamp.isoformat()
                    ot.exit_price = float(df.iloc[i]["close"])
                    ot.result = "CLOSE"
                    diff = (ot.exit_price - ot.entry_price) if ot.direction == "LONG" \
                           else (ot.entry_price - ot.exit_price)
                    pos_size = self._position_size_for(ot.entry_price, ot.stop_loss, risk_pct=getattr(ot, 'risk_pct', None))
                    ot.pnl_amount = diff * (pos_size / ot.entry_price) if ot.entry_price > 0 else 0.0
                    cost_info = self._compute_costs(ot.entry_price, ot.exit_price, ot.direction,
                                                     pos_size)
                    ot.cost_total = cost_info["total"]
                    ot.pnl_net = (ot.pnl_amount or 0) - ot.cost_total
                    ot.pnl_net_pct = (ot.pnl_net / (ot.entry_price * (pos_size / ot.entry_price))) * 100 \
                        if ot.entry_price > 0 else 0
                    ot.pnl_percent = (diff / abs(ot.entry_price - ot.stop_loss)) * 100.0 \
                        if abs(ot.entry_price - ot.stop_loss) > 0 else 0.0
                    ot.r_multiple = (ot.pnl_percent or 0.0) / 100.0
                    capital += (ot.pnl_amount or 0.0)
                    locked_cash -= ot.entry_notional
                    equity.append(capital)
                    trades.append(ot)
                    open_trades.remove(ot)

            # ── Stale trade cleanup ─────────────────────────────
            stale = [ot for ot in open_trades if i - ot.entry_idx > (ot.max_hold_bars or MAX_HOLD_BARS)]
            for s in stale:
                s.exit_idx = i
                s.exit_timestamp = df.iloc[i]["timestamp"]
                if isinstance(s.exit_timestamp, pd.Timestamp):
                    s.exit_timestamp = s.exit_timestamp.isoformat()
                s.exit_price = float(df.iloc[i]["close"])
                s.result = "EXPIRED"
                diff = (s.exit_price - s.entry_price) if s.direction == "LONG" \
                       else (s.entry_price - s.exit_price)
                risk_s = abs(s.entry_price - s.stop_loss)
                s.r_multiple = (diff / risk_s) if risk_s > 0 else 0.0
                s.pnl_percent = (diff / s.entry_price) * 100.0 if s.entry_price > 0 else 0.0
                pos_size = self._position_size_for(s.entry_price, s.stop_loss, risk_pct=getattr(s, 'risk_pct', None))
                s.pnl_amount = diff * (pos_size / s.entry_price) if s.entry_price > 0 else 0.0
                cost_info = self._compute_costs(s.entry_price, s.exit_price, s.direction, pos_size)
                s.cost_total = cost_info["total"]
                s.pnl_net = (s.pnl_amount or 0) - s.cost_total
                s.pnl_net_pct = (s.pnl_net / pos_size) * 100.0 if pos_size > 0 else 0.0
                capital += (s.pnl_amount or 0.0)
                equity.append(capital)
                locked_cash -= s.entry_notional
                trades.append(s)
                open_trades.remove(s)

        while open_trades:
            ot = open_trades.pop(0)
            locked_cash -= ot.entry_notional
            ot.exit_idx = len(df) - 1
            ot.exit_timestamp = df.iloc[-1]["timestamp"]
            if isinstance(ot.exit_timestamp, pd.Timestamp):
                ot.exit_timestamp = ot.exit_timestamp.isoformat()
            ot.exit_price = float(df.iloc[-1]["close"])
            ot.result = "EXPIRED"
            diff = (ot.exit_price - ot.entry_price) if ot.direction == "LONG" \
                   else (ot.entry_price - ot.exit_price)
            risk_e = abs(ot.entry_price - ot.stop_loss)
            ot.r_multiple = (diff / risk_e) if risk_e > 0 else 0.0
            ot.pnl_percent = (diff / ot.entry_price) * 100.0 if ot.entry_price > 0 else 0.0
            pos_size = self._position_size_for(ot.entry_price, ot.stop_loss, risk_pct=getattr(ot, 'risk_pct', None))
            ot.pnl_amount = diff * (pos_size / ot.entry_price) if ot.entry_price > 0 else 0.0
            cost_info = self._compute_costs(ot.entry_price, ot.exit_price, ot.direction, pos_size)
            ot.cost_total = cost_info["total"]
            ot.pnl_net = (ot.pnl_amount or 0) - ot.cost_total
            ot.pnl_net_pct = (ot.pnl_net / pos_size) * 100.0 if pos_size > 0 else 0.0
            capital += (ot.pnl_amount or 0.0)
            equity.append(capital)
            trades.append(ot)

        # ── Evaluate benchmark trades ──────────────────────────
        for _bbt in benchmark_queue:
            self._evaluate_benchmark_trade(_bbt, df)
            trades.append(_bbt)

        return self._aggregate(trades, equity)

    def _bars_until_day_end(self, idx: int, df: pd.DataFrame, last_of_day: set[int]) -> int | None:
        """Return number of bars remaining until end of trading day from idx."""
        remaining = 0
        for j in range(idx, len(df)):
            if j in last_of_day:
                return remaining
            remaining += 1
        return None

    def _evaluate_benchmark_trade(self, bt: BacktestTrade, df: pd.DataFrame):
        """Evaluate a benchmark trade against subsequent bars (no capital impact)."""
        for j in range(bt.entry_idx + 1, min(bt.entry_idx + MAX_HOLD_BARS + 1, len(df))):
            high = float(df.iloc[j]["high"])
            low = float(df.iloc[j]["low"])

            if bt.direction == "LONG":
                if low <= bt.stop_loss:
                    bt.exit_idx = j
                    bt.exit_price = bt.stop_loss
                    bt.result = "LOSS"
                    bt.r_multiple = -1.0
                    return
                if high >= bt.take_profit:
                    bt.exit_idx = j
                    bt.exit_price = bt.take_profit
                    risk = abs(bt.entry_price - bt.stop_loss)
                    reward = abs(bt.take_profit - bt.entry_price)
                    bt.r_multiple = reward / risk if risk > 0 else 0
                    bt.result = "WIN"
                    return
            else:
                if high >= bt.stop_loss:
                    bt.exit_idx = j
                    bt.exit_price = bt.stop_loss
                    bt.result = "LOSS"
                    bt.r_multiple = -1.0
                    return
                if low <= bt.take_profit:
                    bt.exit_idx = j
                    bt.exit_price = bt.take_profit
                    risk = abs(bt.entry_price - bt.stop_loss)
                    reward = abs(bt.take_profit - bt.entry_price)
                    bt.r_multiple = reward / risk if risk > 0 else 0
                    bt.result = "WIN"
                    return

        bt.exit_idx = len(df) - 1
        bt.exit_price = float(df.iloc[-1]["close"])
        bt.result = "EXPIRED"
        bt.r_multiple = 0.0

    def _position_size_for(self, entry: float, sl: float, risk_pct: float | None = None) -> float:
        """Delegates to the shared capital model (scripts.capital_model).

        ``risk_pct`` carries the per-trade risk budget (calendar conviction or
        other scaling applied at entry). When None, the model default is used.
        """
        return position_size_for(entry, sl, risk_pct=risk_pct)

    def _settle_trade(self, ot: BacktestTrade, result: dict):
        ot.exit_idx = result["exit_idx"]
        ot.exit_price = result["exit_price"]
        ot.exit_timestamp = result.get("exit_timestamp", "")
        ot.result = result["result"]
        risk = abs(ot.entry_price - ot.stop_loss)
        diff = (ot.exit_price - ot.entry_price) if ot.direction == "LONG" \
               else (ot.entry_price - ot.exit_price)
        if risk > 0 and ot.entry_price > 0:
            # Signed R = realised move / initial risk. Identical to the legacy
            # WIN(reward/risk)/LOSS(-1.0) for fixed SL/TP exits, but also correct
            # for trailing-stop exits that close between the initial SL and entry
            # (a partial loss ≈ -0.4R, not a full -1.0R) or above entry.
            ot.r_multiple = diff / risk
        else:
            ot.r_multiple = 0.0
        ot.pnl_percent = (diff / ot.entry_price) * 100.0 if ot.entry_price > 0 else 0.0
        pos_size = self._position_size_for(ot.entry_price, ot.stop_loss, risk_pct=getattr(ot, 'risk_pct', None))
        ot.pnl_amount = diff * (pos_size / ot.entry_price) if ot.entry_price > 0 else 0.0

        entry_value = pos_size
        cost_info = self._compute_costs(ot.entry_price, ot.exit_price, ot.direction, entry_value)
        ot.cost_total = cost_info["total"]
        ot.pnl_net = (ot.pnl_amount or 0) - ot.cost_total
        ot.pnl_net_pct = (ot.pnl_net / entry_value) * 100 if entry_value > 0 else 0

    def _check_exit(self, trade: BacktestTrade, df: pd.DataFrame, current_idx: int) -> dict | None:
        if current_idx <= trade.entry_idx:
            return None

        entry_idx = trade.entry_idx
        max_hold = trade.max_hold_bars or MAX_HOLD_BARS

        # ── Trailing-stop exit (Daily Trend Breakout) ──────────────
        # Close-based chandelier: the high-water mark and the exit trigger both
        # use the bar CLOSE (matches the validated concept test). The fixed
        # take_profit is ignored so winners run until the trail is hit or the
        # time stop expires. LONG-only for v1 (SHORT falls through to fixed).
        if trade.trail_atr_mult > 0 and trade.direction == "LONG":
            hwm = trade.entry_price          # highest close since entry
            stop = trade.stop_loss           # starts at the initial ATR stop
            for j in range(entry_idx + 1, min(current_idx + 1, entry_idx + max_hold + 1)):
                if j >= len(df):
                    break
                candle = df.iloc[j]
                close = float(candle["close"])
                atr_j = candle.get("_atr_trail", float("nan"))
                atr_j = float(atr_j) if atr_j == atr_j else 0.0  # NaN guard
                if close > hwm:
                    hwm = close
                if atr_j > 0:
                    stop = max(stop, hwm - trade.trail_atr_mult * atr_j)
                if close <= stop:
                    exit_ts = candle["timestamp"]
                    if isinstance(exit_ts, pd.Timestamp):
                        exit_ts = exit_ts.isoformat()
                    result = "WIN" if close > trade.entry_price else "LOSS"
                    return {"exit_idx": j, "exit_price": close, "result": result,
                            "exit_timestamp": str(exit_ts)}
            return None

        for j in range(entry_idx + 1, min(current_idx + 1, entry_idx + max_hold + 1)):
            if j >= len(df):
                break
            candle = df.iloc[j]
            high = float(candle["high"])
            low = float(candle["low"])
            exit_ts = candle["timestamp"]
            if isinstance(exit_ts, pd.Timestamp):
                exit_ts = exit_ts.isoformat()

            if trade.direction == "LONG":
                if low <= trade.stop_loss:
                    return {"exit_idx": j, "exit_price": trade.stop_loss, "result": "LOSS", "exit_timestamp": str(exit_ts)}
                if high >= trade.take_profit:
                    return {"exit_idx": j, "exit_price": trade.take_profit, "result": "WIN", "exit_timestamp": str(exit_ts)}
            else:
                if high >= trade.stop_loss:
                    return {"exit_idx": j, "exit_price": trade.stop_loss, "result": "LOSS", "exit_timestamp": str(exit_ts)}
                if low <= trade.take_profit:
                    return {"exit_idx": j, "exit_price": trade.take_profit, "result": "WIN", "exit_timestamp": str(exit_ts)}

        return None

    def _aggregate(self, trades: list[BacktestTrade], equity: list[float]) -> BacktestSummary:
        summary = BacktestSummary(symbol=self.symbol, timeframe=self.timeframe)
        summary.equity_curve = equity if equity else [INITIAL_CAPITAL]

        primary = [t for t in trades if not t.is_benchmark]
        summary.trades = primary

        if not primary:
            return summary

        resolved = []
        for t in primary:
            if t.result in ("WIN", "LOSS", "EXPIRED"):
                resolved.append(t)
            elif t.result == "CLOSE" and t.r_multiple is not None:
                resolved.append(t)

        wins = [t for t in resolved if (t.result == "WIN") or (t.result in ("CLOSE", "EXPIRED") and (t.r_multiple or 0) > 0)]
        losses = [t for t in resolved if (t.result == "LOSS") or (t.result in ("CLOSE", "EXPIRED") and (t.r_multiple or 0) <= 0)]
        summary.total_trades = len(resolved)
        summary.wins = len(wins)
        summary.losses = len(losses)
        summary.win_rate = (len(wins) / summary.total_trades * 100.0) if summary.total_trades > 0 else 0.0

        all_closed = [t for t in primary if t.r_multiple is not None]
        r_values = [t.r_multiple for t in all_closed if t.r_multiple is not None]
        summary.avg_r = sum(r_values) / len(r_values) if r_values else 0.0

        gross_win = sum((t.pnl_amount or 0.0) for t in wins) if wins else 0.0
        gross_loss = abs(sum((t.pnl_amount or 0.0) for t in losses)) if losses else 1.0
        summary.profit_factor = gross_win / gross_loss if gross_loss > 0 else 0.0

        summary.total_pnl_pct = ((equity[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100.0 if equity else 0.0

        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
        summary.max_drawdown = max_dd

        return summary


# ── Report ─────────────────────────────────────────────────────────

def _print_trade_breakdown(trades: list[BacktestTrade], label: str, key: str):
    """Print a breakdown of trades grouped by a field.

    key is the attribute name on BacktestTrade, e.g. 'day_type', 'stock_type', 'strategy'.
    """
    groups: dict[str, list[BacktestTrade]] = {}
    for t in trades:
        val = getattr(t, key, "UNKNOWN")
        groups.setdefault(val, []).append(t)

    print(f"     {label}:")
    for val, grp in sorted(groups.items(), key=lambda x: -len(x[1])):
        wins = sum(1 for t in grp if t.result == "WIN")
        losses = sum(1 for t in grp if t.result == "LOSS")
        total = len(grp)
        wr = (wins / total) * 100 if total > 0 else 0
        avg_r = sum(t.r_multiple or 0 for t in grp if t.r_multiple is not None)
        avg_r = avg_r / total if total > 0 else 0
        pnl = sum(t.pnl_amount or 0 for t in grp)
        print(f"       {val:20s}  n={total:3d}  WR={wr:5.1f}%  avgR={avg_r:+.2f}  PnL={pnl:+.0f}")


def _print_condition_strategy_breakdown(trades: list[BacktestTrade]):
    """Print a 2D breakdown: (day_type, stock_type, strategy) → WR, avg R."""
    groups: dict[tuple[str, str, str], list[BacktestTrade]] = {}
    for t in trades:
        if t.result not in ("WIN", "LOSS"):
            continue
        key = (t.day_type or "UNKNOWN", t.stock_type or "UNKNOWN", t.strategy or "UNKNOWN")
        groups.setdefault(key, []).append(t)

    if not groups:
        return

    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    print()
    print("     Condition × Strategy Breakdown:")
    print(f"       {'Day Type':15s} {'Stock Type':12s} {'Strategy':38s} {'n':>4s} {'WR':>6s} {'AvgR':>6s}")
    print(f"       {'-'*15} {'-'*12} {'-'*38} {'-'*4} {'-'*6} {'-'*6}")

    best_per_condition: dict[tuple[str, str], tuple[str, int, float]] = {}

    for (dt, st, strat), grp in sorted_groups:
        wins = sum(1 for t in grp if t.result == "WIN")
        total = len(grp)
        wr = (wins / total) * 100 if total > 0 else 0
        avg_r = sum(t.r_multiple or 0 for t in grp)
        avg_r = avg_r / total if total > 0 else 0
        print(f"       {dt:15s} {st:12s} {strat:38s} {total:4d} {wr:5.1f}% {avg_r:+5.2f}")

        cond = (dt, st)
        cur_best = best_per_condition.get(cond)
        if cur_best is None or (wr > cur_best[2] and total >= 2):
            best_per_condition[cond] = (strat, total, wr)

    print()
    print("     Best Strategy Per Condition (min 2 trades):")
    print(f"       {'Day Type':15s} {'Stock Type':12s} {'Best Strategy':38s} {'n':>4s} {'WR':>6s}")
    print(f"       {'-'*15} {'-'*12} {'-'*38} {'-'*4} {'-'*6}")
    for cond, (strat, total, wr) in sorted(best_per_condition.items(),
                                            key=lambda x: -x[1][2] if x[1][2] > 0 else 0):
        print(f"       {cond[0]:15s} {cond[1]:12s} {strat:38s} {total:4d} {wr:5.1f}%")


def _export_trades_csv(trades: list[BacktestTrade], filepath: str):
    """Export trade list to CSV including ML features."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Determine all feature keys present across trades
    all_feature_keys = sorted(set(
        k for t in trades
        for k in (t.features or {}).keys()
        if k not in ("day_type", "stock_type", "strategy", "direction", "timeframe")
    ))

    fields = [
        "symbol", "timeframe", "direction", "strategy",
        "entry_idx", "entry_price", "stop_loss", "take_profit",
        "exit_idx", "exit_price", "result", "day_type", "stock_type",
        "r_multiple", "pnl_percent", "pnl_amount",
        "cost_total", "pnl_net", "pnl_net_pct", "reasoning",
        "is_benchmark",
    ] + all_feature_keys

    with open(filepath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for t in trades:
            row = [
                t.symbol, t.timeframe, t.direction, t.strategy,
                t.entry_idx, t.entry_price, t.stop_loss, t.take_profit,
                t.exit_idx, t.exit_price, t.result, t.day_type, t.stock_type,
                t.r_multiple, t.pnl_percent, t.pnl_amount,
                t.cost_total, t.pnl_net, t.pnl_net_pct, t.reasoning,
                t.is_benchmark,
            ]
            for k in all_feature_keys:
                val = (t.features or {}).get(k)
                row.append(val if val is not None else "")
            w.writerow(row)
    _log.info(f"Trades exported to {filepath}")


def print_report(summaries: list[BacktestSummary]):
    print()
    print("=" * 80)
    print("  WALK-FORWARD BACKTEST RESULTS")
    print("=" * 80)
    print()

    for s in summaries:
        print(f"  {s.name:25s} | {s.timeframe:4s} | "
              f"Trades: {s.total_trades:3d} | "
              f"Win Rate: {s.win_rate:5.1f}% | "
              f"Avg R: {s.avg_r:5.2f} | "
              f"PF: {s.profit_factor:5.2f} | "
              f"PnL: {s.total_pnl_pct:+6.2f}% | "
              f"Max DD: {s.max_drawdown:5.1f}%")

    print()
    print("-" * 80)

    for s in summaries:
        if s.total_trades == 0:
            continue
        print()
        print(f"  ── {s.symbol} ({s.timeframe}) ──")
        print(f"     Total Trades:    {s.total_trades}")
        print(f"     Wins:            {s.wins}")
        print(f"     Losses:          {s.losses}")
        print(f"     Win Rate:        {s.win_rate:.1f}%")
        print(f"     Avg R Multiple:  {s.avg_r:.2f}")
        print(f"     Profit Factor:   {s.profit_factor:.2f}")
        print(f"     Total PnL:       {s.total_pnl_pct:+.2f}%")
        print(f"     Max Drawdown:    {s.max_drawdown:.1f}%")
        print(f"     Equity:          ₹{INITIAL_CAPITAL:,.0f} → ₹{INITIAL_CAPITAL + INITIAL_CAPITAL * s.total_pnl_pct / 100:,.0f}")
        print()

        winners = [t for t in s.trades if t.result == "WIN"]
        losers = [t for t in s.trades if t.result == "LOSS"]

        if winners:
            avg_win_r = sum(t.r_multiple or 0 for t in winners) / len(winners)
            print(f"     Avg Win R:       {avg_win_r:.2f}")
        if losers:
            avg_loss_r = sum(t.r_multiple or 0 for t in losers) / len(losers)
            print(f"     Avg Loss R:      {avg_loss_r:.2f}")

        # ── Cost summary ────────────────────────────────────
        total_costs = sum(t.cost_total or 0 for t in s.trades)
        total_net_pnl = sum(t.pnl_net or 0 for t in s.trades if t.pnl_net is not None)
        print(f"     Total Costs:     ₹{total_costs:,.0f}")
        print(f"     Net PnL (est):   ₹{total_net_pnl:,.0f}")

        # ── Day type / stock type / strategy breakdown ──────
        resolved = [t for t in s.trades if t.result in ("WIN", "LOSS")]
        if resolved:
            _print_trade_breakdown(resolved, "Day Type Breakdown", "day_type")
            _print_trade_breakdown(resolved, "Stock Type Breakdown", "stock_type")
            _print_trade_breakdown(resolved, "Strategy Breakdown", "strategy")
            # ── Condition × strategy breakdown ─────────────
            _print_condition_strategy_breakdown(resolved)
            # Score bucket breakdown
            buckets = {80: "HIGH≥80", 60: "MEDIUM≥60", 30: "LOW<60"}
            print("     Score Bucket Breakdown:")
            for thresh, label in sorted(buckets.items()):
                bucket = [t for t in resolved if t.score >= thresh] if thresh > 30 \
                         else [t for t in resolved if t.score < 60]
                if not bucket:
                    continue
                wins_b = sum(1 for t in bucket if t.result == "WIN")
                losses_b = sum(1 for t in bucket if t.result == "LOSS")
                total_b = len(bucket)
                wr_b = (wins_b / total_b) * 100 if total_b > 0 else 0
                avg_r_b = sum(t.r_multiple or 0 for t in bucket if t.r_multiple is not None)
                avg_r_b = avg_r_b / total_b if total_b > 0 else 0
                print(f"       {label:20s}  n={total_b:3d}  WR={wr_b:5.1f}%  avgR={avg_r_b:+.2f}")

        if len(s.equity_curve) > 1:
            eq_s = pd.Series(s.equity_curve)
            print(f"     Final Equity:    ₹{eq_s.iloc[-1]:,.0f}")
            print(f"     Sharpe (approx): {(eq_s.pct_change().mean() / eq_s.pct_change().std() * (252**0.5)) if eq_s.pct_change().std() > 0 else 0:.2f}")

        # ── CSV export ──────────────────────────────────────
        if s.trades:
            csv_path = f"data/trades_{s.symbol}_{s.timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            _export_trades_csv(s.trades, csv_path)
            print(f"     Trades exported: {csv_path}")

        print()

    total_all = sum(s.total_trades for s in summaries)
    total_wins = sum(s.wins for s in summaries)
    total_losses = sum(s.losses for s in summaries)
    if total_all > 0:
        print("  ── AGGREGATE ──")
        print(f"     Total Trades:    {total_all}")
        print(f"     Win Rate:        {(total_wins / total_all) * 100:.1f}%")
        total_pnl = sum(s.total_pnl_pct for s in summaries)
        print(f"     Avg PnL/Symbol:  {total_pnl / len(summaries):+.2f}%" if summaries else "")
        print()


# ── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Walk-forward backtest engine")
    parser.add_argument("--intraday", "-i", action="store_true",
                        help="Run in intraday mode (15m/1h only, force-close at EOD)")
    parser.add_argument("--strategy", "-s", type=str, default=None,
                        help="Force a specific strategy for all conditions")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Run only this symbol (overrides BACKTEST_SYMBOLS)")
    args = parser.parse_args()

    results: list[BacktestSummary] = []
    active_tfs = ["15m", "1h"] if args.intraday else TIMEFRAMES
    mode_tag = "_intraday" if args.intraday else ""

    # Filter symbols if --symbol specified
    symbols_to_run = [(s, n, p) for s, n, p in BACKTEST_SYMBOLS
                      if args.symbol is None or s.startswith(args.symbol.upper())]

    if args.strategy:
        mode_tag = f"{mode_tag}_{args.strategy.replace(' ', '_').lower()}"

    # Resolve Upstox NSE keys and run
    for symbol, name, provider in symbols_to_run:
        resolved_symbol = resolve_upstox_key(symbol, provider)
        for tf in active_tfs:
            strat_label = f" [{args.strategy}]" if args.strategy else ""
            print(f"  Backtesting {name} ({resolved_symbol}) @ {tf}"
                  f"{' [INTRADAY]' if args.intraday else ''}{strat_label}...")
            bt = WalkForwardBacktest(resolved_symbol, name, tf, provider,
                                     intraday_mode=args.intraday,
                                     force_strategy=args.strategy)
            summary = bt.run(days=120)
            summary.name = name
            results.append(summary)

            if summary.total_trades > 0:
                print(f"    ✓ {summary.total_trades} trades, "
                      f"WR={summary.win_rate:.0f}%, "
                      f"PF={summary.profit_factor:.2f}, "
                      f"PnL={summary.total_pnl_pct:+.2f}%")
            else:
                print(f"    — No trades generated")

    print_report(results)

    report_path = f"data/backtest_report{mode_tag}.json"
    report_data = []
    for s in results:
        report_data.append({
            "symbol": s.symbol,
            "name": getattr(s, "name", s.symbol),
            "timeframe": s.timeframe,
            "total_trades": s.total_trades,
            "wins": s.wins,
            "losses": s.losses,
            "win_rate": round(s.win_rate, 2),
            "avg_r": round(s.avg_r, 2),
            "profit_factor": round(s.profit_factor, 2),
            "total_pnl_pct": round(s.total_pnl_pct, 2),
            "max_drawdown": round(s.max_drawdown, 2),
        })
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"  Report saved to {report_path}")


if __name__ == "__main__":
    main()
