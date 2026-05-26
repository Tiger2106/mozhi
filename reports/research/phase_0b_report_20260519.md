<!--
author: 墨衡 (moheng)
created_time: 2026-05-19 16:17 GMT+8
task_id: phase_0b
status: COMPLETED
based_on: unified_reform_plan_v3_20260519.md §2.3
-->

# Phase 0b 执行报告：Q9a Q_FAILURES 基础设施 + 评分标准化

**完成时间**: 2026-05-19 16:17 GMT+8
**执行者**: 墨衡 (moheng) — 深度投资专家 / 审计师

---

## 一、执行摘要

Phase 0b（Q9a Q_FAILURES 基础设施）已完成全部 4 个子任务：

| 子任务 | 工时 | 完成 | 输出文件 |
|:------:|:----:|:----:|:---------|
| 0b-1: Q9a Q_FAILURES 基础设施 | 0.5天 | ✅ | `src/utils/q_failures_db.py` + `q_failures/` 目录 |
| 0b-2: Q9a 查询引擎 | 0.5天 | ✅ | `src/utils/q9a_failure_registry.py` |
| 0b-3: Gate 集成 | 0.3天 | ✅ | `src/utils/gate_integration.py` |
| 0b-4: 评分标准化（拆分） | ~0.5天 | ✅ | `src/utils/confidence_rating.py` |
| **合计** | **~1.8天** | **100%** | **4 个模块文件** |

---

## 二、交付物清单

### 2.0 目录结构
```
C:\Users\17699\mozhi_platform\
├── q_failures\                           # 新创建 — Q9a 失败记录存储
│   └── q_failures.db                     # SQLite 数据库（首次 initialize 时自动创建）
└── src\utils\
    ├── q_failures_db.py                  # 0b-1: 数据库 schema + CRUD
    ├── q9a_failure_registry.py           # 0b-2: 查询引擎 + 聚合统计
    ├── gate_integration.py               # 0b-3: G1/G2/G3 → Q9a 自动写入
    ├── confidence_rating.py              # 0b-4: 评分标准化（A/B/C/D/F）
    └── existence_validator.py            # Phase 0a 输出（依赖引用）
```

### 2.1 0b-1: Q_FAILURES 数据库 (`q_failures_db.py`)

**数据库表 `q_failures` Schema**:
```sql
q_failures (
    failure_id         TEXT PRIMARY KEY,       -- UUID v4
    strategy_id        TEXT NOT NULL,           -- 策略名称/ID
    parameter_set      TEXT NOT NULL DEFAULT '{}', -- JSON 参数集
    failure_type       TEXT NOT NULL CHECK(...),   -- 枚举约束
    regime             TEXT,                    -- 市场状态
    cause              TEXT,                    -- 根因描述
    discovered_by      TEXT NOT NULL,           -- 如 "Q1", "G3"
    confidence_before  REAL,                    -- 失败前置信度
    confidence_after   REAL,                    -- 失败后置信度
    timestamp          TEXT NOT NULL,           -- ISO8601 CST +08:00
    run_id             TEXT,                    -- 关联 trade_engine.db
    report_id          TEXT,                    -- 关联报告
    human_notes        TEXT DEFAULT ''
)
```

**FailureType 枚举**: STATISTICAL_NOISE / PARAMETER_PEAK / REGIME_BOUNDED / CAPACITY_LIMITED / TEMPORAL_DECAY / OOS_FAILURE / LOW_CONFIDENCE / HUMAN_REJECTED / EDGE_CASE

**核心类**:
- `QFailureRecord` — 数据类，含自动 UUID 生成和时间戳
- `QFailuresDB` — 管理器，支持 initialize/insert/insert_batch/get_record/query/count
- 6 个索引覆盖所有查询维度

### 2.2 0b-2: 查询引擎 (`q9a_failure_registry.py`)

**查询能力**:
| 接口 | 功能 | 示例 |
|:-----|:-----|:-----|
| `list_failures(...)` | 多条件检索 | failure_type + strategy_id + regime + 时间范围 |
| `get_by_strategy(id)` | 特定策略全部失败记录 | "grid_601857" |
| `get_by_failure_type(ft)` | 特定失败类型全部记录 | "STATISTICAL_NOISE" |
| `top_failure_types(n)` | Top-N 失败类型 | 百分比 + 涉及策略列表 |
| `strategy_profile(id)` | 单策略失败全景 | 按类型/市场/门控聚合 + 复发检测 |
| `trend_analysis(days, bucket)` | 时间序列趋势 | 方向判定 (up/down/stable) |
| `detect_recurrence(id)` | 复发检测 | 同类型相隔>=30天算复发 |
| `export_to_json(path)` | 全量 JSON 导出 | 可读报表 |

### 2.3 0b-3: Gate 集成 (`gate_integration.py`)

