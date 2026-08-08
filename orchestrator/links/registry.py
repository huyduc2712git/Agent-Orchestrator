"""Registry gom parser — loop match/parse."""
from __future__ import annotations

from typing import Any

from .base import LinkParser
from .git_intent import apply_git_intent
from .parsers import (
    FigmaParser,
    GitHubParser,
    GitLabParser,
    JiraParser,
    extract_raw_urls,
)


class LinkRegistry:
    def __init__(self) -> None:
        self._parsers: list[LinkParser] = []

    def register(self, parser: LinkParser) -> None:
        self._parsers.append(parser)

    def detect_and_parse(self, url: str) -> dict[str, Any]:
        candidate = (url or "").strip()
        # Nếu là câu văn bản — lấy URL đầu tiên
        if " " in candidate or "\n" in candidate:
            urls = extract_raw_urls(candidate)
            if not urls:
                return {"type": "unknown", "raw_url": url, "url": url}
            candidate = urls[0]
        for parser in self._parsers:
            if parser.match(candidate):
                parsed = parser.parse(candidate)
                parsed.setdefault("url", candidate)
                parsed["_parser"] = parser.name
                return parsed
        return {"type": "unknown", "raw_url": url, "url": candidate}

    def detect_all(self, text: str) -> list[dict[str, Any]]:
        """Tìm mọi URL trong text → parse; bỏ unknown trùng."""
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in extract_raw_urls(text):
            parsed = self.detect_and_parse(raw)
            key = f"{parsed.get('type')}:{parsed.get('clone_url') or parsed.get('file_key') or parsed.get('url')}"
            if parsed.get("type") == "unknown" or key in seen:
                continue
            seen.add(key)
            # gắn steer/tags từ parser
            for parser in self._parsers:
                if parser.name == parsed.get("_parser") or parser.match(raw):
                    parsed["steer_build"] = parser.steer_build(parsed)
                    parsed["steer_qa"] = parser.steer_qa(parsed)
                    parsed["tags"] = parser.tags(parsed)
                    break
            results.append(parsed)
        # Phân biệt clone workspace vs nguồn API/tham chiếu theo câu user
        return apply_git_intent(text, results)

    def first_of_type(self, text: str, *types: str) -> dict[str, Any] | None:
        for item in self.detect_all(text):
            if item.get("type") in types:
                return item
        return None

    def planning_hints(self, links: list[dict[str, Any]]) -> str:
        """Đoạn ngắn inject vào planning prompt thay vì hardcode Figma/Git rules."""
        if not links:
            return "(không phát hiện link Figma/GitHub/GitLab/Jira trong tin nhắn)"
        lines = ["Link đã phát hiện (bắt buộc đưa nguyên văn vào description subtask liên quan):"]
        for link in links:
            t = link.get("type")
            intent = link.get("git_intent") or ""
            intent_note = ""
            if t in ("github", "gitlab"):
                if intent == "reference_source":
                    intent_note = (
                        " — INTENT: NGUỒN API/THAM CHIẾU (KHÔNG clone đè project; "
                        "giữ FE hiện có; git_clone vào thư mục con nếu cần)"
                    )
                else:
                    intent_note = " — INTENT: clone workspace vào project dir"
            ref = link.get("ref")
            ref_note = f" ref=`{ref}`" if ref else ""
            lines.append(f"- [{t}] {link.get('url')}{ref_note}{intent_note}")
            if link.get("steer_build"):
                lines.append(f"  Build: {link['steer_build']}")
            if link.get("steer_qa"):
                lines.append(f"  QA: {link['steer_qa']}")
            if link.get("tags"):
                lines.append(f"  Tags: {', '.join(link['tags'])}")
        return "\n".join(lines)


def build_default_registry() -> LinkRegistry:
    reg = LinkRegistry()
    reg.register(GitHubParser())
    reg.register(GitLabParser())
    reg.register(FigmaParser())
    reg.register(JiraParser())
    return reg


default_registry = build_default_registry()


def detect_links(text: str) -> list[dict[str, Any]]:
    return default_registry.detect_all(text)


def steer_hints(text: str) -> str:
    return default_registry.planning_hints(detect_links(text))
