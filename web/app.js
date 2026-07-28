/* Agent Orchestrator — Board (ảnh mẫu) + Chat (Ollie) */

const COLUMNS = [
  { key: "working", label: "Working", headClass: "working", statuses: ["in_progress"] },
  { key: "needs-you", label: "Needs You", headClass: "needs-you", statuses: ["blocked", "backlog"] },
  { key: "review", label: "In Review", headClass: "review", statuses: ["testing", "review"] },
  { key: "ready", label: "Ready to Merge", headClass: "ready", statuses: ["done"] },
];

const AGENT_STYLE = {
  jarvis: { bg: "#1e3a5f", fg: "#60a5fa" },
  stark: { bg: "#431407", fg: "#fb923c" },
  banner: { bg: "#2e1065", fg: "#a78bfa" },
  hawkeye: { bg: "#052e16", fg: "#4ade80" },
  pepper: { bg: "#500724", fg: "#f472b6" },
  system: { bg: "#422006", fg: "#fbbf24" },
  operator: { bg: "#27272a", fg: "#a1a1aa" },
};

const state = {
  tasks: new Map(),
  openTaskId: null,
  activeView: "board",
  thinking: false,
  activeProject: "",
  projects: [],
};
const $ = (id) => document.getElementById(id);

/* ---------- Navigation ---------- */

function switchView(view) {
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
    $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
    $("chat-text")?.focus();
  }
  if (view === "board") renderSidebar();
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

function notifyTab(view) {
  if (state.activeView !== view) $(`dot-${view}`)?.classList.remove("hidden");
}

function goChat() {
  if (!state.activeProject) {
    openNewProject("Hãy tạo hoặc chọn project trước khi giao task.");
    return;
  }
  switchView("chat");
  $("chat-text")?.focus();
}
$("btn-new-task-2")?.addEventListener("click", goChat);
$("btn-orchestrator")?.addEventListener("click", goChat);

/* ---------- Chat ---------- */

function setThinking(on) {
  state.thinking = on;
  const el = $("footer-status");
  if (!el) return;
  el.classList.toggle("thinking", on);
  el.innerHTML = on
    ? '<span class="status-pulse"></span> thinking…'
    : '<span class="status-pulse"></span> sẵn sàng';
}

function renderChatMessage(m) {
  const box = $("chat-messages");
  if (m.role === "system") {
    const row = document.createElement("div");
    row.className = "msg-row system";
    row.innerHTML = `<div class="msg-bubble">${escapeHtml(m.message)}</div>`;
    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
    return;
  }
  const isUser = m.role === "user";
  const row = document.createElement("div");
  row.className = `msg-row ${isUser ? "user" : "jarvis"}`;
  row.innerHTML = `
    <span class="avatar ${isUser ? "avatar-user" : "avatar-jarvis"}">${isUser ? "B" : "J"}</span>
    <div>
      <div class="msg-bubble">${escapeHtml(m.message)}</div>
      <div class="msg-time">${formatTime(m.created_at)}</div>
    </div>`;
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
  if (!isUser) setThinking(false);
}

function formatTime(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }); }
  catch { return ""; }
}

function formatDuration(ms) {
  if (!ms || ms < 0) return "0m";
  const sec = Math.floor(ms / 1000);
  const min = Math.floor(sec / 60);
  const hr = Math.floor(min / 60);
  const day = Math.floor(hr / 24);
  if (day > 0) return `${day}d ${hr % 24}h`;
  if (hr > 0) return `${hr}h ${min % 60}m`;
  if (min > 0) return `${min}m`;
  return `${sec}s`;
}

function taskElapsed(t) {
  if (!t?.created_at) return "";
  const start = new Date(t.created_at).getTime();
  const end = ["done", "archived"].includes(t.status) && t.updated_at
    ? new Date(t.updated_at).getTime()
    : Date.now();
  return formatDuration(end - start);
}

async function loadChat() {
  const res = await fetch("/api/chat");
  const data = await res.json();
  $("chat-messages").innerHTML = "";
  if (!data.messages.length) {
    const w = document.createElement("div");
    w.className = "msg-row jarvis";
    w.innerHTML = `<span class="avatar avatar-jarvis">J</span><div><div class="msg-bubble">Ask me something!</div></div>`;
    $("chat-messages").appendChild(w);
  } else {
    data.messages.forEach(renderChatMessage);
  }
}

