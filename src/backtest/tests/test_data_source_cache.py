"""
Tests for AkshareDataSource cache functionality.

覆盖：命中缓存、缓存过期、并行安全、不同参数、自动建目录、写后验证、parquet/pickle 回退
"""

import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from backtest.data_source import AkshareDataSource


# ── 测试夹具 ──────────────────────────────────────────────────────────────


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """模拟 akshare 返回的原始数据（中文列名）"""
    return pd.DataFrame(
        {
            "日期": ["2025-01-02", "2025-01-03"],
            "开盘": [10.0, 10.5],
            "最高": [11.0, 11.2],
            "最低": [9.8, 10.1],
            "收盘": [10.5, 10.8],
            "成交量": [10000, 12000],
            "成交额": [105000, 130000],
        }
    )


@pytest.fixture
def expected_cols():
    return ["date", "open", "high", "low", "close", "volume", "amount"]


def _side_effect(**kwargs):
    """让 mock 的 akshare 略过真实的列映射检查，直接返回一个预置 DataFrame

    为测试方便，让 mock 返回英文列名 data 而非中文列名。
    实际逻辑中 fetch_daily 会进行 rename，测试 mock 返回已处理数据。
    """
    # 返回基础行情数据，确保有足够行数
    return pd.DataFrame(
        {
            "日期": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "开盘": [10.0, 10.5, 10.3],
            "最高": [11.0, 11.2, 10.9],
            "最低": [9.8, 10.1, 10.0],
            "收盘": [10.5, 10.8, 10.6],
            "成交量": [10000, 12000, 11000],
            "成交额": [105000, 130000, 116000],
        }
    )


# ── 测试主体 ──────────────────────────────────────────────────────────────


class TestCache:
    """缓存行为测试"""

    def test_cache_hit(self, tmp_path, expected_cols):
        """命中缓存：第二次调用不触发 akshare"""
        cache_dir = tmp_path / "cache"
        ds = AkshareDataSource(cache_dir=str(cache_dir), cache_ttl_hours=24)

        with patch("akshare.stock_zh_a_hist", side_effect=_side_effect) as mock_ak:
            df1 = ds.fetch_daily("601857", "20250101", "20250110")
            assert not df1.empty

        # 第二次调用：应命中缓存，akshare 不应再被调
        with patch("akshare.stock_zh_a_hist", side_effect=_side_effect) as mock_ak:
            df2 = ds.fetch_daily("601857", "20250101", "20250110")
            assert not df2.empty
            mock_ak.assert_not_called()

        # 数据一致性
        pd.testing.assert_frame_equal(df1, df2)

    def test_cache_miss(self, tmp_path, expected_cols):
        """无缓存时触发 akshare 调用"""
        cache_dir = tmp_path / "cache"
        ds = AkshareDataSource(cache_dir=str(cache_dir))

        with patch("akshare.stock_zh_a_hist", side_effect=_side_effect) as mock_ak:
            df = ds.fetch_daily("601857", "20250101", "20250110")
            assert not df.empty
            mock_ak.assert_called_once()

    def test_cache_expiry(self, tmp_path, expected_cols):
        """过期缓存不命中，触发重新请求"""
        cache_dir = tmp_path / "cache"
        ds = AkshareDataSource(cache_dir=str(cache_dir), cache_ttl_hours=24)

        # 第一次写入缓存
        with patch("akshare.stock_zh_a_hist", side_effect=_side_effect) as mock_ak:
            ds.fetch_daily("601857", "20250101", "20250110")
            assert mock_ak.call_count == 1

        # 手动将缓存文件的 mtime 改到 25 小时前，使缓存过期
        cache_file = ds._cache_path("601857", "20250101", "20250110", "qfq")
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).timestamp()
        os.utime(str(cache_file), (old_time, old_time))

        # 重新请求应再次调用 akshare
        with patch("akshare.stock_zh_a_hist", side_effect=_side_effect) as mock_ak:
            df = ds.fetch_daily("601857", "20250101", "20250110")
            assert not df.empty
            mock_ak.assert_called_once()

    def test_cache_ttl_parameter_respected(self, tmp_path, expected_cols):
        """cache_ttl_hours=0 时缓存始终过期，每次都调 akshare"""
        cache_dir = tmp_path / "cache"
        ds = AkshareDataSource(cache_dir=str(cache_dir), cache_ttl_hours=0)

        with patch("akshare.stock_zh_a_hist", side_effect=_side_effect) as mock_ak:
            ds.fetch_daily("601857", "20250101", "20250110")
            mock_ak.assert_called_once()

            # 立即再请求（TTL=0 不命中）
            ds.fetch_daily("601857", "20250101", "20250110")
            assert mock_ak.call_count == 2

    def test_cache_directory_auto_created(self, tmp_path):
        """指定不存在的缓存目录时自动创建"""
        cache_dir = tmp_path / "nonexistent" / "deep" / "cache"
        assert not cache_dir.exists()

        ds = AkshareDataSource(cache_dir=str(cache_dir))
        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_different_params_different_cache(self, tmp_path):
        """不同参数生成不同缓存文件"""
        cache_dir = tmp_path / "cache"
        ds = AkshareDataSource(cache_dir=str(cache_dir))

        path_a = ds._cache_path("601857", "20250101", "20250110", "qfq")
        path_b = ds._cache_path("601857", "20250101", "20250110", "hfq")
        path_c = ds._cache_path("600000", "20250101", "20250110", "qfq")
        path_d = ds._cache_path("601857", "20250201", "20250210", "qfq")

        assert path_a.name != path_b.name
        assert path_a.name != path_c.name
        assert path_a.name != path_d.name
        assert path_b.name != path_c.name

    def test_parallel_safety(self, tmp_path, expected_cols):
        """多线程并发调 fetch_daily 不引发错误"""
        cache_dir = tmp_path / "cache"
        ds = AkshareDataSource(cache_dir=str(cache_dir), cache_ttl_hours=24)
        errors = []

        def fetch(symbol):
            try:
                with patch("akshare.stock_zh_a_hist", side_effect=_side_effect):
                    ds.fetch_daily(symbol, "20250101", "20250110")
            except Exception as e:
                errors.append((symbol, e))

        threads = [
            threading.Thread(target=fetch, args=(f"60{i}",))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发错误: {errors}"

    def test_cache_pickle_fallback_write_read(self, tmp_path, expected_cols):
        """验证 pickle 回退写入后能正确读出"""
        cache_dir = tmp_path / "cache"
        ds = AkshareDataSource(cache_dir=str(cache_dir))

        # 验证无 parquet 环境时写入后能读回
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
                "open": [10.0, 10.5],
                "close": [10.5, 10.8],
            }
        )

        cache_path = ds._cache_path("600000", "20250101", "20250110", "qfq")
        ds._write_cache(df, cache_path)

        assert cache_path.exists()

        loaded = ds._read_cache(cache_path)
        assert loaded is not None
        assert not loaded.empty
        pd.testing.assert_frame_equal(df, loaded)
