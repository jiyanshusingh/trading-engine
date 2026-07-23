"""
Per-symbol SL/TP tuning for Manual Institutional (time-gated) strategy.

Grid: sl_mult ∈ {0.3, 0.5, 0.8, 1.0}, tp_mult ∈ {3.0, 4.0, 5.0, 6.0, 8.0}
Runs each symbol independently; picks the (sl, tp) combo with best PF
(≥1.3, trades ≥ 10). Supports --window morning|evening for window-specific
tuning, outputs to data/manual_{window}_tunings.json.
"""

import json
import os
import sys
import time
from itertools import product

sys.path.insert(0, ".")

from scripts.backtest import WalkForwardBacktest, resolve_upstox_key

WATCHLIST_FILE = "data/symbol_watchlists.json"
SYMBOLS_FILE = "data/manual_strategy_watchlist.json"
OUTPUT = "data/manual_symbol_tunings_500.json"
TIMEFRAME = "15m"
DAYS = 365
SL_MULTS = [0.3, 0.5, 0.8]
TP_MULTS = [3.0, 5.0, 6.0, 8.0]
MIN_TRADES = 10
MIN_PF = 1.3


def load_symbols(window=None, limit=None):
    """Load symbols to tune. If window is set, read from symbol_watchlists.json's
    manual_morning/manual_evening list. Otherwise read from combined watchlist."""
    if window:
        key = f"manual_{window}"
        with open(WATCHLIST_FILE) as f:
            data = json.load(f)
        syms = data.get(key, [])
        if not syms:
            print(f"  [error] no symbols found for watchlist '{key}' in {WATCHLIST_FILE}")
            sys.exit(1)
        print(f"Loaded {len(syms)} symbols from '{key}' watchlist")
    else:
        with open(SYMBOLS_FILE) as f:
            data = json.load(f)
        syms = data.get("deployable", [])
        details = data.get("details", {})
        syms.sort(key=lambda s: (-details.get(s, {}).get("profit_factor", 0), -details.get(s, {}).get("trades", 0)))
        print(f"Loaded {len(syms)} deployable symbols from {SYMBOLS_FILE}")
    if limit and limit < len(syms):
        syms = syms[:limit]
    return syms


def run_combo(symbol: str, sl_mult: float, tp_mult: float) -> dict:
    instr_key = resolve_upstox_key(f"{symbol}.NS", "upstox")
    if instr_key == f"{symbol}.NS":
        return {"trades": 0, "pf": 0.0, "avg_r": 0.0, "pnl_pct": 0.0, "wr": 0.0, "dd": 100.0}

    tuning = {"sl_mult": sl_mult, "tp_mult": tp_mult, "atr_period": 14}
    try:
        bt = WalkForwardBacktest(
            instr_key, symbol, TIMEFRAME, "upstox",
            intraday_mode=True,
            force_strategy="Manual Institutional (time-gated)",
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
    ap = argparse.ArgumentParser(description="Per-symbol SL/TP tuning for Manual Institutional")
    ap.add_argument("--limit", type=int, default=None, help="only tune top N symbols (by PF)")
    ap.add_argument("--symbols", default=None, help="comma-separated symbol list (overrides watchlist)")
    ap.add_argument("--out", default=None, help="output path override")
    ap.add_argument("--window", default=None, choices=["morning", "evening"],
                    help="restrict tuning to a single golden window")
    args = ap.parse_args()

    os.environ["SKIP_WEDNESDAY"] = "1"

    # Determine window suffix for output path
    window = args.window
    out_path = args.out
    if not out_path:
        if window:
            out_path = f"data/manual_{window}_tunings.json"
        else:
            out_path = OUTPUT

    # Set env vars so strategy respects window filter and does NOT load
    # existing per-symbol tunings (which would override the grid).
    if window:
        os.environ["MANUAL_GOLDEN_WINDOW"] = window
    os.environ["MANUAL_TUNINGS"] = "/dev/null"
    os.environ["MANUAL_MORNING_TUNINGS"] = "/dev/null"
    os.environ["MANUAL_EVENING_TUNINGS"] = "/dev/null"

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = load_symbols(window=window, limit=args.limit)

    grid = list(product(SL_MULTS, TP_MULTS))
    tunings = {}
    total_start = time.time()

    for idx, sym in enumerate(symbols, 1):
        print(f"\n[{idx}/{len(symbols)}] {sym} — grid {len(grid)} combos")
        best = {"trades": 0, "pf": 0.0, "avg_r": 0.0, "sl": 0.5, "tp": 5.0, "pnl_pct": 0.0, "wr": 0.0, "dd": 100.0}

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
            changed = (best["sl"] != 0.5 or best["tp"] != 5.0)
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

    # Save
    window_label = f" {window}" if window else ""
    output = {
        "strategy": f"Manual Institutional (time-gated){window_label}",
        "window": window,
        "timeframe": TIMEFRAME,
        "mode": "INTRADAY",
        "default_sl": 0.5,
        "default_tp": 5.0,
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
