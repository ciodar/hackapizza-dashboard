from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class SSEEvent:
    ts_ms: int
    type: str
    data: Any
    raw: str | None = None
