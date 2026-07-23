"""
NIFTY Index Futures Engine — VWAP-reversion + momentum scoring (15m intraday).

Combines mean-reversion (extreme VWAP deviations revert) with momentum (range
breakouts, Bollinger expansion) — the two most reliable index-futures patterns.

Scoring factors (0-100 total):
  1. VWAP distance percentile  0-25  — fade extreme VWAP deviations
  2. Bollinger %B              0-20  — reversion at band extremes
  3. 3-bar momentum            0-15  — RSI rate of change
  4. Volume ratio              0-15  — conviction on breakouts
  5. Range breakout            0-15  — prior-bar high/low breakout
  6. 1d trend alignment        0-10  — reduce counter-trend, don't nullify

Each factor scores independently for LONG and SHORT. Separate thresholds:
LONG_MIN_SCORE=60, SHORT_MIN_SCORE=50 (lower to account for trend bias).

Usage:
    engine = NiftyFuturesEngine()
    result = engine.compute(df_15m, nifty_1d=None)
"""

from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

_log = logging.getLogger("nifty_futures_engine")

LONG_MIN_SCORE = int(os.environ.get("NIFTY_FUTURES_LONG_MIN_SCORE", "60"))
SHORT_MIN_SCORE = int(os.environ.get("NIFTY_FUTURES_SHORT_MIN_SCORE", "50"))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> np.ndarray:
    h, l, c = high.values, low.values, close.values
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    tr_series = pd.Series(tr).rolling(period).mean()
    arr = np.full(len(close), np.nan)
    arr[1:] = tr_series.values
    arr[:period] = np.nan
    return arr


def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan).fillna(1)
    return (tp * vol).cumsum() / vol.cumsum()


def _rsi(series: pd.Series, period: int = 14) -> np.ndarray:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).values


def _bollinger(df: pd.DataFrame, period: int = 20, stds: float = 2.0) -> tuple:
    sma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    upper = sma + stds * std
    lower = sma - stds * std
    bb_pct = ((df["close"] - lower) / (upper - lower).replace(0, np.nan)).values
    return bb_pct, upper, lower


