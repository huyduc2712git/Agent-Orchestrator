"""Bộ tool thực thi thật cho agent: file, command, search, http, figma, board.

Tool surface lấy cảm hứng / tương thích [DeepSeek-Reasonix](https://github.com/esengine/DeepSeek-Reasonix)
(glob, grep, edit_file, multi_edit, move_file, web_fetch, todo_write; alias bash/ls).
"""
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from .. import config, settings
from ..board import store
from ..board.models import SEVERITIES, Task
from ..qa import browser as qa_browser

log = logging.getLogger("tools")

# Reasonix name → handler nội bộ (args được normalize)
_TOOL_ALIASES = {
    "bash": "run_command",
    "ls": "list_dir",
}

# ---------- OpenAI tool schemas ----------

TOOL_SCHEMAS: dict[str, dict] = {
    "read_file": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Đọc file text trong project (Reasonix-style). Path tương đối. "
                "Optional offset/limit (1-based line) để đọc từng trang; mỗi dòng có số dòng."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "Dòng bắt đầu 1-based (optional)"},
                    "limit": {"type": "integer", "description": "Số dòng tối đa (optional)"},
                },
                "required": ["path"],
            },
        },
    },
    "write_file": {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Ghi (tạo mới hoặc ghi đè) một file trong project directory. Tự tạo thư mục cha nếu chưa có.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "list_dir": {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "Liệt kê file/thư mục (alias Reasonix: ls). recursive=true → depth-first, bỏ .git/node_modules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Mặc định gốc project"},
                    "recursive": {"type": "boolean", "description": "Mặc định false"},
                },
            },
        },
    },
    "ls": {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "Alias Reasonix của list_dir — liệt kê thư mục.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                },
            },
        },
    },
    "glob": {
        "type": "function",
        "function": {
            "name": "glob",
            "description": (
                "Reasonix glob: tìm file theo pattern (vd **/*.tsx, src/**/*.css). "
                "Bỏ qua node_modules/.git/dist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern"},
                    "path": {"type": "string", "description": "Thư mục gốc tương đối (mặc định .)"},
                },
                "required": ["pattern"],
            },
        },
    },
    "grep": {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Reasonix grep: tìm regex trong file/thư mục. Trả path:line:text, tối đa 200 hits. "
                "Ưu tiên hơn shell grep."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression"},
                    "path": {"type": "string", "description": "File hoặc thư mục (mặc định .)"},
                    "glob": {"type": "string", "description": "Lọc file vd *.ts"},
                    "case_insensitive": {"type": "boolean"},
                },
                "required": ["pattern"],
            },
        },
    },
    "search_files": {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Tìm chuỗi văn bản (substring, case-insensitive). Regex dùng tool grep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "glob": {"type": "string", "description": "Pattern lọc file, vd *.py, *.html. Mặc định tất cả."},
                },
                "required": ["query"],
            },
        },
    },
    "edit_file": {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Reasonix edit_file: thay đúng một lần old_string → new_string trong file. "
                "old_string phải xuất hiện đúng 1 lần (thêm context nếu trùng)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    "multi_edit": {
        "type": "function",
        "function": {
            "name": "multi_edit",
            "description": (
                "Reasonix multi_edit: áp dụng tuần tự nhiều edit trên một file trong bộ nhớ; "
                "chỉ ghi đĩa nếu tất cả thành công."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
        },
    },
    "move_file": {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Reasonix move_file: đổi tên/di chuyển file trong project (không dùng shell mv).",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                },
                "required": ["source_path", "destination_path"],
            },
        },
    },
    "run_command": {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Chạy một lệnh PowerShell trong project directory (timeout "
                f"{config.COMMAND_TIMEOUT_SECONDS}s). Alias Reasonix: bash. "
                "KHÔNG chạy lệnh chờ vô hạn (dev server foreground) — nếu cần server, "
                "chạy dạng Start-Process node ... -RedirectStandardOutput 'server.log' (KHÔNG dùng -NoNewWindow)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    "bash": {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Alias Reasonix của run_command — chạy shell trong project dir.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    "http_get": {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "HTTP GET một URL (verify server/trang). Trả status + phần đầu body thô.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    "web_fetch": {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Reasonix web_fetch: GET URL, HTML → text đọc được; JSON/text giữ nguyên. "
                "Dùng đọc docs/API ngoài filesystem."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "description": "Mặc định 8000"},
                },
                "required": ["url"],
            },
        },
    },
    "todo_write": {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": (
                "Reasonix todo_write: ghi/cập nhật task list có cấu trúc cho công việc hiện tại. "
                "Gửi FULL list mỗi lần (thay thế list cũ). Giữ đúng 1 item in_progress."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                                },
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    "figma_get": {
        "type": "function",
        "function": {
            "name": "figma_get",
            "description": (
                "Lấy thiết kế từ Figma (token trong Settings). Ưu tiên cây node (màu hex, font, layout). "
                "Nếu API nodes bị 429/lỗi: tự export PNG frame + Vision mô tả UI — dùng kết quả đó để code, "
                "KHÔNG gọi figma_get lại liên tục. Truyền url có node-id hoặc node_id rõ ràng. "
                "Khi project có MCP: ưu tiên mcp_call get_design_context trước."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Link Figma (figma.com/design/... hoặc /file/...) hoặc file key"},
                    "node_id": {"type": "string", "description": "Tùy chọn: id node (vd '12:34' hoặc '12-34')"},
                },
                "required": ["url"],
            },
        },
    },
    "mcp_list_tools": {
        "type": "function",
        "function": {
            "name": "mcp_list_tools",
            "description": (
                "Liệt kê tools trên MCP server của project (mcp_url trong Settings). "
                "Mặc định builtin http://127.0.0.1:PORT/mcp/figma (get_design_context, get_screenshot, …)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "mcp_call": {
        "type": "function",
        "function": {
            "name": "mcp_call",
            "description": (
                "Gọi một MCP tool. Figma builtin: get_design_context / get_metadata / get_screenshot "
                "(arguments cần url Figma có node-id). Dùng TRƯỚC figma_get khi project đã gắn MCP."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "description": "Tên tool MCP, vd get_design_context",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments JSON object (vd {\"url\": \"https://figma.com/design/...\"})",
                    },
                    "arguments_json": {
                        "type": "string",
                        "description": "Thay arguments bằng chuỗi JSON nếu model tiện serialize",
                    },
                },
                "required": ["tool"],
            },
        },
    },
    "git_clone": {
        "type": "function",
        "function": {
            "name": "git_clone",
            "description": (
                "Clone (hoặc reuse) repo GitHub/GitLab vào project directory. "
                "Hỗ trợ token private trong Settings → Git tokens. "
                "Trả về path, remote, branch, status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Link GitHub/GitLab (https://github.com/owner/repo)"},
                    "branch": {"type": "string", "description": "Branch tùy chọn"},
                },
                "required": ["url"],
            },
        },
    },
    "git_status": {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Xem git status / remote / log gần đây trong project directory (repo đã clone).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "run_skill": {
        "type": "function",
        "function": {
            "name": "run_skill",
            "description": (
                "Load playbook body của một skill theo name (vd explore, vite-fe-smoke, "
                "frontend-ui-engineering). Chỉ trả markdown checklist — không spawn subagent. "
                "Giới hạn vài lần / task. Dùng khi skill index gợi ý playbook liên quan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Bare skill id (không có @), vd replace-brand-assets",
                    },
                },
                "required": ["name"],
            },
        },
    },
    "post_message": {
        "type": "function",
        "function": {
            "name": "post_message",
            "description": "Đăng một message/comment vào task hiện tại trên board (deliverable, tiến độ, phát hiện).",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    },
    "search_tasks": {
        "type": "function",
        "function": {
            "name": "search_tasks",
            "description": "Tìm task/bug trên board theo từ khóa — BẮT BUỘC dùng trước khi tạo bug để tránh trùng lặp.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    "create_bug_ticket": {
        "type": "function",
        "function": {
            "name": "create_bug_ticket",
            "description": (
                "Tạo bug ticket chính thức với schema bắt buộc. Chỉ dùng sau khi đã "
                "search_tasks để chắc chắn chưa có ticket trùng. Bug sẽ tự động được "
                "link 'related' về task hiện tại (QA/Security). "
                "Khi QA FAIL một build sub cụ thể: BẮT BUỘC truyền related_subtask_id "
                "(vd sub-2534) để gắn bug về đúng sub nguồn. "
                "area: frontend→Kid, backend→Agasa."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string", "description": "Evidence, expected vs actual, file/line liên quan"},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "repro_steps": {"type": "string"},
                    "area": {
                        "type": "string",
                        "enum": ["frontend", "backend"],
                        "description": "'frontend' -> Kid; 'backend' (API/DB/auth/SQL injection/IDOR) -> Agasa.",
                    },
                    "related_subtask_id": {
                        "type": "string",
                        "description": (
                            "Id build subtask bị lỗi (vd sub-2534). "
                            "Heiji QA FAIL theo checklist từng sub phải điền."
                        ),
                    },
                },
                "required": ["title", "description", "severity", "repro_steps"],
            },
        },
    },
    "screenshot_url": {
        "type": "function",
        "function": {
            "name": "screenshot_url",
            "description": (
                "Mở URL live trong trình duyệt headless (Playwright), chụp screenshot PNG "
                "và lưu vào artifacts của task. Dùng cho Visual QA Report. "
                "Hỗ trợ viewport desktop (1440x900), mobile (375x812), hoặc tùy chỉnh. "
                "Có thể click selector trước khi chụp (vd tab filter) hoặc scroll_y để chụp mid-page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Live URL cần chụp (http://...)"},
                    "name": {"type": "string", "description": "Tên file slug, vd 'desktop-top' hoặc 'mobile-tab-processing'"},
                    "viewport": {"type": "string", "enum": ["desktop", "mobile", "tablet"], "description": "Mặc định desktop"},
                    "full_page": {"type": "boolean", "description": "Chụp full page scroll. Mặc định true."},
                    "wait_ms": {"type": "integer", "description": "Chờ sau load (ms). Mặc định 1500."},
                    "click_selector": {"type": "string", "description": "CSS selector click trước khi chụp (tùy chọn)"},
                    "scroll_y": {"type": "integer", "description": "Scroll Y trước khi chụp (tùy chọn)"},
                },
                "required": ["url", "name"],
            },
        },
    },
    "inspect_render": {
        "type": "function",
        "function": {
            "name": "inspect_render",
            "description": (
                "Kiểm tra render/CSS/console trên URL live. Trả bảng CSS/RENDER VERIFICATION: "
                "body background, h1, brand color, invisible text, broken images, console errors. "
                "Có thể click tab/filter rồi đếm selector (vd chỉ còn 1 order khi filter 'Đang xử lý')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "viewport": {"type": "string", "enum": ["desktop", "mobile", "tablet"]},
                    "click_selector": {"type": "string", "description": "Click trước khi inspect (vd tab filter)"},
                    "expect_selector": {"type": "string", "description": "CSS selector đếm sau click"},
                    "expect_min_count": {"type": "integer", "description": "Số phần tử tối thiểu mong đợi"},
                    "brand_hex": {"type": "string", "description": "Màu brand mong đợi, vd #ee3434"},
                    "body_bg_hex": {"type": "string", "description": "Màu nền body mong đợi, vd #f9fafb"},
                },
                "required": ["url"],
            },
        },
    },
    "compare_image": {
        "type": "function",
        "function": {
            "name": "compare_image",
            "description": (
                "So sánh screenshot đã chụp (trong artifacts hoặc project) với ảnh reference "
                "(PNG export Figma hoặc mockup trong project). Trả similarity % và diff image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "screenshot": {"type": "string", "description": "Path screenshot (tên trong artifacts hoặc path trong project)"},
                    "reference": {"type": "string", "description": "Path ảnh reference trong project directory"},
                    "threshold": {"type": "number", "description": "Ngưỡng similarity PASS (0-1). Mặc định 0.92."},
                },
                "required": ["screenshot", "reference"],
            },
        },
    },
    "save_start_command": {
        "type": "function",
        "function": {
            "name": "save_start_command",
            "description": (
                "Lưu lệnh khởi động backend/server cho project hiện tại. "
                "Orchestrator sẽ tự động chạy lệnh này khi khởi động lần sau. "
                "GỌI SAU KHI đã start server thành công và verify health OK."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Lệnh start server đầy đủ, vd: 'npm run start' hoặc 'node dist/server.cjs'"},
                },
                "required": ["command"],
            },
        },
    },
}


