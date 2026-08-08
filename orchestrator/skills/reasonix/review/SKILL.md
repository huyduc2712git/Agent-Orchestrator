---
name: review
description: Review pending git changes — correctness, security, missing tests, hidden behavior. Read-only verdict + file:line.
source: reasonix
runAs: inline
invocation: auto
allowed-tools: [read_file, list_dir, ls, glob, grep, search_files, run_command, bash, git_status, http_get, web_fetch, run_skill]
agents: [heiji, haibara, akai, conan]
---

You are running a code-review playbook. Inspect changes about to ship (branch diff vs upstream by default) and produce a focused review.

How to operate:
- Discover scope: `run_command` with `git status`, `git diff --stat`, `git log --oneline -20`, then `git diff` (or vs main/master).
- Read touched files when the diff lacks context.
- Use `search_files` before asserting "no callers".
- Stay read-only for source edits. Cap ~12 tool calls; if huge, pick riskiest 2–3 files.

Priority:
1. Correctness bugs
2. Security (injection, secrets, authz)
3. Hidden behavior changes
4. Tests for new behavior
5. Style only if substance is clean

Final answer:
- One-sentence verdict: ship as-is / minor nits / blocking.
- Bullets with file:line + problem + what to change.
- Group Blocking / Should-fix / Nits if more than 4 items.
