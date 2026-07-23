"""
Institutional Probability Engine — multi-factor dual scoring.

Each factor returns *bullish* and *bearish* points (0..max). The engine sums
all factors, then clamps the aggregate to a 0-100 score per side (the
"probability" scale), and emits LONG/SHORT only when the score clears
LONG_MIN_SCORE / SHORT_MIN_SCORE (see module constants below).

Factors (raw per-side max; combined raw capacity = 123 before clamping):
  1. Market Regime     (12) — NIFTY/BANKNIFTY EMA alignment + swing + breadth
  2. Sector Strength    (12) — Relative performance + volume ratio
  3. Price Action       (16) — Swing structure + breakout/breakdown + support
  4. Volume             (12) — RVOL on up/down bars
  5. Breakout Quality   (10) — A/B checklist per direction
  6. Risk/Reward         (8) — Market-based RR
  7. Indicators          (5) — EMA + RSI + MACD + VWAP
  8. Catalyst            (5) — Accumulation / distribution
  9. Session Timing     (10) — Time-of-day (calibrated from analysis; 0 until)
 10. Historical Perf.   (10) — Trailing returns + relative strength vs NIFTY
 11. Short Context      (20) — Dedicated bearish evidence (HTF-down, LL/LH,
                               breakdown, relative weakness, distribution)
"""

from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

_log = logging.getLogger("inst_prob_engine")

# ── Decision thresholds (single source of truth) ─────────────────
# These MUST match the backtester's acceptance gate (MIN_PROB /
# SHORT_MIN_PROB in scripts/backtest.py), which imports these values.
# The engine only emits a direction once the score clears the threshold,
# so running the engine directly (e.g. for live/forward signals) applies
# the same bar as the walk-forward backtest.
#
# Overridable via env vars for threshold sweeps without code edits:
#   INST_LONG_MIN_SCORE, INST_SHORT_MIN_SCORE
LONG_MIN_SCORE = int(os.environ.get("INST_LONG_MIN_SCORE", "70"))
SHORT_MIN_SCORE = int(os.environ.get("INST_SHORT_MIN_SCORE", "40"))

# ── Helpers ──────────────────────────────────────────────────────


def _ema(series: pd.Series, period: int) -> float:
    return float(series.ewm(span=period, adjust=False).mean().iloc[-1])


def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    h = high.values
    l = low.values
    c = close.values
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    return float(pd.Series(tr).rolling(period).mean().iloc[-1])


def _vwap(df: pd.DataFrame) -> float:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan).fillna(1)
    return float((tp * vol).sum() / vol.sum())


def _detect_swings(df: pd.DataFrame, lookback: int = 5) -> dict:
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    swing_highs = []
    swing_lows = []
    for i in range(lookback, n - lookback):
        if highs[i] == max(highs[i - lookback : i + lookback + 1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i - lookback : i + lookback + 1]):
            swing_lows.append((i, lows[i]))

    last_sh_price = swing_highs[-1][1] if swing_highs else 0.0
    last_sl_price = swing_lows[-1][1] if swing_lows else 0.0
    prev_sh_price = swing_highs[-2][1] if len(swing_highs) >= 2 else 0.0
    prev_sl_price = swing_lows[-2][1] if len(swing_lows) >= 2 else 0.0

    enough_swings = prev_sh_price > 0 and prev_sl_price > 0
    if enough_swings:
        hh = last_sh_price > prev_sh_price
        hl = last_sl_price > prev_sl_price
        ll = last_sl_price < prev_sl_price
        lh = last_sh_price < prev_sh_price
    else:
        hh = hl = ll = lh = False

    return {
        "has_hh": hh,
        "has_hl": hl,
        "has_ll": ll,
        "has_lh": lh,
        "last_swing_high": last_sh_price,
        "last_swing_low": last_sl_price,
        "prev_swing_high": prev_sh_price,
        "prev_swing_low": prev_sl_price,
    }


def _nearest_resistance(highs: np.ndarray, price: float, lookback: int = 30) -> tuple[float | None, float]:
    """Highest swing high that price has already broken above (behind price)."""
    recent = highs[-lookback:-1] if len(highs) > lookback else highs[:-1]
    broken = recent[recent < price]
    if len(broken) == 0:
        return None, 0.0
    nearest = float(np.max(broken))
    pct = (price - nearest) / nearest * 100 if nearest > 0 else 0
    return nearest, pct


def _nearest_forward_resistance(highs: np.ndarray, price: float, lookback: int = 30) -> tuple[float | None, float]:
    """Lowest swing high above price = nearest overhead resistance (ahead)."""
    recent = highs[-lookback:-1] if len(highs) > lookback else highs[:-1]
    above = recent[recent > price]
    if len(above) == 0:
        return None, 0.0
    nearest = float(np.min(above))
    pct = (nearest - price) / price * 100 if price > 0 else 0
    return nearest, pct


def _nearest_support(lows: np.ndarray, price: float, lookback: int = 30) -> tuple[float | None, float]:
    """Highest swing low below price = nearest support below."""
    recent = lows[-lookback:-1] if len(lows) > lookback else lows[:-1]
    below = recent[recent < price]
    if len(below) == 0:
        return None, 0.0
    nearest = float(np.max(below))
    pct = (price - nearest) / nearest * 100 if nearest > 0 else 0
    return nearest, pct


def _nearest_broken_support(lows: np.ndarray, price: float, lookback: int = 30) -> tuple[float | None, float]:
    """Lowest swing low above price = nearest support broken below. Returns +ve % for distance below."""
    recent = lows[-lookback:-1] if len(lows) > lookback else lows[:-1]
    above = recent[recent > price]
    if len(above) == 0:
        return None, 0.0
    nearest = float(np.min(above))
    pct = (nearest - price) / price * 100 if price > 0 else 0
    return nearest, pct


