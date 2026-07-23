"""
NIFTY Futures Strategy — VWAP-reversion + momentum (15m intraday).

Wraps NiftyFuturesEngine into the ExecutableStrategy interface so it runs
through the backtest engine (scripts/backtest.py) and paper trader.

Default SL=1.5×ATR, TP=3.0×ATR, max hold 12 bars (3h). These are tight
scalp-style stops appropriate for 15m index futures.

Usage:
    strat = NiftyFuturesStrategy()
    result = strat.run(df, symbol="NIFTY", timeframe="15m")
    # result.trade_candidates[0] → TradeCandidate with direction, entry, SL, TP
"""

from __future__ import annotations

import logging

import pandas as pd

from engines.nifty_futures_engine import NiftyFuturesEngine, LONG_MIN_SCORE as MIN_SCORE
from strategies.executable import ExecutableStrategy, StrategyResult, TradeCandidate

_log = logging.getLogger("nifty_futures_strategy")


class NiftyFuturesStrategy(ExecutableStrategy):
    """VWAP-reversion + momentum strategy for NIFTY 15m intraday futures."""

    @property
    def name(self) -> str:
        return "NIFTY Futures"

    def __init__(
        self,
        sl_mult: float = 1.5,
        tp_mult: float = 3.0,
        atr_period: int = 14,
        max_hold_bars: int = 12,
        score_threshold: int | None = None,
        **_ignored,
    ):
        self.sl_mult = sl_mult
        self.tp_mult = tp_mult
        self.atr_period = atr_period
        self.max_hold_bars = max_hold_bars
        self.score_threshold = score_threshold or MIN_SCORE
        self._engine = NiftyFuturesEngine(atr_period=atr_period)

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        day_type: str = "",
        stock_type: str = "",
        **kwargs,
    ) -> StrategyResult:
        if df is None or len(df) < 30:
            return StrategyResult(metadata={"reason": "insufficient data"})

        # Compute opening range from first 2 bars of today (09:15-09:45 IST)
        opening_range = None
        if len(df) >= 2:
            try:
                is_today_bar = pd.to_datetime(df["timestamp"].iloc[-1]).date() == \
                    pd.Timestamp.now().date()
            except Exception:
                is_today_bar = False
            if is_today_bar:
                # Find first 2 bars of today
                today_mask = pd.to_datetime(df["timestamp"]).date == \
                    pd.Timestamp.now().date()
                today_bars = df[today_mask]
                if len(today_bars) >= 2:
                    or_high = float(today_bars["high"].iloc[:2].max())
                    or_low = float(today_bars["low"].iloc[:2].min())
                    opening_range = (or_high, or_low)

        nifty_1d = kwargs.get("nifty_daily", None)

        result = self._engine.compute(df, nifty_1d=nifty_1d, opening_range=opening_range)

        if result["direction"] == "NEUTRAL":
            return StrategyResult(metadata={
                "direction": "NEUTRAL",
                "score": result.get("total_score", 0),
            })

        score = result["total_score"]
        if score < self.score_threshold:
            return StrategyResult(metadata={
                "direction": result["direction"],
                "score": score,
                "reason": f"score {score} < threshold {self.score_threshold}",
            })

        atr_val = result.get("atr", 0)
        if atr_val <= 0:
            return StrategyResult(metadata={"reason": "ATR not available"})

        entry_price = float(df["close"].iloc[-1])
        direction = result["direction"]

        if direction == "LONG":
            stop_loss = round(entry_price - self.sl_mult * atr_val, 2)
            take_profit = round(entry_price + self.tp_mult * atr_val, 2)
        else:
            stop_loss = round(entry_price + self.sl_mult * atr_val, 2)
            take_profit = round(entry_price - self.tp_mult * atr_val, 2)

        candidate = TradeCandidate(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            is_executable=True,
            rationale=f"NIFTY Futures {direction} score={score} "
                      f"vwap_dist={result.get('factors', {}).get('vwap_long', 0):.0f}/"
                      f"{result.get('factors', {}).get('vwap_short', 0):.0f} "
                      f"bb={result.get('bb_pct', 0.5):.2f} "
                      f"rsi={result.get('rsi', 50):.0f}",
            symbol=symbol,
            timeframe=timeframe,
            ranking_score=score,
            max_hold_bars=self.max_hold_bars,
        )

        return StrategyResult(
            trade_candidates=[candidate],
            metadata={
                "direction": direction,
                "score": score,
                "factors": result.get("factors", {}),
                "vwap": result.get("vwap", 0),
                "atr": atr_val,
            },
        )
