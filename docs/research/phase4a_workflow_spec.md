<!--
author: 墨衡 (moheng)
created_time: 2026-05-19 17:45 +08:00
task_id: phase4a_workflow
version: v1.0
-->

# Phase 4a: 研究流程重构规范

**版本**: v1.0  
**更新日期**: 2026-05-19  
**作者**: 墨衡 (moheng)  
**定位**: 将现有的 P 系列研究流程标准化为 Layer Q 治理兼容的工作流

---

## 一、概述

### 1.1 背景

现有的 P1~P8 研究流程遵循"先研究，后文档"的范式，各阶段缺乏统一的准入/准出标准，导致：

- 研究结果的可重复性无法保证
- Layer Q 治理检查项缺失系统化注入
- 从研究立项到报告产出的路径无标准化脚手框架

Phase 4a 的目标是标准化这一流程，使其与 Layer Q（Transverse Governance Layer）无缝集成。

### 1.2 核心原则

| 原则 | 描述 |
|:-----|:------|
| **双账本补全** | 研究结果写入 P 系列账本（"赚了吗？"），可信度验证写入 Q 层审计账本（"为什么可信？"） |
| **门禁先行** | 研究产出在进入任何正式 Q 层评估前，必须通过 G1 Existence Gate |
| **版本锁定** | 研究产出的数据源版本必须在立项时锁定，避免基线漂移 |
| **分类透明** | 研究报告中的每个数据块必须标注其分类（计算值/观察判断/理论估计） |
| **样本量透明** | n<30 的报告必须在显著位置标注样本量警告 |

---

## 二、标准化流程

### 2.1 全局工作流

```
研究立项
    │
    ▼
┌──────────────────────┐
│ Step 1: 前置条件确认   │  ← 数据源、时间范围、参数空间、版本锁定
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Step 2: 研究执行       │  ← 回测/因子计算/参数扫描
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────┐
│ Step 3: Q 层验证提交               │
│  ├── G1: ExistenceValidator      │
│  ├── Q3: RegimeValidator         │
│  ├── Q5: TemporalValidator       │
│  └── (可选) Q2/Q4/Q6             │
└──────────┬───────────────────────┘
           │
           ▼
┌───────────────────────────────────┐
│ Step 4: 验证结果评估               │
│  ├── PASS → 继续                  │
│  ├── WARN → 记录修改后继续         │
│  └── FAIL → 写入 Q9a + 终止       │
└──────────┬────────────────────────┘
           │
           ▼
┌──────────────────────┐
│ Step 5: 报告生成       │  ← 使用标准化模板填充
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Step 6: 质审核验       │  ← Layer Q Step 4 质量审查
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Step 7: 归档发布       │  ← 写入 KnowledgeBridge + Q_FAILURES
└──────────────────────┘
```

### 2.2 步骤详情

#### Step 1: 前置条件确认（准入）

| 字段 | 必填 | 说明 |
|:-----|:----:|:------|
| `research_name` | ✅ | 研究名称（唯一标识） |
| `data_source` | ✅ | 数据源路径/版本哈希 |
| `date_from` | ✅ | 回测起始日期 |
| `date_to` | ✅ | 回测截止日期 |
| `parameter_space` | ✅ | 参数空间 JSON 描述 |
| `method` | ✅ | 策略方法（grid/trend/reversal/factor） |
| `target_symbol` | ✅ | 标的代码 |
| `q_validators` | ✅ | 必须运行的验证器列表（默认: G1 + Q3 + Q5） |
| `version_lock` | ✅ | 数据源版本锁定签名（SHA256 或 Git hash） |

#### Step 2: 研究执行

按照 P 系列方法论执行研究。每个 P 系列（P1~P8）产出独立的结构化数据文件。

#### Step 3: Q 层验证提交

通过 `Phase4cInterface.submit_for_validation()` 提交验证。

**必须运行的 validators**（默认管线）：

| 验证器 | 门禁 | 优先级 | 说明 |
|:------|:----:|:------:|:-----|
| Q1 ExistenceValidator | G1 | P0 | 存在性验证（6 项检查） |
| Q3 RegimeValidator | — | P0 | 市场状态一致性 |
| Q5 TemporalValidator | — | P0 | 时间稳定性 |
| Q2 RobustnessSurface | — | P1 | 参数稳定性（参数扫描报告适用） |
| Q4 CapacityValidator | — | P1 | 资金容量（策略回测时适用） |
| Q6 OOS Survival | — | P1 | 样本外生存率（多期数据时适用） |

#### Step 4: 验证结果评估

