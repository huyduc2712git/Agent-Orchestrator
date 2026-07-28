"""Cấu hình chung, đọc từ .env ở gốc dự án."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash-free")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# Phân bổ model theo thế mạnh, tránh dồn hết cho một model:
#   planner  — lập kế hoạch, chain-of-thought dài, tool calling tin cậy
#   coder    — viết/sửa code thật
#   critic   — QA/validation, cần bám prompt chuẩn và ít bịa
#   summary  — tổng hợp, memory, tài liệu (rẻ và nhanh)
MODEL_PLANNER = os.getenv("MODEL_PLANNER", "deepseek-v4-flash-free")
MODEL_CODER = os.getenv("MODEL_CODER", "deepseek-v4-flash-free")
MODEL_CRITIC = os.getenv("MODEL_CRITIC", "nemotron-3-ultra-free")
MODEL_SUMMARY = os.getenv("MODEL_SUMMARY", "mimo-v2.5-free")

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8600"))
BASE_URL = f"http://{HOST}:{PORT}"

WORKSPACE_DIR = ROOT_DIR / "workspace"
MEMORY_DIR = WORKSPACE_DIR / "memory"
WIKI_DIR = WORKSPACE_DIR / "wiki"
ARTIFACTS_DIR = WORKSPACE_DIR / "artifacts"
DB_PATH = WORKSPACE_DIR / "board.db"
WEB_DIR = ROOT_DIR / "web"

# Giới hạn an toàn cho agent runtime
MAX_AGENT_ITERATIONS = 25
COMMAND_TIMEOUT_SECONDS = 120
MAX_TOOL_OUTPUT_CHARS = 12_000
MAX_CONCURRENT_AGENTS = 1

# Board Patrol quét định kỳ (giây)
PATROL_INTERVAL_SECONDS = 30 * 60
SCHEDULER_INTERVAL_SECONDS = 3

for _d in (WORKSPACE_DIR, MEMORY_DIR, WIKI_DIR, ARTIFACTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
