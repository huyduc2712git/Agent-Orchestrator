"""Builtin Figma MCP endpoint — Streamable HTTP JSON-RPC tại /mcp/figma."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..mcp import figma_shim

log = logging.getLogger("api.mcp")
router = APIRouter(tags=["mcp"])

PROTOCOL = "2024-11-05"


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle_rpc(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method") or ""
    req_id = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "orchestrator-figma-mcp", "version": "1.0.0"},
            "instructions": (
                "Builtin Figma MCP của AI Orchestrator. Dùng get_design_context / get_metadata / "
                "get_screenshot với url Figma (có node-id). Auth bằng Figma PAT trong Settings — "
                "không cần OAuth remote mcp.figma.com."
            ),
        })

    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None  # 204

    if method == "ping":
        return _ok(req_id, {})

    if method == "tools/list":
        return _ok(req_id, {"tools": figma_shim.TOOL_DEFS})

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not name:
            return _err(req_id, -32602, "missing tool name")
        try:
            text = figma_shim.handle_tool(name, arguments)
            return _ok(req_id, figma_shim.text_result(text))
        except Exception as e:
            log.exception("MCP tool %s failed", name)
            return _ok(req_id, figma_shim.text_result(f"ERROR: {type(e).__name__}: {e}", is_error=True))

    if req_id is None:
        return None
    return _err(req_id, -32601, f"Method not found: {method}")


@router.post("/mcp/figma")
@router.post("/mcp/figma/")
async def figma_mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_err(None, -32700, "Parse error"), status_code=400)

    # batch
    if isinstance(body, list):
        out = []
        for item in body:
            if isinstance(item, dict):
                r = _handle_rpc(item)
                if r is not None:
                    out.append(r)
        return JSONResponse(out)

    if not isinstance(body, dict):
        return JSONResponse(_err(None, -32600, "Invalid Request"), status_code=400)

    result = _handle_rpc(body)
    if result is None:
        return Response(status_code=204)
    return JSONResponse(result)


@router.get("/mcp/figma")
@router.get("/mcp/figma/")
async def figma_mcp_info():
    return {
        "ok": True,
        "name": "orchestrator-figma-mcp",
        "protocol": PROTOCOL,
        "transport": "streamable-http",
        "tools": [t["name"] for t in figma_shim.TOOL_DEFS],
        "hint": "POST JSON-RPC (initialize / tools/list / tools/call). Gắn URL này vào Settings → Project MCP.",
    }
