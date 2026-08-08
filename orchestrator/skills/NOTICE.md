# Third-party skills & prompt patterns

## DeepSeek-Reasonix (MIT)
Source: https://github.com/esengine/DeepSeek-Reasonix
Adapted:
- Builtin skill playbooks (`explore`, `research`, `review`, `security-review`, `test`, `init`)
- Cache-stable skills-index system-prompt pattern
- Tool surface ideas from `docs/TOOL_CONTRACT.md` / `internal/tool/builtin`:
  `glob`, `grep`, `edit_file`, `multi_edit`, `move_file`, `web_fetch`, `todo_write`,
  plus aliases `bash`→`run_command`, `ls`→`list_dir`; `read_file` offset/limit.
Not ported (out of scope): LSP, fleet/task subagents, bash_output/wait/kill_shell,
install_source, notebook_edit, delete_symbol (Go-only), Seatbelt sandbox.
Not affiliated with Reasonix; Detective personas remain Orchestrator-owned.

## addyosmani/agent-skills (MIT)
Source: https://github.com/addyosmani/agent-skills
Vendored under `vendor/addy/` — see `vendor/addy/LICENSE`.
Skills are loaded on-demand via `run_skill`; bodies are not injected into every request.
