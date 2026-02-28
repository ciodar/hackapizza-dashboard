import asyncio
import time
from app.storage.sqlite import SQLiteStore

class Repository:
    def __init__(self, sqlite: SQLiteStore) -> None:
        self._sqlite = sqlite

    async def flush_from_state(self, snap: dict) -> None:
        ts_ms = int(time.time() * 1000)
        try:
            await asyncio.to_thread(self._sqlite.insert_snapshot, "state", ts_ms, {
                "phase": snap.get("phase"),
                "my_restaurant": snap.get("my_restaurant"),
                "restaurants_count": len(snap.get("restaurants") or []),
            })
        except Exception:
            pass
