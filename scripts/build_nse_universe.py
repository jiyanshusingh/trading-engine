"""
Build the NSE trading universe = NIFTY 500 + F&O stocks, minus illiquid/penny
names — Phase 35.

Sources (all authoritative, no scraping of anti-bot HTML):
  1. Upstox instrument master (complete.json.gz) — the source of truth for
     Upstox instrument keys + the set of real NSE equities (segment NSE_EQ,
     instrument_type EQ). Also yields the F&O underlyings (segment NSE_FO →
     distinct underlying_symbol / underlying_key).
  2. NIFTY 500 constituent CSV from niftyindices.com (symbol + ISIN).

Penny/illiquid filter: fetch ~40 recent daily bars per symbol from Upstox V3
and drop any whose average daily turnover (close×volume) is below a floor
(default ₹1 crore) or whose average volume is negligible.

Output: data/nse_universe.json
  {
    "generated_at": ..., "total": N, "nse500": N, "fno": N,
    "dropped_penny": N, "dropped_unresolved": N,
    "symbols": ["RELIANCE", ...],
    "keys": {"RELIANCE": "NSE_EQ|INE002A01018", ...}
  }

Usage
-----
    .venv/bin/python scripts/build_nse_universe.py
    .venv/bin/python scripts/build_nse_universe.py --min-turnover-cr 2
    .venv/bin/python scripts/build_nse_universe.py --no-volume-filter   # fast, skip liquidity check
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, ".")

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_log = logging.getLogger("build_nse_universe")

_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
_NIFTY500_URL = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_OUT_PATH = Path("data/nse_universe.json")
_KEYS_CACHE = Path("data/cache/metadata/instrument_keys.json")

# Index underlyings in NSE_FO that are NOT tradable equities — exclude.
_INDEX_UNDERLYINGS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
    "NIFTYIT", "NIFTYINFRA", "NIFTYPSE", "BANKEX", "SENSEX", "SENSEX50",
}


def _fetch_upstox_master() -> list[dict]:
    _log.info("Downloading Upstox instrument master …")
    r = requests.get(_MASTER_URL, timeout=90)
    r.raise_for_status()
    data = json.load(gzip.GzipFile(fileobj=io.BytesIO(r.content)))
    _log.info("  %d instruments", len(data))
    return data


def _fetch_nifty500() -> list[dict]:
    _log.info("Downloading NIFTY 500 constituent list …")
    r = requests.get(_NIFTY500_URL, headers={"User-Agent": _UA}, timeout=30)
    r.raise_for_status()
    rows = list(pd.read_csv(io.StringIO(r.text)).to_dict("records"))
    _log.info("  %d constituents", len(rows))
    return rows


def _build_symbol_maps(master: list[dict]) -> tuple[dict, dict]:
    """Return (isin->key, trading_symbol->(key,symbol)) for real NSE equities."""
    by_isin: dict[str, tuple[str, str]] = {}
    by_symbol: dict[str, str] = {}
    for d in master:
        if d.get("segment") != "NSE_EQ" or d.get("instrument_type") != "EQ":
            continue
        key = d.get("instrument_key")
        sym = d.get("trading_symbol")
        isin = d.get("isin")
        if not key or not sym:
            continue
        by_symbol[sym] = key
        if isin:
            by_isin[isin] = (key, sym)
    return by_isin, by_symbol


def _fno_underlyings(master: list[dict]) -> dict[str, str]:
    """Return {underlying_symbol: underlying_key} for NSE_FO stock derivatives."""
    out: dict[str, str] = {}
    for d in master:
        if d.get("segment") != "NSE_FO":
            continue
        sym = d.get("underlying_symbol")
        key = d.get("underlying_key")
        if not sym or not key or sym in _INDEX_UNDERLYINGS:
            continue
        if not key.startswith("NSE_EQ|"):
            continue
        out[sym] = key
    return out


def _avg_turnover_cr(provider, key: str) -> tuple[float, float]:
    """Return (avg_daily_turnover_in_crore, avg_daily_volume) over ~40 days."""
    try:
        end = datetime.now()
        df = provider.load_historical_v3(key, "1d", end - timedelta(days=45), end)
        if df is None or df.empty:
            return 0.0, 0.0
        df = df.tail(30)
        turnover = (df["close"] * df["volume"]).mean()
        return float(turnover) / 1e7, float(df["volume"].mean())
    except Exception as e:
        _log.debug("  turnover fetch failed for %s: %s", key, e)
        return -1.0, -1.0  # sentinel: fetch error (keep, don't penalise)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build NSE 500 + F&O trading universe")
    ap.add_argument("--min-turnover-cr", type=float, default=1.0,
                    help="Drop symbols with avg daily turnover below this (₹ crore). Default 1.")
    ap.add_argument("--min-volume", type=float, default=0,
                    help="Also drop symbols with avg daily volume below this. Default 0 "
                         "(disabled — turnover in ₹ is the correct liquidity metric; an "
                         "absolute share floor wrongly drops high-priced liquid names like MRF).")
    ap.add_argument("--no-volume-filter", action="store_true",
                    help="Skip the liquidity/penny filter (fast).")
    args = ap.parse_args()

    master = _fetch_upstox_master()
    by_isin, by_symbol = _build_symbol_maps(master)
    _log.info("Real NSE equities in master: %d (by ISIN %d)", len(by_symbol), len(by_isin))

    # ── NIFTY 500 ──
    n500 = _fetch_nifty500()
    resolved: dict[str, str] = {}   # symbol -> key
    src_nse500, src_fno = set(), set()
    unresolved = []
    for row in n500:
        sym = str(row.get("Symbol", "")).strip()
        isin = str(row.get("ISIN Code", "")).strip()
        if not sym:
            continue
        key = None
        if isin and isin in by_isin:
            key = by_isin[isin][0]
        elif sym in by_symbol:
            key = by_symbol[sym]
        elif isin:
            key = f"NSE_EQ|{isin}"  # construct from ISIN (Upstox key format)
        if key:
            resolved[sym] = key
            src_nse500.add(sym)
        else:
            unresolved.append(sym)

    # ── F&O ──
    fno = _fno_underlyings(master)
    for sym, key in fno.items():
        if sym not in resolved:
            resolved[sym] = key
        src_fno.add(sym)

    _log.info("Merged universe (pre-filter): %d  (NSE500 %d, F&O %d, overlap %d)",
              len(resolved), len(src_nse500), len(src_fno),
              len(src_nse500 & src_fno))
    if unresolved:
        _log.warning("Unresolved NSE500 symbols (%d): %s",
                     len(unresolved), ", ".join(unresolved[:20]))

    # ── Penny / illiquid filter ──
    dropped_penny = []
    if not args.no_volume_filter:
        from config.daemon_config import UPSTOX
        from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider
        provider = UpstoxMarketDataProvider(UPSTOX["access_token"])
        _log.info("Liquidity filter: min turnover ₹%.1f cr, min vol %d …",
                  args.min_turnover_cr, args.min_volume)
        kept = {}
        items = list(resolved.items())
        for i, (sym, key) in enumerate(items):
            cr, vol = _avg_turnover_cr(provider, key)
            if cr == -1.0:  # fetch error — keep (fail-open, F&O/500 are liquid anyway)
                kept[sym] = key
            elif cr < args.min_turnover_cr or (args.min_volume and vol < args.min_volume):
                dropped_penny.append((sym, round(cr, 2), int(vol)))
            else:
                kept[sym] = key
            if (i + 1) % 50 == 0:
                _log.info("  …%d/%d checked, %d kept, %d dropped",
                          i + 1, len(items), len(kept), len(dropped_penny))
            time.sleep(0.05)
        resolved = kept
        if dropped_penny:
            _log.info("Dropped %d penny/illiquid: %s", len(dropped_penny),
                      ", ".join(f"{s}({c}cr)" for s, c, v in dropped_penny[:25]))

    symbols = sorted(resolved.keys())
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(symbols),
        "nse500": len(src_nse500),
        "fno": len(src_fno),
        "overlap": len(src_nse500 & src_fno),
        "dropped_penny": len(dropped_penny),
        "dropped_unresolved": len(unresolved),
        "min_turnover_cr": args.min_turnover_cr,
        "min_volume": args.min_volume,
        "symbols": symbols,
        "keys": {s: resolved[s] for s in symbols},
        "penny_detail": [{"symbol": s, "turnover_cr": c, "avg_vol": v} for s, c, v in dropped_penny],
    }
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUT_PATH.write_text(json.dumps(out, indent=2))
    _log.info("Wrote %s: %d symbols (NSE500 %d + F&O %d, dropped %d penny / %d unresolved)",
              _OUT_PATH, len(symbols), len(src_nse500), len(src_fno),
              len(dropped_penny), len(unresolved))

    # Merge new keys into the shared Upstox key cache (so download_history etc. reuse them).
    try:
        cache = json.loads(_KEYS_CACHE.read_text()) if _KEYS_CACHE.exists() else {}
        cache.update(resolved)
        _KEYS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _KEYS_CACHE.write_text(json.dumps(cache, indent=2))
        _log.info("Updated Upstox key cache: %d keys", len(cache))
    except Exception as e:
        _log.warning("Could not update key cache: %s", e)


if __name__ == "__main__":
    main()
