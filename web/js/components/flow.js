/* Agent Orchestrator — Workflow & Project Tree Canvas Component */

import { state, $, escapeHtml, formatTime } from "../state.js";
import { AGENT_INFO, getAgentAvatarHtml } from "../constants.js";
import { openModal } from "./modal.js";
import {
  formatMarkdownMessage,
  sendChatMessage,
  sendChatImage,
  skillPillHtml,
  splitUserMessageParts,
  userImageHtml,
  conanWorkStats,
  plannerModelLabel,
} from "./chat.js";

let canvasState = {
  mode: "flow", // "flow" (Live 6-Phase Pipeline) | "tree" (Project Task Dependency Tree)
  zoom: 1,
  panX: 40,
  panY: 40,
  isDragging: false,
  dragStartX: 0,
  dragStartY: 0,
  selectedNodeId: null,
};

export function initFlowCanvas() {
  initFlowChat();
  const container = $("flow-canvas-container");
  if (!container) return;

  // Pan / Drag events
  container.addEventListener("mousedown", (e) => {
    if (e.target.closest(".flow-node") || e.target.closest(".flow-toolbar")) return;
    canvasState.isDragging = true;
    canvasState.dragStartX = e.clientX - canvasState.panX;
    canvasState.dragStartY = e.clientY - canvasState.panY;
    container.style.cursor = "grabbing";
  });

  window.addEventListener("mousemove", (e) => {
    if (!canvasState.isDragging) return;
    canvasState.panX = e.clientX - canvasState.dragStartX;
    canvasState.panY = e.clientY - canvasState.dragStartY;
    applyTransform();
  });

  window.addEventListener("mouseup", () => {
    canvasState.isDragging = false;
    if (container) container.style.cursor = "grab";
  });

  // Zoom on wheel
  container.addEventListener("wheel", (e) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    const newZoom = Math.min(Math.max(canvasState.zoom * zoomFactor, 0.4), 2.2);
    
    // Zoom toward cursor
    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    canvasState.panX = mouseX - (mouseX - canvasState.panX) * (newZoom / canvasState.zoom);
    canvasState.panY = mouseY - (mouseY - canvasState.panY) * (newZoom / canvasState.zoom);
    canvasState.zoom = newZoom;
    applyTransform();
  }, { passive: false });

  // Mode buttons
  $("btn-flow-mode-live")?.addEventListener("click", () => setFlowMode("flow"));
  $("btn-flow-mode-tree")?.addEventListener("click", () => setFlowMode("tree"));

  // Zoom controls
  $("btn-flow-zoom-in")?.addEventListener("click", () => zoomCanvas(1.2));
  $("btn-flow-zoom-out")?.addEventListener("click", () => zoomCanvas(0.8));
  $("btn-flow-zoom-reset")?.addEventListener("click", () => resetZoom());
  $("btn-flow-fit")?.addEventListener("click", () => fitView());

  renderFlow();
}

export function setFlowMode(mode) {
  canvasState.mode = mode;
  $("btn-flow-mode-live")?.classList.toggle("active", mode === "flow");
  $("btn-flow-mode-tree")?.classList.toggle("active", mode === "tree");
  resetZoom();
  renderFlow();
}

function zoomCanvas(factor) {
  canvasState.zoom = Math.min(Math.max(canvasState.zoom * factor, 0.4), 2.2);
  applyTransform();
}

function resetZoom() {
  canvasState.zoom = 1;
  canvasState.panX = 40;
  canvasState.panY = 40;
  applyTransform();
}

function fitView() {
  canvasState.zoom = 0.85;
  canvasState.panX = 30;
  canvasState.panY = 60;
  applyTransform();
}

function applyTransform() {
  const content = $("flow-viewport");
  if (content) {
    content.style.transform = `translate(${canvasState.panX}px, ${canvasState.panY}px) scale(${canvasState.zoom})`;
  }
  const zoomDisplay = $("flow-zoom-level");
  if (zoomDisplay) {
    zoomDisplay.textContent = `${Math.round(canvasState.zoom * 100)}%`;
  }
}

