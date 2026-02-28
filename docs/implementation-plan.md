Below is a **technical implementation specification** for Option A (**FastAPI + NiceGUI**) that a developer can directly implement. It includes:

* **Overall structure** (modules, startup, background tasks)
* **Data models**
* **Function signatures** + **behavior** + **return values**
* **Feature-by-feature specs** (monitoring, SSE, ranking, market, meals, alerts, MCP actions, persistence, export)

I’m intentionally designing for **unknown/variable payload schemas** (because hackathon servers often evolve). Parsers must be defensive.

---

# 1) Overall architecture and runtime model

## 1.1 Processes and responsibilities

Single Python service, one process:

* **Collectors**

  * HTTP polling (all public endpoints)
  * SSE upstream (single connection per restaurant)
* **Aggregator**

  * Derived metrics (rankings, throughput, opportunities)
  * Alerts engine
* **Storage**

  * In-memory “live state”
  * SQLite persistence (optional but recommended)
* **UI**

  * NiceGUI pages reading live state and refreshing periodically
* **API**

  * FastAPI endpoints for JSON exports + websockets relay (optional but recommended)

## 1.2 Concurrency model

* Everything runs on **asyncio** event loop (FastAPI + NiceGUI).
* Background tasks started on app startup:

  * `poll_scheduler_task`
  * `sse_listener_task`
  * `alerts_engine_task`
  * `persistence_flush_task` (optional)

State access must be synchronized with `asyncio.Lock`.

---

# 2) Project structure

## 2.1 Directory layout

```
app/
  main.py
  config.py
  logging_setup.py

  models/
    common.py
    endpoint.py
    sse.py
    restaurant.py
    market.py
    bids.py
    meals.py
    alerts.py
    mcp.py

  core/
    state.py
    event_bus.py
    time.py
    utils.py

  clients/
    hackapizza_http.py
    hackapizza_sse.py
    hackapizza_mcp.py

  collectors/
    registry.py
    poller.py
    summarizers.py

  aggregators/
    ranking.py
    market_intel.py
    meals_kpi.py
    bids_intel.py

  alerts/
    engine.py
    rules.py

  storage/
    sqlite.py
    repository.py

  ui/
    app_ui.py
    pages/
      overview.py
      endpoint_health.py
      competition.py
      serving.py
      market.py
      bids.py
      events.py
      actions.py
      exports.py
```

---

# 3) Configuration specification

## 3.1 `AppConfig` (Pydantic settings)

### Signature

```python
# app/config.py
from pydantic_settings import BaseSettings
from pydantic import Field

class AppConfig(BaseSettings):
    base_url: str = Field(..., description="Hackapizza server base URL, e.g. https://host")
    api_key: str = Field(..., description="x-api-key header value")

    restaurant_id: int = Field(..., description="Your restaurant ID for SSE and private endpoints")
    turn_id: int | None = Field(None, description="Current turn_id for /meals and /bid_history")

    http_timeout_s: float = 10.0
    max_concurrency: int = 5

    # polling presets
    polling_mode: str = "normal"  # "low" | "normal" | "aggressive"

    # persistence
    sqlite_path: str = "hackapizza_dashboard.sqlite"
    persistence_enabled: bool = True
    persistence_flush_interval_s: float = 5.0

    # UI / security
    basic_auth_enabled: bool = False
    basic_auth_user: str = "admin"
    basic_auth_pass: str = "admin"
```

### Behavior

* Loaded from environment variables (standard BaseSettings behavior).
* UI must allow changing `restaurant_id`, `turn_id`, `polling_mode` at runtime (and restart tasks accordingly).

### Return values

* Instantiation returns config object; no side effects.

---

# 4) Core models (types you will use everywhere)

## 4.1 Common types

```python
# app/models/common.py
from dataclasses import dataclass
from enum import Enum
from typing import Any

class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    CRIT = "crit"

class GamePhase(str, Enum):
    SPEAKING = "speaking"
    CLOSED_BID = "closed_bid"
    WAITING = "waiting"
    SERVING = "serving"
    STOPPED = "stopped"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class TimeRangeStats:
    p50_ms: float | None
    p95_ms: float | None
    error_rate_1m: float
    error_rate_5m: float

@dataclass(frozen=True)
class JsonSafe:
    value: Any  # must be JSON-serializable or handled by encoder
```

---

# 5) State store specification (single source of truth)

## 5.1 `StateStore`

### Signature

