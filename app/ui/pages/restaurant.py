from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None


def build_restaurant_page(state: StateStore) -> None:
    @ui.page("/restaurant")
    async def restaurant():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🏠 My Restaurant — State & History").classes("text-2xl font-bold")
            ui.label(
                "Balance, reputation and status — live from restaurant_state_turns table."
            ).classes("text-grey text-sm")

            @ui.refreshable
            def render_history(snap: dict):
                my = snap.get("my_restaurant") or {}
                # Prefer restaurant_state_history (from restaurant_state_turns table)
                rst_history = snap.get("restaurant_state_history") or []
                history = rst_history or (snap.get("snapshots_history") or [])
                menu = snap.get("menu") or []

                # ── Current state KPIs (from latest restaurant_state_turns row) ──
                current_state = rst_history[-1] if rst_history else {}
                bal = current_state.get("balance") if current_state else my.get("balance")
                rep = current_state.get("reputation") if current_state else my.get("reputation")
                is_open = current_state.get("is_open") if current_state else my.get("is_open")

                with ui.row().classes("gap-4 mb-4 flex-wrap"):
                    with ui.card().classes("min-w-[140px]"):
                        ui.label("Balance").classes("text-sm text-grey")
                        ui.label(f"💰 {bal:.2f}" if bal is not None else "N/A").classes("text-2xl font-bold")
                    with ui.card().classes("min-w-[140px]"):
                        ui.label("Reputation").classes("text-sm text-grey")
                        ui.label(f"⭐ {rep:.2f}" if rep is not None else "N/A").classes("text-2xl font-bold")
                    with ui.card().classes("min-w-[140px]"):
                        ui.label("Status").classes("text-sm text-grey")
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
                    ui.label("📈 Balance & Reputation per Turn").classes("text-lg font-bold mt-4")
                    columns = [
                        {"name": "turn", "label": "Turn", "field": "turn", "sortable": True},
                        {"name": "balance", "label": "Balance", "field": "balance", "sortable": True},
                        {"name": "reputation", "label": "Reputation", "field": "reputation", "sortable": True},
                        {"name": "status", "label": "Status", "field": "status"},
                        {"name": "clients_served", "label": "Clients Served", "field": "clients_served", "sortable": True},
                    ]
                    rows = []
                    for h in reversed(history):  # newest first in table
                        b = h.get("balance")
                        r = h.get("reputation")
                        clients = h.get("clients_served")
                        open_val = h.get("is_open")
                        rows.append({
                            "turn": str(h.get("turn_number") or 0),
                            "balance": f"{b:.2f}" if b is not None else "—",
                            "reputation": f"{r:.4f}" if r is not None else "—",
                            "status": ("🟢" if open_val else "🔴") if open_val is not None else "—",
                            "clients_served": str(clients) if clients is not None else "—",
                        })
                    ui.table(columns=columns, rows=rows, row_key="turn").classes("w-full")
                elif not my and not rst_history:
                    ui.label("No data yet — waiting for agent to run.").classes("text-grey mt-4")

            async def tick():
                snap = await state.snapshot()
                render_history.refresh(snap)

            render_history({})
            ui.timer(2.0, tick)

