/* Agent Orchestrator — Kanban Board Component */

import { COLUMNS, AGENT_INFO, getAgentIconHtml } from "../constants.js";
import { state, $, escapeHtml, taskElapsed, parseMeta, pillFor, cardTag } from "../state.js";
import { renderSidebar, updateFooterProject } from "./sidebar.js";
import { openModal } from "./modal.js";
import { blockTask } from "../api.js";

export function metaRows(t, meta, isLatestDone = false) {
  if (meta.stacked_prs && Array.isArray(meta.stacked_prs)) {
    return `<div class="stacked-prs">` + meta.stacked_prs.map(pr => {
      const ciCls = pr.ci === "Passing" ? "pass" : pr.ci === "Failing" ? "fail" : "dim";
      const revCls = pr.review === "Approved" ? "pass" : pr.review === "Changes requested" ? "warn" : "dim";
      const isMerged = pr.pr_status === "merged" || pr.merge === "Merged";
      const mergeText = pr.merge || (isMerged ? "Merged" : "Mergeable");
      const mergeCls = (mergeText === "Mergeable" || mergeText === "Merged") ? "pass" : "dim";
      return `
        <div class="stacked-pr-block">
          <div class="meta-row"><span class="mk">PR</span><span class="mv">${escapeHtml(pr.pr_num)} · ${escapeHtml(pr.pr_status)}</span></div>
          <div class="meta-row">
            <span class="mk">CI</span><span class="mv ${ciCls}">${escapeHtml(pr.ci)}</span>
            <span class="mk-inline">Review</span><span class="mv ${revCls}">${escapeHtml(pr.review)}</span>
          </div>
          <div class="meta-row"><span class="mk">Merge</span><span class="mv ${mergeCls}">${escapeHtml(mergeText)}</span></div>
        </div>`;
    }).join("") + `</div>`;
  }

  const isMerged = meta.pr_status === "merged" || meta.merge === "Merged" || meta.merged === true || (t.status === "done" && !isLatestDone && meta.pr_status !== "open");
  const prStatus = meta.pr_status || (isMerged ? "merged" : "open");

  let pr = meta.pr;
  if (!pr) {
    if (meta.pr_num) {
      pr = `${meta.pr_num} · ${prStatus}`;
    } else if (t.status === "in_progress" || t.status === "backlog") {
      pr = "no PR yet";
    } else {
      pr = `${t.id} · ${prStatus}`;
    }
  }
  
  let ci = meta.ci || (t.status === "done" ? "Passing" : (t.status === "blocked" || t.status === "failed") ? "Failing" : "Pending");
  let ciCls = ci === "Passing" ? "pass" : ci === "Failing" ? "fail" : "dim";

  let review = meta.review || (t.status === "done" ? "Approved" : (t.status === "blocked" || t.status === "failed") ? "Changes requested" : "None");
  let revCls = review === "Approved" ? "pass" : review === "Changes requested" ? "warn" : "dim";

  let merge = meta.merge;
  if (!merge) {
    if (isMerged) {
      merge = "Merged";
    } else if (t.status === "done") {
      merge = "Mergeable";
    } else if (t.status === "blocked" || t.status === "failed") {
      merge = "Restore Clear";
    } else if (t.status === "in_progress" || t.status === "backlog") {
      merge = "Pending";
    } else {
      merge = "Checking";
    }
  } else if (prStatus === "merged" && merge === "Mergeable") {
    merge = "Merged";
  }
  let mergeCls = (merge === "Mergeable" || merge === "Merged") ? "pass" : (merge === "Restore Clear" || merge === "Blocked") ? "warn" : "dim";

  return `
    <div class="meta-row"><span class="mk">PR</span><span class="mv">${escapeHtml(pr)}</span></div>
    <div class="meta-row"><span class="mk">CI</span><span class="mv ${ciCls}">${escapeHtml(ci)}</span><span class="mk-inline">Review</span><span class="mv ${revCls}">${escapeHtml(review)}</span></div>
    <div class="meta-row"><span class="mk">Merge</span><span class="mv ${mergeCls}">${escapeHtml(merge)}</span></div>`;
}

export function attentionFor(t, meta) {
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

export function childStatusMeta(status) {
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

export function getProgressStyle(percent, hasOpenBugs) {
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

export function childrenOf(parentId) {
  return [...state.tasks.values()]
    .filter((c) => c.parent_id === parentId)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
}

export function subtasksFor(t) {
  const children = childrenOf(t.id);
  const work = children.filter((c) => c.type !== "bug");
  const bugs = children.filter((c) => c.type === "bug");
  if (!work.length && !bugs.length) return "";

  const renderRows = (list, kind) => list.map((sub, i) => {
    let agentName = sub.assignee || "kid";
    const explicitCritics = ["akai", "amuro", "haibara", "heiji", "conan"];
    if (sub.status === "testing" && !explicitCritics.includes(agentName.toLowerCase())) {
      agentName = "heiji";
    } else if (sub.status === "review" && !explicitCritics.includes(agentName.toLowerCase())) {
      agentName = "haibara";
    }
    const iconHtml = getAgentIconHtml(agentName.toLowerCase());
    const { statusText, subCls } = childStatusMeta(sub.status);
    const step = sub.id || (kind === "bug" ? `bug-${i + 1}` : `#${i + 1}`);

    return `
      <div class="subtask-card-row ${subCls}${kind === "bug" ? " is-bug" : ""}">
        <span class="subtask-dot"></span>
        <span class="subtask-step">${escapeHtml(step)}</span>
        <span class="subtask-title" title="${escapeHtml(sub.title)}">${escapeHtml(sub.title)}</span>
        <span class="subtask-agent-tag"><span class="subtask-agent-icon">${iconHtml}</span> ${escapeHtml(agentName)}</span>
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
        <span class="subtasks-label">BUGS (${open} / ${bugs.length})</span>
      </div>
      <div class="subtasks-list">${renderRows(bugs, "bug")}</div>
    </div>`;
  }
  return html;
}

export function renderCard(t, isLatestDone = false) {
  const card = document.createElement("div");
  card.className = "task-card";
  card.onclick = () => openModal(t.id);
  const meta = parseMeta(t);
  const pill = pillFor(t, meta);
  const children = childrenOf(t.id);
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
        ${cardTag(t, children)}
        ${blockBtn}
      </div>
    </div>
    <div class="task-card-title">${escapeHtml(t.title)}</div>
    <div class="task-card-path">${escapeHtml(path)}</div>
    <div class="task-card-meta">${metaRows(t, meta, isLatestDone)}</div>
    ${subtasksFor(t)}
    ${attentionFor(t, meta)}`;
  return card;
}

export function renderBoard() {
  const board = $("board");
  if (!board) return;
  board.innerHTML = "";
  let parents = [...state.tasks.values()].filter((t) => !t.parent_id);
  if (state.activeProject) {
    parents = parents.filter((t) => t.project === state.activeProject);
  }

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
      tasks.forEach((t, idx) => {
        const isLatestDone = col.key === "done" && idx === 0;
        body.appendChild(renderCard(t, isLatestDone));
      });
    }
    colEl.appendChild(body);
    board.appendChild(colEl);
  }
  updateFooterProject();
  renderSidebar();
}
