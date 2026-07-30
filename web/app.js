/* Agent Orchestrator — Board (ảnh mẫu) + Chat (Ollie) */

const COLUMNS = [
  { key: "backlog", label: "To Do / Backlog", headClass: "col-backlog", statuses: ["backlog"] },
  { key: "working", label: "In Progress", headClass: "col-working", statuses: ["in_progress"] },
  { key: "blocked", label: "Needs Attention", headClass: "col-blocked", statuses: ["blocked", "failed"] },
  { key: "testing", label: "In Testing / QA", headClass: "col-testing", statuses: ["testing"] },
  { key: "review", label: "In Review", headClass: "col-review", statuses: ["review"] },
  { key: "done", label: "Done / Ready", headClass: "col-done", statuses: ["done"] },
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
  chatMessages: [],
  plannerModel: "",
  workStartedAt: null, // Date.now() khi user gửi, để badge live chính xác
};
const $ = (id) => document.getElementById(id);

function customConfirm(title, message, okText = "Đồng ý", okBg = "") {
  return new Promise((resolve) => {
    const backdrop = $("confirm-backdrop");
    const titleEl = $("confirm-title");
    const msgEl = $("confirm-msg");
    const okBtn = $("confirm-ok-btn");
    const cancelBtn = $("confirm-cancel-btn");
    if (!backdrop) {
      resolve(window.confirm(message));
      return;
    }
    titleEl.textContent = title || "Xác nhận";
    msgEl.innerHTML = (message || "").replace(
      /"(tsk-[^"]+)"/g,
      '<code style="color: #60a5fa; background: rgba(96, 165, 250, 0.15); border: 1px solid rgba(96, 165, 250, 0.35); padding: 2px 7px; border-radius: 5px; font-weight: 650; font-family: monospace; font-size: 0.9em; box-shadow: 0 0 8px rgba(96, 165, 250, 0.25);">"$1"</code>'
    );
    okBtn.textContent = okText;
    if (okBg) okBtn.style.background = okBg;
    else okBtn.style.background = "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)";

    const cleanup = (val) => {
      backdrop.classList.add("hidden");
      okBtn.onclick = null;
      cancelBtn.onclick = null;
      resolve(val);
    };

    okBtn.onclick = () => cleanup(true);
    cancelBtn.onclick = () => cleanup(false);
    backdrop.classList.remove("hidden");
  });
}

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

