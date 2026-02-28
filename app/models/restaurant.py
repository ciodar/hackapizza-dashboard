from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class RestaurantRow:
    restaurant_id: int | None
    name: str | None
    balance: float | None
    reputation: float | None
    is_open: bool | None
    raw: dict[str, Any]

@dataclass(frozen=True)
class RestaurantsOverview:
    ts_ms: int
    restaurants: list[RestaurantRow]

@dataclass(frozen=True)
class MenuItem:
    name: str | None
    price: float | None
    raw: dict[str, Any]

@dataclass(frozen=True)
class MenuSnapshot:
    ts_ms: int
    restaurant_id: int
    items: list[MenuItem]

@dataclass(frozen=True)
class RestaurantDetail:
    ts_ms: int
    restaurant_id: int
    balance: float | None
    reputation: float | None
    is_open: bool | None
    inventory: dict[str, float]
    raw: dict[str, Any]
