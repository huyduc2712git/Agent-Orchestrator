"""Xuất báo cáo quy trình chạy task tsk-4895 ra file Markdown."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from orchestrator.board import store

def export_report(task_id: str = "tsk-4895"):
    t = store.get_task(task_id)
    if not t:
        print(f"Task {task_id} không tồn tại!")
        return

    subs = store.list_tasks(parent_id=task_id)
    
    md = []
    md.append(f"# Báo cáo Quy trình thực thi Task [{t.id}]")
    md.append(f"**Tiêu đề:** {t.title}")
    md.append(f"**Trạng thái:** `{t.status.upper()}`")
    md.append(f"**Project:** `{t.project}` ({t.project_dir})")
    md.append(f"**Tạo bởi:** `{t.created_by}` | **Thời gian khởi tạo:** {t.created_at}")
    md.append(f"**Cập nhật cuối:** {t.updated_at}\n")
    
    md.append("## 📝 Yêu cầu ban đầu (Description)")
    md.append(f"```text\n{t.description}\n```\n")
    
    md.append("---")
    md.append("## 👥 Tổng hợp các Subtasks & Bug Tickets được tạo")
    md.append("| ID | Loại | Agent gán | Trạng thái | Tiêu đề |")
    md.append("|---|---|---|---|---|")
    for s in subs:
        icon = "🐛" if s.type == "bug" else "📋"
        md.append(f"| {s.id} | {icon} {s.type} | `{s.assignee}` | `{s.status.upper()}` | {s.title} |")
    md.append("")
    
    md.append("---")
    md.append("## 🔄 Chi tiết Tiến trình & Deliverables theo từng Agent")
    
    # 1. Main task events
    main_events = store.list_events(t.id)
    if main_events:
        md.append(f"### 🎯 Task cha `{t.id}` Events")
        for ev in main_events:
            agent = ev.agent or "system"
            md.append(f"- **[{ev.created_at[:19]}] `{agent}` (`{ev.kind}`):** {ev.message}")
        md.append("")

    # 2. Subtasks & Bugs events
    for s in subs:
        sevents = store.list_events(s.id)
        icon = "🐛" if s.type == "bug" else "📋"
        md.append(f"### {icon} [{s.id}] {s.title}")
        md.append(f"- **Loại:** `{s.type}` | **Assignee:** `{s.assignee}` | **Status:** `{s.status.upper()}`")
        if s.description:
            md.append(f"- **Mô tả / Repro:** {s.description.strip()}")
        if sevents:
            md.append("- **Nhật ký sự kiện (Event log):**")
            for ev in sevents:
                agent = ev.agent or "system"
                md.append(f"  - **[{ev.created_at[:19]}] `{agent}` (`{ev.kind}`):** {ev.message}")
        md.append("")

    md.append("---")
    md.append("## 🏁 Tổng kết Quy trình Pipeline (Closure Summary)")
    md.append("1. **Phase 1-2 (Phân tích & Lập kế hoạch):** Conan nhận yêu cầu, tạo task cha `tsk-4895` và giao subtask `sub-6228` cho **Agasa** (Backend Specialist).")
    md.append("2. **Phase 3 (Thực thi Backend):** Agasa cập nhật `server.cjs` trong `D:\\AI-Projects\\smoke`, thêm endpoint `GET /api/health` trả về JSON `status: ok` và `timestamp`.")
    md.append("3. **Phase 4 (Visual & Automated QA):** **Heiji** tiến hành kiểm tra endpoint `http://127.0.0.1:3000/api/health` trả về HTTP 200 OK.")
    md.append("4. **Phase 5a (Security Review):** **Shuichi Akai** rà soát lỗ hổng bảo mật code `server.cjs`, phát hiện 2 lỗ hổng Path Traversal (`bug-3421`) & DoS Malformed URL (`bug-5999`). Giao **Kid** fix thành công.")
    md.append("5. **Phase 5b (Penetration Testing & Infra Review):** **Rei Furuya (Amuro)** thử tấn công pentest trên preview URL, phát hiện thêm 2 lỗ hổng hạ tầng preview (`bug-8991` & `bug-2208`). Giao **Kid** fix thành công.")
    md.append("6. **Phase 5c (Final Review & Approval):** **Conan** review độc lập toàn bộ chain deliverables, xác nhận mọi bug đều đã fix PASS, cấp **VERDICT: APPROVED** và chuyển task sang **DONE**.")

    report_path = Path(__file__).resolve().parent.parent / "task_tsk-4895_report.md"
    report_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Đã xuất file báo cáo tại: {report_path}")

if __name__ == "__main__":
    export_report()
