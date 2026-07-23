"""
Executable Strategy Interface

Defines the uniform interface that all backtestable strategies
must implement, along with shared data types for strategy results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TradeCandidate:
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    is_executable: bool = True
    rationale: str = ""
    symbol: str = ""
    timeframe: str = ""
    ranking_score: int = 80
    # Trailing-stop support (Daily Trend Breakout). When ``trail_atr_mult`` > 0
    # the backtester / paper trader trail the stop at
    # ``high_water_mark - trail_atr_mult * ATR`` (close-based) and IGNORE the
    # fixed ``take_profit`` — letting winners run. 0 keeps legacy fixed SL/TP.
    trail_atr_mult: float = 0.0
    # Optional per-trade override of the global MAX_HOLD_BARS time stop.
    max_hold_bars: int | None = None


@dataclass
class StrategyResult:
    trade_candidates: list[TradeCandidate] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class ExecutableStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def run(
        self,
        df,
        symbol: str,
        timeframe: str,
        day_type: str = "",
        stock_type: str = "",
        **kwargs,
    ) -> StrategyResult:
        ...
