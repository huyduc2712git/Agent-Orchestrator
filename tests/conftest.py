"""Pytest fixtures and path setup for AI Orchestrator."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from tests.test_helpers import isolate_test_workspace


@pytest.fixture(autouse=True)
def isolated_workspace():
    """Tự động cách ly workspace & SQLite DB cho mỗi test case."""
    with isolate_test_workspace() as ws_path:
        yield ws_path