def schemas_for(tool_names: list[str]) -> list[dict]:
    out = []
    for n in tool_names:
        sch = TOOL_SCHEMAS.get(n)
        if sch:
            out.append(sch)
        else:
            log.warning("schema thiếu cho tool %s", n)
    return out


# ---------- Executor ----------

class ToolContext:
    """Ngữ cảnh thực thi tool của một agent trên một task cụ thể."""

    def __init__(self, agent: str, task: Task):
        self.agent = agent
        self._todos: list[dict] = []
        self.task = task
        if task.project_dir:
            self.project_dir = Path(task.project_dir)
        else:
            self.project_dir = config.WORKSPACE_DIR / "projects" / task.project
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, rel_path: str) -> Path:
        p = (self.project_dir / rel_path).resolve()
        if not str(p).startswith(str(self.project_dir.resolve())):
            raise ValueError(f"Path ra ngoài project directory: {rel_path}")
        return p

    def _artifact_dir(self) -> Path:
        d = config.ARTIFACTS_DIR / self.task.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _artifact_url(self, filename: str) -> str:
        return f"{config.BASE_URL}/artifacts/{self.task.id}/{filename}"

    def _resolve_artifact_or_project(self, path: str) -> Path:
        """Path có thể là tên file trong artifacts hoặc path tương đối trong project."""
        art = self._artifact_dir() / path
        if art.is_file():
            return art
        return self._resolve(path)

    def execute(self, name: str, args: dict) -> str:
        try:
            canon = _TOOL_ALIASES.get(name, name)
            # Normalize Reasonix bash args if needed
            if name == "bash" and "command" not in args and "cmd" in args:
                args = {**args, "command": args.get("cmd")}
            handler = getattr(self, f"_tool_{canon}", None)
            if handler is None:
                return f"ERROR: tool không tồn tại: {name}"
            # Drop unknown kwargs that models sometimes invent
            import inspect
            sig = inspect.signature(handler)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                call_args = args
            else:
                allowed = set(sig.parameters)
                call_args = {k: v for k, v in (args or {}).items() if k in allowed}
            out = handler(**call_args)
            if len(out) > config.MAX_TOOL_OUTPUT_CHARS:
                out = out[: config.MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"
            return out
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    # --- file tools ---

    def _tool_read_file(self, path: str, offset: int | None = None, limit: int | None = None) -> str:
        p = self._resolve(path)
        if not p.is_file():
            return f"ERROR: file không tồn tại: {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        start = 1
        if offset is not None:
            start = max(1, int(offset))
        end = total + 1
        if limit is not None:
            end = min(total + 1, start + max(0, int(limit)))
        elif offset is not None:
            end = total + 1
        if offset is None and limit is None:
            # Giữ behavior cũ cho file ngắn; file dài vẫn đánh số dòng
            if total <= 400:
                return text
            start, end = 1, 400
        chunk = lines[start - 1 : end - 1]
        numbered = "\n".join(f"{i}|{line}" for i, line in enumerate(chunk, start))
        trailer = f"\n\n[lines {start}-{start + len(chunk) - 1} of {total}]"
        if end <= total:
            trailer += f" — còn {total - end + 1} dòng; tăng offset để đọc tiếp"
        return numbered + trailer

    def _tool_write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: đã ghi {len(content)} ký tự vào {path}"

    def _tool_list_dir(self, path: str = ".", recursive: bool = False) -> str:
        p = self._resolve(path)
        if not p.is_dir():
            return f"ERROR: thư mục không tồn tại: {path}"
        lines = []
        if not recursive:
            for child in sorted(p.iterdir()):
                try:
                    rel = child.relative_to(self.project_dir)
                except ValueError:
                    rel = Path(child.name)
                if child.is_dir():
                    lines.append(f"{rel.as_posix()}/")
                else:
                    try:
                        sz = child.stat().st_size
                    except OSError:
                        sz = 0
                    lines.append(f"{rel.as_posix()}  ({sz} B)")
            return "\n".join(lines) or "(trống)"

        # recursive depth-first
        count = 0
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in self._SEARCH_SKIP_DIRS and not d.startswith(".")]
            root_p = Path(root)
            for name in sorted(files):
                fp = root_p / name
                try:
                    rel = fp.relative_to(self.project_dir).as_posix()
                except ValueError:
                    continue
                if any(part in self._SEARCH_SKIP_DIRS for part in Path(rel).parts):
                    continue
                lines.append(rel)
                count += 1
                if count >= 500:
                    lines.append("...[max 500 entries — thu hẹp path]")
                    return "\n".join(lines)
        return "\n".join(lines) or "(trống)"

    # Bỏ qua khi search — tránh treo hàng phút trong node_modules/dist
    _SEARCH_SKIP_DIRS = frozenset({
        "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", ".nuxt", "coverage", ".turbo", ".cache",
        "qa-shots", ".playwright",
    })

    def _iter_project_files(self, root: Path, glob_pat: str = "**/*"):
        if "**" not in glob_pat and not any(ch in glob_pat for ch in "*?["):
            glob_pat = f"**/{glob_pat}"
        elif "**" not in glob_pat and "/" not in glob_pat and "\\" not in glob_pat:
            glob_pat = f"**/{glob_pat}"
        for f in root.glob(glob_pat):
            if not f.is_file():
                continue
            try:
                rel_parts = f.relative_to(self.project_dir).parts
            except ValueError:
                continue
            if any(p in self._SEARCH_SKIP_DIRS for p in rel_parts):
                continue
            yield f

    def _tool_glob(self, pattern: str, path: str = ".") -> str:
        root = self._resolve(path or ".")
        if not root.exists():
            return f"ERROR: path không tồn tại: {path}"
        if root.is_file():
            root = root.parent
        pat = pattern or "**/*"
        hits = []
        for f in self._iter_project_files(root, pat):
            try:
                hits.append(f.relative_to(self.project_dir).as_posix())
            except ValueError:
                continue
            if len(hits) >= 200:
                hits.append("...[max 200]")
                break
        return "\n".join(hits) or "(không tìm thấy)"

    def _tool_grep(
        self,
        pattern: str,
        path: str = ".",
        glob: str = "**/*",
        case_insensitive: bool = False,
    ) -> str:
        root = self._resolve(path or ".")
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            return f"ERROR: regex không hợp lệ: {e}"
        hits: list[str] = []
        files = []
        if root.is_file():
            files = [root]
        else:
            files = list(self._iter_project_files(root, glob or "**/*"))
        scanned = 0
        for f in files:
            scanned += 1
            if scanned > 800:
                hits.append("...[đã quét 800 file — thu hẹp path/glob]")
                break
            try:
                if f.stat().st_size > 1_000_000:
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                rel = f.relative_to(self.project_dir).as_posix()
            except ValueError:
                rel = str(f)
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n...[max 200 hits]"
        return "\n".join(hits) or "(không tìm thấy)"

    def _tool_edit_file(self, path: str, old_string: str, new_string: str) -> str:
        p = self._resolve(path)
        if not p.is_file():
            return f"ERROR: file không tồn tại: {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_string)
        if count == 0:
            return "ERROR: old_string không khớp — thêm context hoặc đọc lại file"
        if count > 1:
            return f"ERROR: old_string khớp {count} lần — cần unique (thêm dòng quanh)"
        p.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
        return f"OK: edit_file {path} (−{len(old_string)} +{len(new_string)} chars)"

    def _tool_multi_edit(self, path: str, edits: list) -> str:
        p = self._resolve(path)
        if not p.is_file():
            return f"ERROR: file không tồn tại: {path}"
        if not edits:
            return "ERROR: edits rỗng"
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, ed in enumerate(edits):
            old = ed.get("old_string", "")
            new = ed.get("new_string", "")
            n = text.count(old)
            if n == 0:
                return f"ERROR: multi_edit bước {i + 1}: old_string không khớp — file chưa ghi"
            if n > 1:
                return f"ERROR: multi_edit bước {i + 1}: old_string khớp {n} lần"
            text = text.replace(old, new, 1)
        p.write_text(text, encoding="utf-8")
        return f"OK: multi_edit {path} — {len(edits)} edits"

    def _tool_move_file(self, source_path: str, destination_path: str) -> str:
        src = self._resolve(source_path)
        dst = self._resolve(destination_path)
        if not src.exists():
            return f"ERROR: source không tồn tại: {source_path}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            return f"ERROR: destination đã tồn tại: {destination_path}"
        shutil.move(str(src), str(dst))
        return f"OK: moved {source_path} → {destination_path}"

    def _tool_web_fetch(self, url: str, max_chars: int = 8000) -> str:
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(url)
        except Exception as e:
            return f"ERROR: web_fetch failed: {e}"
        ctype = (resp.headers.get("content-type") or "").lower()
        body = resp.text or ""
        if "html" in ctype or body.lstrip()[:32].lower().startswith("<!DOCTYPE html") or "<html" in body[:500].lower():
            # Strip scripts/styles then tags
            cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", body)
            cleaned = re.sub(r"(?is)<br\s*/?>", "\n", cleaned)
            cleaned = re.sub(r"(?is)</p>", "\n", cleaned)
            cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
            cleaned = re.sub(r"[ \t]+", " ", cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            body = cleaned
        limit = max(500, int(max_chars or 8000))
        if len(body) > limit:
            body = body[:limit] + "\n...[truncated]"
        return f"status={resp.status_code} content-type={ctype}\n\n{body}"

    def _tool_todo_write(self, todos: list) -> str:
        if not isinstance(todos, list) or not todos:
            return "ERROR: todos phải là mảng không rỗng"
        normalized = []
        in_prog = 0
        for i, t in enumerate(todos):
            if not isinstance(t, dict):
                return f"ERROR: todos[{i}] không phải object"
            st = str(t.get("status") or "pending").lower()
            if st not in ("pending", "in_progress", "completed", "cancelled"):
                return f"ERROR: status không hợp lệ: {st}"
            if st == "in_progress":
                in_prog += 1
            normalized.append({
                "id": str(t.get("id") or f"t{i + 1}"),
                "content": str(t.get("content") or "").strip(),
                "status": st,
            })
            if not normalized[-1]["content"]:
                return f"ERROR: todos[{i}].content rỗng"
        if in_prog > 1:
            return "ERROR: chỉ được đúng 1 item in_progress"
        self._todos = normalized
        lines = ["# Agent todos", ""]
        for t in normalized:
            mark = {"pending": "○", "in_progress": "▶", "completed": "✓", "cancelled": "✕"}.get(t["status"], "?")
            lines.append(f"{mark} [{t['status']}] {t['id']}: {t['content']}")
        blob = "\n".join(lines)
        try:
            store.add_event(self.task.id, self.agent, "system", f"todo_write:\n{blob}")
        except Exception:
            pass
        return blob

    def _tool_search_files(self, query: str, glob: str = "**/*") -> str:
        if "**" not in glob:
            glob = f"**/{glob}"
        hits = []
        q = query.lower()
        scanned = 0
        max_files = 800
        for f in self.project_dir.glob(glob):
            if not f.is_file():
                continue
            try:
                rel_parts = f.relative_to(self.project_dir).parts
            except ValueError:
                continue
            if any(p in self._SEARCH_SKIP_DIRS for p in rel_parts):
                continue
            try:
                if f.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            scanned += 1
            if scanned > max_files:
                extra = f"\n...[đã quét {max_files} file — thu hẹp glob, vd src/**/*.tsx]"
                return ("\n".join(hits) + extra) if hits else f"(không tìm thấy){extra}"
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if q in line.lower():
                        hits.append(f"{f.relative_to(self.project_dir)}:{i}: {line.strip()[:200]}")
                        if len(hits) >= 50:
                            return "\n".join(hits) + "\n...[max 50 hits]"
            except OSError:
                continue
        return "\n".join(hits) or "(không tìm thấy)"

    # --- command / http ---

    def _detect_shell(self) -> tuple[list[str], str]:
        """Phát hiện shell khả dụng trên máy đang chạy orchestrator."""
        ps = shutil.which("powershell")
        if ps:
            # -WindowStyle Hidden: không hiện cửa sổ console PowerShell
            return [
                ps, "-NoProfile", "-WindowStyle", "Hidden",
                "-ExecutionPolicy", "Bypass", "-Command",
            ], "powershell"
        pwsh = shutil.which("pwsh")
        if pwsh:
            return [
                pwsh, "-NoProfile", "-WindowStyle", "Hidden", "-Command",
            ], "pwsh"
        sh = shutil.which("bash") or shutil.which("sh")
        if sh:
            return [sh, "-c"], "bash"
        raise RuntimeError(
            "Không tìm thấy shell khả dụng (powershell/pwsh/bash/sh) trên máy này"
        )

    @staticmethod
    def _inject_start_process_hidden(text: str) -> str:
        """Ép mọi Start-Process chạy Hidden — không hiện cửa sổ lên màn hình."""
        if "Start-Process" not in text and "start-process" not in text.lower():
            return text
        out = re.sub(r"-NoNewWindow\b", "", text, flags=re.IGNORECASE)
        # Đã có -WindowStyle → chuẩn hóa về Hidden
        out = re.sub(
            r"-WindowStyle\s+\w+",
            "-WindowStyle Hidden",
            out,
            flags=re.IGNORECASE,
        )
        # Chưa có -WindowStyle sau Start-Process
        out = re.sub(
            r"\bStart-Process\b(?![^\n]*-WindowStyle)",
            "Start-Process -WindowStyle Hidden",
            out,
            flags=re.IGNORECASE,
        )
        return out

    def _force_commands_hidden(self, command: str, shell_kind: str) -> str:
        """Chặn PowerShell/Start-Process hiện cửa sổ — chỉ chạy ngầm."""
        if shell_kind not in ("powershell", "pwsh"):
            return command

        command = self._inject_start_process_hidden(command)

        # Agent hay viết: powershell -File scripts/foo.ps1 (Start-Process nằm trong file)
        for m in re.finditer(
            r"(?:^|[\s;|&])(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+[^\n]*?-File\s+[\"']?([^\s\"']+\.ps1)",
            command,
            flags=re.IGNORECASE,
        ):
            rel = m.group(1)
            try:
                path = Path(rel) if Path(rel).is_absolute() else self._resolve(rel)
            except (ValueError, OSError):
                continue
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
                patched = self._inject_start_process_hidden(raw)
                if patched != raw:
                    path.write_text(patched, encoding="utf-8")
                    log.info(
                        "Đã ép -WindowStyle Hidden trong %s (chặn hiện cửa sổ)",
                        path.name,
                    )
            except OSError as e:
                log.warning("Không patch được %s: %s", path, e)

        # Nested: powershell ... → bỏ WindowStyle Normal nếu có
        command = re.sub(
            r"(powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+(?!.*-WindowStyle)",
            r"\1 -WindowStyle Hidden ",
            command,
            count=1,
            flags=re.IGNORECASE,
        )
        return command

    def _tool_run_command(self, command: str) -> str:
        try:
            shell_prefix, shell_kind = self._detect_shell()
        except RuntimeError as e:
            return f"ERROR: {e}"

        # && -> ; chỉ cần thiết cho Windows PowerShell 5.1 (pwsh/bash đều hỗ trợ && native)
        if shell_kind == "powershell":
            command = re.sub(r"\s+&&\s+", "; ", command)

        command = self._force_commands_hidden(command, shell_kind)

        is_one_off = (
            "python -c" in command
            or "py -c" in command
            or "type " in command
            or "cat " in command
            or "echo " in command
            or "pytest" in command
            or "python test_" in command
        )
        server_pattern = (
            r"\b(npm\s+(run\s+)?(dev|start)|yarn\s+(dev|start)|bun\s+(run\s+)?(dev|start)|"
            r"vite|next\s+dev|uvicorn|fastapi\s+dev|node\s+server|"
            r"python\s+-m\s+uvicorn|python\s+app\.py|python\s+main\.py)\b"
        )
        # -File *.ps1 có Start-Process / start server → coi là background
        ps1_bg = bool(re.search(r"-File\s+[\"']?\S+\.ps1", command, re.I)) and (
            "Start-Process" in command
            or "start_diag" in command.lower()
            or "server" in command.lower()
        )
        is_background = not is_one_off and (
            "Start-Process" in command
            or "Start-Job" in command
            or ps1_bg
            or bool(re.search(server_pattern, command, re.IGNORECASE))
        )

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        if is_background:
            original_cmd = command
            log.info("Khởi chạy background process ngầm (%s): %s", shell_kind, command)

            try:
                if shell_kind in ("powershell", "pwsh"):
                    argv = shell_prefix + [command]
                    popen_kwargs: dict = {"creationflags": creationflags}
                else:
                    # Agent lỡ viết Start-Process trên máy không có PowerShell → bóc lệnh thật + nohup
                    inner = re.sub(
                        r"Start-Process\s+(-WindowStyle\s+\S+\s+)?(-ArgumentList\s+)?",
                        "",
                        command,
                        flags=re.IGNORECASE,
                    ).strip().strip('"').strip("'")
                    argv = [shell_prefix[0], "-c", f"nohup {inner} > /dev/null 2>&1 &"]
                    popen_kwargs = {}

                proc = subprocess.Popen(
                    argv,
                    cwd=str(self.project_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    **popen_kwargs,
                )
                try:
                    exit_code = proc.wait(timeout=3.0)
                    result = (
                        f"exit_code={exit_code}\n"
                        "(Lệnh background/server đã được khởi chạy ngầm thành công — không hiện cửa sổ)"
                    )
                except subprocess.TimeoutExpired:
                    result = (
                        "exit_code=0\n"
                        "(Lệnh background/server đã được khởi chạy ngầm thành công — không hiện cửa sổ)"
                    )

                self._auto_save_start_command(original_cmd)
                return (
                    result
                    + "\n💡 Tip: gọi save_start_command để lưu lệnh start — "
                    "Orchestrator sẽ tự chạy lại khi khởi động."
                )
            except Exception as e:
                return f"ERROR: không thể khởi chạy background process: {e}"

        try:
            proc = subprocess.run(
                shell_prefix + [command],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=config.COMMAND_TIMEOUT_SECONDS,
                creationflags=creationflags,
            )
            out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
            return f"exit_code={proc.returncode}\n{out.strip()}"
        except subprocess.TimeoutExpired:
            return (
                f"ERROR: lệnh vượt quá timeout {config.COMMAND_TIMEOUT_SECONDS}s — "
                "nếu khởi chạy background server hãy dùng Start-Process -WindowStyle Hidden (Windows) "
                "hoặc lệnh server trực tiếp (npm run dev / node server)"
            )

    @staticmethod
    def _infer_api_base_from_command(command: str) -> str:
        """Suy api_base từ lệnh start (vd -p 4010, --port 3000, :3000)."""
        cmd = command or ""
        m = re.search(r"(?:--port|-p)\s+(\d{2,5})\b", cmd, re.I)
        if not m:
            m = re.search(r"localhost:(\d{2,5})\b|:(\d{2,5})\b", cmd, re.I)
        port = None
        if m:
            port = m.group(1) or (m.group(2) if m.lastindex and m.lastindex >= 2 else None)
        if not port and re.search(r"\bprism\b", cmd, re.I):
            port = "4010"  # Prism mock default
        if not port:
            return ""
        return f"http://127.0.0.1:{port}"

    def _auto_save_start_command(self, command: str) -> None:
        """Tự động lưu lệnh start backend vào project settings khi chạy server ngầm thành công."""
        try:
            slug = self.task.project
            if not slug:
                return
            # Lọc bỏ phần Start-Process wrapper, giữ lệnh gốc
            clean_cmd = command.strip()
            if clean_cmd.startswith("Start-Process"):
                # Trích lệnh thật từ -ArgumentList hoặc -Command
                m = re.search(r'-Command\s+(.+?)(?:\"|\'|$)', clean_cmd)
                if m:
                    clean_cmd = m.group(1).strip().strip('"').strip("'")
                else:
                    clean_cmd = command.strip()
            proj = settings.get_project(slug) or {}
            kwargs: dict = {}
            if not proj.get("start_command"):
                kwargs["start_command"] = clean_cmd
            if not (proj.get("api_base") or "").strip():
                inferred = self._infer_api_base_from_command(command) or self._infer_api_base_from_command(clean_cmd)
                if inferred:
                    kwargs["api_base"] = inferred
            if kwargs:
                settings.upsert_project(slug, **kwargs)
                log.info("Auto-saved project '%s' settings: %s", slug, kwargs)
        except Exception as e:
            log.warning("Không thể auto-save start_command: %s", e)

    def _tool_save_start_command(self, command: str) -> str:
        """Agent gọi tool này để lưu lệnh start server vào project settings."""
        slug = self.task.project
        if not slug:
            return "ERROR: task không gắn project — không thể lưu start_command"
        try:
            kwargs: dict = {"start_command": command.strip()}
            proj = settings.get_project(slug) or {}
            extra = ""
            if not (proj.get("api_base") or "").strip():
                inferred = self._infer_api_base_from_command(command)
                if inferred:
                    kwargs["api_base"] = inferred
                    extra = f"\nĐã suy api_base={inferred} (proxy Live /api → backend)."
            settings.upsert_project(slug, **kwargs)
            return (
                f"OK: Đã lưu start_command cho project '{slug}': {command.strip()}\n"
                f"Orchestrator sẽ tự động chạy lệnh này khi khởi động lần sau.{extra}"
            )
        except Exception as e:
            return f"ERROR: {e}"

    def _tool_http_get(self, url: str) -> str:
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            body = resp.text[:3000]
            return f"status={resp.status_code}\ncontent-type={resp.headers.get('content-type', '')}\n{body}"
        except httpx.HTTPError as e:
            return f"ERROR: {e}"

    # --- figma ---

    def _tool_figma_get(self, url: str, node_id: str = "") -> str:
        import time
        from urllib.parse import unquote

        from ..links import default_registry

        # LLM hay dính dấu , " ở cuối URL khi gọi tool
        url = unquote((url or "").strip().rstrip(",\"' \n\t"))
        node_id = (node_id or "").strip().rstrip(",\"' \n\t").replace("-", ":")

        parsed = default_registry.detect_and_parse(url)
        file_key = ""
        if parsed.get("type") == "figma":
            file_key = parsed.get("file_key") or ""
            if not node_id:
                node_id = (parsed.get("node_id") or "").replace("-", ":")
        if not file_key:
            m = re.search(r"figma\.com/(?:file|design|proto|board)/([A-Za-z0-9]+)", url)
            file_key = m.group(1) if m else (url if re.fullmatch(r"[A-Za-z0-9]{15,}", url) else "")
        if not file_key:
            return "ERROR: không nhận diện được file key từ link. Định dạng: figma.com/design/<key>/..."

        cached = _figma_cache_load(file_key, node_id)
        if cached:
            return cached + "\n\n(NOTE: cache local — không gọi Figma API lại)"

        tokens = settings.figma_tokens()
        if not tokens:
            return "ERROR: chưa có Figma token nào — thêm token trong Settings (⚙) trên UI."

        if node_id:
            api = f"https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}&depth=6"
        else:
            api = f"https://api.figma.com/v1/files/{file_key}?depth=25"

        last_err = ""
        hit_429 = False
        for tok in tokens:
            try:
                resp = httpx.get(api, headers={"X-Figma-Token": tok["token"]}, timeout=30)
            except httpx.HTTPError as e:
                last_err = f"{tok['name']}: {e}"
                continue

            if resp.status_code == 429:
                hit_429 = True
                ra = resp.headers.get("Retry-After") or ""
                try:
                    wait_s = int(float(ra))
                except (TypeError, ValueError):
                    wait_s = 60
                # Chỉ soft-retry nếu chờ ngắn; high-limit (giờ) → vision ngay
                if wait_s <= 30:
                    log.warning("Figma 429 — chờ %ss rồi thử lại", wait_s)
                    time.sleep(wait_s)
                    try:
                        resp = httpx.get(api, headers={"X-Figma-Token": tok["token"]}, timeout=30)
                    except httpx.HTTPError as e:
                        last_err = f"{tok['name']}: {e}"
                        continue
                if resp.status_code == 429:
                    hrs = max(0, wait_s // 3600)
                    mins = (wait_s % 3600) // 60
                    last_err = f"{tok['name']}: HTTP 429 (Retry-After ~{hrs}h{mins}m)"
                    continue

            if resp.status_code == 200:
                data = resp.json()
                if node_id:
                    nodes = data.get("nodes", {})
                    entry = next(iter(nodes.values()), None)
                    doc = entry.get("document") if entry else None
                    if not doc:
                        return f"ERROR: node {node_id} không tồn tại trong file."
                else:
                    doc = data.get("document")
                    if not doc:
                        return "ERROR: response Figma không có document."
                name = data.get("name", "")
                lines: list[str] = []
                _figma_walk(doc, 0, lines)
                header = f"Figma file: {name} (key={file_key})"
                if node_id:
                    header += f" — node {node_id}"
                text = header + "\n" + "\n".join(lines)
                _figma_cache_save(file_key, node_id, text)
                return text

            last_err = f"{tok['name']}: HTTP {resp.status_code}"
            if resp.status_code == 403:
                try:
                    err = resp.json().get("err") or resp.text[:120]
                except Exception:
                    err = resp.text[:120]
                last_err += f" ({err})"
            continue

        # nodes API fail/429 → export PNG + Vision (quota images thường vẫn còn)
        if node_id:
            vision_text = _figma_vision_fallback(file_key, node_id, tokens, artifact_dir=self._artifact_dir())
            if vision_text:
                return vision_text
        elif hit_429:
            return (
                f"ERROR: Figma nodes API rate-limit ({last_err}). "
                "Cần node-id trong URL (vd ?node-id=6695-15995) để fallback export ảnh + Vision. "
                "ĐỪNG gọi figma_get lại liên tục."
            )

        return (
            f"ERROR: không đọc được Figma ({last_err}). "
            "Token sai/hết hạn, file không có quyền, hoặc rate limit — "
            "xem Settings → Figma tokens."
        )

    # --- board tools ---

    def _project_mcp(self) -> tuple[str, str]:
        """(mcp_url, token) — mặc định builtin shim."""
        slug = (self.task.project or "").strip()
        proj = settings.get_project(slug) if slug else None
        url = ((proj or {}).get("mcp_url") or "").strip()
        token = ((proj or {}).get("mcp_token") or "").strip()
        if not url:
            url = f"{config.BASE_URL}/mcp/figma"
        return url, token

    def _tool_mcp_list_tools(self) -> str:
        from ..mcp import McpError, mcp_list_tools

        url, token = self._project_mcp()
        try:
            tools = mcp_list_tools(url, token=token)
        except McpError as e:
            return f"ERROR: {e}\nmcp_url: {url}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}\nmcp_url: {url}"
        if not tools:
            return f"(không có tool) mcp_url={url}"
        lines = [f"mcp_url: {url}", f"tools ({len(tools)}):"]
        for t in tools:
            name = t.get("name", "?")
            desc = (t.get("description") or "").replace("\n", " ")[:160]
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def _tool_mcp_call(self, tool: str, arguments: dict | None = None, arguments_json: str = "") -> str:
        import json as _json
        from ..mcp import McpError, mcp_call

        tool = (tool or "").strip()
        if not tool:
            return "ERROR: thiếu tên tool"
        args: dict = {}
        if isinstance(arguments, dict):
            args = arguments
        elif (arguments_json or "").strip():
            try:
                parsed = _json.loads(arguments_json)
                if isinstance(parsed, dict):
                    args = parsed
                else:
                    return "ERROR: arguments_json phải là object JSON"
            except _json.JSONDecodeError as e:
                return f"ERROR: arguments_json không hợp lệ: {e}"
        url, token = self._project_mcp()
        try:
            return mcp_call(url, tool, args, token=token)
        except McpError as e:
            return f"ERROR: {e}\nmcp_url: {url}\ntool: {tool}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}\nmcp_url: {url}"

    def _tool_run_skill(self, name: str) -> str:
        from ..skills.loader import get_skill, note_run_skill, resolve_skill_name, run_skill_allowed

        key = resolve_skill_name(name or "")
        if not key:
            return f"ERROR: skill không tồn tại: {name!r}. Dùng đúng id trong Skills index."
        if not run_skill_allowed(self.task.id):
            return (
                "ERROR: đã hết quota run_skill cho task này (tối đa 3). "
                "Làm theo các Active Skills / body đã load."
            )
        sk = get_skill(key)
        if not sk:
            return f"ERROR: không đọc được skill {key}"
        # Agent subagent profiles = system prompt, không phải playbook on-demand
        if sk.source == "agent" and (
            sk.invocation == "manual" or sk.run_as == "subagent"
        ):
            return (
                f"ERROR: `{sk.name}` là agent profile (system prompt), không gọi qua run_skill. "
                "Chọn playbook trong Skills index (native/reasonix/addy)."
            )
        n = note_run_skill(self.task.id)
        return (
            f"# Skill `{sk.name}` ({sk.source}) — load #{n}/3\n\n"
            f"{sk.description}\n\n---\n\n{sk.body}"
        )

    def _tool_post_message(self, message: str) -> str:
        store.add_event(self.task.id, self.agent, "comment", message)
        return "OK: đã đăng message vào task " + self.task.id

    def _tool_search_tasks(self, query: str) -> str:
        tasks = store.search_tasks(query)
        if not tasks:
            return "(không có task nào khớp)"
        return "\n".join(
            f"{t.id} [{t.type}/{t.status}] {t.title} (assignee: {t.assignee or '-'})"
            for t in tasks
        )

    _BACKEND_HINTS = re.compile(
        r"(\.py\b|/api/|sql\s*injection|\bauth\b|\bidor\b|database|backend|"
        r"express|fastapi|endpoint|server\.cjs|sqlite|mysql|postgres)",
        re.IGNORECASE,
    )
    _FRONTEND_HINTS = re.compile(
        r"(\.tsx?\b|\.css\b|\.vue\b|component|render|layout|viewport|"
        r"mobile|header|button|frontend|\bui\b)",
        re.IGNORECASE,
    )

    def _guess_area(self, text: str) -> str:
        """Đoán area từ mô tả/repro. Mơ hồ → frontend (an toàn hơn với ranh giới Kid)."""
        has_backend = bool(self._BACKEND_HINTS.search(text or ""))
        has_frontend = bool(self._FRONTEND_HINTS.search(text or ""))
        return "backend" if (has_backend and not has_frontend) else "frontend"

    _OPERATOR_ONLY_BUG = re.compile(
        r"(rotate\s+(leaked\s+)?credentials?|mysql\s+prod|password\s+mysql|"
        r"đổi\s+password\s+(mysql|duolingo|prod)|operator.*(rotate|đổi\s+password)|"
        r"14\.225\.|user\s+'upos'|live\s+mysql)",
        re.I,
    )

    def _tool_create_bug_ticket(
        self,
        title: str,
        description: str,
        severity: str,
        repro_steps: str,
        area: str = "",
        related_subtask_id: str = "",
    ) -> str:
        if severity not in SEVERITIES:
            return f"ERROR: severity phải là một trong {SEVERITIES}"
        if not (title and description and repro_steps):
            return "ERROR: schema bug bắt buộc đủ title, description, severity, repro_steps"
        blob = f"{title}\n{description}\n{repro_steps}"
        if self._OPERATOR_ONLY_BUG.search(blob):
            return (
                "ERROR: không tạo bug kiểu rotate credential / truy cập MySQL-prod / "
                "đổi password tài khoản ngoài. Đó là việc Human Operator. "
                "Chỉ scrub file trong project + post_message cảnh báo ngắn — không spawn bug agent."
            )
        area_norm = (area or "").strip().lower()
        if area_norm not in ("frontend", "backend"):
            area_norm = self._guess_area(f"{description}\n{repro_steps}")
        assignee = "agasa" if area_norm == "backend" else "kid"

        related_sub = None
        rel_id = (related_subtask_id or "").strip()
        if rel_id:
            related_sub = store.get_task(rel_id)
            if not related_sub:
                return f"ERROR: related_subtask_id={rel_id!r} không tồn tại"
            parent_id = self.task.parent_id or self.task.id
            if related_sub.parent_id and related_sub.parent_id != parent_id and related_sub.id != parent_id:
                return (
                    f"ERROR: {rel_id} không thuộc cùng task cha "
                    f"(expected parent {parent_id}, got {related_sub.parent_id})"
                )

        rel_note = f" Related build sub: {rel_id}." if rel_id else ""
        bug = store.create_task(
            title=title,
            description=(
                f"Observed while working on {self.task.id}.{rel_note} {description}"
            ),
            type="bug",
            project=self.task.project,
            project_dir=self.task.project_dir,
            parent_id=self.task.parent_id or self.task.id,
            assignee=assignee,
            tags=["discovered-issue", "bug", f"area-{area_norm}"],
            severity=severity,
            repro_steps=repro_steps,
            created_by=self.agent,
        )
        store.add_dep(self.task.id, bug.id, "related")
        if related_sub:
            store.add_dep(bug.id, related_sub.id, "related")
            store.add_event(
                related_sub.id, self.agent, "system",
                f"Bug {bug.id} gắn từ QA/Security — related sub này: {title}",
            )
        store.add_event(
            self.task.id, self.agent, "system",
            f"Bug ticket {bug.id} đã được tạo và link related: {title} "
            f"(area={area_norm}, {assignee}"
            + (f", related_sub={rel_id}" if rel_id else "")
            + ")",
        )
        return (
            f"OK: đã tạo bug {bug.id} (gắn task cha, {assignee} fix, area={area_norm}"
            + (f", related_subtask={rel_id}" if rel_id else "")
            + ") — đây là BUG ticket, không phải subtask."
        )

    # --- git tools ---

    def _tool_git_clone(self, url: str, branch: str = "") -> str:
        from .. import git_ops
        result = git_ops.ensure_clone(url, self.project_dir, branch=branch or "")
        if not result.get("ok"):
            return f"ERROR: {result.get('error', 'clone failed')}"
        # Clone vào thư mục con → chỉ chuyển project_dir của task hiện tại.
        # KHÔNG đổi parent (tránh biến project FE gốc thành api/duolingo-api).
        new_path = result.get("path") or ""
        if new_path and Path(new_path).resolve() != self.project_dir.resolve():
            store.update_task_fields(self.task.id, project_dir=new_path)
            self.project_dir = Path(new_path)
            self.task.project_dir = new_path
        lines = [
            f"OK: {result.get('message', 'git ready')}",
            f"path: {result.get('path')}",
            f"remote: {result.get('remote')}",
            f"branch: {result.get('branch')}",
            f"repo: {result.get('repo')}",
            f"status:\n{result.get('status', '')}",
        ]
        return "\n".join(lines)

    def _tool_git_status(self) -> str:
        from .. import git_ops
        result = git_ops.repo_status(self.project_dir)
        if not result.get("ok"):
            return f"ERROR: {result.get('error', 'git status failed')}"
        return (
            f"path: {result.get('path')}\n"
            f"remote: {result.get('remote')}\n"
            f"status:\n{result.get('status')}\n"
            f"log:\n{result.get('log')}\n"
            f"remotes:\n{result.get('remotes')}"
        )

    # --- visual QA tools ---

    def _tool_screenshot_url(
        self,
        url: str,
        name: str,
        viewport: str = "desktop",
        full_page: bool = True,
        wait_ms: int = 1500,
        click_selector: str = "",
        scroll_y: int | None = None,
    ) -> str:
        safe = re.sub(r"[^\w\-]+", "-", name.strip())[:60] or "screenshot"
        out = self._artifact_dir() / f"{safe}.png"
        try:
            result = qa_browser.capture_screenshot(
                url, out,
                viewport_name=viewport,
                full_page=full_page,
                wait_ms=wait_ms,
                click_selector=click_selector,
                scroll_y=scroll_y,
            )
        except Exception as e:
            return f"ERROR: screenshot thất bại: {type(e).__name__}: {e}"
        view_url = self._artifact_url(out.name)
        lines = [
            f"OK: screenshot saved",
            f"artifact: {out.name}",
            f"view_url: {view_url}",
            f"viewport: {result.get('viewport')}",
            f"title: {result.get('title', '')}",
            f"final_url: {result.get('final_url', url)}",
        ]
        if result.get("console_errors"):
            lines.append(f"console_errors: {result['console_errors'][:5]}")
        return "\n".join(lines)

    def _tool_inspect_render(
        self,
        url: str,
        viewport: str = "desktop",
        click_selector: str = "",
        expect_selector: str = "",
        expect_min_count: int = 0,
        brand_hex: str = "",
        body_bg_hex: str = "",
    ) -> str:
        try:
            result = qa_browser.inspect_render(
                url,
                viewport_name=viewport,
                click_selector=click_selector,
                expect_selector=expect_selector,
                expect_min_count=expect_min_count,
                brand_hex=brand_hex,
                body_bg_hex=body_bg_hex,
            )
        except Exception as e:
            return f"ERROR: inspect_render thất bại: {type(e).__name__}: {e}"
        table = qa_browser.format_inspect_table(result)
        return table + f"\n\nURL: {url}\nViewport: {result.get('viewport')}"

    def _tool_compare_image(
        self, screenshot: str, reference: str, threshold: float = 0.92
    ) -> str:
        shot = self._resolve_artifact_or_project(screenshot)
        ref = self._resolve(reference)
        try:
            result = qa_browser.compare_images(shot, ref, threshold=threshold)
        except Exception as e:
            return f"ERROR: compare_image thất bại: {type(e).__name__}: {e}"
        if not result.get("ok"):
            return f"ERROR: {result.get('error', 'unknown')}"
        diff_name = Path(result["diff_path"]).name
        lines = [
            f"similarity: {result['similarity']} (threshold {result['threshold']})",
            f"verdict: {result['verdict']}",
            f"screenshot: {shot.name}",
            f"reference: {ref.relative_to(self.project_dir) if ref.is_relative_to(self.project_dir) else ref}",
            f"diff_view_url: {self._artifact_url(diff_name)}",
            f"size: {result['size']}",
        ]
        return "\n".join(lines)


def _figma_hex(node: dict) -> str:
    """Màu solid đầu tiên của node dạng #rrggbb, hoặc ''."""
    for fill in node.get("fills") or []:
        if fill.get("type") == "SOLID" and fill.get("visible", True):
            c = fill.get("color", {})
            return "#{:02x}{:02x}{:02x}".format(
                round(c.get("r", 0) * 255), round(c.get("g", 0) * 255), round(c.get("b", 0) * 255)
            )
    return ""


def _figma_cache_path(file_key: str, node_id: str) -> Path:
    safe_node = (node_id or "root").replace(":", "-").replace("/", "_")[:80]
    d = Path(config.WORKSPACE_DIR) / "cache" / "figma"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{file_key}_{safe_node}.txt"


def _figma_cache_load(file_key: str, node_id: str) -> str:
    path = _figma_cache_path(file_key, node_id)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
        return text if len(text) > 40 else ""
    except OSError:
        return ""


def _figma_cache_save(file_key: str, node_id: str, text: str) -> None:
    try:
        _figma_cache_path(file_key, node_id).write_text(text, encoding="utf-8")
    except OSError as e:
        log.warning("Không lưu cache Figma: %s", e)


def _run_coro_sync(coro, timeout: float = 180.0):
    """Chạy coroutine từ tool sync — an toàn cả khi đã có event loop."""
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=timeout)


def _figma_png_path(file_key: str, node_id: str) -> Path:
    safe_node = (node_id or "root").replace(":", "-").replace("/", "_")[:80]
    d = Path(config.WORKSPACE_DIR) / "cache" / "figma"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{file_key}_{safe_node}.png"


def _figma_export_png(file_key: str, node_id: str, tokens: list[dict]) -> Path | None:
    """Export frame qua /v1/images — thường không dính cùng quota high-limit của /files."""
    if not node_id or not tokens:
        return None
    dest = _figma_png_path(file_key, node_id)
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    api = f"https://api.figma.com/v1/images/{file_key}"
    for tok in tokens:
        try:
            resp = httpx.get(
                api,
                params={"ids": node_id, "format": "png", "scale": 1.5},
                headers={"X-Figma-Token": tok["token"]},
                timeout=60,
            )
        except httpx.HTTPError as e:
            log.warning("Figma images export failed (%s): %s", tok.get("name"), e)
            continue
        if resp.status_code != 200:
            log.warning(
                "Figma images HTTP %s (%s): %s",
                resp.status_code, tok.get("name"), resp.text[:160],
            )
            continue
        img_url = (resp.json().get("images") or {}).get(node_id)
        if not img_url:
            continue
        try:
            raw = httpx.get(img_url, timeout=120, follow_redirects=True)
            raw.raise_for_status()
            dest.write_bytes(raw.content)
            log.info("Figma PNG saved %s (%s bytes)", dest.name, dest.stat().st_size)
            return dest
        except httpx.HTTPError as e:
            log.warning("Download Figma PNG failed: %s", e)
            continue
    return None


async def _figma_vision_describe_async(png_path: Path) -> str:
    """Mô tả UI từ PNG bằng model Vision (lazy import tránh circular)."""
    from .. import llm
    from ..core.orchestrator import _prepare_vision_data_url, _vision_candidate_llms

    roles = settings.role_models()
    if roles.get("vision"):
        vision = settings.resolve_llm(role="vision")
    elif config.MODEL_VISION:
        vision = {
            "model": config.MODEL_VISION,
            "base_url": config.LLM_BASE_URL,
            "api_key": config.LLM_API_KEY,
            "name": config.MODEL_VISION,
        }
    elif roles.get("planner"):
        vision = settings.resolve_llm(role="planner")
    else:
        return ""

    data_url, _ = _prepare_vision_data_url(png_path)
    prompt = [
        {
            "type": "text",
            "text": (
                "Bạn là trợ lý vision cho builder UI. Mô tả ảnh Figma bằng tiếng Việt, "
                "đủ chi tiết để code UI fake-data: layout (sidebar/header/cột), màu nền + accent (#hex nếu đoán được), "
                "component + text nhìn thấy, dark/light. Không bịa chi tiết không có trong ảnh."
            ),
        },
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    for cfg in _vision_candidate_llms(vision):
        try:
            msg = await llm.chat(
                [{"role": "user", "content": prompt}],
                model=cfg["model"],
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                max_retries=2,
            )
            text = (msg.get("content") or "").strip()
            if text:
                used = cfg.get("name") or cfg["model"]
                return f"(Vision model: {used})\n{text}"
        except Exception as e:
            log.warning("Figma vision candidate `%s` failed: %s", cfg.get("model"), e)
    return ""


def _figma_vision_fallback(
    file_key: str,
    node_id: str,
    tokens: list[dict],
    artifact_dir: Path | None = None,
) -> str:
    """Khi nodes API fail/429: export PNG + Vision → cache text cho lần gọi sau."""
    png = _figma_export_png(file_key, node_id, tokens)
    if not png:
        return ""
    if artifact_dir is not None:
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            art = artifact_dir / f"figma-{node_id.replace(':', '-')}.png"
            if not art.exists() or art.stat().st_size != png.stat().st_size:
                shutil.copy2(png, art)
        except OSError as e:
            log.warning("Copy Figma PNG vào artifacts thất bại: %s", e)
    try:
        desc = _run_coro_sync(_figma_vision_describe_async(png), timeout=180.0)
    except Exception as e:
        log.exception("Figma vision fallback crashed")
        return (
            f"Figma nodes API lỗi — đã export PNG `{png}` nhưng Vision fail: {e}. "
            "Đọc ảnh trong cache/artifacts hoặc mô tả UI theo task description. "
            "ĐỪNG gọi figma_get lại."
        )
    if not desc:
        return (
            f"Figma nodes API lỗi — đã export PNG `{png}` nhưng Vision không trả mô tả. "
            "ĐỪNG gọi figma_get lại; build theo description task."
        )
    text = (
        f"Figma VISION fallback (key={file_key}) — node {node_id}\n"
        f"PNG: {png}\n\n"
        f"{desc}\n\n"
        "NOTE: nodes API rate-limit/lỗi — dùng mô tả Vision này để code UI. "
        "ĐỪNG gọi figma_get lại trong task này trừ khi cần node khác."
    )
    _figma_cache_save(file_key, node_id, text)
    try:
        png.with_suffix(".vision.txt").write_text(desc, encoding="utf-8")
    except OSError:
        pass
    return text


_FIGMA_MAX_LINES = 350


def _figma_walk(node: dict, depth: int, lines: list[str]) -> None:
    if len(lines) >= _FIGMA_MAX_LINES:
        if len(lines) == _FIGMA_MAX_LINES:
            lines.append("...[cây bị cắt — dùng node_id để xem chi tiết một nhánh]")
        return
    parts = [f"[{node.get('type', '?')}] {node.get('name', '')}"]
    box = node.get("absoluteBoundingBox") or {}
    if box:
        parts.append(f"{round(box.get('width', 0))}x{round(box.get('height', 0))} @({round(box.get('x', 0))},{round(box.get('y', 0))})")
    hex_color = _figma_hex(node)
    if hex_color:
        parts.append(f"fill={hex_color}")
    if node.get("cornerRadius"):
        parts.append(f"radius={node['cornerRadius']}")
    if node.get("type") == "TEXT":
        style = node.get("style", {})
        text = (node.get("characters") or "").replace("\n", " ")[:80]
        parts.append(f'text="{text}"')
        if style:
            parts.append(f"font={style.get('fontFamily', '?')} {style.get('fontSize', '?')}px w{style.get('fontWeight', '?')}")
    node_id = node.get("id", "")
    lines.append("  " * depth + " ".join(parts) + (f" (id={node_id})" if node_id else ""))
    for child in node.get("children") or []:
        _figma_walk(child, depth + 1, lines)


# Core coding surface ≈ Reasonix default (aliases bash/ls included for skill bodies)
DEFAULT_WORKER_TOOLS = [
    "read_file", "write_file", "edit_file", "multi_edit", "move_file",
    "list_dir", "ls", "glob", "grep", "search_files",
    "run_command", "bash", "http_get", "web_fetch",
    "todo_write", "run_skill",
    "figma_get", "mcp_list_tools", "mcp_call",
    "git_clone", "git_status",
    "post_message", "search_tasks", "create_bug_ticket", "save_start_command",
]
QA_TOOLS = [
    "read_file", "list_dir", "ls", "glob", "grep", "search_files",
    "run_command", "bash", "http_get", "web_fetch",
    "todo_write", "run_skill",
    "figma_get", "mcp_list_tools", "mcp_call", "git_clone", "git_status",
    "screenshot_url", "inspect_render", "compare_image",
    "post_message", "search_tasks", "create_bug_ticket", "save_start_command",
]
