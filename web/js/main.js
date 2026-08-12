/* Agent Orchestrator — Main Application Entry Point */

import { state, $, updateFooterProject, taskElapsed } from "./state.js";
import { playTing, toggleSound, isSoundEnabled } from "./sound.js";
import { loadBoard, loadProjects, blockTask, selectProject } from "./api.js";
import { renderBoard } from "./components/board.js";
import { renderSidebar, switchView, goChat, notifyTab } from "./components/sidebar.js";
import { openModal, openNewProject, setProjectCreateMode, renderEvent, shouldShowEvent } from "./components/modal.js";
import { loadChat, sendChatMessage, resizeChatInput, resetChatInputHeight, appendChatMessage, renderChatMessage, setThinking, initChatImageAttach, handleChatMentionKeydown, loadSkillMentions } from "./components/chat.js";
import { initSettingsEvents, openSettingsModal } from "./components/settings.js";
import { initFlowCanvas, renderFlow } from "./components/flow.js";

// Make key functions available globally for inline HTML events
window.blockTask = blockTask;
window.selectProject = selectProject;
window.switchView = switchView;
window.openModal = openModal;
window.openSettingsModal = openSettingsModal;
window.playTing = playTing;
window.toggleSound = toggleSound;
window.renderFlow = renderFlow;

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
        // Ting khi có thông báo hoàn thành hoặc bot báo xong
        const text = ev.message?.text || "";
        if (text.includes("✅") || text.includes("hoàn thành") || text.includes("đã xong") || text.includes("PASS")) {
          playTing("chat_complete");
        }
      } else if (type === "task_updated" || type === "task_created" || type === "board_reload") {
        if (ev.task) {
          const prev = state.tasks.get(ev.task.id);
          // Phát ting khi subtask hoặc task cha hoàn thành (status chuyển sang done hoặc testing hoàn tất bước)
          if (prev && prev.status !== ev.task.status) {
            if (ev.task.status === "done" || (ev.task.parent_id && (ev.task.status === "done" || ev.task.status === "testing"))) {
              playTing("task_complete");
            }
          } else if (!prev && ev.task.status === "done") {
            playTing("task_done");
          }
          state.tasks.set(ev.task.id, ev.task);
        }
        loadBoard();
        renderFlow();
        notifyTab("board");
        if (state.openTaskId === ev.task?.id) openModal(ev.task.id);
      } else if (type === "event") {
        if (state.openTaskId === ev.event?.task_id && shouldShowEvent(ev.event)) {
          const node = renderEvent(ev.event);
          if (node) $("modal-events")?.appendChild(node);
        }
        const evText = ev.event?.text || "";
        if (ev.event?.kind === "status" && (evText.includes("done") || evText.includes("PASS") || evText.includes("hoàn thành"))) {
          playTing("event_complete");
        }
        loadBoard();
        renderFlow();
      } else if (type === "thinking") {
        setThinking(ev.on);
        renderFlow();
      }
    } catch (err) {
      console.error("WS error:", err);
    }
  };
}

function startDurationTicker() {
  setInterval(() => {
    document.querySelectorAll(".task-card-time[data-task-id]").forEach((el) => {
      const t = state.tasks.get(el.dataset.taskId);
      if (!t) return;
      if (!["in_progress", "testing", "review"].includes(t.status)) return;
      const elapsed = taskElapsed(t);
      if (elapsed) el.textContent = `⏱ ${elapsed}`;
    });
  }, 15000);
}

