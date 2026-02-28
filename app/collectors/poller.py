import asyncio
import random
import time
from collections import deque
from typing import Any, Callable

from app.clients.hackapizza_http import HackapizzaHttpClient
from app.collectors.registry import EndpointSpec
from app.collectors.summarizers import (
    summarize_restaurants, summarize_restaurant_detail, summarize_menu,
    summarize_market_entries, summarize_meals, summarize_bid_history, summarize_recipes,
)
from app.core.state import StateStore
from app.models.common import Severity
from app.models.endpoint import EndpointCheck, EndpointStatus

SUMMARIZER_MAP = {
    "restaurants": summarize_restaurants,
    "market": summarize_market_entries,
    "recipes": summarize_recipes,
    "restaurant_detail": summarize_restaurant_detail,
    "menu": summarize_menu,
    "meals": summarize_meals,
    "bid_history": summarize_bid_history,
}

MODE_MULTIPLIERS = {"low": 2.0, "normal": 1.0, "aggressive": 0.5}

class PollScheduler:
    def __init__(self, state: StateStore, client: HackapizzaHttpClient, specs: list[EndpointSpec], max_concurrency: int) -> None:
        self._state = state
        self._client = client
        self._specs = specs
        self._sem = asyncio.Semaphore(max_concurrency)
        self._backoff: dict[str, float] = {}
        self._next_run: dict[str, float] = {}

    async def run_forever(self, ctx_provider: Callable[[], dict[str, Any]]) -> None:
        now = time.monotonic()
        for spec in self._specs:
            self._next_run[spec.name] = now + random.uniform(0, spec.default_interval_s * 0.3)
        
        while True:
            ctx = ctx_provider()
            mode_mult = MODE_MULTIPLIERS.get(ctx.get("polling_mode", "normal"), 1.0)
            now = time.monotonic()
            tasks = []
            for spec in self._specs:
                if not spec.enabled(ctx):
                    continue
                if now >= self._next_run.get(spec.name, 0):
                    tasks.append(asyncio.create_task(self._poll_with_sem(spec, ctx)))
                    interval = (self._backoff.get(spec.name, spec.default_interval_s)) * mode_mult
                    jitter = random.uniform(-0.1, 0.1) * interval
                    self._next_run[spec.name] = now + interval + jitter
            await asyncio.sleep(0.1)

    async def _poll_with_sem(self, spec: EndpointSpec, ctx: dict[str, Any]) -> None:
        async with self._sem:
            try:
                await self.poll_once(spec, ctx)
            except Exception:
                pass

    async def poll_once(self, spec: EndpointSpec, ctx: dict[str, Any]) -> None:
        path = spec.path_template
        params: dict[str, Any] = {}
        restaurant_id = ctx.get("restaurant_id")
        turn_id = ctx.get("turn_id")
        
        if spec.requires_restaurant_id and restaurant_id:
            path = path.replace("{restaurant_id}", str(restaurant_id))
        if spec.requires_turn_id and turn_id:
            params["turn_id"] = turn_id
        if spec.name == "meals" and restaurant_id:
            params["restaurant_id"] = restaurant_id
        
        result = await self._client.get_json(path, params if params else None)
        ts_ms = int(time.time() * 1000)
        
        # compute stats from ring buffer
        checks_buf = self._state.endpoint_checks.setdefault(spec.name, deque(maxlen=300))
        now_ms = ts_ms
        checks_1m = [c for c in checks_buf if now_ms - c.ts_ms <= 60_000]
        checks_5m = [c for c in checks_buf if now_ms - c.ts_ms <= 300_000]
        
        def calc_stats(checks: list) -> dict:
            if not checks:
                return {"error_rate": 0.0, "avg_latency_ms": None, "p95_latency_ms": None, "count": 0}
            errors = sum(1 for c in checks if not c.ok)
            latencies = sorted(c.latency_ms for c in checks if c.ok)
            avg_lat = sum(latencies) / len(latencies) if latencies else None
            p95 = latencies[int(len(latencies) * 0.95)] if latencies else None
            return {"error_rate": errors / len(checks), "avg_latency_ms": avg_lat, "p95_latency_ms": p95, "count": len(checks)}
        
        # handle backoff for 429
        if result.status_code == 429:
            self._backoff[spec.name] = min(self._backoff.get(spec.name, spec.default_interval_s) * 2, 60.0)
        elif result.ok:
            current_backoff = self._backoff.get(spec.name, spec.default_interval_s)
            self._backoff[spec.name] = max(spec.default_interval_s, current_backoff * 0.8)
        
        # compute severity
        last_ok_ts = None
        if result.ok:
            last_ok_ts = ts_ms
        else:
            existing = self._state.endpoint_status.get(spec.name)
            if existing:
                last_ok_ts = existing.last_ok_ts_ms
        
        severity = Severity.OK
        if not result.ok:
            severity = Severity.CRIT
        elif last_ok_ts and (ts_ms - last_ok_ts) > 30_000:
            severity = Severity.CRIT
        
        summary = None
        if result.ok and result.payload is not None:
            try:
                summary = await self._process_payload(spec, result.payload, ctx)
            except Exception:
                pass
        
        check = EndpointCheck(
            ts_ms=ts_ms, ok=result.ok, status_code=result.status_code,
            latency_ms=result.latency_ms, error=result.error, payload_summary=summary,
        )
        
        async with self._state.lock:
            checks_buf.append(check)
            stats_1m = calc_stats(list(checks_1m) + [check])
            stats_5m = calc_stats(list(checks_5m) + [check])
            self._state.endpoint_status[spec.name] = EndpointStatus(
                name=spec.name, severity=severity, last_check=check,
                stats_1m=stats_1m, stats_5m=stats_5m, last_ok_ts_ms=last_ok_ts,
            )

    async def _process_payload(self, spec: EndpointSpec, payload: Any, ctx: dict[str, Any]) -> dict | None:
        restaurant_id = ctx.get("restaurant_id", 1)
        turn_id = ctx.get("turn_id")
        key = spec.summarizer_key
        
        if key == "restaurants":
            model, summary = summarize_restaurants(payload)
            if model:
                async with self._state.lock:
                    self._state.restaurants_overview = model
            return summary
        elif key == "restaurant_detail":
            model, summary = summarize_restaurant_detail(payload, restaurant_id)
            if model:
                async with self._state.lock:
                    self._state.my_restaurant = model
            return summary
        elif key == "menu":
            model, summary = summarize_menu(payload, restaurant_id)
            if model:
                async with self._state.lock:
                    self._state.my_menu = model
            return summary
        elif key == "market":
            model, summary = summarize_market_entries(payload)
            if model:
                async with self._state.lock:
                    self._state.market = model
            return summary
        elif key == "meals":
            if turn_id:
                model, summary = summarize_meals(payload, turn_id, restaurant_id)
                if model:
                    async with self._state.lock:
                        self._state.meals = model
                return summary
        elif key == "bid_history":
            if turn_id:
                model, summary = summarize_bid_history(payload, turn_id)
                if model:
                    async with self._state.lock:
                        self._state.bid_history = model
                return summary
        elif key == "recipes":
            recipes, summary = summarize_recipes(payload)
            async with self._state.lock:
                self._state.recipes_cache = recipes
            return summary
        return None
