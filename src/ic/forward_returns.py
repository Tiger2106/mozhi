"""
前向收益计算模块（§3.4.3）

为截面IC分析提供各周期前向收益（基于后复权 adj_close_b 价格）：
  - Forward_1D  : adj_close_b[t+1] / adj_close_b[t] - 1
  - Forward_5D  : adj_close_b[t+5] / adj_close_b[t] - 1
  - Forward_10D : adj_close_b[t+10] / adj_close_b[t] - 1
  - Forward_20D : adj_close_b[t+20] / adj_close_b[t] - 1

核心设计：
  - compute_forward_returns(trade_date, horizons=[1,5,10,20]) → list[dict]
  - 基于后复权 adj_close_b 价格计算（由 src.data.adjustment 模块生成）
  - 从 a50_daily_ohlcv 读取数据
  - 停牌/退市日至对应收益为 None
  - 含长假后首截面不足时排除逻辑（horizon 对应未来交易日不足时返回 None）

基类设计模式，DatabaseManager 参数注入。

验收标准：
  - compute_forward_returns('2026-05-26') 对 A50 50成分股返回合理收益
  - 提供数据不足时返回 None

用法:
    from src.db.connection import get_manager
    from src.ic.forward_returns import ForwardReturns

    mgr = get_manager()
    engine = ForwardReturns(db_manager=mgr)

    with mgr.get() as conn:
        results = engine.compute_forward_returns(conn, '2026-05-26')
        # [
        #   {"ts_code": "600000.SH", "forward_1d": 0.01, ...},
        #   ...
        # ]

Author: 墨衡
Created: 2026-05-30T12:07:00+08:00
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
import sqlite3

from src.db.connection import DatabaseManager

logger = logging.getLogger(__name__)

# ── 默认前向收益周期（交易日个数） ─────────────────────
DEFAULT_HORIZONS = [1, 5, 10, 20]


class ForwardReturns:
    """前向收益计算引擎。

    基于后复权价格 adj_close_b 计算各周期前向收益，
    供截面IC分析的 rank(factor[t]) vs return[t+1..t+N] 用途。

    Parameters
    ----------
    db_manager : DatabaseManager, optional
        数据库连接管理器，用于后续与管线集成
    horizons : list[int], optional
        前向收益周期列表（默认 [1, 5, 10, 20]）
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        horizons: Optional[List[int]] = None,
    ):
        self.db_manager = db_manager
        self.horizons = sorted(horizons or DEFAULT_HORIZONS)

    @property
    def horizon_field_map(self) -> Dict[int, str]:
        """周期 → 输出字段名 映射。"""
        return {h: f"forward_{h}d" for h in self.horizons}

    # ════════════════════════════════════════════════════════════
    # 公共接口
    # ════════════════════════════════════════════════════════════

    def compute_forward_returns(
        self,
        conn: sqlite3.Connection,
        trade_date: str,
        horizons: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """计算指定截面日 T 的各周期前向收益。

        前向收益 = adj_close_b[t+N] / adj_close_b[t] - 1
        其中 N 为严格 N 个交易日。

        Parameters
        ----------
        conn : sqlite3.Connection
            SQLite 连接（须已设置 PRAGMA foreign_keys=ON）
        trade_date : str
            截面日期（支持 YYYYMMDD 或 YYYY-MM-DD 格式）
        horizons : list[int], optional
            前向收益周期列表，默认使用 self.horizons

        Returns
        -------
        list[dict]
            [
                {
                    "ts_code": "600000.SH",
                    "forward_1d": 0.01,       # 1日前向收益
                    "forward_5d": 0.02,       # 5日前向收益
                    "forward_10d": 0.03,      # 10日前向收益
                    "forward_20d": 0.05,      # 20日前向收益
                },
                ...
            ]
            停牌/退市/数据不足时对应收益为 None
        """
        # ── 标准化日期格式（统一为 YYYYMMDD） ─────────
        trade_date_std = self._normalize_date(trade_date)
        horizons = sorted(horizons or self.horizons)
        field_map = {h: f"forward_{h}d" for h in horizons}

        logger.info(
            "compute_forward_returns | trade_date=%s horizons=%s",
            trade_date_std, horizons,
        )

        # ── 1. 获取截面日 T 所有成分股的后复权价格 ──
        date_prices = self._get_date_prices(conn, trade_date_std)
        if not date_prices:
            logger.warning(
                "No stocks found at trade_date=%s", trade_date_std
            )
            return []

        # ── 2. 获取 T 之后各 horizon 交易日价格 ─────
        max_horizon = max(horizons)
        future_prices = self._get_future_prices(
            conn, trade_date_std, max_horizon,
        )

        # ── 3. 逐股票计算前向收益 ────────────────────
        results = []
        for row in date_prices:
            ts_code = row["ts_code"]
            price_t = row["adj_close_b"]

            record: Dict[str, Any] = {"ts_code": ts_code}

            # 截面日价格缺失 → 所有前向收益为 None
            if price_t is None or not self._is_finite(price_t):
                for h in horizons:
                    record[field_map[h]] = None
                results.append(record)
                continue

            future_rows = future_prices.get(ts_code, [])

            for h in horizons:
                forward_val = self._compute_single_forward(
                    price_t, future_rows, h,
                )
                record[field_map[h]] = forward_val

            results.append(record)

        # ── 4. 统计并日志输出 ────────────────────────
        stock_count = len(results)
        valid_counts = {}
        for h in horizons:
            valid = sum(
                1 for r in results if r[field_map[h]] is not None
            )
            valid_counts[field_map[h]] = valid

        logger.info(
            "Forward returns | date=%s stocks=%d valid=%s",
            trade_date_std, stock_count, valid_counts,
        )

        return results

    # ════════════════════════════════════════════════════════════
    # 数据查询
    # ════════════════════════════════════════════════════════════

    def _get_date_prices(
        self,
        conn: sqlite3.Connection,
        trade_date: str,
    ) -> List[sqlite3.Row]:
        """获取截面日 T 所有成分股的后复权收盘价。"""
        rows = conn.execute(
            """
            SELECT ts_code, adj_close_b
            FROM a50_daily_ohlcv
            WHERE trade_date = ?
              AND adj_close_b IS NOT NULL
            ORDER BY ts_code
            """,
            (trade_date,),
        ).fetchall()
        return rows

    def _get_future_prices(
        self,
        conn: sqlite3.Connection,
        trade_date: str,
        max_horizon: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """获取截面日 T 之后 max_horizon 个交易日的后复权价格。

        对每个成分股，返回按 trade_date 升序排列的未来价格列表。

        Returns:
            {ts_code: [{trade_date: str, adj_close_b: float}, ...]}
        """
        rows = conn.execute(
            """
            SELECT ts_code, trade_date, adj_close_b
            FROM a50_daily_ohlcv
            WHERE trade_date > ?
            ORDER BY ts_code, trade_date
            """,
            (trade_date,),
        ).fetchall()

        # 按股票分组
        future_prices: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            code = row["ts_code"]
            if code not in future_prices:
                future_prices[code] = []
            future_prices[code].append({
                "trade_date": row["trade_date"],
                "adj_close_b": row["adj_close_b"],
            })

        return future_prices

    # ════════════════════════════════════════════════════════════
    # 核心计算
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_single_forward(
        price_t: float,
        future_rows: List[Dict[str, Any]],
        horizon: int,
    ) -> Optional[float]:
        """计算单个周期前向收益。

        Returns:
            forward_return or None（未来数据不足时）
        """
        # 需要 horizon 个交易日之后的对应行
        if len(future_rows) < horizon:
            return None

        target_row = future_rows[horizon - 1]  # 0-based
        price_t_plus_n = target_row["adj_close_b"]

        if price_t_plus_n is None or price_t == 0:
            return None

        if not ForwardReturns._is_finite(price_t_plus_n):
            return None

        return price_t_plus_n / price_t - 1.0

    # ════════════════════════════════════════════════════════════
    # 辅助方法
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """标准化日期格式为 YYYYMMDD。

        支持：
          - 2026-05-26  →  20260526
          - 20260526    →  20260526
        """
        cleaned = date_str.replace("-", "").strip()
        if len(cleaned) == 8 and cleaned.isdigit():
            return cleaned
        raise ValueError(f"无法解析日期: {date_str}")

    @staticmethod
    def _is_finite(val: Any) -> bool:
        """检查数值是否为有限的 float（非 NaN/Inf）。"""
        import math
        return not (val is None or math.isnan(float(val)) or math.isinf(float(val)))

    def __repr__(self) -> str:
        return (
            f"<ForwardReturns horizons={self.horizons}>"
        )
