import time
from nicegui import ui
from app.core.state import StateStore
from app.aggregators.ranking import compute_ranking
from app.aggregators.meals_kpi import compute_meals_kpi

_render_nav = lambda: None

PHASE_COLORS = {
    "speaking": "blue",
    "closed_bid": "orange",
    "waiting": "grey",
    "serving": "green",
    "stopped": "red",
    "unknown": "grey",
}

def build_overview_page(state: StateStore) -> None:
    @ui.page("/")
    async def overview():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🍕 Hackapizza Dashboard").classes("text-3xl font-bold")
            
            status_row = ui.row().classes("w-full gap-4 items-center")
            cards_row = ui.row().classes("w-full gap-4")
            alerts_section = ui.column().classes("w-full")
            
            @ui.refreshable
            def render_content(snap: dict):
                # Status bar
                with status_row:
                    status_row.clear()
                    phase = snap.get("phase", "unknown")
                    color = PHASE_COLORS.get(phase, "grey")
                    ui.badge(f"Phase: {phase.upper()}", color=color).classes("text-sm")
                    
                    sse_ok = snap.get("sse_connected", False)
                    sse_color = "green" if sse_ok else ("orange" if snap.get("sse_blocked") else "red")
                    ui.badge(f"SSE: {'✓' if sse_ok else '✗'}", color=sse_color).classes("text-sm")

                    turn_number = snap.get("turn_number", 0)
                    turn_id = snap.get("turn_id")
                    turn_label = f"Turn #{turn_number}"
                    if turn_id is not None:
                        turn_label += f"  (id {turn_id})"
                    ui.badge(turn_label, color="purple" if turn_number else "grey").classes("text-sm")
                    
                    hb_age = snap.get("heartbeat_age_s")
                    if hb_age is not None:
                        hb_color = "green" if hb_age < 15 else "red"
                        ui.badge(f"HB: {hb_age:.0f}s", color=hb_color).classes("text-sm")
                
                # KPI cards
                cards_row.clear()
                with cards_row:
                    my = snap.get("my_restaurant") or {}
                    balance = my.get("balance")
                    reputation = my.get("reputation")
                    is_open = my.get("is_open")
                    
                    with ui.card().classes("min-w-[150px]"):
                        ui.label("Balance").classes("text-sm text-grey")
                        ui.label(f"💰 {balance:.2f}" if balance is not None else "N/A").classes("text-2xl font-bold")
                    
                    with ui.card().classes("min-w-[150px]"):
                        ui.label("Reputation").classes("text-sm text-grey")
                        ui.label(f"⭐ {reputation:.2f}" if reputation is not None else "N/A").classes("text-2xl font-bold")
                    
                    with ui.card().classes("min-w-[150px]"):
                        ui.label("Status").classes("text-sm text-grey")
                        status_text = "🟢 Open" if is_open else ("🔴 Closed" if is_open is False else "❓ Unknown")
                        ui.label(status_text).classes("text-2xl font-bold")
                    
                    # Ranking card
                    overview_data = snap.get("restaurants") or []
                    if overview_data:
                        from app.models.restaurant import RestaurantsOverview, RestaurantRow
                        import time as t
                        rows_data = [RestaurantRow(r["id"], r["name"], r["balance"], r["reputation"], r["is_open"], {}) for r in overview_data]
                        ov = RestaurantsOverview(ts_ms=int(t.time()*1000), restaurants=rows_data)
                        ranking = compute_ranking(ov, my.get("id", 1))
                        if ranking:
                            with ui.card().classes("min-w-[150px]"):
                                ui.label("Rank").classes("text-sm text-grey")
                                ui.label(f"🏆 #{ranking.my_rank}" if ranking.my_rank else "N/A").classes("text-2xl font-bold")
                                if ranking.delta_to_leader is not None:
                                    ui.label(f"▲{ranking.delta_to_leader:.0f} to leader").classes("text-xs text-grey")
                    
                    # Meals KPI
                    meals_data = snap.get("meals") or []
                    if meals_data:
                        from app.models.meals import MealsSnapshot, MealRequest
                        import time as t
                        meal_reqs = [MealRequest(m.get("client_id"), m.get("client_name"), m.get("order_text"), m.get("executed"), {}) for m in meals_data]
                        meals_snap = MealsSnapshot(ts_ms=int(t.time()*1000), turn_id=0, restaurant_id=0, meals=meal_reqs)
                        kpi = compute_meals_kpi(meals_snap)
                        if kpi:
                            color_map = {"ok": "green", "warn": "orange", "crit": "red"}
                            with ui.card().classes("min-w-[150px]"):
                                ui.label("Meals").classes("text-sm text-grey")
                                ui.label(f"🍽️ {kpi.pending} pending").classes("text-2xl font-bold")
                                ui.badge(kpi.backlog_severity, color=color_map.get(kpi.backlog_severity, "grey"))
                
                # Alerts
                alerts_section.clear()
                with alerts_section:
                    active = snap.get("active_alerts") or {}
                    if active:
                        ui.label("🚨 Active Alerts").classes("text-xl font-bold mt-4")
                        for aid, alert in active.items():
                            if not alert.get("acknowledged"):
                                color = {"crit": "red", "warn": "orange", "ok": "green"}.get(alert.get("severity", "ok"), "grey")
                                with ui.card().classes(f"w-full border-l-4 border-{color}-500 bg-{color}-50"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.badge(alert.get("severity", "").upper(), color=color)
                                        ui.label(alert.get("title", "")).classes("font-bold")
                                    ui.label(alert.get("message", "")).classes("text-sm text-grey")
            
            async def tick():
                snap = await state.snapshot()
                render_content.refresh(snap)
            
            render_content({})
            ui.timer(1.5, tick)