| verdict | 含义 | 操作 |
|:-------:|:-----|:-----|
| PASS | 全部验证通过 | 继续 Step 5 |
| WARN | 轻度问题，非致命 | 记录警告到报告 ⚠️ 块，继续 Step 5 |
| FAIL | 重大验证失败 | 写入 Q9a FAILURE Registry → 终止流水线 |

#### Step 5: 报告生成

使用标准化研究模板（见 `templates/research_template.md`）填充。必须包含：

- 📊 **数据分类块**（报告头部）
- ⚠️ **样本量警告**（n<30 时）
- **Q 层验证结果块**（报告末尾）
- 每个章节的数据块标注（✅/⚠️/🔮）

#### Step 6: 质审核验

由 Layer Q Step 4 质量审查 agent 执行。核验维度：

- 事实准确性（与 Q 验证结果一致）
- 逻辑完整性（论证链条无跳跃）
- 风险披露充分性
- 操作建议合规性

#### Step 7: 归档发布

输出产物：

| 产出 | 路径 | 说明 |
|:-----|:-----|:------|
| 研究报告 | `reports/research/P{n}_{name}_{date}.md` | 标准化模板填充 |
| Q 验证报告 | `reports/validation/{task_id}_q_report.json` | Q 层验证完整结果 |
| KDB 记录 | KnowledgeBridge 集成 | 研究要点入库 |
| Q9a 记录 | `q_failures/q_failures.db` | 仅当 FAIL 发生时写入 |

---

## 三、Q 层验证指标要求

### 3.1 默认管线验证器配置

#### G1 — ExistenceValidator（必选）

| 检查 | 阈值 | 说明 |
|:----:|:----:|:------|
| C1 最小交易数 | N ≥ 30 | 统计显著性门槛 |
| C2 多 Regime 覆盖 | K ≥ 2 | 不在单一市场状态下有效 |
| C3 多年度覆盖 | T ≥ 2 年 | 跨时间周期验证 |
| C4 非单段收益 | 最大占比 < 40% | 不依赖极端单次交易 |
| C5 信号密度 | 年均 ≥ 12 | 低频策略边界标注 |
| C6 样本分布 | 单窗 ≤ 50% | 时间分布均匀性 |

**输出**: `ExistenceResult{exists: bool, confidence: float, fail_reasons: list[str]}`

#### Q3 — RegimeValidator（必选）

| 指标 | 阈值 | 说明 |
|:----:|:----:|:------|
| 正收益状态数 | ≥ 2 | 至少 2 种市场状态下获得正收益 |
| 集中度 | ≤ 80% | 单一状态收益占比不超过 80% |

**输出**: `RegimeValidationResult{passed: bool, positive_regime_count: int, dominant_regime: str, dominant_share_pct: float}`

#### Q5 — TemporalValidator（必选）

| 指标 | 阈值 | 说明 |
|:----:|:----:|:------|
| 年度窗口方向一致性 | ≥ 3/4 | 年度窗口中至少 3 个方向一致 |
| 不一致严重度 | < 1% | 不一致窗口的收益偏差小于 1% |

**输出**: `TemporalStabilityResult{is_stable: bool, confidence: float, inconsistent_windows: list[int]}`

### 3.2 验证器调用优先级

```
提交验证
  │
  ├── ⏩ Q1 (G1 Gate) ── FAIL ──→ 写入 Q9a → 终止
  │         │
  │         PASS
  │         ▼
  ├── ⏩ Q3 (Regime) ── FAIL ──→ 写入 Q9a → WARN（非致命，继续）
  │         │
  │         PASS/WARN
  │         ▼
  ├── ⏩ Q5 (Temporal) ── FAIL ──→ 写入 Q9a → WARN（非致命，继续）
  │         │
  │         PASS/WARN
  │         ▼
  └── 综合报告生成
```

### 3.3 验证结果嵌入报告

每份研究产出的末尾必须包含 Q 层验证结果块：

```markdown
---

## Q 层验证结果

| 验证器 | 结果 | 置信度 | 关键指标 | 备注 |
|:------|:----:|:------:|:---------|:-----|
| G1 Existence | ✅ PASS | 0.85 | C1=30 ✅ C2=3 ✅ C3=2.5 ✅ C4=22% ✅ C5=15 ✅ C6=35%✅ | — |
| Q3 Regime | ✅ PASS | 0.72 | 正收益状态=3/5, 集中度=62% | — |
| Q5 Temporal | ✅ PASS | 0.68 | 4/4 窗口一致 | — |
| **Q 综合评级** | **B** | — | 瓶颈: Q5 | 可接受 |
```

