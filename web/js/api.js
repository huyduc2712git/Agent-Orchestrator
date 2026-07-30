/* Agent Orchestrator — API Async Service Layer */

import { state, $, updateFooterProject, updateChatModelPill } from "./state.js";
import { renderBoard } from "./components/board.js";
import { renderSidebar } from "./components/sidebar.js";
import { openModal } from "./components/modal.js";

export const API_BASE = (location.protocol === "file:" || !location.host) ? "http://127.0.0.1:8600" : "";

export async function loadBoard() {
  try {
    const res = await fetch(`${API_BASE}/api/board`);
    const data = await res.json();
    state.tasks.clear();
    data.tasks.forEach((t) => state.tasks.set(t.id, t));
    await loadProjects();
    await loadSettings();
    renderBoard();
  } catch (e) {
    console.error("Failed to load board:", e);
  }
}

export async function loadSettings() {
  try {
    const res = await fetch(`${API_BASE}/api/settings`);
    const data = await res.json();
    if (data.agents && Array.isArray(data.agents)) {
      const conan = data.agents.find((a) => a.key === "conan");
      if (conan && (conan.model || conan.tool_name)) {
        state.plannerModel = conan.model || conan.tool_name;
      }
    }
    if (!state.plannerModel && data.role_models && data.role_models.planner) {
      state.plannerModel = data.role_models.planner;
    }
    updateChatModelPill();
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}

export async function loadProjects() {
  try {
    const res = await fetch(`${API_BASE}/api/projects`);
    const data = await res.json();
    state.projects = data.projects || [];
    if (data.active_project) state.activeProject = data.active_project;
    else if (!state.activeProject && state.projects.length) {
      state.activeProject = state.projects[0].slug;
    }
    updateFooterProject();
    renderSidebar();
  } catch (e) {
    console.error("Failed to load projects:", e);
  }
}

export async function selectProject(slug) {
  state.activeProject = slug;
  try {
    await fetch(`${API_BASE}/api/projects/${encodeURIComponent(slug)}/select`, { method: "POST" });
  } catch (e) {
    console.error("Failed to select project:", e);
  }
  updateFooterProject();
  renderBoard();
}

export async function removeProject(slug, label) {
  const taskCount = [...state.tasks.values()].filter((t) => !t.parent_id && t.project === slug).length;
  const proj = state.projects.find((p) => p.slug === slug);
  const dirHint = proj?.project_dir
    ? `\nThư mục trên đĩa cũng sẽ bị xóa:\n${proj.project_dir}`
    : "\nThư mục project trên đĩa (nếu có) cũng sẽ bị xóa.";
  const msg = taskCount
    ? `Xóa project "${label}"?\n${taskCount} task sẽ bị archive và ẩn khỏi board.${dirHint}`
    : `Xóa project "${label}"?${dirHint}`;
  if (!confirm(msg)) return;
  try {
    const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(slug)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Không xóa được");
      return;
    }
    state.projects = data.projects || state.projects.filter((p) => p.slug !== slug);
    state.activeProject = data.active_project || "";
    for (const [id, t] of [...state.tasks.entries()]) {
      if (t.project === slug) state.tasks.delete(id);
    }
    if (state.openTaskId && !state.tasks.has(state.openTaskId)) {
      $("modal-backdrop")?.classList.add("hidden");
      state.openTaskId = null;
    }
    updateFooterProject();
    if (data.dir_errors?.length) {
      alert("Đã xóa project, nhưng một số thư mục chưa gỡ được:\n" + data.dir_errors.join("\n"));
    }
    renderBoard();
  } catch (e) {
    alert("Lỗi khi xóa project: " + e);
  }
}

export async function blockTask(taskId) {
  try {
    const res = await fetch(`${API_BASE}/api/tasks/${encodeURIComponent(taskId)}/block`, { method: "POST" });
    const data = await res.json();
    if (res.ok && data.accepted) {
      await loadBoard();
      const modal = $("modal-task-detail");
      if (modal && modal.style.display !== "none") {
        openModal(taskId);
      }
    } else {
      console.warn("blockTask failed/not accepted:", data);
    }
  } catch (err) {
    console.error("Failed to block task:", err);
  }
}
window.blockTask = blockTask;
