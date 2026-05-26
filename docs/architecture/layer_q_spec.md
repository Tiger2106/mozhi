<!--
author: 墨衡 (moheng)
created_time: 2026-05-19 16:31 GMT+8
task_id: phase1_patch_q_layer
-->

# Layer Q Spec — 当前实现状态文档

**版本**: v1.0  
**更新日期**: 2026-05-19  
**作者**: 墨衡 (moheng)  
**定位**: Transverse Governance Layer（横向治理层）—— 可信度审计账本（账本B）

---

## 一、架构总览

```
Layer Q — Transverse Governance Layer（横向治理层）
═════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────┐
│                   Q层流水线                                    │
│                                                              │
│  回测结果     Q1         Q2         Q3                       │
│  ─────────→ Existence → Robustness → Regime     ← 待实现 →  │
│   (全部P系列) Test [✅]    Surface     Consistency  [✅]     │
│                          [❌待实现]                           │
│       │         │           │           │                    │
│       │         ▼           ▼           ▼                    │
│       │    ┌─────────────────────────────────┐              │
│       │    │      中间评分（3维预聚合）        │              │
│       │    └─────────────────────────────────┘              │
│       │                                                      │
│       │         Q4         Q5         Q6                     │
│       │    ┌─── Capacity → Temporal → OOS                   │
│       │    │   Stability  Stability  Survival                │
│       │    │   [❌待实现]    [✅]       [❌待实现]            │
│       │    └──────────────────────────────────────────┐     │
│       │                         │                       │     │
│       │                         ▼                       │     │
│       │    ┌────────────────────────────────────────┐   │     │
│       │    │      Q7: ConfidenceScoreAggregator      │   │     │
│       │    │  6维评分 → 复合R → A~F评级 + 瓶颈     │   │     │
│       │    │             [❌待实现]                   │   │     │
│       │    └────────────────────────────────────────┘   │     │
│       │                         │                       │     │
│       │                         ▼                       │     │
│       │    ┌────────────────────────────────────────┐   │     │
│       │    │    Q8: Failure Attribution Engine        │   │     │
│       │    │  根因分析→归因比例→改进方向推荐  [✅]    │   │     │
│       │    └────────────────────────────────────────┘   │     │
│       │                         │                       │     │
│       │                         ▼                       │     │
│       │    ┌────────────────────────────────────────┐   │     │
│       │    │    Q9a: Q_FAILURES (正式审计)   [✅]     │   │     │
│       │    │    Q9b: RESEARCH_FAILURES (全量研究) [✅] │   │     │
│       │    └────────────────────────────────────────┘   │     │
│       │                         │                       │     │
│       └─────────────────────────┼───────────────────────┘     │
│                                 ▼                             │
│                    ┌────────────────────────────┐             │
│                    │  产出:                     │             │
│                    │  ① Q层审计报告              │             │
│                    │  ② P报告末段标准化段         │             │
│                    │  ③ Failure Registry记录    │             │
│                    └────────────────────────────┘             │
│                                                              │
│  管控机制:                                                    │
│  ┌────────┐  ┌────────┐  ┌───────────────┐  ┌──────────────┐│
│  │G1 Gate │→│G2 Gate │→│G3 Multi-Sign  │→│Q9 Failure    ││
│  │Existence│  │Robust  │  │(墨涵+墨萱      │  │Registry     ││
│  │ [✅]    │  │[❌待实现]│  │ +Owner) [✅]  │  │[✅]         ││
│  └────────┘  └────────┘  └───────────────┘  └──────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、已实现模块

### 2.1 Q1 — ExistenceValidator ✅

**文件**: `src/utils/existence_validator.py`  
**作者**: 墨衡  
**状态**: ✅ 已实现  
**测试**: ✅ 含单元测试

#### 功能
6 项存在性验证检查：

| 检查 | 名称 | 默认阈值 | 说明 |
|:----:|:-----|:--------:|:----:|
| C1 | 最小交易数 | N ≥ 30 | 统计显著性门槛 |
| C2 | 多Regime覆盖 | K ≥ 2 | 不在单一市场状态下有效 |
| C3 | 多年度覆盖 | T ≥ 2 年 | 跨时间周期验证 |
| C4 | 非单段收益 | 最大占比 < 40% | 不依赖极端单次交易 |
| C5 | 信号密度 | 年均 ≥ 12 | 低频策略边界标注 |
| C6 | 样本分布 | 单窗 ≤ 50% | 时间分布均匀性 |

#### 数据结构
```python
@dataclass
class ExistenceResult:
    exists: bool              # 全部通过 = True
    confidence: float         # 0.0 ~ 1.0（加权平均：C1=30%, C2~C6各10~15%）
    fail_reasons: list[str]   # 未通过项的说明
    details: dict             # 每项检查的详细值
```

#### 使用方式
```python
from utils.existence_validator import validate_existence, TradeRecord

