"""Recipe catalog page — shows all recipes with ingredients and per-turn stats."""
from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None


def build_recipes_page(state: StateStore) -> None:
    @ui.page("/recipes")
    async def recipes_page():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("📖 Recipe Catalog").classes("text-2xl font-bold")

            @ui.refreshable
            def render_recipes(snap: dict):
                recipes = snap.get("recipes") or []
                recipe_stats = snap.get("recipe_stats") or []

                # Build a lookup: recipe_name → stats
                stats_by_name: dict[str, dict] = {}
                for s in recipe_stats:
                    name = s.get("recipe_name") or ""
                    if name:
                        stats_by_name[name] = s

                if not recipes:
                    ui.label("No recipe data. Populated after first game turn.").classes("text-grey")
                    return

                # ── Recipe stats table (if available) ──
                if recipe_stats:
                    ui.label("📊 This Turn's Performance").classes("text-lg font-bold")
                    columns = [
                        {"name": "recipe", "label": "Recipe", "field": "recipe", "sortable": True},
                        {"name": "prestige", "label": "Prestige", "field": "prestige", "sortable": True},
                        {"name": "requests", "label": "Requests", "field": "requests", "sortable": True},
                        {"name": "served", "label": "Served", "field": "served", "sortable": True},
                        {"name": "rate", "label": "Rate %", "field": "rate", "sortable": True},
                    ]
                    rows = []
                    for s in sorted(recipe_stats, key=lambda x: x.get("num_requests", 0), reverse=True):
                        reqs = s.get("num_requests") or 0
                        served = s.get("num_served") or 0
                        rate = f"{served / reqs * 100:.0f}" if reqs > 0 else "—"
                        rows.append({
                            "recipe": s.get("recipe_name") or "?",
                            "prestige": str(s.get("prestige") or 0),
                            "requests": str(reqs),
                            "served": str(served),
                            "rate": rate,
                        })
                    ui.table(columns=columns, rows=rows, row_key="recipe").classes("w-full mb-4")

                # ── Full recipe catalog ──
                ui.label(f"📋 All Recipes ({len(recipes)})").classes("text-lg font-bold mt-2")
                for r in sorted(recipes, key=lambda x: x.get("name", "")):
                    name = r.get("name") or "Unknown"
                    prestige = r.get("prestige") or 0
                    prep_ms = r.get("preparation_time_ms") or 0
                    prep_s = f"{prep_ms / 1000:.1f}s" if prep_ms else "?"
                    ingredients = r.get("ingredients") or {}
                    stats = stats_by_name.get(name)

                    header = f"{'⭐' * min(prestige, 5)} {name}  (prestige {prestige}, prep {prep_s})"
                    with ui.expansion(header).classes("w-full"):
                        if ingredients:
                            with ui.row().classes("flex-wrap gap-2"):
                                for ing, qty in sorted(ingredients.items()):
                                    ui.badge(f"{ing} ×{qty}", color="teal")
                        else:
                            ui.label("No ingredients listed.").classes("text-sm text-grey")
                        if stats:
                            reqs = stats.get("num_requests") or 0
                            served = stats.get("num_served") or 0
                            rate = f"{served / reqs * 100:.0f}%" if reqs > 0 else "—"
                            ui.label(f"This turn: {reqs} requests, {served} served ({rate})").classes("text-sm text-green mt-1")

            async def tick():
                snap = await state.snapshot()
                render_recipes.refresh(snap)

            render_recipes({})
            ui.timer(5.0, tick)
