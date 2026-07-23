from dataclasses import dataclass


@dataclass
class Trade:

    symbol: str

    entry: float

    exit: float

    stop_loss: float

    target: float

    quantity: int

    direction: str

    result: str

    pnl: float

    rr: float