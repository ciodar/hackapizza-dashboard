"""Strategy page — displays per-turn strategic decisions from the strategy agent."""
import datetime
import json
from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None

_AGENT_COLORS = {
    "menu": "purple",
    "bid": "orange",
    "market": "teal",
    "service": "green",
    "allergy": "red",
}

_AGENT_ICONS = {
    "menu": "🍕",
    "bid": "💰",
    "market": "🛒",
    "service": "🍽️",
    "allergy": "⚠️",
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


def build_strategy_page(state: StateStore) -> None:
    @ui.page("/strategy")
    async def strategy_page():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🧭 Strategy Decisions").classes("text-2xl font-bold")
            ui.label(
                "Per-turn strategic guidance produced by the strategy agent and injected into each sub-agent's system prompt."
            ).classes("text-grey text-sm")

            @ui.refreshable
            def render_strategy(snap: dict):
                all_decisions = snap.get("decisions_recent") or []
                strategy_decisions = [
                    d for d in all_decisions if d.get("decision_type") == "turn_strategy"
                ]

                if not strategy_decisions:
                    ui.label("No strategy decisions recorded yet.").classes("text-grey")
                    return

                ui.label(f"{len(strategy_decisions)} strategy decision(s)").classes("text-sm text-grey")

                for d in strategy_decisions:
                    turn = d.get("turn_number") or "?"
                    ts_str = _fmt_ts(d.get("ts"))
                    data = d.get("data_json") or {}

                    should_open = data.get("should_open")
                    open_reasoning = data.get("open_reasoning") or ""
                    agent_guidance = data.get("agent_guidance") or []

                    open_icon = "✅" if should_open else "🚫"
                    open_label = "OPEN" if should_open else "CLOSED"
                    open_color = "green" if should_open else "red"

                    with ui.expansion(
                        f"[Turn {turn}]  {open_icon} {open_label}  —  {ts_str}",
                        icon="strategy",
                    ).classes("w-full"):
                        with ui.row().classes("gap-2 mb-3 items-center"):
                            ui.badge(open_label, color=open_color)
                            ui.badge(f"Turn {turn}", color="grey")
                            ui.badge(ts_str, color="grey")

                        if open_reasoning:
                            with ui.card().classes("w-full bg-grey-1 mb-3"):
                                ui.label("Open/Close Reasoning").classes("font-bold text-sm")
                                ui.label(open_reasoning).classes("text-sm")

                        if agent_guidance:
                            ui.label("Per-Agent Guidance").classes("font-bold text-sm mb-1")
                            for entry in agent_guidance:
                                agent_name = entry.get("agent_name") or "unknown"
                                guidance = entry.get("guidance") or ""
                                color = _AGENT_COLORS.get(agent_name, "grey")
                                icon = _AGENT_ICONS.get(agent_name, "🔹")

                                with ui.card().classes("w-full mb-2"):
                                    with ui.row().classes("items-center gap-2 mb-1"):
                                        ui.badge(f"{icon} {agent_name}", color=color)
                                    ui.label(guidance).classes("text-sm whitespace-pre-wrap")
                        else:
                            ui.label("No per-agent guidance in this entry (legacy format).").classes("text-sm text-grey italic")
                            # Fallback: render raw JSON for old flat format
                            ui.code(json.dumps(data, indent=2, ensure_ascii=False)[:800]).classes("text-xs w-full")

            _last_snap: list[dict] = [{}]

            async def tick():
                snap = await state.snapshot()
                if snap.get("_changed", True):
                    _last_snap[0] = snap
                    render_strategy.refresh(snap)

            render_strategy({})
            ui.timer(5.0, tick)
