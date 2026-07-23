"""
Telegram notifier for trade signals and alerts.

Sends messages via HTTP POST to the Telegram Bot API.
"""

from __future__ import annotations

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("TradingAI")


def send_telegram(
    message: str,
    bot_token: str,
    chat_id: str,
) -> bool:
    if not bot_token or not chat_id:
        return False

    url = (
        f"https://api.telegram.org/bot{bot_token}/sendMessage"
    )
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode()

    try:
        req = Request(url, data=payload, headers={
            "Content-Type": "application/json",
        })
        with urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except URLError as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def format_signal_alert(
    symbol: str,
    name: str,
    timeframe: str,
    direction: str,
    entry: float | None,
    stop: float | None,
    target: float | None,
    rr: float | None,
    regime: str = "",
) -> str:
    lines = [
        f"🚨 <b>NEW SIGNAL</b>",
        f"<b>{name}</b> ({symbol})",
        f"⏱ {timeframe}",
        f"📈 Direction: <b>{direction}</b>",
    ]
    if entry is not None:
        lines.append(f"💰 Entry: {entry:.2f}")
    if stop is not None:
        lines.append(f"🛑 Stop: {stop:.2f}")
    if target is not None:
        lines.append(f"🎯 Target: {target:.2f}")
    if rr is not None:
        lines.append(f"📊 R:R: {rr:.2f}")
    if regime:
        lines.append(f"📉 Regime: {regime}")
    return "\n".join(lines)


def format_stop_hit_alert(
    symbol: str,
    name: str,
    timeframe: str,
    entry: float,
    exit_price: float,
    pnl_percent: float,
) -> str:
    emoji = "🔴" if pnl_percent < 0 else "🟢"
    return (
        f"{emoji} <b>TRADE CLOSED</b>\n"
        f"<b>{name}</b> ({symbol}) @ {timeframe}\n"
        f"Entry: {entry:.2f}\n"
        f"Exit: {exit_price:.2f}\n"
        f"PnL: {pnl_percent:+.2f}%"
    )
