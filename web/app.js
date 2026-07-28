/* Agent Orchestrator — Board (ảnh mẫu) + Chat (Ollie) */

const COLUMNS = [
  { key: "backlog", label: "To Do / Backlog", headClass: "col-backlog", statuses: ["backlog"] },
  { key: "working", label: "In Progress", headClass: "col-in-progress", statuses: ["in_progress"] },
  { key: "needs-you", label: "Needs Attention", headClass: "col-blocked", statuses: ["blocked"] },
  { key: "testing", label: "In Testing / QA", headClass: "col-testing", statuses: ["testing"] },
  { key: "review", label: "In Review", headClass: "col-review", statuses: ["review"] },
  { key: "ready", label: "Done / Ready", headClass: "col-done", statuses: ["done"] },
];

const AGENT_INFO = {
  jarvis: { name: "Jarvis", role: "Squad Lead", icon: "🤖", bg: "#1a2233", fg: "#60a5fa", border: "#2c3b59" },
  coulson: { name: "Coulson", role: "BA Agent", icon: "📋", bg: "#1c212c", fg: "#94a3b8", border: "#2d3545" },
  stark: { name: "Stark", role: "Frontend Developer", icon: "💻", bg: "#2a1b14", fg: "#fb923c", border: "#472b1d" },
  banner: { name: "Banner", role: "DevOps Engineer", icon: "⚡", bg: "#211633", fg: "#a78bfa", border: "#392557" },
  hawkeye: { name: "Hawkeye", role: "Visual QA", icon: "🔍", bg: "#12241a", fg: "#4ade80", border: "#1f402c" },
  pepper: { name: "Pepper", role: "Summary & QA", icon: "📝", bg: "#2d1624", fg: "#f472b6", border: "#4a243b" },
  operator: { name: "Operator", role: "Human Reviewer", icon: "👤", bg: "#1f1f23", fg: "#a1a1aa", border: "#333338" },
  system: { name: "System", role: "System Event", icon: "⚙️", bg: "#261c10", fg: "#fbbf24", border: "#423019" },
};

const AGENT_STYLE = {
  jarvis: AGENT_INFO.jarvis,
  coulson: AGENT_INFO.coulson,
  stark: AGENT_INFO.stark,
  banner: AGENT_INFO.banner,
  hawkeye: AGENT_INFO.hawkeye,
  pepper: AGENT_INFO.pepper,
  system: AGENT_INFO.system,
  operator: AGENT_INFO.operator,
};

const KIND_ICON = {
  comment: "💬",
  status: "↻",
  system: "⚙",
};

const AGENT_LABEL = {
  jarvis: "Jarvis",
  coulson: "Coulson",
  pepper: "Pepper",
  stark: "Stark",
  banner: "Banner",
  hawkeye: "Hawkeye",
  system: "System",
  operator: "Operator",
};

function agentEventIcon(agent, kind) {
  const n = (agent || "system").toLowerCase();
  const info = AGENT_INFO[n] || { name: agent || "System", role: "", icon: "🤖", bg: "#1a2233", fg: "#60a5fa", border: "#2c3b59" };
  return `
    <div class="event-icon-wrap" title="${escapeHtml(info.name)} — ${escapeHtml(info.role)}">
      <span class="event-icon agent-${escapeHtml(n)}" style="background:${info.bg};color:${info.fg};border:1px solid ${info.border}">${info.icon}</span>
    </div>`;
}

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

const toggleSidebarBtn = document.querySelector(".sidebar-toggle-btn");
if (toggleSidebarBtn) {
  toggleSidebarBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    document.body.classList.toggle("sidebar-collapsed");
    const isCollapsed = document.body.classList.contains("sidebar-collapsed");
    localStorage.setItem("sidebar-collapsed", isCollapsed ? "true" : "false");
  });
}
if (localStorage.getItem("sidebar-collapsed") === "true") {
  document.body.classList.add("sidebar-collapsed");
}

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

