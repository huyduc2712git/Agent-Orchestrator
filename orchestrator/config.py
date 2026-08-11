"""Cấu hình chung, đọc từ .env ở gốc dự án."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
# override=True: key mới trong .env thắng biến môi trường cũ (Windows/shell)
load_dotenv(ROOT_DIR / ".env", override=True)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash-free")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# Model "thinking" đốt phần lớn budget vào reasoning_tokens; budget nhỏ khiến
# content trả về rỗng hoặc JSON bị cắt giữa chừng (finish_reason=length).
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16384"))
LLM_MAX_TOKENS_CEILING = int(os.getenv("LLM_MAX_TOKENS_CEILING", "32768"))

# Phân bổ model theo thế mạnh, tránh dồn hết cho một model:
#   planner  — lập kế hoạch, chain-of-thought dài, tool calling tin cậy
#   coder    — viết/sửa code thật
#   critic   — QA/validation, cần bám prompt chuẩn và ít bịa
#   summary  — tổng hợp, memory, tài liệu (rẻ và nhanh)
MODEL_PLANNER = os.getenv("MODEL_PLANNER", "deepseek-v4-flash-free")
MODEL_CODER = os.getenv("MODEL_CODER", "deepseek-v4-flash-free")
MODEL_CRITIC = os.getenv("MODEL_CRITIC", "nemotron-3-ultra-free")
MODEL_SUMMARY = os.getenv("MODEL_SUMMARY", "mimo-v2.5-free")
# Vision: không có default free — phải gán model hỗ trợ ảnh trong Settings (role vision)
MODEL_VISION = os.getenv("MODEL_VISION", "")

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8600"))
BASE_URL = f"http://{HOST}:{PORT}"

WORKSPACE_DIR = ROOT_DIR / "workspace"
MEMORY_DIR = WORKSPACE_DIR / "memory"
WIKI_DIR = WORKSPACE_DIR / "wiki"
ARTIFACTS_DIR = WORKSPACE_DIR / "artifacts"
UPLOADS_DIR = WORKSPACE_DIR / "uploads"
PROJECTS_DIR = WORKSPACE_DIR / "projects"
DB_PATH = WORKSPACE_DIR / "board.db"
WEB_DIR = ROOT_DIR / "web"

# Giới hạn an toàn cho agent runtime
MAX_AGENT_ITERATIONS = 45
COMMAND_TIMEOUT_SECONDS = 120
MAX_TOOL_OUTPUT_CHARS = 12_000
# Giữ N tool result gần nhất đủ dài; các tool cũ bị cắt để giảm input tokens
TOOL_HISTORY_KEEP_RECENT = int(os.getenv("TOOL_HISTORY_KEEP_RECENT", "6"))
TOOL_HISTORY_OLD_CHARS = int(os.getenv("TOOL_HISTORY_OLD_CHARS", "500"))
MAX_CONCURRENT_AGENTS = 1
CHAT_IMAGE_MAX_BYTES = 8 * 1024 * 1024
# Nén ảnh trước khi gửi vision API (tránh 413 Payload Too Large — Cloudflare/Workers AI)
VISION_IMAGE_MAX_SIDE = 1280
VISION_IMAGE_JPEG_QUALITY = 82
VISION_IMAGE_MAX_BYTES = 900_000  # ~0.9MB raw → base64 vẫn dưới giới hạn payload thường gặp

# Board Patrol quét định kỳ (giây)
PATROL_INTERVAL_SECONDS = 30 * 60
SCHEDULER_INTERVAL_SECONDS = 3

for _d in (WORKSPACE_DIR, MEMORY_DIR, WIKI_DIR, ARTIFACTS_DIR, UPLOADS_DIR, PROJECTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
