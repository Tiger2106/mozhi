"""
集成测试：RiskPipeline 与 PortfolioIntegration 的三模块流水线。

测试场景：
1. enable_all=True — 全流水线跑通（MarketStateFilter + VolatilityRiskManager + DrawdownGuard）
2. enable_all=False — 向后兼容，原有回测不受影响
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.risk.risk_pipeline import RiskPipeline, RiskPipelineConfig
from backtest.risk.drawdown_guard import DrawdownGuardConfig
from backtest.risk.volatility_risk_manager import VolatilityRiskConfig
from backtest.risk.market_state_filter import MarketStateFilterConfig
from backtest.engine.portfolio_integration import PortfolioIntegration
from backtest.regime.regime_analyzer import RegimeAnalyzer


def _make_test_data(n_bars: int = 100) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成模拟 OHLCV 和信号数据。"""
    dates = pd.date_range("2025-01-01", periods=n_bars, freq="D")

    # OHLCV — 简单的正弦波 + 趋势 + 噪声
    np.random.seed(42)
    t = np.linspace(0, 4 * np.pi, n_bars)
    base = 100 + 0.5 * np.arange(n_bars)  # 轻微上升趋势
    noise = np.random.normal(0, 0.5, size=n_bars)
    close_prices = base + 5 * np.sin(t) + noise
    close_prices = np.maximum(close_prices, 50)  # 防止负价格

    ohlcv = pd.DataFrame(
        {
            "open": close_prices * 0.99,
            "high": close_prices * 1.02,
            "low": close_prices * 0.98,
            "close": close_prices,
            "volume": np.random.randint(1_000_000, 10_000_000, size=n_bars),
        },
        index=dates,
    )

    # 信号 — 包含买入和卖出
    signals = pd.DataFrame(
        {"signal": np.zeros(n_bars, dtype=int)},
        index=dates,
    )
    # 第 20 天买入（确保 ATR period=14 计算完成），第 40 天卖出
    signals.iloc[20, 0] = 1   # buy
    signals.iloc[40, 0] = -1  # sell

    return ohlcv, signals


def test_pipeline_enabled() -> None:
    """Test 1: 全流水线启用 — 验证模块编排正常。

    预期：
    - run() 正常返回四个元素的 tuple
    - summary_metrics 包含 risk_events
    - equity_curve 有数据
    """
    print("=" * 60)
    print("Test 1: RiskPipeline 全流水线（enable_all=True）")
    print("=" * 60)

    ohlcv, signals = _make_test_data(100)

    # 配置各子模块
    mf_cfg = MarketStateFilterConfig(enabled=True)
    vr_cfg = VolatilityRiskConfig(enabled=True)
    dd_cfg = DrawdownGuardConfig(enabled=True)

    pipeline_cfg = RiskPipelineConfig(
        market_state_filter=mf_cfg,
        volatility_risk=vr_cfg,
        drawdown_guard=dd_cfg,
        enable_market_state_filter=True,
        enable_volatility_risk=True,
        enable_drawdown_guard=True,
    )

    regime_analyzer = RegimeAnalyzer()
    pipeline = RiskPipeline(regime_analyzer=regime_analyzer, config=pipeline_cfg)

    pi = PortfolioIntegration(
        initial_cash=1_000_000.0,
        risk_pipeline=pipeline,
    )

    equity_curve, trades, daily_metrics, summary_metrics = pi.run(signals, ohlcv)

    assert not equity_curve.empty, "权益曲线不应为空"
    assert len(trades) > 0, "应有成交记录"
    assert "risk_events" in summary_metrics, "summary 应包含 risk_events"

    print(f"  ✅ equity_curve 长度: {len(equity_curve)}")
    print(f"  ✅ trades 数量: {len(trades)}")
    print(f"  ✅ risk_events 数量: {len(summary_metrics['risk_events'])}")
    print(f"  ✅ total_return: {summary_metrics.get('total_return', 'N/A')}")
    print(f"  ✅ max_drawdown: {summary_metrics.get('max_drawdown', 'N/A')}")
    print("  ✅ Test 1 PASS\n")


