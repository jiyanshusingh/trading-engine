"""
Phase B5 — ML Standalone Strategy (executable wrapper).

A self-contained ML strategy that GENERATES entries from raw market state (not a
filter on other strategies). At each bar it scores BOTH a LONG and a SHORT entry
with the trained model (data/ml_strategy_model.json) and takes whichever clears
the deploy threshold (default 0.80, walk-forward validated across regimes in
scripts/walkforward_ml_strategy.py). Exits use the same fixed SL 0.5% / TP 5.0%
the model was trained on.

Feature parity with training is guaranteed by reusing the exact same helpers the
dataset generator mirrors: WalkForwardBacktest._compute_entry_features (stock
technicals) and build_htf_context (30m/1d context for both the stock and NIFTY).
"""

from __future__ import annotations

import json
import logging
import os

import numpy as np
import pandas as pd

from strategies.executable import ExecutableStrategy, StrategyResult, TradeCandidate

_log = logging.getLogger("ml_strategy")

MODEL_PATH = os.environ.get("ML_STRATEGY_MODEL", "data/ml_strategy_model.json")
META_PATH = os.environ.get("ML_STRATEGY_META", "data/ml_strategy_model_meta.json")


class MLStrategy(ExecutableStrategy):

    @property
    def name(self) -> str:
        return "ML Standalone"

    def __init__(self, threshold: float | None = None, **kwargs):
        # Accept & ignore sl_mult/tp_mult/atr_period/min_score that the backtest
        # passes to all strategies — this strategy uses fixed % SL/TP baked into
        # the trained model's labels.
        self._model = None
        self._features: list[str] = []
        self._threshold = 0.80
        self._sl_pct = 0.005
        self._tp_pct = 0.05
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
            self._threshold = meta.get("threshold", 0.80)
            self._sl_pct = meta.get("sl_pct", 0.005)
            self._tp_pct = meta.get("tp_pct", 0.05)
            self._model = XGBClassifier()
            self._model.load_model(MODEL_PATH)
            _log.info("Loaded ML strategy model (%d features, thr=%.2f)",
                      len(self._features), self._threshold)
        except Exception as exc:
            _log.warning("ML strategy model unavailable (%s); strategy inert", exc)
            self._model = None

    # ── feature construction (single bar, matches training) ──────────
    @staticmethod
    def _nifty_context(nifty_df, nifty_daily, ts) -> dict:
        """NIFTY 30m/1d context, mapped to nifty_* keys (mirrors dataset gen)."""
        from scripts.backtest import build_htf_context, _resample_1m_to
        ctx: dict = {}
        n30 = None
        if nifty_df is not None and not nifty_df.empty:
            try:
                n30 = _resample_1m_to(nifty_df, 30)
            except Exception:
                n30 = None
        raw = build_htf_context(n30, nifty_daily, ts)
        for k, v in raw.items():
            ctx[f"nifty_{k}"] = v
        return ctx

    def _feature_row(self, df, htf_ctx, nifty_ctx, direction) -> dict:
        from scripts.backtest import WalkForwardBacktest
        feats = dict(WalkForwardBacktest._compute_entry_features(df))
        feats.update(htf_ctx or {})       # 30m_*, 1d_* for the stock
        feats.update(nifty_ctx or {})     # nifty_30m_*, nifty_1d_*
        ts = pd.to_datetime(df["timestamp"].iloc[-1])
        feats["hour"] = ts.hour + ts.minute / 60.0
        feats["weekday"] = ts.weekday()
        feats["direction"] = direction
        return feats

    def _predict(self, feat_rows: list[dict]) -> np.ndarray:
        X = pd.DataFrame(feat_rows)
        cat = [c for c in ["30m_trend", "1d_trend", "nifty_30m_trend",
                           "nifty_1d_trend", "direction"] if c in X.columns]
        X = pd.get_dummies(X, columns=cat, dummy_na=True)
        X = X.reindex(columns=self._features, fill_value=0)
        X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        return self._model.predict_proba(X)[:, 1]

    def run(self, df, symbol, timeframe, day_type="", stock_type="", **kwargs) -> StrategyResult:
        if self._model is None or df is None or len(df) < 60:
            return StrategyResult()

        htf_ctx = kwargs.get("htf_ctx", {}) or {}
        nifty_df = kwargs.get("nifty_df", None)
        nifty_daily = kwargs.get("nifty_daily", None)
        stock_daily = kwargs.get("stock_daily", None)
        ts = pd.to_datetime(df["timestamp"].iloc[-1])
        # If the backtest ran with multi_tf_filter OFF, htf_ctx is empty — build
        # the stock 30m/1d context ourselves so features match training and we do
        # not depend on (or trigger) the engine's htf_check gate.
        if not htf_ctx:
            from scripts.backtest import build_htf_context, _resample_1m_to
            try:
                s30 = _resample_1m_to(df, 30)
            except Exception:
                s30 = None
            htf_ctx = build_htf_context(s30, stock_daily, ts)
        nifty_ctx = self._nifty_context(nifty_df, nifty_daily, ts)

        rows, dirs = [], []
        for d in ("LONG", "SHORT"):
            rows.append(self._feature_row(df, htf_ctx, nifty_ctx, d))
            dirs.append(d)
        try:
            probs = self._predict(rows)
        except Exception as exc:
            _log.warning("ML predict failed for %s: %s", symbol, exc)
            return StrategyResult()

        best_i = int(np.argmax(probs))
        best_p, best_dir = float(probs[best_i]), dirs[best_i]
        if best_p < self._threshold:
            return StrategyResult(metadata={"direction": "NONE",
                                            "ml_proba": round(best_p, 3)})

        # Phase E regime gate: skip LONG entries when NIFTY is in a daily
        # downtrend (the walk-forward showed this protects bear-market bleed
        # while letting the threshold drop to 0.75 for +3× more net PnL).
        nifty_trend = (nifty_ctx or {}).get("nifty_1d_trend", "FLAT")
        if best_dir == "LONG" and nifty_trend == "DOWN":
            return StrategyResult(metadata={"direction": "NONE",
                                            "ml_proba": round(best_p, 3),
                                            "regime_skip": True})

        entry = float(df["close"].iloc[-1])
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
            rationale=f"ML Standalone {best_dir} P={best_p:.2f}",
            symbol=symbol,
            timeframe=timeframe,
        )
        return StrategyResult(trade_candidates=[tc],
                              metadata={"direction": best_dir,
                                        "ml_proba": round(best_p, 3)})