/** Cập nhật lại toàn bộ Flow & Tree theo trạng thái mới nhất từ State/WebSocket */
export function renderFlow() {
  const viewport = $("flow-viewport");
  if (!viewport) return;

  if (canvasState.mode === "flow") {
    renderLiveOrchestrationFlow(viewport);
  } else {
    renderProjectTaskTree(viewport);
  }
  updateFlowMetrics();
}

function updateFlowMetrics() {
  const allTasks = [...state.tasks.values()];
  const currentProjTasks = state.activeProject 
    ? allTasks.filter(t => t.project === state.activeProject)
    : allTasks;

  const running = currentProjTasks.filter(t => ["in_progress", "testing", "review"].includes(t.status)).length;
  const done = currentProjTasks.filter(t => t.status === "done").length;
  const total = currentProjTasks.length;

  const activeAgents = new Set(
    currentProjTasks
      .filter(t => ["in_progress", "testing", "review"].includes(t.status) && t.assignee)
      .map(t => t.assignee.toLowerCase())
  );

  const statsPill = $("flow-stats-pill");
  if (statsPill) {
    statsPill.innerHTML = `
      <span class="metric-tag"><span class="dot-pulse"></span> Running: <strong>${running}</strong></span>
      <span class="metric-tag">✅ Done: <strong>${done}/${total}</strong></span>
      <span class="metric-tag">🤖 Active: <strong>${activeAgents.size}</strong></span>
    `;
  }
}

// -------------------------------------------------------------
// 1. LIVE 6-PHASE ORCHESTRATION PIPELINE (DAG GRAPH)
// -------------------------------------------------------------

