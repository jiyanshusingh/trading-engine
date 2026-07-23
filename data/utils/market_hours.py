"""NSE market hours and holiday calendar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as _timezone
import zoneinfo
_NSE_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

# NSE market hours
_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)

# Major NSE holidays for the current year (2026).
_HOLIDAYS: set[tuple[int, int, int]] = {
    (2026, 1, 26),   # Republic Day
    (2026, 3, 1),    # Mahashivaratri
    (2026, 3, 31),   # Id-ul-fitr
    (2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    (2026, 4, 17),   # Good Friday
    (2026, 5, 1),    # Maharashtra Day
    (2026, 8, 15),   # Independence Day
    (2026, 8, 27),   # Ganesh Chaturthi
    (2026, 10, 2),   # Mahatma Gandhi Jayanti
    (2026, 10, 22),  # Dussehra
    (2026, 11, 9),   # Diwali Balipratipada
    (2026, 11, 12),  # Gurunanak Jayanti
    (2026, 12, 25),  # Christmas
}


def _ist_now() -> datetime:
    return datetime.now(_timezone.utc).astimezone(_NSE_TZ)


def is_market_open(dt: datetime | None = None) -> tuple[bool, str, timedelta]:
    """Check if NSE market is open at the given datetime (default: now).

    Returns
    -------
    (is_open: bool, reason: str, remaining: timedelta)
    """
    if dt is None:
        dt = _ist_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_timezone.utc).astimezone(_NSE_TZ)
    else:
        dt = dt.astimezone(_NSE_TZ)

    ist_date = dt.date()

    # Weekend
    if ist_date.weekday() >= 5:
        remaining = timedelta(0)
        next_mon = ist_date + timedelta(days=(7 - ist_date.weekday()))
        reason = f"Weekend — next trading day: {next_mon}"
        return False, reason, remaining

    # Holiday
    hkey = (ist_date.year, ist_date.month, ist_date.day)
    if hkey in _HOLIDAYS:
        remaining = timedelta(0)
        reason = f"NSE holiday ({ist_date})"
        return False, reason, remaining

    # Time check
    dt_time = dt.time()
    if dt_time < _MARKET_OPEN:
        remaining = timedelta(0)
        delta = (_MARKET_OPEN.hour * 3600 + _MARKET_OPEN.minute * 60) - (dt_time.hour * 3600 + dt_time.minute * 60)
        reason = f"Market opens at 09:15 IST ({_fmt_delta(delta)} remaining)"
        return False, reason, timedelta(seconds=delta)

    if dt_time >= _MARKET_CLOSE:
        remaining = timedelta(0)
        reason = f"Market closed at 15:30 IST"
        return False, reason, remaining

    # Market is open
    open_secs = dt_time.hour * 3600 + dt_time.minute * 60 + dt_time.second
    close_secs = _MARKET_CLOSE.hour * 3600 + _MARKET_CLOSE.minute * 60
    remaining_secs = max(0, close_secs - open_secs)
    remaining = timedelta(seconds=remaining_secs)
    reason = f"Market open — {_fmt_delta(remaining_secs)} remaining ({dt_time.strftime('%H:%M')} IST)"
    return True, reason, remaining


def _fmt_delta(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def next_market_open(from_dt: datetime | None = None) -> datetime:
    """Return the datetime of the next market open."""
    if from_dt is None:
        from_dt = _ist_now()

    cand = from_dt
    for _ in range(14):
        cand_date = cand.date()
        if cand_date.weekday() < 5 and (cand_date.year, cand_date.month, cand_date.day) not in _HOLIDAYS:
            open_dt = datetime(cand_date.year, cand_date.month, cand_date.day,
                               _MARKET_OPEN.hour, _MARKET_OPEN.minute, tzinfo=cand.tzinfo or _NSE_TZ)
            if cand <= open_dt:
                return open_dt
            # Try next day
        cand = cand + timedelta(days=1)
    return from_dt  # fallback
