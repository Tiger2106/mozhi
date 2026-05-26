"""
墨枢 - BenchmarkProvider akshare 接入单元测试

覆盖 register_stock_from_akshare 和 register_index_from_akshare
两个桥接函数，全部 mock akshare 接口，不调真实网络。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtest.benchmark import BenchmarkProvider
from backtest.benchmark_data_source import (
    calc_buy_hold_return,
    register_index_from_akshare,
    register_stock_from_akshare,
)
from backtest.data_source import AkshareDataSource


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def provider() -> BenchmarkProvider:
    """干净的 BenchmarkProvider 实例。"""
    return BenchmarkProvider()


# ═══════════════════════════════════════════════════════════════
# test_register_stock_from_akshare
# ═══════════════════════════════════════════════════════════════


class TestRegisterStockFromAkshare:

    @patch("akshare.stock_zh_a_hist")
    def test_register_stock_from_akshare(
        self, mock_ak_hist: MagicMock, provider: BenchmarkProvider
    ):
        """mock akshare.stock_zh_a_hist，验证股票行情注册为基准成功。"""
        # 使用禁用了缓存的 DataSource 避免真实缓存干扰
        ds = AkshareDataSource(cache_ttl_hours=0)

        # ── 构造模拟数据 ──
        mock_df = pd.DataFrame({
            "日期": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "开盘": [8.50, 8.55, 8.60],
            "最高": [8.60, 8.65, 8.70],
            "最低": [8.45, 8.50, 8.55],
            "收盘": [8.55, 8.58, 8.62],
            "成交量": [100000, 120000, 110000],
            "成交额": [855000, 1029600, 948200],
        })
        mock_ak_hist.return_value = mock_df

        # ── 执行 ──
        index = register_stock_from_akshare(
            provider=provider,
            symbol="601857",
            name="中国石油",
            start_date="20250101",
            end_date="20250110",
            ds=ds,
        )

        # ── 断言 ──
        assert index is not None
        assert index.name == "中国石油"
        assert index.code == "601857"
        assert len(index.points) == 3

        # 验证第一条记录
        first = index.points[0]
        assert first.date == "2025-01-02"
        assert first.close == 8.55
        assert first.nav == pytest.approx(1.0)  # 基准日为 1.0

        # 验证最后一条记录
        last = index.points[-1]
        assert last.date == "2025-01-06"
        assert last.close == 8.62

        # 验证缓存
        cached = provider.get("中国石油")
        assert cached is not None

        # 验证 mock 被调用
        mock_ak_hist.assert_called_once()
        call_kwargs = mock_ak_hist.call_args.kwargs
        assert call_kwargs["symbol"] == "601857"

    @patch("akshare.stock_zh_a_hist")
    def test_register_stock_empty_data_raises(
        self, mock_ak_hist: MagicMock, provider: BenchmarkProvider
    ):
        """空数据时应抛出 ValueError。"""
        ds = AkshareDataSource(cache_ttl_hours=0)
        mock_ak_hist.return_value = pd.DataFrame()

        with pytest.raises(ValueError, match="无法从 akshare 获取"):
            register_stock_from_akshare(
                provider=provider,
                symbol="601857",
                name="中国石油",
                start_date="20250101",
                end_date="20250110",
                ds=ds,
            )


# ═══════════════════════════════════════════════════════════════
# test_register_index_csi300
# ═══════════════════════════════════════════════════════════════


class TestRegisterIndexCsi300:

    @patch("akshare.stock_zh_index_daily")
    def test_register_index_csi300(
        self, mock_index: MagicMock, provider: BenchmarkProvider
    ):
        """mock 指数接口，验证沪深300注册后数据正确。"""
        # ── 构造模拟数据（沪深300点位级别） ──
        mock_df = pd.DataFrame({
            "日期": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "开盘": [3930.0, 3940.0, 3920.0],
            "最高": [3950.0, 3960.0, 3940.0],
            "最低": [3920.0, 3930.0, 3910.0],
            "收盘": [3940.0, 3935.0, 3925.0],
            "成交量": [200000000, 210000000, 190000000],
            "成交额": [788000000000, 826350000000, 745750000000],
        })
        mock_index.return_value = mock_df

        # ── 执行 ──
        idx = register_index_from_akshare(
            provider=provider,
            index_name="csi300",
            start_date="20250101",
            end_date="20250131",
        )

        # ── 断言 ──
        assert idx is not None
        assert idx.name == "沪深300"
        assert idx.code == "000300.SH"
        assert len(idx.points) == 3

        # 第一条应为基准日
        first = idx.points[0]
        assert first.date == "2025-01-02"
        assert first.close == 3940.0
        assert first.nav == pytest.approx(1.0)

        # 净值计算: 第二日 3935 / 3940 ≈ 0.99873
        second = idx.points[1]
        assert second.date == "2025-01-03"
        assert second.nav == pytest.approx(3935.0 / 3940.0, rel=1e-4)

        # 验证缓存
        cached = provider.get("csi300")
        assert cached is idx

        # 验证 mock 调用
        mock_index.assert_called_once_with(symbol="sh000300")

    @patch("akshare.stock_zh_index_daily")
    def test_register_index_empty_data_raises(
        self, mock_index: MagicMock, provider: BenchmarkProvider
    ):
        """空数据时应抛出 ValueError。"""
        mock_index.return_value = pd.DataFrame()

        with pytest.raises(ValueError, match="无法获取指数行情"):
            register_index_from_akshare(
                provider=provider,
                index_name="csi300",
                start_date="20250101",
                end_date="20250131",
            )


# ═══════════════════════════════════════════════════════════════
# test_register_index_shanghai
# ═══════════════════════════════════════════════════════════════


class TestRegisterIndexShanghai:

    @patch("akshare.stock_zh_index_daily")
    def test_register_index_shanghai(
        self, mock_index: MagicMock, provider: BenchmarkProvider
    ):
        """mock 上证指数接口，验证注册成功且数据正确。"""
        # ── 构造模拟数据（上证指数点位级别） ──
        mock_df = pd.DataFrame({
            "日期": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "开盘": [3350.0, 3360.0, 3345.0],
            "最高": [3370.0, 3380.0, 3360.0],
            "最低": [3340.0, 3350.0, 3330.0],
            "收盘": [3360.0, 3355.0, 3348.0],
            "成交量": [500000000, 520000000, 480000000],
            "成交额": [1680000000000, 1744600000000, 1607040000000],
        })
        mock_index.return_value = mock_df

        # ── 执行 ──
        idx = register_index_from_akshare(
            provider=provider,
            index_name="shanghai",
            start_date="20250101",
            end_date="20250131",
        )

        # ── 断言 ──
        assert idx is not None
        assert idx.name == "上证指数"
        assert idx.code == "000001.SH"
        assert len(idx.points) == 3

        first = idx.points[0]
        assert first.date == "2025-01-02"
        assert first.close == 3360.0
        assert first.nav == pytest.approx(1.0)

        # 验证 total_return
        total_ret = idx.total_return_pct
        expected = (3348.0 - 3360.0) / 3360.0 * 100.0
        assert total_ret == pytest.approx(expected, rel=1e-4)

        mock_index.assert_called_once_with(symbol="sh000001")

    @patch("akshare.stock_zh_index_daily")
    def test_register_invalid_index_name(
        self, mock_index: MagicMock, provider: BenchmarkProvider
    ):
        """不支持的指数名称应抛出 ValueError。"""
        with pytest.raises(ValueError, match="不支持的指数名称"):
            register_index_from_akshare(
                provider=provider,
                index_name="shenzhen",
                start_date="20250101",
                end_date="20250131",
            )
        mock_index.assert_not_called()

    @patch("akshare.stock_zh_index_daily")
    def test_register_index_data_ordering(
        self, mock_index: MagicMock, provider: BenchmarkProvider
    ):
        """验证返回的数据按日期升序排列。"""
        # 故意乱序输入
        mock_df = pd.DataFrame({
            "日期": pd.to_datetime(["2025-01-06", "2025-01-02", "2025-01-03"]),
            "开盘": [3345.0, 3350.0, 3360.0],
            "最高": [3360.0, 3370.0, 3380.0],
            "最低": [3330.0, 3340.0, 3350.0],
            "收盘": [3348.0, 3360.0, 3355.0],
            "成交量": [480000000, 500000000, 520000000],
            "成交额": [1607040000000, 1680000000000, 1744600000000],
        })
        mock_index.return_value = mock_df

        idx = register_index_from_akshare(
            provider=provider,
            index_name="shanghai",
            start_date="20250101",
            end_date="20250131",
        )

        dates = [p.date for p in idx.points]
        assert dates == sorted(dates), "数据应按日期升序"
        assert dates[0] == "2025-01-02"
        assert dates[-1] == "2025-01-06"


# ═══════════════════════════════════════════════════════════════
# test_calc_buy_hold_return
# ═══════════════════════════════════════════════════════════════


class TestCalcBuyHoldReturn:
    """calc_buy_hold_return 单元测试（mock AkshareDataSource.fetch_daily）"""

    def _make_daily_df(self, start_dt: str, n_days: int, base_close: float = 10.0) -> pd.DataFrame:
        """生成模拟日线数据，收盘价在 base_close 附近小幅波动。"""
        dates = pd.date_range(start=start_dt, periods=n_days, freq="B")  # 仅工作日
        closes = [
            round(base_close + 0.1 * i + (0.05 if i % 2 == 0 else -0.05), 2)
            for i in range(n_days)
        ]
        return pd.DataFrame({
            "date": dates,
            "open": closes,
            "high": [c + 0.1 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": [100000] * n_days,
            "amount": [c * 100000 for c in closes],
        })

    # ── 基础 import ──

    def test_calc_buy_hold_return(self):
        """正常计算：60个交易日，验证收益率计算正确。"""
        mock_df = self._make_daily_df("2026-02-02", 60, base_close=18.0)
        start_close = mock_df.iloc[0]["close"]
        end_close = mock_df.iloc[-1]["close"]

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
                ds=ds,
            )

        expected_return = round((end_close - start_close) / start_close, 4)
        expected_pct = round(expected_return * 100, 2)

        assert result["symbol"] == "601857"
        assert result["name"] == "中国石油"
        assert result["start_close"] == float(start_close)
        assert result["end_close"] == float(end_close)
        assert result["total_return"] == expected_return
        assert result["total_return_pct"] == expected_pct

    # ── 日期对齐 ──

    def test_date_alignment(self):
        """起止日非交易日时，自动对齐到最近交易日。"""
        # 生成 2026-02-02（周一）开始的 60 个交易日
        mock_df = self._make_daily_df("2026-02-02", 60, base_close=18.0)
        actual_first_date = mock_df.iloc[0]["date"].strftime("%Y-%m-%d")
        actual_last_date = mock_df.iloc[-1]["date"].strftime("%Y-%m-%d")
        start_close = mock_df.iloc[0]["close"]
        end_close = mock_df.iloc[-1]["close"]

        # 用非交易日作为 start_date / end_date
        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",   # 周日
                end_date="20260517",     # 周日
                ds=ds,
            )

        assert result["start_date"] == actual_first_date
        assert result["end_date"] == actual_last_date
        assert result["start_close"] == float(start_close)
        assert result["end_close"] == float(end_close)

    # ── 数据不足 ──

    def test_insufficient_data_raises(self):
        """数据不足 30 个交易日应抛出 ValueError。"""
        mock_df = self._make_daily_df("2026-02-02", 15, base_close=18.0)

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            with pytest.raises(ValueError, match="不足 30 个"):
                calc_buy_hold_return(
                    symbol="601857",
                    name="中国石油",
                    start_date="20260201",
                    end_date="20260515",
                    ds=ds,
                )

    # ── 空数据 ──

    def test_empty_data_raises(self):
        """空 DataFrame 应抛出 ValueError。"""
        with patch.object(AkshareDataSource, "fetch_daily", return_value=pd.DataFrame()):
            ds = AkshareDataSource(cache_ttl_hours=0)
            with pytest.raises(ValueError, match="无法获取"):
                calc_buy_hold_return(
                    symbol="601857",
                    name="中国石油",
                    start_date="20260201",
                    end_date="20260515",
                    ds=ds,
                )

    # ── 正好 30 个交易日（边界） ──

    def test_exactly_30_days(self):
        """恰好 30 个交易日应正常通过。"""
        mock_df = self._make_daily_df("2026-02-02", 30, base_close=18.0)
        start_close = mock_df.iloc[0]["close"]
        end_close = mock_df.iloc[-1]["close"]

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
                ds=ds,
            )

        expected_return = round((end_close - start_close) / start_close, 4)
        assert result["total_return"] == expected_return

    # ── 负数收益率 ──

    def test_negative_return(self):
        """收盘价下跌时应返回负数收益率。"""
        dates = pd.date_range("2026-02-02", periods=30, freq="B")
        closes = [20.0 - 0.2 * i for i in range(30)]  # 持续下跌
        mock_df = pd.DataFrame({
            "date": dates, "open": closes, "high": closes,
            "low": closes, "close": closes,
            "volume": [100000] * 30, "amount": [c * 100000 for c in closes],
        })

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
                ds=ds,
            )

        assert result["total_return"] < 0
        assert result["total_return_pct"] < 0

    # ══════════════════════════════════════════════════════
    # KPI 计算
    # ══════════════════════════════════════════════════════

    def test_kpi_fields_present(self):
        """正常 KPI 计算：验证所有新增字段存在且类型正确。"""
        mock_df = self._make_daily_df("2026-02-02", 60, base_close=18.0)

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
                ds=ds,
            )

        # 验证所有新增字段存在
        expected_keys = {
            "annualized_return_pct", "max_drawdown_pct",
            "max_drawdown_duration", "win_rate", "calmar_ratio", "trading_days",
        }
        for key in expected_keys:
            assert key in result, f"缺少 KPI 字段: {key}"

        # 类型检查
        assert isinstance(result["annualized_return_pct"], float)
        assert isinstance(result["max_drawdown_pct"], float)
        assert isinstance(result["max_drawdown_duration"], int)
        assert isinstance(result["win_rate"], float)
        assert isinstance(result["calmar_ratio"], float)
        assert isinstance(result["trading_days"], int)
        assert result["trading_days"] == 60

    def test_kpi_annualized_return(self):
        """验证年化收益率公式：((1 + tr) ^ (365 / td) - 1) * 100。"""
        mock_df = self._make_daily_df("2026-02-02", 60, base_close=18.0)
        start_close = float(mock_df.iloc[0]["close"])
        end_close = float(mock_df.iloc[-1]["close"])
        total_return = round((end_close - start_close) / start_close, 4)
        trading_days = 60

        expected_annualized = round(
            ((1 + total_return) ** (365 / trading_days) - 1) * 100, 2
        )

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
                ds=ds,
            )

        assert result["annualized_return_pct"] == expected_annualized

    def test_kpi_max_drawdown_scenario(self):
        """最大回撤场景：系列先涨后跌，验证回撤值和持续天数。"""
        # 构造：前 20 天上涨，然后 10 天大幅下跌，然后 10 天略回升
        dates = pd.date_range("2026-02-02", periods=40, freq="B")
        closes = (
            [100.0 + i * 2.0 for i in range(20)]     # 前 20 天：100 → 138
            + [138.0 - (i + 1) * 6.0 for i in range(10)]  # 中 10 天：132 → 78
            + [78.0 + i * 1.5 for i in range(10)]    # 后 10 天：79.5 → 91.5
        )
        mock_df = pd.DataFrame({
            "date": dates,
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [100000] * 40,
            "amount": [c * 100000 for c in closes],
        })

        # 理论最大回撤: peak=138 (index 19), trough=78 (index 29)
        # drawdown = (78 - 138) / 138 = -0.43478... ⇒ -43.48%
        expected_max_dd = round((78 - 138) / 138 * 100, 2)
        # 回撤从索引 20 开始，到结束（索引 39）仍未恢复，持续 20 天
        expected_duration = 20

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
                ds=ds,
            )

        assert result["max_drawdown_pct"] == expected_max_dd, f"预期 {expected_max_dd}, 实际 {result['max_drawdown_pct']}"
        assert result["max_drawdown_duration"] == expected_duration, f"预期 {expected_duration}, 实际 {result['max_drawdown_duration']}"

    def test_kpi_zero_drawdown_uptrend(self):
        """单边上涨（回撤=0）：合并测试零回撤、Calmar=0、win_rate=1.0。"""
        # 严格单边上涨
        dates = pd.date_range("2026-02-02", periods=40, freq="B")
        closes = [100.0 + i * 0.5 for i in range(40)]
        mock_df = pd.DataFrame({
            "date": dates,
            "open": closes,
            "high": [c + 0.1 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": [100000] * 40,
            "amount": [c * 100000 for c in closes],
        })

        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            ds = AkshareDataSource(cache_ttl_hours=0)
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
                ds=ds,
            )

        assert result["max_drawdown_pct"] == 0.0, "单边上涨不应有回撤"
        assert result["max_drawdown_duration"] == 0, "单边上涨回撤持续天数应为 0"
        assert result["calmar_ratio"] == 0.0, "回撤为 0 时 Calmar 应为 0"
        assert result["win_rate"] == 1.0, "单边上涨日胜率应为 1.0"

    # ── ds 为 None（自动创建） ──

    def test_ds_is_none(self):
        """不传 ds 参数时应自动创建数据源。"""
        mock_df = self._make_daily_df("2026-02-02", 30, base_close=18.0)
        with patch.object(AkshareDataSource, "fetch_daily", return_value=mock_df):
            result = calc_buy_hold_return(
                symbol="601857",
                name="中国石油",
                start_date="20260201",
                end_date="20260515",
            )
        assert result["symbol"] == "601857"
        assert result["total_return"] is not None
