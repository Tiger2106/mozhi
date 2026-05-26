# Stage 3 修订计划 — 建议反馈与修改方案

**作者**: 墨衡
**创建时间**: 2026-05-20 11:55 (+08:00)
**任务**: meeting_decouple_20260519_signal_protocol_v1_revision
**参考文件**:
- Stage 3 汇总: `report/meeting/meeting_decouple_20260519_stage3_summary.md`
- 墨萱审阅: `.../stage3_review_moxuan.md`
- 玄知审阅: `.../stage3_review_xuanzhi.md`
- Signal Protocol v1: `docs/05_protocols/signal_protocol_v1.md`
- ADR-004: `docs/adr/ADR-004_architecture_migration.md`

---

## 建议总览

| # | 来源 | 建议 | 裁决 | 修改文件 |
|:-:|:----:|:-----|:----:|:---------|
| 1 | 墨萱 | Phase 0 测试桩优先于功能实现 | ✅ **接受** | ADR-004 §五、执行计划 |
| 2 | 墨萱 | 偏差对账脚本 Phase 1 搭建骨架 | ✅ **接受** | ADR-004 §五、执行计划 |
| 3 | 玄知 | REJECTED 升级为独立生命周期状态 | ✅ **接受** | Signal Protocol v1 §3.1 / §3.2 |
| 4 | 玄知 | 补充 TC-06 测试用例 | ✅ **接受** | Signal Protocol v1 §4.4 |
| 5 | 玄知 | Q3 触发条件设时间锚点 + 量化条件 | ✅ **接受** | ADR-004 §3.3 / Stage 3 汇总 ¥ |
| 6 | 玄知 | extras 预留 quality.* 和 trace.parent_signal_id | ✅ **接受** | Signal Protocol v1 §1.2 |
| 7 | 玄知 | Parquet schema 升级评估 | ✅ **有条件接受** — 记入 Q3 评估清单，v1 不做变更 | ADR-004 §3.3 / Signal Protocol v1 §1.4.2 |

---

## 详细修订方案

### 建议 1: Phase 0 测试桩优先于功能实现

**来源**: 墨萱（3.1 节）
**裁决**: ✅ **接受**

**理由**:
- 完全对齐 Owner D2 "契约先行" 决策。原计划 "Signal Protocol v1 → Interface Freeze → 测试桩 → 开发" 中测试桩的顺序已在架构层面确认，墨萱的建议将这一原则在 Phase 0 内进一步细化为"测试桩先于功能实现"。
- 这是执行层面的优先级细化，不是 scope 扩展，不影响 Level 3 冻结线。

**修改方案**:

修改 `ADR-004` §五、执行计划 → Phase 0 描述。

**原内容**:
```
| Phase 0 | Day 1-2 | Signal Protocol v1 + Serializer | 墨萱测试桩 + 墨涵 knowledge.db schema |
```

**改为**:
```
| Phase 0 | Day 1-2 | ① Signal Protocol v1 + Interface Freeze
                        ② 墨萱测试桩（Signal 序列化/反序列化桩 → knowledge.db schema 桩 → Consumer 接口签验桩）
                        ③ Serializer 实现 | 可执行测试桩（Day 3 可直接验证 Phase 1 产出）|
```

并在 ADR-004 §四 末尾增加一条注释：
> **Phase 0 执行顺序**：协议冻结 → 测试桩（墨萱并行）→ 功能实现（墨衡）。测试桩的验收断言必须先于功能实现，确保 Day 3 进入 Phase 1 时墨衡的产出可以直接通过测试，而非返工。

---

### 建议 2: 偏差对账脚本 Phase 1 搭建骨架

**来源**: 墨萱（3.3 节）
**裁决**: ✅ **接受**

**理由**:
- 5 类偏差中，**Signal 一致率 ≥ 98%** 是核心指标。Phase 1 统一 Signal 产出后即可开始对比，无需等待 Phase 3。
- 尽早搭建对账骨架可获得更长的观察窗口（Phase 1 中期 ~ Phase 3 结束，约 8-10 天），避免 Phase 3 发现偏差后时间不足。
- 不改变各级 Phase 的交付物职责，仅改变对账脚本的搭建时序。

**修改方案**:

修改 `ADR-004` §五、执行计划 → Phase 1 和 Phase 3 的描述。

**Phase 1 新增**（原内容不变，增加注解行）:
```
| Phase 1 | Day 3-7 | 策略重构（统一Signal产出）
                        + **偏差对账脚本骨架搭建（墨萱）**
                        - Signal一致率对比桩先行（最长线指标）
                        - Trade Count / PnL / MaxDD / Timing Drift 对比桩框架 | 墨萱信号一致性测试 |
```

**Phase 3 更新**:
```
| Phase 3 | Day 12-15 | 双系统验证 + 旧代码清理 + **偏差对账详细关联** | 5类偏差验收（阈值执行）+ 降级策略 |
```

