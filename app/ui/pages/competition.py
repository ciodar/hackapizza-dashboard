from nicegui import ui
from app.core.state import StateStore
from app.aggregators.ranking import compute_ranking
from app.models.restaurant import RestaurantsOverview, RestaurantRow
import time

_render_nav = lambda: None

def build_competition_page(state: StateStore) -> None:
    @ui.page("/competition")
    async def competition():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🏆 Competition").classes("text-2xl font-bold")
            
            @ui.refreshable
            def render_ranking(snap: dict):
                restaurants = snap.get("restaurants") or []
                my = snap.get("my_restaurant") or {}
                my_id = my.get("id", 1)
                
                if not restaurants:
                    ui.label("No data available").classes("text-grey")
                    return
                
                rows_data = [RestaurantRow(r["id"], r["name"], r["balance"], r["reputation"], r["is_open"], {}) for r in restaurants]
                ov = RestaurantsOverview(ts_ms=int(time.time()*1000), restaurants=rows_data)
                ranking = compute_ranking(ov, my_id)
                
                if not ranking:
                    ui.label("No ranking available").classes("text-grey")
                    return
                
                if ranking.my_rank:
                    with ui.row().classes("gap-4 mb-4"):
                        with ui.card():
                            ui.label("My Rank").classes("text-sm text-grey")
                            ui.label(f"#{ranking.my_rank} / {len(ranking.rows)}").classes("text-2xl font-bold")
                        if ranking.delta_to_leader is not None:
                            with ui.card():
                                ui.label("Gap to Leader").classes("text-sm text-grey")
                                ui.label(f"-{ranking.delta_to_leader:.2f}").classes("text-2xl font-bold text-red")
                        if ranking.delta_to_prev is not None:
                            with ui.card():
                                ui.label("Gap to Prev").classes("text-sm text-grey")
                                ui.label(f"-{ranking.delta_to_prev:.2f}").classes("text-2xl font-bold text-orange")
                        if ranking.delta_to_next is not None:
                            with ui.card():
                                ui.label("Ahead of Next").classes("text-sm text-grey")
                                ui.label(f"+{ranking.delta_to_next:.2f}").classes("text-2xl font-bold text-green")
                
                columns = [
                    {"name": "rank", "label": "Rank", "field": "rank", "sortable": True},
                    {"name": "name", "label": "Restaurant", "field": "name", "sortable": True},
                    {"name": "balance", "label": "Balance", "field": "balance", "sortable": True},
                    {"name": "reputation", "label": "Reputation", "field": "reputation", "sortable": True},
                    {"name": "is_open", "label": "Open", "field": "is_open"},
                ]
                rows = [
                    {
                        "rank": r.rank,
                        "name": r.name or f"Restaurant #{r.restaurant_id}",
                        "balance": f"{r.balance:.2f}" if r.balance is not None else "N/A",
                        "reputation": f"{r.reputation:.2f}" if r.reputation is not None else "N/A",
                        "is_open": "🟢" if r.is_open else "🔴",
                        "_highlight": r.restaurant_id == my_id,
                    }
                    for r in ranking.rows
                ]
                ui.table(columns=columns, rows=rows, row_key="rank").classes("w-full")
            
            async def tick():
                snap = await state.snapshot()
                render_ranking.refresh(snap)
            
            render_ranking({})
            ui.timer(2.0, tick)
