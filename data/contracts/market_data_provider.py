"""
Market Data Provider Contract

Version 1.0

Defines the interface for supplying historical or live
market data to the trading engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class MarketDataProvider(ABC):
    """
    Abstract Market Data Provider.
    """

    # ==========================================================
    # Metadata
    # ==========================================================

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""
        ...

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """
        Provider type.

        Examples
        --------
        CSV
        API
        LIVE
        DATABASE
        WEBSOCKET
        """
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Provider version."""
        ...

    # ==========================================================
    # Historical Data
    # ==========================================================

    @abstractmethod
    def load_historical_data(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        start_date=None,
        end_date=None,
    ) -> pd.DataFrame:
        """
        Load historical OHLCV data.

        Returns
        -------
        pandas.DataFrame

        Required columns
        ----------------
        timestamp
        open
        high
        low
        close
        volume
        """
        ...

    # ==========================================================
    # Latest Data
    # ==========================================================

    @abstractmethod
    def load_latest_data(
        self,
        symbol: str,
        timeframe: str,
        lookback: int = 500,
    ) -> pd.DataFrame:
        """
        Load the most recent candles.
        """
        ...