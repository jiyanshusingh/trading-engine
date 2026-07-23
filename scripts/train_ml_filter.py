"""
Phase 30 — ML net-profit filter.

Trains a classifier to predict whether a trade signal will be NET-POSITIVE
after costs (pnl_net > 0), using only entry-time features. The goal is NOT to
generate signals but to FILTER an existing strategy's signals down to the
high-conviction subset that clears the cost hurdle — directly attacking the
binding constraint identified in Phases 14/27/29 (cost-per-trade, not
direction).

Rigor:
  * Pools trades from multiple strategy backtests (each tagged by strategy).
  * TIME-based OOS split (train = earliest 60%, test = latest 40%) — never a
    random split (that would leak regime).
  * Evaluates on the held-out test set by NET RUPEES: does taking only the
    ML-approved trades beat taking all trades, and is it net-positive?

Usage:
  python scripts/train_ml_filter.py data/backtest_trades_15m_ml_rsm.json \
      data/backtest_trades_15m_ml_manual.json data/backtest_trades_15m_ml_combined.json
"""

import json
import sys

import numpy as np
import pandas as pd

DROP_FEATURES = {"htf_reason"}  # free-text, high-cardinality noise
TRAIN_FRAC = 0.60


def load_trades(paths: list[str]) -> pd.DataFrame:
    rows = []
    for p in paths:
        try:
            trades = json.load(open(p))
        except FileNotFoundError:
            print(f"  WARN missing {p}"); continue
        strat_tag = p.split("_ml_")[-1].replace(".json", "") if "_ml_" in p else p
        for t in trades:
            if t.get("pnl_net") is None or not t.get("features"):
                continue
            row = dict(t["features"])
            row["score"] = t.get("score", 0)
            row["direction"] = t.get("direction", "LONG")
            row["strategy"] = t.get("strategy", strat_tag)
            row["symbol"] = t.get("symbol")
            row["entry_timestamp"] = t.get("entry_timestamp")
            row["pnl_net"] = t["pnl_net"]
            rows.append(row)
    df = pd.DataFrame(rows)
    for c in DROP_FEATURES:
        df.drop(columns=[c], errors="ignore", inplace=True)
    print(f"Loaded {len(df)} trades from {len(paths)} files "
          f"({df['strategy'].nunique()} strategies, {df['symbol'].nunique()} symbols)")
    return df


def build_xy(df: pd.DataFrame):
    df = df.copy()
    df = df[df["entry_timestamp"].notna()].sort_values("entry_timestamp").reset_index(drop=True)
    ts = pd.to_datetime(df["entry_timestamp"])
    df["hour"] = ts.dt.hour + ts.dt.minute / 60.0
    df["weekday"] = ts.dt.weekday

    y = (df["pnl_net"] > 0).astype(int)
    pnl = df["pnl_net"].values
    meta = df[["symbol", "entry_timestamp", "strategy"]].copy()

    X = df.drop(columns=["pnl_net", "symbol", "entry_timestamp"])
    # Coerce: numeric where possible, else categorical -> one-hot
    cat_cols = []
    for c in list(X.columns):
        coerced = pd.to_numeric(X[c], errors="coerce")
        if coerced.notna().mean() >= 0.80:      # mostly numeric
            X[c] = coerced
        else:
            cat_cols.append(c)
    X = pd.get_dummies(X, columns=cat_cols, dummy_na=True)
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return X, y, pnl, meta


def evaluate(name, proba, y_test, pnl_test, thresholds):
    print(f"\n  {name}: threshold sweep on OOS test (net rupees)")
    print(f"  {'thr':>5s} {'trades':>7s} {'kept%':>6s} {'WR':>6s} {'netPnL':>10s} {'net/tr':>7s}")
    base_net = pnl_test.sum()
    print(f"  {'ALL':>5s} {len(pnl_test):7d} {'100%':>6s} "
          f"{100*(y_test==1).mean():5.1f}% {base_net:+10.0f} {base_net/len(pnl_test):+7.0f}")
    best = None
    for thr in thresholds:
        mask = proba >= thr
        n = int(mask.sum())
        if n < 10:
            continue
        net = pnl_test[mask].sum()
        wr = 100 * y_test[mask].mean()
        print(f"  {thr:5.2f} {n:7d} {100*n/len(pnl_test):5.1f}% {wr:5.1f}% "
              f"{net:+10.0f} {net/n:+7.0f}")
        if best is None or net > best[1]:
            best = (thr, net, n, wr)
    return best


