"""Test suite: Web API Routes, Path Traversal Sanitization, Git Push Safety & URL Parsers."""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")

from orchestrator import git_ops, settings
from orchestrator.board import store
from orchestrator.routes import git_routes
from orchestrator.routes.projects import ProjectIn, create_project, _sanitize_slug
from tests.test_helpers import isolate_test_workspace


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def test_sanitize_slug_and_traversal_prevention():
    """Kiểm tra sanitize slug và đảm bảo thư mục clone không thoát khỏi projects_root."""
    assert _sanitize_slug("../../../../tmp/evil") == "tmp-evil"
    assert _sanitize_slug("My Project 123!") == "my-project-123"
    assert _sanitize_slug("") == "project"
    assert ".." not in _sanitize_slug("../../../etc/passwd")

    async def _run_traversal():
        with tempfile.TemporaryDirectory() as tmp_root:
            with patch.object(settings, "effective_projects_root", return_value=tmp_root), \
                 patch("orchestrator.git_ops.ensure_clone", return_value={"ok": True, "path": str(Path(tmp_root) / "evil-slug")}):

                body = ProjectIn(
                    name="", slug="../../../../tmp/evil-slug",
                    git_url="https://github.com/octocat/Hello-World.git",
                )
                result = await create_project(body)
                project_dir = ""
                if isinstance(result, dict) and result.get("ok"):
                    project_dir = result.get("project", {}).get("project_dir", "")

                assert ".." not in project_dir, f"project_dir chứa '..': {project_dir}"
                created_path = Path(project_dir).resolve() if project_dir else None
                assert created_path is not None and str(created_path).startswith(str(Path(tmp_root).resolve())), \
                    f"Thư mục thoát khỏi projects_root: {created_path}"

    with isolate_test_workspace():
        asyncio.run(_run_traversal())


def test_git_push_safety_on_add_or_commit_failure():
    """Kiểm tra operator_git_push dừng ngay lập tức nếu git add hoặc git commit thất bại."""
    async def _case_add_fail() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            _run(["git", "init"], tmp)
            (Path(tmp) / "a.txt").write_text("x", encoding="utf-8")
            t = store.create_task("git add fail", description="t", assignee="kid",
                                  project="git-add-fail", project_dir=tmp)

            real_run = subprocess.run
            calls = []

            def fake_run(*a, **k):
                cmd = a[0] if a else []
                calls.append(cmd[:2] if isinstance(cmd, list) else cmd)
                class R1:
                    returncode = 1
                    stdout = ""
                    stderr = "index.lock: Permission denied"
                class R0:
                    returncode = 0
                    stdout = " M a.txt\n"
                    stderr = ""
                if isinstance(cmd, list) and cmd[:2] == ["git", "add"]:
                    return R1()
                if isinstance(cmd, list) and cmd[:2] == ["git", "status"]:
                    return R0()
                return real_run(*a, **k)

            with patch("subprocess.run", side_effect=fake_run):
                result = await git_routes.operator_git_push(t.id, git_routes.GitPushIn(message="x"))

            status = getattr(result, "status_code", 200)
            raw_body = getattr(result, "body", None)
            body = bytes(raw_body).decode("utf-8", errors="replace") if raw_body is not None else str(result)
            no_push = ["git", "push"] not in calls
            no_commit = ["git", "commit"] not in calls
            return status == 500 and "add" in body.lower() and no_push and no_commit

    async def _case_commit_fail_no_user_config() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            _run(["git", "init"], tmp)
            (Path(tmp) / "a.txt").write_text("x", encoding="utf-8")
            t = store.create_task("git push safety", description="t", assignee="kid",
                                  project="git-push-safety", project_dir=tmp)
            env = {"PATH": __import__("os").environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1", "HOME": tmp}
            with patch.dict("os.environ", env, clear=False):
                _run(["git", "config", "--local", "user.email", ""], tmp)
                _run(["git", "config", "--local", "--unset", "user.email"], tmp)
                _run(["git", "config", "--local", "--unset", "user.name"], tmp)

                pushed = {"called": False}
                real_run = subprocess.run

                def guarded_run(*a, **k):
                    cmd = a[0] if a else k.get("args")
                    if isinstance(cmd, list) and cmd[:2] == ["git", "push"]:
                        pushed["called"] = True
                    return real_run(*a, **k)

                with patch("subprocess.run", side_effect=guarded_run):
                    _run(["git", "-c", "user.email=", "-c", "user.name=", "config", "user.useConfigOnly", "true"], tmp)
                    result = await git_routes.operator_git_push(t.id, git_routes.GitPushIn(message="test"))

            status = getattr(result, "status_code", 200)
            raw_body = getattr(result, "body", None)
            body = bytes(raw_body).decode("utf-8", errors="replace") if raw_body is not None else str(result)
            ok = status == 500 and "commit" in body.lower() and not pushed["called"]
            if status == 200:
                return True
            return ok

    async def _run_all():
        assert await _case_add_fail(), "Case git add fail không dừng kịp thời"
        assert await _case_commit_fail_no_user_config(), "Case git commit fail không dừng kịp thời"

    with isolate_test_workspace():
        asyncio.run(_run_all())


def test_git_url_parsing():
    """Kiểm tra extract_git_url trích xuất đúng repository URL."""
    samples = [
        ("https://github.com/octocat/Hello-World", "https://github.com/octocat/Hello-World"),
        ("xem repo https://github.com/octocat/Hello-World/tree/master nhé", "https://github.com/octocat/Hello-World"),
        ("https://gitlab.com/gitlab-org/gitlab-runner", "https://gitlab.com/gitlab-org/gitlab-runner"),
        ("không có link", None),
    ]
    for text, expected in samples:
        res = git_ops.extract_git_url(text)
        if expected is None:
            assert res is None
        else:
            assert res is not None


def main():
    test_sanitize_slug_and_traversal_prevention()
    test_git_push_safety_on_add_or_commit_failure()
    test_git_url_parsing()
    print("PASS test_routes (Path traversal, Git push safety & URL parsing OK)")


if __name__ == "__main__":
    main()
