from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from data.contracts.market_data_provider import MarketDataProvider


_UPSTOX_BASE = "https://api.upstox.com/v2"


class _V3RateLimiter:
    """Thread-safe limiter for Upstox 'Other Standard APIs' historical limits:
    50/sec, 500/min, 2000/30min. The 30-min cap (~1.11 req/s sustained) is the
    binding one, so we PACE requests EVENLY at a fixed interval rather than
    allowing a burst up to the cap and then freezing for ~20 min while that
    burst ages out of the 30-min window (which looked like a hang). Each caller
    reserves the next evenly-spaced slot under the lock, then sleeps until it —
    giving smooth, observable progress and never tripping a 429.

    A steady interval of 1800/1900 ≈ 0.947s ⇒ ~1.056 req/s ⇒ ~1901 per 30 min
    (safely under 2000), ~63/min (under 500), and well under 50/s."""

    def __init__(self, min_interval: float = 1800.0 / 1900.0):
        self._lock = threading.Lock()
        self._min_interval = min_interval
        self._next_slot = 0.0  # monotonic time of the next free request slot

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            target = max(now, self._next_slot)
            self._next_slot = target + self._min_interval
        delay = target - now
        if delay > 0:
            time.sleep(delay)


_V3_LIMITER = _V3RateLimiter()


class UpstoxMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        access_token: str,
        cache_dir: str | Path | None = None,
    ):
        self._access_token = access_token
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._session = None

    @property
    def provider_name(self) -> str:
        return "UpstoxMarketDataProvider"

    @property
    def provider_type(self) -> str:
        return "API"

    @property
    def version(self) -> str:
        return "1.0"

    # ── Session ──────────────────────────────────────────────────

    def _get_session(self):
        # requests.Session is NOT thread-safe — a single shared Session across
        # backfill worker threads deadlocks urllib3's connection pool (threads
        # block on pool acquisition, 0% CPU, socket timeout never fires). Give
        # each thread its OWN Session (thread-local) so concurrent V3 backfills
        # are safe. A per-thread connection pool + retry adapter is mounted.
        import threading
        if not hasattr(self, "_thread_local"):
            self._thread_local = threading.local()
        sess = getattr(self._thread_local, "session", None)
        if sess is None:
            import requests
            from requests.adapters import HTTPAdapter
            sess = requests.Session()
            sess.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            })
            adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0)
            sess.mount("https://", adapter)
            self._thread_local.session = sess
            self._session = sess  # keep back-compat single-thread reference
        return sess

    # ── Historical Data ──────────────────────────────────────────

    def load_historical_data(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        start_date=None,
        end_date=None,
    ) -> pd.DataFrame:
        if symbol is None:
            raise ValueError("Symbol (instrument key) is required.")

        interval = self._map_timeframe(timeframe)
        to_date = self._fmt_date(end_date or datetime.now())
        from_date = self._fmt_date(start_date or (datetime.now() - timedelta(days=30)))

        df = self._fetch_candles(symbol, interval, to_date, from_date)
        if df.empty:
            return df.reset_index(drop=True)

        tz = df["timestamp"].dt.tz
        if start_date is not None:
            sd = pd.Timestamp(start_date)
            if tz is not None and sd.tzinfo is None:
                sd = sd.tz_localize(tz)
            df = df[df["timestamp"] >= sd]
        if end_date is not None:
            ed = pd.Timestamp(end_date)
            if tz is not None and ed.tzinfo is None:
                ed = ed.tz_localize(tz)
            df = df[df["timestamp"] <= ed]

        return df.reset_index(drop=True)

    def load_latest_data(
        self,
        symbol: str,
        timeframe: str,
        lookback: int = 500,
    ) -> pd.DataFrame:
        interval = self._map_timeframe(timeframe)
        days = self._lookback_to_days(lookback, interval)
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)

        df = self._fetch_candles(symbol, interval, self._fmt_date(to_date), self._fmt_date(from_date))

        return df.tail(lookback).reset_index(drop=True)

    # ── V3 native intervals ──────────────────────────────────────
    # V3 supports TRUE native candles for every timeframe we need
    # (minutes/1..300, hours/1..5, days/1) — no resampling required.
    # tf -> (unit, interval, max window days per request).
    #   minutes 1..15 : 1 month/request ; minutes >15 : 1 quarter/request
    #   hours          : 1 quarter/request ; days : 1 decade/request
    _V3_MAP = {
        "1m":  ("minutes", "1", 27),
        "5m":  ("minutes", "5", 27),
        "15m": ("minutes", "15", 27),
        "30m": ("minutes", "30", 88),
        "1h":  ("hours", "1", 88),
        "1d":  ("days", "1", 3650),
    }

    def load_historical_v3(
        self,
        instrument_key: str,
        timeframe: str,
        start_date,
        end_date=None,
    ) -> pd.DataFrame:
        """Fetch TRUE native candles from Upstox V3 (no resampling).

        Chunks the range to respect V3 per-request window limits and
        concatenates. Returns an empty frame if nothing is available."""
        if timeframe not in self._V3_MAP:
            raise ValueError(f"Unsupported V3 timeframe {timeframe}")
        unit, interval, chunk_days = self._V3_MAP[timeframe]
        end = pd.Timestamp(end_date or datetime.now()).to_pydatetime()
        start = pd.Timestamp(start_date).to_pydatetime()
        pieces = []
        cur_end = end
        while cur_end > start:
            cur_start = max(start, cur_end - timedelta(days=chunk_days))
            df = self._fetch_candles_v3(
                instrument_key, unit, interval,
                self._fmt_date(cur_end), self._fmt_date(cur_start))
            if not df.empty:
                pieces.append(df)
            cur_end = cur_start - timedelta(days=1)
        if not pieces:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        out = pd.concat(pieces, ignore_index=True)
        out = out.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return out

    def load_intraday_v3(self, instrument_key: str, timeframe: str) -> pd.DataFrame:
        """Fetch the CURRENT day's native candles from Upstox V3 intraday."""
        if timeframe not in self._V3_MAP:
            raise ValueError(f"Unsupported V3 timeframe {timeframe}")
        unit, interval, _ = self._V3_MAP[timeframe]
        return self._fetch_candles_v3(instrument_key, unit, interval, None, None, intraday=True)

    def _fetch_candles_v3(
        self,
        instrument_key: str,
        unit: str,
        interval: str,
        to_date: str | None,
        from_date: str | None,
        intraday: bool = False,
    ) -> pd.DataFrame:
        session = self._get_session()
        encoded = quote(instrument_key, safe="")
        if intraday:
            url = f"https://api.upstox.com/v3/historical-candle/intraday/{encoded}/{unit}/{interval}"
        else:
            url = (f"https://api.upstox.com/v3/historical-candle/"
                   f"{encoded}/{unit}/{interval}/{to_date}/{from_date}")
        for attempt in range(4):
            _V3_LIMITER.acquire()
            try:
                resp = session.get(url, timeout=15)
            except Exception as e:
                if attempt < 3:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Upstox V3 network error for {instrument_key}: {e}")
            if resp.status_code == 200:
                break
            if resp.status_code == 429 and attempt < 3:
                # Honour Retry-After if present, else exponential backoff.
                ra = resp.headers.get("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit() else 2.0 * (attempt + 1))
                continue
            raise RuntimeError(
                f"Upstox V3 error {resp.status_code} for {instrument_key}: {resp.text[:200]}")
        candles = resp.json().get("data", {}).get("candles", [])
        if not candles:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
        df = df.drop(columns=["open_interest"]).sort_values("timestamp").reset_index(drop=True)
        return df

    def load_intraday_data(
        self,
        symbol: str,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Fetch the CURRENT day's candles from Upstox's intraday endpoint.

        ``load_historical_data`` uses ``/historical-candle/`` which only serves
        data up to the PREVIOUS trading day — today's live session is never
        returned. This hits ``/historical-candle/intraday/`` which returns the
        in-progress day's candles. Callers that need a live view (paper/real
        trader) should concat this onto the historical frame; the cache builder
        should NOT (it wants complete days only)."""
        if symbol is None:
            raise ValueError("Symbol (instrument key) is required.")
        interval = self._map_timeframe(timeframe)
        return self._fetch_candles(symbol, interval, None, None, intraday=True)

    # ── API Call ──────────────────────────────────────────────────

    def _fetch_candles(
        self,
        instrument_key: str,
        interval: str,
        to_date: str | None,
        from_date: str | None,
        intraday: bool = False,
    ) -> pd.DataFrame:
        session = self._get_session()
        encoded = quote(instrument_key, safe="")
        if intraday:
            url = f"{_UPSTOX_BASE}/historical-candle/intraday/{encoded}/{interval}"
        else:
            url = (
                f"{_UPSTOX_BASE}/historical-candle/"
                f"{encoded}/{interval}/{to_date}/{from_date}"
            )

        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Upstox API error {resp.status_code} for {instrument_key}: {resp.text[:200]}"
            )

        body = resp.json()
        candles = body.get("data", {}).get("candles", [])
        if not candles:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
        df = df.drop(columns=["open_interest"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        return df

    # ── Helpers ──────────────────────────────────────────────────

    def _map_timeframe(self, timeframe: str | None) -> str:
        mapping = {
            "1m": "1minute",
            "5m": "1minute",
            "15m": "30minute",
            "30m": "30minute",
            "1h": "30minute",
            "1d": "day",
            "1w": "week",
            "1mo": "month",
        }
        if timeframe is None or timeframe not in mapping:
            return "day"
        return mapping[timeframe]

    @staticmethod
    def _fmt_date(dt) -> str:
        if isinstance(dt, str):
            return dt[:10]
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def _lookback_to_days(lookback: int, interval: str) -> int:
        multipliers = {
            "1minute": 0.7,
            "30minute": 20,
            "day": 400,
            "week": 2000,
            "month": 8000,
        }
        mult = multipliers.get(interval, 30)
        return max(mult, int(lookback * mult / 400) + 1)

    @property
    def supported_timeframes(self) -> list[str]:
        return ["1m", "15m", "1h", "1d"]