trades = [TradeRecord(date="2026-01-01", pnl_pct=2.5, regime="TREND_UP"), ...]
result = validate_existence(trades)
if result.exists:
    print(f"通过，置信度: {result.confidence}")
else:
    print(f"未通过: {result.fail_reasons}")
```

---

### 2.2 Q3 — Regime Validator ✅

**文件**: `src/utils/q3_regime_validator.py`  
**作者**: 墨衡  
**状态**: ✅ 已实现  
**测试**: ✅ 含单元测试

#### 功能
验证策略在不同市场状态下的表现一致性：
- 支持逐笔交易分析和按 Regime 聚合分析两种模式
- 标准 5 状态命名映射
- ≥2 regime 正收益 = 最低通过标准
- 收益集中度检测（单一状态贡献 > 80% 标记为过度集中）

#### Regime 标准命名

| 标准命名 | 原始命名对照 |
|:--------:|:-------------|
| TREND_UP | UPTREND, BULLISH |
| TREND_DOWN | DOWNTREND, BEARISH |
| SIDEWAYS | RANGE, OSCILLATION |
| HIGH_VOL | BREAKOUT, CLIMAX, HIGH_VOLATILITY |
| LOW_VOL | LOW_VOL, OSCILLATION_LOWVOL |

#### 核心函数
```python
validate_regime_consistency(
    records: list[RegimeTradeRecord],
    min_positive_regimes: int = 2,
    max_dominant_share: float = 80.0,
) -> RegimeValidationResult

validate_from_perf_slices(perf_by_regime: dict[str, float]) -> RegimeValidationResult
regime_check_passes(records, min_positive_regimes=2) -> bool
```

---

### 2.3 Q5 — Temporal Stability ✅

**文件**: `src/utils/q5_temporal_validator.py`  
**作者**: 墨萱  
**状态**: ✅ 已实现  
**测试**: ✅ 含单元测试

#### 功能
检查策略收益/IC 在时间维度上的一致性：
- 将回测期均匀切分为 4 个年度子窗口
- 检查各子窗口的收益/IC 方向一致性
- 方向相反且幅度 ≥ 1% 标记为 TEMPORAL_INCONSISTENCY
- 复用 existence_validator.py 的 TradeRecord 数据结构

#### 核心函数
```python
validate_temporal_stability(
    trades: list[TradeRecord],
    direction_threshold: float = 0.01,
) -> TemporalStabilityResult

is_temporally_consistent(trades) -> bool
```

#### 数据结构
```python
@dataclass
class TemporalStabilityResult:
    is_stable: bool
    confidence: float
    windows: list[WindowStats]
    dominant_direction: str
    inconsistent_windows: list[int]
    inconsistency_severity: float
    details: dict
    fail_reason: Optional[str]
```

---

### 2.4 Q8 — Failure Attribution Engine ✅

**文件**: `src/utils/q8_failure_attribution.py`  
**作者**: 墨衡  
**状态**: ✅ 已实现  
**测试**: ✅ 含单元测试

#### 功能
分析 Q_FAILURES 数据库记录的策略失败数据：
1. **失败类型排行**：各类失败出现的总次数和占比
2. **复发检测**：同一策略同一失败类型是否反复出现
3. **策略失败画像**：特定策略的失败模式分布
4. **按市场状态聚合**：不同市场状态下的失败模式差异
5. **归因报告**：综合分布统计 + 复发检测 + 策略画像

#### 核心类
```python
class FailureAttributionEngine:
    def compute_distribution() -> FailureTypeDistribution   # 分布统计
    def detect_recurrence() -> list[RecurrencePattern]       # 复发检测
    def strategy_summary(sid) -> StrategyFailureSummary      # 策略画像
    def generate_report() -> FailureAttributionReport        # 全库报告
