"""Background poller that tails MySQL tables written by main.py and feeds StateStore."""

import asyncio
import logging
import time
from typing import Any

from app.core.state import StateStore
from app.models.common import GamePhase
from app.models.sse import SSEEvent
from app.storage.mysql_reader import MySQLReader
from app.collectors.summarizers import (
    summarize_meals, summarize_restaurants, summarize_market_entries,
    summarize_bid_history, summarize_menu, summarize_restaurant_detail,
    summarize_recipe_stats, summarize_ingredient_bid_stats,
)

logger = logging.getLogger(__name__)

PHASE_MAP: dict[str, GamePhase] = {
    "speaking": GamePhase.SPEAKING,
    "closed_bid": GamePhase.CLOSED_BID,
    "waiting": GamePhase.WAITING,
    "serving": GamePhase.SERVING,
    "stopped": GamePhase.STOPPED,
}

# If no heartbeat arrives within this window, mark SSE as disconnected
HEARTBEAT_TIMEOUT_S = 60.0

# Refresh business data every N poll cycles (~5 seconds at default 1s interval)
BUSINESS_REFRESH_EVERY = 5


class MySQLPoller:
    def __init__(
        self,
        state: StateStore,
        reader: MySQLReader,
        runtime_config: dict[str, Any],
        poll_interval_s: float = 1.0,
    ) -> None:
        self._state = state
        self._reader = reader
        self._runtime_config = runtime_config
        self._poll_interval_s = poll_interval_s
        self._last_sse_id: int = 0
        self._last_phase_id: int = 0
        self._poll_count: int = 0

    async def run_forever(self) -> None:
        try:
            await self._bootstrap()
            logger.info(
                f"MySQLPoller bootstrapped (sse_id={self._last_sse_id}, phase_id={self._last_phase_id})"
            )
        except Exception as exc:
            logger.warning(f"MySQLPoller bootstrap failed: {exc}")

        while True:
            try:
                await self._poll_once()
            except Exception as exc:
                logger.warning(f"MySQLPoller poll error: {exc}")
                async with self._state.lock:
                    self._state.db_connected = False
                    self._state.last_db_error = f"MySQL unavailable: {exc}"
            await asyncio.sleep(self._poll_interval_s)

    # ──────────────────────────────────────────────
    # Bootstrap: seed cursors and current state from DB
    # ──────────────────────────────────────────────

    async def _bootstrap(self) -> None:
        max_ids = await self._reader.fetch_max_ids()
        self._last_sse_id = max_ids["sse_events"]
        self._last_phase_id = max_ids["phase_transitions"]

        # Seed current phase
        latest_phase = await self._reader.fetch_latest_phase_transition()
        if latest_phase:
            phase = PHASE_MAP.get(latest_phase["to_phase"], GamePhase.UNKNOWN)
            turn_number = latest_phase.get("turn_number") or 0
            async with self._state.lock:
                self._state.phase = phase
                self._state.turn_number = turn_number

        # Seed turn_id and turn_number from latest game_started event
        game_started = await self._reader.fetch_latest_game_started()
        if game_started:
            data = game_started.get("event_json") or {}
            turn_id = data.get("turn_id")
            turn_number = game_started.get("turn_number") or 0
            async with self._state.lock:
                if turn_id is not None:
                    self._state.turn_id = turn_id
                    self._runtime_config["turn_id"] = turn_id
                    logger.info(f"MySQLPoller seeded turn_id={turn_id} turn_number={turn_number}")
                if turn_number > self._state.turn_number:
                    self._state.turn_number = turn_number

        # Seed last_heartbeat_ms from latest heartbeat event in DB
        hb_row = await self._reader.try_fetch_rows(
            "SELECT ts FROM sse_events WHERE event_type='heartbeat' ORDER BY id DESC LIMIT 1"
        )
        if hb_row:
            ts = hb_row[0].get("ts")
            if ts is not None:
                import time as _time
                ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else int(_time.time() * 1000)
                async with self._state.lock:
                    self._state.last_heartbeat_ms = ts_ms
                    logger.info(f"MySQLPoller seeded last_heartbeat_ms from DB")

    async def _poll_once(self) -> None:
        self._poll_count += 1
        await self._process_sse_events()
        await self._process_phase_transitions()
        await self._check_heartbeat_timeout()
        if self._poll_count % BUSINESS_REFRESH_EVERY == 0:
            await self._refresh_business_snapshots()
        # Any successful poll means MySQL is reachable
        async with self._state.lock:
            self._state.db_connected = True
            self._state.last_db_error = None

    async def _process_sse_events(self) -> None:
        rows = await self._reader.fetch_new_sse_events(self._last_sse_id)
        if not rows:
            return

        now_ms = int(time.time() * 1000)
        async with self._state.lock:
            for row in rows:
                # Convert MySQL DATETIME to ms timestamp
                ts = row.get("ts")
                if hasattr(ts, "timestamp"):
                    ts_ms = int(ts.timestamp() * 1000)
                else:
                    ts_ms = now_ms

                event = SSEEvent(ts_ms=ts_ms, type=row["event_type"], data=row["event_json"])
                self._state.events.append(event)

                etype = row["event_type"]
                turn_number = row.get("turn_number") or 0

                if etype == "heartbeat":
                    self._state.last_heartbeat_ms = ts_ms
                    self._state.db_connected = True
                    self._state.last_db_error = None

                elif etype == "game_started":
                    data = row["event_json"] or {}
                    turn_id = data.get("turn_id")
                    if turn_id is not None:
                        self._state.turn_id = turn_id
                        self._runtime_config["turn_id"] = turn_id
                        logger.info(f"New turn started: turn_id={turn_id} turn_number={turn_number}")
                    self._state.turn_number = turn_number

                elif etype == "game_reset":
                    self._state.turn_number = 0
                    self._state.turn_id = None
                    self._runtime_config["turn_id"] = None

                # Keep turn_number monotonically updated from any event
                if turn_number > self._state.turn_number:
                    self._state.turn_number = turn_number

        self._last_sse_id = rows[-1]["id"]

    async def _process_phase_transitions(self) -> None:
        rows = await self._reader.fetch_new_phase_transitions(self._last_phase_id)
        if not rows:
            return

        async with self._state.lock:
            for row in rows:
                phase = PHASE_MAP.get(row["to_phase"], GamePhase.UNKNOWN)
                self._state.phase = phase
                turn_number = row.get("turn_number") or 0
                if turn_number > self._state.turn_number:
                    self._state.turn_number = turn_number

        self._last_phase_id = rows[-1]["id"]

    async def _check_heartbeat_timeout(self) -> None:
        async with self._state.lock:
            if self._state.last_heartbeat_ms:
                age_s = (int(time.time() * 1000) - self._state.last_heartbeat_ms) / 1000.0
                if age_s > HEARTBEAT_TIMEOUT_S and self._state.db_connected:
                    self._state.db_connected = False
                    logger.warning(f"No heartbeat for {age_s:.0f}s — marking DB disconnected")

    # ──────────────────────────────────────────────
    # Business data refresh from DB tables
    # ──────────────────────────────────────────────

    async def _refresh_business_snapshots(self) -> None:
        restaurant_id = self._runtime_config.get("restaurant_id", 1)
        turn_number = self._state.turn_number
        turn_id = self._state.turn_id

        await self._refresh_my_restaurant(restaurant_id, turn_number)
        await self._refresh_menu(turn_number)
        await self._refresh_meals(turn_number, turn_id, restaurant_id)
        await self._refresh_restaurants()
        await self._refresh_market(turn_number)
        if turn_id:
            await self._refresh_bid_history(turn_id)
            await self._refresh_recipe_stats(turn_id)
            await self._refresh_ingredient_bid_stats(turn_id)
        await self._refresh_decisions(turn_number)
        await self._refresh_mcp_calls(turn_number)
        await self._refresh_recipes()
        await self._refresh_snapshots_history()
        await self._refresh_agent_prompts()
        await self._refresh_ingredient_bid_history()
        await self._refresh_phase_transitions()
        await self._refresh_restaurant_state_turns()

    async def _refresh_meals(self, turn_number: int, turn_id: int | None, restaurant_id: int) -> None:
        if not turn_number:
            return
        # First try a dedicated meals table written by the agent
        rows = await self._reader.try_fetch_rows(
            "SELECT * FROM meals WHERE turn_id = %s AND restaurant_id = %s ORDER BY id",
            (turn_id, restaurant_id) if turn_id else (0, restaurant_id),
        )
        if rows is None and turn_id:
            rows = await self._reader.try_fetch_rows(
                "SELECT * FROM meals WHERE turn_id = %s ORDER BY id", (turn_id,)
            )
        if rows is not None:
            model, _ = summarize_meals(rows, turn_id or 0, restaurant_id)
            if model:
                async with self._state.lock:
                    self._state.meals = model
                return
        # Fallback: build from client_spawned SSE events
        meal_dicts = await self._reader.fetch_meals_for_turn(turn_number)
        if meal_dicts:
            model, _ = summarize_meals(meal_dicts, turn_id or 0, restaurant_id)
            if model:
                async with self._state.lock:
                    self._state.meals = model

    async def _refresh_restaurants(self) -> None:
        # Try legacy `restaurants` table first; if missing, derive from SSE game_started
        rows = await self._reader.try_fetch_rows("SELECT * FROM restaurants ORDER BY id")
        if rows is not None:
            model, _ = summarize_restaurants(rows)
            if model:
                async with self._state.lock:
                    self._state.restaurants_overview = model
            return
        # Fallback: build single-restaurant overview from latest snapshot
        # (at minimum we can show our own restaurant)

    async def _refresh_market(self, turn_number: int) -> None:
        # Try legacy `market_entries` table first
        rows = await self._reader.try_fetch_rows(
            "SELECT * FROM market_entries WHERE active = 1 OR active IS NULL ORDER BY id"
        )
        if rows is None:
            rows = await self._reader.try_fetch_rows("SELECT * FROM market_entries ORDER BY id")
        if rows is not None:
            model, _ = summarize_market_entries(rows)
            if model:
                async with self._state.lock:
                    self._state.market = model

    async def _refresh_my_restaurant(self, restaurant_id: int, turn_number: int | None = None) -> None:
        # Try restaurant_state_turns first (most accurate, agent-written)
        rst_rows = await self._reader.fetch_restaurant_state_turns(limit=1)
        if rst_rows:
            row = rst_rows[0]
            data = {
                "balance": float(row["balance"]) if row.get("balance") is not None else None,
                "reputation": float(row["reputation"]) if row.get("reputation") is not None else None,
                "is_open": bool(row.get("is_open")),
            }
            model, _ = summarize_restaurant_detail(data, restaurant_id)
            if model:
                async with self._state.lock:
                    self._state.my_restaurant = model
                return
        # Try actual snapshots table (kind in priority order)
        for kind in ("restaurant_post_bid", "restaurant", "turn_end"):
            snap = await self._reader.fetch_latest_snapshot(kind, turn_number or None)
            if snap and snap.get("data_json"):
                data = snap["data_json"]
                model, _ = summarize_restaurant_detail(data, restaurant_id)
                if model:
                    async with self._state.lock:
                        self._state.my_restaurant = model
                    return
        # Fallback: legacy tables
        rows = await self._reader.try_fetch_rows(
            "SELECT * FROM restaurant_state WHERE restaurant_id = %s ORDER BY id DESC LIMIT 1",
            (restaurant_id,),
        )
        if rows is None:
            rows = await self._reader.try_fetch_rows(
                "SELECT * FROM restaurants WHERE id = %s LIMIT 1", (restaurant_id,)
            )
        if rows:
            model, _ = summarize_restaurant_detail(rows[0], restaurant_id)
            if model:
                async with self._state.lock:
                    self._state.my_restaurant = model

    async def _refresh_menu(self, turn_number: int | None = None) -> None:
        restaurant_id = self._runtime_config.get("restaurant_id", 1)
        # Try decisions table (menu_plan decision contains the chosen menu)
        decisions = await self._reader.fetch_decisions(
            decision_type="menu_plan", turn_number=turn_number, limit=1
        )
        if decisions:
            data = decisions[0].get("data_json") or {}
            # menu decision data_json has items list: [{name, price}, ...]
            items = data.get("items") or data.get("menu") or []
            if items and isinstance(items, list):
                rows = [{"name": it.get("name") or it.get("dish", ""), "price": it.get("price")} for it in items]
                model, _ = summarize_menu(rows, restaurant_id)
                if model:
                    async with self._state.lock:
                        self._state.my_menu = model
                    return
        # Fallback: legacy tables
        rows = await self._reader.try_fetch_rows(
            "SELECT * FROM menu_items WHERE restaurant_id = %s ORDER BY id", (restaurant_id,)
        )
        if rows is None:
            rows = await self._reader.try_fetch_rows(
                "SELECT * FROM menu WHERE restaurant_id = %s ORDER BY id", (restaurant_id,)
            )
        if rows is None:
            return
        model, _ = summarize_menu(rows, restaurant_id)
        if model:
            async with self._state.lock:
                self._state.my_menu = model

    async def _refresh_bid_history(self, turn_id: int) -> None:
        rows = await self._reader.try_fetch_rows(
            "SELECT * FROM bid_history WHERE turn_id = %s ORDER BY id", (turn_id,)
        )
        if rows is None:
            rows = await self._reader.try_fetch_rows(
                "SELECT * FROM bids WHERE turn_id = %s ORDER BY id", (turn_id,)
            )
        if rows is None:
            return
        model, _ = summarize_bid_history(rows, turn_id)
        if model:
            async with self._state.lock:
                self._state.bid_history = model

    async def _refresh_recipe_stats(self, turn_id: int) -> None:
        rows = await self._reader.fetch_recipe_stats(turn_id=turn_id)
        if not rows:
            return
        stats, _ = summarize_recipe_stats(rows)
        async with self._state.lock:
            self._state.recipe_stats_current = stats

    async def _refresh_ingredient_bid_stats(self, turn_id: int) -> None:
        rows = await self._reader.fetch_ingredient_bid_stats(turn_id=turn_id)
        if not rows:
            return
        stats, _ = summarize_ingredient_bid_stats(rows)
        async with self._state.lock:
            self._state.ingredient_bid_stats_current = stats

    async def _refresh_decisions(self, turn_number: int | None = None) -> None:
        rows = await self._reader.fetch_decisions(turn_number=turn_number, limit=50)
        if rows is not None:
            async with self._state.lock:
                self._state.decisions_recent = rows

    async def _refresh_mcp_calls(self, turn_number: int | None = None) -> None:
        rows = await self._reader.fetch_mcp_calls(turn_number=turn_number, limit=100)
        if rows is not None:
            async with self._state.lock:
                self._state.mcp_calls_recent = rows

    async def _refresh_snapshots_history(self) -> None:
        """Fetch per-turn restaurant snapshots for balance/reputation history."""
        # Primary: restaurant_state_turns table (written by agent at end of each turn)
        rst_rows = await self._reader.fetch_restaurant_state_turns(limit=30)
        if rst_rows:
            history = []
            for row in reversed(rst_rows):  # oldest first
                history.append({
                    "turn_number": row.get("turn_number") or 0,
                    "balance": float(row["balance"]) if row.get("balance") is not None else None,
                    "reputation": float(row["reputation"]) if row.get("reputation") is not None else None,
                    "clients_served": None,
                    "ts": row.get("ts"),
                })
            async with self._state.lock:
                self._state.snapshots_history = history
            return
        # Fallback: snapshots table
        rows = await self._reader.fetch_snapshots("restaurant_post_bid", limit=30)
        if not rows:
            rows = await self._reader.fetch_snapshots("restaurant", limit=30)
        if not rows:
            rows = await self._reader.fetch_snapshots("turn_end", limit=30)
        if rows:
            history = []
            seen_turns = set()
            for row in reversed(rows):  # oldest first
                turn = row.get("turn_number") or 0
                if turn in seen_turns:
                    continue
                seen_turns.add(turn)
                data = row.get("data_json") or {}
                history.append({
                    "turn_number": turn,
                    "balance": data.get("balance"),
                    "reputation": data.get("reputation"),
                    "clients_served": data.get("clients_served"),
                    "ts": row.get("ts"),
                })
            async with self._state.lock:
                self._state.snapshots_history = history

    async def _refresh_recipes(self) -> None:
        rows = await self._reader.fetch_recipes_with_ingredients()
        if rows:
            async with self._state.lock:
                self._state.recipes_cache = rows

    async def _refresh_agent_prompts(self) -> None:
        rows = await self._reader.fetch_agent_prompts(limit=50)
        if rows is not None:
            async with self._state.lock:
                self._state.agent_prompts_recent = rows

    async def _refresh_ingredient_bid_history(self) -> None:
        rows = await self._reader.fetch_ingredient_bid_history(limit=300)
        if rows is not None:
            async with self._state.lock:
                self._state.ingredient_bid_history = rows

    async def _refresh_phase_transitions(self) -> None:
        rows = await self._reader.fetch_phase_transitions_recent(limit=50)
        if rows is not None:
            async with self._state.lock:
                self._state.phase_transitions_recent = rows

    async def _refresh_restaurant_state_turns(self) -> None:
        """Fetch restaurant_state_turns for per-turn history."""
        rows = await self._reader.fetch_restaurant_state_turns(limit=30)
        if rows is not None:
            history = []
            for row in reversed(rows):  # oldest first
                history.append({
                    "turn_number": row.get("turn_number") or 0,
                    "turn_id": row.get("turn_id"),
                    "balance": float(row["balance"]) if row.get("balance") is not None else None,
                    "reputation": float(row["reputation"]) if row.get("reputation") is not None else None,
                    "is_open": bool(row.get("is_open")),
                    "ts": row.get("ts"),
                })
            async with self._state.lock:
                self._state.restaurant_state_history = history
