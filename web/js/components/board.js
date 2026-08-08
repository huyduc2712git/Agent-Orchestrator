/* Agent Orchestrator — Kanban Board Component */

import { COLUMNS, AGENT_INFO, getAgentIconHtml } from "../constants.js";
import { state, $, escapeHtml, taskElapsed, parseMeta, pillFor, cardTag } from "../state.js";
import { renderSidebar, updateFooterProject } from "./sidebar.js";
import { openModal } from "./modal.js";
import { blockTask } from "../api.js";

function fmtTaskTokens(n) {
  const v = Number(n) || 0;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (v >= 10_000) return `${(v / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return v.toLocaleString("en-US");
}

function tokenMetaHtml(t) {
  const u = t.token_usage || {};
  const total = u.total_tokens || 0;
  const prompt = u.prompt_tokens || 0;
  const completion = u.completion_tokens || 0;
  const title = `in ${prompt.toLocaleString("en-US")} · out ${completion.toLocaleString("en-US")} · Σ ${total.toLocaleString("en-US")} (task + sub/bug)`;
  return `<span class="mk-inline">Token</span><span class="mv dim token-usage" title="${escapeHtml(title)}">Σ ${fmtTaskTokens(total)}</span>`;
}

/** Skill pipeline (skip-security…) — hiện dưới hàng PR nếu có. */
function skillMetaHtml(t) {
  const tags = (t.tags || []).map((x) => String(x).toLowerCase());
  const pipeline = [];
  if (tags.includes("skip-security") || tags.includes("scope-ui")) {
    pipeline.push(`<span class="mv pass" title="Bỏ Akai Security + Amuro Pentest sau QA">skip-security</span>`);
  }
  if (tags.includes("force-security")) {
    pipeline.push(`<span class="mv warn" title="Bắt buộc Security + Pentest">force-security</span>`);
  }
  const skip = new Set([
    "skip-security", "scope-ui", "force-security", "deploy-prod", "db-migration",
    "security", "no-app-chat",
  ]);
  const workflow = tags.filter((x) => !skip.has(x)).slice(0, 4);
  const wfHtml = workflow
    .map((x) => `<span class="mv dim" title="Workflow skill">@${escapeHtml(x)}</span>`)
    .join(" ");
  if (!pipeline.length && !wfHtml) return "";
  return `<div class="meta-row"><span class="mk">Skill</span>${pipeline.join(" ")}${wfHtml ? " " + wfHtml : ""}</div>`;
}

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
          ${skillMetaHtml(t)}
          <div class="meta-row">
            <span class="mk">CI</span><span class="mv ${ciCls}">${escapeHtml(pr.ci)}</span>
            <span class="mk-inline">Review</span><span class="mv ${revCls}">${escapeHtml(pr.review)}</span>
          </div>
          <div class="meta-row"><span class="mk">Merge</span><span class="mv ${mergeCls}">${escapeHtml(mergeText)}</span>${tokenMetaHtml(t)}</div>
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
    ${skillMetaHtml(t)}
    <div class="meta-row"><span class="mk">CI</span><span class="mv ${ciCls}">${escapeHtml(ci)}</span><span class="mk-inline">Review</span><span class="mv ${revCls}">${escapeHtml(review)}</span></div>
    <div class="meta-row"><span class="mk">Merge</span><span class="mv ${mergeCls}">${escapeHtml(merge)}</span>${tokenMetaHtml(t)}</div>`;
}

