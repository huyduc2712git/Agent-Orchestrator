"""Các parser cụ thể: GitHub, GitLab, Figma, Jira."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from .base import LinkParser

_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def extract_raw_urls(text: str) -> list[str]:
    if not text:
        return []
    found = _URL_IN_TEXT.findall(text)
    # cũng bắt dạng github.com/... không có scheme
    bare = re.findall(
        r"(?:(?<=\s)|^)((?:www\.)?(?:github\.com|gitlab\.com|figma\.com|atlassian\.net)/[^\s<>\"')\]]+)",
        text,
        re.IGNORECASE,
    )
    for b in bare:
        u = b if b.startswith("http") else f"https://{b}"
        if u not in found:
            found.append(u)
    return found


class GitHubParser(LinkParser):
    name = "github"

    def match(self, url: str) -> bool:
        u = url.lower().strip()
        if "githubusercontent.com" in u:
            return False
        return bool(re.search(r"github\.com/[\w.-]+/[\w.-]+", u))

    def parse(self, url: str) -> dict[str, Any]:
        m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", url, re.I)
        owner = m.group(1) if m else ""
        repo = (m.group(2) if m else "").removesuffix(".git")
        clone = f"https://github.com/{owner}/{repo}.git" if owner and repo else ""
        return {
            "type": "github",
            "url": url if url.startswith("http") else f"https://github.com/{owner}/{repo}",
            "host": "github.com",
            "owner": owner,
            "repo": repo,
            "clone_url": clone,
            "path": f"{owner}/{repo}" if owner and repo else "",
        }

    def steer_build(self, parsed: dict[str, Any]) -> str:
        link = parsed.get("url") or parsed.get("clone_url")
        return (
            f"Repo GitHub: {link}. Hệ thống đã/ sẽ clone vào project dir. "
            "Dùng git_status xác nhận remote/branch; code TRÊN repo (không tạo tree song song). "
            "PIPELINE BẮT BUỘC trước khi bàn giao: (1) npm/bun install nếu có package.json; "
            "(2) build FE nếu Vite/React; (3) start backend/API nếu có (Express/server.ts/scripts.start) "
            "bằng run_command nền; (4) http_get health/API trực tiếp + Live URL UI; "
            "(5) SAME-ORIGIN: http_get /api/... trên host Live URL (preview) — path FE đang fetch. "
            "Direct :3000 OK mà preview /api 404 = CHƯA XONG (proxy/api_base) — create_bug_ticket + hướng fix. "
            "Không tự commit/push."
        )

    def steer_qa(self, parsed: dict[str, Any]) -> str:
        return (
            f"Repo: {parsed.get('clone_url') or parsed.get('url')}. "
            "Verify trên codebase đã clone. Smoke BẮT BUỘC: Live URL UI 200 + "
            "API direct (:3000/health…) + API SAME-ORIGIN trên host Live URL (/api/...). "
            "Grep fetch('/api/') trong src. Chỉ UI/direct OK mà same-origin 404 → VERDICT: FAIL "
            "+ create_bug_ticket (proxy/api_base/rewrite)."
        )

    def tags(self, parsed: dict[str, Any]) -> list[str]:
        return ["git-repo", "github"]


class GitLabParser(LinkParser):
    name = "gitlab"

    def match(self, url: str) -> bool:
        return "gitlab.com" in url.lower()

    def parse(self, url: str) -> dict[str, Any]:
        p = urlparse(url if "://" in url else f"https://{url}")
        parts = [x for x in p.path.strip("/").split("/") if x]
        clean: list[str] = []
        for part in parts:
            if part in ("-", "tree", "blob", "commit", "merge_requests", "issues", "wikis"):
                break
            clean.append(part.removesuffix(".git"))
        path = "/".join(clean) if len(clean) >= 2 else ""
        name = clean[-1] if clean else ""
        clone = f"https://gitlab.com/{path}.git" if path else ""
        return {
            "type": "gitlab",
            "url": url,
            "host": "gitlab.com",
            "owner": clean[0] if clean else "",
            "repo": name,
            "clone_url": clone,
            "path": path,
        }

    def steer_build(self, parsed: dict[str, Any]) -> str:
        link = parsed.get("url") or parsed.get("clone_url")
        return (
            f"Repo GitLab: {link}. Clone vào project dir. git_status rồi code trên repo. "
            "PIPELINE: install → build FE → start API → http_get UI + API direct + API same-origin "
            "trên host Live URL. Direct OK / preview /api 404 = chưa xong (proxy). Không tự commit/push."
        )

    def steer_qa(self, parsed: dict[str, Any]) -> str:
        return (
            f"Repo GitLab: {parsed.get('clone_url') or parsed.get('url')}. "
            "Smoke UI + API direct + API same-origin trên Live host; lệch → VERDICT: FAIL + bug ticket."
        )

    def tags(self, parsed: dict[str, Any]) -> list[str]:
        return ["git-repo", "gitlab"]


class FigmaParser(LinkParser):
    name = "figma"

    def match(self, url: str) -> bool:
        return "figma.com" in url.lower()

    def parse(self, url: str) -> dict[str, Any]:
        m = re.search(r"figma\.com/(file|design|proto|board)/([A-Za-z0-9]+)", url, re.I)
        file_key = m.group(2) if m else ""
        node_id = ""
        q = parse_qs(urlparse(url).query)
        if "node-id" in q:
            node_id = q["node-id"][0].replace("-", ":")
        return {
            "type": "figma",
            "url": url,
            "file_key": file_key,
            "node_id": node_id,
            "kind": m.group(1) if m else "",
        }

    def steer_build(self, parsed: dict[str, Any]) -> str:
        link = parsed.get("url", "")
        return (
            f"Figma: {link}. Dùng figma_get với link này TRƯỚC KHI code "
            "(layout, kích thước, mã màu, text, font). "
            "Nếu tool trả VISION fallback do rate-limit: code theo mô tả đó, không spam figma_get."
        )

    def steer_qa(self, parsed: dict[str, Any]) -> str:
        link = parsed.get("url", "")
        return (
            f"Figma reference: {link}. Dùng figma_get + screenshot_url live + "
            "inspect_render + compare_image (nếu có PNG) để đối chiếu visual."
        )

    def tags(self, parsed: dict[str, Any]) -> list[str]:
        return ["figma"]


class JiraParser(LinkParser):
    name = "jira"

    def match(self, url: str) -> bool:
        u = url.lower()
        return "atlassian.net" in u or "/browse/" in u or "jira." in u

    def parse(self, url: str) -> dict[str, Any]:
        m = re.search(r"/browse/([A-Z][A-Z0-9]+-\d+)", url, re.I)
        key = m.group(1).upper() if m else ""
        return {
            "type": "jira",
            "url": url,
            "issue_key": key,
        }

    def steer_build(self, parsed: dict[str, Any]) -> str:
        key = parsed.get("issue_key") or parsed.get("url")
        return f"Jira ticket: {key}. Bám đúng scope issue; ghi issue key trong deliverable."

    def steer_qa(self, parsed: dict[str, Any]) -> str:
        key = parsed.get("issue_key") or parsed.get("url")
        return f"Verify theo acceptance của Jira {key}."

    def tags(self, parsed: dict[str, Any]) -> list[str]:
        return ["jira"] if parsed.get("issue_key") else []
