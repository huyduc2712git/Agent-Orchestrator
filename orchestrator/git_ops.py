"""Git helpers: clone/ensure repo, status — URL parse ủy quyền cho links registry."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from . import settings
from .links import default_registry


def extract_git_url(text: str) -> str | None:
    """Trả về HTTPS clone URL nếu text chứa GitHub/GitLab."""
    link = default_registry.first_of_type(text, "github", "gitlab")
    if link and link.get("clone_url"):
        return link["clone_url"]
    # một URL thuần
    parsed = default_registry.detect_and_parse(text.strip())
    if parsed.get("type") in ("github", "gitlab") and parsed.get("clone_url"):
        return parsed["clone_url"]
    return None


def parse_repo(url: str) -> dict | None:
    """{host, path, name, https_url} từ clone URL hoặc web URL."""
    parsed = default_registry.detect_and_parse(url)
    if parsed.get("type") not in ("github", "gitlab"):
        # thử extract từ chuỗi dài
        link = default_registry.first_of_type(url, "github", "gitlab")
        parsed = link or parsed
    if parsed.get("type") not in ("github", "gitlab"):
        return None
    path = parsed.get("path") or ""
    name = parsed.get("repo") or (path.split("/")[-1] if path else "")
    host = parsed.get("host") or ""
    https = parsed.get("clone_url") or ""
    if not https:
        return None
    return {
        "host": host,
        "path": path,
        "name": name,
        "https_url": https,
    }


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> tuple[int, str]:
    import os
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
        out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        return 1, f"ERROR: git timeout {timeout}s"
    except FileNotFoundError:
        return 1, "ERROR: git không có trên PATH — cài Git rồi thử lại"


def _auth_url(https_url: str) -> str:
    """Chèn token từ Settings nếu có token cho host."""
    info = parse_repo(https_url)
    if not info:
        return https_url
    token = settings.git_token_for_host(info["host"])
    if not token:
        return https_url
    # GitHub: x-access-token ; GitLab: oauth2
    user = "oauth2" if "gitlab" in info["host"] else "x-access-token"
    p = urlparse(https_url)
    netloc = f"{user}:{token}@{p.netloc}"
    return urlunparse((p.scheme, netloc, p.path, "", "", ""))


def _remote_url(repo_dir: Path) -> str:
    code, out = _run(["git", "remote", "get-url", "origin"], cwd=repo_dir)
    if code != 0:
        return ""
    # strip credentials for compare
    return re.sub(r"https://[^@]+@", "https://", out.strip())


def _same_remote(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        u = re.sub(r"https://[^@]+@", "https://", u.strip().lower())
        return u.removesuffix(".git")
    return bool(a and b and norm(a) == norm(b))


def ensure_clone(
    url: str,
    project_dir: str | Path,
    *,
    branch: str = "",
) -> dict:
    """Clone (hoặc reuse) repo vào project_dir.

    - Dir trống / chưa có .git → clone vào project_dir
    - Đã là repo đúng remote → fetch + (optional checkout branch)
    - Có file nhưng chưa git → clone vào project_dir/<repo-name>
    """
    info = parse_repo(url)
    if not info:
        return {"ok": False, "error": f"Không nhận diện GitHub/GitLab URL: {url}"}

    root = Path(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    https = info["https_url"]
    auth = _auth_url(https)

    def _status(repo: Path) -> dict:
        code, out = _run(["git", "status", "-sb"], cwd=repo)
        br = ""
        m = re.match(r"##\s+(\S+)", out)
        if m:
            br = m.group(1).split("...")[0]
        return {
            "ok": True,
            "path": str(repo),
            "remote": _remote_url(repo) or https,
            "branch": br,
            "host": info["host"],
            "repo": info["path"],
            "status": out[:800],
        }

    git_dir = root / ".git"
    if git_dir.is_dir():
        remote = _remote_url(root)
        if _same_remote(remote, https):
            _run(["git", "fetch", "--all", "--prune"], cwd=root, timeout=120)
            if branch:
                code, out = _run(["git", "checkout", branch], cwd=root)
                if code != 0:
                    code, out = _run(["git", "checkout", "-b", branch, f"origin/{branch}"], cwd=root)
                    if code != 0:
                        return {"ok": False, "error": f"checkout {branch} thất bại: {out}", "path": str(root)}
            st = _status(root)
            st["message"] = "Repo đã có sẵn — đã fetch cập nhật."
            return st
        return {
            "ok": False,
            "error": (
                f"project_dir đã là git repo khác (origin={remote or '?'}). "
                f"Chọn project trống hoặc đúng repo {info['path']}."
            ),
            "path": str(root),
        }

    # có file/folder → clone vào thư mục con
    has_content = any(root.iterdir())
    target = root / info["name"] if has_content else root

    if target.exists() and (target / ".git").is_dir():
        if _same_remote(_remote_url(target), https):
            _run(["git", "fetch", "--all", "--prune"], cwd=target, timeout=120)
            st = _status(target)
            st["message"] = f"Dùng repo có sẵn tại {target.name}."
            return st

    if target.exists() and target != root and any(target.iterdir()):
        return {"ok": False, "error": f"Thư mục {target} đã có nội dung — không clone đè."}

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [auth, str(target if target != root else root)]

    # clone vào . : git clone url .
    if target == root:
        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [auth, "."]
        code, out = _run(cmd, cwd=root, timeout=300)
    else:
        code, out = _run(cmd, cwd=root, timeout=300)

    # che token trong output
    out = re.sub(r"https://[^@\s]+@", "https://***@", out)
    if code != 0:
        hint = ""
        if "Authentication failed" in out or "could not read Username" in out or "403" in out:
            hint = " — repo private? Thêm Git token trong Settings."
        return {"ok": False, "error": f"git clone thất bại: {out}{hint}"}

    st = _status(target)
    st["message"] = f"Đã clone {info['path']} → {st['path']}"
    return st


def repo_status(project_dir: str | Path) -> dict:
    root = Path(project_dir)
    if not (root / ".git").is_dir():
        # thử 1 cấp con
        for child in sorted(root.iterdir()) if root.is_dir() else []:
            if child.is_dir() and (child / ".git").is_dir():
                root = child
                break
        else:
            return {"ok": False, "error": "Không tìm thấy .git trong project directory"}
    code, out = _run(["git", "status", "-sb"], cwd=root)
    code2, log = _run(["git", "log", "-3", "--oneline"], cwd=root)
    code3, remotes = _run(["git", "remote", "-v"], cwd=root)
    return {
        "ok": code == 0,
        "path": str(root),
        "remote": _remote_url(root),
        "status": out,
        "log": log,
        "remotes": remotes,
    }
