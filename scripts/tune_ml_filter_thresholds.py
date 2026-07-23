"""
Phase 33 — Per-symbol threshold tuning for the ML universal filter (Option A).

The global filter uses ONE threshold for all symbols. But some symbols are
reliable at 0.55 while others need 0.75+. This finds each symbol's own
threshold on the VALIDATION split and measures the result on the untouched
TEST split — proper OOS, same 50/20/30 time split as train_ml_filter_all.py.

Also saves a dated results file with the full global sweep + per-symbol map +
weekly trade-frequency estimates.

Usage:
  .venv/bin/python scripts/tune_ml_filter_thresholds.py \
    data/backtest_trades_15m_mlall_rsm.json \
    data/backtest_trades_15m_mlall_combined.json \
    data/backtest_trades_15m_mlall_manual.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.train_ml_filter import load_trades, build_xy  # noqa: E402

GLOBAL_THR = 0.65          # val-max-net global threshold (Phase 32)
CANDIDATES = [round(x, 2) for x in np.arange(0.50, 0.96, 0.05)]
MIN_VAL_KEEP = 6           # need >=6 kept val trades to trust a per-symbol thr
SKIP_THR = 0.99            # symbol effectively skipped (no net-positive val thr)
RESULTS_PATH = f"data/results/ml_filter_all_{date.today().isoformat()}.json"
THRESH_MAP_PATH = "data/ml_filter_symbol_thresholds.json"


def sweep(proba, pnl, y, thresholds):
    out = []
    base = float(pnl.sum())
    out.append({"thr": "ALL", "trades": int(len(pnl)), "kept_pct": 100.0,
                "wr": float(100 * (y == 1).mean()), "net": base,
                "net_per_trade": base / max(len(pnl), 1)})
    for thr in thresholds:
        m = proba >= thr
        n = int(m.sum())
        if n == 0:
            continue
        net = float(pnl[m].sum())
        out.append({"thr": thr, "trades": n, "kept_pct": 100.0 * n / len(pnl),
                    "wr": float(100 * y[m].mean()), "net": net,
                    "net_per_trade": net / n})
    return out


def pick_symbol_threshold(proba_s, pnl_s):
    """Best net-PnL threshold on this symbol's validation trades."""
    best_thr, best_net, best_n = None, None, 0
    for thr in CANDIDATES:
        m = proba_s >= thr
        n = int(m.sum())
        if n < MIN_VAL_KEEP:
            continue
        net = float(pnl_s[m].sum())
        if best_net is None or net > best_net:
            best_thr, best_net, best_n = thr, net, n
    if best_thr is None or best_net is None or best_net <= 0:
        return SKIP_THR, 0.0, 0        # nothing net-positive -> skip symbol
    return best_thr, best_net, best_n


