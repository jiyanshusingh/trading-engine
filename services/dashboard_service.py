from services.analysis_service import analyze_stock
from engines.multitimeframe_engine import MultiTimeframeEngine


class DashboardService:

    def analyze(self, symbol):

        result = analyze_stock(symbol)

        mtf = MultiTimeframeEngine()
        result["mtf"] = mtf.analyze(symbol)

        return result