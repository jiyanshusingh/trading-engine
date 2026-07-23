"""
Live Institutional Probability scan — produces TODAY's trade candidates using the
exact same decision path as the walk-forward backtest.

For every watchlist symbol it:
  1. fetches live NSE 15m / 1d data (plus NIFTY) via yfinance,
  2. classifies today's market regime (day_type) and the stock's behavior
     (stock_type) with the same engines the backtest uses per bar,
  3. builds the multi-timeframe context (real 30m resampled from 15m + 1d),
  4. calls ``decide_trade`` — the single shared decision function used by the
     backtester — forcing the validated "Institutional Probability" strategy
     (sl_mult=0.5, tp_mult=5.0, atr_period=14) and feeding it day_type /
     stock_type / htf_ctx,
  5. keeps only LONG candidates that clear the score threshold (>= 70) and the
     HTF alignment filter.

Because it shares ``decide_trade`` with scripts/backtest.py, a live signal is
exactly the decision the backtester would have taken on the same bar.

Usage:
    .venv/bin/python scripts/live_institutional_scan.py
    .venv/bin/python scripts/live_institutional_scan.py --max 6
    .venv/bin/python scripts/live_institutional_scan.py --universe full
    .venv/bin/python scripts/live_institutional_scan.py --no-intraday   # ignore EOD skip
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys as _sys
import time

_sys.path.insert(0, ".")

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
_log = logging.getLogger("live_inst_scan")

from scripts.backtest import (
    _normalize_timestamp_tz,
    _resample_1m_to,
    decide_trade,
    build_htf_context,
    WINDOW_SIZE,
)


def _yf_live(symbol: str, timeframe: str) -> pd.DataFrame | None:
    """Fetch fresh OHLCV from yfinance directly (no Upstox/cache path)."""
    import yfinance as yf

    interval_map = {"15m": "15m", "1h": "60m", "1d": "1d"}
    period_map = {"15m": "60d", "1h": "730d", "1d": "5y"}
    interval = interval_map.get(timeframe, "1d")
    period = period_map.get(timeframe, "1y")
    try:
        df = yf.download(symbol, period=period, interval=interval,
                         auto_adjust=False, progress=False)
    except Exception as e:
        _log.warning(f"yfinance failed for {symbol} @ {timeframe}: {e}")
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    rename = {"Datetime": "timestamp", "Date": "timestamp",
              "Open": "open", "High": "high", "Low": "low",
              "Close": "close", "Volume": "volume"}
    df = df.rename(columns={c: rename[c] for c in df.columns if c in rename})
    for c in ["timestamp", "open", "high", "low", "close", "volume"]:
        if c not in df.columns:
            df[c] = 0 if c == "volume" else None
    return _normalize_timestamp_tz(df)
from scripts.live_scanner import classify_today_day_type
from engines.stock_type_engine import StockTypeEngine

# Focused, reliable default universe; --universe full uses the broader list.
from scanner.watchlist import WATCHLIST as FOCUSED_WATCHLIST
from scripts.live_scanner import WATCHLIST as FULL_WATCHLIST

FORCE_STRATEGY = "Institutional Probability"
TUNING = {"sl_mult": 0.5, "tp_mult": 5.0, "atr_period": 14}
MIN_SCORE = 70  # mirrors LONG_MIN_SCORE in the engine / MIN_PROB in backtest


def _classify_stock_type(
    window_df: pd.DataFrame,
    nifty_window: pd.DataFrame,
    stock_daily: pd.DataFrame | None,
    today,
) -> str:
    """Mirror the backtest's per-bar StockTypeEngine classification."""
    stock_up = window_df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    nifty_up = nifty_window.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    daily_slice = None
    if stock_daily is not None and not stock_daily.empty:
        # Exclude today's bar — during live scanning it is still forming, so
        # including it leaks incomplete OHLC into the StockType classification
        # (the backtest uses ``< current_date`` for the same point-in-time reason).
        daily_slice = stock_daily[stock_daily["timestamp"].dt.date < today].tail(25).copy()
        if not daily_slice.empty:
            daily_slice = daily_slice.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
    try:
        res = StockTypeEngine.classify(stock_up, nifty_up, stock_daily=daily_slice)
        return res.get("type", "UNKNOWN")
    except Exception as e:
        _log.debug(f"StockTypeEngine failed: {e}")
        return "UNKNOWN"


