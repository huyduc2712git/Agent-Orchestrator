/* Agent Orchestrator — Chat Component & SSE Stream */

import { state, $, escapeHtml, formatTime } from "../state.js";
import { getAgentAvatarHtml } from "../constants.js";
import { openNewProject } from "./modal.js";

const SKILL_TAG_NAMES = "skip-security|scope-ui|force-security|security|deploy-prod|db-migration";
const SKILL_TAG_RE = new RegExp(
  `(^|[\\s,;([{'"])(@(?:${SKILL_TAG_NAMES}))(?=\\b)`,
  "gi"
);

export function skillPillHtml(tagWithAt, extraClass = "") {
  const key = String(tagWithAt || "").replace(/^@/, "").toLowerCase();
  const cls = ["chat-skill-pill", extraClass].filter(Boolean).join(" ");
  return (
    `<span class="${cls}" data-skill="${escapeHtml(key)}">` +
    `<span class="chat-skill-at">@</span>${escapeHtml(key)}` +
    `</span>`
  );
}

const SKILL_TAG_SET = new Set(SKILL_TAG_NAMES.split("|"));

/** Tách @skill khỏi nội dung để render pill riêng (không nhét trong bubble). */
export function splitMessageSkills(message) {
  const tags = [];
  let body = String(message || "");
  body = body.replace(SKILL_TAG_RE, (full, prefix, tag) => {
    const key = String(tag).replace(/^@/, "").toLowerCase();
    if (key && !tags.includes(key)) tags.push(key);
    return prefix;
  });
  // Dòng 🏷 từ API (nếu có) — gộp vào pills
  body = body.replace(/(?:^|\n)🏷\s*([^\n]+)/g, (_, list) => {
    for (const part of String(list).split(",")) {
      const key = part.trim().toLowerCase().replace(/^@/, "");
      if (key && !tags.includes(key) && SKILL_TAG_SET.has(key)) tags.push(key);
    }
    return "";
  });
  body = body.replace(/\s{2,}/g, " ").trim();
  return { body, tags };
}

/** Tin user: ảnh + skills + text tách riêng để layout (ảnh | skills → text dưới). */
export function splitUserMessageParts(message) {
  const { body: afterSkills, tags } = splitMessageSkills(message);
  const images = [];
  let body = afterSkills.replace(
    /(?:🖼\s*)?(https?:\/\/[^\s<>"']+\/uploads\/[^\s<>"']+|\/uploads\/[^\s<>"']+)/gi,
    (_full, url) => {
      if (url && !images.includes(url)) images.push(url);
      return " ";
    }
  );
  body = body.replace(/\s{2,}/g, " ").trim();
  return { body, tags, images };
}

const MISSING_IMG_SVG =
  "data:image/svg+xml," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">' +
      '<rect width="128" height="128" rx="12" fill="#1e293b"/>' +
      '<rect x="8" y="8" width="112" height="112" rx="10" fill="none" stroke="#475569" stroke-width="2" stroke-dasharray="6 4"/>' +
      '<path d="M36 84l18-22 14 16 12-10 20 24H36z" fill="#334155"/>' +
      '<circle cx="52" cy="48" r="10" fill="#475569"/>' +
      '<text x="64" y="112" text-anchor="middle" fill="#94a3b8" font-family="system-ui,sans-serif" font-size="11">ảnh đã xóa</text>' +
      "</svg>"
  );

