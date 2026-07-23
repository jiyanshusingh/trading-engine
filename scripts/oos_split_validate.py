"""
OOS split validator (Phase 29 — reusable, mirrors the Phase 25/27 method).

Splits each symbol's trades 50/50 by entry timestamp and keeps only symbols
that are NET-positive (sum of pnl_net, after costs) in BOTH halves. This is the
same robustness filter that fixed Combined Swing (Phase 25) and Manual/RSM
(Phase 27) — it rejects symbols whose edge is confined to one window.

Usage:
  python scripts/oos_split_validate.py data/backtest_trades_15m_mr56_tuned.json
"""

import json
import sys
from collections import defaultdict


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/backtest_trades_15m_mr56_tuned.json"
    trades = json.load(open(path))
    by_sym = defaultdict(list)
    for t in trades:
        if t.get("pnl_net") is None:
            continue
        by_sym[t["symbol"]].append(t)

    print(f"Loaded {len(trades)} trades across {len(by_sym)} symbols from {path}\n")
    survivors = {}
    all_rows = []
    for sym, ts in by_sym.items():
        ts.sort(key=lambda x: x.get("entry_timestamp") or "")
        n = len(ts)
        if n < 10:
            all_rows.append((sym, n, None, None, None, "SKIP<10"))
            continue
        mid = n // 2
        first = sum(x["pnl_net"] for x in ts[:mid])
        second = sum(x["pnl_net"] for x in ts[mid:])
        full = first + second
        ok = first > 0 and second > 0
        all_rows.append((sym, n, first, second, full, "KEEP" if ok else "drop"))
        if ok:
            survivors[sym] = {"trades": n, "net_first": round(first),
                              "net_second": round(second), "net_full": round(full)}

    all_rows.sort(key=lambda r: (r[4] if r[4] is not None else -1e18), reverse=True)
    print(f"{'SYMBOL':14s} {'tr':>4s} {'net_H1':>10s} {'net_H2':>10s} {'net_full':>10s}  verdict")
    print("-" * 62)
    for sym, n, f, s, full, verdict in all_rows:
        if f is None:
            print(f"{sym:14s} {n:4d} {'—':>10s} {'—':>10s} {'—':>10s}  {verdict}")
        else:
            print(f"{sym:14s} {n:4d} {f:+10.0f} {s:+10.0f} {full:+10.0f}  {verdict}")

    keep_full = sum(v["net_full"] for v in survivors.values())
    print("-" * 62)
    print(f"\nSurvivors (net+ in BOTH halves): {len(survivors)}/{len(by_sym)}")
    print(f"Sum net PnL of survivors (full period): ₹{keep_full:+,.0f}")
    print(f"Symbols: {', '.join(sorted(survivors))}")

    out = path.replace(".json", "_oos_survivors.json")
    json.dump({"survivors": survivors, "count": len(survivors),
               "net_full": keep_full}, open(out, "w"), indent=2)
    print(f"\nSaved survivors -> {out}")


if __name__ == "__main__":
    main()
