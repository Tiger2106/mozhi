"""
VERIFY-003 测试夹具 — 依赖注入双模式（Option C）

双模式切换:
  - 默认 (mock): 内存 SQLite + 合成数据，无需真实 DB
  - 真实 DB:     VERIFY_003_USE_REAL_DB=true 环境变量

设计要点:
  1. conn fixture 在 mock 模式下返回内存 SQLite（合成 A50 数据）
  2. stock_codes / trade_dates 从内存 SQLite 读取，与 conn 一致
  3. 自动创建临时 SQLite 文件，patch test_noise_ic.DB_PATH 指向它
     → run_noise_ic_suite(..., db_path=DB_PATH) 自动使用 mock 数据
  4. 合成数据使用固定种子 (MOCK_SEED=42) 确保可复现

Author: 墨衡
Created: 2026-06-01T12:51:00+08:00
"""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pytest

# ── 路径补丁 ──────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent            # tests/
_VERIFY_DIR = _THIS_DIR.parent                          # verify_003/
if str(_VERIFY_DIR) not in sys.path:
    sys.path.insert(0, str(_VERIFY_DIR))

_MOZHI = r"C:\Users\17699\mozhi_platform"
if _MOZHI not in sys.path:
    sys.path.insert(0, _MOZHI)


# ── 模式选择 ──────────────────────────────────

REAL_DB_PATH = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"
USE_REAL_DB = os.environ.get("VERIFY_003_USE_REAL_DB", "").lower() in (
    "true", "1", "yes"
)

# Mock 配置（固定种子确保可复现）
N_MOCK_CODES = 50
N_MOCK_DATES = 60          # > 50 用于 N_DATES=50 筛选
MOCK_SEED = 33
BASE_PRICE = 50.0
PRICE_VOL = 0.02           # 日收益率标准差 ≈ 2%


# ── 辅助: 创建模拟数据库 ─────────────────────


def _create_mock_data(conn: sqlite3.Connection):
    """用模拟 A50 数据填充数据库连接。

    数据结构:
      - a50_universe: 50 只模拟股票代码 (600000.SH ~ 600049.SH)
      - a50_daily_ohlcv: 每个股票 × N_MOCK_DATES 个交易日
        · 前向收益率: i.i.d. N(0, PRICE_VOL²)，截面内中心化
        · 价格: 累积前向收益率得出

    注意:
      每个截面的前向收益率在股票间中心化（均值为0），
      确保随机因子与前向收益率之间的 Rank IC 统计
      更接近理论预期，减少采样波动。
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS a50_universe (
            ts_code TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS a50_daily_ohlcv (
            ts_code TEXT,
            trade_date TEXT,
            adj_close_b REAL,
            PRIMARY KEY (ts_code, trade_date)
        );
    """)

    rng = np.random.default_rng(MOCK_SEED)

    # 股票代码（模拟 A50 风格）
    codes = [f"600{i:03d}.SH" for i in range(N_MOCK_CODES)]
    for code in codes:
        conn.execute(
            "INSERT OR IGNORE INTO a50_universe (ts_code) VALUES (?)",
            (code,),
        )

    # 初始价格
    prices = {code: BASE_PRICE + rng.uniform(-20, 20) for code in codes}

    # 生成交易日序列和价格
    import datetime as dtm

    start = dtm.date(2026, 3, 1)
    day_offset = 0
    inserted = 0

    while inserted < N_MOCK_DATES:
        current_date = start + dtm.timedelta(days=day_offset)
        if current_date.weekday() < 5:
            date_str = current_date.strftime("%Y%m%d")

            # 生成截面级日收益率并中心化
            raw_returns = rng.normal(0, PRICE_VOL, size=len(codes))
            raw_returns -= np.mean(raw_returns)  # 中心化

            for i, code in enumerate(codes):
                prices[code] *= 1.0 + raw_returns[i]
                conn.execute(
                    "INSERT OR IGNORE INTO a50_daily_ohlcv "
                    "(ts_code, trade_date, adj_close_b) VALUES (?, ?, ?)",
                    (code, date_str, round(prices[code], 4)),
                )
            inserted += 1
        day_offset += 1

    conn.commit()


def _create_mock_db_file() -> str:
    """创建包含模拟数据的临时 SQLite 文件，返回路径。"""
    tmp = tempfile.NamedTemporaryFile(
        suffix="_mock_a50.db", delete=False,
    )
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    try:
        _create_mock_data(conn)
    finally:
        conn.close()
    return tmp.name


# ── Session autouse: patch DB_PATH ────────────


@pytest.fixture(scope="session", autouse=True)
def _mock_db_patch():
    """[autouse] Mock 模式下将 DB_PATH 指向临时 mock 数据库文件。

    补丁目标:
      test_noise_ic.DB_PATH   — 测试模块中的 DB_PATH 常量
      lib.random_ic_analysis.DB_PATH — lib 模块中的 DB_PATH 常量

    注: 使用 sys.modules 查找已加载模块，避免
    `from tests import test_noise_ic` 被 mozhi_platform/tests 劫持。
    """
    if USE_REAL_DB:
        yield
        return

    mock_path = _create_mock_db_file()

    # 从 sys.modules 获取已加载的模块（pytest 在 collection 阶段已导入）
    import importlib

    # 查找 verify_003 下的模块
    test_mod = lib_mod = None
    for mod_name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None) or ""
        if "verify_003" not in f:
            continue
        if mod_name.endswith("test_noise_ic"):
            test_mod = mod
        if mod_name.endswith("random_ic_analysis"):
            lib_mod = mod

    # 如果 sys.modules 中没找到（理论不会发生），回退到 importlib
    if test_mod is None:
        test_mod = importlib.import_module("test_noise_ic")
    if lib_mod is None:
        lib_mod = importlib.import_module("lib.random_ic_analysis")

    test_mod.DB_PATH = mock_path
    lib_mod.DB_PATH = mock_path

    yield

    # 清理临时文件
    try:
        os.unlink(mock_path)
    except (OSError, FileNotFoundError):
        pass


# ── Session fixtures ─────────────────────────


@pytest.fixture(scope="session")
def conn():
    """数据库连接（会话级别复用）。

    - mock 模式: 返回内存 SQLite（合成数据）
    - 真实 DB 模式: 连接到真实的 a50_ic.db
    """
    if USE_REAL_DB:
        c = sqlite3.connect(REAL_DB_PATH)
        yield c
        c.close()
    else:
        c = sqlite3.connect(":memory:")
        _create_mock_data(c)
        yield c
        c.close()


@pytest.fixture(scope="session")
def stock_codes(conn):
    """获取 A50 成分股列表。"""
    rows = conn.execute(
        "SELECT ts_code FROM a50_universe ORDER BY ts_code",
    ).fetchall()
    return [r[0] for r in rows]


@pytest.fixture(scope="session")
def trade_dates(conn):
    """获取最近 N_DATES 个交易日（升序）。"""
    # 从 sys.modules 中已加载的 test_noise_ic 读取 N_DATES
    _n_dates = 50  # 默认值
    for mod_name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None) or ""
        if "verify_003" in f and mod_name.endswith("test_noise_ic"):
            _n_dates = getattr(mod, "N_DATES", 50)
            break

    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM a50_daily_ohlcv "
        "ORDER BY trade_date DESC LIMIT ?",
        (_n_dates,),
    ).fetchall()
    dates = [r[0] for r in rows]
    dates.reverse()
    return dates
