from nicegui import ui
from app.core.state import StateStore
from app.alerts.engine import AlertEngine
from app.ui.pages import overview, restaurant, serving, market, bids, events, decisions, recipes, agent, blog

NAV_ITEMS = [
    ("/", "🏠 Overview"),
    ("/restaurant", "🏠 My Restaurant"),
    ("/serving", "🍽️ Serving"),
    ("/market", "🛒 Market"),
    ("/bids", "📊 Bids"),
    ("/recipes", "📖 Recipes"),
    ("/decisions", "🧠 Decisions"),
    ("/events", "📡 Events"),
    ("/agent", "🤖 Agent Prompts"),
    ("/blog", "📰 Blog"),
]

def _render_nav():
    with ui.header().classes("bg-gray-900 text-white"):
        with ui.row().classes("w-full items-center gap-4 px-4"):
            ui.label("🍕 Hackapizza").classes("text-xl font-bold text-white")
            for path, label in NAV_ITEMS:
                ui.link(label, path).classes("text-white no-underline hover:underline text-sm")

import app.ui.pages.overview as _ov
import app.ui.pages.restaurant as _rest
import app.ui.pages.serving as _srv
import app.ui.pages.market as _mkt
import app.ui.pages.bids as _bids
import app.ui.pages.events as _ev
import app.ui.pages.decisions as _dec
import app.ui.pages.recipes as _rec
import app.ui.pages.agent as _agt
import app.ui.pages.blog as _blog

_ov._render_nav = _render_nav
_rest._render_nav = _render_nav
_srv._render_nav = _render_nav
_mkt._render_nav = _render_nav
_bids._render_nav = _render_nav
_ev._render_nav = _render_nav
_dec._render_nav = _render_nav
_rec._render_nav = _render_nav
_agt._render_nav = _render_nav
_blog._render_nav = _render_nav

def build_ui(state: StateStore, alert_engine: AlertEngine) -> None:
    overview.build_overview_page(state)
    restaurant.build_restaurant_page(state)
    serving.build_serving_page(state)
    market.build_market_page(state)
    bids.build_bids_page(state)
    events.build_events_page(state)
    decisions.build_decisions_page(state)
    recipes.build_recipes_page(state)
    agent.build_agent_page(state)
    blog.build_blog_page(state)