function renderLiveOrchestrationFlow(container) {
  const allTasks = [...state.tasks.values()];
  const currentProjTasks = state.activeProject 
    ? allTasks.filter(t => t.project === state.activeProject)
    : allTasks;

  // Tính trạng thái realtime từng Agent
  const statusWeight = { in_progress: 4, testing: 3, review: 2, backlog: 1, done: 0, failed: -1 };

  const getAgentStatus = (agentName) => {
    const matched = currentProjTasks.filter(
      t => t.assignee?.toLowerCase() === agentName.toLowerCase() && 
           ["in_progress", "testing", "review"].includes(t.status)
    );
    if (matched.length > 0) {
      // Ưu tiên: in_progress > testing > review -> updated_at mới nhất -> created_at mới nhất -> ID lớn nhất
      matched.sort((a, b) => {
        const diffWeight = (statusWeight[b.status] || 0) - (statusWeight[a.status] || 0);
        if (diffWeight !== 0) return diffWeight;
        const timeA = a.updated_at || a.created_at || "";
        const timeB = b.updated_at || b.created_at || "";
        if (timeA && timeB && timeA !== timeB) return timeB.localeCompare(timeA);
        return String(b.id).localeCompare(String(a.id));
      });
      return { active: true, status: matched[0].status, task: matched[0], count: matched.length };
    }
    const hasDone = currentProjTasks.some(
      t => t.assignee?.toLowerCase() === agentName.toLowerCase() && t.status === "done"
    );
    return { active: false, status: hasDone ? "idle_done" : "idle", count: 0 };
  };

  const conanStat = getAgentStatus("conan");
  const kidStat = getAgentStatus("kid");
  const agasaStat = getAgentStatus("agasa");
  let heijiStat = getAgentStatus("heiji");
  let haibaraStat = getAgentStatus("haibara");
  const akaiStat = getAgentStatus("akai");
  const amuroStat = getAgentStatus("amuro");

  // Heiji cũng active khi có subtask SQA đang testing/in_progress
  if (!heijiStat.active) {
    const sqaTasks = currentProjTasks.filter(
      t => (t.id.startsWith("sqa-") || t.tags?.includes("qa")) && ["in_progress", "testing"].includes(t.status)
    );
    if (sqaTasks.length > 0) {
      sqaTasks.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
      heijiStat = { active: true, status: sqaTasks[0].status, task: sqaTasks[0], count: sqaTasks.length };
    }
  }

  // Haibara cũng active khi có task ở bước review
  if (!haibaraStat.active) {
    const reviewTasks = currentProjTasks.filter(
      t => t.status === "review" && t.assignee?.toLowerCase() !== "conan"
    );
    if (reviewTasks.length > 0) {
      reviewTasks.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
      haibaraStat = { active: true, status: "review", task: reviewTasks[0], count: reviewTasks.length };
    }
  }

  const hasAnyActive = [conanStat, kidStat, agasaStat, heijiStat, akaiStat, haibaraStat, amuroStat].some(s => s.active);

  // Conan Final Review active khi có parent task hoặc final task ở review
  const finalReviewTask = currentProjTasks.find(
    t => (t.status === "review" && (!t.parent_id || t.assignee === "conan" || t.title.toLowerCase().includes("final")))
  );
  const isFinalReviewActive = Boolean(finalReviewTask);

  // Định nghĩa tọa độ các Node trên Canvas (Layout tương tự hình mẫu)
  const nodes = [
    {
      id: "node-start",
      type: "start",
      title: "Start",
      sub: "Chat / Task Inbound",
      icon: "▶",
      x: 40,
      y: 220,
      w: 140,
      h: 56,
      active: true,
      accent: "#22c55e",
    },
    {
      id: "node-conan-plan",
      type: "agent",
      agent: "conan",
      title: "Conan Planner",
      sub: "6-Phase Engine",
      icon: "🕵️‍♂️",
      x: 230,
      y: 215,
      w: 190,
      h: 66,
      active: conanStat.active || state.thinking,
      status: conanStat.status,
      accent: "#60a5fa",
      currentTask: conanStat.task,
    },
    {
      id: "node-router",
      type: "decision",
      title: "Task Decision Router",
      sub: "Multi-Agent Workflow Classifier",
      icon: "🔀",
      x: 470,
      y: 150,
      w: 330,
      h: 195,
      active: kidStat.active || agasaStat.active || akaiStat.active,
      branches: [
        { label: "📱 Mobile / Web UI (Expo/React/Safe Area)", agent: "kid", active: kidStat.active },
        { label: "⚙️ Backend & Mobile APIs (FastAPI/Auth/Sync)", agent: "agasa", active: agasaStat.active },
        { label: "🛡️ Security & SecureStore Audit", agent: "akai", active: akaiStat.active || amuroStat.active },
      ],
    },
    // Worker nodes
    {
      id: "node-kid",
      type: "worker",
      agent: "kid",
      title: "Kaito Kid",
      sub: "Mobile & Web UI Specialist",
      icon: "🎩",
      x: 850,
      y: 60,
      w: 220,
      h: 70,
      active: kidStat.active,
      status: kidStat.status,
      accent: "#fb923c",
      currentTask: kidStat.task,
      count: kidStat.count,
    },
    {
      id: "node-agasa",
      type: "worker",
      agent: "agasa",
      title: "Dr. Agasa",
      sub: "Backend & Mobile APIs",
      icon: "🧪",
      x: 850,
      y: 165,
      w: 220,
      h: 70,
      active: agasaStat.active,
      status: agasaStat.status,
      accent: "#a78bfa",
      currentTask: agasaStat.task,
      count: agasaStat.count,
    },
    {
      id: "node-akai",
      type: "worker",
      agent: "akai",
      title: "Shuichi Akai / Amuro",
      sub: "Security & Storage Audit",
      icon: "🔫",
      x: 850,
      y: 270,
      w: 220,
      h: 70,
      active: akaiStat.active || amuroStat.active,
      status: akaiStat.status,
      accent: "#93c5fd",
      currentTask: akaiStat.task || amuroStat.task,
      count: (akaiStat.count || 0) + (amuroStat.count || 0),
    },
    // Quality & Critic stage
    {
      id: "node-heiji",
      type: "critic",
      agent: "heiji",
      title: "Heiji Hattori",
      sub: "Visual QA & Mobile Emulation",
      icon: "🔍",
      x: 1120,
      y: 60,
      w: 220,
      h: 70,
      active: heijiStat.active,
      status: heijiStat.status,
      accent: "#4ade80",
      currentTask: heijiStat.task,
      count: heijiStat.count,
    },
    {
      id: "node-haibara",
      type: "critic",
      agent: "haibara",
      title: "Ai Haibara",
      sub: "Quality & Acceptance Review",
      icon: "💊",
      x: 1120,
      y: 195,
      w: 220,
      h: 70,
      active: haibaraStat.active,
      status: haibaraStat.status,
      accent: "#f472b6",
      currentTask: haibaraStat.task,
      count: haibaraStat.count,
    },
    // Final review
    {
      id: "node-final-review",
      type: "review",
      agent: "conan",
      title: "Conan Final Review",
      sub: "Deliverable Acceptance",
      icon: "⚖️",
      x: 1390,
      y: 130,
      w: 200,
      h: 70,
      active: isFinalReviewActive,
      accent: "#60a5fa",
      currentTask: finalReviewTask,
    },
    {
      id: "node-end",
      type: "end",
      title: "Complete",
      sub: "Memory & Board Saved",
      icon: "🏁",
      x: 1640,
      y: 135,
      w: 150,
      h: 60,
      active: true,
      accent: "#22c55e",
    },
  ];

  // Định nghĩa các đường nối (Connections / Edges)
  const edges = [
    { from: "node-start", to: "node-conan-plan", active: true },
    { from: "node-conan-plan", to: "node-router", active: conanStat.active || hasAnyActive },
    { from: "node-router", to: "node-kid", branchIndex: 0, active: kidStat.active },
    { from: "node-router", to: "node-agasa", branchIndex: 1, active: agasaStat.active },
    { from: "node-router", to: "node-akai", branchIndex: 2, active: akaiStat.active || amuroStat.active },
    { from: "node-kid", to: "node-heiji", active: heijiStat.active || kidStat.active },
    { from: "node-agasa", to: "node-haibara", dstOffset: 24, active: agasaStat.active || haibaraStat.active },
    { from: "node-akai", to: "node-haibara", dstOffset: 48, active: akaiStat.active || amuroStat.active || haibaraStat.active },
    { from: "node-heiji", to: "node-final-review", dstOffset: 24, active: heijiStat.active },
    { from: "node-haibara", to: "node-final-review", dstOffset: 48, active: haibaraStat.active },
    { from: "node-final-review", to: "node-end", active: true },
  ];

  // Render SVG Connections Layer
  let svgPaths = "";
  edges.forEach((edge, idx) => {
    const src = nodes.find(n => n.id === edge.from);
    const dst = nodes.find(n => n.id === edge.to);
    if (!src || !dst) return;

    let x1 = src.x + src.w;
    let y1 = src.y + (src.h / 2);
    if (src.type === "decision" && edge.branchIndex !== undefined) {
      x1 = src.x + src.w - 18;
      y1 = src.y + 64 + (edge.branchIndex * 36);
    }
    const x2 = dst.x;
    const y2 = edge.dstOffset !== undefined ? dst.y + edge.dstOffset : dst.y + (dst.h / 2);

    const dx = Math.max(Math.abs(x2 - x1) * 0.5, 40);
    const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

    const activeClass = edge.active ? "flow-edge-active" : "flow-edge-idle";

    svgPaths += `
      <g class="flow-edge-group">
        <path d="${d}" class="flow-edge-bg" />
        <path d="${d}" class="flow-edge-main ${activeClass}" />
        ${edge.active ? `
          <circle r="4" fill="#60a5fa" filter="drop-shadow(0 0 6px #3b82f6)">
            <animateMotion dur="2.4s" repeatCount="indefinite" path="${d}" />
          </circle>
          <circle r="3" fill="#a78bfa" filter="drop-shadow(0 0 4px #8b5cf6)">
            <animateMotion dur="2.4s" begin="1.2s" repeatCount="indefinite" path="${d}" />
          </circle>
        ` : ""}
      </g>
    `;
  });

  // Render HTML Nodes Layer
  let nodesHtml = "";
  nodes.forEach(node => {
    const isActive = node.active;
    const activeCls = isActive ? "node-active" : "";

    if (node.type === "decision") {
      nodesHtml += `
        <div class="flow-node flow-node-decision ${activeCls}" id="${node.id}" style="left:${node.x}px; top:${node.y}px; width:${node.w}px;">
          <div class="decision-header">
            <span class="decision-icon">${node.icon}</span>
            <span class="decision-title">${escapeHtml(node.title)}</span>
          </div>
          <div class="decision-body">
            ${node.branches.map((b, i) => `
              <div class="decision-branch ${b.active ? "branch-active" : ""}">
                <span class="branch-dot"></span>
                <span class="branch-label">${escapeHtml(b.label)}</span>
                <span class="branch-port">●</span>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    } else {
      const avatarHtml = node.agent 
        ? getAgentAvatarHtml(node.agent, "flow-avatar") 
        : `<span class="flow-badge-icon" style="background:${node.accent || '#334155'}">${node.icon}</span>`;

      const extraCount = node.count && node.count > 1 ? `<span class="node-badge-extra">+${node.count - 1}</span>` : "";
      const statusBadge = node.currentTask 
        ? `<div class="node-live-task ${node.currentTask.status === 'in_progress' ? 'pulse-running' : ''}" onclick="window.openModal('${node.currentTask.id}')" title="${escapeHtml(node.currentTask.title)} (${node.currentTask.status})">
             <span class="pulse-dot"></span> ${node.currentTask.id} ${extraCount}
           </div>`
        : "";

      nodesHtml += `
        <div class="flow-node flow-node-standard ${activeCls}" id="${node.id}" style="left:${node.x}px; top:${node.y}px; width:${node.w}px; min-height:${node.h}px;">
          <div class="flow-node-content">
            ${avatarHtml}
            <div class="flow-node-info">
              <div class="flow-node-title">${escapeHtml(node.title)}</div>
              <div class="flow-node-sub">${escapeHtml(node.sub)}</div>
            </div>
          </div>
          ${statusBadge}
        </div>
      `;
    }
  });

  container.innerHTML = `
    <svg class="flow-svg-layer" width="2000" height="800">
      <defs>
        <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>
      ${svgPaths}
    </svg>
    <div class="flow-nodes-layer">
      ${nodesHtml}
    </div>
  `;
}

