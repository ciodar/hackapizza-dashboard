from dataclasses import dataclass
from typing import Any
from app.models.common import Severity

@dataclass(frozen=True)
class EndpointCheck:
    ts_ms: int
    ok: bool
    status_code: int | None
    latency_ms: float
    error: str | None
    payload_summary: dict[str, Any] | None

@dataclass(frozen=True)
class EndpointStatus:
    name: str
    severity: Severity
    last_check: EndpointCheck | None
    stats_1m: dict[str, Any]
    stats_5m: dict[str, Any]
    last_ok_ts_ms: int | None
