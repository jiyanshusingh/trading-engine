"""
Per-symbol SL/TP tuning for the Combined Swing strategy.

Grid: sl_mult ∈ {1.5, 2.0, 2.5, 3.0}, tp_mult ∈ {3.0, 4.0, 6.0}
Runs each symbol independently; picks the (sl, tp) combo with best PF
(≥1.3, trades ≥ 10). Saves to data/combined_swing_tunings.json.

Sources symbols from the Combined Swing swing backtest
(data/backtest_portfolio_15m_combined_swing.json).
"""

import json
import os
import sys
import time
from itertools import product

sys.path.insert(0, ".")

import logging
logging.basicConfig(level=logging.CRITICAL)
for l in ["rsm_strategy", "backtest", "data_registry", "root", "combined_swing_strategy"]:
    logging.getLogger(l).setLevel(logging.CRITICAL)

from scripts.backtest import WalkForwardBacktest

RESULTS_FILE = "data/backtest_portfolio_15m_combined_swing.json"
OUTPUT = "data/combined_swing_tunings_500.json"
TIMEFRAME = "15m"
DAYS = 730
SL_MULTS = [1.5, 2.0, 2.5, 3.0]
TP_MULTS = [3.0, 4.0, 6.0]
MIN_TRADES = 10
MIN_PF = 1.3
DEFAULT_SL = 2.0
DEFAULT_TP = 4.0


def load_symbols(limit=None):
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    syms = [r["symbol"] for r in data if r.get("trades", 0) >= MIN_TRADES]
    details = {r["symbol"]: r for r in data}
    syms.sort(key=lambda s: (-details[s].get("profit_factor", 0), -details[s].get("trades", 0)))
    if limit and limit < len(syms):
        syms = syms[:limit]
    print(f"Loaded {len(syms)} symbols from {RESULTS_FILE}")
    return syms


def run_combo(symbol: str, sl_mult: float, tp_mult: float) -> dict:
    instr_key = f"{symbol}.NS"
    tuning = {"sl_mult": sl_mult, "tp_mult": tp_mult, "atr_period": 14}
    try:
        bt = WalkForwardBacktest(
            instr_key, symbol, TIMEFRAME, "yfinance",
            intraday_mode=False,
            force_strategy="Combined Swing",
            tuning_override=tuning,
            cache_only=True,
        )
        summary = bt.run(days=DAYS)
    except Exception as e:
        print(f"    Error: {e}")
        return {"trades": 0, "pf": 0.0, "avg_r": 0.0, "pnl_pct": 0.0, "wr": 0.0, "dd": 100.0}

    return {
        "trades": summary.total_trades,
        "pf": summary.profit_factor,
        "avg_r": summary.avg_r,
        "pnl_pct": summary.total_pnl_pct,
        "wr": summary.win_rate,
        "dd": summary.max_drawdown,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Per-symbol SL/TP tuning for Combined Swing")
    ap.add_argument("--limit", type=int, default=None, help="only tune top N symbols (by PF)")
    ap.add_argument("--symbols", default=None, help="comma-separated symbol list")
    ap.add_argument("--out", default=None, help="output path override")
    args = ap.parse_args()

    out_path = args.out or OUTPUT

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = load_symbols(limit=args.limit)

    grid = list(product(SL_MULTS, TP_MULTS))
    tunings = {}
    total_start = time.time()

    for idx, sym in enumerate(symbols, 1):
        print(f"\n[{idx}/{len(symbols)}] {sym} — grid {len(grid)} combos")
        best = {"trades": 0, "pf": 0.0, "avg_r": 0.0, "sl": DEFAULT_SL, "tp": DEFAULT_TP,
                "pnl_pct": 0.0, "wr": 0.0, "dd": 100.0}

        for sl, tp in grid:
            t0 = time.time()
            result = run_combo(sym, sl, tp)
            elapsed = time.time() - t0
            tr = result["trades"]
            pf = result["pf"]

            marker = ""
            if tr >= MIN_TRADES and pf >= MIN_PF and pf > best["pf"]:
                best = {**result, "sl": sl, "tp": tp}
                marker = " ← BEST"

            print(f"    sl={sl:.1f} tp={tp:.1f} → tr={tr:3d} PF={pf:.2f} avgR={result['avg_r']:+.2f} PnL={result['pnl_pct']:+.1f}% [{elapsed:.0f}s]{marker}")

        print(f"  => {sym}: BEST sl={best['sl']:.1f} tp={best['tp']:.1f} "
              f"(tr={best['trades']} PF={best['pf']:.2f} PnL={best['pnl_pct']:+.1f}%)")

        if best["trades"] >= MIN_TRADES and best["pf"] >= MIN_PF:
            changed = (best["sl"] != DEFAULT_SL or best["tp"] != DEFAULT_TP)
            tunings[sym] = {
                "sl": best["sl"],
                "tp": best["tp"],
                "trades": best["trades"],
                "pf": round(best["pf"], 2),
                "avg_r": round(best["avg_r"], 3),
                "pnl_pct": round(best["pnl_pct"], 2),
                "wr": round(best["wr"], 1),
                "dd": round(best["dd"], 2),
                "changed": changed,
            }

    output = {
        "strategy": "Combined Swing",
        "timeframe": TIMEFRAME,
        "mode": "SWING",
        "default_sl": DEFAULT_SL,
        "default_tp": DEFAULT_TP,
        "tuned_count": sum(1 for v in tunings.values() if v["changed"]),
        "total_symbols": len(tunings),
        "tunings": tunings,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    changed = [s for s, v in tunings.items() if v["changed"]]
    print(f"\n{'='*60}")
    print(f"Saved to {out_path}")
    print(f"Symbols tuned: {len(tunings)}/{len(symbols)} passed min criteria")
    print(f"Symbols with non-default SL/TP: {len(changed)}")
    if changed:
        print(f"Changed: {', '.join(changed)}")
    print(f"Total time: {(time.time() - total_start) / 60:.1f} min")
    return tunings


if __name__ == "__main__":
    main()