def test_pipeline_disabled() -> None:
    """Test 2: 全流水线关闭 — 验证向后兼容性。

    预期：
    - run() 正常返回
    - risk_events 不存在或为空
    - 与不传 risk_pipeline 的行为一致
    """
    print("=" * 60)
    print("Test 2: 全流水线关闭（enable_all=False）— 向后兼容")
    print("=" * 60)

    ohlcv, signals = _make_test_data(100)

    pipeline_cfg = RiskPipelineConfig(
        enable_market_state_filter=False,
        enable_volatility_risk=False,
        enable_drawdown_guard=False,
    )

    pipeline = RiskPipeline(config=pipeline_cfg)

    pi = PortfolioIntegration(
        initial_cash=1_000_000.0,
        risk_pipeline=pipeline,
    )

    equity_curve, trades, daily_metrics, summary_metrics = pi.run(signals, ohlcv)

    assert not equity_curve.empty, "权益曲线不应为空"
    assert len(trades) > 0, "应有成交记录"

    # risk_events 应为空或不出现
    risk_events = summary_metrics.get("risk_events", [])
    assert len(risk_events) == 0, f"关闭流水线后不应有风控事件，得到 {len(risk_events)}"

    print(f"  ✅ equity_curve 长度: {len(equity_curve)}")
    print(f"  ✅ trades 数量: {len(trades)}")
    print(f"  ✅ risk_events 数量: {len(risk_events)}（预期为 0）")
    print(f"  ✅ total_return: {summary_metrics.get('total_return', 'N/A')}")
    print("  ✅ Test 2 PASS\n")


def test_no_risk_pipeline() -> None:
    """Test 3: 不传 risk_pipeline — 完全向后兼容。

    与旧行为完全一致。
    """
    print("=" * 60)
    print("Test 3: 不传 risk_pipeline — 完全向后兼容")
    print("=" * 60)

    ohlcv, signals = _make_test_data(100)

    pi = PortfolioIntegration(initial_cash=1_000_000.0)

    equity_curve, trades, daily_metrics, summary_metrics = pi.run(signals, ohlcv)

    assert not equity_curve.empty, "权益曲线不应为空"
    assert "risk_events" not in summary_metrics or summary_metrics["risk_events"] == []

    print(f"  ✅ equity_curve 长度: {len(equity_curve)}")
    print(f"  ✅ trades 数量: {len(trades)}")
    print(f"  ✅ risk_pipeline=None，无风控事件")
    print("  ✅ Test 3 PASS\n")


def test_drawdown_guard_state() -> None:
    """Test 4: DrawdownGuard 状态查询。

    验证单个模块的基础功能正常。
    """
    print("=" * 60)
    print("Test 4: DrawdownGuard 状态查询")
    print("=" * 60)

    from backtest.risk.drawdown_guard import DrawdownGuard, DrawdownGuardConfig

    cfg = DrawdownGuardConfig(
        warning_threshold=0.08,
        critical_threshold=0.15,
    )
    guard = DrawdownGuard(cfg)

    # 首个 bar
    s1 = guard.update(current_equity=1_000_000, current_signal=1)
    assert s1 == 1, "首 bar 信号应原样通过"
    state = guard.get_state()
    assert state.breach_level == "none", f"预期 none，得到 {state.breach_level}"
    assert state.current_drawdown == 0.0, "首 bar 回撤应为 0"
    print(f"  ✅ 首 bar: signal={s1}, breach_level={state.breach_level}")

    # 正常状态
    s2 = guard.update(current_equity=1_050_000, current_signal=1)
    assert s2 == 1, "新高时信号应通过"
    state = guard.get_state()
    assert state.current_drawdown == 0.0, "新高时回撤应为 0"
    print(f"  ✅ 新高: signal={s2}, peak={state.peak_equity}")

    # 轻微下跌（不到 warning）
    s3 = guard.update(current_equity=1_020_000, current_signal=1)
    assert s3 == 1, "轻微下跌不应阻断"
    state = guard.get_state()
    print(f"  ✅ 轻微下跌: signal={s3}, drawdown={state.current_drawdown:.4f}")

    # 跌至 warning 阈值以下
    s4 = guard.update(current_equity=950_000, current_signal=1)
    # 回撤 = (1_050_000 - 950_000) / 1_050_000 = 0.0952 > 0.08 → warning，禁止开仓
    state = guard.get_state()
    print(f"  ✅ warning 回撤: signal={s4}, breach={state.breach_level}, dd={state.current_drawdown:.4f}")

    # 跌至 critical 阈值
    s5 = guard.update(current_equity=880_000, current_signal=1)
    # (1_050_000 - 880_000) / 1_050_000 = 0.1619 > 0.15 → critical，强制平仓
    state = guard.get_state()
    assert s5 == -1, f"critical 回撤应强制平仓，得到 signal={s5}"
    assert state.breach_level == "critical", f"预期 critical，得到 {state.breach_level}"
    print(f"  ✅ critical 回撤: signal={s5}, breach={state.breach_level}, dd={state.current_drawdown:.4f}")

    # 验证风控事件
    events = guard.get_risk_events()
    assert len(events) >= 2, f"应有至少 2 个风控事件，得到 {len(events)}"
    print(f"  ✅ 风控事件: {len(events)} 个")

    print("  ✅ Test 4 PASS\n")


