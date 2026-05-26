"""
test_data_source.py — AkshareDataSource 单元测试

覆盖场景：
1. 正常获取并验证列名统一
2. 空结果处理（无交易日期）
3. 参数校验异常
4. 网络重试行为（mock 模拟）
"""
import sys
import os

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from unittest.mock import patch
import pandas as pd
import pytest

from backtest.data_source import AkshareDataSource


class TestAkshareDataSource:
    """AkshareDataSource 测试"""

    @patch("akshare.stock_zh_a_hist")
    def test_fetch_daily_normal(self, mock_api):
        """正常获取：验证列名统一与日期转换"""
        mock_api.return_value = pd.DataFrame({
            "日期": ["2025-01-02", "2025-01-03"],
            "开盘": [10.0, 10.2],
            "最高": [10.5, 10.4],
            "最低": [9.8, 10.0],
            "收盘": [10.3, 10.1],
            "成交量": [1_000_000, 1_200_000],
            "成交额": [10_300_000, 12_120_000],
        })

        ds = AkshareDataSource(cache_ttl_hours=0)
        result = ds.fetch_daily("601857", "20250101", "20250110")

        # 验证列名
        expected_columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        assert list(result.columns) == expected_columns

        # 验证日期类型
        assert pd.api.types.is_datetime64_any_dtype(result["date"])

        # 验证数据行数
        assert len(result) == 2

        # 验证 akshare 调用参数
        mock_api.assert_called_once_with(
            symbol="601857",
            period="daily",
            start_date="20250101",
            end_date="20250110",
            adjust="qfq",
        )

    @patch("akshare.stock_zh_a_hist")
    def test_fetch_daily_empty_result(self, mock_api):
        """空结果处理：返回空 DataFrame 但列名正确"""
        mock_api.return_value = pd.DataFrame()

        ds = AkshareDataSource(cache_ttl_hours=0)
        result = ds.fetch_daily("601857", "20250101", "20250103")

        expected_columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        assert list(result.columns) == expected_columns
        assert len(result) == 0

    @patch("akshare.stock_zh_a_hist")
    def test_fetch_daily_none_result(self, mock_api):
        """None 结果处理"""
        mock_api.return_value = None

        ds = AkshareDataSource(cache_ttl_hours=0)
        result = ds.fetch_daily("601857", "20250101", "20250103")

        expected_columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        assert list(result.columns) == expected_columns
        assert len(result) == 0

    @patch("akshare.stock_zh_a_hist")
    def test_fetch_daily_retry_then_succeed(self, mock_api):
        """重试后成功"""
        mock_api.side_effect = [
            ConnectionError("第一次失败"),
            pd.DataFrame({
                "日期": ["2025-01-02"],
                "开盘": [10.0],
                "最高": [10.5],
                "最低": [9.8],
                "收盘": [10.3],
                "成交量": [1_000_000],
                "成交额": [10_300_000],
            }),
        ]

        ds = AkshareDataSource(max_retries=1, retry_delay=0.01, cache_ttl_hours=0)
        result = ds.fetch_daily("601857", "20250101", "20250110")

        assert len(result) == 1
        assert mock_api.call_count == 2

    @patch("akshare.stock_zh_a_hist")
    @patch("akshare.stock_zh_a_daily")
    def test_fetch_daily_retry_exhausted(self, mock_sina, mock_em):
        """东财重试 + 新浪 fallback 全部失败后抛出异常"""
        mock_em.side_effect = ConnectionError("网络异常")
        mock_sina.side_effect = ConnectionError("新浪也异常")

        ds = AkshareDataSource(max_retries=1, retry_delay=0.01, cache_ttl_hours=0)

        with pytest.raises(ConnectionError) as exc:
            ds.fetch_daily("601857", "20250101", "20250110")
        msg = str(exc.value)
        assert "东财" in msg and "新浪" in msg and "均失败" in msg

        assert mock_em.call_count == 2  # 初始 + 1次重试
        assert mock_sina.call_count == 1  # fallback 1 次

    def test_fetch_daily_empty_symbol(self):
        """空 symbol 参数校验"""
        ds = AkshareDataSource(cache_ttl_hours=0)
        with pytest.raises(ValueError, match="symbol 不能为空"):
            ds.fetch_daily("", "20250101", "20250110")

    def test_fetch_daily_bad_date(self):
        """异常日期格式校验"""
        ds = AkshareDataSource(cache_ttl_hours=0)
        with pytest.raises(ValueError, match="start_date 格式异常"):
            ds.fetch_daily("601857", "2025-01-01", "20250110")
