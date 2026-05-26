# Layer Q 使用指南

author: 墨涵 (mochen)  
created_time: 2026-05-19T16:48:00+08:00  
version: v1.0  
status: READY  
related: layer_q_spec.md, unified_reform_plan_v3_20260519.md

---

## 一、Layer Q 是什么

Layer Q（Transverse Governance Layer）是墨枢的**横向治理层**，独立于 P/B/S/E/R/I 生产层。Q 层不回答"策略赚不赚钱"——那是 P 层的事。Q 层回答的是**"为什么这个研究结论可信？"**

### 核心原则

| 原则 | 含义 |
|:-----|:------|
| **生产者-审计者分离** | P 层生产研究 → Q 层审计可信度 |
| **双账本** | 账本 A（P 层结果）+ 账本 B（Q 层审计记录） |
| **RAW 数据基准** | Q 层以 ORIGINAL RAW DATA 为唯一审计基准 |
| **只读不写** | Q 层不修改 P 层数据，只验证并记录审计结论 |

---

## 二、已有模块速览

| 模块 | 功能 | 位置 | 状态 |
|:-----|:-----|:-----|:----:|
| Q1 ExistenceValidator | 6项存在性检查 | `src/utils/existence_validator.py` | ✅ |
| Q3 Regime Validator | 市场状态覆盖验证 | `src/utils/q3_regime_validator.py` | ✅ |
| Q5 Temporal Validator | 时间稳定性验证 | `src/utils/q5_temporal_validator.py` | ✅ |
| Q4 Capacity Validator | 资金容量评估 | `src/utils/q4_capacity_validator.py` | ✅ |
| Q8 Failure Attribution | 失败归因分析 | `src/utils/q8_failure_attribution.py` | ✅ |
| Q9a Q_FAILURES | 正式审计失败记录 | `src/utils/q_failures_db.py` + `src/utils/q9a_failure_registry.py` | ✅ |
| Q9b RESEARCH_FAILURES | 全量研究失败记录 | `src/utils/research_failures_schema.py` + `research_failures/` | ✅ |
| Q9 Cross Reference | Q9a↔Q9b 交叉引用 | `src/utils/q9_cross_reference_view.py` | ✅ |
| G1 Gate | ExistenceValidator → Q9a | `src/utils/gate_integration.py` | ✅ |
| G2 Gate | Robustness → Q9a | `src/utils/gate_integration.py` | ✅ |
| G3 Gate | 三方会签流程 | `src/pipeline/review_signoff.py` | ✅ |
| 评分标准化 | A/B/C/D/F 评级 | `src/utils/confidence_rating.py` | ✅ |

### 待实现

| 模块 | 功能 | 计划阶段 |
|:-----|:-----|:---------|
| Q2 Robustness | 参数稳定性验证 | Phase 3 |
| Q6 OOS | 样本外存活验证 | Phase 3 |
| Q7 Rating | 置信度聚合评级 | Phase 3 |
| Q层定期评估 | 治理层自身治理 | 季度 |

---

## 三、标准工作流

### 3.1 新策略验证（全链路）

```python
from src.utils.existence_validator import ExistenceValidator
from src.utils.q3_regime_validator import Q3RegimeValidator
from src.utils.q5_temporal_validator import Q5TemporalValidator
from src.utils.gate_integration import GateToQ9aIntegration

# Step 1: 准备交易记录
trades = [TradeRecord(...)]

# Step 2: 存在性验证
validator = ExistenceValidator()
result = validator.validate(trades)

# Step 3: Regime 验证
regime_val = Q3RegimeValidator()
regime_result = regime_val.validate(trades)

# Step 4: 时间稳定性验证
temporal_val = Q5TemporalValidator()
temporal_result = temporal_val.validate(trades)

# Step 5: G1 Gate 自动写入
gate = GateToQ9aIntegration()
gate.from_existence_result(result, strategy_id="S001")
```

### 3.2 单模块快速验证

```python
# 只跑存在性检查 + G1门控
from src.utils.existence_validator import ExistenceValidator
from src.utils.gate_integration import GateToQ9aIntegration

v = ExistenceValidator()
r = v.validate(my_trades)
GateToQ9aIntegration().from_existence_result(r, strategy_id="fast_check")
```

### 3.3 G3 三方会签流程

```python
from src.pipeline.review_signoff import ReviewSignoffManager

mgr = ReviewSignoffManager()
session = mgr.create_session(strategy_id="S001", notes="策略审计")

# 墨萱签署（技术审查）
mgr.sign(session.session_id, signer_id="moxuan",
         step="tech_review", result=True, comment="技术审查通过")

# 墨涵签署（知识审计）
mgr.sign(session.session_id, signer_id="mochen",
         step="knowledge_audit", result=True, comment="知识归档完整")

# Owner签署（业务批准）
mgr.sign(session.session_id, signer_id="owner",
         step="business_approval", result=True, comment="批准执行")
```

---

## 四、Q9 双账本使用指南

### Q9a Q_FAILURES（正式审计失败）

用途：记录 Gate 自动检测到的策略失败，用于可信度治理。

```python
from src.utils.q_failures_db import QFailuresDB

db = QFailuresDB("q_failures/q_failures.db")
# 查询某策略的所有失败
results = db.query_by_strategy("S001")
# 查看 Top-N 失败类型
top_types = db.top_failure_types(n=5)
```

### Q9b RESEARCH_FAILURES（全量研究失败）

用途：记录人工发现的研究失败，用于长期知识积累。

```python
from src.utils.research_failures_schema import ResearchFailuresRegistry

registry = ResearchFailuresRegistry("research_failures/")
# 记录一次研究失败
registry.add_record(
    strategy_name="grid_v1",
    researcher="moheng",
    failure_type_verbose="数据源版本不一致",
    root_cause="akshare 0.9.8→0.9.9 接口变更",
    notes="涉及 P3/P6 两份报告"
)
# 查询该策略的全部失败
records = registry.query(strategy_name="grid_v1")
```

### Q9a↔Q9b 交叉引用

```python
from src.utils.q9_cross_reference_view import Q9CrossReference

xref = Q9CrossReference("q_failures/q_failures.db",
                         registry=ResearchFailuresRegistry("research_failures/"))
result = xref.query_by_strategy("S001")
print(f"双重覆盖率: {result.coverage_stats.coverage_rate:.1%}")
```

---

## 五、评分等级含义

| 等级 | 含义 | 阈值条件 |
|:----:|:-----|:---------|
| A | 高度可信 | 所有 6 项检查通过，confidence ≥ 0.8 |
| B | 可信 | 所有 6 项检查通过，confidence ≥ 0.6 |
| C | 有条件可信 | 1~2 项检查边界未通过但可解释 |
| D | 低可信度 | ≥3 项检查未通过 |
| F | 不可信 | 硬门禁（C1 交易数<30）触发 |

---

## 六、注意事项

1. **数据必须为 RAW 版** — Q 层不接受 MODIFIED 数据作为评分依据
2. **F 级是阻断性的** — 未通过 C1 门槛的策略直接标记 F，不进入后续验证
3. **G3 会签是串行的** — 墨萱→墨涵→Owner，前一步不通过则阻塞后续
4. **Q9a 和 Q9b 不互斥** — 一个策略可以在 Q9a 有记录、Q9b 也有记录，两者独立
5. **Q 层不修改任何数据** — Q 层是只读审计层，笔记记录是唯一的写入操作
6. **重复验证** — 同一策略再次提交时，Q 层检查是否是已有记录的复发
