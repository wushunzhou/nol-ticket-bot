"""
config.py — 从 .env 加载所有配置，提供带默认值的常量
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 优先加载项目根目录的 .env（src/ 上两级）
_root = Path(__file__).resolve().parents[3]
load_dotenv(_root / ".env", override=False)

# ── 演出信息 ──────────────────────────────────────
GOODS_CODE  = os.getenv("GOODS_CODE",  "26005973")
PLACE_CODE  = os.getenv("PLACE_CODE",  "26000437")
BIZ_CODE    = os.getenv("BIZ_CODE",    "10965")
LANG        = os.getenv("LANG",        "zh-CN")

BASE_URL    = "https://world.nol.com"

# ── 账号 ──────────────────────────────────────────
NOL_EMAIL    = os.getenv("NOL_EMAIL",    "")
NOL_PASSWORD = os.getenv("NOL_PASSWORD", "")

# ── 浏览器 ────────────────────────────────────────
CHROMIUM_PATH = os.getenv("CHROMIUM_PATH", "")
HEADLESS      = os.getenv("HEADLESS", "false").lower() == "true"
WINDOW_W      = 1280
WINDOW_H      = 800

# ── 购票行为 ──────────────────────────────────────
SEAT_GRADE_PREFERENCE = [
    g.strip().upper()
    for g in os.getenv("SEAT_GRADE_PREFERENCE", "VIP,R,S,A").split(",")
    if g.strip()
]
MAX_TICKETS         = int(os.getenv("MAX_TICKETS", "2"))
STOP_BEFORE_PAYMENT = os.getenv("STOP_BEFORE_PAYMENT", "true").lower() == "true"

# ── 轮询参数 ──────────────────────────────────────
POLL_INTERVAL     = float(os.getenv("POLL_INTERVAL",  "1.5"))
QUEUE_POLL        = 2.0
QUEUE_TIMEOUT     = int(os.getenv("QUEUE_TIMEOUT",    "600"))
PAGE_WAIT_TIMEOUT = 30