---

### 建议 3: REJECTED 升级为独立生命周期状态

**来源**: 玄知（2.2 节）
**裁决**: ✅ **接受**

**理由**:
- 当前 `FILTERED`（风控过滤）是 `CONSUMED` 的子状态（`consumed_{signal_id}.json` → `decision: "FILTERED"`）。这有两个问题：
  1. 风控过滤的信号没有被真正"消费"，放在 CONSUMED 下掩盖了数据流被终端层中断的事实
  2. 风控过滤的归因分析需要从所有消费记录中按 decision 字段检索，无独立目录可遍历，性能差
- 协议 §4.3 策略 C 已定义 `signals/rejected/` 目录用于版本不匹配拒绝，规范上已有先例
- **这不是 scope 扩展**：不新增模块，仅将子状态提升为显式状态，文件结构微调

**修改方案**:

#### 3a. 修改 Signal Protocol v1 §3.1 生命周期状态机

修改状态图，增加 REJECTED 分支，与 CONSUMED 并行：

```
                                 ┌────────────────────────────┐
                                 │         GENERATED           │
                                 │  (Research 端产出Signal)    │
                                 └───────────┬────────────────┘
                                             │
                                             ▼
                                 ┌────────────────────────────┐
                                 │        SERIALIZED           │
                                 │  (写入文件/消息队列，持久化) │
                                 └───────────┬────────────────┘
                                             │
                                             ▼
                                 ┌────────────────────────────┐
                                 │        TRANSMITTED          │
                                 │  (从Research传输到Trading)   │
                                 └──────┬──────────┬──────────┘
                                        │                      │
                                        ▼                      ▼
                          ┌────────────────────┐   ┌──────────────────────┐
                          │      CONSUMED      │   │      REJECTED        │
                          │  (执行/暂存)        │   │  (风控/规则/版本拒绝) │
                          └──────┬─────────────┘   └──────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
        ┌────────────────────┐   ┌────────────────────┐
        │      ARCHIVED      │   │      EXPIRED       │
        │  (成功消费+归档)    │   │  (超时未消费/过期)  │
        └────────────────────┘   └────────────────────┘
```

#### 3b. 新增 Signal Protocol v1 §3.2 中 REJECTED 阶段说明

在 CONSUMED 之后、ARCHIVED 之前插入:

```
#### Stage 4.5: REJECTED

- **触发**: Consumer 端决定不执行该信号，原因包括：
  - **风控过滤**: 风控规则拦截（如持仓上限、杠杆超标、日内回转限制）
  - **规则过滤**: 策略参数限制（如最小置信度阈值、最大持仓期限）
  - **版本不匹配**: Consumer 的 MAJOR ≠ 信号的 MAJOR（见 §4.3 策略 C）
- **操作**:
  - 写入 `signals/rejected/{date}/rejected_{signal_id}.json`，记录拒绝原因
  - 禁止删除或修改原始信号文件
- **拒绝记录格式**:
  ```json
  {
    "signal_id": "<uuid>",
    "consumer": "trading_engine_v1",
    "rejected_at": "2026-05-20T10:31:00+08:00",
    "reason": "RISK_CONTROL / RULE_FILTER / VERSION_MISMATCH",
    "detail": "<拒绝的具体依据, 如持仓已达上限>"
  }
  ```
- **负责人**: Trading 端 SignalConsumer / 风控模块
- **归档**: 拒绝记录保留 90 天（与 ARCHIVED 一致）
- **不可逆**: 一旦标记为 REJECTED，不可重新消费
```

#### 3c. 同步更新 §3.2 CONSUMED 阶段描述

删除原 `CONSUMED` 中关于 `decision: "FILTERED"` 的描述，将过滤逻辑迁移至 REJECTED。

**原内容（CONSUMED 的消费确认示例）**:
```json
{
  "signal_id": "<uuid>",
  "consumer": "trading_engine_v1",
  "consumed_at": "2026-05-20T10:31:00+08:00",
  "decision": "EXECUTED / STAGED / FILTERED",
  "reason": "<若被过滤则记录原因>"
}
```

**改为**：
```json
{
  "signal_id": "<uuid>",
  "consumer": "trading_engine_v1",
  "consumed_at": "2026-05-20T10:31:00+08:00",
  "decision": "EXECUTED / STAGED",
  "reason": "<可选说明>"
}
```

**decision 仅保留 `EXECUTED` 和 `STAGED`，`FILTERED` 移动到 REJECTED 阶段。**

#### 3d. 同步更新 §4.3 策略 C（信号拒绝）

将策略 C 的拒绝写入路径从单个文件定位调整为统一使用 REJECTED 阶段：

**原内容**:
> 2. 写入 signals/rejected/ 下

