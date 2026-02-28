from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class MarketEntry:
    entry_id: int | None
    side: str | None
    ingredient: str | None
    quantity: float | None
    price: float | None
    owner_id: int | None
    raw: dict[str, Any]

@dataclass(frozen=True)
class MarketSnapshot:
    ts_ms: int
    entries: list[MarketEntry]
