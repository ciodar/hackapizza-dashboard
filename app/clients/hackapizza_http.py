import time
import httpx
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status_code: int | None
    latency_ms: float
    payload: Any | None
    error: str | None

class HackapizzaHttpClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_s
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"x-api-key": api_key},
            timeout=timeout_s,
        )

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> HttpResult:
        t0 = time.monotonic()
        try:
            r = await self._client.get(path, params=params)
            latency_ms = (time.monotonic() - t0) * 1000
            if r.status_code >= 200 and r.status_code < 300:
                try:
                    payload = r.json()
                    return HttpResult(ok=True, status_code=r.status_code, latency_ms=latency_ms, payload=payload, error=None)
                except Exception as e:
                    return HttpResult(ok=False, status_code=r.status_code, latency_ms=latency_ms, payload=None, error=f"json_decode_error: {e}")
            return HttpResult(ok=False, status_code=r.status_code, latency_ms=latency_ms, payload=None, error=f"http_{r.status_code}")
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            return HttpResult(ok=False, status_code=None, latency_ms=latency_ms, payload=None, error=str(e))

    async def post_json(self, path: str, body: Any, params: dict[str, Any] | None = None) -> HttpResult:
        t0 = time.monotonic()
        try:
            r = await self._client.post(path, json=body, params=params)
            latency_ms = (time.monotonic() - t0) * 1000
            if r.status_code >= 200 and r.status_code < 300:
                try:
                    payload = r.json()
                    return HttpResult(ok=True, status_code=r.status_code, latency_ms=latency_ms, payload=payload, error=None)
                except Exception as e:
                    return HttpResult(ok=False, status_code=r.status_code, latency_ms=latency_ms, payload=None, error=f"json_decode_error: {e}")
            return HttpResult(ok=False, status_code=r.status_code, latency_ms=latency_ms, payload=None, error=f"http_{r.status_code}")
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            return HttpResult(ok=False, status_code=None, latency_ms=latency_ms, payload=None, error=str(e))

    async def close(self) -> None:
        await self._client.aclose()
