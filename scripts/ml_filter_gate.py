"""
Phase 33 — Live inference wrapper for the ML Universal Filter (Option A).

Loads the full-universe filter model (`data/ml_filter_all.json`) and scores a
LIVE trade decision with the SAME feature vector the backtest logs, so the
paper/live trader can gate entries on P(net-positive-after-costs).

Feature parity is guaranteed by:
  1. reusing `WalkForwardBacktest._compute_entry_features` for the 8 technicals,
  2. replicating the exact `features` assembly from scripts/backtest.py, plus the
     `score`/`hour`/`weekday` additions and `DROP_FEATURES` from train_ml_filter,
  3. reindexing the one-hot row to the trained feature list (missing cols -> 0).

OOS (Phase 32): global thr 0.65 -> +₹108,598 over 795 test trades (+₹137/trade).
Per-symbol thresholds were tested and REJECTED (overfit, worse OOS) — use global.
"""

from __future__ import annotations

import json
import os

import pandas as pd

_MODEL = None
_FEATURES = None
_MODEL_PATH = "data/ml_filter_all.json"
_META_PATH = "data/ml_filter_all_meta.json"
DROP_FEATURES = {"htf_reason"}  # must match scripts/train_ml_filter.py


def _load() -> bool:
    """Lazy-load the model + feature list. Returns False if unavailable."""
    global _MODEL, _FEATURES
    if _MODEL is not None:
        return True
    if not (os.path.exists(_MODEL_PATH) and os.path.exists(_META_PATH)):
        return False
    try:
        from xgboost import XGBClassifier
        meta = json.load(open(_META_PATH))
        _FEATURES = meta["features"]
        m = XGBClassifier()
        m.load_model(_MODEL_PATH)
        _MODEL = m
        return True
    except Exception:
        return False


def filter_proba(window_df, htf_ctx, *, day_type, stock_type, strategy,
                 direction, score, htf_pass, entry_ts) -> float | None:
    """P(trade is net-positive after costs). None if it can't be scored."""
    if not _load():
        return None
    from scripts.backtest import WalkForwardBacktest
    feats = WalkForwardBacktest._compute_entry_features(window_df)
    if not feats:                       # <50 bars -> insufficient data
        return None
    feats["day_type"] = day_type
    feats["stock_type"] = stock_type
    feats["strategy"] = strategy
    feats["direction"] = direction
    feats["timeframe"] = "15m"
    feats.update(htf_ctx or {})
    feats["htf_pass"] = 1 if htf_pass else 0
    feats["score"] = score
    for c in DROP_FEATURES:
        feats.pop(c, None)
    ts = pd.to_datetime(entry_ts)
    feats["hour"] = ts.hour + ts.minute / 60.0
    feats["weekday"] = ts.weekday()
    # Session bucket (IST) — must match backtest.py feature assembly.
    hr = ts.hour + ts.minute / 60.0
    if hr < 10.0:
        feats["session"] = "opening"
    elif hr < 11.5:
        feats["session"] = "morning"
    elif hr < 14.0:
        feats["session"] = "midday"
    else:
        feats["session"] = "afternoon"

    X = pd.DataFrame([feats])
    # numeric where possible, one-hot the rest (mirrors build_xy), then align
    X = pd.get_dummies(X)
    X = X.reindex(columns=_FEATURES, fill_value=0)
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    try:
        return float(_MODEL.predict_proba(X)[0, 1])
    except Exception:
        return None


def passes_ml_filter(ctx, decision, threshold: float) -> tuple[bool, float | None]:
    """Gate a paper-trade decision. Returns (pass, proba).

    Fail-open: if the model can't score (missing model / insufficient bars),
    returns (True, None) so the filter never silently blocks all trades.
    """
    proba = filter_proba(
        ctx["window"], ctx.get("htf_ctx"),
        day_type=ctx.get("day_type"), stock_type=ctx.get("stock_type"),
        strategy=decision.strategy_name, direction=decision.direction,
        score=decision.score, htf_pass=getattr(decision, "htf_pass", 0),
        entry_ts=ctx.get("last_ts"),
    )
    if proba is None:
        return True, None
    return proba >= threshold, proba
