"""
Build F&O instrument master — futures and options contracts for NSE indices.

Sources:
  1. Upstox instrument master JSON (complete.json.gz) — the source of truth for
     NSE_FO segment contracts: instrument keys, expiry, strike, lot sizes.
  2. NSE expiry schedule (derived from contract data).

Output: data/fno_instruments.json
  {
    "generated_at": "...",
    "underlyings": {
      "NIFTY": {
        "futures": [
          {"instrument_key": "NSE_FO|...", "trading_symbol": "...",
           "expiry": "2026-07-28", "lot_size": 65, "tick_size": 10.0}
        ],
        "options": {
          "lot_size": 65, "tick_size": 5.0,
          "expiries": {"2026-07-28": {"weekly": true, "monthly": true}, ...},
          "contracts": [
            {"instrument_key": "...", "expiry": "...",
             "strike": 24500.0, "option_type": "CE", ...}
          ]
        },
        "lot_size": 65, "contract_multiplier": 65,
        "margin_nrml": 159250.0, "margin_mis": 79625.0
      },
      "BANKNIFTY": {...},
      "FINNIFTY": {...}
    },
    "active_futures": {
      "NIFTY": {"instrument_key": "...", "expiry": "..."}
    }
  }

Usage:
    .venv/bin/python scripts/build_fno_master.py
    .venv/bin/python scripts/build_fno_master.py --indices NIFTY BANKNIFTY
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_log = logging.getLogger("build_fno_master")

_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
_OUT_PATH = Path("data/fno_instruments.json")
_KEYS_CACHE = Path("data/cache/metadata/instrument_keys.json")

# All index underlyings available in NSE_FO
ALL_INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]

# Estimated margin % of contract value (conservative)
# NRML = SPAN + Exposure margin; MIS = SPAN only (no exposure)
_NRML_MARGIN_PCT = 0.10   # 10% of notional
_MIS_MARGIN_PCT = 0.05    # 5% of notional (intraday, approx)

# Approximate spot prices for notional calculation (will be refined from data)
_SPOT_ESTIMATES = {"NIFTY": 24500, "BANKNIFTY": 52000, "FINNIFTY": 23000, "MIDCPNIFTY": 50000}


def _fetch_master() -> list[dict]:
    _log.info("Downloading Upstox instrument master …")
    r = requests.get(_MASTER_URL, timeout=90)
    r.raise_for_status()
    data = json.load(gzip.GzipFile(fileobj=io.BytesIO(r.content)))
    _log.info("  %d total instruments", len(data))
    return data


def _build_index_master(master: list[dict], indices: list[str]) -> dict:
    """Build the F&O master for the requested index underlyings."""
    now_ms = datetime.now().timestamp() * 1000
    out: dict = {}

    for idx in indices:
        idx_data: dict = {}

        # ── Futures ──
        futs = [
            d for d in master
            if d.get("segment") == "NSE_FO"
            and d.get("underlying_symbol") == idx
            and d.get("instrument_type") == "FUT"
        ]
        future_contracts = []
        for f in futs:
            exp_dt = datetime.fromtimestamp(
                int(f["expiry"]) / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d")
            future_contracts.append({
                "instrument_key": f["instrument_key"],
                "trading_symbol": f.get("trading_symbol", ""),
                "expiry": exp_dt,
                "expiry_ts": int(f["expiry"]),
                "lot_size": int(f.get("lot_size", 0)),
                "tick_size": float(f.get("tick_size", 0)),
            })

        future_contracts.sort(key=lambda x: x["expiry_ts"])
        lot_size = future_contracts[0]["lot_size"] if future_contracts else 0

        # Nearest active futures contract (by expiry, prefer closest)
        active_idx = None
        for i, c in enumerate(future_contracts):
            if c["expiry_ts"] >= now_ms - 7 * 86400 * 1000:  # within a week of expiry
                if active_idx is None:
                    active_idx = i
                elif c["expiry_ts"] < future_contracts[active_idx]["expiry_ts"]:
                    active_idx = i
        if active_idx is None and future_contracts:
            active_idx = 0  # fallback to nearest

        idx_data["futures"] = {
            "contracts": future_contracts,
            "lot_size": lot_size,
            "contract_multiplier": lot_size,
            "tick_size": float(future_contracts[0].get("tick_size", 0)) if future_contracts else 0,
        }
        if active_idx is not None and future_contracts:
            idx_data["futures"]["active"] = future_contracts[active_idx]["instrument_key"]
            idx_data["futures"]["active_expiry"] = future_contracts[active_idx]["expiry"]
        else:
            idx_data["futures"]["active"] = None
            idx_data["futures"]["active_expiry"] = None

        # ── Options ──
        opts = [
            d for d in master
            if d.get("segment") == "NSE_FO"
            and d.get("underlying_symbol") == idx
            and d.get("instrument_type") in ("CE", "PE")
        ]
        opt_expiries: dict = {}
        opt_contracts = []
        for o in opts:
            exp_dt = datetime.fromtimestamp(
                int(o["expiry"]) / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d")

            if exp_dt not in opt_expiries:
                opt_expiries[exp_dt] = {
                    "expiry_ts": int(o["expiry"]),
                    "monthly": False,
                }
            opt_contracts.append({
                "instrument_key": o["instrument_key"],
                "trading_symbol": o.get("trading_symbol", ""),
                "expiry": exp_dt,
                "expiry_ts": int(o["expiry"]),
                "strike_price": float(o.get("strike_price", 0)),
                "option_type": o.get("instrument_type", ""),
                "lot_size": int(o.get("lot_size", 0)),
                "tick_size": float(o.get("tick_size", 0)),
            })

        # Mark monthly expiries: the last Tuesday of each month that has options
        monthly_expiries = _monthly_expiry_dates(opt_expiries)
        for exp, info in opt_expiries.items():
            if exp in monthly_expiries:
                info["monthly"] = True

        opt_lot = opt_contracts[0]["lot_size"] if opt_contracts else 0
        idx_data["options"] = {
            "contracts": opt_contracts,
            "expiries": {e: v for e, v in sorted(opt_expiries.items())},
            "lot_size": opt_lot,
            "tick_size": float(opt_contracts[0]["tick_size"]) if opt_contracts else 0,
        }

        # ── Margin estimates ──
        spot = _SPOT_ESTIMATES.get(idx, 25000)
        if lot_size:
            notional = float(spot) * lot_size
            idx_data["margin_nrml"] = round(notional * _NRML_MARGIN_PCT, 2)
            idx_data["margin_mis"] = round(notional * _MIS_MARGIN_PCT, 2)
        else:
            idx_data["margin_nrml"] = 0
            idx_data["margin_mis"] = 0

        out[idx] = idx_data
        _log.info("  %s: %d futures, %d options, lot=%d, margin NRML=₹%.0f MIS=₹%.0f",
                  idx, len(future_contracts), len(opt_contracts), lot_size,
                  idx_data["margin_nrml"], idx_data["margin_mis"])

    return out


def _monthly_expiry_dates(expiries: dict) -> set:
    """Identify monthly expiry dates from the list of available option expiries.
    
    Monthly expiry = the last Tuesday of each month (NSE convention for index
    derivatives). Among the available expiries, the last Tuesday of a month
    that has the greatest number of strikes is marked as monthly.
    """
    from collections import defaultdict
    by_month = defaultdict(list)
    for exp, info in expiries.items():
        dt = datetime.strptime(exp, "%Y-%m-%d")
        key = (dt.year, dt.month)
        by_month[key].append(exp)

    monthly = set()
    for key, dates in by_month.items():
        if not dates:
            continue
        # The last available expiry of each month is the monthly expiry
        dates.sort()
        monthly.add(dates[-1])
    return monthly


def _make_active_futures(underlyings: dict) -> dict:
    """Return {underlying: active_futures_info} for each index."""
    active: dict = {}
    for idx, data in underlyings.items():
        futures = data.get("futures", {})
        if futures.get("active"):
            active[idx] = {
                "instrument_key": futures["active"],
                "expiry": futures["active_expiry"],
                "lot_size": futures["lot_size"],
                "tick_size": futures["tick_size"],
                "contract_multiplier": futures["contract_multiplier"],
            }
    return active


def main() -> None:
    ap = argparse.ArgumentParser(description="Build F&O instrument master (NSE index futures + options)")
    ap.add_argument("--indices", nargs="*", default=ALL_INDICES,
                    help=f"Index underlyings (default: all: {', '.join(ALL_INDICES)})")
    args = ap.parse_args()

    indices = [i.upper() for i in args.indices]
    for i in indices:
        if i not in ALL_INDICES:
            _log.error("Unknown index %s (valid: %s)", i, ", ".join(ALL_INDICES))
            sys.exit(1)

    master = _fetch_master()
    underlyings = _build_index_master(master, indices)

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "underlyings": underlyings,
        "active_futures": _make_active_futures(underlyings),
        "total_underlyings": len(indices),
    }

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUT_PATH.write_text(json.dumps(out, indent=2))
    _log.info("Wrote %s: %d underlyings", _OUT_PATH, len(indices))

    # Merge F&O keys into the shared instrument key cache so data fetchers
    # (refresh_data_cache.py, download_history.py) can resolve them.
    all_keys: dict = {}
    for idx, data in underlyings.items():
        for c in data.get("futures", {}).get("contracts", []):
            all_keys[c["trading_symbol"]] = c["instrument_key"]
            all_keys[f"{idx}_FUT"] = c["instrument_key"]
        for c in data.get("options", {}).get("contracts", []):
            all_keys[c["trading_symbol"]] = c["instrument_key"]
    try:
        cache = json.loads(_KEYS_CACHE.read_text()) if _KEYS_CACHE.exists() else {}
        cache.update(all_keys)
        _KEYS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _KEYS_CACHE.write_text(json.dumps(cache, indent=2))
        _log.info("Updated Upstox key cache: %d keys (+%d F&O)",
                  len(cache), len(all_keys))
    except Exception as e:
        _log.warning("Could not update key cache: %s", e)


if __name__ == "__main__":
    main()
