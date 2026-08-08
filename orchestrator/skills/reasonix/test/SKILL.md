---
name: test
description: Run project tests, diagnose failures, fix, re-run until green (or stop after 2 attempts on same failure).
source: reasonix
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, list_dir, search_files, run_command, http_get, run_skill]
agents: [kid, agasa]
---

This skill is INLINED. Run the project's test suite, diagnose failures, propose and apply fixes, re-run.

How to operate:
1. Detect test command from package.json / go.mod / pyproject / Cargo.toml. If unsure, state assumption — don't guess wildly.
2. `run_command` the suite; capture failures (file + line).
3. Fix distinct failures: production bug → fix code; test bug → fix test and say so; environmental → stop and report.
4. Re-run. Stop when green; or same failure after 2 attempts; or escalate 3+ unrelated failures one at a time.

Don't: install deps without noting it; skip/delete failing tests to force green; silence the runner.

Lead with a one-line status each step.
