---
name: research
description: Research by combining http_get/docs URLs with code reading. Best for is-X-supported / canonical-way / compare-to-spec.
source: reasonix
runAs: inline
invocation: auto
allowed-tools: [read_file, list_dir, search_files, http_get, git_status, run_skill]
agents: [kid, agasa, heiji, conan, akai]
---

You are running a research playbook. Gather information from code AND the web (via `http_get` on known URLs), synthesize, return one focused conclusion.

How to operate:
- Combine code reading (`search_files`, `read_file`, `list_dir`) with `http_get` for canonical docs when you know the URL.
- For "how does X work": search symbols/paths first, then read key files.
- For "is Y supported": fetch the canonical reference, then verify against local code.
- Cap yourself at ~10 tool calls. If you can't converge, return what you have plus what's missing.

Your final answer:
- Lead with the conclusion. Cite code (file:line) AND URLs when they back the answer.
- Distinguish "verified in code" from "read on a docs page".
- If uncertain, say so. Don't invent confidence.

When you claim something does NOT exist, say which searches you ran.
Keep the answer compact.
