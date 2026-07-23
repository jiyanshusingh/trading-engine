from engines.data_engine import DataEngine
from engines.indicator_engine import IndicatorEngine
from engines.market_structure import MarketStructure
from engines.smc_engine import SMCEngine
from engines.liquidity_engine import LiquidityEngine
from engines.premium_discount_engine import PremiumDiscountEngine
from engines.order_block_engine import OrderBlockEngine
from engines.fvg_engine import FVGEngine
from engines.signal_engine import SignalEngine
from engines.risk_engine import RiskEngine
from engines.probability_engine import ProbabilityEngine
from engines.confluence_engine import ConfluenceEngine
from engines.rating_engine import RatingEngine


def analyze_stock(
    symbol,
    period="1y",
    interval="1d"
):

    engine = DataEngine()

    df = engine.get_data(
        symbol,
        period=period,
        interval=interval
    )

    # Indicators
    ind = IndicatorEngine()
    df = ind.calculate(df)

    # Market Structure
    ms = MarketStructure(df)
    df = ms.detect_swings()
    df = ms.classify_structure()
    df = ms.detect_trend_state()
    df = ms.detect_bos()

    # SMC
    smc = SMCEngine(df)
    df = smc.detect_choch()

    # Liquidity
    liq = LiquidityEngine(df)
    df =liq.detect_liquidity_sweeps()
    
    # Premium / Discount
    pd_engine = PremiumDiscountEngine(df)
    df = pd_engine.detect_zones()

    # Order Blocks
    ob = OrderBlockEngine(df)
    df = ob.detect_order_blocks()

    # Fair Value Gaps
    fvg = FVGEngine(df)
    df = fvg.detect_fvg()

    # Signal
    signal = SignalEngine(df)
    result = signal.generate_signal()

    # Risk
    risk = RiskEngine(df)
    trade = risk.calculate()
    
    prob = ProbabilityEngine(df)
    probability = prob.calculate()
    
    conf = ConfluenceEngine(df, result)
    confluence = conf.calculate()
    
    rating_engine = RatingEngine(
    result,
    probability,
    confluence
    )
    rating = rating_engine.calculate()
    
    latest = df.iloc[-1]

    latest = df.iloc[-1]

    indicators = {
    "EMA 20": round(latest["EMA20"], 2),
    "EMA 50": round(latest["EMA50"], 2),
    "EMA 200": round(latest["EMA200"], 2),
    "RSI": round(latest["RSI"], 2),
    "MACD": round(latest["MACD"], 2),
    "MACD Signal": round(latest["MACD_SIGNAL"], 2),
    "MACD Histogram": round(latest["MACD_HIST"], 2),
    "ATR": round(latest["ATR"], 2),
    }

    return {
        "symbol": symbol,
        "df": df,
        "signal": result,
        "risk": trade,
        "probability": probability,
        "confluence": confluence,
        "rating": rating,
        "indicators": indicators
    }