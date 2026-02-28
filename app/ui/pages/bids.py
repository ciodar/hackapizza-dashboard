from nicegui import ui
from app.core.state import StateStore
from app.aggregators.bids_intel import compute_bid_intel
from app.models.bids import BidHistorySnapshot, BidRow
import time

_render_nav = lambda: None

def build_bids_page(state: StateStore) -> None:
    @ui.page("/bids")
    async def bids():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("📊 Bid History").classes("text-2xl font-bold")
            
            @ui.refreshable
            def render_bids(snap: dict):
                # ── Ingredient bid stats from DB (all restaurants, per turn) ──
                ing_stats = snap.get("ingredient_bid_stats") or []
                if ing_stats:
                    ui.label("📈 Per-Ingredient Bid Stats (all restaurants this turn)").classes("text-lg font-bold")
                    columns = [
                        {"name": "ingredient", "label": "Ingredient", "field": "ingredient", "sortable": True},
                        {"name": "min_price", "label": "Min", "field": "min_price", "sortable": True},
                        {"name": "avg_price", "label": "Avg", "field": "avg_price", "sortable": True},
                        {"name": "max_price", "label": "Max", "field": "max_price", "sortable": True},
                        {"name": "total_qty", "label": "Total Qty", "field": "total_qty", "sortable": True},
                    ]
                    rows = [
                        {
                            "ingredient": s.get("ingredient_name") or "Unknown",
                            "min_price": f"{s['min_price_paid']:.2f}" if s.get("min_price_paid") is not None else "—",
                            "avg_price": f"{s['avg_price_paid']:.2f}" if s.get("avg_price_paid") is not None else "—",
                            "max_price": f"{s['max_price_paid']:.2f}" if s.get("max_price_paid") is not None else "—",
                            "total_qty": str(s.get("total_quantity") or 0),
                        }
                        for s in ing_stats
                    ]
                    ui.table(columns=columns, rows=rows, row_key="ingredient").classes("w-full")

                # ── Per-bid distribution from raw bid_history ──
                bids_data = snap.get("bids") or []
                
                if not bids_data and not ing_stats:
                    ui.label("No bid history. Runs after turn ends (stopped phase).").classes("text-grey")
                    return
                
                if bids_data:
                    bid_rows = [BidRow(b.get("ingredient"), b.get("bid"), b.get("quantity"), b.get("restaurant_id"), {}) for b in bids_data]
                    snap_obj = BidHistorySnapshot(ts_ms=int(time.time()*1000), turn_id=0, bids=bid_rows)
                    intel = compute_bid_intel(snap_obj)
                    
                    if intel and intel.per_ingredient:
                        ui.label("Distribution per Ingredient").classes("text-lg font-bold mt-4")
                        columns = [
                            {"name": "ingredient", "label": "Ingredient", "field": "ingredient", "sortable": True},
                            {"name": "min_bid", "label": "Min", "field": "min_bid"},
                            {"name": "median_bid", "label": "Median", "field": "median_bid"},
                            {"name": "max_bid", "label": "Max", "field": "max_bid"},
                            {"name": "count", "label": "Count", "field": "count"},
                        ]
                        rows = [
                            {
                                "ingredient": s.ingredient,
                                "min_bid": f"{s.min_bid:.2f}" if s.min_bid is not None else "—",
                                "median_bid": f"{s.median_bid:.2f}" if s.median_bid is not None else "—",
                                "max_bid": f"{s.max_bid:.2f}" if s.max_bid is not None else "—",
                                "count": str(s.sample_count),
                            }
                            for s in intel.per_ingredient
                        ]
                        ui.table(columns=columns, rows=rows, row_key="ingredient").classes("w-full")
                    
                    ui.label("All Bids").classes("text-lg font-bold mt-4")
                    columns = [
                        {"name": "ingredient", "label": "Ingredient", "field": "ingredient", "sortable": True},
                        {"name": "bid", "label": "Price", "field": "bid", "sortable": True},
                        {"name": "quantity", "label": "Qty", "field": "quantity"},
                        {"name": "restaurant", "label": "Restaurant", "field": "restaurant"},
                    ]
                    rows = [
                        {
                            "ingredient": b.get("ingredient") or "Unknown",
                            "bid": f"{b['bid']:.2f}" if b.get("bid") is not None else "N/A",
                            "quantity": str(b.get("quantity") or ""),
                            "restaurant": str(b.get("restaurant_id") or ""),
                        }
                        for b in bids_data
                    ]
                    ui.table(columns=columns, rows=rows, row_key="ingredient").classes("w-full")
            
            async def tick():
                snap = await state.snapshot()
                render_bids.refresh(snap)
            
            render_bids({})
            ui.timer(5.0, tick)
