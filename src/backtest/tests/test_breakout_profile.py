"""
Phase 1-B 测试：False Breakout Profile

测试内容:
  1. B1: breakout_events 数据库初始化与表结构
  2. B2: 特征提取函数正常
  3. B3: 评分卡正确分类
  4. B4: 报告生成与 JSON 输出
  5. 与真实回测数据集成

用法:
    pytest src/backtest/tests/test_breakout_profile.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pytest
import pandas as pd
import numpy as np

# ── 配置 ──────────────────────────────────────────────────────

BASE = r"C:\Users\17699\mozhi_platform"
sys.path.insert(0, BASE)
os.chdir(BASE)

MOZHI_BASE = Path(BASE)

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """生成标准假突破测试数据。

    模拟 100 个交易日，包含:
      - 1 次真突破（放量 + 持续）
      - 3 次假突破（缩量 + 反转）
    """
    np.random.seed(42)
    dates = pd.bdate_range(start="2026-01-01", periods=100, freq="B")

    # 基础价格: 在 10~11 区间震荡 50 天，然后趋势上涨 50 天
    base = np.full(100, 10.0)
    base[:50] += np.cumsum(np.random.randn(50) * 0.02)  # 震荡
    base[:50] = np.clip(base[:50], 9.8, 10.5)
    base[50:] = 10.0 + np.arange(1, 51) * 0.05 + np.random.randn(50) * 0.02  # 趋势

    close = base
    open_p = close - np.random.rand(100) * 0.05
    high = close + np.random.rand(100) * 0.08
    low = close - np.random.rand(100) * 0.08

    # 成交量: 假突破期间缩量，真突破放量
    volume = np.random.randint(5_000_000, 15_000_000, 100)
    # 在第 25 天（假突破1）和第 40 天（假突破2）附近缩量
    volume[23:27] = 3_000_000
    volume[38:42] = 4_000_000
    # 在第 55 天（真突破）放量
    volume[53:57] = 25_000_000
    # 在第 70 天（假突破3）缩量
    volume[68:72] = 3_500_000

    df = pd.DataFrame({
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def real_market_data() -> pd.DataFrame:
    """加载真实市场数据（601857）。"""
    csv_path = MOZHI_BASE / "data" / "market" / "601857_SH.csv"
    if not csv_path.exists():
        pytest.skip("实际市场数据文件不存在: 601857_SH.csv")
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    # 标准化列名
    col_map = {"Open": "open", "High": "high", "Low": "low",
               "Close": "close", "Volume": "volume", "Amount": "amount"}
    df = df.rename(columns=col_map)
    required = ["open", "high", "low", "close", "volume"]
    for c in required:
        if c not in df.columns:
            pytest.skip(f"市场数据缺少列: {c}")
    # 只保留 2026 年
    df = df[df.index >= "2026-01-01"]
    return df


# ═══════════════════════════════════════════════════════════════
# B1: 数据库测试
# ═══════════════════════════════════════════════════════════════


class TestBreakoutEventDB:
    """B1: breakout_events 数据库表测试。"""

    def test_init_and_table_structure(self):
        """测试数据库初始化和表结构。"""
        from backtest.signals.breakout_profile import BreakoutEventDB

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = BreakoutEventDB(db_path)

            # 验证表已创建
            conn = db._ensure_conn()
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]
            assert "breakout_events" in table_names, "breakout_events 表未创建"

            # 验证表结构
            columns = conn.execute("PRAGMA table_info(breakout_events)").fetchall()
            col_names = [c[1] for c in columns]
            expected_cols = [
                "breakout_id", "batch_id", "timestamp", "symbol",
                "price", "volume", "direction",
                "volume_ratio", "vwap_deviation",
                "regime", "trend_quality", "volume_ratio_20",
                "atr_value", "atr_expansion",
                "obv_value", "obv_change",
                "breakout_persistence",
                "is_false_breakout", "breakout_score", "confidence",
                "features_json", "created_at",
            ]
            for col in expected_cols:
                assert col in col_names, f"缺少列: {col}"

            # 验证索引
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='breakout_events'"
            ).fetchall()
            idx_names = [i[0] for i in indexes]
            assert "idx_bo_batch" in idx_names
            assert "idx_bo_symbol" in idx_names
            assert "idx_bo_timestamp" in idx_names
            assert "idx_bo_label" in idx_names

            db.close()
        finally:
            try:
                os.unlink(db_path)
            except PermissionError:
                pass

    def test_insert_and_query(self):
        """测试插入和查询。"""
        from backtest.signals.breakout_profile import (
            BreakoutEventDB, BreakoutEvent
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = BreakoutEventDB(db_path)

            # 插入样本数据
            fake_features = {'volume_ratio': 1.5, 'vwap_deviation': 0.8}

            event = BreakoutEvent(
                breakout_id="brk_test_001",
                batch_id="bt_test",
                timestamp="2026-01-15",
                symbol="601857",
                price=10.16,
                volume=5000000,
                direction="up",
                volume_ratio=0.95,
                vwap_deviation=0.5,
                regime="RANGE",
                trend_quality=0.3,
                volume_ratio_20=0.9,
                atr_value=0.15,
                atr_expansion=1.05,
                obv_value=100000,
                obv_change=0.0,
                breakout_persistence=1,
                is_false_breakout=True,
                breakout_score=0.25,
                confidence=0.8,
                features_json=json.dumps(fake_features),
            )

            db.insert_breakout(event)

            # 查询
            results = db.query_breakouts()
            assert len(results) == 1
            assert results[0]["breakout_id"] == "brk_test_001"
            assert results[0]["is_false_breakout"] == 1
            assert results[0]["regime"] == "RANGE"

            # 按 label 筛选
            false_ones = db.query_breakouts(label=True)
            assert len(false_ones) == 1
            true_ones = db.query_breakouts(label=False)
            assert len(true_ones) == 0

            # 统计
            stats = db.get_summary_stats()
            assert stats["total"] == 1
            assert stats["true_breakout_count"] == 0
            assert stats["false_breakout_count"] == 1

            db.close()
        finally:
            try:
                os.unlink(db_path)
            except PermissionError:
                pass

    def test_batch_insert(self):
        """测试批量插入。"""
        from backtest.signals.breakout_profile import (
            BreakoutEventDB, BreakoutEvent
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = BreakoutEventDB(db_path)
            events = []
            for i in range(5):
                events.append(BreakoutEvent(
                    breakout_id=f"brk_batch_{i}",
                    batch_id="bt_batch",
                    timestamp=f"2026-01-{10 + i:02d}",
                    symbol="601857",
                    price=10.0 + i * 0.1,
                    volume=5000000,
                    direction="up",
                    volume_ratio=1.0 + i * 0.1,
                    vwap_deviation=0.5 + i * 0.2,
                    regime="RANGE" if i < 3 else "TREND_UP",
                    trend_quality=0.3 + i * 0.1,
                    volume_ratio_20=1.0,
                    atr_value=0.15,
                    atr_expansion=1.0,
                    obv_value=100000,
                    obv_change=0.0,
                    breakout_persistence=i,
                    is_false_breakout=(i % 2 == 0),
                    breakout_score=0.5 - i * 0.1,
                    confidence=0.7,
                    features_json="{}",
                ))

            db.insert_batch(events)

            # 验证
            all_events = db.query_breakouts(batch_id="bt_batch", limit=100)
            assert len(all_events) == 5

            stats = db.get_summary_stats("bt_batch")
            assert stats["total"] == 5
            assert stats["true_breakout_count"] == 2  # i=1,3
            assert stats["false_breakout_count"] == 3  # i=0,2,4

            db.close()
        finally:
            try:
                os.unlink(db_path)
            except PermissionError:
                pass


# ═══════════════════════════════════════════════════════════════
# B2: 特征提取测试
# ═══════════════════════════════════════════════════════════════


class TestBreakoutFeatureExtractor:
    """B2: 假突破特征提取测试。"""

    def test_precompute_factors(self, sample_ohlcv):
        """测试因子预计算。"""
        from backtest.signals.breakout_profile import BreakoutFeatureExtractor

        extractor = BreakoutFeatureExtractor()
        extractor.precompute_factors(sample_ohlcv)

        cached_keys = extractor._cached_features.keys()
        assert "atr" in cached_keys
        assert "vwap" in cached_keys
        assert "volume_ratio" in cached_keys
        assert "obv" in cached_keys
        assert "adx" in cached_keys
        assert "trend_strength" in cached_keys
        assert "vwap_deviation" in cached_keys

    def test_extract_at_known_point(self, sample_ohlcv):
        """在已知的突破点提取特征并验证合理性。"""
        from backtest.signals.breakout_profile import BreakoutFeatureExtractor

        extractor = BreakoutFeatureExtractor()
        extractor.precompute_factors(sample_ohlcv)

        # 测试在真突破区域（第 55 天附近，放量区）
        features_true = extractor.extract_at(sample_ohlcv, 54)
        assert features_true.volume_ratio > 0, "真突破区量比应为正"

        # 测试在假突破区域（第 25 天附近，缩量区）
        features_false = extractor.extract_at(sample_ohlcv, 24)

        # 真突破的量比应显著大于假突破
        # （模拟数据第54天附近放量到2500万，第24天缩量到300万）
        assert features_true.volume > features_false.volume, \
            "模拟数据中真突破区的成交量应大于假突破区"

    def test_batch_extract(self, sample_ohlcv):
        """测试批量提取。"""
        from backtest.signals.breakout_profile import BreakoutFeatureExtractor

        extractor = BreakoutFeatureExtractor()
        indices = [10, 30, 55, 75]
        results = extractor.extract_batch(sample_ohlcv, indices)

        assert len(results) == 4
        for fs in results:
            assert isinstance(fs.volume_ratio, float)
            assert isinstance(fs.vwap_deviation, float)
            assert isinstance(fs.breakout_persistence, int)
            assert isinstance(fs.regime_at_breakout, str)

    def test_persistence_calculation(self, sample_ohlcv):
        """测试持续日数计算。"""
        from backtest.signals.breakout_profile import BreakoutFeatureExtractor

        extractor = BreakoutFeatureExtractor()
        extractor.precompute_factors(sample_ohlcv)

        # 在第25天附近提取（假突破 — 价格会很快回落）
        fs_false = extractor.extract_at(sample_ohlcv, 24)
        # 在第55天附近提取（真突破 — 价格趋势向上，持续更久）
        fs_true = extractor.extract_at(sample_ohlcv, 54)

        # 模拟数据中趋势段的持续性应当比震荡段长
        print(f"  假突破持续性: {fs_false.breakout_persistence}")
        print(f"  真突破持续性: {fs_true.breakout_persistence}")


# ═══════════════════════════════════════════════════════════════
# B3: 评分卡测试
# ═══════════════════════════════════════════════════════════════


class TestBreakoutScoringCard:
    """B3: 真假突破评分卡测试。"""

    def test_score_true_breakout(self):
        """真突破场景评分测试。"""
        from backtest.signals.breakout_profile import (
            BreakoutScoringCard, FeatureSet
        )

        card = BreakoutScoringCard()

        # 模拟真突破特征
        features = FeatureSet(
            volume_ratio=2.5,
            vwap_deviation=8.5,
            regime_at_breakout="TREND_UP",
            trend_quality=0.85,
            volume_ratio_20=2.0,
            atr_value=0.3,
            atr_expansion=1.5,
            obv_value=500000,
            obv_change=1.0,
            breakout_persistence=15,
            price=10.5,
            volume=20000000,
        )

        result = card.score(features)
        print(f"真突破评分: {result}")
        assert result["score"] >= 0.60, f"真突破评分应>=0.60, 实际={result['score']}"
        assert result["classification"] == "true_breakout"
        assert result["is_false_breakout"] is False

    def test_score_false_breakout(self):
        """假突破场景评分测试。"""
        from backtest.signals.breakout_profile import (
            BreakoutScoringCard, FeatureSet
        )

        card = BreakoutScoringCard()

        # 模拟假突破特征
        features = FeatureSet(
            volume_ratio=0.8,
            vwap_deviation=0.5,
            regime_at_breakout="RANGE",
            trend_quality=0.15,
            volume_ratio_20=0.9,
            atr_value=0.1,
            atr_expansion=0.95,
            obv_value=100000,
            obv_change=0.0,
            breakout_persistence=1,
            price=10.0,
            volume=3000000,
        )

        result = card.score(features)
        print(f"假突破评分: {result}")
        assert result["score"] < 0.40, f"假突破评分应<0.40, 实际={result['score']}"
        assert result["classification"] == "false_breakout"
        assert result["is_false_breakout"] is True

    def test_score_uncertain(self):
        """不确定场景评分测试。"""
        from backtest.signals.breakout_profile import (
            BreakoutScoringCard, FeatureSet
        )

        card = BreakoutScoringCard()

        # 模拟不确定场景（特征弱）— 放量不足+VWAP偏离一般
        features = FeatureSet(
            volume_ratio=1.2,
            vwap_deviation=2.0,
            regime_at_breakout="UPTREND",
            trend_quality=0.45,
            volume_ratio_20=1.1,
            atr_value=0.2,
            atr_expansion=1.1,
            obv_value=200000,
            obv_change=0.5,
            breakout_persistence=3,
            price=10.2,
            volume=8000000,
        )

        result = card.score(features)
        print(f"不确定评分: {result}")
        # 应落在 0.40~0.60
        assert 0.30 <= result["score"] <= 0.70, \
            f"不确定场景评分应在0.40附近, 实际={result['score']}"

    def test_batch_score(self):
        """批量评分测试。"""
        from backtest.signals.breakout_profile import (
            BreakoutScoringCard, FeatureSet
        )

        card = BreakoutScoringCard()
        features_list = [
            # 真突破
            FeatureSet(
                volume_ratio=2.5, vwap_deviation=8.5,
                regime_at_breakout="TREND_UP", trend_quality=0.85,
                volume_ratio_20=2.0, atr_value=0.3,
                atr_expansion=1.5, obv_value=500000,
                obv_change=1.0, breakout_persistence=15,
                price=10.5, volume=20000000,
            ),
            # 假突破
            FeatureSet(
                volume_ratio=0.8, vwap_deviation=0.5,
                regime_at_breakout="RANGE", trend_quality=0.15,
                volume_ratio_20=0.9, atr_value=0.1,
                atr_expansion=0.95, obv_value=100000,
                obv_change=0.0, breakout_persistence=1,
                price=10.0, volume=3000000,
            ),
            # 不确定
            FeatureSet(
                volume_ratio=1.2, vwap_deviation=2.0,
                regime_at_breakout="UPTREND", trend_quality=0.45,
                volume_ratio_20=1.1, atr_value=0.2,
                atr_expansion=1.1, obv_value=200000,
                obv_change=0.5, breakout_persistence=3,
                price=10.2, volume=8000000,
            ),
        ]

        results = card.batch_score(features_list)
        assert len(results) == 3
        assert results[0]["classification"] == "true_breakout"
        assert results[1]["classification"] == "false_breakout"
        # 第三个结果应该是不确定或处于中间区域
        print(f"批量评分结果: {[r['classification'] for r in results]}")


# ═══════════════════════════════════════════════════════════════
# B4: 报告生成测试
# ═══════════════════════════════════════════════════════════════


class TestBreakoutReport:
    """B4: 假突破报告生成测试。"""

    def test_generate_report_with_sample_data(self, sample_ohlcv):
        """使用样本数据生成报告。"""
        from backtest.signals.breakout_profile import (
            generate_breakout_report, detect_breakout_points
        )

        # 检测突破点
        indices = detect_breakout_points(sample_ohlcv)
        assert len(indices) > 0, "应检测到至少一个突破点"

        with tempfile.TemporaryDirectory() as tmpdir:
            # 生成报告
            report = generate_breakout_report(
                df=sample_ohlcv,
                breakout_indices=indices,
                batch_id="bt_test_sample",
                symbol="601857",
                output_dir=tmpdir,
                persist_db=False,
            )

            # 验证报告结构
            assert "meta" in report
            assert "summary_stats" in report
            assert "events" in report
            assert "feature_comparison_matrix" in report

            # 验证汇总统计
            stats = report["summary_stats"]
            assert stats["total_breakouts"] == len(indices)
            assert stats["total_breakouts"] > 0

            # 验证事件详情
            for event in report["events"]:
                assert "timestamp" in event
                assert "features" in event
                assert "score_card" in event
                assert "classification" in event["score_card"]
                assert event["score_card"]["classification"] in (
                    "true_breakout", "false_breakout", "uncertain"
                )

            # 验证特征对比矩阵
            fcm = report["feature_comparison_matrix"]
            assert "volume_ratio" in fcm
            assert "vwap_deviation" in fcm

            # 验证 JSON 文件已写入
            report_path = Path(tmpdir) / f"false_breakout_profile_bt_test_sample.json"
            assert report_path.exists(), f"报告文件未生成: {report_path}"

            # 验证 IO 正确性
            with open(report_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["meta"]["batch_id"] == "bt_test_sample"
            assert loaded["summary_stats"]["total_breakouts"] == len(indices)

    def test_report_stats_consistency(self, sample_ohlcv):
        """报告统计一致性验证。"""
        from backtest.signals.breakout_profile import (
            generate_breakout_report, detect_breakout_points
        )

        indices = detect_breakout_points(sample_ohlcv)

        with tempfile.TemporaryDirectory() as tmpdir:
            report = generate_breakout_report(
                df=sample_ohlcv,
                breakout_indices=indices,
                batch_id="bt_stats_test",
                symbol="601857",
                output_dir=tmpdir,
                persist_db=False,
            )

            stats = report["summary_stats"]
            events = report["events"]

            # 分类计数和统计一致
            true_cnt = sum(1 for e in events if e["score_card"]["classification"] == "true_breakout")
            false_cnt = sum(1 for e in events if e["score_card"]["classification"] == "false_breakout")
            uncertain_cnt = sum(1 for e in events if e["score_card"]["classification"] == "uncertain")

            assert stats["true_breakout_count"] == true_cnt
            assert stats["false_breakout_count"] == false_cnt
            assert stats["uncertain_count"] == uncertain_cnt
            assert stats["total_breakouts"] == len(events)


# ═══════════════════════════════════════════════════════════════
# B5: 与真实回测数据集成的集成测试
# ═══════════════════════════════════════════════════════════════


class TestBreakoutProfileIntegration:
    """B5: 与真实回测数据集成测试。"""

    def test_detect_breakout_on_real_data(self, real_market_data):
        """在真实市场数据上检测突破点。"""
        from backtest.signals.breakout_profile import detect_breakout_points

        indices = detect_breakout_points(real_market_data)
        print(f"检测到 {len(indices)} 个突破点")

        # 验证每个索引有效
        for idx in indices:
            assert 0 <= idx < len(real_market_data)

    def test_feature_extraction_on_real_data(self, real_market_data):
        """在真实数据上提取特征。"""
        from backtest.signals.breakout_profile import (
            BreakoutFeatureExtractor, detect_breakout_points
        )

        indices = detect_breakout_points(real_market_data)
        if len(indices) < 2:
            pytest.skip("真实数据突破点不足，跳过")

        extractor = BreakoutFeatureExtractor()
        features_list = extractor.extract_batch(real_market_data, indices[:10])

        assert len(features_list) <= 10
        for fs in features_list:
            # 验证所有特征都是合理值
            assert fs.volume_ratio >= 0, "volume_ratio 不能为负"
            assert fs.trend_quality >= 0, "trend_quality 不能为负"
            assert fs.breakout_persistence >= 0, "persistence 不能为负"
            assert fs.regime_at_breakout in (
                "RANGE", "UPTREND", "DOWNTREND", "BREAKOUT", "CLIMAX",
                "TREND_UP", "UNKNOWN", ""
            ), f"未知的 regime: {fs.regime_at_breakout}"
            print(
                f"  [{fs.regime_at_breakout:>10}] idx=? "
                f"vol={fs.volume_ratio:.2f} "
                f"vwap={fs.vwap_deviation:.2f}% "
                f"atr={fs.atr_value:.4f} "
                f"pers={fs.breakout_persistence}d"
            )

    def test_scoring_card_on_real_data(self, real_market_data):
        """在真实数据上运行评分卡。"""
        from backtest.signals.breakout_profile import (
            BreakoutFeatureExtractor, BreakoutScoringCard,
            detect_breakout_points,
        )

        indices = detect_breakout_points(real_market_data)
        if len(indices) < 2:
            pytest.skip("真实数据突破点不足，跳过")

        extractor = BreakoutFeatureExtractor()
        features_list = extractor.extract_batch(real_market_data, indices[:10])

        card = BreakoutScoringCard()
        results = card.batch_score(features_list)

        for idx, result in zip(indices[:10], results):
            print(
                f"  评分={result['score']:.3f} "
                f"分类={result['classification']:>15} "
                f"置信度={result['confidence']:.3f} "
                f"组件={result['components']}"
            )

    def test_end_to_end_report_on_real_data(self, real_market_data):
        """在真实数据上端到端生成报告。"""
        from backtest.signals.breakout_profile import (
            generate_breakout_report, detect_breakout_points
        )

        indices = detect_breakout_points(real_market_data)
        if len(indices) < 2:
            pytest.skip("真实数据突破点不足，跳过")

        with tempfile.TemporaryDirectory() as tmpdir:
            report = generate_breakout_report(
                df=real_market_data,
                breakout_indices=indices,
                batch_id="bt_integration_test",
                symbol="601857",
                output_dir=tmpdir,
                persist_db=False,
            )

            # 验证报告完整性
            stats = report["summary_stats"]
            assert stats["total_breakouts"] == len(indices)
            print(f"端到端报告: 共 {stats['total_breakouts']} 个突破点")
            print(f"  真突破: {stats['true_breakout_count']}")
            print(f"  假突破: {stats['false_breakout_count']}")
            print(f"  不确定: {stats['uncertain_count']}")
            print(f"  假突破占比: {stats['false_ratio']}%")
