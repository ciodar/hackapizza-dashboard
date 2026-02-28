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
    
    # 1. auth error - any endpoint 401
    for name, ep in snap.get("endpoint_statuses", {}).items():
        lc = ep.get("last_check") or {}
        if lc.get("status_code") == 401:
            alerts["auth_error"] = _make_alert("auth_error", Severity.CRIT, "Authentication Error", f"Endpoint {name} returned 401", existing)
            break

    # 2/3/4. SSE disconnected / blocked / heartbeat stale — skipped:
    #         SSE is intentionally disabled; the restaurant agent owns that connection.
    
    # 5. Critical endpoint down
    for ep_name in ("restaurants", "my_restaurant"):
        ep = snap.get("endpoint_statuses", {}).get(ep_name)
        if ep:
            lc = ep.get("last_check") or {}
            lc_ts = lc.get("ts_ms", 0)
            if not lc.get("ok") and (now - lc_ts) > 30_000:
                alerts[f"endpoint_down_{ep_name}"] = _make_alert(f"endpoint_down_{ep_name}", Severity.CRIT, f"Endpoint Down: {ep_name}", f"/{ep_name} has been failing for >30s", existing)
    
    # 6. Rate limit storm - check multiple 429s recently
    rate_limit_count = 0
    for name, ep in snap.get("endpoint_statuses", {}).items():
        stats = ep.get("stats_1m") or {}
        lc = ep.get("last_check") or {}
        if lc.get("status_code") == 429:
            rate_limit_count += 1
    if rate_limit_count >= 2:
        alerts["rate_limit_storm"] = _make_alert("rate_limit_storm", Severity.WARN, "Rate Limit Storm", f"{rate_limit_count} endpoints hitting 429", existing)
    
    # 7. Serving phase but restaurant closed
    phase = snap.get("phase")
    my = snap.get("my_restaurant") or {}
    if phase == "serving" and my.get("is_open") is False:
        alerts["serving_closed"] = _make_alert("serving_closed", Severity.CRIT, "Restaurant Closed During Service", "Restaurant is closed while in serving phase", existing)
    
    # 8. Serving phase but empty menu
    if phase == "serving" and len(snap.get("menu") or []) == 0:
        alerts["serving_no_menu"] = _make_alert("serving_no_menu", Severity.CRIT, "No Menu During Service", "Menu is empty while in serving phase", existing)
    
    # 9. Serving backlog
    meals = snap.get("meals") or []
    pending = sum(1 for m in meals if not m.get("executed"))
    if pending >= 10:
        alerts["serving_backlog_crit"] = _make_alert("serving_backlog_crit", Severity.CRIT, "Serving Backlog Critical", f"{pending} pending meals", existing)
    elif pending >= 5:
        alerts["serving_backlog_warn"] = _make_alert("serving_backlog_warn", Severity.WARN, "Serving Backlog Warning", f"{pending} pending meals", existing)
    
    return alerts
