"""
NIFTY Futures 15m intraday backtest.

Standalone backtest for the NIFTY Futures strategy. Uses ^NSEI spot data as
the price proxy (index futures track spot minus cost of carry). Applies
futures-specific: lot-based sizing, STT 0.01% sell-side, contract multiplier.

Usage:
    .venv/bin/python scripts/backtest_nifty_futures.py
    .venv/bin/python scripts/backtest_nifty_futures.py --days 365
    .venv/bin/python scripts/backtest_nifty_futures.py --sl 2.0 --tp 4.0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
_log = logging.getLogger("bt_nifty_futures")

# NIFTY futures constants
LOT_SIZE = 65
CONTRACT_MULTIPLIER = 65
FNO_CAPITAL = 160000.0
STT_PCT = 0.01  # 0.01% on sell side
EXCHANGE_FEE_PCT = 0.0002
SEBI_FEE_PCT = 0.0001
GST_PCT = 18.0  # on brokerage


def _trade_cost(entry, exit, qty, direction):
    """Futures cost model: STT on sell side + exchange + SEBI + GST."""
    buy_value = min(entry, exit) * qty
    sell_value = max(entry, exit) * qty
    turnover = entry * qty + exit * qty
    stt = sell_value * STT_PCT / 100
    exchange_fee = turnover * EXCHANGE_FEE_PCT / 100
    sebi = turnover * SEBI_FEE_PCT / 100
    brokerage = 20.0  # flat ₹20 per order
    gst = brokerage * GST_PCT / 100
    return round(stt + exchange_fee + sebi + brokerage + gst, 2)


def _atr_series(high, low, close, period=14):
    h, l, c = high.values, low.values, close.values
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    tr_series = pd.Series(tr).rolling(period).mean()
    arr = np.full(len(close), np.nan)
    arr[1:] = tr_series.values
    return arr


def run_backtest(df: pd.DataFrame, sl_mult: float = 1.5, tp_mult: float = 3.0,
                 days: int = 730, capital: float = FNO_CAPITAL) -> dict:
    """Run the NIFTY futures 15m backtest on ^NSEI data."""
    from engines.nifty_futures_engine import NiftyFuturesEngine, LONG_MIN_SCORE, SHORT_MIN_SCORE

    # Slice to the requested period
    cutoff = df["timestamp"].max() - timedelta(days=days)
    df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    if len(df) < 200:
        _log.error("Need ≥200 bars, got %d", len(df))
        return {}

    _log.info("Backtesting %d bars (%.0f days, sl=%.1f tp=%.1f)",
              len(df), days, sl_mult, tp_mult)

    engine = NiftyFuturesEngine()
    nifty_1d = pd.read_parquet("data/cache/1d/^NSEI.parquet")

    # Precompute ATR series for the whole backtest window
    atr_s = _atr_series(df["high"], df["low"], df["close"], 14)

    trades = []
    capital_series = [capital]
    peak = capital
    daily_entries = {}

    for i in range(200, len(df)):
        window = df.iloc[:i + 1]
        bar = df.iloc[i]
        ts = bar["timestamp"]
        date_str = str(ts.date())

        # Skip if daily entry cap reached
        daily_entries.setdefault(date_str, 0)

        result = engine.compute(window, nifty_1d=nifty_1d)

        if result["direction"] == "NEUTRAL":
            capital_series.append(capital_series[-1])
            continue

        direction = result["direction"]
        score = result["total_score"]
        entry_price = float(bar["close"])
        atr_val = float(atr_s[i]) if not np.isnan(atr_s[i]) else 0
        if atr_val <= 0:
            capital_series.append(capital_series[-1])
            continue

        # Position sizing: we have ₹1.6L capital, enough for exactly 1 lot
        # of NIFTY futures (margin ≈ ₹1.6L at ~10% of ₹15.9L notional).
        # Default 1 lot — no fractional lots in futures.
        lots = 1
        qty = lots * LOT_SIZE

        # Check affordability (MIS intraday margin ≈ 5% of notional)
        margin_needed = entry_price * LOT_SIZE * 0.05
        if margin_needed > capital_series[-1]:
            capital_series.append(capital_series[-1])
            continue

        # Enforce daily entry cap (max 3 per day for futures)
        if daily_entries[date_str] >= 3:
            capital_series.append(capital_series[-1])
            continue

        daily_entries[date_str] += 1

        # Entry
        if direction == "LONG":
            stop_loss = entry_price - sl_mult * atr_val
            take_profit = entry_price + tp_mult * atr_val
        else:
            stop_loss = entry_price + sl_mult * atr_val
            take_profit = entry_price - tp_mult * atr_val

        trade = {
            "entry_ts": str(ts),
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "lots": lots,
            "qty": qty,
            "score": score,
            "status": "OPEN",
        }

        # Forward-simulate this trade (max 24 bars = 6h intraday)
        exit_price = None
        exit_reason = None
        max_bars = 24
        for j in range(i + 1, min(i + 1 + max_bars, len(df))):
            future_bar = df.iloc[j]
            high, low = float(future_bar["high"]), float(future_bar["low"])

            if direction == "LONG":
                if low <= stop_loss:
                    exit_price = stop_loss
                    exit_reason = "SL"
                    break
                if high >= take_profit:
                    exit_price = take_profit
                    exit_reason = "TP"
                    break
            else:
                if high >= stop_loss:
                    exit_price = stop_loss
                    exit_reason = "SL"
                    break
                if low <= take_profit:
                    exit_price = take_profit
                    exit_reason = "TP"
                    break

        if exit_price is None:
            # Time stop — close at last bar's close
            last_bar = df.iloc[min(i + max_bars, len(df) - 1)]
            exit_price = float(last_bar["close"])
            exit_reason = "TIME"

        # P&L
        if direction == "LONG":
            pnl = qty * (exit_price - entry_price)
        else:
            pnl = qty * (entry_price - exit_price)

        cost = _trade_cost(entry_price, exit_price, qty, direction)
        net_pnl = pnl - cost

        trade.update({
            "exit_price": round(exit_price, 2),
            "exit_reason": exit_reason,
            "pnl": round(pnl, 2),
            "cost": round(cost, 2),
            "net_pnl": round(net_pnl, 2),
            "status": "CLOSED",
        })

        capital_series.append(capital_series[-1] + net_pnl)
        trades.append(trade)

        if capital_series[-1] < capital_series[-2]:
            peak = max(peak, capital_series[-1])

    # Stats
    if not trades:
        _log.warning("0 trades generated")
        return {"total_trades": 0, "capital_series": capital_series}

    df_trades = pd.DataFrame(trades)
    total_trades = len(df_trades)
    wins = df_trades[df_trades["net_pnl"] > 0]
    losses = df_trades[df_trades["net_pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
    total_pnl = df_trades["net_pnl"].sum()
    avg_pnl = df_trades["net_pnl"].mean()
    gross_pnl = df_trades["pnl"].sum()
    total_cost = df_trades["cost"].sum()
    avg_r = (df_trades["pnl"] / (df_trades["entry_price"] * 0.01)).mean()

    longs = df_trades[df_trades["direction"] == "LONG"]
    shorts = df_trades[df_trades["direction"] == "SHORT"]

    dd = max_drawdown(capital_series)
    final_capital = capital_series[-1]

    stats = {
        "total_trades": total_trades,
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "win_rate_pct": round(win_rate, 1),
        "wins": len(wins),
        "losses": len(losses),
        "avg_r": round(avg_r, 3),
        "gross_pnl": round(gross_pnl, 2),
        "total_cost": round(total_cost, 2),
        "net_pnl": round(total_pnl, 2),
        "avg_net_pnl": round(avg_pnl, 2),
        "max_drawdown": round(dd, 2),
        "max_drawdown_pct": round(dd / max(capital_series) * 100, 2) if max(capital_series) > 0 else 0,
        "final_capital": round(final_capital, 2),
        "return_pct": round((final_capital - capital) / capital * 100, 2),
        "sl_mult": sl_mult,
        "tp_mult": tp_mult,
        "days": days,
        "bars_tested": len(df) - 200,
        "long_win_rate": round(len(wins[wins.index.isin(longs.index)]) / len(longs) * 100, 1) if len(longs) > 0 else 0,
        "short_win_rate": round(len(wins[wins.index.isin(shorts.index)]) / len(shorts) * 100, 1) if len(shorts) > 0 else 0,
    }

    return {"stats": stats, "trades": trades, "capital_series": capital_series}


def max_drawdown(equity_curve: list) -> float:
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    return max_dd


def main():
    ap = argparse.ArgumentParser(description="NIFTY futures 15m intraday backtest")
    ap.add_argument("--sl", type=float, default=1.5)
    ap.add_argument("--tp", type=float, default=3.0)
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--save", action="store_true", help="Save results to file")
    args = ap.parse_args()

    _log.info("Loading ^NSEI 15m data …")
    df = pd.read_parquet("data/cache/15m/^NSEI.parquet")
    _log.info("  %d bars loaded", len(df))

    t0 = time.time()
    result = run_backtest(df, sl_mult=args.sl, tp_mult=args.tp, days=args.days)
    elapsed = time.time() - t0

    if not result:
        _log.error("Backtest returned empty")
        return

    stats = result.get("stats", {})
    trades = result.get("trades", [])
    cap = result.get("capital_series", [])

    print()
    print("=" * 60)
    print(f"  NIFTY Futures 15m Backtest")
    print(f"  SL={args.sl}xATR  TP={args.tp}xATR  Days={args.days}")
    print("=" * 60)
    print(f"  Trades:          {stats.get('total_trades', 0)}"
          f" (L {stats.get('long_trades', 0)} / S {stats.get('short_trades', 0)})")
    print(f"  Win rate:        {stats.get('win_rate_pct', 0):.1f}%"
          f" (L {stats.get('long_win_rate', 0):.1f}% / S {stats.get('short_win_rate', 0):.1f}%)")
    print(f"  Gross P&L:       ₹{stats.get('gross_pnl', 0):,.2f}")
    print(f"  Costs:           ₹{stats.get('total_cost', 0):,.2f}")
    print(f"  Net P&L:         ₹{stats.get('net_pnl', 0):,.2f}")
    print(f"  Avg net/trade:   ₹{stats.get('avg_net_pnl', 0):,.2f}")
    print(f"  Avg R:           {stats.get('avg_r', 0):.3f}")
    print(f"  Start capital:   ₹{FNO_CAPITAL:,.2f}")
    print(f"  Final capital:   ₹{stats.get('final_capital', 0):,.2f}")
    print(f"  Return:          {stats.get('return_pct', 0):.2f}%")
    print(f"  Max drawdown:    ₹{stats.get('max_drawdown', 0):,.2f}"
          f" ({stats.get('max_drawdown_pct', 0):.1f}%)")
    print(f"  Time:            {elapsed:.1f}s")
    print("=" * 60)

    if args.save:
        out_path = Path(f"data/backtest_nifty_futures_sl{args.sl}_tp{args.tp}.json")
        out_path.write_text(json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "config": {"sl_mult": args.sl, "tp_mult": args.tp, "days": args.days,
                       "capital": FNO_CAPITAL, "lot_size": LOT_SIZE},
            "stats": stats,
        }, indent=2))
        _log.info("Saved to %s", out_path)

        # Also save trades
        trades_path = Path(f"data/backtest_trades_nifty_futures_sl{args.sl}_tp{args.tp}.json")
        trades_path.write_text(json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "trades": [t for t in trades if t.get("status") == "CLOSED"],
        }, indent=2))
        _log.info("Trades saved to %s", trades_path)


if __name__ == "__main__":
    main()