function formatMarkdownMessage(text) {
  if (!text) return "";
  let html = escapeHtml(text);
  // Bold **text**
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Italic *text*
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  // Code `text`
  html = html.replace(/`(.*?)`/g, '<code class="chat-code">$1</code>');
  // Line breaks
  html = html.replace(/\n/g, '<br/>');
  return html;
}

function focusChatInput(prefix) {
  const ta = $("chat-text");
  if (!ta) return;
  if (prefix) ta.value = prefix;
  ta.focus();
}

function renderChatMessage(m) {
  const box = $("chat-messages");
  if (!box) return;
  if (m.role === "system") {
    const timeStr = formatTime(m.created_at) || "";
    const row = document.createElement("div");
    row.className = "msg-row system-msg";
    row.innerHTML = `
      <span class="avatar avatar-system">⚙️</span>
      <div class="msg-jarvis-wrapper">
        <div class="msg-meta-jarvis">
          <span class="name" style="color: #eab308;">System / Board Patrol</span>
          ${timeStr ? `<span class="dot">•</span><span class="time">${timeStr}</span>` : ''}
          <span class="system-badge">System Notification</span>
        </div>
        <div class="msg-bubble system-bubble">${formatMarkdownMessage(m.message)}</div>
      </div>`;
    const thinkRow = $("thinking-row");
    if (thinkRow) box.insertBefore(row, thinkRow);
    else box.appendChild(row);
    box.scrollTop = box.scrollHeight;
    return;
  }
  const isUser = m.role === "user";
  const row = document.createElement("div");
  row.className = `msg-row ${isUser ? "user" : "jarvis"}`;
  
  const timeStr = formatTime(m.created_at) || "12:42 PM";

  if (isUser) {
    row.innerHTML = `
      <div class="msg-user-wrapper">
        <div class="msg-meta-user">
          <span class="time">${timeStr}</span>
          <span class="dot">•</span>
          <span class="name">Bạn</span>
        </div>
        <div class="msg-bubble user-bubble">${formatMarkdownMessage(m.message)}</div>
      </div>
      <span class="avatar avatar-user">👤</span>`;
  } else {
    row.innerHTML = `
      <span class="avatar avatar-jarvis">🎯</span>
      <div class="msg-jarvis-wrapper">
        <div class="msg-meta-jarvis">
          <span class="name">Jarvis</span>
          <span class="dot">•</span>
          <span class="time">${timeStr}</span>
          <span class="model-badge">deepseek/deepseek-v4-flash</span>
          <span class="worked-badge">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
            Worked • 1 step • 2s ∨
          </span>
        </div>
        <div class="msg-bubble jarvis-bubble">${formatMarkdownMessage(m.message)}</div>
      </div>`;
  }
  const thinkRow = $("thinking-row");
  if (thinkRow) box.insertBefore(row, thinkRow);
  else box.appendChild(row);
  box.scrollTop = box.scrollHeight;
  if (!isUser) setThinking(false);
}

