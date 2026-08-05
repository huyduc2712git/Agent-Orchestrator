"""MCP Streamable HTTP client (JSON-RPC) — gọi tools trên mcp_url của project."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

log = logging.getLogger("mcp.client")


class McpError(Exception):
    pass


def _parse_sse_data(text: str) -> dict[str, Any] | None:
    """Lấy JSON cuối từ SSE `data: {...}` nếu server trả text/event-stream."""
    last: dict[str, Any] | None = None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            last = json.loads(payload)
        except json.JSONDecodeError:
            continue
    return last


class McpClient:
    """Client tối giản: initialize → tools/list → tools/call."""

    def __init__(self, url: str, *, token: str = "", timeout: float = 90.0):
        self.url = (url or "").strip().rstrip("/")
        if not self.url:
            raise McpError("mcp_url trống")
        self.token = (token or "").strip()
        self.timeout = timeout
        self.session_id = ""
        self._req_id = 0

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            resp = httpx.post(
                self.url,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            raise McpError(f"MCP HTTP lỗi: {e}") from e

        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid

        if resp.status_code == 401:
            raise McpError(
                "MCP 401 Unauthorized — remote Figma MCP cần OAuth (Cursor/Claude). "
                "Dùng builtin `/mcp/figma` hoặc Desktop MCP (127.0.0.1:3845) khi Figma app bật Dev Mode MCP."
            )
        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            raise McpError(f"MCP HTTP {resp.status_code}: {resp.text[:300]}")

        ctype = (resp.headers.get("content-type") or "").lower()
        text = resp.text or ""
        data: dict[str, Any] | None
        if "text/event-stream" in ctype or text.lstrip().startswith("event:"):
            data = _parse_sse_data(text)
        else:
            try:
                data = resp.json()
            except Exception as e:
                raise McpError(f"MCP response không phải JSON: {e}; body={text[:200]}") from e

        if not isinstance(data, dict):
            return None
        if data.get("error"):
            err = data["error"]
            if isinstance(err, dict):
                raise McpError(f"MCP error: {err.get('message') or err}")
            raise McpError(f"MCP error: {err}")
        return data

    def initialize(self) -> dict[str, Any]:
        data = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-orchestrator", "version": "1.0"},
            },
        })
        # notification — ignore errors
        try:
            self._post({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            })
        except McpError:
            pass
        return (data or {}).get("result") or {}

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        data = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        })
        result = (data or {}).get("result") or {}
        tools = result.get("tools") or []
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        self.initialize()
        data = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        })
        result = (data or {}).get("result") or {}
        # MCP content blocks
        content = result.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif block.get("type") == "image":
                    parts.append(f"[image mime={block.get('mimeType', '')}]")
                else:
                    parts.append(json.dumps(block, ensure_ascii=False)[:2000])
            text = "\n".join(p for p in parts if p).strip()
            if result.get("isError"):
                raise McpError(text or "MCP tool returned isError")
            return text or json.dumps(result, ensure_ascii=False)[:8000]
        if result.get("isError"):
            raise McpError(str(result))
        return json.dumps(result, ensure_ascii=False)[:8000]


def _is_builtin_mcp(url: str) -> bool:
    u = (url or "").rstrip("/").lower()
    return u.endswith("/mcp/figma") or "/mcp/figma" in u


def mcp_list_tools(url: str, token: str = "") -> list[dict[str, Any]]:
    if _is_builtin_mcp(url):
        from .figma_shim import TOOL_DEFS
        return list(TOOL_DEFS)
    return McpClient(url, token=token).list_tools()


def mcp_call(url: str, tool: str, arguments: dict[str, Any] | None = None, token: str = "") -> str:
    if _is_builtin_mcp(url):
        from .figma_shim import handle_tool
        return handle_tool(tool, arguments or {})
    return McpClient(url, token=token).call_tool(tool, arguments)


def looks_like_figma_mcp(url: str) -> bool:
    u = (url or "").lower()
    return "mcp.figma.com" in u or ":3845" in u or u.rstrip("/").endswith("/mcp/figma")