```python
# app/core/state.py
import asyncio
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
    sse_blocked: bool = False  # 409
    last_sse_error: str | None = None

    # endpoint health
    endpoint_status: dict[str, EndpointStatus] = field(default_factory=dict)
    endpoint_checks: dict[str, deque[EndpointCheck]] = field(default_factory=dict)  # per endpoint ring buffer

    # latest business snapshots
    restaurants_overview: RestaurantsOverview | None = None
    my_restaurant: RestaurantDetail | None = None
    my_menu: MenuSnapshot | None = None
    market: MarketSnapshot | None = None
    meals: MealsSnapshot | None = None
    bid_history: BidHistorySnapshot | None = None

    # live events
    events: deque[SSEEvent] = field(default_factory=lambda: deque(maxlen=2000))

    # derived outputs
    active_alerts: dict[str, AlertInstance] = field(default_factory=dict)
```

### Behavior

* All read/write operations that mutate the store must be done under `async with state.lock`.
* For performance: reads in UI can either:

  * also use the lock, or
  * use a `state.snapshot()` method (recommended) that copies the needed pieces atomically.

### Methods (required)

```python
class StateStore:
    async def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot used by UI/API."""
```

**Implementation brief**

* Under lock, shallow-copy the latest objects (or `.model_dump()` if pydantic).
* Avoid returning huge raw payloads by default; provide “details endpoints” for raw payload.

---

# 6) HTTP client wrapper (instrumentation built-in)

## 6.1 `HackapizzaHttpClient`

### Signature

```python
# app/clients/hackapizza_http.py
from dataclasses import dataclass
from typing import Any
import httpx

@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status_code: int | None
    latency_ms: float
    payload: Any | None
    error: str | None

class HackapizzaHttpClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: float) -> None: ...

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> HttpResult:
        """GET JSON endpoint. Always returns HttpResult; never raises for network/HTTP errors."""

    async def post_json(self, path: str, body: Any, params: dict[str, Any] | None = None) -> HttpResult:
        """POST JSON endpoint. Always returns HttpResult; never raises for network/HTTP errors."""
```

### Behavior

* Adds `x-api-key` header to every request.
* Measures latency (`time.monotonic()`).
* On non-JSON response, set `ok=False`, `payload=None`, `error="json_decode_error: ..."`.

### Return values

* `HttpResult.ok=True` only if:

  * HTTP status in 200..299
  * JSON parsed successfully

---

# 7) Endpoint registry + poller subsystem

## 7.1 Endpoint spec model

### Signature

```python
# app/collectors/registry.py
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

Summarizer = Callable[[Any], dict[str, Any]]

@dataclass(frozen=True)
class EndpointSpec:
    name: str
    method: str                 # "GET"
    path_template: str          # e.g. "/restaurant/{restaurant_id}"
    default_interval_s: float
    requires_restaurant_id: bool
    requires_turn_id: bool
    enabled: Callable[[dict[str, Any]], bool]   # receives runtime context, decides if active
    summarizer: Summarizer
```

### Behavior

* `enabled(ctx)` controls phase-aware polling (optional).
* `path_template` rendered using runtime context (restaurant_id, turn_id).

### Return values

* Pure data structure.

---

## 7.2 Registry builder

### Signature

```python
def build_endpoint_registry() -> list[EndpointSpec]:
    """Return all endpoint specs to monitor. Must include all public endpoints + private ones when allowed."""
```

### Required endpoints + suggested intervals

* `/restaurants` (2s)
* `/market/entries` (3s)
* `/recipes` (90s)
* `/restaurant/{restaurant_id}` (2s)
* `/restaurant/{restaurant_id}/menu` (7s)
* `/meals` (enabled only if turn_id set; 1–2s during serving else 6–10s)
* `/bid_history` (enabled only if turn_id set; 6–10s during/after closed_bid else disabled)

**Implementation brief**

* Provide `enabled(ctx)` functions that check:

  * ctx has turn_id
  * ctx phase
* Provide “polling_mode” multiplier (aggressive halves intervals; low doubles).

---

## 7.3 Polling scheduler

### Signature

```python
# app/collectors/poller.py
import asyncio
from app.core.state import StateStore
from app.clients.hackapizza_http import HackapizzaHttpClient
from app.collectors.registry import EndpointSpec

class PollScheduler:
    def __init__(self, state: StateStore, client: HackapizzaHttpClient, specs: list[EndpointSpec],
                 max_concurrency: int) -> None: ...

    async def run_forever(self, ctx_provider: Callable[[], dict[str, Any]]) -> None:
        """
        Main loop. Schedules per-endpoint poll tasks based on next_run timestamps.
        Must handle jitter, backoff on 429, and never crash the process.
        """

    async def poll_once(self, spec: EndpointSpec, ctx: dict[str, Any]) -> None:
        """Poll one endpoint, update endpoint health, store summary into StateStore."""
```