# ── Engine ───────────────────────────────────────────────────────


class InstitutionalProbabilityEngine:
    def __init__(self, sl_mult: float = 3.0, tp_mult: float = 4.0, atr_period: int = 14,
                 short_sl_mult: float = 1.0, short_tp_mult: float = 1.0):
        self.sl_mult = sl_mult
        self.tp_mult = tp_mult
        self.atr_period = atr_period
        # Short-specific SL/TP multipliers (scale the swing/ATR risk-reward
        # used for SHORT entries). Default 1.0 preserves the prior behaviour.
        # Raising short_sl_mult widens the SHORT stop, which lowers cost-in-R
        # (the ₹50k position is capped, so a wider stop = larger deployed risk
        # = smaller cost per R) — the lever that makes the edge survive costs.
        self.short_sl_mult = short_sl_mult
        self.short_tp_mult = short_tp_mult

    def compute(
        self,
        df: pd.DataFrame,
        nifty_df: pd.DataFrame | None = None,
        stock_daily: pd.DataFrame | None = None,
        day_type: str = "",
        stock_type: str = "",
        sector_name: str | None = None,
        htf_ctx: dict | None = None,
        entry_time: str | None = None,
        nifty_daily: pd.DataFrame | None = None,
        banknifty_df: pd.DataFrame | None = None,
        vix_daily: pd.DataFrame | None = None,
    ) -> dict:
        if df is None or len(df) < 60:
            return self._empty_result("Insufficient data")

        factors = {}
        reasons_bull = []
        reasons_bear = []

        factors["market_regime"] = self._score_market_regime(nifty_df, day_type, htf_ctx, banknifty_df, vix_daily)
        reasons_bull.append(f"RegimeBull={factors['market_regime']['bullish']}")
        reasons_bear.append(f"RegimeBear={factors['market_regime']['bearish']}")

        factors["sector_strength"] = self._score_sector_strength(df, stock_type, sector_name)
        reasons_bull.append(f"SectorBull={factors['sector_strength']['bullish']}")
        reasons_bear.append(f"SectorBear={factors['sector_strength']['bearish']}")

        factors["price_action"] = self._score_price_action(df, stock_daily)
        reasons_bull.append(f"PriceBull={factors['price_action']['bullish']}")
        reasons_bear.append(f"PriceBear={factors['price_action']['bearish']}")

        factors["volume"] = self._score_volume(df)
        reasons_bull.append(f"VolBull={factors['volume']['bullish']}")
        reasons_bear.append(f"VolBear={factors['volume']['bearish']}")

        factors["breakout_quality"] = self._score_breakout_quality(
            df, day_type, factors["market_regime"]["bullish"], htf_ctx
        )
        reasons_bull.append(f"BOBull={factors['breakout_quality']['bullish']}")
        reasons_bear.append(f"BOBear={factors['breakout_quality']['bearish']}")

        factors["risk_reward"] = self._score_risk_reward(df)
        reasons_bull.append(f"RRBull={factors['risk_reward']['bullish']}")
        reasons_bear.append(f"RRBear={factors['risk_reward']['bearish']}")

        factors["indicators"] = self._score_indicators(df)
        reasons_bull.append(f"IndBull={factors['indicators']['bullish']}")
        reasons_bear.append(f"IndBear={factors['indicators']['bearish']}")

        factors["catalyst"] = self._score_catalyst(df)
        reasons_bull.append(f"CatBull={factors['catalyst']['bullish']}")
        reasons_bear.append(f"CatBear={factors['catalyst']['bearish']}")

        # ── New factors: session timing + historical performance ──
        factors["session_timing"] = self._score_session_timing(entry_time, htf_ctx)
        reasons_bull.append(f"SessionBull={factors['session_timing']['bullish']}")
        reasons_bear.append(f"SessionBear={factors['session_timing']['bearish']}")

        factors["historical_performance"] = self._score_historical_performance(
            df, stock_daily, nifty_daily
        )
        reasons_bull.append(f"HistBull={factors['historical_performance']['bullish']}")
        reasons_bear.append(f"HistBear={factors['historical_performance']['bearish']}")

        # ── Phase 3: dedicated SHORT context ──
        # SHORT must be "genuinely bearish", not merely "not bullish". This
        # factor contributes only to the bearish side and is the core of the
        # SHORT rework: bearish HTF trend, bearish swing structure (LL/LH),
        # downside breakdown through support, and stock underperformance vs
        # NIFTY (relative weakness).
        factors["short_context"] = self._score_short_context(
            df, nifty_df, nifty_daily, stock_daily, htf_ctx
        )
        reasons_bear.append(f"ShortCtx={factors['short_context']['bearish']}")

        bullish_total = sum(f["bullish"] for f in factors.values())
        bearish_total = sum(f["bearish"] for f in factors.values())
        bullish_total = min(bullish_total, 100)
        bearish_total = min(bearish_total, 100)

        # ── Phase 1: confluence requirement (optional, env-gated) ──
        # A high aggregate score must be backed by the core pillars agreeing,
        # not just by a single strong factor. This trims marginal "spiky"
        # setups. Controlled by INST_CONFLUENCE_MIN (min bullish points each
        # core factor must clear). Default: disabled (0).
        _conf_min = int(os.environ.get("INST_CONFLUENCE_MIN", "0"))
        if _conf_min > 0:
            _core = ("market_regime", "price_action", "volume")
            _core_bull = min(factors[c]["bullish"] for c in _core)
            _core_bear = min(factors[c]["bearish"] for c in _core)
        else:
            _core_bull = _core_bear = 999  # never blocks when disabled

        direction = "NONE"
        total_score = 0
        if bullish_total >= LONG_MIN_SCORE and _core_bull >= _conf_min:
            direction = "LONG"
            total_score = bullish_total
        elif bearish_total >= SHORT_MIN_SCORE and _core_bear >= _conf_min:
            direction = "SHORT"
            total_score = bearish_total

        # ── Phase 2: regime gate (optional, env-gated) ──
        # Align trade direction with the HTF daily trend: require UP for LONG
        # and DOWN for SHORT. Controlled by INST_REQUIRE_TREND_UP=1. Default: off.
        _require_trend_up = os.environ.get("INST_REQUIRE_TREND_UP", "0") == "1"
        if _require_trend_up and htf_ctx:
            _dtd = htf_ctx.get("1d_trend", "FLAT")
            if direction == "LONG" and _dtd != "UP":
                direction = "NONE"
                total_score = 0
                reasons_bull.append(f"RegimeGate=blocked(daily={_dtd})")
            elif direction == "SHORT" and _dtd != "DOWN":
                direction = "NONE"
                total_score = 0
                reasons_bear.append(f"RegimeGate=blocked(daily={_dtd})")

        return {
            "total_score": total_score,
            "bullish_score": bullish_total,
            "bearish_score": bearish_total,
            "direction": direction,
            "factors": factors,
            "reasons": "; ".join(reasons_bull + reasons_bear),
            "detailed_breakdown": {
                name: {
                    "bullish": f["bullish"],
                    "bearish": f["bearish"],
                    "max": f["max"],
                    **f.get("detail", {}),
                }
                for name, f in factors.items()
            },
        }

    # ── Factor 1: Market Regime (0–15 each side) ────────────────
    # Uses NIFTY (primary) + India VIX (fear/gauge) + Bank Nifty (sector
    # conviction). VIX and Bank Nifty add up to ~6 points of combined influence
    # so the NIFTY EMA/swing core remains the dominant driver (~9/15).

    def _score_market_regime(
        self, nifty_df: pd.DataFrame | None, day_type: str,
        htf_ctx: dict | None = None,
        banknifty_df: pd.DataFrame | None = None,
        vix_daily: pd.DataFrame | None = None,
    ) -> dict:
        bull = 0
        bear = 0
        detail = {}

        # ── NIFTY core (0–12 each side) ─────────────────────────
        if nifty_df is not None and len(nifty_df) >= 60:
            close = nifty_df["close"]
            ema20 = _ema(close, 20)
            ema50 = _ema(close, 50)
            ema200 = _ema(close, 200) if len(close) >= 200 else None
            last_close = float(close.iloc[-1])

            if last_close > ema20:
                bull += 3
                detail["ema20"] = "above"
            elif last_close < ema20:
                bear += 3
                detail["ema20"] = "below"
            else:
                detail["ema20"] = "at"

            if last_close > ema50:
                bull += 3
                detail["ema50"] = "above"
            elif last_close < ema50:
                bear += 3
                detail["ema50"] = "below"
            else:
                detail["ema50"] = "at"

            if ema200 is not None:
                if last_close > ema200:
                    bull += 3
                    detail["ema200"] = "above"
                elif last_close < ema200:
                    bear += 3
                    detail["ema200"] = "below"
                else:
                    detail["ema200"] = "at"

            swings = _detect_swings(nifty_df)
            if swings["has_hh"] and swings["has_hl"]:
                bull += 3
                detail["swing_struct"] = "HH_HL"
            elif swings["has_ll"] and swings["has_lh"]:
                bear += 3
                detail["swing_struct"] = "LL_LH"
            elif swings["has_hh"] or swings["has_hl"]:
                bull += 1
                detail["swing_struct"] = "partial_bull"
            elif swings["has_ll"] or swings["has_lh"]:
                bear += 1
                detail["swing_struct"] = "partial_bear"
            else:
                detail["swing_struct"] = "flat"
        else:
            detail["note"] = "No NIFTY data"

        # ── Day type breadth (0–3 each side) ────────────────────
        if day_type == "REVERSAL":
            if nifty_df is not None and len(nifty_df) >= 50:
                nifty_close = nifty_df["close"]
                if float(nifty_close.iloc[-1]) > _ema(nifty_close, 50):
                    bull += 3
                    detail["breadth"] = "bull_reversal"
                else:
                    bear += 3
                    detail["breadth"] = "bear_reversal"
            else:
                detail["breadth"] = "reversal_unknown"
        elif day_type in ("TREND_UP", "GAP_UP"):
            bull += 3
            detail["breadth"] = "bullish"
        elif day_type in ("TREND_DOWN", "GAP_DOWN"):
            bear += 3
            detail["breadth"] = "bearish"
        else:
            detail["breadth"] = "neutral"

        # ── HTF bonus (0–1 each side) ───────────────────────────
        if htf_ctx:
            td = htf_ctx.get("1d_trend", "FLAT")
            if td == "UP":
                bull += 1
                detail["htf_1d"] = "up"
            elif td == "DOWN":
                bear += 1
                detail["htf_1d"] = "down"
            else:
                detail["htf_1d"] = "flat"

        # ── India VIX (0–2 bull, 0–4 bear) ─────────────────────
        # Fear/greed gauge: low VIX = calm tailwind for longs,
        # high VIX = risk-off headwind that favours shorts.
        if vix_daily is not None and len(vix_daily) >= 5:
            vix_close = vix_daily["close"].values
            vix_val = float(vix_close[-1])
            detail["vix"] = round(vix_val, 2)

            if vix_val < 15:
                bull += 1
                detail["vix_zone"] = "LOW"
            elif vix_val < 22:
                detail["vix_zone"] = "NORMAL"
            elif vix_val < 30:
                bear += 2
                detail["vix_zone"] = "ELEVATED"
            else:
                bear += 3
                detail["vix_zone"] = "EXTREME"

            vix_5d_ago = float(vix_close[-5])
            vix_chg = ((vix_val - vix_5d_ago) / vix_5d_ago) * 100
            detail["vix_chg_5d_pct"] = round(vix_chg, 2)
            if vix_chg < -10:
                bull += 1
                detail["vix_trend"] = "plunging"
            elif vix_chg > 10:
                bear += 1
                detail["vix_trend"] = "spiking"
            else:
                detail["vix_trend"] = "flat"

        # ── Bank Nifty (0–3 each side) ─────────────────────────
        # Relative strength vs NIFTY + EMA20 alignment. Banking
        # outperformance signals broad market strength.
        if (
            banknifty_df is not None
            and nifty_df is not None
            and len(banknifty_df) >= 20
            and len(nifty_df) >= 20
        ):
            bn_close = banknifty_df["close"].values
            nf_close = nifty_df["close"].values
            bn_ret_5 = (bn_close[-1] - bn_close[-5]) / bn_close[-5] * 100
            nf_ret_5 = (nf_close[-1] - nf_close[-5]) / nf_close[-5] * 100
            rel_str = bn_ret_5 - nf_ret_5
            detail["bn_rel_5d"] = round(rel_str, 2)
            if rel_str > 2:
                bull += 2
                detail["bn_relative"] = "outperforming"
            elif rel_str < -2:
                bear += 2
                detail["bn_relative"] = "underperforming"
            else:
                detail["bn_relative"] = "neutral"

            bn_ema20 = _ema(banknifty_df["close"], 20)
            bn_last = float(bn_close[-1])
            if bn_last > bn_ema20:
                bull += 1
                detail["bn_ema20"] = "above"
            elif bn_last < bn_ema20:
                bear += 1
                detail["bn_ema20"] = "below"
            else:
                detail["bn_ema20"] = "at"

        return {"bullish": min(bull, 15), "bearish": min(bear, 15), "max": 15, "detail": detail}

    # ── Factor 2: Sector Strength (0–15 each side) ─────────────

    def _score_sector_strength(
        self, df: pd.DataFrame, stock_type: str, sector_name: str | None
    ) -> dict:
        detail = {}

        stock_map = {
            "RS_LEADER": (5, 0),
            "BREAKOUT": (5, 0),
            "DEFENSIVE": (3, 1),
            "FOLLOWER": (2, 2),
            "IN_LINE": (1, 2),
            "WEAKNESS": (0, 4),
            "BREAKDOWN": (0, 5),
        }
        bull_rs, bear_rs = stock_map.get(stock_type, (1, 2))
        detail["stock_type_score"] = (bull_rs, bear_rs)

        avg_vol = float(df["volume"].tail(21).head(20).mean())
        last_vol = float(df["volume"].iloc[-1])
        rvol = last_vol / max(avg_vol, 1)
        detail["rvol"] = round(rvol, 2)

        if rvol > 2.0:
            bull_v = 8
            bear_v = 2
        elif rvol > 1.5:
            bull_v = 6
            bear_v = 1
        elif rvol > 1.0:
            bull_v = 4
            bear_v = 3
        elif rvol > 0.5:
            bull_v = 2
            bear_v = 5
        else:
            bull_v = 1
            bear_v = 7

        detail["vol_tier"] = (bull_v, bear_v)

        return {
            "bullish": min(bull_rs + bull_v, 12),
            "bearish": min(bear_rs + bear_v, 12),
            "max": 12,
            "detail": detail,
        }

    # ── Factor 3: Price Action (0–20 each side) ────────────────

    def _score_price_action(
        self, df: pd.DataFrame, stock_daily: pd.DataFrame | None
    ) -> dict:
        bull = 0
        bear = 0
        detail = {}

        close = df["close"].values
        last_close = float(close[-1])

        atr_val = _atr(df["high"], df["low"], pd.Series(close), self.atr_period)
        if atr_val <= 0:
            atr_val = last_close * 0.01

        highs = df["high"].values
        lows = df["low"].values

        # Swing structure
        swings = _detect_swings(df)
        if swings["has_hh"] and swings["has_hl"]:
            bull += 8
            detail["swing_struct"] = "HH_HL"
        elif swings["has_ll"] and swings["has_lh"]:
            bear += 8
            detail["swing_struct"] = "LL_LH"
        elif swings["has_hh"] or swings["has_hl"]:
            bull += 4
            detail["swing_struct"] = "partial_bull"
        elif swings["has_ll"] or swings["has_lh"]:
            bear += 4
            detail["swing_struct"] = "partial_bear"
        else:
            detail["swing_struct"] = "flat"

        # Bullish: breakout above resistance
        resist, break_pct = _nearest_resistance(highs, last_close)
        if resist is not None and break_pct > 0.5:
            if break_pct > 5.0:
                bull += 6
            elif break_pct > 2.0:
                bull += 4
            else:
                bull += 3
            detail["breakout_pct"] = round(break_pct, 2)
        elif resist is not None and break_pct > 0:
            bull += 1
            detail["breakout_pct"] = round(break_pct, 2)
        else:
            detail["breakout_pct"] = 0

        # Bearish: genuine breakdown below support (with displacement)
        supp, bd_pct = _nearest_broken_support(lows, last_close)
        if supp is not None and bd_pct > 0:
            if bd_pct > 2.0:
                bear += 8
            elif bd_pct > 0.5:
                bear += 5
            else:
                bear += 2
            detail["breakdown_pct"] = round(bd_pct, 2)
        else:
            detail["breakdown_pct"] = 0

        # ── SELL-THE-RIP: rally into overhead resistance + rejection ──
        rally = self._recent_rally_into_resistance(df, highs, lows, close, atr_val)
        detail["sell_the_rip"] = rally
        if rally:
            bear += 8

        # ── Below VWAP / EMA confirmation (bearish context) ──
        vwap_val = _vwap(df)
        ema20 = _ema(pd.Series(close), 20)
        if last_close < vwap_val:
            bear += 2
            detail["vwap"] = "below"
        else:
            detail["vwap"] = "above"
        if last_close < ema20:
            bear += 1

        # Bullish support quality (pullback to support)
        bull_support = 0
        if swings["last_swing_low"] > 0:
            low_dist = last_close - swings["last_swing_low"]
            low_atr_dist = low_dist / max(atr_val, 0.01)
            if low_atr_dist <= 1.0:
                bull_support = 6
            elif low_atr_dist <= 2.0:
                bull_support = 5
            elif low_atr_dist <= 3.0:
                bull_support = 4
            elif low_atr_dist <= 5.0:
                bull_support = 3
            else:
                bull_support = 1
        else:
            ema50 = _ema(pd.Series(close), 50)
            if last_close > ema20 and last_close > ema50:
                bull_support = 4
            elif last_close > ema20:
                bull_support = 2
        bull += bull_support
        detail["support_quality"] = bull_support

        # Overhead supply (bearish). Strong only in sell-the-rip context,
        # otherwise mild — sitting near a high after a decline is a weak short.
        bear_resist = 0
        if swings["last_swing_high"] > 0:
            high_dist = swings["last_swing_high"] - last_close
            high_atr_dist = high_dist / max(atr_val, 0.01)
            if rally:
                bear_resist = 4 if high_atr_dist <= 1.0 else (2 if high_atr_dist <= 2.0 else 0)
            else:
                bear_resist = 2 if high_atr_dist <= 1.0 else 0
        bear += bear_resist
        detail["resist_proximity"] = bear_resist

        return {"bullish": min(bull, 16), "bearish": min(bear, 16), "max": 16, "detail": detail}

    def _recent_rally_into_resistance(
        self, df: pd.DataFrame, highs, lows, close, atr_val: float
    ) -> bool:
        """Detect a genuine 'sell-the-rip' short setup:
        price rallied into overhead resistance (rolling-max high) over the last
        ~20 bars, then closed weak (lower half of its range)."""
        n = len(close)
        if n < 12:
            return False
        look = min(20, n - 1)
        start = float(close[-look])
        end = float(close[-1])
        if start <= 0:
            return False
        rally_pct = (end - start) / abs(start) * 100

        # Resistance = rolling-max high over the lookback window
        window = highs[-(look + 1):-1] if n > look else highs[:-1]
        if len(window) == 0:
            return False
        resist = float(np.max(window))
        if resist <= 0:
            return False
        high_dist = resist - end
        high_atr_dist = high_dist / max(atr_val, 0.01)

        # Must have rallied AND be at/near overhead resistance
        if not (rally_pct > 2.0 and 0 <= high_atr_dist <= 2.0):
            return False

        # Rejection: last candle closed in its lower half (weak close)
        last_o = float(df["open"].values[-1])
        last_c = end
        last_h = float(highs[-1])
        last_l = float(lows[-1])
        if last_h <= last_l:
            return False
        body_mid = (last_o + last_c) / 2.0
        return last_c < body_mid

    # ── Factor 4: Volume (0–15 each side) ──────────────────────

    def _score_volume(self, df: pd.DataFrame) -> dict:
        if "volume" not in df.columns:
            return {"bullish": 0, "bearish": 0, "max": 12, "detail": {"rvol": 0}}

        avg_vol = float(df["volume"].tail(21).head(20).mean())
        last_vol = float(df["volume"].iloc[-1])
        rvol = last_vol / max(avg_vol, 1)

        close = df["close"].values
        price_up = float(close[-1]) > float(close[-3]) if len(close) >= 3 else True

        bull = 0
        bear = 0
        if rvol >= 3.0:
            if price_up:
                bull = 15
            else:
                bear = 15
        elif rvol >= 1.5:
            if price_up:
                bull = 10
            else:
                bear = 10
        elif rvol >= 1.0:
            if price_up:
                bull = 5
            else:
                bear = 5
        else:
            if price_up:
                bull = 2
            else:
                bear = 2

        return {"bullish": bull, "bearish": bear, "max": 12, "detail": {"rvol": round(rvol, 2)}}

    # ── Factor 5: Breakout / Breakdown Quality (0–15 each side) ─

    def _score_breakout_quality(
        self, df: pd.DataFrame, day_type: str, regime_bullish: int,
        htf_ctx: dict | None = None,
    ) -> dict:
        bull = 0
        bear = 0
        detail = {}

        close = df["close"].values
        last_close = float(close[-1])
        highs = df["high"].values
        lows = df["low"].values

        atr_val = _atr(df["high"], df["low"], pd.Series(close), self.atr_period)
        if atr_val <= 0:
            atr_val = last_close * 0.01

        avg_vol = float(df["volume"].tail(21).head(20).mean())
        last_vol = float(df["volume"].iloc[-1])
        rvol = last_vol / max(avg_vol, 1)

        # ── Bullish breakout checklist ──
        resist, break_pct = _nearest_resistance(highs, last_close)
        if resist is not None and break_pct > 0.5:
            if break_pct > 3.0:
                bull += 3
            elif break_pct > 1.5:
                bull += 2
            else:
                bull += 1
            detail["breaks_resistance"] = round(break_pct, 2)
        else:
            detail["breaks_resistance"] = 0

        if rvol > 1.5:
            bull += 3
            detail["vol_confirmed_bull"] = True
        else:
            detail["vol_confirmed_bull"] = False

        recent_low = float(np.min(lows[-10:-1])) if len(lows) > 10 else float(np.min(lows[:-1]))
        if resist is not None and recent_low > resist * 0.99:
            bull += 3
            detail["retest_holds"] = True
        else:
            detail["retest_holds"] = False

        market_ok = day_type in ("TREND_UP", "GAP_UP") or regime_bullish >= 9
        if market_ok:
            bull += 3
            detail["market_aligned_bull"] = True
        else:
            detail["market_aligned_bull"] = False

        # ── Bearish breakdown checklist ──
        supp, bd_pct = _nearest_broken_support(lows, last_close)
        if supp is not None and bd_pct > 0.5:
            if bd_pct > 3.0:
                bear += 3
            elif bd_pct > 1.5:
                bear += 2
            else:
                bear += 1
            detail["breaks_support"] = round(bd_pct, 2)
        else:
            detail["breaks_support"] = 0

        if rvol > 1.5:
            bear += 3
            detail["vol_confirmed_bear"] = True
        else:
            detail["vol_confirmed_bear"] = False

        recent_high = float(np.max(highs[-10:-1])) if len(highs) > 10 else float(np.max(highs[:-1]))
        if supp is not None and recent_high < supp * 1.01:
            bear += 3
            detail["retest_fails"] = True
        else:
            detail["retest_fails"] = False

        market_bad = day_type in ("TREND_DOWN", "GAP_DOWN")
        if market_bad:
            bear += 3
            detail["market_aligned_bear"] = True
        else:
            detail["market_aligned_bear"] = False

        # HTF bonus
        if htf_ctx:
            t30 = htf_ctx.get("30m_trend", "FLAT")
            if t30 == "UP":
                bull += 1
                detail["htf_30m"] = "up"
            elif t30 == "DOWN":
                bear += 1
                detail["htf_30m"] = "down"
            else:
                detail["htf_30m"] = "flat"

        return {"bullish": min(bull, 10), "bearish": min(bear, 10), "max": 10, "detail": detail}

    # ── Factor 6: Risk/Reward (0–10 each side) ─────────────────

    def _score_risk_reward(self, df: pd.DataFrame) -> dict:
        close = pd.Series(df["close"].values)
        high = pd.Series(df["high"].values)
        low = pd.Series(df["low"].values)
        entry = float(close.iloc[-1])
        atr_val = _atr(high, low, close, self.atr_period)
        if atr_val <= 0:
            atr_val = entry * 0.01

        swings = _detect_swings(df)

        # LONG: risk = support distance below, reward = resistance distance above
        risk_long = atr_val * self.sl_mult
        if swings["last_swing_low"] > 0 and entry > swings["last_swing_low"]:
            risk_long = max(risk_long, entry - swings["last_swing_low"])
        fwd_res, _ = _nearest_forward_resistance(df["high"].values, entry)
        reward_long = atr_val * self.tp_mult
        if fwd_res is not None and fwd_res > entry:
            reward_long = min(reward_long, fwd_res - entry)
        rr_long = reward_long / max(risk_long, 0.01)

        if rr_long >= 2.5:
            bull_score = 10
            bull_tier = "institutional"
        elif rr_long >= 1.5:
            bull_score = 7
            bull_tier = "good"
        elif rr_long >= 1.0:
            bull_score = 5
            bull_tier = "fair"
        else:
            bull_score = 0
            bull_tier = "reject"

        # SHORT: risk = resistance distance above, reward = support distance below
        risk_short = atr_val * self.sl_mult * self.short_sl_mult
        if swings["last_swing_high"] > 0 and swings["last_swing_high"] > entry:
            risk_short = max(risk_short, (swings["last_swing_high"] - entry) * self.short_sl_mult)
        supp, _ = _nearest_support(df["low"].values, entry)
        reward_short = atr_val * self.tp_mult * self.short_tp_mult
        if supp is not None and entry > supp:
            reward_short = min(reward_short, (entry - supp) * self.short_tp_mult)
        rr_short = reward_short / max(risk_short, 0.01)

        if rr_short >= 2.5:
            bear_score = 10
            bear_tier = "institutional"
        elif rr_short >= 1.5:
            bear_score = 7
            bear_tier = "good"
        elif rr_short >= 1.0:
            bear_score = 5
            bear_tier = "fair"
        else:
            bear_score = 0
            bear_tier = "reject"

        return {
            "bullish": bull_score,
            "bearish": bear_score,
            "max": 8,
            "detail": {
                "rr_long": round(rr_long, 2),
                "rr_short": round(rr_short, 2),
                "tier_long": bull_tier,
                "tier_short": bear_tier,
                "sl_long": round(entry - risk_long, 2),
                "tp_long": round(entry + reward_long, 2),
                "sl_short": round(entry + risk_short, 2),
                "tp_short": round(entry - reward_short, 2),
                "atr": round(atr_val, 2),
            },
        }

    # ── Factor 7: Indicators (0–5 each side) ───────────────────

    def _score_indicators(self, df: pd.DataFrame) -> dict:
        bull = 0
        bear = 0
        detail = {}

        close = df["close"]
        last_close = float(close.iloc[-1])

        ema20 = _ema(close, 20)
        ema50 = _ema(close, 50)
        ema200 = _ema(close, 200) if len(close) >= 200 else None

        if ema20 > ema50 and (ema200 is None or ema50 > ema200):
            bull += 2
            detail["ema_aligned"] = "bullish"
        elif ema20 < ema50 and (ema200 is None or ema50 < ema200):
            bear += 2
            detail["ema_aligned"] = "bearish"
        else:
            detail["ema_aligned"] = "mixed"

        rsi_val = _rsi(close)
        if 50 <= rsi_val <= 70:
            bull += 1
            detail["rsi"] = "healthy_bull"
        elif rsi_val > 70:
            detail["rsi"] = "overbought"
        elif rsi_val < 30:
            bear += 1
            detail["rsi"] = "oversold_bear"
        else:
            detail["rsi"] = "neutral"

        macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_val = float(macd_line.iloc[-1])
        signal_val = float(signal.iloc[-1])
        if macd_val > signal_val:
            bull += 1
            detail["macd"] = "bullish"
        else:
            bear += 1
            detail["macd"] = "bearish"

        if "volume" in df.columns:
            vwap_val = _vwap(df)
            if last_close > vwap_val:
                bull += 1
                detail["vwap"] = "above"
            else:
                bear += 1
                detail["vwap"] = "below"
        else:
            detail["vwap"] = None

        return {"bullish": min(bull, 5), "bearish": min(bear, 5), "max": 5, "detail": detail}

    # ── Factor 8: Catalyst (0–5 each side) ────────────────────

    def _score_catalyst(self, df: pd.DataFrame) -> dict:
        bull = 0
        bear = 0
        detail = {}

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values if "volume" in df.columns else None

        price_up = float(close[-1]) > float(close[-5]) if len(close) >= 5 else True
        detail["price_rising"] = price_up

        vol_trend = False
        if volume is not None:
            vol_trend = float(np.mean(volume[-5:])) > float(np.mean(volume[-10:-5])) * 1.1
            detail["volume_rising"] = vol_trend
        else:
            detail["volume_rising"] = False

        # Bullish: accumulation
        if price_up and vol_trend:
            bull += 3
            detail["accumulation"] = "strong"
        elif price_up:
            bull += 1
            detail["accumulation"] = "mild"

        # Bearish: distribution
        if not price_up and vol_trend:
            bear += 3
            detail["distribution"] = "strong"
        elif not price_up:
            bear += 1
            detail["distribution"] = "mild"

        # Bullish: dips absorbed
        dips_absorbed = float(np.min(low[-5:])) > float(np.min(low[-10:-5])) if len(low) >= 10 else False
        if dips_absorbed:
            bull += 2
            detail["dips_absorbed"] = True
        else:
            detail["dips_absorbed"] = False

        # Bearish: failed bounces
        failed_bounce = float(np.max(high[-5:])) < float(np.max(high[-10:-5])) if len(high) >= 10 else False
        if failed_bounce:
            bear += 2
            detail["failed_bounce"] = True
        else:
            detail["failed_bounce"] = False

        return {"bullish": min(bull, 5), "bearish": min(bear, 5), "max": 5, "detail": detail}

    # ── Factor 9: Session / Time-of-Day Timing (0–10 each side) ──
    #
    # Scores the entry bar's market session. Weights are calibrated from
    # evidence via scripts/analyze_time_of_day.py (saved to
    # data/time_of_day_analysis.json). Default is neutral until calibrated.

    SESSION_WEIGHTS = {
        "opening": {"bull": 0, "bear": 0},
        "morning": {"bull": 0, "bear": 0},
        "midday": {"bull": 0, "bear": 0},
        "afternoon": {"bull": 0, "bear": 0},
        "closing": {"bull": 0, "bear": 0},
    }

    @classmethod
    def _session_from_time(cls, entry_time: str | None) -> str:
        if not entry_time:
            return "unknown"
        try:
            from datetime import datetime as _dt
            ts = entry_time.replace("Z", "+00:00")
            dt = _dt.fromisoformat(ts)
            hour = dt.hour + dt.minute / 60.0
            from config.trading_config import SESSION_STARTS, SESSION_ENDS
            for name, start in SESSION_STARTS.items():
                end = SESSION_ENDS[name]
                sh, sm = map(float, start.split(":"))
                eh, em = map(float, end.split(":"))
                s_val = sh + sm / 60.0
                e_val = eh + em / 60.0
                if s_val <= hour < e_val:
                    return name
            return "unknown"
        except Exception:
            return "unknown"

    def _score_session_timing(
        self, entry_time: str | None, htf_ctx: dict | None = None
    ) -> dict:
        detail = {}
        session = self._session_from_time(entry_time)
        detail["session"] = session

        weights = self.SESSION_WEIGHTS.get(session, {"bull": 0, "bear": 0})
        bull = weights["bull"]
        bear = weights["bear"]

        # HTF alignment within session context
        if htf_ctx:
            td = htf_ctx.get("1d_trend", "FLAT")
            if td == "UP":
                bull += 1
            elif td == "DOWN":
                bear += 1

        return {"bullish": min(bull, 10), "bearish": min(bear, 10), "max": 10, "detail": detail}

    # ── Factor 10: Historical Stock Performance (0–10 each side) ──
    #
    # Uses trailing multi-window returns (5d/20d/60d/120d) from stock_daily
    # to assess the stock's recent performance nature. Positive momentum
    # supports LONG; negative supports SHORT. Relative strength vs Nifty
    # daily is also considered.

    def _score_historical_performance(
        self,
        df: pd.DataFrame,
        stock_daily: pd.DataFrame | None,
        nifty_daily: pd.DataFrame | None,
    ) -> dict:
        detail = {}
        bull = 0
        bear = 0

        if stock_daily is None or len(stock_daily) < 10:
            detail["note"] = "No daily history"
            return {"bullish": 0, "bearish": 0, "max": 10, "detail": detail}

        try:
            closes = stock_daily["close"].astype(float).values
            n = len(closes)

            # Trailing returns for multiple windows
            windows = [5, 20, 60, 120]
            ret_sum_bull = 0
            ret_sum_bear = 0
            for w in windows:
                if n > w:
                    ret = (closes[-1] - closes[-w - 1]) / closes[-w - 1] * 100
                else:
                    ret = 0.0
                detail[f"ret_{w}d"] = round(ret, 2)
                # Bullish if positive momentum, bearish if negative
                if ret > 5.0:
                    ret_sum_bull += 3
                elif ret > 0:
                    ret_sum_bull += 1
                elif ret < -5.0:
                    ret_sum_bear += 3
                elif ret < 0:
                    ret_sum_bear += 1

            bull += min(ret_sum_bull, 7)
            bear += min(ret_sum_bear, 7)

            # Relative strength vs Nifty daily
            if nifty_daily is not None and len(nifty_daily) >= 20:
                nifty_closes = nifty_daily["close"].astype(float).values
                if len(nifty_closes) > 20:
                    stock_ret = (closes[-1] - closes[-21]) / closes[-21] * 100
                    nifty_ret = (nifty_closes[-1] - nifty_closes[-21]) / nifty_closes[-21] * 100
                    rs = stock_ret - nifty_ret
                    detail["rel_strength_20d"] = round(rs, 2)
                    if rs > 3.0:
                        bull += 3
                    elif rs < -3.0:
                        bear += 3

        except Exception as e:
            detail["error"] = str(e)
            return {"bullish": 0, "bearish": 0, "max": 10, "detail": detail}

        return {"bullish": min(bull, 10), "bearish": min(bear, 10), "max": 10, "detail": detail}

    # ── Phase 3: dedicated SHORT context (0–20 bearish, 0 bullish) ──
    #
    # Genuine bearish evidence. This is the heart of fixing SHORT: it scores
    # "is this a real short", independent of the (separate) bullish logic.
    def _score_short_context(
        self,
        df: pd.DataFrame,
        nifty_df: pd.DataFrame | None,
        nifty_daily: pd.DataFrame | None,
        stock_daily: pd.DataFrame | None,
        htf_ctx: dict | None,
    ) -> dict:
        detail: dict = {}
        bear = 0

        # 1) HTF daily trend DOWN (institutional alignment for shorts)
        if htf_ctx:
            td = htf_ctx.get("1d_trend", "FLAT")
            if td == "DOWN":
                bear += 5
                detail["htf_1d"] = "down"
            elif td == "FLAT":
                bear += 1
                detail["htf_1d"] = "flat"
            else:
                detail["htf_1d"] = "up"

        # 2) Bearish swing structure (LL/LH) on the entry timeframe
        try:
            swings = _detect_swings(df)
            if swings["has_ll"] and swings["has_lh"]:
                bear += 5
                detail["swing_struct"] = "LL_LH"
            elif swings["has_ll"] or swings["has_lh"]:
                bear += 2
                detail["swing_struct"] = "partial_bear"
            else:
                detail["swing_struct"] = "none"
        except Exception:
            detail["swing_struct"] = "err"

        # 3) Breakdown through nearest support (bearish confirmation)
        try:
            lows = df["low"].values
            last = float(df["close"].iloc[-1])
            sup, sup_pct = _nearest_support(lows, last)
            if sup is not None and sup_pct <= 0.5:
                # price sitting just below / breaking the nearest support
                bear += 4
                detail["breakdown_near_support"] = True
            else:
                detail["breakdown_near_support"] = False
        except Exception:
            detail["breakdown_near_support"] = "err"

        # 4) Relative weakness vs NIFTY (stock falling harder than index).
        #    Compare stock daily return against NIFTY DAILY return (apples to
        #    apples). Previously this compared the stock's 20-day daily return
        #    against NIFTY's 20-*intraday*-bar return, which on 15m data meant
        #    comparing a month of stock data against ~5 hours of NIFTY.
        try:
            if stock_daily is not None and len(stock_daily) >= 21:
                sc = stock_daily["close"].astype(float).values
                s_ret = (sc[-1] - sc[-21]) / sc[-21] * 100
                if nifty_daily is not None and len(nifty_daily) >= 21:
                    nc = nifty_daily["close"].astype(float).values
                    n_ret = (nc[-1] - nc[-21]) / nc[-21] * 100
                    rs = s_ret - n_ret
                    detail["rel_strength_20d"] = round(rs, 2)
                    if rs < -3.0:
                        bear += 4
                    elif rs < 0:
                        bear += 2
                else:
                    if s_ret < -3.0:
                        bear += 4
                    elif s_ret < 0:
                        bear += 2
        except Exception:
            detail["rs_err"] = True

        # 5) Distribution volume on the last down bar
        try:
            vol = df["volume"].astype(float).values
            close = df["close"].astype(float).values
            if len(vol) >= 2 and len(close) >= 2:
                down_bar = close[-1] < close[-2]
                avg_vol = float(pd.Series(vol).tail(20).mean())
                rvol = float(vol[-1]) / max(avg_vol, 1)
                if down_bar and rvol > 1.5:
                    bear += 2
                    detail["distribution_vol"] = True
                else:
                    detail["distribution_vol"] = False
        except Exception:
            detail["vol_err"] = True

        return {"bullish": 0, "bearish": min(bear, 20), "max": 20, "detail": detail}

    @staticmethod
    def _empty_result(reason: str) -> dict:
        return {
            "total_score": 0,
            "bullish_score": 0,
            "bearish_score": 0,
            "direction": "NONE",
            "factors": {
                k: {"bullish": 0, "bearish": 0, "max": m, "detail": {}}
                for k, m in [
                    ("market_regime", 12),
                    ("sector_strength", 12),
                    ("price_action", 16),
                    ("volume", 12),
                    ("breakout_quality", 10),
                    ("risk_reward", 8),
                    ("indicators", 5),
                    ("catalyst", 5),
                     ("session_timing", 10),
                    ("historical_performance", 10),
                    ("short_context", 20),
                ]
            },
            "reasons": reason,
            "detailed_breakdown": {},
        }