def _load_601857_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """加载 601857（中国石油）的真实行情数据，并生成简单的买入信号。

    Returns:
        tuple: (ohlcv, signals) DataFrames。
    """
    csv_path = "C:/Users/17699/mozhi_platform/data/market/601857_SH.csv"
    df = pd.read_csv(
        csv_path,
        parse_dates=["date"],
        index_col="date",
        dtype={"turnover_rate": float},
    )
    df.columns = [c.lower() for c in df.columns]

    # 确保 OHLCV 列存在
    expected_cols = {"open", "high", "low", "close", "volume"}
    missing = expected_cols - set(df.columns)
    if missing:
        raise ValueError(f"601857 CSV 缺少列: {missing}")

    # 使用 2020 年全年数据（约 242 个交易日）
    df = df.loc["2020-01-01":"2020-12-31"].copy()

    # 生成信号：第 20 天买入（MA 计算至少需 20 个 bar），第 60 天卖出
    n = len(df)
    signals = pd.DataFrame(
        {"signal": np.zeros(n, dtype=int)},
        index=df.index,
    )
    buy_idx = min(20, n - 1)
    sell_idx = min(60, n - 1)
    if buy_idx < n:
        signals.iloc[buy_idx, 0] = 1
    if sell_idx < n:
        signals.iloc[sell_idx, 0] = -1

    return df, signals


def test_with_601857_enabled() -> None:
    """Test 6: 使用 601857 真实行情的全流水线测试。

    加载 A 股 601857（中国石油）2020 年行情数据，
    启用 RiskPipeline 三个模块，验证全流程正确运行。
    """
    print("=" * 60)
    print("Test 6: 601857 真实行情 — 全流水线（enable_all=True）")
    print("=" * 60)

    ohlcv, signals = _load_601857_data()

    mf_cfg = MarketStateFilterConfig(enabled=True)
    vr_cfg = VolatilityRiskConfig(enabled=True)
    dd_cfg = DrawdownGuardConfig(enabled=True)

    pipeline_cfg = RiskPipelineConfig(
        market_state_filter=mf_cfg,
        volatility_risk=vr_cfg,
        drawdown_guard=dd_cfg,
        enable_market_state_filter=True,
        enable_volatility_risk=True,
        enable_drawdown_guard=True,
    )

    regime_analyzer = RegimeAnalyzer()
    pipeline = RiskPipeline(regime_analyzer=regime_analyzer, config=pipeline_cfg)

    pi = PortfolioIntegration(
        initial_cash=1_000_000.0,
        risk_pipeline=pipeline,
    )

    equity_curve, trades, daily_metrics, summary_metrics = pi.run(signals, ohlcv)

    assert not equity_curve.empty, "权益曲线不应为空"
    assert len(trades) > 0, "应有成交记录"
    assert "risk_events" in summary_metrics, "summary 应包含 risk_events"

    print(f"  ✅ 数据范围: {ohlcv.index[0].date()} → {ohlcv.index[-1].date()}")
    print(f"  ✅ 数据量: {len(ohlcv)} bars")
    print(f"  ✅ equity_curve 长度: {len(equity_curve)}")
    print(f"  ✅ trades 数量: {len(trades)}")
    print(f"  ✅ risk_events 数量: {len(summary_metrics['risk_events'])}")
    print(f"  ✅ total_return: {summary_metrics.get('total_return', 'N/A')}")
    print(f"  ✅ max_drawdown: {summary_metrics.get('max_drawdown', 'N/A')}")
    print("  ✅ Test 6 PASS\n")


