# R1 架构重构方案 v2（整合版）

> **作者：** 墨衡 (moheng)  
> **创建时间：** 2026-05-18 07:20 +08:00  
> **版本：** v2.0  
> **背景：** 整合阶段评审会（2026-05-17）14项TODO + 排除数据源可行性顾虑 → 纯量价换手率可实施路径

---

## 目录

1. [R1 架构概览与核心设计原则](#1-r1-架构概览与核心设计原则)
2. [纯量价 + 换手率可实施路径](#2-纯量价--换手率可实施路径)
3. [整合后的分阶段实施计划](#3-整合后的分阶段实施计划)
4. [工作量重新评估](#4-工作量重新评估)
5. [代码清理计划](#5-代码清理计划)
6. [渐进式改造策略（新旧系统并行方案）](#6-渐进式改造策略新旧系统并行方案)
7. [依赖关系与关键风险](#7-依赖关系与关键风险)

---

## 1. R1 架构概览与核心设计原则

### 1.1 架构目标

R1 架构将当前的多策略分离体系（reversal、grid、trend、bias、KDJ 等各自独立管线）统一为 **"数据层 → 指标层 → 因子层 → 信号层 → 执行层"** 的五层架构，消除策略之间的重复计算和配置碎片化。

### 1.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **数据源统一** | 全部通过 `market_data_adapter.py` 接入，单入口多后端（AKShare/BaoStock/Sina） |
| **指标计算唯一** | 每种指标只在 `indicator_engine.py` 实现一次，所有策略调用同一函数 |
| **因子计算可组合** | `factor_repository.py` 管理所有因子，支持按策略组筛选订阅 |
| **信号统一映射** | `signal_mapper_v2.py` 根据因子评分 + 风险控制输出标准信号格式 |
| **执行层统一** | `signal_trade_executor.py` + `paper_trade/` 统一处理所有交易信号 |
| **冷热分离** | 指标/因子 UPSERT 入库（冷存储），实时信号内存计算（热路径） |

### 1.3 新旧架构对照

| 维度 | 当前（旧系统） | 目标（R1） |
|------|--------------|-----------|
| 策略入口 | 各自独立管线（`run_reversal.py`, `run_trend.py`, `grid_engine.py`） | 统一 `pipeline_connector.py` 调度 |
| 指标计算 | 各策略分别实现或硬编码 | `indicator_engine.py` 统一计算 + UPSERT 入库 |
| 因子逻辑 | 散落在 `factor_calculator.py`（策略目录内）、`reversal_position.py` 等 | `factor_repository.py` 集中管理 |
| 信号格式 | 不一致（reversal 输出 dict, grid 输出 grid_order, 趋势输出 position） | 标准 `Signal` dataclass → `paper_trade/` |
| 仓位管理 | 多套规则（`reversal_position.py`, `trend_position.py`, `grid_engine.py` 各自计算） | `position_manager_v2.py` 统一管理 |
| 配置 | 多份配置分散在各文件 | `config/position_rules.json` + `risk_thresholds_config.json` 集中管理 |

---

## 2. 纯量价 + 换手率可实施路径

> **说明：** 业主明确排除北向资金、龙虎榜、板块数据等数据源可行性顾虑，本方案仅基于纯量价 + 换手率构建因子体系。

### 2.1 支持的数据源维度

| 维度 | 来源 | 数据字段 | 备注 |
|------|------|---------|------|
| **价格** | AKShare/BaoStock | open, high, low, close | 日线/分钟线 |
| **成交量** | AKShare/BaoStock | volume | 日线/分钟线 |
| **换手率** | AKShare/BaoStock | turnover_rate / turnover_rate_f | 日级 |
| **成交额** | AKShare/BaoStock | amount | 辅助 |

### 2.2 基于纯量价的因子体系

```
                              ┌──────────────────────────┐
                              │     市场数据适配器         │
                              │   market_data_adapter.py  │
                              └────────────┬─────────────┘
                                           │
                              ┌────────────▼─────────────┐
                              │     技术指标引擎           │
                              │   indicator_engine.py     │
                              │  ┌────────┬──────────┐   │
                              │  │ RSI/KDJ │ MACD     │   │
                              │  │ MA/BB   │ 趋势评分 │   │
                              │  └────────┴──────────┘   │
                              └────────────┬─────────────┘
                                           │
                              ┌────────────▼─────────────┐
                              │     因子仓库               │
                              │   factor_repository.py    │
                              │  ┌────────────────────┐   │
                              │  │ 动量类(RSI/MACD方向)│   │
                              │  │ 趋势类(MA排列/宽度) │   │
                              │  │ 波动率类(BB/RSI波动)│   │
                              │  │ 超买超卖类(RSI/KDJ) │   │
                              │  │ 量价类(量比/换手率) │   │
                              │  │ 换手率类(换手率变化)│   │
                              │  └────────────────────┘   │
                              └────────────┬─────────────┘
                                           │
                              ┌────────────▼─────────────┐
                              │     信号映射器 v2         │
                              │   signal_mapper_v2.py     │
                              │   因子评分 → 信号映射     │
                              └────────────┬─────────────┘
                                           │
                              ┌────────────▼─────────────┐
                              │     交易执行层             │
                              │   paper_trade/            │
                              └──────────────────────────┘
```

### 2.3 换手率特有因子（新增维度）

在原有的 T3 因子体系基础上，补充换手率维度：

| 因子名 | 计算方式 | 用途 |
|--------|---------|------|
| `turnover_ratio` | 当日换手率（原始） | 活跃度衡量 |
| `turnover_ma5_ratio` | 当日换手率 / 5日均值 | 放量/缩量识别 |
| `turnover_change_1d` | 换手率日环比变化率 | 活跃度突变信号 |
| `turnover_rank_20d` | 20日分位数排名 [0,1] | 相对活跃度 |
| `price_turnover_corr_5d` | 5日价格-换手率相关性 | 价量配合度 |

### 2.4 排除的数据源及替代方案

| 被排除的数据源 | 原有用途 | 纯量价替代方案 |
|-------------|---------|--------------|
| 北向资金 | 外资动向判断 | 用价格-换手率相关性 + 波动率判断资金意图 |
| 龙虎榜 | 主力/游资追踪 | 用换手率异常 + 价格位置超买超卖替代 |
| 板块数据 | 板块轮动 | 用个股相对指数强弱替代（MA排列 vs 指数MA排列） |

---

## 3. 整合后的分阶段实施计划

### 3.1 阶段总览

```
时间轴 →
┌─────────────────────────────────────────────────────────────────────────────┐
│ 阶段一 (4h)      阶段二 (6h)       阶段三 (3h)      阶段四 (2h)            │
│ 基础设施 +       │ 指标因子统一      │ 统一信号框架     │ 清理 + 并行验证    │
│ 纯量价管道       │ + TODO-P0/P1    │ + TODO-P1      │ + TODO-P2/P3      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 阶段一：基础设施与纯量价管道（约 4 小时）

**核心目标：** 构建统一的数据接入层 + 指标因子计算能力，确保纯量价+换手率数据链完整。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R1-01 | 确认 `market_data_adapter.py` 对纯量价数据（O/H/L/C/Vol/Amt）的字段完整性，在 DDL 中加入 `turnover_rate` 字段 | 20min | DDL 更新 + 适配器验证 | — |
| R1-02 | `market_data_adapter.py` 增加换手率 `turnover_rate` 字段的读入和校验（AKShare `stock_zh_a_hist` API 直接支持） | 15min | 适配器 `_validate_fields()` 更新 | R1-01 |
| R1-03 | `validation_config.py` 新增换手率字段的校验规则（必填 + 范围 `[0, 100]`） | 10min | `validation_config.py` 更新 | R1-02 |
| R1-04 | `indicator_engine.py` 检查当前 RSI/KDJ/MACD/MA/BB 实现，确认与 `data_source_adapter.py` 的对接方式 | 15min | 指标引擎适配确认 | R1-01 |
| R1-05 | `indicator_engine.py` 增加 `calc_turnover_indicators()` 函数：turnover_ma5, turnover_std20, turnover_rank20 | 20min | 指标引擎换手率分支 | R1-03 |
| R1-06 | `factor_repository.py` 增加纯量价+换手率因子组：
 • `turnover_ratio` / `turnover_ma5_ratio` / `turnover_change_1d` / `turnover_rank_20d` / `price_turnover_corr_5d`
 • `volume_ratio` 优化（当前已是5日均量比，增加3日/10日选项）
 • 原有动量/趋势/波动率/超买超卖因子审核去重 | 25min | 因子仓库 v2 更新 | R1-05 |
| R1-07 | 端到端数据验证：5只标的跑通 量价 → 指标 → 因子 全链路 | 20min | 验证通过报告 | R1-04→06 |

**本阶段整合的 TODO 项：**

| TODO | 关联模块 | 在本阶段的位置 | 处理方式 |
|:----:|:--------|:--------------:|:--------|
| TODO-01 | BitableSync | 前置运维 | 墨涵配置，不影响代码开发，本阶段并行完成 |
| TODO-02 | BitableSync | 前置运维 | 同 TODO-01，墨涵完成 |
| TODO-03 | BitableSync | 前置运维 | 同 TODO-01，墨涵完成 |
| TODO-04 | BitableSync | R1-07 验证后 | **墨衡**运行 `e2e_bitable_sync.py` 确认生产写入 |

#### P0 前置依赖（BitableSync 运维配置）

```
▸ 任务：打通 Bitable 写入通道（知识库持久化链路的前置条件）
▸ 执行方式：与 R1-01 到 R1-06 并行进行
▸ 流程：
  墨涵:
  ┌─ TODO-01: 飞书开发者后台开通 bitable:bitable 权限 ─────┐
  ├─ TODO-02: 飞书工作台创建目标 Bitable 表 ──────────────┤
  ├─ TODO-03: 配置 .env.bitable（BITABLE_APP_TOKEN + BITABLE_TABLE_ID）─┤
  墨衡:
  └─ TODO-04: R1-07 验证后运行 e2e_bitable_sync.py 确认 ──┘
```

**阶段一产出：**
- ✅ 纯量价 + 换手率数据链完整可用
- ✅ 指标引擎 + 因子仓库包含换手率维度
- ✅ 端到端 5只标的验证通过
- ✅ BitableSync 运维通道可用（墨涵+墨衡）

---

### 3.3 阶段二：指标因子统一 + 遗留TODO集成（约 6 小时）

**核心目标：** 将散落在各策略中的重复指标/因子逻辑迁移到 `indicator_engine.py` + `factor_repository.py`，消除重复代码，修复已知技术债。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R2-01 | **reversal 策略指标依赖审查**：检查 `run_reversal.py` → `signal_bridge.py` → `reversal_strategy.py` 的 RSI/MACD/ATR 计算，确认是否与 `indicator_engine.py` 重复或可替换 | 30min | 差异分析报告 | R1-07 |
| R2-02 | **trend 策略指标依赖审查**：检查 `run_trend.py` → `trend_strategy.py` → `trend_position.py` 的 MA/MACD/ATR 计算 | 30min | 差异分析报告 | R1-07 |
| R2-03 | **grid 策略指标依赖审查**：检查 `grid_engine.py` 的 BB/MA 计算，确认与 BB_width/bollinger 实现是否一致 | 20min | 差异分析报告 | R1-07 |
| R2-04 | **factor_calculator.py（策略内）因子迁移**：将策略目录下的 `strategies/factor_calculator.py` 中未在 `factor_repository.py` 中存在的因子移至统一仓库 | 30min | 统一因子仓库完成 | R2-01→03 |
| R2-05 | **`indicator_engine.py` 添加缺口检测因子**：gap_day_up/down/before（当前仅在 T3.4 规划中，但无实现） | 20min | 缺口检测功能 | R1-04 |
| R2-06 | **`factor_repository.py` 添加 quality_score 防数据污染**（TODO-11） | 15min | quality_score 逻辑 | R2-04 |
| R2-07 | **`run_reversal.py` config_key 统一为 `_build_config_key()`**（TODO-05，回测插件） | 20min | run_reversal.py 重构 | R2-01 |
| R2-08 | **清理 runner 中旧 import 路径**（`backtest_engine` 残留）（TODO-06，回测插件） | 15min | import 路径清理 | R2-02 |
| R2-09 | **deprecated `run_new()` 物理删除**（TODO-07，回测插件） | 10min | 代码删除 | R2-07 |
| R2-10 | **`knowledge_bridge_v2.py` 文件状态确认与清理**（TODO-08，KB前端） | 15min | KB 清理确认 | R1-04→06 |
| R2-11 | **`signal_mapper_v2.py` 适配统一因子输出格式**：确保新因子仓库的输出能被 v2 信号映射器消费 | 30min | signal_mapper_v2 适配完成 | R2-04 |
| R2-12 | **多策略并行集成测试**：reversal/trend 各 3 种场景，结果与旧系统对照 | 45min | 集成测试通过 | R2-11 |

**本阶段整合的 TODO 项：**

| TODO | 优先级 | 状态 | 具体任务 |
|:----:|:------:|:----:|:---------|
| TODO-05 | P1 | ✅ 集成到 R2-07 | `run_reversal.py` config_key 统一为 `_build_config_key()` |
| TODO-06 | P1 | ✅ 集成到 R2-08 | 清理 runner 旧 import 路径 |
| TODO-07 | P1 | ✅ 集成到 R2-09 | `run_new()` 物理删除 |
| TODO-08 | P1 | ✅ 集成到 R2-10 | `knowledge_bridge_v2.py` 状态确认与清理 |
| TODO-10 | P1 | ⏳ 排入 R2-13 | ReportBuilder 60KB 按章节拆分子模块（PDF报告） |
| TODO-11 | P2 | ✅ 集成到 R2-06 | quality_score 防数据污染 |
| TODO-09 | P1 | ⏳ 排入 R2-14 | Token 自动续期真实环境测试（BitableSync） |

| R2-13 | **ReportBuilder 60KB 按章节拆分子模块**（TODO-10，PDF报告） | 30min | 子模块拆分 | R2-11 |
| R2-14 | **Token 自动续期真实环境测试**（TODO-09，BitableSync） | 15min | 续期测试通过 | TODO-04 |

**阶段二产出：**
- ✅ 所有重复指标/因子迁移完成
- ✅ `run_reversal.py` + runner import 清理完成
- ✅ `run_new()` 物理删除
- ✅ `knowledge_bridge_v2.py` 状态确认
- ✅ quality_score 防污染逻辑
- ✅ ReportBuilder 子模块拆分
- ✅ BitableSync Token 续期测试通过
- ✅ 多策略并行集成测试通过

---

### 3.4 阶段三：统一信号框架 + 策略解耦（约 3 小时）

**核心目标：** 将现有策略（reversal/grid/trend）的信号输出统一到 `signal_mapper_v2.py`，实现 **策略 → 信号** 的解耦，使任意策略组合可以生成统一信号。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R3-01 | **reversal 信号桥接**：实现 `reversal_strategy.py` → `signal_mapper_v2.py` 的信号转换适配层，保留 `ReversalBacktestConfig` 参数，输出标准信号 | 40min | `reversal_adapter.py` | R2-11 |
| R3-02 | **trend 信号桥接**：`trend_strategy.py` → `signal_mapper_v2.py` 信号转换适配层 | 40min | `trend_adapter.py` | R2-11 |
| R3-03 | **grid 信号桥接**：`grid_engine.py` → `signal_mapper_v2.py` 信号转换适配层 | 30min | `grid_adapter.py` | R2-11 |
| R3-04 | **统一信号格式定义**：在 `signal_mapper_v2.py` 中定义标准 `R1Signal` dataclass（包含 action/confidence/price/quantity/reason/source_strategy），确保所有适配层输出相同格式 | 20min | `R1Signal` dataclass | R3-01 |
| R3-05 | **多信号冲突解决**：多个策略同时产生信号时，`signal_mapper_v2.py` 根据置信度 + 风险评分裁决最终信号，接入 `risk_manager.py` 风控检查 | 30min | 冲突解决逻辑 | R3-04 |
| R3-06 | **端到端信号验证**：3种策略同时运行，信号通过统一管道进入 `paper_trade/` 执行 | 30min | E2E 验证通过 | R3-05 |

**本阶段不涉及 TODO 项（所有 TODO 已在阶段一、二处理完成）。**

**阶段三产出：**
- ✅ reversal/trend/grid 三策略统一信号输出
- ✅ 标准 `R1Signal` dataclass 定义
- ✅ 多信号冲突解决逻辑
- ✅ 端到端信号执行验证

---

### 3.5 阶段四：归档清理 + CI 增强 + 远期准备（约 2 小时）

**核心目标：** 安全地弃用旧代码路径，建立 CI 性能基线，为远期架构演进做准备。

| 序号 | 任务 | 时长 | 产出 | 依赖 |
|:----:|------|:----:|------|:----:|
| R4-01 | **旧 reversal 管线冻结**：将 `backtest_engine/strategies/run_reversal.py` 标记为 DEPRECATED，所有新信号必须通过 `reversal_adapter.py` 输出 | 15min | 管线冻结标记 | R3-01 |
| R4-02 | **旧 trend 管线冻结**：`backtest_engine/strategies/run_trend.py` 标记 DEPRECATED | 15min | 管线冻结标记 | R3-02 |
| R4-03 | **旧 grid 引擎冻结**：`grid_engine.py` 标记 DEPRECATED，调用入口增加警告日志 | 15min | 引擎冻结标记 | R3-03 |
| R4-04 | **废弃文件归档**（详见 §5 代码清理计划） | 30min | 归档执行完成 | R4-01→03 |
| R4-05 | **CI 性能趋势分析**（TODO-12，pytest-benchmark） | 30min | pytest-benchmark 配置 + 首次基线 | R4-04 |
| R4-06 | **知识衰减算法预研**（TODO-13，KB，P3） | 20min | 衰减设计文档初稿 | — |
| R4-07 | **投研分析师统一工作台界面设计预研**（TODO-14，平台，P3） | 15min | 界面草图 + PRD 初稿 | — |

**本阶段整合的 TODO 项：**

| TODO | 优先级 | 状态 | 具体任务 |
|:----:|:------:|:----:|:---------|
| TODO-12 | P2 | ✅ R4-05 | CI 性能趋势分析（pytest-benchmark） |
| TODO-13 | P3 | ✅ R4-06 | 知识衰减算法预研（≥2000条触发） |
| TODO-14 | P3 | ✅ R4-07 | 投研分析师统一工作台界面设计预研 |

**阶段四产出：**
- ✅ 旧管线全部冻结，新 R1 信号框架全面接管
- ✅ 废弃代码安全归档
- ✅ CI 性能基线首次建立
- ✅ P3 远期预研文档完成

---

## 4. 工作量重新评估

### 4.1 阶段工时汇总

| 阶段 | 工作内容 | 纯开发工时 | TODO 附加工时 | 小时合计 |
|:----:|---------|:--------:|:------------:|:--------:|
| **阶段一** | 基础设施 + 纯量价管道 | 105min | ~15min (TODO-04) | **≈ 2h** |
| **阶段二** | 指标因子统一 + 历史TODO修复 | 200min | ~125min (TODO-05→11) | **≈ 6h** |
| **阶段三** | 统一信号框架 + 策略解耦 | 160min | — | **≈ 3h** |
| **阶段四** | 归档清理 + CI增强 + 远期准备 | 80min | ~65min (TODO-12→14) | **≈ 2h** |
| **合计** | | **≈ 9h** | **≈ 3.5h** | **≈ 13h** |

### 4.2 各角色工时分配

| 角色 | 阶段一 | 阶段二 | 阶段三 | 阶段四 | **合计** |
|:----:|:------:|:------:|:------:|:------:|:--------:|
| **墨衡** 🖋️ | 1.5h | 4h | 3h | 1.5h | **10h** |
| **墨萱** 🧪 | 0.5h | 1h | 0.5h | 0.5h | **2.5h** |
| **墨涵** 🤝 | 0.5h | 0.5h | — | — | **1h** |
| **玄知** 📡 | — | — | — | — | **0h** |
| **合计** | **2.5h** | **5.5h** | **3.5h** | **2h** | **≈ 13h** |

### 4.3 里程碑时间线

```
T+0       阶段一开始
├── TODO-01→03 (墨涵并行) ─────────────────────────────┐
├── R1-01→06 (墨衡主线)                                  │
T+2h      阶段一完成 ──── TODO-04 (墨衡验证) ────────────┤
T+2.5h    阶段二开始                                      │
├── TODO-05→11 逐个修复                                  │
├── R2-01→14 指标因子迁移                                │
T+8.5h    阶段二完成                                      │
T+9h      阶段三开始 ──── 信号统一                        │
T+12h     阶段三完成                                      │
T+12.5h   阶段四开始 ──── 清理归档 + CI + 预研            │
T+14.5h   阶段四完成 ──── 全面验收                         │
                                                         │
总预算：≈ 15h（含 2h 缓冲）                              │
◄─────────────────────────────────────────────────────────►
```

---

## 5. 代码清理计划

### 5.1 清理原则

| 原则 | 说明 |
|:----|:----|
| **冻结 > 删除** | 先设置 DEPRECATED 标记并增加警告日志，确保下游无调用方后再物理删除 |
| **归档 > 丢弃** | 所有废弃代码移至 `mozhi_share_lib/archive/YYYYMMDD_r1_cleanup/`，保留 90 天 |
| **先查引用，后操作** | 每次清理前运行 `grep -r "模块名" .` 确认无依赖 |
| **分批执行** | 按阶段分 4 批清理，每批有回滚计划 |

### 5.2 批次清理计划

#### 批次 A（阶段一结束后 — 轻度清理）

| 文件 | 操作 | 检查条件 |
|:----|:----|:--------|
| `backtest_engine/strategies/factor_calculator.py` | **冻结** + 日志警告 | 确认 `factor_repository.py` 已覆盖所有因子 |
| `backtest_engine/strategies/optimize_reversal_params.py` | 保留（可能后续用于回测工具库） | — |

#### 批次 B（阶段二中途中 — 历史TODO清理）

| 文件 | 操作 | 依据 |
|:----|:----|:-----|
| `backtest_engine/strategies/run_reversal.py` | 重构 `config_key` 逻辑 | TODO-05 |
| 涉及旧 `backtest_engine` import 路径的 runner 文件 | 更新 import 路径 | TODO-06 |
| 任何模块中残留的 `run_new()` 方法 | 物理删除 | TODO-07 |
| `knowledge_bridge_v2.py` | 确认状态后移除或冻结 | TODO-08 |

#### 批次 C（阶段三完成后 — 核心清理）

| 文件 | 操作 | 检查条件 |
|:----|:----|:--------|
| `backtest_engine/strategies/run_reversal.py` | **废止** → **归档** | 所有 reversal 信号已通过 `reversal_adapter.py` |
| `backtest_engine/strategies/run_trend.py` | **废止** → **归档** | 所有 trend 信号已通过 `trend_adapter.py` |
| `automation_v2/phase1_core/grid_engine.py` | **废止** → **归档** | 所有 grid 信号已通过 `grid_adapter.py` |
| `backtest_engine/strategies/reversal_strategy.py` | **归档** | 标志位检测通过 |
| `backtest_engine/strategies/trend_strategy.py` | **归档** | 标志位检测通过 |
| `backtest_engine/strategies/reversal_position.py` | **归档** | `position_manager_v2.py` 已接管 |
| `backtest_engine/strategies/trend_position.py` | **归档** | `position_manager_v2.py` 已接管 |
| `backtest_engine/strategies/factor_calculator.py` | 确认已无引用 → **归档** | — |

#### 批次 D（阶段四 — 尾料清理）

| 文件 | 操作 | 依据 |
|:----|:----|:-----|
| `automation_v2/phase1_core/valuation_config.py.bak` | 确认无耗时删除 | 备份文件 |
| `automation_v2/phase1_core/signal_trade_executor.py.bak` | 确认无耗时删除 | 备份文件 |
| `backtest_engine/signal_bridge.py` | 检查 | 如果已被 `signal_mapper_v2.py` 完全替代 → **归档** |
| 所有标记为 DEPRECATED 的文件 | 确认无引用 → **归档** | — |
| 创建归档清单：`archive/manifest_r1_cleanup_20260518.csv` | 记录每文件操作日期、去向、原因 | — |

### 5.3 归档操作流程

```python
# 归档示例（伪代码）
def archive_file(src_path: str, reason: str):
    archive_root = "C:/Users/17699/mo_zhi_sharereposits/archive/r1_cleanup_20260518"
    dest = os.path.join(archive_root, os.path.relpath(src_path, base_dir))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(src_path, dest)  # 仅移动，非删除
    
    # 在源位置放一个跳转文件
    with open(src_path + ".redirect", "w") as f:
        f.write(f"Archived to: {dest}\n")
        f.write(f"Reason: {reason}\n")
        f.write(f"Date: 2026-05-18\n")

# 保留期：90天
# 90天后通过清理脚本自动删除：
# python scripts/cleanup_old_archives.py --older-than 90
```

### 5.4 回滚预案

| 回滚场景 | 操作 |
|---------|------|
| 某归档文件被意外调用 | 从 archive 目录还原 `shutil.move` 回源位置 |
| `direct` 跳转文件不影响 Git | `git checkout` 恢复即可 |
| 多策略同时新信号异常 | 回退信号适配层 → 临时启用 `run_reversal.py` 旧管线 |

---

## 6. 渐进式改造策略（新旧系统并行方案）

### 6.1 并行架构设计

```
                     ┌──────────────────────────┐
                     │    pipeline_connector.py  │
                     │     (统一调度器 v2)        │
                     └────────────┬─────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ 旧系统管线        │   │ R1新系统          │   │ 并行验证层        │
│ (DEPRECATED)     │   │ (DOUBLE_CHECK)    │   │                  │
│                  │   │                  │   │                  │
│ run_reversal.py  │   │ signal_mapper_v2 │   │ 信号对比检查器    │
│ run_trend.py     │   │ indicator_engine │   │ ✓ 偏差 >5% 告警  │
│ grid_engine.py   │   │ factor_repository│   │ ✓ 偏差 >10% 阻断 │
│                  │   │ adapter层        │   │                  │
│ ▸ 原始输出       │   │ ▸ 标准化信号输出  │   │ ▸ 生成对比报告    │
│ ▸ 格式不一致     │   │ ▸ 统一格式        │   │                  │
└──────────────────┘   └──────────────────┘   └──────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │    paper_trade/执行层     │
                    │   (最终消费端)            │
                    └──────────────────────────┘
```

### 6.2 并行验证机制

**核心逻辑：旧系统输出 + R1 输出 → 并行比较 → 只有一致或 R1 优于旧时切换到 R1。**

| 阶段 | 并行模式 | 信号路由 |
|:----:|:--------|:---------|
| **阶段一** | 纯量价管道并行 | R1 管道只做数据计算验证，不输出交易信号 |
| **阶段二** | 指标因子并行比对 | R1 和旧策略各自计算指标，结果写入 `signals/consensus/comparison/` 进行逐项比对，偏差容忍 ≤ 3% |
| **阶段三** | 信号并行输出（双路） | R1 和旧策略同时输出信号到 `paper_trade/`，但只有旧信号 → 执行层。R1 信号写入比较日志 |
| **阶段四** | 信号切换（全量验证通过后） | 删除并行层，R1 信号完全接管，旧管线关闭 |

### 6.3 并行验证参数

```python
# 并行验证配置
PARALLEL_VALIDATION_CONFIG = {
    "comparison_threshold": {
        "rsi": 0.5,      # RSI偏差容忍±0.5
        "kdj": 1.0,      # KDJ偏差容忍±1.0
        "macd": 0.3,     # MACD偏差容忍±0.3%
        "ma": 0.1,       # MA偏差容忍±0.1%
        "factor": 0.05,  # 因子值偏差容忍±5%
        "signal": 0.1,   # 信号偏差容忍±10%
    },
    "auto_failover": True,   # 连续5次超过阈值触发自动回滚
    "log_path": "signals/consensus/r1_comparison_metrics.json",
    "enable_visual_diff": True,  # 生成对比图表
}

# 信号切换条件
SWITCH_CONDITIONS = {
    "min_parallel_days": 5,       # 至少并行运行5个交易日
    "max_deviation_rate": 0.03,   # 最大日均偏差率≤3%
    "max_anomaly_days": 1,        # 最多允许1天异常
    "paper_trade_pnl_comparison": True,  # 模拟盘收益对比
}
```

### 6.4 回退保护机制

| 异常场景 | 触发条件 | 自动恢复动作 |
|---------|---------|------------|
| R1 信号与旧系统持续偏离 | 连续 3 次偏离 > 5% | 自动切换到旧管线，R1 进入调试模式 |
| R1 输出空信号（数据异常） | 连续 5 分钟无有效信号 | 回退到旧管线 |
| paper_trade PnL 异常 | R1 信号 PnL 连续 2 天低于旧信号 10% | 标记 R1 信号为测试模式，仅记录不执行 |
| 指标计算超时 | R1 单标的计算 > 3 秒 | 降低并行度，临时关闭 R1 计算 |

### 6.5 切换流程（红蓝部署模式）

```
Step 1: 并行阶段 ── 旧信号 → paper_trade 执行
                    R1信号 → 比较日志 (只记录不执行)

Step 2: 验证通过 ── 双方偏差 < 3%，连续 5 天
                    发飞书通知："R1 信号验证稳定，请确认切换？"
                    等待人工确认 or 超时自动推进

Step 3: 逐步切换 ── Day 1: 30% R1信号 + 70% 旧信号
                    Day 2: 50% R1信号 + 50% 旧信号
                    Day 3: 80% R1信号 + 20% 旧信号
                    Day 4: 100% R1信号 (旧管线只保留fallback)

Step 4: 全面接管 ── 旧管线归档，R1作为默认信号源
                    保留旧管线DEPRECATED标记90天用于紧急回滚
```

---

## 7. 依赖关系与关键风险

### 7.1 关键依赖关系图

```
TODO-01→03 (墨涵外置)
    ↓
TODO-04 (墨衡验证)
    ↓
阶段一 (R1-01→07)  ←── 纯量价管道建立
    ↓
阶段二 (R2-01→14)  ←── TODO-05→11 集成修复
    ↓
阶段三 (R3-01→06)  ←── 信号统一框架
    ↓
阶段四 (R4-01→07)  ←── TODO-12→14 清理 + 预研
```

### 7.2 风险清单

| 编号 | 风险 | 概率 | 影响 | 缓解措施 |
|:----:|------|:----:|:----:|:--------|
| R01 | 换手率字段在 AKShare 部分标的为空 | 中 | 因子计算中断 | factor_repository 设置缺省值，标记为 unavailable |
| R02 | `indicator_engine.py` 与旧策略实现有精度差异 | 低 | 信号偏差 | 阶段二建立自动比对机制 tolerances ≤ 3% |
| R03 | 多策略同时信号冲突 | 中 | 交易逻辑混乱 | 阶段三冲突解决模块按置信度 + 风险评分裁决 |
| R04 | 旧管线归档后发现仍有引用 | 中 | 运行时异常 | 归档时保留 `.redirect` 跳转文件和 `grep` 检查 |
| R05 | BitableSync Token 续期失败 | 低 | KB 持久化中断 | 增加 fallback 本地文件存储 |

### 7.3 关键决策记录

| 决策 | 结论 | 依据 |
|:----|:----|:-----|
| 排除的数据源替代方案 | 纯量价+换手率替代龙虎榜/北向/板块 | 主人明确排除可行性顾虑 |
| TODO 整合方式 | 插入对应模块的任务流，不独立成线 | 减少上下文切换，降低管理成本 |
| 旧系统删除策略 | 先冻结 → 并行验证 → 再归档 | 确保无引用且新系统稳定后再清理 |
| 切换模式 | 红蓝部署渐进式（30%→50%→80%→100%） | 最小化业务中断风险 |

---

*本方案由墨衡基于代码审计 + 阶段评审会TODO清单 + 纯量价约束条件综合产出*
