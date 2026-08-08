---
name: same-origin-api
description: Smoke API direct port AND same-origin /api on Live URL preview host.
source: native
runAs: inline
invocation: auto
allowed-tools: [read_file, list_dir, search_files, run_command, http_get, create_bug_ticket, post_message, run_skill]
agents: [kid, agasa, heiji]
---

When FE calls `/api/...`:

1. Start API if needed (background `run_command`); note start command + base URL.
2. `http_get` health/endpoint on backend port directly.
3. `http_get` same path on Live URL host (`/preview/.../api/...` or proxy path).
4. Direct OK but preview 404/502 → fix proxy/`api_base` or `create_bug_ticket` with fix direction. Do NOT report done.
5. Deliverable must include both status codes.
