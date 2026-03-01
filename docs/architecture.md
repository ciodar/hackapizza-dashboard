# Hackapizza Dashboard — Architecture & Strategy Guide

> **Audience**: Hackathon judges evaluating technical implementation, and team members maintaining the solution.

---

## 1. System Overview

The **Hackapizza Dashboard** is a real-time monitoring and observability layer built for the Hackapizza 2.0 competition. It reads data that the main game agent writes to a shared **MySQL database** and presents it through a live web UI (FastAPI + NiceGUI).

```
┌────────────────────────┐         ┌──────────────────────┐
│  Game Agent (main.py)  │──writes──▶  MySQL Database      │
│  (datapizza-ai based)  │         │  - sse_events         │
└────────────────────────┘         │  - phase_transitions  │
                                   │  - decisions          │
                                   │  - mcp_calls          │
                                   │  - snapshots          │
                                   │  - restaurant_state_  │
                                   │    turns              │
                                   │  - recipes / meals    │
                                   │  - blog_articles      │
                                   │  - agent_prompts      │
                                   └──────────┬───────────┘
                                              │ reads (polling)
                                   ┌──────────▼───────────┐
                                   │  Dashboard App        │
                                   │  ┌─────────────────┐  │
                                   │  │  MySQLPoller     │  │  (tails DB every 1s)
                                   │  └────────┬────────┘  │
                                   │           ▼           │
                                   │  ┌─────────────────┐  │
                                   │  │  StateStore      │  │  (in-memory, asyncio.Lock)
                                   │  └────────┬────────┘  │
                                   │     ┌─────┴──────┐    │
                                   │     ▼            ▼    │
                                   │  AlertEngine   NiceGUI │
                                   │  (rules)      (11 UI  │
                                   │               pages)  │
                                   └──────────────────────┘
```

### Runtime Model

- **Single asyncio process** running FastAPI + NiceGUI on port 8080.
- **Background tasks**: `MySQLPoller` (data ingestion), `AlertEngine` (rule evaluation every 2 s).
- All state access synchronized via `asyncio.Lock` to prevent race conditions.
- Optional **SQLite** persistence for local snapshots (`hackapizza_dashboard.sqlite`).

---

## 2. Agent Description, Tools & Communication

### 2.1 Agent Description

The game agent (external to this dashboard) is a **datapizza-ai based autonomous agent** that manages a galactic restaurant through the competition's MCP (Model Context Protocol) interface. It operates through a cycle of:

1. **Observing** game state (SSE events, HTTP endpoints)
2. **Deciding** strategy (via LLM calls through Regolo.ai)
3. **Acting** (MCP tool calls to the game server)

The dashboard monitors all three steps in real time.

### 2.2 MCP Tools Available to the Agent

The game server exposes 10 MCP tools via JSON-RPC POST to `/mcp`:

| Tool | Purpose | Phase Restrictions |
|------|---------|-------------------|
| `closed_bid` | Submit blind auction bids for ingredients | `closed_bid` only |
| `save_menu` | Set/update restaurant menu (dishes + prices) | `speaking`, `closed_bid`, `waiting` |
| `prepare_dish` | Start cooking a dish (consumes ingredients, takes time) | `serving` only |
| `serve_dish` | Deliver a prepared dish to a specific client | `serving` only |
| `create_market_entry` | Post a BUY or SELL offer on the inter-restaurant market | All active phases |
| `execute_transaction` | Accept another restaurant's market offer | All active phases |
| `delete_market_entry` | Remove your own market listing | All active phases |
| `update_restaurant_is_open` | Open/close the restaurant (close-only during serving) | All active phases |
| `send_message` | Send a direct message to another team | All active phases |
| `restaurant_info` / `get_meals` | Read-only queries | All phases incl. `stopped` |

The phase-tool matrix is enforced in `app/core/utils.py` (`PHASE_TOOL_MATRIX`) and is used by the dashboard to validate whether an agent action was legal for the current phase.

### 2.3 Communication Channels

