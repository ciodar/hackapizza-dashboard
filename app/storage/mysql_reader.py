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
