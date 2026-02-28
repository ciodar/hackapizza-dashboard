import asyncio
import logging

from app.alerts.rules import evaluate_all_rules
from app.core.state import StateStore
from app.models.alerts import AlertInstance

logger = logging.getLogger(__name__)

class AlertEngine:
    def __init__(self, state: StateStore) -> None:
        self._state = state

    async def run_forever(self, interval_s: float = 2.0) -> None:
        while True:
            try:
                snap = await self._state.snapshot()
                async with self._state.lock:
                    existing = dict(self._state.active_alerts)
                new_alerts = evaluate_all_rules(snap, existing)
                async with self._state.lock:
                    self._state.active_alerts = new_alerts
            except Exception as e:
                logger.error(f"Alert engine error: {e}")
            await asyncio.sleep(interval_s)

    async def acknowledge(self, alert_id: str) -> bool:
        async with self._state.lock:
            if alert_id in self._state.active_alerts:
                self._state.active_alerts[alert_id].acknowledged = True
                return True
        return False
