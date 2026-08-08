---
name: extend-existing-app
description: Project already has app — edit in place; FORBIDDEN to scaffold a new Vite/CRA app.
source: native
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, list_dir, search_files, run_command, http_get, post_message, run_skill]
agents: [kid, agasa]
---

If `package.json` + `src/` or root `index.html` already exist:

- EXTEND / patch existing code only.
- Do NOT run `npm create vite`, CRA, or wipe the project.
- Match existing stack (deps, scripts, folder layout).
- Deliverable states "extended existing app at …".
