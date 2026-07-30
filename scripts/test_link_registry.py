"""Smoke test link parser-registry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.links import default_registry, detect_links, steer_hints

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def main():
    cases = [
        "https://figma.com/design/abc123XYZ/My-File?node-id=12-34",
        "https://github.com/octocat/Hello-World/tree/master",
        "https://gitlab.com/gitlab-org/gitlab-runner/-/tree/main",
        "https://company.atlassian.net/browse/PROJ-42",
        "xem https://github.com/a/b và https://www.figma.com/design/fff111/Landing",
    ]

    for c in cases:
        print("---")
        print(c[:70])
        for item in detect_links(c):
            print(" ", item.get("type"), item.get("clone_url") or item.get("file_key") or item.get("issue_key"))
        print(default_registry.detect_and_parse(c.split()[0] if c.startswith("http") else c))

    print("\nHINTS:\n", steer_hints(cases[-1]))


if __name__ == "__main__":
    main()

