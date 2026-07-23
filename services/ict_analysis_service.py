from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

_log = logging.getLogger("ict_service")


class ICTAnalysisService:
    def __init__(self):
        self._provider_cache = {}
        self._obs_builder = None
        self._semantic_pipeline = None
        self._trading_pipeline = None

    # ── Chart Data ─────────────────────────────────────────────

    def get_chart_data(
        self, symbol: str, timeframe: str = "15m", lookback: int = 100, provider_type: str = "yfinance"
    ) -> pd.DataFrame | None:
        return self._fetch_data(symbol, timeframe, lookback, provider_type)

    # ── Market Context ──────────────────────────────────────────

    def get_market_context(self) -> dict:
        indices = {
            "NIFTY 50": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "SENSEX": "^BSESN",
        }
        context = {}
        for name, sym in indices.items():
            try:
                tk = yf.Ticker(sym)
                hist = tk.history(period="3d", interval="1d")
                if len(hist) >= 2:
                    curr = hist["Close"].iloc[-1]
                    prev = hist["Close"].iloc[-2]
                    chg = ((curr - prev) / prev) * 100
                    context[name] = {"value": round(curr, 2), "change": round(chg, 2)}
                else:
                    context[name] = {"value": None, "change": None}
            except Exception:
                context[name] = {"value": None, "change": None}

        # Market regime: VIX + FII/DII + combined assessment
        try:
            from engines.market_regime_engine import classify as classify_regime
            context["market_regime"] = classify_regime()
        except Exception as exc:
            _log.warning("Market regime classification failed: %s", exc)
            context["market_regime"] = None

        # Sector rotation
        try:
            from engines.sector_rotation_engine import get_sector_rotation
            context["sector_rotation"] = get_sector_rotation()
        except Exception as exc:
            _log.warning("Sector rotation analysis failed: %s", exc)
            context["sector_rotation"] = None

        return context

    # ── Day Type / Stock Type / Strategy Classification ──────────

    def get_day_type(self) -> dict:
        from engines.day_type_engine import DayTypeEngine
        return DayTypeEngine.classify()

    def get_stock_type(self, symbol: str, provider_type: str = "yfinance") -> dict:
        from engines.stock_type_engine import StockTypeEngine

        df = self._fetch_data(symbol, "15m", 50, provider_type)
        nifty_df = self._fetch_data("^NSEI", "15m", 50, "yfinance")

        # Rename lowercase cols → uppercase for the engine
        if df is not None and not df.empty:
            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
        if nifty_df is not None and not nifty_df.empty:
            nifty_df = nifty_df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })

        stock_daily = None
        if provider_type == "yfinance":
            try:
                tk = yf.Ticker(symbol)
                stock_daily = tk.history(period="1mo", interval="1d")
            except Exception:
                pass

        return StockTypeEngine.classify(df, nifty_df, stock_daily)

    def get_strategy_recommendation(self, day_type: str, stock_type: str) -> dict:
        from strategies.selector import select, get_recommended_tuning

        strategy, rationale = select(day_type, stock_type)
        tuning = get_recommended_tuning(day_type, stock_type)

        return {
            "day_type": day_type,
            "stock_type": stock_type,
            "strategy_name": strategy.name if strategy else "Unknown",
            "strategy_category": strategy.category if strategy else "",
            "confidence": strategy.confidence if strategy else "UNKNOWN",
            "description": strategy.description[:200] if strategy else "",
            "rationale": rationale,
            "tuning": tuning,
            "best_conditions": strategy.best_conditions if strategy else [],
            "core_concepts": strategy.core_concepts[:5] if strategy else [],
            "gaps": strategy.gaps[:3] if strategy else [],
        }

    # ── ICT Pipeline Analysis ───────────────────────────────────

    def analyze(
        self,
        symbol: str,
        name: str,
        timeframe: str,
        lookback: int = 200,
        provider_type: str = "yfinance",
    ) -> dict | None:
        df = self._fetch_data(symbol, timeframe, lookback, provider_type)
        if df is None or len(df) < 30:
            return None

        result = self._run_pipeline(df, symbol, name, timeframe)
        return result

    def analyze_all_timeframes(
        self,
        symbol: str,
        name: str,
        timeframes: list[tuple[str, int]] | None = None,
        provider_type: str = "yfinance",
    ) -> dict[str, dict]:
        if timeframes is None:
            timeframes = [("15m", 200), ("1h", 96), ("1d", 200)]

        results = {}
        for tf, lookback in timeframes:
            r = self.analyze(symbol, name, tf, lookback, provider_type)
            if r:
                results[tf] = r
        return results

    # ── Price/Broader Stock Data for Analysis ───────────────────

    def get_stock_profile(self, symbol: str) -> dict:
        profile = {"symbol": symbol}
        try:
            tk = yf.Ticker(symbol)

            hist = tk.history(period="2d", interval="1d")
            if len(hist) >= 2:
                profile["prev_close"] = round(float(hist["Close"].iloc[-2]), 2)
                profile["today_close"] = round(float(hist["Close"].iloc[-1]), 2)
                profile["daily_change_pct"] = round(
                    ((hist["Close"].iloc[-1] - hist["Close"].iloc[-2])
                     / hist["Close"].iloc[-2]) * 100, 2
                )
            elif len(hist) == 1:
                profile["today_close"] = round(float(hist["Close"].iloc[-1]), 2)
                profile["daily_change_pct"] = 0.0

            vol_series = hist["Volume"].dropna()
            if not vol_series.empty:
                profile["volume"] = int(vol_series.iloc[-1])
                avg_vol = vol_series.tail(21).mean()
                profile["avg_volume"] = int(avg_vol) if not pd.isna(avg_vol) else 0
                profile["vol_ratio"] = round(profile["volume"] / profile["avg_volume"], 2) if profile.get("avg_volume", 0) > 0 else 1.0

            intra = tk.history(period="1d", interval="15m")
            if not intra.empty:
                profile["open"] = round(float(intra["Open"].iloc[0]), 2)
                profile["high"] = round(float(intra["High"].max()), 2)
                profile["low"] = round(float(intra["Low"].min()), 2)
                profile["current"] = round(float(intra["Close"].iloc[-1]), 2)
                profile["intraday_change_pct"] = round(
                    ((intra["Close"].iloc[-1] - intra["Open"].iloc[0])
                     / intra["Open"].iloc[0]) * 100, 2
                )
                profile["day_range_pct"] = round(
                    ((profile["current"] - profile["low"])
                     / (profile["high"] - profile["low"])) * 100
                    if profile["high"] != profile["low"] else 100
                )

                vol_today = intra["Volume"].sum()
                if vol_today > 0:
                    profile["volume"] = int(vol_today)
                profile["candle_count"] = len(intra)
                profile["bullish_candles"] = int((intra["Close"] > intra["Open"]).sum())
                profile["bearish_candles"] = int((intra["Close"] < intra["Open"]).sum())
        except Exception as e:
            _log.warning(f"Stock profile error for {symbol}: {e}")
        return profile

    def get_historical_context(self, symbol: str) -> dict:
        ctx = {}
        try:
            tk = yf.Ticker(symbol)
            hist = tk.history(period="1mo", interval="1d")
            if len(hist) >= 5:
                latest = hist.iloc[-1]
                prev_day = hist.iloc[-2]
                ctx["prev_day_close"] = round(float(prev_day["Close"]), 2)
                ctx["prev_day_high"] = round(float(prev_day["High"]), 2)
                ctx["prev_day_low"] = round(float(prev_day["Low"]), 2)
                ctx["prev_day_vol"] = int(prev_day["Volume"]) if not pd.isna(prev_day["Volume"]) else 0

                week_ago = hist.iloc[-5]
                ctx["week_ago_close"] = round(float(week_ago["Close"]), 2)
                ctx["week_change_pct"] = round(
                    ((latest["Close"] - week_ago["Close"]) / week_ago["Close"]) * 100, 2
                )

                ctx["month_high"] = round(float(hist["High"].tail(21).max()), 2)
                ctx["month_low"] = round(float(hist["Low"].tail(21).min()), 2)
        except Exception:
            pass
        return ctx

    # ── Internal ────────────────────────────────────────────────

    def _fetch_data(self, symbol: str, timeframe: str, lookback: int, provider_type: str) -> pd.DataFrame | None:
        if provider_type == "upstox":
            return self._fetch_upstox(symbol, timeframe, lookback)
        try:
            import yfinance as yf
            interval_map = {"1m": "1m", "15m": "15m", "1h": "60m", "1d": "1d"}
            period_map = {"1m": "7d", "15m": "1mo", "1h": "3mo", "1d": "6mo"}
            interval = interval_map.get(timeframe, "1d")
            period = period_map.get(timeframe, "1mo")
            tk = yf.Ticker(symbol)
            df = tk.history(period=period, interval=interval)
            if df.empty:
                return None
            df = df.reset_index()
            rename = {"Datetime": "timestamp", "Date": "timestamp",
                       "Open": "open", "High": "high", "Low": "low",
                       "Close": "close", "Volume": "volume"}
            df = df.rename(columns={c: rename[c] for c in df.columns if c in rename})
            for c in ["timestamp", "open", "high", "low", "close", "volume"]:
                if c not in df.columns:
                    df[c] = None
            return df.tail(lookback).reset_index(drop=True)
        except Exception as e:
            _log.warning(f"Fetch error for {symbol}: {e}")
            return None

    def _fetch_upstox(self, instrument_key: str, timeframe: str, lookback: int) -> pd.DataFrame | None:
        try:
            from config.daemon_config import UPSTOX
            token = UPSTOX.get("access_token", "")
            if not token:
                return None
            from data.upstox.upstox_market_data_provider import UpstoxMarketDataProvider
            provider = self._provider_cache.get("upstox")
            if provider is None:
                provider = UpstoxMarketDataProvider(access_token=token)
                self._provider_cache["upstox"] = provider
            return provider.load_latest_data(instrument_key, timeframe, lookback)
        except Exception as e:
            _log.warning(f"Upstox fetch error: {e}")
            return None

    def _run_pipeline(self, df: pd.DataFrame, symbol: str, name: str, timeframe: str) -> dict | None:
        try:
            from data.builders.observation_history_builder import ObservationHistoryBuilder
            from domain.semantic_construction.semantic_construction_pipeline import SemanticConstructionPipeline
            from application.pipeline.trading_pipeline import TradingPipeline
            from domain.reasoning.ict.ict_reasoning_model import ICTReasoningModel
            from domain.opportunity.ict_opportunity_generator import ICTOpportunityGenerator
            from domain.opportunity.ict_opportunity_assessor import ICTOpportunityAssessor
            from domain.opportunity.ict_opportunity_ranker import ICTOpportunityRanker
            from domain.portfolio.ict_portfolio_allocator import ICTPortfolioAllocator
            from domain.trade.ict_trade_constructor import ICTTradeConstructor
            from domain.execution.ict_execution_planner import ICTExecutionPlanner

            if self._obs_builder is None:
                self._obs_builder = ObservationHistoryBuilder()
            if self._semantic_pipeline is None:
                self._semantic_pipeline = SemanticConstructionPipeline()
            if self._trading_pipeline is None:
                self._trading_pipeline = TradingPipeline(
                    reasoning_model=ICTReasoningModel(),
                    opportunity_generator=ICTOpportunityGenerator(),
                    opportunity_assessor=ICTOpportunityAssessor(),
                    opportunity_ranker=ICTOpportunityRanker(),
                    portfolio_allocator=ICTPortfolioAllocator(),
                    trade_constructor=ICTTradeConstructor(
                        stop_loss_multiplier=3.0,
                        take_profit_multiplier=4.0,
                        atr_period=14,
                        min_risk_reward=0.0,
                    ),
                    execution_planner=ICTExecutionPlanner(),
                )

            obs = self._obs_builder.build(df=df, symbol=symbol, timeframe=timeframe, source="LIVE")
            market = self._semantic_pipeline.build(obs)
            result = self._trading_pipeline.run(market)

            regime = result.market_theses[0].market_regime if result.market_theses else ""
            trades_data = []
            for tc in result.trade_candidates:
                trades_data.append({
                    "direction": tc.direction,
                    "entry": tc.entry_price,
                    "stop": tc.stop_loss,
                    "target": tc.take_profit,
                    "rr": tc.risk_reward_ratio,
                    "order_type": tc.order_type,
                    "position_size": tc.position_size,
                })

            return {
                "symbol": symbol,
                "name": name,
                "timeframe": timeframe,
                "regime": regime,
                "trades": trades_data,
                "thesis_count": result.thesis_count,
                "opportunity_count": result.opportunity_count,
                "trade_count": result.trade_count,
                "last_close": round(float(df["close"].iloc[-1]), 2) if not df.empty else None,
            }
        except Exception as e:
            _log.warning(f"Pipeline error for {symbol} @ {timeframe}: {e}")
            return None
