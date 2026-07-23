"""
Daemon configuration for continuous intraday monitoring.

Edit these values to customize which symbols to track,
which timeframes to analyze, and how to get notified.
"""

# ────────────────────────────────────────────────
# Watchlist — symbols to monitor
# Format: (ticker, display_name, data_provider)
#   ticker = yfinance symbol (e.g. "MCX.NS" for NSE, "GC=F" for COMEX)
#            or Upstox instrument key (e.g. "MCX_FO|GOLD")
#   display_name = human-readable label
#   data_provider = "yfinance" | "upstox"
# ────────────────────────────────────────────────
WATCHLIST = [
    ("MCX.NS", "MCX India", "yfinance"),
    ("GC=F", "Gold Futures", "yfinance"),
    ("SI=F", "Silver Futures", "yfinance"),
    ("MCX_FO|555922", "Gold MCX Mini", "upstox"),
    ("MCX_FO|471726", "Silver MCX Mini", "upstox"),
    ("MCX_FO|520702", "Crude Oil MCX", "upstox"),
    ("MCX_FO|562048", "Copper MCX", "upstox"),
]

# ────────────────────────────────────────────────
# Timeframe configuration (Smart Tier B)
#   enabled        : whether to scan this timeframe
#   lookback       : candles to fetch for analysis
#   run_pipeline   : run full ICT pipeline on this TF
#   monitor_stops  : check open trade stops/targets
#   update_every   : how often to scan (in seconds)
# ────────────────────────────────────────────────
TIMEFRAMES = {
    "1m": {
        "enabled": True,
        "lookback": 200,
        "run_pipeline": False,
        "monitor_stops": True,
        "update_every": 60,
    },
    "15m": {
        "enabled": True,
        "lookback": 200,
        "run_pipeline": True,
        "monitor_stops": False,
        "update_every": 900,
    },
    "1h": {
        "enabled": True,
        "lookback": 96,
        "run_pipeline": True,
        "monitor_stops": False,
        "update_every": 3600,
    },
    "1d": {
        "enabled": True,
        "lookback": 200,
        "run_pipeline": True,
        "monitor_stops": False,
        "update_every": 86400,
    },
}

# ────────────────────────────────────────────────
# Trade constructor parameters (per-timeframe overrides supported)
# ────────────────────────────────────────────────
TRADE_CONSTRUCTOR = {
    "stop_loss_multiplier": 3.0,
    "take_profit_multiplier": 4.0,
    "atr_period": 14,
    "min_risk_reward": 0.0,
}

# Per-timeframe overrides (if absent, TRADE_CONSTRUCTOR base values are used)
# Best params from ASIANPAINT.NS backtest (intraday 15m / swing 1h):
#   15m: SL=2.0x TP=3.0x ATR=14  → -12.5% PnL (least lossy)
#    1h: SL=3.0x TP=4.0x ATR=14  → +113.9% PnL, 63.5% WR, 3.08 PF
TRADE_CONSTRUCTOR_TF = {
    "15m": {"stop_loss_multiplier": 2.0, "take_profit_multiplier": 3.0, "atr_period": 14},
}

# ────────────────────────────────────────────────
# Risk management
# ────────────────────────────────────────────────
RISK = {
    "max_capital_per_trade": 25.0,
    "max_concurrent_trades": 4,
}

# ────────────────────────────────────────────────
# Telegram notification
# Set enabled=True and fill in bot_token + chat_id
# https://core.telegram.org/bots/tutorial
# ────────────────────────────────────────────────
TELEGRAM = {
    "enabled": False,
    "bot_token": "",
    "chat_id": "",
}

# ────────────────────────────────────────────────
# State persistence
# ────────────────────────────────────────────────
STATE = {
    "db_path": "data/trade_state.json",
}

# ────────────────────────────────────────────────
# Upstox API configuration
# Set enabled=True and set UPSTOX_ACCESS_TOKEN env var.
# ────────────────────────────────────────────────
import os as _os

# Load .env file if present
_env_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), ".env")
if _os.path.isfile(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _os.environ.setdefault(_k.strip(), _v.strip())

UPSTOX = {
    "enabled": True,
    "access_token": _os.environ.get("UPSTOX_ACCESS_TOKEN", ""),
}

# Map NSE ticker symbols to Upstox instrument keys
UPSTOX_NSE_KEYS = {
    "ASIANPAINT": "NSE_EQ|INE021A01026",
    "BSE": "NSE_EQ|INE118H01025",
    "OIL": "NSE_EQ|INE274J01014",
}