```

---

### 2.5 Q9a — Q_FAILURES（正式审计失败数据库）✅

**文件**: `src/utils/q_failures_db.py`, `src/utils/q9a_failure_registry.py`  
**存储**: `mozhi_platform/q_failures/q_failures.db` (SQLite)  
**作者**: 墨衡  
**状态**: ✅ 已实现

#### 功能
- 记录所有 Quality Gate (G1/G2/G3) 和 Q层验证器发现的审计失败
- 作为"可信度审计账本 (账本B)"的核心存储组件
- 与 KnowledgeBridge 形成镜像互补（KB 记录"什么成功"，Q_FAILURES 记录"什么失败"）

#### failure_type 枚举
```
STATISTICAL_NOISE  — Q1: 统计噪声
PARAMETER_PEAK     — Q2: 参数尖峰
REGIME_BOUNDED     — Q3: 单一市场状态
CAPACITY_LIMITED   — Q4: 资金容量不足（预留）
TEMPORAL_DECAY     — Q5: 时间漂移
OOS_FAILURE        — Q6: 样本外失效
LOW_CONFIDENCE     — Q7: 置信度不足（预留）
HUMAN_REJECTED     — G3: 人工复审不通过
EDGE_CASE          — 兜底
```

#### 核心类
```python
class QFailuresDB:     # 数据库管理器（CRUD）
class Q9aFailureRegistry:  # 查询引擎（聚合统计 + 趋势分析 + 复发检测）
```

---

### 2.6 Q9b — RESEARCH_FAILURES（全量研究失败数据库）✅

**文件**: `research_failures/q9b_research_failures.py`  
**文件**: `src/utils/research_failures_schema.py`  
**存储**: `research_failures/records/{failure_id}.json` (JSON 文件)  
**作者**: 墨衡 + 墨萱  
**状态**: ✅ 已实现

#### 功能
- 记录所有研究过程中产生的失败（人工复盘、元研究发现的模式性失败）
- 独立于 Q9a 的数据结构，通过 strategy_id + failure_id 交叉引用

#### 新增枚举类型（Q9b 专有）
```
VETO_FAILURE       — Owner 否决
DATA_ISSUE         — 数据问题（幸存者偏差等）
METHODOLOGY_BIAS   — 方法论偏见（前视偏差等）
```

#### 核心类
```python
class ResearchFailuresDB:        # JSON 文件管理器
class ResearchFailuresRegistry:  # SQLite 数据库管理器（含交叉引用）
```

---

### 2.7 G1 — Existence Gate ✅

**文件**: `src/utils/gate_integration.py`  
**作者**: 墨衡  
**状态**: ✅ 已实现（G1/G2/G3 写入 Q9a 集成）

#### 功能
- G1 失败 → 自动写入 failure_type=STATISTICAL_NOISE, discovered_by="Q1"
- G2 失败 → 自动写入 failure_type=PARAMETER_PEAK, discovered_by="Q2"
- G3 失败 → 自动写入 failure_type=HUMAN_REJECTED, discovered_by="G3"

#### 核心类
```python
class GateToQ9aIntegration:
    @staticmethod
    def from_existence_result(sid, fail_reasons, ...) -> tuple[str, str]
    def record_g1_failure(...) -> str
    def record_g2_failure(...) -> str
    def record_g3_failure(...) -> str
    def record_failure(...) -> str  # 通用写入
```

---

## 三、已实现模块关系图

```
Q1 (existence_validator.py)
    │
    ├── G1 Gate ── FAIL ──→ GateToQ9aIntegration.record_g1_failure()
    │                              │
    │                              ▼
    │                       Q9a Q_FAILURES (q_failures.db)
    │                              │
Q3 (q3_regime_validator.py)        │
    │                              ├── Q8 Attribution (q8_failure_attribution.py)
Q5 (q5_temporal_validator.py)      │       │
    │                              │       └── 聚合分析 → 复发检测 → 报告
    ├── G3 Gate ── FAIL ──→ GateToQ9aIntegration.record_g3_failure()
    │                              │
    │                              ▼
    │                       Q9b RESEARCH_FAILURES (JSON files)
    │                              │
    └─────────── 交叉引用 ─────────┘
```

---

## 四、待实现模块

| 模块 | 优先级 | 工时 | 说明 |
|:----:|:------:|:----:|:-----|
| **Q2 Robustness** | P0 | 2.0天 | 参数地形分析，PlateauScore 计算，最优参数孤立检测 |
| **Q4 Capacity** | P0 | 1.0天 | 资金容量评估，模拟多规模级下边际收益衰减 |
| **Q6 OOS** | P1 | 1.5天 | 样本外生存率分析，Walk-Forward 验证 |
| **Q7 Rating** | P1 | 1.0天 | 6 维评分聚合 → 复合 R → A~F 评级 + 瓶颈分析 |
| **G2 Gate** | P0 | 0.5天 | Robustness Gate 门禁集成 |
| **集成测试** | P0 | 0.5天 | 端到端链路测试（Phase 1） |

---

## 五、文件清单

| 文件 | 模块 | 大小 |
|:-----|:----:|:----:|
| `src/utils/existence_validator.py` | Q1 | ✅ |
| `src/utils/q3_regime_validator.py` | Q3 | ✅ |
| `src/utils/q5_temporal_validator.py` | Q5 | ✅ |
| `src/utils/q8_failure_attribution.py` | Q8 | ✅ |
| `src/utils/q9a_failure_registry.py` | Q9a | ✅ |
| `src/utils/q_failures_db.py` | Q9a DB | ✅ |
| `src/utils/gate_integration.py` | G1/G2/G3 | ✅ |
| `research_failures/q9b_research_failures.py` | Q9b | ✅ |
| `src/utils/research_failures_schema.py` | Q9b Schema | ✅ |
| `src/utils/q_failures_db.py` | Q9a DB | ✅ |
| `scripts/test_phase1_integration.py` | 集成测试 | ✅ |

---

## 六、修订历史

| 版本 | 日期 | 变更内容 | 作者 |
|:----:|:----:|:---------|:----:|
| v1.0 | 2026-05-19 | 初始版本，记录 Phase 1 完成状态 | 墨衡 |