def _bars_until_close(last_ts: pd.Timestamp) -> int:
    """Number of 15m bars remaining until the 15:30 IST market close.

    yfinance 15m bars are stamped at bar CLOSE, so the 15:15 bar is the last
    one — at that point 0 bars remain (do not enter on a closed bar). The +1
    previously assumed bar-open stamping and returned 2 on the final bar.
    """
    close = last_ts.normalize() + pd.Timedelta(hours=15, minutes=30)
    if last_ts.tzinfo is not None:
        close = close.tz_localize(None).tz_localize(last_ts.tz)
    remaining = int((close - last_ts).total_seconds() // (15 * 60))
    return max(0, remaining)


def main():
    parser = argparse.ArgumentParser(description="Live Institutional Probability scan")
    parser.add_argument("--max", type=int, default=None,
                        help="Limit number of symbols scanned (default: all in universe)")
    parser.add_argument("--universe", choices=["focused", "full"], default="focused",
                        help="Watchlist to scan (default: focused 10)")
    parser.add_argument("--delay", type=float, default=0.25,
                        help="Delay between symbols (s) to avoid rate limits")
    parser.add_argument("--no-intraday", action="store_true",
                        help="Do not skip entries in the last bars of the day")
    parser.add_argument("--output", default="data/live_institutional_scan.json")
    args = parser.parse_args()

    symbols = FULL_WATCHLIST if args.universe == "full" else FOCUSED_WATCHLIST
    if args.max is not None:
        symbols = symbols[: args.max]

    print("=" * 70)
    print(f"  LIVE INSTITUTIONAL PROBABILITY SCAN — "
          f"{pd.Timestamp.now(tz='Asia/Kolkata').strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"  Universe: {len(symbols)} symbols | Strategy: {FORCE_STRATEGY} | "
          f"SL={TUNING['sl_mult']} TP={TUNING['tp_mult']} ATR={TUNING['atr_period']}")
    print(f"  Threshold: LONG score >= {MIN_SCORE} | Multi-TF: ON")
    print("=" * 70)

    # Shared NIFTY context (regime + HTF daily trend)
    nifty_15m = _yf_live("^NSEI", "15m")
    nifty_1d = _yf_live("^NSEI", "1d")
    banknifty_15m = _yf_live("^NSEBANK", "15m")
    vix_1d = _yf_live("^INDIAVIX", "1d")

    day_info = classify_today_day_type()
    day_type = day_info.get("day_type", "UNKNOWN")
    print(f"\n  Day Type: {day_type}"
          + (f"  ({day_info.get('confidence', '')})" if day_info.get("confidence") else ""))
    if day_info.get("reasoning"):
        print(f"  Reasoning: {day_info['reasoning']}")
    print()

    candidates = []
    for idx, raw in enumerate(symbols, 1):
        sym = raw.replace(".NS", "").strip().upper()
        yf_sym = f"{sym}.NS"
        try:
            stock_15m = _yf_live(yf_sym, "15m")
            if stock_15m is None or len(stock_15m) < WINDOW_SIZE + 5:
                print(f"  [{idx}/{len(symbols)}] {sym:18s} — insufficient 15m data")
                time.sleep(args.delay)
                continue

            stock_1d = _yf_live(yf_sym, "1d")
            stock_30m = _resample_1m_to(stock_15m, 30)

            window = stock_15m.tail(WINDOW_SIZE).reset_index(drop=True)
            nifty_win = nifty_15m.tail(WINDOW_SIZE).reset_index(drop=True) if nifty_15m is not None else None
            if nifty_win is None or len(nifty_win) < WINDOW_SIZE:
                nifty_win = window  # degrade gracefully; regime still computed from stock

            last_ts = stock_15m["timestamp"].iloc[-1]
            today = last_ts.date() if hasattr(last_ts, "date") else last_ts
            stock_type = _classify_stock_type(window, nifty_win, stock_1d, today)

            htf_ctx = build_htf_context(stock_30m, stock_1d, last_ts)
            intraday_remaining = _bars_until_close(last_ts) if not args.no_intraday else None

            decision = decide_trade(
                window, yf_sym, "15m",
                day_type, stock_type,
                nifty_15m, stock_1d, stock_30m, last_ts,
                banknifty_df=banknifty_15m,
                vix_daily=vix_1d,
                force_strategy=FORCE_STRATEGY,
                tuning_override=TUNING,
                multi_tf_filter=True,
                intraday_mode=not args.no_intraday,
                intraday_remaining_bars=intraday_remaining,
                max_day_bar=None, day_bar=None,
                htf_ctx=htf_ctx,
            )

            if decision is None:
                print(f"  [{idx}/{len(symbols)}] {sym:18s} st={stock_type:12s} — no signal")
                time.sleep(args.delay)
                continue

            # The live config is LONG-only (SHORT is disabled); skip SHORT ideas.
            if decision.direction != "LONG":
                print(f"  [{idx}/{len(symbols)}] {sym:18s} st={stock_type:12s} — "
                      f"{decision.direction} signal (disabled)")
                time.sleep(args.delay)
                continue

            risk = abs(decision.entry_price - decision.stop_loss)
            reward = abs(decision.take_profit - decision.entry_price)
            rr = (reward / risk) if risk > 0 else 0.0
            candidates.append({
                "symbol": sym,
                "day_type": day_type,
                "stock_type": stock_type,
                "direction": decision.direction,
                "score": round(decision.score, 1),
                "entry": round(decision.entry_price, 2),
                "stop_loss": round(decision.stop_loss, 2),
                "take_profit": round(decision.take_profit, 2),
                "risk_pct": round(risk / decision.entry_price * 100, 2) if decision.entry_price else 0,
                "reward_pct": round(reward / decision.entry_price * 100, 2) if decision.entry_price else 0,
                "rr": round(rr, 2),
                "htf_pass": decision.htf_pass,
                "htf_reason": decision.htf_reason,
                "htf_ctx": {k: htf_ctx.get(k) for k in ("30m_trend", "30m_return_3", "1d_trend", "1d_return")},
                "rationale": decision.rationale,
            })
            print(f"  [{idx}/{len(symbols)}] {sym:18s} st={stock_type:12s} → "
                  f"{decision.direction} score={decision.score:.0f} entry={decision.entry_price:.2f} "
                  f"SL={decision.stop_loss:.2f} TP={decision.take_profit:.2f} RR={rr:.1f}")
            time.sleep(args.delay)
        except KeyboardInterrupt:
            break
        except Exception as e:
            _log.warning(f"  [{idx}/{len(symbols)}] {sym}: {e}")
            continue

    # ── Report ──
    candidates.sort(key=lambda x: -x["score"])
    print("\n" + "=" * 70)
    print(f"  TRADE CANDIDATES ({len(candidates)} — LONG, score >= {MIN_SCORE}, HTF aligned)")
    print("=" * 70)
    if candidates:
        for c in candidates:
            print(f"\n  {c['symbol']}  [{c['day_type']} / {c['stock_type']}]  score={c['score']}")
            print(f"    Entry : ₹{c['entry']:.2f}")
            print(f"    SL    : ₹{c['stop_loss']:.2f}  (-{c['risk_pct']:.1f}%)")
            print(f"    TP    : ₹{c['take_profit']:.2f}  (+{c['reward_pct']:.1f}%)  RR={c['rr']:.1f}")
            print(f"    HTF   : {c['htf_ctx']} — {c['htf_reason']}")
            if c["rationale"]:
                print(f"    Why   : {c['rationale']}")
    else:
        print("  (none — no symbol cleared the score threshold + HTF filter right now)")

    os.makedirs("data", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({
            "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M %Z"),
            "day_type": day_type,
            "strategy": FORCE_STRATEGY,
            "tuning": TUNING,
            "threshold": MIN_SCORE,
            "candidates": candidates,
        }, f, indent=2)
    print(f"\n  Saved {len(candidates)} candidates to {args.output}")
    print("=" * 70)


if __name__ == "__main__":
    main()
