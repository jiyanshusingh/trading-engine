"""
Phase 1 — Build the strict symbol whitelist from a portfolio backtest result.

Reads a data/backtest_portfolio_<tf>.json produced by run_backtest_portfolio.py
and records symbols meeting PF >= MIN_PF and trades >= MIN_TRADES into
data/symbol_whitelist.json under the (timeframe, mode) bucket.

Usage
-----
    .venv/bin/python -m scripts.build_whitelist --result data/backtest_portfolio_15m.json \
        --timeframe 15m --intraday
    .venv/bin/python -m scripts.build_whitelist --result data/backtest_portfolio_1h.json \
        --timeframe 1h --swing
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.symbol_whitelist import MIN_PF, MIN_TRADES, bucket_key, _PATH


def build(result_path: str, timeframe: str, intraday: bool) -> list[str]:
    rows = json.loads(Path(result_path).read_text())
    passed = []
    print(f"\n  Whitelist rule: PF >= {MIN_PF} AND trades >= {MIN_TRADES}")
    print(f"  {'Symbol':16s} {'Tr':>4s} {'PF':>7s} {'PnL%':>7s}  verdict")
    print("  " + "-" * 48)
    for r in sorted(rows, key=lambda x: -x.get("profit_factor", 0)):
        pf = r.get("profit_factor", 0.0)
        tr = r.get("trades", 0)
        ok = pf >= MIN_PF and tr >= MIN_TRADES
        if ok:
            passed.append(r["symbol"])
        print(f"  {r['symbol']:16s} {tr:4d} {pf:7.2f} {r.get('total_pnl_pct',0):+6.2f}%  "
              f"{'KEEP' if ok else 'drop'}")

    key = bucket_key(timeframe, intraday)
    data = json.loads(_PATH.read_text()) if _PATH.exists() else {}
    data[key] = passed
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2))
    print(f"\n  → {len(passed)} symbols kept for '{key}': {passed}")
    print(f"  → saved to {_PATH}")
    return passed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--timeframe", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--intraday", action="store_true")
    g.add_argument("--swing", action="store_true")
    args = ap.parse_args()
    build(args.result, args.timeframe, intraday=args.intraday)


if __name__ == "__main__":
    main()
