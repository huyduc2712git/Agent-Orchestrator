/* Agent Orchestrator — Settings Modal & Configuration Component */

import { state, $, escapeHtml, updateChatModelPill } from "../state.js";
import { API_BASE, loadSettings } from "../api.js";

export function openSettingsModal() {
  const backdrop = $("settings-backdrop");
  if (!backdrop) return;
  backdrop.classList.remove("hidden");
  loadAndRenderSettings();
}

export function closeSettingsModal() {
  const backdrop = $("settings-backdrop");
  if (backdrop) backdrop.classList.add("hidden");
}

export function initSettingsEvents() {
  // Open Settings button
  $("sidebar-settings-btn")?.addEventListener("click", openSettingsModal);

  // Close Settings button & backdrop click
  $("settings-close")?.addEventListener("click", closeSettingsModal);
  $("settings-backdrop")?.addEventListener("click", (e) => {
    if (e.target === $("settings-backdrop")) closeSettingsModal();
  });

  // Tab switching
  document.querySelectorAll(".settings-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".settings-tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".settings-tab-content").forEach((c) => c.classList.add("hidden"));
      btn.classList.add("active");
      const tabId = btn.dataset.tab;
      const tabEl = $(tabId);
      if (tabEl) tabEl.classList.remove("hidden");
    });
  });

  // Form Submissions
  setupLlmToolForm();
  setupFigmaTokenForm();
  setupGitTokenForm();
  setupProjectsRootForm();
}

async function loadAndRenderSettings() {
  try {
    const res = await fetch(`${API_BASE}/api/settings`);
    const data = await res.json();

    renderLlmTools(data.llm_tools || [], data.has_active_tasks);
    renderRoleModels(data.role_models || {}, data.role_labels || {}, data.llm_tools || [], data.has_active_tasks);
    renderFigmaTokens(data.figma_tokens || []);
    renderGitTokens(data.git_tokens || []);
    renderProjectsRoot(data.projects_root || "", data.projects_root_custom || "");

    // Update global state
    if (data.agents && Array.isArray(data.agents)) {
      const conan = data.agents.find((a) => a.key === "conan");
      if (conan && (conan.model || conan.tool_name)) {
        state.plannerModel = conan.model || conan.tool_name;
      }
    }
    updateChatModelPill();
  } catch (err) {
    console.error("Failed to load settings:", err);
  }
}

