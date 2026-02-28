from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None

def build_endpoint_health_page(state: StateStore) -> None:
    @ui.page("/health")
    async def endpoint_health():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🔌 Endpoint Health").classes("text-2xl font-bold")
            
            grid = ui.grid(columns=3).classes("w-full gap-4")
            
            @ui.refreshable
            def render_endpoints(snap: dict):
                grid.clear()
                with grid:
                    statuses = snap.get("endpoint_statuses") or {}
                    # SSE is intentionally disabled (single connection per restaurant — owned by agent)
                    sse_status = {
                        "name": "sse_events (disabled — agent only)",
                        "severity": "warn",
                        "last_check": {
                            "ok": False,
                            "latency_ms": None,
                            "status_code": None,
                            "error": "Disabled: single SSE connection reserved for restaurant agent",
                            "ts_ms": None,
                        },
                        "stats_1m": {},
                        "stats_5m": {},
                    }
                    all_statuses = {"SSE": sse_status, **statuses}
                    
                    for name, ep in all_statuses.items():
                        sev = ep.get("severity", "ok")
                        color = {"ok": "green", "warn": "orange", "crit": "red"}.get(sev, "grey")
                        lc = ep.get("last_check") or {}
                        with ui.card().classes("w-full"):
                            with ui.row().classes("items-center gap-2 justify-between"):
                                ui.label(name).classes("font-bold")
                                ui.badge(sev.upper(), color=color)
                            if lc:
                                status_code = lc.get("status_code")
                                latency = lc.get("latency_ms")
                                ok = lc.get("ok", False)
                                ui.label(f"{'✓' if ok else '✗'} {status_code or 'N/A'} | {latency:.0f}ms" if latency else f"{'✓' if ok else '✗'} {status_code or 'N/A'}").classes("text-sm")
                                if lc.get("error"):
                                    ui.label(f"Error: {lc.get('error')[:50]}").classes("text-xs text-red")
                            stats1m = ep.get("stats_1m") or {}
                            if stats1m.get("count", 0) > 0:
                                err_rate = stats1m.get("error_rate", 0) * 100
                                avg_lat = stats1m.get("avg_latency_ms")
                                ui.label(f"1m: {err_rate:.0f}% errors | {avg_lat:.0f}ms avg" if avg_lat else f"1m: {err_rate:.0f}% errors").classes("text-xs text-grey")
            
            async def tick():
                snap = await state.snapshot()
                render_endpoints.refresh(snap)
            
            render_endpoints({})
            ui.timer(2.0, tick)