### Behavior of `run_forever`

* Maintains next-run time per endpoint
* Applies jitter: ±10% interval
* Uses `asyncio.Semaphore(max_concurrency)` for concurrent requests
* Implements backoff per endpoint:

  * if status 429: increase interval exponentially (cap, e.g. 60s)
  * on success: decay backoff gradually back to default interval
* Must continue even if one endpoint keeps failing

### Behavior of `poll_once`

1. Render URL path from `path_template` + ctx
2. Call `client.get_json(...)`
3. Create `EndpointCheck`
4. Update `state.endpoint_status[name]` and append to `state.endpoint_checks[name]`
5. If ok: call `spec.summarizer(payload)` and store into correct state field (e.g. restaurants overview)

### Return values

* Both return `None` (side effects: update StateStore)

---

## 7.4 Endpoint health models

### Signature

```python
# app/models/endpoint.py
from dataclasses import dataclass
from typing import Any
from app.models.common import Severity

@dataclass(frozen=True)
class EndpointCheck:
    ts_ms: int
    ok: bool
    status_code: int | None
    latency_ms: float
    error: str | None
    payload_summary: dict[str, Any] | None

@dataclass(frozen=True)
class EndpointStatus:
    name: str
    severity: Severity
    last_check: EndpointCheck | None
    stats_1m: dict[str, Any]   # computed p50/p95/error rate
    stats_5m: dict[str, Any]
    last_ok_ts_ms: int | None
```

### Behavior

* Severity rule (suggested):

  * CRIT: last check not ok OR last_ok older than 30s
  * WARN: p95 latency above threshold OR error_rate_1m > X
  * OK otherwise

---

# 8) SSE listener + internal event bus

## 8.1 SSE event model

### Signature

```python
# app/models/sse.py
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class SSEEvent:
    ts_ms: int
    type: str
    data: Any
    raw: str | None = None  # optional raw line for debugging
```

---

## 8.2 SSE listener

### Signature

```python
# app/clients/hackapizza_sse.py
from typing import AsyncIterator
import aiohttp

class SSEListener:
    def __init__(self, base_url: str, api_key: str) -> None: ...

    async def connect(self, restaurant_id: int) -> AsyncIterator[SSEEvent]:
        """
        Connect to /events/{restaurant_id} and yield SSEEvent objects.
        Must handle:
          - initial "data: connected"
          - JSON events with {type, data}
        On fatal errors (401/403/404/409) raise a typed exception (see below).
        """

class SSEAuthError(Exception): ...
class SSEForbiddenError(Exception): ...
class SSENotFoundError(Exception): ...
class SSEAlreadyConnectedError(Exception): ...  # 409
```

### Behavior

* Parses SSE framing:

  * accumulate lines until blank line
  * extract `data:` content
* If `data == "connected"`: yield event type `"connected"` with data `None`
* Else parse JSON:

  * expect keys `type` and `data`
  * if parse fails: yield type `"parse_error"` with raw content (do not crash)

### Return values

* Async iterator of `SSEEvent`

---

## 8.3 Event bus (optional but recommended)

### Signature

```python
# app/core/event_bus.py
import asyncio
from typing import Any

class EventBus:
    def __init__(self) -> None: ...

    def subscribe(self) -> "asyncio.Queue[Any]":
        """Return a queue that receives published events."""

    def unsubscribe(self, queue: "asyncio.Queue[Any]") -> None:
        """Stop sending events to this queue."""

    async def publish(self, event: Any) -> None:
        """Fan-out to all subscriber queues (non-blocking best-effort)."""
```

### Behavior

* Each subscriber gets its own queue.
* Publish should not block forever; use `put_nowait` and drop if full (or cap queues).

### Return values

* Subscribe returns a queue.

---

## 8.4 SSE runner task

### Signature

```python
# app/main.py or app/collectors/sse_runner.py
async def sse_runner(state: StateStore, bus: EventBus, listener: SSEListener,
                     restaurant_id_provider: Callable[[], int]) -> None:
    """
    Maintain a single upstream SSE connection.
    Updates StateStore:
      - phase
      - last_heartbeat_ms
      - events ring buffer
      - sse_connected / sse_blocked / last_sse_error
    Publishes events to EventBus for UI/ws relay.
    """
```

