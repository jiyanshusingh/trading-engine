"""
5m Opening-Range-Breakout (ORB) backtest harness.

Tests whether trading the break of the first 15m bar's range (09:15-09:30)
in the subsequent opening hour (09:30-10:00) is profitable, in BOTH directions.
Self-contained (does not use the decide_trade infrastructure) for speed.

Gap filters (--gap-mode):
  none        : trade both directions regardless of overnight gap (baseline)
  continue    : LONG only on gap-up days, SHORT only on gap-down days
  fade        : LONG only on gap-down days, SHORT only on gap-up days

Strategy:
  - Opening range = high/low of the first 15m bar (09:15-09:30)
  - Gap = today's first 5m open vs previous day's close
  - Entry: first 5m bar in 09:30-10:00 where close breaks above range_high (LONG)
    or below range_low (SHORT)
  - SL = 1.0 x range_height (distance to opposite side of range)
  - TP = rr x range_height (default rr=2.0)
  - Exit at TP/SL or at 10:30 (end of opening hour), whichever first
  - Costs: STT 0.025% (intraday), brokerage ~0.05%, slippage 0.05% (net ~0.125%)
"""
import json
import sys
import os
import glob
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from data.downloader.data_registry import get_bars

# Cost model (matching backtest.py net-of-costs)
STT = 0.00025          # intraday equity STT
BROKERAGE = 0.0005     # ~0.05%
SLIPPAGE = 0.0005      # ~0.05% per side (round trip = 2x)
COST_RATE = STT + BROKERAGE + 2 * SLIPPAGE  # ~0.125% of notional round-trip


def load_5m(symbol, days=120):
    df = get_bars(symbol, "5m", lookback_days=days)
    if df is None or len(df) < 30:
        return None
    df = df.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    df["date"] = df.index.date
    return df


def classify_gap(gap_pct, threshold):
    """Return 'up', 'down', or 'flat' for an overnight gap percentage."""
    if gap_pct > threshold:
        return "up"
    if gap_pct < -threshold:
        return "down"
    return "flat"


def backtest_symbol_orb(symbol, rr=2.0, max_hold_bars=12, gap_mode="none",
                        gap_threshold=0.003):
    df = load_5m(symbol)
    if df is None:
        return []
    trades = []
    # Precompute previous-day close for gap measurement
    days_sorted = sorted(df["date"].unique())
    last_close_by_date = {d: g["close"].iloc[-1] for d, g in df.groupby("date")}
    prev_close_map = {}
    for idx, d in enumerate(days_sorted):
        if idx > 0:
            prev_close_map[d] = last_close_by_date[days_sorted[idx - 1]]
    for day, g in df.groupby("date"):
        g = g.sort_index()
        # Need at least the first 15m bar (09:15-09:30) + entry window
        day_bars = g[g.index.time >= pd.Timestamp("09:15").time()]
        if len(day_bars) < 4:
            continue
        # Gap = first 5m bar open vs previous day's close
        today_open = day_bars["open"].iloc[0]
        prev_close = prev_close_map.get(day)
        if prev_close is None or prev_close <= 0:
            gap_pct = 0.0
        else:
            gap_pct = (today_open - prev_close) / prev_close
        gap_dir = classify_gap(gap_pct, gap_threshold)
        # Opening range = first 15 minutes (09:15-09:30)
        open_range = day_bars[day_bars.index.time <= pd.Timestamp("09:30").time()]
        if len(open_range) < 1:
            continue
        range_high = open_range["high"].max()
        range_low = open_range["low"].min()
        range_h = range_high - range_low
        if range_h <= 0:
            continue
        # Entry window: bars from 09:30 to 10:00 (exclusive of first bar)
        entry_window = day_bars[(day_bars.index.time > pd.Timestamp("09:30").time()) &
                                (day_bars.index.time <= pd.Timestamp("10:00").time())]
        if len(entry_window) == 0:
            continue
        # Look for first breakout
        entered = False
        for i, bar in entry_window.iterrows():
            close = bar["close"]
            if close > range_high:
                direction = "LONG"
                entry = close
                sl = entry - range_h       # 1x range below
                tp = entry + rr * range_h
                entered = True
                break
            elif close < range_low:
                direction = "SHORT"
                entry = close
                sl = entry + range_h       # 1x range above
                tp = entry - rr * range_h
                entered = True
                break
        if not entered:
            continue
        # Gap-mode direction filter
        if gap_mode == "continue":
            if direction == "LONG" and gap_dir != "up":
                continue
            if direction == "SHORT" and gap_dir != "down":
                continue
        elif gap_mode == "fade":
            if direction == "LONG" and gap_dir != "down":
                continue
            if direction == "SHORT" and gap_dir != "up":
                continue
        # Simulate until TP/SL or 10:30
        exit_window = entry_window[entry_window.index > i]
        # Also include bars up to 10:30
        late = day_bars[(day_bars.index.time > pd.Timestamp("10:00").time()) &
                        (day_bars.index.time <= pd.Timestamp("10:30").time())]
        sim = pd.concat([exit_window, late]).sort_index()
        result = None
        exit_px = None
        bars_held = 0
        for j, b in sim.iterrows():
            bars_held += 1
            if direction == "LONG":
                if b["low"] <= sl:
                    result = "LOSS"; exit_px = sl; break
                if b["high"] >= tp:
                    result = "WIN"; exit_px = tp; break
            else:
                if b["high"] >= sl:
                    result = "LOSS"; exit_px = sl; break
                if b["low"] <= tp:
                    result = "WIN"; exit_px = tp; break
            if bars_held >= max_hold_bars:
                result = "WIN" if (b["close"] - entry) * (1 if direction == "LONG" else -1) > 0 else "LOSS"
                exit_px = b["close"]
                break
        if result is None:
            # Hold to end of sim (use last close)
            last = sim.iloc[-1]["close"]
            result = "WIN" if (last - entry) * (1 if direction == "LONG" else -1) > 0 else "LOSS"
            exit_px = last
        # PnL (notional-based, 1 share equivalent -> scale by 1/entry)
        gross_ret = (exit_px - entry) / entry * (1 if direction == "LONG" else -1)
        net_ret = gross_ret - COST_RATE
        trades.append({
            "symbol": symbol, "direction": direction, "entry": entry,
            "exit": exit_px, "result": result, "gross_ret": gross_ret,
            "net_ret": net_ret, "range_h_pct": range_h / entry,
            "entry_time": str(i), "bars_held": bars_held,
            "gap_pct": gap_pct, "gap_dir": gap_dir,
        })
    return trades


