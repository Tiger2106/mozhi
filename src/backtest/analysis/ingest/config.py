"""config.py — 默认路径、常量配置

P0 MVP: 默认路径推断（pyproject.toml 搜索定位）
"""

from __future__ import annotations

from pathlib import Path


# ——— 默认常量 ———

DEFAULT_SCHEMA_VERSION = "4.0"
"""分析层 schema 版本号，写入 schema_version 表"""

ANALYSIS_TYPE_TTL: dict[str, int] = {
    "summary": 60,         # 日盘后/盘中快速摘要
    "deep_analysis": 120,  # 深度分析
    "tech_review": 90,     # 技术审查
    "validation": 60,      # 校验
    "resolution": 60,      # 决议/归档
}
"""每种 analysis_type 的管道超时秒数"""


# ——— 路径推断工具 ———

def find_project_root() -> Path:
    """搜索 pyproject.toml 定位项目根目录"""
    _current = Path(__file__).resolve()
    for parent in _current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError(
        f"找不到 pyproject.toml，无法确定项目根目录（从 {_current} 向上搜索）"
    )


def resolve_db_path(db_path: str | None = None) -> str:
    """返回数据库路径"""
    if db_path:
        return db_path
    root = find_project_root()
    return str(root / "data" / "backtest.db")


def resolve_signal_root(signal_root: str | None = None) -> str:
    """返回信号文件根目录 (.done/.failed)"""
    if signal_root:
        return signal_root
    root = find_project_root()
    return str(root.parent / "mo_zhi_sharereports" / "pipeline" / "tasks")


def resolve_archive_root(archive_root: str | None = None) -> str:
    """返回归档根目录"""
    if archive_root:
        return archive_root
    root = find_project_root()
    return str(root / "archive")
