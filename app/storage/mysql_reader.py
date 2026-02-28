"""Async MySQL reader that tails tables written by the main.py agent."""

import json
import logging
from typing import Any

import aiomysql

logger = logging.getLogger(__name__)


class MySQLReader:
    def __init__(self, host: str, port: int, user: str, password: str, db: str) -> None:
        self._config = dict(host=host, port=port, user=user, password=password, db=db)
        self._pool: aiomysql.Pool | None = None

    async def connect(self) -> None:
        self._pool = await aiomysql.create_pool(
            minsize=1, maxsize=3, autocommit=True, **self._config
        )
        logger.info("MySQLReader connected")

    async def close(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    async def fetch_max_ids(self) -> dict[str, int]:
        """Return current MAX(id) for each table — used to bootstrap cursor."""
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COALESCE(MAX(id), 0) FROM sse_events")
                sse_max = (await cur.fetchone())[0]
                await cur.execute("SELECT COALESCE(MAX(id), 0) FROM phase_transitions")
                phase_max = (await cur.fetchone())[0]
        return {"sse_events": sse_max, "phase_transitions": phase_max}

    async def fetch_new_sse_events(self, since_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, ts, event_type, event_json, phase, turn_number "
                    "FROM sse_events WHERE id > %s ORDER BY id ASC LIMIT 200",
                    (since_id,),
                )
                rows = await cur.fetchall()
        result = []
        for row in rows:
            row = dict(row)
            if isinstance(row.get("event_json"), str):
                try:
                    row["event_json"] = json.loads(row["event_json"])
                except Exception:
                    row["event_json"] = {}
            result.append(row)
        return result

    async def fetch_new_phase_transitions(self, since_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, ts, from_phase, to_phase, turn_number "
                    "FROM phase_transitions WHERE id > %s ORDER BY id ASC LIMIT 100",
                    (since_id,),
                )
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fetch_latest_game_started(self) -> dict[str, Any] | None:
        """Fetch the most recent game_started event to seed turn_id and turn_number."""
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT event_json, turn_number FROM sse_events "
                    "WHERE event_type = 'game_started' ORDER BY id DESC LIMIT 1"
                )
                row = await cur.fetchone()
        if row is None:
            return None
        row = dict(row)
        if isinstance(row.get("event_json"), str):
            try:
                row["event_json"] = json.loads(row["event_json"])
            except Exception:
                row["event_json"] = {}
        return row

    async def fetch_latest_phase_transition(self) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT to_phase, turn_number FROM phase_transitions ORDER BY id DESC LIMIT 1"
                )
                row = await cur.fetchone()
        return dict(row) if row else None

    async def fetch_meals_for_turn(self, turn_number: int) -> list[dict[str, Any]]:
        """Build meals list from client_spawned SSE events for the given turn_number."""
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, event_json FROM sse_events "
                    "WHERE event_type = 'client_spawned' AND turn_number = %s ORDER BY id",
                    (turn_number,),
                )
                rows = await cur.fetchall()
        meals = []
        for row in rows:
            data = row.get("event_json") or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}
            meals.append({
                "client_id": data.get("client_id") or data.get("clientId") or str(row["id"]),
                "client_name": data.get("clientName") or data.get("client_name"),
                "order": data.get("orderText") or data.get("order_text") or data.get("order"),
                "executed": data.get("executed", False),
            })
        return meals

    async def try_fetch_rows(self, query: str, params: tuple = ()) -> list[dict[str, Any]] | None:
        """Execute a query and return rows, or None if the table/query fails."""
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(query, params)
                    rows = await cur.fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return None

    # ──────────────────────────────────────────────
    # Methods for actual agent-written tables
    # ──────────────────────────────────────────────

    async def fetch_latest_snapshot(self, kind: str, turn_number: int | None = None) -> dict[str, Any] | None:
        """Fetch the most recent snapshot of a given kind (optionally for a turn)."""
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if turn_number:
                    await cur.execute(
                        "SELECT id, ts, kind, data_json, phase, turn_number "
                        "FROM snapshots WHERE kind=%s AND turn_number=%s ORDER BY id DESC LIMIT 1",
                        (kind, turn_number),
                    )
                else:
                    await cur.execute(
                        "SELECT id, ts, kind, data_json, phase, turn_number "
                        "FROM snapshots WHERE kind=%s ORDER BY id DESC LIMIT 1",
                        (kind,),
                    )
                row = await cur.fetchone()
        if row is None:
            return None
        row = dict(row)
        if isinstance(row.get("data_json"), str):
            try:
                row["data_json"] = json.loads(row["data_json"])
            except Exception:
                row["data_json"] = {}
        return row

    async def fetch_snapshots(self, kind: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recent snapshots of a given kind, newest first."""
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, ts, kind, data_json, phase, turn_number "
                    "FROM snapshots WHERE kind=%s ORDER BY id DESC LIMIT %s",
                    (kind, limit),
                )
                rows = await cur.fetchall()
        result = []
        for row in rows:
            row = dict(row)
            if isinstance(row.get("data_json"), str):
                try:
                    row["data_json"] = json.loads(row["data_json"])
                except Exception:
                    row["data_json"] = {}
            result.append(row)
        return result

    async def fetch_decisions(
        self, decision_type: str | None = None, turn_number: int | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch recent decisions, optionally filtered by type and/or turn."""
        conditions = []
        params: list[Any] = []
        if decision_type:
            conditions.append("decision_type=%s")
            params.append(decision_type)
        if turn_number is not None:
            conditions.append("turn_number=%s")
            params.append(turn_number)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    f"SELECT id, ts, agent_name, decision_type, data_json, phase, turn_number "
                    f"FROM decisions {where} ORDER BY id DESC LIMIT %s",
                    tuple(params),
                )
                rows = await cur.fetchall()
        result = []
        for row in rows:
            row = dict(row)
            if isinstance(row.get("data_json"), str):
                try:
                    row["data_json"] = json.loads(row["data_json"])
                except Exception:
                    row["data_json"] = {}
            result.append(row)
        return result

    async def fetch_mcp_calls(
        self, tool_name: str | None = None, turn_number: int | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch recent MCP calls, optionally filtered."""
        conditions = []
        params: list[Any] = []
        if tool_name:
            conditions.append("tool_name=%s")
            params.append(tool_name)
        if turn_number is not None:
            conditions.append("turn_number=%s")
            params.append(turn_number)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    f"SELECT id, ts, tool_name, args_json, result_json, is_error, latency_ms, phase, turn_number "
                    f"FROM mcp_calls {where} ORDER BY id DESC LIMIT %s",
                    tuple(params),
                )
                rows = await cur.fetchall()
        result = []
        for row in rows:
            row = dict(row)
            for col in ("args_json", "result_json"):
                if isinstance(row.get(col), str):
                    try:
                        row[col] = json.loads(row[col])
                    except Exception:
                        pass
            result.append(row)
        return result

    async def fetch_recipes_with_ingredients(self) -> list[dict[str, Any]]:
        """Return all recipes with their ingredient list joined in."""
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT r.id AS recipe_id, r.name AS recipe_name,
                           r.prestige, r.preparation_time_ms,
                           i.name AS ingredient_name, ri.quantity
                    FROM recipes r
                    LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
                    LEFT JOIN ingredients i ON i.id = ri.ingredient_id
                    ORDER BY r.name, i.name
                    """
                )
                rows = await cur.fetchall()
        # Group by recipe
        recipes: dict[int, dict] = {}
        for row in rows:
            row = dict(row)
            rid = row["recipe_id"]
            if rid not in recipes:
                recipes[rid] = {
                    "id": rid,
                    "name": row["recipe_name"],
                    "prestige": row["prestige"],
                    "preparation_time_ms": row["preparation_time_ms"],
                    "ingredients": {},
                }
            if row["ingredient_name"]:
                recipes[rid]["ingredients"][row["ingredient_name"]] = row["quantity"]
        return list(recipes.values())

    async def fetch_recipe_stats(self, turn_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch recipe_stats rows, joined with recipe name."""
        params: list[Any] = []
        where = ""
        if turn_id is not None:
            where = "WHERE rs.turn_id=%s"
            params.append(turn_id)
        params.append(limit)
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    f"""
                    SELECT rs.turn_id, r.name AS recipe_name, r.prestige,
                           rs.num_requests, rs.num_served,
                           rs.avg_price, rs.min_price, rs.max_price
                    FROM recipe_stats rs
                    JOIN recipes r ON r.id = rs.recipe_id
                    {where}
                    ORDER BY rs.num_requests DESC, r.name
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fetch_agent_prompts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent agent_prompts rows, newest first."""
        rows = await self.try_fetch_rows(
            "SELECT id, ts, agent_name, system_prompt, input_prompt, output_json, phase, turn_number "
            "FROM agent_prompts ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        if rows is None:
            return []
        result = []
        for row in rows:
            if isinstance(row.get("output_json"), str):
                try:
                    row["output_json"] = json.loads(row["output_json"])
                except Exception:
                    pass
            result.append(row)
        return result

    async def fetch_ingredient_bid_history(self, limit: int = 300) -> list[dict[str, Any]]:
        """Fetch ingredient_bid_stats across ALL turns (for cross-turn trend view)."""
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT ibs.turn_id, i.name AS ingredient_name,
                           ibs.avg_price_paid, ibs.min_price_paid, ibs.max_price_paid,
                           ibs.total_quantity
                    FROM ingredient_bid_stats ibs
                    JOIN ingredients i ON i.id = ibs.ingredient_id
                    ORDER BY ibs.turn_id ASC, i.name
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fetch_blog_articles(self, category: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch blog articles from the blog_articles table, optionally filtered by category."""
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    if category:
                        await cur.execute(
                            """
                            SELECT id, guid, title, slug, category, author, pub_date, summary, content, fetched_at
                            FROM blog_articles
                            WHERE category = %s
                            ORDER BY pub_date DESC
                            LIMIT %s
                            """,
                            (category, limit),
                        )
                    else:
                        await cur.execute(
                            """
                            SELECT id, guid, title, slug, category, author, pub_date, summary, content, fetched_at
                            FROM blog_articles
                            ORDER BY pub_date DESC
                            LIMIT %s
                            """,
                            (limit,),
                        )
                    rows = await cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"fetch_blog_articles failed: {e}")
            return []

    async def fetch_phase_transitions_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent phase_transitions rows, newest first."""
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, ts, from_phase, to_phase, turn_number "
                    "FROM phase_transitions ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fetch_restaurant_state_turns(self, limit: int = 30) -> list[dict[str, Any]]:
        """Fetch restaurant state snapshots per turn from restaurant_state_turns, newest first."""
        rows = await self.try_fetch_rows(
            "SELECT id, turn_number, turn_id, balance, reputation, is_open, ts "
            "FROM restaurant_state_turns ORDER BY turn_number DESC LIMIT %s",
            (limit,),
        )
        return rows or []

    async def fetch_ingredient_bid_stats(self, turn_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch ingredient_bid_stats rows joined with ingredient name."""
        params: list[Any] = []
        where = ""
        if turn_id is not None:
            where = "WHERE ibs.turn_id=%s"
            params.append(turn_id)
        params.append(limit)
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    f"""
                    SELECT ibs.turn_id, i.name AS ingredient_name,
                           ibs.avg_price_paid, ibs.min_price_paid, ibs.max_price_paid,
                           ibs.total_quantity
                    FROM ingredient_bid_stats ibs
                    JOIN ingredients i ON i.id = ibs.ingredient_id
                    {where}
                    ORDER BY ibs.total_quantity DESC, i.name
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
