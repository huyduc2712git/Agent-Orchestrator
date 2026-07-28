"""Smoke test git URL parsing + clone public repo."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import git_ops

samples = [
    "https://github.com/octocat/Hello-World",
    "xem repo https://github.com/octocat/Hello-World/tree/master nhé",
    "https://gitlab.com/gitlab-org/gitlab-runner",
    "không có link",
]
for s in samples:
    print(repr(s[:50]), "->", git_ops.extract_git_url(s))

with tempfile.TemporaryDirectory() as d:
    r = git_ops.ensure_clone("https://github.com/octocat/Hello-World", d)
    print("clone:", r.get("ok"), r.get("message") or r.get("error"))
    if r.get("ok"):
        st = git_ops.repo_status(r["path"])
        print("status ok:", st.get("ok"), "remote:", st.get("remote"))
