from nicegui import ui
from app.core.state import StateStore
from app.aggregators.bids_intel import compute_bid_intel
from app.models.bids import BidHistorySnapshot, BidRow
import time
from collections import defaultdict

_render_nav = lambda: None

def build_bids_page(state: StateStore) -> None:
    @ui.page("/bids")
    async def bids():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("📊 Bid History").classes("text-2xl font-bold")

            # ── Turn selector ──
            async def on_turn_change(e):
                await load_data()

            turn_select = ui.select(
                options={'current': 'Current Turn'},
                value='current',
                on_change=on_turn_change,
                label='Select Turn',
            ).classes('w-64')

            @ui.refreshable
            def render_bids(snap: dict, bids_override=None, stats_override=None):
                bid_history = snap.get("ingredient_bid_history") or []
                bids_data = bids_override if bids_override is not None else (snap.get("bids") or [])
                ing_stats = stats_override if stats_override is not None else (snap.get("ingredient_bid_stats") or [])

                # ── Cross-turn ingredient price trends ──
                if bid_history:
                    ui.label("📉 Ingredient Price Trends (All Turns)").classes("text-lg font-bold")
                    by_ingredient: dict[str, list[dict]] = defaultdict(list)
                    for row in bid_history:
                        by_ingredient[row.get("ingredient_name") or "?"].append(row)
                    columns = [
                        {"name": "ingredient", "label": "Ingredient", "field": "ingredient", "sortable": True},
                        {"name": "turns", "label": "Turns", "field": "turns"},
                        {"name": "min_ever", "label": "Min Ever", "field": "min_ever", "sortable": True},
                        {"name": "avg_avg", "label": "Avg", "field": "avg_avg", "sortable": True},
                        {"name": "max_ever", "label": "Max Ever", "field": "max_ever", "sortable": True},
                    ]
                    rows = []
                    for ing, records in sorted(by_ingredient.items()):
                        mins = [r["min_price_paid"] for r in records if r.get("min_price_paid") is not None]
                        avgs = [r["avg_price_paid"] for r in records if r.get("avg_price_paid") is not None]
                        maxs = [r["max_price_paid"] for r in records if r.get("max_price_paid") is not None]
                        turn_ids = sorted({r.get("turn_id") for r in records if r.get("turn_id")})
                        rows.append({
                            "ingredient": ing,
                            "turns": ", ".join(str(t) for t in turn_ids),
                            "min_ever": f"{min(mins):.2f}" if mins else "—",
                            "avg_avg": f"{sum(avgs)/len(avgs):.2f}" if avgs else "—",
                            "max_ever": f"{max(maxs):.2f}" if maxs else "—",
                        })
                    ui.table(columns=columns, rows=rows, row_key="ingredient").classes("w-full")

                # ── Ingredient bid stats for selected turn ──
                if ing_stats:
                    ui.label("📈 Per-Ingredient Bid Stats (all restaurants, selected turn)").classes("text-lg font-bold")
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
                if not bids_data and not ing_stats:
                    ui.label("No bid data for this turn.").classes("text-grey")
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
                            "_idx": str(i),
                            "ingredient": b.get("ingredient") or "Unknown",
                            "bid": f"{b['bid']:.2f}" if b.get("bid") is not None else "N/A",
                            "quantity": str(b.get("quantity") or ""),
                            "restaurant": str(b.get("restaurant_id") or ""),
                        }
                        for i, b in enumerate(bids_data)
                    ]
                    ui.table(columns=columns, rows=rows, row_key="_idx").classes("w-full")

            async def load_data():
                snap = await state.snapshot()
                current_turn_id = snap.get("turn_id")
                current_turn_number = snap.get("turn_number") or 0

                # Build turn options from known data
                bid_history_all = snap.get("ingredient_bid_history") or []
                rst_history = snap.get("restaurant_state_history") or []
                known_turns: dict[int, int] = {}
                for r in rst_history:
                    tid, tn = r.get("turn_id"), r.get("turn_number")
                    if tid is not None:
                        known_turns[tid] = tn or tid
                for r in bid_history_all:
                    tid = r.get("turn_id")
                    if tid is not None and tid not in known_turns:
                        known_turns[tid] = tid

                opts = {'current': f'Current Turn ({current_turn_number})'}
                for tid in sorted(known_turns.keys(), reverse=True):
                    if tid != current_turn_id:
                        opts[str(tid)] = f'Turn {known_turns[tid]}'
                turn_select.set_options(opts)

                sel = turn_select.value

                if sel == 'current':
                    render_bids.refresh(snap)
                else:
                    selected_turn_id = int(sel)
                    # Fetch raw bids for the selected turn from DB
                    bids_data = []
                    reader = state._reader
                    if reader:
                        rows = await reader.try_fetch_rows(
                            "SELECT * FROM bid_history WHERE turn_id = %s ORDER BY id",
                            (selected_turn_id,),
                        )
                        if rows is None:
                            rows = await reader.try_fetch_rows(
                                "SELECT * FROM bids WHERE turn_id = %s ORDER BY id",
                                (selected_turn_id,),
                            )
                        if rows:
                            for r in rows:
                                ingredient = r.get("ingredient_name") or r.get("ingredient")
                                bid_price = r.get("price") or r.get("bid")
                                bids_data.append({
                                    "ingredient": ingredient,
                                    "bid": float(bid_price) if bid_price is not None else None,
                                    "quantity": r.get("quantity"),
                                    "restaurant_id": r.get("restaurant_id"),
                                })
                    # Filter cross-turn stats to selected turn
                    turn_stats = [
                        {
                            "ingredient_name": r.get("ingredient_name"),
                            "min_price_paid": r.get("min_price_paid"),
                            "avg_price_paid": r.get("avg_price_paid"),
                            "max_price_paid": r.get("max_price_paid"),
                            "total_quantity": r.get("total_quantity"),
                        }
                        for r in bid_history_all
                        if r.get("turn_id") == selected_turn_id
                    ]
                    render_bids.refresh(snap, bids_data, turn_stats)

            async def tick():
                if turn_select.value == 'current':
                    await load_data()

            render_bids({})
            await load_data()
            ui.timer(5.0, tick)
