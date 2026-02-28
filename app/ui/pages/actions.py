from nicegui import ui
from app.core.state import StateStore
from app.clients.hackapizza_mcp import HackapizzaMcpClient
from app.core.utils import is_tool_allowed
from app.models.common import GamePhase

_render_nav = lambda: None

TOOLS = [
    ("save_menu", "Save Menu", [("items", "list", 'e.g. [{"name": "Pizza", "price": 10}]')]),
    ("closed_bid", "Closed Bid", [("bids", "list", 'e.g. [{"ingredient": "flour", "bid": 5, "quantity": 10}]')]),
    ("prepare_dish", "Prepare Dish", [("dish_name", "str", "e.g. Margherita Pizza")]),
    ("serve_dish", "Serve Dish", [("dish_name", "str", "dish name"), ("client_id", "str", "client ID")]),
    ("create_market_entry", "Create Market Entry", [("side", "str", "BUY or SELL"), ("ingredient_name", "str", "ingredient"), ("quantity", "float", "qty"), ("price", "float", "price")]),
    ("execute_transaction", "Execute Transaction", [("market_entry_id", "int", "entry ID")]),
    ("delete_market_entry", "Delete Market Entry", [("market_entry_id", "int", "entry ID")]),
    ("send_message", "Send Message", [("recipient_id", "int", "recipient restaurant ID"), ("text", "str", "message text")]),
    ("update_restaurant_is_open", "Update Open Status", [("is_open", "bool", "true/false")]),
]

def build_actions_page(state: StateStore, mcp: HackapizzaMcpClient | None) -> None:
    @ui.page("/actions")
    async def actions():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("⚡ Actions (MCP)").classes("text-2xl font-bold")
            
            if mcp is None:
                ui.label("MCP client not configured (no API key).").classes("text-red")
                return
            
            result_log = ui.column().classes("w-full gap-1 font-mono text-sm mt-4")
            
            snap = await state.snapshot()
            phase_str = snap.get("phase", "unknown")
            try:
                phase = GamePhase(phase_str)
            except Exception:
                phase = GamePhase.UNKNOWN
            
            ui.badge(f"Phase: {phase.value}", color="blue").classes("mb-4")
            
            for tool_name, tool_label, fields in TOOLS:
                allowed = is_tool_allowed(phase, tool_name)
                with ui.expansion(f"{'✅' if allowed else '🚫'} {tool_label}").classes("w-full"):
                    if not allowed:
                        ui.label(f"Not allowed in phase: {phase.value}").classes("text-red text-sm")
                        continue
                    
                    inputs = {}
                    for field_name, field_type, placeholder in fields:
                        inp = ui.input(label=field_name, placeholder=placeholder).classes("w-full")
                        inputs[field_name] = (inp, field_type)
                    
                    async def call_tool(tn=tool_name, inp=inputs):
                        args = {}
                        for fname, (inp_widget, ftype) in inp.items():
                            val = inp_widget.value
                            try:
                                if ftype == "int":
                                    args[fname] = int(val)
                                elif ftype == "float":
                                    args[fname] = float(val)
                                elif ftype == "bool":
                                    args[fname] = val.lower() in ("true", "1", "yes")
                                elif ftype == "list":
                                    import json
                                    args[fname] = json.loads(val)
                                else:
                                    args[fname] = val
                            except Exception as e:
                                ui.notify(f"Invalid input for {fname}: {e}", type="negative")
                                return
                        
                        result = await mcp.call_tool(tn, args)
                        status = "✅" if not result.is_error else "❌"
                        msg = result.content_text or result.error or str(result.raw)
                        with result_log:
                            ui.label(f"{status} [{tn}] {msg[:200]}").classes("text-sm")
                        ui.notify(f"{status} {tn}: {msg[:100]}", type="positive" if not result.is_error else "negative")
                    
                    ui.button(f"Execute {tool_label}", on_click=call_tool).classes("mt-2")
