# 报告升级 V2 设计方案：从"指标回测报告"到"研究型量化分析系统"

> **作者**: 墨衡 (moheng)
> **版本**: v1.0
> **创建时间**: 2026-05-18T16:10:00+08:00
> **评审状态**: 待评审
> **关联文件**:
>   - V2 反馈文件: `incoming/2605181545研究型量化分析报告V2.txt`
>   - 评估报告: `reports/backtest/report_v2_evaluation_20260518.md`
>   - 修改后报告 V2: `reports/backtest/backtest_report_20260518_research_v2.md`

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [6大改进章节详细设计](#2-6大改进章节详细设计)
3. ["伪研究"修正方案](#3-伪研究修正方案)
4. [四层报告结构（总结）](#4-四层报告结构总结)
5. [实施路线](#5-实施路线)
6. [文件结构（路径规划）](#6-文件结构路径规划)

---

## 1. 背景与目标

### 1.1 为什么需要报告升级

当前系统已完成了从"纯收益回测"到"多维分析"的初步进化。修改后报告 V2 实现了：

- Layer 1 结果层（收益、夏普、回撤）
- Layer 2 行为层（交易行为、趋势质量、因子观测）
- Layer 3 结构层（Regime、风控、成交量、假突破）
- Layer 4 研究层（KnowledgeBridge 知识提炼）

但核心问题在于：**报告填充了信息，但没有填充证据**。

| 维度 | 当前状态 | 目标状态 |
|------|----------|----------|
| 数据基础 | 84 天，1 笔成交 | 多标的 × 多周期 ≥ 200 笔样本 |
| 统计支撑 | 无分布信息，结论基于单点 | 全信号分布 + 条件收益矩阵 |
| 研究深度 | 案例分析为主 | 统计研究 + 可检验假设 |
| 自动化程度 | 人工标注占比高 | 事件采集 → 自动化统计 → 报告生成 |
| 扩展性 | 单标的单策略 | 多标的 × 多周期 × 多策略 |

### 1.2 目标：L3 级研究型报告

- **L1（基础回测）**：收益指标 + 净值曲线 — ✅ 已完成
- **L2（结构化分析）**：Regime + 风控 + 成交结构 — ✅ 已完成（V2）
- **L3（研究型）**：信号分布 + 条件收益 + 衰减曲线 + 趋势生命周期 — 🚧 本方案

**核心转变**：

```
"这一笔赚了多少"  →  "在什么条件下，系统整体表现如何"
    案例研究             统计研究（Evidence-based）
```

---

## 2. 6大改进章节详细设计

### 2.1 Signal Distribution Analysis（信号分布分析）

**优先级**: P0 | **预估工作量**: 3~5 人天

#### 功能描述

建立信号的全链路统计体系，覆盖从信号产生到最终成交的完整生命周期：

**输出内容 A — 信号过滤链路漏斗**:

| 项目 | 统计值 | 数据来源 |
|:----|:------|:--------|
| 总信号数 | N_total | signal_events 表 |
| 被 MarketStateFilter 过滤 | N_filtered_market | signal_events.filters.MarketStateFilter |
| 被冷却期拒绝 | N_filtered_cooldown | signal_events.filters.CoolingPeriod |
| 被 DrawdownGuard 阻断 | N_filtered_drawdown | signal_events.filters.DrawdownGuard |
| 通过全部过滤器 | N_passed | — |
| 实际成交信号 | N_executed | Trade 日志 |
| 全局过滤率 | (N_total - N_executed) / N_total | 计算 |

**输出内容 B — 信号置信度分桶统计**:

| 分数区间 | 信号数量 | 成交数 | 胜率 | 平均收益 |
|:-------:|:-------:|:-----:|:---:|:--------:|
| 0.9~1.0 | — | — | — | — |
| 0.8~0.9 | — | — | — | — |
| 0.7~0.8 | — | — | — | — |
| <0.7 | — | — | — | — |

**输出内容 C — 过滤器触发频率热图**:

```
MarketStateFilter  | ###### (65次)
CoolingPeriod      | ### (28次)
DrawdownGuard      | # (4次)
VolatilityRiskMgr  | (0次)
```

#### 数据依赖

| 需要的数据 | 当前系统状态 | 新增采集点 |
|:---------|:-----------|:----------|
| 信号产生事件（每次策略判定） | ❌ 未记录 | `signal_events` 表（新增） |
| 每个信号经过的过滤器链日志 | ❌ 未记录 | 各过滤器的 `record_event()` 方法 |
| SignalFusion 置信度分数 | ⚠️ 内部有，未持久化 | 信号事件中记录 fusion_score |
| 成交/未成交的最终结果 | ✅ 已有 Trades 日志 | 补充到 signal_events |

**数据结构定义**:

```json
{
  "event_id": "sig_{seq}",
  "timestamp": "2026-01-22T09:30:00",
  "symbol": "601857",
  "signal_type": "grid_trigger",
  "fusion_score": 0.85,
  "filters": {
    "MarketStateFilter": {"status": "pass", "reason": null},
    "CoolingPeriod": {"status": "pass", "reason": null},
    "DrawdownGuard": {"status": "pass", "reason": null}
  },
  "final_decision": "executed",
  "executed_price": 10.16,
  "executed_qty": 200
}
```

#### signal_events 表架构设计

```sql
CREATE TABLE signal_events (
    event_id        TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    strategy_id     TEXT NOT NULL,
    signal_type     TEXT NOT NULL,        -- 'grid_trigger', 'breakout', 'volume_signal'
    fusion_score    REAL,                 -- [0, 1], SignalFusion 加权分数
    filters_json    TEXT,                 -- JSON: 各过滤器状态
    final_decision  TEXT NOT NULL,        -- 'executed', 'filtered', 'confidence_low'
    executed_price  REAL,
    executed_qty    INTEGER,
    regime_at_time  TEXT,                 -- 信号产生时的 Regime 状态
    batch_id        TEXT                  -- 回测批号，用于关联
);
CREATE INDEX idx_signal_events_symbol ON signal_events(symbol);
CREATE INDEX idx_signal_events_timestamp ON signal_events(timestamp);
CREATE INDEX idx_signal_events_strategy ON signal_events(strategy_id);
```

#### 回测引擎事件钩子接口设计

当前回测引擎没有事件钩子机制，无法在关键执行节点触发回调。需要为引擎增加**事件钩子系统**，使 signal_events 采集、过滤器日志等模块能正确接入，而无需直接耦合侵入引擎核心逻辑。

##### 所需钩子点定义

| 钩子点标识 | 触发时机 | 传入参数 | 预期用途 |
|:----------|:--------|:--------|:--------|
| `on_signal_created` | 策略模块（Method）产生信号判定结果后，进入过滤器链之前 | `signal_id, symbol, signal_type, raw_score, timestamp, context` | 记录信号原始事件，开始全链路追踪 |
| `on_filter_check` | 每个过滤器执行完毕后 | `signal_id, filter_name, status, reason, elapsed_ms` | 记录过滤器链日志；统计各层过滤触发频率 |
| `on_pre_decision` | 全部过滤器执行完毕，SignalFusion 评分完成，最终决策前 | `signal_id, fusion_score, filter_summary, regime` | 保存中间决策状态（方便事后回溯） |
| `on_decision_made` | 最终成交/拒绝/待定决策已产生 | `signal_id, final_decision, executed_price, executed_qty, reason` | 写入 signal_events 的 final_decision 字段，关联执行结果 |
| `on_position_update` | 持仓变动时（开仓、平仓、加仓、减仓） | `symbol, direction, price, qty, position_after` | 与 Trades 日志同步，验证 signal_events 与实盘明细的一致性 |

##### 钩子在引擎执行流程中的位置和调用时序

```
策略周期 DAG（单次信号生命周期）:

Strategy Signal Trigger
       │
       ▼
   [on_signal_created]  ←─ 1. 信号原始事件
       │
   ┌───┴───┐
   │ Filter Chain        │
   │  ├─ MarketStateFilter
   │  │      └→ [on_filter_check]  ←─ 2. 每过滤器执行后触发
   │  ├─ CoolingPeriod
   │  │      └→ [on_filter_check]
   │  ├─ DrawdownGuard
   │  │      └→ [on_filter_check]
   │  └─ VolatilityRiskMgr
   │           └→ [on_filter_check]
   └───┬───┘
       │
   SignalFusion 评分
       │
       ▼
   [on_pre_decision]     ←─ 3. 决策前快照
       │
   ┌───┴────┐
   │ Decision Engine     │  (最终判定: execute / filter / confidence_low)
   └───┬────┘
       │
       ├─ 成交 → [on_decision_made]  ←─ 4. 决策结果
       │           └→ [on_position_update]  ←─ 5. 持仓变更
       │
       └─ 拒绝 → [on_decision_made]  ←─ 4'. 拒绝事件
```

##### 接口签名

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class SignalEvent:
    signal_id: str
    symbol: str
    signal_type: str          # 'grid_trigger', 'breakout', 'volume_signal'
    raw_score: float
    timestamp: str            # ISO8601
    extra_context: Dict[str, Any] = None

@dataclass
class FilterResult:
    filter_name: str
    status: str               # 'pass' | 'reject' | 'bypass'
    reason: Optional[str] = None
    elapsed_ms: float = 0.0

@dataclass
class DecisionResult:
    final_decision: str       # 'executed' | 'filtered' | 'confidence_low'
    fusion_score: float
    executed_price: Optional[float] = None
    executed_qty: Optional[int] = None
    reject_reason: Optional[str] = None

class BacktestEventHook(ABC):
    """回测引擎事件钩子基类。所有钩子实现必须继承此类。"""

    @abstractmethod
    def on_signal_created(self, event: SignalEvent) -> None:
        """策略模块产生信号时触发。"""
        ...

    @abstractmethod
    def on_filter_check(self, signal_id: str, result: FilterResult) -> None:
        """每个过滤器执行完毕后触发。"""
        ...

    @abstractmethod
    def on_pre_decision(self, signal_id: str, fusion_score: float,
                        filter_summary: Dict[str, FilterResult],
                        regime: Optional[str]) -> None:
        """所有过滤器执行完毕、最终决策前触发。"""
        ...

    @abstractmethod
    def on_decision_made(self, signal_id: str, decision: DecisionResult) -> None:
        """最终决策已产生时触发。"""
        ...

    @abstractmethod
    def on_position_update(self, symbol: str, direction: str,
                           price: float, qty: int,
                           position_after: int) -> None:
        """持仓变动时触发。"""
        ...


class SignalEventCollector(BacktestEventHook):
    """信号事件采集器：实现所有钩子并将数据写入 signal_events DB。"""

    def __init__(self, db_path: str = "data/signals/signal_events.db"):
        self.db = self._init_db(db_path)

    def on_signal_created(self, event: SignalEvent) -> None:
        # INSERT INTO signal_events (event_id, timestamp, ...) VALUES (...)
        ...

    def on_filter_check(self, signal_id: str, result: FilterResult) -> None:
        # UPDATE signal_events SET filters_json = ... WHERE event_id = signal_id
        ...

    def on_decision_made(self, signal_id: str, decision: DecisionResult) -> None:
        # UPDATE signal_events SET final_decision = ..., executed_price = ...
        ...
```

##### 引擎集成方式

```python
# 回测引擎初始化时注册钩子
engine = BacktestEngine(strategy=strategy, data=data)

# 注册信号事件采集器
signal_collector = SignalEventCollector(
    db_path="data/signals/signal_events.db"
)
engine.register_hook(signal_collector)

# 可选：注册过滤器日志采集器
filter_logger = FilterChainLogger(
    db_path="data/signals/filters_log.db"
)
engine.register_hook(filter_logger)

# 引擎内部自动按上文时序调用各钩子方法
engine.run()
```

> **设计要点**:
> - 钩子采用**观察者模式（Observer Pattern）**，引擎仅维护一个 `List[BacktestEventHook]`，在关键节点遍历调用
> - 钩子之间无顺序依赖：SignalEventCollector 和 FilterChainLogger 可以独立注册或移除
> - 钩子执行失败不影响主流程：异常捕获后日志告警，不阻断回测
> - 是否启用通过配置开关控制：`config.hooks.enabled = True`

#### 工作量拆解

| 子任务 | 工作量 | 说明 |
|:------|:-----:|:----|
| signal_events DB 架构与迁移 | 0.5 天 | SQLite 建表 + 升级脚本 |
| 信号事件采集点插入 | 1 天 | BaseMethod / SignalFusion 模块改造 |
| 过滤器链日志接入 | 1 天 | 各 Filter 模块增加 event 记录 |
| 事后统计分析模块 | 1 天 | 聚合查询 + 置信度分桶 |
| 报告展示层渲染 | 0.5 天 | 漏斗图 + 分桶表 + 热图 |
| 单元测试 + 验证 | 0.5 天 | — |
| **合计** | **4.5 天** | — |

---

### 2.2 Conditional Return Matrix（条件收益矩阵）

**优先级**: P1 | **预估工作量**: 2~3 人天

#### 功能描述

构建 Regime（行）× 成交量条件（列）的二维条件收益矩阵，回答"在什么条件下赚钱"。

**输出内容 — 条件收益矩阵**:

| Regime ↓ \\ 成交量 → | 放量 | 缩量 | 正常量 |
|:-------------------:|:---:|:---:|:-----:|
| **TREND_UP** | N / avg_ret / win% | N / avg_ret / win% | N / avg_ret / win% |
| **DOWNTREND** | N / avg_ret / win% | N / avg_ret / win% | N / avg_ret / win% |
| **RANGE** | N / avg_ret / win% | N / avg_ret / win% | N / avg_ret / win% |
| **RANGE_SIDEWAYS** | N / avg_ret / win% | N / avg_ret / win% | N / avg_ret / win% |

每个格子的数据：`交易次数 / 平均收益率 / 胜率`

**额外输出**:

- **条件收益差异显著性检验**：放量 TREND_UP 的收益是否显著高于缩量 TREND_UP？（T-test / Mann-Whitney U）
- **条件频数热图**：展示各条件的交易分布密度，避免"小样本格"过度解读
- **收益分布箱线图**：按条件分组展示收益分布（含异常值标注）

#### 数据依赖

| 需要的数据 | 当前系统状态 | 新增采集点 |
|:---------|:-----------|:----------|
| 每笔交易的 Regime 标签 | ⚠️ 已有 Regime 序列，但需绑定到每笔交易 | 交易记录增加 `regime_at_trade` 字段 |
| 成交量的条件分桶 | ⚠️ 框架就绪，未自动化 | 放量/缩量阈值标准化 |
| 跨标的 × 跨周期的多笔交易 | ❌ 当前仅 1 笔 | Phase 2 多标的扩展 |
| 收益分布的分位数统计 | ❌ 未实现 | 计算函数库 |

**成交量分桶规则**:

```python
VOLUME_THRESHOLDS = {
    "放量": volume > 20d_MA_volume * 1.5,
    "缩量": volume < 20d_MA_volume * 0.7,
    "正常量": 其他
}
```

#### 工作量拆解

| 子任务 | 工作量 | 说明 |
|:------|:-----:|:----|
| Regime → 交易绑定逻辑 | 0.5 天 | 回测中为每笔交易记录当时 Regime |
| 成交量条件分桶标准化 | 0.5 天 | 阈值参数化 + 自动化标注 |
| 条件收益聚合计算 | 0.5 天 | 分组统计 + 显著性检验 |
| 报告展示层渲染 | 0.5 天 | 矩阵表 + 箱线图 |
| 单元测试 | 0.5 天 | — |
| **合计** | **2.5 天** | — |

**关键约束**: 矩阵的实际价值需多标的 × 多周期数据支撑（建议 ≥ 200 笔交易）。Phase 1 搭建框架占位，Phase 2 填充数据。

---

### 2.3 Capital Efficiency（持仓效率分析）

**优先级**: P1 | **预估工作量**: 5~10 人天

#### 功能描述

从"单标的持仓效率"和"多标的并行覆盖"两个层面分析资金使用效率。

**输出内容 A — 单标的持仓效率指标**:

| 指标 | 值 | 计算方式 |
|:----|:--|:--------|
| 平均持仓时间 | — | 所有持仓的 (平仓日 - 开仓日) 均值 |
| 最大持仓时间 | — | — |
| 空仓时间占比 | — | 无持仓日 / 总交易日 |
| 资金利用率 | — | 平均持仓市值 / 总资金 |
| 单位资金收益 | — | 总收益 / 平均持仓市值 |
| 单位风险收益 | — | 总收益 / 最大回撤金额 |
| 资金周转率 | — | 总成交金额 / 平均持仓市值 |

**输出内容 B — 多标的并行模拟框架**:

核心公式：
```
E[Return_multi] = Σ(R_i × W_i × Utilization_i)

其中:
  R_i          = 单标的年化收益率
  W_i          = 资金权重
  Utilization_i = 标的 i 的实际持仓时间占比
```

模拟输出表：

| 标的数量 | 资金分配方案 | 理论闲置率 | 模拟年化 | 相关性折扣系数 |
|:-------:|:-----------:|:---------:|:--------:|:-------------:|
| 1 | 100% 给标的 A | real | real | 1.0 |
| 3 | 33% × 3 | projected | projected | 0.7 |
| 10 | 10% × 10 | projected | projected | 0.5 |
| 50 | 2% × 50 | projected | projected | 0.3 |

**额外输出**: 持仓重合度热图（多标的间时间维度的持仓重叠分析）、标的间相关性矩阵。

#### 数据依赖

| 需要的数据 | 当前系统状态 | 新增采集点 |
|:---------|:-----------|:----------|
| 单标的持仓效率基础数据 | ✅ 已有（空闲期、利用率） | 完善到对应字段 |
| 多标的并行回测引擎 | ❌ 不存在 | 全新架构设计 |
| 标的池行情数据 | ⚠️ 有单标的，无多标的标准化 | 多标的行情自动接入 |
| 资金池分配逻辑 | ❌ 不存在 | 等权重/风险平价/动态分配 |
| 标的间相关性 | ❌ 不存在 | 从回测数据计算 |

**多标的架构改造范围**:

```
当前架构（单标的）:
  Method → PortfolioManager (单资金池, 单symbol)

目标架构（多标的）:
  MultiInstrumentRunner
    ├── Instrument A: Method → PortfolioManagerA (子资金池)
    ├── Instrument B: Method → PortfolioManagerB (子资金池)
    ├── ...
    └── FundAllocator (全局资金池 → 子资金池)
        ├── 等权重分配
        ├── 风险平价分配
        └── 动态分配（需优化器）
```

#### 工作量拆解

| 子任务 | 工作量 | 说明 |
|:------|:-----:|:----|
| 单标的数据完善 + 展示层 | 0.5 天 | 已有数据包装 |
| 多标的并行运行框架设计 | 2 天 | 架构设计 + 接口定义 |
| 多标的数据加载（行情接入） | 2 天 | 多标的 OHLCV 标准化加载 |
| 资金池分配管理 | 1.5 天 | 等权重 + 风险平价 |
| 相关性计算 + 效率模拟 | 1 天 | — |
| 报告展示层渲染 | 0.5 天 | — |
| 单元测试 + 集成测试 | 1 天 | — |
| **合计** | **8.5 天** | — |

**分阶段策略**: Phase 1 产出单标的持仓效率指标（0.5 天），完整多标的系统留到 Phase 3。

---

### 2.4 Signal Decay Analysis（信号衰减分析）

**优先级**: P2 | **预估工作量**: 3~5 人天

#### 功能描述

研究信号的"有效周期"——信号产生后，收益随持有时间的变化曲线，识别最优持有窗口和趋势衰减点。

**输出内容 A — 持有期收益衰减曲线**:

```
平均收益(%)
   |
   |                          ● (最优持有期)
   |                       ●
   |                    ●
   |                 ●
   |              ●
   |           ●
   |        ●
   |     ●
   |  ●
   |─●───●───●───●───●───●───●───●───●─→ 持有期(天)
   0   1   3   5   7  10  15  20  25  30
```

**输出内容 B — 衰减分析表**:

| 持有期(天) | 平均收益 | 胜率 | 收益/风险比 | 样本量 | 置信区间 |
|:---------:|:-------:|:---:|:----------:|:-----:|:-------:|
| 1 | +0.20% | 52% | 0.8 | — | ±0.5% |
| 3 | +0.80% | 56% | 1.2 | — | ±0.8% |
| 5 | +1.70% | 61% | 1.8 | — | ±1.2% |
| 10 | +3.40% | 65% | 2.1 | — | ±2.0% |
| 20 | +2.10% | 58% | 1.4 | — | ±2.5% |

**输出内容 C — 最优持有期推荐**:

```
基于衰减曲线拐点：
  最优持有期：10 天（收益拐点前）
  次优持有期：5 天（收益加速区间）
  建议止损：持有 > 10 天仍未盈利 → 趋势已失效
```

**额外输出**: 按 Regime 分组的衰减曲线对比、按标的分组的衰减差异、多信号冲突时的衰减叠加效应。

#### 数据依赖

| 需要的数据 | 当前系统状态 | 新增采集点 |
|:---------|:-----------|:----------|
| 信号产生后 N 天的价格序列 | ❌ 未自动化保存 | 回测时保存每日收盘价 |
| 信号产生后每日浮盈/浮亏 | ❌ 未采集 | 中间市值的逐日记录 |
| 信号时间戳 | ⚠️ 有间接记录，需标准化 | 统一为 signal_events 的时间戳 |
| 最优持有期拐点算法 | ❌ 不存在 | 收益曲线二阶导 / 滚动 Sharpe 优化 |
| 跨标的 × 多周期的完备衰减统计 | ❌ | 需 Phase 2 多标的 |

#### 工作量拆解

| 子任务 | 工作量 | 说明 |
|:------|:-----:|:----|
| 持有期收益回溯计算 | 1 天 | 从 signal_events 回溯 N 日价格 |
| 每日持仓市值记录 | 0.5 天 | 回测引擎改造：逐日记录持仓市值 |
| 衰减曲线计算 + 拟合 | 1 天 | 平均收益 vs 持有期 + 置信区间 |
| 最优持有期判定算法 | 1 天 | 拐点检测（二阶导 / 滚动 Sharpe） |
| 报告展示层渲染 | 0.5 天 | 曲线图 + 分析表 |
| 单元测试 | 0.5 天 | — |
| **合计** | **4.5 天** | — |

**依赖约束**: 需要 ≥ 30 笔交易数据才能构建有统计意义的衰减曲线。建议在 Phase 2 多标的扩展后进行。

---

### 2.5 False Breakout Profile（假突破画像）

**优先级**: P0 | **预估工作量**: 1~2 人天（基础版），+2~3 天（分类器）

#### 功能描述

构建真假突破的多维特征对比矩阵，设计自动真假突破分类器。

**输出内容 A — 真假突破特征对比矩阵**:

| 特征 | 假突破特征（均值） | 真突破特征（均值） | 区分度 | 计算来源 |
|:----|:----------------:|:----------------:|:-----:|:--------|
| 成交量变化率 | +8% | +61% | 高 | Volume 日线 |
| VWAP 偏离（突破后 3 日均值） | 0.8% | +11.9% | 高 | Anchored VWAP |
| ATR 扩张比（突破日 / 前 20 日均值） | — | — | ⚠️ 待计算 | ATR 序列 |
| OBV 变化 | 无 | 强 | ⚠️ 待计算 | OBV 序列 |
| 持续日数 | 1.3 天 | 31 天 | 高 | 价格序列 |
| 突破时 Regime | 100% RANGE | TREND_UP | 高 | Regime 序列 |
| 突破价与近期高点距离 | 近（±0.5%） | 持续远离 | 中 | 价格序列 |

**输出内容 B — 真假突破评分卡（规则版）**:

```python
真突破置信度 = 
  w1 × VolumeSignal      (0~1)   w1 = 0.35
  + w2 × VWAPDeviation   (0~1)   w2 = 0.20
  + w3 × RegimeAlignment (0~1)   w3 = 0.25
  + w4 × Persistence     (0~1)   w4 = 0.20

阈值：
  真突破判定：> 0.60
  待观察：    0.40 ~ 0.60
  假突破判定：< 0.40
```

**输出内容 C — 假突破模式总结**:

```
回测期内假突破的共同特征模式：
  模式 A: RANGE 中放量但未突破 VWAP → 1 日反转
  模式 B: 高位缩量突破 → 2 日内回归  
  模式 C: Regime 转换期杂波 → 无持续方向
```

**分类器中期方案**:

| 阶段 | 方案 | 样本要求 | 实现复杂度 |
|:----:|:----|:--------:|:---------:|
| Phase 1 | 规则评分卡（加权特征组合） | ~10 样本 | 低 |
| Phase 2 | Logistic Regression | 50+ 样本 | 中 |
| Phase 3 | XGBoost / LightGBM | 200+ 样本 | 高 |

#### 数据依赖

| 需要的数据 | 当前系统状态 | 新增采集点 |
|:---------|:-----------|:----------|
| 突破事件列表（含真假标记） | ✅ 已有（§11.1） | 标准化为 breakout_events 表 |
| 成交量变化率 | ✅ 可从日线计算 | 自动化到特征提取 |
| VWAP 偏离度 | ✅ 已有 Anchored VWAP | 自动化到特征提取 |
| ATR 扩张比 | ⚠️ 需引入 ATR 计算 | ATRFactor 或 VolatilityRiskManager 复用 |
| OBV 变化 | ❌ 未实现 | OBV 计算模块 |
| Regime 模式 | ✅ 已有 Regime 序列 | 自动化绑定 |

##### 数据源可用性验证 🔍

> **验证时间**: 2026-05-18（P0 评审时执行）
> **验证结论**: ATR/OBV 所需数据可用 ✅

| 验证项 | 状态 | 详情 |
|:------|:----|:----|
| 日线 OHLCV 数据文件 | ✅ 存在 | `data/market/601857_SH.csv`, `data/market/000001_SZ.csv`（注：路径为 `data/market/*.csv`，非设计文档最初假设的 `data/market/daily/` 子目录，已在 §6.2 修正） |
| Volume 列完整性 | ✅ 完整 | 两文件均包含 `volume`、`amount` 列，2010-01-01 ~ 2026-05-14 无缺失 |
| ATR 计算可行性 | ✅ 可行 | 需 `high`, `low`, `close` 三列（均存在），可由 `VolatilityRiskManager` 复用计算 |
| OBV 计算可行性 | ✅ 可行 | 需 `close`, `volume` 两列（均存在），新增 `OBVFactor` 模块实现 |
| 回测期（84 天）内数据覆盖 | ✅ 完整 | 2026-01-01 ~ 2026-05-14 全部交易日均有数据 |

> **重要发现**: 当前数据存储在 `data/market/*.csv` 平面文件结构（非 `data/market/daily/` 子目录）。设计文档 §6.2 文件结构已同步修正为实际路径。ATR/OBV 计算所需的基础字段（high/low/close/volume）全部可用，特征提取可立即开始，**无需额外的数据采购或清洗工作**。

**breakout_events 表架构**:

```sql
CREATE TABLE breakout_events (
    event_id        TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    direction       TEXT NOT NULL,        -- 'up', 'down'
    breakout_price  REAL NOT NULL,
    actual_label    TEXT,                 -- 'true_breakout', 'false_breakout', 'pending'
    duration_days   INTEGER,
    return_pct      REAL,
    -- 特征列（Phase 1 填充）
    volume_change   REAL,                 -- 突破日成交量 / 前 20 日均量 - 1
    vwap_deviation  REAL,                 -- 突破后 3 日均 VWAP 偏离
    regime_at_break TEXT,                 -- 突破时的 Regime
    atr_ratio       REAL,                 -- 突破日 ATR / 前 20 日均 ATR
    obv_change      REAL,                 -- OBV 变化率
    score           REAL,                 -- 分类器预测分数
    confidence      REAL                  -- 分类器置信度
);
```

#### 工作量拆解

| 子任务 | 工作量 | 说明 |
|:------|:-----:|:----|
| breakout_events 表设计 + 数据回填 | 0.5 天 | 基于 §11 已有 7 样本回填 |
| ATR 特征提取 | 0.5 天 | 复用 VolatilityRiskManager 的 ATR 计算 |
| OBV 特征提取 + 计算 | 0.5 天 | 新增 OBVFactor |
| 规则版评分卡实现 | 0.5 天 | 加权特征 + 阈值判定 |
| 特征对比矩阵展示层 | 0.5 天 | 表格 + 雷达图 |
| 单元测试 + 验证 | 0.5 天 | — |
| **合计（基础版）** | **3 天** | — |
| 分类器（Logistic Regression） | +2 天 | 需 50+ 样本，Phase 2 |

---

### 2.6 Trend Lifecycle Analysis（趋势生命周期分析）

**优先级**: P1 | **预估工作量**: 2~4 人天

#### 功能描述

建立右侧趋势的 5 阶段量化模型，将趋势分解为可识别、可统计、可检验的阶段序列。

**输出内容 A — 趋势生命周期 5 阶段模型**:

```
价格
  ↑
  |     ┌────── 5.分配期 (Distribution)
  |    ╱          OBV背离，量价不一致
  |   ╱
  |  ╱  ──── 4.衰竭期 (Exhaustion)
  | ╱           VWAP偏离 > 10%, Volume萎缩
  |╱
  |     ──── 3.主升期 (Main Trend)
  |\\           Volume Expansion, TrendQuality 峰值
  | \\
  |  \\  ──── 2.加速期 (Acceleration)
  |   \\         TrendQuality > 0.8
  |    \\
  |     └── 1.启动期 (Initiation)
  |           放量突破 VWAP, Regime→TREND_UP
  └───────────────────────────────→ 时间
```

**输出内容 B — 各阶段量化判定标准**:

| 阶段 | 代号 | 核心判定条件 | 辅助条件 | 策略动作 |
|:----|:----|:-----------|:--------|:--------|
| 1. 启动期 | INIT | Regime 切换至 TREND_UP + 突破 VWAP | Volume > 20日均量 | 可建仓 |
| 2. 加速期 | ACCEL | TrendQuality > 0.8 | 连续 3 日 VWAP 正偏离 | 加仓/持仓 |
| 3. 主升期 | MAIN | Volume 持续放大 + 偏离度扩大 | 斜率 > 0.3%/日 | 持仓 |
| 4. 衰竭期 | EXHAUST | VWAP 偏离 > 10% + Volume 萎缩 | TrendQuality 下降 > 0.1 | 减仓/止盈 |
| 5. 分配期 | DISTRIB | OBV 背离 + Regime 切换信号 | 出现假突破 | 平仓/离场 |

**输出内容 C — 回测期内阶段标注结果**:

| 时间区间 | 阶段 | 判定依据 | 策略状态 | 阶段收益 |
|:-------:|:----|:--------|:--------|:--------|
| 2026-01-05 ~ 01-21 | 启动前（低质量 RANGE） | Regime=RANGE, TQ=0.45 | 空仓 | 0% |
| 2026-01-22 ~ 01-28 | 🟢 启动期 | 放量突破 VWAP | 开仓 | +3.35% |
| 2026-01-29 ~ 02-12 | 🟢 加速期 | TQ=0.82 | 持仓 | +5.12% |
| 2026-02-13 ~ 02-28 | 🟢 主升期 | TQ=0.91, Volume 放大 | 持仓 | +16.24% |
| 2026-02-28 ~ 03-04 | 🟡 衰竭期 | VWAP 偏离 11.9% | 止盈平仓 | +5.47% |
| 2026-03-05 ~ 05-14 | 🔴 分配期 | 多次假突破 | 空仓 | 0% |

**输出内容 D — 生命周期阶段统计**:

| 阶段 | 出现次数 | 平均持续时间 | 平均收益 | 胜率 | 策略参与度 |
|:----|:-------:|:----------:|:-------:|:---:|:---------:|
| 启动期 | — | — | — | — | — |
| 加速期 | — | — | — | — | — |
| 主升期 | — | — | — | — | — |
| 衰竭期 | — | — | — | — | — |
| 分配期 | — | — | — | — | — |

**输出内容 E — 可检验的研究假设**:

```
H₁: 启动期的信号胜率 > 衰竭期的信号胜率
H₂: 主升期加仓的 Sharpe 比率 > 启动期加仓的 Sharpe 比率
H₃: 识别衰竭期信号并提前减仓可减少平均回撤 30%+
H₄: 分配期的假突破比例 > 启动期的假突破比例
```

#### 数据依赖

| 需要的数据 | 当前系统状态 | 新增采集点 |
|:---------|:-----------|:----------|
| TrendQuality 序列 | ✅ 已有（§6.2） | 保存为时间序列 |
| VWAP 偏离度序列 | ✅ 已有 Anchored VWAP | 计算每日偏离 |
| Volume 序列 | ✅ 已有 | — |
| Regime 序列 | ✅ 已有（§8.1） | 保存为时间序列 |
| OBV 序列 | ❌ 未实现 | 与假突破画像共享 OBV 模块 |
| 阶段状态机判定算法 | ❌ 不存在 | 新增 TrendLifecycleStageDetector |
| 跨标的生命周期对比 | ❌ | Phase 2 多标的 |

**阶段状态机接口设计**:

```python
@dataclass
class LifecycleStage:
    stage: str          # 'pre_init' | 'init' | 'accel' | 'main' | 'exhaust' | 'distrib'
    start_date: str
    end_date: str
    confidence: float

class TrendLifecycleStageDetector:
    """趋势生命周期阶段检测器。
    
    基于 TrendQuality + VWAP 偏离 + Volume + Regime 序列，
    使用状态机标注每个交易日所处的趋势阶段。
    """
    
    def detect(
        self, 
        df: pd.DataFrame,         # 必须含: close, volume, high, low
        regime_series: pd.Series,
        trend_quality: pd.Series,
        vwap: pd.Series,
    ) -> List[LifecycleStage]:
        """标记完整的生命周期阶段序列。"""
        ...
    
    def get_stage_at(self, date: str) -> Optional[str]:
        """查询指定日期的阶段。"""
        ...
```

#### 工作量拆解

| 子任务 | 工作量 | 说明 |
|:------|:-----:|:----|
| 生命周期阶段量化标准定义 | 1 天 | 阈值标定 + 规则编写 |
| 阶段判定状态机实现 | 1 天 | TrendLifecycleStageDetector |
| 历史阶段回溯标注 | 0.5 天 | 对回测期运行状态机 |
| 各阶段收益 + 策略行为统计 | 0.5 天 | — |
| 报告展示层渲染 | 0.5 天 | 5 阶段时间线图 + 统计表 |
| 单元测试 + 验证 | 0.5 天 | — |
| **合计** | **4 天** | — |

---

## 3. "伪研究"修正方案

### 3.1 当前报告中的"伪研究"问题清单

在 V2 修改后的报告（research_v2）中已识别以下问题：

| 位置 | 原文 | 问题分析 | 严重性 |
|:----|:----|:--------|:-----:|
| §7.1 因子贡献表 | "约 35%（observation）" | 虽然已标注 observation，但"约 35%"仍暗示精确占比，可能被误解为统计结论 | 🟡 中 |
| §9.4 被过滤亏损 | "避免亏损约 5.9%（假设）" | 纯假设推算，无回测数据支撑，存在误导风险 | 🟡 中 |
| §11.3 假突破特征 | "假突破特征（Observation）" | 基于 6 个样本的观察，标注正确，保持 | 🟢 低 |
| §11.1 真假突破 % | "14.3% / 85.7%" | 基于 7 笔事件统计，可标注但需强调样本量局限 | 🟢 低 |

### 3.2 Observation 标注规则（正式版）

所有非统计性结论必须遵循以下标注规范：

#### 规则 1：明确标注 "Observation"

```
格式：[Observation] 本次交易中…（基于 N 次观察）

适用场景：
- 单笔或小于 30 笔的交易分析
- 基于规则的定性判断
- 未经统计验证的模式描述

禁止场景：
- ❌ 不得写入 KnowledgeBridge 作为定量结论
- ❌ 不得用于参数优化的决策依据
```

#### 规则 2：数字范围化

```
正确：约 30~40%（观测范围）
错误：约 35%（精确值，Observation 标注不够）

理由：少数样本的精确数值造成"伪精度"假象，范围值更诚实
```

#### 规则 3：样本量声明

每份报告必须包含统一的"数据局限性"声明，具体格式：

```markdown
> **数据局限性声明**
> 本报告基于回测期 N 个交易日、M 笔交易数据生成。
> 所有标注为 [Observation] 的结论为基于当前样本的观测性陈述，
> 非具有统计意义的定量结论。
> 
> 统计意义的样本要求：
> - 收益分布分析：≥ 30 笔交易
> - 条件收益矩阵：每格 ≥ 10 笔交易
> - 信号衰减分析：≥ 30 笔交易
> - 分类器训练：≥ 200 笔交易（含标签）
```

#### 规则 4：替代用词对照表

| 原用词（禁止） | 替代用词（推荐） |
|:-------------|:---------------|
| 贡献（Contribution） | 观测权重（Observation Weight） |
| 估计占比 | 观测占比 |
| 预测收益 | 假设推算（Hypothetical Projection） |
| 因子贡献 | 因子观测表现 |
| 结论 | 当前观察结果 |
| 规律 | 样本内模式（In-sample Pattern） |

### 3.3 修正路线图

| 阶段 | 操作 | 耗时 |
|:----|:----|:----|
| 立即 | 替换 §7.1 "贡献" 为 "观测权重" | 0.5 小时 |
| 立即 | §9.4 补充 "纯机械推算" 标注 | 0.25 小时 |
| Phase 1 | 实现 Observation 标注规则的系统级强制执行 | 0.5 天 |
| Phase 1 | 报告模板统一集成数据局限性声明 | 0.5 天 |
| Phase 1 | 增加 "数字范围化" 的校验逻辑 | 0.5 天 |

---

## 4. 四层报告结构（总结）

### 4.1 四层结构模型

```
┌──────────────────────────────────────────────────┐
│                   ┌──────────┐                    │
│                   │ Layer 1  │  结果层            │
│                   │  结果层   │  - 总收益率        │
│                   │          │  - 夏普比率        │
│                   └────┬─────│  - 最大回撤        │
│                        │    └───                 │
│                        ▼                         │
│                   ┌──────────┐                    │
│                   │ Layer 2  │  行为层            │
│                   │  行为层   │  - 交易行为        │
│                   │          │  - 趋势质量分布    │
│                   └────┬─────│  - 因子观测分析    │
│                        │    └───                 │
│                        ▼                         │
│                   ┌──────────┐                    │
│                   │ Layer 3  │  结构层            │
│                   │  结构层   │  - Regime 分析    │
│                   │          │  - 风控行为        │
│                   └────┬─────│  - 成交量结构     │
│                        │    └───                 │
│                        ▼                         │
│                   ┌──────────┐                    │
│                   │ Layer 4  │  研究层            │
│                   │  研究层   │  - 知识提炼       │
│                   │          │  - 参数稳定性     │
│                   └──────────│  - 失败模式总结   │
│                                      └───         │
│                        │                         │
│                        ▼                         │
│              ┌─────────────────────┐              │
│              │ Layer 5（V2 新增）   │  研究深化层  │
│              │ 研究深化层           │  - Signal Distribution   │
│              │                     │  - Conditional Return    │
│              │                     │  - Capital Efficiency    │
│              │                     │  - Signal Decay          │
│              │                     │  - False Breakout Profile│
│              │                     │  - Trend Lifecycle      │
│              └─────────────────────┘              │
└──────────────────────────────────────────────────┘
```

### 4.2 各层核心问题

| 层级 | 核心问题 | 读者 | 决策价值 |
|:----:|:---------|:----|:--------|
| Layer 1 | 赚了多少？风险多大？ | 决策者 | 是否值得进一步研究 |
| Layer 2 | 在什么市场赚钱？ | 策略研究员 | 策略的适用环境 |
| Layer 3 | 机构成本在哪？成交量如何验证？ | 量化研究员 | 市场结构理解 |
| Layer 4 | 规律是什么？什么时候不能用？ | 投资经理 | 策略知识沉淀 |
| Layer 5 | 统计上是否显著？条件收益如何分布？ | 量化研究员 | 策略的统计可靠性 |

### 4.3 四层结构的迭代路径

```
Phase 1 → Layer 1-4 基础都就绪 + Layer 5 框架占位
Phase 2 → Layer 5 开始有数据（多标的 × 多周期）
Phase 3 → Layer 5 完整运行（统计显著性达标）
Phase 4 → Layer 1-5 全部自动化 -> L3 机构级
```

---

## 5. 实施路线

### 5.1 Phase 1（本周）：信号采集体系 + 假突破画像

> ⚠️ **串行依赖说明（P0 评审修正）**: Signal Distribution 内部的 4 个子任务存在严格的串行依赖关系，无法并行执行。依赖链：
> ```
> DB架构 → 信号采集点改造 → 过滤器日志接入 → 聚合展示
>    0.5d        1d               1d             1.5d
> └──────────────────────── 4 天（最小串行路径）────────────────┘
> ```
> 由于聚合展示必须等前三步全部完成后才能开始，Signal Distribution 模块实际最少需要 **4 天**，而不是 4 个子任务可并行分摊的乐观估算。
>
> False Breakout Profile 内部也存在串行依赖：
> ```
> breakout_events 表 → ATR+OBV 特征提取 → 规则评分卡 → 展示层
>      0.5d                 1d                 1d           0.5d
> └──────────────────── 3 天（最小串行路径）──────────────────────┘
> ```
> 两条串行链可以**并行**进行（不同模块），但各自内部必须串行。

| 优先级 | 模块 | 具体任务 | 工作量 | 串行依赖 | 产出 |
|:-----:|:----|:--------|:-----:|:--------|:----|
| P0 | Signal Distribution | signal_events DB 架构 + 数据迁移 | 0.5 天 | 链首，无前置依赖 | 建表 + 迁移脚本 |
| P0 | Signal Distribution | 信号事件采集点改造（BaseMethod / SignalFusion） | 1 天 | ⛓️ 依赖 DB 架构完成 | 采集点就绪 |
| P0 | Signal Distribution | 过滤器链日志接入（含钩子系统集成） | 1 天 | ⛓️ 依赖采集点改造完成 | 各 Filter 有 event 记录 |
| P0 | Signal Distribution | 聚合统计 + 展示层 | 1.5 天 | ⛓️ 依赖日志接入完成 | 漏斗图 + 置信度分桶表 |
| P0 | False Breakout Profile | breakout_events 表 + 数据回填（7 样本） | 0.5 天 | 链首，无前置依赖 | 特征矩阵可展示 |
| P0 | False Breakout Profile | ATR + OBV 特征提取 | 1 天 | ⛓️ 依赖 breakout_events 完成 | 计算模块就绪 |
| P0 | False Breakout Profile | 规则评分卡 + 展示层 | 1.5 天 | ⛓️ 依赖特征提取完成 | 特征对比矩阵 + 评分卡 |
| P0 | 伪研究修正 | Observation 标注规则强制执行 + 模板集成 | 1 天 | 可并行 | 报告模板更新 |
| **Phase 1 合计** | — | — | **10~12 天** ⚠️ | — | — |

> **串行依赖导致的工期变化**:
> - 原乐观估算（8 天）假设所有子任务可完全并行
> - 实际 Signal Distribution 串行链最少 4 天，False Breakout Profile 串行链最少 3 天
> - 加上测试 + 集成 Buffer，Phase 1 实际工期估算为 **10~12 天**

> **Phase 1 关键交付物**:
> - `data/signals/signal_events.db` — 信号事件数据库
> - `data/signals/breakout_events.db` — 突破事件数据库
> - `src/backtest/signals/` — 采集模块目录
> - 报告模板 v2.1 — 集成 Observation 标注 + 数据局限性声明

### 5.2 Phase 2（下周）：条件收益矩阵 + 趋势生命周期

| 优先级 | 模块 | 具体任务 | 工作量 | 产出 |
|:-----:|:----|:--------|:-----:|:----|
| P1 | Conditional Return | Regime→交易绑定逻辑 | 0.5 天 | 每笔交易带 Regime 标签 |
| P1 | Conditional Return | 成交量条件分桶标准化 | 0.5 天 | 放量/缩量阈值参数化 |
| P1 | Conditional Return | 聚合计算 + 展示层 | 1 天 | 条件收益矩阵 + 箱线图 |
| P1 | Trend Lifecycle | 阶段量化标准定义 | 1 天 | 5 阶段判定规则 |
| P1 | Trend Lifecycle | 阶段状态机实现 | 1 天 | TrendLifecycleStageDetector |
| P1 | Trend Lifecycle | 历史回溯 + 展示层 | 1.5 天 | 阶段时间线 + 统计表 |
| P1 | Capital Efficiency（单标的） | 持仓效率指标完整化 | 0.5 天 | 单标的数据完善 |
| P1 | 多周期数据扩展 | 历史回测周期扩展（当前84天→3年） | 2 天 | 标的历史数据加载 |
| **Phase 2 合计** | — | — | **8 天** | — |

> **Phase 2 关键交付物**:
> - `src/backtest/research/conditional_return_matrix.py`
> - `src/backtest/research/trend_lifecycle_detector.py`
> - 扩展后的历史回测数据（2023~2026 年）
> - 报告模板 v2.2 — 集成条件矩阵 + 生命周期

### 5.3 Phase 3（下月）：持仓效率（多标的）+ 信号衰减

| 优先级 | 模块 | 具体任务 | 工作量 | 产出 |
|:-----:|:----|:--------|:-----:|:----|
| P1 | Capital Efficiency | 多标的并行运行框架设计 | 2 天 | MultiInstrumentRunner |
| P1 | Capital Efficiency | 资金池分配管理 | 1.5 天 | 等权重 + 风险平价 |
| P1 | Capital Efficiency | 相关性计算 + 效率模拟 | 1 天 | 多标的收益模型 |
| P1 | Capital Efficiency | 展示层渲染 | 0.5 天 | 闲置率/年化对比表 |
| P2 | Signal Decay | 持有期收益回溯计算 | 1 天 | 从 signal_events 回溯 |
| P2 | Signal Decay | 衰减曲线拟合 + 拐点检测 | 1.5 天 | 衰减曲线 + 最优持有期 |
| P2 | Signal Decay | 展示层渲染 | 0.5 天 | 衰减曲线图 + 分析表 |
| P2 | 分类器训练 | 假突破 Logistic Regression 训练 | 2 天 | 需 ≥ 50 样本 |
| **Phase 3 合计** | — | — | **10 天** | — |

> **Phase 3 关键交付物**:
> - `src/backtest/engine/multi_instrument_runner.py` — 多标的并行引擎
> - `src/backtest/research/signal_decay_analyzer.py`
> - `src/backtest/research/breakout_classifier.py` — Logistic Regression 分类器
> - 报告模板 v3.0 — L3 机构级

### 5.4 总工时估算汇总

| 阶段 | 总工时 | 主要产出 |
|:----|:-----:|:--------|
| Phase 1（本周） | 8 人天 | 采集体系 + 假突破画像 + 伪研究修正 |
| Phase 2（下周） | 8 人天 | 条件矩阵 + 生命周期 + 单标的数据完善 |
| Phase 3（下月） | 10 人天 | 多标的引擎 + 衰减分析 + 分类器 |
| **总计** | **26 人天** | **L3 研究员级报告系统** |

### 5.5 依赖路线图

```
Phase 1                  Phase 2                   Phase 3
────────                 ────────                  ────────
signal_events 采集 ──────→ Regime→交易绑定     ───→ 多标的并行引擎
     │                         │                      │
     ▼                         ▼                      ▼
过滤器日志接入        ───→ 条件收益矩阵       ───→ 相关性计算
     │                         │                      │
     ▼                         ▼                      ▼
置信度分桶            ───→ 成交量分桶       ───→ 资金池分配
     │                                     
     │                  TrendLifecycle 状态机 ──→ 阶段统计
     │                         │
     ▼                         ▼
breakout_events 表     ──→ 生命周期标注      ──→ 衰减曲线
     │                         │                      │
     ▼                         ▼                      ▼
ATR+OBV 特征提取      ──→ 阶段收益统计     ───→ 分类器训练
     │
     ▼
规则评分卡            ──────────────────────────→ LogReg 分类器
```

---

## 6. 文件结构（路径规划）

### 6.1 报告文件目录结构

```
mozhi_platform/
└── reports/
    ├── backtest/                       # 回测报告
    │   ├── report_v2_evaluation_20260518.md
    │   └── backtest_report_20260518_research_v2.md
    │
    ├── morning/                        # 早报（Step2 → Step5 流水线产出）
    │   └── {YYYYMMDD}/
    │       ├── datacollection_{task_id}.json        # 玄知采集数据
    │       ├── structured_analysis_{task_id}.json   # 墨衡: Step2
    │       ├── reportdraft_{task_id}.md             # 主报告草稿
    │       ├── review_feedback_{task_id}.md         # 墨衡: Step4 审查
    │       └── final_report_{task_id}.md            # 最终版
    │
    ├── midday/                         # 午报（结构同 morning）
    │   └── {YYYYMMDD}/
    │       ├── datacollection_{task_id}.json
    │       ├── structured_analysis_{task_id}.json
    │       ├── reportdraft_{task_id}.md
    │       ├── review_feedback_{task_id}.md
    │       └── final_report_{task_id}.md
    │
    ├── research/                       # 研究报告（V2 深化层独立目录）
    │   ├── {YYYY}/
    │   │   ├── signal_distribution_{symbol}_{YYYYMMDD}.md
    │   │   ├── conditional_return_matrix_{symbol}_{YYYYMMDD}.md
    │   │   ├── capital_efficiency_{symbol}_{YYYYMMDD}.md
    │   │   ├── signal_decay_{symbol}_{YYYYMMDD}.md
    │   │   ├── false_breakout_profile_{symbol}_{YYYYMMDD}.md
    │   │   └── trend_lifecycle_{symbol}_{YYYYMMDD}.md
    │   │
    │   └── cross_section/              # 横截面研究（Phase 2~3）
    │       ├── cross_section_ranking_{YYYYMMDD}.md
    │       ├── sector_comparison_{date}.md
    │       └── multi_instrument_report_{date}.md
    │
    └── templates/                      # 报告模板
        ├── report_template_v1.md       # P0: 基础版
        ├── report_template_v2.md       # 当前版（4层结构）
        └── report_template_v3.md       # 目标版（集成 V2 研究深化层）
```

### 6.2 数据文件目录结构

```
mozhi_platform/
└── data/
    ├── signals/                        # 信号事件数据
    │   ├── signal_events.db            # SQLite: 全量信号事件
    │   ├── breakout_events.db          # SQLite: 突破事件 + 特征
    │   └── filters_log.db              # SQLite: 过滤器链日志
    │
    ├── market/                         # 行情数据
    │   ├── 601857_SH.csv               # ✅ 已验证：含 volume 列，ATR/OBV 可用
    │   ├── 000001_SZ.csv               # ✅ 已验证：含 volume 列
    │   ├── market_data.db              # SQLite 汇总数据库
    │   ├── ...                         # 更多标的 CSV（待接入）
    │   └── intraday/                   # 分钟线（Phase 3 预留）
    │
    ├── regimes/                        # Regime 序列数据
    │   └── regime_history_{symbol}.parquet
    │
    ├── trend_quality/                  # 趋势质量数据
    │   └── trend_quality_history_{symbol}.parquet
    │
    └── simulation/                     # 多标的模拟数据（Phase 3）
        ├── portfolio_simulation_results.parquet
        └── correlation_matrix.parquet
```

### 6.3 源代码目录结构（新增模块）

```
mozhi_platform/
└── src/
    └── backtest/
        ├── signals/                    ← 新增: 信号事件采集模块
        │   ├── __init__.py
        │   ├── signal_event_collector.py    # signal_events 写入
        │   ├── filter_logger.py             # 过滤器链日志
        │   └── signal_stats.py              # 统计分析（漏斗/置信度分桶）
        │
        ├── research/                   ← 新增: 研究报告生成模块
        │   ├── __init__.py
        │   ├── conditional_return.py        # 条件收益矩阵
        │   ├── capital_efficiency.py        # 持仓效率分析
        │   ├── signal_decay.py              # 信号衰减分析
        │   ├── breakout_classifier.py       # 真假突破分类器
        │   └── trend_lifecycle.py           # 趋势生命周期检测
        │
        ├── factors/volume/             ← 已有 + 新增
        │   ├── vwap_factor.py               # 不改
        │   ├── volume_profile_factor.py      # 不改
        │   └── anchored_vwap.py             # 已设计（P1）
        │
        └── engine/                     ← 已有 + 改造
            ├── portfolio_integration.py     # 已改造（RiskPipeline）
            ├── portfolio/
            │   └── portfolio_manager.py     # 已改造（position_ratio）
            └── knowledge_bridge.py          # 已改造（risk_context）
                │
        └─── risk/                      ← 已新增（风险模块）
            ├── __init__.py
            ├── drawdown_guard.py
            ├── volatility_risk_manager.py
            ├── market_state_filter.py
            └── pipeline.py
```

### 6.4 设计文档目录结构

```
mozhi_platform/
└── docs/
    └── 09_roadmap/                     ← 设计方案文档
        ├── risk_module_design.md            # 风险模块设计方案（已完成）
        └── report_upgrade_v2_design.md      # 本文件: V2 报告升级设计方案
```

### 6.5 文件路径映射表

| 数据域 | 路径模式 | 说明 |
|:------|:--------|:----|
| 信号事件 | `data/signals/signal_events.db` | SQLite 数据库，按 batch_id 区分回测批次 |
| 突破事件 | `data/signals/breakout_events.db` | 含特征列，供分类器训练 |
| 研究报告 | `reports/research/{YYYY}/{type}_{symbol}_{date}.md` | 6 种研究类型 |
| 横截面报告 | `reports/research/cross_section/{type}_{date}.md` | 跨标的对比分析 |
| 行情数据 | `data/market/{symbol}_{exchange}.csv` | 日线 OHLCV（已验证含 volume 列，ATR/OBV 可用） |
| 趋势生命周期 | `data/trend_quality/trend_quality_history_{symbol}.parquet` | 时间序列数据 |
| 模拟结果 | `data/simulation/portfolio_simulation_results.parquet` | 多标的场景模拟 |

---

## 附录：A — 与现有系统的兼容性策略

| 场景 | 行为 |
|:----|:----|
| 未安装 signal_events 数据库 | 报告自动降级：§13~§18 显示 Structural Placeholder，不影响 §1~§12 正常展示 |
| 回测数据未满足最小样本量 | 报告自动标注数据局限性声明，统计性区域显示"N/A" |
| Phase 1 进行中，Phase 2 未开始 | 条件收益矩阵、趋势生命周期显示**空框架**，不报错 |
| 已有旧版报告 | 旧版报告保留，不自动重写。仅新增 V2 研究深化层报告 |

## 附录：B — 评审问题清单

- [ ] Phase 1 的 8 天是否在可接受交付周期内？
- [ ] signal_events DB 的架构是否满足 Phase 2/3 拓展需求？
- [ ] Observation 标注规则是否需要更多样例？
- [ ] 多标的并行引擎是否采用独立进程/线程模型？
- [ ] 分类器是否需要嵌套已有的 KnowledgeBridge？
- [ ] 报告模板 v3.0 是否需要设计为可配置（by option 开关各章节）？
- [ ] 路径合规审查是否通过？
