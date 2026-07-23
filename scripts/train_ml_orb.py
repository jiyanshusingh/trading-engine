"""
Phase C2 — Opening-minutes ML model training.

Trains an XGBoost binary classifier on data/ml_orb_dataset.parquet to predict
whether an opening-window (09:15-10:30) 5m entry is net-profitable after costs
(pnl_net > 0), under the same SL 0.3% / TP 1.5% / max hold 48 the dataset used.

Direction is an input feature (one-hot), so a single model scores both LONG and
SHORT. Time-based split (first 70% train, last 30% test) to avoid lookahead.

Usage:
  .venv/bin/python scripts/train_ml_orb.py
  .venv/bin/python scripts/train_ml_orb.py --ds data/ml_orb_dataset.parquet
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import (precision_score, recall_score, roc_auc_score,
                             classification_report, confusion_matrix)

DS_PATH = "data/ml_orb_dataset.parquet"
MODEL_PATH = "data/ml_orb_model.json"
META_PATH = "data/ml_orb_model_meta.json"

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", type=str, default=DS_PATH)
    ap.add_argument("--model-out", type=str, default=MODEL_PATH)
    ap.add_argument("--meta-out", type=str, default=META_PATH)
    ap.add_argument("--test-size", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print(f"Loading {args.ds} ...")
    df = load_dataset(args.ds)
    print(f"  {len(df):,} rows, target balance: {100*df['target'].mean():.1f}% positive")

    # Time-based split: sort by timestamp, take first 70% train / last 30% test
    df = df.sort_values("timestamp").reset_index(drop=True)
    n = len(df)
    split = int(n * (1 - args.test_size))
    train_df = df.iloc[:split]
    test_df = df.iloc[split:]
    print(f"  train={len(train_df):,}, test={len(test_df):,} "
          f"(split at {df['timestamp'].iloc[split]})")

    X_train, y_train, feats = build_matrix(train_df, NUMERIC_FEATURES, CAT_FEATURES)
    X_test, y_test, _ = build_matrix(test_df, NUMERIC_FEATURES, CAT_FEATURES)
    # align test columns to train
    X_test = X_test.reindex(columns=feats, fill_value=0.0)

    print("Training XGBoost ...")
    model = xgb.XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
        reg_lambda=2.0, reg_alpha=1.0,
        objective="binary:logistic", eval_metric="logloss",
        random_state=args.seed, n_jobs=-1,
    )
    model.fit(X_train, y_train,
              eval_set=[(X_train, y_train), (X_test, y_test)],
              verbose=False)

    # ── Evaluate ──
    proba_train = model.predict_proba(X_train)[:, 1]
    proba_test = model.predict_proba(X_test)[:, 1]
    auc_train = roc_auc_score(y_train, proba_train)
    auc_test = roc_auc_score(y_test, proba_test)
    print(f"\nROC-AUC: train={auc_train:.3f} test={auc_test:.3f}")

    # Threshold sweep on test set optimising net PnL
    test_df = test_df.copy()
    test_df["proba"] = proba_test
    best_thr, best_pnl = 0.5, -1e18
    for thr in np.round(np.arange(0.50, 0.96, 0.01), 2):
        sel = test_df[test_df["proba"] >= thr]
        if len(sel) == 0:
            continue
        pnl = sel[LABEL].sum()
        if pnl > best_pnl:
            best_pnl, best_thr = pnl, thr
    print(f"\nBest threshold (max test net PnL): {best_thr:.2f}")
    print(f"  trades taken: {(test_df['proba']>=best_thr).sum():,}")
    print(f"  test net PnL: ₹{best_pnl:,.0f}")
    print(f"  test WR: {100*(test_df[test_df['proba']>=best_thr][LABEL]>0).mean():.1f}%")

    # Report at a few fixed thresholds
    for thr in [0.6, 0.7, 0.8, 0.9]:
        sel = test_df[test_df["proba"] >= thr]
        if len(sel) == 0:
            print(f"  thr={thr}: 0 trades"); continue
        wr = 100 * (sel[LABEL] > 0).mean()
        pnl = sel[LABEL].sum()
        prec = precision_score(y_test, (proba_test >= thr).astype(int), zero_division=0)
        rec = recall_score(y_test, (proba_test >= thr).astype(int), zero_division=0)
        print(f"  thr={thr}: n={len(sel):5d} WR={wr:5.1f}% netPnL=₹{pnl:+10,.0f} "
              f"prec={prec:.3f} rec={rec:.3f}")

    # Feature importance (gain)
    imp = model.get_booster().get_score(importance_type="gain")
    imp_sorted = sorted(imp.items(), key=lambda x: x[1], reverse=True)[:15]
    print("\nTop features (gain):")
    for f, v in imp_sorted:
        print(f"  {f:32s} {v:8.1f}")

    # Save
    model.save_model(args.model_out)
    meta = {
        "features": feats,
        "threshold": float(best_thr),
        "sl_pct": 0.003, "tp_pct": 0.015, "max_hold": 48,
        "label": "pnl_net > 0 (SL 0.3% / TP 1.5% / 48 bars, both directions)",
        "auc_test": float(auc_test), "auc_train": float(auc_train),
        "test_net_pnl": float(best_pnl), "n_train": len(train_df),
        "n_test": len(test_df),
    }
    with open(args.meta_out, "w") as f:
        import json
        json.dump(meta, f, indent=2)
    print(f"\nSaved model -> {args.model_out}")
    print(f"Saved meta  -> {args.meta_out}")


if __name__ == "__main__":
    main()
