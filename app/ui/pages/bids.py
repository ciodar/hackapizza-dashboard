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
                bids_data = snap.get("bids") or []
                
                if not bids_data:
                    ui.label("No bid history. Set turn_id in config.").classes("text-grey")
                    return
                
                bid_rows = [BidRow(b.get("ingredient"), b.get("bid"), b.get("quantity"), b.get("restaurant_id"), {}) for b in bids_data]
                snap_obj = BidHistorySnapshot(ts_ms=int(time.time()*1000), turn_id=0, bids=bid_rows)
                intel = compute_bid_intel(snap_obj)
                
                if intel and intel.per_ingredient:
                    ui.label("Distribution per Ingredient").classes("text-lg font-bold")
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
                    {"name": "bid", "label": "Bid", "field": "bid", "sortable": True},
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
