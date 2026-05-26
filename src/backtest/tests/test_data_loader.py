"""
test_data_loader.py — data_loader.populate_stock_daily 单元测试

覆盖场景：
1. 正常写入数据量验证
2. 重复写入去重验证
3. 空 DataFrame 处理
"""

import sqlite3
import tempfile
from unittest.mock import patch
import pandas as pd
import pytest

from backtest.data_loader import populate_stock_daily


class TestPopulateStockDaily:
    """populate_stock_daily 测试"""

    def _mock_df(self, n_days: int = 3, start_date: str = "20250101") -> pd.DataFrame:
        """生成模拟日线 DataFrame。"""
        from datetime import datetime, timedelta

        base = datetime.strptime(start_date, "%Y%m%d")
        rows = []
        for i in range(n_days):
            d = base + timedelta(days=i)
            rows.append({
                "date": d,
                "open": 10.0 + i * 0.1,
                "high": 10.5 + i * 0.1,
                "low": 9.8 + i * 0.1,
                "close": 10.3 + i * 0.1,
                "volume": 1_000_000 + i * 100_000,
                "amount": 10_300_000 + i * 1_030_000,
            })
        return pd.DataFrame(rows)

    def test_populate_normal(self):
        """正常写入：验证写入数据量"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            mock_df = self._mock_df(n_days=5)
            mock_ds = type("MockDS", (), {"fetch_daily": lambda self, s, sd, ed: mock_df})()

            written = populate_stock_daily(
                symbol="601857",
                start_date="20250101",
                end_date="20250110",
                db_path=db_path,
                ds=mock_ds,
            )

            # 验证写入条数
            assert written == 5, f"预期写入 5 条，实际写入 {written} 条"

            # 验证数据库内容
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM stock_daily WHERE code='601857'")
            count = cur.fetchone()[0]
            assert count == 5

            # 验证字段不为空
            cur.execute("SELECT code, date, open, close FROM stock_daily LIMIT 1")
            row = cur.fetchone()
            assert row[0] == "601857"
            assert row[1] == "20250101"
            assert row[2] == 10.0
            conn.close()
        finally:
            import os as _os
            _os.unlink(db_path)

    def test_populate_dedup(self):
        """重复写入去重：第二次写入不增加记录数"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            mock_df = self._mock_df(n_days=3)
            mock_ds = type("MockDS", (), {"fetch_daily": lambda self, s, sd, ed: mock_df})()

            # 第一次写入
            written1 = populate_stock_daily(
                symbol="601857",
                start_date="20250101",
                end_date="20250105",
                db_path=db_path,
                ds=mock_ds,
            )
            assert written1 == 3, f"首次写入预期 3 条，实际 {written1}"

            # 第二次写入（相同数据）
            written2 = populate_stock_daily(
                symbol="601857",
                start_date="20250101",
                end_date="20250105",
                db_path=db_path,
                ds=mock_ds,
            )
            assert written2 == 0, f"重复写入预期 0 条（全部去重），实际 {written2}"

            # 数据库记录数仍为 3
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM stock_daily WHERE code='601857'")
            count = cur.fetchone()[0]
            assert count == 3
            conn.close()
        finally:
            import os as _os
            _os.unlink(db_path)

    def test_populate_empty(self):
        """空 DataFrame 处理：写入 0 条"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            empty_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount"])
            mock_ds = type("MockDS", (), {"fetch_daily": lambda self, s, sd, ed: empty_df})()

            written = populate_stock_daily(
                symbol="601857",
                start_date="20250101",
                end_date="20250105",
                db_path=db_path,
                ds=mock_ds,
            )

            assert written == 0, f"空数据应写入 0 条，实际 {written}"
        finally:
            import os as _os
            _os.unlink(db_path)

    def test_populate_partial_dedup(self):
        """部分去重：新数据 + 已有数据混合"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            # 首次写入：3 天
            df1 = self._mock_df(n_days=3)
            mock_ds1 = type("MockDS", (), {"fetch_daily": lambda self, s, sd, ed: df1})()

            w1 = populate_stock_daily("601857", "20250101", "20250105", db_path=db_path, ds=mock_ds1)
            assert w1 == 3

            # 第二次写入：5 天（前 3 天重复 + 后 2 天新数据）
            df2 = self._mock_df(n_days=5)
            mock_ds2 = type("MockDS", (), {"fetch_daily": lambda self, s, sd, ed: df2})()

            w2 = populate_stock_daily("601857", "20250101", "20250110", db_path=db_path, ds=mock_ds2)
            assert w2 == 2, f"部分去重预期写入 2 条新数据，实际 {w2}"

            # 总记录数应为 5
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM stock_daily WHERE code='601857'")
            count = cur.fetchone()[0]
            assert count == 5
            conn.close()
        finally:
            import os as _os
            _os.unlink(db_path)