| 方法 | 对应门控 | failure_type | discovered_by |
|:-----|:--------:|:------------:|:-------------:|
| `record_g1_failure(...)` | G1 (ExistenceValidator) | STATISTICAL_NOISE | Q1 |
| `record_g2_failure(...)` | G2 (Robustness) | PARAMETER_PEAK | Q2 |
| `record_g3_failure(...)` | G3 (Multi-Sign) | HUMAN_REJECTED | G3 |
| `record_failure(...)` | 通用（Q3~Q7） | 自定义 | 自定义 |
| `from_existence_result(...)` | 工厂方法 | 自动映射 | 一行调用 |

**集成模式**:
```python
# ExistenceValidator FAIL 分支
from gate_integration import GateToQ9aIntegration
GateToQ9aIntegration.from_existence_result(
    strategy_id="grid_601857",
    fail_reasons=["C1: total_trades=12 < 30", "C4: max_share=0.95 > 0.40"],
)
```

### 2.4 0b-4: 评分标准化 (`confidence_rating.py`)

**ResearchConfidence 枚举**:
| 评级 | 复合 R 范围 | 含义 |
|:----:|:-----------:|:----|
| A | 0.80 ~ 1.00 | 高置信度 — 全维度验证通过 |
| B | 0.65 ~ 0.80 | 中高置信度 — 轻微不足 |
| C | 0.50 ~ 0.65 | 中置信度 — 存在过拟合风险 |
| D | 0.30 ~ 0.50 | 低置信度 — 需要复审 |
| F | 0.00 ~ 0.30 | 极低置信度 — 严重缺陷 |

**评分聚合逻辑**:
- 复合 R = 加权调和平均（短板效应，任一维度过低压低总分）
- C1 硬门禁未通过 → 复合 R ≤ 0.30（自动 F）
- 瓶颈维度 = 评分 < 0.65 的 1~3 个最低维度
- 支持 `from_composite_r(r)` 和 `existence_to_rating(er)` 映射

**双账本设计**:
- 评级属于账本B（可信度审计），独立于账本A（收益指标）
- 研究者不能给自己盖章 → 评级由 ConfidenceAggregator 统一输出

---

## 三、G1 集成验证

Phase 0a 的 `existence_validator.py` 输出 `ExistenceResult{exists, confidence, fail_reasons}`。
Phase 0b 的 `gate_integration.py` 中 `from_existence_result()` 直接将 fail_reasons 映射为 Q9a 记录：

```python
from gate_integration import GateToQ9aIntegration
from existence_validator import validate_existence, TradeRecord, ExistenceResult

# Phase 0a: 验证
result = validate_existence(trades)

# Phase 0b: 失败时自动记录（一行代码）
if not result.exists:
    GateToQ9aIntegration.from_existence_result(
        strategy_id="my_strategy",
        fail_reasons=result.fail_reasons,
    )
```

---

## 四、里程碑 M0.5 完成条件检查

| 完成条件 | 状态 | 验证方法 |
|:---------|:----:|:---------|
| ✅ `q_failures/` 目录存在，数据库表已建 | ✅ | 目录已创建，`initialize()` 自建表 |
| ✅ Q9a 模块支持录入+查询+聚合统计 | ✅ | Top-N / strategy_profile / trend_analysis 均通过测试 |
| ✅ G1/G2/G3 失败结果自动写入 | ✅ | `record_g1_failure()` 等 4 个方法均通过测试 |
| ✅ 验证测试通过 | ✅ | 完整集成测试：DB → 查询 → Gate 集成 → 评级映射 |

---

## 五、下一阶段：Phase 1 可启动

Phase 1 任务清单（参考 `unified_reform_plan_v3_20260519.md §2.4`）：

| # | 任务 | 责任 | 工时 |
|:-:|:-----|:----:|:----:|
| 1.1 | Q3: Regime Validator | 墨衡 | 1.0天 |
| 1.2 | Q5: Temporal Stability | 墨萱 | 0.5天 |
| 1.3 | Q8: Failure Attribution Engine | 墨衡 | 0.5天 |
| 1.4 | G1+G2 门控完善（含 Q9a 写入） | 墨衡 | 0.5天 |
| 1.5 | G3 Multi-Sign Gate 流程 | 墨萱 | 1.0天 |
| 1.6 | Q9b RESEARCH_FAILURES 数据库表+目录 | 墨萱 | 0.3天 |
| 1.7 | Q9b RESEARCH_FAILURES 写入/查询模块 | 墨衡 | 0.2天 |
| 1.8 | 全流程集成测试 | 墨衡+墨萱 | 1.5天 |
| 1.9 | Q层产出文档（含 Q9a+Q9b） | 墨衡 | 0.5天 |
| **合计** | | | **~5.5天** |

**关键前提**:
- ✅ Phase 0a (ExistenceValidator MVP) — 已完成
- ✅ Phase 0b (Q9a Q_FAILURES) — **本次交付完成**
- → Phase 1 可立即启动（Day 3~8 时间线）

---

*本文由墨枢系统（墨衡 v7.2）生成*
*版本: v1.0 | 状态: COMPLETED*
*下一阶段: Phase 1 → 墨衡负责 Q3/Q8/G1+G2 完善 (+2.0天)*
