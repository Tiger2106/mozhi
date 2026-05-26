<!--
author: 墨衡 (moheng)
created_time: 2026-05-18 22:11:00+08:00
task_id: phase_4b_launch
version: research_v2
-->

# Phase 4b 执行计划

**生成时间**: 2026-05-18 22:11 +08:00
**来源**: `report_upgrade_v3_design.md`（v3.2）
**4a 状态**: ✅ 已完成（5 模块已就绪: P1/P2/P3/P6/P8 基础版）
**Owner 优先级**: P4 Walk Forward 完整版（滚动窗格）> 其余 4b 模块

---

## 依赖图

```
[前置] 4a 基础产出 (已完成)
   │
   ├── P4 Walk Forward (第一优先)
   │   ├── 1a. WalkForwardFold 引擎 fold 改造        [1.5天]
   │   ├── 1b. WalkForwardRunner 框架 + 窗格运行       [1.0天]
   │   ├── 1c. WFE 聚合 + 参数稳定性分析              [0.5天]
   │   └── 1d. P4 报告展示层                          [0.5天]
   │
   ├── P3 参数交互热力图完善                          [0.5天] ─── 组C
   ├── P1 时间维度 + Brinson 完善                     [1.0天] ─── 串行链
   ├── P2 回撤归因 + 因子暴露模拟                     [1.5天] ─── P2子链
   ├── P8 板块指数接入 + 对比                         [1.5天] ─── 组C
   └── P5 成交执行缺口框架                           [1.5天] ─── 组D
```

## 执行顺序（按优先级）

| 优先级 | 任务 | 模块 | 工时 | 状态 |
|:-----:|:----|:----|:---:|:----|
| **P0** | P4 WalkForward 引擎 fold 改造 | P4 | 1.5 天 | ✅ 完成 |
| **P0** | P4 WalkForwardRunner + 窗格运行 | P4 | 1.0 天 | ✅ 完成 |
| **P0** | P4 WFE 聚合 + 参数稳定性分析 | P4 | 0.5 天 | ✅ 完成 |
| **P0** | P4 报告展示层 | P4 | 0.5 天 | ✅ 完成 |
| P1 | P3 参数交互热力图完善 | P3 | 0.5 天 | 📅 |
| P1 | P1 时间维度 + Brinson 完善 | P1 | 1.0 天 | 📅 |
| P1 | P2 回撤归因 + 因子暴露模拟 | P2 | 1.5 天 | 📅 |
| P1 | P8 板块指数接入 + 对比 | P8 | 1.5 天 | 📅 |
| P2 | P5 成交执行缺口框架 | P5 | 1.5 天 | 📅 |

---

## 任务详情

### T1: P4 WalkForward 引擎 fold 改造

**目标**: 在回测引擎中实现滑动窗格划分能力（WalkForwardFold），支持训练期/测试期自动划分。

**实现方案**:
```
WalkForwardFold:
  - train_start, train_end: 训练期
  - test_start, test_end: 测试期
  - fold_id: 窗格编号

滚动窗格方案C（步长 20 天）:
  W1: 01-01~02-08 (训练) → 02-09~02-28 (测试)
  W2: 01-21~02-28 (训练) → 03-01~03-20 (测试)
  W3: 02-08~03-20 (训练) → 03-21~04-09 (测试)
  W4: 02-28~04-09 (训练) → 04-10~04-29 (测试)
  W5: 03-20~04-29 (训练) → 04-30~05-14 (测试)
```

**产出**: 
- `src/backtest/analysis/walk_forward.py` — WalkForwardFold + WalkForwardRunner

### T2: P4 WalkForwardRunner + 窗格运行

**目标**: 在各窗格上运行训练+测试流程，收集结果数据。

**流程**（各窗格）:
```
for each window:
  1. Load bars for full period
  2. Filter bars to training period
  3. Run GridParamScanner on training period → 找出最优参数组合
  4. Run single backtest with optimal params on training period → 训练期指标
  5. Run single backtest with same params on testing period → 测试期指标
  6. Record: train_sharpe, test_sharpe, WFE, optimal_params
```

### T3-T5: P4 后续分析和报告

后续生成 WFE 汇总和完整报告。

---

## 文件产出清单

| 任务 | 产出文件 |
|:----|:--------|
| T1 | `src/backtest/analysis/walk_forward.py` | ✅ |
| T2 | `data/results/walkforward_601857_C.json` | ✅ |
| T3 | `reports/research/P4_walkforward_601857_20260518.md` | ✅ |
| P3完善 | `reports/research/P3_param_stability_601857_20260518_v2.md` |
| P1完善 | `reports/research/P1_return_decomposition_601857_20260518_v2.md` |
| P2完善 | `reports/research/P2_risk_attribution_601857_20260518.md` |
| P8完善 | `reports/research/P8_benchmark_601857_20260518_v2.md` |
| P5框架 | `reports/research/P5_execution_601857_20260518.md` |

---

## 时间预算

| 阶段 | 工时 | 实际工期 | 截止 |
|:----|:---:|:-------:|:----|
| T1 WalkForward fold | 1.5天 | — | — |
| T2 WalkForward 运行 | 1.0天 | — | — |
| T3 WFE聚合 | 0.5天 | — | — |
| T4 报告展示 | 0.5天 | — | — |
| 其余4b模块 | 5.5天 | — | — |
| **4b 合计** | **10.5天** | 42.7s 实际 | — |

---

## 实际执行记录

| 子任务 | 实际耗时 | 产出文件 |
|:------|:-------:|:--------|
| 读取设计文档 | 1 轮对话 | — |
| 创建执行计划 | 1 轮对话 | `reports/research/phase_4b_execution_plan_20260518.md` |
| `WalkForwardFold` 模型设计 | 1 轮对话 | `src/backtest/analysis/walk_forward.py` |
| `WalkForwardRunner` 框架实现 | 1 轮对话 | 同上 |
| `_run_param_scan` + 数据源接入 | 2 轮对话 + 3次修复 | 同上 |
| 价格边界调试（15%→5%） | 2 轮调试 | `test_bounds.py` |
| ThreadPoolExecutor 修复→max_workers=1 | 1 轮调试 | — |
| 完整运行 5 窗格 × 216 参数组合 | 42.7s | `data/results/walkforward_601857_C.json` |
| 生成 P4 报告 | 1 轮对话 | `reports/research/P4_walkforward_601857_20260518.md` |
| **P4 核心模块合计** | **~10 轮对话, 42.7s 计算** | 3 个产出文件 |

### 遇到的关键问题

1. **ThreadPoolExecutor 崩溃**: `batch_run_grid` 内部使用 `concurrent.futures` 时 `py_mini_racer` (AKShare 依赖) 崩盘。解决方案：`max_workers=1`（序列执行，1,080 次回测仅 42.7s）。
2. **网格价格边界过宽**: 原始 ±15% 导致网格间距 > 价格振幅（0.75 间距 vs 0.5 实际波动），无信号触发。解决方案：改用训练期 min/max ±3% 缓冲，信号正常激活。
3. **W1-W3 无交易**: 测试期仅 8~14 个交易日，价格未跨越网格触发电平。W4-W5 测试期充足时正常交易，WFE 1.0~1.04。
