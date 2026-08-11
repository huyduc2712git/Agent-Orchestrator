"""Test helpers & workspace isolation fixture for AI Orchestrator tests."""
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from orchestrator import config
from orchestrator.board import store


@contextmanager
def isolate_test_workspace() -> Generator[Path, None, None]:
    """Tạo workspace & SQLite DB cô lập trong temp directory.
    Đảm bảo:
    1. Không ghi đè hay tạo dữ liệu rác trong workspace/board.db
    2. Không tạo thư mục project trong workspace/projects/
    3. Tự động đóng kết nối DB và dọn dẹp sạch sẽ 100% khi kết thúc.
    """
    old_db_path = config.DB_PATH
    old_workspace_dir = config.WORKSPACE_DIR
    old_artifacts_dir = config.ARTIFACTS_DIR
    old_wiki_dir = config.WIKI_DIR
    old_memory_dir = config.MEMORY_DIR
    old_uploads_dir = config.UPLOADS_DIR

    # Đóng kết nối DB cũ nếu có
    if store._conn is not None:
        try:
            store._conn.close()
        except Exception:
            pass
        store._conn = None

    tmp_dir = tempfile.mkdtemp(prefix="orch_test_ws_")
    tmp_path = Path(tmp_dir).resolve()

    try:
        # Chuyển toàn bộ đường dẫn runtime sang temp dir
        config.WORKSPACE_DIR = tmp_path
        config.DB_PATH = tmp_path / "test_board.db"
        config.ARTIFACTS_DIR = tmp_path / "artifacts"
        config.WIKI_DIR = tmp_path / "wiki"
        config.MEMORY_DIR = tmp_path / "memory"
        config.UPLOADS_DIR = tmp_path / "uploads"

        config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        config.WIKI_DIR.mkdir(parents=True, exist_ok=True)
        config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        (tmp_path / "projects").mkdir(parents=True, exist_ok=True)

        # Khởi tạo DB connection & schema
        store._db()

        yield tmp_path

    finally:
        # Đóng DB kết nối
        if store._conn is not None:
            try:
                store._conn.close()
            except Exception:
                pass
            store._conn = None

        # Khôi phục config gốc
        config.DB_PATH = old_db_path
        config.WORKSPACE_DIR = old_workspace_dir
        config.ARTIFACTS_DIR = old_artifacts_dir
        config.WIKI_DIR = old_wiki_dir
        config.MEMORY_DIR = old_memory_dir
        config.UPLOADS_DIR = old_uploads_dir

        # Xóa sạch thư mục temp
        shutil.rmtree(tmp_path, ignore_errors=True)
