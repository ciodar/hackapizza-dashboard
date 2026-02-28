import asyncio
import time
from dataclasses import dataclass, field
from collections import deque
from typing import Any

from app.models.common import GamePhase
from app.models.endpoint import EndpointStatus, EndpointCheck
from app.models.sse import SSEEvent
from app.models.restaurant import RestaurantsOverview, RestaurantDetail, MenuSnapshot
from app.models.market import MarketSnapshot
from app.models.meals import MealsSnapshot
from app.models.bids import BidHistorySnapshot
from app.models.alerts import AlertInstance

@dataclass
class StateStore:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # connectivity / meta
    phase: GamePhase = GamePhase.UNKNOWN
    last_heartbeat_ms: int | None = None
    sse_connected: bool = False
    sse_blocked: bool = False
    last_sse_error: str | None = None

    # turn tracking (populated by MySQLPoller from main.py's MySQL writes)
    turn_number: int = 0
    turn_id: int | None = None

    # endpoint health
    endpoint_status: dict[str, EndpointStatus] = field(default_factory=dict)
    endpoint_checks: dict[str, deque] = field(default_factory=dict)

    # latest business snapshots
    restaurants_overview: RestaurantsOverview | None = None
    my_restaurant: RestaurantDetail | None = None
    my_menu: MenuSnapshot | None = None
    market: MarketSnapshot | None = None
    meals: MealsSnapshot | None = None
    bid_history: BidHistorySnapshot | None = None
    recipes_cache: list[dict] = field(default_factory=list)

    # live events
    events: deque = field(default_factory=lambda: deque(maxlen=2000))

    # derived outputs
    active_alerts: dict[str, AlertInstance] = field(default_factory=dict)

    async def snapshot(self) -> dict[str, Any]:
        async with self.lock:
            now_ms = int(time.time() * 1000)
            hb_age = None
            if self.last_heartbeat_ms:
                hb_age = (now_ms - self.last_heartbeat_ms) / 1000.0

            restaurants = []
            if self.restaurants_overview:
                for r in self.restaurants_overview.restaurants:
                    restaurants.append({
                        "id": r.restaurant_id,
                        "name": r.name,
                        "balance": r.balance,
                        "reputation": r.reputation,
                        "is_open": r.is_open,
                    })

            my = None
            if self.my_restaurant:
                my = {
                    "id": self.my_restaurant.restaurant_id,
                    "balance": self.my_restaurant.balance,
                    "reputation": self.my_restaurant.reputation,
                    "is_open": self.my_restaurant.is_open,
                    "inventory": self.my_restaurant.inventory,
                }

            menu = []
            if self.my_menu:
                menu = [{"name": i.name, "price": i.price} for i in self.my_menu.items]

            market_entries = []
            if self.market:
                for e in self.market.entries:
                    market_entries.append({
                        "id": e.entry_id,
                        "side": e.side,
                        "ingredient": e.ingredient,
                        "quantity": e.quantity,
                        "price": e.price,
                        "owner_id": e.owner_id,
                    })

            meals = []
            if self.meals:
                for m in self.meals.meals:
                    meals.append({
                        "client_id": m.client_id,
                        "client_name": m.client_name,
                        "order_text": m.order_text,
                        "executed": m.executed,
                    })

            bids = []
            if self.bid_history:
                for b in self.bid_history.bids:
                    bids.append({
                        "ingredient": b.ingredient,
                        "bid": b.bid,
                        "quantity": b.quantity,
                        "restaurant_id": b.restaurant_id,
                    })

            endpoint_statuses = {}
            for name, status in self.endpoint_status.items():
                endpoint_statuses[name] = {
                    "name": status.name,
                    "severity": status.severity.value,
                    "last_check": {
                        "ok": status.last_check.ok,
                        "status_code": status.last_check.status_code,
                        "latency_ms": status.last_check.latency_ms,
                        "error": status.last_check.error,
                        "ts_ms": status.last_check.ts_ms,
                    } if status.last_check else None,
                    "stats_1m": status.stats_1m,
                    "stats_5m": status.stats_5m,
                    "last_ok_ts_ms": status.last_ok_ts_ms,
                }

            recent_events = []
            for ev in list(self.events)[-100:]:
                recent_events.append({
                    "ts_ms": ev.ts_ms,
                    "type": ev.type,
                    "data": ev.data,
                })

            alerts = {}
            for aid, alert in self.active_alerts.items():
                alerts[aid] = {
                    "alert_id": alert.alert_id,
                    "severity": alert.severity.value,
                    "title": alert.title,
                    "message": alert.message,
                    "first_seen_ms": alert.first_seen_ms,
                    "last_seen_ms": alert.last_seen_ms,
                    "acknowledged": alert.acknowledged,
                }

            return {
                "phase": self.phase.value,
                "turn_number": self.turn_number,
                "turn_id": self.turn_id,
                "sse_connected": self.sse_connected,
                "sse_blocked": self.sse_blocked,
                "last_sse_error": self.last_sse_error,
                "heartbeat_age_s": hb_age,
                "restaurants": restaurants,
                "my_restaurant": my,
                "menu": menu,
                "market_entries": market_entries,
                "meals": meals,
                "bids": bids,
                "endpoint_statuses": endpoint_statuses,
                "recent_events": recent_events,
                "active_alerts": alerts,
                "recipes_count": len(self.recipes_cache),
            }
