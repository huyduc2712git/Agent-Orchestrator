"""Interface chung cho mọi link parser."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LinkParser(ABC):
    """Mọi parser phải có match() + parse()."""

    name: str = "base"

    @abstractmethod
    def match(self, url: str) -> bool:
        """True nếu parser này nhận URL này."""

    @abstractmethod
    def parse(self, url: str) -> dict[str, Any]:
        """Trả dict chuẩn hóa. Luôn có key `type` và `url`."""

    def steer_build(self, parsed: dict[str, Any]) -> str:
        """Hướng dẫn ngắn gắn vào subtask build (có thể override)."""
        return ""

    def steer_qa(self, parsed: dict[str, Any]) -> str:
        """Hướng dẫn ngắn gắn vào subtask QA."""
        return ""

    def tags(self, parsed: dict[str, Any]) -> list[str]:
        return []
