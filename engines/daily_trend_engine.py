"""
Daily Trend Breakout Engine

Scores a daily (1d) bar as a LONG trend-continuation entry. The core signal is a
Donchian channel breakout (close above the prior N-bar high) filtered by a
6-factor trend-quality score. Designed to be paired with a trailing ATR stop
(no fixed take-profit) so a small number of large winners drive the edge — the
behaviour validated in the concept test (channel=15, trail_atr=4.0,
initial_sl_atr=4.0 → +3.29% avg gross / PF 1.93 over 452 symbols × 5yr).

LONG-only (v1). SHORT is intentionally not implemented (user instruction).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _sma(values: np.ndarray, period: int) -> float:
    if len(values) < period:
        return float("nan")
    return float(np.mean(values[-period:]))


def _rsi(close: np.ndarray, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    if len(close) < 2:
        return 0.0
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
    )
    return float(np.mean(tr[-period:]))


def _adx_proxy(df: pd.DataFrame, period: int = 14) -> float:
    """Lightweight ADX-style trend-strength proxy in [0, 100].

    Uses the average directional movement over ``period`` bars normalised by the
    average true range — captures "is this a strong directional move" without the
    full Wilder smoothing.
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    if len(close) < period + 1:
        return 0.0
    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
    )
    atr = np.mean(tr[-period:])
    if atr <= 0:
        return 0.0
    plus_di = 100.0 * np.mean(plus_dm[-period:]) / atr
    minus_di = 100.0 * np.mean(minus_dm[-period:]) / atr
    denom = plus_di + minus_di
    if denom <= 0:
        return 0.0
    dx = 100.0 * abs(plus_di - minus_di) / denom
    return float(dx)


class DailyTrendEngine:
    """6-factor LONG trend-breakout scorer for daily bars."""

    def __init__(self, channel: int = 15, atr_period: int = 14):
        self.channel = channel
        self.atr_period = atr_period

    def compute(
        self,
        df: pd.DataFrame,
        nifty_df: pd.DataFrame | None = None,
        **kwargs,
    ) -> dict:
        empty = {
            "total_score": 0,
            "bullish_score": 0,
            "direction": "NONE",
            "atr": 0.0,
            "factors": {},
            "reasons": "insufficient data",
            "detailed_breakdown": {},
        }
        if df is None or len(df) < 60:
            return empty

        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float)
        volume = df["volume"].values.astype(float)

        entry = float(close[-1])
        atr = _atr(df, self.atr_period)
        if atr <= 0:
            atr = entry * 0.01

        # ── Core trigger: Donchian channel breakout ──
        # Prior N-bar high EXCLUDING the current (breakout) bar → no look-ahead.
        if len(high) < self.channel + 1:
            return empty
        prior_high = float(np.max(high[-(self.channel + 1):-1]))
        is_breakout = entry > prior_high
        if not is_breakout:
            return {**empty, "reasons": "no breakout", "atr": atr}

        factors: dict[str, float] = {}
        reasons: list[str] = []

        # F1 — Breakout strength (0-20): how far above the channel high, in ATR.
        bo_atr = (entry - prior_high) / atr if atr > 0 else 0.0
        f1 = float(np.clip(bo_atr / 1.0, 0.0, 1.0) * 20.0)
        factors["breakout_strength"] = f1
        reasons.append(f"breakout +{bo_atr:.2f}ATR")

        # F2 — Trend quality (0-25): SMA50 > SMA200 (golden) + price above both.
        sma50 = _sma(close, 50)
        sma200 = _sma(close, 200)
        f2 = 0.0
        if sma50 == sma50 and sma200 == sma200:  # not NaN
            if sma50 > sma200:
                f2 += 12.0
                reasons.append("SMA50>SMA200")
            if entry > sma50:
                f2 += 7.0
            if entry > sma200:
                f2 += 6.0
        elif sma50 == sma50 and entry > sma50:
            f2 += 10.0  # partial credit when 200 history missing
        factors["trend_quality"] = f2

        # F3 — Volume confirmation (0-15): breakout-bar volume vs 20-bar average.
        vol_avg = float(np.mean(volume[-21:-1])) if len(volume) >= 21 else float(np.mean(volume[:-1]) if len(volume) > 1 else volume[-1])
        vol_ratio = (volume[-1] / vol_avg) if vol_avg > 0 else 1.0
        f3 = float(np.clip((vol_ratio - 1.0) / 1.0, 0.0, 1.0) * 15.0)
        factors["volume_confirmation"] = f3
        if vol_ratio >= 1.3:
            reasons.append(f"vol x{vol_ratio:.1f}")

        # F4 — Trend strength (0-15): ADX proxy.
        adx = _adx_proxy(df, self.atr_period)
        f4 = float(np.clip(adx / 40.0, 0.0, 1.0) * 15.0)
        factors["trend_strength"] = f4
        if adx >= 20:
            reasons.append(f"ADX~{adx:.0f}")

        # F5 — RSI momentum (0-15): reward healthy momentum (55-75), penalise
        # overbought (>82) and weak (<50).
        rsi = _rsi(close, 14)
        if 55.0 <= rsi <= 75.0:
            f5 = 15.0
        elif 50.0 <= rsi < 55.0:
            f5 = 10.0
        elif 75.0 < rsi <= 82.0:
            f5 = 8.0
        elif rsi > 82.0:
            f5 = 3.0
        else:
            f5 = 2.0
        factors["rsi_momentum"] = f5

        # F6 — Relative strength vs NIFTY (0-10): stock 20-bar return minus
        # NIFTY 20-bar return.
        f6 = 5.0  # neutral default when NIFTY unavailable
        try:
            if nifty_df is not None and len(nifty_df) >= 21 and len(close) >= 21:
                nclose = nifty_df["close"].values.astype(float)
                stock_ret = (close[-1] / close[-21] - 1.0)
                nifty_ret = (nclose[-1] / nclose[-21] - 1.0)
                rs = stock_ret - nifty_ret
                f6 = float(np.clip(0.5 + rs / 0.10 * 0.5, 0.0, 1.0) * 10.0)
                if rs > 0:
                    reasons.append("RS>NIFTY")
        except Exception:
            pass
        factors["rs_vs_nifty"] = f6

        total = f1 + f2 + f3 + f4 + f5 + f6

        return {
            "total_score": round(total, 1),
            "bullish_score": round(total, 1),
            "direction": "LONG",
            "atr": atr,
            "prior_high": prior_high,
            "factors": factors,
            "reasons": ", ".join(reasons),
            "detailed_breakdown": factors,
        }