---

## 四、产出格式规范

### 4.1 文件结构

每份研究报告的文件结构（遵循标准化模板）：

```
标题 + 元数据头部
├── ⚠️ 样本量警告（仅在 n < 30 时出现）
├── 📊 数据分类声明（强制性）
├── 章节目录
│   ├── §1 ~ §N 分析章节
│   │   ├── 一阶结论（表格/图表）
│   │   └── 分析解读
│   └── 引用/交叉链接
├── 附录（参数定义/方法论/术语表）
└── Q 层验证结果（强制性尾部块）
```

### 4.2 数据分类标注规范

报告中每个数据块必须标注分类：

| 标签 | 含义 | 使用场景 |
|:----:|:-----|:---------|
| ✅ **回测计算值** | 从回测 JSON/CSV 精确计算 | 净值曲线、指标表、热力图 |
| ⚠️ **观察性判断** | 研究者的定性分析和策略解读 | Observation 块、模式识别 |
| 🔮 **理论估计** | 理论推导/外推/假设性结论 | Brinson 改造、小样本外推 |

### 4.3 元数据头部规范

```markdown
<!--
author: <作者名>
created_time: <ISO8601 时间戳>
task_id: <任务 ID>
version: <版本号>
research_flow_version: <Phase 4a 工作流版本>
preconditions: <前置条件确认文件路径>
q_validators_used: <使用的验证器列表>
-->
```

---

## 五、自动化脚本

### 5.1 脚手架命令

通过 `python -m scripts.research_workflow` 提供的命令：

| 命令 | 功能 |
|:-----|:------|
| `init --name X --method Y --symbol Z` | 初始化新的研究项目 |
| `validate --task_id X` | 提交 Q 层验证 |
| `report --task_id X --template T` | 使用模板生成报告 |
| `status --task_id X` | 查询研究状态 |
| `list` | 列出所有研究项目 |

### 5.2 示例工作流

```bash
# 1. 初始化新的研究项目
python -m scripts.research_workflow init \
    --name "p9_capacity_test_601857" \
    --method "grid" \
    --symbol "601857" \
    --date_from "2026-01-01" \
    --date_to "2026-05-14" \
    --param_space '{"n_levels": [3,5,7], "cooldown": [1,2]}'

# 2. 填充研究内容后提交 Q 层验证
python -m scripts.research_workflow validate \
    --task_id "p9_capacity_test_601857" \

# 3. 生成最终报告
python -m scripts.research_workflow report \
    --task_id "p9_capacity_test_601857" \
    --template "research_template.md"
```

---

## 六、版本兼容性

| 现有模块 | 影响 | 说明 |
|:---------|:----:|:------|
| P1~P8 现有报告 | 无 | 现有报告保持原格式，仅追加 Q 治理补充块 |
| Phase 4c Interface | 调用 | 工作流 Step 3 通过 Phase4cInterface 提交验证 |
| Layer Q 验证器 | 无修改 | 工作流层包装，不改变验证器内部逻辑 |
| KnowledgeBridge | 输出集成 | 研究报告发布时同步写入 KB |

---

## 七、错误处理

| 场景 | 操作 |
|:-----|:------|
| 前置条件不全 | 拒绝立项，返回具体缺失字段 |
| Q 验证失败（G1） | 写入 Q9a + 终止流水线 |
| Q 验证失败（Q3/Q5） | 写入 Q9a + WARN（继续报告生成，但报告标注警告） |
| 模板填充失败 | 回退到纯文本报告，记录错误到日志 |
| 超时 | 180 秒自动超时保护 |

---

## 八、附录

### 8.1 与 P 系列映射关系

| 系列 | 研究类型 | 默认 Q 验证器 |
|:----:|:---------|:--------------:|
| P1 | 收益归因 | G1 + Q3 + Q5 |
| P2 | 风险归因 | G1 + Q3 + Q5 |
| P3 | 参数稳定性 | G1 + Q2 + Q3 |
| P4 | Walk Forward | G1 + Q5 + Q6 |
| P5 | 执行缺口 | G1 + Q3 + Q5 |
| P6 | 仓位风险 | G1 + Q3 |
| P7 | 因子 IC | G1 + Q3 + Q5 |
| P8 | 基准对比 | G1 + Q3 + Q5 |
| P9+ | 扩展研究 | G1 + (新增验证器) |

### 8.2 修订历史

| 版本 | 日期 | 变更内容 | 作者 |
|:----:|:----:|:---------|:----:|
| v1.0 | 2026-05-19 | 初始版本，定义研究流程规范 | 墨衡 |