$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ta = $("chat-text");
  const text = ta.value.trim();
  if (!text) return;
  if (!state.activeProject) {
    openNewProject("Chọn hoặc tạo project trước khi gửi task.");
    return;
  }
  ta.value = "";
  resetChatInputHeight();
  $("chat-send").disabled = true;
  setThinking(true);
  try {
    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, project: state.activeProject || "" }),
    });
  } finally {
    $("chat-send").disabled = false;
    ta.focus();
  }
});

$("chat-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("chat-form").requestSubmit(); }
});

function resizeChatInput() {
  const ta = $("chat-text");
  if (!ta) return;
  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
}

function resetChatInputHeight() {
  const ta = $("chat-text");
  if (!ta) return;
  ta.style.height = "auto";
}

$("chat-text").addEventListener("input", resizeChatInput);

document.querySelectorAll(".suggestion-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("chat-text").value = chip.dataset.prompt;
    resizeChatInput();
    $("chat-text").focus();
  });
});

/* ---------- Board cards (bám ảnh mẫu) ---------- */

function pillFor(t) {
  if (t.status === "in_progress") return { cls: "pill-working", text: "Working" };
  if (t.status === "blocked" && t.type === "bug") return { cls: "pill-failed", text: "CI failed" };
  if (t.status === "blocked") return { cls: "pill-changes", text: "Changes requested" };
  if (t.status === "backlog") return { cls: "pill-queued", text: "Queued" };
  if (t.status === "review") return { cls: "pill-pending", text: "Review pending" };
  if (t.status === "testing") return { cls: "pill-pending", text: "QA in progress" };
  if (t.status === "done") return { cls: "pill-ready", text: "Ready" };
  return { cls: "pill-pending", text: t.status };
}

function agentBadge(name) {
  const n = (name || "jarvis").toLowerCase();
  const s = AGENT_STYLE[n] || AGENT_STYLE.jarvis;
  return `<span class="agent-badge"><span class="av" style="background:${s.bg};color:${s.fg}">${n[0]}</span>${escapeHtml(n)}</span>`;
}

const KIND_ICON = {
  comment: "💬",
  status: "↻",
  system: "⚙",
};

const AGENT_LABEL = {
  jarvis: "Jarvis",
  pepper: "Pepper",
  stark: "Stark",
  banner: "Banner",
  hawkeye: "Hawkeye",
  system: "System",
  operator: "Operator",
};

function agentEventIcon(agent, kind) {
  const n = (agent || "system").toLowerCase();
  const s = AGENT_STYLE[n] || AGENT_STYLE.jarvis;
  const label = AGENT_LABEL[n] || agent || "System";
  const kindIcon = KIND_ICON[kind] || "•";
  const letter = n === "system" ? "⚙" : (label[0] || "?").toUpperCase();
  return `
    <div class="event-icon-wrap" title="${escapeHtml(label)}">
      <span class="event-icon agent-${escapeHtml(n)}" style="background:${s.bg};color:${s.fg}">${letter}</span>
      <span class="event-kind-icon kind-${escapeHtml(kind)}">${kindIcon}</span>
    </div>`;
}

function metaRows(t) {
  const pr = t.status === "in_progress" || t.status === "backlog"
    ? "no PR yet"
    : `${t.id} · ${t.status === "done" ? "merged" : "open"}`;

  let ci = "—", ciCls = "";
  if (t.status === "done") { ci = "Passing"; ciCls = "pass"; }
  else if (t.status === "blocked") { ci = "Failing"; ciCls = "fail"; }
  else if (t.status === "testing" || t.status === "review") { ci = "Pending"; ciCls = "warn"; }

  let review = "None";
  if (t.status === "review") review = "Pending";
  else if (t.status === "done") review = "Approved";
  else if (t.status === "blocked") review = "Changes requested";

  let merge = "—";
  if (t.status === "done") merge = "Mergeable";
  else if (t.status === "review" && t.review_type === "operator") merge = "Checking";

  return `
    <div class="meta-row"><span class="mk">PR</span><span class="mv">${pr}</span></div>
    <div class="meta-row"><span class="mk">CI</span><span class="mv ${ciCls}">${ci}</span></div>
    <div class="meta-row"><span class="mk">Review</span><span class="mv ${review === "Approved" ? "pass" : review === "Changes requested" ? "warn" : ""}">${review}</span></div>
    <div class="meta-row"><span class="mk">Merge</span><span class="mv ${merge === "Mergeable" ? "pass" : ""}">${merge}</span></div>`;
}

