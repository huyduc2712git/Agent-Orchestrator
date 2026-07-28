"""Link parser-registry: phát hiện & parse URL (Figma, GitHub, GitLab, …)."""
from .base import LinkParser
from .registry import LinkRegistry, default_registry, detect_links, steer_hints

__all__ = [
    "LinkParser",
    "LinkRegistry",
    "default_registry",
    "detect_links",
    "steer_hints",
]
