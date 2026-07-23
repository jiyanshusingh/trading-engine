"""
One-time importer for historical daily data from Kaggle NIFTY-50 dataset.

Usage
-----
    python -m data.downloader.kaggle_importer --csv path/to/symbol.csv

Expected CSV format (from ``rohanrao/nifty50-stock-market-data``):
    Date, Symbol, Series, Prev Close, Open, High, Low, Last, Close, ...

The importer extracts OHLCV and appends to ``data/cache/1d/{symbol}.parquet``.

Only stocks in our 30-symbol watchlist are imported.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from data.downloader.watched_symbols import SYMBOLS

_log = logging.getLogger(__name__)

_CACHE_DIR = Path("data/cache") / "1d"


def import_csv(csv_path: str) -> dict[str, int]:
    """
    Read a Kaggle NIFTY-50 CSV, extract OHLCV for matching symbols, append to cache.
    """
    raw = pd.read_csv(csv_path)
    _log.info("Read %d rows from %s", len(raw), csv_path)

    needed = set(SYMBOLS)
    stats: dict[str, int] = {}

    for symbol in sorted(needed & set(raw["Symbol"].unique())):
        chunk = raw[raw["Symbol"] == symbol].copy()
        chunk.columns = [c.strip() for c in chunk.columns]

        # Map columns to standard names
        rename = {"Date": "timestamp", "Open": "open", "High": "high",
                  "Low": "low", "Close": "close", "Volume": "volume"}
        df = chunk.rename(columns={c: rename[c] for c in chunk.columns if c in rename})
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].dropna(subset=["open"])

        if df.empty:
            continue

        # Merge with existing cache
        cache_path = _CACHE_DIR / f"{symbol}.parquet"
        if cache_path.exists():
            existing = pd.read_parquet(cache_path)
            if not existing.empty:
                df = pd.concat([existing, df], ignore_index=True)
                df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path, index=False)
        stats[symbol] = len(df)
        _log.info("  %s: %d bars → %s", symbol, len(df), cache_path)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Kaggle NIFTY-50 daily CSV")
    parser.add_argument("--csv", required=True, help="Path to Kaggle CSV file")
    args = parser.parse_args()

    if not Path(args.csv).exists():
        _log.error("File not found: %s", args.csv)
        return

    stats = import_csv(args.csv)
    _log.info("Imported %d/%d watchlist symbols", len(stats), len(SYMBOLS))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
