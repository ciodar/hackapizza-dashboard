import time
from typing import Any

from app.clients.hackapizza_http import HackapizzaHttpClient
from app.models.mcp import McpToolResult

class HackapizzaMcpClient:
    def __init__(self, http: HackapizzaHttpClient) -> None:
        self._http = http

    async def call_tool(self, tool_name: str, tool_args: dict[str, Any]) -> McpToolResult:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": tool_args,
            }
        }
        t0 = time.monotonic()
        result = await self._http.post_json("/mcp", body)
        latency_ms = (time.monotonic() - t0) * 1000
        
        if not result.ok:
            return McpToolResult(ok=False, latency_ms=latency_ms, is_error=True, content_text=result.error, raw=None, error=result.error)
        
        payload = result.payload or {}
        mcp_result = payload.get("result", {})
        is_error = mcp_result.get("isError", False)
        content = mcp_result.get("content", [])
        content_text = content[0].get("text") if content else None
        
        return McpToolResult(ok=True, latency_ms=latency_ms, is_error=is_error, content_text=content_text, raw=payload, error=None)
