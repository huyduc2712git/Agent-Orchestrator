---
name: figma-mcp
description: Task has Figma link — use mcp_call get_design_context (or figma_get); do not invent UI.
source: native
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, list_dir, figma_get, mcp_list_tools, mcp_call, http_get, post_message, run_skill]
agents: [kid, heiji]
---

1. If Figma URL present: prefer `mcp_call` tool `get_design_context` with `{"url": "..."}`.
2. Fallback: `figma_get`. Don't spam after you already have design context / VISION block.
3. Build or QA against that context — no guessing colors/layout when context exists.
4. Cite Figma node / key tokens in deliverable or QA report.
