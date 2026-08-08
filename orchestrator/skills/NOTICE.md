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

## anthropics/skills — frontend-design
Source: https://github.com/anthropics/skills/tree/main/skills/frontend-design
Vendored under `vendor/anthropic/frontend-design/` — see `LICENSE.txt` in that folder.
Adapted frontmatter for Orchestrator tools (`screenshot_url`, `inspect_render`, …).

## vercel-labs/agent-skills — react-best-practices (MIT)
Source: https://github.com/vercel-labs/agent-skills/tree/main/skills/react-best-practices
Vendored under `vendor/vercel/react-best-practices/` (includes `rules/` + `AGENTS.md`).
Catalog name: `react-best-practices` (alias `vercel-react-best-practices`).

## addyosmani/web-quality-skills — accessibility (MIT)
Source: https://github.com/addyosmani/web-quality-skills/tree/main/skills/accessibility
Vendored under `vendor/web-quality/accessibility/` — see `vendor/web-quality/LICENSE`.
Alias: `a11y`.
