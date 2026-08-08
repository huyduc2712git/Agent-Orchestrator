---
name: vite-fe-smoke
description: Vite/React FE — npm install if needed, build, verify Live URL 200, no blank screen.
source: native
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, list_dir, search_files, run_command, http_get, post_message, run_skill]
agents: [kid, agasa]
---

Checklist for web FE (package.json / Vite / React):

1. If `node_modules` missing → `npm install` (or bun/pnpm as lockfile indicates).
2. Build: `npm run build` or `npx vite build`. Fix failures before claiming done.
3. Smoke Live URL from task prompt (`/preview/<project>/`) with `http_get` → expect 200.
4. Blank white screen / missing root mount = NOT done.
5. `post_message` deliverable with build result + Live URL.
