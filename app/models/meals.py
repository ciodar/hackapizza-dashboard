from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class MealRequest:
    client_id: str | None
    client_name: str | None
    order_text: str | None
    executed: bool | None
    raw: dict[str, Any]

@dataclass(frozen=True)
class MealsSnapshot:
    ts_ms: int
    turn_id: int
    restaurant_id: int
    meals: list[MealRequest]
