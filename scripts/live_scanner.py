"""
Live Market Scanner — fetches NIFTY day type, screens stocks, finds trade ideas.

Usage:
    .venv/bin/python scripts/live_scanner.py
"""

from __future__ import annotations

import logging
import sys as _sys
import time

_sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_log = logging.getLogger("live_scanner")

# ── Expanded watchlist ──────────────────────────────────────────
WATCHLIST = sorted([
    "ASIANPAINT", "BSE", "OIL", "ACUTAAS", "POWERINDIA",
    "FORCEMOT", "ZEEL", "ATHER",
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "KOTAKBANK", "SBIN", "BHARTIARTL", "ITC", "HINDUNILVR",
    "LT", "AXISBANK", "BAJFINANCE", "MARUTI", "TITAN",
    "TATAMOTORS", "TATASTEEL", "NTPC", "SUNPHARMA", "WIPRO",
    "HCLTECH", "ULTRACEMCO", "ADANIENT", "TECHM", "TRENT",
    "PIDILITIND", "HDFCLIFE", "SBILIFE", "ICICIPRULI",
    "BAJAJFINSV", "M&M", "POWERGRID", "GRASIM", "JSWSTEEL",
    "COALINDIA", "ONGC", "BRITANNIA", "DRREDDY", "CIPLA",
    "EICHERMOT", "HEROMOTOCO", "DIVISLAB", "APOLLOHOSP",
    "NESTLEIND", "HAL", "BEL", "TVSMOTOR", "DABUR",
    "HAVELLS", "TORNTPHARM", "SRTRANSFIN", "BIOCON",
    "TATACONSUM", "ABB", "SIEMENS", "AMBUJACEM",
])

import argparse
import json
import os
import pandas as pd


def classify_today_day_type(upstox: bool = False) -> dict:
    from scripts.backtest import _normalize_timestamp_tz
    from engines.day_type_engine import DayTypeEngine

    today = pd.Timestamp.now(tz="Asia/Kolkata")
    _log.info(f"Fetching NIFTY data for day_type classification ({today.date()})...")

    if upstox:
        import scripts.paper_trade as _pt
        nifty_daily = _pt._upstox_live("^NSEI", "1d")
        nifty_intra = _pt._upstox_live("^NSEI", "15m")
    else:
        from scripts.backtest import fetch_data
        nifty_daily = fetch_data("^NSEI", "1d", "yfinance", 10)
        nifty_intra = fetch_data("^NSEI", "15m", "yfinance", 5)

    if nifty_daily is not None:
        nifty_daily = _normalize_timestamp_tz(nifty_daily)

    if nifty_intra is not None:
        nifty_intra = _normalize_timestamp_tz(nifty_intra)

    if nifty_intra is None or nifty_intra.empty:
        return {"day_type": "UNKNOWN", "reason": "no_nifty_intraday_data"}

    today_data = nifty_intra[nifty_intra["timestamp"].dt.date == today.date()]
    prev_daily = None
    if nifty_daily is not None:
        prev_daily = nifty_daily[nifty_daily["timestamp"].dt.date < today.date()].tail(5).copy()

    if today_data.empty:
        return {"day_type": "UNKNOWN", "reason": "no_intraday_data_for_today"}

    try:
        result = DayTypeEngine.classify_historical(
            timestamp=today_data.iloc[-1]["timestamp"],
            nifty_intraday=today_data,
            nifty_daily=prev_daily,
        )
        return {
            "day_type": result.get("type", "UNKNOWN"),
            "confidence": result.get("confidence", ""),
            "reasoning": result.get("reasoning", ""),
            "bars_today": len(today_data),
        }
    except Exception as e:
        return {"day_type": "UNKNOWN", "reason": f"classification_error: {e}"}