// -------------------------------------------------------------
// 2. PROJECT TASK DEPENDENCY TREE (DAG TREE)
// -------------------------------------------------------------

function renderProjectTaskTree(container) {
  const allTasks = [...state.tasks.values()];
  const currentProjTasks = state.activeProject 
    ? allTasks.filter(t => t.project === state.activeProject)
    : allTasks;

  if (!currentProjTasks.length) {
    container.innerHTML = `
      <div class="flow-empty-state">
        <div class="flow-empty-icon">🌳</div>
        <h3>Project chưa có Task</h3>
        <p>Gửi yêu cầu trong Chat để Conan tạo cây Task và điều phối các Agent thực hiện.</p>
      </div>
    `;
    return;
  }

  // Tách Task cha (Parent tasks) và Subtasks
  const parents = currentProjTasks.filter(t => !t.parent_id);
  const subtasksMap = new Map();
  currentProjTasks.filter(t => t.parent_id).forEach(sub => {
    if (!subtasksMap.has(sub.parent_id)) subtasksMap.set(sub.parent_id, []);
    subtasksMap.get(sub.parent_id).push(sub);
  });

  let nodes = [];
  let edges = [];

  let currentY = 40;
  parents.forEach(p => {
    const parentNode = {
      id: `task-${p.id}`,
      taskId: p.id,
      title: p.title,
      type: "parent",
      status: p.status,
      assignee: p.assignee || "conan",
      x: 60,
      y: currentY,
      w: 240,
      h: 80,
    };
    nodes.push(parentNode);

    const subs = subtasksMap.get(p.id) || [];
    let subY = currentY;

    if (subs.length === 0) {
      currentY += 120;
    } else {
      subs.forEach((sub, subIdx) => {
        const subNode = {
          id: `task-${sub.id}`,
          taskId: sub.id,
          title: sub.title,
          type: "subtask",
          status: sub.status,
          assignee: sub.assignee || "kid",
          severity: sub.severity,
          x: 360,
          y: subY,
          w: 260,
          h: 75,
        };
        nodes.push(subNode);

        edges.push({
          from: parentNode.id,
          to: subNode.id,
          active: ["in_progress", "testing", "review"].includes(sub.status),
        });

        subY += 95;
      });
      currentY = Math.max(currentY + 120, subY + 30);
    }
  });

  // Render SVG Edges
  let svgPaths = "";
  edges.forEach((edge, idx) => {
    const src = nodes.find(n => n.id === edge.from);
    const dst = nodes.find(n => n.id === edge.to);
    if (!src || !dst) return;

    const x1 = src.x + src.w;
    const y1 = src.y + (src.h / 2);
    const x2 = dst.x;
    const y2 = dst.y + (dst.h / 2);

    const dx = Math.max(Math.abs(x2 - x1) * 0.5, 40);
    const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    const activeClass = edge.active ? "flow-edge-active" : "flow-edge-idle";

    svgPaths += `
      <g class="flow-edge-group">
        <path d="${d}" class="flow-edge-bg" />
        <path d="${d}" class="flow-edge-main ${activeClass}" />
        ${edge.active ? `
          <circle r="4" fill="#38bdf8">
            <animateMotion dur="2s" repeatCount="indefinite" path="${d}" />
          </circle>
        ` : ""}
      </g>
    `;
  });

  // Render Tree Task Cards
  let nodesHtml = "";
  nodes.forEach(node => {
    const statusCls = `status-${node.status || "backlog"}`;
    const avatar = getAgentAvatarHtml(node.assignee, "tree-avatar");

    nodesHtml += `
      <div class="flow-node flow-tree-card ${statusCls}" id="${node.id}" style="left:${node.x}px; top:${node.y}px; width:${node.w}px;" onclick="window.openModal('${node.taskId}')">
        <div class="tree-card-top">
          <span class="tree-card-id">${node.taskId}</span>
          <span class="tree-status-badge ${statusCls}">${node.status}</span>
        </div>
        <div class="tree-card-title">${escapeHtml(node.title)}</div>
        <div class="tree-card-footer">
          <div class="tree-card-assignee">${avatar} <span>${escapeHtml(node.assignee)}</span></div>
        </div>
      </div>
    `;
  });

  container.innerHTML = `
    <svg class="flow-svg-layer" width="1600" height="${Math.max(currentY + 100, 800)}">
      ${svgPaths}
    </svg>
    <div class="flow-nodes-layer">
      ${nodesHtml}
    </div>
  `;
}

