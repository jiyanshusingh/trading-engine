"""
Live market scanner — 6-strategy scan tiers shown on the dashboard.

Each tier uses a dedicated watchlist + strategy, matching what the paper trader
deploys. No portfolio/order management (that is paper_trade.py's job).

Strategies & tiers:
  Strategy                    Tiers (watchlist)                           TF
  ────────────────────────    ────────────────────────────────────────    ───
  Relative Strength Momentum  rs_momentum_swing_tuned (rsm_swing, 8)     15m
  Combined Swing              combined_swing (combined_swing, 17)         15m
  Manual Inst. (time-gated)   manual_morning_deploy (9) / evening. (5)   15m
  ML Standalone               ml_standalone (full_nse_500, 500)           15m
  Daily Trend Breakout        daily_trend (daily_trend_breakout, 108)     1d
  ML Opening Breakout         orb_scan (full_universe, 500)               5m

Usage
-----
  .venv/bin/python scripts/market_scan.py                 # yfinance (delayed)
  .venv/bin/python scripts/market_scan.py --upstox        # live Upstox feed
  .venv/bin/python scripts/market_scan.py --list-tiers    # show tier plan
  .venv/bin/python scripts/market_scan.py --loop --interval 15
  .venv/bin/python scripts/market_scan.py --json          # machine-readable
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys as _sys
import threading
import time

_log = logging.getLogger(__name__)

_sys.path.insert(0, ".")

# Enable the SHORT side of the engine (INST_SHORT_MIN_SCORE=40) BEFORE importing
# backtest/paper_trade, whose module-level SHORT_MIN_PROB constant freezes at
# import time. SHORT signals are still gated in _scan_symbol (allow_shorts /
# force_short), so this does not leak SHORT into LONG-only runs.
os.environ.setdefault("INST_SHORT_MIN_SCORE", "40")

import atexit
import http.server
import pandas as pd

import scripts.paper_trade as _pt  # reuse Upstox/yfinance bar fetchers + resample
from scripts.backtest import WINDOW_SIZE, build_htf_context, decide_trade
from scripts.live_institutional_scan import (
    _bars_until_close,
    _classify_stock_type,
    _yf_live,
)
from scripts.live_scanner import classify_today_day_type

WATCHLIST_PATH = "data/symbol_watchlists.json"

# (tier_label, watchlist_key, category, spec)
#   category: "intraday" | "swing"  — drives the report grouping
#   spec: tf / sl / tp / intraday    — the scan parameters for this tier
SCAN_TIERS = [
    ("rs_momentum_swing_tuned", "rsm_swing", "swing",
     {"tf": "15m", "sl": 2.0, "tp": 4.0, "intraday": False,
      "strategy": "Relative Strength Momentum"}),
    ("combined_swing", "combined_swing", "swing",
     {"tf": "15m", "sl": 2.0, "tp": 4.0, "intraday": False,
      "strategy": "Combined Swing"}),
    ("manual_morning_deploy", "manual_morning_deploy", "intraday",
     {"tf": "15m", "sl": 0.5, "tp": 5.0, "intraday": True,
      "strategy": "Manual Institutional (time-gated)"}),
    ("manual_evening_deploy", "manual_evening_deploy", "intraday",
     {"tf": "15m", "sl": 0.5, "tp": 5.0, "intraday": True,
      "strategy": "Manual Institutional (time-gated)"}),
    ("ml_standalone", "full_nse_500", "swing",
     {"tf": "15m", "sl": 0.5, "tp": 5.0, "intraday": False,
      "strategy": "ML Standalone", "multi_tf_filter": False}),
    ("daily_trend", "daily_trend_breakout", "swing",
     {"tf": "1d", "sl": 4.0, "tp": 5.0, "intraday": False,
      "strategy": "Daily Trend Breakout"}),
    ("orb_scan", "full_universe", "intraday",
     {"tf": "5m", "sl": 1.0, "tp": 2.0, "intraday": True,
      "strategy": "ML Opening Breakout"}),
]


def _load_watchlists() -> dict:
    if not os.path.exists(WATCHLIST_PATH):
        raise SystemExit(f"  [error] watchlist file not found: {WATCHLIST_PATH}")
    return json.load(open(WATCHLIST_PATH))


def _fetch(symbol: str, tf: str) -> pd.DataFrame | None:
    """Fetch OHLCV for ``symbol`` at ``tf`` using the configured data source."""
    if _pt.USE_UPSTOX:
        return _pt._upstox_live(symbol, tf)
    return _yf_live(f"{symbol}.NS", tf)


def _scan_symbol(sym: str, spec: dict, allow_shorts: bool,
                 force_short: bool = False) -> dict | None:
    """Scan one symbol with one spec. Returns a signal dict or None.

    ``force_short`` restricts the reported signal to SHORT direction (used by
    the dedicated SHORT tier); ``allow_shorts`` only permits SHORT to leak from
    a normal LONG tier.
    """
    tf = spec["tf"]
    intraday = spec["intraday"]
    try:
        stock = _fetch(sym, tf)
        if stock is None or len(stock) < WINDOW_SIZE + 5:
            return None
        # NSEI index symbol for yfinance is "^NSEI" (NOT "^NSEI.NS")
        nifty = _pt._upstox_live("^NSEI", tf) if _pt.USE_UPSTOX else _yf_live("^NSEI", tf)
        banknifty = _pt._upstox_live("^NSEBANK", tf) if _pt.USE_UPSTOX else _yf_live("^NSEBANK", tf)
        vix_1d = _pt._upstox_live("^INDIAVIX", "1d") if _pt.USE_UPSTOX else _yf_live("^INDIAVIX", "1d")
        stock_1d = _fetch(sym, "1d")
    except Exception:
        return None

    last_ts = stock["timestamp"].iloc[-1]
    today = last_ts.date() if hasattr(last_ts, "date") else last_ts
    current_price = float(stock["close"].iloc[-1])

    window = stock.tail(WINDOW_SIZE).reset_index(drop=True)
    nifty_win = nifty.tail(WINDOW_SIZE).reset_index(drop=True) if nifty is not None else None
    if nifty_win is None or len(nifty_win) < WINDOW_SIZE:
        nifty_win = window

    day_info = classify_today_day_type(upstox=_pt.USE_UPSTOX)
    day_type = day_info.get("day_type", "UNKNOWN")
    stock_type = _classify_stock_type(window, nifty_win, stock_1d, today)
    stock_30m = _pt._resample_safe(stock, 30)
    htf_ctx = build_htf_context(stock_30m, stock_1d, last_ts)
    intraday_remaining = _bars_until_close(last_ts) if intraday else None

    tuning = {"sl_mult": spec["sl"], "tp_mult": spec["tp"], "atr_period": 14}
    decision = decide_trade(
        window, f"{sym}.NS", tf,
        day_type, stock_type,
        nifty, stock_1d, stock_30m, last_ts,
        banknifty_df=banknifty,
        vix_daily=vix_1d,
        force_strategy=spec.get("strategy", ""),
        tuning_override=tuning,
        tuning_override_is_default=True,
        multi_tf_filter=spec.get("multi_tf_filter", True),
        intraday_mode=intraday,
        intraday_remaining_bars=intraday_remaining,
        htf_ctx=htf_ctx,
        original_symbol=sym,
    )
    if decision is None:
        return None
    if decision.direction == "SHORT" and not allow_shorts and not force_short:
        return None
    if force_short and decision.direction != "SHORT":
        return None

    risk = abs(decision.entry_price - decision.stop_loss)
    reward = abs(decision.take_profit - decision.entry_price)
    r_mult = (reward / risk) if risk > 0 else 0.0

    # Cache the full decision context so the price ticker can recompute this
    # signal's score/entry live as the LTP moves (without re-fetching bars).
    category = "intraday" if intraday else "swing"
    with _cache_lock:
        _cached_scan_data[f"{sym}:{tf}:{category}"] = {
            "window": window.copy(),
            "yf_sym": f"{sym}.NS",
            "tf": tf,
            "day_type": day_type,
            "stock_type": stock_type,
            "nifty_15m": nifty,
            "stock_1d": stock_1d,
            "stock_30m": stock_30m,
            "last_ts": last_ts,
            "banknifty_15m": banknifty,
            "vix_1d": vix_1d,
            "strategy_name": spec.get("strategy", ""),
            "multi_tf_filter": spec.get("multi_tf_filter", True),
            "tuning": tuning,
            "intraday": intraday,
            "htf_ctx": htf_ctx,
            "original_symbol": sym,
        }

    return {
        "symbol": sym,
        "tier": None,            # filled by caller
        "category": category,
        "tf": tf,
        "direction": decision.direction,
        "score": round(decision.score, 1),
        "entry": round(decision.entry_price, 2),
        "stop_loss": round(decision.stop_loss, 2),
        "take_profit": round(decision.take_profit, 2),
        "r_multiple": round(r_mult, 2),
        "price": round(current_price, 2),
        "strategy": spec.get("strategy", ""),
    }


def _scan_daily(sym: str) -> dict | None:
    """Scan one symbol with Daily Trend Breakout on 1d bars."""
    tf = "1d"
    try:
        stock = _fetch(sym, tf)
        if stock is None or len(stock) < 250:
            return None
        # Exclude today's incomplete bar (PIT — decisions use prior completed close)
        today = pd.Timestamp.now(tz="Asia/Kolkata").date()
        stock = stock[stock["timestamp"].dt.date < today].reset_index(drop=True)
        if len(stock) < 250:
            return None
        nifty_1d = _pt._upstox_live("^NSEI", tf) if _pt.USE_UPSTOX else _yf_live("^NSEI", tf)
    except Exception:
        return None

    current_price = float(stock["close"].iloc[-1])

    from strategies.daily_trend_strategy import DailyTrendBreakoutStrategy
    strategy = DailyTrendBreakoutStrategy()
    result = strategy.run(
        stock.tail(250).reset_index(drop=True), f"{sym}.NS", tf,
        nifty_df=nifty_1d, nifty_daily=nifty_1d,
    )
    if not result or not result.trade_candidates:
        return None

    tc = result.trade_candidates[0]
    risk = abs(tc.entry_price - tc.stop_loss) if tc.stop_loss else 0.01
    reward = abs(tc.take_profit - tc.entry_price) if tc.take_profit else 0.01
    r_mult = (reward / risk) if risk > 0 else 0.0

    return {
        "symbol": sym,
        "tier": None,
        "category": "swing",
        "tf": tf,
        "direction": tc.direction,
        "score": round(tc.ranking_score, 1),
        "entry": round(tc.entry_price, 2),
        "stop_loss": round(tc.stop_loss, 2) if tc.stop_loss else 0,
        "take_profit": round(tc.take_profit, 2) if tc.take_profit else 0,
        "r_multiple": round(r_mult, 2),
        "price": round(current_price, 2),
        "strategy": "Daily Trend Breakout",
    }


def _scan_orb(sym: str) -> dict | None:
    """Scan one symbol with ML Opening Breakout on 5m bars."""
    tf = "5m"
    try:
        stock = _fetch(sym, tf)
        if stock is None or len(stock) < 130:
            return None
        nifty_5m = _pt._upstox_live("^NSEI", tf) if _pt.USE_UPSTOX else _yf_live("^NSEI", tf)
        nifty_1d = _pt._upstox_live("^NSEI", "1d") if _pt.USE_UPSTOX else _yf_live("^NSEI", "1d")
    except Exception:
        return None

    current_price = float(stock["close"].iloc[-1])

    from strategies.orb_ml_strategy import MLOpeningBreakoutStrategy
    strategy = MLOpeningBreakoutStrategy()
    result = strategy.run(
        stock.tail(130).reset_index(drop=True), f"{sym}.NS", tf,
        nifty_df=nifty_5m, nifty_daily=nifty_1d,
    )
    if not result or not result.trade_candidates:
        return None

    tc = result.trade_candidates[0]
    risk = abs(tc.entry_price - tc.stop_loss) if tc.stop_loss else 0.01
    reward = abs(tc.take_profit - tc.entry_price) if tc.take_profit else 0.01
    r_mult = (reward / risk) if risk > 0 else 0.0

    return {
        "symbol": sym,
        "tier": None,
        "category": "intraday",
        "tf": tf,
        "direction": tc.direction,
        "score": round(tc.ranking_score, 1),
        "entry": round(tc.entry_price, 2),
        "stop_loss": round(tc.stop_loss, 2) if tc.stop_loss else 0,
        "take_profit": round(tc.take_profit, 2) if tc.take_profit else 0,
        "r_multiple": round(r_mult, 2),
        "price": round(current_price, 2),
        "strategy": "ML Opening Breakout",
    }


def _run_scan(allow_shorts: bool) -> tuple[list[dict], int]:
    from scripts.trade_history import is_traded, record_signals
    data = _load_watchlists()
    with _cache_lock:
        _cached_scan_data.clear()

    now = pd.Timestamp.now(tz="Asia/Kolkata")
    hour_min = now.hour + now.minute / 60.0
    today_date = now.strftime("%Y-%m-%d")
    in_opening_window = 9.25 <= hour_min < 10.5
    scan_deadline = time.time() + 180  # 3-minute max per scan

    scanned: dict[tuple, set] = {}
    signals: list[dict] = []
    total_scanned = 0

    for tier_label, wl_key, category, spec in SCAN_TIERS:
        if time.time() > scan_deadline:
            _log.warning("scan deadline hit — returning %d signals from %d scanned", len(signals), total_scanned)
            break

        force_short = spec.get("force_short", False)
        strategy = spec.get("strategy", "")
        if wl_key not in data:
            continue
        key = (spec["tf"], spec["intraday"], force_short, strategy)
        done = scanned.setdefault(key, set())

        if strategy == "Daily Trend Breakout":
            with _daily_scan_lock:
                if _daily_scan_date == today_date:
                    continue
                _daily_scan_date = today_date
            for sym in data[wl_key]:
                if time.time() > scan_deadline:
                    break
                if sym in done:
                    continue
                done.add(sym)
                total_scanned += 1
                sig = _scan_daily(sym)
                if sig is not None:
                    sig["tier"] = tier_label
                    signals.append(sig)
            continue

        if strategy == "ML Opening Breakout":
            if not in_opening_window:
                continue
            for sym in data[wl_key]:
                if time.time() > scan_deadline:
                    break
                if sym in done:
                    continue
                done.add(sym)
                total_scanned += 1
                sig = _scan_orb(sym)
                if sig is not None:
                    sig["tier"] = tier_label
                    signals.append(sig)
            continue

        for sym in data[wl_key]:
            if time.time() > scan_deadline:
                break
            if sym in done:
                continue
            done.add(sym)
            total_scanned += 1
            sig = _scan_symbol(sym, spec, allow_shorts, force_short)
            if sig is not None:
                sig["tier"] = tier_label
                signals.append(sig)

    fresh = [s for s in signals if not is_traded(s["symbol"], s["direction"])]
    skipped = len(signals) - len(fresh)
    if skipped:
        _log.info("trade_history: filtered %d already-traded signals", skipped)

    if fresh:
        record_signals(fresh)

    fresh.sort(key=lambda s: (0 if s["category"] == "intraday" else 1, -s["score"]))

    stale_count = 0
    for i in reversed(range(len(fresh))):
        sig = fresh[i]
        live = _latest_prices.get(sig["symbol"])
        if live is not None:
            entry = sig["entry"]
            if sig["direction"] == "LONG" and live > entry * 1.002:
                stale_count += 1
                fresh.pop(i)
            elif sig["direction"] == "SHORT" and live < entry * 0.998:
                stale_count += 1
                fresh.pop(i)
    if stale_count:
        _log.info("filtered %d stale signals (live price past entry)", stale_count)

    return fresh, total_scanned


def _print_report(signals: list[dict], source: str, scanned_n: int) -> None:
    now = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M %Z")
    intraday = [s for s in signals if s["category"] == "intraday"]
    swing = [s for s in signals if s["category"] == "swing"]

    print("=" * 74)
    print(f"  MARKET SCAN — {now}   source: {source}   scans: {scanned_n}")
    print("=" * 74)

    def _strategy_label(name: str) -> str:
        return {"Relative Strength Momentum": "RSM",
                "Combined Swing": "Cmb",
                "Manual Institutional (time-gated)": "Man",
                "ML Standalone": "ML",
                "Daily Trend Breakout": "DT",
                "ML Opening Breakout": "ORB",
                }.get(name, "IP")

    def _table(rows: list[dict], header: str, with_tf: bool) -> None:
        print(f"\n── {header} ({len(rows)}) ──")
        if not rows:
            print("  (no signals)")
            return
        if with_tf:
            print(f"  {'SYMBOL':10s} {'STRAT':4s} {'SCORE':>5s} {'DIR':5s} {'ENTRY':>10s} "
                  f"{'SL':>10s} {'TP':>10s} {'R':>5s} {'TF':>4s}")
        else:
            print(f"  {'SYMBOL':10s} {'STRAT':4s} {'SCORE':>5s} {'DIR':5s} {'ENTRY':>10s} "
                  f"{'SL':>10s} {'TP':>10s} {'R':>5s}")
        for s in rows:
            label = _strategy_label(s.get("strategy", "IP"))
            line = (f"  {s['symbol']:10s} {label:4s} {s['score']:>5.0f} {s['direction']:5s} "
                    f"₹{s['entry']:>9.2f} ₹{s['stop_loss']:>9.2f} "
                    f"₹{s['take_profit']:>9.2f} {s['r_multiple']:>5.2f}")
            if with_tf:
                line += f" {s['tf']:>4s}"
            print(line)

    _table(intraday, "INTRADAY TRADES (15m)", with_tf=False)
    _table(swing, "SWING TRADES (15m / 1h)", with_tf=True)

    print(f"\n── SUMMARY ──")
    print(f"  INTRADAY: {len(intraday)}  |  SWING: {len(swing)}  |  TOTAL: {len(signals)}")
    print(f"  Tiers: RSM→Combined→Manual_mor→Manual_eve→ML_Standalone→Daily_Trend→ORB")


# ── Web dashboard server (--serve) ────────────────────────────────────────────
_latest_scan: dict = {"ts": "", "signals": [], "scanned_n": 0,
                      "status": "starting", "cycles": 0, "uptime": 0.0,
                      "nifty": None, "day_type": "—", "day_confidence": "",
                      "scanning": False, "portfolio": None,
                      "recent_trades": [], "open_trades": [],
                      "holding_stats": None}
_latest_prices: dict[str, float] = {}  # symbol → current price for M2M
# Per-signal scan context, keyed by "SYM:tf:category". Stores everything needed
# to re-run decide_trade() with a live LTP substituted for the last bar's close,
# so the price ticker thread can refresh a signal's score/entry/SL/TP between
# full scans (see _live_recompute). Rebuilt on every full scan.
_cached_scan_data: dict[str, dict] = {}
_cache_lock = threading.Lock()
_scan_lock = threading.Lock()
_server_start = time.time()
# Once-per-day gate for Daily Trend Breakout scan
_daily_scan_date: str = ""
_daily_scan_lock = threading.Lock()

# Persistent WebSocket feed for live prices (started once, read by _fetch_live_prices
# instead of opening a new batch WS connection per ticker cycle).
_WS_FEED: Any = None
_WS_MAX_SYMBOLS = int(os.environ.get("INST_WS_MAX_SYMBOLS", "9999"))


def _start_ws_feed() -> None:
    """Start a persistent WebSocket feed for the scanner.

    Subscribes all symbols across every SCAN_TIERS watchlist plus NSEI, BANKNIFTY,
    and INDIAVIX so the dashboard price ticker reads from the buffer in real-time.
    """
    global _WS_FEED
    from config.daemon_config import UPSTOX
    from data.upstox.upstox_live_feed import UpstoxLiveFeed
    token = UPSTOX.get("access_token", "")
    if not token:
        _log.warning("ws-feed: no Upstox token — persistent WS disabled")
        return
    try:
        data = _load_watchlists()
    except SystemExit:
        _log.warning("ws-feed: no watchlists — persistent WS disabled")
        return
    syms: set[str] = {"^NSEI", "^NSEBANK", "^INDIAVIX"}
    for _, wl_key, _, _ in SCAN_TIERS:
        syms.update(data.get(wl_key, []))
    keys: list[str] = []
    for sym in sorted(syms):
        k = _pt._instrument_key_for(sym)
        if k:
            keys.append(k)
    if len(keys) > _WS_MAX_SYMBOLS:
        _log.info("ws-feed: %d symbols exceeds cap of %d; subscribing first %d",
                  len(keys), _WS_MAX_SYMBOLS, _WS_MAX_SYMBOLS)
        keys = keys[:_WS_MAX_SYMBOLS]
    if not keys:
        return
    try:
        feed = UpstoxLiveFeed(access_token=token)
        feed.start(keys, mode="full")
        _WS_FEED = feed
        _log.info("ws-feed: persistent stream started (%d keys, mode=full)", len(keys))
    except Exception as e:
        _log.warning("ws-feed: could not start persistent stream: %s", e)


def _get_lan_ip() -> str:
    """Get the primary LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("192.168.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"


def _unrealized_pnl(p: dict) -> float:
    """Compute unrealized P&L for a position using the latest live price."""
    px = _latest_prices.get(p["symbol"])
    if px is None:
        return 0.0
    if p["direction"] == "LONG":
        return round(p["shares"] * (px - p["entry_price"]), 2)
    else:
        return round(p["shares"] * (p["entry_price"] - px), 2)


def _load_paper_state() -> dict | None:
    """Load paper trader state file safely. Returns None if missing/invalid."""
    path = "data/paper_portfolio.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            state = json.load(f)

        # Multi-strategy state (new format)
        if "strategies" in state:
            strategies = state["strategies"]
            all_positions = []
            total_cash = 0.0
            total_day_entries = 0
            total_peak = 0.0
            for sname, sstate in strategies.items():
                cash = sstate.get("cash", 0)
                total_cash += cash
                total_day_entries += sstate.get("day_entries", 0)
                total_peak = max(total_peak, sstate.get("peak_equity", 0))
                for p in sstate.get("positions", []):
                    p["strategy"] = sname
                    p["price"] = _latest_prices.get(p["symbol"])
                    p["unrealized_pnl"] = _unrealized_pnl(p)
                    all_positions.append(p)

            # Cross-reference with trade_history — hide stale positions whose
            # trade was already closed (crash after record_trade_exit but before
            # _save_state removed the position).
            try:
                from scripts.trade_history import open_trades
                open_keys = {
                    (t["symbol"], t["direction"], t.get("strategy"), t.get("mode"))
                    for t in open_trades()
                }
                filtered = []
                for p in all_positions:
                    key = (p["symbol"], p["direction"],
                           p.get("strategy"), p.get("mode"))
                    if key in open_keys:
                        filtered.append(p)
                    else:
                        print(f"[paper-state] dropped stale position "
                              f"{p['symbol']} ({p.get('strategy')}) "
                              f"— no matching OPEN trade")
                all_positions = filtered
            except Exception as e:
                print(f"[paper-state] WARN trade_history cross-ref failed: {e}")

            return {
                "cash": total_cash,
                "day": state.get("day", ""),
                "day_entries": total_day_entries,
                "positions": all_positions,
                "trades": len(state.get("trades", [])),
                "peak_equity": total_peak,
                "strategies": {
                    sname: {
                        "cash": s.get("cash", 0),
                        "day_entries": s.get("day_entries", 0),
                        "peak_equity": s.get("peak_equity", 0),
                        "positions": len(s.get("positions", [])),
                    }
                    for sname, s in strategies.items()
                },
            }

        # Legacy flat state
        positions = state.get("positions", [])
        for p in positions:
            p["price"] = _latest_prices.get(p["symbol"])
            p["unrealized_pnl"] = _unrealized_pnl(p)

        # Cross-reference with trade_history (same as multi-strategy path)
        try:
            from scripts.trade_history import open_trades
            open_keys = {
                (t["symbol"], t["direction"], t.get("strategy"), t.get("mode"))
                for t in open_trades()
            }
            filtered = []
            for p in positions:
                key = (p["symbol"], p["direction"],
                       p.get("strategy"), p.get("mode"))
                if key in open_keys:
                    filtered.append(p)
                else:
                    print(f"[paper-state] dropped stale position "
                          f"{p['symbol']} ({p.get('strategy')}) "
                          f"— no matching OPEN trade")
            positions = filtered
        except Exception as e:
            print(f"[paper-state] WARN trade_history cross-ref failed: {e}")

        return {
            "cash": state.get("cash", 0),
            "day": state.get("day", ""),
            "day_entries": state.get("day_entries", 0),
            "positions": positions,
            "trades": len(state.get("trades", [])),
            "peak_equity": state.get("peak_equity", 0),
        }
    except Exception:
        return None


def _classify_day_type(nifty_intra, nifty_daily) -> dict:
    """Classify day type from raw NIFTY data."""
    from engines.day_type_engine import DayTypeEngine
    try:
        if nifty_intra is None or nifty_intra.empty:
            return {"day_type": "—", "day_confidence": ""}
        today_data = nifty_intra.copy()
        if "timestamp" in today_data.columns:
            today_data = today_data.set_index("timestamp")
        last_ts = today_data.index[-1]
        result = DayTypeEngine.classify_historical(
            timestamp=last_ts,
            nifty_intraday=today_data.reset_index(),
            nifty_daily=nifty_daily,
        )
        return {
            "day_type": result.get("type", "—"),
            "day_confidence": result.get("confidence", ""),
        }
    except Exception:
        return {"day_type": "—", "day_confidence": ""}


def _fetch_market_context(upstox: bool) -> dict:
    """Fetch market context: NIFTY price/change, day type."""
    ctx = {"nifty": None, "nifty_change_pct": 0, "day_type": "—", "day_confidence": ""}
    try:
        if upstox:
            nifty_15m = _pt._upstox_live("^NSEI", "15m")
            nifty_1d = _pt._upstox_live("^NSEI", "1d")
        else:
            nifty_15m = _yf_live("^NSEI", "15m")
            nifty_1d = _yf_live("^NSEI", "1d")
        if nifty_15m is not None and not nifty_15m.empty:
            closes = nifty_15m["close"].astype(float)
            ctx["nifty"] = round(float(closes.iloc[-1]), 2)
            if len(closes) >= 2:
                pct = ((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]) * 100
                ctx["nifty_change_pct"] = round(float(pct), 2)

        # Override Nifty price with live quote when using Upstox (historical
        # 15m bars may not include today's incomplete candle → stale price).
        if upstox:
            try:
                from config.daemon_config import UPSTOX
                import requests
                token = UPSTOX.get("access_token", "")
                if token:
                    url = "https://api.upstox.com/v2/market-quote/quotes"
                    resp = requests.get(url, params={"symbol": "NSE_INDEX|Nifty 50"},
                                        headers={"Accept": "application/json",
                                                 "Authorization": f"Bearer {token}"},
                                        timeout=8)
                    if resp.status_code == 200:
                        data = resp.json().get("data", {}) or {}
                        quote = (data.get("NSE_INDEX:Nifty 50")
                                 or data.get("NSE_INDEX|Nifty 50") or {})
                        lp = quote.get("last_price")
                        if lp is not None:
                            ctx["nifty"] = round(float(lp), 2)
                        nc = quote.get("net_change")
                        ohlc = quote.get("ohlc") or {}
                        if nc is not None and ohlc.get("open"):
                            ctx["nifty_change_pct"] = round(
                                (float(nc) / float(ohlc["open"])) * 100, 2
                            )
            except Exception:
                pass

        day_info = _classify_day_type(nifty_15m, nifty_1d)
        ctx["day_type"] = day_info.get("day_type", "—")
        ctx["day_confidence"] = day_info.get("day_confidence", "")
    except Exception:
        pass
    return ctx


def _yf_live_price(symbol: str) -> float | None:
    """Lightweight yfinance price fetch (~1 request, fast)."""
    import yfinance as yf
    for interval in ("1m", "5m", "15m"):
        try:
            df = yf.download(f"{symbol}.NS", period="5d", interval=interval,
                             progress=False, auto_adjust=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return float(df["Close"].iloc[-1])
        except Exception:
            continue
    return None


def _fetch_live_prices(symbols: list[str], upstox: bool) -> dict[str, float]:
    """Fetch live prices for a list of symbols; returns {symbol: price}.

    With ``--upstox`` reads from the persistent WS stream buffer first
    (real-time, zero connect overhead), then falls back to a one-shot
    batch WS call for any symbol not yet in the buffer.
    """
    result: dict[str, float] = {}
    if not symbols:
        return result
    if upstox:
        missing: list[tuple[str, str]] = []  # (symbol, instrument_key)
        for sym in symbols:
            k = _pt._instrument_key_for(sym)
            if not k:
                continue
            if _WS_FEED is not None:
                try:
                    px = _WS_FEED.get_latest_price(k)
                    if px and px.get("close"):
                        result[sym] = round(float(px["close"]), 2)
                        continue
                except Exception:
                    pass
            missing.append((sym, k))
        # Fallback: one-shot batch WS for symbols not in the persistent stream
        if missing:
            from config.daemon_config import UPSTOX
            token = UPSTOX.get("access_token", "")
            if token:
                try:
                    from data.upstox.upstox_live_feed import UpstoxLiveFeed
                    feed = UpstoxLiveFeed(access_token=token)
                    batch = feed.get_live_batch(
                        [k for _, k in missing], mode="full", timeout=10
                    )
                    for sym, key in missing:
                        item = batch.get(key)
                        close = item.get("close") if item else None
                        if close:
                            result[sym] = round(float(close), 2)
                except Exception as e:
                    _log.warning("price_ticker WS fallback failed: %s", e)
    else:
        for sym in symbols:
            try:
                px = _yf_live_price(sym)
                if px is not None:
                    result[sym] = round(px, 2)
            except Exception:
                pass
    return result


def _live_recompute(key: str, ltp: float, cached: dict, orig_direction: str) -> dict | None:
    """Re-run ``decide_trade`` with the live LTP substituted for the last bar's
    close, so a signal's score/entry/SL/TP track the price between full scans.

    Returns the updated signal fields (score, entry, stop_loss, take_profit,
    r_multiple, price) or ``None`` if the signal no longer validates at the live
    price (score below threshold, HTF/last-bar gate fails, or direction flipped).
    All other decision context (NIFTY, daily bars, HTF, day/stock type) is reused
    from the cached full-scan snapshot — only the last bar's price is refreshed.
    """
    try:
        window = cached["window"].copy()
        last = len(window) - 1
        # Substitute the live price as the last bar's close; widen the bar's
        # high/low if the live tick has printed beyond the completed range.
        prev_hi = float(window.at[last, "high"])
        prev_lo = float(window.at[last, "low"])
        window.at[last, "close"] = ltp
        window.at[last, "high"] = max(prev_hi, ltp)
        window.at[last, "low"] = min(prev_lo, ltp)

        intraday = cached["intraday"]
        intraday_remaining = _bars_until_close(cached["last_ts"]) if intraday else None
        decision = decide_trade(
            window, cached["yf_sym"], cached["tf"],
            cached["day_type"], cached["stock_type"],
            cached["nifty_15m"], cached["stock_1d"], cached["stock_30m"],
            cached["last_ts"],
            banknifty_df=cached["banknifty_15m"],
            vix_daily=cached["vix_1d"],
            force_strategy=cached["strategy_name"],
            tuning_override=cached["tuning"],
            tuning_override_is_default=True,
            multi_tf_filter=cached.get("multi_tf_filter", True),
            intraday_mode=intraday,
            intraday_remaining_bars=intraday_remaining,
            htf_ctx=cached["htf_ctx"],
            original_symbol=cached["original_symbol"],
        )
        if decision is None or decision.direction != orig_direction:
            return None
        risk = abs(decision.entry_price - decision.stop_loss)
        reward = abs(decision.take_profit - decision.entry_price)
        r_mult = (reward / risk) if risk > 0 else 0.0
        return {
            "score": round(decision.score, 1),
            "entry": round(decision.entry_price, 2),
            "stop_loss": round(decision.stop_loss, 2),
            "take_profit": round(decision.take_profit, 2),
            "r_multiple": round(r_mult, 2),
            "price": round(ltp, 2),
        }
    except Exception as e:
        _log.warning("live_recompute failed for %s: %s", key, e)
        return None


def _price_ticker_thread(interval_sec: int = 30, upstox: bool = False) -> None:
    """Keep prices + portfolio fresh without re-running the full scan."""
    while True:
        time.sleep(interval_sec)
        with _scan_lock:
            cur = [dict(s) for s in _latest_scan.get("signals", [])]

        # Collect all symbols to refresh: signals + open positions
        all_syms = set()
        for sig in cur:
            all_syms.add(sig["symbol"])
        portfolio = _load_paper_state()
        if portfolio:
            for p in portfolio.get("positions", []):
                all_syms.add(p["symbol"])

        if all_syms:
            prices = _fetch_live_prices(list(all_syms), upstox)
            with _scan_lock:
                _latest_prices.update(prices)

        # Live score/entry refresh: re-run decide_trade for each signal with the
        # current LTP so score, entry, SL, TP and R track the price between full
        # scans. Skipped while a full scan is running (avoids racing decide_trade
        # calls) — the scan itself refreshes everything on completion. Done on
        # the local ``cur`` copy + snapshots, so no lock is held during the CPU
        # work (decide_trade); the result is published under the lock below.
        with _scan_lock:
            scanning = _latest_scan.get("scanning", False)
            price_snapshot = dict(_latest_prices)
        with _cache_lock:
            cache_snapshot = dict(_cached_scan_data)

        refreshed = []
        for sig in cur:
            live = price_snapshot.get(sig["symbol"])
            if live is None:
                refreshed.append(sig)
                continue
            key = f"{sig['symbol']}:{sig['tf']}:{sig['category']}"
            cached = None if scanning else cache_snapshot.get(key)
            if cached is not None:
                upd = _live_recompute(key, live, cached, sig["direction"])
                if upd is None:
                    continue  # no longer a valid signal at the live price → drop
                sig.update(upd)
                refreshed.append(sig)
            else:
                # No cache entry (or mid-scan): refresh price only + legacy
                # stale-entry filter (drop when live price has passed the entry).
                sig["price"] = live
                entry = sig["entry"]
                if sig["direction"] == "LONG" and live > entry * 1.002:
                    continue
                if sig["direction"] == "SHORT" and live < entry * 0.998:
                    continue
                refreshed.append(sig)
        cur = refreshed

        # Reload portfolio + trades after price update so M2M/trade-history stay fresh
        from scripts.trade_history import open_trades, recent_trades
        portfolio = _load_paper_state()
        _recent = recent_trades(10)
        _open = open_trades()
        ts = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M %Z")
        with _scan_lock:
            _latest_scan["signals"] = cur
            _latest_scan["portfolio"] = portfolio
            _latest_scan["recent_trades"] = _recent
            _latest_scan["open_trades"] = _open
            _latest_scan["ts"] = ts


def _compute_holding_stats() -> dict:
    """Average holding time for CLOSED trades, grouped by trading mode.

    Reads the shared trade-history log, parses opened_at/closed_at for closed
    trades, and returns hours-held statistics. Trades without a ``mode`` field
    (pre-change history) are counted in the overall average but not in the
    per-mode breakdown.

    Returns
    -------
    dict  keys: avg_hours, avg_hours_intraday, avg_hours_swing,
                trade_count, mode_counts
    """
    from datetime import datetime
    from scripts.trade_history import _load
    data = _load()
    trades = data.get("trades", [])
    total_sec = 0.0
    n = 0
    intraday_sec = 0.0
    intraday_n = 0
    swing_sec = 0.0
    swing_n = 0
    mode_counts = {"intraday": 0, "swing": 0}
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        opened = t.get("opened_at")
        closed = t.get("closed_at")
        if not opened or not closed:
            continue
        try:
            o = datetime.strptime(opened.split(" IST")[0], "%Y-%m-%d %H:%M")
            c = datetime.strptime(closed.split(" IST")[0], "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        sec = (c - o).total_seconds()
        if sec < 0:
            continue
        total_sec += sec
        n += 1
        mode = t.get("mode")
        if mode in ("intraday", "swing"):
            mode_counts[mode] += 1
            if mode == "intraday":
                intraday_sec += sec
                intraday_n += 1
            else:
                swing_sec += sec
                swing_n += 1
    return {
        "avg_hours": round(total_sec / 3600.0 / n, 2) if n else None,
        "avg_hours_intraday": round(intraday_sec / 3600.0 / intraday_n, 2) if intraday_n else None,
        "avg_hours_swing": round(swing_sec / 3600.0 / swing_n, 2) if swing_n else None,
        "trade_count": n,
        "mode_counts": mode_counts,
    }


def _publish(signals: list[dict], scanned_n: int, status: str = "ok",
             upstox: bool = False) -> None:
    ctx = _fetch_market_context(upstox)
    portfolio = _load_paper_state()
    from scripts.trade_history import recent_trades, open_trades
    _recent = recent_trades(10)
    _open = open_trades()
    _holding = _compute_holding_stats()
    with _scan_lock:
        _latest_scan.update({
            "ts": pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M %Z"),
            "signals": signals,
            "scanned_n": scanned_n,
            "status": status,
            "cycles": _latest_scan.get("cycles", 0) + 1,
            "nifty": ctx["nifty"],
            "nifty_change_pct": ctx["nifty_change_pct"],
            "day_type": ctx["day_type"],
            "day_confidence": ctx["day_confidence"],
            "portfolio": portfolio,
            "source": "upstox" if upstox else "yfinance",
            "recent_trades": _recent,
            "open_trades": _open,
            "holding_stats": _holding,
        })


def _scan_worker(allow_shorts: bool, interval_min: int, source: str) -> None:
    """Background thread: re-scans on a timer, publishes to ``_latest_scan``."""
    from data.utils.market_hours import is_market_open, next_market_open
    upstox_flag = _pt.USE_UPSTOX
    while True:
        now = pd.Timestamp.now(tz="Asia/Kolkata")
        open_flag, _, _ = is_market_open(now)
        if open_flag:
            with _scan_lock:
                _latest_scan["scanning"] = True
            try:
                signals, scanned_n = _run_scan(allow_shorts)
                _publish(signals, scanned_n, "ok", upstox=upstox_flag)
            except Exception as e:
                _publish([], 0, f"error: {e}", upstox=upstox_flag)
            with _scan_lock:
                _latest_scan["scanning"] = False
        else:
            with _scan_lock:
                _latest_scan["status"] = "closed — market not open"
            nxt = next_market_open(now)
            sleep_s = max(60, int((nxt - now).total_seconds()))
            time.sleep(sleep_s)
            continue
        time.sleep(interval_min * 60)


_DASHBOARD_HTML = None  # deprecated: dashboard.html is now read fresh per request


def _load_dashboard_html() -> str:
    # Read fresh from disk on every request so dashboard.html edits take effect
    # without restarting the scanner. The "/" route is only hit on a full page
    # load (the 15s auto-refresh polls /api/latest, not "/"), so the tiny file
    # read is negligible.
    path = os.path.join(os.path.dirname(__file__), "..", "web", "dashboard.html")
    with open(path) as f:
        return f.read()


class _ScanHTTPHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/dashboard", "/index.html"):
            html = _load_dashboard_html().encode("utf-8")
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/api/latest":
            with _scan_lock:
                payload = dict(_latest_scan)
                payload["uptime"] = round(time.time() - _server_start, 1)
            self._send(200, json.dumps(payload).encode("utf-8"))
        elif self.path == "/api/status":
            with _scan_lock:
                payload = {k: _latest_scan[k] for k in
                           ("ts", "status", "cycles", "scanned_n")}
                payload["uptime"] = round(time.time() - _server_start, 1)
            self._send(200, json.dumps(payload).encode("utf-8"))
        else:
            self._send(404, b'{"error":"Not Found"}')

    def log_message(self, *args):  # silence default logging
        return


def _start_server(port: int) -> None:
    lan_ip = _get_lan_ip()
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), _ScanHTTPHandler)
    print(f"\n  \033[1mDashboard started\033[0m")
    print(f"    Local:   http://localhost:{port}/")
    print(f"    Network: http://{lan_ip}:{port}/")
    print(f"    API:     http://{lan_ip}:{port}/api/latest")
    print(f"  Ctrl-C to stop.\n")
    srv.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description="Live market scan → trade signals")
    ap.add_argument("--upstox", action="store_true",
                    help="Use Upstox real-broker feed instead of yfinance")
    ap.add_argument("--shorts", action="store_true",
                    help="Allow SHORT signals (off by default — not OOS-validated)")
    ap.add_argument("--loop", action="store_true", help="Re-scan every --interval min")
    ap.add_argument("--interval", type=int, default=5, help="Scan interval in minutes (default 5)")
    ap.add_argument("--list-tiers", action="store_true",
                    help="Print the scan tier plan and exit")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    ap.add_argument("--serve", action="store_true",
                    help="Start the web dashboard server (network-accessible)")
    ap.add_argument("--port", type=int, default=8080, help="Dashboard port (with --serve)")
    args = ap.parse_args()

    if args.list_tiers:
        print("Scan tiers (priority order):")
        for tier_label, wl_key, category, spec in SCAN_TIERS:
            print(f"  {tier_label:14s} wl={wl_key:14s} {category:8s} "
                  f"tf={spec['tf']} sl={spec['sl']} tp={spec['tp']} "
                  f"intraday={spec['intraday']}")
        return

    # configure data source for the shared fetchers
    _pt.USE_UPSTOX = args.upstox
    source = "upstox" if args.upstox else "yfinance"

    # Start persistent WebSocket feed for live price streaming (dashboard ticker).
    if args.upstox:
        _start_ws_feed()

    def _ws_cleanup():
        global _WS_FEED
        if _WS_FEED is not None:
            try:
                _WS_FEED.stop()
                _log.info("ws-feed: persistent stream stopped")
            except Exception:
                pass
    atexit.register(_ws_cleanup)

    if args.serve:
        # Seed initial context immediately so dashboard shows data on first load
        ctx = _fetch_market_context(args.upstox)
        with _scan_lock:
            _latest_scan.update({
                "nifty": ctx["nifty"],
                "nifty_change_pct": ctx["nifty_change_pct"],
                "day_type": ctx["day_type"],
                "day_confidence": ctx["day_confidence"],
                "source": source,
                "status": "starting",
            })
            _latest_scan["portfolio"] = _load_paper_state()

        worker = threading.Thread(
            target=_scan_worker, args=(args.shorts, args.interval, source),
            daemon=True,
        )
        worker.start()
        ticker = threading.Thread(
            target=_price_ticker_thread,
            args=(30, args.upstox),
            daemon=True,
        )
        ticker.start()
        try:
            _start_server(args.port)
        except KeyboardInterrupt:
            print("\n  [stop] dashboard server stopped.")
        return

    if not args.loop:
        signals, scanned_n = _run_scan(args.shorts)
        if args.json:
            print(json.dumps({"signals": signals}, indent=2))
        else:
            _print_report(signals, source, scanned_n)
        return

    print(f"  Market scan loop started (interval={args.interval}m, source={source}). "
          f"Ctrl-C to stop.")
    try:
        while True:
            now = pd.Timestamp.now(tz="Asia/Kolkata")
            from data.utils.market_hours import is_market_open
            open_flag, _, _ = is_market_open(now)
            if open_flag:
                signals, scanned_n = _run_scan(args.shorts)
                if args.json:
                    print(json.dumps({"ts": now.strftime("%Y-%m-%d %H:%M"),
                                      "signals": signals}, indent=2))
                else:
                    _print_report(signals, source, scanned_n)
            else:
                print(f"  [closed] market not open at {now:%H:%M} — skipping")
                from data.utils.market_hours import next_market_open
                nxt = next_market_open(now)
                sleep_s = max(60, int((nxt - now).total_seconds()))
            time.sleep(args.interval * 60)
    except KeyboardInterrupt:
        print("\n  [stop] scan loop interrupted.")


if __name__ == "__main__":
    main()
