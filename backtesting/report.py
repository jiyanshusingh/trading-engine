from backtesting.metrics import Metrics


class Report:

    @staticmethod
    def generate(trades):

        return {

            "Total Trades": len(trades),

            "Win Rate": Metrics.win_rate(trades),

            "Average RR": Metrics.average_rr(trades),

            "Total PnL": Metrics.total_pnl(trades)

        }