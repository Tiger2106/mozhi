# 回测报告改进方案 v2 — 执行摘要

> 作者: 墨涵（墨衡执行）| 日期: 2026-05-16 07:20 | 状态: ✅ 全部4项完成
> 依据: `report_improvements_todo.md`

---

## 改进总览

| # | 改进项 | 状态 | 涉及文件 | 完成时间 |
|:-:|--------|:----:|----------|:--------:|
| 1 | **基准对标（买入持有）** | ✅ | `multi_runner.py`, `chart_generator.py`, `benchmark.py` | 07:00 |
| 2 | **历史数据扩展至2020年** | ✅ | `data_historical_fill.py`, `data_filler.py` | 07:09 |
| 3 | **买卖盈利概率分析** | ✅ | `performance.py`, `generate_comparison.py` | 07:16 |
| 4 | **策略参数配置输出** | ✅ | `generate_comparison.py` | 07:19 |

---

## 1. 基准对标（买入持有）

**文件：** `mozhi_platform/src/backtest/strategies/multi_runner.py`
**文件：** `mozhi_platform/src/backtest/pipeline/chart_generator.py`

- `CombinedResult` 新增 `benchmark_total_return` / `benchmark_name`
- `MultiStrategyResult` 新增 `benchmark_info`
- `run_multi()` 接收 `benchmark_equity` + `benchmark_name`
- 新增 `compute_benchmark_equity(bars, capital)` 辅助方法
- `chart_generator.py` 图表叠加橙色虚线基准线

**使用方式：**
```python
eq = MultiStrategyRunner.compute_benchmark_equity(bars, 1_000_000)
result = runner.run_multi(strategies=..., bars=bars, benchmark_equity=eq, benchmark_name="中国石油")
```

---

## 2. 历史数据扩展至2020年

**文件：** `mozhi_platform/src/backtest/data_historical_fill.py`（新增）
**文件：** `mozhi_platform/src/backtest/data_filler.py`（更新默认值）

- 采集3只标的（601857/600519/000001）
- 覆盖 2020-01-02 ~ 2026-05-15
- 每只 1540 行，总计 4620 行
- 前复权口径
- 幂等写入 SQLite

---

## 3. 买卖盈利概率分析

**文件：** `mozhi_platform/src/backtest/performance.py`
**文件：** `mozhi_platform/src/backtest/reports/generate_comparison.py`

- `performance.py` 新增 `pair_trades_to_roundtrips()`（交易配对）和 `compute_trade_distribution()`（盈亏分布）
- 报告新增 **第六节「交易盈利概率分析」**：
  - 逐笔交易明细表（开仓日/平仓日/方向/开仓价/平仓价/数量/盈亏金额/收益率/持仓天数）
  - 盈亏分布统计表（胜率/盈亏比/平均单笔盈利/亏损/最大单笔）

---

## 4. 策略参数配置输出

**文件：** `mozhi_platform/src/backtest/reports/generate_comparison.py`

- 新增 `_extract_params_block()` 从 Config dataclass 自动读取
- 趋势策略参数：signal_type, ma_fast, ma_slow, position_ratio, stop_loss
- 反转策略参数：rsi_period, oversold, overbought, cooler_days
- 网格策略参数：GridConfig（下界/上界/层数）+ GridPositionManager（仓位/止损）
- 报告第零节新增"策略参数配置"区块

---

## 后续建议

1. **将模拟交易数据替换为实际回测数据** — 当前盈利概率分析使用已知胜率生成模拟数据，接入 `BacktestResult.trades` 后即完全真实
2. **修复 trading_calendar 表** — 约103个节假日被误标记为交易日，不建议影响回测，但建议择机清洗
3. **扩展到更多标的** — 当前仅 601857/600519/000001 有完整历史数据
