/* Agent Orchestrator — Constants */

export const COLUMNS = [
  { key: "backlog", label: "To Do / Backlog", headClass: "col-backlog", statuses: ["backlog"] },
  { key: "working", label: "In Progress", headClass: "col-working", statuses: ["in_progress"] },
  { key: "blocked", label: "Needs Attention", headClass: "col-blocked", statuses: ["blocked", "failed"] },
  { key: "testing", label: "In Testing / QA", headClass: "col-testing", statuses: ["testing", "review"] },
  { key: "done", label: "Done / Ready", headClass: "col-done", statuses: ["done"] },
];

export const AGENT_INFO = {
  conan: { name: "Conan", role: "Squad Lead / Orchestrator", icon: "🕵️‍♂️", bg: "#1a2233", fg: "#60a5fa", border: "#2c3b59", avatar: "/static/avatar_agent/Conan.png" },
  coulson: { name: "Coulson", role: "BA Agent", icon: "📋", bg: "#1c212c", fg: "#94a3b8", border: "#2d3545" },
  kid: { name: "Kaito Kid", role: "Frontend Builder / UI", icon: "🎩", bg: "#2a1b14", fg: "#fb923c", border: "#472b1d", avatar: "/static/avatar_agent/Kid.png" },
  agasa: { name: "Agasa", role: "Backend Specialist", icon: "🧪", bg: "#211633", fg: "#a78bfa", border: "#392557", avatar: "/static/avatar_agent/Agasa.png" },
  heiji: { name: "Heiji", role: "Visual QA / Hiện trường", icon: "🔍", bg: "#12241a", fg: "#4ade80", border: "#1f402c", avatar: "/static/avatar_agent/Heiji.png" },
  haibara: { name: "Ai Haibara", role: "Quality Reviewer", icon: "💊", bg: "#2d1624", fg: "#f472b6", border: "#4a243b", avatar: "/static/avatar_agent/Haibara.png" },
  akai: { name: "Shuichi Akai", role: "Security Reviewer", icon: "🔫", bg: "#1a1f2e", fg: "#93c5fd", border: "#2c3b59", avatar: "/static/avatar_agent/Akai.png" },
  amuro: { name: "Amuro", role: "Penetration Tester", icon: "🕵️", bg: "#1f1a14", fg: "#fbbf24", border: "#423018", avatar: "/static/avatar_agent/Amuro.png" },
  operator: { name: "Operator", role: "Human Reviewer", icon: "👤", bg: "#1f1f23", fg: "#a1a1aa", border: "#333338" },
  system: { name: "System", role: "System Event", icon: "⚙️", bg: "#261c10", fg: "#fbbf24", border: "#423019" },
};

export function getAgentAvatarHtml(agentKey, extraClass = "") {
  const ag = (agentKey || "system").toLowerCase();
  const info = AGENT_INFO[ag] || { icon: "🤖", bg: "#1f1f23", fg: "#a1a1aa", border: "#333338" };
  const cls = `avatar avatar-${ag} ${extraClass}`.trim();
  if (info.avatar) {
    return `<span class="${cls}"><img src="${info.avatar}" alt="${info.name || ag}" class="avatar-img" /></span>`;
  }
  return `<span class="${cls}">${info.icon}</span>`;
}

export function getAgentIconHtml(agentKey, extraClass = "") {
  const ag = (agentKey || "system").toLowerCase();
  const info = AGENT_INFO[ag] || { icon: "🤖" };
  const cls = `agent-icon-img ${extraClass}`.trim();
  if (info.avatar) {
    return `<img src="${info.avatar}" alt="${info.name || ag}" class="${cls}" />`;
  }
  return info.icon;
}

export const AGENT_STYLE = {
  conan: AGENT_INFO.conan,
  coulson: AGENT_INFO.coulson,
  kid: AGENT_INFO.kid,
  agasa: AGENT_INFO.agasa,
  heiji: AGENT_INFO.heiji,
  haibara: AGENT_INFO.haibara,
  akai: AGENT_INFO.akai,
  amuro: AGENT_INFO.amuro,
  system: AGENT_INFO.system,
  operator: AGENT_INFO.operator,
};

export const KIND_ICON = {
  comment: "💬",
  status: "↻",
  system: "⚙",
};

export const AGENT_LABEL = {
  conan: "Conan",
  coulson: "Coulson",
  haibara: "Ai Haibara",
  kid: "Kaito Kid",
  agasa: "Agasa",
  heiji: "Heiji",
  akai: "Shuichi Akai",
  amuro: "Amuro",
  system: "System",
  operator: "Operator",
};

export const STATUS_LABEL = {
  backlog: "Backlog",
  in_progress: "Working",
  blocked: "Blocked",
  failed: "Failed",
  testing: "Testing",
  review: "Review",
  done: "Done",
};