function setThinking(on) {
  state.thinking = !!on;
  const box = $("chat-messages");
  if (!box) return;
  let thinkRow = $("thinking-row");
  if (on) {
    if (!thinkRow) {
      thinkRow = document.createElement("div");
      thinkRow.id = "thinking-row";
      thinkRow.className = "msg-row jarvis thinking";
      thinkRow.innerHTML = `
        <span class="avatar avatar-jarvis">🤖</span>
        <div class="msg-bubble thinking-bubble">
          <span class="thinking-text">Jarvis đang suy nghĩ...</span>
          <span class="typing-dots">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
          </span>
        </div>`;
    }
    box.appendChild(thinkRow);
    box.scrollTop = box.scrollHeight;
  } else if (thinkRow) {
    thinkRow.remove();
  }
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
    w.innerHTML = `<span class="avatar avatar-jarvis">🤖</span><div><div class="msg-bubble">Ask me something!</div></div>`;
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

function parseMeta(t) {
  if (!t || !t.description) return {};
  if (t.description.startsWith("{")) {
    try { return JSON.parse(t.description); } catch(e) {}
  }
  return {};
}

function pillFor(t, meta) {
  if (meta.pill_text) return { cls: meta.pill_cls || "pill-pending", text: meta.pill_text };
  if (t.status === "in_progress") return { cls: "pill-working", text: "Working" };
  if (t.status === "blocked" && t.type === "bug") return { cls: "pill-failed", text: "CI failed" };
  if (t.status === "blocked") return { cls: "pill-changes", text: "Changes requested" };
  if (t.status === "backlog") return { cls: "pill-queued", text: "Queued" };
  if (t.status === "review") return { cls: "pill-pending", text: "Review pending" };
  if (t.status === "testing") return { cls: "pill-pending", text: "QA in progress" };
  if (t.status === "done") return { cls: "pill-ready", text: "Ready" };
  return { cls: "pill-pending", text: t.status };
}

function cardTag(t) {
  const assigneeName = t.assignee || "stark";
  const agent = assigneeName.toLowerCase();
  const info = AGENT_INFO[agent] || { icon: "🤖" };
  return `<span class="card-agent-tag" title="${escapeHtml(assigneeName)}">${info.icon} ${escapeHtml(assigneeName)}</span>`;
}

function metaRows(t, meta) {
  if (meta.stacked_prs && Array.isArray(meta.stacked_prs)) {
    return `<div class="stacked-prs">` + meta.stacked_prs.map(pr => {
      const ciCls = pr.ci === "Passing" ? "pass" : pr.ci === "Failing" ? "fail" : "dim";
      const revCls = pr.review === "Approved" ? "pass" : pr.review === "Changes requested" ? "warn" : "dim";
      const mergeCls = pr.merge === "Mergeable" ? "pass" : "dim";
      return `
        <div class="stacked-pr-block">
          <div class="meta-row"><span class="mk">PR</span><span class="mv">${escapeHtml(pr.pr_num)} · ${escapeHtml(pr.pr_status)}</span></div>
          <div class="meta-row">
            <span class="mk">CI</span><span class="mv ${ciCls}">${escapeHtml(pr.ci)}</span>
            <span class="mk-inline">Review</span><span class="mv ${revCls}">${escapeHtml(pr.review)}</span>
          </div>
          <div class="meta-row"><span class="mk">Merge</span><span class="mv ${mergeCls}">${escapeHtml(pr.merge)}</span></div>
        </div>`;
    }).join("") + `</div>`;
  }

  const pr = meta.pr ? meta.pr : (meta.pr_num ? `${meta.pr_num} · ${meta.pr_status || "open"}` : (t.status === "in_progress" || t.status === "backlog" ? "no PR yet" : `${t.id} · ${t.status === "done" ? "merged" : "open"}`));
  
  let ci = meta.ci || (t.status === "done" ? "Passing" : t.status === "blocked" ? "Failing" : "Pending");
  let ciCls = ci === "Passing" ? "pass" : ci === "Failing" ? "fail" : "dim";

  let review = meta.review || (t.status === "done" ? "Approved" : t.status === "blocked" ? "Changes requested" : "None");
  let revCls = review === "Approved" ? "pass" : review === "Changes requested" ? "warn" : "dim";

  let merge = meta.merge || (t.status === "done" ? "Mergeable" : "Checking");
  let mergeCls = merge === "Mergeable" ? "pass" : "dim";

  return `
    <div class="meta-row"><span class="mk">PR</span><span class="mv">${escapeHtml(pr)}</span></div>
    <div class="meta-row"><span class="mk">CI</span><span class="mv ${ciCls}">${escapeHtml(ci)}</span><span class="mk-inline">Review</span><span class="mv ${revCls}">${escapeHtml(review)}</span></div>
    <div class="meta-row"><span class="mk">Merge</span><span class="mv ${mergeCls}">${escapeHtml(merge)}</span></div>`;
}

function attentionFor(t, meta) {
  if (!meta.attention_title && t.status !== "blocked" && t.status !== "backlog") return "";

  const title = meta.attention_title || (t.status === "blocked" ? (t.type === "bug" ? "Fix failing CI" : "Address requested changes") : "Waiting to start");
  
  let titleCls = "yellow";
  if (title.includes("failing") || title.includes("CI")) titleCls = "red";
  else if (title.includes("Draft")) titleCls = "dim";

  const sub = meta.attention_sub ? `<div class="attention-sub">${escapeHtml(meta.attention_sub)}</div>` : "";
  const link = meta.attention_link ? `<a class="attention-link" href="#">${escapeHtml(meta.attention_link)}</a>` : "";

  return `
    <div class="task-card-attention">
      <div class="attention-label">NEEDS ATTENTION</div>
      <div class="attention-content">
        <span class="attention-title ${titleCls}">${escapeHtml(title)}</span>
        ${link}
      </div>
      ${sub}
    </div>`;
}

function renderCard(t) {
  const card = document.createElement("div");
  card.className = "task-card";
  card.onclick = () => openModal(t.id);
  const meta = parseMeta(t);
  const pill = pillFor(t, meta);
  const path = meta.branch || (t.project_dir
    ? t.project_dir.replace(/^.*[\\/]projects[\\/]/, "demo/")
    : `demo/${t.project}`);
  const elapsed = taskElapsed(t);
  const timeBadge = elapsed ? `<span class="task-card-time" title="Thời gian tổng">⏱ ${elapsed}</span>` : "";
  card.innerHTML = `
    <div class="task-card-head">
      <span class="pill ${pill.cls}"><span class="pill-dot"></span>${pill.text}</span>
      ${cardTag(t)}
    </div>
    <div class="task-card-title">${escapeHtml(t.title)}</div>
    <div class="task-card-path">${escapeHtml(path)}</div>
    <div class="task-card-meta">${metaRows(t, meta)}</div>
    ${attentionFor(t, meta)}
    ${timeBadge}`;
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
    colEl.className = `kanban-col col-${col.key}`;
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
    const isExpanded = state.activeProject === p.slug || state.expandedProjects?.has(p.slug);
    const group = document.createElement("div");
    group.className = "project-group" + (state.activeProject === p.slug ? " active" : "");

    const head = document.createElement("div");
    head.className = "project-name" + (state.activeProject === p.slug ? " selected" : "");
    head.innerHTML = `
      <span class="chevron">▼</span>
      <span class="project-label">${escapeHtml(p.name || p.slug)}</span>
      <button class="project-remove" title="Xóa project" type="button">×</button>`;
    head.querySelector(".project-label").onclick = (e) => { e.stopPropagation(); selectProject(p.slug); };
    head.querySelector(".chevron").onclick = (e) => { e.stopPropagation(); selectProject(p.slug); };
    head.querySelector(".project-remove").onclick = (e) => {
      e.stopPropagation();
      removeProject(p.slug, p.name || p.slug);
    };
    group.appendChild(head);

    const list = document.createElement("div");
    list.className = "project-tasks";
    const parents = [...state.tasks.values()].filter((t) => !t.parent_id && t.project === p.slug);
    if (!parents.length) {
      list.innerHTML = '<div class="sidebar-hint" style="padding-left:20px">Chưa có task</div>';
    } else {
      for (const t of parents) {
        const item = document.createElement("div");
        item.className = "sidebar-task" + (state.openTaskId === t.id ? " active" : "");
        
        let dotColor = "#9ba1aa";
        if (t.status === "in_progress") dotColor = "#b1763d";
        else if (t.status === "blocked" && t.type === "bug") dotColor = "#ef4444";
        else if (t.status === "blocked") dotColor = "#e8c14a";
        else if (t.status === "review" || t.status === "testing") dotColor = "#9ba1aa";
        else if (t.status === "done") dotColor = "#74b98a";

        item.innerHTML = `<span class="dot" style="background:${dotColor}"></span><span class="label">${escapeHtml(t.title)}</span>`;
        item.onclick = (e) => { e.stopPropagation(); selectProject(p.slug); openModal(t.id); };
        list.appendChild(item);
      }
    }
    group.appendChild(list);
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
  if (!t) {
    console.error("Task not found:", taskId);
    return;
  }

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
  if (!msg) return "";
  let s = escapeHtml(msg);
  
  // Artifact screenshot URLs -> inline images with nice frame
  s = s.replace(/(view_url|diff_view_url):\s*(https?:\/\/[^\s<]+)/gi, (_, _k, url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank" class="qa-shot-link">📸 View Screenshot</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);
  s = s.replace(/(https?:\/\/[^\s<]+\/artifacts\/[^\s<]+\.png)/gi, (url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank" class="qa-shot-link">📸 View Screenshot</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);

  // Markdown Headers
  s = s.replace(/^### (.+)$/gm, '<h4 class="event-h3">$1</h4>');
  s = s.replace(/^## (.+)$/gm, '<h3 class="event-h2">$1</h3>');
  s = s.replace(/^# (.+)$/gm, '<h2 class="event-h1">$1</h2>');

  // Bold text
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Inline code block `file.ext`
  s = s.replace(/`([^`]+)`/g, '<code class="event-inline-code">$1</code>');

  // Markdown status badges (PASS / FAIL)
  s = s.replace(/✅/g, '<span class="icon-pass">✅</span>');
  s = s.replace(/❌/g, '<span class="icon-fail">❌</span>');
  s = s.replace(/\bPASS\b/g, '<span class="badge-pass">PASS</span>');
  s = s.replace(/\bFAIL\b/g, '<span class="badge-fail">FAIL</span>');

  // Parse markdown tables properly into HTML <table>
  const lines = s.split("\n");
  let inTable = false;
  let tableRows = [];
  let outLines = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith("|") && line.endsWith("|")) {
      if (line.includes("---")) continue; // Skip separator line
      const cells = line.split("|").filter((_, idx, arr) => idx > 0 && idx < arr.length - 1).map(c => c.trim());
      tableRows.push(cells);
    } else {
      if (tableRows.length > 0) {
        let tHtml = '<table class="qa-table"><thead><tr>';
        const headers = tableRows[0];
        tHtml += headers.map(h => `<th>${h}</th>`).join('') + '</tr></thead><tbody>';
        for (let r = 1; r < tableRows.length; r++) {
          tHtml += '<tr>' + tableRows[r].map(c => `<td>${c}</td>`).join('') + '</tr>';
        }
        tHtml += '</tbody></table>';
        outLines.push(tHtml);
        tableRows = [];
      }
      if (line) outLines.push(line);
    }
  }
  if (tableRows.length > 0) {
    let tHtml = '<table class="qa-table"><thead><tr>';
    const headers = tableRows[0];
    tHtml += headers.map(h => `<th>${h}</th>`).join('') + '</tr></thead><tbody>';
    for (let r = 1; r < tableRows.length; r++) {
      tHtml += '<tr>' + tableRows[r].map(c => `<td>${c}</td>`).join('') + '</tr>';
    }
    tHtml += '</tbody></table>';
    outLines.push(tHtml);
  }

  return outLines.join("<br>");
}

const AGENT_ROLE_TITLE = {
  jarvis: "Jarvis (Squad Lead)",
  pepper: "Pepper (Summary & QA)",
  stark: "Stark (Senior Coder)",
  banner: "Banner (UI Developer)",
  hawkeye: "Hawkeye (Visual QA)",
  system: "System",
  operator: "Operator",
};

function renderEvent(e) {
  const agent = (e.agent || "system").toLowerCase();
  const label = AGENT_ROLE_TITLE[agent] || AGENT_LABEL[agent] || e.agent || "System";
  const div = document.createElement("div");
  div.className = `event kind-${e.kind} agent-event-${agent}`;

  const formattedTime = new Date(e.created_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  const formattedBody = formatEventMessage(e.message);

  const isStructured = e.message && (
    e.message.includes("|") || 
    e.message.includes("##") || 
    e.message.includes("http") || 
    agent === "pepper"
  );

  const bodyContent = isStructured
    ? `<div class="event-content-box">${formattedBody}</div>`
    : `<div class="event-body-text">${formattedBody}</div>`;

  div.innerHTML = `
    <div class="event-card">
      <div class="event-card-header">
        ${agentEventIcon(e.agent, e.kind)}
        <span class="event-agent-name">${escapeHtml(label)}</span>
        <span class="event-time">${formattedTime}</span>
      </div>
      ${bodyContent}
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

  // LLM tools list — hiện model + base_url + default badge
  const DEFAULT_MODELS = ["deepseek-v4-flash-free", "nemotron-3-ultra-free", "mimo-v2.5-free"];
  const toolList = $("llm-tool-list");
  toolList.innerHTML = tools.length
    ? tools.map((t) => {
        const isDef = t.is_default || DEFAULT_MODELS.includes(t.model);
        return `
      <div class="llm-tool-row ${t.enabled ? "" : "off"}">
        <div class="llm-model-info">
          <div class="llm-model-name-row">
            <code class="llm-model-name">${escapeHtml(t.model)}</code>
            ${isDef ? '<span class="default-badge">Hệ thống</span>' : ''}
          </div>
          <div class="llm-model-url">${escapeHtml(t.base_url || "https://opencode.ai/zen/v1")}</div>
        </div>
        <div class="llm-tool-actions">
          <label class="toggle" title="${isDef ? "Model mặc định của hệ thống luôn ở trạng thái bật" : (t.enabled ? "Tắt model" : "Bật model")}">
            <input type="checkbox" data-id="${escapeHtml(t.id)}" ${t.enabled ? "checked" : ""} ${isDef ? "disabled" : ""} />
            <span class="toggle-track"></span>
          </label>
          ${!isDef ? `<button class="btn-delete-llm-tool" data-id="${escapeHtml(t.id)}" title="Xóa model">Xóa</button>` : ''}
        </div>
      </div>`;
      }).join("")
    : '<div class="settings-hint">(chưa có LLM tool — thêm bên dưới)</div>';

  toolList.querySelectorAll('input[type="checkbox"]:not([disabled])').forEach((cb) => {
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

  toolList.querySelectorAll(".btn-delete-llm-tool").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("Bạn có chắc muốn xóa model này không?")) return;
      const res = await fetch(`/api/settings/llm-tools/${encodeURIComponent(btn.dataset.id)}`, {
        method: "DELETE",
      });
      const d = await res.json();
      if (!res.ok) {
        settingsMsg(d.error || "Lỗi khi xóa", false);
        return;
      }
      settingsMsg("Đã xóa model thành công", true);
      loadSettings();
    };
  });

  const hasActiveTasks = !!data.has_active_tasks;
  const enabledTools = tools.filter((t) => t.enabled);
  const toolOptions = enabledTools.map((t) =>
    `<option value="${escapeHtml(t.id)}">${escapeHtml(t.model)}</option>`
  ).join("");

  // Role pickers (planner/coder/critic/summary) + agent mapping
  const roleOrder = ["planner", "coder", "critic", "summary"];
  const activeWarningHtml = hasActiveTasks
    ? `<div class="active-tasks-lock-banner">
        🔒 <strong>Đang có Task đang thực thi:</strong> Để tránh xung đột tiến trình, vui lòng chờ các Agent hoàn thành công việc trước khi thay đổi cấu hình Model.
       </div>`
    : '';

  $("agent-models").innerHTML = activeWarningHtml + roleOrder.map((role) => {
    const label = roleLabels[role] || role;
    const agents = (data.agents || []).filter((a) => a.role === role).map((a) => a.display).join(", ");
    const selected = roles[role] || "";
    return `
      <div class="model-row ${hasActiveTasks ? "locked" : ""}">
        <div class="model-row-main">
          <div class="model-row-name">${escapeHtml(label)}</div>
          <div class="model-row-role">${escapeHtml(agents || role)}</div>
        </div>
        <select class="model-select" data-role="${escapeHtml(role)}" ${hasActiveTasks ? "disabled title='Đang có task đang chạy — không thể đổi model'" : ""}>
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
document.querySelectorAll(".settings-tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".settings-tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".settings-tab-content").forEach((c) => {
      c.classList.add("hidden");
      c.classList.remove("active");
    });
    btn.classList.add("active");
    const targetId = btn.dataset.tab;
    const target = $(targetId);
    if (target) {
      target.classList.remove("hidden");
      target.classList.add("active");
    }
  });
});

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