def test_with_601857_disabled() -> None:
    """Test 7: 使用 601857 真实行情，关闭流水线 — 验证不受影响。

    加载 A 股 601857 行情，disable_all=True，
    确认流水线关闭后回测正常，无风控事件。
    """
    print("=" * 60)
    print("Test 7: 601857 真实行情 — 关闭流水线（enable_all=False）")
    print("=" * 60)

    ohlcv, signals = _load_601857_data()

    pipeline_cfg = RiskPipelineConfig(
        enable_market_state_filter=False,
        enable_volatility_risk=False,
        enable_drawdown_guard=False,
    )

    pipeline = RiskPipeline(config=pipeline_cfg)

    pi = PortfolioIntegration(
        initial_cash=1_000_000.0,
        risk_pipeline=pipeline,
    )

    equity_curve, trades, daily_metrics, summary_metrics = pi.run(signals, ohlcv)

    assert not equity_curve.empty, "权益曲线不应为空"
    assert len(trades) > 0, "应有成交记录"

    risk_events = summary_metrics.get("risk_events", [])
    assert len(risk_events) == 0, f"关闭流水线后不应有风控事件，得到 {len(risk_events)}"

    print(f"  ✅ 数据范围: {ohlcv.index[0].date()} → {ohlcv.index[-1].date()}")
    print(f"  ✅ 数据量: {len(ohlcv)} bars")
    print(f"  ✅ equity_curve 长度: {len(equity_curve)}")
    print(f"  ✅ trades 数量: {len(trades)}")
    print(f"  ✅ risk_events 数量: {len(risk_events)}（预期为 0）")
    print(f"  ✅ total_return: {summary_metrics.get('total_return', 'N/A')}")
    print("  ✅ Test 7 PASS\n")


def test_volatility_manager_sizing() -> None:
    """Test 5: VolatilityRiskManager 仓位计算。

    验证单个模块的基础功能正常。
    """
    print("=" * 60)
    print("Test 5: VolatilityRiskManager 仓位计算")
    print("=" * 60)

    from backtest.risk.volatility_risk_manager import VolatilityRiskManager, VolatilityRiskConfig

    cfg = VolatilityRiskConfig(
        enabled=True,
        atr_period=5,
        risk_per_trade_pct=0.01,
        max_position_pct=0.20,
    )
    mgr = VolatilityRiskManager(cfg)

    ohlcv, signals = _make_test_data(50)
    result = mgr.process(signals, ohlcv)

    assert "position_ratio" in result.columns, "结果应包含 position_ratio 列"
    # 有信号的行的 position_ratio 应 > 0
    buy_row = result[result["signal"] == 1]
    if len(buy_row) > 0:
        pr = buy_row["position_ratio"].iloc[0]
        assert 0 < pr <= 0.25, f"买入信号的仓位比例应在 (0, 0.25] 范围内，得到 {pr}"
        print(f"  ✅ 买入信号仓位比例: {pr:.4f}")

    print(f"  ✅ position_ratio 列存在，非空")
    print("  ✅ Test 5 PASS\n")


if __name__ == "__main__":
    tests = [
        test_drawdown_guard_state,
        test_volatility_manager_sizing,
        test_pipeline_enabled,
        test_pipeline_disabled,
        test_no_risk_pipeline,
        test_with_601857_enabled,
        test_with_601857_disabled,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAIL: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"结果: {passed}/{len(tests)} 通过", end="")
    if failed > 0:
        print(f", {failed} 失败 ❌")
    else:
        print(" ✅")


# ════════════════════════════════════════════════════════════════
# P1 模块测试
# ════════════════════════════════════════════════════════════════