def stock_type_for_symbol(name: str, instrument_key: str, nifty_intraday: pd.DataFrame) -> str:
    from scripts.backtest import fetch_data, _normalize_timestamp_tz, WINDOW_SIZE
    from engines.stock_type_engine import StockTypeEngine

    df = fetch_data(instrument_key, "15m", "upstox", 60)
    if df is None or len(df) < WINDOW_SIZE:
        return "UNKNOWN"
    df = _normalize_timestamp_tz(df)

    window = df.iloc[-WINDOW_SIZE:].reset_index(drop=True)
    stock_up = window.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })

    nifty_win = nifty_intraday.iloc[-WINDOW_SIZE:].reset_index(drop=True) if nifty_intraday is not None else None
    if nifty_win is None or len(nifty_win) < WINDOW_SIZE:
        return "UNKNOWN"

    nifty_up = nifty_win.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })

    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    stock_daily = fetch_data(instrument_key, "1d", "upstox", 90, original_symbol=instrument_key)
    daily_slice = None
    if stock_daily is not None:
        stock_daily = _normalize_timestamp_tz(stock_daily)
        daily_slice = stock_daily[stock_daily["timestamp"].dt.date < today].tail(25).copy()
        if not daily_slice.empty:
            daily_slice = daily_slice.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })

    try:
        result = StockTypeEngine.classify(stock_up, nifty_up, stock_daily=daily_slice)
        return result.get("type", "UNKNOWN")
    except Exception as e:
        _log.debug(f"StockTypeEngine failed for {name}: {e}")
        return "UNKNOWN"


