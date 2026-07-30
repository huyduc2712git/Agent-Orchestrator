"""Bộ tool thực thi thật cho agent: file, command, search, http, figma, board."""
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import httpx

from .. import config, settings
from ..board import store
from ..board.models import SEVERITIES, Task
from ..qa import browser as qa_browser

log = logging.getLogger("tools")

# ---------- OpenAI tool schemas ----------

TOOL_SCHEMAS: dict[str, dict] = {
    "read_file": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Đọc nội dung một file trong project directory. Path tương đối so với project dir.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
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
            "description": "Liệt kê file/thư mục trong project directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Mặc định là gốc project"}},
            },
        },
    },
    "search_files": {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Tìm chuỗi văn bản trong các file của project (case-insensitive). Trả về file:line:content.",
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
    "run_command": {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Chạy một lệnh PowerShell trong project directory (timeout "
                f"{config.COMMAND_TIMEOUT_SECONDS}s). Dùng cho build, test, git... "
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
    "http_get": {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "HTTP GET một URL (để verify server/trang web). Trả về status code + phần đầu body.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    "figma_get": {
        "type": "function",
        "function": {
            "name": "figma_get",
            "description": (
                "Lấy thiết kế từ Figma (dùng token trong Settings). Trả về cây node rút gọn: "
                "tên, loại, kích thước, vị trí, màu (hex), text, font. Dùng node_id để đào sâu "
                "vào một node cụ thể khi cây bị cắt bớt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Link Figma (figma.com/design/... hoặc /file/...) hoặc file key"},
                    "node_id": {"type": "string", "description": "Tùy chọn: id node (vd '12:34') để lấy chi tiết một nhánh"},
                },
                "required": ["url"],
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
                "link 'related' về task hiện tại."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string", "description": "Evidence, expected vs actual, file/line liên quan"},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "repro_steps": {"type": "string"},
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
    return [TOOL_SCHEMAS[n] for n in tool_names]


# ---------- Executor ----------

class ToolContext:
    """Ngữ cảnh thực thi tool của một agent trên một task cụ thể."""

    def __init__(self, agent: str, task: Task):
        self.agent = agent
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
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return f"ERROR: tool không tồn tại: {name}"
            out = handler(**args)
            if len(out) > config.MAX_TOOL_OUTPUT_CHARS:
                out = out[: config.MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"
            return out
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    # --- file tools ---

    def _tool_read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.is_file():
            return f"ERROR: file không tồn tại: {path}"
        return p.read_text(encoding="utf-8", errors="replace")

    def _tool_write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: đã ghi {len(content)} ký tự vào {path}"

    def _tool_list_dir(self, path: str = ".") -> str:
        p = self._resolve(path)
        if not p.is_dir():
            return f"ERROR: thư mục không tồn tại: {path}"
        lines = []
        for child in sorted(p.iterdir()):
            kind = "dir " if child.is_dir() else "file"
            lines.append(f"{kind}  {child.relative_to(self.project_dir)}")
        return "\n".join(lines) or "(trống)"

    def _tool_search_files(self, query: str, glob: str = "**/*") -> str:
        if "**" not in glob:
            glob = f"**/{glob}"
        hits = []
        q = query.lower()
        for f in self.project_dir.glob(glob):
            if not f.is_file() or f.stat().st_size > 1_000_000:
                continue
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

    def _tool_run_command(self, command: str) -> str:
        # 1. Tự động đổi && thành ; cho tương thích với PowerShell 5.1 trên Windows
        command = re.sub(r"\s+&&\s+", "; ", command)

        # 2. Tự động đảm bảo Start-Process dùng -WindowStyle Hidden để ẩn hoàn toàn cửa sổ console trên Windows
        if "Start-Process" in command:
            if "-NoNewWindow" in command:
                command = re.sub(r"-NoNewWindow\b", "", command, flags=re.IGNORECASE)
            if "-WindowStyle" not in command:
                command = re.sub(r"\bStart-Process\b", "Start-Process -WindowStyle Hidden", command, flags=re.IGNORECASE)

        # 3. Tự động nhận diện lệnh chạy server ngầm (Start-Process / Start-Job hoặc dev/prod server)
        server_pattern = r"\b(node|python|py|npm|npx|bun|yarn)\b.*\b(server|app\.py|main\.py|dev|start|preview|vite|next|uvicorn|fastapi)\b"
        is_background = (
            "Start-Process" in command
            or "Start-Job" in command
            or bool(re.search(server_pattern, command, re.IGNORECASE))
        )

        if is_background:
            # Lưu lệnh gốc trước khi bọc Start-Process (để auto-start lần sau)
            original_cmd = command

            # Nếu chưa dùng Start-Process mà gọi lệnh server trực tiếp, tự bọc Start-Process với -WindowStyle Hidden để chạy ngầm ẩn cửa sổ
            if "Start-Process" not in command and "Start-Job" not in command:
                log.info("Tự động bọc lệnh server sang Start-Process: %s", command)
                command = f'Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command {json.dumps(command)}"'

            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                    cwd=str(self.project_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                try:
                    exit_code = proc.wait(timeout=3.0)
                    result = f"exit_code={exit_code}\n(Lệnh background/server đã được khởi chạy ngầm thành công)"
                except subprocess.TimeoutExpired:
                    result = "exit_code=0\n(Lệnh background/server đã được khởi chạy ngầm thành công)"

                # Auto-save start_command vào project settings
                self._auto_save_start_command(original_cmd)
                return result + "\n💡 Tip: gọi save_start_command để lưu lệnh start — Orchestrator sẽ tự chạy lại khi khởi động."
            except Exception as e:
                return f"ERROR: không thể khởi chạy background process: {e}"

        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=config.COMMAND_TIMEOUT_SECONDS,
            )
            out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
            return f"exit_code={proc.returncode}\n{out.strip()}"
        except subprocess.TimeoutExpired:
            return f"ERROR: lệnh vượt quá timeout {config.COMMAND_TIMEOUT_SECONDS}s — nếu khởi chạy background server hãy dùng Start-Process"

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
            proj = settings.get_project(slug)
            if proj and not proj.get("start_command"):
                settings.upsert_project(slug, start_command=clean_cmd)
                log.info("Auto-saved start_command cho project '%s': %s", slug, clean_cmd)
        except Exception as e:
            log.warning("Không thể auto-save start_command: %s", e)

    def _tool_save_start_command(self, command: str) -> str:
        """Agent gọi tool này để lưu lệnh start server vào project settings."""
        slug = self.task.project
        if not slug:
            return "ERROR: task không gắn project — không thể lưu start_command"
        try:
            settings.upsert_project(slug, start_command=command.strip())
            return f"OK: Đã lưu start_command cho project '{slug}': {command.strip()}\nOrchestrator sẽ tự động chạy lệnh này khi khởi động lần sau."
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
        from ..links import default_registry

        parsed = default_registry.detect_and_parse(url)
        file_key = ""
        if parsed.get("type") == "figma":
            file_key = parsed.get("file_key") or ""
            if not node_id:
                node_id = parsed.get("node_id") or ""
        if not file_key:
            m = re.search(r"figma\.com/(?:file|design|proto|board)/([A-Za-z0-9]+)", url)
            file_key = m.group(1) if m else (url if re.fullmatch(r"[A-Za-z0-9]{15,}", url) else "")
        if not file_key:
            return "ERROR: không nhận diện được file key từ link. Định dạng: figma.com/design/<key>/..."

        tokens = settings.figma_tokens()
        if not tokens:
            return "ERROR: chưa có Figma token nào — thêm token trong Settings (⚙) trên UI."

        if node_id:
            api = f"https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}&depth=6"
        else:
            api = f"https://api.figma.com/v1/files/{file_key}?depth=25"

        last_err = ""
        for tok in tokens:
            resp = None
            for attempt in range(3):
                try:
                    resp = httpx.get(api, headers={"X-Figma-Token": tok["token"]}, timeout=30)
                except httpx.HTTPError as e:
                    last_err = f"{tok['name']}: {e}"
                    resp = None
                    break
                if resp.status_code == 429 and attempt < 2:
                    import time
                    time.sleep(2 * (attempt + 1))
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
                    return header + "\n" + "\n".join(lines)
                last_err = f"{tok['name']}: HTTP {resp.status_code}"
                if resp.status_code != 429:
                    break
            # HTTPError hoặc hết retry trên token này → thử token tiếp
            continue
        return (
            f"ERROR: không token nào truy cập được file ({last_err}). "
            "File có thể thuộc account khác hoặc bị Figma Limit (HTTP 429) — thêm token hoặc thử lại sau."
        )

    # --- board tools ---

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

    def _tool_create_bug_ticket(
        self, title: str, description: str, severity: str, repro_steps: str
    ) -> str:
        if severity not in SEVERITIES:
            return f"ERROR: severity phải là một trong {SEVERITIES}"
        if not (title and description and repro_steps):
            return "ERROR: schema bug bắt buộc đủ title, description, severity, repro_steps"
        bug = store.create_task(
            title=title,
            description=f"Observed while working on {self.task.id}. {description}",
            type="bug",
            project=self.task.project,
            project_dir=self.task.project_dir,
            parent_id=self.task.parent_id or self.task.id,
            assignee="stark",
            tags=["discovered-issue", "bug"],
            severity=severity,
            repro_steps=repro_steps,
            created_by=self.agent,
        )
        store.add_dep(self.task.id, bug.id, "related")
        store.add_event(
            self.task.id, self.agent, "system",
            f"Bug ticket {bug.id} đã được tạo và link related: {title}",
        )
        return f"OK: đã tạo bug {bug.id} (gắn task cha, Stark fix) — đây là BUG ticket, không phải subtask."

    # --- git tools ---

    def _tool_git_clone(self, url: str, branch: str = "") -> str:
        from .. import git_ops
        result = git_ops.ensure_clone(url, self.project_dir, branch=branch or "")
        if not result.get("ok"):
            return f"ERROR: {result.get('error', 'clone failed')}"
        # Nếu clone vào thư mục con, cập nhật project_dir của task để agent làm đúng chỗ
        new_path = result.get("path") or ""
        if new_path and Path(new_path).resolve() != self.project_dir.resolve():
            store.update_task_fields(self.task.id, project_dir=new_path)
            if self.task.parent_id:
                store.update_task_fields(self.task.parent_id, project_dir=new_path)
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


DEFAULT_WORKER_TOOLS = [
    "read_file", "write_file", "list_dir", "search_files",
    "run_command", "http_get", "figma_get", "git_clone", "git_status",
    "post_message", "search_tasks", "create_bug_ticket", "save_start_command",
]
QA_TOOLS = [
    "read_file", "list_dir", "search_files", "run_command",
    "http_get", "figma_get", "git_clone", "git_status",
    "screenshot_url", "inspect_render", "compare_image",
    "post_message", "search_tasks", "create_bug_ticket", "save_start_command",
]
