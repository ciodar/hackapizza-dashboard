import datetime
from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None

def build_events_page(state: StateStore) -> None:
    @ui.page("/events")
    async def events():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("📡 Events & Messages").classes("text-2xl font-bold")
            
            filter_input = ui.input(placeholder="Filter events...").classes("w-full max-w-md")
            
            @ui.refreshable
            def render_events(snap: dict, filter_text: str = ""):
                all_events = list(reversed(snap.get("recent_events") or []))
                if filter_text:
                    all_events = [e for e in all_events if filter_text.lower() in str(e.get("type", "")).lower() or filter_text.lower() in str(e.get("data", "")).lower()]
                
                with ui.column().classes("w-full gap-1 font-mono text-sm"):
                    for ev in all_events[:200]:
                        ts = ev.get("ts_ms", 0)
                        try:
                            dt = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
                        except Exception:
                            dt = "?"
                        etype = ev.get("type", "unknown")
                        data = ev.get("data", "")
                        
                        is_msg = etype in ("new_message", "message")
                        bg = "bg-blue-50" if is_msg else ("bg-green-50" if etype == "game_phase_changed" else "bg-white")
                        
                        with ui.row().classes(f"w-full px-2 py-1 {bg} rounded gap-2 items-start"):
                            ui.label(dt).classes("text-grey min-w-[60px]")
                            ui.badge(etype, color="blue" if is_msg else "grey").classes("text-xs")
                            ui.label(str(data)[:200]).classes("text-sm break-all")
            
            async def tick():
                snap = await state.snapshot()
                render_events.refresh(snap, filter_input.value)
            
            render_events({})
            ui.timer(1.0, tick)