function attentionFor(t) {
  if (t.status !== "blocked" && t.status !== "backlog") return "";
  const action = t.status === "blocked"
    ? (t.type === "bug" ? "Fix failing CI" : "Address requested changes")
  : "Waiting to start";
  return `<div class="task-card-attention">
    <div class="attention-label">NEEDS ATTENTION</div>
    <div class="attention-text">${action}</div>
  </div>`;
}

function renderCard(t) {
  const card = document.createElement("div");
  card.className = "task-card";
  card.onclick = () => openModal(t.id);
  const pill = pillFor(t);
  const path = t.project_dir
    ? t.project_dir.replace(/^.*[\\/]projects[\\/]/, "demo/")
    : `demo/${t.project}`;
  card.innerHTML = `
    <span class="task-card-time" title="Thời gian tổng">${taskElapsed(t)}</span>
    <div class="task-card-head">
      <span class="pill ${pill.cls}"><span class="pill-dot"></span>${pill.text}</span>
      ${agentBadge(t.assignee)}
    </div>
    <div class="task-card-title">${escapeHtml(t.title)}</div>
    <div class="task-card-path">${escapeHtml(path)}</div>
    <div class="task-card-meta">${metaRows(t)}</div>
    ${attentionFor(t)}`;
  return card;
}

function renderBoard() {
  const board = $("board");
  board.innerHTML = "";
  let parents = [...state.tasks.values()].filter((t) => !t.parent_id);
  if (state.activeProject) {
    parents = parents.filter((t) => t.project === state.activeProject);
  }

  for (const col of COLUMNS) {
    const colEl = document.createElement("div");
    colEl.className = "kanban-col";
    const tasks = parents.filter((t) => col.statuses.includes(t.status));
    colEl.innerHTML = `
      <div class="col-head ${col.headClass}">
        <span class="indicator"></span>
        ${col.label}
        <span class="count">${tasks.length}</span>
      </div>`;
    const body = document.createElement("div");
    body.className = "col-body";
    if (!state.activeProject) {
      body.innerHTML = '<div class="col-empty">Chọn project ở sidebar</div>';
    } else if (!tasks.length) {
      body.innerHTML = '<div class="col-empty">—</div>';
    } else {
      tasks.forEach((t) => body.appendChild(renderCard(t)));
    }
    colEl.appendChild(body);
    board.appendChild(colEl);
  }
  updateFooterProject();
  renderSidebar();
  const sub = $("board-subtitle");
  if (sub) {
    sub.textContent = state.activeProject
      ? `Project: ${state.activeProject} — task mới từ Chat sẽ gắn vào đây`
      : "Chọn hoặc tạo project ở sidebar trước";
  }
}

function updateFooterProject() {
  const el = $("footer-project");
  if (el) el.textContent = state.activeProject ? `Project: ${state.activeProject}` : "Project: — chưa chọn";
}

function renderSidebar() {
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
    const group = document.createElement("div");
    group.className = "project-group" + (state.activeProject === p.slug ? " active" : "");

    const head = document.createElement("div");
    head.className = "project-name" + (state.activeProject === p.slug ? " selected" : "");
    head.innerHTML = `
      <span class="chevron">${state.activeProject === p.slug ? "▼" : "▸"}</span>
      <span class="project-label">${escapeHtml(p.name || p.slug)}</span>
      <button class="project-remove" title="Xóa project" type="button">×</button>`;
    head.querySelector(".project-label").onclick = (e) => { e.stopPropagation(); selectProject(p.slug); };
    head.querySelector(".chevron").onclick = (e) => { e.stopPropagation(); selectProject(p.slug); };
    head.querySelector(".project-remove").onclick = (e) => {
      e.stopPropagation();
      removeProject(p.slug, p.name || p.slug);
    };
    group.appendChild(head);

    if (state.activeProject === p.slug) {
      const list = document.createElement("div");
      list.className = "project-tasks";
      const parents = [...state.tasks.values()].filter((t) => !t.parent_id && t.project === p.slug);
      if (!parents.length) {
        list.innerHTML = '<div class="sidebar-hint" style="padding-left:20px">Chưa có task</div>';
      }
      for (const t of parents) {
        const item = document.createElement("div");
        item.className = "sidebar-task" + (state.openTaskId === t.id ? " active" : "");
        const colors = { in_progress: "#f97316", blocked: "#ef4444", backlog: "#71717a",
          testing: "#eab308", review: "#a1a1aa", done: "#22c55e" };
        item.innerHTML = `<span class="dot" style="background:${colors[t.status] || "#71717a"}"></span><span class="label">${escapeHtml(t.title)}</span>`;
        item.onclick = (e) => { e.stopPropagation(); switchView("board"); openModal(t.id); };
        list.appendChild(item);
      }
      group.appendChild(list);
    }
    box.appendChild(group);
  }
}

