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
                # ── Recipe stats from DB ──
                recipe_stats = snap.get("recipe_stats") or []
                if recipe_stats:
                    ui.label("📊 Recipe Performance (this turn)").classes("text-lg font-bold")
                    columns = [
                        {"name": "recipe", "label": "Recipe", "field": "recipe", "sortable": True},
                        {"name": "requests", "label": "Requests", "field": "requests", "sortable": True},
                        {"name": "served", "label": "Served", "field": "served", "sortable": True},
                        {"name": "rate", "label": "Service Rate", "field": "rate", "sortable": True},
                        {"name": "prestige", "label": "Prestige", "field": "prestige", "sortable": True},
                    ]
                    rows = []
                    for s in recipe_stats:
                        requests = s.get("num_requests") or 0
                        served = s.get("num_served") or 0
                        rate = f"{served / requests * 100:.0f}%" if requests > 0 else "—"
                        rows.append({
                            "recipe": s.get("recipe_name") or "Unknown",
                            "requests": str(requests),
                            "served": str(served),
                            "rate": rate,
                            "prestige": str(s.get("prestige") or 0),
                        })
                    ui.table(columns=columns, rows=rows, row_key="recipe").classes("w-full")

                # ── Live meals ──
                meals = snap.get("meals") or []
                
                with ui.row().classes("gap-4 mb-4 mt-4"):
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
                elif not recipe_stats:
                    ui.label("No meals data yet. Populates during serving phase.").classes("text-grey")
                
                events = [e for e in (snap.get("recent_events") or []) if e.get("type") in ("client_spawned", "preparation_complete", "serve_dish")]
                if events:
                    ui.label("Recent Events").classes("text-lg font-bold mt-4")
                    for ev in events[-20:]:
                        ui.label(f"[{ev['type']}] {ev.get('data', '')}").classes("text-sm font-mono")
            
            async def tick():
                snap = await state.snapshot()
                if snap.get("_changed", True):
                    render_meals.refresh(snap)
            
            render_meals({})
            ui.timer(1.5, tick)
