"""墨枢平台共享配置模块

集中管理平台路径配置，消除各模块中的硬编码。
所有路径通过 pathlib 基于用户目录自动解析。

用法:
    from src.config import PROJECT_ROOT, SHARED_REPORTS, ANALYSIS_DB, SIGNALS_TASKS_DIR, SHANGHAI_TZ

Author: 墨衡
Created: 2026-05-16
"""

import os
import re
from pathlib import Path

from datetime import timezone, timedelta

SHANGHAI_TZ = timezone(timedelta(hours=8))


# ── get_mozhihome() ❲墨枢平台根目录❳ ─────────────────
# 优先读环境变量 MOZHIHOME，未设置时通过模块路径自动推断。
def get_mozhihome() -> Path:
    """获取墨枢平台根目录。

    优先级：
      1. 环境变量 MOZHIHOME（最高优先级）
      2. 模块路径自动推断：src/config.py → mozhi_platform/
      3. 工作目录推断（若 cwd/src/ 存在）
      4. 回退：~/mozhi_platform
    """
    env_home = os.environ.get("MOZHIHOME")
    if env_home:
        return Path(env_home).resolve()
    _config_dir = Path(__file__).resolve().parent  # src/
    if _config_dir.name == "src":
        return _config_dir.parent  # mozhi_platform/
    cwd = Path(os.getcwd()).resolve()
    if (cwd / "src").is_dir():
        return cwd
    return Path.home() / "mozhi_platform"


# ── 项目根目录 ❲自动推断❳ ────────────────────────────
PROJECT_ROOT = get_mozhihome()

# ── 共享报告目录 ❲环境变量可覆盖❳ ─────────────────────
# 新产出文件统一写入 mozhi_platform/reports/
SHARED_REPORTS = Path(
    os.environ.get("MOZHI_SHARED_REPORTS",
                   str(PROJECT_ROOT / "reports"))
)

# ── 派生路径 ──────────────────────────────────────────
ANALYSIS_DB = SHARED_REPORTS / "analysis.db"
MARKET_DATA_DB = PROJECT_ROOT / "data" / "market" / "market_data.db"
PIPELINE_CACHE_DB = PROJECT_ROOT / "data" / "pipeline_cache.db"  # DB_UNIFY_0525: 管线缓存库
KNOWLEDGE_DB = PROJECT_ROOT / "data" / "knowledge.db"

SIGNALS_DIR = SHARED_REPORTS / "signals"
SIGNALS_TASKS_DIR = SIGNALS_DIR / "tasks"

OUT_DIR = PROJECT_ROOT / "reports" / "backtest"
CHART_DIR = PROJECT_ROOT / "reports" / "charts"
LOG_DIR = PROJECT_ROOT / "logs"

# ── 确保目录存在 ──────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── Symbol 格式化 ──────────────────────────────────────────
# A 股代码归一为标准 XXXXXX.SH（上交所主板默认）

SYMBOL_PATTERN = re.compile(r"^\d{6}(\.(SH|SZ|BJ))?$")


def normalize_symbol(symbol: str) -> str:
    """统一 symbol 格式为 XXXXXX.SH（A股主逻辑板）"""
    if not symbol:
        return symbol
    symbol = symbol.strip().upper()
    m = SYMBOL_PATTERN.match(symbol)
    if not m:
        return symbol  # 非标准格式，原样返回
    if "." in symbol:
        return symbol  # 已有后缀
    # 裸码：601857 → 601857.SH（默认主板上交所）
    return f"{symbol}.SH"


def init_sys_path():
    """将 PROJECT_ROOT 加入 sys.path（替代 _pipeline_main.py 中的硬编码 BASE）。"""
    import sys
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    if str(SHARED_REPORTS) not in sys.path:
        sys.path.append(str(SHARED_REPORTS))
