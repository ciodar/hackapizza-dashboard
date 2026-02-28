"""
Seed the MySQL database with realistic test data across 3 turns.
Covers all tables written by the agent so every dashboard page has data to show.

Usage:
    cd hackapizza-dashboard
    python -m tests.seed_test_data

Or with custom DB params:
    MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_USER=appuser \
    MYSQL_PASSWORD=apppassword MYSQL_DB=hackapizza \
    python -m tests.seed_test_data

Pass --clear to wipe existing data first (test-only tables).
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

import aiomysql

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", 3306)),
    "user": os.getenv("MYSQL_USER", "appuser"),
    "password": os.getenv("MYSQL_PASSWORD", "apppassword"),
    "db": os.getenv("MYSQL_DB", "hackapizza"),
}

# ─── Schema (mirrors hackapizza/db.py SCHEMA exactly) ─────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS sse_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    event_type VARCHAR(64),
    event_json JSON,
    phase VARCHAR(32),
    turn_number INT
);

CREATE TABLE IF NOT EXISTS phase_transitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    from_phase VARCHAR(32),
    to_phase VARCHAR(32),
    turn_number INT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    kind VARCHAR(64),
    data_json JSON,
    phase VARCHAR(32),
    turn_number INT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    agent_name VARCHAR(64),
    decision_type VARCHAR(64),
    data_json JSON,
    phase VARCHAR(32),
    turn_number INT
);

CREATE TABLE IF NOT EXISTS mcp_calls (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    tool_name VARCHAR(64),
    args_json JSON,
    result_json JSON,
    is_error BOOLEAN DEFAULT FALSE,
    latency_ms INT,
    phase VARCHAR(32),
    turn_number INT
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    first_seen_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_ingredient_name (name)
);

CREATE TABLE IF NOT EXISTS recipes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    prestige INT NOT NULL DEFAULT 0,
    preparation_time_ms INT NOT NULL DEFAULT 0,
    description TEXT,
    UNIQUE KEY uq_recipe_name (name)
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    recipe_id INT NOT NULL,
    ingredient_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    UNIQUE KEY uq_recipe_ingredient (recipe_id, ingredient_id),
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
);

CREATE TABLE IF NOT EXISTS recipe_stats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    recipe_id INT NOT NULL,
    turn_id INT NOT NULL,
    avg_price DECIMAL(10,2),
    min_price DECIMAL(10,2),
    max_price DECIMAL(10,2),
    num_requests INT NOT NULL DEFAULT 0,
    num_served INT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_recipe_turn (recipe_id, turn_id),
    FOREIGN KEY (recipe_id) REFERENCES recipes(id)
);

CREATE TABLE IF NOT EXISTS ingredient_bid_stats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ingredient_id INT NOT NULL,
    turn_id INT NOT NULL,
    avg_price_paid DECIMAL(10,2),
    min_price_paid DECIMAL(10,2),
    max_price_paid DECIMAL(10,2),
    total_quantity INT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_ingredient_turn (ingredient_id, turn_id),
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
);

CREATE TABLE IF NOT EXISTS bid_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    turn_id INT NOT NULL,
    restaurant_id INT,
    restaurant_name VARCHAR(255),
    ingredient_id INT,
    ingredient_name VARCHAR(255) NOT NULL,
    quantity INT NOT NULL DEFAULT 0,
    price DECIMAL(10,2) NOT NULL,
    fetched_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    KEY idx_bid_history_turn (turn_id),
    KEY idx_bid_history_ingredient (ingredient_id),
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
);

CREATE TABLE IF NOT EXISTS customer_name_map (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    customer_id INT NOT NULL,
    first_seen_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_customer_name (customer_name)
);

CREATE TABLE IF NOT EXISTS agent_prompts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    agent_name VARCHAR(64),
    system_prompt TEXT,
    input_prompt TEXT,
    output_json JSON,
    phase VARCHAR(32),
    turn_number INT
);
"""


