"""
DataLayer — 数据层 (BT-001/BT-004/GP-001)
=========================================
职责：
1. 一次性加载数据（GP-001），输出 BacktestData 合约
2. 字段校验 + 缺失值处理（BT-004）
3. 数据指纹计算 + 验证
4. 前视偏差运行时检测（BT-007 TimeAlignmentGuard）

约束：
- GP-001: 数据一次性加载，不重复读取
- GP-004: 确定性执行（不依赖随机数）
- BT-004: 输出必须符合 BacktestData 合约
- BT-006/BT-007: 时间对齐 + 前视偏差防护

作者: moheng
版本: v1.0
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path

from ..contracts.backtest_data_contract import (
    BacktestBar, BacktestData,
    MissingValuePolicy, TimeAlignmentGuard,
)

_TZ_CN = timezone(timedelta(hours=8))


class DataLayer:
    """数据层：加载、校验、指纹化

    使用方式:
        dl = DataLayer()
        data = dl.load("601857.SH", start_date="20200101", end_date="20260515")
        # data 是 BacktestData 合约对象
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(
            Path(__file__).resolve().parent.parent.parent.parent
            / "data" / "market" / "market_data.db"
        )
        self._loaded = False  # GP-001: 确保一次性加载

    # ── 核心加载接口 ──────────────────────────────────────

    def load(self, symbol: str,
             start_date: str = "",
             end_date: str = "",
             table: str = "stock_daily",
             code_col: str = "ts_code",
             date_col: str = "trade_date") -> BacktestData:
        """GP-001: 一次性加载数据并返回 BacktestData 合约

        Args:
            symbol: 股票代码（含后缀，如 "601857.SH"）
            start_date: 起始日期 YYYYMMDD，空=不限
            end_date: 结束日期 YYYYMMDD，空=不限
            table: 数据库表名
            code_col: 代码列名
            date_col: 日期列名

        Returns:
            BacktestData 合约对象

        Raises:
            RuntimeError: 重复加载（GP-001 违约）
            ValueError: 数据为空
        """
        # GP-001: 禁止重复加载
        if self._loaded:
            raise RuntimeError(
                "GP-001 violation: DataLayer.load() called twice. "
                "Data must be loaded exactly once."
            )
        self._loaded = True

        # 构造 SQL
        sql = f"""
            SELECT {date_col}, symbol, open, high, low, close,
                   volume, amount, adj_factor, data_source, version
            FROM {table}
            WHERE {code_col} = ?
        """
        params = [symbol]

        # 先获取 symbol 再拼接到 SQL（避免子查询参数问题）
        # 实际查询用 ts_code 列
        sql = f"""
            SELECT trade_date, ts_code, open, high, low, close,
                   volume, amount, adj_factor, data_source, version
            FROM stock_daily
            WHERE ts_code = ?
        """
        params = [symbol]

        if start_date:
            sql += f" AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += f" AND trade_date <= ?"
            params.append(end_date)

        sql += " ORDER BY trade_date ASC"

        # 执行查询
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            raise ValueError(
                f"No data found for symbol={symbol}, "
                f"start={start_date}, end={end_date}"
            )

        # 转换为 BacktestBar
        raw_bars = []
        for r in rows:
            raw = {
                "symbol": r["ts_code"] if "ts_code" in r.keys() else symbol,
                "date": r["trade_date"],
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"] or 0,
                "amount": r["amount"] or 0,
                "adj_factor": r["adj_factor"] or 1.0,
                "data_source": r["data_source"] if "data_source" in r.keys() else "unknown",
                "version": r["version"] if "version" in r.keys() else "v1.0",
            }
            raw_bars.append(raw)

        # 缺失值处理
        bars = MissingValuePolicy.validate_and_fill(raw_bars)

        # 字段级校验
        all_errors = []
        for b in bars:
            all_errors.extend(b.validate())

        if all_errors:
            # 前10条错误
            raise ValueError(
                f"Validation errors ({len(all_errors)} total): "
                f"{all_errors[:10]}"
            )

        # 日期升序检查
        date_errors = TimeAlignmentGuard.check_bars_ascending(bars)
        if date_errors:
            raise ValueError(f"Date ordering errors: {date_errors[:5]}")

        # 组装 BacktestData
        created_at = datetime.now(_TZ_CN).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        data = BacktestData(
            symbol=symbol,
            date_range=(bars[0].date, bars[-1].date),
            total_bars=len(bars),
            data_fingerprint="",  # 稍后计算
            contract_version="v1.0",
            created_at=created_at,
            bars=bars,
        )

        # 计算指纹
        data.data_fingerprint = data.compute_fingerprint()

        return data

    # ── 指纹验证（单独调用，不破坏 GP-001） ────────────

    @staticmethod
    def verify_data_fingerprint(data: BacktestData) -> bool:
        """验证数据指纹是否匹配"""
        return data.verify_fingerprint()

    # ── 重新加载（仅限测试/调试） ───────────────────────

    def reset(self):
        """重置加载状态（仅用于测试场景）"""
        self._loaded = False
