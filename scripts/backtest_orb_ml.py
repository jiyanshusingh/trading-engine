"""
Phase C3 — Opening-minutes ML backtest.

Loads data/ml_orb_model.json and, for each 5m bar in the opening window
(09:15-10:30) across all cached 5m symbols, computes the same features the model
was trained on, scores LONG + SHORT, and enters whichever clears the deploy
threshold. Trades use the same SL 0.3% / TP 1.5% / max hold 48 the model trained on.

Reuses the feature helpers from scripts/ml_dataset_orb_5m.py so training/serving
feature parity is guaranteed.

Usage:
  .venv/bin/python scripts/backtest_orb_ml.py --threshold 0.65
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.downloader.data_registry import get_bars  # noqa: E402
from scripts.ml_dataset_orb_5m import (  # reuse feature parity helpers
    compute_stock_features, add_opening_features, compute_nifty_context,
    classify_gap, label_forward_5m, SL_PCT, TP_PCT, MAX_HOLD, GAP_THRESHOLD,
)

MODEL_PATH = "data/ml_orb_model.json"
META_PATH = "data/ml_orb_model_meta.json"

RAW_NUMERIC = [
    "gap_pct", "opening_range_15m_pct", "opening_range_30m_pct",
    "price_position_in_range_15m", "price_position_in_range_30m",
    "first_bar_return", "first_bar_range_pct", "first_bar_volume_ratio",
    "cum_return_since_open", "minutes_since_open", "prev_day_range_pct",
    "prev_day_return", "rsi_14", "atr_pct", "volume_ratio", "bb_width",
    "recent_high_dist_pct", "recent_low_dist_pct", "ema20_dist_pct",
    "ema50_dist_pct", "nifty_1d_return", "nifty_gap_pct",
    "hour", "minute", "weekday",
]
RAW_CAT = ["direction", "gap_dir", "nifty_1d_trend"]

# Cost model (net-of-costs, round trip)
STT = 0.00025
BROKERAGE = 0.0005
SLIPPAGE = 0.0005
COST_RATE = STT + BROKERAGE + 2 * SLIPPAGE


def build_features(symbol, nifty_feat_map):
    """Return a per-bar feature df for the opening window of every day."""
    df5 = get_bars(symbol, "5m", 100000, live=False)
    if df5 is None or len(df5) < 130:
        return None
    df5 = df5.sort_values("timestamp").reset_index(drop=True)
    df5["timestamp"] = pd.to_datetime(df5["timestamp"])
    df5["date"] = df5["timestamp"].dt.date
    df5["time"] = df5["timestamp"].dt.time

    feat = compute_stock_features(df5)
    feat["date"] = df5["date"].values
    feat["time"] = df5["time"].values
    feat["open"] = df5["open"].values
    feat["volume"] = df5["volume"].values

    days = sorted(df5["date"].unique())
    frames = []
    for idx, day in enumerate(days):
        if idx == 0:
            continue
        day_df = feat[feat["date"] == day]
        if len(day_df) == 0:
            continue
        window_mask = ((day_df["time"] >= pd.Timestamp("09:15").time()) &
                       (day_df["time"] <= pd.Timestamp("10:30").time()))
        if not window_mask.any():
            continue
        enriched = add_opening_features(day_df, df5, day, days, idx, nifty_feat_map)
        enriched = enriched[window_mask].copy()
        frames.append(enriched)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def predict_features(model, features, df):
    X = df[features].copy()
    X = pd.get_dummies(X, columns=["gap_dir", "nifty_1d_trend"], dummy_na=False)
    X = X.reindex(columns=features, fill_value=0.0)
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return model.predict_proba(X)[:, 1]


def simulate_trade(df5, entry_ts, direction, close_series):
    """Forward-simulate the fixed SL/TP trade from entry_ts; return net ret."""
    i = close_series.index[close_series["timestamp"] == entry_ts]
    if len(i) == 0:
        return None
    i = i[0]
    entry = float(close_series["close"].iloc[i])
    if entry <= 0:
        return None
    if direction == "LONG":
        sl = entry * (1 - SL_PCT)
        tp = entry * (1 + TP_PCT)
    else:
        sl = entry * (1 + SL_PCT)
        tp = entry * (1 - TP_PCT)
    end = min(i + 1 + MAX_HOLD, len(close_series))
    w = close_series.iloc[i + 1:end]
    if len(w) == 0:
        return None
    if direction == "LONG":
        sl_hits = w["low"].values <= sl
        tp_hits = w["high"].values >= tp
    else:
        sl_hits = w["high"].values >= sl
        tp_hits = w["low"].values <= tp
    sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else -1
    tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else -1
    if sl_idx >= 0 and tp_idx >= 0 and sl_idx == tp_idx:
        return None
    if sl_idx >= 0 and (tp_idx < 0 or sl_idx < tp_idx):
        exit_px = sl
    elif tp_idx >= 0 and (sl_idx < 0 or tp_idx < sl_idx):
        exit_px = tp
    else:
        exit_px = w["close"].iloc[-1]
    gross = (exit_px - entry) / entry if direction == "LONG" else (entry - exit_px) / entry
    return gross - COST_RATE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=None,
                    help="deploy threshold (default: from model meta)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--take-best", action="store_true",
                    help="take only the single best-direction call per bar")
    args = ap.parse_args()

    meta = json.load(open(META_PATH))
    features = meta["features"]
    threshold = args.threshold if args.threshold is not None else meta["threshold"]
    print(f"Model threshold: {threshold:.2f} (auc_test={meta.get('auc_test', 0):.3f})")

    from xgboost import XGBClassifier
    model = XGBClassifier()
    model.load_model(MODEL_PATH)

    files = glob.glob("data/cache/5m/*.parquet")
    symbols = sorted(os.path.basename(f)[:-8] for f in files)
    symbols = [s for s in symbols if not s.startswith("^")]
    if args.limit:
        symbols = symbols[:args.limit]

    nifty_df = get_bars("^NSEI", "5m", 100000, live=False)
    nifty1d = get_bars("^NSEI", "1d", 100000, live=False)
    nifty_feat_map = compute_nifty_context(nifty_df, nifty1d)

    import time as _t
    all_trades = []
    t0 = _t.time()
    for k, sym in enumerate(symbols, 1):
        try:
            fdf = build_features(sym, nifty_feat_map)
        except Exception as e:
            print(f"  [{k}/{len(symbols)}] {sym} ERR: {e}")
            continue
        if fdf is None or fdf.empty:
            continue
        fdf = fdf.copy()
        # Re-score with explicit direction (the model takes direction as a feature)
        long_rows = fdf.copy(); long_rows["direction"] = "LONG"
        short_rows = fdf.copy(); short_rows["direction"] = "SHORT"
        for dset, d in [(long_rows, "LONG"), (short_rows, "SHORT")]:
            X = dset[[c for c in RAW_NUMERIC + RAW_CAT if c in dset.columns]].copy()
            X = pd.get_dummies(X, columns=RAW_CAT, dummy_na=False)
            X = X.reindex(columns=features, fill_value=0.0)
            X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)
            dset["proba"] = model.predict_proba(X)[:, 1]
        fdf["proba_long"] = long_rows["proba"].values
        fdf["proba_short"] = short_rows["proba"].values

        df5 = get_bars(sym, "5m", 100000, live=False)
        df5 = df5.sort_values("timestamp").reset_index(drop=True)
        df5["timestamp"] = pd.to_datetime(df5["timestamp"])

        for _, row in fdf.iterrows():
            entry_ts = row["timestamp"]
            taken = False
            for d, p in [("LONG", row["proba_long"]), ("SHORT", row["proba_short"])]:
                if p >= threshold:
                    net = simulate_trade(df5, entry_ts, d, df5)
                    if net is None:
                        continue
                    all_trades.append({
                        "symbol": sym, "direction": d, "entry_time": str(entry_ts),
                        "net_ret": net, "proba": p,
                    })
                    taken = True
                    if args.take_best:
                        break
            _ = taken
        if k % 20 == 0:
            print(f"  [{k}/{len(symbols)}] done ({_t.time()-t0:.0f}s)")

    if not all_trades:
        print("No trades generated"); return
    res = pd.DataFrame(all_trades)
    print(f"\nTotal ML ORB trades: {len(res)}")
    wins = (res["net_ret"] > 0).sum()
    print(f"WR: {100*wins/len(res):.1f}%")
    print(f"Avg net ret/trade: {res['net_ret'].mean()*100:.3f}%")
    print(f"Total net ret (sum): {res['net_ret'].sum()*100:.2f}%")
    for d in ["LONG", "SHORT"]:
        sub = res[res["direction"] == d]
        if len(sub):
            w = (sub["net_ret"] > 0).sum()
            print(f"  {d}: {len(sub)} trades, WR {100*w/len(sub):.1f}%, "
                  f"avg net {sub['net_ret'].mean()*100:.3f}%, sum {sub['net_ret'].sum()*100:.2f}%")
    res.to_json(f"data/orb_ml_results_{threshold}.json", orient="records")
    print(f"Saved data/orb_ml_results_{threshold}.json")


if __name__ == "__main__":
    main()
