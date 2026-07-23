
from __future__ import annotations

import numpy as np
import pandas as pd


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    return float(np.mean(tr[-period:]))


def _vwap(df: pd.DataFrame) -> pd.Series:
    return (df["volume"] * df["close"]).cumsum() / df["volume"].cumsum()


class RelativeStrengthEngine:

    def __init__(self, atr_period: int = 14):
        self.atr_period = atr_period

    def compute(
        self,
        df: pd.DataFrame,
        nifty_df: pd.DataFrame | None = None,
        stock_daily: pd.DataFrame | None = None,
        day_type: str = "",
        stock_type: str = "",
        **kwargs,
    ) -> dict:
        if df is None or len(df) < 20:
            return {
                "total_score": 0,
                "bullish_score": 0,
                "bearish_score": 0,
                "direction": "NONE",
                "factors": {},
                "reasons": "insufficient data",
                "detailed_breakdown": {},
            }

        factors = {}

        f1 = self._rs_vs_nifty(df, nifty_df)
        factors["rs_vs_nifty"] = f1

        f2 = self._volume_surge(df)
        factors["volume_surge"] = f2

        f3 = self._vwap_separation(df)
        factors["vwap_separation"] = f3

        f4 = self._breakout_from_range(df)
        factors["breakout_range"] = f4

        f5 = self._price_acceleration(df)
        factors["price_acceleration"] = f5

        f6 = self._nifty_context(nifty_df)
        factors["nifty_context"] = f6

        f7 = self._intraday_structure(df)
        factors["intraday_structure"] = f7

        bullish_total = sum(f["bullish"] for f in factors.values())
        bearish_total = sum(f["bearish"] for f in factors.values())
        bullish_total = min(bullish_total, 100)
        bearish_total = min(bearish_total, 100)

        threshold = 55
        direction = "NONE"
        total_score = 0
        if bullish_total >= threshold:
            direction = "LONG"
            total_score = bullish_total
        elif bearish_total >= threshold:
            direction = "SHORT"
            total_score = bearish_total

        reasons_parts = []
        for name, f in factors.items():
            detail = f.get("detail", {})
            extra = ""
            if isinstance(detail, dict) and detail:
                extra = str(detail)
            reasons_parts.append(f"{name}(bull={f['bullish']},bear={f['bearish']})")

        return {
            "total_score": total_score,
            "bullish_score": bullish_total,
            "bearish_score": bearish_total,
            "direction": direction,
            "factors": factors,
            "reasons": "; ".join(reasons_parts),
            "detailed_breakdown": factors,
        }

    def _rs_vs_nifty(
        self, df: pd.DataFrame, nifty_df: pd.DataFrame | None
    ) -> dict:
        if nifty_df is None or len(nifty_df) < 5:
            return {"bullish": 0, "bearish": 0, "max": 25, "detail": {"error": "no nifty data"}}

        stock_close = df["close"].values
        nifty_close = nifty_df["close"].values

        stock_ret_1 = (stock_close[-1] - stock_close[-2]) / stock_close[-2] * 100
        nifty_ret_1 = (nifty_close[-1] - nifty_close[-2]) / nifty_close[-2] * 100
        rs_1 = stock_ret_1 - nifty_ret_1

        stock_ret_3 = (stock_close[-1] - stock_close[-4]) / stock_close[-4] * 100 if len(stock_close) >= 4 else 0
        nifty_ret_3 = (nifty_close[-1] - nifty_close[-4]) / nifty_close[-4] * 100 if len(nifty_close) >= 4 else 0
        rs_3 = stock_ret_3 - nifty_ret_3

        score = 0
        if rs_1 > 0.5:
            score += 7
        elif rs_1 > 0.3:
            score += 4
        elif rs_1 > 0.1:
            score += 2

        if rs_3 > 1.0:
            score += 10
        elif rs_3 > 0.5:
            score += 7
        elif rs_3 > 0.3:
            score += 4
        elif rs_3 > 0.1:
            score += 2

        bear = 0
        if rs_1 < -0.5:
            bear += 7
        elif rs_1 < -0.3:
            bear += 4
        if rs_3 < -1.0:
            bear += 10
        elif rs_3 < -0.5:
            bear += 7

        score = min(score, 25)
        bear = min(bear, 25)

        return {
            "bullish": score,
            "bearish": bear,
            "max": 25,
            "detail": {"rs_1": round(rs_1, 2), "rs_3": round(rs_3, 2)},
        }

    def _volume_surge(self, df: pd.DataFrame) -> dict:
        volumes = df["volume"].values
        closes = df["close"].values
        if len(volumes) < 20:
            return {"bullish": 0, "bearish": 0, "max": 20, "detail": {}}

        avg_vol = np.mean(volumes[-20:])
        if avg_vol == 0:
            return {"bullish": 0, "bearish": 0, "max": 20, "detail": {}}

        vol_ratio = volumes[-1] / avg_vol
        last_bar_down = closes[-1] < closes[-2] if len(closes) >= 2 else False

        score = 0
        if vol_ratio > 3.0:
            score = 20
        elif vol_ratio > 2.0:
            score = 15
        elif vol_ratio > 1.5:
            score = 10
        elif vol_ratio > 1.2:
            score = 5
        elif vol_ratio > 1.0:
            score = 2

        bear = 0
        if vol_ratio > 3.0 and last_bar_down:
            bear = 20
        elif vol_ratio > 2.0 and last_bar_down:
            bear = 15
        elif vol_ratio > 1.5 and last_bar_down:
            bear = 10
        elif vol_ratio > 1.2 and last_bar_down:
            bear = 5
        elif vol_ratio > 1.0 and last_bar_down:
            bear = 2

        return {
            "bullish": score,
            "bearish": bear,
            "max": 20,
            "detail": {"vol_ratio": round(vol_ratio, 2), "down_bar": last_bar_down},
        }

    def _vwap_separation(self, df: pd.DataFrame) -> dict:
        if len(df) < 3:
            return {"bullish": 0, "bearish": 0, "max": 15, "detail": {}}

        vwap = _vwap(df)
        current_close = df["close"].iloc[-1]
        vwap_current = vwap.iloc[-1]
        vwap_prev = vwap.iloc[-3] if len(vwap) >= 3 else vwap.iloc[-1]

        if vwap_current == 0:
            return {"bullish": 0, "bearish": 0, "max": 15, "detail": {}}

        vwap_dist = (current_close - vwap_current) / vwap_current * 100
        vwap_slope = "RISING" if vwap_current > vwap_prev else "FALLING"

        score = 0
        if vwap_dist > 0.5 and vwap_slope == "RISING":
            score = 15
        elif vwap_dist > 0.5:
            score = 12
        elif vwap_dist > 0.3:
            score = 8
        elif vwap_dist > 0.1:
            score = 4
        elif current_close > vwap_current:
            score = 2

        bear = 0
        if vwap_dist < -0.5 and vwap_slope == "FALLING":
            bear = 15
        elif vwap_dist < -0.5:
            bear = 10
        elif vwap_dist < -0.3:
            bear = 6
        elif current_close < vwap_current:
            bear = 2

        return {
            "bullish": score,
            "bearish": bear,
            "max": 15,
            "detail": {"vwap_dist_pct": round(vwap_dist, 2), "vwap_slope": vwap_slope},
        }

    def _breakout_from_range(self, df: pd.DataFrame) -> dict:
        if len(df) < 5:
            return {"bullish": 0, "bearish": 0, "max": 15, "detail": {}}

        recent = df.tail(5)
        low_window = recent["low"].min()
        high_window = recent["high"].max()
        current_close = df["close"].iloc[-1]
        range_size = high_window - low_window

        if range_size == 0:
            return {"bullish": 0, "bearish": 0, "max": 15, "detail": {}}

        position_in_range = (current_close - low_window) / range_size * 100
        near_high = current_close >= high_window * 0.98

        score = 0
        if position_in_range > 90 and near_high:
            score = 15
        elif position_in_range > 85:
            score = 10
        elif position_in_range > 75:
            score = 5
        elif current_close > high_window:
            score = 12

        bear = 0
        pos_bear = 100 - position_in_range
        near_low = current_close <= low_window * 1.02
        if pos_bear > 90 and near_low:
            bear = 15
        elif pos_bear > 85:
            bear = 10
        elif pos_bear > 75:
            bear = 5
        elif current_close < low_window:
            bear = 12

        return {
            "bullish": score,
            "bearish": bear,
            "max": 15,
            "detail": {"pos_in_range": round(position_in_range, 1), "near_high": near_high},
        }

    def _price_acceleration(self, df: pd.DataFrame) -> dict:
        closes = df["close"].values
        if len(closes) < 7:
            return {"bullish": 0, "bearish": 0, "max": 10, "detail": {}}

        roc_3 = (closes[-1] - closes[-4]) / closes[-4] * 100
        roc_5 = (closes[-1] - closes[-6]) / closes[-6] * 100

        score = 0
        if roc_3 > roc_5 and roc_5 > 0.5 and roc_3 > 1.0:
            score = 10
        elif roc_3 > roc_5 and roc_5 > 0.5:
            score = 5
        elif roc_3 > 0.5:
            score = 2

        bear = 0
        if roc_3 < roc_5 and roc_5 < -0.5 and roc_3 < -1.0:
            bear = 10
        elif roc_3 < roc_5 and roc_5 < -0.5:
            bear = 5
        elif roc_3 < -0.5:
            bear = 2

        return {
            "bullish": score,
            "bearish": bear,
            "max": 10,
            "detail": {"roc_3": round(roc_3, 2), "roc_5": round(roc_5, 2)},
        }

    def _nifty_context(self, nifty_df: pd.DataFrame | None) -> dict:
        if nifty_df is None or len(nifty_df) < 2:
            return {"bullish": 0, "bearish": 0, "max": 10, "detail": {}}

        nifty_close = nifty_df["close"].values
        nifty_high = nifty_df["high"].values
        nifty_low = nifty_df["low"].values

        nifty_change = (nifty_close[-1] - nifty_close[0]) / nifty_close[0] * 100
        nifty_range = (nifty_high.max() - nifty_low.min()) / nifty_low.min() * 100

        score = 0
        if abs(nifty_change) < 0.3 and nifty_range >= 0.5:
            score = 10
        elif abs(nifty_change) < 0.5:
            score = 5
        elif nifty_change < -0.5:
            score = 3

        bear = 0
        if nifty_change < -0.5 and nifty_range >= 1.0:
            bear = 10
        elif nifty_change < -0.5:
            bear = 5
        elif nifty_change < -0.3:
            bear = 3

        return {
            "bullish": score,
            "bearish": bear,
            "max": 10,
            "detail": {"nifty_change": round(nifty_change, 2), "nifty_range": round(nifty_range, 2)},
        }

    def _intraday_structure(self, df: pd.DataFrame) -> dict:
        if len(df) < 5:
            return {"bullish": 0, "bearish": 0, "max": 5, "detail": {}}

        highs = df["high"].values
        lows = df["low"].values
        closes = df["open"].values
        opens = df["close"].values

        hh_count = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
        hl_count = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1])
        bullish_candles = sum(1 for i in range(len(closes)) if closes[i] > opens[i])
        total = len(closes)
        bull_ratio = bullish_candles / total if total > 0 else 0

        score = 0
        if hh_count >= 3 and bull_ratio > 0.6:
            score = 5
        elif bull_ratio > 0.6:
            score = 3
        elif hh_count >= 2:
            score = 2

        bear = 0
        ll_count = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])
        if ll_count >= 3 and bull_ratio < 0.4:
            bear = 5
        elif bull_ratio < 0.4:
            bear = 3
        elif ll_count >= 2:
            bear = 2

        return {
            "bullish": score,
            "bearish": bear,
            "max": 5,
            "detail": {"hh_count": hh_count, "bull_ratio": round(bull_ratio, 2)},
        }
