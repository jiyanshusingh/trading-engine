class Metrics:

    @staticmethod
    def win_rate(trades):

        if not trades:
            return 0

        wins = sum(
            1 for trade in trades
            if trade.result == "WIN"
        )

        return round(
            wins / len(trades) * 100,
            2
        )

    @staticmethod
    def average_rr(trades):

        if not trades:
            return 0

        return round(
            sum(t.rr for t in trades) / len(trades),
            2
        )

    @staticmethod
    def total_pnl(trades):

        return round(
            sum(t.pnl for t in trades),
            2
        )