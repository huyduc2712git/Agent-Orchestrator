import { AGENT_INFO } from "./constants.js";

export const state = {
  tasks: new Map(),
  openTaskId: null,
  activeView: "board",
  thinking: false,
  activeProject: "",
  projects: [],
  chatMessages: [],
  plannerModel: "",
  workStartedAt: null,
};

export const $ = (id) => document.getElementById(id);

export function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

export function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (e) {
    return "";
  }
}

export function taskElapsed(t) {
  if (!t.created_at) return "";
  const start = new Date(t.created_at).getTime();
  const end = t.updated_at ? new Date(t.updated_at).getTime() : Date.now();
  const diffMs = Math.max(0, end - start);
  const min = Math.floor(diffMs / 60000);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin ? `${hr}h ${remMin}m` : `${hr}h`;
}

export function getProjectIcon(p) {
  const provider = p.git_info?.provider || "none";
  if (provider === "github") {
    return `<span class="git-icon github-icon" title="GitHub Repository (${escapeHtml(p.git_info?.remote_url || '')})">🐙</span>`;
  }
  if (provider === "gitlab") {
    return `<span class="git-icon gitlab-icon" title="GitLab Repository (${escapeHtml(p.git_info?.remote_url || '')})">🦊</span>`;
  }
  if (provider === "bitbucket") {
    return `<span class="git-icon bitbucket-icon" title="Bitbucket Repository (${escapeHtml(p.git_info?.remote_url || '')})">🪣</span>`;
  }
  if (provider === "git" || p.git_info?.is_git_repo) {
    return `<span class="git-icon git-icon-generic" title="Git Repository (${escapeHtml(p.git_info?.remote_url || '')})">🌐</span>`;
  }
  return `<span class="project-folder-icon" title="Local Folder">📁</span>`;
}

export function parseMeta(t) {
  if (!t || !t.description) return {};
  if (t.description.startsWith("{")) {
    try { return JSON.parse(t.description); } catch(e) {}
  }
  return {};
}

export function getLatestDoneTaskId(project) {
  const doneTasks = [...state.tasks.values()]
    .filter(x => !x.parent_id && x.status === "done" && (project ? x.project === project : true))
    .sort((a, b) => {
      const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
      const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;
      return timeA === timeB ? String(b.id).localeCompare(String(a.id)) : timeB - timeA;
    });
  return doneTasks[0]?.id;
}

export function pillFor(t, meta) {
  if (meta.pill_text) return { cls: meta.pill_cls || "pill-pending", text: meta.pill_text };
  if (t.status === "backlog") return { cls: "pill-backlog", text: "To Do" };
  if (t.status === "in_progress") return { cls: "pill-working", text: "In Progress" };
  if (t.status === "blocked" && t.type === "bug") return { cls: "pill-failed", text: "CI Failed" };
  if (t.status === "failed") return { cls: "pill-failed", text: "Failed" };
  if (t.status === "blocked") return { cls: "pill-changes", text: "Needs Attention" };
  if (t.status === "testing") return { cls: "pill-testing", text: "QA Testing" };
  if (t.status === "review") return { cls: "pill-review", text: "In Review" };
  if (t.status === "done") return { cls: "pill-ready", text: "Done" };
  return { cls: "pill-pending", text: t.status };
}

export function updateFooterProject() {
  const el = document.getElementById("footer-project");
  if (el) el.textContent = state.activeProject ? `Project: ${state.activeProject}` : "Project: — chưa chọn";

  const chatProj = document.getElementById("chat-project-name");
  if (chatProj) {
    chatProj.textContent = state.activeProject || "— chưa chọn";
  }
}

export function updateChatModelPill() {
  const el = document.getElementById("chat-model-name");
  if (el) {
    el.textContent = state.plannerModel || "deepseek-v4-flash-free";
  }
}

export function resolveAssignee(t, subtasks = []) {
  if (!t) return "conan";

  // Dynamic agent resolution based on task lifecycle status
  if (t.status === "testing") return "heiji";
  if (t.status === "review") return "haibara";
  if (t.status === "done" || t.status === "blocked" || t.status === "failed") {
    return t.review_type === "operator" ? "operator" : "conan";
  }

  if (t.assignee && t.assignee.trim()) return t.assignee.trim();

  const subs = subtasks.length ? subtasks : [...state.tasks.values()].filter((c) => c.parent_id === t.id);
  if (subs.length) {
    const activeSub = subs.find((s) => ["in_progress", "testing", "review", "blocked"].includes(s.status));
    if (activeSub) {
      if (activeSub.status === "testing") return "heiji";
      if (activeSub.status === "review") return "haibara";
      if (activeSub.assignee) return activeSub.assignee;
    }
  }
  return "kid";
}

export function cardTag(t) {
  if (!t) return "";
  const assigneeName = resolveAssignee(t);
  const agent = assigneeName.toLowerCase();
  const info = AGENT_INFO[agent] || { icon: "🤖" };
  let html = `<span class="card-agent-tag" title="${escapeHtml(assigneeName)}">${info.icon} ${escapeHtml(assigneeName)}</span>`;
  if (t.type === "bug") {
    const sev = t.severity ? ` · ${t.severity}` : "";
    html += `<span class="card-tag tag-bug" title="Bug${sev}">🐛 Bug${escapeHtml(sev)}</span>`;
  }
  return html;
}


