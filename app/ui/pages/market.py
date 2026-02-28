from nicegui import ui
from app.core.state import StateStore
from app.aggregators.market_intel import compute_market_intel
from app.models.market import MarketSnapshot, MarketEntry
import time

_render_nav = lambda: None

def build_market_page(state: StateStore) -> None:
    @ui.page("/market")
    async def market():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🛒 Market").classes("text-2xl font-bold")
            
            @ui.refreshable
            def render_market(snap: dict):
                entries_data = snap.get("market_entries") or []
                
                if entries_data:
                    entries = [MarketEntry(e["id"], e["side"], e["ingredient"], e["quantity"], e["price"], e["owner_id"], {}) for e in entries_data]
                    market_snap = MarketSnapshot(ts_ms=int(time.time()*1000), entries=entries)
                    intel = compute_market_intel(market_snap)
                    
                    if intel and intel.opportunities:
                        ui.label("💡 Opportunities").classes("text-lg font-bold")
                        with ui.row().classes("gap-2 flex-wrap"):
                            for opp in intel.opportunities:
                                color = "green" if opp["type"] == "cheap_supply" else "blue"
                                icon = "🛒" if opp["type"] == "cheap_supply" else "💰"
                                ui.badge(f"{icon} {opp['ingredient']} @ {opp['price']:.2f}", color=color)
                    
                    if intel and intel.per_ingredient:
                        ui.label("📊 Per Ingredient").classes("text-lg font-bold mt-4")
                        columns = [
                            {"name": "ingredient", "label": "Ingredient", "field": "ingredient", "sortable": True},
                            {"name": "best_buy", "label": "Best Buy (SELL)", "field": "best_buy", "sortable": True},
                            {"name": "best_sell", "label": "Best Sell (BUY)", "field": "best_sell", "sortable": True},
                            {"name": "median", "label": "Median", "field": "median", "sortable": True},
                            {"name": "buy_vol", "label": "Buy Vol", "field": "buy_vol"},
                            {"name": "sell_vol", "label": "Sell Vol", "field": "sell_vol"},
                        ]
                        rows = [
                            {
                                "ingredient": s.ingredient,
                                "best_buy": f"{s.best_buy_price:.2f}" if s.best_buy_price is not None else "—",
                                "best_sell": f"{s.best_sell_price:.2f}" if s.best_sell_price is not None else "—",
                                "median": f"{s.median_price:.2f}" if s.median_price is not None else "—",
                                "buy_vol": f"{s.buy_volume:.0f}",
                                "sell_vol": f"{s.sell_volume:.0f}",
                            }
                            for s in intel.per_ingredient
                        ]
                        ui.table(columns=columns, rows=rows, row_key="ingredient").classes("w-full")
                    
                    ui.label("📋 All Entries").classes("text-lg font-bold mt-4")
                    columns = [
                        {"name": "side", "label": "Side", "field": "side"},
                        {"name": "ingredient", "label": "Ingredient", "field": "ingredient", "sortable": True},
                        {"name": "quantity", "label": "Qty", "field": "quantity"},
                        {"name": "price", "label": "Price", "field": "price", "sortable": True},
                        {"name": "owner", "label": "Owner", "field": "owner"},
                    ]
                    rows = [
                        {
                            "side": ("🟢 BUY" if e.get("side") == "BUY" else "🔴 SELL") if e.get("side") else "?",
                            "ingredient": e.get("ingredient") or "Unknown",
                            "quantity": str(e.get("quantity") or ""),
                            "price": f"{e['price']:.2f}" if e.get("price") is not None else "N/A",
                            "owner": str(e.get("owner_id") or ""),
                        }
                        for e in entries_data
                    ]
                    ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")
                else:
                    ui.label("No market entries available.").classes("text-grey")
            
            async def tick():
                snap = await state.snapshot()
                render_market.refresh(snap)
            
            render_market({})
            ui.timer(3.0, tick)
