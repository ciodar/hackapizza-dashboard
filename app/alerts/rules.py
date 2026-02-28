import time
from typing import Any

from app.models.alerts import AlertInstance
from app.models.common import Severity

def _ts() -> int:
    return int(time.time() * 1000)

def _make_alert(alert_id: str, severity: Severity, title: str, message: str, existing: dict[str, AlertInstance]) -> AlertInstance:
    now = _ts()
    if alert_id in existing:
        old = existing[alert_id]
        return AlertInstance(alert_id=alert_id, severity=severity, title=title, message=message, first_seen_ms=old.first_seen_ms, last_seen_ms=now, acknowledged=old.acknowledged)
    return AlertInstance(alert_id=alert_id, severity=severity, title=title, message=message, first_seen_ms=now, last_seen_ms=now)

def evaluate_all_rules(snap: dict[str, Any], existing: dict[str, AlertInstance]) -> dict[str, AlertInstance]:
    alerts: dict[str, AlertInstance] = {}
    now = _ts()

    # DB connectivity alert
    if not snap.get("db_connected", False):
        db_err = snap.get("last_db_error") or "No recent heartbeat from MySQL"
        alerts["db_disconnected"] = _make_alert("db_disconnected", Severity.CRIT, "Database Disconnected", db_err, existing)

    # Serving phase but restaurant closed
    phase = snap.get("phase")
    my = snap.get("my_restaurant") or {}
    if phase == "serving" and my.get("is_open") is False:
        alerts["serving_closed"] = _make_alert("serving_closed", Severity.CRIT, "Restaurant Closed During Service", "Restaurant is closed while in serving phase", existing)

    # Serving phase but empty menu
    if phase == "serving" and len(snap.get("menu") or []) == 0:
        alerts["serving_no_menu"] = _make_alert("serving_no_menu", Severity.CRIT, "No Menu During Service", "Menu is empty while in serving phase", existing)

    # Serving backlog
    meals = snap.get("meals") or []
    pending = sum(1 for m in meals if not m.get("executed"))
    if pending >= 10:
        alerts["serving_backlog_crit"] = _make_alert("serving_backlog_crit", Severity.CRIT, "Serving Backlog Critical", f"{pending} pending meals", existing)
    elif pending >= 5:
        alerts["serving_backlog_warn"] = _make_alert("serving_backlog_warn", Severity.WARN, "Serving Backlog Warning", f"{pending} pending meals", existing)

    return alerts
