"""
Day Type Engine

Classifies the type of market day every hour from market open
using NIFTY price action, breadth, and volatility.

Day types:
  TREND_UP      — Persistent upward movement, VWAP slope positive, sector breadth > 70%
  TREND_DOWN    — Persistent downward movement, VWAP slope negative, sector breadth < 30%
  RANGE         — Tight range (< 0.8x ATR), VWAP oscillation, low sector participation
  GAP_UP        — Opens above prev day high, holds above VWAP
  GAP_DOWN      — Opens below prev day low, stays below VWAP
  REVERSAL      — Opens one side, closes opposite with volume confirmation
  CHOPPY        — Wide range but no follow-through, multiple VWAP crosses

Updated hourly from market open.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

_log = logging.getLogger("day_type")


MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
HOURS_IN_SESSION = 6  # 9:15 AM to 3:30 PM


class DayTypeEngine:
    @staticmethod
    def get_market_hours_data() -> pd.DataFrame | None:
        try:
            tk = yf.Ticker("^NSEI")
            df = tk.history(period="2d", interval="60m")
            if df.empty:
                return None
            df = df.reset_index()
            df["timestamp"] = pd.to_datetime(df["Datetime"] if "Datetime" in df.columns else df["Date"])
            df = df.set_index("timestamp")
            df = df.tz_localize(None) if df.index.tz is not None else df
            return df
        except Exception as e:
            _log.warning(f"Failed to fetch market data: {e}")
            return None

    @staticmethod
    def get_prev_day_data() -> pd.DataFrame | None:
        try:
            tk = yf.Ticker("^NSEI")
            df = tk.history(period="5d", interval="1d")
            if df.empty or len(df) < 2:
                return None
            return df
        except Exception as e:
            _log.warning(f"Failed to fetch prev day data: {e}")
            return None

    @staticmethod
    def get_intraday_nifty() -> pd.DataFrame | None:
        try:
            tk = yf.Ticker("^NSEI")
            df = tk.history(period="1d", interval="15m")
            if df.empty:
                return None
            df = df.reset_index()
            df["timestamp"] = pd.to_datetime(df["Datetime"] if "Datetime" in df.columns else df["Date"])
            df = df.set_index("timestamp")
            df = df.tz_localize(None) if df.index.tz is not None else df
            return df
        except Exception as e:
            _log.warning(f"Failed to fetch intraday nifty: {e}")
            return None

    @staticmethod
    def get_sector_breadth() -> dict:
        try:
            sector_etfs = {
                "BANKNIFTY": "^NSEBANK",
                "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
                "IT": "^CNXIT",
                "PHARMA": "^CNXPHARMA",
                "AUTO": "^CNXAUTO",
                "MIDCAP": "^NSMIDCP",
                "SENSEX": "^BSESN",
            }
            results = {}
            tk = yf.Ticker("^NSEI")
            nifty_hist = tk.history(period="2d", interval="1d")
            if len(nifty_hist) < 2:
                return {}
            nifty_chg = ((nifty_hist["Close"].iloc[-1] - nifty_hist["Close"].iloc[-2]) / nifty_hist["Close"].iloc[-2]) * 100

            for name, sym in sector_etfs.items():
                try:
                    stk = yf.Ticker(sym)
                    h = stk.history(period="2d", interval="1d")
                    if len(h) >= 2:
                        chg = ((h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2]) * 100
                        results[name] = chg
                    else:
                        results[name] = None
                except Exception:
                    results[name] = None

            above = sum(1 for v in results.values() if v is not None and v >= nifty_chg)
            total = sum(1 for v in results.values() if v is not None)
            breadth_pct = (above / total) * 100 if total > 0 else 50

            return {
                "sector_changes": results,
                "breadth_pct": round(breadth_pct, 1),
                "nifty_change": round(nifty_chg, 2),
            }
        except Exception as e:
            _log.warning(f"Sector breadth error: {e}")
            return {"breadth_pct": 50, "sector_changes": {}, "nifty_change": 0}

    @classmethod
    def classify_historical(
        cls,
        timestamp,
        nifty_intraday: pd.DataFrame | None,
        nifty_daily: pd.DataFrame | None,
        banknifty_daily: pd.DataFrame | None = None,
    ) -> dict:
        """
        Classify day type using pre-fetched historical data instead of live yfinance.

        Parameters
        ----------
        timestamp : datetime-like
            The 'current' time for the backtest bar (used to determine hours_since_open).
        nifty_intraday : pd.DataFrame | None
            NIFTY intraday bars for the current trading day (must have Open/High/Low/Close/Volume).
        nifty_daily : pd.DataFrame | None
            NIFTY daily bars for recent days (used for gap analysis). Should include
            the previous trading day's data.
        """
        if nifty_intraday is None or nifty_intraday.empty:
            return cls._default_result("No intraday NIFTY data")

        # Normalise timestamp
        ts = pd.to_datetime(timestamp)
        if ts.tz is not None:
            ts = ts.tz_localize(None)
        today_date = ts.date()
        now_time = ts.time()

        # Filter intraday to current date
        intra_today = nifty_intraday.copy()
        if "timestamp" in intra_today.columns:
            intra_today = intra_today.set_index("timestamp")
        if intra_today.index.tz is not None:
            intra_today.index = intra_today.index.tz_localize(None)

        # Only keep bars up to and including the current timestamp
        intra_today = intra_today[intra_today.index <= ts].copy()
        if intra_today.empty:
            return cls._default_result("No bars up to current timestamp")

        # Rename columns to uppercase convention used internally
        intra_today = intra_today.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })

        hours_since_open = max(1, round((now_time.hour * 60 + now_time.minute - 555) / 60))
        hours_since_open = max(1, min(hours_since_open, HOURS_IN_SESSION))

        # Calculate metrics (same as classify())
        open_price = float(intra_today["Open"].iloc[0])
        current_price = float(intra_today["Close"].iloc[-1])
        high_price = float(intra_today["High"].max())
        low_price = float(intra_today["Low"].min())

        daily_change_pct = round(((current_price - open_price) / open_price) * 100, 2)

        # Build hourly DataFrame for ATR calculation
        df_hours = intra_today.resample("1h").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna()

        atr = cls._calculate_atr(df_hours)
        day_range = high_price - low_price
        range_vs_atr = round(day_range / atr, 2) if atr and atr > 0 else 0

        vwap = cls._calculate_vwap(intra_today)
        vwap_distance_pct = round(((current_price - vwap) / vwap) * 100, 2) if vwap else 0
        vwap_slope = cls._calculate_vwap_slope(intra_today, vwap)
        vwap_crosses = cls._count_vwap_crosses(intra_today, vwap)

        bullish_candles = int((intra_today["Close"] > intra_today["Open"]).sum())
        bearish_candles = int((intra_today["Close"] < intra_today["Open"]).sum())
        total_candles = len(intra_today)
        bull_ratio = bullish_candles / total_candles if total_candles > 0 else 0.5

        total_volume = int(intra_today["Volume"].sum()) if "Volume" in intra_today.columns else 0

        at_high = current_price >= high_price * 0.995
        at_low = current_price <= low_price * 1.005

        # Gap analysis from nifty_daily — rename to uppercase for _analyze_gap
        if nifty_daily is not None and not nifty_daily.empty:
            gap_daily = nifty_daily.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
        else:
            gap_daily = nifty_daily
        gap_info = cls._analyze_gap(intra_today, gap_daily)

        hourly_trend = cls._analyze_hourly_trend(df_hours)

        # Breadth — use Bank Nifty daily as a proxy for sector breadth
        # (BN above 20d EMA = bullish breadth, below = bearish)
        breadth_pct = 50.0
        if banknifty_daily is not None and not banknifty_daily.empty:
            try:
                bn = banknifty_daily.copy()
                if "timestamp" in bn.columns:
                    bn = bn.set_index("timestamp")
                bn_close = bn["close"].astype(float)
                if len(bn_close) >= 20:
                    bn_ema20 = bn_close.ewm(span=20, adjust=False).mean().iloc[-1]
                    bn_last = bn_close.iloc[-1]
                    bn_above = bn_last > bn_ema20
                    # Scale breadth: 40 (bearish) ↔ 60 (bullish)
                    breadth_pct = 65.0 if bn_above else 35.0
            except Exception:
                breadth_pct = 50.0

        day_type, strength, phase = cls._determine_day_type(
            daily_change_pct=daily_change_pct,
            range_vs_atr=range_vs_atr,
            vwap_distance_pct=vwap_distance_pct,
            vwap_slope=vwap_slope,
            vwap_crosses=vwap_crosses,
            bull_ratio=bull_ratio,
            at_high=at_high,
            at_low=at_low,
            gap_info=gap_info,
            breadth_pct=breadth_pct,
            hourly_trend=hourly_trend,
            hours_since_open=hours_since_open,
        )

        total_hours = HOURS_IN_SESSION
        if hours_since_open <= 2:
            phase = "EARLY"
        elif hours_since_open <= 4:
            phase = "MID"
        else:
            phase = "LATE"

        first_hour_open = float(intra_today["Open"].iloc[0])
        first_hour_close = None
        first_hour_high = None
        first_hour_low = None
        first_hour_candles = intra_today.head(4)
        if len(first_hour_candles) >= 2:
            first_hour_close = float(first_hour_candles["Close"].iloc[-1])
            first_hour_high = float(first_hour_candles["High"].max())
            first_hour_low = float(first_hour_candles["Low"].min())
        first_hour_direction = "UP" if first_hour_close and first_hour_close >= first_hour_open else "DOWN" if first_hour_close else "FLAT"

        return {
            "type": day_type,
            "strength": strength,
            "phase": phase,
            "hours_since_open": hours_since_open,
            "metrics": {
                "open": round(open_price, 2),
                "current": round(current_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "range": round(day_range, 2),
                "range_vs_atr": range_vs_atr,
                "atr": round(atr, 2) if atr else None,
                "change_pct": daily_change_pct,
                "volume": total_volume,
                "vwap": round(vwap, 2) if vwap else None,
                "vwap_distance_pct": vwap_distance_pct,
                "vwap_slope_direction": vwap_slope,
                "vwap_crosses": vwap_crosses,
                "bullish_candles": bullish_candles,
                "bearish_candles": bearish_candles,
                "bull_ratio": round(bull_ratio, 2),
                "sector_breadth_pct": breadth_pct,
            },
            "first_hour": {
                "open": round(first_hour_open, 2) if first_hour_open else None,
                "close": round(first_hour_close, 2) if first_hour_close else None,
                "high": round(first_hour_high, 2) if first_hour_high else None,
                "low": round(first_hour_low, 2) if first_hour_low else None,
                "direction": first_hour_direction,
            },
            "gap": gap_info,
            "hourly_trend": hourly_trend,
            "sector_breadth": {"breadth_pct": breadth_pct, "sector_changes": {}, "nifty_change": 0},
        }

    @classmethod
    def classify(cls) -> dict:
        df_intra = cls.get_intraday_nifty()
        df_hours = cls.get_market_hours_data()
        df_prev = cls.get_prev_day_data()
        breadth = cls.get_sector_breadth()

        if df_intra is None or df_intra.empty:
            return cls._default_result("No intraday data")

        today = datetime.now()
        today_date = today.date()

        intra_today = df_intra[df_intra.index.date == today_date].copy()
        if intra_today.empty:
            return cls._default_result("Market not yet open")

        # Strip timezone for consistent comparison
        if intra_today.index.tz is not None:
            intra_today.index = intra_today.index.tz_localize(None)

        now_time = today.time()
        hours_since_open = max(1, round((now_time.hour - 9 + (now_time.minute - 15) / 60)))
        hours_since_open = min(hours_since_open, HOURS_IN_SESSION)

        # Calculate key metrics
        open_price = float(intra_today["Open"].iloc[0])
        current_price = float(intra_today["Close"].iloc[-1])
        high_price = float(intra_today["High"].max())
        low_price = float(intra_today["Low"].min())
        total_volume = int(intra_today["Volume"].sum()) if "Volume" in intra_today.columns else 0

        daily_change_pct = round(((current_price - open_price) / open_price) * 100, 2)

        # ATR calculation on hourly data
        atr = cls._calculate_atr(df_hours)

        # Day range as % of ATR
        day_range = high_price - low_price
        range_vs_atr = round(day_range / atr, 2) if atr and atr > 0 else 0

        # VWAP calculation
        vwap = cls._calculate_vwap(intra_today)
        vwap_distance_pct = round(((current_price - vwap) / vwap) * 100, 2) if vwap else 0

        # VWAP slope
        vwap_slope = cls._calculate_vwap_slope(intra_today, vwap)

        # Gap analysis
        gap_info = cls._analyze_gap(intra_today, df_prev)

        # VWAP crosses
        vwap_crosses = cls._count_vwap_crosses(intra_today, vwap)

        # Candle analysis
        bullish_candles = int((intra_today["Close"] > intra_today["Open"]).sum())
        bearish_candles = int((intra_today["Close"] < intra_today["Open"]).sum())
        total_candles = len(intra_today)
        bull_ratio = bullish_candles / total_candles if total_candles > 0 else 0.5

        # Check if hitting new session highs/lows
        at_high = current_price >= high_price * 0.995
        at_low = current_price <= low_price * 1.005

        # Hourly segment analysis
        hourly_trend = cls._analyze_hourly_trend(df_hours)

        # Determine day type
        day_type, strength, phase = cls._determine_day_type(
            daily_change_pct=daily_change_pct,
            range_vs_atr=range_vs_atr,
            vwap_distance_pct=vwap_distance_pct,
            vwap_slope=vwap_slope,
            vwap_crosses=vwap_crosses,
            bull_ratio=bull_ratio,
            at_high=at_high,
            at_low=at_low,
            gap_info=gap_info,
            breadth_pct=breadth.get("breadth_pct", 50),
            hourly_trend=hourly_trend,
            hours_since_open=hours_since_open,
        )

        # Determine phase
        total_hours = HOURS_IN_SESSION
        if hours_since_open <= 2:
            phase = "EARLY"
        elif hours_since_open <= 4:
            phase = "MID"
        else:
            phase = "LATE"

        # First hour info
        first_hour_open = float(intra_today["Open"].iloc[0])
        first_hour_close = None
        first_hour_high = None
        first_hour_low = None
        first_hour_candles = intra_today.head(4)
        if len(first_hour_candles) >= 2:
            first_hour_close = float(first_hour_candles["Close"].iloc[-1])
            first_hour_high = float(first_hour_candles["High"].max())
            first_hour_low = float(first_hour_candles["Low"].min())
        first_hour_direction = "UP" if first_hour_close and first_hour_close >= first_hour_open else "DOWN" if first_hour_close else "FLAT"

        return {
            "type": day_type,
            "strength": strength,
            "phase": phase,
            "hours_since_open": hours_since_open,
            "metrics": {
                "open": round(open_price, 2),
                "current": round(current_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "range": round(day_range, 2),
                "range_vs_atr": range_vs_atr,
                "atr": round(atr, 2) if atr else None,
                "change_pct": daily_change_pct,
                "volume": total_volume,
                "vwap": round(vwap, 2) if vwap else None,
                "vwap_distance_pct": vwap_distance_pct,
                "vwap_slope_direction": vwap_slope,
                "vwap_crosses": vwap_crosses,
                "bullish_candles": bullish_candles,
                "bearish_candles": bearish_candles,
                "bull_ratio": round(bull_ratio, 2),
                "sector_breadth_pct": breadth.get("breadth_pct", 50),
            },
            "first_hour": {
                "open": round(first_hour_open, 2) if first_hour_open else None,
                "close": round(first_hour_close, 2) if first_hour_close else None,
                "high": round(first_hour_high, 2) if first_hour_high else None,
                "low": round(first_hour_low, 2) if first_hour_low else None,
                "direction": first_hour_direction,
            },
            "gap": gap_info,
            "hourly_trend": hourly_trend,
            "sector_breadth": breadth,
        }

    @classmethod
    def _determine_day_type(
        cls,
        daily_change_pct: float,
        range_vs_atr: float,
        vwap_distance_pct: float,
        vwap_slope: str,
        vwap_crosses: int,
        bull_ratio: float,
        at_high: bool,
        at_low: bool,
        gap_info: dict,
        breadth_pct: float,
        hourly_trend: str,
        hours_since_open: int,
    ) -> tuple:
        is_gap_up = gap_info.get("type") == "GAP_UP" and gap_info.get("filled", False) is False
        is_gap_down = gap_info.get("type") == "GAP_DOWN" and gap_info.get("filled", False) is False
        gap_filled = gap_info.get("filled", False)

        # Trend day detection
        strong_directional = abs(daily_change_pct) >= 0.8 and range_vs_atr >= 0.8
        strong_bullish = daily_change_pct > 0 and (vwap_slope == "RISING" or (at_high and bull_ratio > 0.6))
        strong_bearish = daily_change_pct < 0 and (vwap_slope == "FALLING" or (at_low and bull_ratio < 0.4))

        # Gap day detection
        if is_gap_up and (strong_bullish or vwap_distance_pct > 0.2):
            return "GAP_UP", min(90, 50 + abs(daily_change_pct) * 8), "EARLY" if hours_since_open <= 2 else "MID"
        if is_gap_down and (strong_bearish or vwap_distance_pct < -0.2):
            return "GAP_DOWN", min(90, 50 + abs(daily_change_pct) * 8), "EARLY" if hours_since_open <= 2 else "MID"

        # Reversal detection
        if gap_filled and abs(daily_change_pct) > 0.5 and vwap_crosses >= 1:
            return "REVERSAL", min(85, 50 + abs(daily_change_pct) * 6), "MID"

        # Trend day detection
        if strong_bullish and (range_vs_atr >= 0.7 or breadth_pct > 60):
            strength = min(95, 50 + abs(daily_change_pct) * 7 + (breadth_pct - 50) * 0.5)
            return "TREND_UP", int(strength), "EARLY" if hours_since_open <= 2 else "MID"

        if strong_bearish and (range_vs_atr >= 0.7 or breadth_pct < 40):
            strength = min(95, 50 + abs(daily_change_pct) * 7 + (50 - breadth_pct) * 0.5)
            return "TREND_DOWN", int(strength), "EARLY" if hours_since_open <= 2 else "MID"

        # Choppy / Range detection
        if vwap_crosses >= 3 or (range_vs_atr >= 1.2 and abs(daily_change_pct) < 0.8):
            return "CHOPPY", min(80, 30 + vwap_crosses * 10), "MID" if hours_since_open >= 2 else "EARLY"

        if range_vs_atr < 0.8 and abs(daily_change_pct) < 0.5:
            return "RANGE", min(80, 40 + range_vs_atr * 20), "EARLY" if hours_since_open <= 2 else "MID"

        # Fallback
        if daily_change_pct > 0:
            return "TREND_UP", 55, "EARLY"
        return "TREND_DOWN", 55, "EARLY"

    @staticmethod
    def _calculate_atr(df: pd.DataFrame | None, period: int = 14) -> float | None:
        if df is None or len(df) < period + 1:
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
    def _calculate_vwap_slope(df: pd.DataFrame, vwap: float | None) -> str:
        if vwap is None or len(df) < 4:
            return "FLAT"
        try:
            current_price = float(df["Close"].iloc[-1])
            earlier_price = float(df["Close"].iloc[-4])
            if current_price > vwap * 1.001 and current_price > earlier_price:
                return "RISING"
            if current_price < vwap * 0.999 and current_price < earlier_price:
                return "FALLING"
            return "FLAT"
        except Exception:
            return "FLAT"

    @staticmethod
    def _count_vwap_crosses(df: pd.DataFrame, vwap: float | None) -> int:
        if vwap is None or len(df) < 3:
            return 0
        try:
            closes = df["Close"].values
            above = closes[0] > vwap
            crosses = 0
            for c in closes[1:]:
                now_above = c > vwap
                if now_above != above:
                    crosses += 1
                    above = now_above
            return crosses
        except Exception:
            return 0

    @staticmethod
    def _analyze_gap(intra_today: pd.DataFrame, df_prev: pd.DataFrame | None) -> dict:
        result = {"type": "NO_GAP", "filled": False, "size_pct": 0}
        if df_prev is None or len(df_prev) < 2:
            return result
        try:
            # Normalise column casing
            df_p = df_prev.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            prev_close = float(df_p["Close"].iloc[-2])
            prev_high = float(df_p["High"].iloc[-2])
            prev_low = float(df_p["Low"].iloc[-2])
            today_open = float(intra_today["Open"].iloc[0])
            today_low = float(intra_today["Low"].min())
            today_high = float(intra_today["High"].max())

            gap_pct = round(((today_open - prev_close) / prev_close) * 100, 2)

            if today_open > prev_high:
                gap_type = "GAP_UP"
                filled = today_low <= prev_high
            elif today_open < prev_low:
                gap_type = "GAP_DOWN"
                filled = today_high >= prev_low
            else:
                return {"type": "NO_GAP", "filled": False, "size_pct": gap_pct}

            return {"type": gap_type, "filled": filled, "size_pct": gap_pct,
                    "prev_close": round(prev_close, 2), "today_open": round(today_open, 2)}
        except Exception:
            return result

    @staticmethod
    def _analyze_hourly_trend(df_hours: pd.DataFrame | None) -> str:
        if df_hours is None or len(df_hours) < 3:
            return "NEUTRAL"
        try:
            closes = df_hours["Close"].tail(6).values
            if len(closes) < 3:
                return "NEUTRAL"
            up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
            down_count = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
            if up_count >= down_count * 2:
                return "BULLISH"
            if down_count >= up_count * 2:
                return "BEARISH"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    @staticmethod
    def _default_result(reason: str) -> dict:
        return {
            "type": "UNKNOWN",
            "strength": 0,
            "phase": "PRE_MARKET",
            "hours_since_open": 0,
            "metrics": {},
            "first_hour": {},
            "gap": {"type": "NO_GAP", "filled": False, "size_pct": 0},
            "hourly_trend": "NEUTRAL",
            "sector_breadth": {"breadth_pct": 50, "sector_changes": {}, "nifty_change": 0},
            "error": reason,
        }