### Behavior

* Connect loop with backoff on network errors
* On `SSEAlreadyConnectedError`:

  * set `state.sse_blocked=True`
  * set `state.sse_connected=False`
  * sleep longer (e.g. 30s) before retry
* When receiving event:

  * append to state.events
  * if type `game_phase_changed`: set state.phase
  * if type `heartbeat`: set state.last_heartbeat_ms = data["ts"]
  * publish to bus

---

# 9) Summarizers + business models (robust parsing)

Because payloads aren’t fully specified, summarizers must:

* accept `Any`
* return small dict summaries
* optionally return parsed structured models (pydantic/dataclasses)

## 9.1 Restaurants overview

### Model

```python
# app/models/restaurant.py
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
```

### Summarizer signature

```python
# app/collectors/summarizers.py
def summarize_restaurants(payload: Any) -> tuple[RestaurantsOverview | None, dict[str, Any]]:
    """
    Parse GET /restaurants payload.
    Returns (model, summary_dict).
    Never raises; if parse fails return (None, {"parse_ok": False, "error": "..."}).
    """
```

### Behavior

* Determine if payload is list; if not, mark parse_ok False
* Extract fields with heuristics:

  * id: `row.get("id")` or `row.get("restaurantId")`
  * balance: `row.get("balance")` or `row.get("money")`
  * name: `row.get("name")` or `row.get("restaurantName")`
* Keep `raw=row` always

### Return values

* `RestaurantsOverview` or `None`
* summary dict includes:

  * `count`
  * `top_balance` (if available)
  * `parse_ok`

---

## 9.2 My restaurant detail

### Model

```python
@dataclass(frozen=True)
class RestaurantDetail:
    ts_ms: int
    restaurant_id: int
    balance: float | None
    reputation: float | None
    is_open: bool | None
    inventory: dict[str, float]  # ingredient -> quantity (best-effort)
    raw: dict[str, Any]
```

### Summarizer signature

```python
def summarize_restaurant_detail(payload: Any, restaurant_id: int) -> tuple[RestaurantDetail | None, dict[str, Any]]:
    """Parse GET /restaurant/:id."""
```

### Behavior

* Extract inventory from likely structures:

  * dict mapping name->qty
  * list of {name, quantity}
* Normalize quantities to float where possible
* Summary dict:

  * `balance`, `reputation`, `is_open`
  * `inventory_items`, `inventory_total_qty`

---

## 9.3 Menu snapshot

### Model

```python
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
```

### Summarizer signature

```python
def summarize_menu(payload: Any, restaurant_id: int) -> tuple[MenuSnapshot | None, dict[str, Any]]:
    """Parse GET /restaurant/:id/menu."""
```

### Summary dict

* `items_count`, `avg_price`, `min_price`, `max_price`, `parse_ok`

---

## 9.4 Market snapshot

### Model

```python
# app/models/market.py
from dataclasses import dataclass

@dataclass(frozen=True)
class MarketEntry:
    entry_id: int | None
    side: str | None        # BUY / SELL
    ingredient: str | None
    quantity: float | None
    price: float | None
    owner_id: int | None
    raw: dict

@dataclass(frozen=True)
class MarketSnapshot:
    ts_ms: int
    entries: list[MarketEntry]
```

### Summarizer signature

```python
def summarize_market_entries(payload: Any) -> tuple[MarketSnapshot | None, dict[str, Any]]:
    """Parse GET /market/entries."""
```

### Summary dict

* `active_count`, `buy_count`, `sell_count`, `parse_ok`

---

## 9.5 Meals snapshot (turn-dependent)

### Model

```python
# app/models/meals.py
from dataclasses import dataclass

@dataclass(frozen=True)
class MealRequest:
    client_id: str | None
    client_name: str | None
    order_text: str | None
    executed: bool | None
    raw: dict

@dataclass(frozen=True)
class MealsSnapshot:
    ts_ms: int
    turn_id: int
    restaurant_id: int
    meals: list[MealRequest]
```

### Summarizer signature

```python
def summarize_meals(payload: Any, turn_id: int, restaurant_id: int) -> tuple[MealsSnapshot | None, dict[str, Any]]:
    """Parse GET /meals."""
```

### Summary dict

* `total`, `pending`, `executed`, `parse_ok`

---

## 9.6 Bid history snapshot (turn-dependent)

### Model

