"""
SL/TP grid tuning for Institutional Probability strategy.

Grid: sl_mult ∈ {0.5, 1.0, 1.5, 2.0, 2.5, 3.0}
      tp_mult ∈ {1.5, 2.0, 2.5, 3.0, 4.0, 5.0}

Runs full 30-symbol 15m portfolio backtest for each combo.
Saves results to data/sltp_tuning_results.csv
"""

from __future__ import annotations

import csv
import logging
import os
import sys
import time
from itertools import product

sys.path.insert(0, ".")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from data.downloader.watched_symbols import SYMBOLS
from scripts.backtest import WalkForwardBacktest, resolve_upstox_key

SL_MULTS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
TP_MULTS = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
TIMEFRAME = "15m"
DAYS = 120


def _run_combo(sl_mult: float, tp_mult: float, intraday: bool) -> dict:
    trade_count = 0
    win_count = 0
    loss_count = 0
    pnl_sum = 0.0
    r_sum = 0.0
    pf_numer = 0.0
    pf_denom = 0.0
    max_dd = 0.0
    sym_with_trades = 0

    tuning = {"sl_mult": sl_mult, "tp_mult": tp_mult, "atr_period": 14}

    for sym in SYMBOLS:
        instr_key = resolve_upstox_key(f"{sym}.NS", "upstox")
        if instr_key == f"{sym}.NS":
            continue

        try:
            bt = WalkForwardBacktest(
                instr_key, sym, TIMEFRAME, "upstox",
                intraday_mode=intraday,
                force_strategy="Institutional Probability",
                tuning_override=tuning,
            )
            summary = bt.run(days=DAYS)
        except Exception:
            continue

        if summary.total_trades == 0:
            continue

        sym_with_trades += 1
        trade_count += summary.total_trades
        win_count += summary.wins
        loss_count += summary.losses
        pnl_sum += summary.total_pnl_pct
        r_sum += summary.avg_r * summary.total_trades
        max_dd = max(max_dd, summary.max_drawdown)

        for t in summary.trades:
            if t.r_multiple is not None:
                if t.r_multiple > 0:
                    pf_numer += t.r_multiple
                else:
                    pf_denom += abs(t.r_multiple)

    if trade_count == 0:
        return {
            "sl_mult": sl_mult, "tp_mult": tp_mult,
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 1.0,
            "avg_r": 0.0, "total_pnl_pct": 0.0, "max_dd": 0.0,
            "sym_with_trades": 0,
        }

    wr = win_count / trade_count * 100
    avg_r = r_sum / trade_count
    pf = pf_numer / max(pf_denom, 0.001)

    return {
        "sl_mult": sl_mult, "tp_mult": tp_mult,
        "total_trades": trade_count,
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "avg_r": round(avg_r, 2),
        "total_pnl_pct": round(pnl_sum, 2),
        "max_dd": round(max_dd, 2),
        "sym_with_trades": sym_with_trades,
    }


def main():
    import argparse

    ap = argparse.ArgumentParser(description="SL/TP grid tuning")
    ap.add_argument("--timeframe", "-t", default="15m")
    ap.add_argument("--days", "-d", type=int, default=120)
    ap.add_argument("--no-intraday", action="store_true",
                    help="Swing mode (allow overnight holds)")
    ap.add_argument("--out", default=None, help="override CSV output path")
    args = ap.parse_args()

    global TIMEFRAME, DAYS
    TIMEFRAME = args.timeframe
    DAYS = args.days
    intraday = not args.no_intraday
    out_path = args.out or f"data/sltp_tuning_{TIMEFRAME}{'_swing' if not intraday else ''}.csv"

    combos = list(product(SL_MULTS, TP_MULTS))
    total = len(combos)
    print(f"SL/TP Tuning: {total} combos across {len(SYMBOLS)} symbols @ {TIMEFRAME}"
          f" ({'intraday' if intraday else 'swing'})")
    print(f"{'#':>3} {'sl_mult':>7} {'tp_mult':>7} {'Trades':>6} {'WR%':>5} "
          f"{'PF':>7} {'avgR':>6} {'PnL%':>7} {'MaxDD':>6} {'Syms':>4}  Time")
    print("-" * 72)

    rows = []
    start = time.time()

    for idx, (sl, tp) in enumerate(combos, 1):
        t0 = time.time()
        row = _run_combo(sl, tp, intraday)
        elapsed = time.time() - t0
        left = total - idx
        eta = left * elapsed / max(idx, 1) if idx > 0 else 0
        print(f"{idx:>3d} {sl:>7.1f} {tp:>7.1f} {row['total_trades']:>6d} "
              f"{row['win_rate']:>4.1f}% {row['profit_factor']:>7.2f} "
              f"{row['avg_r']:>6.2f} {row['total_pnl_pct']:>6.2f}% "
              f"{row['max_dd']:>5.2f}% {row['sym_with_trades']:>4d}  "
              f"[{elapsed:3.0f}s / ETA {eta:4.0f}s]")
        rows.append(row)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    rows.sort(key=lambda r: (-r["profit_factor"], r["total_trades"]))
    print("\n" + "=" * 72)
    print(f"TOP 10 CONFIGURATIONS (by Profit Factor)  —  total {time.time()-start:.0f}s")
    print("=" * 72)
    print(f"{'Rank':>4} {'sl_mult':>7} {'tp_mult':>7} {'Trades':>6} {'WR%':>5} "
          f"{'PF':>7} {'avgR':>6} {'PnL%':>7} {'MaxDD':>6}")
    print("-" * 55)
    for rank, row in enumerate(rows[:10], 1):
        print(f"{rank:>4d} {row['sl_mult']:>7.1f} {row['tp_mult']:>7.1f} "
              f"{row['total_trades']:>6d} {row['win_rate']:>4.1f}% "
              f"{row['profit_factor']:>7.2f} {row['avg_r']:>6.2f} "
              f"{row['total_pnl_pct']:>6.2f}% {row['max_dd']:>5.2f}%")

    print(f"\nFull results: {out_path}")


if __name__ == "__main__":
    main()