**SSE (Server-Sent Events)** — The primary real-time channel:

| Event | Scope | Description |
|-------|-------|-------------|
| `game_started` | broadcast | New turn begins, carries `turn_id` |
| `game_phase_changed` | broadcast | Phase transition: speaking → closed_bid → waiting → serving → stopped |
| `client_spawned` | private | A new client arrives with an order |
| `preparation_complete` | private | A dish finished cooking |
| `message` | broadcast | Public message from any team |
| `new_message` | private | Direct message from another team |
| `heartbeat` | broadcast | Liveness check (epoch ms) |
| `game_reset` | broadcast | Full game state reset |

**Inter-Restaurant Messaging** — Via `send_message` MCP tool + `new_message` SSE event. Used during the `speaking` phase for diplomacy, alliance negotiation, and trade coordination.

**Market** — Public marketplace where all restaurants can see BUY/SELL offers. Created via `create_market_entry`, accepted via `execute_transaction`.

---

## 3. Memory Handling

### 3.1 In-Memory State (`StateStore`)

The `StateStore` dataclass in `app/core/state.py` is the **single source of truth** for the dashboard. It holds:

| Category | Fields | Source |
|----------|--------|--------|
| **Connectivity** | `phase`, `last_heartbeat_ms`, `db_connected` | MySQLPoller (SSE events table) |
| **Turn tracking** | `turn_number`, `turn_id` | `game_started` events |
| **Business snapshots** | `restaurants_overview`, `my_restaurant`, `my_menu`, `market`, `meals`, `bid_history` | DB tables, refreshed every 5 poll cycles (~5s) |
| **Agent telemetry** | `decisions_recent`, `mcp_calls_recent`, `agent_prompts_recent` | Agent-written DB tables |
| **Analytics** | `recipe_stats_current`, `ingredient_bid_stats_current`, `ingredient_bid_history` | Aggregated DB views |
| **History** | `snapshots_history`, `restaurant_state_history`, `phase_transitions_recent` | Per-turn snapshots |
| **Live events** | `events` (ring buffer, max 2000) | SSE events replayed from DB |
| **Alerts** | `active_alerts` | AlertEngine |
| **Content** | `blog_articles`, `recipes_cache` | DB tables |

**Concurrency**: All mutations happen under `async with state.lock`. UI reads use `state.snapshot()` which atomically copies all data and computes an MD5 fingerprint for change detection — preventing unnecessary UI refreshes.

### 3.2 MySQL as Shared Memory

The agent writes its observations, decisions, and actions into MySQL tables. The dashboard's `MySQLPoller` then tails these tables using cursor-based pagination (`WHERE id > last_seen_id`). Key tables:

| Table | Written by | Content |
|-------|-----------|---------|
| `sse_events` | Agent | All SSE events with JSON payload, phase, turn number |
| `phase_transitions` | Agent | Phase changes with from/to and turn number |
| `decisions` | Agent | Strategic decisions (menu plans, bid strategies, turn strategies) |
| `mcp_calls` | Agent | Every MCP tool invocation with args, result, latency, error status |
| `snapshots` | Agent | Periodic state snapshots (restaurant state, market, inventory) |
| `restaurant_state_turns` | Agent | Per-turn balance, reputation, open/closed status |
| `agent_prompts` | Agent | Full LLM prompts and responses (system + input + output) |
| `recipes` / `recipe_ingredients` / `ingredients` | Agent | Normalized recipe data |
| `recipe_stats` | Agent | Per-turn recipe performance (requests, served, prices) |
| `ingredient_bid_stats` | Agent | Per-turn ingredient bidding statistics |
| `blog_articles` | Agent | News/bios fetched from the hackablog |

### 3.3 SQLite Persistence (Local)

Optional local SQLite DB (`hackapizza_dashboard.sqlite`) stores:
- **Endpoint checks** — historical health of API calls
- **SSE events** — local copy of the event stream
- **Snapshots** — periodic state dumps

This serves as a backup and enables offline analysis.

### 3.4 Change Detection

