/* Agent Orchestrator — Chat Component & SSE Stream */

import { state, $, escapeHtml, formatTime } from "../state.js";
import { getAgentAvatarHtml } from "../constants.js";
import { openNewProject } from "./modal.js";

export function formatMarkdownMessage(text) {
  if (!text) return "";
  text = text.replace(
    /(https?:\/\/[^\s<>"']+\/preview\/[a-z0-9_-]+)(?![\w./#-])/gi,
    "$1/"
  );
  text = text.replace(
    /(https?:\/\/[^\s<>"']+\/preview\/[a-z0-9_-]+)(?=\s|$|[)\].,!])/gi,
    (url) => (url.endsWith("/") ? url : url + "/")
  );

  const codeBlocks = [];
  text = text.replace(/```([\s\S]*?)```/g, (_, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre class="chat-pre"><code class="chat-code">${escapeHtml(code.trim())}</code></pre>`);
    return `___CODEBLOCK_${idx}___`;
  });

  const inlineCodes = [];
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code class="chat-code">${escapeHtml(code)}</code>`);
    return `___INLINECODE_${idx}___`;
  });

  let html = escapeHtml(text);

  // Ảnh upload (/uploads/...) → thumbnail, không hiện raw link
  html = html.replace(
    /(?:🖼\s*)?(https?:\/\/[^\s<&]+\/uploads\/[^\s<&]+|\/uploads\/[^\s<&]+)/gi,
    (_full, url) => {
      const src = url;
      return (
        `<a href="${src}" target="_blank" rel="noopener" class="chat-img-link" title="Mở ảnh gốc">` +
        `<img src="${src}" alt="Ảnh đính kèm" class="chat-attach-thumb" loading="lazy" />` +
        `</a>`
      );
    }
  );

  html = html.replace(
    /(https?:\/\/[^\s<]+)/gi,
    (url) => {
      // đã render thành <img> ở trên — bỏ qua URL nằm trong src/href ảnh
      if (/\/uploads\//i.test(url)) return url;
      let href = url;
      const m = href.match(/^(https?:\/\/[^/]+\/preview\/[a-z0-9_-]+)\/?$/i);
      if (m) href = m[1] + "/";
      return `<a href="${href}" target="_blank" rel="noopener">${url}</a>`;
    }
  );

  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
  html = html.replace(/\n/g, "<br/>");

  inlineCodes.forEach((codeHtml, i) => {
    html = html.replace(`___INLINECODE_${i}___`, codeHtml);
  });
  codeBlocks.forEach((codeHtml, i) => {
    html = html.replace(`___CODEBLOCK_${i}___`, codeHtml);
  });

  return html;
}

export function focusChatInput(prefix) {
  const ta = $("chat-text");
  if (!ta) return;
  if (prefix) ta.value = prefix;
  ta.focus();
}

export function formatDurationPrecise(ms) {
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

export function conanWorkStats(messages, index) {
  const m = messages[index];
  if (!m || (m.role !== "conan" && m.role !== "system")) return null;

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

export function plannerModelLabel() {
  return (state.plannerModel || "").trim() || "planner";
}

export function appendChatMessage(m) {
  if (!m) return;
  if (m.id != null && state.chatMessages.some((x) => x.id === m.id)) return;
  state.chatMessages.push(m);
  renderChatMessage(m, state.chatMessages.length - 1);
}

export function renderChatMessage(m, index) {
  const box = $("chat-messages");
  if (!box) return;
  if (!m || !m.message || !m.message.trim()) return;
  if (index == null) {
    index = state.chatMessages.findIndex((x) => x === m || (m.id != null && x.id === m.id));
    if (index < 0) {
      state.chatMessages.push(m);
      index = state.chatMessages.length - 1;
    }
  }

  if (m.role === "system") {
    const timeStr = formatTime(m.created_at);
    const work = conanWorkStats(state.chatMessages, index);
    const row = document.createElement("div");
    row.className = "msg-row system-msg";
    row.innerHTML = `
      ${getAgentAvatarHtml("system")}
      <div class="msg-conan-wrapper">
        <div class="msg-meta-conan">
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
  row.className = `msg-row ${isUser ? "user" : "conan"}`;
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
      ${getAgentAvatarHtml("user")}`;
  } else {
    const work = conanWorkStats(state.chatMessages, index);
    row.innerHTML = `
      ${getAgentAvatarHtml("conan")}
      <div class="msg-conan-wrapper">
        <div class="msg-meta-conan">
          <span class="name">Conan</span>
          ${timeStr ? `<span class="dot">•</span><span class="time">${escapeHtml(timeStr)}</span>` : ""}
          <span class="model-badge">${escapeHtml(plannerModelLabel())}</span>
          ${work ? `<span class="worked-badge" title="Thời gian thật từ lúc bạn gửi đến phản hồi này">${escapeHtml(work.label)}</span>` : ""}
        </div>
        <div class="msg-bubble conan-bubble">${formatMarkdownMessage(m.message)}</div>
      </div>`;
    if (state.workStartedAt) state.workStartedAt = null;
  }
  const thinkRow = $("thinking-row");
  if (thinkRow) box.insertBefore(row, thinkRow);
  else box.appendChild(row);
  box.scrollTop = box.scrollHeight;
  if (!isUser) setThinking(false);
}

export function setThinking(on) {
  state.thinking = !!on;
  const box = $("chat-messages");
  if (!box) return;
  let thinkRow = $("thinking-row");
  if (on) {
    if (!thinkRow) {
      thinkRow = document.createElement("div");
      thinkRow.id = "thinking-row";
      thinkRow.className = "msg-row conan thinking";
      thinkRow.innerHTML = `
        ${getAgentAvatarHtml("conan")}
        <div class="msg-bubble thinking-bubble">
          <span class="thinking-text">Conan đang suy nghĩ...</span>
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

export async function loadChat() {
  const res = await fetch("/api/chat");
  const data = await res.json();
  const box = $("chat-messages");
  if (!box) return;
  box.innerHTML = "";
  state.chatMessages = (data.messages || []).filter((m) => m && m.message && m.message.trim());
  if (!state.chatMessages.length) {
    const w = document.createElement("div");
    w.className = "msg-row conan";
    w.innerHTML = `${getAgentAvatarHtml("conan")}<div><div class="msg-bubble">Ask me something!</div></div>`;
    box.appendChild(w);
  } else {
    state.chatMessages.forEach((m, i) => renderChatMessage(m, i));
  }
}

export function resizeChatInput() {
  const ta = $("chat-text");
  if (!ta) return;
  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
}

export function resetChatInputHeight() {
  const ta = $("chat-text");
  if (!ta) return;
  ta.style.height = "auto";
}

/** Ảnh chờ gửi trong composer — chọn xong chưa upload cho đến khi bấm Gửi. */
let _pendingImage = null; // { file, previewUrl, name }

export function hasPendingImage() {
  return !!_pendingImage?.file;
}

export function clearPendingImage() {
  if (_pendingImage?.previewUrl) {
    try {
      URL.revokeObjectURL(_pendingImage.previewUrl);
    } catch (_) {}
  }
  _pendingImage = null;
  const wrap = $("chat-image-preview");
  const img = $("chat-image-preview-img");
  const name = $("chat-image-preview-name");
  if (img) img.removeAttribute("src");
  if (name) name.textContent = "";
  wrap?.classList.add("hidden");
}

function showPendingImage(file) {
  clearPendingImage();
  if (!file) return;
  const previewUrl = URL.createObjectURL(file);
  _pendingImage = { file, previewUrl, name: file.name || "image" };
  const wrap = $("chat-image-preview");
  const img = $("chat-image-preview-img");
  const name = $("chat-image-preview-name");
  if (img) img.src = previewUrl;
  if (name) name.textContent = _pendingImage.name;
  wrap?.classList.remove("hidden");
}

export async function sendChatMessage(text) {
  const msg = (text || "").trim();
  if (!msg && !hasPendingImage()) return;
  if (!state.activeProject) {
    openNewProject("Chọn hoặc tạo project trước khi gửi task.");
    return;
  }

  // Có ảnh đính kèm → upload + vision; không có → chat text thường
  if (hasPendingImage()) {
    const file = _pendingImage.file;
    clearPendingImage();
    const ta = $("chat-text");
    if (ta) ta.value = "";
    resetChatInputHeight();
    await sendChatImage(file, msg);
    return;
  }

  const ta = $("chat-text");
  if (ta) ta.value = "";
  resetChatInputHeight();
  const sendBtn = $("chat-send");
  if (sendBtn) sendBtn.disabled = true;
  state.workStartedAt = Date.now();
  setThinking(true);
  try {
    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg, project: state.activeProject || "" }),
    });
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    if (ta) ta.focus();
  }
}

export async function sendChatImage(file, message) {
  if (!file) return;
  if (!state.activeProject) {
    openNewProject("Chọn hoặc tạo project trước khi gửi ảnh.");
    return;
  }
  const sendBtn = $("chat-send");
  if (sendBtn) sendBtn.disabled = true;
  state.workStartedAt = Date.now();
  setThinking(true);
  try {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("message", message || "");
    fd.append("project", state.activeProject || "");
    const res = await fetch("/api/chat/upload-image", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert(data.error || `Upload ảnh thất bại (HTTP ${res.status})`);
      setThinking(false);
    }
  } catch (e) {
    alert("Upload ảnh lỗi: " + e);
    setThinking(false);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    $("chat-text")?.focus();
  }
}

export function initChatImageAttach() {
  const input = $("chat-image-input");
  const btn = $("chat-attach-btn");
  if (!input || !btn) return;
  btn.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      alert("Chỉ chọn file ảnh (png/jpg/webp/gif).");
      return;
    }
    // Chỉ gắn vào composer — chưa gửi lên server
    showPendingImage(file);
    $("chat-text")?.focus();
  });
  $("chat-image-preview-remove")?.addEventListener("click", () => {
    clearPendingImage();
    $("chat-text")?.focus();
  });
}
