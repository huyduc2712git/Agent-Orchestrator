"""Model dữ liệu cho board: Task, Dependency, Event."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

STATUSES = ["backlog", "in_progress", "blocked", "testing", "review", "done", "archived"]

TASK_TYPES = ["task", "bug"]
REVIEW_TYPES = ["agent", "operator"]
SEVERITIES = ["low", "medium", "high", "critical"]
DEP_TYPES = ["blocks", "related"]

# Tag nào xuất hiện -> bắt buộc operator review (người thật duyệt)
OPERATOR_REVIEW_TAGS = {"db-migration", "security", "deploy-prod"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    type: str = "task"  # task | bug
    status: str = "backlog"
    assignee: str = ""  # tên agent hoặc "" (chưa gán)
    project: str = "default"
    project_dir: str = ""  # thư mục agent được phép thao tác
    parent_id: str = ""  # subtask trỏ về task cha
    tags: list[str] = field(default_factory=list)
    review_type: str = "agent"  # agent | operator
    severity: str = ""  # chỉ dùng cho bug
    repro_steps: str = ""  # chỉ dùng cho bug
    created_by: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.type,
            "status": self.status,
            "assignee": self.assignee,
            "project": self.project,
            "project_dir": self.project_dir,
            "parent_id": self.parent_id,
            "tags": self.tags,
            "review_type": self.review_type,
            "severity": self.severity,
            "repro_steps": self.repro_steps,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Event:
    id: int
    task_id: str
    agent: str
    kind: str  # comment | status | system
    message: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent": self.agent,
            "kind": self.kind,
            "message": self.message,
            "created_at": self.created_at,
        }