async function loadProjects() {
  try {
    const res = await fetch("/api/projects");
    const data = await res.json();
    state.projects = data.projects || [];
    if (data.active_project) state.activeProject = data.active_project;
    else if (!state.activeProject && state.projects.length) {
      state.activeProject = state.projects[0].slug;
    }
  } catch { /* ignore */ }
}

async function selectProject(slug) {
  state.activeProject = slug;
  try {
    await fetch(`/api/projects/${encodeURIComponent(slug)}/select`, { method: "POST" });
  } catch { /* ignore */ }
  updateFooterProject();
  renderBoard();
}

async function removeProject(slug, label) {
  const taskCount = [...state.tasks.values()].filter((t) => !t.parent_id && t.project === slug).length;
  const msg = taskCount
    ? `Xóa project "${label}"?\n${taskCount} task sẽ bị archive và ẩn khỏi board.`
    : `Xóa project "${label}"?`;
  if (!confirm(msg)) return;
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(slug)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Không xóa được");
      return;
    }
    state.projects = data.projects || state.projects.filter((p) => p.slug !== slug);
    state.activeProject = data.active_project || "";
    // Gỡ task đã archive khỏi state UI
    for (const [id, t] of [...state.tasks.entries()]) {
      if (t.project === slug) state.tasks.delete(id);
    }
    if (state.openTaskId && !state.tasks.has(state.openTaskId)) {
      $("modal-backdrop")?.classList.add("hidden");
      state.openTaskId = null;
    }
    updateFooterProject();
    renderBoard();
  } catch (e) {
    alert("Lỗi khi xóa project: " + e);
  }
}

function openNewProject(hint) {
  $("project-backdrop").classList.remove("hidden");
  const msg = $("project-msg");
  if (msg) {
    msg.textContent = hint || "";
    msg.className = "settings-msg " + (hint ? "ok" : "");
  }
  $("project-name")?.focus();
}

$("btn-new-project")?.addEventListener("click", () => openNewProject());
$("project-close")?.addEventListener("click", () => $("project-backdrop").classList.add("hidden"));
$("project-backdrop")?.addEventListener("click", (e) => {
  if (e.target === $("project-backdrop")) $("project-backdrop").classList.add("hidden");
});
$("project-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("project-name").value.trim();
  if (!name) return;
  $("project-add").disabled = true;
  try {
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (res.ok) {
      state.projects = state.projects.filter((p) => p.slug !== data.project.slug);
      state.projects.push(data.project);
      state.activeProject = data.project.slug;
      $("project-name").value = "";
      $("project-backdrop").classList.add("hidden");
      updateFooterProject();
      renderBoard();
    } else {
      $("project-msg").textContent = data.error || "Lỗi";
      $("project-msg").className = "settings-msg err";
    }
  } finally {
    $("project-add").disabled = false;
  }
});

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

async function loadBoard() {
  const res = await fetch("/api/board");
  const data = await res.json();
  state.tasks.clear();
  data.tasks.forEach((t) => state.tasks.set(t.id, t));
  await loadProjects();
  renderBoard();
}

/* ---------- Modal ---------- */

const STATUS_LABEL = {
  backlog: "Backlog", in_progress: "Working", blocked: "Blocked",
  testing: "Testing", review: "Review", done: "Done",
};

