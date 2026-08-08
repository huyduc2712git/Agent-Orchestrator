---
name: init
description: Bootstrap or refresh ORCH.md / AGENTS.md — concise project memory for future sessions.
source: reasonix
runAs: inline
invocation: manual
allowed-tools: [read_file, write_file, list_dir, search_files, run_command, run_skill]
agents: [conan, kid, agasa]
---

Bootstrap (or refresh) durable project memory. Prefer `ORCH.md` at project root; if `AGENTS.md` / `REASONIX.md` / `CLAUDE.md` already exists, improve that file in place.

How to operate:
1. List project root; read existing memory doc if any.
2. Explore enough: manifest, README, build/test scripts, entry points,  a few representative files for conventions.
3. Write a tight doc:
   - Title + one-line description
   - ## Project — stack, entry point
   - ## Commands — exact build/test/run/lint
   - ## Architecture — 3–7 load-bearing modules
   - ## Conventions — only rules agents must follow
   - ## Notes — empty stub
4. Keep it short — it may load into prompts. No secrets. Verify commands against real files.

Summarize what you captured for the user to review.
