"""
Phase B3b — Walk-forward evaluation of the ML Standalone Strategy.

A single contiguous train/val/test split is fragile: if the val slice lands in
one market regime (e.g. a bear market for a LONG-only model) the threshold picked
there does not transfer. This runs an EXPANDING-WINDOW walk-forward (same method
as Phase 14): for each fold, fit on everything before the fold, pick the
threshold on a small val slice, then measure NET rupees on the untouched test
slice. Aggregating across folds averages threshold selection over regimes and
gives an honest OOS number.

Also supports an optional NIFTY regime gate (--regime-gate): only consider LONG
bars where NIFTY is not in a daily downtrend — the classic fix for a LONG-only
strategy's bear-market bleed.

Usage:
  .venv/bin/python scripts/walkforward_ml_strategy.py
  .venv/bin/python scripts/walkforward_ml_strategy.py --regime-gate
  .venv/bin/python scripts/walkforward_ml_strategy.py --folds 4 --regime-gate
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.train_ml_strategy import build_xy, DEFAULT_DS  # noqa: E402

MIN_VAL_TRADES = 30


def _fit(Xtr, ytr):
    from xgboost import XGBClassifier
    pos = max(int(ytr.sum()), 1)
    neg = max(int((ytr == 0).sum()), 1)
    clf = XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=neg / pos, eval_metric="logloss",
        random_state=42, n_jobs=8,
    )
    clf.fit(Xtr, ytr)
    return clf


def _pick_threshold(proba_val, pnl_val, thresholds):
    """Selectivity-first: highest threshold that is net-positive on val with
    >= MIN_VAL_TRADES kept."""
    chosen = None
    for thr in thresholds:
        m = proba_val >= thr
        if m.sum() >= MIN_VAL_TRADES and pnl_val[m].sum() > 0:
            chosen = thr
    return chosen if chosen is not None else thresholds[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=DEFAULT_DS)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--regime-gate", action="store_true",
                    help="only trade LONG when NIFTY 1d trend is not DOWN")
    ap.add_argument("--fixed-thr", type=float, default=0.0,
                    help="use a fixed a-priori threshold instead of val-selection")
    ap.add_argument("--save-trades", type=str, default="",
                    help="dump per-trade (fold, proba, pnl_net, direction, net_pos) "
                         "for the gated test bars to CSV (for Phase B sizing sim)")
    args = ap.parse_args()

    df = pd.read_parquet(args.dataset).sort_values("timestamp").reset_index(drop=True)
    print(f"Loaded {len(df):,} bars from {df['symbol'].nunique()} symbols")

    regime_ok = None
    if args.regime_gate:
        # NIFTY not in a daily downtrend (UP or FLAT).
        regime_ok = (df.get("nifty_1d_trend", pd.Series(["FLAT"] * len(df))) != "DOWN").values
        print(f"Regime gate ON: {100*regime_ok.mean():.1f}% of bars are NIFTY non-downtrend")

    X, y, pnl = build_xy(df)
    y = y.values
    n = len(X)
    thresholds = [round(x, 2) for x in np.arange(0.50, 0.96, 0.05)]

    # Expanding window: fold k tests slice [ (0.5 + 0.5*k/F) ... ].  We carve the
    # back half of the timeline into F disjoint test slices; val is the 5% just
    # before each test slice; train is everything before val.
    F = args.folds
    agg_base_net = agg_ml_net = agg_ml_trades = 0
    agg_ml_wins = 0
    trade_rows = []   # for --save-trades (Phase B sizing experiment)
    print(f"\n{'fold':>4s} {'thr':>5s} {'testBars':>9s} {'raw net':>12s} "
          f"{'ML trades':>9s} {'ML net':>12s} {'net/tr':>7s} {'WR':>6s}")
    for k in range(F):
        test_lo = 0.5 + 0.5 * k / F
        test_hi = 0.5 + 0.5 * (k + 1) / F
        i_test_lo, i_test_hi = int(n * test_lo), int(n * test_hi)
        i_val_lo = int(n * (test_lo - 0.05))
        Xtr, ytr = X.iloc[:i_val_lo], y[:i_val_lo]
        Xval, pnlval = X.iloc[i_val_lo:i_test_lo], pnl[i_val_lo:i_test_lo]
        Xte, yte, pnlte = X.iloc[i_test_lo:i_test_hi], y[i_test_lo:i_test_hi], pnl[i_test_lo:i_test_hi]
        if len(Xte) < 100 or len(Xval) < 100:
            continue

        clf = _fit(Xtr, ytr)
        proba_val = clf.predict_proba(Xval)[:, 1]
        proba_te = clf.predict_proba(Xte)[:, 1]

        gate_val = np.ones(len(Xval), bool)
        gate_te = np.ones(len(Xte), bool)
        if regime_ok is not None:
            gate_val = regime_ok[i_val_lo:i_test_lo]
            gate_te = regime_ok[i_test_lo:i_test_hi]

        thr = _pick_threshold(proba_val[gate_val], pnlval[gate_val], thresholds)
        if args.fixed_thr > 0:
            thr = args.fixed_thr
        m = (proba_te >= thr) & gate_te
        n_kept = int(m.sum())
        ml_net = pnlte[m].sum() if n_kept else 0.0
        base_net = pnlte.sum()
        wr = 100 * yte[m].mean() if n_kept else 0.0

        agg_base_net += base_net
        agg_ml_net += ml_net
        agg_ml_trades += n_kept
        agg_ml_wins += int(yte[m].sum()) if n_kept else 0
        print(f"{k+1:>4d} {thr:5.2f} {len(Xte):9,d} {base_net:+12,.0f} "
              f"{n_kept:9,d} {ml_net:+12,.0f} "
              f"{(ml_net/n_kept if n_kept else 0):+7.0f} {wr:5.1f}%")

        # ── Phase B: collect gated test bars for sizing simulation ──
        if args.save_trades:
            Xte_dir = X.iloc[i_test_lo:i_test_hi]
            dir_long = Xte_dir.get("direction_LONG", pd.Series(0, index=Xte_dir.index)).values
            dirs = np.where(dir_long == 1, "LONG", "SHORT")
            mask = gate_te
            fold_rows = pd.DataFrame({
                "fold": k + 1,
                "proba": proba_te[mask],
                "pnl_net": pnlte[mask],
                "direction": dirs[mask],
                "net_pos": yte[mask].astype(int),
            })
            trade_rows.append(fold_rows)

    print("\n  ── AGGREGATE OOS (walk-forward) ──")
    print(f"  raw (all bars):  net ₹{agg_base_net:+,.0f}")
    if agg_ml_trades:
        print(f"  ML-filtered:     net ₹{agg_ml_net:+,.0f} over {agg_ml_trades:,} trades "
              f"({agg_ml_net/agg_ml_trades:+.0f}/trade), "
              f"WR {100*agg_ml_wins/agg_ml_trades:.1f}%")
    verdict = ("WORKS OOS (net-positive aggregate across folds)"
               if agg_ml_trades >= 50 and agg_ml_net > 0
               else "NOT ROBUST across folds")
    print(f"  VERDICT: {verdict}")

    if args.save_trades and trade_rows:
        out = pd.concat(trade_rows, ignore_index=True)
        out.to_csv(args.save_trades, index=False)
        print(f"\n  Saved {len(out):,} per-trade rows (gated test bars) -> {args.save_trades}")


if __name__ == "__main__":
    main()