export function childStatusMeta(status, assignee = "") {
  const agent = (assignee || "").toLowerCase();
  const isCritic = ["heiji", "akai", "amuro", "haibara"].includes(agent);
  let statusText = "Pending";
  let subCls = "sub-backlog";
  if (status === "in_progress") { statusText = "Running"; subCls = "sub-working"; }
  else if (status === "testing") {
    // Critic → QA; Kid/Agasa testing = xong bước → hiện Done (không map sang Heiji)
    statusText = isCritic ? "QA Testing" : "Done ✓";
    subCls = isCritic ? "sub-testing" : "sub-done";
  }
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

/** Trên card: Done / archived / builder đã xong bước → thu gọn. */
export function isChildCollapsedOnCard(c) {
  if (c.status === "done" || c.status === "archived") return true;
  if (c.status === "testing") {
    const a = (c.assignee || "").toLowerCase();
    return !["heiji", "akai", "amuro", "haibara"].includes(a);
  }
  return false;
}

export function subtasksFor(t) {
  const children = childrenOf(t.id);
  const work = children.filter((c) => c.type !== "bug");
  const bugs = children.filter((c) => c.type === "bug");
  if (!work.length && !bugs.length) return "";

  const renderRows = (list, kind) => list.map((sub, i) => {
    // Hiện đúng assignee — không map kid→heiji chỉ vì status=testing
    const agentName = sub.assignee || "kid";
    const iconHtml = getAgentIconHtml(agentName.toLowerCase());
    const { statusText, subCls } = childStatusMeta(sub.status, agentName);
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

  const doneSummary = (n, kind) => n <= 0 ? "" : `
      <div class="subtask-card-row sub-done-collapsed${kind === "bug" ? " is-bug" : ""}" title="Mở task để xem danh sách đầy đủ">
        <span class="subtask-dot"></span>
        <span class="subtask-title subtask-done-summary">${n} done — mở task để xem</span>
        <span class="subtask-badge sub-done">Done ✓</span>
      </div>`;

  let html = "";
  if (work.length) {
    // done, hoặc builder đã xong bước (testing) — critic testing vẫn là QA chưa xong
    const completed = work.filter(isChildCollapsedOnCard).length;
    const active = work.filter((c) => !isChildCollapsedOnCard(c));
    const percent = Math.round((completed / work.length) * 100);
    const hasOpenBugs = bugs.some((b) => !isChildCollapsedOnCard(b));
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
      <div class="subtasks-list">${renderRows(active, "task")}${doneSummary(completed, "task")}</div>
    </div>`;
  }
  if (bugs.length) {
    const open = bugs.filter((c) => !isChildCollapsedOnCard(c)).length;
    const active = bugs.filter((c) => !isChildCollapsedOnCard(c));
    const doneN = bugs.length - open;
    html += `
    <div class="task-card-subtasks task-card-bugs">
      <div class="subtasks-header">
        <span class="subtasks-label">BUGS (${open} / ${bugs.length})</span>
      </div>
      <div class="subtasks-list">${renderRows(active, "bug")}${doneSummary(doneN, "bug")}</div>
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
  const timeBadge = elapsed
    ? `<span class="task-card-time" data-task-id="${escapeHtml(t.id)}" title="Thời gian chạy">⏱ ${elapsed}</span>`
    : "";
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
    ${subtasksFor(t)}`;
  return card;
}

const ACTIVE_STATUS_RANK = {
  in_progress: 0,
  testing: 1,
  review: 2,
  blocked: 3,
  failed: 4,
  backlog: 5,
  done: 6,
};

function taskPath(t) {
  if (!t) return "";
  const meta = parseMeta(t);
  return meta.branch || (t.project_dir
    ? t.project_dir.replace(/^.*[\\/]projects[\\/]/, "demo/")
    : `demo/${t.project}`);
}

function pickFocusTask(parents) {
  const ranked = parents
    .filter((t) => ACTIVE_STATUS_RANK[t.status] !== undefined && t.status !== "done" && t.status !== "archived")
    .sort((a, b) => {
      const ra = ACTIVE_STATUS_RANK[a.status] ?? 99;
      const rb = ACTIVE_STATUS_RANK[b.status] ?? 99;
      if (ra !== rb) return ra - rb;
      const timeA = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const timeB = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return timeB - timeA;
    });
  return ranked[0] || null;
}

export function updateBoardFocus(parents = null) {
  const pathEl = $("board-focus-path");
  const taskEl = $("board-focus-task");
  const pillEl = $("board-focus-pill");
  if (!pathEl || !taskEl || !pillEl) return;

  if (!state.activeProject) {
    pathEl.textContent = "— chưa chọn project";
    taskEl.textContent = "";
    taskEl.hidden = true;
    pillEl.hidden = true;
    pillEl.innerHTML = "";
    pillEl.className = "board-focus-pill";
    return;
  }

  const list = parents || [...state.tasks.values()].filter(
    (t) => !t.parent_id && t.project === state.activeProject,
  );
  const focus = pickFocusTask(list);
  const path = focus ? taskPath(focus) : `demo/${state.activeProject}`;
  pathEl.textContent = path;

  if (focus) {
    taskEl.textContent = focus.title || focus.id || "";
    taskEl.hidden = !taskEl.textContent;
    const meta = parseMeta(focus);
    const pill = pillFor(focus, meta);
    pillEl.className = `board-focus-pill pill ${pill.cls}`;
    pillEl.innerHTML = `<span class="pill-dot"></span>${escapeHtml(pill.text)}`;
    pillEl.hidden = false;
  } else {
    taskEl.textContent = "Không có task đang chạy";
    taskEl.hidden = false;
    pillEl.className = "board-focus-pill pill pill-backlog";
    pillEl.innerHTML = `<span class="pill-dot"></span>Idle`;
    pillEl.hidden = false;
  }
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
  updateBoardFocus(parents);
  updateFooterProject();
  renderSidebar();
}