def main():
    from xgboost import XGBClassifier
    paths = sys.argv[1:] or [
        "data/backtest_trades_15m_ml_rsm.json",
        "data/backtest_trades_15m_ml_manual.json",
        "data/backtest_trades_15m_ml_combined.json",
    ]
    df = load_trades(paths)
    if len(df) < 200:
        print("Not enough trades to train."); return
    X, y, pnl, meta = build_xy(df)

    n = len(X)
    # 3-way TIME split: train (fit model) / val (pick threshold) / test (final,
    # untouched). Picking the threshold on val — not test — avoids the optimism
    # of selecting the cutoff on the same data we report.
    i_tr = int(n * 0.50)
    i_val = int(n * 0.70)
    Xtr, Xval, Xte = X.iloc[:i_tr], X.iloc[i_tr:i_val], X.iloc[i_val:]
    ytr, yval, yte = y.iloc[:i_tr], y.iloc[i_tr:i_val], y.iloc[i_val:]
    pnltr, pnlval, pnlte = pnl[:i_tr], pnl[i_tr:i_val], pnl[i_val:]
    print(f"\nTime split: train={len(Xtr)} (net ₹{pnltr.sum():+,.0f})  "
          f"val={len(Xval)} (net ₹{pnlval.sum():+,.0f})  "
          f"test={len(Xte)} (net ₹{pnlte.sum():+,.0f})")
    print(f"Features: {X.shape[1]}")

    pos = max(int(ytr.sum()), 1)
    neg = max(int((ytr == 0).sum()), 1)
    clf = XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=neg / pos, eval_metric="logloss",
        random_state=42, n_jobs=8,
    )
    clf.fit(Xtr, ytr)

    thresholds = [round(x, 2) for x in np.arange(0.40, 0.91, 0.05)]
    # 1) show the val sweep and pick the threshold with best val net PnL
    #    (require >= 20 kept trades on val so we don't pick a noisy tail).
    proba_val = clf.predict_proba(Xval)[:, 1]
    print("\n  VALIDATION sweep (threshold picked here):")
    evaluate("val", proba_val, yval.values, pnlval, thresholds)
    # Selectivity-first rule (decided a-priori from the strategy thesis: only
    # extreme selectivity beats costs): pick the HIGHEST threshold that is still
    # net-positive on val with >= MIN_VAL_TRADES kept. Maximising val *total*
    # PnL instead over-selects a mid threshold full of marginal trades that do
    # not generalise.
    MIN_VAL_TRADES = 20
    chosen = None
    for thr in thresholds:
        m = proba_val >= thr
        if m.sum() >= MIN_VAL_TRADES and pnlval[m].sum() > 0:
            chosen = (thr, pnlval[m].sum())   # keep overwriting -> highest thr wins
    chosen_thr = chosen[0] if chosen else 0.75

    # 2) apply the CHOSEN threshold to the untouched TEST set — the honest number
    proba_te = clf.predict_proba(Xte)[:, 1]
    print(f"\n  TEST sweep (for reference; deploy uses fixed thr={chosen_thr}):")
    evaluate("test", proba_te, yte.values, pnlte, thresholds)

    m = proba_te >= chosen_thr
    n_kept = int(m.sum())
    net = pnlte[m].sum() if n_kept else 0.0
    base = pnlte.sum()
    print("\n  ── HONEST DEPLOYABLE RESULT ──")
    print(f"  val-chosen threshold = {chosen_thr}")
    print(f"  raw (unfiltered) TEST: net ₹{base:+,.0f} over {len(pnlte)} trades "
          f"({base/len(pnlte):+.0f}/trade)")
    if n_kept:
        print(f"  ML-filtered TEST:      net ₹{net:+,.0f} over {n_kept} trades "
              f"({net/n_kept:+.0f}/trade), WR {100*yte.values[m].mean():.1f}%")
    verdict = ("ML FILTER WORKS OOS (val-chosen thr → net-positive on untouched test)"
               if n_kept >= 20 and net > 0
               else "NOT ROBUST — val-chosen threshold is not net-positive on test")
    print(f"  VERDICT: {verdict}")

    imp = sorted(zip(X.columns, clf.feature_importances_), key=lambda x: -x[1])[:15]
    print("\n  Top features:")
    for f, v in imp:
        print(f"    {f:28s} {v:.3f}")

    clf.save_model("data/ml_net_filter.json")
    json.dump({"threshold": chosen_thr, "features": list(X.columns),
               "test_net": float(net), "test_trades": int(n_kept)},
              open("data/ml_net_filter_meta.json", "w"), indent=2)
    print("\n  Saved model -> data/ml_net_filter.json")


if __name__ == "__main__":
    main()