The `snapshot()` method computes an MD5 fingerprint over all state fields (excluding `heartbeat_age_s` which changes every second). The `_changed` flag tells UI timers whether to trigger a re-render, minimizing wasted cycles.

---

## 4. Communication Handoff

### 4.1 Data Flow: Agent → Dashboard

```
Agent writes to MySQL
        │
        ▼
MySQLPoller._poll_once()  (every 1s)
   ├── _process_sse_events()      → state.events, state.phase, state.turn_id
   ├── _process_phase_transitions() → state.phase, state.turn_number
   ├── _check_heartbeat_timeout()   → state.db_connected
   └── _refresh_business_snapshots() (every 5 cycles)
          ├── _refresh_my_restaurant()
          ├── _refresh_menu()
          ├── _refresh_meals()
          ├── _refresh_restaurants()
          ├── _refresh_market()
          ├── _refresh_bid_history()
          ├── _refresh_recipe_stats()
          ├── _refresh_ingredient_bid_stats()
          ├── _refresh_decisions()
          ├── _refresh_mcp_calls()
          ├── _refresh_recipes()
          ├── _refresh_snapshots_history()
          ├── _refresh_agent_prompts()
          ├── _refresh_ingredient_bid_history()
          ├── _refresh_phase_transitions()
          ├── _refresh_restaurant_state_turns()
          └── _refresh_blog_articles()
```

### 4.2 Data Flow: Dashboard → UI

Each of the 11 NiceGUI pages uses a `ui.timer` (1.5–5s intervals) that calls `state.snapshot()` and re-renders only when `_changed == True`.

### 4.3 Phase-Driven Handoff

The turn lifecycle drives all handoffs:

```
speaking ──▶ closed_bid ──▶ waiting ──▶ serving ──▶ stopped
   │              │             │           │           │
   │  Negotiate   │  Submit     │  Finalize │  Cook &   │  Analyze
   │  alliances   │  blind      │  menu,    │  serve    │  results
   │  & trade     │  bids for   │  adjust   │  clients  │
   │              │  ingredients│  strategy │           │
```

When `MySQLPoller` detects a new `game_phase_changed` event, it updates `state.phase`, which propagates to all UI pages and the AlertEngine.

### 4.4 EventBus (Internal Pub/Sub)

The `EventBus` provides fire-and-forget fan-out:
- Subscribers get an `asyncio.Queue(maxsize=500)`.
- `publish()` uses `put_nowait()` — drops events silently if a subscriber's queue is full.
- Used to relay events from the poller to any internal consumers (e.g., future WebSocket relay).

---

## 5. Error Recovery

### 5.1 MySQL Connectivity

- **Heartbeat timeout**: If no heartbeat event arrives within 60 seconds, `MySQLPoller` marks `state.db_connected = False` and sets `state.last_db_error`.
- **Poll errors**: Each `_poll_once()` is wrapped in try/except. On failure, `db_connected` is set to `False` but the poller keeps running and retries on the next cycle (every 1s).
- **Bootstrap failure**: If the initial bootstrap fails (e.g., MySQL not yet available), it logs a warning and proceeds to the poll loop, which will succeed once MySQL comes online.

### 5.2 AlertEngine

The `AlertEngine` runs in a continuous loop (every 2s) and evaluates rules against the current state snapshot. Current alert rules:

| Alert ID | Severity | Trigger |
|----------|----------|---------|
| `db_disconnected` | CRIT | `db_connected == False` |
| `serving_closed` | CRIT | Phase is `serving` but restaurant is closed |
| `serving_no_menu` | CRIT | Phase is `serving` but menu is empty |
| `serving_backlog_crit` | CRIT | ≥ 10 pending meals |
| `serving_backlog_warn` | WARN | ≥ 5 pending meals |

Alerts are **persistent** (first_seen / last_seen timestamps), **acknowledgeable** via `POST /api/alerts/{id}/ack`, and **auto-cleared** when the condition resolves.

### 5.3 Defensive Parsing (Summarizers)

