"""
墨枢 (MoShu) — 回测知识库核心模块

在 mozhi_platform 中的位置：
 回测引擎 → _persist_result() → KnowledgeDB.store_run() → knowledge.db
 knowledge.db → aggregate_knowledge() → knowledge_entries
 knowledge_entries → KnowledgeExtractor → weekly_reference_{W}.yaml → 早报

三个原则：不替换只追加 / 可逆性 / 渐进实施

用法::

    from backtest.pipeline.knowledge_db import KnowledgeDB, make_run_id

    db = KnowledgeDB()
    db.initialize()  # 幂等建表

    run_id = db.store_run(
        strategy_type="grid",
        symbol="601857.SH",
        config=config,
        result=result,
        config_key="v1_params",
    )

Author: 墨衡
Created: 2026-05-16
Version: 1.0
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

VALID_INSIGHT_CATEGORIES = frozenset({
    "sharp_drop",
    "sharpe_reversal",
    "win_rate_drop",
    "high_conflict",
    "consecutive_loss",
    "drawdown_breach",
    "drawdown_recovery",
    "allocation_bias",
})
"""
8 类预定义知识类别，与 KnowlegeExtractor 类别体系一致。

类别说明：
  sharp_drop         — 策略表现剧烈下滑
  sharpe_reversal    — 夏普比率反转（正→负 或 负→正）
  win_rate_drop      — 胜率显著下降
  high_conflict      — 多策略间冲突率高
  consecutive_loss   — 连续亏损事件
  drawdown_breach    — 回撤突破阈值
  drawdown_recovery  — 回撤恢复事件
  allocation_bias    — 资金分配偏差
"""


DDL_SCRIPT = """
-- ============================================================
-- 墨枢 — 回测知识库 DDL
-- 对应设计方案 §2.2（v2.2）
-- 六张表 + 索引：backtest_runs, params_snapshot, market_context,
--               performance_results, knowledge_entries,
--               knowledge_run_links
-- ============================================================

-- 1. backtest_runs — 回测运行主表
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id              TEXT PRIMARY KEY,
    strategy            TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    config_key          TEXT NOT NULL DEFAULT '',
    strategy_tag        TEXT NOT NULL DEFAULT '',
    start_date          TEXT NOT NULL DEFAULT '',
    end_date            TEXT NOT NULL DEFAULT '',
    data_days           INTEGER NOT NULL DEFAULT 0,
    param_version       TEXT NOT NULL DEFAULT '',
    run_by              TEXT NOT NULL DEFAULT 'auto',
    triggered_by        TEXT NOT NULL DEFAULT '',
    report_path         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy ON backtest_runs(strategy);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_symbol   ON backtest_runs(symbol);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created  ON backtest_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_symbol_created ON backtest_runs(strategy, symbol, created_at DESC);