async function openModal(taskId) {
  state.openTaskId = taskId;
  const res = await fetch(`/api/tasks/${taskId}`);
  const data = await res.json();
  const t = data.task;

  $("modal-task-id").textContent = t.id;
  $("modal-status").textContent = STATUS_LABEL[t.status] || t.status;
  const typeBadge = $("modal-type");
  typeBadge.classList.toggle("hidden", t.type !== "bug");
  if (t.type === "bug") typeBadge.textContent = `bug · ${t.severity || "?"}`;

  $("modal-title").textContent = t.title;
  const elapsed = taskElapsed(t);
  const preview = t.project ? `${location.origin}/preview/${t.project}/` : "";
  $("modal-meta").innerHTML = [
    elapsed ? `Thời gian: <b>${elapsed}</b>` : null,
    `Assignee: <b>${t.assignee || "—"}</b>`,
    `Project: <b>${t.project}</b>`,
    t.parent_id ? `Parent: <b>${t.parent_id}</b>` : null,
    preview ? `Live: <a href="${preview}" target="_blank">${preview}</a>` : null,
    data.deps.length ? `Deps: <b>${data.deps.map((d) => d.depends_on).join(", ")}</b>` : null,
  ].filter(Boolean).join(" · ");

  const actions = $("modal-actions");
  actions.innerHTML = "";
  if (t.status === "review") {
    const btn = document.createElement("button");
    btn.className = "btn-approve";
    btn.textContent = "✓ Approve (operator)";
    btn.onclick = async () => { await fetch(`/api/tasks/${t.id}/approve`, { method: "POST" }); openModal(t.id); };
    actions.appendChild(btn);
  }
  if (t.status === "blocked") {
    const btn = document.createElement("button");
    btn.textContent = "↺ Chạy lại";
    btn.onclick = async () => { await fetch(`/api/tasks/${t.id}/rerun`, { method: "POST" }); openModal(t.id); };
    actions.appendChild(btn);
  }

  $("modal-desc").textContent = t.description || "(không có mô tả)";
  $("modal-events").innerHTML = "";
  data.events.forEach((e) => $("modal-events").appendChild(renderEvent(e)));
  $("modal-backdrop").classList.remove("hidden");
  renderSidebar();
}

