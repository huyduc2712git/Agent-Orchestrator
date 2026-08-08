---
name: explore
description: Explore the codebase read-only and return one distilled answer. Best for find-all / how-does-X-work / survey.
source: reasonix
runAs: inline
invocation: auto
allowed-tools: [read_file, list_dir, ls, glob, grep, search_files, http_get, web_fetch, git_status, run_skill]
agents: [kid, agasa, heiji, conan, akai]
---

You are running an exploration playbook. Investigate the codebase, then return one focused, distilled answer.

How to operate:
- Stay read-only. Prefer `glob` / `grep` / `read_file` / `ls` (Reasonix-style) over shell find/grep. `git_status` OK.
- Cast a wide net first (search + list) to map the territory; then read the 3–10 most relevant files in full.
- Don't read every file — breadth first, depth only where the question demands it.
- Stop exploring as soon as you can answer. Over-exploration is pure waste.

Your final answer:
- One paragraph (or a few short bullets). Lead with the conclusion.
- Cite specific file paths + line ranges when they support the answer.
- If the question can't be answered from what you found, say so plainly and suggest where to look next.

When you claim something does NOT exist, say which searches you ran.
Keep the final answer compact: short paragraphs or bullets, no walls of text.
