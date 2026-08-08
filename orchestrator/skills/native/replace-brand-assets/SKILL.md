---
name: replace-brand-assets
description: Replace logo/favicon/PWA icons from user-upload file — copy exact bytes, never redraw as SVG.
source: native
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, list_dir, search_files, run_command, http_get, post_message, run_skill]
agents: [kid]
---

When task includes `[Ảnh đã lưu tại: …]` or path under `assets/user-uploads/`:

1. Copy that exact file into `public/` (and favicon / apple-touch / PWA sizes as required). Do NOT invent SVG or redraw.
2. Update `index.html`, `manifest`, and UI references (sidebar logo, etc.).
3. Remove old brand text if asked.
4. Rebuild; verify Live URL + icon URLs are not 404.
5. Deliverable: source path, dest paths, hash/size match note.