**行为已对齐** — REJECTED 阶段的 `signals/rejected/` 目录即为策略 C 的写入位置，无需额外修改。

---

### 建议 4: 补充 TC-06 测试用例

**来源**: 玄知（2.3 节）
**裁决**: ✅ **接受**

**理由**:
- 兼容矩阵 §4.1 已描述 "v2 Consumer 消费 v1 信号 → ⚠️ 降级消费（默认值填充）"，但测试用例未覆盖。
- TC-05 只覆盖了 v1.0 Consumer + v1.1 Signal（MINOR 向前兼容），缺了 MAJOR 降级场景。
- 补充 TC-06 可以完整验证降级策略链（策略 A → 策略 B → 策略 C）中的策略 B。

**修改方案**:

在 Signal Protocol v1 §4.4 TC-05 之后追加 TC-06：

```markdown
#### 测试用例 TC-06: MAJOR 降级消费（v2 Consumer 消费 v1 信号）

```
场景: Consumer v2.0 收到 protocol_version="1.0" 的信号
前提: v2.0 协议新增了 Core 字段 "risk_level": "high"（对比 v1.0）
输入:
  { "signal_id": "...", "symbol": "601857",
    "direction": "BUY", "confidence": 0.82,
    "horizon": "short", "signal_type": "trend",
    "timestamp": "2026-05-20T10:30:00+08:00",
    "protocol_version": "1.0",
    "extras": {} }
预期行为:
  - ✅ 触发策略 B（版本降级）
  - ✅ v2.0 新增字段（如 "risk_level"）用协议定义的默认值填充
  - ✅ 8 个 v1.0 Core 字段正确解析
  - ✅ 日志记录 "Signal version 1.0 downgraded to consumer default"
  - ✅ 信号进入 CONSUMED 状态
  - ✅ 若降级后 Core 字段不完整 → 触发策略 C（信号拒绝）
```
```

---

### 建议 5: Q3 触发条件设时间锚点 + 量化条件

**来源**: 玄知（1.3 节）
**裁决**: ✅ **接受**

**理由**:
- 原表述 "当策略 > 10 时" 在 ADR-004 §3.3 和 Stage 3 汇总 ¥ 中均过于模糊，如果 Q3 时策略数仍为 4 个，Level 5 可能无限期搁置，系统在中期面临新瓶颈。
- 时间锚点 + 量化条件是战略级合理性补充，不影响 v1 执行计划。

**注意**: 此变更影响 ADR-004 和 Stage 3 汇总文件，不影响 Signal Protocol v1。

**修改方案**:

#### 5a. 修改 ADR-004 §3.3

**原内容**:
> Q3 再评估：当策略数 > 10 或有跨市场需求时，启动 Signal Store 等扩展

**改为**:
> **Q3 启动评估条件**（任一满足即启动）:
> - **时间锚点**: 2026-09-01 准时进行一次架构健康检查
> - **策略数 ≥ 8**: 启动 Signal Store 设计评估
> - **knowledge.db 写入量 > 10 万条/月**: 启动知识过期治理（v2 TTL）评估
> - **跨市场接入提案出现**: 启动多市场适配器设计评估

#### 5b. 同步更新 Stage 3 汇总 ¥ 节点

修改 §5.2 Q3 待评估项的开头，增加触发条件声明。

---

### 建议 6: extras 预留 quality.* 和 trace.parent_signal_id

**来源**: 玄知（2.4 节）
**裁决**: ✅ **接受**

**理由**:
- 纯文档变更，不涉及 schema 修改，不影响 Core 冻结。
- 成本为零（只加注释行），收益为正（Q3 ML 集成和信号追踪可以自然接入）。
- 符合 extras §1.2 命名空间约定的扩展模式。

**修改方案**:

修改 Signal Protocol v1 §1.2 extras 使用规范中的"v1 预留键"列表。

**原内容**:
```
ml.*            → ML 模型相关
factor.*        → 因子解释
market.*        → 多市场扩展
risk.*          → 风险标注
analyst.*       → 人工注释
```

**改为**:
```
ml.*              → ML 模型相关（feature_importances、model_version、ensemble_weights）
factor.*          → 因子解释
market.*          → 多市场扩展
risk.*            → 风险标注
analyst.*         → 人工注释
quality.*         → 信号质量（predicted_price、signal_score — 预测精度回填）
trace.parent_signal_id  → 信号引用追踪（关联衍生信号与父信号）
```

注：`trace.parent_signal_id` 因是单一键非命名空间，不适用 `.*` 后缀，直接列出键名。

---

### 建议 7: Parquet schema 升级评估

**来源**: 玄知（2.4 节 — 建议三）
**裁决**: ✅ **有条件接受**

**条件**: v1 不做 schema 升级。在 Q3 评估清单中纳入此议题。

