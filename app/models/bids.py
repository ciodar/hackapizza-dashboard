from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class BidRow:
    ingredient: str | None
    bid: float | None
    quantity: float | None
    restaurant_id: int | None
    raw: dict[str, Any]

@dataclass(frozen=True)
class BidHistorySnapshot:
    ts_ms: int
    turn_id: int
    bids: list[BidRow]