def main():
    from xgboost import XGBClassifier
    paths = sys.argv[1:] or [
        "data/backtest_trades_15m_mlall_rsm.json",
        "data/backtest_trades_15m_mlall_combined.json",
        "data/backtest_trades_15m_mlall_manual.json",
    ]
    df = load_trades(paths)
    X, y, pnl, meta = build_xy(df)
    meta = meta.reset_index(drop=True)
    n = len(X)
    i_tr, i_val = int(n * 0.50), int(n * 0.70)

    Xtr, ytr = X.iloc[:i_tr], y.iloc[:i_tr]
    Xval, Xte = X.iloc[i_tr:i_val], X.iloc[i_val:]
    yval, yte = y.iloc[i_tr:i_val].values, y.iloc[i_val:].values
    pnlval, pnlte = pnl[i_tr:i_val], pnl[i_val:]
    meta_val = meta.iloc[i_tr:i_val].reset_index(drop=True)
    meta_te = meta.iloc[i_val:].reset_index(drop=True)

    pos = max(int(ytr.sum()), 1); neg = max(int((ytr == 0).sum()), 1)
    clf = XGBClassifier(
        n_estimators=400, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=neg / pos, eval_metric="logloss",
        random_state=42, n_jobs=8)
    clf.fit(Xtr, ytr)

    proba_val = clf.predict_proba(Xval)[:, 1]
    proba_te = clf.predict_proba(Xte)[:, 1]

    # ── global sweep on test (reference) ──
    global_sweep = sweep(proba_te, pnlte, yte, CANDIDATES)

    # ── per-symbol thresholds picked on VAL ──
    sym_thr = {}
    for symv in sorted(meta_val["symbol"].dropna().unique()):
        mask = (meta_val["symbol"] == symv).values
        thr, vnet, vn = pick_symbol_threshold(proba_val[mask], pnlval[mask])
        sym_thr[symv] = {"thr": thr, "val_net": vnet, "val_trades": vn}

    # ── apply per-symbol thresholds on TEST ──
    keep = np.zeros(len(pnlte), dtype=bool)
    te_sym = meta_te["symbol"].values
    for i in range(len(pnlte)):
        t = sym_thr.get(te_sym[i], {}).get("thr", GLOBAL_THR)
        keep[i] = proba_te[i] >= t
    ps_net = float(pnlte[keep].sum()); ps_n = int(keep.sum())
    ps_wr = float(100 * yte[keep].mean()) if ps_n else 0.0

    # global 0.65 for comparison
    g_mask = proba_te >= GLOBAL_THR
    g_net = float(pnlte[g_mask].sum()); g_n = int(g_mask.sum())

    # ── weekly frequency (test period) ──
    ts_te = pd.to_datetime(meta_te["entry_timestamp"])
    test_days = ts_te.dt.date.nunique()
    test_weeks = max(test_days / 5.0, 1e-9)
    test_start = str(ts_te.dt.date.min()); test_end = str(ts_te.dt.date.max())

    print(f"\n{'='*66}")
    print(f"  PER-SYMBOL THRESHOLD TUNING (OOS test {test_start}→{test_end})")
    print(f"{'='*66}")
    print(f"  GLOBAL thr {GLOBAL_THR}:      net ₹{g_net:+,.0f}  over {g_n:,} trades "
          f"({g_net/max(g_n,1):+.0f}/tr, {g_n/test_weeks:.0f}/wk)")
    print(f"  PER-SYMBOL thresholds:  net ₹{ps_net:+,.0f}  over {ps_n:,} trades "
          f"({ps_net/max(ps_n,1):+.0f}/tr, {ps_n/test_weeks:.0f}/wk), WR {ps_wr:.1f}%")
    delta = ps_net - g_net
    print(f"  Δ per-symbol vs global: ₹{delta:+,.0f} "
          f"({'BETTER' if delta > 0 else 'worse'})")

    active = {s: v for s, v in sym_thr.items() if v["thr"] < SKIP_THR}
    print(f"\n  {len(active)}/{len(sym_thr)} symbols have a net-positive threshold "
          f"(rest skipped). Sample:")
    for s, v in sorted(active.items(), key=lambda kv: kv[1]["thr"])[:12]:
        print(f"    {s:14s} thr {v['thr']:.2f}  (val {v['val_trades']} tr, ₹{v['val_net']:+,.0f})")

    # ── weekly estimate table (global sweep) ──
    print(f"\n  Weekly frequency by global threshold (test ≈ {test_weeks:.0f} wks):")
    print(f"  {'thr':>5s} {'trades':>7s} {'/wk':>6s} {'/day':>6s} {'net':>11s} {'net/wk':>9s}")
    weekly = []
    for r in global_sweep:
        if r["thr"] == "ALL":
            continue
        wk = r["trades"] / test_weeks
        row = {"thr": r["thr"], "trades": r["trades"], "per_week": round(wk, 1),
               "per_day": round(wk / 5, 2), "net": r["net"],
               "net_per_week": round(r["net"] / test_weeks)}
        weekly.append(row)
        print(f"  {r['thr']:5.2f} {r['trades']:7,d} {wk:6.1f} {wk/5:6.2f} "
              f"{r['net']:+11,.0f} {r['net']/test_weeks:+9,.0f}")

    # ── save dated results ──
    results = {
        "generated": date.today().isoformat(),
        "phase": "32-33: ML Universal Filter (Option A) + per-symbol thresholds",
        "universe_symbols": int(df["symbol"].nunique()),
        "pooled_trades": int(len(df)),
        "strategies": sorted(df["strategy"].dropna().unique().tolist()),
        "data_period": {"start": str(pd.to_datetime(meta["entry_timestamp"]).dt.date.min()),
                        "end": str(pd.to_datetime(meta["entry_timestamp"]).dt.date.max())},
        "split": {"train": i_tr, "val": i_val - i_tr, "test": n - i_val,
                  "scheme": "time 50/20/30"},
        "test_period": {"start": test_start, "end": test_end,
                        "trading_days": int(test_days), "weeks": round(test_weeks, 1)},
        "global_threshold_sweep_test": global_sweep,
        "weekly_estimates": weekly,
        "global_threshold": GLOBAL_THR,
        "global_result": {"net": g_net, "trades": g_n, "per_week": round(g_n / test_weeks, 1)},
        "per_symbol_result": {"net": ps_net, "trades": ps_n, "wr": ps_wr,
                              "per_week": round(ps_n / test_weeks, 1),
                              "delta_vs_global": delta},
        "per_symbol_thresholds": sym_thr,
    }
    os.makedirs("data/results", exist_ok=True)
    json.dump(results, open(RESULTS_PATH, "w"), indent=2, default=str)
    json.dump({s: v["thr"] for s, v in sym_thr.items()},
              open(THRESH_MAP_PATH, "w"), indent=2)
    print(f"\n  Saved results  -> {RESULTS_PATH}")
    print(f"  Saved thr map  -> {THRESH_MAP_PATH}")


if __name__ == "__main__":
    main()