function initEvents() {
  initSettingsEvents();
  // Navigation
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  // Sidebar toggle — logo/brand hoặc nút chevron
  const brandToggleBtn = $("brand-toggle-btn") || document.querySelector(".sidebar-brand");
  const sidebarToggleBtn = $("sidebar-toggle-btn");
  const applySidebarCollapsed = (collapsed) => {
    document.body.classList.toggle("sidebar-collapsed", !!collapsed);
    localStorage.setItem("sidebar-collapsed", collapsed ? "true" : "false");
    const tip = collapsed ? "Nhấp để mở Sidebar" : "Nhấp để đóng Sidebar";
    if (brandToggleBtn) {
      brandToggleBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      brandToggleBtn.title = tip;
    }
    if (sidebarToggleBtn) {
      sidebarToggleBtn.title = tip;
      sidebarToggleBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
    try { renderSidebar(); } catch (_) { /* ignore */ }
  };
  const onToggleSidebar = (e) => {
    e.preventDefault();
    e.stopPropagation();
    applySidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  };
  if (brandToggleBtn) {
    brandToggleBtn.setAttribute("role", "button");
    brandToggleBtn.setAttribute("tabindex", "0");
    brandToggleBtn.addEventListener("click", onToggleSidebar);
    brandToggleBtn.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      onToggleSidebar(e);
    });
  }
  // Nút chevron: đừng bubble lên brand (tránh double-toggle nếu sau này gắn listener khác)
  sidebarToggleBtn?.addEventListener("click", onToggleSidebar);

  const stored = localStorage.getItem("sidebar-collapsed");
  if (stored === "true" || (stored == null && window.innerWidth <= 768)) {
    applySidebarCollapsed(true);
  } else {
    applySidebarCollapsed(false);
  }

  // Quick Action Buttons
  $("btn-new-task-2")?.addEventListener("click", goChat);
  $("btn-orchestrator")?.addEventListener("click", goChat);
  $("bell-btn")?.addEventListener("click", () => toggleSound());
  $("btn-new-project")?.addEventListener("click", () => openNewProject());
  $("project-close")?.addEventListener("click", () => $("project-backdrop")?.classList.add("hidden"));
  $("project-backdrop")?.addEventListener("click", (e) => {
    if (e.target === $("project-backdrop")) $("project-backdrop").classList.add("hidden");
  });
  document.querySelectorAll(".project-mode-tab").forEach((btn) => {
    btn.addEventListener("click", () => setProjectCreateMode(btn.dataset.mode || "folder"));
  });

  // Project Form — folder mới hoặc git clone
  $("project-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const isGit = $("project-mode-git")?.classList.contains("active");
    const msg = $("project-msg");
    let payload;
    if (isGit) {
      const git_url = ($("project-git-url")?.value || "").trim();
      if (!git_url) {
        if (msg) { msg.textContent = "Nhập Git URL (GitHub/GitLab)."; msg.className = "settings-msg err"; }
        return;
      }
      payload = {
        git_url,
        name: ($("project-git-name")?.value || "").trim(),
        project_dir: ($("project-git-dir")?.value || "").trim(),
      };
    } else {
      const name = ($("project-name")?.value || "").trim();
      if (!name) return;
      payload = {
        name,
        project_dir: ($("project-dir")?.value || "").trim(),
      };
    }
    $("project-add").disabled = true;
    if (msg) {
      msg.textContent = isGit ? "Đang clone repo…" : "Đang tạo…";
      msg.className = "settings-msg ok";
    }
    try {
      const res = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        state.projects = state.projects.filter((p) => p.slug !== data.project.slug);
        state.projects.push(data.project);
        state.activeProject = data.project.slug;
        ["project-name", "project-dir", "project-git-url", "project-git-name", "project-git-dir"].forEach((id) => {
          if ($(id)) $(id).value = "";
        });
        $("project-backdrop")?.classList.add("hidden");
        updateFooterProject();
        renderSidebar();
        renderBoard();
      } else if (msg) {
        msg.textContent = data.error || "Lỗi";
        msg.className = "settings-msg err";
      }
    } catch (err) {
      if (msg) {
        msg.textContent = String(err);
        msg.className = "settings-msg err";
      }
    } finally {
      $("project-add").disabled = false;
    }
  });

  // Chat Form & Suggestions — text và/hoặc ảnh đã đính trong composer
  $("chat-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ta = $("chat-text");
    if (!ta) return;
    await sendChatMessage(ta.value);
  });

  $("chat-text")?.addEventListener("keydown", (e) => {
    if (handleChatMentionKeydown(e)) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // Chỉ gửi khi có nội dung (skill gắn qua @ không tính là tin)
      if (!(e.target?.value || "").trim()) return;
      $("chat-form")?.requestSubmit();
    }
  }, true);

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
let _booted = false;
function boot() {
  if (_booted) return;
  _booted = true;
  try {
    initEvents();
    initChatImageAttach();
    initFlowCanvas();
    switchView("board");
    // Projects độc lập với board — tránh sidebar trống khi /api/board chậm/treo
    loadProjects();
    loadChat();
    loadSkillMentions();
    loadBoard();
    connectWS();
    startDurationTicker();
    resizeChatInput();
  } catch (e) {
    _booted = false;
    console.error("Boot init failed:", e);
    const el = document.getElementById("boot-error");
    if (el) {
      el.hidden = false;
      el.textContent = "UI init lỗi: " + (e && e.message ? e.message : String(e));
    }
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  // module load xong sau DOMContentLoaded (thường gặp khi Chrome cache chậm) — vẫn boot
  boot();
}
