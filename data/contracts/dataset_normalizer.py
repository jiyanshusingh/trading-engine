"""
Dataset Normalizer Contract

A DatasetNormalizer converts vendor-specific datasets
(Kaggle, Zerodha, Upstox, NSE, etc.) into the canonical
Institutional Trading AI market data format.

Canonical Schema
----------------
timestamp
open
high
low
close
volume
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd


class DatasetNormalizer(ABC):
    """
    Abstract base class for dataset normalizers.
    """

    CANONICAL_COLUMNS = (
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )

    # ==========================================================
    # Metadata
    # ==========================================================

    @property
    @abstractmethod
    def normalizer_name(self) -> str:
        """
        Human-readable normalizer name.
        """
        ...

    @property
    @abstractmethod
    def vendor(self) -> str:
        """
        Data vendor.

        Examples
        --------
        Kaggle
        Zerodha
        Upstox
        NSE
        """
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """
        Normalizer version.
        """
        ...

    # ==========================================================
    # API
    # ==========================================================

    @abstractmethod
    def normalize(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> pd.DataFrame:
        """
        Normalize a vendor dataset into the canonical schema.

        Parameters
        ----------
        input_path
            Vendor dataset.

        output_path
            Destination of the normalized CSV.

        Returns
        -------
        pandas.DataFrame

        Canonical DataFrame.
        """
        ...

    # ==========================================================
    # Validation Helper
    # ==========================================================

    def validate(
        self,
        df: pd.DataFrame,
    ) -> None:
        """
        Validate canonical schema.
        """

        missing = [
            column
            for column in self.CANONICAL_COLUMNS
            if column not in df.columns
        ]

        if missing:
            raise ValueError(
                "Missing canonical columns: "
                + ", ".join(missing)
            )

        if df.empty:
            raise ValueError(
                "Normalized dataset cannot be empty."
            )