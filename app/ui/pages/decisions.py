"""AI decisions log page — shows what the agent decided each phase."""
import datetime
import json
from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None

DECISION_ICONS = {
    "menu_plan": "🍕",
    "bid_plan": "💰",
    "market_waiting": "🛒",
    "market_serving": "🛒",
    "turn_summary": "📝",
}

DECISION_COLORS = {
    "menu_plan": "purple",
    "bid_plan": "orange",
    "market_waiting": "teal",
    "market_serving": "teal",
    "turn_summary": "green",
}


def _fmt_ts(ts_val) -> str:
    if ts_val is None:
        return "?"
    try:
        if hasattr(ts_val, "strftime"):
            return ts_val.strftime("%H:%M:%S")
        return datetime.datetime.fromtimestamp(float(ts_val) / 1000).strftime("%H:%M:%S")
    except Exception:
        return str(ts_val)


def build_decisions_page(state: StateStore) -> None:
    @ui.page("/decisions")
    async def decisions_page():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🧠 AI Decisions Log").classes("text-2xl font-bold")

            filter_select = ui.select(
                options=["all", "menu_plan", "bid_plan", "market_waiting", "market_serving", "turn_summary"],
                value="all",
                label="Filter by type",
            ).classes("w-48")

            @ui.refreshable
            def render_decisions(snap: dict, filter_type: str = "all"):
                all_decisions = snap.get("decisions_recent") or []
                if filter_type and filter_type != "all":
                    all_decisions = [d for d in all_decisions if d.get("decision_type") == filter_type]

                if not all_decisions:
                    ui.label("No decisions recorded yet.").classes("text-grey")
                    return

                for d in all_decisions[:50]:
                    dtype = d.get("decision_type") or "unknown"
                    icon = DECISION_ICONS.get(dtype, "🔹")
                    color = DECISION_COLORS.get(dtype, "grey")
                    ts_str = _fmt_ts(d.get("ts"))
                    turn = d.get("turn_number") or "?"
                    agent = d.get("agent_name") or ""

                    with ui.expansion(f"{icon} [{turn}] {dtype}  —  {ts_str}  ({agent})").classes("w-full"):
                        data = d.get("data_json") or {}

                        # ── Menu plan ──
                        if dtype == "menu_plan":
                            items = data.get("items") or data.get("menu") or []
                            reasoning = data.get("reasoning") or data.get("explanation") or ""
                            if reasoning:
                                ui.label(f"Reasoning: {reasoning[:300]}").classes("text-sm text-grey italic")
                            if items:
                                with ui.row().classes("flex-wrap gap-2 mt-2"):
                                    for it in items:
                                        name = it.get("name") or it.get("dish") or str(it)
                                        price = it.get("price")
                                        label = f"{name} @ {price:.0f}cr" if price is not None else name
                                        ui.badge(label, color="purple")

                        # ── Bid plan ──
                        elif dtype == "bid_plan":
                            bids = data.get("bids") or []
                            reasoning = data.get("reasoning") or ""
                            if reasoning:
                                ui.label(f"Reasoning: {reasoning[:300]}").classes("text-sm text-grey italic")
                            if bids:
                                columns = [
                                    {"name": "ingredient", "label": "Ingredient", "field": "ingredient"},
                                    {"name": "quantity", "label": "Qty", "field": "quantity"},
                                    {"name": "bid", "label": "Bid", "field": "bid"},
                                ]
                                rows = [
                                    {
                                        "ingredient": b.get("ingredient") or b.get("ingredient_name") or str(b),
                                        "quantity": str(b.get("quantity") or ""),
                                        "bid": f"{b['bid']:.2f}" if b.get("bid") is not None else "?",
                                    }
                                    for b in bids
                                ]
                                ui.table(columns=columns, rows=rows, row_key="ingredient").classes("w-full")

                        # ── Market decisions ──
                        elif dtype in ("market_waiting", "market_serving"):
                            actions = data.get("actions") or []
                            spent = data.get("spent") or 0.0
                            ui.label(f"Total spent: {spent:.2f} credits").classes("text-sm font-bold")
                            if actions:
                                with ui.row().classes("flex-wrap gap-2 mt-1"):
                                    for act in actions:
                                        atype = act.get("type", "?")
                                        side = act.get("side") or ""
                                        ing = act.get("ingredient_name") or ""
                                        qty = act.get("quantity") or ""
                                        price = act.get("price") or ""
                                        label = f"{atype}"
                                        if ing:
                                            label += f" {side} {qty}×{ing}"
                                            if price:
                                                label += f"@{price}"
                                        c = "green" if atype == "EXECUTE" else ("blue" if atype == "CREATE" else "orange")
                                        ui.badge(label, color=c)
                            else:
                                ui.label("No actions taken.").classes("text-sm text-grey")

                        # ── Turn summary ──
                        elif dtype == "turn_summary":
                            summary = data.get("summary") or data.get("text") or data.get("narrative") or ""
                            if not summary and isinstance(data, dict):
                                summary = json.dumps(data, indent=2)[:500]
                            ui.label(summary[:600]).classes("text-sm whitespace-pre-wrap")

                        else:
                            ui.code(json.dumps(data, indent=2)[:500]).classes("text-xs w-full")

            filter_select.on("update:model-value", lambda e: render_decisions.refresh(_last_snap[0], filter_select.value))

            ui.separator()
            ui.label("🔧 MCP Tool Calls Log").classes("text-xl font-bold mt-2")
            mcp_filter = ui.input(placeholder="Filter by tool name...").classes("w-48")

            @ui.refreshable
            def render_mcp_calls(snap: dict, filter_text: str = ""):
                calls = snap.get("mcp_calls_recent") or []
                if filter_text:
                    calls = [c for c in calls if filter_text.lower() in (c.get("tool_name") or "").lower()]
                if not calls:
                    ui.label("No MCP calls recorded yet.").classes("text-grey")
                    return
                columns = [
                    {"name": "ts", "label": "Time", "field": "ts"},
                    {"name": "tool", "label": "Tool", "field": "tool", "sortable": True},
                    {"name": "turn", "label": "Turn", "field": "turn", "sortable": True},
                    {"name": "latency", "label": "Latency ms", "field": "latency", "sortable": True},
                    {"name": "status", "label": "Status", "field": "status"},
                    {"name": "phase", "label": "Phase", "field": "phase"},
                ]
                rows = [
                    {
                        "ts": _fmt_ts(c.get("ts")),
                        "tool": c.get("tool_name") or "?",
                        "turn": str(c.get("turn_number") or "?"),
                        "latency": f"{c['latency_ms']:.0f}" if c.get("latency_ms") is not None else "?",
                        "status": "❌ Error" if c.get("is_error") else "✅ OK",
                        "phase": c.get("phase") or "?",
                    }
                    for c in calls[:100]
                ]
                ui.table(columns=columns, rows=rows, row_key="ts").classes("w-full")

            _last_snap: list[dict] = [{}]

            async def tick():
                snap = await state.snapshot()
                _last_snap[0] = snap
                render_decisions.refresh(snap, filter_select.value)
                render_mcp_calls.refresh(snap, mcp_filter.value)

            mcp_filter.on("update:model-value", lambda e: render_mcp_calls.refresh(_last_snap[0], mcp_filter.value))

            render_mcp_calls({})
            render_decisions({})
            ui.timer(3.0, tick)
