"""
Strategy Registry — minimal metadata for deployed strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Strategy:
    name: str = ""
    category: str = ""
    description: str = ""
    timeframes: list[str] = field(default_factory=list)
    confidence: str = ""
    tuning: dict = field(default_factory=lambda: {"sl_mult": 3.0, "tp_mult": 4.0, "atr_period": 14})


STRATEGIES: dict[str, Strategy] = {}


def register(s: Strategy):
    STRATEGIES[s.name] = s


def get(name: str) -> Strategy | None:
    return STRATEGIES.get(name)


register(Strategy(
    name="Relative Strength Momentum",
    category="Momentum / Growth",
    description="RSI-volume-momentum breakout with per-symbol tunings. Swing (next_close).",
    timeframes=["15m", "1h"],
    confidence="IMPLEMENTED",
    tuning={"sl_mult": 2.0, "tp_mult": 4.0, "atr_period": 14},
))

register(Strategy(
    name="Combined Swing",
    category="Momentum / Growth",
    description="Day-aware RSM-swing LONG, per-symbol SL/TP.",
    timeframes=["15m"],
    confidence="IMPLEMENTED",
    tuning={"sl_mult": 2.0, "tp_mult": 4.0, "atr_period": 14},
))

register(Strategy(
    name="Manual Institutional (time-gated)",
    category="Momentum / Growth",
    description="Time-gated golden window entries with per-symbol tunings and confirmation gate.",
    timeframes=["15m"],
    confidence="IMPLEMENTED",
    tuning={"sl_mult": 0.5, "tp_mult": 5.0, "atr_period": 14},
))

register(Strategy(
    name="ML Standalone",
    category="Execution / Intraday",
    description="XGBoost classifier generates entries from raw market state. Symmetric LONG+SHORT.",
    timeframes=["15m"],
    confidence="IMPLEMENTED",
    tuning={"sl_mult": 0.5, "tp_mult": 5.0, "atr_period": 14},
))

register(Strategy(
    name="Daily Trend Breakout",
    category="Trend Following",
    description="Donchian breakout with trailing ATR stop. LONG-only, daily timeframe.",
    timeframes=["1d"],
    confidence="IMPLEMENTED",
    tuning={"sl_mult": 4.0, "tp_mult": 5.0, "atr_period": 14},
))

register(Strategy(
    name="ML Opening Breakout",
    category="Execution / Intraday",
    description="XGBoost on opening-window features. 5m, symmetric LONG+SHORT.",
    timeframes=["5m"],
    confidence="IMPLEMENTED",
    tuning={"sl_mult": 0.5, "tp_mult": 5.0, "atr_period": 14},
))