def check_recent_signals(name: str, instrument_key: str, day_type: str, stock_type: str) -> dict:
    from scripts.backtest import (
        WalkForwardBacktest, fetch_data, _normalize_timestamp_tz, WINDOW_SIZE,
    )

    df = fetch_data(instrument_key, "15m", "upstox", 60)
    if df is None or len(df) < WINDOW_SIZE + 5:
        return {"active": False, "reason": "insufficient_data"}
    df = _normalize_timestamp_tz(df)

    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    today_mask = df["timestamp"].dt.date == today
    today_indices = df[today_mask].index.tolist()

    bt = WalkForwardBacktest(
        instrument_key, name, "15m", "upstox",
        intraday_mode=True,
    )
    summary = bt.run(days=60)

    today_trades = []
    for t in summary.trades:
        try:
            entry_date = df.iloc[t.entry_idx]["timestamp"].date() if t.entry_idx < len(df) else None
        except Exception:
            entry_date = None
        if entry_date == today:
            today_trades.append(t)

    return {
        "active": len(today_trades) > 0,
        "today_trades": len(today_trades),
        "trades": [
            {
                "direction": t.direction,
                "entry_price": round(t.entry_price, 2),
                "stop_loss": round(t.stop_loss, 2),
                "take_profit": round(t.take_profit, 2),
                "result": t.result,
                "strategy": t.strategy,
                "reasoning": t.reasoning,
                "score": t.score,
            }
            for t in today_trades[:5]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Live market scanner")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Delay between API calls (default: 0.3s)")
    parser.add_argument("--output", default="data/live_scan_results.csv",
                        help="Output CSV path")
    parser.add_argument("--quick", action="store_true",
                        help="Skip per-stock deep scan, just screener results")
    args = parser.parse_args()

    print("=" * 65)
    print(f"  LIVE MARKET SCANNER — {pd.Timestamp.now(tz='Asia/Kolkata').strftime('%Y-%m-%d %H:%M %Z')}")
    print("=" * 65)

    # ── Phase 1: Classify today's day type ────────────────
    print("\n[Phase 1] Classifying today's market condition...")
    day_info = classify_today_day_type()
    dt = day_info.get("day_type", "UNKNOWN")
    print(f"  Day Type: {dt}")
    if day_info.get("confidence"):
        print(f"  Confidence: {day_info['confidence']}")
    if day_info.get("reasoning"):
        print(f"  Reasoning: {day_info['reasoning']}")
    print(f"  Bars today: {day_info.get('bars_today', 0)}")
    if day_info.get("reason"):
        print(f"  Note: {day_info['reason']}")

    # ── Phase 2: Run screener on watchlist ────────────────
    print(f"\n[Phase 2] Scanning {len(WATCHLIST)} symbols...")
    from scripts.backtest import search_upstox_instrument
    from scripts.scan_nse_screener import screen_symbol

    results = []
    for idx, sym_name in enumerate(WATCHLIST):
        try:
            key = search_upstox_instrument(sym_name)
            if key is None:
                _log.debug(f"  [{idx + 1}/{len(WATCHLIST)}] {sym_name}: no key")
                continue
            result = screen_symbol(sym_name, key, days=60)
            results.append(result)

            if result["trades"] > 0:
                tag = "✅" if result["win_rate"] >= 55 and result["profit_factor"] >= 1.3 else "➖"
                print(f"  {tag} [{idx + 1}/{len(WATCHLIST)}] {sym_name:20s} "
                      f"n={result['trades']:3d} WR={result['win_rate']:5.1f}% "
                      f"PF={result['profit_factor']:5.2f} avgR={result['avg_r']:+.2f}")
            else:
                print(f"  ⬜ [{idx + 1}/{len(WATCHLIST)}] {sym_name:20s} 0 trades ({result.get('reason', 'n/a')})")
            time.sleep(args.delay)
        except KeyboardInterrupt:
            break
        except Exception as e:
            _log.warning(f"  [{idx + 1}/{len(WATCHLIST)}] {sym_name}: {e}")
            continue

    # Save results
    csv_path = args.output
    os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
    df_out = pd.DataFrame(results)
    df_out.to_csv(csv_path, index=False)
    print(f"\n  Saved {len(results)} results to {csv_path}")

    # ── Phase 3: Analyze & recommend ──────────────────────
    print(f"\n[Phase 3] Trade Recommendations")
    print("=" * 65)

    active = [r for r in results if r.get("trades", 0) >= 5]
    good = [r for r in active if r.get("win_rate", 0) >= 55 and r.get("profit_factor", 0) >= 1.3]
    maybe = [r for r in active if r not in good and r.get("win_rate", 0) >= 50 and r.get("profit_factor", 0) >= 1.1]

    if dt != "UNKNOWN" and good:
        print(f"\n  Today: {dt} | Recommended strategies based on stock type:\n")

    print(f"\n  TOP PICKS (GOOD — WR>=55%, PF>=1.3, >=5 trades):")
    if good:
        for r in sorted(good, key=lambda x: -x["profit_factor"]):
            print(f"    ✅ {r['symbol']:22s} n={r['trades']:3d}  "
                  f"WR={r['win_rate']:5.1f}%  PF={r['profit_factor']:5.2f}  "
                  f"avgR={r.get('avg_r', 0):+.2f}")
    else:
        print("    (none)")

    print(f"\n  WATCH LIST (MAYBE — WR>=50%, PF>=1.1, >=5 trades):")
    if maybe:
        for r in sorted(maybe, key=lambda x: -x["profit_factor"]):
            print(f"    👀 {r['symbol']:22s} n={r['trades']:3d}  "
                  f"WR={r['win_rate']:5.1f}%  PF={r['profit_factor']:5.2f}  "
                  f"avgR={r.get('avg_r', 0):+.2f}")
    else:
        print("    (none)")

    print(f"\n  SCREENED: {len(WATCHLIST)} symbols, {len(active)} active (>=5 trades), "
          f"{len(good)} GOOD, {len(maybe)} MAYBE")

    # ── Phase 4: Check for TODAY's signals on top candidates ──
    if not args.quick:
        print(f"\n[Phase 4] Checking for live signals on top candidates...")
        print("=" * 65)
        candidates = [r["symbol"] for r in (good + maybe)]
        from scripts.backtest import fetch_data
        nifty_intra = fetch_data("^NSEI", "15m", "yfinance", 5)
        if nifty_intra is not None:
            import scripts.backtest as btmod
            nifty_intra = btmod._normalize_timestamp_tz(nifty_intra)
        else:
            nifty_intra = None

        for sym_name in candidates:
            key = search_upstox_instrument(sym_name)
            if key is None:
                continue
            stock_type = stock_type_for_symbol(sym_name, key, nifty_intra) if nifty_intra is not None else "UNKNOWN"
            signals = check_recent_signals(sym_name, key, dt, stock_type)

            rec_strategy = "—"
            if dt != "UNKNOWN" and stock_type != "UNKNOWN":
                from strategies.selector import select
                strat, rationale = select(dt, stock_type)
                if strat:
                    rec_strategy = f"{strat.name}"

            print(f"\n  {sym_name:22s} | stock_type={stock_type:12s} | rec={rec_strategy}")
            if signals.get("active"):
                for t in signals["trades"]:
                    print(f"    🔴 LIVE SIGNAL: {t['direction']} @ {t['entry_price']} "
                          f"SL={t['stop_loss']} TP={t['take_profit']} "
                          f"({t['strategy']})")
            else:
                bars_today = 0
                if nifty_intra is not None:
                    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
                    bars_today = len(nifty_intra[nifty_intra["timestamp"].dt.date == today])
                print(f"    No live signal yet ({bars_today} bars of data today)")

    print(f"\n{'=' * 65}")
    print(f"  Scan complete at {pd.Timestamp.now(tz='Asia/Kolkata').strftime('%H:%M %Z')}")
    print(f"{'=' * 65}")


if __name__ == "__main__":
    main()
