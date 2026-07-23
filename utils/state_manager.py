"""
JSON-based state persistence for the monitoring daemon.

Tracks last-known signals and open trades per symbol+timeframe
so we only alert on NEW signals (avoid duplicates).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("TradingAI")

DEFAULT_STATE = {
    "signals": {},
    "open_trades": {},
    "last_run": None,
}


class StateManager:
    def __init__(self, path: str):
        self._path = Path(path)
        self._state = self._load()

    # ──────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────

    def _load(self) -> dict:
        if not self._path.exists():
            return dict(DEFAULT_STATE)
        try:
            with open(self._path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load state, resetting: {e}")
            return dict(DEFAULT_STATE)

    def _save(self):
        self._state["last_run"] = datetime.now().isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._state, f, indent=2)

    # ──────────────────────────────────────────
    # Signal tracking
    # ──────────────────────────────────────────

    def signal_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}_{timeframe}"

    def get_last_signal(
        self,
        symbol: str,
        timeframe: str,
    ) -> dict[str, Any] | None:
        key = self.signal_key(symbol, timeframe)
        return self._state["signals"].get(key)

    def update_signal(
        self,
        symbol: str,
        timeframe: str,
        signal: dict[str, Any],
    ) -> bool:
        """
        Returns True if the signal is NEW (different from last known).
        """
        last = self.get_last_signal(symbol, timeframe)
        key = self.signal_key(symbol, timeframe)
        self._state["signals"][key] = signal
        self._save()
        return last != signal

    # ──────────────────────────────────────────
    # Open trade tracking
    # ──────────────────────────────────────────

    def get_open_trade(
        self,
        symbol: str,
        timeframe: str,
    ) -> dict[str, Any] | None:
        key = self.signal_key(symbol, timeframe)
        return self._state["open_trades"].get(key)

    def open_trade(
        self,
        symbol: str,
        timeframe: str,
        trade: dict[str, Any],
    ):
        key = self.signal_key(symbol, timeframe)
        self._state["open_trades"][key] = trade
        self._save()

    def close_trade(self, symbol: str, timeframe: str):
        key = self.signal_key(symbol, timeframe)
        self._state["open_trades"].pop(key, None)
        self._save()

    # ──────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────

    def summary(self) -> str:
        signals = self._state["signals"]
        trades = self._state["open_trades"]
        lines = [
            f"Signals tracked: {len(signals)}",
            f"Open trades: {len(trades)}",
        ]
        for key, trade in trades.items():
            lines.append(
                f"  {key}: {trade.get('direction', '?')} "
                f"entry={trade.get('entry', 0):.2f}"
            )
        return "\n".join(lines)