Every summarizer in `app/collectors/summarizers.py` follows the same pattern:
1. Accept `Any` as input (unknown/variable schemas)
2. Try multiple field name variants (`id` / `restaurantId` / `restaurant_id`)
3. Return `(None, {"parse_ok": False, "error": ...})` on failure — **never raise**
4. Use `_first(dict, *keys)` helper to pick the first non-None value
5. Gracefully handle JSON strings in DB columns (auto-parse)

### 5.4 Graceful Degradation

- **MySQLPoller** uses `try_fetch_rows()` which returns `None` on any DB error (missing table, query failure) — the poller skips that data source and continues.
- **Fallback chains** for restaurant data: `restaurant_state_turns` → `snapshots` (multiple kinds) → legacy `restaurant_state` table → `restaurants` table.
- **Menu fallback**: `decisions` table (menu_post_bid/menu_plan) → `menu_items` table → `menu` table.
- **Meals fallback**: dedicated `meals` table → `client_spawned` SSE events.

### 5.5 Task Lifecycle

- Background tasks are collected in `_tasks` list and cancelled on shutdown.
- `asyncio.gather(*_tasks, return_exceptions=True)` ensures clean shutdown even if tasks raise.

---

## 6. Smart Strategies

### 6.1 Bidding Strategy (Ingredient Auctions)

The dashboard provides intelligence for optimal bidding through several analytics:

**Bid Intel** (`app/aggregators/bids_intel.py`):
- Computes **min / median / max** bid per ingredient from `bid_history`.
- Cross-turn `ingredient_bid_history` tracks how prices evolve over time.
- The `ingredient_bid_stats` table (populated by the agent) provides per-turn: `avg_price_paid`, `min_price_paid`, `max_price_paid`, `total_quantity`.

**Smart bidding approach**:
1. **Historical price analysis**: Before each `closed_bid` phase, review `ingredient_bid_history` across turns to understand price trends for each ingredient.
2. **Competitor observation**: The `bid_history` endpoint reveals all teams' bids after each round — learn who overbids and who underbids.
3. **Marginal pricing**: Bid slightly above the historical median for critical ingredients, and below median for non-essential ones (avoid overpaying).
4. **Budget allocation**: Prioritize ingredients needed for high-prestige recipes with the best profit margin (cross-reference `recipe_stats` with ingredient costs).
5. **Scarcity detection**: If an ingredient's `total_quantity` is trending down across turns while demand stays constant, bid more aggressively.

### 6.2 Menu Ordering & Creation

**Recipe Stats** (`recipe_stats` table):
- Per-turn data: `num_requests`, `num_served`, `avg_price`, `min_price`, `max_price`, `prestige`.
- Reveals which recipes clients actually request vs. which the restaurant offers.

**Smart menu strategy**:
1. **Demand-driven menu**: Include recipes with highest `num_requests` across recent turns.
2. **Client archetype targeting**: Match menu to desired clientele:
   - **Esploratore Galattico**: Low-price, fast dishes (low prestige OK).
   - **Astrobarone**: Medium-high price, good quality, fast.
   - **Saggi del Cosmo**: Highest prestige, price not a concern.
   - **Famiglie Orbitali**: Balanced price-quality.
3. **Inventory awareness**: Only list recipes for which you can realistically acquire ingredients (check bid success rates for each ingredient).
4. **Dynamic menu updates**: The `save_menu` tool can be called during `speaking`, `closed_bid`, and `waiting` — update the menu after knowing your bid results.
5. **Preparation time budgeting**: Each recipe has a `preparation_time_ms` — ensure the menu's combined prep time fits within the serving phase duration.

### 6.3 Price Choice

**Market Intel** (`app/aggregators/market_intel.py`):
- Computes per-ingredient: `best_buy_price`, `best_sell_price`, `median_price`, buy/sell volume.
- Identifies **opportunities**: `cheap_supply` (below 25th percentile) and `good_demand` (above 75th percentile).

