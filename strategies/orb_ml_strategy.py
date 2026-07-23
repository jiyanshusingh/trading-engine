"""
Phase D — ML Opening Breakout strategy (executable wrapper).

A self-contained ML strategy that GENERATES entries from raw opening-minutes
market state. At the most recent completed 5m bar inside the opening window
(09:15-10:30 IST) it scores BOTH a LONG and a SHORT entry with the trained
model (data/ml_orb_model.json) and takes whichever clears the deploy threshold
(default 0.70). Exits use the same fixed SL 0.3% / TP 1.5% / max hold 48 bars
the model was trained on.

Feature parity with training is guaranteed by reusing the EXACT helpers the
dataset generator uses: compute_stock_features + add_opening_features +
compute_nifty_context (all from scripts/ml_dataset_orb_5m.py).

This mirrors the ML Standalone (Phase 31) pattern but is 5m + opening-window
constrained. Like ML Standalone it takes counter-trend entries (SHORT in an
uptrend etc.) so the HTF alignment filter and the ML filter are bypassed in the
paper trader; the model's own features (gap, opening range, NIFTY trend, hour)
already encode the timing/regime selection.
"""

from __future__ import annotations

import json
import logging
import os

import numpy as np
import pandas as pd

from strategies.executable import ExecutableStrategy, StrategyResult, TradeCandidate

_log = logging.getLogger("orb_ml_strategy")

MODEL_PATH = os.environ.get("ML_ORB_MODEL", "data/ml_orb_model.json")
META_PATH = os.environ.get("ML_ORB_META", "data/ml_orb_model_meta.json")

# Opening window (IST) during which entries are allowed.
OPEN_START = pd.Timestamp("09:15").time()
OPEN_END = pd.Timestamp("10:30").time()

# Model-trained trade parameters (also in meta, used as fallback).
SL_PCT = 0.003      # 0.3%
TP_PCT = 0.015      # 1.5%
MAX_HOLD_BARS = 48  # 4h @ 5m


class MLOpeningBreakoutStrategy(ExecutableStrategy):

    @property
    def name(self) -> str:
        return "ML Opening Breakout"

    def __init__(self, threshold: float | None = None, **kwargs):
        # Accept & ignore sl_mult/tp_mult/atr_period/min_score that the backtest
        # passes to all strategies — this strategy uses fixed % SL/TP baked into
        # the trained model's labels.
        self._model = None
        self._features: list[str] = []
        self._threshold = 0.70
        self._sl_pct = SL_PCT
        self._tp_pct = TP_PCT
        self._max_hold = MAX_HOLD_BARS
        # ML proba is the only gate; don't let the engine's score gate interfere.
        self.min_score = 0
        self._load()
        if threshold is not None:
            self._threshold = threshold

    def _load(self) -> None:
        try:
            from xgboost import XGBClassifier
            meta = json.load(open(META_PATH))
            self._features = meta["features"]
            self._threshold = meta.get("threshold", 0.70) if meta.get("threshold") else 0.70
            self._sl_pct = meta.get("sl_pct", SL_PCT)
            self._tp_pct = meta.get("tp_pct", TP_PCT)
            self._model = XGBClassifier()
            self._model.load_model(MODEL_PATH)
            _log.info("Loaded ML ORB model (%d features, thr=%.2f)",
                      len(self._features), self._threshold)
        except Exception as exc:
            _log.warning("ML ORB model unavailable (%s); strategy inert", exc)
            self._model = None

    # ── feature construction (opening-window bar, matches training) ──
    def _feature_row_for_bar(self, df5, feat, day, days, idx, nifty_feat_map):
        """Build the full opening-feature vector for the latest bar of ``day``."""
        from scripts.ml_dataset_orb_5m import add_opening_features
        day_df = feat[feat["date"] == day]
        enriched = add_opening_features(day_df, df5, day, days, idx, nifty_feat_map)
        if enriched is None or enriched.empty:
            return None
        return enriched.iloc[-1]  # latest (most-recent) completed bar of the day

    def _predict(self, rows: list[dict]) -> np.ndarray:
        X = pd.DataFrame(rows)
        cat = [c for c in ["direction", "gap_dir", "nifty_1d_trend"] if c in X.columns]
        X = pd.get_dummies(X, columns=cat, dummy_na=False)
        X = X.reindex(columns=self._features, fill_value=0.0)
        X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        return self._model.predict_proba(X)[:, 1]

    def run(self, df, symbol, timeframe, day_type="", stock_type="", **kwargs) -> StrategyResult:
        if self._model is None or df is None or len(df) < 130:
            return StrategyResult()

        nifty_df = kwargs.get("nifty_df")
        nifty_daily = kwargs.get("nifty_daily")
        from scripts.ml_dataset_orb_5m import compute_stock_features, compute_nifty_context
        nifty_feat_map = compute_nifty_context(nifty_df, nifty_daily)

        df5 = df.sort_values("timestamp").reset_index(drop=True)
        df5["timestamp"] = pd.to_datetime(df5["timestamp"])
        df5["date"] = df5["timestamp"].dt.date
        df5["time"] = df5["timestamp"].dt.time

        feat = compute_stock_features(df5)
        feat["date"] = df5["date"].values
        feat["time"] = df5["time"].values
        feat["open"] = df5["open"].values
        feat["volume"] = df5["volume"].values

        # Only evaluate the most recent completed bar.
        last = feat.iloc[-1]
        last_time = last["time"]
        if not (OPEN_START <= last_time <= OPEN_END):
            return StrategyResult(metadata={"reason": "outside-opening-window",
                                             "time": str(last_time)})

        days = sorted(df5["date"].unique())
        idx = days.index(last["date"])
        if idx == 0:
            return StrategyResult(metadata={"reason": "no-prior-day"})

        row = self._feature_row_for_bar(df5, feat, last["date"], days, idx,
                                        nifty_feat_map)
        if row is None:
            return StrategyResult(metadata={"reason": "no-features"})

        rows = []
        dirs = []
        for d in ("LONG", "SHORT"):
            r = dict(row)
            r["direction"] = d
            rows.append(r)
            dirs.append(d)
        try:
            probs = self._predict(rows)
        except Exception as exc:
            _log.warning("ML ORB predict failed for %s: %s", symbol, exc)
            return StrategyResult()

        best_i = int(np.argmax(probs))
        best_p, best_dir = float(probs[best_i]), dirs[best_i]
        if best_p < self._threshold:
            return StrategyResult(metadata={"direction": "NONE",
                                            "ml_proba": round(best_p, 3)})

        entry = float(df5["close"].iloc[-1])
        if best_dir == "LONG":
            sl = round(entry * (1 - self._sl_pct), 2)
            tp = round(entry * (1 + self._tp_pct), 2)
        else:
            sl = round(entry * (1 + self._sl_pct), 2)
            tp = round(entry * (1 - self._tp_pct), 2)

        tc = TradeCandidate(
            direction=best_dir,
            entry_price=round(entry, 2),
            stop_loss=sl,
            take_profit=tp,
            is_executable=True,
            ranking_score=int(round(best_p * 100)),
            rationale=f"ML Opening Breakout {best_dir} P={best_p:.2f}",
            symbol=symbol,
            timeframe=timeframe,
            max_hold_bars=self._max_hold,
        )
        return StrategyResult(trade_candidates=[tc],
                               metadata={"direction": best_dir,
                                         "ml_proba": round(best_p, 3)})