```python
# app/models/bids.py
from dataclasses import dataclass

@dataclass(frozen=True)
class BidRow:
    ingredient: str | None
    bid: float | None
    quantity: float | None
    restaurant_id: int | None
    raw: dict

@dataclass(frozen=True)
class BidHistorySnapshot:
    ts_ms: int
    turn_id: int
    bids: list[BidRow]
```

### Summarizer signature

```python
def summarize_bid_history(payload: Any, turn_id: int) -> tuple[BidHistorySnapshot | None, dict[str, Any]]:
    """Parse GET /bid_history?turn_id=..."""
```

---

# 10) Derived aggregators (team vs others, market intel, throughput, bids)

These compute additional metrics from snapshots and store into state (or compute on demand for UI).

## 10.1 Ranking aggregator

### Signature

```python
# app/aggregators/ranking.py
from dataclasses import dataclass

@dataclass(frozen=True)
class RankingRow:
    rank: int
    restaurant_id: int | None
    name: str | None
    balance: float | None
    reputation: float | None
    is_open: bool | None

@dataclass(frozen=True)
class RankingSummary:
    ts_ms: int
    rows: list[RankingRow]
    my_rank: int | None
    delta_to_leader: float | None
    delta_to_next: float | None
    delta_to_prev: float | None

def compute_ranking(overview: RestaurantsOverview | None, my_restaurant_id: int) -> RankingSummary | None:
    """
    Sort restaurants by balance descending (fallback to 0 when missing).
    Compute my rank and deltas.
    Return None if overview missing or empty.
    """
```

### Behavior

* Must handle missing balances.
* Must produce stable ordering (tie-breaker: restaurant_id).

### Return values

* `RankingSummary` or `None`

---

## 10.2 Market intelligence aggregator

### Signature

```python
# app/aggregators/market_intel.py
from dataclasses import dataclass

@dataclass(frozen=True)
class IngredientMarketStats:
    ingredient: str
    best_buy_price: float | None   # cheapest SELL entry (you can buy)
    best_sell_price: float | None  # highest BUY entry (you can sell)
    median_price: float | None
    buy_volume: float
    sell_volume: float

@dataclass(frozen=True)
class MarketIntel:
    ts_ms: int
    per_ingredient: list[IngredientMarketStats]
    opportunities: list[dict]   # simple dicts describing “cheap buy” / “good sell”

def compute_market_intel(market: MarketSnapshot | None, *,
                         cheap_buy_thresholds: dict[str, float] | None = None,
                         good_sell_thresholds: dict[str, float] | None = None) -> MarketIntel | None:
    """
    Build per-ingredient stats and detect opportunities.
    Threshold dictionaries are optional. If missing, compute generic opportunities based on percentiles.
    """
```

### Behavior

* Best buy price: min price among SELL entries
* Best sell price: max price among BUY entries
* Median: median among all prices for ingredient
* Opportunities:

  * cheap supply: best_buy_price < threshold
  * good demand: best_sell_price > threshold
* If no thresholds: use heuristic:

  * cheap if best_buy < 25th percentile
  * good sell if best_sell > 75th percentile

---

## 10.3 Meals KPI aggregator

### Signature

```python
# app/aggregators/meals_kpi.py
from dataclasses import dataclass

@dataclass(frozen=True)
class MealsKPI:
    ts_ms: int
    total: int
    pending: int
    executed: int
    execution_rate: float  # executed/total
    backlog_severity: str  # "ok"|"warn"|"crit"

def compute_meals_kpi(meals: MealsSnapshot | None) -> MealsKPI | None:
    """Compute backlog and rate; return None if meals missing."""
```

### Behavior

* backlog severity thresholds (suggested):

  * pending >= 10 -> crit
  * pending >= 5 -> warn
  * else ok

---

## 10.4 Bid intelligence aggregator

### Signature

```python
# app/aggregators/bids_intel.py
from dataclasses import dataclass

@dataclass(frozen=True)
class IngredientBidStats:
    ingredient: str
    min_bid: float | None
    median_bid: float | None
    max_bid: float | None
    sample_count: int

@dataclass(frozen=True)
class BidIntel:
    ts_ms: int
    per_ingredient: list[IngredientBidStats]

def compute_bid_intel(bid_history: BidHistorySnapshot | None) -> BidIntel | None:
    """Compute per-ingredient bid distributions."""
```

---

# 11) Alerts engine (rules + lifecycle)

## 11.1 Alert models

### Signature