def test_anchored_vwap_computation() -> None:
    """Test P1-1: AnchoredVWAP 计算测试。

    验证从 first_bar 锚定的 VWAP 计算、通道、偏离度正确。
    """
    print("=" * 60)
    print("Test P1-1: AnchoredVWAP 计算测试")
    print("=" * 60)

    from backtest.factors.volume.anchored_vwap import (
        AnchorConfig, calc_anchored_vwap, calc_anchored_vwap_score,
        AnchoredVWAPFactor, find_anchor_index,
    )

    # 模拟 50 日数据
    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.normal(0, 1.0, size=50))

    df = pd.DataFrame({
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, size=50),
    }, index=dates)

    # 1. first_bar 锚点
    result = calc_anchored_vwap(df, config=AnchorConfig(type="first_bar"))
    assert "anchored_vwap" in result.columns, "应包含 anchored_vwap 列"
    assert "vwap_upper_1" in result.columns, "应包含 vwap_upper_1 列"
    assert "vwap_deviation" in result.columns, "应包含 vwap_deviation 列"
    assert not result["anchored_vwap"].isna().all(), "VWAP 不应全为 NaN"
    print(f"  ✅ first_bar VWAP 列存在，末值: {result['anchored_vwap'].iloc[-1]:.4f}")

    # 2. 通道验证: upper_1 >= vwap >= lower_1, upper_2 >= upper_1 等
    last = result.iloc[-1]
    assert last["vwap_upper_2"] >= last["vwap_upper_1"], "+2σ 应 >= +1σ"
    assert last["vwap_upper_1"] >= last["anchored_vwap"], "+1σ 应 >= VWAP"
    assert last["anchored_vwap"] >= last["vwap_lower_1"], "VWAP 应 >= -1σ"
    assert last["vwap_lower_1"] >= last["vwap_lower_2"], "-1σ 应 >= -2σ"
    print(f"  ✅ 通道结构正确: U2={last['vwap_upper_2']:.2f} > U1={last['vwap_upper_1']:.2f} > VWAP={last['anchored_vwap']:.2f}")

    # 3. 偏离度计算
    dev_series = result["vwap_deviation"]
    assert not dev_series.isna().all(), "偏离度不应全为 NaN"
    last_dev = dev_series.iloc[-1]
    print(f"  ✅ 偏离度末值: {last_dev:.4f} (标准差距离)")

    # 4. auto_find_anchor_index
    idx = find_anchor_index(df, AnchorConfig(type="first_bar"))
    assert idx == 0, f"first_bar 锚点应为 0，得到 {idx}"
    print(f"  ✅ first_bar 锚点索引: {idx}")

    # 5. score 接口
    score = calc_anchored_vwap_score(df)
    assert "score" in score, "score 字典应含 score 键"
    print(f"  ✅ calc_anchored_vwap_score: score={score['score']}, deviation={score['vwap_deviation']}")

    # 6. AnchoredVWAPFactor 类封装
    factor = AnchoredVWAPFactor(params={"anchor_type": "first_bar"})
    result2 = factor.compute(df)
    assert "anchored_vwap" in result2.columns
    print(f"  ✅ AnchoredVWAPFactor.compute() 正常: vwap末值={result2['anchored_vwap'].iloc[-1]:.4f}")

    # 7. get_score() 类方法
    score2 = factor.get_score(df)
    assert "score" in score2
    print(f"  ✅ AnchoredVWAPFactor.get_score(): score={score2['score']}")

    # 8. anchor_index 结果
    assert score2["anchor_index"] == 0.0
    print(f"  ✅ anchor_index: {score2['anchor_index']}")

    # 9. custom_date 锚点
    result3 = calc_anchored_vwap(df, config=AnchorConfig(type="custom_date", date="2025-01-10"))
    assert not result3["anchored_vwap"].isna().all()
    idx3 = result3["anchor_index"].iloc[0]
    print(f"  ✅ custom_date 锚点索引: {int(idx3)}")

    # 10. high_volume 锚点
    result4 = calc_anchored_vwap(df, config=AnchorConfig(type="high_volume", vol_threshold=2.0))
    idx4 = result4["anchor_index"].iloc[0]
    print(f"  ✅ high_volume 锚点索引: {int(idx4)}")

    print("  ✅ Test P1-1 PASS\n")