const brandToggleBtn = $("brand-toggle-btn") || document.querySelector(".sidebar-brand");
if (brandToggleBtn) {
  brandToggleBtn.addEventListener("click", (e) => {
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
  // Chuẩn hóa Live preview URL: luôn có trailing slash (tránh /preview/voxbeat → load sai)
  text = text.replace(
    /(https?:\/\/[^\s<>"']+\/preview\/[a-z0-9_-]+)(?![\w./#-])/gi,
    "$1/"
  );
  text = text.replace(
    /(https?:\/\/[^\s<>"']+\/preview\/[a-z0-9_-]+)(?=\s|$|[)\].,!])/gi,
    (url) => (url.endsWith("/") ? url : url + "/")
  );
  let html = escapeHtml(text);
  // Autolink http(s)
  html = html.replace(
    /(https?:\/\/[^\s<]+)/gi,
    (url) => {
      let href = url;
      const m = href.match(/^(https?:\/\/[^/]+\/preview\/[a-z0-9_-]+)\/?$/i);
      if (m) href = m[1] + "/";
      return `<a href="${href}" target="_blank" rel="noopener">${url}</a>`;
    }
  );
  // Bold **text**
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  // Italic *text*
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
  // Code `text`
  html = html.replace(/`(.*?)`/g, '<code class="chat-code">$1</code>');
  // Line breaks
  html = html.replace(/\n/g, "<br/>");
  return html;
}

function focusChatInput(prefix) {
  const ta = $("chat-text");
  if (!ta) return;
  if (prefix) ta.value = prefix;
  ta.focus();
}

function formatDurationPrecise(ms) {
  if (ms == null || Number.isNaN(ms) || ms < 0) return "0s";
  const sec = Math.max(0, Math.round(ms / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const s = sec % 60;
  if (min < 60) return s ? `${min}m ${s}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${hr}h ${m}m` : `${hr}h`;
}

/** Worked badge: steps + thời gian thật từ tin user trước → phản hồi này. */
function jarvisWorkStats(messages, index) {
  const m = messages[index];
  if (!m || (m.role !== "jarvis" && m.role !== "system")) return null;

  let userIdx = -1;
  for (let i = index - 1; i >= 0; i--) {
    if (messages[i].role === "user") {
      userIdx = i;
      break;
    }
  }

  let steps = 0;
  for (let i = Math.max(0, userIdx + 1); i <= index; i++) {
    if (messages[i].role !== "user") steps++;
  }
  if (steps < 1) steps = 1;

  let durationMs = null;
  const endAt = m.created_at ? new Date(m.created_at).getTime() : NaN;
  if (userIdx >= 0 && messages[userIdx].created_at && !Number.isNaN(endAt)) {
    durationMs = endAt - new Date(messages[userIdx].created_at).getTime();
  } else if (state.workStartedAt && !Number.isNaN(endAt)) {
    durationMs = endAt - state.workStartedAt;
  } else if (state.workStartedAt) {
    durationMs = Date.now() - state.workStartedAt;
  }
  if (durationMs != null && durationMs < 0) durationMs = 0;

  return {
    steps,
    durationMs,
    label: `Worked • ${steps} step${steps === 1 ? "" : "s"} • ${formatDurationPrecise(durationMs ?? 0)}`,
  };
}

function plannerModelLabel() {
  return (state.plannerModel || "").trim() || "planner";
}

function appendChatMessage(m) {
  if (!m) return;
  if (m.id != null && state.chatMessages.some((x) => x.id === m.id)) return;
  state.chatMessages.push(m);
  renderChatMessage(m, state.chatMessages.length - 1);
}

function renderChatMessage(m, index) {
  const box = $("chat-messages");
  if (!box) return;
  if (index == null) {
    index = state.chatMessages.findIndex((x) => x === m || (m.id != null && x.id === m.id));
    if (index < 0) {
      state.chatMessages.push(m);
      index = state.chatMessages.length - 1;
    }
  }

  if (m.role === "system") {
    const timeStr = formatTime(m.created_at);
    const work = jarvisWorkStats(state.chatMessages, index);
    const row = document.createElement("div");
    row.className = "msg-row system-msg";
    row.innerHTML = `
      <span class="avatar avatar-system">⚙️</span>
      <div class="msg-jarvis-wrapper">
        <div class="msg-meta-jarvis">
          <span class="name" style="color: #eab308;">System / Board Patrol</span>
          ${timeStr ? `<span class="dot">•</span><span class="time">${escapeHtml(timeStr)}</span>` : ""}
          ${work ? `<span class="worked-badge" title="Thời gian thật từ tin nhắn user trước">${escapeHtml(work.label)}</span>` : ""}
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
  const timeStr = formatTime(m.created_at);

  if (isUser) {
    row.innerHTML = `
      <div class="msg-user-wrapper">
        <div class="msg-meta-user">
          ${timeStr ? `<span class="time">${escapeHtml(timeStr)}</span><span class="dot">•</span>` : ""}
          <span class="name">Bạn</span>
        </div>
        <div class="msg-bubble user-bubble">${formatMarkdownMessage(m.message)}</div>
      </div>
      <span class="avatar avatar-user">👤</span>`;
  } else {
    const work = jarvisWorkStats(state.chatMessages, index);
    row.innerHTML = `
      <span class="avatar avatar-jarvis">🎯</span>
      <div class="msg-jarvis-wrapper">
        <div class="msg-meta-jarvis">
          <span class="name">Jarvis</span>
          ${timeStr ? `<span class="dot">•</span><span class="time">${escapeHtml(timeStr)}</span>` : ""}
          <span class="model-badge">${escapeHtml(plannerModelLabel())}</span>
          ${work ? `<span class="worked-badge" title="Thời gian thật từ lúc bạn gửi đến phản hồi này">${escapeHtml(work.label)}</span>` : ""}
        </div>
        <div class="msg-bubble jarvis-bubble">${formatMarkdownMessage(m.message)}</div>
      </div>`;
    if (state.workStartedAt) state.workStartedAt = null;
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
  state.chatMessages = data.messages || [];
  if (!state.chatMessages.length) {
    const w = document.createElement("div");
    w.className = "msg-row jarvis";
    w.innerHTML = `<span class="avatar avatar-jarvis">🤖</span><div><div class="msg-bubble">Ask me something!</div></div>`;
    $("chat-messages").appendChild(w);
  } else {
    state.chatMessages.forEach((m, i) => renderChatMessage(m, i));
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
  state.workStartedAt = Date.now();
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

function cardTag(t) {
  let assigneeName = t.assignee || "stark";
  if (t.status === "testing" && assigneeName !== "hawkeye") {
    assigneeName = "hawkeye";
  } else if (t.status === "review" && assigneeName !== "jarvis" && assigneeName !== "pepper") {
    assigneeName = "pepper";
  } else if (t.status === "done") {
    assigneeName = "jarvis";
  }
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
  
  let ci = meta.ci || (t.status === "done" ? "Passing" : (t.status === "blocked" || t.status === "failed") ? "Failing" : "Pending");
  let ciCls = ci === "Passing" ? "pass" : ci === "Failing" ? "fail" : "dim";

  let review = meta.review || (t.status === "done" ? "Approved" : (t.status === "blocked" || t.status === "failed") ? "Changes requested" : "None");
  let revCls = review === "Approved" ? "pass" : review === "Changes requested" ? "warn" : "dim";

  let merge = meta.merge || (t.status === "done" ? "Mergeable" : "Checking");
  let mergeCls = merge === "Mergeable" ? "pass" : "dim";

  return `
    <div class="meta-row"><span class="mk">PR</span><span class="mv">${escapeHtml(pr)}</span></div>
    <div class="meta-row"><span class="mk">CI</span><span class="mv ${ciCls}">${escapeHtml(ci)}</span><span class="mk-inline">Review</span><span class="mv ${revCls}">${escapeHtml(review)}</span></div>
    <div class="meta-row"><span class="mk">Merge</span><span class="mv ${mergeCls}">${escapeHtml(merge)}</span></div>`;
}

function attentionFor(t, meta) {
  if (!meta.attention_title && t.status !== "blocked" && t.status !== "failed" && t.status !== "backlog") return "";

  const title = meta.attention_title || ((t.status === "blocked" || t.status === "failed") ? (t.type === "bug" ? "Fix failing CI" : "Address requested changes") : "Waiting to start");
  
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

function childStatusMeta(status) {
  let statusText = "Pending";
  let subCls = "sub-backlog";
  if (status === "in_progress") { statusText = "Running"; subCls = "sub-working"; }
  else if (status === "testing") { statusText = "QA Testing"; subCls = "sub-testing"; }
  else if (status === "review") { statusText = "In Review"; subCls = "sub-review"; }
  else if (status === "done") { statusText = "Done ✓"; subCls = "sub-done"; }
  else if (status === "blocked" || status === "failed") {
    statusText = status === "failed" ? "Failed" : "Blocked";
    subCls = "sub-blocked";
  }
  return { statusText, subCls };
}

function getProgressStyle(percent, hasOpenBugs) {
  if (hasOpenBugs) {
    return {
      fill: "linear-gradient(90deg, #f87171, #ef4444)",
      color: "#f87171"
    };
  }
  if (percent === 100) {
    return {
      fill: "linear-gradient(90deg, #34d399, #10b981)",
      color: "#34d399"
    };
  }
  if (percent > 30) {
    return {
      fill: "linear-gradient(90deg, #fb923c, #f59e0b)",
      color: "#fb923c"
    };
  }
  return {
    fill: "linear-gradient(90deg, #38bdf8, #60a5fa)",
    color: "#38bdf8"
  };
}

function childrenOf(parentId) {
  return [...state.tasks.values()]
    .filter((c) => c.parent_id === parentId)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
}

function subtasksFor(t) {
  const children = childrenOf(t.id);
  const work = children.filter((c) => c.type !== "bug");
  const bugs = children.filter((c) => c.type === "bug");
  if (!work.length && !bugs.length) return "";

  const renderRows = (list, kind) => list.map((sub, i) => {
    let agentName = sub.assignee || "stark";
    if (sub.status === "testing" && agentName !== "hawkeye") {
      agentName = "hawkeye";
    } else if (sub.status === "review" && agentName !== "jarvis" && agentName !== "pepper") {
      agentName = "pepper";
    }
    const info = AGENT_INFO[agentName.toLowerCase()] || { icon: "🤖" };
    const { statusText, subCls } = childStatusMeta(sub.status);
    const step = sub.id || (kind === "bug" ? `bug-${i + 1}` : `#${i + 1}`);

    return `
      <div class="subtask-card-row ${subCls}${kind === "bug" ? " is-bug" : ""}">
        <span class="subtask-dot"></span>
        <span class="subtask-step">${escapeHtml(step)}</span>
        <span class="subtask-title" title="${escapeHtml(sub.title)}">${escapeHtml(sub.title)}</span>
        <span class="subtask-agent-tag"><span class="subtask-agent-icon">${info.icon}</span> ${escapeHtml(agentName)}</span>
        <span class="subtask-badge ${subCls}">${statusText}</span>
      </div>`;
  }).join("");

  let html = "";
  if (work.length) {
    const completed = work.filter((c) => c.status === "done" || c.status === "testing" || c.status === "review").length;
    const percent = Math.round((completed / work.length) * 100);
    const hasOpenBugs = bugs.some((b) => b.status !== "done" && b.status !== "archived");
    const pStyle = getProgressStyle(percent, hasOpenBugs);
    html += `
    <div class="task-card-subtasks">
      <div class="subtasks-header">
        <span class="subtasks-label">SUBTASKS (${completed}/${work.length})</span>
        <span class="subtasks-pct" style="color: ${pStyle.color}">${percent}%</span>
      </div>
      <div class="subtasks-progress">
        <div class="subtasks-fill" style="width: ${percent}%; background: ${pStyle.fill}"></div>
      </div>
      <div class="subtasks-list">${renderRows(work, "task")}</div>
    </div>`;
  }
  if (bugs.length) {
    const open = bugs.filter((c) => c.status !== "done" && c.status !== "archived").length;
    html += `
    <div class="task-card-subtasks task-card-bugs">
      <div class="subtasks-header">
        <span class="subtasks-label">BUGS (${open} mở / ${bugs.length})</span>
      </div>
      <div class="subtasks-list">${renderRows(bugs, "bug")}</div>
    </div>`;
  }
  return html;
}

async function blockTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/block`, { method: "POST" });
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
  const canBlock = !["done", "archived", "blocked"].includes(t.status);
  const blockBtn = canBlock ? `<button class="btn-task-block" onclick="event.stopPropagation(); blockTask('${t.id}')" title="Dừng & Chuyển sang Blocked để kiểm tra">✕</button>` : "";

  card.innerHTML = `
    <div class="task-card-head">
      <span class="pill ${pill.cls}"><span class="pill-dot"></span>${pill.text}</span>
      <div class="task-card-head-right">
        ${timeBadge}
        ${cardTag(t)}
        ${blockBtn}
      </div>
    </div>
    <div class="task-card-title">${escapeHtml(t.title)}</div>
    <div class="task-card-path">${escapeHtml(path)}</div>
    <div class="task-card-meta">${metaRows(t, meta)}</div>
    ${subtasksFor(t)}
    ${attentionFor(t, meta)}`;
  return card;
}

function renderBoard() {
  const board = $("board");
  board.innerHTML = "";
  let parents = [...state.tasks.values()].filter((t) => !t.parent_id);
  if (state.activeProject) {
    parents = parents.filter((t) => t.project === state.activeProject);
  }

  // Sắp xếp task mới nhất (theo thời gian tạo) lên trên
  parents.sort((a, b) => {
    const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
    const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;
    return timeA === timeB ? String(b.id).localeCompare(String(a.id)) : timeB - timeA;
  });

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

function getProjectIcon(p) {
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
    if (p.project_dir) head.title = p.project_dir;
    head.innerHTML = `
      <span class="chevron">▼</span>
      ${getProjectIcon(p)}
      <span class="project-label">${escapeHtml(p.name || p.slug)}</span>
      <button class="project-remove" title="Xóa project" type="button">×</button>`;
    head.querySelector(".project-label").onclick = (e) => { e.stopPropagation(); selectProject(p.slug); };
    head.querySelector(".chevron").onclick = (e) => { e.stopPropagation(); selectProject(p.slug); };
    head.querySelector(".project-remove").onclick = (e) => {
      e.stopPropagation();
      removeProject(p.slug, p.name || p.slug);
    };
    group.appendChild(head);

    const isCompact = document.body.classList.contains("sidebar-collapsed") || window.innerWidth <= 768;
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

async function loadProjects() {
  try {
    const res = await fetch("/api/projects");
    const data = await res.json();
    state.projects = data.projects || [];
    if (data.active_project) state.activeProject = data.active_project;
    else if (!state.activeProject && state.projects.length) {
      state.activeProject = state.projects[0].slug;
    }
    renderProjects();
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
  const proj = state.projects.find((p) => p.slug === slug);
  const dirHint = proj?.project_dir
    ? `\nThư mục trên đĩa cũng sẽ bị xóa:\n${proj.project_dir}`
    : "\nThư mục project trên đĩa (nếu có) cũng sẽ bị xóa.";
  const msg = taskCount
    ? `Xóa project "${label}"?\n${taskCount} task sẽ bị archive và ẩn khỏi board.${dirHint}`
    : `Xóa project "${label}"?${dirHint}`;
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
    if (data.dir_errors?.length) {
      alert("Đã xóa project, nhưng một số thư mục chưa gỡ được:\n" + data.dir_errors.join("\n"));
    }
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
  const project_dir = ($("project-dir")?.value || "").trim();
  if (!name) return;
  $("project-add").disabled = true;
  try {
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, project_dir }),
    });
    const data = await res.json();
    if (res.ok) {
      state.projects = state.projects.filter((p) => p.slug !== data.project.slug);
      state.projects.push(data.project);
      state.activeProject = data.project.slug;
      $("project-name").value = "";
      if ($("project-dir")) $("project-dir").value = "";
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
  backlog: "Backlog", in_progress: "Working", blocked: "Blocked", failed: "Failed",
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
  let liveLinks = [];
  if (t.project) {
    const basePrev = `${location.origin}/preview/${t.project}/`;
    liveLinks.push(`<a href="${basePrev}" target="_blank">Trang chủ</a>`);

    const pageMatch = (t.title + " " + (t.description || "")).match(/([a-z0-9_-]+\.html)/i);
    if (pageMatch && pageMatch[1] !== "index.html") {
      const pageFile = pageMatch[1];
      const pagePrev = `${location.origin}/preview/${t.project}/${pageFile}`;
      liveLinks.push(`<a href="${pagePrev}" target="_blank" style="color: #60a5fa; font-weight: 600;">🛍️ Live Page: ${pageFile}</a>`);
    } else if (t.project === "jtshop-clone") {
      const pagePrev = `${location.origin}/preview/${t.project}/product-detail.html`;
      liveLinks.push(`<a href="${pagePrev}" target="_blank" style="color: #60a5fa; font-weight: 600;">🛍️ Live: product-detail.html</a>`);
    }
  }

  $("modal-meta").innerHTML = [
    elapsed ? `Thời gian: <b>${elapsed}</b>` : null,
    `Assignee: <b>${t.assignee || "—"}</b>`,
    `Project: <b>${t.project}</b>`,
    t.parent_id ? `Parent: <b>${t.parent_id}</b>` : null,
    liveLinks.length ? `Live: ${liveLinks.join(" | ")}` : null,
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
  if (t.status === "blocked" || t.status === "failed") {
    const btn = document.createElement("button");
    btn.textContent = "↺ Chạy lại";
    btn.onclick = async () => { await fetch(`/api/tasks/${t.id}/rerun`, { method: "POST" }); openModal(t.id); };
    actions.appendChild(btn);
  } else if (!["done", "archived"].includes(t.status)) {
    const blockBtn = document.createElement("button");
    blockBtn.style.color = "#f87171";
    blockBtn.style.borderColor = "rgba(239, 68, 68, 0.4)";
    blockBtn.textContent = "🛑 Dừng task (Block)";
    blockBtn.onclick = async () => { await blockTask(t.id); };
    actions.appendChild(blockBtn);
  }

  // Nút Push Git cho Operator (chỉ hiển thị khi Task đã DONE và CÓ file chưa push)
  const isGitRepo = data.task?.git_info?.is_git_repo || t.git_info?.is_git_repo;
  const hasChanges = data.task?.git_info?.has_uncommitted_changes || t.git_info?.has_uncommitted_changes;

  if (t.status === "done" && isGitRepo && hasChanges) {
    const gitBtn = document.createElement("button");
    gitBtn.className = "btn-git-push has-pending";
    gitBtn.innerHTML = "🚀 Push Git (Có file mới)";
    gitBtn.title = "Có file code chưa commit/push lên Git";
    gitBtn.onclick = async (e) => {
      e.stopPropagation();
      const msg = prompt(`Nhập Git Commit Message (để trống = tự động):`, `feat: ${t.title}`);
      if (msg === null) return;
      gitBtn.disabled = true;
      gitBtn.textContent = "⏳ Đang push...";
      try {
        const res = await fetch(`/api/tasks/${t.id}/git-push`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: msg })
        });
        const resData = await res.json();
        if (res.ok) {
          alert(`✅ Git Commit & Push Thành Công!\nCommit: ${resData.commit}`);
        } else {
          alert(`ℹ️ Thông báo Git: ${resData.error || "Lỗi không xác định"}`);
        }
      } catch (err) {
        alert(`❌ Lỗi kết nối: ${err.message}`);
      } finally {
        openModal(t.id);
      }
    };
    actions.appendChild(gitBtn);
  }

  // Nút Hủy & Rollback Git về Blocked (Nếu DONE: chỉ hiện khi có file code chưa đồng bộ)
  const canRollback = !["archived", "blocked", "failed"].includes(t.status) && (t.status !== "done" || hasChanges);
  if (canRollback) {
    const rbBtn = document.createElement("button");
    rbBtn.className = "btn-rollback";
    rbBtn.textContent = "↩ Hủy & Rollback Git (Về Blocked)";
    rbBtn.title = "Hủy toàn bộ thay đổi code trên Git và chuyển trạng thái task về Blocked";
    rbBtn.onclick = async (e) => {
      e.stopPropagation();
      const ok = await customConfirm(
        "Hủy & Rollback Code",
        `Bạn có chắc chắn muốn HỦY toàn bộ thay đổi code trên Git và chuyển task "${t.id}" về trạng thái Blocked không?`,
        "Hủy code & Về Blocked"
      );
      if (!ok) return;
      rbBtn.disabled = true;
      rbBtn.textContent = "⏳ Đang rollback...";
      try {
        const res = await fetch(`/api/tasks/${t.id}/reject-rollback`, { method: "POST" });
        const resData = await res.json();
        if (!res.ok) {
          alert(`⚠️ Lỗi: ${resData.error || "Không thể rollback"}`);
        }
      } catch (err) {
        alert(`❌ Lỗi kết nối: ${err.message}`);
      } finally {
        openModal(t.id);
        if (typeof fetchBoard === "function") fetchBoard();
      }
    };
    actions.appendChild(rbBtn);
  }

  $("modal-desc").textContent = t.description || "(không có mô tả)";

  // Đồng bộ children từ API vào state (tránh modal trống nếu board state lệch)
  const apiSubs = Array.isArray(data.subtasks) ? data.subtasks : [];
  apiSubs.forEach((c) => state.tasks.set(c.id, c));

  const subtasksEl = $("modal-subtasks");
  if (subtasksEl) {
    const children = (apiSubs.length
      ? apiSubs
      : [...state.tasks.values()].filter((c) => c.parent_id === t.id)
    ).slice().sort((a, b) => String(a.id).localeCompare(String(b.id)));
    const work = children.filter((c) => c.type !== "bug");
    const bugs = children.filter((c) => c.type === "bug");

    const rowHtml = (list, kind) => list.map((sub, i) => {
      let agentName = sub.assignee || "stark";
      if (sub.status === "testing" && agentName !== "hawkeye") {
        agentName = "hawkeye";
      } else if (sub.status === "review" && agentName !== "jarvis" && agentName !== "pepper") {
        agentName = "pepper";
      }
      const info = AGENT_INFO[agentName.toLowerCase()] || { icon: "🤖" };
      const { statusText, subCls } = childStatusMeta(sub.status);
      const label = sub.id ? sub.id : (kind === "bug" ? `Bug #${i + 1}` : `Subtask #${i + 1}`);
      return `
        <div class="modal-subtask-card ${subCls}${kind === "bug" ? " is-bug" : ""}">
          <div class="subtask-info">
            <span class="subtask-id">${label}</span>
            <div class="subtask-item-title">${escapeHtml(sub.title)}</div>
          </div>
          <span class="subtask-agent"><span class="subtask-agent-icon">${info.icon}</span> <b>${escapeHtml(agentName)}</b></span>
          <span class="subtask-badge ${subCls}">${statusText}</span>
        </div>`;
    }).join("");

    if (work.length || bugs.length) {
      let body = "";
      if (work.length) {
        const completed = work.filter((c) => c.status === "done" || c.status === "testing" || c.status === "review").length;
        const pct = Math.round((completed / work.length) * 100);
        const hasOpenBugs = bugs.some((b) => b.status !== "done" && b.status !== "archived");
        const pStyle = getProgressStyle(pct, hasOpenBugs);
        body += `
          <div class="panel-title" style="margin-top: 16px;">Subtasks (${completed}/${work.length} hoàn tất — <span style="color: ${pStyle.color}">${pct}%</span>)</div>
          <div class="subtasks-progress" style="margin-bottom: 12px;">
            <div class="subtasks-fill" style="width: ${pct}%; background: ${pStyle.fill}"></div>
          </div>
          <div class="modal-subtasks-list">${rowHtml(work, "task")}</div>`;
      }
      if (bugs.length) {
        const open = bugs.filter((c) => c.status !== "done" && c.status !== "archived").length;
        body += `
          <div class="panel-title" style="margin-top: 16px;">Bugs (${open} mở / ${bugs.length})</div>
          <div class="modal-subtasks-list">${rowHtml(bugs, "bug")}</div>`;
      }
      subtasksEl.innerHTML = body;
      subtasksEl.classList.remove("hidden");
    } else {
      subtasksEl.innerHTML = `
        <div class="panel-title" style="margin-top: 16px;">Subtasks / Bugs</div>
        <div class="sidebar-hint" style="padding: 8px 0;">Task này chưa có subtask hay bug.</div>`;
      subtasksEl.classList.remove("hidden");
    }
  }

  $("modal-events").innerHTML = "";
  data.events.forEach((e) => $("modal-events").appendChild(renderEvent(e)));
  $("modal-backdrop").classList.remove("hidden");
  setupModalScroll();
  renderSidebar();
}

function formatEventMessage(msg) {
  if (!msg) return "";
  // Preview URL thiếu slash → thêm (tránh /preview/slug load Vite source sai)
  msg = String(msg).replace(
    /(https?:\/\/[^\s<>"']+\/preview\/[a-z0-9_-]+)(?![\w./#-])/gi,
    "$1/"
  );
  let s = escapeHtml(msg);
  
  // Artifact screenshot URLs -> inline images with nice frame
  s = s.replace(/(view_url|diff_view_url):\s*(https?:\/\/[^\s<]+)/gi, (_, _k, url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank" class="qa-shot-link">📸 View Screenshot</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);
  s = s.replace(/(https?:\/\/[^\s<]+\/artifacts\/[^\s<]+\.png)/gi, (url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank" class="qa-shot-link">📸 View Screenshot</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);

  // Live preview links (sau escape)
  s = s.replace(/(https?:\/\/[^\s<]+\/preview\/[a-z0-9_-]+\/?)/gi, (url) => {
    let href = url.endsWith("/") ? url : url + "/";
    return `<a href="${href}" target="_blank" rel="noopener">${url}</a>`;
  });

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

  // Model planner thật cho badge chat
  const jarvisAgent = (data.agents || []).find((a) => a.key === "jarvis");
  if (jarvisAgent?.model) state.plannerModel = jarvisAgent.model;
  else {
    const plannerToolId = roles.planner;
    const plannerTool = tools.find((t) => t.id === plannerToolId);
    if (plannerTool?.model) state.plannerModel = plannerTool.model;
  }

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

  const rootInput = $("projects-root-input");
  const rootEff = $("projects-root-effective");
  if (rootInput) {
    rootInput.value = data.projects_root_custom || "";
    rootInput.placeholder = data.projects_root || "D:\\…\\AI-Projects";
  }
  if (rootEff) {
    rootEff.innerHTML = `Đang dùng: <code>${escapeHtml(data.projects_root || "")}</code>`
      + (data.projects_root_custom ? "" : " (mặc định ngoài Orchestrator)");
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

$("projects-root-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const path = ($("projects-root-input")?.value || "").trim();
  const res = await fetch("/api/settings/projects-root", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const data = await res.json();
  if (!res.ok) {
    settingsMsg(data.error || "Lỗi lưu Projects root", false);
    return;
  }
  settingsMsg(`Đã lưu Projects root: ${data.projects_root}`, true);
  loadSettings();
});
$("projects-root-reset")?.addEventListener("click", async () => {
  const res = await fetch("/api/settings/projects-root", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: "" }),
  });
  const data = await res.json();
  if (!res.ok) {
    settingsMsg(data.error || "Lỗi", false);
    return;
  }
  if ($("projects-root-input")) $("projects-root-input").value = "";
  settingsMsg(`Reset về mặc định: ${data.projects_root}`, true);
  loadSettings();
});
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
  settingsMsg("Đang kết nối kiểm tra endpoint…", true);
  try {
    const res = await fetch("/api/settings/llm-tools", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: model, base_url, model, api_key }),
    });
    const data = await res.json();
    if (res.ok) {
      settingsMsg(`OK — Đã xác thực thành công & đã thêm ${data.tool.model}`, true);
      $("llm-model").value = "";
      $("llm-api-key").value = "";
      loadSettings();
    } else {
      settingsMsg(data.error || "Lỗi khi kiểm tra Model", false);
    }
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
    if (ev.type === "chat") {
      appendChatMessage(ev.message);
      notifyTab("chat");
    } else if (ev.type === "task_updated" || ev.type === "task_created") {
      if (ev.task) state.tasks.set(ev.task.id, ev.task);
      loadBoard();
      notifyTab("board");
      if (state.openTaskId === ev.task?.id) openModal(ev.task.id);
    } else if (ev.type === "event") {
      if (state.openTaskId === ev.event?.task_id) {
        $("modal-events")?.appendChild(renderEvent(ev.event));
      }
      loadBoard();
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
loadSettings();
connectWS();
startDurationTicker();
resizeChatInput();
setupModalScroll();

/* ---------- Modal Quick Scroll Controls ---------- */
function setupModalScroll() {
  const modalEl = $("modal");
  if (!modalEl) return;

  const toggleBtn = $("modal-scroll-toggle");
  if (toggleBtn) {
    toggleBtn.onclick = (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
      // If modal is scrolled down > 100px, scroll to top; else scroll to bottom
      if (modalEl.scrollTop > 100) {
        modalEl.scrollTo({ top: 0, behavior: "smooth" });
      } else {
        modalEl.scrollTo({ top: modalEl.scrollHeight, behavior: "smooth" });
      }
    };
  }

  const scrollToTop = (e) => {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    modalEl.scrollTo({ top: 0, behavior: "smooth" });
  };

  const scrollToBottom = (e) => {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    modalEl.scrollTo({ top: modalEl.scrollHeight, behavior: "smooth" });
  };

  const topHdr = $("modal-scroll-top-hdr");
  const btmHdr = $("modal-scroll-bottom-hdr");
  const topBtn = $("modal-scroll-top");
  const btmBtn = $("modal-scroll-bottom");

  if (topHdr) topHdr.onclick = scrollToTop;
  if (btmHdr) btmHdr.onclick = scrollToBottom;
  if (topBtn) topBtn.onclick = scrollToTop;
  if (btmBtn) btmBtn.onclick = scrollToBottom;
}

document.addEventListener("keydown", (e) => {
  const modalBackdrop = $("modal-backdrop");
  if (!modalBackdrop || modalBackdrop.classList.contains("hidden")) return;
  const tag = document.activeElement?.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea") return;

  const modalEl = $("modal");
  if (e.key === "Home") {
    e.preventDefault();
    modalEl?.scrollTo({ top: 0, behavior: "smooth" });
  } else if (e.key === "End") {
    e.preventDefault();
    modalEl?.scrollTo({ top: modalEl?.scrollHeight || 999999, behavior: "smooth" });
  }
});