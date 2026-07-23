"""
Backtesting Engine

Walks historical data step by step, running the
pipeline at each step to evaluate how well the
trading logic performs historically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class BacktestTrade:
    """Record of a single backtested trade."""
    symbol: str
    timeframe: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_index: int
    entry_timestamp: str = ""
    exit_index: int | None = None
    exit_price: float | None = None
    exit_timestamp: str | None = None
    result: str | None = None
    pnl: float | None = None
    pnl_percent: float | None = None
    r_multiple: float | None = None
    entry_reasoning: str = ""
    exit_reasoning: str = ""


@dataclass
class BacktestResult:
    """Aggregated backtest results."""
    symbol: str
    timeframe: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    avg_r_multiple: float = 0.0
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)


class BacktestingEngine:
    """
    Walks historical OHLCV data and evaluates trading
    signals against actual price movements.

    For each trade candidate produced by the pipeline,
    the engine simulates entry, stop, and target to
    determine outcome.
    """

    def __init__(
        self,
        pipeline_runner,
        initial_capital: float = 100000.0,
    ):
        """
        Parameters
        ----------
        pipeline_runner
            Callable that accepts a market model and
            returns a PipelineResult with trade_candidates.
        initial_capital
            Starting capital for the backtest.
        """
        self._pipeline_runner = pipeline_runner
        self._initial_capital = initial_capital

    def run(
        self,
        observation_history,
        symbol: str,
        timeframe: str,
    ) -> BacktestResult:
        """
        Run a full backtest over the observation history.
        """
        trades: list[BacktestTrade] = []
        equity = [self._initial_capital]
        capital = self._initial_capital

        window = 100

        for i in range(window, len(observation_history)):
            window_obs = observation_history.observations[:i]
            obs_history = self._build_window(
                window_obs,
                observation_history.metadata,
            )

            try:
                result = self._pipeline_runner(obs_history)
            except Exception:
                continue

            for tc in result.trade_candidates:
                if not tc.is_executable:
                    continue

                bt_trade = self._simulate_trade(
                    tc, i, observation_history
                )
                if bt_trade is not None:
                    trades.append(bt_trade)
                    capital += (bt_trade.pnl or 0.0)
                    equity.append(capital)

        return self._aggregate(trades, equity)

    def _build_window(self, observations, metadata):
        from domain.market_observation.observation_history import (
            ObservationHistory,
        )
        return ObservationHistory(
            observations=tuple(observations),
            metadata=metadata,
        )

    def _simulate_trade(
        self,
        trade_candidate,
        entry_index: int,
        full_history,
    ) -> BacktestTrade | None:
        direction = trade_candidate.direction
        entry = trade_candidate.entry_price
        stop = trade_candidate.stop_loss
        target = trade_candidate.take_profit

        if entry is None or stop is None or target is None:
            return None

        entry_obs = full_history.observations[entry_index]
        entry_ts = getattr(entry_obs, "timestamp", "")
        if isinstance(entry_ts, pd.Timestamp):
            entry_ts = entry_ts.isoformat()

        bt = BacktestTrade(
            symbol=trade_candidate.symbol,
            timeframe=trade_candidate.timeframe,
            direction=direction,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            entry_index=entry_index,
            entry_timestamp=str(entry_ts),
            entry_reasoning=trade_candidate.rationale,
        )

        max_bars = min(
            entry_index + 200,
            len(full_history),
        )

        for j in range(entry_index + 1, max_bars):
            candle = full_history.observations[j]

            if direction == "LONG":
                if candle.low <= stop:
                    bt.exit_index = j
                    bt.exit_price = stop
                    bt.result = "LOSS"
                    bt.pnl = -(entry - stop) * (
                        trade_candidate.position_size / entry
                    ) if entry > 0 else 0.0
                    break
                if candle.high >= target:
                    bt.exit_index = j
                    bt.exit_price = target
                    bt.result = "WIN"
                    bt.pnl = (target - entry) * (
                        trade_candidate.position_size / entry
                    ) if entry > 0 else 0.0
                    break
            else:
                if candle.high >= stop:
                    bt.exit_index = j
                    bt.exit_price = stop
                    bt.result = "LOSS"
                    bt.pnl = -(stop - entry) * (
                        trade_candidate.position_size / entry
                    ) if entry > 0 else 0.0
                    break
                if candle.low <= target:
                    bt.exit_index = j
                    bt.exit_price = target
                    bt.result = "WIN"
                    bt.pnl = (entry - target) * (
                        trade_candidate.position_size / entry
                    ) if entry > 0 else 0.0
                    break

        if bt.exit_index is None:
            last = full_history.observations[-1]
            bt.exit_index = len(full_history) - 1
            bt.exit_price = last.close
            bt.result = "OPEN"
            bt.pnl = 0.0
            bt.exit_timestamp = getattr(last, "timestamp", None)
            if bt.exit_timestamp is not None and isinstance(bt.exit_timestamp, pd.Timestamp):
                bt.exit_timestamp = bt.exit_timestamp.isoformat()

        risk = abs(entry - stop)
        if risk > 0:
            bt.r_multiple = abs(bt.pnl) / (
                trade_candidate.position_size
                * (risk / entry)
            ) if entry > 0 and trade_candidate.position_size > 0 else 0.0

        if trade_candidate.position_size > 0 and entry > 0:
            bt.pnl_percent = (bt.pnl / (
                trade_candidate.position_size
            )) * 100.0

        return bt

    def _aggregate(
        self,
        trades: list[BacktestTrade],
        equity: list[float],
    ) -> BacktestResult:
        result = BacktestResult(
            symbol=trades[0].symbol if trades else "",
            timeframe=trades[0].timeframe if trades else "",
        )

        result.total_trades = len(trades)
        result.trades = trades
        result.equity_curve = equity

        wins = [t for t in trades if t.result == "WIN"]
        losses = [t for t in trades if t.result == "LOSS"]
        result.winning_trades = len(wins)
        result.losing_trades = len(losses)

        if result.total_trades > 0:
            result.win_rate = (result.winning_trades / result.total_trades) * 100.0

        total_wins = sum(t.pnl for t in wins if t.pnl is not None) or 0.0
        total_losses = abs(sum(t.pnl for t in losses if t.pnl is not None)) or 1.0
        result.total_pnl = total_wins - total_losses
        result.profit_factor = total_wins / total_losses if total_losses > 0 else 0.0

        if wins:
            result.avg_win = total_wins / len(wins)
        if losses:
            result.avg_loss = total_losses / len(losses)

        r_values = [t.r_multiple for t in trades if t.r_multiple is not None]
        if r_values:
            result.avg_r_multiple = sum(r_values) / len(r_values)

        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown = max_dd

        return result