def test_regime_context_builder() -> None:
    """Test P1-2: RegimeContextBuilder 综合信号测试。

    验证 builder 的四分量融合正确返回有效的综合信号。
    不依赖 KnowledgeBridge（传 None），仅测试三分量融合。
    """
    print("=" * 60)
    print("Test P1-2: RegimeContextBuilder 综合信号测试")
    print("=" * 60)

    from backtest.risk.regime_context_builder import RegimeContextBuilder, RegimeContextSignal
    from backtest.regime.regime_analyzer import RegimeAnalyzer

    # 生成有趋势的数据
    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    np.random.seed(42)
    # 上涨趋势
    prices = 100 + np.arange(60) * 0.3 + np.random.normal(0, 1.2, size=60)

    df = pd.DataFrame({
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, size=60),
    }, index=dates)

    analyzer = RegimeAnalyzer()
    builder = RegimeContextBuilder(
        regime_analyzer=analyzer,
        knowledge_bridge=None,
    )

    signal = builder.build_signal(df, symbol="601857")

    # 基本结构验证
    assert isinstance(signal, RegimeContextSignal), "应返回 RegimeContextSignal"
    assert signal.action in ("BUY", "SELL", "HOLD", "REDUCE"), f"action 值异常: {signal.action}"
    assert 0.0 <= signal.confidence <= 1.0, f"confidence 应在 [0,1] 间: {signal.confidence}"
    assert -1.0 <= signal.composite_score <= 1.0, f"composite_score 应在 [-1,1] 间: {signal.composite_score}"

    print(f"  ✅ 综合评分: {signal.composite_score}")
    print(f"  ✅ 操作建议: {signal.action}")
    print(f"  ✅ 置信度: {signal.confidence}")
    print(f"  ✅ 市场状态: {signal.regime}")
    print(f"  ✅ VWAP 偏离: {signal.vwap_deviation}σ")
    print(f"  ✅ Volume Profile POC: {signal.volume_profile_poc}")
    print(f"  ✅ LVN 数量: {signal.lvn_count}")
    print(f"  ✅ 推理: {signal.reasoning}")
    print(f"  ✅ 权重: {signal.weights}")

    # 验证各分项存在
    assert signal.weights, "weights 不应为空"
    assert len(signal.weights) >= 3, "至少应有 3 个分量权重"
    print(f"  ✅ 信号分量数量: {len(signal.weights)}")

    # 子分数收集
    subscores = builder.get_sub_scores(df)
    assert "regime" in subscores
    assert "vwap" in subscores
    assert "volume_profile" in subscores
    print(f"  ✅ 子分数: {subscores}")

    # 空数据测试
    empty_signal = builder.build_signal(pd.DataFrame())
    assert empty_signal.action == "HOLD"
    assert empty_signal.confidence == 0.0
    print(f"  ✅ 空数据处理正常: action={empty_signal.action}")

    print("  ✅ Test P1-2 PASS\n")


def test_pipeline_signal_fusion() -> None:
    """Test P1-3: RiskPipeline 信号融合流水线测试。

    验证 RiskPipeline.process_signal_fusion() 集成 RegimeContextBuilder。
    """
    print("=" * 60)
    print("Test P1-3: RiskPipeline 信号融合测试")
    print("=" * 60)

    from backtest.risk.risk_pipeline import RiskPipeline, RiskPipelineConfig
    from backtest.risk.regime_context_builder import RegimeContextSignal
    from backtest.regime.regime_analyzer import RegimeAnalyzer

    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    np.random.seed(42)
    prices = 100 + np.arange(60) * 0.2 + np.random.normal(0, 1.0, size=60)

    df = pd.DataFrame({
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, size=60),
    }, index=dates)

    # 启用信号融合的流水线
    cfg = RiskPipelineConfig(
        enable_market_state_filter=False,
        enable_volatility_risk=False,
        enable_drawdown_guard=False,
        enable_signal_fusion=True,
    )

    analyzer = RegimeAnalyzer()
    pipeline = RiskPipeline(regime_analyzer=analyzer, config=cfg)

    signal = pipeline.process_signal_fusion(df, symbol="601857")

    assert isinstance(signal, RegimeContextSignal), "应返回 RegimeContextSignal"
    print(f"  ✅ 信号融合: action={signal.action}, score={signal.composite_score}")

    # 验证风控事件记录
    events = pipeline.get_all_risk_events()
    fusion_events = [e for e in events if isinstance(e, dict) and e.get("event_type") == "signal_fusion"]
    assert len(fusion_events) >= 1, "应记录至少 1 个 signal_fusion 事件"
    print(f"  ✅ 风控事件记录: {len(fusion_events)} 个 signal_fusion")

    # 关闭信号融合
    cfg2 = RiskPipelineConfig(
        enable_signal_fusion=False,
    )
    pipeline2 = RiskPipeline(regime_analyzer=analyzer, config=cfg2)
    signal2 = pipeline2.process_signal_fusion(df)
    assert signal2.action == "HOLD"
    assert signal2.reasoning == "信号融合已关闭"
    print(f"  ✅ 信号融合关闭: action={signal2.action}")

    print("  ✅ Test P1-3 PASS\n")


