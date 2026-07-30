/* Agent Orchestrator — Main Application Entry Point */

import { state, $, updateFooterProject } from "./state.js";
import { loadBoard, loadProjects, blockTask, selectProject } from "./api.js";
import { renderBoard } from "./components/board.js";
import { renderSidebar, switchView, goChat, notifyTab } from "./components/sidebar.js";
import { openModal, openNewProject, renderEvent } from "./components/modal.js";
import { loadChat, sendChatMessage, resizeChatInput, resetChatInputHeight, appendChatMessage, renderChatMessage, setThinking } from "./components/chat.js";

// Make key functions available globally for inline HTML events
window.blockTask = blockTask;
window.selectProject = selectProject;
window.switchView = switchView;
window.openModal = openModal;

function connectWS() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);
  ws.onopen = () => {
    const el = $("conn-status");
    if (el) { el.textContent = "● online"; el.className = "conn online"; }
  };
  ws.onclose = () => {
    const el = $("conn-status");
    if (el) { el.textContent = "● offline"; el.className = "conn offline"; }
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      const type = ev.type || ev.event;
      if (type === "chat" || type === "chat_message") {
        appendChatMessage(ev.message);
        notifyTab("chat");
      } else if (type === "task_updated" || type === "task_created" || type === "board_reload") {
        if (ev.task) state.tasks.set(ev.task.id, ev.task);
        loadBoard();
        notifyTab("board");
        if (state.openTaskId === ev.task?.id) openModal(ev.task.id);
      } else if (type === "event") {
        if (state.openTaskId === ev.event?.task_id) {
          $("modal-events")?.appendChild(renderEvent(ev.event));
        }
        loadBoard();
      } else if (type === "thinking") {
        setThinking(ev.on);
      }
    } catch (err) {
      console.error("WS error:", err);
    }
  };
}

function startDurationTicker() {
  setInterval(() => {
    const elapsedBadges = document.querySelectorAll(".task-card-time");
    elapsedBadges.forEach((el) => {
      // Re-render tick if needed
    });
  }, 10000);
}

function initEvents() {
  // Navigation
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  // Sidebar toggle
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

  // Quick Action Buttons
  $("btn-new-task-2")?.addEventListener("click", goChat);
  $("btn-orchestrator")?.addEventListener("click", goChat);
  $("btn-new-project")?.addEventListener("click", () => openNewProject());
  $("project-close")?.addEventListener("click", () => $("project-backdrop")?.classList.add("hidden"));
  $("project-backdrop")?.addEventListener("click", (e) => {
    if (e.target === $("project-backdrop")) $("project-backdrop").classList.add("hidden");
  });

  // Project Form
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
        $("project-backdrop")?.classList.add("hidden");
        updateFooterProject();
        renderBoard();
      } else {
        const msg = $("project-msg");
        if (msg) {
          msg.textContent = data.error || "Lỗi";
          msg.className = "settings-msg err";
        }
      }
    } finally {
      $("project-add").disabled = false;
    }
  });

  // Chat Form & Suggestions
  $("chat-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ta = $("chat-text");
    if (!ta) return;
    const text = ta.value.trim();
    await sendChatMessage(text);
  });

  $("chat-text")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("chat-form")?.requestSubmit();
    }
  });

  $("chat-text")?.addEventListener("input", resizeChatInput);

  document.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const ta = $("chat-text");
      if (ta) {
        ta.value = chip.dataset.prompt;
        resizeChatInput();
        ta.focus();
      }
    });
  });

  // Modal Close
  const modalCloseBtn = $("modal-close");
  if (modalCloseBtn) {
    modalCloseBtn.onclick = () => {
      $("modal-backdrop")?.classList.add("hidden");
      state.openTaskId = null;
      renderSidebar();
    };
  }
  $("modal-backdrop")?.addEventListener("click", (e) => {
    if (e.target === $("modal-backdrop")) $("modal-close")?.click();
  });
}

// Initial Boot
document.addEventListener("DOMContentLoaded", () => {
  initEvents();
  switchView("board");
  loadChat();
  loadBoard();
  connectWS();
  startDurationTicker();
  resizeChatInput();
});