/** Cuộn mượt hoặc tức thì xuống tin nhắn mới nhất trong Mini Chat */
export function scrollFlowChatToBottom(smooth = false) {
  const box = $("flow-chat-messages");
  if (!box) return;
  const doScroll = () => {
    box.scrollTo({
      top: box.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  };
  doScroll();
  requestAnimationFrame(doScroll);
  setTimeout(doScroll, 80);
  setTimeout(doScroll, 320); // Đảm bảo cuộn tới đáy sau khi transition hoàn tất
}

/** Khởi tạo các sự kiện cho khung Chat Mini bên cạnh Canvas */
export function initFlowChat() {
  const miniChat = $("flow-mini-chat");
  const toggleBtn = $("btn-flow-toggle-chat");
  const closeBtn = $("btn-mini-chat-close");
  const form = $("flow-chat-form");
  const input = $("flow-chat-input");
  const attachBtn = $("flow-chat-attach");
  const fileInput = $("flow-chat-file-input");

  const setChatOpen = (open) => {
    if (!miniChat) return;
    miniChat.classList.toggle("collapsed", !open);
    toggleBtn?.classList.toggle("is-active", open);
    try {
      localStorage.setItem("flow-mini-chat-open", open ? "true" : "false");
    } catch (_) {}
    if (open) {
      scrollFlowChatToBottom(false);
    }
  };

  // Mặc định mở khung chat trên màn hình lớn
  let savedState = null;
  try {
    savedState = localStorage.getItem("flow-mini-chat-open");
  } catch (_) {}
  setChatOpen(savedState !== "false");

  toggleBtn?.addEventListener("click", () => {
    const isCurrentlyCollapsed = miniChat?.classList.contains("collapsed");
    setChatOpen(isCurrentlyCollapsed);
  });

  closeBtn?.addEventListener("click", () => {
    setChatOpen(false);
  });

  // Submit gửi tin nhắn cho Conan
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = (input?.value || "").trim();
    if (!text) return;
    input.value = "";
    await sendChatMessage(text);
    renderFlowChat();
  });

  // Đính kèm ảnh cho Vision
  attachBtn?.addEventListener("click", () => fileInput?.click());
  fileInput?.addEventListener("change", async () => {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      alert("Chỉ chọn file ảnh (png/jpg/webp/gif).");
      return;
    }
    const text = (input?.value || "").trim();
    if (input) input.value = "";
    await sendChatImage(file, text);
    renderFlowChat();
  });

  renderFlowChat();
  scrollFlowChatToBottom(false);
}

