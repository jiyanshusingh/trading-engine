#!/usr/bin/env python3
"""
Phase 1 — Collect:  run backtests at MANUAL_MIN_SCORE=0 to capture ALL trades
                     with their raw bullish_score, then save to JSON.
Phase 2 — Analyze:  bucket by score threshold, compute WR/avgR/PF/NetPnL%,
                     find the breakeven score.

Usage:
    .venv/bin/python scripts/analyze_manual_score_threshold.py collect
    .venv/bin/python scripts/analyze_manual_score_threshold.py analyze
    .venv/bin/python scripts/analyze_manual_score_threshold.py   (both)
"""
import os, sys, json, time

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE)

# ── Disable score gates only; capital at defaults ─────────────
os.environ["MANUAL_MIN_SCORE"] = "0"
os.environ["INST_LONG_MIN_SCORE"] = "0"

import scripts.backtest as _btmod

def _cache_always(symbol):
    base = symbol.upper()
    if base.endswith(".NS"):
        base = base[:-3]
    return base
_btmod._nse_symbol_for_cache = _cache_always

from scripts.backtest import WalkForwardBacktest

TF = "15m"
DAYS = 700
PROVIDER = "yfinance"
TUNING = {"sl_mult": 0.5, "tp_mult": 5.0, "atr_period": 14}
FORCE_STRATEGY = "Manual Institutional (time-gated)"
OUTPUT = os.path.join(BASE, "data", "manual_score_sweep_trades.json")

WATCHLIST = json.load(open(os.path.join(BASE, "data", "symbol_watchlists.json")))
SYMBOLS = WATCHLIST["manual_golden"]


def collect():
    all_trades = []
    total = len(SYMBOLS)
    t0 = time.time()
    for idx, sym in enumerate(SYMBOLS, 1):
        try:
            bt = WalkForwardBacktest(
                f"{sym}.NS", sym, TF, PROVIDER,
                intraday_mode=True,
                force_strategy=FORCE_STRATEGY,
                tuning_override=TUNING,
                cache_only=True,
            )
            r = bt.run(days=DAYS)
            n = len(r.trades)
            for t in r.trades:
                all_trades.append({
                    "symbol": sym,
                    "score": t.score,
                    "r_multiple": t.r_multiple,
                    "pnl_net": t.pnl_net,
                    "pnl_net_pct": t.pnl_net_pct,
                    "result": t.result,
                    "direction": t.direction,
                    "entry_timestamp": t.entry_timestamp,
                })
        except Exception as e:
            print(f"  [{idx}/{total}] {sym:18s} ✗ {e}", flush=True)
            continue
        print(f"  [{idx}/{total}] {sym:18s} → {n:4d} trades  "
              f"({time.time()-t0:.0f}s elapsed)", flush=True)

    json.dump(all_trades, open(OUTPUT, "w"), indent=2)
    print(f"\nSaved {len(all_trades)} trades → {OUTPUT}")