function formatEventMessage(msg) {
  let s = escapeHtml(msg || "");
  // Artifact screenshot URLs -> inline images
  s = s.replace(/(view_url|diff_view_url):\s*(https?:\/\/[^\s<]+)/gi, (_, _k, url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank">${url}</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);
  s = s.replace(/(https?:\/\/[^\s<]+\/artifacts\/[^\s<]+\.png)/gi, (url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank">${url}</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);
  // Basic markdown headers
  s = s.replace(/^## (.+)$/gm, "<h4>$1</h4>");
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Markdown table rows (simple)
  s = s.replace(/^\| (.+) \|$/gm, (row) => {
    if (row.includes("---")) return "";
    const cells = row.split("|").filter(Boolean).map((c) => c.trim());
    return `<div class="qa-table-row">${cells.map((c) => `<span>${c}</span>`).join("")}</div>`;
  });
  return s.replace(/\n/g, "<br>");
}

function renderEvent(e) {
  const agent = (e.agent || "system").toLowerCase();
  const label = AGENT_LABEL[agent] || e.agent || "System";
  const div = document.createElement("div");
  div.className = `event kind-${e.kind} agent-event-${agent}`;
  div.innerHTML = `
    <div class="event-row">
      ${agentEventIcon(e.agent, e.kind)}
      <div class="event-main">
        <div class="event-head">
          <span class="event-agent-name">${escapeHtml(label)}</span>
          <span class="event-kind-label">${escapeHtml(e.kind)}</span>
          <span class="event-time">${new Date(e.created_at).toLocaleTimeString("vi-VN")}</span>
        </div>
        <div class="event-body">${formatEventMessage(e.message)}</div>
      </div>
    </div>`;
  return div;
}

$("modal-close").onclick = () => { $("modal-backdrop").classList.add("hidden"); state.openTaskId = null; renderSidebar(); };
$("modal-backdrop").addEventListener("click", (e) => { if (e.target === $("modal-backdrop")) $("modal-close").onclick(); });

/* ---------- Settings ---------- */

function openSettings() { $("settings-backdrop").classList.remove("hidden"); settingsMsg("", true); loadSettings(); }
async function loadSettings() {
  const res = await fetch("/api/settings");
  const data = await res.json();
  const tools = data.llm_tools || [];
  const roles = data.role_models || {};
  const roleLabels = data.role_labels || {};

  // LLM tools list — chỉ hiện model name + toggle
  const toolList = $("llm-tool-list");
  toolList.innerHTML = tools.length
    ? tools.map((t) => `
      <div class="llm-tool-row ${t.enabled ? "" : "off"}">
        <code class="llm-model-name">${escapeHtml(t.model)}</code>
        <label class="toggle" title="${t.enabled ? "Tắt" : "Bật"}">
          <input type="checkbox" data-id="${escapeHtml(t.id)}" ${t.enabled ? "checked" : ""} />
          <span class="toggle-track"></span>
        </label>
      </div>`).join("")
    : '<div class="settings-hint">(chưa có LLM tool — thêm bên dưới hoặc dùng từ .env)</div>';
  toolList.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    cb.onchange = async () => {
      const res = await fetch(`/api/settings/llm-tools/${encodeURIComponent(cb.dataset.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: cb.checked }),
      });
      const d = await res.json();
      if (!res.ok) {
        cb.checked = !cb.checked;
        settingsMsg(d.error || "Lỗi", false);
        return;
      }
      settingsMsg(cb.checked ? `Đã bật ${d.tool.model}` : `Đã tắt ${d.tool.model}`, true);
      loadSettings();
    };
  });

  const enabledTools = tools.filter((t) => t.enabled);
  const toolOptions = enabledTools.map((t) =>
    `<option value="${escapeHtml(t.id)}">${escapeHtml(t.model)}</option>`
  ).join("");

  // Role pickers (planner/coder/critic/summary) + agent mapping
  const roleOrder = ["planner", "coder", "critic", "summary"];
  $("agent-models").innerHTML = roleOrder.map((role) => {
    const label = roleLabels[role] || role;
    const agents = (data.agents || []).filter((a) => a.role === role).map((a) => a.display).join(", ");
    const selected = roles[role] || "";
    return `
      <div class="model-row">
        <div class="model-row-main">
          <div class="model-row-name">${escapeHtml(label)}</div>
          <div class="model-row-role">${escapeHtml(agents || role)}</div>
        </div>
        <select class="model-select" data-role="${escapeHtml(role)}">
          ${enabledTools.length ? toolOptions : '<option value="">(không có model đang bật)</option>'}
        </select>
      </div>`;
  }).join("");

  $("agent-models").querySelectorAll("select").forEach((sel) => {
    sel.value = roles[sel.dataset.role] || "";
    sel.onchange = async () => {
      const res2 = await fetch("/api/settings/role-models", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: sel.dataset.role, tool_id: sel.value }),
      });
      const d = await res2.json();
      if (res2.ok) settingsMsg(`Đã gán ${sel.dataset.role} → tool mới`, true);
      else settingsMsg(d.error || "Lỗi", false);
    };
  });

  const list = $("token-list");
  list.innerHTML = data.figma_tokens.length
    ? data.figma_tokens.map((t) => `<div class="token-row"><span>${escapeHtml(t.name)}</span><span style="color:var(--text-dim);font-family:monospace;font-size:0.8rem">${escapeHtml(t.token_masked)}</span><button data-name="${escapeHtml(t.name)}">Xóa</button></div>`).join("")
    : '<div class="settings-hint">(chưa có token)</div>';
  list.querySelectorAll("button").forEach((b) => {
    b.onclick = async () => {
      await fetch(`/api/settings/figma-tokens/${encodeURIComponent(b.dataset.name)}`, { method: "DELETE" });
      loadSettings();
    };
  });

  const gitList = $("git-token-list");
  if (gitList) {
    const gtokens = data.git_tokens || [];
    gitList.innerHTML = gtokens.length
      ? gtokens.map((t) => `<div class="token-row"><span>${escapeHtml(t.name)}</span><span style="color:var(--text-dim);font-size:0.78rem">${escapeHtml(t.host)}</span><span style="color:var(--text-dim);font-family:monospace;font-size:0.8rem">${escapeHtml(t.token_masked)}</span><button data-name="${escapeHtml(t.name)}">Xóa</button></div>`).join("")
      : '<div class="settings-hint">(chưa có — chỉ cần nếu repo private)</div>';
    gitList.querySelectorAll("button").forEach((b) => {
      b.onclick = async () => {
        await fetch(`/api/settings/git-tokens/${encodeURIComponent(b.dataset.name)}`, { method: "DELETE" });
        loadSettings();
      };
    });
  }
}
function settingsMsg(text, ok) { const el = $("settings-msg"); el.textContent = text; el.className = "settings-msg " + (ok ? "ok" : "err"); }
$("sidebar-settings-btn").onclick = openSettings;
$("settings-close").onclick = () => $("settings-backdrop").classList.add("hidden");
$("settings-backdrop").addEventListener("click", (e) => { if (e.target === $("settings-backdrop")) $("settings-close").onclick(); });
$("token-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("token-name").value.trim(), token = $("token-value").value.trim();
  if (!name || !token) return;
  $("token-add").disabled = true;
  settingsMsg("Đang kiểm tra…", true);
  try {
    const res = await fetch("/api/settings/figma-tokens", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, token }),
    });
    const data = await res.json();
    if (res.ok) { settingsMsg(`OK — ${data.account_email}`, true); $("token-name").value = ""; $("token-value").value = ""; loadSettings(); }
    else settingsMsg(data.error || "Lỗi", false);
  } finally { $("token-add").disabled = false; }
});

$("llm-tool-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const base_url = $("llm-base-url").value.trim();
  const model = $("llm-model").value.trim();
  const api_key = $("llm-api-key").value.trim();
  if (!base_url || !model || !api_key) return;
  $("llm-tool-add").disabled = true;
  settingsMsg("Đang kiểm tra endpoint…", true);
  try {
    const res = await fetch("/api/settings/llm-tools", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: model, base_url, model, api_key }),
    });
    const data = await res.json();
    if (res.ok) {
      settingsMsg(`OK — đã thêm ${data.tool.model}`, true);
      $("llm-model").value = "";
      $("llm-api-key").value = "";
      loadSettings();
    } else settingsMsg(data.error || "Lỗi", false);
  } finally {
    $("llm-tool-add").disabled = false;
  }
});

$("git-token-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("git-token-name").value.trim();
  const host = $("git-token-host").value.trim() || "github.com";
  const token = $("git-token-value").value.trim();
  if (!name || !token) return;
  $("git-token-add").disabled = true;
  try {
    const res = await fetch("/api/settings/git-tokens", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, host, token }),
    });
    const data = await res.json();
    if (res.ok) {
      settingsMsg(`OK — Git token cho ${data.host}`, true);
      $("git-token-name").value = "";
      $("git-token-value").value = "";
      loadSettings();
    } else settingsMsg(data.error || "Lỗi", false);
  } finally {
    $("git-token-add").disabled = false;
  }
});

/* ---------- WebSocket ---------- */

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { const el = $("conn-status"); el.textContent = "● online"; el.className = "conn online"; };
  ws.onclose = () => { const el = $("conn-status"); el.textContent = "● offline"; el.className = "conn offline"; setTimeout(connectWS, 3000); };
  ws.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    if (ev.type === "chat") { renderChatMessage(ev.message); notifyTab("chat"); }
    else if (ev.type === "task_updated") {
      state.tasks.set(ev.task.id, ev.task);
      renderBoard();
      notifyTab("board");
      if (state.openTaskId === ev.task.id) openModal(ev.task.id);
    } else if (ev.type === "event" && state.openTaskId === ev.event.task_id) {
      $("modal-events").appendChild(renderEvent(ev.event));
    }
  };
}

/* ---------- Init ---------- */
let _durationTimer = null;
function startDurationTicker() {
  if (_durationTimer) return;
  _durationTimer = setInterval(() => {
    if (state.activeView === "board") renderBoard();
    if (state.openTaskId) {
      const t = state.tasks.get(state.openTaskId);
      if (t && !["done", "archived"].includes(t.status)) {
        const meta = $("modal-meta");
        if (meta?.innerHTML.includes("Thời gian:")) {
          meta.innerHTML = meta.innerHTML.replace(
            /Thời gian: <b>[^<]+<\/b>/,
            `Thời gian: <b>${taskElapsed(t)}</b>`
          );
        }
      }
    }
  }, 60_000);
}

switchView("board");
loadChat();
loadBoard();
connectWS();
startDurationTicker();
resizeChatInput();