**理由**:
- `extras` 序列化为 `STRING(JSON)` 是 v1 阶段在灵活性与结构化之间的合理取舍
- 当前信号量级下（日频、4 策略、单市场），JSON 字符串解析性能不是瓶颈
- 升级到 `STRUCT` 是破坏性变更 — 现有 parquet 文件需要迁移，Consumer 端需要更新 schema
- 正确时机是 Q3 评估 Signal Store 时一并判断

**修改方案**:

在 Signal Protocol v1 §1.4.2 Parquet 末尾增加一条**未来评估备注**：

```markdown
**备注（v1 阶段）**: extras 当前序列化为 `STRING(JSON)` 以保证灵活性。如果 Q3 评估确认以下条件，应重新评估是否需要升级到 `STRUCT` 或 `MAP` 类型：
- 日 signal 写入量 > 10 万条
- 分析查询中 JSON 字符串解析成为性能瓶颈
- 有持续的历史信号分析需求（如 ML 训练数据准备）

届时升级方案：
1. 新增 parquet schema v2，extras 变为 `STRUCT`，同步递增 protocol_version
2. 旧 parquet 文件按需转换（非强制）
3. Consumer 端根据 `protocol_version` 选择解析路径
```

同时在 ADR-004 §3.3 Q3 评估清单中增加一条：
- **Parquet schema 升级评估**: extras 从 `STRING(JSON)` 到 `STRUCT`，在 Signal Store 评估时一并判断

---

## 修改汇总清单

| # | 文件 | 修改内容 | 修改类型 | 与 scope 关系 |
|:-:|:----|:---------|:--------:|:-------------:|
| 1 | ADR-004 §五 | Phase 0 描述细化执行顺序 | 文档澄清 | Level 3 内优化 |
| 1 | ADR-004 §四 | 新增 Phase 0 执行顺序注释 | 文档补充 | Level 3 内优化 |
| 2 | ADR-004 §五 | Phase 1 新增对账脚本骨架 + Phase 3 措辞调整 | 文档补充 | Level 3 内优化 |
| 3 | signal_protocol_v1.md §3.1 | 状态机图增加 REJECTED 分支 | 协议修订 | Level 3 内优化 |
| 3 | signal_protocol_v1.md §3.2 | 新增 REJECTED 阶段 + 修改 CONSUMED | 协议修订 | Level 3 内优化 |
| 4 | signal_protocol_v1.md §4.4 | 追加 TC-06 测试用例 | 协议补充 | Level 3 内优化 |
| 5 | ADR-004 §3.3 | Q3 触发条件细化（时间锚点+量化条件） | 文档补充 | Level 5 约束层 |
| 5 | stage3_summary.md ¥ | 同步更新 Q3 触发条件 | 文档同步 | Level 5 约束层 |
| 6 | signal_protocol_v1.md §1.2 | extras 预留键补充 quality.* + trace.parent_signal_id | 文档补充 | Level 3 内优化 |
| 7 | signal_protocol_v1.md §1.4.2 | 新增 Parquet 未来评估备注 | 文档补充 | Level 5 约束层 |
| 7 | ADR-004 §3.3 | Q3 评估清单新增 parquet schema 升级条目 | 文档补充 | Level 5 约束层 |

**影响范围判定**（按墨枢 scope 管理制度）:
- ✅ Level 3 内优化（建议 1/2/3/4/6）— 直接执行，无需 ADR
- ⚠️ Level 5 约束层（建议 5/7）— 记入 Q3 评估清单，不修改当前架构

---

## 附录：墨萱协议会签状态更新

**关联**: 墨萱审阅意见 §3.2 — 补充建议中提及墨萱在 Signal Protocol v1 的会签状态为 ⏳ 待签

**说明**: 
- 墨萱审阅意见中明确声明：**会签条件已全部满足**（✅ Core 字段冻结 / ✅ 验证规则完整 / ✅ 兼容性覆盖 / ✅ 测试用例覆盖）
- 本修订计划中建议 3（REJECTED 状态升级）和 4（TC-06 补充）是 v1.0 协议的新增内容，墨萱的状态应在本计划实施后更新为 **✅ 已签**
- 建议墨涵在计划生效后更新协议会签表

**当前会签状态**:

| 签署方 | 角色 | 状态 | 备注 |
|:------|:-----|:----:|:------|
| **墨衡** | 协议起草 | ✅ 已签 | — |
| **墨萱** | 质量门 | ⏳ 待签 | 条件满足，本计划实施后应签署 |
| **墨涵** | 知识归档 | ⏳ 待签 | — |
| **Owner** | 方向确认 | ⏳ 待签 | — |

---

*修订计划完 — 7 条建议全部裁决完毕，3 条涉及 Signal Protocol v1 修改，2 条涉及 ADR-004 修改，2 条跨文件修改*