async def init_schema(pool: aiomysql.Pool) -> None:
    """Create all tables if they don't exist (mirrors hackapizza/db.py)."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SET sql_notes = 0")
            for statement in SCHEMA.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    await cur.execute(stmt)
            await cur.execute("SET sql_notes = 1")
    print("✅ Schema initialized (all tables created if missing).")


RECIPES = [
    {
        "name": "Margherita Quantistica",
        "prestige": 3,
        "preparation_time_ms": 4000,
        "ingredients": {"Farina di Grano Antico": 2, "Pomodoro Bionico": 3, "Mozzarella di Bufala": 2},
    },
    {
        "name": "Pizza al Tartufo Nero",
        "prestige": 5,
        "preparation_time_ms": 8000,
        "ingredients": {"Tartufo Nero": 1, "Farina di Grano Antico": 2, "Olio di Oliva Extravergine": 1},
    },
    {
        "name": "Calzone Dimensionale",
        "prestige": 4,
        "preparation_time_ms": 6000,
        "ingredients": {"Farina di Grano Antico": 3, "Mozzarella di Bufala": 3, "Pomodoro Bionico": 2},
    },
    {
        "name": "Focaccia con Rosmarino",
        "prestige": 2,
        "preparation_time_ms": 3000,
        "ingredients": {"Farina di Grano Antico": 2, "Olio di Oliva Extravergine": 2, "Sale Rosa": 1},
    },
    {
        "name": "Bruschetta al Pesto",
        "prestige": 2,
        "preparation_time_ms": 2000,
        "ingredients": {"Pane Antico": 2, "Pesto di Basilico": 2, "Pomodoro Bionico": 1},
    },
    {
        "name": "Risotto ai Funghi Cosmici",
        "prestige": 4,
        "preparation_time_ms": 7000,
        "ingredients": {"Riso Arborio": 3, "Funghi Porcini": 2, "Burro Quantistico": 1},
    },
]

TURNS = [1, 2, 3]
TURN_IDS = {1: 101, 2: 102, 3: 103}  # turn_number → turn_id (as stored by agent)

RESTAURANT_ID = 1
BASE_BALANCE = 1500.0
BASE_REPUTATION = 7.5


async def seed_all(pool: aiomysql.Pool, clear: bool = False) -> None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if clear:
                print("Clearing test data...")
                for table in [
                    "agent_prompts", "mcp_calls", "decisions", "snapshots",
                    "phase_transitions", "sse_events",
                    "ingredient_bid_stats", "bid_history",
                    "recipe_stats", "recipe_ingredients", "recipes", "ingredients",
                    "customer_name_map",
                ]:
                    await cur.execute(f"DELETE FROM {table}")
                print("  cleared.")

            # ── Seed recipes + ingredients ──────────────────────────────────────
            print("Seeding recipes and ingredients...")
            recipe_ids: dict[str, int] = {}
            ingredient_ids: dict[str, int] = {}

            for recipe in RECIPES:
                await cur.execute(
                    """
                    INSERT INTO recipes (name, prestige, preparation_time_ms)
                    VALUES (%s, %s, %s) AS nr
                    ON DUPLICATE KEY UPDATE prestige=nr.prestige, preparation_time_ms=nr.preparation_time_ms
                    """,
                    (recipe["name"], recipe["prestige"], recipe["preparation_time_ms"]),
                )
                await cur.execute("SELECT id FROM recipes WHERE name=%s", (recipe["name"],))
                recipe_ids[recipe["name"]] = (await cur.fetchone())[0]

                for ing_name in recipe["ingredients"]:
                    if ing_name not in ingredient_ids:
                        await cur.execute(
                            "INSERT INTO ingredients (name) VALUES (%s) AS ni ON DUPLICATE KEY UPDATE name=ni.name",
                            (ing_name,),
                        )
                        await cur.execute("SELECT id FROM ingredients WHERE name=%s", (ing_name,))
                        ingredient_ids[ing_name] = (await cur.fetchone())[0]

                    qty = recipe["ingredients"][ing_name]
                    await cur.execute(
                        """
                        INSERT INTO recipe_ingredients (recipe_id, ingredient_id, quantity)
                        VALUES (%s, %s, %s) AS nri
                        ON DUPLICATE KEY UPDATE quantity=nri.quantity
                        """,
                        (recipe_ids[recipe["name"]], ingredient_ids[ing_name], qty),
                    )

            print(f"  {len(recipe_ids)} recipes, {len(ingredient_ids)} ingredients.")

            # ── Seed 3 turns of game events ─────────────────────────────────────
            for turn_num in TURNS:
                turn_id = TURN_IDS[turn_num]
                balance = BASE_BALANCE + (turn_num - 1) * 120.0
                reputation = BASE_REPUTATION + (turn_num - 1) * 0.3
                now = datetime.now() - timedelta(hours=(3 - turn_num) * 2)

                print(f"  Turn {turn_num} (turn_id={turn_id})...")

                # ── SSE events ──────────────────────────────────────────────────
                def _sse(event_type, data, phase, minutes_offset=0):
                    ts = now + timedelta(minutes=minutes_offset)
                    return (
                        ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        event_type,
                        json.dumps(data),
                        phase,
                        turn_num,
                    )

                sse_rows = [
                    _sse("game_started", {"turn_id": turn_id, "turn_number": turn_num}, "speaking", 0),
                    _sse("heartbeat", {"ts": now.isoformat()}, "speaking", 1),
                    _sse("game_phase_changed", {"phase": "closed_bid"}, "speaking", 5),
                    _sse("heartbeat", {"ts": (now + timedelta(minutes=6)).isoformat()}, "closed_bid", 6),
                    _sse("game_phase_changed", {"phase": "waiting"}, "closed_bid", 10),
                    _sse("game_phase_changed", {"phase": "serving"}, "waiting", 15),
                    _sse("client_spawned", {"clientId": 1, "clientName": "Andromeda", "orderText": "Margherita Quantistica please"}, "serving", 16),
                    _sse("client_spawned", {"clientId": 2, "clientName": "Zenith", "orderText": "Pizza al Tartufo Nero"}, "serving", 17),
                    _sse("client_spawned", {"clientId": 3, "clientName": "Vega", "orderText": "Focaccia con Rosmarino"}, "serving", 18),
                    _sse("game_phase_changed", {"phase": "stopped"}, "serving", 30),
                ]
                await cur.executemany(
                    "INSERT INTO sse_events (ts, event_type, event_json, phase, turn_number) VALUES (%s, %s, %s, %s, %s)",
                    sse_rows,
                )

                # ── Phase transitions ───────────────────────────────────────────
                phase_rows = [
                    (now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], None, "speaking", turn_num),
                    ((now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "speaking", "closed_bid", turn_num),
                    ((now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "closed_bid", "waiting", turn_num),
                    ((now + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "waiting", "serving", turn_num),
                    ((now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "serving", "stopped", turn_num),
                ]
                await cur.executemany(
                    "INSERT INTO phase_transitions (ts, from_phase, to_phase, turn_number) VALUES (%s, %s, %s, %s)",
                    phase_rows,
                )

                # ── Snapshots ───────────────────────────────────────────────────
                inventory = {
                    "Farina di Grano Antico": 8 + turn_num,
                    "Pomodoro Bionico": 6,
                    "Mozzarella di Bufala": 5,
                    "Tartufo Nero": 2,
                    "Olio di Oliva Extravergine": 4,
                    "Sale Rosa": 3,
                    "Pane Antico": 4,
                    "Pesto di Basilico": 3,
                    "Riso Arborio": 5,
                    "Funghi Porcini": 3,
                    "Burro Quantistico": 2,
                }

                snap_rows = [
                    (
                        (now + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "restaurant",
                        json.dumps({"balance": balance, "inventory": inventory, "reputation": reputation}),
                        "speaking", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "restaurant_post_bid",
                        json.dumps({"balance": balance - 80.0, "inventory": {k: v + 2 for k, v in inventory.items()}}),
                        "waiting", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "turn_end",
                        json.dumps({
                            "balance": balance + 95.0,
                            "reputation": reputation + 0.2,
                            "used_ingredients": {"Farina di Grano Antico": 4, "Pomodoro Bionico": 3, "Mozzarella di Bufala": 2},
                            "unused_ingredients": {"Sale Rosa": 2, "Burro Quantistico": 1},
                            "clients_served": 8,
                            "clients_not_served": 2,
                            "total_clients": 10,
                            "menu": [
                                {"name": "Margherita Quantistica", "price": 75},
                                {"name": "Pizza al Tartufo Nero", "price": 150},
                                {"name": "Focaccia con Rosmarino", "price": 45},
                                {"name": "Risotto ai Funghi Cosmici", "price": 110},
                            ],
                        }),
                        "stopped", turn_num,
                    ),
                ]
                await cur.executemany(
                    "INSERT INTO snapshots (ts, kind, data_json, phase, turn_number) VALUES (%s, %s, %s, %s, %s)",
                    snap_rows,
                )

                # ── Decisions ───────────────────────────────────────────────────
                menu_items = [
                    {"name": "Margherita Quantistica", "price": 75},
                    {"name": "Pizza al Tartufo Nero", "price": 150},
                    {"name": "Focaccia con Rosmarino", "price": 45},
                    {"name": "Risotto ai Funghi Cosmici", "price": 110},
                ]
                bid_decision = {
                    "bids": [
                        {"ingredient": "Farina di Grano Antico", "quantity": 5, "bid": 12.50},
                        {"ingredient": "Pomodoro Bionico", "quantity": 4, "bid": 8.00},
                        {"ingredient": "Mozzarella di Bufala", "quantity": 3, "bid": 15.00},
                        {"ingredient": "Tartufo Nero", "quantity": 1, "bid": 55.00},
                    ],
                    "reasoning": "Covering menu ingredients for 5 orders each. Tartufo is premium bid.",
                }
                market_decision = {
                    "actions": [
                        {"type": "EXECUTE", "market_entry_id": "42"},
                        {"type": "CREATE", "side": "BUY", "ingredient_name": "Riso Arborio", "quantity": 2, "price": 10.0},
                    ],
                    "spent": 38.50,
                }
                turn_summary = {
                    "summary": f"Turn {turn_num}: Served 8/10 clients. Revenue approx 800cr. "
                               f"Bid on 4 ingredients; won Farina, Pomodoro, Mozzarella. "
                               f"Market agent bought Riso Arborio to cover Risotto orders. "
                               f"Balance +95cr, reputation +0.2.",
                }

                decision_rows = [
                    (
                        (now + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "menu_agent", "menu_plan",
                        json.dumps({"items": menu_items, "reasoning": "Volume-focused menu, 4 items covering all ingredients."}),
                        "speaking", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=7)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "bid_agent", "bid_plan",
                        json.dumps(bid_decision),
                        "closed_bid", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=13)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "market_agent", "market_waiting",
                        json.dumps(market_decision),
                        "waiting", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=32)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "memory_agent", "turn_summary",
                        json.dumps(turn_summary),
                        "stopped", turn_num,
                    ),
                ]
                await cur.executemany(
                    "INSERT INTO decisions (ts, agent_name, decision_type, data_json, phase, turn_number) VALUES (%s, %s, %s, %s, %s, %s)",
                    decision_rows,
                )

                # ── MCP calls ───────────────────────────────────────────────────
                mcp_rows = [
                    (
                        (now + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "save_menu",
                        json.dumps({"items": menu_items}),
                        json.dumps({"content": "Menu saved successfully"}),
                        False, 95, "speaking", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=8)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "closed_bid",
                        json.dumps(bid_decision["bids"]),
                        json.dumps({"content": "Bids submitted"}),
                        False, 110, "closed_bid", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=16)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "prepare_dish",
                        json.dumps({"dish_name": "Margherita Quantistica"}),
                        json.dumps({"content": "Dish prepared"}),
                        False, 4100, "serving", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=17)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "serve_dish",
                        json.dumps({"dish_name": "Margherita Quantistica", "client_id": "1"}),
                        json.dumps({"content": "Dish served, +75cr"}),
                        False, 80, "serving", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=17)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "prepare_dish",
                        json.dumps({"dish_name": "Pizza al Tartufo Nero"}),
                        json.dumps({"content": "Dish prepared"}),
                        False, 8200, "serving", turn_num,
                    ),
                    (
                        (now + timedelta(minutes=18)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "serve_dish",
                        json.dumps({"dish_name": "Pizza al Tartufo Nero", "client_id": "2"}),
                        json.dumps({"content": "Dish served, +150cr"}),
                        False, 75, "serving", turn_num,
                    ),
                ]
                await cur.executemany(
                    "INSERT INTO mcp_calls (ts, tool_name, args_json, result_json, is_error, latency_ms, phase, turn_number) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    mcp_rows,
                )

                # ── Bid history (all restaurants) ────────────────────────────────
                bid_history_rows = []
                restaurants = [
                    (RESTAURANT_ID, "Datapizza"),
                    (2, "La Trattoria Galattica"),
                    (3, "Ristorante del Futuro"),
                ]
                for ing_name, ing_id in ingredient_ids.items():
                    import random
                    random.seed(turn_num * 100 + ing_id)
                    for rest_id, rest_name in restaurants:
                        price = round(random.uniform(5.0, 60.0), 2)
                        qty = random.randint(1, 8)
                        bid_history_rows.append(
                            (turn_id, rest_id, rest_name, ing_id, ing_name, qty, price,
                             (now + timedelta(minutes=9)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])
                        )
                await cur.executemany(
                    "INSERT INTO bid_history (turn_id, restaurant_id, restaurant_name, ingredient_id, ingredient_name, quantity, price, fetched_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    bid_history_rows,
                )

                # ── Ingredient bid stats (aggregates) ────────────────────────────
                for ing_name, ing_id in ingredient_ids.items():
                    prices = [r[6] for r in bid_history_rows if r[4] == ing_name]
                    if not prices:
                        continue
                    await cur.execute(
                        """
                        INSERT INTO ingredient_bid_stats
                            (ingredient_id, turn_id, avg_price_paid, min_price_paid, max_price_paid, total_quantity)
                        VALUES (%s, %s, %s, %s, %s, %s) AS ni
                        ON DUPLICATE KEY UPDATE
                            avg_price_paid=ni.avg_price_paid, min_price_paid=ni.min_price_paid,
                            max_price_paid=ni.max_price_paid, total_quantity=ni.total_quantity
                        """,
                        (
                            ing_id, turn_id,
                            round(sum(prices) / len(prices), 2),
                            round(min(prices), 2),
                            round(max(prices), 2),
                            sum(r[5] for r in bid_history_rows if r[4] == ing_name),
                        ),
                    )

                # ── Recipe stats ─────────────────────────────────────────────────
                import random
                random.seed(turn_num * 999)
                for recipe in RECIPES:
                    rid = recipe_ids[recipe["name"]]
                    requests = random.randint(1, 6)
                    served = random.randint(0, requests)
                    await cur.execute(
                        """
                        INSERT INTO recipe_stats (recipe_id, turn_id, num_requests, num_served)
                        VALUES (%s, %s, %s, %s) AS nr
                        ON DUPLICATE KEY UPDATE num_requests=nr.num_requests, num_served=nr.num_served
                        """,
                        (rid, turn_id, requests, served),
                    )

                # ── Customer name map ────────────────────────────────────────────
                customers = [("Andromeda", 1001), ("Zenith", 1002), ("Vega", 1003)]
                for cname, cid in customers:
                    await cur.execute(
                        """
                        INSERT INTO customer_name_map (customer_name, customer_id)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE customer_id=VALUES(customer_id)
                        """,
                        (cname, cid),
                    )

                print(f"    Turn {turn_num} done.")

    print("✅ Seed complete.")


async def main():
    clear = "--clear" in sys.argv
    pool = await aiomysql.create_pool(minsize=1, maxsize=2, autocommit=True, **DB_CONFIG)
    try:
        await init_schema(pool)
        await seed_all(pool, clear=clear)
    finally:
        pool.close()
        await pool.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