```python
# app/models/alerts.py
from dataclasses import dataclass
from app.models.common import Severity

@dataclass
class AlertInstance:
    alert_id: str
    severity: Severity
    title: str
    message: str
    first_seen_ms: int
    last_seen_ms: int
    acknowledged: bool = False
```

---

## 11.2 Alert rules interface

### Signature

```python
# app/alerts/rules.py
from typing import Protocol
from app.core.state import StateStore
from app.models.alerts import AlertInstance

class AlertRule(Protocol):
    rule_id: str
    def evaluate(self, snap: dict) -> AlertInstance | None:
        """
        Evaluate rule against a snapshot (from state.snapshot()).
        Return AlertInstance if firing, else None.
        """
```

---

## 11.3 Alert engine task

### Signature

```python
# app/alerts/engine.py
import asyncio
from app.core.state import StateStore
from app.alerts.rules import AlertRule

class AlertEngine:
    def __init__(self, state: StateStore, rules: list[AlertRule]) -> None: ...

    async def run_forever(self, interval_s: float = 1.0) -> None:
        """
        Every interval:
          - snapshot state
          - evaluate all rules
          - update state.active_alerts (create/update/resolve)
        Never raises.
        """

    async def acknowledge(self, alert_id: str) -> bool:
        """Mark alert as acknowledged. Return True if it existed."""
```

### Core rules to implement (minimum)

1. `auth_error` – any endpoint last status 401
2. `sse_disconnected` – `sse_connected=False` and not blocked
3. `heartbeat_stale` – last heartbeat older than 15s
4. `critical_endpoint_down` – `/restaurants` or `/restaurant/:id` failing for >30s
5. `rate_limit_storm` – multiple 429 in 60s
6. `serving_closed` – phase=serving & is_open=False
7. `serving_no_menu` – phase=serving & menu empty
8. `serving_backlog` – pending meals high

---

# 12) MCP client + Actions console (optional but spec’d)

## 12.1 MCP models

### Signature

```python
# app/models/mcp.py
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class McpToolResult:
    ok: bool
    latency_ms: float
    is_error: bool
    content_text: str | None
    raw: Any
    error: str | None
```

---

## 12.2 MCP client

### Signature

```python
# app/clients/hackapizza_mcp.py
from typing import Any
from app.clients.hackapizza_http import HackapizzaHttpClient
from app.models.mcp import McpToolResult

class HackapizzaMcpClient:
    def __init__(self, http: HackapizzaHttpClient) -> None: ...

    async def call_tool(self, tool_name: str, tool_args: dict[str, Any]) -> McpToolResult:
        """
        POST /mcp JSON-RPC tools/call.
        Must never raise; always returns McpToolResult.
        """
```

### Behavior

* Builds JSON-RPC body:

  * method: `"tools/call"`
  * params includes tool name + args (match server expectations)
* Parses response:

  * `result.isError`
  * `result.content[0].text` if present

### Return values

* McpToolResult with `ok` meaning HTTP call ok + JSON parsed
* `is_error` meaning tool-level error

---

## 12.3 Phase guard function (must-have)

### Signature

```python
# app/core/utils.py
from app.models.common import GamePhase

def is_tool_allowed(phase: GamePhase, tool_name: str) -> bool:
    """
    Enforce phase matrix from spec.
    Return True if the action is allowed now.
    """
```

### Behavior

Implement the phase table you provided:

* save_menu allowed: speaking, closed_bid, waiting
* closed_bid tool allowed: closed_bid
* prepare_dish/serve_dish allowed: serving
* market tools mostly allowed except stopped
* update_restaurant_is_open only to close during serving, etc.

---

# 13) Persistence layer (SQLite)

## 13.1 SQLite adapter

### Signature

```python
# app/storage/sqlite.py
import sqlite3
from typing import Any

class SQLiteStore:
    def __init__(self, path: str) -> None: ...

    def init_schema(self) -> None:
        """Create tables if missing."""

    def insert_endpoint_check(self, row: dict[str, Any]) -> None: ...
    def insert_sse_event(self, row: dict[str, Any]) -> None: ...
    def insert_snapshot(self, table: str, ts_ms: int, payload: dict[str, Any]) -> None: ...
```

### Behavior

* Use WAL mode for concurrent reads:

  * `PRAGMA journal_mode=WAL;`
* Store payloads as JSON strings.
* Keep schema minimal and append-only.

---

## 13.2 Repository layer (async-friendly)

### Signature

