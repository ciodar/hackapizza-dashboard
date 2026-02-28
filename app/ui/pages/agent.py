"""Agent Prompts page — shows LLM inputs/outputs from the agent_prompts table."""
import json
import datetime
from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None

_AGENT_COLORS = {
    "menu_agent": "purple",
    "bid_agent": "blue",
    "market_agent": "orange",
    "memory_agent": "teal",
    "serving_agent": "green",
}


def _fmt_ts(ts) -> str:
    try:
        if hasattr(ts, "strftime"):
            return ts.strftime("%H:%M:%S")
        return datetime.datetime.fromisoformat(str(ts)).strftime("%H:%M:%S")
    except Exception:
        return str(ts) if ts else "?"


def _truncate(text: str, n: int = 120) -> str:
    if not text:
        return ""
    text = str(text)
    return text[:n] + "…" if len(text) > n else text


def build_agent_page(state: StateStore) -> None:
    @ui.page("/agent")
    async def agent_prompts_page():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("🤖 Agent Prompts").classes("text-2xl font-bold")
            ui.label(
                "Full LLM prompts and outputs recorded per agent call. Useful for debugging agent reasoning."
            ).classes("text-grey text-sm")

            _last_snap = [{}]

            filter_agent = ui.select(
                options=["All", "menu_agent", "bid_agent", "market_agent", "memory_agent", "serving_agent"],
                value="All",
                label="Filter by agent",
            ).classes("max-w-[200px]")

            @ui.refreshable
            def render_prompts(snap: dict, agent_filter: str = "All"):
                prompts = list(snap.get("agent_prompts") or [])
                if agent_filter and agent_filter != "All":
                    prompts = [p for p in prompts if p.get("agent_name") == agent_filter]

                if not prompts:
                    ui.label("No agent prompts recorded yet.").classes("text-grey")
                    return

                ui.label(f"{len(prompts)} prompt(s) recorded").classes("text-sm text-grey")

                for p in prompts:
                    agent = p.get("agent_name") or "unknown"
                    phase = p.get("phase") or "?"
                    turn = p.get("turn_number") or 0
                    ts_str = _fmt_ts(p.get("ts"))
                    color = _AGENT_COLORS.get(agent, "grey")

                    output_raw = p.get("output_json")
                    if isinstance(output_raw, str):
                        try:
                            output_raw = json.loads(output_raw)
                        except Exception:
                            pass

                    with ui.expansion(
                        f"[T{turn}] {agent}  •  {phase}  •  {ts_str}",
                        icon="smart_toy",
                    ).classes("w-full"):
                        with ui.row().classes("gap-2 mb-2"):
                            ui.badge(agent, color=color)
                            ui.badge(f"phase: {phase}", color="grey")
                            ui.badge(f"turn: {turn}", color="grey")

                        sys_prompt = p.get("system_prompt") or ""
                        input_prompt = p.get("input_prompt") or ""

                        if sys_prompt:
                            ui.label("System Prompt").classes("font-bold text-sm mt-2")
                            ui.textarea(value=sys_prompt).classes("w-full font-mono text-xs").props(
                                "readonly outlined dense rows=4"
                            )

                        if input_prompt:
                            ui.label("Input Prompt").classes("font-bold text-sm mt-2")
                            ui.textarea(value=input_prompt).classes("w-full font-mono text-xs").props(
                                "readonly outlined dense rows=6"
                            )

                        if output_raw is not None:
                            ui.label("Output").classes("font-bold text-sm mt-2")
                            output_str = (
                                json.dumps(output_raw, indent=2, ensure_ascii=False)
                                if not isinstance(output_raw, str)
                                else output_raw
                            )
                            ui.textarea(value=output_str).classes("w-full font-mono text-xs").props(
                                "readonly outlined dense rows=6"
                            )

            async def tick():
                snap = await state.snapshot()
                _last_snap[0] = snap
                render_prompts.refresh(snap, filter_agent.value)

            filter_agent.on("update:model-value", lambda _: render_prompts.refresh(_last_snap[0], filter_agent.value))

            render_prompts({})
            ui.timer(5.0, tick)
