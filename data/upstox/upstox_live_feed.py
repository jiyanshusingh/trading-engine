"""
Upstox WebSocket Live Feed — wraps MarketDataStreamerV3 for real-time OHLC.

WS ``full`` mode returns pre-built candles for two intervals:
  - ``"1d"`` — current day aggregated OHLC (open, high, low, close, volume)
  - ``"I1"`` — latest 1-minute candle

Timestamp fields (``ts``) are in **milliseconds**.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pandas as pd

_log = logging.getLogger(__name__)


class UpstoxLiveFeed:
    """
    Real-time market data via Upstox WebSocket.

    Two modes:
    * **Batch** — ``get_live_batch()`` connects, collects one round of
      responses, then disconnects.  Good for the scanner.
    * **Streaming** — ``start()`` keeps the WebSocket open and buffers
      the latest candle per symbol.  Good for the dashboard.
    """

    TIMEOUT = 15.0
    MAX_RECONNECT_ATTEMPTS = 10
    RECONNECT_BASE = 2.0   # seconds; doubled each attempt
    RECONNECT_MAX = 60.0   # cap on backoff

    def __init__(self, access_token: str):
        self._access_token = access_token
        self._streamer: Any = None
        self._connected = False
        self._buffer: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._reconnect_enabled = False
        self._reconnecting = False
        self._instrument_keys: list[str] = []
        self._mode = "full"
        self._on_update: Any = None

    # ── Batch ──────────────────────────────────────────────────────────

    def get_live_batch(
        self,
        instrument_keys: list[str],
        mode: str = "full",
        timeout: float | None = None,
    ) -> dict[str, dict]:
        """
        Subscribe → collect responses → disconnect.

        Returns ``{instrument_key: {interval, open, high, low, close, vol, ts}}``
        with the **first** OHLC interval that was found (typically ``"1d"``).
        """
        from upstox_client import ApiClient, Configuration
        from upstox_client.feeder.market_data_streamer_v3 import (
            MarketDataStreamerV3,
        )

        cfg = Configuration()
        cfg.access_token = self._access_token
        api_client = ApiClient(cfg)

        streamer = MarketDataStreamerV3(
            api_client=api_client,
            instrumentKeys=instrument_keys,
            mode=mode,
        )

        results: dict[str, dict] = {}
        errors: list[str] = []
        done = threading.Event()

        def on_message(data: dict) -> None:
            feeds = data.get("feeds") or {}
            if not feeds:
                return
            for key, feed in feeds.items():
                if mode == "ltpc":
                    ltpc = feed.get("ltpc")
                    if ltpc:
                        results[key] = dict(ltpc)
                else:
                    intervals = self._extract_all_intervals(feed, mode)
                    if intervals:
                        ohlc = intervals.get("1d") or intervals.get("I1")
                        if ohlc:
                            ohlc["_intervals"] = intervals
                            results[key] = ohlc
            done.set()

        def on_error(err: Any) -> None:
            errors.append(str(err))
            done.set()

        streamer.on("message", on_message)
        streamer.on("error", on_error)
        streamer.connect()
        done.wait(timeout=timeout or self.TIMEOUT)
        streamer.disconnect()

        if errors and not results:
            raise RuntimeError(f"WebSocket batch error: {errors[0]}")

        _log.info("WS batch: %d/%d results", len(results), len(instrument_keys))
        return results

    # ── Streaming ──────────────────────────────────────────────────────

    def start(
        self,
        instrument_keys: list[str],
        mode: str = "full",
        on_update: callable | None = None,
    ) -> None:
        """Connect and keep the WebSocket open with auto-reconnect.

        ``on_update(key, all_intervals)`` fires on every message with a dict of
        ``{interval_name: ohlc_dict}``. On error/close the feed auto-reconnects
        with exponential backoff (see :attr:`MAX_RECONNECT_ATTEMPTS`).
        """
        if self._connected:
            _log.warning("WS already connected — ignoring start()")
            return

        self._reconnect_enabled = True
        self._instrument_keys = instrument_keys
        self._mode = mode
        self._on_update = on_update
        self._connect(instrument_keys, mode, on_update)

    def _connect(
        self,
        instrument_keys: list[str],
        mode: str,
        on_update: callable | None,
    ) -> None:
        from upstox_client import ApiClient, Configuration
        from upstox_client.feeder.market_data_streamer_v3 import (
            MarketDataStreamerV3,
        )

        cfg = Configuration()
        cfg.access_token = self._access_token
        api_client = ApiClient(cfg)

        streamer = MarketDataStreamerV3(
            api_client=api_client,
            instrumentKeys=instrument_keys,
            mode=mode,
        )

        def on_message(data: dict) -> None:
            feeds = data.get("feeds") or {}
            if not feeds:
                return
            for key, feed in feeds.items():
                intervals = self._extract_all_intervals(feed, mode)
                if intervals:
                    with self._lock:
                        self._buffer[key] = intervals
                    if on_update:
                        on_update(key, intervals)

        def on_error(err: Any) -> None:
            _log.error("WS error: %s", err)
            self._schedule_reconnect(0)

        def on_close(code: Any = None, reason: Any = None) -> None:
            _log.warning("WS closed (code=%s reason=%s)", code, reason)
            self._schedule_reconnect(0)

        streamer.on("message", on_message)
        streamer.on("error", on_error)
        try:
            streamer.on("close", on_close)
        except Exception:
            pass
        streamer.connect()

        self._streamer = streamer
        self._connected = True
        _log.info("WS streaming started (%d keys)", len(instrument_keys))

    def _schedule_reconnect(self, attempt: int) -> None:
        """Mark disconnected and spawn a backoff reconnect thread (guarded)."""
        self._connected = False
        if not self._reconnect_enabled or self._reconnecting:
            return
        if attempt >= self.MAX_RECONNECT_ATTEMPTS:
            _log.error("WS reconnect aborted after %d attempts", attempt)
            return
        self._reconnecting = True
        wait = min(self.RECONNECT_BASE * (2 ** attempt), self.RECONNECT_MAX)
        _log.info("WS reconnect attempt %d in %.1fs", attempt + 1, wait)

        def _do_reconnect() -> None:
            time.sleep(wait)
            self._reconnecting = False
            if not self._reconnect_enabled:
                return
            try:
                self._connect(self._instrument_keys, self._mode, self._on_update)
            except Exception as e:
                _log.warning("WS reconnect failed: %s", e)
                self._schedule_reconnect(attempt + 1)

        threading.Thread(target=_do_reconnect, daemon=True).start()

    def stop(self) -> None:
        self._reconnect_enabled = False
        self._reconnecting = False
        if self._streamer and self._connected:
            self._streamer.disconnect()
            self._connected = False
            with self._lock:
                self._buffer.clear()
            _log.info("WS disconnected")

    @property
    def connected(self) -> bool:
        return self._connected

    def get_latest(self, instrument_key: str) -> dict | None:
        """
        Return the latest intervals dict for a key (streaming mode).
        Returns ``{interval_name: ohlc_dict}`` or *None*.
        """
        with self._lock:
            return self._buffer.get(instrument_key)

    # ── OHLC extraction ────────────────────────────────────────────────

    @staticmethod
    def _extract_all_intervals(feed: dict, mode: str) -> dict[str, dict]:
        """Pull all OHLC intervals from a feed dict.

        Returns ``{interval_name: {interval, open, high, low, close, vol, ts}}``.
        """
        if mode != "full":
            return {}

        full_feed = feed.get("fullFeed") or {}
        market_ff = full_feed.get("marketFF") or {}
        market_ohlc = market_ff.get("marketOHLC") or {}
        ohlc_list = market_ohlc.get("ohlc") or []
        return {o["interval"]: o for o in ohlc_list}

    # ── Today candle fetch ────────────────────────────────────────────

    def fetch_today_data(
        self,
        instrument_key: str,
    ) -> pd.DataFrame | None:
        """
        Connect → fetch today's ``"1d"`` aggregated candle → disconnect.

        Returns a single-row DataFrame (columns: ``timestamp, open, high,
        low, close, volume``) or *None*.
        """
        from pandas import Timestamp

        try:
            batch = self.get_live_batch([instrument_key], mode="full", timeout=10)
            ohlc = batch.get(instrument_key)
            if ohlc is None:
                return None

            # Try daily first, fall back to 1-minute
            intervals = ohlc.get("_intervals") or {}
            daily = intervals.get("1d") or ohlc

            ts_ms = daily.get("ts", 0)
            try:
                ts = Timestamp(int(ts_ms), unit="ms", tz="UTC")
            except (ValueError, OSError):
                ts = Timestamp.now(tz="UTC")

            return pd.DataFrame([{
                "timestamp": ts,
                "open": float(daily.get("open", 0)),
                "high": float(daily.get("high", 0)),
                "low": float(daily.get("low", 0)),
                "close": float(daily.get("close", 0)),
                "volume": int(daily.get("vol", 0)),
            }])
        except Exception as e:
            _log.debug("fetch_today_data failed for %s: %s", instrument_key, e)
            return None

    # ── Live price fetch ──────────────────────────────────────────────

    def fetch_live_price(
        self,
        instrument_key: str,
    ) -> dict | None:
        """
        Connect → get LTPC → disconnect.  Returns
        ``{ltp, ltt, ltq, cp}`` or *None*.
        """
        try:
            batch = self.get_live_batch([instrument_key], mode="ltpc", timeout=10)
            feed = batch.get(instrument_key)
            if feed:
                return {
                    "ltp": float(feed.get("ltp", 0)),
                    "ltt": int(feed.get("ltt", 0)),
                    "ltq": int(feed.get("ltq", 0)),
                    "cp": float(feed.get("cp", 0)),
                }
            return None
        except Exception as e:
            _log.debug("fetch_live_price failed for %s: %s", instrument_key, e)
            return None
