from dataclasses import dataclass
from enum import Enum
from typing import Any

class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    CRIT = "crit"

class GamePhase(str, Enum):
    SPEAKING = "speaking"
    CLOSED_BID = "closed_bid"
    WAITING = "waiting"
    SERVING = "serving"
    STOPPED = "stopped"
    UNKNOWN = "unknown"
