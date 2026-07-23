"""
Walk-forward OOS validation for ML Opening Breakout — WITH capital constraints.

Same 4-fold expanding-window methodology but now simulates:
  - ₹50k capital, no leverage
  - 1% risk per trade (₹500)
  - 5 entries/day cap
  - Cash-aware: ₹50k notional per trade, deducted when open, restored at close
  - Holding period estimated from pnl_net value

Usage:
  .venv/bin/python scripts/walkforward_orb_ml.py --capital 50000
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import xgboost as xgb

DS_PATH = "data/ml_orb_dataset.parquet"

NUMERIC_FEATURES = [
    "gap_pct", "opening_range_15m_pct", "opening_range_30m_pct",
    "price_position_in_range_15m", "price_position_in_range_30m",
    "first_bar_return", "first_bar_range_pct", "first_bar_volume_ratio",
    "cum_return_since_open", "minutes_since_open", "prev_day_range_pct",
    "prev_day_return", "rsi_14", "atr_pct", "volume_ratio", "bb_width",
    "recent_high_dist_pct", "recent_low_dist_pct", "ema20_dist_pct",
    "ema50_dist_pct", "nifty_1d_return", "nifty_gap_pct",
    "hour", "minute", "weekday",
]
CAT_FEATURES = ["direction", "gap_dir", "nifty_1d_trend"]
LABEL = "pnl_net"

# Holding-period estimate from pnl_net thresholds (based on ₹50k notional)
TP_MIN = 500        # pnl_net ≥ ₹500 → TP was hit → ~30 min avg hold
SL_MAX = -150       # pnl_net ≤ -₹150 → SL was hit → ~10 min avg hold
HOLD_TP_BARS = 6    # 30 min @ 5m
HOLD_SL_BARS = 2    # 10 min @ 5m
HOLD_MAX_BARS = 48  # 4h (max_hold)


def load_dataset(path):
    df = pd.read_parquet(path)
    df = df.dropna(subset=NUMERIC_FEATURES + CAT_FEATURES + [LABEL]).reset_index(drop=True)
    df["target"] = (df[LABEL] > 0).astype(int)
    return df


def build_matrix(df, numeric, cat):
    X = df[numeric + cat].copy()
    X = pd.get_dummies(X, columns=cat, dummy_na=False)
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    y = df["target"].values
    return X, y, list(X.columns)


def estimate_hold_bars(pnl):
    if pnl >= TP_MIN:
        return HOLD_TP_BARS
    elif pnl <= SL_MAX:
        return HOLD_SL_BARS
    return HOLD_MAX_BARS


def simulate_portfolio(signals: pd.DataFrame, capital: float,
                       max_daily: int = 5) -> dict:
    """Simulate capital-constrained trading with daily cap and concurrency.

    ``signals`` must have columns: timestamp, pnl_net (already sorted).
    Returns dict with trades, net_pnl, equity_curve, etc.
    """
    signals = signals.sort_values("timestamp").reset_index(drop=True)
    cash = capital
    equity = capital
    peak = capital
    trades_taken = []
    entries_today: dict[date, int] = {}
    position = None  # {end_time, pnl}

    for _, row in signals.iterrows():
        ts = row["timestamp"]
        d = ts.date()

        # --- Check daily cap ---
        entries_today.setdefault(d, 0)
        if entries_today[d] >= max_daily:
            continue

        # --- Check if previous position has expired ---
        if position is not None and ts >= position["end_time"]:
            cash += position["pnl_return"]
            equity += position["pnl_return"]
            peak = max(peak, equity)
            trades_taken.append(position["pnl"])
            position = None

        # --- Can't enter if a position is still open (₹50k locked) ---
        if position is not None:
            continue

        # --- Enter ---
        pnl = row[LABEL]
        hold_bars = estimate_hold_bars(pnl)
        # 5m bars → timedelta
        end_time = ts + pd.Timedelta(minutes=5 * hold_bars)

        position = {
            "end_time": end_time,
            "pnl": pnl,
            "pnl_return": pnl,  # pnl_net already includes costs
            "entry_time": ts,
        }
        entries_today[d] += 1

    # Flush final position
    if position is not None:
        cash += position["pnl_return"]
        equity += position["pnl_return"]
        trades_taken.append(position["pnl"])

    total_pnl = sum(trades_taken)
    wins = sum(1 for p in trades_taken if p > 0)
    losses = sum(1 for p in trades_taken if p < 0)
    wr = 100 * wins / len(trades_taken) if trades_taken else 0

    return {
        "trades": len(trades_taken),
        "wins": wins,
        "losses": losses,
        "wr": round(wr, 1),
        "net_pnl": round(total_pnl, 2),
        "net_per_trade": round(total_pnl / len(trades_taken), 2) if trades_taken else 0,
        "final_equity": round(equity, 2),
        "peak_equity": round(peak, 2),
    }


def fold_windows(total_dates, n_folds):
    n = len(total_dates)
    for f in range(n_folds):
        train_end = int(n * (f + 1) / (n_folds + 1))
        test_end = int(n * (f + 2) / (n_folds + 1))
        train_dates = total_dates[:train_end]
        test_dates = total_dates[train_end:test_end]
        yield f + 1, train_dates, test_dates


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", type=str, default=DS_PATH)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--thr", type=float, default=0.70)
    ap.add_argument("--capital", type=float, default=50000)
    ap.add_argument("--max-daily", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print(f"Loading {args.ds} ...")
    df = load_dataset(args.ds)
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"  {len(df):,} rows, target balance: {100*df['target'].mean():.1f}% positive")
    print(f"  date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"  capital: ₹{args.capital:,.0f}, max daily: {args.max_daily}, "
          f"threshold: {args.thr}, folds: {args.folds}\n")

    all_dates = sorted(df["timestamp"].dt.date.unique())
    print(f"  unique trading days: {len(all_dates)}\n")

    fold_reports = []

    for fold_id, train_dates, test_dates in fold_windows(all_dates, args.folds):
        train_df = df[df["timestamp"].dt.date.isin(train_dates)].copy()
        test_df = df[df["timestamp"].dt.date.isin(test_dates)].copy()

        t0 = time.time()

        X_train, y_train, feats = build_matrix(train_df, NUMERIC_FEATURES, CAT_FEATURES)
        X_test, y_test_raw, _ = build_matrix(test_df, NUMERIC_FEATURES, CAT_FEATURES)
        X_test = X_test.reindex(columns=feats, fill_value=0.0)

        model = xgb.XGBClassifier(
            n_estimators=400, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
            reg_lambda=2.0, reg_alpha=1.0,
            objective="binary:logistic", eval_metric="logloss",
            random_state=args.seed, n_jobs=-1,
        )
        model.fit(X_train, y_train,
                  eval_set=[(X_train, y_train), (X_test, y_test_raw)],
                  verbose=False)

        proba = model.predict_proba(X_test)[:, 1]
        test_df = test_df.copy()
        test_df["proba"] = proba
        sel = test_df[test_df["proba"] >= args.thr].copy()

        # Unconstrained stats
        oos_trades_raw = len(sel)
        oos_pnl_raw = sel[LABEL].sum()
        oos_wr_raw = 100 * (sel[LABEL] > 0).mean()

        # Capital-constrained simulation
        sim = simulate_portfolio(sel, args.capital, args.max_daily)

        elapsed = time.time() - t0

        print(f"[Fold {fold_id}] "
              f"Raw: {oos_trades_raw:4d}tr WR={oos_wr_raw:5.1f}% ₹{oos_pnl_raw:>+9,.0f} | "
              f"Sim: {sim['trades']:3d}tr WR={sim['wr']:5.1f}% ₹{sim['net_pnl']:>+9,.0f} "
              f"(₹{sim['net_per_trade']:>+7,.0f}/tr)  {elapsed:.0f}s")

        fold_reports.append({
            "fold": fold_id,
            "train_dates": [str(d) for d in train_dates],
            "test_dates": [str(d) for d in test_dates],
            "train_rows": len(train_df),
            "test_rows": len(test_df),
            "raw": {
                "trades": oos_trades_raw,
                "wr": round(oos_wr_raw, 1),
                "net_pnl": round(oos_pnl_raw, 2),
            },
            "simulated": sim,
            "elapsed_s": round(elapsed, 1),
        })

    # ── Aggregate (capital-constrained) ──
    print(f"\n{'=' * 70}")
    print(f"WALK-FORWARD AGGREGATE — Capital-constrained (₹{args.capital:,.0f})")
    print(f"{'=' * 70}")
    print(f"{'Fold':<6}{'Trades':>8}{'WR':>8}{'Net PnL':>14}{'Net/tr':>10}{'Cap used':>10}")
    print(f"{'─' * 70}")
    total_tr = 0
    total_pnl = 0.0
    total_wins = 0
    total_losses = 0
    for r in fold_reports:
        s = r["simulated"]
        cap_used_pct = 100 * s["net_pnl"] / args.capital if args.capital > 0 else 0
        print(f"{r['fold']:<6}{s['trades']:>8,}{s['wr']:>7.1f}%"
              f"₹{s['net_pnl']:>+10,.0f}{'':>3}₹{s['net_per_trade']:>+7,.0f}"
              f"{cap_used_pct:>8.1f}%")
        total_tr += s["trades"]
        total_pnl += s["net_pnl"]
        total_wins += s["wins"]
        total_losses += s["losses"]
    print(f"{'─' * 70}")
    agg_wr = 100 * total_wins / total_tr if total_tr else 0
    agg_net_tr = total_pnl / total_tr if total_tr else 0
    agg_cap_pct = 100 * total_pnl / args.capital if args.capital > 0 else 0
    print(f"{'TOTAL':<6}{total_tr:>8,}{agg_wr:>7.1f}%"
          f"₹{total_pnl:>+10,.0f}{'':>3}₹{agg_net_tr:>+7,.0f}"
          f"{agg_cap_pct:>8.1f}%")

    # Save
    out = {
        "strategy": "ML Opening Breakout",
        "config": {
            "capital": args.capital,
            "max_daily_entries": args.max_daily,
            "threshold": args.thr,
            "folds": args.folds,
            "sl_pct": 0.003, "tp_pct": 0.015, "max_hold_bars": 48,
        },
        "dataset": {
            "path": args.ds,
            "rows": len(df),
            "date_range": [str(df["timestamp"].min()), str(df["timestamp"].max())],
            "trading_days": len(all_dates),
        },
        "aggregate_simulated": {
            "trades": total_tr,
            "wins": total_wins,
            "losses": total_losses,
            "wr": round(agg_wr, 1),
            "net_pnl": round(total_pnl, 2),
            "net_per_trade": round(agg_net_tr, 2),
            "return_on_capital_pct": round(agg_cap_pct, 1),
        },
        "folds": fold_reports,
        "generated": datetime.now().isoformat(),
    }

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = f"data/orb_walkforward_results_{date_str}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved -> {out_path}")

    if total_pnl > 0:
        print(f"\n✅ VERDICT: Net-positive OOS (₹{total_pnl:,.0f}) — "
              f"edge survives capital constraints")
    else:
        print(f"\n❌ VERDICT: Net-negative OOS — edge does NOT survive capital constraints")


if __name__ == "__main__":
    main()
