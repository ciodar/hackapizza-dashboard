import json
import sqlite3
from typing import Any

class SQLiteStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None

    def init_schema(self) -> None:
        conn = self._get_conn()
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                endpoint_name TEXT NOT NULL,
                ok INTEGER NOT NULL,
                status_code INTEGER,
                latency_ms REAL,
                error TEXT,
                payload_summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sse_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                type TEXT NOT NULL,
                data TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                table_name TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
        return self._conn

    def insert_endpoint_check(self, row: dict[str, Any]) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO endpoint_checks (ts_ms, endpoint_name, ok, status_code, latency_ms, error, payload_summary) VALUES (?,?,?,?,?,?,?)",
            (row.get("ts_ms"), row.get("endpoint_name"), int(row.get("ok", False)), row.get("status_code"), row.get("latency_ms"), row.get("error"), json.dumps(row.get("payload_summary")))
        )
        conn.commit()

    def insert_sse_event(self, row: dict[str, Any]) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sse_events (ts_ms, type, data) VALUES (?,?,?)",
            (row.get("ts_ms"), row.get("type"), json.dumps(row.get("data")))
        )
        conn.commit()

    def insert_snapshot(self, table: str, ts_ms: int, payload: dict[str, Any]) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO snapshots (ts_ms, table_name, payload) VALUES (?,?,?)",
            (ts_ms, table, json.dumps(payload))
        )
        conn.commit()