/** Render đồng bộ danh sách tin nhắn realtime trong Mini Chat */
export function renderFlowChat() {
  const box = $("flow-chat-messages");
  if (!box) return;

  if (!state.chatMessages || state.chatMessages.length === 0) {
    box.innerHTML = `
      <div class="mini-chat-empty">
        <span class="empty-icon">💬</span>
        <p>Trò chuyện hoặc giao task cho <strong>Conan</strong> tại đây.</p>
        <span class="empty-hint">Sơ đồ workflow bên phải sẽ cập nhật realtime theo từng chỉ đạo của bạn!</span>
      </div>
    `;
    return;
  }

  let html = "";
  state.chatMessages.forEach((m, index) => {
    if (!m || !m.message || !m.message.trim()) return;
    const timeStr = formatTime(m.created_at);

    if (m.role === "system") {
      const work = conanWorkStats(state.chatMessages, index);
      html += `
        <div class="msg-row system-msg">
          ${getAgentAvatarHtml("system")}
          <div class="msg-conan-wrapper">
            <div class="msg-meta-conan">
              <span class="name" style="color: #eab308;">System / Board Patrol</span>
              ${timeStr ? `<span class="dot">•</span><span class="time">${escapeHtml(timeStr)}</span>` : ""}
              ${work ? `<span class="worked-badge">${escapeHtml(work.label)}</span>` : ""}
              <span class="system-badge">System Notification</span>
            </div>
            <div class="msg-bubble system-bubble">${formatMarkdownMessage(m.message)}</div>
          </div>
        </div>
      `;
      return;
    }

    const isUser = m.role === "user";
    if (isUser) {
      const { body, tags, images } = splitUserMessageParts(m.message);
      const topParts = [];
      if (images.length) {
        topParts.push(`<div class="msg-user-media">${images.map(userImageHtml).join("")}</div>`);
      }
      if (tags.length) {
        topParts.push(`<div class="msg-skill-row">${tags.map((t) => skillPillHtml(t)).join("")}</div>`);
      }
      const topHtml = topParts.length ? `<div class="msg-user-top">${topParts.join("")}</div>` : "";
      const textHtml = body ? `<div class="msg-user-text">${formatMarkdownMessage(body)}</div>` : "";
      if (!topHtml && !textHtml) return;

      html += `
        <div class="msg-row user">
          <div class="msg-user-wrapper">
            <div class="msg-meta-user">
              ${timeStr ? `<span class="time">${escapeHtml(timeStr)}</span><span class="dot">•</span>` : ""}
              <span class="name">Bạn</span>
            </div>
            <div class="msg-bubble user-bubble">
              ${topHtml}
              ${textHtml}
            </div>
          </div>
          ${getAgentAvatarHtml("user")}
        </div>
      `;
    } else {
      const work = conanWorkStats(state.chatMessages, index);
      html += `
        <div class="msg-row conan">
          ${getAgentAvatarHtml("conan")}
          <div class="msg-conan-wrapper">
            <div class="msg-meta-conan">
              <span class="name">Conan</span>
              ${timeStr ? `<span class="dot">•</span><span class="time">${escapeHtml(timeStr)}</span>` : ""}
              <span class="model-badge">${escapeHtml(plannerModelLabel())}</span>
              ${work ? `<span class="worked-badge">${escapeHtml(work.label)}</span>` : ""}
            </div>
            <div class="msg-bubble conan-bubble">${formatMarkdownMessage(m.message)}</div>
          </div>
        </div>
      `;
    }
  });

  if (state.thinking) {
    html += `
      <div class="msg-row conan thinking" id="flow-thinking-row">
        ${getAgentAvatarHtml("conan")}
        <div class="msg-bubble thinking-bubble" aria-live="polite" aria-label="Conan đang suy nghĩ">
          <span class="thinking-text">Conan đang suy nghĩ</span><span class="thinking-ellipsis" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
        </div>
      </div>
    `;
  }

  box.innerHTML = html;
  scrollFlowChatToBottom(false);
}