class NiftyFuturesEngine:
    """Multi-factor scoring engine for NIFTY 15m intraday futures."""

    def __init__(self, atr_period: int = 14, bb_period: int = 20):
        self.atr_period = atr_period
        self.bb_period = bb_period

    def compute(self, df: pd.DataFrame, nifty_1d: pd.DataFrame | None = None,
                opening_range: tuple | None = None) -> dict:
        if df is None or len(df) < 30:
            return self._neutral("insufficient data")

        c = df["close"].values
        h = df["high"].values
        l = df["low"].values
        v = df["volume"].values
        last_idx = len(df) - 1

        atr_arr = _atr(df["high"], df["low"], df["close"], self.atr_period)
        vwap_s = _vwap(df)
        vwap_val = float(vwap_s.iloc[-1])
        atr_val = float(atr_arr[last_idx]) if not np.isnan(atr_arr[last_idx]) else 0
        bb_pct, _, _ = _bollinger(df, self.bb_period)
        rsi_arr = _rsi(df["close"])

        c_val = float(c[last_idx])
        v_val = float(v[last_idx])
        avg_vol = float(np.nanmean(v[-10:])) if len(v) >= 10 else float(v_val)
        vwap_dist = (c_val - vwap_val) / (atr_val if atr_val > 0 else 1)
        momentum = float(rsi_arr[last_idx] - rsi_arr[last_idx - 3]) if last_idx >= 3 else 0

        factors = {}
        long_score = 0
        short_score = 0

        # ── 1. VWAP distance percentile (0-25) ──
        # Score based on where current deviation ranks in the recent 40-bar window
        recent_dists = (c[-40:] - vwap_s.values[-40:]) / (atr_arr[-40:] if not np.isnan(atr_arr[-40:].min()) else 1)
        recent_dists = recent_dists[~np.isnan(recent_dists)]
        if len(recent_dists) >= 10:
            pctile = np.searchsorted(np.sort(recent_dists), vwap_dist) / len(recent_dists)
            if pctile <= 0.15:
                pts = min(25, int((0.15 - pctile) / 0.15 * 25))
                long_score += pts
                factors["vwap_long"] = pts
            else:
                factors["vwap_long"] = 0
            if pctile >= 0.85:
                pts = min(25, int((pctile - 0.85) / 0.15 * 25))
                short_score += pts
                factors["vwap_short"] = pts
            else:
                factors["vwap_short"] = 0
        else:
            factors["vwap_long"] = 0
            factors["vwap_short"] = 0

        # ── 2. Bollinger %B (0-20) ──
        bb_pct_val = float(bb_pct[last_idx]) if not np.isnan(bb_pct[last_idx]) else 0.5
        if bb_pct_val <= 0.2:
            pts = int((0.2 - bb_pct_val) / 0.2 * 20)
            long_score += pts
            factors["bb_long"] = pts
        else:
            factors["bb_long"] = 0
        if bb_pct_val >= 0.8:
            pts = int((bb_pct_val - 0.8) / 0.2 * 20)
            short_score += pts
            factors["bb_short"] = pts
        else:
            factors["bb_short"] = 0

        # ── 3. 3-bar momentum / RSI rate of change (0-15) ──
        rsi_val = float(rsi_arr[last_idx]) if not np.isnan(rsi_arr[last_idx]) else 50
        if rsi_val < 40 and momentum > 2:
            pts = min(15, int(momentum * 3))
            long_score += pts
            factors["mom_long"] = pts
        else:
            factors["mom_long"] = 0
        if rsi_val > 60 and momentum < -2:
            pts = min(15, int(abs(momentum) * 3))
            short_score += pts
            factors["mom_short"] = pts
        else:
            factors["mom_short"] = 0

        # ── 4. Volume ratio (0-15) ──
        vol_ratio = v_val / avg_vol if avg_vol > 0 else 1
        if vol_ratio >= 1.2:
            pts = min(15, int((vol_ratio - 1.0) * 12))
            long_score += pts
            short_score += pts
            factors["vol"] = pts
        else:
            factors["vol"] = 0

        # ── 5. Range breakout (0-15) ──
        # Breakout above/below the prior bar's high/low with ATR confirmation
        if last_idx >= 1:
            prev_high = float(h[last_idx - 1]) if len(df) > last_idx else 0
            prev_low = float(l[last_idx - 1]) if len(df) > last_idx else 0
            if c_val > prev_high and vol_ratio >= 1.0:
                pts = min(15, int((c_val - prev_high) / atr_val * 8) if atr_val > 0 else 5)
                long_score += pts
                factors["range_breakout"] = pts
            elif c_val < prev_low and vol_ratio >= 1.0:
                pts = min(15, int((prev_low - c_val) / atr_val * 8) if atr_val > 0 else 5)
                short_score += pts
                factors["range_breakout"] = pts
            else:
                factors["range_breakout"] = 0
        else:
            factors["range_breakout"] = 0

        # ── 6. 1d trend alignment (0-10) ──
        # Penalize counter-trend trades by 30% (not nullify)
        if nifty_1d is not None and len(nifty_1d) >= 50:
            daily_c = nifty_1d["close"].values
            sma20_vals = pd.Series(daily_c).rolling(20).mean().values
            sma50_vals = pd.Series(daily_c).rolling(50).mean().values
            if not np.isnan(sma20_vals[-1]) and not np.isnan(sma50_vals[-1]):
                daily_trend = "UP" if sma20_vals[-1] > sma50_vals[-1] else "DOWN"
                factors["trend_align"] = 10
                if daily_trend == "UP":
                    short_score = int(short_score * 0.7)
                else:
                    long_score = int(long_score * 0.7)
        else:
            factors["trend_align"] = 0

        # ── Clamp ──
        long_score = min(100, max(0, long_score))
        short_score = min(100, max(0, short_score))

        # Determine direction using separate thresholds
        if long_score >= LONG_MIN_SCORE and long_score >= short_score:
            direction = "LONG"
            total_score = long_score
        elif short_score >= SHORT_MIN_SCORE and short_score >= long_score:
            direction = "SHORT"
            total_score = short_score
        else:
            direction = "NEUTRAL"
            total_score = 0

        return {
            "direction": direction,
            "total_score": total_score,
            "long_score": long_score,
            "short_score": short_score,
            "factors": factors,
            "vwap": round(vwap_val, 2),
            "atr": round(atr_val, 2),
            "bb_pct": round(bb_pct_val, 3),
            "rsi": round(rsi_val, 1),
        }

    def _neutral(self, reason: str = "") -> dict:
        return {
            "direction": "NEUTRAL", "total_score": 0,
            "long_score": 0, "short_score": 0,
            "factors": {}, "vwap": 0, "atr": 0, "bb_pct": 0.5, "rsi": 50,
        }
