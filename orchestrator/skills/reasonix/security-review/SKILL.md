---
name: security-review
description: Security-focused review of branch diff — injection/authz/secrets/path-traversal/crypto. Severity-tagged. Read-only.
source: reasonix
runAs: inline
invocation: auto
allowed-tools: [read_file, list_dir, search_files, run_command, git_status, http_get, run_skill]
agents: [akai, amuro, heiji, conan]
---

You are running a security-review playbook. Inspect pending changes through a security lens.

How to operate:
- Scope: current branch diff vs default branch (or named range).
- `git status` / `git diff --stat` / `git diff`, then `read_file` for auth/validation context.
- `search_files` to verify sanitization / call sites before asserting impact.
- Stay read-only. Cap ~12 tool calls.

Threat model:
- CRITICAL: SQL/NoSQL/shell/template injection; path traversal; missing authn/authz; hardcoded secrets; unsafe deserialization; crypto mistakes.
- HIGH: XSS; SSRF; open redirects; TOCTOU on auth.
- MEDIUM: verbose errors; missing rate limits on credentials; missing cookie flags.

Out of scope: style, naming, non-security nits.

Final answer: one-sentence verdict, then list by severity (file:line + threat + fix direction).
