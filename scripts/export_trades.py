"""
Export trade history to daily CSV files.

Usage:
  .venv/bin/python scripts/export_trades.py              # today's trades
  .venv/bin/python scripts/export_trades.py --date 2026-07-14
  .venv/bin/python scripts/export_trades.py --all         # export every day
  .venv/bin/python scripts/export_trades.py --latest 5    # last 5 days
"""

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

_HISTORY_PATH = "data/trade_history.json"
_EXPORT_DIR = "data/exports"

IST = "Asia/Kolkata"


def _load() -> dict:
    if not os.path.exists(_HISTORY_PATH):
        return {"signals": [], "trades": []}
    with open(_HISTORY_PATH) as f:
        return json.load(f)


def _parse_date(ts: str) -> str | None:
    for fmt in ("%Y-%m-%d %H:%M IST", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(ts.split(" IST")[0].strip(), fmt).strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            continue
    return None


def _write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {len(rows)} rows → {path}")


def export_day(target_date: str, data: dict) -> None:
    signals = data.get("signals", [])
    trades = data.get("trades", [])

    day_signals = [s for s in signals if _parse_date(s.get("ts", "")) == target_date]
    day_trades = [t for t in trades if _parse_date(t.get("ts", "")) == target_date]

    base = os.path.join(_EXPORT_DIR, target_date)

    if day_signals:
        _write_csv(f"{base}_signals.csv", day_signals,
                   ["ts", "symbol", "direction", "score", "entry", "sl", "tp",
                    "r", "tf", "tier", "category"])

    if day_trades:
        _write_csv(f"{base}_trades.csv", day_trades,
                   ["ts", "symbol", "direction", "entry", "shares", "exit",
                    "pnl", "reason", "status", "mode", "strategy",
                    "opened_at", "closed_at"])

    if not day_signals and not day_trades:
        print(f"  no data for {target_date}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Export trade history to daily CSVs")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--date", type=str, default=None,
                       help="Export a specific date (YYYY-MM-DD)")
    group.add_argument("--all", action="store_true",
                       help="Export all dates found in history")
    group.add_argument("--latest", type=int, default=None,
                       help="Export last N days")
    args = ap.parse_args()

    data = _load()

    if args.date:
        dates = [args.date]
    elif args.all:
        seen = set()
        for s in data.get("signals", []):
            d = _parse_date(s.get("ts", ""))
            if d:
                seen.add(d)
        for t in data.get("trades", []):
            d = _parse_date(t.get("ts", ""))
            if d:
                seen.add(d)
        dates = sorted(seen)
    elif args.latest:
        seen = set()
        for s in data.get("signals", []):
            d = _parse_date(s.get("ts", ""))
            if d:
                seen.add(d)
        for t in data.get("trades", []):
            d = _parse_date(t.get("ts", ""))
            if d:
                seen.add(d)
        dates = sorted(seen)[-args.latest:]
    else:
        dates = [date.today().strftime("%Y-%m-%d")]

    print(f"Exporting {len(dates)} day(s) to {_EXPORT_DIR}/")
    for d in dates:
        export_day(d, data)

    print("Done.")


if __name__ == "__main__":
    main()
