/* Agent Orchestrator — Sidebar Component */

import { state, $, escapeHtml, getProjectIcon } from "../state.js";
import { selectProject, removeProject } from "../api.js";
import { openNewProject } from "./modal.js";

export function updateFooterProject() {
  const el = $("footer-project");
  if (el) el.textContent = state.activeProject ? `Project: ${state.activeProject}` : "Project: — chưa chọn";
}

export function switchView(view) {
  state.activeView = view;
  document.body.classList.toggle("view-board-active", view === "board");
  document.body.classList.toggle("view-chat-active", view === "chat");
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });
  $("view-board").classList.toggle("hidden", view !== "board");
  $("view-chat").classList.toggle("hidden", view !== "chat");
  $(`dot-${view}`)?.classList.add("hidden");
  if (view === "chat") {
    const box = $("chat-messages");
    if (box) box.scrollTop = box.scrollHeight;
    $("chat-text")?.focus();
  }
  if (view === "board") renderSidebar();
}

export function notifyTab(view) {
  if (state.activeView !== view) $(`dot-${view}`)?.classList.remove("hidden");
}

export function goChat() {
  if (!state.activeProject) {
    openNewProject("Hãy tạo hoặc chọn project trước khi giao task.");
    return;
  }
  switchView("chat");
  $("chat-text")?.focus();
}

export function renderSidebar() {
  const box = $("sidebar-projects");
  if (!box) return;
  box.innerHTML = "";

  const projectSlugs = new Set(state.projects.map((p) => p.slug));
  for (const t of state.tasks.values()) {
    if (t.project && !projectSlugs.has(t.project)) {
      state.projects.push({ slug: t.project, name: t.project, project_dir: t.project_dir || "" });
      projectSlugs.add(t.project);
    }
  }

  if (!state.projects.length) {
    box.innerHTML = '<div class="sidebar-hint">Chưa có project — bấm + để tạo</div>';
    return;
  }

  for (const p of [...state.projects].sort((a, b) => a.slug.localeCompare(b.slug))) {
    const isExpanded = state.activeProject === p.slug || state.expandedProjects?.has(p.slug);
    const group = document.createElement("div");
    group.className = "project-group" + (state.activeProject === p.slug ? " active" : "");

    const head = document.createElement("div");
    head.className = "project-name" + (state.activeProject === p.slug ? " selected" : "");
    head.title = p.name || p.slug;
    head.innerHTML = `
      <span class="chevron">▼</span>
      ${getProjectIcon(p)}
      <span class="project-label">${escapeHtml(p.name || p.slug)}</span>
      <button class="project-remove" title="Xóa project" type="button">×</button>`;
    head.onclick = (e) => {
      if (e.target.closest(".project-remove")) return;
      e.stopPropagation();
      selectProject(p.slug);
    };
    head.querySelector(".project-remove").onclick = (e) => {
      e.stopPropagation();
      removeProject(p.slug, p.name || p.slug);
    };
    group.appendChild(head);

        const isCompact = document.body.classList.contains("sidebar-collapsed");
    const list = document.createElement("div");
    list.className = "project-tasks";
    if (!isExpanded || isCompact) {
      list.style.display = "none";
    } else {
      const parents = [...state.tasks.values()]
        .filter((t) => !t.parent_id && t.project === p.slug)
        .sort((a, b) => {
          const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
          const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;
          return timeA === timeB ? String(b.id).localeCompare(String(a.id)) : timeB - timeA;
        });
      if (!parents.length) {
        list.innerHTML = '<div class="sidebar-hint" style="padding-left:20px">Chưa có task</div>';
      } else {
        for (const t of parents) {
          const item = document.createElement("div");
          item.className = "sidebar-task" + (state.openTaskId === t.id ? " active" : "");
          
          let dotColor = "#9ba1aa";
          if (t.status === "in_progress") dotColor = "#b1763d";
          else if (t.status === "blocked" && t.type === "bug") dotColor = "#ef4444";
          else if (t.status === "failed") dotColor = "#ef4444";
          else if (t.status === "blocked") dotColor = "#e8c14a";
          else if (t.status === "review" || t.status === "testing") dotColor = "#9ba1aa";
          else if (t.status === "done") dotColor = "#74b98a";

          item.innerHTML = `<span class="dot" style="background:${dotColor}"></span><span class="label">${escapeHtml(t.title)}</span>`;
          item.onclick = (e) => { e.stopPropagation(); selectProject(p.slug); switchView("board"); };
          list.appendChild(item);
        }
      }
    }
    group.appendChild(list);
    box.appendChild(group);
  }
}
