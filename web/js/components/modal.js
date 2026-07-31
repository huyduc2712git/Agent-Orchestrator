/* Agent Orchestrator — Modals & Dialogs Component */

import { STATUS_LABEL, AGENT_INFO, getAgentIconHtml } from "../constants.js";
import { state, $, escapeHtml, taskElapsed, parseMeta, getLatestDoneTaskId, resolveAssignee } from "../state.js";
import { blockTask } from "../api.js";
import { childStatusMeta, getProgressStyle } from "./board.js";
import { renderSidebar } from "./sidebar.js";

export function customConfirm(title, message, okText = "Đồng ý", okBg = "") {
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

export function openNewProject(hint) {
  $("project-backdrop")?.classList.remove("hidden");
  const msg = $("project-msg");
  if (msg) {
    msg.textContent = hint || "";
    msg.className = "settings-msg " + (hint ? "ok" : "");
  }
  $("project-name")?.focus();
}

const AGENT_ROLE_TITLE = {
  conan: "Conan (Squad Lead / Orchestrator)",
  haibara: "Ai Haibara (Quality Reviewer)",
  kid: "Kaito Kid (Frontend Builder)",
  agasa: "Agasa (Backend Specialist)",
  heiji: "Heiji (Visual QA)",
  akai: "Shuichi Akai (Security Reviewer)",
  amuro: "Amuro (Penetration Tester)",
  system: "System",
  operator: "Operator",
};

function formatEventMessage(msg) {
  if (!msg) return "";
  msg = String(msg).replace(
    /(https?:\/\/[^\s<>"']+\/preview\/[a-z0-9_-]+)(?![\w./#-])/gi,
    "$1/"
  );
  let s = escapeHtml(msg);
  
  s = s.replace(/(view_url|diff_view_url):\s*(https?:\/\/[^\s<]+)/gi, (_, _k, url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank" class="qa-shot-link">📸 View Screenshot</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);
  s = s.replace(/(https?:\/\/[^\s<]+\/artifacts\/[^\s<]+\.png)/gi, (url) =>
    `<div class="qa-shot"><a href="${url}" target="_blank" class="qa-shot-link">📸 View Screenshot</a><img src="${url}" alt="screenshot" loading="lazy"/></div>`);

  s = s.replace(/(https?:\/\/[^\s<]+\/preview\/[a-z0-9_-]+\/?)/gi, (url) => {
    let href = url.endsWith("/") ? url : url + "/";
    return `<a href="${href}" target="_blank" rel="noopener">${url}</a>`;
  });

  s = s.replace(/^### (.+)$/gm, '<h4 class="event-h3">$1</h4>');
  s = s.replace(/^## (.+)$/gm, '<h3 class="event-h2">$1</h3>');
  s = s.replace(/^# (.+)$/gm, '<h2 class="event-h1">$1</h2>');

  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  s = s.replace(/`([^`]+)`/g, '<code class="event-inline-code">$1</code>');

  s = s.replace(/✅/g, '<span class="icon-pass">✅</span>');
  s = s.replace(/❌/g, '<span class="icon-fail">❌</span>');
  s = s.replace(/\bPASS\b/g, '<span class="badge-pass">PASS</span>');
  s = s.replace(/\bFAIL\b/g, '<span class="badge-fail">FAIL</span>');

  const lines = s.split("\n");
  let tableRows = [];
  let outLines = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith("|") && line.endsWith("|")) {
      if (line.includes("---")) continue;
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

function agentEventIcon(agentName, kind) {
  const ag = (agentName || "system").toLowerCase();
  const info = AGENT_INFO[ag] || { icon: "🤖", bg: "#1a2233", fg: "#60a5fa", border: "#2c3b59" };
  if (info.avatar) {
    return `<span class="event-icon avatar-img-wrap" style="background:${info.bg};border:1px solid ${info.border}"><img src="${info.avatar}" class="event-avatar-img" alt="${escapeHtml(ag)}"/></span>`;
  }
  return `<span class="event-icon" style="background:${info.bg};color:${info.fg};border:1px solid ${info.border}">${info.icon}</span>`;
}

export function renderEvent(e) {
  const agent = (e.agent || "system").toLowerCase();
  const label = AGENT_ROLE_TITLE[agent] || AGENT_LABEL[agent] || e.agent || "System";
  const div = document.createElement("div");
  div.className = `event kind-${e.kind} agent-event-${agent}`;

  const formattedTime = e.created_at ? new Date(e.created_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }) : "";
  const formattedBody = formatEventMessage(e.message);

  const isStructured = e.message && (
    e.message.includes("|") || 
    e.message.includes("##") || 
    e.message.includes("http") || 
    agent === "haibara" || agent === "akai" || agent === "amuro"
  );

  const bodyContent = isStructured
    ? `<div class="event-content-box">${formattedBody}</div>`
    : `<div class="event-body-text">${formattedBody}</div>`;

  div.innerHTML = `
    <div class="event-card">
      <div class="event-card-header">
        ${agentEventIcon(e.agent, e.kind)}
        <span class="event-agent-name">${escapeHtml(label)}</span>
        <span class="event-time">${escapeHtml(formattedTime)}</span>
      </div>
      ${bodyContent}
    </div>`;
  return div;
}

export function setupModalScroll() {
  const modalEl = $("modal-task-detail") || document.querySelector("#modal-backdrop .modal");
  if (!modalEl) return;
  modalEl.scrollTop = 0;

  const toggleBtn = $("modal-scroll-toggle");
  if (toggleBtn) {
    toggleBtn.onclick = (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
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

if (typeof document !== "undefined") {
  document.addEventListener("keydown", (e) => {
    const modalBackdrop = $("modal-backdrop");
    if (!modalBackdrop || modalBackdrop.classList.contains("hidden")) return;
    const tag = document.activeElement?.tagName?.toLowerCase();
    if (tag === "input" || tag === "textarea") return;

    const modalEl = $("modal-task-detail") || document.querySelector("#modal-backdrop .modal");
    if (e.key === "Home") {
      e.preventDefault();
      modalEl?.scrollTo({ top: 0, behavior: "smooth" });
    } else if (e.key === "End") {
      e.preventDefault();
      modalEl?.scrollTo({ top: modalEl?.scrollHeight || 999999, behavior: "smooth" });
    }
  });
}

export async function openModal(taskId) {
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

  const apiSubs = Array.isArray(data.subtasks) ? data.subtasks : [];
  apiSubs.forEach((c) => state.tasks.set(c.id, c));

  const createdBy = t.created_by || "conan";
  const createdIconHtml = getAgentIconHtml(createdBy.toLowerCase());
  const createdHtml = `${createdIconHtml} <b>${escapeHtml(createdBy)}</b>`;

  const workerName = resolveAssignee(t, apiSubs);
  const workerIconHtml = getAgentIconHtml(workerName.toLowerCase());
  const workerHtml = `${workerIconHtml} <b>${escapeHtml(workerName)}</b>`;

  $("modal-meta").innerHTML = [
    elapsed ? `Thời gian: <b>${elapsed}</b>` : null,
    `Giao bởi: ${createdHtml}`,
    `Thực hiện: ${workerHtml}`,
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

  const meta = parseMeta(t);
  const isLatestDone = t.status === "done" && t.id === getLatestDoneTaskId(t.project);
  const isMerged = meta.pr_status === "merged" || meta.merge === "Merged" || meta.merged === true || (t.status === "done" && !isLatestDone);

  const isGitRepo = data.task?.git_info?.is_git_repo || t.git_info?.is_git_repo;
  const hasChanges = data.task?.git_info?.has_uncommitted_changes || t.git_info?.has_uncommitted_changes;

  if (isMerged) {
    const mergedBadge = document.createElement("span");
    mergedBadge.style.display = "inline-flex";
    mergedBadge.style.alignItems = "center";
    mergedBadge.style.gap = "6px";
    mergedBadge.style.padding = "6px 12px";
    mergedBadge.style.borderRadius = "8px";
    mergedBadge.style.background = "rgba(52, 211, 153, 0.15)";
    mergedBadge.style.border = "1px solid rgba(52, 211, 153, 0.3)";
    mergedBadge.style.color = "#34d399";
    mergedBadge.style.fontSize = "0.82rem";
    mergedBadge.style.fontWeight = "600";
    mergedBadge.innerHTML = "✓ Đã Commit & Merge vào Git";
    actions.appendChild(mergedBadge);
  } else if (t.status === "done" && isGitRepo && hasChanges) {
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

  const canRollback = !isMerged && !["archived", "blocked", "failed"].includes(t.status) && (t.status !== "done" || hasChanges);
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
      }
    };
    actions.appendChild(rbBtn);
  }

  $("modal-desc").textContent = t.description || "(không có mô tả)";

  // apiSubs processed at top of openModal

  const subtasksEl = $("modal-subtasks");
  if (subtasksEl) {
    const children = (apiSubs.length
      ? apiSubs
      : [...state.tasks.values()].filter((c) => c.parent_id === t.id)
    ).slice().sort((a, b) => String(a.id).localeCompare(String(b.id)));
    const work = children.filter((c) => c.type !== "bug");
    const bugs = children.filter((c) => c.type === "bug");

    const rowHtml = (list, kind) => list.map((sub, i) => {
      let agentName = sub.assignee || "kid";
      if (sub.status === "testing" && agentName !== "heiji") {
        agentName = "heiji";
      } else if (sub.status === "review" && agentName !== "conan" && agentName !== "haibara") {
        agentName = "haibara";
      }
      const iconHtml = getAgentIconHtml(agentName.toLowerCase());
      const { statusText, subCls } = childStatusMeta(sub.status);
      const label = sub.id ? sub.id : (kind === "bug" ? `Bug #${i + 1}` : `Subtask #${i + 1}`);
      return `
        <div class="modal-subtask-card ${subCls}${kind === "bug" ? " is-bug" : ""}">
          <div class="subtask-info">
            <span class="subtask-id">${label}</span>
            <div class="subtask-item-title">${escapeHtml(sub.title)}</div>
          </div>
          <span class="subtask-agent"><span class="subtask-agent-icon">${iconHtml}</span> <b>${escapeHtml(agentName)}</b></span>
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
  $("modal-backdrop")?.classList.remove("hidden");
  setupModalScroll();
  renderSidebar();
}
