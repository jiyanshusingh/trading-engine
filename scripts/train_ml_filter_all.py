"""
Options A + C — ML filter (all symbols) and ML strategy-selector.

Both operate on the SAME pooled dataset: the 3 deployed strategies (RSM, Combined
Swing, Manual) run across the FULL universe (data/backtest_trades_15m_mlall_*.json).

  Option A (Universal Filter): the Phase 30 filter, but trained on ALL symbols
    (not just the 56 pruned). For each strategy signal, predict P(net-positive)
    and keep only the high-confidence tail. `strategy` is a feature, so the model
    already conditions on which strategy produced the signal.

  Option C (Strategy Selector): an INFERENCE POLICY on top of the same model.
    When multiple strategies fire on the same (symbol, day), take ONLY the single
    highest-proba signal instead of all approved ones — explicit strategy
    selection / conflict resolution rather than independent filtering.

Rigor mirrors Phase 30: TIME 3-way split (train 50 / val 20 / test 30), the
selectivity-first threshold picked on val, all numbers reported on the untouched
test set by NET rupees.

Usage:
  .venv/bin/python scripts/train_ml_filter_all.py \
    data/backtest_trades_15m_mlall_rsm.json \
    data/backtest_trades_15m_mlall_combined.json \
    data/backtest_trades_15m_mlall_manual.json
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.train_ml_filter import load_trades, build_xy, evaluate  # noqa: E402

MIN_VAL_TRADES = 30
MODEL_PATH = "data/ml_filter_all.json"
META_PATH = "data/ml_filter_all_meta.json"


def pick_threshold(proba_val, pnl_val, thresholds):
    """Selectivity-first: highest threshold net-positive on val with >= MIN kept."""
    chosen = None
    for thr in thresholds:
        m = proba_val >= thr
        if m.sum() >= MIN_VAL_TRADES and pnl_val[m].sum() > 0:
            chosen = thr
    return chosen if chosen is not None else thresholds[-1]


def main():
    from xgboost import XGBClassifier
    paths = sys.argv[1:] or [
        "data/backtest_trades_15m_mlall_rsm.json",
        "data/backtest_trades_15m_mlall_combined.json",
        "data/backtest_trades_15m_mlall_manual.json",
    ]
    df = load_trades(paths)
    if len(df) < 500:
        print("Not enough trades."); return

    X, y, pnl, meta = build_xy(df)
    meta = meta.reset_index(drop=True)
    n = len(X)
    i_tr, i_val = int(n * 0.50), int(n * 0.70)
    Xtr, Xval, Xte = X.iloc[:i_tr], X.iloc[i_tr:i_val], X.iloc[i_val:]
    ytr, yval, yte = y.iloc[:i_tr], y.iloc[i_tr:i_val], y.iloc[i_val:]
    pnltr, pnlval, pnlte = pnl[:i_tr], pnl[i_tr:i_val], pnl[i_val:]
    meta_te = meta.iloc[i_val:].reset_index(drop=True)
    print(f"\nTime split: train={len(Xtr):,} (net ₹{pnltr.sum():+,.0f})  "
          f"val={len(Xval):,} (net ₹{pnlval.sum():+,.0f})  "
          f"test={len(Xte):,} (net ₹{pnlte.sum():+,.0f})")
    print(f"Features: {X.shape[1]}  symbols: {df['symbol'].nunique()}")

    pos = max(int(ytr.sum()), 1)
    neg = max(int((ytr == 0).sum()), 1)
    clf = XGBClassifier(
        n_estimators=400, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=neg / pos, eval_metric="logloss",
        random_state=42, n_jobs=8,
    )
    clf.fit(Xtr, ytr)

    thresholds = [round(x, 2) for x in np.arange(0.50, 0.91, 0.05)]
    proba_val = clf.predict_proba(Xval)[:, 1]
    print("\n  VALIDATION sweep:")
    evaluate("val", proba_val, yval.values, pnlval, thresholds)
    thr = pick_threshold(proba_val, pnlval, thresholds)

    proba_te = clf.predict_proba(Xte)[:, 1]
    print(f"\n  TEST sweep (deploy thr={thr}):")
    evaluate("test", proba_te, yte.values, pnlte, thresholds)

    # ── Option A: independent filter ──
    mA = proba_te >= thr
    nA = int(mA.sum()); netA = pnlte[mA].sum() if nA else 0.0
    base = pnlte.sum()

    # ── Option C: best strategy per (symbol, day) among approved ──
    te = meta_te.copy()
    te["proba"] = proba_te
    te["pnl_net"] = pnlte
    te["y"] = yte.values
    te["day"] = pd.to_datetime(te["entry_timestamp"]).dt.date
    appr = te[te["proba"] >= thr].copy()
    # keep only the single highest-proba signal per (symbol, day)
    best = appr.sort_values("proba").groupby(["symbol", "day"], as_index=False).tail(1)
    nC = len(best); netC = best["pnl_net"].sum() if nC else 0.0

    print("\n  ══════════ RESULTS (untouched TEST, net rupees) ══════════")
    print(f"  RAW (all signals):        net ₹{base:+,.0f} over {len(pnlte):,} trades "
          f"({base/len(pnlte):+.0f}/trade)")
    if nA:
        print(f"  OPTION A (filter ≥{thr}):    net ₹{netA:+,.0f} over {nA:,} trades "
              f"({netA/nA:+.0f}/trade), WR {100*yte.values[mA].mean():.1f}%")
    if nC:
        print(f"  OPTION C (best/sym/day):  net ₹{netC:+,.0f} over {nC:,} trades "
              f"({netC/nC:+.0f}/trade), WR {100*(best['y']==1).mean():.1f}%")
    print("  ══════════════════════════════════════════════════════════")
    va = "WORKS" if nA >= 20 and netA > 0 else "not robust"
    vc = "WORKS" if nC >= 20 and netC > 0 else "not robust"
    print(f"  Option A verdict: {va}   |   Option C verdict: {vc}")

    imp = sorted(zip(X.columns, clf.feature_importances_), key=lambda x: -x[1])[:15]
    print("\n  Top features:")
    for f, v in imp:
        print(f"    {f:32s} {v:.3f}")

    clf.save_model(MODEL_PATH)
    json.dump({"threshold": thr, "features": list(X.columns),
               "test_net_filter": float(netA), "test_trades_filter": int(nA),
               "test_net_selector": float(netC), "test_trades_selector": int(nC)},
              open(META_PATH, "w"), indent=2)
    print(f"\n  Saved model -> {MODEL_PATH}")


if __name__ == "__main__":
    main()
