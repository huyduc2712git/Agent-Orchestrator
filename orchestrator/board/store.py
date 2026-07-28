"""SQLite store cho board: tasks, dependencies, events, chat log."""
import json
import sqlite3
import threading

from .. import bus, config
from .models import Event, Task, now_iso
from .state_machine import TransitionResult, request_transition

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_schema(_conn)
    return _conn


def _init_schema(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            type TEXT DEFAULT 'task',
            status TEXT DEFAULT 'backlog',
            assignee TEXT DEFAULT '',
            project TEXT DEFAULT 'default',
            project_dir TEXT DEFAULT '',
            parent_id TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            review_type TEXT DEFAULT 'agent',
            severity TEXT DEFAULT '',
            repro_steps TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS deps (
            task_id TEXT NOT NULL,
            depends_on TEXT NOT NULL,
            dep_type TEXT DEFAULT 'blocks',
            PRIMARY KEY (task_id, depends_on)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            agent TEXT DEFAULT '',
            kind TEXT DEFAULT 'comment',
            message TEXT DEFAULT '',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            message TEXT DEFAULT '',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS counters (
            name TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        );
        """
    )
    c.commit()


def _next_id(prefix: str = "tsk") -> str:
    c = _db()
    cur = c.execute(
        "INSERT INTO counters(name, value) VALUES(?, 1) "
        "ON CONFLICT(name) DO UPDATE SET value = value + 1 RETURNING value",
        (prefix,),
    )
    value = cur.fetchone()[0]
    c.commit()
    return f"{prefix}-{value:04d}"


def _row_to_task(row: sqlite3.Row) -> Task:
    d = dict(row)
    d["tags"] = json.loads(d.get("tags") or "[]")
    return Task(**d)


# ---------- Tasks ----------

def create_task(
    title: str,
    description: str = "",
    type: str = "task",
    assignee: str = "",
    project: str = "default",
    project_dir: str = "",
    parent_id: str = "",
    tags: list[str] | None = None,
    review_type: str = "agent",
    severity: str = "",
    repro_steps: str = "",
    created_by: str = "",
) -> Task:
    from .models import OPERATOR_REVIEW_TAGS

    tags = tags or []
    # Review gate config: tag nhạy cảm -> bắt buộc operator review
    if set(t.lower() for t in tags) & OPERATOR_REVIEW_TAGS:
        review_type = "operator"

    task = Task(
        id=_next_id("bug" if type == "bug" else "tsk"),
        title=title,
        description=description,
        type=type,
        assignee=assignee,
        project=project,
        project_dir=project_dir,
        parent_id=parent_id,
        tags=tags,
        review_type=review_type,
        severity=severity,
        repro_steps=repro_steps,
        created_by=created_by,
    )
    with _lock:
        _db().execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task.id, task.title, task.description, task.type, task.status,
                task.assignee, task.project, task.project_dir, task.parent_id,
                json.dumps(task.tags, ensure_ascii=False), task.review_type,
                task.severity, task.repro_steps, task.created_by,
                task.created_at, task.updated_at,
            ),
        )
        _db().commit()
    bus.publish({"type": "task_updated", "task": task.to_dict()})
    return task


def get_task(task_id: str) -> Task | None:
    row = _db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def list_tasks(
    status: list[str] | None = None,
    parent_id: str | None = None,
    assignee: str | None = None,
    type: str | None = None,
    include_archived: bool = False,
) -> list[Task]:
    q = "SELECT * FROM tasks WHERE 1=1"
    args: list = []
    if status:
        q += f" AND status IN ({','.join('?' * len(status))})"
        args += status
    elif not include_archived:
        q += " AND status != 'archived'"
    if parent_id is not None:
        q += " AND parent_id = ?"
        args.append(parent_id)
    if assignee is not None:
        q += " AND assignee = ?"
        args.append(assignee)
    if type is not None:
        q += " AND type = ?"
        args.append(type)
    q += " ORDER BY created_at"
    rows = _db().execute(q, args).fetchall()
    return [_row_to_task(r) for r in rows]


def update_task_fields(task_id: str, **fields) -> Task | None:
    if not fields:
        return get_task(task_id)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"], ensure_ascii=False)
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        _db().execute(f"UPDATE tasks SET {sets} WHERE id = ?", [*fields.values(), task_id])
        _db().commit()
    task = get_task(task_id)
    if task:
        bus.publish({"type": "task_updated", "task": task.to_dict()})
    return task


def set_status(task_id: str, new_status: str, actor: str) -> TransitionResult:
    """Điểm vào duy nhất để đổi status — luôn đi qua transition guard."""
    task = get_task(task_id)
    if not task:
        return TransitionResult("", False, f"Task {task_id} không tồn tại.")

    result = request_transition(task, new_status, actor)

    if result.final_status != task.status:
        update_task_fields(task_id, status=result.final_status)
        add_event(
            task_id, actor, "status",
            f"{task.status} → {result.final_status}",
        )
    if result.note:
        add_event(task_id, "system", "system", result.note)
    return result


def search_tasks(query: str, limit: int = 5) -> list[Task]:
    like = f"%{query}%"
    rows = _db().execute(
        "SELECT * FROM tasks WHERE title LIKE ? OR description LIKE ? "
        "ORDER BY created_at DESC LIMIT ?",
        (like, like, limit),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


# ---------- Dependencies ----------

def add_dep(task_id: str, depends_on: str, dep_type: str = "blocks") -> None:
    with _lock:
        _db().execute(
            "INSERT OR IGNORE INTO deps VALUES (?,?,?)", (task_id, depends_on, dep_type)
        )
        _db().commit()


def get_deps(task_id: str) -> list[dict]:
    rows = _db().execute("SELECT * FROM deps WHERE task_id = ?", (task_id,)).fetchall()
    return [dict(r) for r in rows]


def deps_satisfied(task_id: str) -> bool:
    """Dep kiểu blocks được coi là xong khi task nguồn đã qua giai đoạn build."""
    for dep in get_deps(task_id):
        if dep["dep_type"] != "blocks":
            continue
        src = get_task(dep["depends_on"])
        if src and src.status not in ("testing", "review", "done", "archived"):
            return False
    return True


# ---------- Events ----------

def add_event(task_id: str, agent: str, kind: str, message: str) -> Event:
    ts = now_iso()
    with _lock:
        cur = _db().execute(
            "INSERT INTO events(task_id, agent, kind, message, created_at) "
            "VALUES (?,?,?,?,?) RETURNING id",
            (task_id, agent, kind, message, ts),
        )
        event_id = cur.fetchone()[0]
        _db().commit()
    ev = Event(event_id, task_id, agent, kind, message, ts)
    bus.publish({"type": "event", "event": ev.to_dict()})
    return ev


def list_events(task_id: str | None = None, limit: int = 200) -> list[Event]:
    if task_id:
        rows = _db().execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY id LIMIT ?",
            (task_id, limit),
        ).fetchall()
    else:
        rows = _db().execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [Event(**dict(r)) for r in rows]


# ---------- Chat ----------

def add_chat(role: str, message: str) -> dict:
    ts = now_iso()
    with _lock:
        cur = _db().execute(
            "INSERT INTO chat(role, message, created_at) VALUES (?,?,?) RETURNING id",
            (role, message, ts),
        )
        chat_id = cur.fetchone()[0]
        _db().commit()
    msg = {"id": chat_id, "role": role, "message": message, "created_at": ts}
    bus.publish({"type": "chat", "message": msg})
    return msg


def list_chat(limit: int = 100) -> list[dict]:
    rows = _db().execute(
        "SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]