```python
# app/storage/repository.py
import asyncio
from app.storage.sqlite import SQLiteStore

class Repository:
    def __init__(self, sqlite: SQLiteStore) -> None: ...

    async def flush_from_state(self, snap: dict) -> None:
        """
        Persist key pieces (endpoint checks, latest snapshots, sse events).
        Must be safe to call frequently.
        """
```

### Behavior

* Runs blocking SQLite calls in a thread pool:

  * `await asyncio.to_thread(...)`

---

## 13.3 Persistence task

### Signature

```python
async def persistence_runner(state: StateStore, repo: Repository, interval_s: float) -> None:
    """Periodically snapshot state and flush to SQLite."""
```

---

# 14) FastAPI endpoints (for export + debugging + WS relay)

Even though NiceGUI can access state directly, these endpoints are valuable for:

* exporting data
* agent integration
* debugging from CLI

## 14.1 API router

### Required endpoints

#### `GET /api/state`

```python
async def get_state(state: StateStore) -> dict:
    """Return state.snapshot() output."""
```

#### `GET /api/endpoint/{name}/checks?limit=200`

```python
async def get_endpoint_checks(name: str, limit: int, state: StateStore) -> dict:
    """
    Return last N EndpointCheck rows for an endpoint.
    If name not found: 404.
    """
```

#### `POST /api/config`

```python
from pydantic import BaseModel

class UpdateConfig(BaseModel):
    restaurant_id: int | None = None
    turn_id: int | None = None
    polling_mode: str | None = None

async def update_config(body: UpdateConfig, state: StateStore, config_mutator: Callable[[UpdateConfig], None]) -> dict:
    """
    Update runtime config + restart collectors if needed.
    Return updated config.
    """
```

#### `POST /api/alerts/{alert_id}/ack`

```python
async def ack_alert(alert_id: str, engine: AlertEngine) -> dict:
    """Acknowledge alert; return {ok: bool}."""
```

#### Optional: WebSocket `GET /ws/events`

```python
from fastapi import WebSocket

async def ws_events(websocket: WebSocket, bus: EventBus) -> None:
    """
    Subscribe to EventBus and forward JSON-serialized SSE events to client.
    """
```

---

# 15) NiceGUI UI specification (pages + refresh mechanics)

## 15.1 UI bootstrapping

### Signature

```python
# app/ui/app_ui.py
from app.core.state import StateStore
from app.alerts.engine import AlertEngine
from app.clients.hackapizza_mcp import HackapizzaMcpClient

def build_ui(state: StateStore, alert_engine: AlertEngine, mcp: HackapizzaMcpClient | None) -> None:
    """
    Define NiceGUI pages, navigation, and global top bar.
    Must not start background tasks (done in app startup).
    """
```

### Behavior

* Creates global navigation menu to pages
* Creates top bar with:

  * SSE status
  * phase
  * last heartbeat age
  * config editor (restaurant_id, turn_id, polling mode)
* Uses `ui.timer(1.0, ...)` to refresh visible components from `state.snapshot()`

### Return values

* None (UI side effects)

---

## 15.2 Refresh strategy (simple and robust)

Use refreshable blocks:

```python
from nicegui import ui

@ui.refreshable
def overview_panel(snap: dict): ...
```

Then a timer:

```python
def setup_refresh(state: StateStore):
    async def tick():
        snap = await state.snapshot()
        overview_panel.refresh(snap)
        # refresh other visible panels
    ui.timer(1.0, lambda: ui.run_async(tick()))
```

This avoids complex client-side streaming while still being “live”.

---

## 15.3 Page specs

### Overview page (`ui/pages/overview.py`)

**Must show**

* My rank, delta to leader
* Balance/reputation cards
* Phase, SSE, heartbeat age
* Pending meals count
* Active alerts list

**Functions**

```python
def build_overview_page(state: StateStore) -> None:
    """Define route / and compose overview widgets."""
```

---

### Endpoint health page (`endpoint_health.py`)

**Must show**

* Grid of endpoint cards
* Click -> details (latency chart using plotly, or table of last checks)

**Functions**

```python
def build_endpoint_health_page(state: StateStore) -> None: ...
def render_endpoint_card(ep_status: dict) -> None: ...
def render_endpoint_detail(checks: list[dict]) -> None: ...
```

---

### Competition page (`competition.py`)

**Must show**

* Ranking table (from ranking aggregator)
* Chart: my balance vs top N (if you store timeseries; else use current snapshot only)
* Nearest rivals + deltas

**Functions**

```python
def build_competition_page(state: StateStore) -> None: ...
```

---

### Serving page (`serving.py`)

**Must show**

