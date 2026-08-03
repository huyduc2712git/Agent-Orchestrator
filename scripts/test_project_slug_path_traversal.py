"""
Test: POST /api/projects với slug chứa "../" KHÔNG được phép thoát khỏi projects_root
khi tự động tính project_dir để clone git vào.

Bug cũ: slug chưa sanitize trước khi tính project_dir tự động -> đã verify khai thác
được thật, clone repo ra ngoài /tmp (hoàn toàn ngoài projects_root dự kiến).

Cách chạy:
    python scripts/test_project_slug_path_traversal.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import settings  # noqa: E402
from orchestrator.routes.projects import ProjectIn, create_project  # noqa: E402


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False
    projects_root = Path(settings.effective_projects_root()).resolve()
    malicious_slug = "../../../../tmp/evil-slug-traversal-test"

    body = ProjectIn(
        name="", slug=malicious_slug,
        git_url="https://github.com/octocat/Hello-World.git",
    )
    result = await create_project(body)

    project_dir = ""
    created_path = None
    if isinstance(result, dict) and result.get("ok"):
        project_dir = result.get("project", {}).get("project_dir", "")
        created_path = Path(project_dir).resolve() if project_dir else None

    print(f"  project_dir trả về: {project_dir}")

    ok_no_traversal_string = ".." not in project_dir
    print(f'  {"OK  " if ok_no_traversal_string else "FAIL"}  project_dir không còn chứa ".." literal')
    failed = failed or not ok_no_traversal_string

    ok_inside_root = created_path is not None and str(created_path).startswith(str(projects_root))
    print(f'  {"OK  " if ok_inside_root else "FAIL"}  thư mục thực tế nằm trong projects_root ({projects_root})')
    failed = failed or not ok_inside_root

    # Xác nhận /tmp KHÔNG có thư mục nào bị tạo ra ngoài ý muốn
    leaked_path = Path("/tmp/evil-slug-traversal-test")
    ok_not_leaked = not leaked_path.exists()
    print(f'  {"OK  " if ok_not_leaked else "FAIL"}  không có gì bị clone ra /tmp (ngoài projects_root)')
    failed = failed or not ok_not_leaked

    # Dọn dẹp thư mục test đã tạo (nếu có, trong phạm vi an toàn)
    if created_path and created_path.is_dir() and str(created_path).startswith(str(projects_root)):
        shutil.rmtree(created_path, ignore_errors=True)
    if leaked_path.exists():
        shutil.rmtree(leaked_path, ignore_errors=True)

    print()
    if failed:
        print("KẾT QUẢ: FAIL — path traversal qua slug vẫn khai thác được.")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — slug độc hại không thể thoát khỏi projects_root.")
    sys.exit(0)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