-- 2. params_snapshot — 参数快照
CREATE TABLE IF NOT EXISTS params_snapshot (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL UNIQUE,
    param_version       TEXT NOT NULL DEFAULT 'v0_initial',
    params_json         TEXT NOT NULL,
    diff_from_prev      TEXT NOT NULL DEFAULT '{}',
    snapshot_time       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_params_snapshot_run_id   ON params_snapshot(run_id);
CREATE INDEX IF NOT EXISTS idx_params_snapshot_version  ON params_snapshot(param_version);

-- 3. market_context — 市场上下文
CREATE TABLE IF NOT EXISTS market_context (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    date_key            TEXT NOT NULL,
    symbol              TEXT NOT NULL DEFAULT '',
    market_regime       TEXT NOT NULL DEFAULT 'unknown',
    volatility_level    TEXT NOT NULL DEFAULT 'medium',
    trend_strength      REAL NOT NULL DEFAULT 0.0,
    sector_percentile   REAL DEFAULT NULL,
    macro_events        TEXT DEFAULT '[]',
    notes               TEXT DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_market_context_run_id ON market_context(run_id);
CREATE INDEX IF NOT EXISTS idx_market_context_date   ON market_context(date_key);
CREATE INDEX IF NOT EXISTS idx_market_context_regime ON market_context(market_regime);

-- 4. performance_results — 绩效结果
CREATE TABLE IF NOT EXISTS performance_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL UNIQUE,
    total_return_pct    REAL NOT NULL DEFAULT 0.0,
    annual_return_pct   REAL NOT NULL DEFAULT 0.0,
    sharpe_ratio        REAL NOT NULL DEFAULT 0.0,
    max_drawdown_pct    REAL NOT NULL DEFAULT 0.0,
    win_rate_pct        REAL NOT NULL DEFAULT 0.0,
    profit_factor       REAL NOT NULL DEFAULT 0.0,
    total_trades        INTEGER NOT NULL DEFAULT 0,
    avg_holding_bars    REAL NOT NULL DEFAULT 0.0,
    validity_grade      TEXT NOT NULL DEFAULT 'C',
    extra_metrics       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_performance_results_run_id  ON performance_results(run_id);
CREATE INDEX IF NOT EXISTS idx_performance_results_grade   ON performance_results(validity_grade);

-- 5. knowledge_entries — 知识条目（聚合表）
--    UNIQUE 复合约束：相同上下文+相同类别只保留一条
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    strategy            TEXT NOT NULL,
    param_version       TEXT NOT NULL DEFAULT '',
    market_regime       TEXT NOT NULL DEFAULT 'any',
    insight_category    TEXT NOT NULL,
    confidence          TEXT NOT NULL DEFAULT 'medium',
    sample_size         INTEGER NOT NULL DEFAULT 0,
    avg_return_pct      REAL NOT NULL DEFAULT 0.0,
    avg_sharpe          REAL NOT NULL DEFAULT 0.0,
    avg_max_dd_pct      REAL NOT NULL DEFAULT 0.0,
    insight_summary     TEXT NOT NULL DEFAULT '',
    source_run_ids      TEXT NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'active',
    activated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_updated_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deprecated_at       TEXT DEFAULT NULL,
    UNIQUE(symbol, strategy, param_version, market_regime, insight_category)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_entries_symbol   ON knowledge_entries(symbol);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_strategy ON knowledge_entries(strategy);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_status   ON knowledge_entries(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_category ON knowledge_entries(insight_category);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_params   ON knowledge_entries(param_version, market_regime);

-- 6. knowledge_run_links — 知识-运行关联表（v2.2 新增）
--    多对多关系，外键级联
CREATE TABLE IF NOT EXISTS knowledge_run_links (
    knowledge_id        INTEGER NOT NULL,
    run_id              TEXT NOT NULL,
    PRIMARY KEY (knowledge_id, run_id),
    FOREIGN KEY (knowledge_id) REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_knowledge_run_links_kid ON knowledge_run_links(knowledge_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_run_links_rid ON knowledge_run_links(run_id);

-- 7. backtest_equity_series — 净值曲线明细（v7.4 新增）
CREATE TABLE IF NOT EXISTS backtest_equity_series (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    date_idx            INTEGER NOT NULL DEFAULT 0,
    date                TEXT NOT NULL DEFAULT '',
    equity              REAL NOT NULL DEFAULT 0.0,
    nav                 REAL NOT NULL DEFAULT 0.0,
    drawdown            REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_equity_series_run_id ON backtest_equity_series(run_id);
CREATE INDEX IF NOT EXISTS idx_equity_series_run_date ON backtest_equity_series(run_id, date_idx);

-- 8. backtest_trades — 交易明细（v7.4 新增）
CREATE TABLE IF NOT EXISTS backtest_trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    trade_idx           INTEGER NOT NULL DEFAULT 0,
    entry_date          TEXT NOT NULL DEFAULT '',
    exit_date           TEXT NOT NULL DEFAULT '',
    direction           TEXT NOT NULL DEFAULT '',
    entry_price         REAL NOT NULL DEFAULT 0.0,
    exit_price          REAL NOT NULL DEFAULT 0.0,
    quantity            REAL NOT NULL DEFAULT 0.0,
    pnl                 REAL NOT NULL DEFAULT 0.0,
    pnl_pct             REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_trades_run_id ON backtest_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_trades_run_idx ON backtest_trades(run_id, trade_idx);
"""


def _find_project_root() -> str:
    """
    从 knowledge_db.py 所在位置上溯到项目根目录。

    查找顺序：
    1. 从当前文件位置向上查找 pyproject.toml / setup.py
    2. 检查 MOZHI_PLATFORM_ROOT 环境变量
    3. 都找不到则 raise RuntimeError（含可操作命令）

    Returns
    -------
    str
        项目根目录的绝对路径。
    """
    # 从 __file__ 所在目录开始上溯
    current = os.path.dirname(os.path.abspath(__file__))
    while current:
        if os.path.exists(os.path.join(current, "pyproject.toml")):
            return current
        if os.path.exists(os.path.join(current, "setup.py")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            # 到达文件系统根仍未找到 → 尝试环境变量
            env_root = os.environ.get("MOZHI_PLATFORM_ROOT")
            if env_root:
                return env_root
            raise RuntimeError(
                "无法确定项目根目录。请执行以下任一操作：\n"
                " 1. 在项目根目录创建 pyproject.toml 或 setup.py\n"
                " 2. 设置环境变量 MOZHI_PLATFORM_ROOT "
                "(例如: set MOZHI_PLATFORM_ROOT=C:\\path\\to\\mozhi_platform)"
            )
        current = parent
    raise RuntimeError(
        "无法确定项目根目录。请执行以下任一操作：\n"
        " 1. 在项目根目录创建 pyproject.toml 或 setup.py\n"
        " 2. 设置环境变量 MOZHI_PLATFORM_ROOT "
        "(例如: set MOZHI_PLATFORM_ROOT=C:\\path\\to\\mozhi_platform)"
    )


def make_run_id(
    strategy: str,
    symbol: str,
    config_key: str = "",
    tag: str = "",
) -> str:
    """
    统一 run_id 生成函数。

    格式：run_{strategy}_{symbol}_{config_key}_{tag}_{YYYYMMDD_HHMMSS_ffffff}

    各策略 JSON 文件名与新 run_id 的对应关系：
      grid_{symbol}_{config_key}_{tag}_{date}_{time}.json
        → run_grid_{symbol}_{config_key}_{tag}_{date}_{time}
      trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json
        → run_trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}
      reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json
        → run_reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}

    参数
    ----------
    strategy : str
        'grid' | 'trend' | 'reversal'
    symbol : str
        标的代码，如 '601857.SH'
    config_key : str
        配置键（可选）
    tag : str
        策略标签（可选）

    Returns
    -------
    str
        格式为 run_{strategy}_{symbol}_{config_key}_{tag}_{YYYYMMDD_HHMMSS_ffffff}
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    parts = [strategy, symbol, config_key, tag, ts]
    return f"run_{'_'.join(p for p in parts if p)}"


# 默认数据库路径：项目根目录 / data / knowledge.db
try:
    PROJECT_ROOT = _find_project_root()
except RuntimeError:
    # 若无法确定项目根目录，回退到基于 __file__ 的相对路径
    PROJECT_ROOT = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )

DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "knowledge.db")
"""默认知识库数据库路径。"""


# 模块级日志记录器
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# KnowledgeDB
# ═══════════════════════════════════════════════════════════════


class KnowledgeDB:
    """
    回测知识库数据库操作封装。

    所有数据库操作通过此类完成，包括建表、写入、查询、聚合、衰减等。
    使用 SQLite WAL 模式 + busy_timeout 保障并发安全。
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        初始化 KnowledgeDB 实例。

        参数
        ----------
        db_path : str
            数据库文件路径，默认为 DEFAULT_DB_PATH
            (项目根目录/data/knowledge.db)
        """
        self.db_path = db_path
        self._conn_inner: Optional[sqlite3.Connection] = None

    # ── 连接管理 ───────────────────────────────────────────

    @contextmanager
    def _conn(self):
        """
        获取数据库连接（懒加载 + 上下文管理器）。

        WAL 模式 + busy_timeout 支持并发读写。
        foreign_keys=ON 确保级联删除生效。

        Yields
        ------
        sqlite3.Connection
        """
        if self._conn_inner is None:
            self._conn_inner = sqlite3.connect(self.db_path)
            self._conn_inner.execute("PRAGMA journal_mode=WAL;")
            self._conn_inner.execute("PRAGMA foreign_keys=ON;")
            self._conn_inner.execute("PRAGMA busy_timeout=3000;")
            self._conn_inner.row_factory = sqlite3.Row
        yield self._conn_inner

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn_inner is not None:
            self._conn_inner.close()
            self._conn_inner = None

    def __enter__(self) -> "KnowledgeDB":
        """上下文管理器入口。"""
        return self

    def __exit__(self, *args) -> None:
        """上下文管理器出口，自动关闭连接。"""
        self.close()

    # ── 热备份 ──────────────────────────────────────────────

    def backup(self, backup_dir: str = None) -> str:
        """
        使用 SQLite 在线备份 API 创建数据库热备份。

        在数据库正常运行状态下创建一致性备份，无需锁定表。

        参数
        ----------
        backup_dir : str, optional
            备份目录路径，默认备份到 ``data/db/`` 目录下的
            ``knowledge_backup_{YYYYMMDD}.db``

        返回
        -------
        str
            备份文件的绝对路径
        """
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(self.db_path), "db")

        os.makedirs(backup_dir, exist_ok=True)

        date_str = datetime.now().strftime("%Y%m%d")
        backup_path = os.path.join(backup_dir, f"knowledge_backup_{date_str}.db")

        with self._conn() as conn:
            backup_conn = sqlite3.connect(backup_path)
            try:
                conn.backup(backup_conn, pages=-1)
            finally:
                backup_conn.close()

        return os.path.abspath(backup_path)

    # ── 建表 ──────────────────────────────────────────────

    def initialize(self) -> None:
        """
        建立六张表和索引。幂等设计，可重复调用。

        执行 DDL_SCRIPT 中所有 CREATE TABLE IF NOT EXISTS
        和 CREATE INDEX IF NOT EXISTS 语句。

        Raises
        ------
        sqlite3.DatabaseError
            建表失败时抛出
        """
        with self._conn() as conn:
            conn.executescript(DDL_SCRIPT)
            conn.commit()

    # ── 核心 CRUD ────────────────────────────────────────────

    def store_run(
        self,
        strategy: str,
        symbol: str,
        config_key: str = "",
        strategy_tag: str = "",
        start_date: str = "",
        end_date: str = "",
        data_days: int = 0,
        param_version: str = "v0_initial",
        run_by: str = "auto",
        triggered_by: str = "",
        report_path: str = "",
        params_json: dict = None,
        diff_from_prev: dict = None,
        metrics: dict = None,
    ) -> str:
        """
        三步事务写入，返回 run_id。

        在单事务内完成以下写入（使用 ``with self._conn:`` 自动提交/回滚）：
          1. ``backtest_runs``    — 回测运行主记录
          2. ``params_snapshot``  — 参数快照
          3. ``performance_results`` — 绩效结果（含 ``validity_grade`` 自动判定）

        参数
        ----------
        strategy : str
            策略类型，如 'grid' | 'trend' | 'reversal'
        symbol : str
            标的代码，如 '601857.SH'
        config_key : str
            配置键（可选）
        strategy_tag : str
            策略标签（可选）
        start_date : str
            回测开始日期，格式 YYYYMMDD
        end_date : str
            回测结束日期，格式 YYYYMMDD
        data_days : int
            交易日数
        param_version : str
            参数版本号
        run_by : str
            执行者，'auto' | 'manual'
        triggered_by : str
            触发源，如 'scheduler' | 'webhook' | 'manual' | 'backfill'
        report_path : str
            对应 JSON 文件相对路径
        params_json : dict, optional
            完整参数字典（将 JSON 序列化存储）
        diff_from_prev : dict, optional
            与前一次同策略同标的的参数差异（将 JSON 序列化存储）
        metrics : dict, optional
            绩效指标字典，支持的字段：
            - total_return_pct (float)
            - annual_return_pct (float)
            - sharpe_ratio (float)
            - max_drawdown_pct (float)
            - win_rate_pct (float)
            - profit_factor (float)
            - total_trades (int)
            - avg_holding_bars (float)

        返回
        -------
        str
            生成的 run_id

        异常
        ------
        sqlite3.Error
            任一 INSERT 失败时事务整体回滚

        validity_grade 判定逻辑
        -----------------------
        | 等级 | 条件                                              |
        |:-----|:---------------------------------------------------|
        | A    | data_days >= 60 且 sharpe_ratio > 0.5 且 最大回撤 < 10 |
        | B    | data_days >= 20 且 sharpe_ratio > 0.0                |
        | C    | 不满足 B 级                                          |
        """
        run_id = make_run_id(strategy, symbol, config_key, strategy_tag)

        # ── validity_grade 判定 ──
        metrics = metrics or {}
        sharpe = float(metrics.get("sharpe_ratio", 0.0))
        dd = float(metrics.get("max_drawdown_pct", 100.0))

        if data_days >= 60 and sharpe > 0.5 and dd < 10:
            validity_grade = "A"
        elif data_days >= 20 and sharpe > 0.0:
            validity_grade = "B"
        else:
            validity_grade = "C"

        with self._conn() as conn:
            with conn:
                # Step 1: backtest_runs
                conn.execute(
                    """
                    INSERT INTO backtest_runs
                        (run_id, strategy, symbol, config_key, strategy_tag,
                         start_date, end_date, data_days, param_version, run_by,
                         triggered_by, report_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        strategy,
                        symbol,
                        config_key,
                        strategy_tag,
                        start_date,
                        end_date,
                        data_days,
                        param_version,
                        run_by,
                        triggered_by,
                        report_path,
                    ),
                )

                # Step 2: params_snapshot
                conn.execute(
                    """
                    INSERT INTO params_snapshot
                        (run_id, param_version, params_json, diff_from_prev)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        param_version,
                        json.dumps(params_json or {}, ensure_ascii=False),
                        json.dumps(diff_from_prev or {}, ensure_ascii=False),
                    ),
                )

                # Step 3: performance_results
                conn.execute(
                    """
                    INSERT INTO performance_results
                        (run_id, total_return_pct, annual_return_pct, sharpe_ratio,
                         max_drawdown_pct, win_rate_pct, profit_factor, total_trades,
                         avg_holding_bars, validity_grade)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        metrics.get("total_return_pct", 0.0),
                        metrics.get("annual_return_pct", 0.0),
                        metrics.get("sharpe_ratio", 0.0),
                        metrics.get("max_drawdown_pct", 0.0),
                        metrics.get("win_rate_pct", 0.0),
                        metrics.get("profit_factor", 0.0),
                        metrics.get("total_trades", 0),
                        metrics.get("avg_holding_bars", 0.0),
                        validity_grade,
                    ),
                )

        return run_id

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        按 run_id 查询完整回测运行记录。

        使用 LEFT JOIN 合并三张表（``backtest_runs`` + ``params_snapshot``
        + ``performance_results``），返回合并后的字典。若未找到则返回 None。

        JSON 字段（params_json / diff_from_prev / extra_metrics）
        在返回前自动反序列化为字典。

        参数
        ----------
        run_id : str
            回测运行 ID

        返回
        -------
        dict or None
            包含三张表所有字段的字典，键名前缀说明：
            - ``sv_*`` — 来自 params_snapshot
            - ``perf_*`` — 来自 performance_results
            无前缀字段来自 backtest_runs
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT
                    r.*,
                    p.param_version        AS sv_param_version,
                    p.params_json          AS sv_params_json,
                    p.diff_from_prev       AS sv_diff_from_prev,
                    p.snapshot_time        AS sv_snapshot_time,
                    f.total_return_pct     AS perf_total_return_pct,
                    f.annual_return_pct    AS perf_annual_return_pct,
                    f.sharpe_ratio         AS perf_sharpe_ratio,
                    f.max_drawdown_pct     AS perf_max_drawdown_pct,
                    f.win_rate_pct         AS perf_win_rate_pct,
                    f.profit_factor        AS perf_profit_factor,
                    f.total_trades         AS perf_total_trades,
                    f.avg_holding_bars     AS perf_avg_holding_bars,
                    f.validity_grade       AS perf_validity_grade,
                    f.extra_metrics        AS perf_extra_metrics,
                    f.created_at           AS perf_created_at
                FROM backtest_runs r
                LEFT JOIN params_snapshot p      ON r.run_id = p.run_id
                LEFT JOIN performance_results f  ON r.run_id = f.run_id
                WHERE r.run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            result = dict(row)

            # 反序列化 JSON 字段
            for json_key in ("sv_params_json", "sv_diff_from_prev", "perf_extra_metrics"):
                val = result.get(json_key)
                if val and isinstance(val, str):
                    try:
                        result[json_key] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass  # 保留原始字符串

            return result

    def list_runs(
        self,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        多条件查询回测运行记录。

        支持按 ``strategy`` 和 ``symbol`` 可选过滤，结果按
        ``created_at DESC`` 排序，支持分页。

        参数
        ----------
        strategy : str, optional
            策略类型过滤（精确匹配）
        symbol : str, optional
            标的代码过滤（精确匹配）
        limit : int
            每页条数，默认 20
        offset : int
            偏移量，默认 0

        返回
        -------
        list[dict]
            匹配的回测运行记录列表，每项为 ``backtest_runs`` 表的一行
        """
        conditions: List[str] = []
        params: List[Any] = []

        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        with self._conn() as conn:
            cursor = conn.execute(
                f"""
                SELECT * FROM backtest_runs
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── 回填接口 ──────────────────────────────────────────

    def backfill_run(
        self,
        run_id: str,
        strategy: str,
        symbol: str,
        config_key: str = "",
        strategy_tag: str = "",
        start_date: str = "",
        end_date: str = "",
        data_days: int = 0,
        param_version: str = "v0_backfill",
        run_by: str = "auto",
        triggered_by: str = "backfill",
        report_path: str = "",
        params_json: dict = None,
        metrics: dict = None,
    ) -> bool:
        """
        回填接口：单条写入回测运行记录，使用 ``INSERT OR IGNORE`` 避免重复写入。

        与 ``store_run()`` 的区别：
        - 需要外部提供 ``run_id``（而非自动生成）
        - 使用 ``INSERT OR IGNORE``，已存在时静默跳过而非报错
        - 更多字段有默认值（适用于历史 JSON 回填时字段不完整的情况）
        - 写入三条记录使用同一事务保护
        - 不自动判定 ``validity_grade``，由调用方传入或使用默认值

        参数
        ----------
        run_id : str
            回测运行 ID（外部生成，需保证唯一性）
        strategy : str
            策略类型，如 'grid' | 'trend' | 'reversal'
        symbol : str
            标的代码，如 '601857.SH'
        config_key : str
            配置键（可选）
        strategy_tag : str
            策略标签（可选）
        start_date : str
            回测开始日期，格式 YYYYMMDD
        end_date : str
            回测结束日期，格式 YYYYMMDD
        data_days : int
            交易日数
        param_version : str
            参数版本号，默认 'v0_backfill'
        run_by : str
            执行者，默认 'auto'
        triggered_by : str
            触发源，默认 'backfill'
        report_path : str
            对应 JSON 文件相对路径
        params_json : dict, optional
            完整参数字典（将 JSON 序列化存储）
        metrics : dict, optional
            绩效指标字典，字段同 ``store_run()``，额外支持 ``validity_grade``

        返回
        -------
        bool
            True 表示成功写入（或已存在且忽略），False 表示写入失败
        """
        metrics = metrics or {}

        try:
            with self._conn() as conn:
                with conn:
                    # Step 1: backtest_runs — INSERT OR IGNORE
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO backtest_runs
                            (run_id, strategy, symbol, config_key, strategy_tag,
                             start_date, end_date, data_days, param_version, run_by,
                             triggered_by, report_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            strategy,
                            symbol,
                            config_key,
                            strategy_tag,
                            start_date,
                            end_date,
                            data_days,
                            param_version,
                            run_by,
                            triggered_by,
                            report_path,
                        ),
                    )

                    # 若 backtest_runs 已存在（INSERT OR IGNORE 未实际插入），
                    # 则静默跳过整条记录（不写入 params_snapshot 和 performance_results）
                    if cursor.rowcount == 0:
                        return True  # 已有该记录，视为成功

                    # Step 2: params_snapshot — INSERT OR IGNORE
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO params_snapshot
                            (run_id, param_version, params_json)
                        VALUES (?, ?, ?)
                        """,
                        (
                            run_id,
                            param_version,
                            json.dumps(params_json or {}, ensure_ascii=False),
                        ),
                    )

                    # Step 3: performance_results — INSERT OR IGNORE
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO performance_results
                            (run_id, total_return_pct, annual_return_pct, sharpe_ratio,
                             max_drawdown_pct, win_rate_pct, profit_factor, total_trades,
                             avg_holding_bars, validity_grade)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            metrics.get("total_return_pct", 0.0),
                            metrics.get("annual_return_pct", 0.0),
                            metrics.get("sharpe_ratio", 0.0),
                            metrics.get("max_drawdown_pct", 0.0),
                            metrics.get("win_rate_pct", 0.0),
                            metrics.get("profit_factor", 0.0),
                            metrics.get("total_trades", 0),
                            metrics.get("avg_holding_bars", 0.0),
                            metrics.get("validity_grade", "C"),
                        ),
                    )

            return True
        except sqlite3.Error as e:
            logger.error("回填失败 run_id=%s, strategy=%s, symbol=%s: %s",
                         run_id, strategy, symbol, e)
            return False

    def update_performance(
        self,
        run_id: str,
        metrics: dict,
    ) -> bool:
        """
        补录绩效：更新 ``performance_results`` 表中指定 run_id 的记录。

        只更新 ``metrics`` 中非 None 的字段。
        若某字段为 None 或缺失，则不修改数据库中该字段的现有值。

        参数
        ----------
        run_id : str
            回测运行 ID
        metrics : dict
            需要更新的绩效指标字典，支持的字段：
            - total_return_pct, annual_return_pct, sharpe_ratio
            - max_drawdown_pct, win_rate_pct, profit_factor
            - total_trades, avg_holding_bars, validity_grade
            - extra_metrics (dict, 将 JSON 序列化存储)

        返回
        -------
        bool
            True 表示有记录被更新，False 表示未找到对应记录或更新失败
        """
        # 绩效表字段 → metrics 键名映射
        field_map = {
            "total_return_pct": "total_return_pct",
            "annual_return_pct": "annual_return_pct",
            "sharpe_ratio": "sharpe_ratio",
            "max_drawdown_pct": "max_drawdown_pct",
            "win_rate_pct": "win_rate_pct",
            "profit_factor": "profit_factor",
            "total_trades": "total_trades",
            "avg_holding_bars": "avg_holding_bars",
            "validity_grade": "validity_grade",
        }

        # 收集需要更新的字段
        set_clauses: List[str] = []
        set_params: List[Any] = []

        for db_col, metric_key in field_map.items():
            value = metrics.get(metric_key)
            if value is not None:
                set_clauses.append(f"{db_col} = ?")
                set_params.append(value)

        # 处理 extra_metrics（JSON 序列化）
        extra = metrics.get("extra_metrics")
        if extra is not None:
            set_clauses.append("extra_metrics = ?")
            set_params.append(
                json.dumps(extra, ensure_ascii=False) if isinstance(extra, dict) else extra
            )

        if not set_clauses:
            return False  # 无有效更新字段

        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    f"""
                    UPDATE performance_results
                    SET {', '.join(set_clauses)}
                    WHERE run_id = ?
                    """,
                    [*set_params, run_id],
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error("补录绩效失败 run_id=%s: %s", run_id, e)
            return False

    def get_performance(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        查询单条绩效记录。

        参数
        ----------
        run_id : str
            回测运行 ID

        返回
        -------
        dict or None
            ``performance_results`` 表的一行，包含所有字段。
            ``extra_metrics`` 自动反序列化为字典。
            未找到时返回 None。
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM performance_results
                WHERE run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            result = dict(row)

            # 反序列化 extra_metrics
            extra_metrics = result.get("extra_metrics")
            if extra_metrics and isinstance(extra_metrics, str):
                try:
                    result["extra_metrics"] = json.loads(extra_metrics)
                except (json.JSONDecodeError, TypeError):
                    pass

            return result

    # ── 知识聚合 ──────────────────────────────────────────

    def aggregate_knowledge(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        market_regime: str = "any",
    ) -> int:
        """
        从 performance_results 按 strategy、symbol 分组聚合知识条目。

        对每组合并计算 sample_size、avg_return、avg_sharpe、avg_max_dd，
        用 UPSERT 模式写入或更新 knowledge_entries 表。

        参数
        ----------
        symbol : str, optional
            标的过滤（精确匹配），默认全量聚合
        strategy : str, optional
            策略类型过滤（精确匹配），默认全量聚合
        market_regime : str
            默认市场状态值（当 market_context 无数据时使用），默认 "any"

        返回
        -------
        int
            本次新增/更新的知识条目数

        confidence 判定逻辑
        -----------------------
        | 等级   | 条件                                                  |
        |:-------|:------------------------------------------------------|
        | high   | sample_size>=5 AND avg_sharpe>0.5 AND avg_max_dd<8     |
        | medium | sample_size>=2（不满足 high 条件）                      |
        | low    | sample_size<2                                          |
        """
        conditions: List[str] = []
        params: List[Any] = [market_regime]

        # v7.3: 过滤尚未回填市场状态的回测（NULL），避免计入"any"分类导致统计偏差
        conditions.append("mc.market_regime IS NOT NULL AND mc.market_regime != 'any'")

        if symbol:
            conditions.append("r.symbol = ?")
            params.append(symbol)
        if strategy:
            conditions.append("r.strategy = ?")
            params.append(strategy)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        with self._conn() as conn:
            cursor = conn.execute(
                f"""
                SELECT
                    r.symbol,
                    r.strategy,
                    COALESCE(ps.param_version, '') AS param_version,
                    COALESCE(mc.market_regime, ?)  AS actual_regime,
                    COUNT(*)                       AS sample_size,
                    AVG(p.total_return_pct)        AS avg_return,
                    AVG(p.sharpe_ratio)            AS avg_sharpe,
                    AVG(p.max_drawdown_pct)        AS avg_max_dd,
                    json_group_array(DISTINCT r.run_id) AS source_run_ids
                FROM performance_results p
                JOIN backtest_runs r          ON p.run_id = r.run_id
                LEFT JOIN params_snapshot ps  ON p.run_id = ps.run_id
                LEFT JOIN market_context mc   ON p.run_id = mc.run_id
                {where_clause}
                GROUP BY r.symbol, r.strategy, ps.param_version, mc.market_regime
                """,
                params,
            )

            rows = cursor.fetchall()
            if not rows:
                return 0

            updated = 0
            for row in rows:
                rd = dict(row)
                sample_sz = rd["sample_size"]
                avg_shp = rd["avg_sharpe"] or 0.0
                avg_dd = rd["avg_max_dd"] or 0.0

                # ── confidence 判定 ──
                if sample_sz >= 5 and avg_shp > 0.5 and avg_dd < 8:
                    confidence = "high"
                elif sample_sz >= 2:
                    confidence = "medium"
                else:
                    confidence = "low"

                conn.execute(
                    """
                    INSERT INTO knowledge_entries
                        (symbol, strategy, param_version, market_regime,
                         insight_category, confidence, sample_size,
                         avg_return_pct, avg_sharpe, avg_max_dd_pct,
                         source_run_ids, status, activated_at, last_updated_at)
                    VALUES (?, ?, ?, ?, 'aggregated', ?, ?, ?, ?, ?, ?,
                            'active', datetime('now','localtime'), datetime('now','localtime'))
                    ON CONFLICT(symbol, strategy, param_version, market_regime, insight_category)
                    DO UPDATE SET
                        confidence      = excluded.confidence,
                        sample_size     = excluded.sample_size,
                        avg_return_pct  = excluded.avg_return_pct,
                        avg_sharpe      = excluded.avg_sharpe,
                        avg_max_dd_pct  = excluded.avg_max_dd_pct,
                        source_run_ids  = excluded.source_run_ids,
                        status          = 'active',
                        last_updated_at = excluded.last_updated_at
                    """,
                    (
                        rd["symbol"],
                        rd["strategy"],
                        rd["param_version"],
                        rd["actual_regime"],
                        confidence,
                        sample_sz,
                        rd["avg_return"],
                        avg_shp,
                        avg_dd,
                        rd["source_run_ids"],
                    ),
                )

                # ── 同步 knowledge_run_links 关联表 ──
                # 使用 UNIQUE 复合约束字段查询刚 UPSERT 的知识条目 ID
                c2 = conn.execute(
                    "SELECT id FROM knowledge_entries "
                    "WHERE symbol=? AND strategy=? AND param_version=? "
                    "AND market_regime=? AND insight_category='aggregated'",
                    (rd["symbol"], rd["strategy"], rd["param_version"], rd["actual_regime"]),
                )
                r2 = c2.fetchone()
                if r2 is not None:
                    knowledge_id = r2["id"]
                    try:
                        run_ids = json.loads(rd["source_run_ids"])
                    except (json.JSONDecodeError, TypeError):
                        run_ids = []
                    # 在现有事务内直接操作 knowledge_run_links
                    conn.execute(
                        "DELETE FROM knowledge_run_links WHERE knowledge_id=?",
                        (knowledge_id,),
                    )
                    for rid in run_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO knowledge_run_links (knowledge_id, run_id) VALUES (?, ?)",
                            (knowledge_id, rid),
                        )

                updated += 1

            conn.commit()
            return updated

    # ── 关联表同步 ──────────────────────────────────────────

    def sync_run_links(self, knowledge_id: int, run_ids: List[str]) -> int:
        """
        同步知识条目与回测运行的关联关系。

        先删除该知识条目的所有旧关联，再批量插入新关联。
        整个操作在单事务内完成。

        参数
        ----------
        knowledge_id : int
            knowledge_entries 表的主键 ID
        run_ids : list[str]
            需关联的 run_id 列表

        返回
        -------
        int
            实际插入的关联数
        """
        with self._conn() as conn:
            with conn:
                conn.execute(
                    "DELETE FROM knowledge_run_links WHERE knowledge_id = ?",
                    (knowledge_id,),
                )
                conn.executemany(
                    "INSERT INTO knowledge_run_links (knowledge_id, run_id) VALUES (?, ?)",
                    [(knowledge_id, rid) for rid in run_ids],
                )
        return len(run_ids)

    # ── 衰减检查 ──────────────────────────────────────────

    def decay_check(self, max_age_days: int = 90) -> Dict[str, int]:
        """
        检查 knowledge_entries 中过期的知识条目并标记状态。

        标记规则：
        - 超过 max_age_days 但不超过 max_age_days*2 → status = 'degraded'
        - 超过 max_age_days*2 → status = 'deprecated'

        参数
        ----------
        max_age_days : int
            有效天数阈值，默认 90

        返回
        -------
        dict
            {"degraded": int, "deprecated": int}
        """
        with self._conn() as conn:
            # ── 标记 degraded：超出 max_age_days 但未达 2*max_age_days ──
            cursor = conn.execute(
                """
                UPDATE knowledge_entries
                SET status = 'degraded'
                WHERE last_updated_at < datetime('now', 'localtime', ? || ' days')
                  AND last_updated_at >= datetime('now', 'localtime', ? || ' days')
                  AND status NOT IN ('degraded', 'deprecated')
                """,
                (str(-max_age_days), str(-max_age_days * 2)),
            )
            degraded = cursor.rowcount

            # ── 标记 deprecated：超出 2*max_age_days ──
            cursor = conn.execute(
                """
                UPDATE knowledge_entries
                SET status = 'deprecated',
                    deprecated_at = datetime('now', 'localtime')
                WHERE last_updated_at < datetime('now', 'localtime', ? || ' days')
                  AND status != 'deprecated'
                """,
                (str(-max_age_days * 2),),
            )
            deprecated = cursor.rowcount

            conn.commit()
        return {"degraded": degraded, "deprecated": deprecated}

    # ── 查询已衰减条目 ──────────────────────────────────────

    def list_deprecated(
        self,
        status: str = "deprecated",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        查询已标记为衰减/废弃的知识条目。

        参数
        ----------
        status : str
            要查询的状态，'degraded' 或 'deprecated'，默认 'deprecated'
        limit : int
            最大返回条数，默认 50

        返回
        -------
        list[dict]
            knowledge_entries 表中匹配状态的行
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM knowledge_entries
                WHERE status = ?
                ORDER BY last_updated_at DESC
                LIMIT ?
                """,
                (status, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── 降级市场状态检测 ────────────────────────────────────

    @staticmethod
    def _estimate_market_regime(symbol: str, date: str, window_short=20, window_long=60) -> dict:
        """
        降级版市场状态判断：用均线+波动率粗分类。

        优先从本地 pickle 缓存读取日线数据（backtest_data_cache/），
        兜底尝试 akshare 在线数据。计算短期/长期均线交叉
        及波动率阈值来判断市场状态。无需 T6 模块。

        参数
        ----------
        symbol : str
            标的代码，如 '601857.SH' 或 '601857'
        date : str
            参考日期，格式 YYYYMMDD
        window_short : int
            短期均线窗口，默认 20
        window_long : int
            长期均线窗口，默认 60

        返回
        -------
        dict
            regime: 'bull' | 'bear' | 'sideways' | 'volatile'
            volatility: 'low' | 'medium' | 'high'
            short_ma: float, long_ma: float, price: float
            confidence: 'rough' — 标记为降级数据
        """
        import pandas as pd

        # ── 归一化 symbol 代码 ──
        code = symbol.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')

        # ── 尝试从本地 pickle 缓存加载 ──
        import glob as _glob
        import os as _os

        # 获取项目根目录
        try:
            root = _find_project_root()
        except Exception:
            root = _os.path.normpath(
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..")
            )

        cache_dir = _os.path.join(root, "backtest_data_cache")
        df = None

        if _os.path.isdir(cache_dir):
            # 查找该 code 的所有缓存分片，按文件名中的日期排序
            pattern = _os.path.join(cache_dir, f"{code}_*.parquet")
            cache_files = sorted(_glob.glob(pattern))

            if cache_files:
                try:
                    chunks = []
                    for f in cache_files:
                        try:
                            chunk = pd.read_pickle(f)
                            chunks.append(chunk)
                        except Exception:
                            continue
                    if chunks:
                        full = pd.concat(chunks, ignore_index=True)
                        full = full.drop_duplicates(subset=['date']).sort_values('date')
                        full['date'] = pd.to_datetime(full['date'])
                        target = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8])
                        # 取目标日期或之前的数据
                        hist = full[full['date'] <= target].tail(window_long + window_short)
                        if len(hist) >= window_long:
                            df = hist
                except Exception:
                    df = None

        # ── 兜底：尝试 akshare 在线获取 ──
        if df is None:
            try:
                import akshare as ak
                _df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date="", end_date=date,
                    adjust="qfq"
                )
                if not _df.empty and len(_df) >= window_long:
                    df = _df
                    df['close'] = df['收盘']
            except Exception:
                pass

        # ── 仍无数据则返回 unknown ──
        if df is None or len(df) < window_long:
            return {
                'regime': 'unknown',
                'volatility': 'medium',
                'short_ma': 0.0,
                'long_ma': 0.0,
                'price': 0.0,
                'confidence': 'rough'
            }

        # ── 计算均线 ──
        close = df['close']
        short_ma = float(close.rolling(window=window_short).mean().iloc[-1])
        long_ma = float(close.rolling(window=window_long).mean().iloc[-1])
        price = float(close.iloc[-1])

        # ── 计算波动率（60日滚动标准差） ──
        returns = close.pct_change()
        rolling_vol = returns.rolling(window=window_long).std().dropna()
        curr_vol = float(returns.std())

        # 90% 分位数作为高波动阈值
        high_threshold = float(rolling_vol.quantile(0.9)) if len(rolling_vol) > 10 else curr_vol * 1.5
        low_threshold = float(rolling_vol.quantile(0.3)) if len(rolling_vol) > 10 else curr_vol * 0.5

        # ── 波动率分级 ──
        if curr_vol > high_threshold:
            vol_level = 'high'
        elif curr_vol < low_threshold:
            vol_level = 'low'
        else:
            vol_level = 'medium'

        # ── 市场状态分类 ──
        ma_ratio = (short_ma - long_ma) / long_ma if long_ma != 0 else 0

        if vol_level == 'high':
            regime = 'volatile'
        elif ma_ratio > 0.02:
            regime = 'bull'
        elif ma_ratio < -0.02:
            regime = 'bear'
        else:
            regime = 'sideways'

        return {
            'regime': regime,
            'volatility': vol_level,
            'short_ma': round(short_ma, 2),
            'long_ma': round(long_ma, 2),
            'price': round(price, 2),
            'confidence': 'rough'
        }

    # ── 市场上下文存储 ──────────────────────────────────────

    def store_market_context(self, run_id: str, context: dict, date_key: str = "") -> bool:
        """
        将市场状态写入 market_context 表。

        幂等设计：先删除该 run_id 的已有记录，再插入新记录。

        参数
        ----------
        run_id : str
            回测运行 ID
        context : dict
            _estimate_market_regime() 返回的字典，包含 regime, volatility,
            short_ma, long_ma, price, confidence
        date_key : str, optional
            日期键（YYYYMMDD），未提供时从 backtest_runs 的 end_date 获取

        返回
        -------
        bool
            写入成功返回 True
        """
        with self._conn() as conn:
            with conn:
                # 幂等：删除该 run_id 的已有记录
                conn.execute("DELETE FROM market_context WHERE run_id = ?", (run_id,))

                # 获取 symbol 和 end_date
                cursor = conn.execute(
                    "SELECT symbol, end_date FROM backtest_runs WHERE run_id = ?",
                    (run_id,),
                )
                row = cursor.fetchone()
                symbol = row['symbol'] if row else ''
                run_end_date = row['end_date'] if row else ''

                # date_key 优先级：参数 > backtest_runs.end_date > 今日
                actual_date_key = (
                    date_key
                    or (run_end_date[:8] if run_end_date else '')
                    or datetime.now().strftime('%Y%m%d')
                )

                # 计算 trend_strength = (short_ma - long_ma) / long_ma
                short_ma = context.get('short_ma', 0.0)
                long_ma = context.get('long_ma', 0.0)
                divisor = max(abs(long_ma), 0.001)
                trend_strength = round((short_ma - long_ma) / divisor, 4)

                # 将降级数据的额外信息序列化到 notes 字段
                notes = json.dumps({
                    'short_ma': context.get('short_ma', 0),
                    'long_ma': context.get('long_ma', 0),
                    'price': context.get('price', 0),
                    'data_source': 'akshare',
                    'confidence': context.get('confidence', 'rough'),
                }, ensure_ascii=False)

                conn.execute(
                    '''
                    INSERT INTO market_context
                        (run_id, date_key, symbol, market_regime, volatility_level,
                         trend_strength, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        run_id,
                        actual_date_key,
                        symbol,
                        context['regime'],
                        context['volatility'],
                        trend_strength,
                        notes,
                    ),
                )

        return True

    # ── 市场上下文回填 ──────────────────────────────────────

    def backfill_market_context(self, run_ids: list = None) -> int:
        """
        对指定（或全部）回测运行回填市场上下文。

        遍历没有 market_context 记录的 run_id（或指定列表），
        调用 _estimate_market_regime() 判断市场状态并写入。

        参数
        ----------
        run_ids : list[str], optional
            指定回填的 run_id 列表。为 None 时自动查找所有缺失
            market_context 记录的 run_id。

        返回
        -------
        int
            成功回填的记录数
        """
        if run_ids is None:
            with self._conn() as conn:
                cursor = conn.execute(
                    '''
                    SELECT r.run_id, r.symbol, r.end_date
                    FROM backtest_runs r
                    LEFT JOIN market_context mc ON r.run_id = mc.run_id
                    WHERE mc.run_id IS NULL
                    ORDER BY r.created_at DESC
                    '''
                )
                rows = cursor.fetchall()
            run_ids = [(dict(r)['run_id'], dict(r)['symbol'], dict(r)['end_date']) for r in rows]
        else:
            # 从数据库获取 symbol 和 end_date
            enriched = []
            with self._conn() as conn:
                for rid in run_ids:
                    cursor = conn.execute(
                        "SELECT symbol, end_date FROM backtest_runs WHERE run_id = ?",
                        (rid,),
                    )
                    row = cursor.fetchone()
                    symbol = row['symbol'] if row else ''
                    end_date = row['end_date'] if row else ''
                    enriched.append((rid, symbol, end_date))
            run_ids = enriched

        filled = 0
        errors = []

        for run_id, symbol, end_date in run_ids:
            if not symbol:
                continue
            date_key = end_date[:8] if end_date else ''
            if not date_key:
                continue

            try:
                context = self._estimate_market_regime(symbol, date_key)

                if context['regime'] == 'unknown':
                    # 数据不可用，跳过
                    continue

                self.store_market_context(run_id, context, date_key=date_key)
                filled += 1

            except Exception as exc:
                errors.append(f"{run_id}: {exc}")

        if errors:
            import sys
            print(f"[backfill] {len(errors)} errors (first 5):", file=sys.stderr)
            for e in errors[:5]:
                print(f"  {e}", file=sys.stderr)

        return filled

    # ── 净值曲线持久化 ────────────────────────────────────

    def store_equity_series(
        self,
        run_id: str,
        equity_curve: List[Dict[str, Any]],
        initial_capital: Optional[float] = None,
    ) -> int:
        """
        存储净值曲线到 backtest_equity_series 表。

        幂等设计：先删除该 run_id 的已有记录，再批量插入新记录。

        参数
        ----------
        run_id : str
            回测运行 ID
        equity_curve : list[dict]
            净值曲线列表，每项须含 date 和 total_equity 字段。
            格式: [{"date": "20200102", "total_equity": 1000000.0}, ...]
        initial_capital : float, optional
            初始资金。若未提供，从 performance_results 关联查询。

        返回
        -------
        int
            写入的记录数
        """
        if not equity_curve:
            return 0

        # ── 确定初始资本（从第一条净值记录获取）──
        ic = initial_capital
        if ic is None:
            ic = float(equity_curve[0].get("total_equity", 1_000_000))
            if ic <= 0:
                ic = 1_000_000

        with self._conn() as conn:
            with conn:
                # 幂等：删除该 run_id 的已有净值记录
                conn.execute(
                    "DELETE FROM backtest_equity_series WHERE run_id = ?",
                    (run_id,),
                )

                records = []
                for idx, ec in enumerate(equity_curve):
                    equity = float(ec.get("total_equity", 0.0))
                    nav = equity / ic if ic > 0 else 1.0
                    drawdown = float(ec.get("drawdown", 0.0))
                    date_str = str(ec.get("date", ""))
                    records.append((run_id, idx, date_str, equity, nav, drawdown))

                conn.executemany(
                    """
                    INSERT INTO backtest_equity_series
                        (run_id, date_idx, date, equity, nav, drawdown)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    records,
                )

        return len(records)

    # ── 交易明细持久化 ────────────────────────────────────

    def store_trades(
        self,
        run_id: str,
        trades: List[Dict[str, Any]],
    ) -> int:
        """
        存储交易明细到 backtest_trades 表

        将原始订单（BUY/SELL）配对为完整交易记录：
        第 i 个 BUY 与第 i 个 SELL 配对为一条交易。
        幂等设计：先删除该 run_id 的所有记录再重新插入。

        参数
        ----------
        run_id : str
            回测运行 ID
        trades : list[dict]
            原始订单列表，含 side=buy/sell。
            格式: [{"date": "20200106", "side": "buy", "price": 4.6647,
                     "quantity": 32100, "fee": 44.92}, ...]

        返回
        -------
        int
            写入的记录数（配对后的完整交易数）
        """
        if not trades:
            return 0

        # 分离买入和卖出订单，按出现顺序保留
        buys = [t for t in trades if t.get("side", "").upper() == "BUY"]
        sells = [t for t in trades if t.get("side", "").upper() == "SELL"]

        # 配对：第 i 个 buy 与第 i 个 sell
        paired_count = min(len(buys), len(sells))

        with self._conn() as conn:
            with conn:
                # 幂等：删除该 run_id 的所有交易记录
                conn.execute(
                    "DELETE FROM backtest_trades WHERE run_id = ?",
                    (run_id,),
                )

                records = []
                for i in range(paired_count):
                    b = buys[i]
                    s = sells[i]
                    entry_date = str(b.get("date", ""))
                    exit_date = str(s.get("date", ""))
                    entry_price = float(b.get("price", 0.0))
                    exit_price = float(s.get("price", 0.0))
                    quantity = float(b.get("quantity", 0))

                    # 计算盈亏
                    fees = float(b.get("fee", 0)) + float(s.get("fee", 0))
                    pnl = (exit_price - entry_price) * quantity - fees
                    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0

                    records.append((
                        run_id, i, entry_date, exit_date, "long",
                        round(entry_price, 4), round(exit_price, 4), quantity,
                        round(pnl, 2), round(pnl_pct, 2),
                    ))

                # 未配对的订单也写入（作为单向交易）
                remaining = buys[paired_count:] + sells[paired_count:]
                for i, t in enumerate(remaining):
                    idx = paired_count + i
                    side = t.get("side", "").upper()
                    date_val = str(t.get("date", ""))
                    price = float(t.get("price", 0.0))
                    quantity = float(t.get("quantity", 0))

                    entry_date = date_val if side == "BUY" else ""
                    exit_date = date_val if side == "SELL" else ""
                    entry_price = price if side == "BUY" else 0.0
                    exit_price = price if side == "SELL" else 0.0
                    direction = "long" if side == "BUY" else "short"

                    records.append((
                        run_id, idx, entry_date, exit_date, direction,
                        entry_price, exit_price, quantity, 0.0, 0.0,
                    ))

                conn.executemany(
                    """
                    INSERT INTO backtest_trades
                        (run_id, trade_idx, entry_date, exit_date, direction,
                         entry_price, exit_price, quantity, pnl, pnl_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    records,
                )

        return len(records)

    # ========== 净值曲线查询 ==========
    def get_equity_series(self, run_id: str) -> List[Dict[str, Any]]:
        """
        按 run_id 查询净值曲线。

        参数
        ----------
        run_id : str
            回测运行 ID

        返回
        -------
        list[dict]
            按 date_idx 升序排列的净值曲线记录
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM backtest_equity_series
                WHERE run_id = ?
                ORDER BY date_idx ASC
                """,
                (run_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── 交易明细查询 ──────────────────────────────────────

    def get_trades(self, run_id: str) -> List[Dict[str, Any]]:
        """
        按 run_id 查询交易明细。

        参数
        ----------
        run_id : str
            回测运行 ID

        返回
        -------
        list[dict]
            按 trade_idx 升序排列的交易记录
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM backtest_trades
                WHERE run_id = ?
                ORDER BY trade_idx ASC
                """,
                (run_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── 最新 run_id 查询 ──────────────────────────────────

    def get_latest_run_id(
        self,
        strategy: str = "grid",
        symbol: str = "601857.SH",
        limit: int = 1,
    ) -> Optional[str]:
        """
        获取指定策略/标的最新回测运行 run_id。

        参数
        ----------
        strategy : str
            策略类型（默认 grid）
        symbol : str
            标的代码（默认 601857.SH）
        limit : int
            返回第几条（默认 1，即最新一条）

        返回
        -------
        str or None
            run_id，未找到时返回 None
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT run_id FROM backtest_runs
                WHERE strategy = ? AND symbol = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (strategy, symbol, limit, 0),
            )
            row = cursor.fetchone()
            return row[0] if row else None
