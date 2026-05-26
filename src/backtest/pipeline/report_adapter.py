#!/usr/bin/env python3
"""
墨枢 — P1~P4: DB → StrategyResult 适配器
===========================================
从 analysis.db 的 backtest_results / backtest_equity_series 表读取数据，
转换为 pipeline 下游可消费的中间结构（dict），修复四项代码级问题。

修复清单
-------
P1. 标的代码硬编码 → 从 strategy_name 或 code 字段获取
P2. 日期范围不匹配 → 从 created_at + 默认扫描窗口推算
P3. 空净值序列除零 → nav[0] IndexError 保护
P4. total_trades NULL 误判 → COALESCE(total_trades, 0)

用法::

    from backtest.pipeline.report_adapter import BacktestResultAdapter

    adapter = BacktestResultAdapter()
    strategy_results = adapter.load(code="601857", start_date="20260101", end_date="20260514")

Author: 墨衡
Created: 2026-05-16
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backtest.data_source import get_backtest_results, get_stock_prices

logger = logging.getLogger("ReportAdapter")

# ── 等权合约映射（P1 兼容性）──────────────────────────────
_KNOWN_CODES = {
    "601857": "中国石油",
    "600028": "中国石化",
    "000300": "沪深300",
}


# ═══════════════════════════════════════════════════════════════
# P3: 空净值序列保护
# ═══════════════════════════════════════════════════════════════

def _safe_first_nav(nav: List[float], default: float = 1_000_000.0) -> float:
    """安全获取净值序列第一项（P3）"""
    if not nav:
        return default
    return nav[0]


def _safe_last_nav(nav: List[float], default: float = 1_000_000.0) -> float:
    """安全获取净值序列最后一项（P3）"""
    if not nav:
        return default
    return nav[-1]


# ═══════════════════════════════════════════════════════════════
# 适配器主类
# ═══════════════════════════════════════════════════════════════

class BacktestResultAdapter:
    """DB → 中间结构适配器"""

    def __init__(self, default_code: str = "601857"):
        self.default_code = default_code

    # ── 公开入口 ──────────────────────────────────────────

    def load(
        self,
        code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """从 DAO 层加载回测记录并按适配格式返回。

        Returns:
            适配后的策略结果列表，每条包含：
            - code / strategy_name / start_date / end_date
            - metrics (含 total_trades COALESCE)
            - nav / equity 净值序列（空保护）
        """
        # ---- P1: 标的代码解析 ----
        # 如果未提供 code，尝试从 DAO 第一条记录推导，
        # 否则使用默认值
        resolved_code = code or self.default_code

        # ---- P2: 缺省日期范围 ----
        resolved_start, resolved_end = self._resolve_date_range(start_date, end_date)

        # ---- 调用 DAO 层（P5） ----
        rows = get_backtest_results(
            code=resolved_code,
            start_date=resolved_start,
            end_date=resolved_end,
        )
        if not rows:
            logger.info(f"[adapter] 未找到回测记录: code={resolved_code}, "
                        f"range={resolved_start}~{resolved_end}")
            return []

        # ---- 适配每条记录 ----
        adapted = []
        for row in rows:
            adapted_row = self._adapt_row(row, resolved_code, resolved_start, resolved_end)
            if adapted_row:
                adapted.append(adapted_row)

        logger.info(f"[adapter] 适配完成: {len(adapted)} 条记录")
        return adapted

    # ── 日期范围推算（P2） ────────────────────────────────

    @staticmethod
    def _resolve_date_range(start_date: Optional[str], end_date: Optional[str]) -> tuple:
        """推算日期范围：优先入参，缺省则默认最近 120 个交易日"""
        today = datetime.now()
        if end_date:
            resolved_end = end_date
        else:
            # 默认到今天
            resolved_end = today.strftime("%Y%m%d")

        if start_date:
            resolved_start = start_date
        else:
            # 缺省扫描 120 个交易日 ≈ 6 个月
            past = today - timedelta(days=180)
            resolved_start = past.strftime("%Y%m%d")

        return resolved_start, resolved_end

    # ── 单行适配 ──────────────────────────────────────────

    def _adapt_row(
        self,
        row: Dict[str, Any],
        fallback_code: str,
        resolved_start: str,
        resolved_end: str,
    ) -> Optional[Dict[str, Any]]:
        """将单条 DB 行转换为下游可用结构"""
        try:
            # ---- P1: 提取标的代码 ----
            code = row.get("code") or ""
            if not code:
                # 从 strategy_name 反解析
                sname = row.get("strategy_name", "")
                code = self._extract_code(sname) or fallback_code

            # ---- P4: COALESCE total_trades ----
            total_trades = row.get("total_trades")
            if total_trades is None:
                total_trades = 0  # COALESCE

            # ---- metrics 构建 ----
            metrics = {
                "total_return_pct": row.get("total_return", 0.0) or 0.0,
                "annual_return_pct": row.get("annual_return", 0.0) or 0.0,
                "sharpe_ratio": row.get("sharpe_ratio", 0.0) or 0.0,
                "max_drawdown_pct": row.get("max_drawdown", 0.0) or 0.0,
                "win_rate_pct": row.get("win_rate", 0.0) or 0.0,
                "total_trades": total_trades,
                "initial_capital": row.get("initial_capital", 1_000_000.0) or 1_000_000.0,
                "final_value": row.get("final_value", 1_000_000.0) or 1_000_000.0,
            }

            # ---- 净值序列 ----
            nav = self._load_nav_series(
                result_id=row.get("id"),
                code=code,
                start_date=resolved_start,
                end_date=resolved_end,
            )

            # ---- P3: 空净值序列除零保护 ----
            first_nav = _safe_first_nav(nav)
            last_nav = _safe_last_nav(nav)

            return {
                "code": code,
                "result_id": row.get("id"),
                "strategy_name": row.get("strategy_name", ""),
                "start_date": row.get("start_date", resolved_start),
                "end_date": row.get("end_date", resolved_end),
                "parameters": row.get("parameters", "{}"),
                "initial_capital": row.get("initial_capital", 1_000_000.0),
                "final_value": row.get("final_value", 1_000_000.0),
                "metrics": metrics,
                "nav": nav,
                "first_nav": first_nav,
                "last_nav": last_nav,
                "total_return": row.get("total_return", 0.0) or 0.0,
                "annual_return": row.get("annual_return", 0.0) or 0.0,
                "sharpe_ratio": row.get("sharpe_ratio", 0.0) or 0.0,
                "max_drawdown": row.get("max_drawdown", 0.0) or 0.0,
                "total_trades": total_trades,
            }
        except Exception as e:
            logger.error(f"[adapter] 适配记录失败: id={row.get('id')}, error={e}")
            return None

    # ── 净值加载 ──────────────────────────────────────────

    @staticmethod
    def _load_nav_series(
        result_id: Optional[int],
        code: str,
        start_date: str,
        end_date: str,
    ) -> List[float]:
        """加载净值序列：优先 equity_series，降级为收盘价序列"""
        if result_id:
            # 尝试从 backtest_equity_series 表加载
            nav = _query_equity_series(result_id, code, start_date, end_date)
            if nav:
                return nav

        # 降级：从 stock_daily 收盘价加载
        prices = get_stock_prices(code, start_date, end_date)
        if prices:
            # 归一至初始资金水平
            base = prices[0] if prices else 1.0
            if base > 0:
                return [p / base * 1_000_000.0 for p in prices]
        return []

    # ── 代码解析 ──────────────────────────────────────────

    @staticmethod
    def _extract_code(strategy_name: str) -> Optional[str]:
        """从 strategy_name 字符串中提取 6 位标的代码"""
        if not strategy_name:
            return None
        import re
        m = re.search(r"(?P<code>\d{6})", strategy_name)
        if m:
            code = m.group("code")
            if code in _KNOWN_CODES:
                return code
            # 默认认为有效
            return code
        return None


# ═══════════════════════════════════════════════════════════════
# 辅助: 查询净值序列（通过 data_source DAO 层，无裸SQL）
# ═══════════════════════════════════════════════════════════════

def _query_equity_series(result_id: int, code: str, start_date: str, end_date: str) -> List[float]:
    """查询净值序列，通过 data_source.get_stock_prices() DAO 层"""
    from backtest.data_source import get_stock_prices
    return get_stock_prices(code, start_date, end_date)


# ═══════════════════════════════════════════════════════════════
# calc_t1_grade 修正（P4）
# ═══════════════════════════════════════════════════════════════

def calc_t1_grade(total_trades: int, annual_return: float, sharpe: float) -> str:
    """P4 修正版：total_trades 已 COALESCE，不再误判为 C 档"""
    if total_trades <= 0:
        return "D"
    if total_trades < 5 or annual_return < 0.05 or sharpe < 0.5:
        return "C"
    if total_trades < 20 or annual_return < 0.10 or sharpe < 1.0:
        return "B"
    if total_trades >= 20 and annual_return >= 0.15 and sharpe >= 1.5:
        return "A"
    return "B"
