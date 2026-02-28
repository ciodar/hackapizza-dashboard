import asyncio
import logging
import os

from fastapi import FastAPI
from nicegui import ui, app as nicegui_app

from app.config import AppConfig
from app.core.state import StateStore
from app.core.event_bus import EventBus
from app.clients.hackapizza_http import HackapizzaHttpClient
from app.clients.hackapizza_mcp import HackapizzaMcpClient
from app.alerts.engine import AlertEngine
from app.storage.sqlite import SQLiteStore
from app.storage.repository import Repository
from app.storage.mysql_reader import MySQLReader
from app.collectors.mysql_poller import MySQLPoller
from app.models.common import GamePhase
from app.ui.app_ui import build_ui

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

config = AppConfig()
state = StateStore()
bus = EventBus()

# SSE is intentionally disabled: only one SSE connection per restaurant is allowed
# (returns 409 if already active). The restaurant agent owns that connection.
state.last_sse_error = "SSE disabled — reserved for the restaurant agent (single connection per restaurant)"

http_client: HackapizzaHttpClient | None = None
mcp_client: HackapizzaMcpClient | None = None
_tasks: list[asyncio.Task] = []
_runtime_config = {"restaurant_id": config.restaurant_id, "turn_id": config.turn_id, "polling_mode": config.polling_mode}

def get_ctx():
    return dict(_runtime_config)

async def startup():
    global http_client, mcp_client

    logger.info(f"Starting Hackapizza Dashboard (base_url={config.base_url}, restaurant_id={config.restaurant_id})")

    http_client = HackapizzaHttpClient(config.base_url, config.api_key, config.http_timeout_s)

    if config.api_key:
        mcp_client = HackapizzaMcpClient(http_client)

    if config.persistence_enabled:
        db = SQLiteStore(config.sqlite_path)
        db.init_schema()
        repo = Repository(db)

    if config.mysql_enabled:
        mysql_reader = MySQLReader(
            host=config.mysql_host,
            port=config.mysql_port,
            user=config.mysql_user,
            password=config.mysql_password,
            db=config.mysql_db,
        )
        try:
            await mysql_reader.connect()
            mysql_poller = MySQLPoller(state, mysql_reader, _runtime_config, config.mysql_poll_interval_s)
            _tasks.append(asyncio.create_task(mysql_poller.run_forever(), name="mysql_poller"))
            logger.info("MySQLPoller started — tailing main.py events from MySQL")
        except Exception as exc:
            logger.warning(f"Could not connect to MySQL, dashboard will work without live events: {exc}")

    alert_engine = AlertEngine(state)
    _tasks.append(asyncio.create_task(alert_engine.run_forever(), name="alerts"))

    logger.info("Background tasks started (SSE disabled — reserved for agent)")

async def shutdown():
    for task in _tasks:
        task.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
    if http_client:
        await http_client.close()
    logger.info("Shutdown complete")

fastapi_app = FastAPI(title="Hackapizza Dashboard API")

@fastapi_app.get("/api/state")
async def get_state():
    return await state.snapshot()

@fastapi_app.get("/api/config")
async def get_config():
    return _runtime_config

from pydantic import BaseModel
from typing import Optional

class UpdateConfig(BaseModel):
    restaurant_id: Optional[int] = None
    turn_id: Optional[int] = None
    polling_mode: Optional[str] = None

@fastapi_app.post("/api/config")
async def update_config(body: UpdateConfig):
    if body.restaurant_id is not None:
        _runtime_config["restaurant_id"] = body.restaurant_id
    if body.turn_id is not None:
        _runtime_config["turn_id"] = body.turn_id
    if body.polling_mode is not None:
        _runtime_config["polling_mode"] = body.polling_mode
    return _runtime_config

@fastapi_app.post("/api/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str):
    async with state.lock:
        if alert_id in state.active_alerts:
            state.active_alerts[alert_id].acknowledged = True
            return {"ok": True}
    return {"ok": False}

nicegui_app.on_startup(startup)
nicegui_app.on_shutdown(shutdown)

def create_app() -> FastAPI:
    alert_engine_for_ui = AlertEngine(state)
    build_ui(state, alert_engine_for_ui, mcp_client)
    ui.run_with(fastapi_app, mount_path="/", storage_secret="hackapizza-secret-42")
    return fastapi_app
