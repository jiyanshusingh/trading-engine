"""
Paper-trading simulator for the Institutional Probability strategy (15m intraday
and swing).

Reuses the EXACT live decision path as the backtest / live scanner
(``decide_trade`` + ``build_htf_context`` + the same yfinance live fetch), then
adds the missing piece for "paper trading": a simulated portfolio that

  * sizes positions by capital (1% risk = ₹500 on ₹50k, no leverage),
  * enforces max 5 new entries per day,
  * opens a paper position when ``decide_trade`` returns a signal (intraday
    or swing),
  * monitors open positions against the live close and fills SL/TP,
  * tracks cash, open positions, realized P&L and equity.

State persists to ``data/paper_portfolio.json`` so a crash/restart is safe.

Modes
-----
  --mode intraday  (default) — positions close at EOD (real NSE intraday product)
  --mode swing     — positions hold overnight, exit at next_open / next_close
  --mode both      — run BOTH intraday and swing simultaneously; intraday
                     positions are force-closed at EOD, swing positions carry
                     over and exit on their scheduled time.

NOTE: default live prices come from yfinance (delayed ~15-20 min). Pass --upstox
to use the Upstox real-broker feed (REST 1m→15m for bars, WebSocket for live
prices). This is still a SIMULATED portfolio — no real orders are placed; each
fill is logged with an Upstox-format order payload ready for deployment.

Usage
-----
  .venv/bin/python scripts/paper_trade.py                 # one scan+manage cycle
  .venv/bin/python scripts/paper_trade.py --loop --interval 15   # poll every 15m
  .venv/bin/python scripts/paper_trade.py --symbols ONGC,WIPRO,RELIANCE
  .venv/bin/python scripts/paper_trade.py --upstox --symbols ONGC,WIPRO,RELIANCE
  .venv/bin/python scripts/paper_trade.py --reset         # wipe state, start fresh
  .venv/bin/python scripts/paper_trade.py --upstox --loop --interval 15  # live broker feed
"""

from __future__ import annotations

import argparse
import json
import os
import sys as _sys
import time

_sys.path.insert(0, ".")

# Default SHORT min score to 70 (LONG-only) if not set; --shorts flag changes
# this to 40 in the entry gate (see ALLOW_SHORTS). Must be set before engine
# import so the module-level default is correct.
os.environ.setdefault("INST_SHORT_MIN_SCORE", "70")

import pandas as pd

from scripts.backtest import (
    WINDOW_SIZE,
    _confirmation_gate,
    build_htf_context,
    decide_trade,
    resolve_upstox_key,
)
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
from scripts.live_institutional_scan import (
    FOCUSED_WATCHLIST,
    FORCE_STRATEGY,
    MIN_SCORE,
    TUNING,
    _bars_until_close,
    _classify_stock_type,
    _yf_live,
)
from scripts.live_scanner import classify_today_day_type
from scripts.ml_filter_gate import passes_ml_filter
from utils.telegram_notifier import format_signal_alert, send_telegram

# ── Capital model ──
# Pulled from scripts/capital_model (shared with the backtest engine) so the
# risk model can never diverge between simulation and live trading.

STATE_PATH = os.environ.get("INST_PAPER_STATE", "data/paper_portfolio.json")
TF = "15m"

# Per-strategy timeframe. Unmapped strategies default to the intraday TF ("15m").
# The Daily Trend Breakout strategy (Phase 37) runs on native daily bars with a
# trailing ATR stop and is evaluated ONCE per day in an afternoon pass (see
# _DAILY_ENTRY_WINDOW), entering at the current live price.
STRATEGY_TIMEFRAMES: dict[str, str] = {
    "Daily Trend Breakout": "1d",
}
# Afternoon window (IST decimal hours) during which the once-per-day daily pass
# (trailing-exit checks + new daily entries) runs. Chosen by backtest analysis
# (scripts/analyze_daily_entry_timing.py): the 09:15 open is the WORST entry
# time; 13:30-14:30 yields the highest net PnL (stocks gap up on breakouts then
# pull back intraday, giving a better fill in the early afternoon).
_DAILY_ENTRY_WINDOW = (13.5, 14.5)  # 13:30 → 14:30 IST


def _tf_for(strat_name: str) -> str:
    return STRATEGY_TIMEFRAMES.get(strat_name, TF)


def _is_daily_strategy(strat_name: str) -> bool:
    return _tf_for(strat_name) == "1d"

USE_UPSTOX = False  # set True via --upstox; uses the Upstox real-broker feed
REAL_ORDERS = False  # set True via --real; places actual Upstox orders (live money)
MAX_ORDER_VALUE = 25000.0  # hard safety cap: reject any single real order above this notional (₹)
ALLOW_SHORTS = False  # set True via --shorts; SHORT not yet OOS-validated
USE_CONVICTION = True   # conviction sizing ON by default; --no-conviction to disable
TRADING_MODE = "intraday"  # "intraday" | "swing" | "both" — set via --mode
SWING_EXIT_MODE = "next_close"  # "next_open" or "next_close"
SWING_ALLOW_SHORTS = False  # set True via --swing-shorts
ML_FILTER = False       # set True via --ml-filter: gate entries on P(net-positive) (Phase 32/33)
ML_FILTER_THR = 0.65    # global filter threshold (val-max-net, OOS +₹108,598); --ml-filter-thr
COOLDOWNS: dict[tuple[str, str, str], float] = {}  # (symbol, direction, strategy) -> expiry epoch; set after a stop-loss exit
LAST_ENTRY_BAR: dict[tuple[str, str, str], str] = {}  # (symbol, direction, strategy) -> last_ts string; dedup same-bar re-entries

# ── Telegram notification helpers ─────────────────────────────────────