def test_p1_all_modules_integration() -> None:
    """Test P1-4: 全量 P1+P0 流水线测试。

    验证 AnchoredVWAP + RegimeContextBuilder + RiskPipeline 全模块集成。
    加载 601857 真实数据，启用所有 P0+P1 模块。
    """
    print("=" * 60)
    print("Test P1-4: 全量 P1+P0 流水线测试（601857 真实数据）")
    print("=" * 60)

    from backtest.risk.risk_pipeline import RiskPipeline, RiskPipelineConfig
    from backtest.risk.market_state_filter import MarketStateFilterConfig
    from backtest.risk.volatility_risk_manager import VolatilityRiskConfig
    from backtest.risk.drawdown_guard import DrawdownGuardConfig
    from backtest.risk.regime_context_builder import RegimeContextSignal
    from backtest.regime.regime_analyzer import RegimeAnalyzer
    from backtest.engine.portfolio_integration import PortfolioIntegration
    from backtest.factors.factor_registry import FactorRegistry
    from backtest.factors.volume.anchored_vwap import calc_anchored_vwap, AnchorConfig

    ohlcv, signals = _load_601857_data()

    # 配置全量 P0+P1
    cfg = RiskPipelineConfig(
        market_state_filter=MarketStateFilterConfig(enabled=True),
        volatility_risk=VolatilityRiskConfig(enabled=True),
        drawdown_guard=DrawdownGuardConfig(enabled=True),
        enable_market_state_filter=True,
        enable_volatility_risk=True,
        enable_drawdown_guard=True,
        enable_signal_fusion=True,
    )

    analyzer = RegimeAnalyzer()
    pipeline = RiskPipeline(regime_analyzer=analyzer, config=cfg)

    # 1. AnchoredVWAP 在真实数据上运行
    vwap_result = calc_anchored_vwap(ohlcv)
    assert "anchored_vwap" in vwap_result.columns
    vwap_last = vwap_result["anchored_vwap"].iloc[-1]
    print(f"  ✅ AnchoredVWAP 末值: {vwap_last:.4f}")

    # 2. 信号融合
    fusion_signal = pipeline.process_signal_fusion(ohlcv, symbol="601857")
    assert isinstance(fusion_signal, RegimeContextSignal)
    print(f"  ✅ 信号融合: action={fusion_signal.action}, score={fusion_signal.composite_score}, conf={fusion_signal.confidence:.2f}")

    # 3. 全量流水线回测
    pi = PortfolioIntegration(
        initial_cash=1_000_000.0,
        risk_pipeline=pipeline,
    )
    equity_curve, trades, daily_metrics, summary_metrics = pi.run(signals, ohlcv)

    assert not equity_curve.empty, "权益曲线不应为空"
    assert len(trades) > 0, "应有成交记录"
    assert "risk_events" in summary_metrics, "summary 应包含 risk_events"

    print(f"  ✅ 回测范围: {ohlcv.index[0].date()} → {ohlcv.index[-1].date()}")
    print(f"  ✅ equity_curve 长度: {len(equity_curve)}")
    print(f"  ✅ trades 数量: {len(trades)}")
    print(f"  ✅ risk_events 数量: {len(summary_metrics['risk_events'])}")
    print(f"  ✅ total_return: {summary_metrics.get('total_return', 'N/A')}")
    print(f"  ✅ max_drawdown: {summary_metrics.get('max_drawdown', 'N/A')}")

    # 4. FactorRegistry 确认已注册 anchored_vwap
    registry = FactorRegistry()
    volume_factors = registry.list_factors("volume")
    assert "anchored_vwap" in volume_factors, "anchored_vwap 应注册在 volume 分类"
    print(f"  ✅ FactorRegistry volume 族: {volume_factors}")

    # 5. RiskPipeline 完整风控事件列表
    all_events = pipeline.get_all_risk_events()
    event_types = set(
        e.get("event_type", "") if isinstance(e, dict) else getattr(e, "event_type", "")
        for e in all_events
    )
    print(f"  ✅ 风控事件类型: {event_types}")

    print("  ✅ Test P1-4 PASS\n")