export function userImageHtml(url) {
  const src = escapeHtml(url);
  return (
    `<a href="${src}" target="_blank" rel="noopener" class="chat-img-link" title="Ảnh đính kèm">` +
    `<img src="${src}" alt="Ảnh đính kèm" class="chat-attach-thumb" loading="lazy" ` +
    `onerror="this.onerror=null;this.src='${MISSING_IMG_SVG}';this.classList.add('is-missing');if(this.parentElement)this.parentElement.classList.add('is-missing');" />` +
    `</a>`
  );
}

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
  text = text.replace(/```(?:([a-zA-Z0-9_-]+)\n)?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    const langClass = lang ? ` class="chat-code language-${escapeHtml(lang.trim())}"` : ` class="chat-code"`;
    codeBlocks.push(`<pre class="chat-pre"><code${langClass}>${escapeHtml((code || "").trim())}</code></pre>`);
    return `___CODEBLOCK_${idx}___`;
  });

  const inlineCodes = [];
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code class="chat-code">${escapeHtml(code)}</code>`);
    return `___INLINECODE_${idx}___`;
  });

  // Skills @tag → placeholder trước escape
  const skills = [];
  text = text.replace(SKILL_TAG_RE, (full, prefix, tag) => {
    const idx = skills.length;
    skills.push(skillPillHtml(tag));
    return `${prefix}___SKILL_${idx}___`;
  });

  let html = escapeHtml(text);

  // Ảnh upload (/uploads/...) → thumbnail, không hiện raw link
  html = html.replace(
    /(?:🖼\s*)?(https?:\/\/[^\s<&]+\/uploads\/[^\s<&]+|\/uploads\/[^\s<&]+)/gi,
    (_full, url) => {
      const src = url;
      return (
        `<a href="${src}" target="_blank" rel="noopener" class="chat-img-link" title="Ảnh đính kèm">` +
        `<img src="${src}" alt="Ảnh đính kèm" class="chat-attach-thumb" loading="lazy" ` +
        `onerror="this.onerror=null;this.src='${MISSING_IMG_SVG}';this.classList.add('is-missing');if(this.parentElement)this.parentElement.classList.add('is-missing');" />` +
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

  skills.forEach((pill, i) => {
    html = html.replace(`___SKILL_${i}___`, pill);
  });
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
    const { body, tags, images } = splitUserMessageParts(m.message);
    const topParts = [];
    if (images.length) {
      topParts.push(
        `<div class="msg-user-media">${images.map(userImageHtml).join("")}</div>`
      );
    }
    if (tags.length) {
      topParts.push(
        `<div class="msg-skill-row">${tags.map((t) => skillPillHtml(t)).join("")}</div>`
      );
    }
    const topHtml = topParts.length
      ? `<div class="msg-user-top">${topParts.join("")}</div>`
      : "";
    const textHtml = body
      ? `<div class="msg-user-text">${formatMarkdownMessage(body)}</div>`
      : "";
    // Không có gì để hiện (hiếm) — bỏ qua
    if (!topHtml && !textHtml) return;
    row.innerHTML = `
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
        <div class="msg-bubble thinking-bubble" aria-live="polite" aria-label="Conan đang suy nghĩ">
          <span class="thinking-text">Conan đang suy nghĩ</span><span class="thinking-ellipsis" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
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
  try {
    if (typeof window.renderFlowChat === "function") {
      window.renderFlowChat();
    }
  } catch (_) {}
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

const PIPELINE_MENTIONS = [
  { tag: "skip-security", desc: "Bỏ Akai Security + Amuro Pentest sau QA" },
  { tag: "scope-ui", desc: "Task chỉ UI — tương đương skip-security" },
  { tag: "force-security", desc: "Bắt buộc chạy Security + Pentest" },
  { tag: "deploy-prod", desc: "Deploy prod — cần operator review" },
  { tag: "db-migration", desc: "Migration DB — cần operator review" },
];

/** Pipeline + workflow skills từ GET /api/skills */
let _mentionCatalog = [...PIPELINE_MENTIONS];

export async function loadSkillMentions() {
  try {
    const res = await fetch("/api/skills");
    const data = await res.json();
    const skills = (data.skills || []).map((s) => ({
      tag: String(s.name || "").toLowerCase(),
      desc: String(s.description || s.source || "").slice(0, 120),
      source: s.source,
      runAs: s.runAs || s.run_as || "inline",
      invocation: s.invocation || "auto",
    })).filter((s) => {
      if (!s.tag) return false;
      // Agent subagent profiles = system prompts, không gắn @skill trên task
      if (s.source === "agent" && (s.invocation === "manual" || s.runAs === "subagent")) {
        return false;
      }
      return true;
    });
    const seen = new Set(PIPELINE_MENTIONS.map((x) => x.tag));
    // Ưu tiên: pipeline → native → reasonix → workspace → addy (Addy dài, đừng che skill hay dùng)
    const sourceRank = { native: 0, reasonix: 1, workspace: 2, addy: 3, agent: 9 };
    const playbooks = skills
      .filter((s) => !seen.has(s.tag))
      .sort((a, b) => {
        const ra = sourceRank[a.source] ?? 5;
        const rb = sourceRank[b.source] ?? 5;
        if (ra !== rb) return ra - rb;
        return a.tag.localeCompare(b.tag);
      });
    _mentionCatalog = [...PIPELINE_MENTIONS, ...playbooks];
  } catch (e) {
    console.warn("loadSkillMentions failed", e);
    _mentionCatalog = [...PIPELINE_MENTIONS];
  }
}

let _mention = { open: false, items: [], index: 0, start: -1, query: "" };
/** Skills đã gắn vào composer (pill) — gửi kèm tin nhắn. */
const _composerSkills = new Set();

function hideMentionMenu() {
  _mention = { open: false, items: [], index: 0, start: -1, query: "" };
  const menu = $("chat-mention-menu");
  if (menu) {
    menu.classList.add("hidden");
    menu.innerHTML = "";
  }
}

function renderComposerSkills() {
  const wrap = $("chat-skill-chips");
  if (!wrap) return;
  const tags = [..._composerSkills];
  if (!tags.length) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = tags
    .map(
      (tag) =>
        `<span class="chat-skill-pill composer" data-skill="${escapeHtml(tag)}">` +
        `<span class="chat-skill-at">@</span>${escapeHtml(tag)}` +
        `<button type="button" class="chat-skill-remove" data-skill="${escapeHtml(tag)}" aria-label="Gỡ @${escapeHtml(tag)}">×</button>` +
        `</span>`
    )
    .join("");
  wrap.classList.remove("hidden");
  wrap.querySelectorAll(".chat-skill-remove").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => {
      e.preventDefault();
      removeComposerSkill(btn.dataset.skill);
    });
  });
}

function addComposerSkill(tag) {
  const key = String(tag || "").toLowerCase().replace(/^@/, "");
  if (!key || !_mentionCatalog.some((x) => x.tag === key)) return;
  _composerSkills.add(key);
  renderComposerSkills();
}

/** Dùng từ Settings “Use in chat”. */
export function useSkillInChat(tag) {
  addComposerSkill(tag);
  const ta = $("chat-input");
  ta?.focus();
}

function removeComposerSkill(tag) {
  _composerSkills.delete(String(tag || "").toLowerCase());
  renderComposerSkills();
}

function clearComposerSkills() {
  _composerSkills.clear();
  renderComposerSkills();
}

function messageWithSkills(text) {
  let msg = (text || "").trim();
  for (const tag of _composerSkills) {
    const re = new RegExp(`(?:^|[\\s,;])@${tag.replace(/-/g, "\\-")}(?=\\s|$)`, "i");
    if (!re.test(msg)) msg = msg ? `${msg} @${tag}` : `@${tag}`;
  }
  return msg.trim();
}

function renderMentionMenu() {
  const menu = $("chat-mention-menu");
  if (!menu) return;
  if (!_mention.open || !_mention.items.length) {
    menu.classList.add("hidden");
    menu.innerHTML = "";
    return;
  }
  menu.innerHTML = _mention.items
    .map((it, i) => {
      const src = it.source ? `<span class="mention-src">${escapeHtml(it.source)}</span>` : "";
      return (
        `<button type="button" class="chat-mention-item${i === _mention.index ? " is-active" : ""}" data-idx="${i}" role="option">` +
        `<span class="chat-skill-pill menu"><span class="chat-skill-at">@</span>${escapeHtml(it.tag)}</span>` +
        `${src}` +
        `<span class="mention-desc">${escapeHtml(it.desc)}</span>` +
        `</button>`
      );
    })
    .join("");
  menu.classList.remove("hidden");
  menu.querySelectorAll(".chat-mention-item").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const idx = Number(btn.dataset.idx);
      applyMention(idx);
    });
  });
}

function detectMentionAtCursor(ta) {
  const pos = ta.selectionStart ?? ta.value.length;
  const before = ta.value.slice(0, pos);
  const m = before.match(/(^|[\s,;([{'"])@([a-z0-9_-]*)$/i);
  if (!m) return null;
  return { start: pos - m[2].length - 1, query: m[2].toLowerCase() };
}

function updateMentionSuggest(ta) {
  const hit = detectMentionAtCursor(ta);
  if (!hit) {
    hideMentionMenu();
    return;
  }
  const items = _mentionCatalog.filter(
    (it) => !hit.query || it.tag.startsWith(hit.query) || it.tag.includes(hit.query)
  ).slice(0, 14);
  if (!items.length) {
    hideMentionMenu();
    return;
  }
  _mention = {
    open: true,
    items,
    index: Math.min(_mention.index, items.length - 1),
    start: hit.start,
    query: hit.query,
  };
  if (_mention.index < 0) _mention.index = 0;
  renderMentionMenu();
}

/** Chặn Enter gửi ngay sau khi chọn skill từ menu @. */
let _blockSendUntil = 0;

function applyMention(idx) {
  const ta = $("chat-text");
  const item = _mention.items[idx];
  if (!ta || !item || _mention.start < 0) return;
  // Xóa đoạn @đang-gõ — skill hiện ở pill tray, không chèn text thô khó đọc
  const pos = ta.selectionStart ?? ta.value.length;
  const before = ta.value.slice(0, _mention.start);
  const after = ta.value.slice(pos);
  ta.value = `${before}${after}`.replace(/\s{2,}/g, " ");
  const caret = Math.min(before.length, ta.value.length);
  ta.setSelectionRange(caret, caret);
  addComposerSkill(item.tag);
  _blockSendUntil = Date.now() + 400;
  hideMentionMenu();
  resizeChatInput();
  ta.focus();
}

/** true nếu đã xử lý phím (chặn gửi tin / xuống dòng). */
export function handleChatMentionKeydown(e) {
  if (_mention.open) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      e.stopPropagation();
      _mention.index = (_mention.index + 1) % _mention.items.length;
      renderMentionMenu();
      return true;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      e.stopPropagation();
      _mention.index = (_mention.index - 1 + _mention.items.length) % _mention.items.length;
      renderMentionMenu();
      return true;
    }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
      applyMention(_mention.index);
      return true;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      hideMentionMenu();
      return true;
    }
  }
  // Enter ngay sau khi chọn skill — không gửi
  if (e.key === "Enter" && Date.now() < _blockSendUntil) {
    e.preventDefault();
    e.stopPropagation();
    if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
    return true;
  }
  return false;
}

export async function sendChatMessage(text) {
  if (Date.now() < _blockSendUntil) return;
  const body = (text || "").trim();
  // Chỉ skill, chưa có nội dung → không gửi (Enter chọn @ không được thành tin)
  if (!body && !hasPendingImage()) return;
  const msg = messageWithSkills(text);
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
    hideMentionMenu();
    clearComposerSkills();
    await sendChatImage(file, msg);
    return;
  }

  const ta = $("chat-text");
  if (ta) ta.value = "";
  resetChatInputHeight();
  hideMentionMenu();
  clearComposerSkills();
  const sendBtn = $("chat-send");
  if (sendBtn) sendBtn.disabled = true;
  state.workStartedAt = Date.now();
  setThinking(true);
  try {
    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: msg,
        project: state.activeProject || "",
      }),
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

  const ta = $("chat-text");
  ta?.addEventListener("input", () => updateMentionSuggest(ta));
  ta?.addEventListener("click", () => updateMentionSuggest(ta));
  ta?.addEventListener("blur", () => {
    // delay để mousedown chọn item kịp chạy
    setTimeout(() => hideMentionMenu(), 150);
  });
}
