from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class McpToolResult:
    ok: bool
    latency_ms: float
    is_error: bool
    content_text: str | None
    raw: Any
    error: str | None
