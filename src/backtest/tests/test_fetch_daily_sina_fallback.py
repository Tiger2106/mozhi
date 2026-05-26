"""
test_fetch_daily_sina_fallback.py — 新浪日线 fallback 单元测试

覆盖场景：
1. test_sina_fallback_success — mock 东财失败，验证新浪被调用
2. test_sina_symbol_mapping — 601857→sh601857, 000001→sz000001, 300750→sz300750
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

from backtest.data_source import AkshareDataSource, _to_sina_symbol


class TestSinaSymbolMapping:
    """新浪 symbol 前缀映射测试"""

    def test_sh_main_board(self):
        """601857 沪市主板 → sh601857"""
        assert _to_sina_symbol("601857") == "sh601857"
        assert _to_sina_symbol("601857.SH") == "sh601857"

    def test_sz_main_board(self):
        """000001 深市主板 → sz000001"""
        assert _to_sina_symbol("000001") == "sz000001"
        assert _to_sina_symbol("000001.SZ") == "sz000001"

    def test_sz_gem(self):
        """300750 创业板 → sz300750"""
        assert _to_sina_symbol("300750") == "sz300750"
        assert _to_sina_symbol("300750.SZ") == "sz300750"

    def test_bj_board(self):
        """4/8 开头北交所 → bj"""
        assert _to_sina_symbol("430017") == "bj430017"
        assert _to_sina_symbol("830849") == "bj830849"


class TestSinaFallback:
    """新浪 fallback 降级测试"""

    @patch("akshare.stock_zh_a_hist")
    @patch("akshare.stock_zh_a_daily")
    def test_sina_fallback_success(self, mock_sina, mock_em):
        """东财失败 → 新浪 fallback，返回正确英文列名"""
        # 东财抛出异常
        mock_em.side_effect = ConnectionError("Eastern Broker shielded")

        # 新浪返回数据（英文列名）
        mock_sina.return_value = pd.DataFrame({
            "date": ["2025-01-02", "2025-01-03"],
            "open": [10.0, 10.2],
            "high": [10.5, 10.4],
            "low": [9.8, 10.0],
            "close": [10.3, 10.1],
            "volume": [1_000_000, 1_200_000],
            "amount": [10_300_000, 12_120_000],
            "outstanding_share": [18_300_000_000, 18_300_000_000],
            "turnover": [0.0055, 0.0066],
        })

        ds = AkshareDataSource(max_retries=0, cache_ttl_hours=0)
        result = ds.fetch_daily("601857", "20250101", "20250110")

        # 验证东财被调用但失败
        mock_em.assert_called_once()
        # 验证新浪被调用
        mock_sina.assert_called_once()
        call_kwargs = mock_sina.call_args.kwargs
        assert call_kwargs["symbol"] == "sh601857"

        # 验证列名统一（纯英文，无中文）
        expected_columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        assert list(result.columns) == expected_columns

        # 验证数据行数
        assert len(result) == 2

        # 验证日期类型
        assert pd.api.types.is_datetime64_any_dtype(result["date"])

    @patch("akshare.stock_zh_a_hist")
    @patch("akshare.stock_zh_a_daily")
    def test_sina_fallback_also_fails(self, mock_sina, mock_em):
        """东财失败 → 新浪也失败 → 抛出 ConnectionError"""
        mock_em.side_effect = ConnectionError("Eastern Broker shielded")
        mock_sina.side_effect = ConnectionError("Sina also shielded")

        ds = AkshareDataSource(max_retries=0, cache_ttl_hours=0)

        with pytest.raises(ConnectionError) as exc:
            ds.fetch_daily("601857", "20250101", "20250110")
        # 中文断言 + 是字面值，不是正则
        msg = str(exc.value)
        assert "东财" in msg and "新浪" in msg and "均失败" in msg, (
            f"Expected '东财+新浪均失败' in error, got: {msg}"
        )

        assert mock_em.call_count == 1
        assert mock_sina.call_count == 1

    @patch("akshare.stock_zh_a_hist")
    @patch("akshare.stock_zh_a_daily")
    def test_sina_fallback_empty_result(self, mock_sina, mock_em):
        """东财失败 → 新浪返回空 → 返回空 DataFrame 但列名正确"""
        mock_em.side_effect = ConnectionError("Eastern Broker shielded")
        mock_sina.return_value = pd.DataFrame()

        ds = AkshareDataSource(max_retries=0, cache_ttl_hours=0)
        result = ds.fetch_daily("601857", "20250101", "20250103")

        expected_columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        assert list(result.columns) == expected_columns
        assert len(result) == 0
