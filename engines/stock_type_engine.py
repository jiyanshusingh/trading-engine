"""
Stock Type Engine

Classifies each stock relative to the broader market (NIFTY)
to determine if it is leading, following, lagging, or breaking out.

Updated alongside the DayTypeEngine each hour.
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

_log = logging.getLogger("stock_type")


class StockTypeEngine:
    @classmethod
    def classify(
        cls,
        stock_df: pd.DataFrame | None,
        nifty_df: pd.DataFrame | None,
        stock_daily: pd.DataFrame | None = None,
    ) -> dict:
        if stock_df is None or stock_df.empty or nifty_df is None or nifty_df.empty:
            return cls._default_result("No data")

        result = {}

        # Intraday performance
        stock_ret = cls._calculate_return(stock_df)
        nifty_ret = cls._calculate_return(nifty_df)

        result["stock_return_pct"] = round(stock_ret, 2) if stock_ret is not None else 0
        result["nifty_return_pct"] = round(nifty_ret, 2) if nifty_ret is not None else 0

        # Relative return
        if stock_ret is not None and nifty_ret is not None:
            result["relative_return_pct"] = round(stock_ret - nifty_ret, 2)
        else:
            result["relative_return_pct"] = 0

        # VWAP analysis
        vwap = cls._calculate_vwap(stock_df)
        current_price = float(stock_df["Close"].iloc[-1])
        result["vwap"] = round(vwap, 2) if vwap else None
        result["vwap_distance_pct"] = round(((current_price - vwap) / vwap) * 100, 2) if vwap and vwap != 0 else 0
        result["above_vwap"] = current_price > vwap if vwap else None

        # Volume analysis
        avg_vol = cls._calculate_avg_volume(stock_df)
        today_vol = int(stock_df["Volume"].sum()) if "Volume" in stock_df.columns else 0
        result["volume"] = today_vol
        result["avg_volume"] = int(avg_vol) if avg_vol else 0
        result["vol_ratio"] = round(today_vol / avg_vol, 2) if avg_vol and avg_vol > 0 else 1.0

        # Price action
        high = float(stock_df["High"].max())
        low = float(stock_df["Low"].min())
        open_price = float(stock_df["Open"].iloc[0])
        result["day_range"] = round(high - low, 2)
        result["position_in_range"] = round(((current_price - low) / (high - low)) * 100, 1) if high != low else 50

        # 20-day high/low check
        if stock_daily is not None and not stock_daily.empty:
            last_20_high = float(stock_daily["High"].tail(20).max())
            last_20_low = float(stock_daily["Low"].tail(20).min())
            result["near_20d_high"] = current_price >= last_20_high * 0.98
            result["near_20d_low"] = current_price <= last_20_low * 1.02
            result["20d_high"] = round(last_20_high, 2)
            result["20d_low"] = round(last_20_low, 2)
        else:
            result["near_20d_high"] = False
            result["near_20d_low"] = False

        # Volatility check
        atr = cls._calculate_atr(stock_df)
        result["atr"] = round(atr, 2) if atr else None
        result["atr_pct"] = round((atr / current_price) * 100, 2) if atr and current_price else 0

        # Candle analysis
        bullish = int((stock_df["Close"] > stock_df["Open"]).sum())
        bearish = int((stock_df["Close"] < stock_df["Open"]).sum())
        total = len(stock_df)
        result["bullish_candles"] = bullish
        result["bearish_candles"] = bearish
        result["bullish_ratio"] = round(bullish / total, 2) if total > 0 else 0.5

        # Determine stock type
        result["type"], result["strength"] = cls._determine_stock_type(
            relative_return=result["relative_return_pct"],
            above_vwap=result["above_vwap"],
            vwap_distance=result["vwap_distance_pct"],
            vol_ratio=result["vol_ratio"],
            near_20d_high=result["near_20d_high"],
            near_20d_low=result["near_20d_low"],
            bullish_ratio=result["bullish_ratio"],
            position_in_range=result["position_in_range"],
            atr_pct=result["atr_pct"],
        )

        return result

    @classmethod
    def _determine_stock_type(
        cls,
        relative_return: float,
        above_vwap: bool | None,
        vwap_distance: float,
        vol_ratio: float,
        near_20d_high: bool,
        near_20d_low: bool,
        bullish_ratio: float,
        position_in_range: float,
        atr_pct: float,
    ) -> tuple:
        # Breakout
        if near_20d_high and vol_ratio >= 1.3 and vwap_distance > 0 and relative_return > 0:
            return "BREAKOUT", min(95, 60 + vol_ratio * 10 + relative_return * 5)

        # Relative Strength Leader
        if relative_return > 0.5 and above_vwap and vol_ratio >= 1.2 and bullish_ratio > 0.55:
            strength = min(90, 55 + relative_return * 8 + vol_ratio * 5)
            return "RS_LEADER", int(strength)

        # Relative Strength Follower
        if relative_return > -0.3 and above_vwap:
            return "FOLLOWER", 55

        # Breakdown
        if near_20d_low and vol_ratio >= 1.3 and vwap_distance < 0:
            return "BREAKDOWN", min(90, 55 + abs(relative_return) * 5)

        # Weakness
        if relative_return < -0.5 and (above_vwap is False or vwap_distance < -0.2):
            strength = min(85, 50 + abs(relative_return) * 6)
            return "WEAKNESS", int(strength)

        # In-Line
        if abs(relative_return) <= 0.5:
            return "IN_LINE", 50

        # Defensive (stock up while market down)
        if relative_return > 0.5 and not above_vwap:
            return "DEFENSIVE", 60

        return "IN_LINE", 50

    @staticmethod
    def _calculate_return(df: pd.DataFrame) -> float | None:
        if df.empty:
            return None
        try:
            open_p = float(df["Open"].iloc[0])
            close_p = float(df["Close"].iloc[-1])
            return ((close_p - open_p) / open_p) * 100 if open_p != 0 else 0
        except Exception:
            return None

    @staticmethod
    def _calculate_vwap(df: pd.DataFrame) -> float | None:
        if df.empty or "Volume" not in df.columns:
            return None
        try:
            vol = df["Volume"].values.astype(float)
            if vol.sum() == 0:
                return None
            tp = (df["High"].values + df["Low"].values + df["Close"].values) / 3
            return float(np.average(tp, weights=vol))
        except Exception:
            return None

    @staticmethod
    def _calculate_avg_volume(df: pd.DataFrame) -> float | None:
        if df.empty or "Volume" not in df.columns:
            return None
        try:
            return float(df["Volume"].tail(20).mean())
        except Exception:
            return None

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float | None:
        if df.empty or len(df) < period + 1:
            return None
        try:
            high = df["High"].values
            low = df["Low"].values
            close = df["Close"].values
            tr = np.maximum(high[1:] - low[1:],
                            np.maximum(np.abs(high[1:] - close[:-1]),
                                       np.abs(low[1:] - close[:-1])))
            return float(np.mean(tr[-period:]))
        except Exception:
            return None

    @staticmethod
    def _default_result(reason: str) -> dict:
        return {
            "type": "UNKNOWN",
            "strength": 0,
            "stock_return_pct": 0,
            "nifty_return_pct": 0,
            "relative_return_pct": 0,
            "vwap": None,
            "vwap_distance_pct": 0,
            "above_vwap": None,
            "volume": 0,
            "avg_volume": 0,
            "vol_ratio": 1.0,
            "day_range": 0,
            "position_in_range": 50,
            "bullish_candles": 0,
            "bearish_candles": 0,
            "bullish_ratio": 0.5,
            "near_20d_high": False,
            "near_20d_low": False,
            "atr": None,
            "atr_pct": 0,
            "error": reason,
        }
