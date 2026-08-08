"""Phân biệt GitHub/GitLab: clone cả repo vào project vs chỉ dùng làm nguồn API/tham chiếu."""
from __future__ import annotations

import re
from typing import Any

# "BE API từ github...", "lấy API từ...", "thay API bằng..."
_REF_SOURCE = re.compile(
    r"("
    r"(?:be|backend|api)\s*(?:từ|tu|from|của|cua)\b|"
    r"(?:lấy|lay|dùng|dung|thay|integrate|tích\s*hợp)\s+"
    r"(?:(?:be|backend)\s+)?api\b|"
    r"\bapi\s*(?:từ|tu|from)\s*https?://|"
    r"thay\s*(?:bằng|bang)\s*api|"
    r"nguồn\s*api|source\s*(?:api|repo)|"
    r"dựa\s*trên\s*(?:repo|api)|based\s+on\s+(?:the\s+)?(?:repo|api)|"
    r"dùng\s*repo\s*(?:làm|cho)\s*api|use\s+(?:as\s+)?(?:the\s+)?api"
    r")",
    re.I,
)

# Clone rõ ràng cả repo workspace
_CLONE_WORKSPACE = re.compile(
    r"("
    r"\bgit\s*clone\b|"
    r"clone\s+(?:repo|repository|toàn\s*bộ|ca\s*repo)|"
    r"clone\s+https?://(?:www\.)?(?:github|gitlab)\.com|"
    r"clone\s+(?:về|vao|vào)\s+(?:thư\s*mục|folder|dir)|"
    r"fork\s+về|kéo\s*(?:cả\s*)?repo"
    r")",
    re.I,
)

# Clone FE/UI — không đồng nghĩa clone link GitHub kèm theo
_CLONE_FE_ONLY = re.compile(
    r"clone\s+(?:fe\b|frontend|ui\b|web\b|giao\s*diện)",
    re.I,
)


def extract_git_ref(url: str) -> str:
    """Lấy branch/commit từ /tree/<ref> hoặc /commit/<sha>."""
    if not url:
        return ""
    m = re.search(r"/(?:tree|commit)/([^/?#]+)", url, re.I)
    return (m.group(1) if m else "").strip()


def classify_git_intent(text: str, link: dict[str, Any] | None = None) -> str:
    """Trả 'reference_source' | 'clone_workspace'."""
    t = text or ""
    link = link or {}
    repo = (link.get("repo") or "").strip()
    clone_url = (link.get("clone_url") or link.get("url") or "").strip()

    # Clone tường minh đúng repo này
    if repo and re.search(rf"clone\s+.*\b{re.escape(repo)}\b", t, re.I):
        if not _REF_SOURCE.search(t):
            return "clone_workspace"
    if re.search(r"clone\s+https?://(?:www\.)?(?:github|gitlab)\.com", t, re.I):
        # Chỉ khi URL được clone khớp link (hoặc message chỉ có 1 git link)
        if clone_url:
            host_path = re.sub(r"^https?://|\.git$", "", clone_url, flags=re.I)
            if host_path and host_path.lower() in t.lower().replace("https://", "").replace("http://", ""):
                # "clone https://github.com/igorskh/..." → workspace
                # nhưng "clone FE ..., API từ https://github.com/..." → vẫn reference nếu có REF
                if _REF_SOURCE.search(t) or _CLONE_FE_ONLY.search(t):
                    return "reference_source"
                return "clone_workspace"

    if _REF_SOURCE.search(t):
        return "reference_source"

    # "clone FE web X, ... github.com/..." + nhắc API/BE → github = nguồn API
    if _CLONE_FE_ONLY.search(t) and re.search(r"\b(api|be|backend)\b", t, re.I):
        return "reference_source"

    if _CLONE_WORKSPACE.search(t) and not _REF_SOURCE.search(t):
        return "clone_workspace"

    # Mặc định: giữ hành vi cũ (link GitHub đơn = clone workspace) trừ khi clone FE + API
    return "clone_workspace"


def apply_git_intent(text: str, links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gắn intent/ref + sửa steer/tags cho từng link git."""
    out: list[dict[str, Any]] = []
    for link in links:
        item = dict(link)
        if item.get("type") not in ("github", "gitlab"):
            out.append(item)
            continue
        ref = item.get("ref") or extract_git_ref(item.get("url") or "")
        if ref:
            item["ref"] = ref
        intent = classify_git_intent(text, item)
        item["git_intent"] = intent
        if intent == "reference_source":
            item["clone_into_project"] = False
            ref_note = f" @ `{ref}`" if ref else ""
            link_u = item.get("url") or item.get("clone_url")
            item["steer_build"] = (
                f"NGUỒN API/THAM CHIẾU (không thay project bằng repo này): {link_u}{ref_note}. "
                "Giữ nguyên FE/project hiện có. Lấy/port API từ repo nguồn "
                f"(git_clone vào thư mục con vd. `api/` hoặc `vendor/{item.get('repo') or 'upstream'}`, "
                f"checkout đúng ref{ref_note if ref else ''}) — KHÔNG xóa UI, KHÔNG biến project_dir thành clone gốc. "
                "PIPELINE: (1) Agasa start API + smoke port trực tiếp; "
                "(2) Kid FE + same-origin /api sau khi có UI. "
                "BE-first: 502 Live host /api khi chưa FE/api_base ≠ bug — ghi note + save_start_command. "
                "Không tự commit/push."
            )
            item["steer_qa"] = (
                f"Nguồn API: {link_u}{ref_note}. Verify FE cũ vẫn còn; API mới từ nguồn đó; "
                "Live URL UI + same-origin /api; login/test theo mô tả user nếu có. "
                "Clone nhầm đè FE → VERDICT: FAIL."
            )
            tags = [t for t in (item.get("tags") or []) if t not in ("git-repo",)]
            for t in ("api-source", "github" if item.get("type") == "github" else "gitlab",
                      "same-origin-api", "extend-existing-app"):
                if t not in tags:
                    tags.append(t)
            item["tags"] = tags
        else:
            item["clone_into_project"] = True
        out.append(item)
    return out