**Pricing strategy**:
1. **Cost-plus pricing**: Calculate ingredient cost per dish (sum of bid prices for required ingredients) + markup.
2. **Competitive benchmarking**: Other restaurants' menus are visible — price within the range of competitors for similar-quality dishes.
3. **Margin optimization**: Use `recipe_stats.avg_price` across all restaurants to gauge market rate, then price slightly below to attract more clients.
4. **Prestige-based tiers**:
   - Low prestige (1–3): Price 50–100 credits (budget clients).
   - Medium prestige (4–6): Price 100–250 credits (balanced clients).
   - High prestige (7–10): Price 250–600+ credits (luxury clients).
5. **Dynamic repricing**: Track `num_served / num_requests` ratio. If a dish is requested but not served (by competitors), you can charge more. If a dish goes unsold, lower the price.

### 6.4 Market Trading

The inter-restaurant market enables surplus monetization and shortage mitigation:

1. **Sell expiring ingredients**: Ingredients expire at end of turn — better to sell cheap than waste.
2. **Buy missing ingredients**: If the blind auction didn't yield enough, check the market before serving phase.
3. **Price arbitrage**: The `opportunities` array from `compute_market_intel()` flags ingredients trading below the 25th percentile (buy opportunity) or above the 75th percentile (sell opportunity).
4. **Timing**: Market entries expire at end of turn. Create sell orders early, buy orders late (when sellers get desperate).

### 6.5 Strategy Agent & Turn Guidance

The dashboard's Strategy page (`/strategy`) displays structured `turn_strategy` decisions from the agent. Each decision includes:
- **should_open** — whether to open the restaurant this turn (with reasoning).
- **agent_guidance** — per-sub-agent guidance strings for:
  - `menu` agent: what dishes to list, pricing changes
  - `bid` agent: which ingredients to prioritize, bid amounts
  - `market` agent: what to buy/sell on the open market
  - `service` agent: cooking order priorities, client handling
  - `allergy` agent: intolerance checks for the current client pool

This hierarchical strategy pattern (strategy agent → sub-agent guidance → MCP tool calls) enables coherent multi-phase decision making.

---

## 7. Dashboard UI Pages

| Page | Path | Purpose |
|------|------|---------|
| Overview | `/` | Balance, reputation, phase, alerts, menu badges, meal backlog |
| My Restaurant | `/restaurant` | Detailed inventory, open/close status, per-turn history |
| Serving | `/serving` | Live client orders, execution status |
| Market | `/market` | Active BUY/SELL listings, opportunity detection |
| Bids | `/bids` | Bid history per turn, ingredient price trends |
| Recipes | `/recipes` | Full recipe catalog with ingredients and prep times |
| Strategy | `/strategy` | Per-turn strategy decisions with per-agent guidance |
| Decisions | `/decisions` | Agent decision log (all types) |
| Events | `/events` | Raw SSE event stream |
| Agent Prompts | `/agent` | Full LLM prompt/response logs |
| Blog | `/blog` | In-game news articles and character bios |

---

## 8. Configuration

All settings via environment variables (`.env` file supported):

| Variable | Default | Description |
|----------|---------|-------------|
| `RESTAURANT_ID` | `1` | Your restaurant ID |
| `TURN_ID` | auto | Current turn (auto-detected from DB) |
| `MYSQL_HOST` | `127.0.0.1` | MySQL server host |
| `MYSQL_PORT` | `3306` | MySQL server port |
| `MYSQL_USER` | `appuser` | MySQL username |
| `MYSQL_PASSWORD` | `apppassword` | MySQL password |
| `MYSQL_DB` | `hackapizza` | MySQL database name |
| `MYSQL_POLL_INTERVAL_S` | `1.0` | Polling frequency (seconds) |
| `PERSISTENCE_ENABLED` | `True` | Enable SQLite local persistence |
| `UI_HOST` | `0.0.0.0` | Dashboard bind host |
| `UI_PORT` | `8080` | Dashboard bind port |

Runtime config updates via `POST /api/config` (restaurant_id, turn_id).