def analyze():
    if not os.path.exists(OUTPUT):
        print(f"No trade data found. Run 'collect' first.")
        return
    trades = json.load(open(OUTPUT))
    print(f"Loaded {len(trades)} trades\n")

    scores = sorted(set(t["score"] for t in trades))
    # Report at thresholds: 0, 5, 10, 15, … 100
    thresholds = list(range(0, 101, 5))

    print(f"{'Score ≥':>8s}  {'Trades':>7s}  {'WR':>7s}  {'avgR':>7s}  "
          f"{'PF':>7s}  {'NetPnL%':>9s}  {'Cumul PnL':>10s}")
    print("-" * 65)

    best_stats = None
    best_threshold = None

    for th in thresholds:
        subset = [t for t in trades if t["score"] >= th]
        if not subset:
            continue
        n = len(subset)
        wins = [t for t in subset if t.get("pnl_net") is not None and t["pnl_net"] > 0]
        losses = [t for t in subset if t.get("pnl_net") is not None and t["pnl_net"] <= 0]
        wr = (len(wins) / n * 100.0) if n > 0 else 0.0
        r_vals = [t["r_multiple"] for t in subset if t["r_multiple"] is not None]
        avg_r = sum(r_vals) / len(r_vals) if r_vals else 0.0
        gross_win = sum(abs(t["pnl_net"]) for t in wins if t["pnl_net"] is not None and t["pnl_net"] > 0)
        gross_loss = sum(abs(t["pnl_net"]) for t in losses if t["pnl_net"] is not None and t["pnl_net"] < 0)
        pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0) / 1
        total_pnl = sum(t["pnl_net"] for t in subset if t["pnl_net"] is not None)
        total_pnl_pct = sum(t["pnl_net_pct"] for t in subset if t["pnl_net_pct"] is not None)
        netpnl_label = f"{total_pnl_pct:+7.2f}%"
        cumul_label = f"₹{total_pnl:+,.0f}"

        marker = ""
        if total_pnl >= 0 and best_threshold is None:
            best_threshold = th
            best_stats = (n, wr, avg_r, pf, total_pnl_pct, total_pnl)
            marker = "  ← BREAKEVEN"

        # color for NetPnL%
        pnl_str = f"{total_pnl_pct:+7.2f}%"
        if total_pnl >= 0:
            pnl_str = f"\033[32m{total_pnl_pct:+7.2f}%\033[0m"
        else:
            pnl_str = f"\033[31m{total_pnl_pct:+7.2f}%\033[0m"

        print(f"{th:>8d}  {n:>7d}  {wr:>6.1f}%  {avg_r:>+7.3f}  "
              f"{pf:>7.2f}  {pnl_str:>9s}  {cumul_label:>10s}"
              f"{'  ← BREAKEVEN' if marker else ''}")

    print()
    if best_threshold is not None:
        n, wr, avg_r, pf, pnl_pct, pnl = best_stats
        print(f"═══ BREAKEVEN at score ≥ {best_threshold} "
              f"({n} trades, WR={wr:.1f}%, avgR={avg_r:+.3f}, "
              f"PF={pf:.2f}, NetPnL={pnl_pct:+.2f}%, ₹{pnl:+,.0f}) ═══")
    else:
        print("═══ No breakeven threshold found (negative across all scores) ═══")

    # Also show per-score bucket (non-cumulative)
    print("\n\nPer-score bucket (non-cumulative):")
    print(f"{'Score':>8s}  {'Trades':>7s}  {'WR':>7s}  {'avgR':>7s}  {'PF':>7s}  {'NetPnL%':>9s}")
    print("-" * 55)
    for th in thresholds:
        lo = th
        hi = th + 5
        subset = [t for t in trades if lo <= t["score"] < hi]
        if not subset:
            continue
        n = len(subset)
        wins = [t for t in subset if t.get("pnl_net") is not None and t["pnl_net"] > 0]
        losses = [t for t in subset if t.get("pnl_net") is not None and t["pnl_net"] <= 0]
        wr = (len(wins) / n * 100.0) if n > 0 else 0.0
        r_vals = [t["r_multiple"] for t in subset if t["r_multiple"] is not None]
        avg_r = sum(r_vals) / len(r_vals) if r_vals else 0.0
        gross_win = sum(abs(t["pnl_net"]) for t in wins if t["pnl_net"] is not None and t["pnl_net"] > 0)
        gross_loss = sum(abs(t["pnl_net"]) for t in losses if t["pnl_net"] is not None and t["pnl_net"] < 0)
        pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0) / 1
        total_pnl_pct = sum(t["pnl_net_pct"] for t in subset if t["pnl_net_pct"] is not None)

        clr = "\033[32m" if total_pnl_pct >= 0 else "\033[31m"
        print(f"{f'{lo}-{hi-1}':>8s}  {n:>7d}  {wr:>6.1f}%  {avg_r:>+7.3f}  "
              f"{pf:>7.2f}  {clr}{total_pnl_pct:+7.2f}%\033[0m")

    print()


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "both"
    if phase in ("collect", "both"):
        collect()
    if phase in ("analyze", "both",):
        analyze()
