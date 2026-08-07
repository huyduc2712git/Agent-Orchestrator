"""Resolve thư mục project / clone — không nhồi repo nặng vào workspace Orchestrator."""
from __future__ import annotations

import re
from pathlib import Path

from . import config

# Windows abs path — KHÔNG khớp `https://` (chữ `s:` trong https)
_WIN_ABS = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]):[\\/](?![\\/])([^\s\"'<>|*?]{0,240})",
)
_UNIX_ABS = re.compile(r"(?<![\w:])(/(?:Users|home|opt|var|tmp|mnt|data)[^\s\"'<>|*?]{0,240})")
_QUOTED = re.compile(
    r"""(?:vào|toi|tới|thư\s*mục|folder|path|dir(?:ectory)?)\s*[:=]?\s*["']([^"']+)["']""",
    re.I,
)
_AFTER_VAO = re.compile(
    r"""(?:clone\s+)?(?:vào|toi|tới)\s+(?:thư\s*mục\s+)?"?(?P<path>[A-Za-z]:[\\/](?![\\/])[^\s\"'<>|*?]+|/(?:Users|home|opt|var|tmp|mnt|data)[^\s\"'<>|*?]+)"?""",
    re.I,
)
_DEFAULT_PHRASE = re.compile(
    r"(?:dùng\s+)?mặc\s*định|default\s*(?:path|folder|dir)?|ok\s*default",
    re.I,
)
_URL_STRIP = re.compile(r"https?://[^\s<>\"')\]]+|git@[^\s<>\"')\]]+", re.I)


def default_projects_root() -> Path:
    """Ngoài cây Orchestrator: <parent-of-orchestrator>/AI-Projects."""
    return (config.ROOT_DIR.parent / "AI-Projects").resolve()


def is_under_orchestrator(path: str | Path) -> bool:
    """True nếu path nằm trong thư mục cài Orchestrator (workspace/repo app)."""
    try:
        p = Path(path).expanduser().resolve()
        root = config.ROOT_DIR.resolve()
        return p == root or root in p.parents
    except (OSError, RuntimeError, ValueError):
        return False


_FILE_EXT_REJECT = re.compile(
    r"\.(png|jpe?g|gif|webp|svg|ico|bmp|pdf|zip|rar|7z|tar|gz|"
    r"mp3|mp4|wav|mov|avi|mkv|exe|dll|msi|dmg|"
    r"docx?|xlsx?|pptx?|csv|json|md|txt|log|map)$",
    re.I,
)


def is_plausible_fs_path(path: str) -> bool:
    """Loại URL bị nhầm thành path (vd https:// → s:\\github.com\\...)."""
    if not path or not str(path).strip():
        return False
    s = str(path).strip().strip("\"'`")
    # markdown/artifact rác hay dính vào cuối path
    s = s.rstrip("]`'\"")
    low = s.lower().replace("/", "\\")
    # https:// → s:\...
    if re.match(r"^[a-z]:\\\\", low) or re.match(r"^[a-z]://", s.lower()):
        return False
    if "github.com" in low or "gitlab.com" in low:
        return False
    if low.endswith(".git") or "\\.git\\" in low or low.endswith("\\.git"):
        return False
    if s.lower().startswith(("http://", "https://", "git@")):
        return False
    # Path tới file (ảnh upload, …) không phải project_dir
    if _FILE_EXT_REJECT.search(s):
        return False
    try:
        p = Path(s).expanduser()
        if p.exists() and p.is_file():
            return False
    except (OSError, RuntimeError, ValueError):
        pass
    # Windows: cần drive:\something hoặc UNC
    if re.match(r"^[A-Za-z]:", s):
        rest = s[2:].lstrip("\\/")
        if not rest:
            return False  # chỉ "D:" — không đủ
        # Ổ đĩa không tồn tại (vd S:) → không dùng
        try:
            import os

            drive = s[:2].upper()
            if os.name == "nt" and drive and not os.path.exists(drive + "\\"):
                return False
        except OSError:
            return False
        return True
    if s.startswith("/") or s.startswith("~"):
        return True
    return False


def extract_target_dir(text: str) -> str | None:
    """Lấy đường dẫn tuyệt đối người dùng chỉ định trong tin nhắn (nếu có)."""
    if not text:
        return None
    # Bỏ URL trước khi quét path — tránh https:// → s:\
    cleaned = _URL_STRIP.sub(" ", text)
    # Bỏ dòng ảnh đã lưu (tránh nhầm file PNG thành project_dir)
    cleaned = re.sub(
        r"\[Ảnh đã lưu tại:[^\]]*\]",
        " ",
        cleaned,
        flags=re.I,
    )

    candidates: list[str] = []
    m = _QUOTED.search(cleaned)
    if m:
        candidates.append(m.group(1))
    m = _AFTER_VAO.search(cleaned)
    if m:
        candidates.append(m.group("path"))
    m = _WIN_ABS.search(cleaned)
    if m:
        candidates.append(m.group(0))
    m = _UNIX_ABS.search(cleaned)
    if m:
        candidates.append(m.group(1))

    for raw in candidates:
        norm = _normalize_path(raw)
        if is_plausible_fs_path(norm):
            return norm
    return None


def wants_default_path(text: str) -> bool:
    return bool(text and _DEFAULT_PHRASE.search(text))


def _normalize_path(raw: str) -> str:
    s = raw.strip().rstrip(",.;")
    s = s.strip("\"'`")
    s = s.rstrip("]`'\"")
    # bỏ trailing slash trừ drive root
    if len(s) > 3:
        s = s.rstrip("/\\")
    return str(Path(s).expanduser())


def resolve_project_dir(
    *,
    slug: str,
    explicit: str = "",
    active_project_dir: str = "",
    projects_root: str = "",
) -> tuple[str, str]:
    """Chọn thư mục làm việc / clone.

    Ưu tiên:
      1. explicit (tin nhắn / planner / form) — phải là thư mục, không phải file ảnh
      2. active project_dir nếu KHÔNG nằm trong Orchestrator
      3. projects_root/slug (Settings hoặc default ngoài Orchestrator)

    Trả (path, reason) — reason ngắn để Conan báo user.
    """
    slug = (slug or "project").strip() or "project"
    if explicit and is_plausible_fs_path(explicit):
        p = Path(explicit).expanduser()
        # Nếu lỡ trỏ vào file (hiếm) → lên thư mục cha hợp lệ
        try:
            if p.exists() and p.is_file():
                p = p.parent
        except OSError:
            pass
        return str(p), f"theo đường dẫn bạn chỉ định"
    # explicit rác (URL nhầm path / file ảnh) → bỏ qua
    if explicit and not is_plausible_fs_path(explicit):
        explicit = ""

    if active_project_dir and is_plausible_fs_path(active_project_dir):
        ap = Path(active_project_dir).expanduser()
        try:
            if ap.exists() and ap.is_file():
                ap = ap.parent
        except OSError:
            pass
        if not is_under_orchestrator(ap):
            return str(ap), f"theo project đang chọn"
        # Đã có repo thật trong workspace cũ — giữ để không phá task cũ
        try:
            if (ap / ".git").is_dir() or any(ap.glob("*")):
                return str(ap), f"giữ project_dir hiện có (đã có dữ liệu)"
        except OSError:
            pass
    elif active_project_dir and not is_plausible_fs_path(active_project_dir):
        # Settings bị ghi nhầm path ảnh — bỏ, dùng mặc định
        active_project_dir = ""

    root = Path(projects_root).expanduser() if projects_root else default_projects_root()
    target = root / slug
    return str(target), f"mặc định ngoài Orchestrator (`{root}`)"


def _is_protected_root(path: Path) -> bool:
    """Không bao giờ xóa các thư mục hệ thống / gốc cấu hình."""
    protected = {
        config.ROOT_DIR.resolve(),
        config.WORKSPACE_DIR.resolve(),
        default_projects_root().resolve(),
    }
    try:
        # projects_root custom cũng bảo vệ (chỉ xóa con)
        from . import settings as app_settings

        custom = (app_settings.projects_root() or "").strip()
        if custom:
            protected.add(Path(custom).expanduser().resolve())
    except Exception:
        pass
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return True
    if resolved in protected:
        return True
    # drive root / home
    if resolved.parent == resolved:
        return True
    home = Path.home().resolve()
    if resolved == home:
        return True
    return False


def can_delete_project_dir(path: str | Path, slug: str = "") -> tuple[bool, str]:
    """Cho phép xóa thư mục project nếu an toàn."""
    if not path:
        return False, "không có path"
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as e:
        return False, str(e)
    if not p.exists():
        return False, "không tồn tại"
    if not p.is_dir():
        return False, "không phải thư mục"
    if _is_protected_root(p):
        return False, "path được bảo vệ (root/config)"

    slug_l = (slug or "").lower().strip()
    name_ok = (not slug_l) or (p.name.lower() == slug_l) or (slug_l in p.name.lower())

    under_ws_projects = False
    try:
        ws_proj = (config.WORKSPACE_DIR / "projects").resolve()
        under_ws_projects = p == ws_proj / p.name and ws_proj in p.parents
        if ws_proj in p.parents or p.parent == ws_proj:
            under_ws_projects = True
    except (OSError, RuntimeError):
        pass

    under_orch = is_under_orchestrator(p)
    under_default_root = False
    try:
        under_default_root = default_projects_root().resolve() in p.parents
    except (OSError, RuntimeError):
        pass
    under_custom_root = False
    try:
        from . import settings as app_settings

        custom = (app_settings.projects_root() or "").strip()
        if custom:
            cr = Path(custom).expanduser().resolve()
            under_custom_root = cr in p.parents
    except Exception:
        pass

    if under_ws_projects or under_orch or under_default_root or under_custom_root:
        if name_ok or under_ws_projects or under_default_root or under_custom_root:
            return True, "ok"
    # Path ngoài nhưng tên khớp slug + đủ sâu (tránh xóa nhầm)
    if name_ok and len(p.parts) >= 3:
        return True, "ok"
    return False, "path không đủ an toàn để xóa tự động"


def safe_remove_project_dir(path: str | Path, slug: str = "") -> dict:
    """Xóa thư mục project trên đĩa nếu được phép. Trả {ok, path, error?}."""
    import os
    import shutil
    import stat
    import time

    ok, reason = can_delete_project_dir(path, slug)
    if not ok:
        return {"ok": False, "path": str(path or ""), "error": reason}
    p = Path(path).expanduser().resolve()

    # Windows: npm/dev/git thường giữ lock → Access Denied nếu không dừng trước
    killed = _stop_processes_using_dir(p)

    def _onerror(func, path_str, _exc_info):
        try:
            os.chmod(path_str, stat.S_IWRITE)
            func(path_str)
        except OSError:
            pass

    last_err: Exception | None = None
    for attempt in range(4):
        if not p.exists():
            return {
                "ok": True,
                "path": str(p),
                "killed_processes": killed,
            }
        try:
            shutil.rmtree(p, onerror=_onerror)
            if not p.exists():
                return {
                    "ok": True,
                    "path": str(p),
                    "killed_processes": killed,
                }
        except OSError as e:
            last_err = e
        # Thử đổi tên rồi xóa (đôi khi bypass lock tên cũ)
        if p.exists() and attempt == 1:
            trash = p.parent / f".trash-{p.name}-{int(time.time())}"
            try:
                p.rename(trash)
                p = trash
            except OSError:
                pass
        time.sleep(0.4 * (attempt + 1))
        if attempt == 2:
            killed.extend(_stop_processes_using_dir(p))

    err = str(last_err) if last_err else "không xóa được (file đang bị process khác giữ)"
    hint = (
        " — có thể npm run dev / node / terminal vẫn mở trong thư mục này. "
        "Đóng process đó rồi xóa lại, hoặc restart Orchestrator."
    )
    return {
        "ok": False,
        "path": str(p),
        "error": err + hint,
        "killed_processes": killed,
    }


def _stop_processes_using_dir(target: Path) -> list[str]:
    """Dừng process có CommandLine/cwd chứa path project (Windows). Không đụng orchestrator.main."""
    import os
    import sys

    killed: list[str] = []
    if sys.platform != "win32":
        return killed
    try:
        import subprocess

        needle = str(target).lower().replace("/", "\\")
        out = subprocess.check_output(
            ["wmic", "process", "get", "ProcessId,CommandLine", "/FORMAT:CSV"],
            stderr=subprocess.DEVNULL,
            errors="ignore",
            timeout=15,
        )
    except Exception:
        return killed

    my_pid = os.getpid()
    for line in out.splitlines():
        low = line.lower()
        if needle not in low:
            continue
        # Không tự kill process orchestrator đang chạy
        if "orchestrator.main" in low or "orchestrator\\main" in low:
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[-1].strip())
        except ValueError:
            continue
        if pid <= 0 or pid == my_pid:
            continue
        try:
            os.kill(pid, 9)
            killed.append(f"pid={pid}")
        except OSError:
            pass
    return killed