def test_anchored_vwap_no_data() -> None:
    """Test P1-5: AnchoredVWAP 空数据与边界处理测试。"""
    print("=" * 60)
    print("Test P1-5: AnchoredVWAP 边界情况测试")
    print("=" * 60)

    from backtest.factors.volume.anchored_vwap import (
        AnchorConfig, calc_anchored_vwap, calc_anchored_vwap_score, find_anchor_index,
    )

    # 空 DataFrame
    empty_df = pd.DataFrame()
    try:
        result = calc_anchored_vwap(empty_df)
        assert result.empty, "空 df 应返回空结果"
        print(f"  ✅ 空 DataFrame 处理正常")
    except (ValueError, KeyError, IndexError) as e:
        print(f"  ✅ 空 DataFrame 引发预期异常: {e}")

    # 极短数据（1 bar）
    dates = pd.date_range("2025-01-01", periods=1, freq="D")
    df_short = pd.DataFrame({
        "open": [100.0],
        "high": [101.0],
        "low": [99.0],
        "close": [100.5],
        "volume": [5_000_000],
    }, index=dates)

    result_short = calc_anchored_vwap(df_short)
    assert "anchored_vwap" in result_short.columns
    assert not result_short.isna().all().all(), "1 bar 不应全 NaN"
    print(f"  ✅ 1 bar 数据处理正常: vwap={result_short['anchored_vwap'].iloc[0]:.4f}")

    # 自定义日期锚点（日期不存在）
    dates_longer = pd.date_range("2025-01-10", periods=10, freq="D")
    df_med = pd.DataFrame({
        "open": np.random.uniform(99, 101, 10),
        "high": np.random.uniform(101, 103, 10),
        "low": np.random.uniform(97, 99, 10),
        "close": np.random.uniform(99, 101, 10),
        "volume": np.random.randint(1_000_000, 10_000_000, 10),
    }, index=dates_longer)

    # 找早于数据的日期 → 应该从第一个 bar 开始
    result_early = calc_anchored_vwap(df_med, config=AnchorConfig(type="custom_date", date="2025-01-01"))
    idx_early = result_early["anchor_index"].iloc[0]
    print(f"  ✅ 早于数据范围的 custom_date: anchor_idx={int(idx_early)}")

    print("  ✅ Test P1-5 PASS\n")


# ── 注册 P1 测试到执行列表 ──

if __name__ == "__main__":
    p0_tests = [
        test_drawdown_guard_state,
        test_volatility_manager_sizing,
        test_pipeline_enabled,
        test_pipeline_disabled,
        test_no_risk_pipeline,
        test_with_601857_enabled,
        test_with_601857_disabled,
    ]
    p1_tests = [
        test_anchored_vwap_computation,
        test_regime_context_builder,
        test_pipeline_signal_fusion,
        test_p1_all_modules_integration,
        test_anchored_vwap_no_data,
    ]

    all_tests = p0_tests + p1_tests

    passed = 0
    failed = 0
    for test in all_tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAIL: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"P0+P1 结果: {passed}/{len(all_tests)} 通过", end="")
    if failed > 0:
        print(f", {failed} 失败 ❌")
    else:
        print(" ✅")
