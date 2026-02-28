"""Blog page — displays news and bios from Cronache dal Cosmo."""
import datetime
from nicegui import ui
from app.core.state import StateStore

_render_nav = lambda: None

CATEGORY_ICONS = {
    "news": "📰",
    "bio": "👤",
}

CATEGORY_COLORS = {
    "news": "blue",
    "bio": "purple",
}


def _fmt_date(dt_val) -> str:
    if dt_val is None:
        return "?"
    try:
        if hasattr(dt_val, "strftime"):
            return dt_val.strftime("%Y-%m-%d %H:%M")
        return str(dt_val)
    except Exception:
        return str(dt_val)


def _strip_html(html: str) -> str:
    """Basic HTML tag stripping for display."""
    import re
    if not html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def build_blog_page(state: StateStore) -> None:
    @ui.page("/blog")
    async def blog_page():
        _render_nav()
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("📰 Cronache dal Cosmo").classes("text-2xl font-bold")
            ui.label("News and client profiles from the galactic blog").classes("text-grey")

            with ui.row().classes("gap-4"):
                filter_select = ui.select(
                    options=["all", "news", "bio"],
                    value="all",
                    label="Filter by category",
                ).classes("w-48")

            @ui.refreshable
            def render_articles(snap: dict, filter_cat: str = "all"):
                articles = snap.get("blog_articles") or []
                if filter_cat and filter_cat != "all":
                    articles = [a for a in articles if a.get("category") == filter_cat]

                if not articles:
                    ui.label("No blog articles found. Articles are fetched at the start of each turn.").classes("text-grey")
                    return

                # Separate news and bios
                news = [a for a in articles if a.get("category") == "news"]
                bios = [a for a in articles if a.get("category") == "bio"]

                if filter_cat == "all" or filter_cat == "news":
                    if news:
                        ui.label("📰 Latest News").classes("text-xl font-bold mt-4")
                        for article in news[:10]:
                            _render_article_card(article)

                if filter_cat == "all" or filter_cat == "bio":
                    if bios:
                        ui.label("👤 Client Profiles (Bios)").classes("text-xl font-bold mt-4")
                        ui.label("These profiles describe client preferences and behaviors.").classes("text-grey text-sm")
                        with ui.row().classes("flex-wrap gap-4 mt-2"):
                            for bio in bios[:20]:
                                _render_bio_card(bio)

            def _render_article_card(article: dict):
                title = article.get("title") or "Untitled"
                author = article.get("author") or "Unknown"
                pub_date = _fmt_date(article.get("pub_date"))
                summary = _strip_html(article.get("summary") or "")
                content = _strip_html(article.get("content") or "")
                category = article.get("category") or "news"
                icon = CATEGORY_ICONS.get(category, "📄")
                color = CATEGORY_COLORS.get(category, "grey")

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.badge(f"{icon} {category}", color=color)
                        ui.label(title).classes("text-lg font-bold")
                    with ui.row().classes("gap-4 text-sm text-grey"):
                        ui.label(f"By {author}")
                        ui.label(f"Published: {pub_date}")
                    if summary:
                        ui.label(summary[:500]).classes("mt-2")
                    with ui.expansion("Full content").classes("w-full mt-2"):
                        ui.label(content[:2000] if content else "No content available.").classes("whitespace-pre-wrap text-sm")

            def _render_bio_card(bio: dict):
                title = bio.get("title") or "Unknown"
                content = _strip_html(bio.get("content") or bio.get("summary") or "")

                with ui.card().classes("w-80"):
                    ui.label(f"👤 {title}").classes("text-lg font-bold")
                    ui.label(content[:300] if content else "No description.").classes("text-sm mt-1")

            filter_select.on("update:model-value", lambda e: render_articles.refresh(_last_snap[0], filter_select.value))

            _last_snap: list[dict] = [{}]

            async def tick():
                snap = await state.snapshot()
                _last_snap[0] = snap
                render_articles.refresh(snap, filter_select.value)

            render_articles({})
            ui.timer(5.0, tick)