* Pending meals table + executed
* Throughput KPIs
* Live SSE feed filtered to serving events

**Functions**

```python
def build_serving_page(state: StateStore) -> None: ...
```

---

### Market page (`market.py`)

**Must show**

* Market entries table (filterable)
* Per-ingredient best buy/sell + median
* Opportunities panel

**Functions**

```python
def build_market_page(state: StateStore) -> None: ...
```

---

### Bids page (`bids.py`)

**Must show**

* Per ingredient distribution stats
* Bid history table

**Functions**

```python
def build_bids_page(state: StateStore) -> None: ...
```

---

### Events & messages (`events.py`)

**Must show**

* Searchable event log
* Highlight direct messages (`new_message`)

**Functions**

```python
def build_events_page(state: StateStore) -> None: ...
```

---

### Actions (`actions.py`) (optional MCP)

**Must show**

* Phase guard status for each tool
* Form inputs for tool args
* Confirmations for destructive actions
* Tool call result log

**Functions**

```python
def build_actions_page(state: StateStore, mcp: HackapizzaMcpClient) -> None: ...

async def call_tool_with_guard(state: StateStore, mcp: HackapizzaMcpClient,
                               tool_name: str, args: dict) -> dict:
    """
    Validate phase/tool allowed, call MCP, update state with call result, return result dict.
    """
```

---

### Exports (`exports.py`)

**Must show**

* Buttons to download JSON:

  * state snapshot
  * endpoint checks
  * events log
* Optionally export CSV from SQLite

**Functions**

```python
def build_exports_page(state: StateStore) -> None: ...
```

---

# 16) “Monitor all public endpoints” — explicit list of what to implement

For each public endpoint you must implement:

1. **EndpointSpec entry** in registry
2. **poller integration**
3. **summarizer**
4. **state field update** (assign parsed model)
5. **UI visualization** (at least card + a page section)

### Mapping table (implementation requirement)

* `/restaurants` → `StateStore.restaurants_overview`
* `/market/entries` → `StateStore.market`
* `/recipes` → keep cached somewhere (either add `StateStore.recipes_cache`)
* `/restaurant/{id}` (my id) → `StateStore.my_restaurant`
* `/restaurant/{id}/menu` (my id) → `StateStore.my_menu`
* `/meals` → `StateStore.meals` (only if turn_id set)
* `/bid_history` → `StateStore.bid_history` (only if turn_id set)

Also add **synthetic “endpoint”** for SSE:

* name: `"sse:/events/{restaurant_id}"`
* status computed from `state.sse_connected`, `state.last_heartbeat_ms`

---

# 17) Startup / shutdown lifecycle

## 17.1 App entrypoint

### Signature

```python
# app/main.py
from fastapi import FastAPI
from nicegui import ui
import asyncio

def create_app() -> FastAPI:
    """
    Create FastAPI app, attach NiceGUI, init state, start background tasks.
    Return FastAPI app for uvicorn.
    """
```

### Behavior

* Initialize:

  * config
  * state
  * http client
  * sse listener
  * bus
  * poll scheduler
  * alert engine
  * persistence repo (optional)
* Register startup event:

  * start tasks via `asyncio.create_task(...)`
* Register shutdown event:

  * cancel tasks gracefully

### Return values

* FastAPI app instance

---

# 18) Testing specification (minimum viable)

## Unit tests

* Summarizers: given sample payloads, produce expected summaries
* Ranking: sorting + deltas
* Market intel: best buy/sell and medians
* Alert rules: snapshots triggering properly

## Integration tests (optional)

* Mock server (httpx MockTransport) returning:

  * 401, 429, invalid JSON
* Ensure poller backoff works and state updates

---

# 19) Implementation checklist (developer “definition of done”)

You are done when:

* ✅ Dashboard shows **live phase + heartbeat** from SSE (or clearly shows SSE blocked)
* ✅ Endpoint Health page shows:

  * status code, latency, error rate for each endpoint
* ✅ Overview shows:

  * my rank & delta to leader
  * balance/reputation
  * pending meals
  * active alerts
* ✅ Competition shows sortable ranking table
* ✅ Market shows best prices and opportunities
* ✅ Alerts fire on SSE disconnect, 401, 429 storms, serving closed/backlog
* ✅ Changing restaurant_id/turn_id in UI updates collectors correctly

---

If you want, I can follow up with a **“nearly-code” skeleton** (actual Python module stubs with docstrings and placeholder implementations) matching these signatures, so your team can fill in the payload parsing and UI styling quickly.