def summarize(label, trades):
    if not trades:
        print(f"  {label}: 0 trades")
        return
    df = pd.DataFrame(trades)
    wins = (df["result"] == "WIN").sum()
    print(f"  {label}: {len(df)} trades | WR {100*wins/len(df):.1f}% | "
          f"avg net {df['net_ret'].mean()*100:.3f}% | sum net {df['net_ret'].sum()*100:.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-mode", choices=["none", "continue", "fade"], default="none")
    ap.add_argument("--gap-threshold", type=float, default=0.003)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=0, help="limit symbols (debug)")
    args = ap.parse_args()

    files = glob.glob("data/cache/5m/*.parquet")
    symbols = sorted(os.path.basename(f).replace(".parquet", "") for f in files)
    if args.limit:
        symbols = symbols[:args.limit]
    print(f"[{args.gap_mode}] Testing ORB on {len(symbols)} symbols with 5m data "
          f"(gap_threshold={args.gap_threshold*100:.2f}%)")

    all_trades = []
    for sym in symbols:
        try:
            t = backtest_symbol_orb(sym, rr=args.rr, gap_mode=args.gap_mode,
                                    gap_threshold=args.gap_threshold)
            all_trades.extend(t)
        except Exception as e:
            pass

    print(f"Total ORB trades: {len(all_trades)}")
    if not all_trades:
        print("No trades generated")
        return

    df = pd.DataFrame(all_trades)
    wins = (df["result"] == "WIN").sum()
    print(f"WR: {100*wins/len(df):.1f}%")
    print(f"Avg net ret/trade: {df['net_ret'].mean()*100:.3f}%")
    print(f"Total net ret (sum): {df['net_ret'].sum()*100:.2f}%")
    print(f"Avg range height %: {df['range_h_pct'].mean()*100:.2f}%")

    # By direction
    for d in ["LONG", "SHORT"]:
        sub = df[df["direction"] == d]
        if len(sub):
            w = (sub["result"] == "WIN").sum()
            print(f"  {d}: {len(sub)} trades, WR {100*w/len(sub):.1f}%, "
                  f"avg net {sub['net_ret'].mean()*100:.3f}%, sum {sub['net_ret'].sum()*100:.2f}%")

    # By gap direction (regardless of filter)
    print("  -- by gap direction --")
    for gd in ["up", "down", "flat"]:
        sub = df[df["gap_dir"] == gd]
        if len(sub):
            w = (sub["result"] == "WIN").sum()
            print(f"    gap {gd:5s}: {len(sub)} trades, WR {100*w/len(sub):.1f}%, "
                  f"avg net {sub['net_ret'].mean()*100:.3f}%, sum {sub['net_ret'].sum()*100:.2f}%")

    # Save (tagged filename)
    out = f"data/orb_5m_results_{args.gap_mode}.json"
    df.to_json(out, orient="records")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
