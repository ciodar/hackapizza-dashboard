import asyncio
import json
import time
from typing import AsyncIterator

import aiohttp

from app.models.sse import SSEEvent

class SSEAuthError(Exception): pass
class SSEForbiddenError(Exception): pass
class SSENotFoundError(Exception): pass
class SSEAlreadyConnectedError(Exception): pass

class SSEListener:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def connect(self, restaurant_id: int) -> AsyncIterator[SSEEvent]:
        url = f"{self._base_url}/events/{restaurant_id}"
        headers = {"x-api-key": self._api_key, "Accept": "text/event-stream"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=None, sock_read=60)) as resp:
                if resp.status == 401:
                    raise SSEAuthError("401 Unauthorized")
                if resp.status == 403:
                    raise SSEForbiddenError("403 Forbidden")
                if resp.status == 404:
                    raise SSENotFoundError("404 Not Found")
                if resp.status == 409:
                    raise SSEAlreadyConnectedError("409 Already Connected")
                
                buffer = []
                async for line_bytes in resp.content:
                    line = line_bytes.decode("utf-8").rstrip("\r\n")
                    if line == "":
                        # process accumulated event
                        data_lines = [l[len("data:"):].strip() for l in buffer if l.startswith("data:")]
                        buffer = []
                        for raw_data in data_lines:
                            ts_ms = int(time.time() * 1000)
                            if raw_data == "connected":
                                yield SSEEvent(ts_ms=ts_ms, type="connected", data=None, raw=raw_data)
                            else:
                                try:
                                    obj = json.loads(raw_data)
                                    etype = obj.get("type", "unknown")
                                    edata = obj.get("data", {})
                                    yield SSEEvent(ts_ms=ts_ms, type=etype, data=edata, raw=raw_data)
                                except Exception:
                                    yield SSEEvent(ts_ms=ts_ms, type="parse_error", data=raw_data, raw=raw_data)
                    else:
                        buffer.append(line)