function renderLlmTools(tools, hasActiveTasks) {
  const container = $("llm-tool-list");
  if (!container) return;
  container.innerHTML = "";

  if (!tools.length) {
    container.innerHTML = '<div class="sidebar-hint">Chưa có LLM Tool nào được thêm</div>';
    return;
  }

  tools.forEach((t) => {
    const row = document.createElement("div");
    row.className = "llm-tool-row" + (t.enabled === false ? " off" : "");
    const isChecked = t.enabled !== false ? "checked" : "";
    const defaultBadge = t.is_default ? '<span class="default-badge">System Default</span>' : "";

    row.innerHTML = `
      <input type="checkbox" data-id="${t.id}" class="llm-toggle-chk" ${isChecked} ${t.is_default ? "disabled" : ""} title="${t.is_default ? "Mặc định hệ thống" : "Bật/Tắt model"}" style="cursor:pointer; width:16px; height:16px; accent-color:#3b82f6;"/>
      <div class="llm-model-info">
        <div class="llm-model-name-row">
          <span class="llm-model-name">${escapeHtml(t.model)}</span>
          ${defaultBadge}
        </div>
        <div class="llm-model-url">${escapeHtml(t.base_url || "Built-in System Model")}</div>
      </div>
      <div class="llm-tool-actions">
        ${!t.is_default ? `<button type="button" class="btn-delete-llm-tool" data-id="${t.id}">Xóa</button>` : ""}
      </div>
    `;

    row.querySelector(".llm-toggle-chk")?.addEventListener("change", async (e) => {
      const enabled = e.target.checked;
      try {
        const resp = await fetch(`${API_BASE}/api/settings/llm-tools/${encodeURIComponent(t.id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
        });
        const rData = await resp.json();
        if (!resp.ok) {
          e.target.checked = !enabled;
          alert(rData.error || "Lỗi khi đổi trạng thái");
        } else {
          loadAndRenderSettings();
        }
      } catch (err) {
        e.target.checked = !enabled;
        alert("Lỗi kết nối: " + err.message);
      }
    });

    row.querySelector(".btn-delete-llm-tool")?.addEventListener("click", async () => {
      if (!confirm(`Xóa LLM Tool "${t.model}"?`)) return;
      try {
        const resp = await fetch(`${API_BASE}/api/settings/llm-tools/${encodeURIComponent(t.id)}`, { method: "DELETE" });
        const rData = await resp.json();
        if (!resp.ok) alert(rData.error || "Lỗi khi xóa tool");
        else loadAndRenderSettings();
      } catch (err) {
        alert("Lỗi kết nối: " + err.message);
      }
    });

    container.appendChild(row);
  });
}

const ROLE_UI_META = {
  planner: {
    title: "Planner / Squad Lead",
    sub: "Conan • Phân tách task & Điều phối Squad",
    avatar: "/static/avatar_agent/Conan.png",
    icon: "🕵️‍♂️",
  },
  coder: {
    title: "Coding / Debug Specialist",
    sub: "Kaito Kid & Agasa • Xây dựng UI/FE & BE API",
    avatar: "/static/avatar_agent/Kid.png",
    icon: "🎩",
  },
  critic: {
    title: "QA / Security Reviewer",
    sub: "Haibara, Heiji, Akai, Amuro • Review & Pentest",
    avatar: "/static/avatar_agent/Haibara.png",
    icon: "💊",
  },
  summary: {
    title: "Summary / Patrol Memory",
    sub: "System Patrol • Báo cáo tiến độ & Tuần tra",
    avatar: "",
    icon: "⚙️",
  },
  vision: {
    title: "Vision / Image Chat",
    sub: "Đọc ảnh đính kèm trong Orchestrator Chat (bắt buộc model hỗ trợ ảnh)",
    avatar: "",
    icon: "🖼",
  },
};

function formatModelOptionLabel(tool) {
  return tool.model || tool.name || "Unknown";
}

function renderRoleModels(roleModels, roleLabels, tools, hasActiveTasks) {
  const container = $("agent-models");
  if (!container) return;
  container.innerHTML = "";

  const enabledTools = tools.filter((t) => t.enabled !== false);
  const roles = Object.keys(roleLabels).length ? roleLabels : {
    planner: "Planner / Squad Lead (Conan)",
    coder: "Coder / UI Builder (Kid, Agasa)",
    critic: "Critic / QA (Heiji, Haibara, Akai, Amuro)",
    summary: "Summary / Reporter",
  };

  for (const [roleKey, fallbackLabel] of Object.entries(roles)) {
    const meta = ROLE_UI_META[roleKey] || {
      title: fallbackLabel,
      sub: "Nhiệm vụ thuộc nhóm " + roleKey,
      icon: "🤖",
    };

    const card = document.createElement("div");
    card.className = "role-card";

    const currentToolId = roleModels[roleKey] || "";
    let optionsHtml = enabledTools.map((t) => {
      const selected = t.id === currentToolId || t.model === currentToolId ? "selected" : "";
      return `<option value="${t.id}" ${selected}>${escapeHtml(formatModelOptionLabel(t))}</option>`;
    }).join("");

    const avatarHtml = meta.avatar
      ? `<img src="${meta.avatar}" alt="${escapeHtml(meta.title)}"/>`
      : meta.icon;

    card.innerHTML = `
      <div class="role-card-left">
        <div class="role-avatar-wrap">${avatarHtml}</div>
        <div>
          <div class="role-info-title">${escapeHtml(meta.title)}</div>
          <div class="role-info-sub">${escapeHtml(meta.sub)}</div>
        </div>
      </div>
      <select data-role="${roleKey}" class="role-select" title="Đổi LLM Model cho vai trò này">
        ${optionsHtml}
      </select>
    `;

    card.querySelector(".role-select")?.addEventListener("change", async (e) => {
      const tool_id = e.target.value;
      try {
        const resp = await fetch(`${API_BASE}/api/settings/role-models`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: roleKey, tool_id }),
        });
        const rData = await resp.json();
        if (!resp.ok) {
          alert(rData.error || "Lỗi khi cập nhật role model");
          loadAndRenderSettings();
        } else {
          loadAndRenderSettings();
        }
      } catch (err) {
        alert("Lỗi kết nối: " + err.message);
      }
    });

    container.appendChild(card);
  }
}

function renderFigmaTokens(tokens) {
  const container = $("token-list");
  if (!container) return;
  container.innerHTML = "";

  if (!tokens.length) {
    container.innerHTML = '<div class="sidebar-hint">Chưa có Figma Token nào</div>';
    return;
  }

  tokens.forEach((t) => {
    const row = document.createElement("div");
    row.className = "token-row";
    row.innerHTML = `
      <div class="llm-model-info">
        <div class="llm-model-name">${escapeHtml(t.name)}</div>
        <div class="llm-model-url">${escapeHtml(t.token_masked)}</div>
      </div>
      <button type="button" class="btn-delete-llm-tool" data-name="${t.name}">Xóa</button>
    `;
    row.querySelector(".btn-delete-llm-tool")?.addEventListener("click", async () => {
      if (!confirm(`Xóa Figma Token "${t.name}"?`)) return;
      try {
        const resp = await fetch(`${API_BASE}/api/settings/figma-tokens/${encodeURIComponent(t.name)}`, { method: "DELETE" });
        if (resp.ok) loadAndRenderSettings();
        else alert("Lỗi khi xóa token");
      } catch (err) {
        alert("Lỗi kết nối: " + err.message);
      }
    });
    container.appendChild(row);
  });
}

function renderGitTokens(tokens) {
  const container = $("git-token-list");
  if (!container) return;
  container.innerHTML = "";

  if (!tokens.length) {
    container.innerHTML = '<div class="sidebar-hint">Chưa có Git Token nào</div>';
    return;
  }

  tokens.forEach((t) => {
    const row = document.createElement("div");
    row.className = "token-row";
    row.innerHTML = `
      <div class="llm-model-info">
        <div class="llm-model-name">${escapeHtml(t.name)} (${escapeHtml(t.host || "github.com")})</div>
        <div class="llm-model-url">${escapeHtml(t.token_masked)}</div>
      </div>
      <button type="button" class="btn-delete-llm-tool" data-name="${t.name}">Xóa</button>
    `;
    row.querySelector(".btn-delete-llm-tool")?.addEventListener("click", async () => {
      if (!confirm(`Xóa Git Token "${t.name}"?`)) return;
      try {
        const resp = await fetch(`${API_BASE}/api/settings/git-tokens/${encodeURIComponent(t.name)}`, { method: "DELETE" });
        if (resp.ok) loadAndRenderSettings();
        else alert("Lỗi khi xóa token");
      } catch (err) {
        alert("Lỗi kết nối: " + err.message);
      }
    });
    container.appendChild(row);
  });
}

function renderProjectsRoot(effective, custom) {
  const input = $("projects-root-input");
  const hint = $("projects-root-effective");
  if (input) input.value = custom || "";
  if (hint) {
    hint.innerHTML = custom
      ? `Thư mục đang áp dụng: <code style="color:#60a5fa;">${escapeHtml(effective)}</code> (Tùy chỉnh)`
      : `Thư mục đang áp dụng: <code style="color:#60a5fa;">${escapeHtml(effective)}</code> (Mặc định hệ thống)`;
  }
}

function setupLlmToolForm() {
  const form = $("llm-tool-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const base_url = $("llm-base-url")?.value.trim();
    const model = $("llm-model")?.value.trim();
    const api_key = $("llm-api-key")?.value.trim();
    const submitBtn = $("llm-tool-add");

    if (!base_url || !model || !api_key) return;
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "⏳ Đang kiểm tra API & Thêm..."; }

    try {
      const resp = await fetch(`${API_BASE}/api/settings/llm-tools`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url, model, api_key }),
      });
      const data = await resp.json();
      if (resp.ok) {
        if ($("llm-base-url")) $("llm-base-url").value = "";
        if ($("llm-model")) $("llm-model").value = "";
        if ($("llm-api-key")) $("llm-api-key").value = "";
        alert("✅ Đã kiểm tra kết nối & Thêm LLM Tool thành công!");
        loadAndRenderSettings();
      } else {
        alert(`❌ Không thể thêm LLM Tool:\n${data.error || "Lỗi không xác định"}`);
      }
    } catch (err) {
      alert("❌ Lỗi kết nối server: " + err.message);
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "+ Thêm LLM Model"; }
    }
  });
}

function setupFigmaTokenForm() {
  const form = $("token-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("token-name")?.value.trim();
    const token = $("token-value")?.value.trim();
    const submitBtn = $("token-add");

    if (!name || !token) return;
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "⏳ Đang xác thực Figma..."; }

    try {
      const resp = await fetch(`${API_BASE}/api/settings/figma-tokens`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, token }),
      });
      const data = await resp.json();
      if (resp.ok) {
        if ($("token-name")) $("token-name").value = "";
        if ($("token-value")) $("token-value").value = "";
        alert(`✅ Figma Token hợp lệ! Tài khoản: ${data.account_email || name}`);
        loadAndRenderSettings();
      } else {
        alert(`❌ Lỗi: ${data.error || "Token không hợp lệ"}`);
      }
    } catch (err) {
      alert("❌ Lỗi kết nối: " + err.message);
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "+ Thêm Figma Token"; }
    }
  });
}

function setupGitTokenForm() {
  const form = $("git-token-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("git-token-name")?.value.trim();
    const host = $("git-token-host")?.value.trim() || "github.com";
    const token = $("git-token-value")?.value.trim();
    const submitBtn = $("git-token-add");

    if (!name || !token) return;
    if (submitBtn) { submitBtn.disabled = true; }

    try {
      const resp = await fetch(`${API_BASE}/api/settings/git-tokens`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, host, token }),
      });
      const data = await resp.json();
      if (resp.ok) {
        if ($("git-token-name")) $("git-token-name").value = "";
        if ($("git-token-value")) $("git-token-value").value = "";
        alert("✅ Đã lưu Git Token thành công!");
        loadAndRenderSettings();
      } else {
        alert(`❌ Lỗi: ${data.error || "Không lưu được"}`);
      }
    } catch (err) {
      alert("❌ Lỗi kết nối: " + err.message);
    } finally {
      if (submitBtn) { submitBtn.disabled = false; }
    }
  });
}

function setupProjectsRootForm() {
  const form = $("projects-root-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const path = $("projects-root-input")?.value.trim() || "";
    try {
      const resp = await fetch(`${API_BASE}/api/settings/projects-root`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const data = await resp.json();
      if (resp.ok) {
        alert("✅ Đã lưu thư mục Projects root mới!");
        loadAndRenderSettings();
      } else {
        alert(`❌ Lỗi: ${data.error || "Không lưu được"}`);
      }
    } catch (err) {
      alert("❌ Lỗi kết nối: " + err.message);
    }
  });

  $("projects-root-reset")?.addEventListener("click", async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/settings/projects-root`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: "" }),
      });
      if (resp.ok) {
        alert("✅ Đã reset về thư mục Projects root mặc định!");
        loadAndRenderSettings();
      }
    } catch (err) {
      alert("❌ Lỗi kết nối: " + err.message);
    }
  });
}
