<!--
author: 墨衡
created_time: 2026-05-16
task_id: backtest_fix_P6
-->
# 回测变更汇总表 — v4.0 方案

## 概述

v4.0 方案涉及 **4 项子方案**对 `run_grid.py` / `run_trend.py` / `run_reversal.py` 的交叉修改。
以下表格汇总所有改动点，明确每次改动的函数/方法边界。

## 子方案定义

| 编号 | 方案 | 对应文件 | 核心改动 |
|:---:|:-----|:--------|:---------|
| 项1 | **配置规范化** | 三文件 | 统一的 Config dataclass + `__post_init__` 默认值 |
| 项2 | **信号注入模式** | 三文件 | SignalBridge 消费预生成信号，替代运行时实时计算 |
| 项3 | **批量运行** | 三文件 | `*_batch()` 函数 + ThreadPoolExecutor 并行执行 |
| 项4 | **结果持久化** | 三文件 | `_persist_result()` + 文件名规范 + 买入持有基准 |

## run_grid.py 改动明细

| 改动项 | 函数/方法 | 行号 | 改动说明 | 所属项 |
|:-----:|:---------|:----:|:---------|:------:|
| 1g | `GridRunnerConfig.__post_init__` | §270 | 信号/仓位默认值注入；支持 GridVotingSignal / StaticGridSignal / DynamicGridSignal 等联合类型 | 项1 |
| 2g | `GridSignalProvider.compute_signal` | §128 | 封装网格信号计算逻辑，供 `_GridRunnerStrategy` 消费 | 项2 |
| 3g | `_GridRunnerStrategy.on_bar` | §467 | 核心逐Bar处理：信号→止损→敞口检查→冷却→开平仓；替代旧版内联逻辑 | 项2 |
| 4g | `run_grid_backtest` | §672 | 完整回测管线：数据加载→信号提供→引擎执行→买入持有基准→结果持久化；异常隔离（独立 try/except） | 项1/3 |
| 5g | `batch_run_grid` | §822 | 并发批量运行；ThreadPoolExecutor + as_completed；错误隔离（失败项 status="FAILED"） | 项3 |
| 6g | `_persist_result` | §884 | 结果写入 backtest_results/，文件名: `grid_{symbol}_{signal}_{tag}_{timestamp}.json` | 项4 |
| 7g | `make_grid_config` | §938 | 快捷创建 GridRunnerConfig；根据 position_mode 自动匹配 GridFixedPosition/GridLayerPosition/GridBatcherPosition | 项1 |

> 计 7 项改动，其中核心改动 5 项（1g/3g/4g/5g/6g），辅助 2 项。

## run_trend.py 改动明细

| 改动项 | 函数/方法 | 行号 | 改动说明 | 所属项 |
|:-----:|:---------|:----:|:---------|:------:|
| 1t | `TrendBacktestConfig.__post_init__` | §160 | 5种信号类型（ma/macd/bollinger/trend_score/voting）+ 3种仓位模式（fixed/trend_score/pyramid）的默认参数映射 | 项1 |
| 2t | `generate_signals` | §278 | 信号生成调度函数；根据 signal_type 分发到 ma/macd/bollinger/trend_score/voting | 项2 |
| 3t | `_TrendRunnerStrategy.on_bar` | §358 | 内部策略：SignalBridge 消费信号 + TrendPositionManager 仓位管理 + StopLossTakeProfit 风控 | 项2 |
| 4t | `run_trend_backtest` | §504 | 主运行函数：数据加载→信号生成→仓位管理器→引擎配置→执行→持久化；可接收可选 Config 参数 | 项1/3 |
| 5t | `run_trend_backtest_batch` | §691 | 并发批量运行；ThreadPoolExecutor；结果顺序与传入 configs 一致 | 项3 |
| 6t | `_persist_result` | §634 | 结果持久化，文件名: `trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json` | 项4 |

> 计 6 项改动，其中核心改动 5 项（1t/2t/3t/4t/5t），辅助 1 项。

## run_reversal.py 改动明细

| 改动项 | 函数/方法 | 行号 | 改动说明 | 所属项 |
|:-----:|:---------|:----:|:---------|:------:|
| 1r | `ReversalBacktestConfig.__post_init__` | §160 | 5种信号类型（rsi/kdj/bollinger_reversal/bias/voted）+ 3种仓位模式（fixed/oversold_depth/batch）+ cooler_days 字段 | 项1 |
| 2r | `generate_signals` | §278 | 信号生成调度函数；分发到 rsi/kdj/bollinger_reversal/bias/voted | 项2 |
| 3r | `_ReversalRunnerStrategy.on_bar` | §367 | 内部策略：SignalBridge 消费信号 + ReversalCooler 冷却管理 + ReversalPositionManager 仓位风控；含空头仓位管理 | 项2 |
| 4r | `run_reversal_backtest` | §514 | 主运行函数：数据加载→信号生成→冷却管理→仓位管理器→引擎执行→持久化 | 项1/3 |
| 5r | `run_reversal_backtest_batch` | §704 | 并发批量运行；ThreadPoolExecutor；单次运行异常隔离 | 项3 |
| 6r | `_persist_result` | §646 | 结果持久化，文件名: `reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json` | 项4 |

> 计 6 项改动，其中核心改动 5 项（1r/2r/3r/4r/5r），辅助 1 项。

## 跨文件一致性对照

| 模式 | run_grid.py | run_trend.py | run_reversal.py |
|:----|:-----------|:------------|:---------------|
| Config dataclass + `__post_init__` | `GridRunnerConfig` | `TrendBacktestConfig` | `ReversalBacktestConfig` |
| 信号生成/提供 | `GridSignalProvider.compute_signal()` | `generate_signals()` | `generate_signals()` |
| 内部策略类 | `_GridRunnerStrategy` | `_TrendRunnerStrategy` | `_ReversalRunnerStrategy` |
| 主运行函数 | `run_grid_backtest()` | `run_trend_backtest()` | `run_reversal_backtest()` |
| 批量运行 | `batch_run_grid()` | `run_trend_backtest_batch()` | `run_reversal_backtest_batch()` |
| 结果持久化 | `_persist_result()` | `_persist_result()` | `_persist_result()` |
| 买入持有基准 | `run_grid_backtest` 内联 | `calc_buy_hold_return` 外部引用 | `calc_buy_hold_return` 外部引用 |

## 变更日期

| 日期 | 版本 | 变更说明 |
|:---:|:----:|:--------|
| 2026-05-15 | v4.0 | 三文件改造：Config规范化 + SignalBridge注入 + 批量运行 + 持久化 |
| 2026-05-16 | v4.0 fix | generate_comparison.py W2修复：真实回测数据替换模拟交易 |
