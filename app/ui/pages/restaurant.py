from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None


def build_restaurant_page(state: StateStore) -> None:
    @ui.page("/restaurant")
    async def restaurant():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🏠 My Restaurant — Turn History").classes("text-2xl font-bold")
            ui.label(
                "Balance, reputation and inventory history across all turns recorded in the local DB."
            ).classes("text-grey text-sm")

            @ui.refreshable
            def render_history(snap: dict):
                my = snap.get("my_restaurant") or {}
                history = snap.get("snapshots_history") or []
                menu = snap.get("menu") or []

                # ── Current state KPIs ──
                with ui.row().classes("gap-4 mb-4 flex-wrap"):
                    with ui.card().classes("min-w-[140px]"):
                        ui.label("Balance").classes("text-sm text-grey")
                        bal = my.get("balance")
                        ui.label(f"💰 {bal:.2f}" if bal is not None else "N/A").classes("text-2xl font-bold")
                    with ui.card().classes("min-w-[140px]"):
                        ui.label("Reputation").classes("text-sm text-grey")
                        rep = my.get("reputation")
                        ui.label(f"⭐ {rep:.2f}" if rep is not None else "N/A").classes("text-2xl font-bold")
                    with ui.card().classes("min-w-[140px]"):
                        ui.label("Status").classes("text-sm text-grey")
                        is_open = my.get("is_open")
                        txt = "🟢 Open" if is_open else ("🔴 Closed" if is_open is False else "❓ Unknown")
                        ui.label(txt).classes("text-2xl font-bold")
                    with ui.card().classes("min-w-[140px]"):
                        ui.label("Turn").classes("text-sm text-grey")
                        ui.label(f"#{snap.get('turn_number', 0)}").classes("text-2xl font-bold")

                # ── Active menu ──
                if menu:
                    ui.label("🍕 Active Menu").classes("text-lg font-bold mt-2")
                    with ui.row().classes("flex-wrap gap-2"):
                        for item in menu:
                            name = item.get("name") or "?"
                            price = item.get("price")
                            label = f"{name}  {price:.0f}cr" if price is not None else name
                            ui.badge(label, color="purple")

                # ── Inventory ──
                inv = my.get("inventory") or {}
                if inv:
                    ui.label("📦 Current Inventory").classes("text-lg font-bold mt-2")
                    columns = [
                        {"name": "ingredient", "label": "Ingredient", "field": "ingredient", "sortable": True},
                        {"name": "qty", "label": "Quantity", "field": "qty", "sortable": True},
                    ]
                    rows = [
                        {"ingredient": k, "qty": f"{v:.1f}" if isinstance(v, float) else str(v)}
                        for k, v in sorted(inv.items())
                    ]
                    ui.table(columns=columns, rows=rows, row_key="ingredient").classes("w-full max-w-lg")

                # ── Turn history table ──
                if history:
                    ui.label("📈 Balance & Reputation History").classes("text-lg font-bold mt-4")
                    columns = [
                        {"name": "turn", "label": "Turn", "field": "turn", "sortable": True},
                        {"name": "balance", "label": "Balance", "field": "balance", "sortable": True},
                        {"name": "reputation", "label": "Reputation", "field": "reputation", "sortable": True},
                        {"name": "clients_served", "label": "Clients Served", "field": "clients_served", "sortable": True},
                    ]
                    rows = []
                    for h in history:
                        bal = h.get("balance")
                        rep = h.get("reputation")
                        clients = h.get("clients_served")
                        rows.append({
                            "turn": str(h.get("turn_number") or 0),
                            "balance": f"{bal:.2f}" if bal is not None else "—",
                            "reputation": f"{rep:.2f}" if rep is not None else "—",
                            "clients_served": str(clients) if clients is not None else "—",
                        })
                    ui.table(columns=columns, rows=rows, row_key="turn").classes("w-full")
                elif not my:
                    ui.label("No data yet — waiting for agent to run.").classes("text-grey mt-4")

            async def tick():
                snap = await state.snapshot()
                render_history.refresh(snap)

            render_history({})
            ui.timer(2.0, tick)
