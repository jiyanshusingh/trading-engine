"""
Strategy Selector — executable strategy registry for deployed strategies.
"""

from __future__ import annotations


EXECUTABLE_MAP: dict[str, type] = {}


def register_executable(name: str, strategy_cls: type):
    EXECUTABLE_MAP[name] = strategy_cls


def get_executable(name: str, **kwargs):
    cls = EXECUTABLE_MAP.get(name)
    if cls is None:
        return None
    return cls(**kwargs)


def select(day_type: str | None = None,
           stock_type: str | None = None) -> tuple[None, None]:
    """Auto-select a strategy by market conditions (stub).

    Returns ``(None, None)`` so callers fall back to the configured default.
    """
    return None, None


# ── Deployed strategies ───────────────────────────────────────────────

from strategies.relative_strength_strategy import RelativeStrengthStrategy
from strategies.combined_swing_strategy import CombinedSwingStrategy
from strategies.manual_institutional_strategy import ManualInstitutionalStrategy
from strategies.ml_strategy import MLStrategy
from strategies.daily_trend_strategy import DailyTrendBreakoutStrategy
from strategies.orb_ml_strategy import MLOpeningBreakoutStrategy
from strategies.nifty_futures_strategy import NiftyFuturesStrategy

register_executable("Relative Strength Momentum", RelativeStrengthStrategy)
register_executable("Combined Swing", CombinedSwingStrategy)
register_executable("Manual Institutional (time-gated)", ManualInstitutionalStrategy)
register_executable("ML Standalone", MLStrategy)
register_executable("Daily Trend Breakout", DailyTrendBreakoutStrategy)
register_executable("ML Opening Breakout", MLOpeningBreakoutStrategy)
register_executable("NIFTY Futures", NiftyFuturesStrategy)
