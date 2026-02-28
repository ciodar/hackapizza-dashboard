from nicegui import ui
from app.core.state import StateStore
from app.alerts.engine import AlertEngine
from app.clients.hackapizza_mcp import HackapizzaMcpClient
from app.ui.pages import overview, endpoint_health, competition, serving, market, bids, events, actions

NAV_ITEMS = [
    ("/", "🏠 Overview"),
    ("/health", "🔌 Endpoint Health"),
    ("/competition", "🏆 Competition"),
    ("/serving", "🍽️ Serving"),
    ("/market", "🛒 Market"),
    ("/bids", "📊 Bids"),
    ("/events", "📡 Events"),
    ("/actions", "⚡ Actions"),
]

def _render_nav():
    with ui.header().classes("bg-gray-900 text-white"):
        with ui.row().classes("w-full items-center gap-4 px-4"):
            ui.label("🍕 Hackapizza").classes("text-xl font-bold text-white")
            for path, label in NAV_ITEMS:
                ui.link(label, path).classes("text-white no-underline hover:underline text-sm")

import app.ui.pages.overview as _ov
import app.ui.pages.endpoint_health as _eh
import app.ui.pages.competition as _comp
import app.ui.pages.serving as _srv
import app.ui.pages.market as _mkt
import app.ui.pages.bids as _bids
import app.ui.pages.events as _ev
import app.ui.pages.actions as _act

_ov._render_nav = _render_nav
_eh._render_nav = _render_nav
_comp._render_nav = _render_nav
_srv._render_nav = _render_nav
_mkt._render_nav = _render_nav
_bids._render_nav = _render_nav
_ev._render_nav = _render_nav
_act._render_nav = _render_nav

def build_ui(state: StateStore, alert_engine: AlertEngine, mcp: HackapizzaMcpClient | None) -> None:
    overview.build_overview_page(state)
    endpoint_health.build_endpoint_health_page(state)
    competition.build_competition_page(state)
    serving.build_serving_page(state)
    market.build_market_page(state)
    bids.build_bids_page(state)
    events.build_events_page(state)
    actions.build_actions_page(state, mcp)
