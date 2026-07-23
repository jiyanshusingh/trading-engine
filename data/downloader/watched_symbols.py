"""
Master symbol list — 30 NSE stocks for intraday scanning & data cache.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

_log = logging.getLogger(__name__)

# ── 30-Stock Watchlist ──────────────────────────────────────────────
# NSE trading symbols (no .NS suffix — yfinance convention is applied
# on the fly, Upstox keys are resolved once and cached).

SYMBOLS: Final[list[str]] = [
    "HINDUNILVR",
    "MARUTI",
    "ADANIENT",
    "NESTLEIND",
    "TATACONSUM",
    "EICHERMOT",
    "CIPLA",
    "ICICIBANK",
    "OIL",
    "ABB",
    "TORNTPHARM",
    "TECHM",
    "WIPRO",
    "INFY",
    "ONGC",
    "BHARTIARTL",
    "BSE",
    "PIDILITIND",
    "HDFCBANK",
    "ICICIPRULI",
    "ITC",
    "BEL",
    "DIVISLAB",
    "COALINDIA",
    "TCS",
    "RELIANCE",
    "SBIN",
    "LT",
    "AXISBANK",
    "KOTAKBANK",
]

# PHYSICSWALLAH (delisted) → NESTLEIND replacement
# +5 added: RELIANCE, SBIN, LT, AXISBANK, KOTAKBANK

YF_SUFFIX = ".NS"

_KEYS_PATH = Path("data/cache/metadata/instrument_keys.json")


# ── Upstox key cache ───────────────────────────────────────────────

def load_key_cache() -> dict[str, str]:
    """Return ``{trading_symbol: instrument_key}`` from local cache."""
    if _KEYS_PATH.exists():
        return json.loads(_KEYS_PATH.read_text())
    return {}


def save_key_cache(keys: dict[str, str]) -> None:
    _KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KEYS_PATH.write_text(json.dumps(keys, indent=2))


def resolve_symbols(force: bool = False) -> dict[str, str]:
    """
    Resolve all 30 symbols to Upstox instrument keys.

    Uses cached keys unless ``force=True``.
    Returns ``{trading_symbol: instrument_key}``.
    """
    cache = {} if force else load_key_cache()
    missing = [s for s in SYMBOLS if s not in cache]
    if not missing:
        return cache

    from scripts.backtest import search_upstox_instrument
    for sym in missing:
        key = search_upstox_instrument(sym)
        if key:
            cache[sym] = key
            _log.info("Resolved %s → %s", sym, key)
        else:
            _log.warning("Could not resolve %s", sym)

    save_key_cache(cache)
    return cache


def key_for(symbol: str) -> str | None:
    """Get cached instrument key for an NSE trading symbol."""
    return load_key_cache().get(symbol)


# ── Phase 5: expanded candidate universe (Nifty-100 style) ──
# Curated liquid NSE names beyond the core 30, used to widen the pool from
# which the expectancy whitelist cherry-picks. Validated/downloaded via
# scripts/download_history.py --symbols before being promoted to SYMBOLS.
EXPANSION_CANDIDATES: Final[list[str]] = [
    # already in core 30 (kept for reference / dedup)
    # — additional liquid large/mid caps —
    "TATAMOTORS", "TATASTEEL", "SUNPHARMA", "TITAN", "BAJFINANCE",
    "BAJAJFINSV", "BAJAJ-AUTO", "HEROMOTOCO", "M&M", "MCDOWELL-N",
    "ULTRACEMCO", "GRASIM", "SHREECEM", "CEMENT", "JSWSTEEL",
    "TATAELXSI", "INDUSINDBK", "PFC", "RECLTD", "POWERGRID",
    "NTPC", "NHPC", "GAIL", "ONGC", "IOC",
    "BPCL", "VEDL", "HINDALCO", "NATIONALUM", "JINDALSTEL",
    "ASHOKLEY", "MOTHERSON", "BOSCHLTD", "MRF", "EICHERMOT",
    "ZYDUSLIFE", "LUPIN", "DRREDDY", "AUROPHARMA", "ALKEM",
    "APOLLOHOSP", "MAXHEALTH", "FORTIS", "METROPOLIS", "LAURUSLABS",
    "INFOEDGE", "NAUKRI", "PERSISTENT", "MPHASIS", "LTIM",
    "LTTS", "COFORGE", "OFSS", "WIPRO", "HCLTECH",
    "CANBK", "PNB", "BANKBARODA", "UNIONBANK", "FEDERALBNK",
    "IDFCFIRSTB", "RBLBANK", "INDUSINDBK", "YESBANK", "JIOFIN",
    "ADANIPORTS", "ADANIENT", "ADANIGREEN", "ADANIPOWER", "ADANITRANS",
    "TRENT", "DMART", "NYKAA", "PAYTM", "ZOMATO",
    "POLICYBZR", "IRCTC", "IRFC", "RVNL", "TITAGARH",
    "HAL", "BEL", "MAZDOCK", "COCHINSHIP", "CUMMINSIND",
    "SIEMENS", "ABB", "SCHNEIDER", "HAVELLS", "VOLTAS",
    "DIXON", "AMBUJACEM", "ACC", "JINDALSTEEL", "SAIL",
    # ── User-requested additions (Jul 2026) ──
    "360ONE", "AFFLE", "APTUS", "BALRAMCHIN", "BDL", "BHEL",
    "BIOCON", "BSOFT", "CANHLIFE", "CGCL", "CUB", "CYIENT",
    "ENRIN", "GALLANTT", "GVT&D", "HEG", "HEXT", "HOMEFIRST",
    "ICICIAMC", "ICICIGI", "INDIANB", "INTELLECT", "IPCALAB",
    "J&KBANK", "JSWINFRA", "KALYANKJIL", "KPITTECH", "LATENTVIEW",
    "LTM", "M&MFIN", "MAHABANK", "MANAPPURAM", "MAPMYINDIA",
    "MUTHOOTFIN", "NEWGEN", "NLCINDIA", "NUVAMA", "PCBL",
    "PINELABS", "PPLPHARMA", "PWL", "RRKABEL", "SAPPHIRE",
    "SAREGAMA", "SHYAMMETL", "SONATSOFTW", "SUMICHEM", "TATATECH",
    "THERMAX", "TRAVELFOOD", "TRITURBINE", "UTIAMC", "VBL",
    "WELSPUNLIV", "ZENSARTECH", "ZENTEC",
    # ── Batch 3: user-requested (Jul 2026) ──
    "CPPLUS", "ATHERENERG", "ACUTAAS", "KIRLOSENG", "HFCL", "NETWEB", "SYRMA",
    "GROWW", "IDEA", "BELRISE", "CEMPRO", "AEGISLOG", "GODREJIND", "LODHA",
    "AEGISVOPAK", "WELCORP", "SIGNATURE",
]


def expansion_universe() -> list[str]:
    """Core 30 + de-duplicated expansion candidates (trading symbols)."""
    seen: set[str] = set()
    out: list[str] = []
    for s in list(SYMBOLS) + list(EXPANSION_CANDIDATES):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

