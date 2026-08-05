"""Builtin Figma MCP shim — tool handlers dùng REST token + images/vision (không cần OAuth Figma remote)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .. import config, settings
from ..agents.tools import (
    _figma_cache_load,
    _figma_cache_save,
    _figma_export_png,
    _figma_vision_fallback,
    _figma_walk,
)
import httpx

log = logging.getLogger("mcp.figma_shim")

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "get_metadata",
        "description": (
            "Sparse metadata / node tree từ Figma (layout, size, màu hex, text). "
            "Truyền link Figma có node-id hoặc fileKey+nodeId."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Link Figma design"},
                "fileKey": {"type": "string"},
                "nodeId": {"type": "string"},
            },
        },
    },
    {
        "name": "get_screenshot",
        "description": "Export PNG frame Figma (API /v1/images) — dùng khi cần nhìn UI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "fileKey": {"type": "string"},
                "nodeId": {"type": "string"},
            },
        },
    },
    {
        "name": "get_design_context",
        "description": (
            "Design context để code UI: node tree + (khi cần) Vision mô tả. "
            "Ưu tiên tool này khi project có MCP builtin."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "fileKey": {"type": "string"},
                "nodeId": {"type": "string"},
                "clientLanguages": {"type": "string"},
                "clientFrameworks": {"type": "string"},
            },
        },
    },
    {
        "name": "whoami",
        "description": "Xác nhận Figma token Orchestrator (PAT) còn hiệu lực.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _parse_figma_ref(url: str = "", file_key: str = "", node_id: str = "") -> tuple[str, str]:
    url = unquote((url or "").strip().rstrip(",\"' \n\t"))
    file_key = (file_key or "").strip()
    node_id = (node_id or "").strip().replace("-", ":")
    if url:
        m = re.search(r"figma\.com/(?:file|design|proto|board)/([A-Za-z0-9]+)", url, re.I)
        if m:
            file_key = file_key or m.group(1)
        q = parse_qs(urlparse(url).query)
        if not node_id and "node-id" in q:
            node_id = q["node-id"][0].replace("-", ":")
    return file_key, node_id


def _nodes_tree(file_key: str, node_id: str) -> str:
    tokens = settings.figma_tokens()
    if not tokens:
        return "ERROR: chưa có Figma token trong Settings."

    cached = _figma_cache_load(file_key, node_id)
    if cached and "VISION fallback" not in cached[:80]:
        return cached

    if node_id:
        api = f"https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}&depth=6"
    else:
        api = f"https://api.figma.com/v1/files/{file_key}?depth=25"

    last_err = ""
    for tok in tokens:
        try:
            resp = httpx.get(api, headers={"X-Figma-Token": tok["token"]}, timeout=30)
        except httpx.HTTPError as e:
            last_err = str(e)
            continue
        if resp.status_code == 429:
            # Fallback vision path
            if node_id:
                text = _figma_vision_fallback(file_key, node_id, tokens)
                if text:
                    return text
            return f"ERROR: Figma nodes 429 — cần nodeId để Vision fallback. ({tok['name']})"
        if resp.status_code != 200:
            last_err = f"HTTP {resp.status_code}"
            continue
        data = resp.json()
        if node_id:
            nodes = data.get("nodes") or {}
            entry = next(iter(nodes.values()), None)
            doc = (entry or {}).get("document")
            if not doc:
                return f"ERROR: node {node_id} không tồn tại."
        else:
            doc = data.get("document")
            if not doc:
                return "ERROR: không có document."
        name = data.get("name", "")
        lines: list[str] = []
        _figma_walk(doc, 0, lines)
        text = f"Figma file: {name} (key={file_key})" + (f" — node {node_id}" if node_id else "") + "\n" + "\n".join(lines)
        _figma_cache_save(file_key, node_id, text)
        return text
    return f"ERROR: không đọc được nodes ({last_err})"


def handle_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    if name == "whoami":
        tokens = settings.figma_tokens()
        if not tokens:
            return "ERROR: chưa có Figma PAT trong Settings."
        tok = tokens[0]
        try:
            r = httpx.get(
                "https://api.figma.com/v1/me",
                headers={"X-Figma-Token": tok["token"]},
                timeout=20,
            )
        except httpx.HTTPError as e:
            return f"ERROR: {e}"
        if r.status_code != 200:
            return f"ERROR: /me HTTP {r.status_code} — {r.text[:200]}"
        data = r.json()
        return json.dumps(
            {"ok": True, "token_name": tok.get("name"), "id": data.get("id"), "email": data.get("email"), "handle": data.get("handle")},
            ensure_ascii=False,
        )

    url = str(args.get("url") or args.get("link") or "")
    file_key, node_id = _parse_figma_ref(
        url,
        str(args.get("fileKey") or args.get("file_key") or ""),
        str(args.get("nodeId") or args.get("node_id") or ""),
    )
    if not file_key:
        return "ERROR: cần url Figma hoặc fileKey."

    if name == "get_metadata":
        return _nodes_tree(file_key, node_id)

    if name == "get_screenshot":
        if not node_id:
            return "ERROR: get_screenshot cần nodeId (hoặc url có node-id)."
        tokens = settings.figma_tokens()
        png = _figma_export_png(file_key, node_id, tokens)
        if not png:
            return "ERROR: không export được PNG (token/429/node)."
        # copy vào uploads để view
        dest = config.UPLOADS_DIR / f"mcp-figma-{file_key[:8]}-{node_id.replace(':', '-')}.png"
        try:
            dest.write_bytes(png.read_bytes())
        except OSError:
            dest = png
        view = f"{config.BASE_URL}/uploads/{dest.name}" if dest.parent == config.UPLOADS_DIR else str(dest)
        return f"OK: screenshot\npath: {dest}\nview_url: {view}\nnode: {node_id}"

    if name == "get_design_context":
        meta = _nodes_tree(file_key, node_id)
        # Nếu đã là vision fallback hoặc nodes OK — bổ sung screenshot hint
        extra = ""
        if node_id and "ERROR:" not in meta[:30]:
            tokens = settings.figma_tokens()
            # Nếu meta thiếu màu/vision và từng 429, vision đã nằm trong meta
            if "VISION fallback" not in meta and len(meta) < 200:
                vision = _figma_vision_fallback(file_key, node_id, tokens)
                if vision:
                    extra = "\n\n--- Vision ---\n" + vision
            fw = str(args.get("clientFrameworks") or "react")
            lang = str(args.get("clientLanguages") or "typescript")
            header = (
                f"# Design context (builtin Figma MCP)\n"
                f"Target: {fw} / {lang}\n"
                f"fileKey={file_key} nodeId={node_id or '(root)'}\n\n"
            )
            return header + meta + extra
        return meta + extra

    return f"ERROR: tool không hỗ trợ trên builtin shim: {name}"


def text_result(text: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": bool(is_error or text.startswith("ERROR:")),
    }
