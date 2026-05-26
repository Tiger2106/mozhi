# R1 架构重构方案 v3（整合版）

> **作者：** 墨衡 (moheng)
> **创建时间：** 2026-05-18 07:50 +08:00
> **版本：** v3.0
> **背景：** 在 v2 基础上，整合《右侧顺势量化研究体系（机构化重构方案 v1.0）》的核心内容：Triple Factor 框架、三种具体研究方法、Execution Simulator、研究归因系统、VWAP/Volume Profile/Trend Quality 因子深度化

---

## 目录

1. [对比分析：附件文件 vs 现有 R1 v2 方案](#1-对比分析附件文件-vs-现有-r1-v2-方案)
2. [整合后的 R1 v3 架构总览](#2-整合后的-r1-v3-架构总览)
3. [分阶段实施计划（v3 整合版）](#3-分阶段实施计划v3-整合版)
4. [新增模块详细设计](#4-新增模块详细设计)
5. [目录结构 v3](#5-目录结构-v3)
6. [范围确认与排除项](#6-范围确认与排除项)
7. [工作量重新评估](#7-工作量重新评估)

---

## 1. 对比分析：附件文件 vs 现有 R1 v2 方案

### 1.1 差异点

| 维度 | R1 v2（现有方案） | 附件文件（右侧顺势量化研究体系） | 差异程度 |
|:----:|:----------------:|:-----------------------------:|:--------:|
| **因子架构** | 五层：数据→指标→因子→信号→执行；因子分为动量/趋势/波动率/超买超卖/量价/换手率六大类 | 三因子：Regime(市场状态) + Volume Flow(资金行为) + Structure(市场结构)，因子层分离出 Trend/Volume/Structure 三个独立子模块 | **补充** — v2 因子分类以技术指标类型划分，附件以市场行为维度划分，可互补 |
| **策略体系** | 三策略（reversal/grid/trend）通过 adapter 统一信号 | 三研究法（breakout_retest/continuation/volume_price_expansion），脱敏为"研究方法" | **互补** — 附件提供的三种 method 是纯右侧顺势交易策略，v2 的 reversal 是左侧，grid 是震荡，三方正好覆盖完整交易谱系 |
| **VWAP 定位** | 未单独强调 VWAP，仅通过量价因子隐含 | VWAP 为核心因子（vwap/vwap_distance/vwap_trend/vwap_support），Anchored VWAP | **新增** — v2 缺失 VWAP 因子族 |
| **Volume Profile** | 未涉及 | POC/Value Area/HVN/LVN，全量价分布分析 | **新增** — v2 无此模块 |
| **Trend Quality** | 趋势评分在因子仓库中有但未模块化 | trend_smoothness/pullback_depth/breakout_efficiency 作为独立因子 | **补充细化** — 可在 v2 趋势评分基础上扩展 |
| **Execution Simulator** | paper_trade 模拟交易，无滑点/流动性/印花税模型 | 专门 Execution Simulator，模拟滑点/流动性/印花税/涨停无法成交 | **新增** — v2 的 paper_trade 不包含这些细节 |
| **研究归因** | 无正式归因系统 | Trade Attribution（按 Regime/时间/标的/市场状态归因）+ Regime Analyzer | **新增** |
| **知识体系** | KnowledgeBridge + BitableSync（知识持久化框架） | Knowledge Types + KnowledgeBridge 回测知识沉淀 | **方向一致** — v2 已有框架，附件提供 Knowledge Types 内容分类 |
| **参数稳定性研究** | 无 | Parameter Surface Analyzer（参数敏感度/平原/鲁棒性） | **新增** — 可作为 P2 任务 |
| **去敏感化** | 未涉及 | 三类策略脱敏为 research methods | **新增意识** — 可在命名层面采纳 |
| **风险模块** | risk_manager + drawdown_guard（已在 codebase 中） | volatility_risk + drawdown_guard + regime filter | **已有** — v2 已有部分实现，附件补充了 regime filter 思路 |

### 1.2 互补点总结

| 附件文件的优势（v2 所无） | v2 的优势（附件所无） |
|:------------------------|:--------------------|
| Triple Factor 市场视角框架（Regime + Volume + Structure） | 五层严格分层架构（数据→指标→因子→信号→执行） |
| 三种纯右侧顺势交易 method | 已有 reversal + grid + trend 完整策略管线 |
| VWAP 因子族（含 Anchored VWAP） | 换手率因子体系（5个因子） |
| Volume Profile 因子族（POC/VA/HVN/LVN） | 端到端集成测试 + 并行验证机制 |
| Execution Simulator（滑点/流动性/印花税/涨跌停） | 红蓝部署渐进式切换方案 |
| Trade Attribution 研究归因系统 | CI 性能基线（pytest-benchmark） |
| Parameter Surface Analyzer | 代码清理 + 归档计划 |
| 知识分类体系（Knowledge Types） | TODO 清单全覆盖 |
| 右侧顺势交易哲学（retest 确认后入场） | BitableSync 持久化链路 |

### 1.3 整合策略

```
v2 的五层架构（基础框架） 
  + 附件的三因子视角（补充因子组织维度）
  + 三种右侧 method（扩展策略库）
  + VWAP/VP/TrendQuality 因子（补充因子维度）
  + Execution Simulator（提升 backtest 真实度）
  + Trade Attribution（增加研究分析能力）
  = R1 v3（完整版）
```

---

## 2. 整合后的 R1 v3 架构总览

### 2.1 架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                        Market Data Layer                         │
│              market_data_adapter.py（纯量价+换手率）              │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      Indicator Engine                            │
│                     indicator_engine.py                           │
│   RSI/KDJ/MACD/MA/BB   │   VWAP因子族   │   Volume Profile       │
│   换手率指标            │   Trend Quality │   缺口检测            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      Factor Repository                           │
│                     factor_repository.py                          │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Regime 维度  │  │ Volume Flow  │  │  Structure 维度      │   │
│  │  (市场状态)   │  │ (资金行为)    │  │ (市场结构)           │   │
│  ├──────────────┤  ├──────────────┤  ├──────────────────────┤   │
│  │ trend_str    │  │ volume_surge │  │ breakout_score       │   │
│  │ volatility   │  │ smart_money  │  │ pullback_quality     │   │
│  │ market_regime│  │ absorption   │  │ trend_channel        │   │
│  │ momentum     │  │ distribution │  │ HH/HL结构            │   │
│  │ vwap偏���     │  │ effort_result│  │ MA排列/宽度          │   │
│  │ ATR范围      │  │ VWAP位置     │  │ 支撑/阻力            │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  VWAP因子族(vwap_distance/vwap_trend/vwap_support)     │      │
│  │  Volume Profile因子族(POC/VA_HIGH/VA_LOW/HVN/LVN)      │      │
│  │  Trend Quality因子族(smoothness/pullback_depth/efficiency)│    │
│  │  换手率因子族(turnover_ratio/ma5/change/rank/corr)     │      │
│  │  动量/趋势/波动率/超买超卖因子族                         │      │
│  └────────────────────────────────────────────────────────┘      │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      Research Methods 层                          │
│                    (研究方法，非策略，去敏感化)                     │
│                                                                   │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ breakout_retest │  │ continuation  │  │ volume_price     │    │
│  │ (突破回踩确认)  │  │ (趋势延续回调) │  │ _expansion       │    │
│  │                 │  │              │  │ (量价爆发)       │    │
│  │ 右侧顺势交易    │  │ 趋势增强回调 │  │ 量价双升模式     │    │
│  └─────────────────┘  └──────────────┘  └──────────────────┘    │
│                                                                   │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ reversal_method │  │ grid_method  │  │ trend_method       │   │
│  │ (原有reversal)  │  │ (原有grid)   │  │ (原有trend跟随)   │   │
│  └─────────────────┘  └──────────────┘  └────────────────────┘   │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      Signal Mapper v2                             │
│                     signal_mapper_v2.py                            │
│   因子评分 → 信号映射（含多Research Method冲突解决）               │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      Position / Risk Engine                       │
│                     position_manager_v2.py                         │
│                     risk_manager + drawdown_guard                  │
│                     volatility_risk (ATR动态仓位)                 │
│                     regime_filter (不同Regime不同策略)            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      Backtest Engine (核心改造)                    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Execution Simulator (新增)                                 │  │
│  │ execution_simulator.py                                     │  │
│  │ • 滑点模拟 (slippage)                                      │  │
│  │ • 流动性匹配 (liquidity)                                   │  │
│  │ • 印花税/交易成本 (tax/fee)                                │  │
│  │ • 涨跌停无法成交 (limit_lock)                              │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Trade Attribution (新增)                                    │  │
│  │ trade_attribution.py                                        │  │
│  │ • 按Regime归因 (regime_contrib)                             │  │
│  │ • 按时间段归因 (time_contrib)                               │  │
│  │ • 按标的归因 (symbol_contrib)                               │  │
│  │ • 按市场状态归因 (state_contrib)                            │  │
│  │ • 归因报告输出 (attribution_report)                         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Regime Analyzer (新增)                                      │  │
│  │ regime_analyzer.py                                          │  │
│  │ • 各Regime下WinRate/Sharpe统计                              │  │
│  │ • 最佳/最差Regime识别                                       │  │
│  │ • Regime切换信号检测                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Parameter Surface Analyzer (新增，P2)                     │  │
│  │ parameter_surface_analyzer.py                              │  │
│  │ • 参数敏感度热力图 (sensitivity_heatmap)                    │  │
│  │ • 参数平原检测 (plateau_detection)                         │  │
│  │ • 鲁棒性评分 (robustness_score)                            │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      KnowledgeBridge (保留，但不修改前端)         │
│                     knowledge_bridge_v2.py                        │
│                     knowledge_types.py (新增知识分类)             │
│                     = 回测结果 → 知识沉淀                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                      Paper Trade / Execution                      │
│                     (统一执行层，沿用 v2)                         │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 v2 → v3 新增模块一览

| 新增模块 | 文件 | 阶段 | 说明 |
|:--------|:----|:----:|:-----|
| VWAP 因子族 | `factor_definitions/vwap_factor.py` | 阶段一 | vwap, vwap_distance, vwap_trend, vwap_support, anchored_vwap |
| Volume Profile 因子族 | `factor_definitions/volume_profile_factor.py` | 阶段一 | poc, value_area_high/low, high_volume_nodes, low_volume_nodes |
| Trend Quality 因子族 | `factor_definitions/trend_quality_factor.py` | 阶段一 | trend_smoothness, pullback_depth, breakout_efficiency, trend_quality_score |
| Regime Analyzer 因子 | `factor_definitions/regime_factor.py` | 阶段一 | trend_strength, volatility_state, market_regime, momentum_state（原有trend评分→扩展） |
| Volume Flow 因子 | `factor_definitions/volume_flow_factor.py` | 阶段一 | volume_surge, smart_money_score, absorption_score, distribution_score, effort_result_ratio（在原有量价因子上扩展） |
| Structure 因子 | `factor_definitions/structure_factor.py` | 阶段一 | breakout_score, pullback_quality, trend_channel, market_structure（新写，整合原有信号逻辑） |
| Three Research Methods | `research_methods/breakout_retest_method.py`, `continuation_method.py`, `volume_price_expansion_method.py` | 阶段二 | 各 method 定义因子评分→信号转换规则 |
| Execution Simulator | `execution/execution_simulator.py` | 阶段二 | 滑点/流动性/印花税/涨跌停模型 |
| Trade Attribution | `research/trade_attribution.py` | 阶段三 | 多维度归因分析 |
| Regime Analyzer | `research/regime_analyzer.py` | 阶段三 | Regime 维度绩效统计 |
| Knowledge Types | `knowledge/knowledge_types.py` | 阶段三 | 知识分类体系（parameter_sensitivity, regime_behavior 等） |
| Parameter Surface Analyzer | `research/parameter_surface_analyzer.py` | **P2** | 参数稳定性研究 |

---

## 3. 分阶段实施计划（v3 整合版）

### 3.1 阶段总览

```
时间轴 →
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ 阶段一 (5h)             阶段二 (7h)               阶段三 (4h)         阶段四 (2h)          │
│ 基础设施 +               │ 指标因子统一 +         │ 统一信号框架 +    │ 清理 + CI +       │
│ 纯量价管道 +             │ TODO-P0/P1 +           │ TODO-P1 +         │ TODO-P2/P3 +      │
│ 新因子族扩展(VWAP/VP/TQ)│ 新Research Method +    │ Execution Sim +   │ 远期准备          │
│                         │ Execution Simulator    │ Trade Attribution  │                    │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 阶段一：基础设施 + 纯量价管道 + 新因子族扩展（约 5 小时）

**核心目标：** 在原 v2 阶段一基础上，同步建设 VWAP/Volume Profile/Trend Quality/Regime/Volume Flow/Structure 六类新因子的计算能力。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R1-01 | `market_data_adapter.py` 纯量价字段完整性确认 + `turnover_rate` 字段读入 | 35min | DDL 更新 + 适配器验证 | — |
| R1-02 | `indicator_engine.py` 换手率指标：`calc_turnover_indicators()` | 20min | 换手率分支 | R1-01 |
| R1-03 | **`vwap_factor.py`（新增）**：vwap, vwap_distance, vwap_trend, vwap_support, anchored_vwap 计算 | 30min | VWAP 因子模块 | R1-01 |
| R1-04 | **`volume_profile_factor.py`（新增）**：POC, Value Area High/Low, HVN, LVN（基于日线/分钟线计算） | 30min | Volume Profile 因子模块 | R1-01 |
| R1-05 | **`trend_quality_factor.py`（新增）**：trend_smoothness, pullback_depth, breakout_efficiency, trend_quality_score | 20min | Trend Quality 因子模块 | R1-01 |
| R1-06 | **`regime_factor.py`（新增）**：trend_strength, volatility_state, market_regime, momentum_state（5 种 state: UPTREND/DOWNTREND/RANGE/BREAKOUT/CLIMAX） | 30min | Regime 因子模块 | R1-01 |
| R1-07 | **`volume_flow_factor.py`（新增）**：volume_surge, smart_money_score, absorption_score, distribution_score, effort_result_ratio | 25min | Volume Flow 因子模块 | R1-01 |
| R1-08 | **`structure_factor.py`（新增）**：breakout_score, pullback_quality, trend_channel, market_structure | 25min | Structure 因子模块 | R1-01 |
| R1-09 | `factor_repository.py` 整合所有新因子族，按 Regime/Volume Flow/Structure 三维度组织 | 20min | 因子仓库 v3 更新 | R1-03→08 |
| R1-10 | 端到端验证：5只标的跑通 量价 → 6族因子 → 因子仓库全链路 | 30min | 验证通过报告 | R1-02→09 |

**阶段一产出：**
- ✅ 纯量价 + 换手率数据链完整可用
- ✅ VWAP / Volume Profile / Trend Quality 因子模块
- ✅ Regime / Volume Flow / Structure 因子模块（三因子框架基础）
- ✅ 因子仓库按三维度组织
- ✅ 端到端 5只标的验证通过
- ✅ BitableSync 运维通道（墨涵并行）

---

### 3.3 阶段二：指标因子统一 + Research Method + Execution Simulator（约 7 小时）

**核心目标：** 在 v2 阶段二基础上，建设三种新的 Research Method 并开始 Execution Simulator 开发。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R2-01 | **延续 v2：** reversal/trend/grid 指标依赖审查 + `factor_calculator.py` 迁移 | 80min | 差异分析报告 + 因子迁移 | R1-10 |
| R2-02 | **延续 v2：** TODO-05→10 集成修复（config_key/import/run_new/KB/Bitable） | 60min | TODO 修复 | R2-01 |
| R2-03 | **`breakout_retest_method.py`（新增）**：条件定义（UPTREND + 突破结构高点 + 量放大 + 回踩VWAP + 再次上攻）+ 退出规则 | 40min | Research Method 1 | R1-10 |
| R2-04 | **`continuation_method.py`（新增）**：强趋势回调入场（趋势中 + ATR控制 + VWAP支撑 + 回调缩量）+ 退出规则 | 30min | Research Method 2 | R1-10 |
| R2-05 | **`volume_price_expansion_method.py`（新增）**：量价双升（price_expansion + volume_expansion + volatility_expansion）+ 退出规则 | 30min | Research Method 3 | R1-10 |
| R2-06 | **`execution_simulator.py`（新增）**：滑点模型（固定比例+动态）+ 流动性匹配 + 印花税 + 涨跌停模拟 | 45min | Execution Simulator 初版 | R2-01 |
| R2-07 | **渐进集成：** 三种 Research Method 因子评分 → `factor_repository.py` signal_rules 注册 | 25min | Rule 注册完成 | R2-03→05 |
| R2-08 | 多 Method+策略 集成测试：reversal + trend + grid + 3 Research Methods = 6个信号源 | 45min | 集成测试通过 | R2-07 |

**阶段二产出：**
- ✅ 所有重复指标/因子迁移完成
- ✅ TODO-05→10 修复
- ✅ 三种 Research Method 可用（因子评分 + 信号规则）
- ✅ Execution Simulator 初版（滑点/流动性/税费/涨跌停）
- ✅ 6个信号源集成测试通过

---

### 3.4 阶段三：统一信号框架 + 研究归因 + Execution Simulator 集成（约 4 小时）

**核心目标：** 在 v2 阶段三基础上，加入 Trade Attribution 和 Regime Analyzer，并将 Execution Simulator 接入回测流程。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R3-01 | **延续 v2：** reversal/trend/grid adapter 信号桥接 + `R1Signal` dataclass 定义 | 60min | 三 adapter + 标准信号 | R2-02 |
| R3-02 | **Research Method adapter（新增）**：三种 method → `signal_mapper_v2.py` 适配层 | 30min | method_adapter 写入 | R2-07 |
| R3-03 | **多信号冲突解决扩展**：6个信号源（3旧策略 + 3 Research Method）冲突裁决，增加 Research Method 置信度权重 | 20min | 冲突解决 v2 | R3-01→02 |
| R3-04 | **Execution Simulator 回测集成**：将 execution_simulator 作为回测引擎后处理层，影响 PnL/胜率计算 | 30min | 回测集成完成 | R2-06 |
| R3-05 | **`trade_attribution.py`（新增）**：按 Regime/时间段/标的/市场状态 4 维度归因 | 40min | 归因系统初版 | R3-04 |
| R3-06 | **`regime_analyzer.py`（新增）**：各 Regime 状态下的 WinRate/Sharpe/最大回撤统计 + 最佳/最差 Regime 标记 | 30min | Regime 分析模块 | R3-05 |
| R3-07 | **`knowledge_types.py`（新增）**：定义 Knowledge Types 枚举（parameter_sensitivity, regime_behavior, trend_quality, volume_behavior, breakout_pattern, risk_event, execution_issue） | 15min | 知识分类 | R3-06 |
| R3-08 | 端到端信号 + 回测 + 归因 + 知识 全链路验证 | 30min | E2E 验证通过 | R3-04→07 |

**阶段三产出：**
- ✅ 6个信号源统一信号输出
- ✅ Execution Simulator 影响回测 PnL
- ✅ Trade Attribution 4 维度归因
- ✅ Regime Analyzer 绩效统计
- ✅ Knowledge Types 分类体系
- ✅ 全链路端到端验证

---

### 3.5 阶段四：归档清理 + CI 增强 + 远期准备（约 2 小时）

**核心目标：** 与 v2 阶段四一致，追加远期准备内容。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R4-01 | **延续 v2：** 旧管线冻结 + 废弃文件归档 | 45min | 归档执行完成 | R3-08 |
| R4-02 | **延续 v2：** CI 性能基线（pytest-benchmark） | 30min | 基线建立 | R4-01 |
| R4-03 | **`parameter_surface_analyzer.py`（新增，P2）**：参数敏感度热力图 + 平原检测 + 鲁棒性评分 | 30min | P2 模块初版 | R3-08 |
| R4-04 | 知识衰减算法预研（P3）+ 统一工作台预研（P3） | 30min | 预研文档 | — |

**阶段四产出：**
- ✅ 旧管线全部冻结
- ✅ 废弃代码安全归档
- ✅ CI 性能基线建立
- ✅ Parameter Surface Analyzer（P2）
- ✅ 知识衰减 + 工作台预研（P3）

---

## 4. 新增模块详细设计

### 4.1 VWAP 因子族（`factor_definitions/vwap_factor.py`）

```python
# v3 新增：VWAP 因子族
class VWAPFactors:
    def __init__(self, df: pd.DataFrame):
        # df 必须包含: date, high, low, close, volume
    
    def calc_vwap(self) -> pd.Series:
        """标准 VWAP = Σ(典型价格 × 成交量) / Σ(成交量)"""
        # typical_price = (high + low + close) / 3
        # vwap = (tp * volume).cumsum() / volume.cumsum()
        pass
    
    def calc_anchored_vwap(self, anchor_date: str) -> pd.Series:
        """Anchored VWAP: 从指定日期开始计算"""
        pass
    
    def calc_vwap_distance(self) -> pd.Series:
        """vwap_distance = (close - vwap) / vwap, 衡量偏离程度"""
        pass
    
    def calc_vwap_trend(self) -> pd.Series:
        """vwap_trend: VWAP 线斜率/方向"""
        pass
    
    def calc_vwap_support(self) -> pd.Series:
        """vwap_support: 价格是否围绕 VWAP 运行（回踩 VWAP 次数/质量）"""
        pass
```

**回测系统集成方式：** 作为 `indicator_engine.py` 的一个 `calc_vwap_factors()` 函数；因子值存入 `factor_repository.py` 的 `vwap_*` 字段。

### 4.2 Volume Profile 因子族（`factor_definitions/volume_profile_factor.py`）

```python
class VolumeProfileFactors:
    def calc_poc(self, df: pd.DataFrame, n_bins: int = 24) -> float:
        """POC = Point of Control = 成交量最大的价格区间"""
        pass
    
    def calc_value_area(self, df: pd.DataFrame, pct: float = 0.70) -> Tuple[float, float]:
        """Value Area = 包含 pct% 成交量的价格区域"""
        pass
    
    def calc_hvn_lvn(self, df: pd.DataFrame) -> Tuple[float, float]:
        """HVN = High Volume Nodes, LVN = Low Volume Nodes"""
        pass
```

**回测系统中触发器：** 在 `indicator_engine.py` 中按日/周计算，适用于日内/日间级别分析。

### 4.3 Trend Quality 因子族（`factor_definitions/trend_quality_factor.py`）

```python
class TrendQualityFactors:
    def calc_trend_smoothness(self, df: pd.DataFrame, period: int = 20) -> float:
        """衡量趋势的平滑程度（回归残差的倒数）"""
        pass
    
    def calc_pullback_depth(self, df: pd.DataFrame, lookback: int = 10) -> float:
        """回调深度：从高点回落的比例，越浅越好"""
        pass
    
    def calc_breakout_efficiency(self, df: pd.DataFrame, lookback: int = 10) -> float:
        """突破效率：突破后 x 日的涨幅与波动率比"""
        pass
    
    def calc_trend_quality_score(self, df: pd.DataFrame) -> float:
        """综合分数（加权三项指标）"""
        pass
```

### 4.4 Regime 因子（`factor_definitions/regime_factor.py`）

```python
class RegimeFactor:
    REGIME_STATES = ["UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX"]
    
    def calc_trend_strength(self, df: pd.DataFrame) -> float:
        """ADX + 均线斜率"""
        pass
    
    def calc_volatility_state(self, df: pd.DataFrame) -> str:
        """ATR 分位数, LOW / NORMAL / HIGH"""
        pass
    
    def calc_market_regime(self, df: pd.DataFrame) -> str:
        """综合判断：方向+波动+结构 → UPTREND/DOWNTREND/RANGE/BREAKOUT/CLIMAX"""
        pass
    
    def calc_momentum_state(self, df: pd.DataFrame) -> float:
        """动量强度评分"""
        pass
```

### 4.5 Execution Simulator（`execution/execution_simulator.py`）

```python
class ExecutionSimulator:
    def __init__(self, config: dict):
        self.slippage_model = config.get("slippage", "fixed")  # fixed / proportional
        self.slippage_rate = config.get("slippage_rate", 0.001)  # 0.1%
        self.liquidity_threshold = config.get("liquidity_threshold", 1000000)  # 成交额阈值
        self.stamp_tax = config.get("stamp_tax", 0.001)  # 印花税（A股 0.1%）
        self.commission = config.get("commission", 0.00025)  # 手续费（万2.5）
    
    def simulate_execution(self, signal: dict, market_data: pd.DataFrame):
        """模拟交易执行，返回实际成交价格和成交状态"""
        result = {}
        result["limit_lock"] = self._check_limit_lock(signal, market_data)
        if result["limit_lock"]:
            result["filled"] = False
            result["filled_price"] = None
        else:
            result["filled_price"] = self._apply_slippage(signal, market_data)
            result["liquidity_penalty"] = self._check_liquidity(signal, market_data)
            result["transaction_cost"] = self._calc_cost(result["filled_price"])
        return result
    
    def _check_limit_lock(self, ...): ...
    def _apply_slippage(self, ...): ...
    def _check_liquidity(self, ...): ...
    def _calc_cost(self, ...): ...
```

### 4.6 Trade Attribution（`research/trade_attribution.py`）

```python
class TradeAttribution:
    def attribute_by_regime(self, trades: List[dict]) -> dict:
        """按市场状态归因：UPTREND下赢率、DOWNTREND下表现等"""
        pass
    
    def attribute_by_time(self, trades: List[dict], periods: List[str]) -> dict:
        """按时间段归因：上午/下午、月初/月末"""
        pass
    
    def attribute_by_symbol(self, trades: List[dict]) -> dict:
        """按标的归因：哪些标的表现好"""
        pass
    
    def attribute_by_state(self, trades: List[dict]) -> dict:
        """按入场时市场状态归因"""
        pass
    
    def generate_attribution_report(self, trades: List[dict]) -> str:
        """生成归因报告"""
        pass
```

### 4.7 Regime Analyzer（`research/regime_analyzer.py`）

```python
class RegimeAnalyzer:
    def analyze(self, trades: List[dict]) -> pd.DataFrame:
        """返回每个 Regime 下的绩效表"""
        return pd.DataFrame({
            "regime": ["UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX"],
            "win_rate": [...],
            "sharpe": [...],
            "max_drawdown": [...],
            "trade_count": [...]
        })
    
    def best_regime(self) -> str: ...
    def worst_regime(self) -> str: ...
    def regime_transition_signals(self) -> List[dict]: ...
```

### 4.8 Research Method 信号规则（三法信号映射）

| Method | 入场条件（因子评分驱动） | 出场条件 | 适用 Regime |
|:------|:----------------------|:---------|:-----------|
| `breakout_retest` | ① Regime=UPTREND ② 结构突破（HH/HL确认）③ 量放大 ≥ MA5*1.5 ④ 回踩VWAP/MA不破 ⑤ 再次上攻 | 跌破入场K线低点 / VWAP失守 | UPTREND, BREAKOUT |
| `continuation` | ① 趋势中（ADX ≥ 25）② 回调深度 ≤ ATR×1.5 ③ VWAP上方 ④ 回调缩量 ≤ MA5*0.7 ⑤ 方向性恢复 | 跌破趋势线 / 反方向突破 | UPTREND, DOWNTREND |
| `volume_price_expansion` | ① 量放大 ≥ MA10*2 ② 价突破前高 ③ 波动率扩张（ATR↑）④ 换手率异常 | 量萎缩 / 价格停滞 | BREAKOUT, UPTREND |

---

## 5. 目录结构 v3

```
quant/
├── factors/
│   ├── trend/
│   │   ├── __init__.py
│   │   ├── regime_factor.py              # [v3新增] 市场状态识别
│   │   └── trend_quality_factor.py       # [v3新增] 趋势质量
│   ├── volume/
│   │   ├── __init__.py
│   │   ├── volume_flow_factor.py         # [v3新增] 资金行为
│   │   ├── volume_profile_factor.py      # [v3新增] 量价分布
│   │   └── vwap_factor.py                # [v3新增] VWAP因子族
│   ├── structure/
│   │   ├── __init__.py
│   │   └── structure_factor.py           # [v3新增] 市场结构
│   └── volatility/                       # 已有
│       └── __init__.py
│
├── research_methods/                     # [v3重构] 从"strategies"脱敏为"methods"
│   ├── __init__.py
│   ├── breakout_retest_method.py         # [v3新增] 突破回踩确认
│   ├── continuation_method.py            # [v3新增] 趋势延续回调
│   ├── volume_price_expansion_method.py  # [v3新增] 量价爆发
│   ├── reversal_method.py                # 原有reversal → 重命名
│   ├── grid_method.py                    # 原有grid → 重命名
│   └── trend_method.py                   # 原有trend → 重命名
│
├── strategies/                           # [v3保留] 原目录，存放method_adapter和组合策略
│   └── ...
│
├── execution/
│   ├── __init__.py
│   ├── execution_simulator.py            # [v3新增] 交易执行模拟
│   └── paper_trade/                      # 已有
│
├── research/
│   ├── __init__.py
│   ├── trade_attribution.py              # [v3新增] 交易归因
│   ├── regime_analyzer.py                # [v3新增] Regime分析
│   ├── parameter_surface_analyzer.py     # [v3新增] 参数稳定性 (P2)
│   └── correlation/                      # 新增目录
│
├── knowledge/
│   ├── __init__.py
│   ├── knowledge_types.py                # [v3新增] 知识分类
│   └── knowledge_bridge_v2.py            # 已有
│
├── backtest/                             # 已有（核心改造点）
│   ├── engine/                           # 回测引擎（集成execution_simulator）
│   ├── runner/                           # 运行器
│   └── results/                          # 结果（含归因数据）
│
├── reports/                              # 已有
├── runners/                              # 已有
└── risk/                                 # 已有（volatility + drawdown + regime filter）
```

### 5.1 去敏感化方案

| 原术语 | v2 术语 | v3 术语 | 理由 |
|:------|:--------|:--------|:-----|
| 策略 (strategy) | strategy | **research method**（研究方法） | 去敏感化，强调研究属性 |
| 交易信号 | signal | research signal | 保持一致 |
| 策略管线 | strategy pipeline | **method pipeline** | 同上 |
| 策略目录 | `strategies/` | **`research_methods/`** + `strategies/` 仍保留适配层 | 渐进迁移 |

> 注：保持向后兼容 —— `strategies/` 目录保留 adapter 层和组合策略，`research_methods/` 存放独立的 method 实现。

---

## 6. 范围确认与排除项

### 6.1 在本方案范围内（R1 只改回测系统）

| 模块 | 处理方式 | 原因 |
|:----|:--------|:-----|
| VWAP 因子族 | ✅ 全部纳入 `indicator_engine` + `factor_repository` | 属于因子计算，回测系统核心功能 |
| Volume Profile 因子族 | ✅ 同上 | 同上 |
| Trend Quality 因子族 | ✅ 同上 | 同上 |
| Regime/Volume Flow/Structure 三因子 | ✅ 纳入 `factor_repository` 新维度 | 改变因子组织方式 |
| 三种 Research Method | ✅ 纳入 `research_methods/` 新目录 | 新增研究管线 |
| Execution Simulator | ✅ 纳入回测引擎后处理层 | 提升回测真实度 |
| Trade Attribution | ✅ 纳�� research/ | 回测结果的后分析 |
| Regime Analyzer | ✅ 纳入 research/ | 同上 |
| Parameter Surface Analyzer | ✅ P2 任务 | 参数稳定性回测分析 |
| Knowledge Types | ✅ 保留 | 作为回测结果 → 知识沉淀的分类体系 |
| 去敏感化：methods 命名 | ✅ 采纳 | 纯术语调整 |

### 6.2 不在本方案范围内（或仅保留不动）

| 模块 | 处理方式 | 原因 |
|:----|:--------|:-----|
| BitableSync 前端改造 | ❌ 不动 | 墨涵运维，不在 R1 代码改造范围 |
| KB 前端（UI）改造 | ❌ 不动 | 主人明确排除 |
| PDF 报告生成改造 | ❌ 不动 | 主人明确排除；ReportBuilder 子模块拆分(v2 TODO-10) 可做，但不扩展 PDF 能力 |
| 飞书群消息自动推送 | ❌ 不动 | 子 agent 不涉及群消息 |
| 实时行情 WebSocket 接入 | ❌ 不动 | 纯回测系统，不改变数据获取方式 |
| 板块/龙虎榜/北向数据 | ❌ 排除 | 主人明确排除可行性顾虑 |

### 6.3 KnowledgeBridge 处理策略

| 行为 | 策略 |
|:----|:-----|
| `knowledge_bridge_v2.py` 状态确认 + 清理 | ✅ 做（v2 TODO-08） |
| `knowledge_types.py` 知识分类 | ✅ 新增 |
| KB 前端 UI/Bitable 展示层 | ❌ 不动 |
| 回测结果→知识沉淀的逻辑 | ✅ 改进（回测归因数据 + Knowledge Types 标签） |

---

## 7. 工作量重新评估

### 7.1 阶段工时汇总（v2 vs v3 对比）

| 阶段 | v2 原始工时 | v3 新增工时 | v3 总计 | 环比变化 |
|:----:|:----------:|:----------:|:-------:|:--------:|
| 阶段一 | 2h | +3h（6个新因子族开发） | **5h** | +150% |
| 阶段二 | 6h | +1h（3 Research Method + Execution Simulator） | **7h** | +17% |
| 阶段三 | 3h | +1h（Trade Attribution + Regime Analyzer + Knowledge Types） | **4h** | +33% |
| 阶段四 | 2h | +0.5h（Parameter Surface Analyzer P2） | **2h** | +25% |
| **合计** | **13h** | **+5.5h** | **≈ 18h** | **+42%** |

### 7.2 各角色工时分配（v3）

| 角色 | 阶段一 | 阶段二 | 阶段三 | 阶段四 | **合计** |
|:----:|:------:|:------:|:------:|:------:|:--------:|
| **墨衡** 🖋️ | 4h | 5.5h | 3.5h | 1.5h | **14.5h** |
| **墨萱** 🧪 | 0.5h | 1h | 0.5h | 0.5h | **2.5h** |
| **墨涵** 🤝 | 0.5h | 0.5h | — | — | **1h** |
| **合计** | **5h** | **7h** | **4h** | **2h** | **≈ 18h** |

### 7.3 里程碑时间线

```
T+0        阶段一开始
├── 墨涵并行: TODO-01→03 (BitableSync)
├── 墨衡主线: R1-01→10 (基础管道 + 6因子族)
T+5h       阶段一完成
T+5.5h     阶段二开始
├── 延续 v2: R2-01→02 TODO修复 + 指标迁移
├── v3新增: R2-03→07 三method + Execution Simulator
T+12.5h    阶段二完成
T+13h      阶段三开始
├── v2延续: R3-01→03 adapter + 信号统一
├── v3新增: R3-04→07 Execution集成 + 归因 + KnowledgeTypes
T+17h      阶段三完成
T+17.5h    阶段四开始（清理 + CI + P2）
T+19.5h    阶段四完成 → 全面验收

总预算：≈ 20h（含 1.5h 缓冲）
◄────────────────────────────────────────────────────────►
```

---

*本方案 v3 由墨衡在 v2 基础上，整合《右侧顺势量化研究体系（机构化重构方案 v1.0）》的核心内容产出。附件文件的 Triple Factor 框架、三种 Research Method、VWAP/Volume Profile/Trend Quality 因子、Execution Simulator、Trade Attribution 均已按 R1 范围（仅改回测系统）纳入分阶段计划。*
