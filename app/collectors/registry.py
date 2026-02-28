from dataclasses import dataclass
from typing import Any, Callable, Awaitable

Summarizer = Callable[[Any], dict[str, Any]]

@dataclass(frozen=True)
class EndpointSpec:
    name: str
    method: str
    path_template: str
    default_interval_s: float
    requires_restaurant_id: bool
    requires_turn_id: bool
    enabled: Callable[[dict[str, Any]], bool]
    summarizer_key: str   # key used to dispatch to correct summarizer

def build_endpoint_registry() -> list[EndpointSpec]:
    always = lambda ctx: True
    has_turn = lambda ctx: ctx.get("turn_id") is not None
    
    return [
        EndpointSpec(
            name="restaurants",
            method="GET",
            path_template="/restaurants",
            default_interval_s=10.0,
            requires_restaurant_id=False,
            requires_turn_id=False,
            enabled=always,
            summarizer_key="restaurants",
        ),
        EndpointSpec(
            name="market_entries",
            method="GET",
            path_template="/market/entries",
            default_interval_s=10.0,
            requires_restaurant_id=False,
            requires_turn_id=False,
            enabled=always,
            summarizer_key="market",
        ),
        EndpointSpec(
            name="recipes",
            method="GET",
            path_template="/recipes",
            default_interval_s=120.0,
            requires_restaurant_id=False,
            requires_turn_id=False,
            enabled=always,
            summarizer_key="recipes",
        ),
        EndpointSpec(
            name="my_restaurant",
            method="GET",
            path_template="/restaurant/{restaurant_id}",
            default_interval_s=10.0,
            requires_restaurant_id=True,
            requires_turn_id=False,
            enabled=always,
            summarizer_key="restaurant_detail",
        ),
        EndpointSpec(
            name="my_menu",
            method="GET",
            path_template="/restaurant/{restaurant_id}/menu",
            default_interval_s=15.0,
            requires_restaurant_id=True,
            requires_turn_id=False,
            enabled=always,
            summarizer_key="menu",
        ),
        EndpointSpec(
            name="meals",
            method="GET",
            path_template="/meals",
            default_interval_s=10.0,
            requires_restaurant_id=True,
            requires_turn_id=True,
            enabled=has_turn,
            summarizer_key="meals",
        ),
        EndpointSpec(
            name="bid_history",
            method="GET",
            path_template="/bid_history",
            default_interval_s=15.0,
            requires_restaurant_id=False,
            requires_turn_id=True,
            enabled=has_turn,
            summarizer_key="bid_history",
        ),
    ]
