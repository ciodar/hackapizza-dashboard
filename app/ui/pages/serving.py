from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None

def build_serving_page(state: StateStore) -> None:
    @ui.page("/serving")
    async def serving():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🍽️ Serving").classes("text-2xl font-bold")
            
            @ui.refreshable
            def render_meals(snap: dict):
                meals = snap.get("meals") or []
                
                with ui.row().classes("gap-4 mb-4"):
                    total = len(meals)
                    executed = sum(1 for m in meals if m.get("executed"))
                    pending = total - executed
                    
                    with ui.card():
                        ui.label("Total").classes("text-sm text-grey")
                        ui.label(str(total)).classes("text-2xl font-bold")
                    with ui.card():
                        ui.label("Pending").classes("text-sm text-grey")
                        color = "red" if pending >= 10 else ("orange" if pending >= 5 else "green")
                        ui.label(str(pending)).classes(f"text-2xl font-bold text-{color}")
                    with ui.card():
                        ui.label("Executed").classes("text-sm text-grey")
                        ui.label(str(executed)).classes("text-2xl font-bold text-green")
                    with ui.card():
                        ui.label("Rate").classes("text-sm text-grey")
                        rate = executed / total * 100 if total > 0 else 0
                        ui.label(f"{rate:.0f}%").classes("text-2xl font-bold")
                
                if meals:
                    columns = [
                        {"name": "client", "label": "Client", "field": "client"},
                        {"name": "order", "label": "Order", "field": "order"},
                        {"name": "status", "label": "Status", "field": "status"},
                    ]
                    rows = [
                        {
                            "client": m.get("client_name") or m.get("client_id") or "Unknown",
                            "order": (m.get("order_text") or "")[:80],
                            "status": "✅ Done" if m.get("executed") else "⏳ Pending",
                        }
                        for m in meals
                    ]
                    ui.table(columns=columns, rows=rows, row_key="client").classes("w-full")
                else:
                    ui.label("No meals data. Set turn_id in config.").classes("text-grey")
                
                events = [e for e in (snap.get("recent_events") or []) if e.get("type") in ("client_spawned", "preparation_complete", "serve_dish")]
                if events:
                    ui.label("Recent Events").classes("text-lg font-bold mt-4")
                    for ev in events[-20:]:
                        ui.label(f"[{ev['type']}] {ev.get('data', '')}").classes("text-sm font-mono")
            
            async def tick():
                snap = await state.snapshot()
                render_meals.refresh(snap)
            
            render_meals({})
            ui.timer(1.5, tick)
