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

1. Start API if needed (background `run_command`); note start command + base URL; `save_start_command`.
2. `http_get` health/endpoint on backend port directly.
3. **BE-first / chưa có FE:** bước 2 đủ. Live host `/api` 502 vì chưa `api_base` → NOTE trong deliverable, **không** `create_bug_ticket`. Same-origin để Kid/Heiji sau khi FE gọi `/api`.
4. **Khi đã có FE** gọi `/api/...`: `http_get` same path trên Live host. Direct OK nhưng preview 404/502 → set `api_base` hoặc `create_bug_ticket` hướng fix. Do NOT report done.
5. Deliverable: direct status luôn; same-origin status khi FE đã có.
