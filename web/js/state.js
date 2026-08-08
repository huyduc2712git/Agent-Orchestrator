import { AGENT_INFO, getAgentIconHtml } from "./constants.js";

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

/** Tách mô tả task một khối thành đoạn dễ đọc trên board modal. */
export function softBreakTaskDescription(raw) {
  let s = String(raw || "").trim();
  if (!s || s.includes("\n")) return s;

  // Section labels thường bị Planner viết liền câu
  const cues = [
    /\bStack\s*:/i,
    /Nguồn\s+ảnh[^:]{0,48}:/i,
    /\bVerify\s*:/i,
    /\bDeliverable\s*:/i,
    /\bRàng\s*buộc\s*:/i,
    /\bMục\s*tiêu\s*:/i,
    /\bAcceptance\s*:/i,
    /\bCập\s*nhật\b/i,
  ];
  for (const re of cues) {
    s = s.replace(new RegExp(`\\s+(${re.source})`, re.flags), "\n\n$1");
  }
  // Live URL: chỉ tách khi đứng sau dấu câu / cộng
  s = s.replace(/([.+])\s+(Live\s+URL\b)/gi, "$1\n$2");
  // Ràng buộc kiểu "— KHÔNG scaffold…"
  s = s.replace(/\s+[—–-]\s*(KHÔNG\b)/gi, "\n— $1");
  // Câu mới sau dấu chấm + chữ hoa (kể cả tiếng Việt)
  s = s.replace(
    /([.!?])\s+(?=[A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ])/g,
    "$1\n",
  );
  return s;
}

/** HTML an toàn cho #modal-desc — giữ xuống dòng, làm nổi label. */
export function formatTaskDescriptionHtml(raw) {
  const empty = "(không có mô tả)";
  if (!raw || !String(raw).trim()) return escapeHtml(empty);

  const text = softBreakTaskDescription(raw);
  const parts = text.split(/\n+/).map((p) => p.trim()).filter(Boolean);
  return parts
    .map((p) => {
      let line = escapeHtml(p);
      line = line.replace(
        /^(Stack|Nguồn ảnh[^:]*|Verify|Live URL|Deliverable|Ràng buộc|Mục tiêu|Acceptance)\s*:/i,
        "<strong class=\"desc-label\">$1:</strong>",
      );
      // Path / URL đọc rõ hơn
      line = line.replace(
        /(https?:\/\/[^\s<]+|[A-Za-z]:\\[^\s<]+)/g,
        "<code class=\"desc-path\">$1</code>",
      );
      return `<p class="desc-line">${line}</p>`;
    })
    .join("");
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
  if (!t || !t.created_at) return "";
  const start = new Date(t.created_at).getTime();
  if (Number.isNaN(start)) return "";
  // Task đang chạy → đếm realtime đến hiện tại (không khóa theo updated_at)
  const active = ["in_progress", "testing", "review"].includes(t.status);
  const end = active
    ? Date.now()
    : (t.updated_at ? new Date(t.updated_at).getTime() : Date.now());
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
  if (t.status === "blocked") return { cls: "pill-changes", text: "Needs input" };
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

  const explicitCritics = ["akai", "amuro", "haibara", "heiji", "conan"];
  const subs = subtasks.length
    ? subtasks
    : [...state.tasks.values()].filter((c) => c.parent_id && String(c.parent_id) === String(t.id));

  if (subs.length) {
    // 1. Ưu tiên subtask/bug đang chạy thực tế (in_progress)
    let activeSub = subs.find((s) => s.status === "in_progress");
    
    // 2. Nếu không có cái nào in_progress, lấy subtask/bug đang ở bước testing/QA
    if (!activeSub) {
      activeSub = subs.find((s) => s.status === "testing");
    }

    // 3. Tiếp theo lấy subtask đang ở review hoặc blocked/failed
    if (!activeSub) {
      activeSub = subs.find((s) => ["review", "blocked", "failed"].includes(s.status));
    }

    if (activeSub) {
      const subAssignee = (activeSub.assignee || "").toLowerCase();
      
      // Nếu subtask gán cho Critic (Akai, Amuro, Haibara, Heiji, Conan) -> Trả về đúng Critic đó
      if (explicitCritics.includes(subAssignee)) {
        return subAssignee;
      }

      // Nếu subtask/bug Builder đang chạy (in_progress) -> Trả về đúng Agent đó (Kid/Agasa/...)
      if (activeSub.status === "in_progress") {
        return activeSub.assignee || "kid";
      }

      // Nếu subtask Builder đang chờ/đang QA (testing) -> Heiji đang test
      if (activeSub.status === "testing") {
        return "heiji";
      }

      // Nếu subtask Builder đang ở bước Review -> Haibara review
      if (activeSub.status === "review") {
        return "haibara";
      }

      if (activeSub.assignee) return activeSub.assignee;
    }
  }

  const tAssignee = (t.assignee || "").toLowerCase();
  if (explicitCritics.includes(tAssignee)) {
    return tAssignee;
  }

  // Dynamic agent resolution dựa theo trạng thái task cha
  if (t.status === "testing") return "heiji";
  if (t.status === "review") return "haibara";
  if (t.status === "done" || t.status === "blocked" || t.status === "failed") {
    return t.review_type === "operator" ? "operator" : "conan";
  }

  if (t.assignee && t.assignee.trim()) return t.assignee.trim();

  return "kid";
}

export function cardTag(t, subtasks = []) {
  if (!t) return "";
  const assigneeName = resolveAssignee(t, subtasks);
  const agent = assigneeName.toLowerCase();
  const iconHtml = getAgentIconHtml(agent);
  let html = `<span class="card-agent-tag" title="${escapeHtml(assigneeName)}">${iconHtml} ${escapeHtml(assigneeName)}</span>`;
  if (t.type === "bug") {
    const sev = t.severity ? ` · ${t.severity}` : "";
    html += `<span class="card-tag tag-bug" title="Bug${sev}">🐛 Bug${escapeHtml(sev)}</span>`;
  }
  return html;
}