def _notify_entry(pos: dict, strat_name: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        msg = format_signal_alert(
            symbol=pos["symbol"], name=strat_name,
            timeframe=pos.get("mode", "intraday"),
            direction=pos["direction"], entry=pos["entry_price"],
            stop=pos.get("stop_loss"), target=pos.get("take_profit"),
            rr=None, regime=""
        )
        send_telegram(msg, token, chat_id)
    except Exception:
        pass

def _notify_exit(fill: dict):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        dir_emoji = "🟢" if fill["pnl"] >= 0 else "🔴"
        msg = (
            f"{dir_emoji} <b>TRADE CLOSED</b>\n"
            f"<b>{fill['symbol']}</b> ({fill['strategy']})\n"
            f"{'📈' if fill['direction']=='LONG' else '📉'} {fill['direction']}\n"
            f"Entry: ₹{fill['entry_price']:.2f} → Exit: ₹{fill['exit_price']:.2f}\n"
            f"PnL: <b>₹{fill['pnl']:+.0f}</b> ({fill['reason']})\n"
            f"Shares: {fill['shares']}"
        )
        send_telegram(msg, token, chat_id)
    except Exception:
        pass

# Runtime globals for strategy dispatch (set by run_cycle entry loop)
PAPER_STRATEGY: str = "Institutional Probability"
PAPER_TUNING: dict | None = None

# Multi-strategy state (set via --strategies CLI)
active_strategies: list[str] = ["Institutional Probability"]
strategy_allocs: dict[str, float] = {"Institutional Probability": 100.0}
strategy_capitals: dict[str, float] = {"Institutional Probability": INITIAL_CAPITAL}
strategy_tunings: dict[str, dict | None] = {"Institutional Probability": None}

# Time-based watchlist switching for Manual Institutional strategy
MORNING_WATCHLIST_SYMBOLS: list[str] = []
EVENING_WATCHLIST_SYMBOLS: list[str] = []

# Per-strategy watchlist routing: maps each strategy to the watchlist key(s)
# it should scan. Symbols are loaded from data/symbol_watchlists.json. The
# scanner (market_scan.py SCAN_TIERS) uses the same per-strategy split; this
# keeps the paper trader aligned so each strategy only trades its own universe
# instead of a single merged list. First non-empty key wins; extra keys are
# appended as fallbacks / extra symbols.
# Phase 34: full-universe deployment. The ML filter (--ml-filter) now handles
# symbol selection dynamically, so RSM/Combined/Manual scan the full 153-symbol
# universe instead of their Phase-27 pruned watchlists (the filter picks the
# good trades). ML Standalone also scans the full universe (its own thr 0.80
# model selects entries). To revert to the pruned watchlists, restore the keys
# below (rsm_swing / combined_swing / manual_*_deploy).
STRATEGY_WATCHLISTS: dict[str, list[str]] = {
    "Institutional Probability": ["consensus"],
    "Relative Strength Momentum": ["full_nse_500"],
    "Combined Swing": ["full_nse_500"],
    "Manual Institutional (time-gated)": ["manual_morning_deploy_500", "manual_evening_deploy_500"],
    "ML Standalone": ["full_nse_500"],
    # Phase D: ML Opening Breakout — 5m opening-minutes strategy (09:15-10:30).
    # Scans the full 500-symbol NSE universe; the model selects entries via its
    # own thr-0.70 gate. Uses full_nse_500 (the Phase 35 universe) so every
    # cached 5m symbol is covered.
    "ML Opening Breakout": ["full_nse_500"],
    # Phase 37: daily trend-breakout runs on its own 108-symbol net-positive
    # universe (backtest: net +Rs2.2M / 5yr). Trailing ATR stop, LONG-only.
    "Daily Trend Breakout": ["daily_trend_breakout"],
}


# ── Upstox live data (real broker feed) ──
def _instrument_key_for(symbol: str):
    """Resolve a yfinance-style symbol to an Upstox instrument key."""
    if symbol in ("^NSEI", "NIFTY", "Nifty 50"):
        return "NSE_INDEX|Nifty 50"
    if symbol in ("^NSEBANK", "^BANKNIFTY", "Bank Nifty"):
        return "NSE_INDEX|Nifty Bank"
    return resolve_upstox_key(f"{symbol}.NS", "upstox")


def _symbol_for_instrument_key(ikey: str) -> str | None:
    """Reverse-map an Upstox instrument key back to a yfinance-style base symbol.
    Best-effort: uses the known key cache; returns None if unresolved."""
    if not ikey:
        return None
    if ikey == "NSE_INDEX|Nifty 50":
        return "^NSEI"
    if ikey == "NSE_INDEX|Nifty Bank":
        return "^NSEBANK"
    try:
        from config.daemon_config import UPSTOX_NSE_KEYS
        for base, key in UPSTOX_NSE_KEYS.items():
            if key == ikey:
                return base
    except Exception:
        pass
    return None


def _merge_intraday(provider, key, interval, hist_df):
    """Append TODAY's in-progress candles (from Upstox's intraday endpoint) onto
    the historical frame. The /historical-candle/ endpoint only serves up to the
    PREVIOUS trading day, so without this the live trader decides on yesterday's
    bars (and the day-of-week gate reads the wrong weekday). Best-effort: on any
    failure or empty intraday response, returns the historical frame unchanged."""
    if hist_df is None:
        return hist_df
    try:
        intra = provider.load_intraday_data(key, interval)
    except Exception:
        return hist_df
    if intra is None or len(intra) == 0:
        return hist_df
    try:
        import pandas as _pd
        merged = _pd.concat([hist_df, intra], ignore_index=True)
        merged["timestamp"] = _pd.to_datetime(merged["timestamp"])
        merged = (
            merged.drop_duplicates(subset="timestamp", keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        return merged
    except Exception:
        return hist_df


def _upstox_live(symbol: str, timeframe: str):
    """Fetch OHLCV from Upstox. 15m is built by resampling 1m (Upstox has no
    native 15m bar); 1d uses the daily interval. Returns the same DataFrame
    contract as ``_yf_live``: columns [timestamp, open, high, low, close,
    volume], tz-naive IST."""
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider
    from datetime import datetime, timedelta

    token = UPSTOX.get("access_token", "")
    if not token:
        return None
    key = _instrument_key_for(symbol)
    if not key:
        return None
    try:
        provider = UpstoxMarketDataProvider(token)
        if timeframe == "15m":
            start = datetime.now() - timedelta(days=8)
            df = provider.load_historical_data(key, "1m", start_date=start)
            if df is None or len(df) < 200:
                return None
            df = _merge_intraday(provider, key, "1m", df)
            df = _resample_safe(df, 15)
        elif timeframe == "1d":
            start = datetime.now() - timedelta(days=730)
            df = provider.load_historical_data(key, "1d", start_date=start)
            df = _merge_intraday(provider, key, "1d", df)
        elif timeframe == "1m":
            start = datetime.now() - timedelta(days=3)  # wider span: Upstox 1m chunker returns 0 for short windows
            df = provider.load_historical_data(key, "1m", start_date=start)
            df = _merge_intraday(provider, key, "1m", df)
            if df is not None and len(df) > 0:
                df = df.tail(390).reset_index(drop=True)  # keep last ~1 trading day of 1m candles
        elif timeframe == "5m":
            # 5m has no native Upstox interval; resample 1m (same pipeline as the
            # training data: download_history.py resamples 1m→5m). 8d of 1m yields
            # ~600 5m bars — enough for EMA50 + opening-range features.
            start = datetime.now() - timedelta(days=8)
            df = provider.load_historical_data(key, "1m", start_date=start)
            if df is None or len(df) < 200:
                return None
            df = _merge_intraday(provider, key, "1m", df)
            df = _resample_safe(df, 5)
        else:
            return None
        if df is None or df.empty:
            return None
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        from scripts.backtest import _normalize_timestamp_tz
        df = _normalize_timestamp_tz(df)
        return df
    except Exception:
        return None


def _upstox_live_price(symbol: str):
    """Latest tradable price for a held stock via Upstox WebSocket batch."""
    from data.downloader.data_registry import get_live_price
    try:
        px = get_live_price(symbol)
        if px and px.get("close"):
            return float(px["close"])
    except Exception:
        return None
    return None


def _order_payload(symbol, txn_type, qty, price, trigger, sl, mode="intraday"):
    """Upstox-format order payload for a fill (ready to POST to /v2/order/place).

    ``mode`` selects the Upstox product: "swing" -> "D" (delivery, holds
    overnight), anything else -> "I" (intraday, auto-squared at 15:30).
    Entry/exit orders are placed as MARKET; ``trigger``/``sl`` are recorded for
    the in-code SL/TP monitor, not sent as separate broker orders.
    """
    return {
        "exchange": "NSE",
        "symbol": symbol,
        "instrument_key": _instrument_key_for(symbol) if USE_UPSTOX else None,
        "quantity": qty,
        "transaction_type": txn_type,
        "order_type": "MARKET",
        "product": "D" if mode == "swing" else "I",
        "price": price,
        "trigger_price": trigger,
        "stop_loss": sl,
    }


def place_upstox_order(order: dict) -> str | None:
    """Place a REAL order via Upstox ``/v2/order/place``. Returns order_id or None.

    Never raises — callers decide what to do on failure (skip entry / retry
    exit). Only invoke when REAL_ORDERS is set. Enforces the MAX_ORDER_VALUE
    notional safety cap.
    """
    from config.daemon_config import UPSTOX
    token = UPSTOX.get("access_token", "")
    if not token:
        print("[order] WARN no Upstox token — cannot place real order")
        return None

    instrument_key = order.get("instrument_key")
    if not instrument_key:
        print(f"[order] WARN no instrument_key for {order.get('symbol')} — cannot place real order")
        return None

    # Hard safety cap: reject oversized orders (market orders use price 0, so
    # fall back to the recorded reference price for the notional estimate).
    ref_price = float(order.get("price") or 0)
    notional = ref_price * int(order["quantity"])
    if notional > MAX_ORDER_VALUE:
        print(f"[order] BLOCKED {order.get('symbol')} notional ₹{notional:,.0f} "
              f"> cap ₹{MAX_ORDER_VALUE:,.0f} — order NOT placed")
        return None

    order_type = order.get("order_type", "MARKET")
    body = {
        "quantity": int(order["quantity"]),
        "product": order.get("product", "I"),  # "I" intraday / "D" delivery (swing)
        "validity": "DAY",
        # MARKET orders must send price 0; LIMIT/SL send the actual price.
        "price": 0.0 if order_type == "MARKET" else ref_price,
        "tag": "inst-prob",
        "instrument_token": instrument_key,
        "order_type": order_type,  # MARKET / LIMIT / SL / SL-M
        "transaction_type": order["transaction_type"],  # BUY / SELL
        "disclosed_quantity": 0,
        "trigger_price": float(order.get("trigger_price") or 0),
        "is_amo": False,
    }
    url = "https://api.upstox.com/v2/order/place"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        from data.upstox.upstox_http import upstox_post
        resp = upstox_post(url, headers=headers, json=body, timeout=15)
        if resp.status_code != 200:
            print(f"[order] WARN Upstox HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        order_id = resp.json().get("data", {}).get("order_id")
        print(f"[order] LIVE {body['transaction_type']} {body['quantity']} "
              f"{order.get('symbol')} product={body['product']} → order_id={order_id}")
        return order_id
    except Exception as e:
        print(f"[order] WARN Upstox order error: {e}")
        return None


# ── Upstox order/position reconciliation helpers ──
_ORDER_POLL_ATTEMPTS = 3   # how many times to poll order status
_ORDER_POLL_DELAY = 5      # seconds between polls
_FILLED_STATES = {"complete", "filled", "traded"}
_DEAD_STATES = {"rejected", "cancelled", "canceled"}
# Divergence between paper cash and broker available margin above which we warn.
_CASH_DIVERGENCE_WARN = float(os.environ.get("INST_CASH_DIVERGENCE_WARN", "5000"))
# Re-run a conservative reconcile every N cycles during the trading day.
_RECONCILE_EVERY_N_CYCLES = int(os.environ.get("INST_RECONCILE_EVERY", "20"))
_CYCLE_COUNTER = 0  # incremented each run_cycle; drives periodic reconcile


def _upstox_headers() -> dict | None:
    from config.daemon_config import UPSTOX
    token = UPSTOX.get("access_token", "")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def poll_order_fill(order_id: str, requested_qty: int | None = None) -> dict | None:
    """Poll Upstox ``/v2/order/details`` until the order reaches a terminal
    state or attempts are exhausted. Returns a dict with keys:
        {status, avg_price, filled_qty, requested_qty, complete, partial, raw}
    or None if the status could not be determined. Never raises.

    ``complete`` is True when the whole requested quantity filled (or, when
    ``requested_qty`` is unknown, when the broker reports a filled state).
    ``partial`` is True when 0 < filled_qty < requested_qty.
    """
    if not order_id:
        return None
    headers = _upstox_headers()
    if not headers:
        return None
    from data.upstox.upstox_http import upstox_get
    url = "https://api.upstox.com/v2/order/details"
    last: dict | None = None
    for attempt in range(_ORDER_POLL_ATTEMPTS):
        try:
            resp = upstox_get(url, headers=headers,
                              params={"order_id": order_id}, timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", {}) or {}
                status = str(data.get("status", "")).lower()
                avg_price = float(data.get("average_price") or 0) or None
                filled_qty = int(data.get("filled_quantity") or 0)
                if requested_qty:
                    complete = filled_qty >= requested_qty
                else:
                    complete = status in _FILLED_STATES
                partial = (filled_qty > 0) and not complete
                last = {"status": status, "avg_price": avg_price,
                        "filled_qty": filled_qty, "requested_qty": requested_qty,
                        "complete": complete, "partial": partial, "raw": data}
                # Fully filled → done. Dead → done. Otherwise keep polling for a
                # partial to settle into a terminal state before giving up.
                if complete and avg_price:
                    return last
                if status in _DEAD_STATES:
                    return last
            else:
                print(f"[order] WARN order/details HTTP {resp.status_code}: {resp.text[:150]}")
        except Exception as e:
            print(f"[order] WARN order/details error: {e}")
        if attempt < _ORDER_POLL_ATTEMPTS - 1:
            time.sleep(_ORDER_POLL_DELAY)
    return last


def cancel_upstox_order(order_id: str) -> bool:
    """Cancel an open/partially-filled Upstox order. Returns True on success.
    Used to void the unfilled remainder of a partially-filled order so it does
    not fill later behind the bot's back. Never raises."""
    if not order_id:
        return False
    from config.daemon_config import UPSTOX
    token = UPSTOX.get("access_token", "")
    if not token:
        return False
    url = "https://api.upstox.com/v2/order/cancel"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        # Upstox cancel is DELETE; upstox_http exposes get/post — use requests directly.
        import requests
        resp = requests.delete(url, headers=headers,
                               params={"order_id": order_id}, timeout=15)
        if resp.status_code == 200:
            return True
        print(f"[order] WARN cancel HTTP {resp.status_code}: {resp.text[:150]}")
    except Exception as e:
        print(f"[order] WARN cancel error: {e}")
    return False


def fetch_upstox_funds() -> float | None:
    """Return the broker's available equity margin (₹) or None on failure.
    Used to cross-check the paper portfolio's total cash against reality."""
    headers = _upstox_headers()
    if not headers:
        return None
    from data.upstox.upstox_http import upstox_get
    url = "https://api.upstox.com/v2/user/get-funds-and-margin"
    try:
        resp = upstox_get(url, headers=headers,
                          params={"segment": "SEC"}, timeout=15)
        if resp.status_code != 200:
            # 423 = nightly funds-service maintenance (not an error).
            print(f"[reconcile] funds check unavailable (HTTP {resp.status_code})")
            return None
        data = resp.json().get("data", {}) or {}
        equity = data.get("equity") or data.get("SEC") or {}
        avail = equity.get("available_margin")
        if avail is None:
            return None
        return float(avail)
    except Exception as e:
        print(f"[reconcile] WARN funds fetch error: {e}")
        return None


# ── Write-ahead order log (WAL) for crash resilience ──
# Every real order's INTENT is appended here BEFORE it is placed, and marked
# resolved once the paper position is booked. On startup any unresolved intent
# is reconciled against the broker so a crash between "order placed" and "state
# saved" cannot orphan a position (and its intended SL/TP/strategy survive).
_WAL_PATH = "data/pending_orders.jsonl"


def _wal_record(intent: dict) -> None:
    """Append an order intent to the WAL before placing it. Never raises."""
    if not REAL_ORDERS:
        return
    try:
        rec = dict(intent)
        rec["_wal_ts"] = pd.Timestamp.now(tz="Asia/Kolkata").isoformat()
        rec["_wal_status"] = "placed"
        with open(_WAL_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"[wal] WARN could not record intent: {e}")


def _wal_resolve(wal_id: str) -> None:
    """Mark a WAL intent resolved (position booked / order finalised)."""
    if not REAL_ORDERS or not wal_id:
        return
    try:
        with open(_WAL_PATH, "a") as f:
            f.write(json.dumps({"_wal_id": wal_id, "_wal_status": "resolved",
                                "_wal_ts": pd.Timestamp.now(tz="Asia/Kolkata").isoformat()}) + "\n")
    except Exception as e:
        print(f"[wal] WARN could not resolve {wal_id}: {e}")


def _wal_pending() -> dict:
    """Return unresolved WAL intents keyed by instrument_key (latest wins)."""
    import os as _os
    if not _os.path.exists(_WAL_PATH):
        return {}
    placed: dict = {}
    resolved: set = set()
    try:
        with open(_WAL_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("_wal_status") == "resolved":
                    resolved.add(rec.get("_wal_id"))
                elif rec.get("_wal_status") == "placed":
                    placed[rec.get("_wal_id")] = rec
    except Exception as e:
        print(f"[wal] WARN could not read log: {e}")
        return {}
    out = {}
    for wid, rec in placed.items():
        if wid in resolved:
            continue
        ikey = rec.get("instrument_key")
        if ikey:
            out[ikey] = rec
    return out


def _wal_reset() -> None:
    """Truncate the WAL (all intents resolved). Called after startup recovery."""
    import os as _os
    try:
        if _os.path.exists(_WAL_PATH):
            _os.remove(_WAL_PATH)
    except Exception as e:
        print(f"[wal] WARN could not reset log: {e}")


def fetch_upstox_positions() -> dict | None:
    """Fetch open intraday/short-term positions from Upstox.

    Returns a dict keyed by instrument_key ->
        {qty (signed), avg_price, direction, raw}
    or None if the call failed (so callers can distinguish "no positions"
    (empty dict) from "couldn't reach broker" (None)). Never raises.
    """
    headers = _upstox_headers()
    if not headers:
        return None
    from data.upstox.upstox_http import upstox_get
    url = "https://api.upstox.com/v2/portfolio/short-term-positions"
    try:
        resp = upstox_get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"[reconcile] WARN positions HTTP {resp.status_code}: {resp.text[:150]}")
            return None
        rows = resp.json().get("data", []) or []
    except Exception as e:
        print(f"[reconcile] WARN positions fetch error: {e}")
        return None
    out: dict = {}
    for r in rows:
        ikey = r.get("instrument_token") or r.get("instrument_key")
        if not ikey:
            continue
        qty = int(r.get("quantity") or 0)
        if qty == 0:
            continue  # net-flat; not an open position
        # buy_price/average_price differ across Upstox payloads; prefer average.
        avg_price = float(r.get("average_price") or r.get("buy_price")
                          or r.get("last_price") or 0) or None
        out[ikey] = {
            "qty": qty,
            "avg_price": avg_price,
            "direction": "LONG" if qty > 0 else "SHORT",
            "raw": r,
        }
    return out


def _adopt_broker_position(state: dict, ikey: str, bpos: dict, now, wal: dict) -> bool:
    """Adopt a broker position the paper state doesn't know about. Uses the WAL
    intent (if present) to recover the intended strategy / SL / TP / mode;
    otherwise assigns it to the strategy with the most free cash and applies a
    protective default SL/TP so the position is still risk-managed. Returns True
    if adopted."""
    intent = wal.get(ikey) or {}
    symbol = intent.get("symbol") or _symbol_for_instrument_key(ikey)
    if not symbol:
        print(f"[reconcile] WARN cannot resolve symbol for {ikey} — NOT adopted "
              f"(qty={bpos['qty']} @₹{bpos['avg_price']}); verify manually")
        return False
    direction = bpos["direction"]
    entry_px = round(float(bpos["avg_price"] or intent.get("entry_price") or 0), 2)
    qty = abs(int(bpos["qty"]))
    if entry_px <= 0 or qty < 1:
        return False
    # Attribution: WAL intent's strategy, else the strategy with most free cash.
    strat_name = intent.get("strategy")
    if strat_name not in state.get("strategies", {}):
        strat_name = max(state.get("strategies", {}).items(),
                         key=lambda kv: kv[1].get("cash", 0),
                         default=(active_strategies[0], {}))[0]
    mode = intent.get("mode", "swing")
    # SL/TP: WAL intent if present, else protective defaults (±5% / ±10%).
    if intent.get("stop_loss") and intent.get("take_profit"):
        sl = round(float(intent["stop_loss"]), 2)
        tp = round(float(intent["take_profit"]), 2)
    elif direction == "LONG":
        sl, tp = round(entry_px * 0.95, 2), round(entry_px * 1.10, 2)
    else:
        sl, tp = round(entry_px * 1.05, 2), round(entry_px * 0.90, 2)
    pos = {
        "symbol": symbol, "direction": direction, "strategy": strat_name,
        "entry_price": entry_px, "stop_loss": sl, "take_profit": tp,
        "shares": qty, "opened_at": intent.get("_wal_ts", now.strftime("%Y-%m-%d %H:%M"))[:16].replace("T", " "),
        "score": intent.get("score", 0), "mode": mode, "adopted": True,
    }
    sstate = state["strategies"].setdefault(strat_name, {"cash": 0, "positions": [], "day_entries": 0})
    if direction == "LONG":
        sstate["cash"] = sstate.get("cash", 0) - qty * entry_px
    sstate.setdefault("positions", []).append(pos)
    src = "WAL intent" if intent else "protective default SL/TP"
    print(f"[reconcile] ADOPTED {symbol:10s} {direction:5s} qty={qty} @₹{entry_px:.2f} "
          f"→ [{strat_name}] ({src}, SL ₹{sl:.2f} / TP ₹{tp:.2f})")
    return True


def reconcile_state_with_broker(state: dict, periodic: bool = False) -> None:
    """Align paper positions with Upstox's actual open positions. Only runs when
    REAL_ORDERS. Mutates ``state`` in place.

    Startup mode (``periodic=False``):
    - Paper position not open at broker  → book a reconcile exit + remove it.
    - Broker position not in paper state → adopt it (WAL-informed attribution).
    - Matching positions → correct entry_price + shares to the broker's values.
    - Cross-check total paper cash vs broker available margin.

    Periodic mode (``periodic=True``, mid-day): CONSERVATIVE — never auto-closes
    a paper position (avoids the race where a just-opened position hasn't settled
    into short-term-positions yet). Only fixes prices/shares, adopts unknowns,
    and cash-checks.
    """
    broker = fetch_upstox_positions()
    if broker is None:
        print("[reconcile] SKIP — could not fetch broker positions (market closed / API down)")
        return

    now = pd.Timestamp.now(tz="Asia/Kolkata")
    wal = _wal_pending()
    matched_keys: set = set()
    corrections = 0

    for sname, sstate in state.get("strategies", {}).items():
        for p in list(sstate.get("positions", [])):
            ikey = _instrument_key_for(p["symbol"])
            bpos = broker.get(ikey)
            if bpos is None:
                if periodic:
                    # Don't close mid-day (settlement race). Just note it.
                    continue
                # Startup: broker no longer holds this → closed (auto-square/manual).
                last_px = _upstox_live_price(p["symbol"]) or p["entry_price"]
                if p["direction"] == "LONG":
                    result = "WIN" if (last_px - p["entry_price"]) >= 0 else "LOSS"
                else:
                    result = "WIN" if (p["entry_price"] - last_px) >= 0 else "LOSS"
                p["strategy"] = sname
                _record_exit(state, p, last_px, now, result, "RECONCILE-CLOSED", place_order=False)
                sstate["positions"].remove(p)
                corrections += 1
                print(f"[reconcile] {p['symbol']:10s} {p['direction']:5s} [{sname}] "
                      f"— not open at broker → removed phantom (exit ₹{last_px:.2f})")
            else:
                matched_keys.add(ikey)
                if bpos["avg_price"] and abs(bpos["avg_price"] - p["entry_price"]) > 0.01:
                    old = p["entry_price"]
                    p["entry_price"] = round(bpos["avg_price"], 2)
                    corrections += 1
                    print(f"[reconcile] {p['symbol']:10s} {p['direction']:5s} [{sname}] "
                          f"— entry price fixed ₹{old:.2f} → ₹{p['entry_price']:.2f}")
                bqty = abs(int(bpos["qty"]))
                if bqty and bqty != int(p.get("shares", 0)):
                    old_sh = int(p.get("shares", 0))
                    p["shares"] = bqty
                    corrections += 1
                    print(f"[reconcile] {p['symbol']:10s} {p['direction']:5s} [{sname}] "
                          f"— shares fixed {old_sh} → {bqty} (broker qty)")

    # Broker positions the paper state doesn't know about → adopt them.
    for ikey, bpos in broker.items():
        if ikey not in matched_keys:
            if _adopt_broker_position(state, ikey, bpos, now, wal):
                corrections += 1

    # Cash cross-check (informational; we never blindly overwrite paper cash).
    broker_cash = fetch_upstox_funds()
    if broker_cash is not None:
        paper_cash = sum(s.get("cash", 0) for s in state.get("strategies", {}).values())
        if abs(paper_cash - broker_cash) > _CASH_DIVERGENCE_WARN:
            print(f"[reconcile] ⚠️  CASH DIVERGENCE: paper ₹{paper_cash:,.0f} vs "
                  f"broker available ₹{broker_cash:,.0f} "
                  f"(Δ₹{paper_cash - broker_cash:+,.0f}) — verify (broker margin may "
                  f"include funds outside this bot)")
        else:
            print(f"[reconcile] cash OK — paper ₹{paper_cash:,.0f} ≈ broker ₹{broker_cash:,.0f}")

    # Startup only: WAL fully reconciled → truncate it.
    if not periodic:
        _wal_reset()

    tag = "periodic" if periodic else "startup"
    if corrections == 0:
        print(f"[reconcile:{tag}] OK — paper state matches broker positions")
    else:
        print(f"[reconcile:{tag}] applied {corrections} correction(s)")


# ── sizing (delegates to shared scripts.capital_model.position_size_for) ──


def _init_fresh_state() -> dict:
    """Return a clean multi-strategy state with per-strategy substates."""
    return {
        "day": None,
        "day_entries": 0,
        "trades": [],
        "equity_curve": [{"ts": None, "equity": INITIAL_CAPITAL}],
        "_strategy_allocs": dict(strategy_allocs),
        "strategies": {
            name: {
                "cash": strategy_capitals.get(name, INITIAL_CAPITAL),
                "day_entries": 0,
                "positions": [],
                "peak_equity": strategy_capitals.get(name, INITIAL_CAPITAL),
            }
            for name in active_strategies
        },
    }


def _load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return _init_fresh_state()
    try:
        state = json.load(open(STATE_PATH))
    except (json.JSONDecodeError, ValueError) as e:
        import shutil
        backup = STATE_PATH + ".corrupt"
        try:
            shutil.copy2(STATE_PATH, backup)
        except Exception:
            backup = STATE_PATH
        print(f"[state] WARN corrupt state file ({e}); backed up to {backup}; "
              f"starting fresh")
        return _init_fresh_state()

    # Migrate single-strategy → multi-strategy structure
    if "strategies" not in state:
        _migrate_old_state(state)

    # Prune stale strategies, add missing ones, and redistribute when the
    # allocation config changes (strategies added/removed or alloc % changed).
    existing = state.get("strategies", {})
    missing = [n for n in active_strategies if n not in existing]
    stale  = [n for n in existing if n not in active_strategies]
    prev_allocs = state.get("_strategy_allocs", {})
    curr_allocs = dict(strategy_allocs)
    alloc_changed = (prev_allocs != curr_allocs)

    if missing or stale or alloc_changed:
        # Prune stale strategies (skip those with open positions)
        for name in stale:
            s = existing.get(name, {})
            if s.get("positions"):
                print(f"  [state] SKIP removing stale strategy {name} — "
                      f"{len(s['positions'])} open position(s)")
                continue
            print(f"  [state] removed stale strategy {name} "
                  f"(freed ₹{s.get('cash',0):.2f})")
            del existing[name]

        # Redistribute all cash by alloc ratio
        total_alloc = sum(strategy_allocs.get(n, 0) for n in active_strategies) or 1
        total_cash = sum(s.get("cash", 0) for s in existing.values())

        for name in active_strategies:
            alloc = strategy_allocs.get(name, 0)
            cash = round(total_cash * alloc / total_alloc, 2) if total_alloc else 0
            if name not in existing:
                existing[name] = {
                    "cash": cash,
                    "day_entries": 0,
                    "positions": [],
                    "peak_equity": strategy_capitals.get(name, INITIAL_CAPITAL),
                }
            else:
                existing[name]["cash"] = cash

        state["_strategy_allocs"] = curr_allocs
        print(f"  [state] redistributed ₹{total_cash:.2f} across "
              f"{len(active_strategies)} strategies by alloc ratio")

    # Guard against missing equity_curve
    if "equity_curve" not in state:
        state["equity_curve"] = [{"ts": None, "equity": _equity(state, {})}]
    return state


def _migrate_old_state(state: dict) -> None:
    """Convert old flat single-strategy state to nested multi-strategy format.

    Distributes old total cash across all active strategies per ``--alloc``.
    Old positions are discarded (strategy origin unknown) and the day resets.
    """
    old_cash = state.pop("cash", INITIAL_CAPITAL)
    state.pop("day_entries", None)
    state.pop("positions", None)
    state.pop("peak_equity", None)
    total_alloc = sum(strategy_allocs.get(n, 0) for n in active_strategies)
    state["strategies"] = {
        name: {
            "cash": round(old_cash * strategy_allocs.get(name, 0) / total_alloc, 2)
                    if total_alloc else strategy_capitals.get(name, INITIAL_CAPITAL),
            "day_entries": 0,
            "positions": [],
            "peak_equity": strategy_capitals.get(name, INITIAL_CAPITAL),
        }
        for name in active_strategies
    }
    state["_strategy_allocs"] = dict(strategy_allocs)


def _save_state(state: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _equity(state: dict, prices: dict) -> float:
    eq = 0.0
    for strat in state.get("strategies", {}).values():
        eq += strat["cash"]
        for p in strat.get("positions", []):
            px = prices.get(p["symbol"])
            if px is not None:
                if p["direction"] == "LONG":
                    eq += p["shares"] * px
                else:
                    eq += p["shares"] * (p["entry_price"] - px)
    return eq


# ── Transaction costs (mirror scripts.backtest._compute_costs) ───────────────
# These MUST match the backtest so the paper trader's equity is realistic.
_COSTS_ENABLED = os.environ.get("INST_COSTS", "1") != "0"
_SLIPPAGE_PCT = float(os.environ.get("INST_SLIPPAGE_PCT", "0.05"))       # 0.05 % per side
_BROKERAGE_PER_TRADE = float(os.environ.get("INST_BROKERAGE", "20.0"))   # ₹20 flat / order
_STT_PCT = float(os.environ.get("INST_STT_PCT", "0.025"))                # 0.025 % STT on sell (intraday equity)
_GST_PCT = float(os.environ.get("INST_GST_PCT", "18.0"))                 # 18 % GST on (brokerage + exchange)
_EXCHANGE_FEE_PCT = float(os.environ.get("INST_EXCHANGE_FEE_PCT", "0.0001"))


def _trade_cost(entry_price, exit_price, direction, position_value):
    """Round-trip transaction cost in ₹, matching scripts.backtest._compute_costs."""
    if not _COSTS_ENABLED or position_value <= 0:
        return 0.0
    slippage_entry = position_value * (_SLIPPAGE_PCT / 100.0)
    slippage_exit = position_value * (_SLIPPAGE_PCT / 100.0)
    brokerage = _BROKERAGE_PER_TRADE
    if direction == "LONG":
        stt = exit_price * (position_value / entry_price) * (_STT_PCT / 100.0) if entry_price > 0 else 0
    else:
        stt = entry_price * (position_value / entry_price) * (_STT_PCT / 100.0) if entry_price > 0 else 0
    turnover = position_value * 2
    exchange_fees = turnover * (_EXCHANGE_FEE_PCT / 100.0)
    gst = (brokerage + exchange_fees) * (_GST_PCT / 100.0)
    return slippage_entry + slippage_exit + brokerage + stt + exchange_fees + gst


def _book_partial_exit(state: dict, p: dict, exit_price: float, qty: int,
                       now, result: str, reason: str) -> None:
    """Book the closed portion of a partially-filled exit (``qty`` shares) into
    cash + trade history WITHOUT placing any order (the fill already happened).
    The caller shrinks ``p['shares']`` and keeps the remainder open."""
    strat_name = p.get("strategy", active_strategies[0])
    strat_state = state.setdefault("strategies", {}).setdefault(strat_name, {})
    direction = p["direction"]
    pnl = qty * (exit_price - p["entry_price"]) if direction == "LONG" \
        else qty * (p["entry_price"] - exit_price)
    position_value = qty * p["entry_price"]
    cost = _trade_cost(p["entry_price"], exit_price, direction, position_value)
    net_pnl = pnl - cost
    if direction == "LONG":
        strat_state["cash"] = strat_state.get("cash", 0) + qty * exit_price - cost
    else:
        strat_state["cash"] = strat_state.get("cash", 0) + net_pnl
    risk = abs(p["entry_price"] - p["stop_loss"])
    r_mult = ((exit_price - p["entry_price"]) / risk) if direction == "LONG" \
        else ((p["entry_price"] - exit_price) / risk)
    r_mult = r_mult if risk else 0.0
    fill = {
        "symbol": p["symbol"], "direction": direction, "side": "EXIT",
        "strategy": strat_name,
        "entry_price": round(p["entry_price"], 2), "exit_price": round(exit_price, 2),
        "shares": qty, "pnl": round(net_pnl, 2), "cost": round(cost, 2),
        "r_multiple": round(r_mult, 3), "result": result,
        "ts": now.strftime("%Y-%m-%d %H:%M"), "reason": reason, "partial": True,
    }
    state["trades"].append(fill)
    try:
        from scripts.trade_history import record_trade_exit
        record_trade_exit(p["symbol"], direction, round(exit_price, 2),
                          reason, round(net_pnl, 2), now.strftime("%Y-%m-%d %H:%M"),
                          mode=p.get("mode"), strategy=p.get("strategy"))
    except Exception:
        pass


def _record_exit(state: dict, p: dict, exit_price: float, now, result: str, reason: str,
                 place_order: bool = True) -> dict | None:
    """Close an open position at ``exit_price``; update cash + append a fill.

    When ``place_order`` is True and REAL_ORDERS is set, a real exit order is
    placed and its fill is confirmed. If the broker order fails or does not
    fill, the position is LEFT OPEN (returns None) and marked for retry on the
    next cycle — we never book a paper exit that the broker didn't execute.
    ``place_order=False`` books the paper exit only (used by reconciliation,
    where the broker already closed the position).

    LONG is closed with a SELL (cash returns at exit price); SHORT is closed
    with a BUY (net P&L booked — no cash moved at short open, so the whole
    ``pnl`` lands at exit). The order payload transaction_type follows the
    direction (SELL to close a LONG, BUY to close a SHORT).
    """
    strat_name = p.get("strategy", active_strategies[0])
    strat_state = state.setdefault("strategies", {}).setdefault(strat_name, {})

    direction = p["direction"]
    close_txn = "BUY" if direction == "SHORT" else "SELL"
    exit_order = _order_payload(p["symbol"], close_txn, p["shares"],
                                round(exit_price, 2), None, None,
                                mode=p.get("mode", "intraday"))

    # ── Real exit order (only with --real, and not a reconcile close) ──
    # Place + confirm the fill BEFORE booking the paper exit. If the broker
    # order fails or doesn't fill, leave the position OPEN and mark it for a
    # retry next cycle — never book an exit the broker didn't execute.
    if REAL_ORDERS and place_order:
        oid = place_upstox_order(exit_order)
        if not oid:
            p["exit_retry"] = int(p.get("exit_retry", 0)) + 1
            print(f"[order] WARN real EXIT order REJECTED for {p['symbol']} "
                  f"({direction}) — position kept OPEN, retry #{p['exit_retry']} next cycle")
            return None
        exit_order["order_id"] = oid
        fillinfo = poll_order_fill(oid, requested_qty=p["shares"])
        filled = int(fillinfo.get("filled_qty") or 0) if fillinfo else 0
        if fillinfo is None or fillinfo.get("status") in _DEAD_STATES \
                or not fillinfo.get("avg_price") or filled < 1:
            p["exit_retry"] = int(p.get("exit_retry", 0)) + 1
            status = fillinfo.get("status") if fillinfo else "unknown"
            print(f"[order] WARN real EXIT not confirmed for {p['symbol']} "
                  f"(status={status} filled={filled}) — position kept OPEN, "
                  f"retry #{p['exit_retry']} next cycle")
            return None
        # Use the broker's actual fill price for honest paper P&L.
        exit_price = round(float(fillinfo["avg_price"]), 2)
        exit_order["fill_price"] = exit_price
        # ── Partial exit: only part of the position closed. Book the closed
        # portion, shrink the position in place, cancel the remainder, and
        # return None so the caller KEEPS the (now smaller) position open to
        # close the rest next cycle. ──
        if fillinfo.get("partial") and filled < p["shares"]:
            if cancel_upstox_order(oid):
                print(f"[order] partial EXIT {p['symbol']} closed {filled}/{p['shares']} "
                      f"— remainder cancelled, {p['shares']-filled} kept open")
            else:
                print(f"[order] partial EXIT {p['symbol']} closed {filled}/{p['shares']} "
                      f"— WARN remainder NOT cancelled")
            _book_partial_exit(state, p, exit_price, filled, now, result, reason + "-PARTIAL")
            p["shares"] -= filled
            p["exit_retry"] = int(p.get("exit_retry", 0)) + 1
            return None
        p.pop("exit_retry", None)

    pnl = p["shares"] * (exit_price - p["entry_price"]) if direction == "LONG" \
        else p["shares"] * (p["entry_price"] - exit_price)
    risk = abs(p["entry_price"] - p["stop_loss"])
    r_mult = (abs(exit_price - p["entry_price"]) / risk) if result == "WIN" else -1.0
    position_value = p["shares"] * p["entry_price"]
    cost = _trade_cost(p["entry_price"], exit_price, direction, position_value)
    net_pnl = pnl - cost
    if direction == "LONG":
        strat_state["cash"] = strat_state.get("cash", 0) + p["shares"] * exit_price - cost
    else:
        strat_state["cash"] = strat_state.get("cash", 0) + net_pnl
    exit_order["price"] = round(exit_price, 2)
    fill = {
        "symbol": p["symbol"], "direction": direction, "side": "EXIT",
        "strategy": strat_name,
        "entry_price": round(p["entry_price"], 2), "exit_price": round(exit_price, 2),
        "shares": p["shares"], "pnl": round(net_pnl, 2), "cost": round(cost, 2),
        "r_multiple": round(r_mult, 3), "result": result,
        "ts": now.strftime("%Y-%m-%d %H:%M"), "reason": reason,
        "order": exit_order,
    }
    state["trades"].append(fill)
    from scripts.trade_history import record_trade_exit
    record_trade_exit(p["symbol"], direction, round(exit_price, 2),
                      reason, round(net_pnl, 2), now.strftime("%Y-%m-%d %H:%M"),
                      mode=p.get("mode"), strategy=p.get("strategy"))
    _notify_exit(fill)
    return fill


def _check_bar_exit(bar_ohlc, stop_loss, take_profit, direction, opened_at=None):
    """Check the last completed bar's OHLC for SL/TP triggers.
    Mirrors backtest._check_exit logic: a touch of the stop or target during
    the bar is considered a fill at that level.

    ``opened_at`` (position open timestamp, "YYYY-MM-DD HH:MM") guards against
    STALE bars: if the completed bar closed at/before the position opened, its
    range predates the trade and must NOT trigger an exit. This prevents the
    Upstox-REST bug where today's intraday bars aren't served yet, so
    ``bar_ohlc`` holds yesterday's last bar (whose low/high can falsely hit the
    SL/TP). When the bar is stale we return None so the caller falls back to the
    live price check.
    """
    if bar_ohlc is None:
        return None
    bar_ts = bar_ohlc.get("ts")
    if opened_at and bar_ts and str(bar_ts)[:16] <= str(opened_at)[:16]:
        return None  # bar predates the position → stale, ignore
    high, low = bar_ohlc["high"], bar_ohlc["low"]
    if direction == "LONG":
        if low <= stop_loss:
            return stop_loss, "LOSS"
        if high >= take_profit:
            return take_profit, "WIN"
    else:
        if high >= stop_loss:
            return stop_loss, "LOSS"
        if low <= take_profit:
            return take_profit, "WIN"
    return None


def _build_symbol_context(sym: str, nifty_15m, nifty_1d, now, live_price=None,
                          banknifty_15m=None, vix_1d=None):
    """Fetch + pre-analyze one symbol once. Returns a context dict (or None on
    fetch failure) with everything ``decide_trade`` needs so it can be run for
    BOTH intraday and swing modes without re-fetching data."""
    yf_sym = f"{sym}.NS"
    try:
        if USE_UPSTOX:
            stock_15m = _upstox_live(sym, TF)
            stock_1m = _upstox_live(sym, "1m")   # recent 1m candles for entry timing
        else:
            stock_15m = _yf_live(yf_sym, TF)
            stock_1m = None                         # yfinance 1m unreliable → gate off
        if stock_15m is None or len(stock_15m) < WINDOW_SIZE + 5:
            return None
        if USE_UPSTOX:
            stock_1d = _upstox_live(sym, "1d")
        else:
            stock_1d = _yf_live(yf_sym, "1d")
        stock_30m = _resample_safe(stock_15m, 30)
    except Exception:
        return None

    last_ts = stock_15m["timestamp"].iloc[-1]
    today = last_ts.date() if hasattr(last_ts, "date") else last_ts
    entry_date = last_ts  # entry-bar timestamp (also used for calendar conviction)
    current_price = live_price if live_price is not None else float(stock_15m["close"].iloc[-1])

    window = stock_15m.tail(WINDOW_SIZE).reset_index(drop=True)
    nifty_win = nifty_15m.tail(WINDOW_SIZE).reset_index(drop=True) if nifty_15m is not None else None
    if nifty_win is None or len(nifty_win) < WINDOW_SIZE:
        nifty_win = window

    day_info = classify_today_day_type(upstox=USE_UPSTOX)
    day_type = day_info.get("day_type", "UNKNOWN")
    stock_type = _classify_stock_type(window, nifty_win, stock_1d, today)
    htf_ctx = build_htf_context(stock_30m, stock_1d, last_ts)
    bar_ohlc = None
    if len(stock_15m) >= 2:
        bar_ohlc = {
            "high": float(stock_15m["high"].iloc[-2]),
            "low": float(stock_15m["low"].iloc[-2]),
            # Timestamp of the last COMPLETED bar. Used by the exit loop to
            # reject stale bars (e.g. Upstox REST returns yesterday's bars when
            # today's intraday data isn't yet served) — a bar that closed BEFORE
            # a position opened must never trigger that position's SL/TP.
            "ts": str(stock_15m["timestamp"].iloc[-2]),
        }
    return {
        "sym": sym, "yf_sym": yf_sym, "window": window, "stock_30m": stock_30m,
        "stock_1d": stock_1d, "nifty_15m": nifty_15m, "last_ts": last_ts,
        "today": today, "entry_date": entry_date, "current_price": current_price,
        "nifty_win": nifty_win, "day_type": day_type, "stock_type": stock_type,
        "htf_ctx": htf_ctx, "bar_ohlc": bar_ohlc,
        "banknifty_15m": banknifty_15m, "vix_1d": vix_1d,
        "stock_1m": stock_1m, "nifty_1d": nifty_1d,
    }


def _decide_trade_for_mode(ctx: dict, intraday: bool):
    """Run ``decide_trade`` inside a pre-built symbol context for one mode."""
    intraday_remaining = _bars_until_close(ctx["last_ts"]) if intraday else None
    # ML Standalone builds its own 30m/1d + NIFTY context and legitimately takes
    # counter-trend entries (SHORT in an uptrend, etc.), so the HTF alignment
    # filter must be OFF for it (Phase 31 ran backtests with --no-multi-tf).
    multi_tf = PAPER_STRATEGY != "ML Standalone"
    return decide_trade(
        ctx["window"], ctx["yf_sym"], TF,
        ctx["day_type"], ctx["stock_type"],
        ctx["nifty_15m"], ctx["stock_1d"], ctx["stock_30m"], ctx["last_ts"],
        nifty_daily=ctx.get("nifty_1d"),
        banknifty_df=ctx["banknifty_15m"],
        vix_daily=ctx["vix_1d"],
        force_strategy=PAPER_STRATEGY,
        tuning_override=PAPER_TUNING,
        tuning_override_is_default=True,
        multi_tf_filter=multi_tf,
        intraday_mode=intraday,
        intraday_remaining_bars=intraday_remaining,
        htf_ctx=ctx["htf_ctx"],
        original_symbol=ctx["sym"],
    )


def _evaluate_symbol(sym: str, nifty_15m, nifty_1d, now, live_price=None,
                     banknifty_15m=None, vix_1d=None, intraday=True):
    """Fetch live data for one symbol, return (decision_or_None, current_price).

    Uses the Upstox feed when ``USE_UPSTOX`` is set, else yfinance. ``live_price``
    (when given) overrides the last-bar close as the current price for exit checks.
    ``intraday`` controls whether the last-bar filter is applied (False for swing).
    """
    ctx = _build_symbol_context(sym, nifty_15m, nifty_1d, now, live_price,
                                banknifty_15m, vix_1d)
    if ctx is None:
        return None, None
    decision = _decide_trade_for_mode(ctx, intraday)
    return decision, ctx["current_price"], ctx["entry_date"], ctx["bar_ohlc"]


# ── Daily Trend Breakout (Phase 37) ──────────────────────────────────────────
# The daily strategy runs on native 1d bars with a trailing ATR stop (no fixed
# TP). It is evaluated in a once-per-day morning pass: the SIGNAL is computed on
# the last COMPLETED daily bar (today's in-progress bar excluded, PIT), and the
# entry is booked that morning (next-day-open semantics). Trailing exits use a
# close-based ATR chandelier replayed from the entry bar — an exact live mirror
# of WalkForwardBacktest._check_exit's trailing branch.
_DAILY_WINDOW = 250   # matches WalkForwardBacktest.window_size for 1d


def _build_daily_context(sym: str, nifty_1d, now, live_price=None):
    """Build a point-in-time daily context for one symbol, or None.

    ``window`` holds the last _DAILY_WINDOW COMPLETED daily bars (today's
    in-progress bar excluded) so the breakout signal never peeks at an unfinished
    day. ``current_price`` is the live/last price used as the entry fill.
    """
    yf_sym = f"{sym}.NS"
    try:
        stock_1d = _upstox_live(sym, "1d") if USE_UPSTOX else _yf_live(yf_sym, "1d")
    except Exception:
        return None
    if stock_1d is None or len(stock_1d) < 5:
        return None
    stock_1d = stock_1d.copy()
    stock_1d["timestamp"] = pd.to_datetime(stock_1d["timestamp"])
    today = now.date()
    completed = stock_1d[stock_1d["timestamp"].dt.date < today].reset_index(drop=True)
    if len(completed) < _DAILY_WINDOW + 5:
        return None
    last_ts = completed["timestamp"].iloc[-1]
    # Entry fill: live tick if available, else the current (possibly in-progress)
    # bar close, else yesterday's completed close.
    if live_price is not None:
        current_price = float(live_price)
    else:
        current_price = float(stock_1d["close"].iloc[-1])
    window = completed.tail(_DAILY_WINDOW).reset_index(drop=True)

    # Precompute ATR(14) for this symbol's daily bars so the entry branch can
    # recalculate the stop_loss from the live entry price.
    import numpy as np
    h = completed["high"].to_numpy(dtype=float)
    l = completed["low"].to_numpy(dtype=float)
    c = completed["close"].to_numpy(dtype=float)
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr_series = pd.Series(tr).rolling(14).mean()
    atr_14 = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0.0

    return {
        "sym": sym, "yf_sym": yf_sym, "window": window,
        "stock_1d": completed, "last_ts": last_ts, "today": today,
        "current_price": current_price, "nifty_1d": nifty_1d,
        "atr_14": atr_14,
    }


def _decide_daily(ctx: dict):
    """Run decide_trade for the Daily Trend Breakout strategy on a daily context.

    multi_tf_filter is OFF (the breakout is already SMA50>SMA200 trend-aligned;
    the full backtest ran with --no-multi-tf), intraday_mode is OFF.
    """
    return decide_trade(
        ctx["window"], ctx["yf_sym"], "1d",
        "", "",
        None, ctx["stock_1d"], None, ctx["last_ts"],
        nifty_daily=ctx.get("nifty_1d"),
        force_strategy=PAPER_STRATEGY,
        tuning_override=PAPER_TUNING,
        tuning_override_is_default=True,
        multi_tf_filter=False,
        intraday_mode=False,
        original_symbol=ctx["sym"],
    )


def _daily_trailing_exit(stock_1d, signal_date: str, entry_price: float,
                         initial_stop: float, trail_atr_mult: float,
                         max_hold_bars: int):
    """Replay the close-based ATR chandelier over completed daily bars since entry.

    ``stock_1d`` = completed daily bars (today excluded). ``signal_date`` = the
    date of the signal (entry) bar. Returns:
      {"exit": True,  "reason": "TRAIL"|"MAX-HOLD", "result": "WIN"|"LOSS"}  or
      {"exit": False, "stop": <current trail stop>, "bars_held": n}          or
      None if the entry bar can't be located / not enough data.

    Mirrors WalkForwardBacktest._check_exit's trailing branch exactly (hwm and
    trigger both on the CLOSE; stop ratchets up monotonically from initial_stop).
    """
    import numpy as np
    d = stock_1d.reset_index(drop=True)
    if len(d) < 2:
        return None
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    h = d["high"].to_numpy(dtype=float)
    l = d["low"].to_numpy(dtype=float)
    c = d["close"].to_numpy(dtype=float)
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = pd.Series(tr).rolling(14).mean().to_numpy()
    atr_trail = np.concatenate([[np.nan], atr])

    sig = pd.to_datetime(signal_date).date()
    dates = d["timestamp"].dt.date
    matches = d.index[dates == sig]
    if len(matches):
        entry_idx = int(matches[-1])
    else:
        earlier = d.index[dates <= sig]
        if len(earlier) == 0:
            return None
        entry_idx = int(earlier[-1])

    last_idx = len(d) - 1
    hwm = entry_price
    stop = initial_stop
    for j in range(entry_idx + 1, min(last_idx + 1, entry_idx + max_hold_bars + 1)):
        close = c[j]
        atr_j = atr_trail[j]
        atr_j = float(atr_j) if atr_j == atr_j else 0.0  # NaN guard
        if close > hwm:
            hwm = close
        if atr_j > 0:
            stop = max(stop, hwm - trail_atr_mult * atr_j)
        if close <= stop:
            return {"exit": True, "reason": "TRAIL",
                    "result": "WIN" if close > entry_price else "LOSS"}
    bars_held = last_idx - entry_idx
    if bars_held >= max_hold_bars:
        last_close = c[last_idx]
        return {"exit": True, "reason": "MAX-HOLD",
                "result": "WIN" if last_close > entry_price else "LOSS"}
    return {"exit": False, "stop": round(stop, 2), "bars_held": bars_held}


def _resample_safe(df, minutes):
    from scripts.backtest import _resample_1m_to
    try:
        return _resample_1m_to(df, minutes)
    except Exception:
        return None


# ── ML Opening Breakout (Phase D) ──────────────────────────────────────────
# 5m opening-minutes ML strategy (09:15-10:30 IST). XGBoost scores BOTH a LONG
# and SHORT entry from raw opening structure; takes whichever clears thr 0.70.
# Fixed SL 0.3% / TP 1.5% / max hold 48 bars. Symmetric by design (like ML
# Standalone) — bypasses the ML filter, day-of-week gate, confirmation gate and
# HTF alignment filter; the model's own features already encode timing/regime.
_OPEN_WINDOW = (9.25, 10.5)  # 09:15 → 10:30 IST


def _is_orb_strategy(strat_name: str) -> bool:
    return strat_name == "ML Opening Breakout"


def _build_5m_opening_context(sym: str, nifty_5m, nifty_1d, now, live_price=None):
    """Build a 5m opening-window context for one symbol, or None.

    Fetches native 5m bars (the model was trained on 5m resampled-from-1m),
    excludes today's in-progress bar so the signal uses only completed bars.
    """
    yf_sym = f"{sym}.NS"
    try:
        stock_5m = _upstox_live(sym, "5m") if USE_UPSTOX else _yf_live(yf_sym, "5m")
    except Exception:
        return None
    if stock_5m is None or len(stock_5m) < 130:
        return None
    stock_5m = stock_5m.copy()
    stock_5m["timestamp"] = pd.to_datetime(stock_5m["timestamp"])
    today = now.date()
    completed = stock_5m[stock_5m["timestamp"].dt.date < today].reset_index(drop=True)
    if len(completed) < 130:
        return None
    last_ts = completed["timestamp"].iloc[-1]
    window = completed.tail(130).reset_index(drop=True)
    if live_price is not None:
        current_price = float(live_price)
    else:
        current_price = float(completed["close"].iloc[-1])
    return {
        "sym": sym, "yf_sym": yf_sym, "window": window,
        "nifty_df": nifty_5m, "nifty_daily": nifty_1d,
        "last_ts": last_ts, "today": today, "current_price": current_price,
    }


def _decide_5m_opening(ctx: dict):
    """Run the ML Opening Breakout strategy on a 5m opening context.

    Instantiates the strategy directly (bypassing decide_trade's generic path)
    and returns its StrategyResult. The strategy scores the latest completed
    5m bar inside 09:15-10:30 and returns a TradeCandidate if proba >= thr.
    """
    from strategies.orb_ml_strategy import MLOpeningBreakoutStrategy
    strategy = MLOpeningBreakoutStrategy()
    return strategy.run(ctx["window"], ctx["sym"], "5m",
                        nifty_df=ctx.get("nifty_df"),
                        nifty_daily=ctx.get("nifty_daily"))


def _strategy_equity(state: dict, strat_name: str, prices: dict) -> float:
    strat = state["strategies"][strat_name]
    eq = strat["cash"]
    for p in strat.get("positions", []):
        px = prices.get(p["symbol"])
        if px is not None:
            if p["direction"] == "LONG":
                eq += p["shares"] * px
            else:
                eq += p["shares"] * (p["entry_price"] - px)
    return eq


def _is_golden_window(now: pd.Timestamp) -> str | None:
    """Return 'morning', 'evening', or None based on the current time."""
    hour = now.hour + now.minute / 60.0
    if 9.75 <= hour <= 10.5:     # 09:45 to 10:30 inclusive (matches strategy)
        return "morning"
    if 13.5 <= hour <= 14.5:     # 13:30 to 14:30 inclusive (matches strategy)
        return "evening"
    return None


def run_cycle(state: dict, symbols: list[str],
              strategy_symbols: dict[str, list[str]] | None = None) -> dict:
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    now_date = now.strftime("%Y-%m-%d")

    # reset daily entry counter on a new day
    if state.get("day") != now_date:
        prev_day = state.get("day")
        if prev_day:
            try:
                from scripts.export_trades import export_day
                data = json.load(open("data/trade_history.json"))
                export_day(prev_day, data)
            except Exception as e:
                print(f"  [export] failed to export {prev_day}: {e}")
        state["day"] = now_date
        for s in state.get("strategies", {}).values():
            s["day_entries"] = 0
        COOLDOWNS.clear()
        LAST_ENTRY_BAR.clear()

    total_cash = sum(s.get("cash", 0) for s in state.get("strategies", {}).values())
    total_open = sum(len(s.get("positions", [])) for s in state.get("strategies", {}).values())
    total_day_entries = sum(s.get("day_entries", 0) for s in state.get("strategies", {}).values())

    print("=" * 70)
    print(f"  PAPER TRADING CYCLE — {now.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"  Strategies: {', '.join(active_strategies)}")
    print(f"  Cash: ₹{total_cash:,.0f} | Day entries: {total_day_entries}"
          f"/{MAX_TRADES_PER_DAY*len(active_strategies)} | "
          f"Open: {total_open}")
    print("=" * 70)

    # ── periodic mid-day reconciliation (conservative) ──
    global _CYCLE_COUNTER
    _CYCLE_COUNTER += 1
    if (REAL_ORDERS and _RECONCILE_EVERY_N_CYCLES > 0
            and _CYCLE_COUNTER % _RECONCILE_EVERY_N_CYCLES == 0):
        print(f"  [reconcile] periodic check (cycle #{_CYCLE_COUNTER})")
        try:
            reconcile_state_with_broker(state, periodic=True)
        except Exception as e:
            print(f"  [reconcile] periodic error: {e}")

    nifty_15m = _upstox_live("^NSEI", TF) if USE_UPSTOX else _yf_live("^NSEI", TF)
    nifty_1d = _upstox_live("^NSEI", "1d") if USE_UPSTOX else _yf_live("^NSEI", "1d")
    banknifty_15m = _upstox_live("^NSEBANK", TF) if USE_UPSTOX else _yf_live("^NSEBANK", TF)
    vix_1d = _upstox_live("^INDIAVIX", "1d") if USE_UPSTOX else _yf_live("^INDIAVIX", "1d")
    nifty_5m = _upstox_live("^NSEI", "5m") if USE_UPSTOX else _yf_live("^NSEI", "5m")

    prices = {}
    new_fills = []

    # Once-per-day daily pass (Daily Trend Breakout): trailing-exit checks + new
    # daily entries run only in the morning window, and only once per day.
    hour_min_now = now.hour + now.minute / 60.0
    has_daily = any(_is_daily_strategy(s) for s in active_strategies)
    in_daily_window = _DAILY_ENTRY_WINDOW[0] <= hour_min_now < _DAILY_ENTRY_WINDOW[1]
    do_daily_pass = (has_daily and in_daily_window
                     and state.get("daily_pass_date") != now_date)

    # Opening-window gate for the 5m ML Opening Breakout strategy: it only
    # evaluates (and may enter) during 09:15-10:30 IST. Unlike the daily pass it
    # is NOT once-per-day — it runs every cycle inside the window so it can catch
    # the model's signal on whichever 5m bar clears the threshold.
    has_orb = any(_is_orb_strategy(s) for s in active_strategies)
    in_opening_window = _OPEN_WINDOW[0] <= hour_min_now < _OPEN_WINDOW[1]

    # ── 0) intraday EOD force-close (swing positions carry over) ──
    # With --real, intraday positions (product="I") are auto-squared by Upstox
    # at 15:30. Fetch the broker's live positions once so we don't try to place
    # a second exit order for something already closed (which would open a NEW
    # opposite position). If broker no longer holds it → book the paper exit
    # WITHOUT placing an order.
    eod_broker = fetch_upstox_positions() if REAL_ORDERS else None
    for sname, sstate in state.get("strategies", {}).items():
        for p in list(sstate.get("positions", [])):
            if p.get("mode") in ("swing", "daily"):
                continue  # swing + daily positions hold overnight / multi-day
            opened_date = (p.get("opened_at") or "")[:10]
            if opened_date and opened_date != now_date:
                live_price = _upstox_live_price(p["symbol"]) if USE_UPSTOX else None
                _, cur, _, _ = _evaluate_symbol(p["symbol"], nifty_15m, nifty_1d, now, live_price=live_price,
                                                banknifty_15m=banknifty_15m, vix_1d=vix_1d)
                exit_price = cur if cur is not None else p["entry_price"]
                if p["direction"] == "LONG":
                    result = "WIN" if (exit_price - p["entry_price"]) >= 0 else "LOSS"
                else:
                    result = "WIN" if (p["entry_price"] - exit_price) >= 0 else "LOSS"
                p["strategy"] = sname
                # If the broker already auto-squared it, book the paper exit only
                # (no new order). Otherwise place a real exit order.
                broker_has = (eod_broker is not None
                              and _instrument_key_for(p["symbol"]) in eod_broker)
                place = not (REAL_ORDERS and eod_broker is not None and not broker_has)
                reason = "EOD-FORCE-CLOSE" if place else "EOD-AUTOSQUARE"
                fill = _record_exit(state, p, exit_price, now, result, reason,
                                    place_order=place)
                if fill is None:
                    continue  # real exit failed → keep position, retry next cycle
                sstate["positions"].remove(p)
                new_fills.append(fill)
                print(f"  {reason:16s} {p['symbol']:10s} close @₹{fill['exit_price']:.2f}  "
                      f"PnL=₹{fill['pnl']:+,.0f}  R={fill['r_multiple']:+.2f}  "
                      f"(opened {opened_date}) [{sname}]")

    # ── 1) manage open positions (exit checks) ──
    for sname, sstate in state.get("strategies", {}).items():
        still_open = []
        for p in sstate.get("positions", []):
            p["strategy"] = sname
            sym = p["symbol"]
            if p.get("mode") == "daily" or p.get("trail_atr_mult", 0):
                still_open.append(p)  # daily trailing positions → managed in the daily pass
                continue
            if p.get("exit_order_id"):
                still_open.append(p)
                continue
            live_price = _upstox_live_price(sym) if USE_UPSTOX else None
            _, cur, _, bar_ohlc = _evaluate_symbol(sym, nifty_15m, nifty_1d, now, live_price=live_price,
                                                    banknifty_15m=banknifty_15m, vix_1d=vix_1d)
            if cur is None:
                still_open.append(p)
                continue
            prices[sym] = cur
            # Trust the price-based SL/TP trigger only when we have a real live
            # tick. On Upstox, `cur` falls back to the last (stale) bar close
            # when the WebSocket is down — using that for SL/TP would misfire
            # (same class of bug as the stale bar_ohlc). yfinance mode has no
            # live feed, so its bar close IS the intended price source.
            live_ok = (live_price is not None) if USE_UPSTOX else True
            exit_price = None
            result = None
            if p["direction"] == "LONG":
                exit_price, result = _check_bar_exit(
                    bar_ohlc, p["stop_loss"], p["take_profit"], "LONG",
                    opened_at=p.get("opened_at"),
                ) or (None, None)
                if exit_price is None and live_ok and cur <= p["stop_loss"]:
                    exit_price, result = p["stop_loss"], "LOSS"
                elif exit_price is None and live_ok and cur >= p["take_profit"]:
                    exit_price, result = p["take_profit"], "WIN"
            else:
                exit_price, result = _check_bar_exit(
                    bar_ohlc, p["stop_loss"], p["take_profit"], "SHORT",
                    opened_at=p.get("opened_at"),
                ) or (None, None)
                if exit_price is None and live_ok and cur >= p["stop_loss"]:
                    exit_price, result = p["stop_loss"], "LOSS"
                elif exit_price is None and live_ok and cur <= p["take_profit"]:
                    exit_price, result = p["take_profit"], "WIN"
            # Max-hold time stop (5m opening strategy): the model was trained
            # with a 48-bar (4h) hold cap. Exit at the current price once the
            # position has been open >= max_hold_bars 5m bars. (Intraday EOD
            # force-close at 15:30 is the ultimate backstop.)
            if exit_price is None and p.get("max_hold_bars"):
                _opened = pd.Timestamp(p.get("opened_at")) if p.get("opened_at") else None
                if _opened is not None:
                    bars_held = (now - _opened).total_seconds() / 300.0  # 5m bars
                    if bars_held >= p["max_hold_bars"]:
                        exit_price, result = cur, ("WIN" if (cur - p["entry_price"]) >= 0
                                                   else "LOSS")
            if exit_price is not None:
                fill = _record_exit(state, p, exit_price, now, result, "SIGNAL")
                if fill is None:
                    still_open.append(p)  # real exit failed → keep, retry next cycle
                    continue
                new_fills.append(fill)
                print(f"  EXIT  {sym:10s} {result:4s} @₹{fill['exit_price']:.2f}  "
                       f"PnL=₹{fill['pnl']:+,.0f}  R={fill['r_multiple']:+.2f}  [{sname}]")
                if result == "LOSS":
                    COOLDOWNS[(sym, p["direction"], sname)] = time.time() + 3600
            else:
                still_open.append(p)
        sstate["positions"] = still_open

    # ── 1b) swing exit: force-close prev-day swing positions at exit time ──
    # Runs regardless of the global mode so that swing positions (opened in
    # --mode swing or --mode both) always get their scheduled exit. Skip when
    # the global mode is strictly intraday AND there are no swing positions —
    # but checking is cheap, so just iterate and let the mode filter do the work.
    hour_min = now.hour + now.minute / 60.0
    exit_hour = 9.5 if SWING_EXIT_MODE == "next_open" else 15.25
    if abs(hour_min - exit_hour) < 0.125:  # within ~7.5 min of exit time
        for sname, sstate in state.get("strategies", {}).items():
            for p in list(sstate.get("positions", [])):
                if p.get("mode") != "swing":
                    continue
                opened_date = (p.get("opened_at") or "")[:10]
                if opened_date and opened_date != now_date:
                    live_price = _upstox_live_price(p["symbol"]) if USE_UPSTOX else None
                    _, cur, _, _ = _evaluate_symbol(p["symbol"], nifty_15m, nifty_1d, now,
                                                    live_price=live_price, banknifty_15m=banknifty_15m,
                                                    vix_1d=vix_1d, intraday=False)
                    exit_price = cur if cur is not None else p["entry_price"]
                    if p["direction"] == "LONG":
                        result = "WIN" if (exit_price - p["entry_price"]) >= 0 else "LOSS"
                    else:
                        result = "WIN" if (p["entry_price"] - exit_price) >= 0 else "LOSS"
                    p["strategy"] = sname
                    reason = f"SWING-EXIT-{SWING_EXIT_MODE.upper()}"
                    fill = _record_exit(state, p, exit_price, now, result, reason)
                    if fill is None:
                        continue  # real exit failed → keep position, retry next cycle
                    sstate["positions"].remove(p)
                    new_fills.append(fill)
                    print(f"  {reason} {p['symbol']:10s} close @₹{fill['exit_price']:.2f}  "
                          f"PnL=₹{fill['pnl']:+,.0f}  R={fill['r_multiple']:+.2f}  "
                          f"(opened {opened_date}) [{sname}]")

    # ── 1c) daily trailing-stop exits (Daily Trend Breakout, once/day) ──
    # Replay the close-based ATR chandelier over completed daily bars. Runs only
    # in the morning daily pass. Exit fills at the current market price.
    if do_daily_pass:
        for sname, sstate in state.get("strategies", {}).items():
            if not _is_daily_strategy(sname):
                continue
            for p in list(sstate.get("positions", [])):
                if not p.get("trail_atr_mult", 0):
                    continue
                sym = p["symbol"]
                live_price = _upstox_live_price(sym) if USE_UPSTOX else None
                dctx = _build_daily_context(sym, nifty_1d, now, live_price=live_price)
                if dctx is None:
                    continue
                cur = dctx["current_price"]
                prices[sym] = cur
                res = _daily_trailing_exit(
                    dctx["stock_1d"], p.get("signal_date", (p.get("opened_at") or "")[:10]),
                    p["entry_price"], p["stop_loss"],
                    float(p["trail_atr_mult"]), int(p.get("max_hold_bars") or 60),
                )
                if res is None:
                    continue
                if not res.get("exit"):
                    # ratchet the displayed trailing stop upward for visibility
                    if res.get("stop"):
                        p["stop_loss"] = max(p["stop_loss"], res["stop"])
                    continue
                p["strategy"] = sname
                reason = f"TRAIL-STOP" if res["reason"] == "TRAIL" else "MAX-HOLD"
                fill = _record_exit(state, p, cur, now, res["result"], reason)
                if fill is None:
                    continue  # real exit failed → keep position, retry next cycle
                sstate["positions"].remove(p)
                new_fills.append(fill)
                print(f"  {reason:10s} {sym:10s} {res['result']:4s} @₹{fill['exit_price']:.2f}  "
                      f"PnL=₹{fill['pnl']:+,.0f}  R={fill['r_multiple']:+.2f}  [{sname}]")

    # ── 2) scan for new entries (per strategy) ──
    for strat_name in active_strategies:
        strat_state = state["strategies"][strat_name]
        strat_peak = strat_state.get("peak_equity", strategy_capitals.get(strat_name, INITIAL_CAPITAL))
        strat_equity = _strategy_equity(state, strat_name, prices)
        dd_scaler = drawdown_risk_scaler(strat_equity, strat_peak)
        if dd_scaler < 1.0:
            print(f"  [{strat_name}] [dd] equity ₹{strat_equity:,.0f} vs peak ₹{strat_peak:,.0f} "
                  f"→ risk x{dd_scaler}")
        if strat_state["day_entries"] >= MAX_TRADES_PER_DAY:
            print(f"  [{strat_name}] [cap] daily entry limit ({MAX_TRADES_PER_DAY}) reached — no new entries")
            continue
        if dd_scaler == 0.0:
            print(f"  [{strat_name}] [halt] max drawdown reached — no new entries this cycle")
            continue

        global PAPER_STRATEGY, PAPER_TUNING
        PAPER_STRATEGY = strat_name
        PAPER_TUNING = strategy_tunings.get(strat_name)

        # Per-strategy symbol list: each strategy scans only its own watchlist
        # (when provided) instead of the shared flat list. Falls back to the
        # shared list for backward compatibility.
        strat_symbols = list(strategy_symbols.get(strat_name, symbols)) \
            if strategy_symbols else list(symbols)

        # ── Daily Trend Breakout: once-per-day morning pass ──────────────────
        # Trailing-stop LONG-only strategy on native 1d bars. Bypasses the
        # intraday/swing machinery: no 1m gate (no 1m relevance), no confirmation
        # gate (auto-passes for non-Manual), no day-of-week gate (a daily
        # breakout is not weekday-sensitive), no ML filter (the filter model was
        # trained on 15m RSM/Combined/Manual signals only). Drawdown scaler,
        # conviction sizing, cooldown and the daily entry cap still apply.
        if _is_daily_strategy(strat_name):
            if not do_daily_pass:
                continue
            open_syms = {p["symbol"] for p in strat_state["positions"]}
            for sym in strat_symbols:
                if strat_state["day_entries"] >= MAX_TRADES_PER_DAY:
                    break
                if sym in open_syms:
                    continue
                live_price = _upstox_live_price(sym) if USE_UPSTOX else None
                dctx = _build_daily_context(sym, nifty_1d, now, live_price=live_price)
                if dctx is None:
                    continue
                decision = _decide_daily(dctx)
                cur = dctx["current_price"]
                if decision is None or cur is None:
                    continue
                if decision.direction != "LONG" or not decision.trail_atr_mult:
                    continue  # LONG-only v1; must carry a trailing stop
                direction = "LONG"
                cool_key = (sym, direction, strat_name)
                if cool_key in COOLDOWNS and time.time() < COOLDOWNS[cool_key]:
                    continue
                risk_pct = RISK_PER_TRADE_PCT
                if USE_CONVICTION:
                    risk_pct *= conviction_multiplier(decision.score)
                if dd_scaler < 1.0:
                    risk_pct *= dd_scaler
                risk_pct = min(risk_pct, MAX_RISK_PCT)
                entry_px = round(cur, 2)
                # Recompute stop loss for the actual entry price (the analysis
                # proved entering at the current market price outperforms the old
                # fixed "yesterday's close" entry). SL distance is the same ATR-
                # based distance the strategy computed; only the base price shifts.
                sl_distance = round(decision.entry_price - decision.stop_loss, 2)
                actual_stop = round(entry_px - sl_distance, 2)
                notional = position_size_for(entry_px, actual_stop,
                                             risk_pct=risk_pct)
                if notional <= 0:
                    continue
                notional = min(notional, strat_state["cash"])
                shares = int(notional / entry_px)
                if shares < 1:
                    continue
                entry_shares = shares
                entry_order = _order_payload(sym, "BUY", shares, entry_px, None,
                                             actual_stop, mode="swing")
                # Real-order path (delivery product "D"); paper-first deploy keeps
                # REAL_ORDERS off. Mirrors the intraday entry's WAL+confirm flow.
                if REAL_ORDERS:
                    wal_id = f"{sym}:{direction}:{now.strftime('%Y%m%d%H%M%S')}"
                    _wal_record({
                        "_wal_id": wal_id, "side": "ENTRY", "symbol": sym,
                        "direction": direction, "strategy": strat_name, "mode": "daily",
                        "instrument_key": entry_order.get("instrument_key"),
                        "requested_qty": shares, "entry_price": entry_px,
                        "stop_loss": actual_stop,
                        "take_profit": round(decision.take_profit, 2),
                        "score": round(decision.score, 1),
                    })
                    oid = place_upstox_order(entry_order)
                    if not oid:
                        print(f"  [{strat_name}] [real-entry-fail] {sym} — rejected")
                        _wal_resolve(wal_id)
                        continue
                    entry_order["order_id"] = oid
                    fillinfo = poll_order_fill(oid, requested_qty=shares)
                    filled = int(fillinfo.get("filled_qty") or 0) if fillinfo else 0
                    if fillinfo is None or fillinfo.get("status") in _DEAD_STATES \
                            or not fillinfo.get("avg_price") or filled < 1:
                        status = fillinfo.get("status") if fillinfo else "unknown"
                        print(f"  [{strat_name}] [real-entry-unfilled] {sym} status={status}")
                        _wal_resolve(wal_id)
                        continue
                    entry_px = round(float(fillinfo["avg_price"]), 2)
                    if fillinfo.get("partial") and filled < shares:
                        cancel_upstox_order(oid)
                    entry_shares = filled
                    entry_order["fill_price"] = entry_px
                    entry_order["price"] = entry_px
                    entry_order["quantity"] = entry_shares
                    _wal_resolve(wal_id)
                strat_state["cash"] -= entry_shares * entry_px
                pos = {
                    "symbol": sym, "direction": direction, "strategy": strat_name,
                    "entry_price": entry_px,
                    "stop_loss": actual_stop,
                    "take_profit": round(decision.take_profit, 2),
                    "shares": entry_shares, "opened_at": now.strftime("%Y-%m-%d %H:%M"),
                    "score": round(decision.score, 1), "mode": "daily",
                    "trail_atr_mult": float(decision.trail_atr_mult),
                    "trail_high": entry_px,
                    "max_hold_bars": int(decision.max_hold_bars or 60),
                    "signal_date": str(pd.Timestamp(dctx["last_ts"]).date()),
                }
                strat_state["positions"].append(pos)
                strat_state["day_entries"] += 1
                open_syms.add(sym)
                state["trades"].append({
                    "symbol": sym, "direction": direction, "side": "ENTRY",
                    "strategy": strat_name, "entry_price": entry_px,
                    "stop_loss": actual_stop,
                    "take_profit": round(decision.take_profit, 2),
                    "shares": entry_shares, "ts": now.strftime("%Y-%m-%d %H:%M"),
                    "order": entry_order,
                })
                from scripts.trade_history import record_trade_entry
                record_trade_entry(sym, direction, entry_px, entry_shares,
                                   now.strftime("%Y-%m-%d %H:%M"), mode="daily",
                                   strategy=strat_name)
                _notify_entry(pos, strat_name)
                print(f"  ENTRY {sym:10s} LONG  @₹{entry_px:.2f}  "
                       f"SL=₹{actual_stop:.2f} trail×{decision.trail_atr_mult:.1f}ATR  "
                      f"shares={entry_shares} (₹{entry_shares*entry_px:,.0f})  "
                      f"score={decision.score:.0f} risk={risk_pct:.2f}%  [daily] [{strat_name}]")
            continue  # daily strategy handled — skip the intraday/swing loop

        # ── ML Opening Breakout: 5m opening-window pass ──────────────────────
        # Symmetric 5m ML strategy (09:15-10:30). Bypasses the intraday/swing
        # machinery: no 1m gate (irrelevant at 5m), no confirmation gate (Manual
        # only), no day-of-week gate (a 5m opening signal is not weekday-
        # sensitive), no ML filter (the filter model was trained on 15m RSM/
        # Combined/Manual signals only). Drawdown scaler, conviction sizing,
        # cooldown and the daily entry cap still apply. Evaluated every cycle
        # inside the opening window.
        if _is_orb_strategy(strat_name):
            if not in_opening_window:
                continue
            open_syms = {p["symbol"] for p in strat_state["positions"]}
            for sym in strat_symbols:
                if strat_state["day_entries"] >= MAX_TRADES_PER_DAY:
                    break
                if sym in open_syms:
                    continue
                live_price = _upstox_live_price(sym) if USE_UPSTOX else None
                octx = _build_5m_opening_context(sym, nifty_5m, nifty_1d, now, live_price=live_price)
                if octx is None:
                    continue
                result = _decide_5m_opening(octx)
                if not result or not result.trade_candidates:
                    continue
                tc = result.trade_candidates[0]
                direction = tc.direction
                cool_key = (sym, direction, strat_name)
                if cool_key in COOLDOWNS and time.time() < COOLDOWNS[cool_key]:
                    continue
                # Bar-dedup: don't re-enter on the same completed 5m bar.
                bar_key = (sym, direction, strat_name)
                bar_ts = str(octx["last_ts"])
                if bar_key in LAST_ENTRY_BAR and LAST_ENTRY_BAR[bar_key] == bar_ts:
                    continue
                risk_pct = RISK_PER_TRADE_PCT
                if USE_CONVICTION:
                    risk_pct *= ml_proba_multiplier(tc.ranking_score / 100.0)
                if dd_scaler < 1.0:
                    risk_pct *= dd_scaler
                risk_pct = min(risk_pct, MAX_RISK_PCT)
                notional = position_size_for(tc.entry_price, tc.stop_loss, risk_pct=risk_pct)
                if notional <= 0:
                    continue
                notional = min(notional, strat_state["cash"])
                shares = int(notional / tc.entry_price)
                if shares < 1:
                    continue
                entry_txn = "SELL" if direction == "SHORT" else "BUY"
                entry_order = _order_payload(sym, entry_txn, shares,
                                             round(tc.entry_price, 2), None,
                                             round(tc.stop_loss, 2), mode="intraday")
                entry_px = round(tc.entry_price, 2)
                entry_shares = shares
                if REAL_ORDERS:
                    wal_id = f"{sym}:{direction}:{now.strftime('%Y%m%d%H%M%S')}"
                    _wal_record({
                        "_wal_id": wal_id, "side": "ENTRY", "symbol": sym,
                        "direction": direction, "strategy": strat_name, "mode": "intraday",
                        "instrument_key": entry_order.get("instrument_key"),
                        "requested_qty": shares,
                        "entry_price": entry_px,
                        "stop_loss": round(tc.stop_loss, 2),
                        "take_profit": round(tc.take_profit, 2),
                        "score": round(tc.ranking_score, 1),
                    })
                    oid = place_upstox_order(entry_order)
                    if not oid:
                        print(f"  [{strat_name}] [real-entry-fail] {sym} {direction} — rejected")
                        _wal_resolve(wal_id)
                        continue
                    entry_order["order_id"] = oid
                    fillinfo = poll_order_fill(oid, requested_qty=shares)
                    filled = int(fillinfo.get("filled_qty") or 0) if fillinfo else 0
                    if fillinfo is None or fillinfo.get("status") in _DEAD_STATES \
                            or not fillinfo.get("avg_price") or filled < 1:
                        status = fillinfo.get("status") if fillinfo else "unknown"
                        print(f"  [{strat_name}] [real-entry-unfilled] {sym} {direction} — status={status}")
                        _wal_resolve(wal_id)
                        continue
                    entry_px = round(float(fillinfo["avg_price"]), 2)
                    if fillinfo.get("partial") and filled < shares:
                        cancel_upstox_order(oid)
                    entry_shares = filled
                    entry_order["fill_price"] = entry_px
                    entry_order["price"] = entry_px
                    entry_order["quantity"] = entry_shares
                    _wal_resolve(wal_id)
                if direction == "LONG":
                    strat_state["cash"] -= entry_shares * entry_px
                pos = {
                    "symbol": sym, "direction": direction, "strategy": strat_name,
                    "entry_price": entry_px,
                    "stop_loss": round(tc.stop_loss, 2),
                    "take_profit": round(tc.take_profit, 2),
                    "shares": entry_shares, "opened_at": now.strftime("%Y-%m-%d %H:%M"),
                    "score": round(tc.ranking_score, 1), "mode": "intraday",
                    "max_hold_bars": int(tc.max_hold_bars or 48),
                }
                strat_state["positions"].append(pos)
                strat_state["day_entries"] += 1
                open_syms.add(sym)
                LAST_ENTRY_BAR[bar_key] = bar_ts
                state["trades"].append({
                    "symbol": sym, "direction": direction, "side": "ENTRY",
                    "strategy": strat_name,
                    "entry_price": entry_px,
                    "stop_loss": round(tc.stop_loss, 2),
                    "take_profit": round(tc.take_profit, 2),
                    "shares": entry_shares, "ts": now.strftime("%Y-%m-%d %H:%M"),
                    "order": entry_order,
                })
                from scripts.trade_history import record_trade_entry
                record_trade_entry(sym, direction, entry_px, entry_shares,
                                   now.strftime("%Y-%m-%d %H:%M"), mode="intraday",
                                   strategy=strat_name)
                _notify_entry(pos, strat_name)
                print(f"  ENTRY {sym:10s} {direction:5s} @₹{entry_px:.2f}  "
                      f"SL=₹{tc.stop_loss:.2f} TP=₹{tc.take_profit:.2f}  "
                      f"shares={entry_shares} (₹{entry_shares*entry_px:,.0f})  "
                      f"P={tc.ranking_score/100:.2f}  [{strat_name}]")
            continue  # opening-breakout handled — skip the intraday/swing loop

        # Time-gated symbol filter: only Manual strategy is restricted to
        # the current golden window's pre-optimized watchlist.
        if "manual institutional" in strat_name.lower() and (MORNING_WATCHLIST_SYMBOLS or EVENING_WATCHLIST_SYMBOLS):
            w = _is_golden_window(now)
            if w == "morning":
                strat_symbols = [s for s in strat_symbols if s in MORNING_WATCHLIST_SYMBOLS]
                print(f"  [{strat_name}] morning window — {len(strat_symbols)} symbols")
            elif w == "evening":
                strat_symbols = [s for s in strat_symbols if s in EVENING_WATCHLIST_SYMBOLS]
                print(f"  [{strat_name}] evening window — {len(strat_symbols)} symbols")
            elif not w:
                print(f"  [{strat_name}] [skip] outside golden windows — scanning paused")
                continue

        # Determine which modes this strategy evaluates. --mode both runs
        # intraday AND swing concurrently; a symbol may hold both position types.
        modes_to_evaluate = []
        if TRADING_MODE in ("intraday", "both"):
            modes_to_evaluate.append("intraday")
        if TRADING_MODE in ("swing", "both"):
            modes_to_evaluate.append("swing")

        # Track already-open symbols per mode ACROSS ALL strategies so the
        # same symbol cannot be held by two strategies in the same mode (Phase
        # 38: prevents cross-strategy duplicates like COALINDIA RSM + Combined).
        open_by_mode: dict[str, set] = {"intraday": set(), "swing": set(), "daily": set()}
        for sn in active_strategies:
            for p in state["strategies"].get(sn, {}).get("positions", []):
                m = p.get("mode", "intraday")
                open_by_mode.setdefault(m, set()).add(p["symbol"])

        for sym in strat_symbols:
            if strat_state["day_entries"] >= MAX_TRADES_PER_DAY:
                break
            for mode in modes_to_evaluate:
                if sym in open_by_mode.get(mode, set()):
                    continue
                if strat_state["day_entries"] >= MAX_TRADES_PER_DAY:
                    break
                # Swing entry gate: targeted windows from RSM 15m backtest
                # (5,410 trades). Primary 10:00–11:45 (avgR +0.10); plus two
                # isolated high-edge afternoon slots: 14:00–14:15 (avgR +0.31)
                # and 14:45–15:00 (avgR +0.09). Excludes the opening auction
                # (09:15), the 13:00–13:30 lunch dip, and the bad 14:15/14:30/
                # 15:15 bars. Replaces the old flat 14:30–15:15 gate which had
                # avgR +0.0097 (break-even).
                # Combined Swing carries its OWN day-aware gate inside the
                # strategy, so it bypasses this generic gate to avoid conflict.
                if mode == "swing" and "combined" not in strat_name.lower():
                    hour_min = now.hour + now.minute / 60.0
                    allowed = (
                        (10.0 <= hour_min < 11.75) or
                        (14.0 <= hour_min < 14.25) or
                        (14.75 <= hour_min < 15.0)
                    )
                    if not allowed:
                        continue
                is_swing = mode == "swing"
                live_price = _upstox_live_price(sym) if USE_UPSTOX else None
                ctx = _build_symbol_context(sym, nifty_15m, nifty_1d, now, live_price=live_price,
                                            banknifty_15m=banknifty_15m, vix_1d=vix_1d)
                if ctx is None:
                    continue
                decision = _decide_trade_for_mode(ctx, intraday=not is_swing)
                cur = ctx["current_price"]
                entry_date = ctx["entry_date"]
                if decision is None or cur is None:
                    continue
                # ML Standalone is symmetric by design (its model scores BOTH
                # LONG and SHORT per bar and takes whichever clears thr 0.80,
                # walk-forward validated net-positive in bear AND bull folds), so
                # it always trades both directions regardless of the --shorts flag.
                is_ml_standalone = strat_name == "ML Standalone"
                allow_shorts = ALLOW_SHORTS if not is_swing else SWING_ALLOW_SHORTS
                if is_ml_standalone:
                    allow_shorts = True
                if decision.direction == "SHORT" and not allow_shorts:
                    continue
                direction = decision.direction
                cool_key = (sym, direction, strat_name)
                if cool_key in COOLDOWNS and time.time() < COOLDOWNS[cool_key]:
                    remaining = int((COOLDOWNS[cool_key] - time.time()) / 60)
                    print(f"  [{strat_name}] [cooldown] {sym} {direction} — {remaining}m left")
                    continue
                # Bar-dedup: don't re-enter the same (symbol, direction, strategy)
                # on the same completed 15m bar — the signal is identical (stale).
                bar_key = (sym, direction, strat_name)
                bar_ts = str(ctx["last_ts"])
                if bar_key in LAST_ENTRY_BAR and LAST_ENTRY_BAR[bar_key] == bar_ts:
                    print(f"  [{strat_name}] [dup] {sym} {direction} — same bar {bar_ts}")
                    continue
                # 1m entry refinement: only take the 15m signal if the current
                # 1m price still supports the entry level (matches manual 1m timing).
                stock_1m = ctx.get("stock_1m")
                if stock_1m is not None and len(stock_1m) > 0:
                    last_1m_close = float(stock_1m["close"].iloc[-1])
                    ref_price = last_1m_close if live_price is None else live_price
                    threshold = decision.entry_price * 0.002  # 0.2%
                    if direction == "LONG" and ref_price < decision.entry_price - threshold:
                        print(f"  [{strat_name}] [1m-gate] {sym} {direction} — "
                              f"₹{ref_price:.2f} vs entry ₹{decision.entry_price:.2f}")
                        continue
                    if direction == "SHORT" and ref_price > decision.entry_price + threshold:
                        print(f"  [{strat_name}] [1m-gate] {sym} {direction} — "
                              f"₹{ref_price:.2f} vs entry ₹{decision.entry_price:.2f}")
                        continue
                # ── Bar confirmation gate (Phase 24) — Manual only ──
                # Manual enters on time windows regardless of bar quality; the
                # gate requires a bullish signal bar + volume expansion. Validated
                # on 22,022 trades: flips the deployed watchlist from net loss to
                # net profit. RSM/Combined pass through (gate redundant/harmful).
                if not _confirmation_gate(ctx["window"], decision.entry_price,
                                          direction, strat_name):
                    print(f"  [{strat_name}] [confirm] {sym} {direction} — "
                          f"signal bar not bullish / no volume expansion")
                    continue
                # ── ML Universal Filter gate (Phase 32/33) — opt-in ──
                # Score P(net-positive-after-costs) from the same feature vector
                # the backtest logs; take only the high-confidence tail. OOS:
                # thr 0.65 -> +₹108,598 / 795 test trades (+₹137/trade).
                # ML Standalone is skipped: the filter model was trained on
                # RSM/Combined/Manual signals only (no strategy_ML-Standalone
                # column), so its P(net+) is undefined for those entries. The
                # standalone's OWN thr-0.80 model already gates its trades. The
                # ML Opening Breakout is likewise skipped: the filter model was
                # trained on 15m RSM/Combined/Manual signals (no strategy_ML-
                # Opening-Breakout column), so its P(net+) is undefined for the
                # 5m opening entries. Its OWN thr-0.70 model already gates them.
                if ML_FILTER and not is_ml_standalone and not _is_orb_strategy(strat_name):
                    ok, proba = passes_ml_filter(ctx, decision, ML_FILTER_THR)
                    if not ok:
                        print(f"  [{strat_name}] [ml-filter] {sym} {direction} — "
                              f"P={proba:.2f} < {ML_FILTER_THR}")
                        continue
                    if proba is not None:
                        print(f"  [{strat_name}] [ml-filter] {sym} {direction} — "
                              f"PASS P={proba:.2f}")
                # ML Standalone bypasses the day-of-week gate: weekday is already
                # one of its model features, so external day sizing/skips would
                # double-count. Its position size comes purely from model conviction.
                cal_mult = 1.0 if is_ml_standalone else \
                    calendar_conviction_multiplier(entry_date, direction, strategy=strat_name)
                if cal_mult == 0.0:
                    # Data-backed day-of-week HARD SKIP for this strategy
                    # (e.g. RSM Thursday, Manual Wednesday). See capital_model.
                    _day = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][entry_date.weekday()]
                    print(f"  [{strat_name}] [day-skip] {sym} {direction} — "
                          f"{_day} is a negative day for this strategy")
                    continue
                risk_pct = RISK_PER_TRADE_PCT
                if USE_CONVICTION:
                    if is_ml_standalone:
                        # Phase B: proba-band sizing (replaces conviction_multiplier,
                        # which maps every ML Standalone score ≥70 → 1.5x flat).
                        risk_pct *= ml_proba_multiplier(decision.score / 100.0)
                    else:
                        risk_pct *= conviction_multiplier(decision.score)
                risk_pct *= cal_mult
                if dd_scaler < 1.0:
                    risk_pct *= dd_scaler
                risk_pct = min(risk_pct, MAX_RISK_PCT)
                strat_capital = strategy_capitals.get(strat_name, INITIAL_CAPITAL)
                notional = position_size_for(decision.entry_price, decision.stop_loss, risk_pct=risk_pct,
                                             capital=strat_capital)
                if notional <= 0:
                    continue
                notional = min(notional, strat_state["cash"])
                shares = int(notional / decision.entry_price)
                if shares < 1:
                    continue
                entry_txn = "SELL" if direction == "SHORT" else "BUY"
                entry_order = _order_payload(sym, entry_txn, shares,
                                             round(decision.entry_price, 2), None,
                                             round(decision.stop_loss, 2),
                                             mode=mode)
                # ── Real entry order (only with --real) ──
                # Place BEFORE any paper bookkeeping so a rejected order leaves
                # no phantom position / no cash movement. On failure, skip this
                # symbol entirely (and let the normal cooldown/dedup apply).
                entry_px = round(decision.entry_price, 2)
                entry_shares = shares
                if REAL_ORDERS:
                    # Write intent to the WAL BEFORE placing so a crash between
                    # "placed" and "booked" can be recovered on next startup.
                    wal_id = f"{sym}:{direction}:{now.strftime('%Y%m%d%H%M%S')}"
                    _wal_record({
                        "_wal_id": wal_id, "side": "ENTRY", "symbol": sym,
                        "direction": direction, "strategy": strat_name, "mode": mode,
                        "instrument_key": entry_order.get("instrument_key"),
                        "requested_qty": shares,
                        "entry_price": entry_px,
                        "stop_loss": round(decision.stop_loss, 2),
                        "take_profit": round(decision.take_profit, 2),
                        "score": round(decision.score, 1),
                    })
                    oid = place_upstox_order(entry_order)
                    if not oid:
                        print(f"  [{strat_name}] [real-entry-fail] {sym} {direction} "
                              f"— order rejected, skipping paper entry too")
                        _wal_resolve(wal_id)
                        continue
                    entry_order["order_id"] = oid
                    # Confirm the fill before booking the paper position so the
                    # shadow cost basis matches the broker's actual fill.
                    fillinfo = poll_order_fill(oid, requested_qty=shares)
                    filled = int(fillinfo.get("filled_qty") or 0) if fillinfo else 0
                    if fillinfo is None or fillinfo.get("status") in _DEAD_STATES \
                            or not fillinfo.get("avg_price") or filled < 1:
                        status = fillinfo.get("status") if fillinfo else "unknown"
                        print(f"  [{strat_name}] [real-entry-unfilled] {sym} {direction} "
                              f"— status={status} filled={filled}, skipping paper entry")
                        _wal_resolve(wal_id)
                        continue
                    entry_px = round(float(fillinfo["avg_price"]), 2)
                    # Partial fill: book exactly what filled, cancel the remainder
                    # so it cannot fill later behind the bot's back.
                    if fillinfo.get("partial") and filled < shares:
                        if cancel_upstox_order(oid):
                            print(f"  [{strat_name}] [partial-entry] {sym} {direction} "
                                  f"filled {filled}/{shares} — remainder cancelled")
                        else:
                            print(f"  [{strat_name}] [partial-entry] {sym} {direction} "
                                  f"filled {filled}/{shares} — WARN remainder NOT cancelled")
                    entry_shares = filled
                    entry_order["fill_price"] = entry_px
                    entry_order["price"] = entry_px
                    entry_order["quantity"] = entry_shares
                    _wal_resolve(wal_id)
                if direction == "LONG":
                    strat_state["cash"] -= entry_shares * entry_px
                pos = {
                    "symbol": sym, "direction": direction, "strategy": strat_name,
                    "entry_price": entry_px,
                    "stop_loss": round(decision.stop_loss, 2),
                    "take_profit": round(decision.take_profit, 2),
                    "shares": entry_shares, "opened_at": now.strftime("%Y-%m-%d %H:%M"),
                    "score": round(decision.score, 1),
                    "mode": mode,
                }
                strat_state["positions"].append(pos)
                strat_state["day_entries"] += 1
                open_by_mode.setdefault(mode, set()).add(sym)
                state["trades"].append({
                    "symbol": sym, "direction": direction, "side": "ENTRY",
                    "strategy": strat_name,
                    "entry_price": entry_px,
                    "stop_loss": round(decision.stop_loss, 2),
                    "take_profit": round(decision.take_profit, 2),
                    "shares": entry_shares, "ts": now.strftime("%Y-%m-%d %H:%M"),
                    "order": entry_order,
                })
                from scripts.trade_history import record_trade_entry
                record_trade_entry(sym, direction, entry_px,
                                   entry_shares, now.strftime("%Y-%m-%d %H:%M"), mode=mode,
                                   strategy=strat_name)
                _notify_entry(pos, strat_name)
                LAST_ENTRY_BAR[bar_key] = bar_ts
                print(f"  ENTRY {sym:10s} {direction:5s} @₹{entry_px:.2f}  "
                      f"SL=₹{decision.stop_loss:.2f} TP=₹{decision.take_profit:.2f}  "
                      f"shares={entry_shares} (₹{entry_shares*entry_px:,.0f})  "
                      f"cal×{cal_mult:.2f} risk={risk_pct:.2f}%  "
                      f"[{mode}] [{strat_name}]")

    # ── 3) equity snapshot ──
    if do_daily_pass:
        # Mark the once-per-day daily pass complete so it doesn't re-run today.
        state["daily_pass_date"] = now_date
    equity = _equity(state, prices)
    for sname in active_strategies:
        s_equity = _strategy_equity(state, sname, prices)
        old_peak = state["strategies"][sname].get("peak_equity", strategy_capitals.get(sname, INITIAL_CAPITAL))
        state["strategies"][sname]["peak_equity"] = round(max(old_peak, s_equity), 2)
    state["equity_curve"].append({"ts": now.strftime("%Y-%m-%d %H:%M"), "equity": round(equity, 2)})
    if len(state["equity_curve"]) > 5000:
        state["equity_curve"] = state["equity_curve"][-5000:]
    total_cash_final = sum(s.get("cash", 0) for s in state.get("strategies", {}).values())
    total_pos_final = sum(len(s.get("positions", [])) for s in state.get("strategies", {}).values())
    print(f"  Equity: ₹{equity:,.0f}  (cash ₹{total_cash_final:,.0f} + "
          f"{total_pos_final} open positions)")
    return state


def _market_open(now: pd.Timestamp) -> bool:
    """True only during NSE trading hours on a non-holiday weekday.

    Delegates to ``data.utils.market_hours.is_market_open`` so weekends AND the
    NSE holiday calendar are respected (the paper trader must not open fake
    positions on a closed market with stale prices).
    """
    from data.utils.market_hours import is_market_open
    open_flag, _, _ = is_market_open(now)
    return open_flag


def _load_watchlist(name: str) -> list[str]:
    path = "data/symbol_watchlists.json"
    if not os.path.exists(path):
        raise SystemExit(f"  [error] watchlist file not found: {path}")
    data = json.load(open(path))
    if name not in data:
        avail = ", ".join(k for k in data if k != "details")
        raise SystemExit(f"  [error] unknown watchlist '{name}'. Available: {avail}")
    syms = list(data[name])
    if not syms:
        raise SystemExit(f"  [error] watchlist '{name}' is empty")
    print(f"  Loaded watchlist '{name}' ({len(syms)} symbols)")
    return syms


def _print_watchlists() -> None:
    path = "data/symbol_watchlists.json"
    if not os.path.exists(path):
        print(f"  [error] watchlist file not found: {path}")
        return
    data = json.load(open(path))
    print("Available watchlists (data/symbol_watchlists.json):")
    for k, v in data.items():
        if k == "details":
            continue
        n = len(v) if isinstance(v, list) else 0
        print(f"  {k:16s} {n} symbols")
    print("\nUse with: --watchlist <name>")


def main() -> None:
    ap = argparse.ArgumentParser(description="Paper-trading simulator (15m intraday)")
    ap.add_argument("--loop", action="store_true", help="Poll during market hours")
    ap.add_argument("--interval", type=int, default=15, help="Poll interval (min)")
    ap.add_argument("--symbols", default=None, help="comma/space separated subset")
    ap.add_argument("--watchlist", default=None,
                    help="named list from data/symbol_watchlists.json "
                         "(15m_intraday, 15m_swing, 1h_swing, consensus, full_consensus)")
    ap.add_argument("--list-watchlists", action="store_true",
                    help="print available watchlists and exit")
    ap.add_argument("--reset", action="store_true", help="wipe state and start fresh")
    ap.add_argument("--upstox", action="store_true",
                    help="Use Upstox real-broker feed instead of yfinance")
    ap.add_argument("--real", action="store_true",
                    help="Place REAL Upstox orders (live money!). Requires --upstox "
                         "and a trading-scoped token. Off by default (paper only).")
    ap.add_argument("--shorts", action="store_true",
                    help="Allow SHORT entries (off by default — not yet OOS-validated)")
    ap.add_argument("--no-conviction", action="store_true",
                    help="Disable score-based risk scaling (use fixed 1% risk)")
    ap.add_argument("--mode", default="intraday", choices=["intraday", "swing", "both"],
                    help="Trading mode: intraday (close at EOD), swing (hold overnight), "
                         "or both (run intraday + swing concurrently)")
    ap.add_argument("--swing-exit", default="next_close", choices=["next_open", "next_close"],
                    help="Swing exit: next_open (09:30) or next_close (15:15)")
    ap.add_argument("--swing-shorts", action="store_true",
                    help="Allow SHORT in swing mode")
    ap.add_argument("--strategy", default=None,
                    help="Single strategy name (backward compat; use --strategies for multi)")
    ap.add_argument("--strategies", default=None,
                    help="Comma-separated strategy names (default: Institutional Probability)")
    ap.add_argument("--alloc", default=None,
                    help="Comma-separated capital %% per strategy (must sum to 100)")
    ap.add_argument("--sl", default=None,
                    help="Comma-separated SL ATR multipliers per strategy")
    ap.add_argument("--tp", default=None,
                    help="Comma-separated TP ATR multipliers per strategy")
    ap.add_argument("--ml-filter", action="store_true",
                    help="Gate entries on the ML universal filter P(net-positive) (Phase 32/33)")
    ap.add_argument("--ml-filter-thr", type=float, default=0.65,
                    help="ML filter threshold (default 0.65 = val-max-net OOS)")
    args = ap.parse_args()

    if args.list_watchlists:
        _print_watchlists()
        return

    global USE_UPSTOX, ALLOW_SHORTS, USE_CONVICTION, REAL_ORDERS
    global active_strategies, strategy_allocs, strategy_capitals, strategy_tunings
    global TRADING_MODE, SWING_EXIT_MODE, SWING_ALLOW_SHORTS
    global ML_FILTER, ML_FILTER_THR
    USE_UPSTOX = args.upstox
    REAL_ORDERS = args.real
    ALLOW_SHORTS = args.shorts
    USE_CONVICTION = not args.no_conviction
    TRADING_MODE = args.mode
    SWING_EXIT_MODE = args.swing_exit
    SWING_ALLOW_SHORTS = args.swing_shorts
    ML_FILTER = args.ml_filter
    ML_FILTER_THR = args.ml_filter_thr

    # --real requires the Upstox feed + a trading-scoped token. Refuse to run
    # live orders on the delayed yfinance feed (stale prices → bad fills).
    if REAL_ORDERS and not USE_UPSTOX:
        raise SystemExit("  [error] --real requires --upstox (live orders need the real-broker feed)")
    if REAL_ORDERS:
        print("  " + "=" * 60)
        print("  ⚠️  LIVE TRADING ENABLED (--real) — REAL ORDERS, REAL MONEY")
        print(f"     Max single-order notional cap: ₹{MAX_ORDER_VALUE:,.0f}")
        print("  " + "=" * 60)

    # Backward compat: --strategy (singular) maps to single-strategy mode
    if args.strategy is not None and args.strategies is None:
        args.strategies = args.strategy
    if args.strategies is None:
        args.strategies = "Institutional Probability"

    strat_names = [s.strip() for s in args.strategies.split(",")]
    if args.alloc is None:
        allocs = [100.0 / len(strat_names)] * len(strat_names)
    else:
        allocs = [float(a.strip()) for a in args.alloc.split(",")]

    if len(strat_names) != len(allocs):
        ap.error("--strategies and --alloc must have the same number of entries")
    if abs(sum(allocs) - 100) > 0.01:
        ap.error("--alloc percentages must sum to 100")

    sl_vals = [float(x) for x in args.sl.split(",")] if args.sl else [None] * len(strat_names)
    tp_vals = [float(x) for x in args.tp.split(",")] if args.tp else [None] * len(strat_names)
    if len(sl_vals) != len(strat_names) or len(tp_vals) != len(strat_names):
        ap.error("--sl and --tp must match --strategies count")

    active_strategies = strat_names
    strategy_allocs = dict(zip(strat_names, allocs))
    strategy_capitals = {name: round(INITIAL_CAPITAL * allocs[i] / 100.0, 2)
                         for i, name in enumerate(strat_names)}
    strategy_tunings = {}
    for i, name in enumerate(strat_names):
        tuning = {}
        if sl_vals[i] is not None:
            tuning["sl_mult"] = sl_vals[i]
        if tp_vals[i] is not None:
            tuning["tp_mult"] = tp_vals[i]
        if tuning:
            tuning["atr_period"] = 14
            strategy_tunings[name] = tuning
        else:
            strategy_tunings[name] = None

    if args.reset and os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
        print("  [reset] cleared paper portfolio state")

    # Resolve the symbol universe.
    #   --symbols     → explicit flat list for ALL strategies (overrides watchlists)
    #   --watchlist   → single named list for ALL strategies
    #   default       → PER-STRATEGY watchlists (STRATEGY_WATCHLISTS): each
    #                  strategy scans only its own universe, matching the
    #                  market_scan SCAN_TIERS split.
    wl_path = "data/symbol_watchlists.json"
    wl_data = json.load(open(wl_path)) if os.path.exists(wl_path) else {}

    if args.symbols:
        symbols = []
        for tok in args.symbols.replace(",", " ").split():
            tok = tok.strip().replace(".NS", "").upper()
            if tok:
                symbols.append(tok)
        strategy_symbols = None  # flat list for every strategy
    elif args.watchlist:
        symbols = _load_watchlist(args.watchlist)
        strategy_symbols = None
    else:
        # Build per-strategy symbol lists from their dedicated watchlists.
        strategy_symbols: dict[str, list[str]] = {}
        flat: set[str] = set()
        for sname in active_strategies:
            wl_keys = list(STRATEGY_WATCHLISTS.get(sname, []))
            # Institutional Probability also scans the SHORT watchlist when --shorts
            if sname == "Institutional Probability" and ALLOW_SHORTS:
                wl_keys.append("15m_intraday_short")
            syms: set[str] = set()
            for key in wl_keys:
                syms.update(wl_data.get(key, []))
            if not syms:
                # Fallback to consensus if the strategy has no watchlist mapping
                syms.update(wl_data.get("consensus", []))
            strategy_symbols[sname] = sorted(syms)
            flat.update(syms)
        symbols = sorted(flat)
        print("  Per-strategy watchlists: " +
              ", ".join(f"{k.split(' (')[0]}={len(v)}" for k, v in strategy_symbols.items()))
        print(f"  Auto-resolved {len(symbols)} unique symbols across "
              f"{len(strategy_symbols)} strategies")

    # Auto-close any OPEN trade in trade_history.json whose symbol is no longer
    # in any active strategy's universe (stale entries from a previous
    # crash / --reset leak into the dashboard's Past Trades forever otherwise).
    from scripts.trade_history import clean_stale_open_trades
    valid = set(symbols) if symbols else set()
    if valid:
        n = clean_stale_open_trades(valid, reason="STALE-RESET")
        if n:
            print(f"  [cleanup] closed {n} stale open trade(s) not in active "
                  f"universe")

    # If the Manual Institutional strategy is active, load time-based watchlists
    # so run_cycle selects the right set for the current golden window. Skipped
    # under the Phase 34 full-universe deployment: Manual's own internal golden-
    # window time gate still applies, and the ML filter handles symbol selection,
    # so we do NOT restrict Manual to the pruned 9/5 deploy lists.
    global MORNING_WATCHLIST_SYMBOLS, EVENING_WATCHLIST_SYMBOLS
    has_manual = any("manual institutional" in s.lower() for s in active_strategies)
    manual_uses_pruned = any(
        "manual_" in k for k in
        STRATEGY_WATCHLISTS.get("Manual Institutional (time-gated)", [])
    )
    if has_manual and manual_uses_pruned and not args.symbols:
        if os.path.exists(wl_path):
            MORNING_WATCHLIST_SYMBOLS = wl_data.get("manual_morning_deploy_500", [])
            EVENING_WATCHLIST_SYMBOLS = wl_data.get("manual_evening_deploy_500", [])
            if MORNING_WATCHLIST_SYMBOLS or EVENING_WATCHLIST_SYMBOLS:
                print(f"  Time-based watchlist switching active: "
                      f"{len(MORNING_WATCHLIST_SYMBOLS)} morning / "
                      f"{len(EVENING_WATCHLIST_SYMBOLS)} evening symbols")

    state = _load_state()
    if args.reset:
        state = _load_state()  # already cleared; rebuild fresh

    # Startup reconciliation: align the shadow state with the broker's actual
    # open positions before trading (removes phantoms, fixes fill prices).
    if REAL_ORDERS:
        reconcile_state_with_broker(state)
        _save_state(state)

    if not args.loop:
        state = run_cycle(state, symbols, strategy_symbols)
        _save_state(state)
        return

    print(f"  Paper-trading loop started (interval={args.interval}m, "
          f"{len(symbols)} symbols). Ctrl-C to stop.")
    MAX_CONSECUTIVE_FAILURES = 5
    fail_count = 0
    try:
        while True:
            now = pd.Timestamp.now(tz="Asia/Kolkata")
            if _market_open(now):
                try:
                    state = run_cycle(state, symbols, strategy_symbols)
                    _save_state(state)
                    fail_count = 0
                except Exception as e:
                    fail_count += 1
                    import traceback
                    traceback.print_exc()
                    print(f"  [error] cycle {fail_count}/{MAX_CONSECUTIVE_FAILURES} "
                          f"failed: {e}")
                    if fail_count >= MAX_CONSECUTIVE_FAILURES:
                        print("  [stop] too many consecutive failures; aborting loop.")
                        raise
            else:
                print(f"  [skip] market closed ({now.strftime('%H:%M')}) — waiting")
            # sleep until next interval (or until next market open if closed)
            sleep_s = args.interval * 60
            if not _market_open(now):
                # wake at the next real market open (skips weekends + holidays)
                from data.utils.market_hours import next_market_open
                nxt = next_market_open(now)
                sleep_s = max(60, int((nxt - now).total_seconds()))
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\n  [stop] loop interrupted; state saved.")
        _save_state(state)


if __name__ == "__main__":
    main()
