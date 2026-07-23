"""One-time script: build sector mapping for all NSE EQ stocks.

Downloads the NSE master contract from Upstox CDN, then fetches sector
info from yfinance for each equity.  Caches result to data/sector_map.json.

Usage:
    .venv/bin/python scripts/build_sector_map.py
"""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_log = logging.getLogger("build_sector_map")

CDN_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
OUTPUT = Path("data/sector_map.json")


def _download_universe() -> list[dict]:
    _log.info("Downloading NSE master contract from CDN ...")
    resp = requests.get(CDN_URL, timeout=30)
    resp.raise_for_status()
    import gzip, io
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as f:
        data = json.loads(f.read().decode("utf-8"))
    eq = [s for s in data if s.get("instrument_type") == "EQ" and s.get("segment") == "NSE_EQ"]
    _log.info("Found %d NSE EQ instruments", len(eq))
    return eq


def _fetch_sector(trading_symbol: str) -> tuple[str, str, str]:
    """Return (trading_symbol, sector, industry) or (sym, None, None) on error."""
    try:
        info = yf.Ticker(f"{trading_symbol}.NS").info
        return trading_symbol, info.get("sector"), info.get("industry")
    except Exception:
        return trading_symbol, None, None


def main():
    universe = _download_universe()
    symbols = [s["trading_symbol"] for s in universe]

    results: dict[str, dict] = {}
    done = 0

    _log.info("Fetching sector info for %d stocks (this takes ~2-3 min) ...", len(symbols))
    with ThreadPoolExecutor(max_workers=12) as pool:
        fut_map = {pool.submit(_fetch_sector, sym): sym for sym in symbols}
        for fut in as_completed(fut_map):
            sym, sector, industry = fut.result()
            results[sym] = {"sector": sector, "industry": industry}
            done += 1
            if done % 200 == 0:
                _log.info("  %d / %d done ...", done, len(symbols))

    # Summarise coverage
    with_sector = sum(1 for v in results.values() if v["sector"])
    _log.info("Done. %d / %d have sector info.", with_sector, len(results))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2))
    _log.info("Saved to %s", OUTPUT)

    # Unique sectors
    sectors = sorted({v["sector"] for v in results.values() if v["sector"]})
    _log.info("Unique sectors found: %s", sectors)


if __name__ == "__main__":
    main()
