"""Background poller that tails MySQL tables written by main.py and feeds StateStore."""

import asyncio
import logging
import time
from typing import Any

from app.core.state import StateStore
from app.models.common import GamePhase
from app.models.sse import SSEEvent
from app.storage.mysql_reader import MySQLReader

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
                    self._state.sse_connected = False
                    self._state.last_sse_error = f"MySQL unavailable: {exc}"
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

    # ──────────────────────────────────────────────
    # Poll loop
    # ──────────────────────────────────────────────

    async def _poll_once(self) -> None:
        await self._process_sse_events()
        await self._process_phase_transitions()
        await self._check_heartbeat_timeout()

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
                    self._state.sse_connected = True
                    self._state.last_sse_error = None

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
                if age_s > HEARTBEAT_TIMEOUT_S and self._state.sse_connected:
                    self._state.sse_connected = False
                    logger.warning(f"No heartbeat for {age_s:.0f}s — marking SSE disconnected")
