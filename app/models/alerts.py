from dataclasses import dataclass
from app.models.common import Severity

@dataclass
class AlertInstance:
    alert_id: str
    severity: Severity
    title: str
    message: str
    first_seen_ms: int
    last_seen_ms: int
    acknowledged: bool = False
