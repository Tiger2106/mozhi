# 编码流程 v1.3 - 完整版(含 Phase P0 拆分阶段)

**文档状态**: signed · **版本**: v1.3 · **作者**: mohan · **日期**: 2026-05-31
**文件名**: `coding_process_v1.3.md`（由 `v1.1` 重命名以匹配文档内版本号）
**签署链**: 墨萱 ✅ → 玄知 ✅ → 墨涵 ✅ → 墨衡 ✅ → Owner ✅
**同步自**: `coding_responsibility_code_of_conduct_v1.2.md` 三项新增规则

---

## 1. 流程全景图

`
                   ┌──────────────┐
                   │  任务到达     │
                   │  (需求/设计)  │
                   └──────┬───────┘
                          ↓
                   ┌──────┴──────┐
                   │  Phase P0   │
                   │  墨衡起草    │
                   │  .split_draft│
                   └──────┬──────┘
                          ↓
                   ┌──────┴──────┐
                   │  Phase P0.5 │
                   │  墨萱复核    │
                   └──────┬──────┘
                          ↓
                   ┌──────┴──────┐
                   │  Phase P0.8 │
                   │  墨萱锁定    │
                   │  墨涵调度脚本│
                   └──────┬──────┘
                          ↓
                   ┌──────┴──────┐
                   │  P0.9       │
                   │  墨涵自检脚本│
                   │  (7项核验)   │
                   └──────┬──────┘
                          ↓
                   ┌──────┴──────┐
                   │  玄知脚本审查│
                   └──────┬──────┘
                          ↓
                   ┌──────┴──────┐
                   │  Stage 1    │
                   │  编码(按    │
                   │  sub_task   │
                   │  串行)      ├───────── 小循环 ─┐
                   ├──────┬──────┤                │
                   │  Stage 1.5 │                │
                   │  自检(每    │                │
                   │  sub_task) │                │
                   ├──────┬──────┤                │
                   │  Stage 2   │                │
                   │  墨萱审查   │                │
                   │  (每sub_task)│               │
                   └──────┬──────┘                │
                          ↓                       │
                   ┌──────┴──────┐                │
                   │  Stage 3~5  │                │
                   │  架构审查→ │                │
                   │  归档→签署  │                │
                   └─────────────┘                │
                                                   │
                   (小循环: stage_1 → 1.5 → 2 → 下一sub_task)
`

---

## 2. 阶段定义

### Phase P0 - 拆分方案起草

**执行者**: 墨衡
**输入**: 细化方案(设计文档 §6)或任务需求
**耗时**: <15min(纯拆分方案起草)
**超时熔断**: 15min 无响应 → 告警 Owner
**产出**: `schedules/split_draft_{task_id}.json`

**拆分原则**:
- 编码子任务 **≤ 15min**(BT-001)
- 测试子任务 **≤ 30min**(BT-009,尽量接近 15min)
- 依赖关系 DAG,无环
- 每项标注 `type`(coding/test)、`affected_files` 和 `acceptance_criteria`
- 正交性:子任务间不重叠

**`.split_draft` 格式**:

```json
{
  "meta": {
    "parent_task": "<task_id>",
    "title": "P0 拆分方案",
    "source_doc": "<设计文档路径>",
    "created_by": "moheng",
    "created_at": "<ISO8601>",
    "total_estimated_min": <sum>,
    "status": "draft"
  },
  "sub_tasks": [
    {
      "id": "<task_id>_001",
      "type": "coding",          # coding | test
      "description": "一句话描述",
      "details": "实现细节 / 算法",
      "estimated_min": 12,
      "dependencies": [],
      "affected_files": ["src/.../file1.py"],
      "acceptance_criteria": "具体可验证标准"
    }
  ]
}
```

---

### Phase P0.5 - 拆分复核

**执行者**: 墨萱
**输入**: `.split_draft`
**产出**: PASS / REJECT(标注问题项)

**7项检查清单**:

| # | 检查项 | 通过条件 |
|:-:|:------|:---------|
| Q1 | 完整性 | 所有改动点被覆盖,无遗漏 |
| Q2 | 正交性 | 子任务无功能重叠,可顺序合并 |
| Q3 | 粒度 | coding 子任务 ≤ 15min,test 子任务 ≤ 30min,大项已进一步拆分 |
| Q4 | 依赖合理性 | DAG 无环,依赖方向正确 |
| Q5 | 验收标准 | 每项有具体可执行标准(非"完成") |
| Q6 | 文件范围 | affected_files 完整覆盖 |
| Q7 | 可测性 | 每项可独立验证 |

**判定**:
- 全部 PASS → **PASS**
- 任一 FAIL → **REJECT**,标注问题 + 修改要求,退回墨衡
- 退回重交上限 **3 次**,超限告警 Owner 裁决

---

### Phase P0.8 - 锁定 + 调度

**执行者**: 墨萱(锁定)→ 墨涵(调度中心)
**输入**: PASS 的 `.split_draft`
**产出**: `.split_final` + 调度脚本

**锁定流程(墨萱)**:
1. 确认 `.split_draft` 已通过 P0.5 复核
2. 将 `meta.status` 改为 `"locked"`
3. 保存为 `schedules/split_final_{task_id}.json`

**调度流程(墨涵)**:
1. 读取 `split_final_{task_id}.json`
2. 调用 `generate_pipeline_script.py` 生成 TMPL-005 调度脚本
   - 每个 sub_task 作为一个编码阶段(stage_1_XXX)
   - 按 dependencies 顺序串行排列
   - 每个编码阶段后紧跟自检阶段(stage_1.5_XXX)
3. 写入 `schedules/coding_pipeline_{task_id}.json`
4. 进入 P0.9 自检

---

### Phase P0.9 - 调度脚本自检(墨涵)

**执行者**: 墨涵
**输入**: 生成的调度脚本
**产出**: PASS / FAIL

**7项机械核验清单**(墨涵不判断调度逻辑合理性,只校验形式正确性):

| # | 检查项 | 通过条件 |
|:-:|:------|:---------|
| M1 | **JSON 格式** | 可解析,无语法错误 |
| M2 | **文件路径存在** | 所有 state_file、.done 路径的目录已创建 |
| M3 | **分支覆盖完整** | 每个 stage 的 dynamic_next 包含 SUCCESS / FAILURE / REJECT / default 分支 |
| M4 | **依赖一致性(双向)** | 所有 stage_X.done 在 deps 中有对应声明,且所有 deps 引用的 stage 在 pipeline 中有对应定义 |
| M5 | **MD5 自签名** | 生成时写入脚本 MD5,自检时重新计算对比(防窜改) |
| M6 | **状态文件初始化** | 对应的 pipeline_state.json 已创建并包含初始结构 |
| M7 | **无重复 stage ID** | 所有 stage 的 ID 唯一,无重名 |

**判定**:
- 全部 PASS → **PASS**,交给玄知审查
- 任一 FAIL → **FAIL**,修复生成器或重跑生成后再次自检

---

### 脚本审查(玄知)

**执行者**: 玄知
**输入**: 调度脚本
**产出**: PASS / CONDITIONAL_PASS / REJECT
**检查**: dynamic_next 分支完整性、状态文件一致性、超时配置

**回退路径(REJECT 时)**:
- REJECT → 退回**墨涵**(不是墨衡),重新生成或修正调度脚本
- 重交上限 **3 次**,超限告警 Owner 介入
- 若脚本层面无法修复(如拆分方案设计缺陷),墨涵启动 Phase P0 重做流程

---

### Stage 1 - 编码

**执行者**: 墨衡

**编码边界定义**（遵循 `coding_responsibility_code_of_conduct_v1.2.md` 规则1）：
- **属于编码**：修改 `.py` 文件逻辑、SQL 语句、测试用例、数据管线代码等影响系统行为的操作
- **不属于编码**（PO 正常职责）：编写规约文档、JSON 配置、目录整理、管理配置文件、执行已存在的命令

调度脚本包含多个编码阶段 `stage_1_001, stage_1_002, ...`,墨衡按顺序逐一执行,每个对应一个 sub_task。单 sub_task 编码完成后进入对应的 Stage 1.5 自检。

**回退路径(Stage 1.5 FAIL → Stage 1)**:
- 墨衡自检 FAIL 后,回退对应 sub_task 的 Stage 1 编码阶段
- 循环上限 **2 次**(与 Stage 2.5 一致),第 3 次告警 Owner
- 不影响其他已完成 sub_task 的状态

**输出**: 代码文件 + `.done`
**超时**: **每子任务** 30min 自动熔断 + 告警 Owner
**说明**: 若分出 N 个子任务,总编码时间 = N × 实际编码时间(串行),超时基准按每子任务独立计算

---

### Stage 1.5 - 自检

**执行者**: 墨衡

**Q1~Q6 检查清单**(TMPL-006):
- Q1 功能性完整性
- Q2 接口兼容性
- Q3 测试覆盖
- Q4 错误处理
- Q5 基线回归
- Q6 文档完整

**输出**: `self_check_pass_{sub_task_id}.json` + `.done`(单子任务时 `sub_task_id` 可省略)
**超时**: 20min(基础)+ 5min(弹性)

**动态跳转**: 通过后进入 **Stage 2(墨萱审查)** 而非直接进入下一子任务

---

### Stage 2 - 代码审查(墨萱) — 小循环内

**执行者**: 墨萱
**触发**: 每个 sub_task 的 Stage 1.5 自检通过后立即执行
**输入**: 单个 sub_task 的代码

**复核通过的客观标准**（遵循 `coding_responsibility_code_of_conduct_v1.2.md` 规则2）：

| 标准 | 说明 | 触发动作 |
|:----|:-----|:---------|
| ① 阻断问题清零 | Review 发现的所有阻断问题已关闭或明确标记已修复 | 复核人逐项确认 |
| ② 测试覆盖率 | 新增代码至少跑通单元测试（不引入新的失败用例） | 展示测试输出 |
| ③ 无静默失败路径 | 代码中不存在"执行了但不报错但结果为空/错误"的路径 | Review 时逐条审查异常路径 |

**审查结论记录**：须记录审查结论，包括发现的问题及通过理由。不得走过场。

审查每个 sub_task 的代码(按 Stage 1 → 1.5 → 2 的小循环串行)。如果审查 FAIL：
- 回退到对应 sub_task 的 Stage 1 编码阶段(小循环重走)
- 循环上限 **2 次**,第 3 次告警 Owner
- 不影响其他已完成 sub_task 的状态

**模板**: TMPL-004
**输出**: PASS / REJECT
**超时**: 15min → 可延至 30min

**动态跳转**: 通过后进入下一 sub_task 的 Stage 1 编码(或全部完成后进入 Stage 3 架构审查)

---

### Stage 2.5 - 修复(仅回退路径) — 小循环内
**输出**: 修复后代码 + 回归验证
**说明**: 回退到对应 sub_task 的 Stage 1 编码阶段,重走 **Stage 1 → 1.5 → 2** 小循环
**循环上限**: 2 次 → 第 3 次告警 Owner 介入

---

### Stage 3 - 架构审查(玄知) — 小循环外,合流审查

**执行者**: 玄知
**触发**: 所有 sub_task 的 Stage 2 审查全部通过后
**范围**: 整体架构一致性、所有 sub_task 的协同与合流、版本兼容、全路径验证
**说明**: 此时各 sub_task 已在小循环内经过墨衡自检+墨萱审查,Stage 3 侧重合流后的架构整体性
**输出**: PASS / CONDITIONAL_PASS / REJECT
**超时**: 15min

**回退路径(REJECT 时)**:
- REJECT → 退回 Stage 2(墨萱代码审查),由墨萱定位具体代码问题后重新审查
- 若架构缺陷涉及重大设计变更(如不兼容的接口变更),退回对应的 sub_task Stage 1 编码阶段(触发小循环重走)
- 循环上限 **2 次**,第 3 次告警 Owner

---

### Stage 4 - 知识归档(墨涵) — 小循环外

**执行者**: 墨涵
**输出**: KID draft(草稿)
**检查**: insight_summary 准确性、confidence 定级(引用回测数据)
**超时**: 5min

**失败路径(FAIL 时)**:
- FAIL → 退回对应 sub_task 的 Stage 2(小循环代码审查),补充数据或修正描述后
- 若知识本身质量不达标(如 confidence 无法支撑定级),标记为 draft 不激活,通知 Owner 决定是否降级丢弃

---

### Stage 5 - Owner 签署

**执行者**: Owner
**范围**: 业务方向确认
**签署后**: KID 激活 + 归档闭环

---

## 4. 墨涵调度中心定义

在整个流程中,墨涵的角色限定为 **7 原子动作**(v1.0 的 5 原子 + 2 新增):

| # | 动作 | 说明 | 场景 |
|:-:|:----|:-----|:----|
| 1 | **读 dynamic_next** | 按 .done 存在性机械匹配分支(先试 SUCCESS,再 FAILURE,再 REJECT,最后 default),**不做逻辑判断** | 每步推进前 |
| 2 | **读 .split_final** | 读子任务清单 | P0.8 |
| 3 | **查文件** | 检查 .done 是否存在 | 每次推进前 |
| 4 | **写状态** | 更新 pipeline_state.json | 每步完成后 |
| 5 | **调 spawn** | spawn 子 agent | 每步启动时 |
| 6 | **调生成器** | 调用 generate_pipeline_script.py | P0.8 |
| 7 | **自检脚本** | 7项机械核验(M1~M7) | P0.9 |

## 5. 约束清单(全文覆盖)

| 编号 | 约束 | 来源 |
|:----|:----|:----:|
| BT-001 | 编码子任务 ≤ 15min | 已编码 |
| BT-002 | 不考虑抽象 | 已编码 |
| BT-003 | 方案细化后编码 | 已编码 |
| BT-004 | 只打回不代修 | 已编码 |
| BT-005 | 输入输出完整性校验 | 已编码 |
| BT-006 | 墨涵不做判断 | 已编码 |
| BT-007 | 重复代码提取 | 已编码 |
| BT-008 | 报告验证≥基-复差值2% | 已编码 |
| **BT-009** | **测试子任务 ≤ 30min(尽量接近 15min)** | **本规范新增** |
| GP-001 | 始于 Why | 已编码 |
| GP-002 | 支持可复现性 | 已编码 |
| GP-003 | 两步验证法 | 已编码 |
| GP-004 | 决策异议升级 | 已编码 |
| GP-005 | 问题定义优先 | 已编码 |
| **P0-002** | **三权分离(方案/审核/调度)** | **本规范新增** |
| **P0-003** | **.split_final 锁定后不可修改** | **本规范新增** |
| **P0-004** | **墨涵自检 7 项机械核验(M1~M7)** | **本规范新增** |
| **P0-005** | **P0.5 退回重交上限 3 次,超限告警 Owner** | **本规范新增** |
| **P0-006** | **脚本审查 REJECT 退回墨涵重生成,上限 3 次** | **本规范新增** |
| **CR-001** | **墨涵不代行编码（墨衡不可用时暂停上报）** | **职责规约 v1.2** |
| **CR-002** | **所有代码须经独立 Review + 复核方可合并** | **职责规约 v1.2** |
| **CR-003** | **复核通过须满足三项客观标准（阻断清零/测试覆盖/无静默失败）** | **职责规约 v1.2** |

---

### 超时汇总表

| 阶段 | 超时 | 超限动作 |
|:----|:----:|:---------|
| Phase P0 (拆分起草) | 15min | 告警 Owner |
| Phase P0.5 (拆分复核) | 10min | 告警 Owner |
| Phase P0.8 (锁定+调度) | 5min | 告警 Owner |
| Phase P0.9 (墨涵自检) | 3min | 告警 Owner |
| 脚本审查(玄知) | 10min | 告警 Owner |
| Stage 1(每子任务) | 30min | 熔断 + 告警 Owner |
| Stage 1.5(每子任务) | 25min | 熔断 + 告警 Owner |
| Stage 2(墨萱审查) | 15min(可延30min) | 告警 Owner |
| Stage 2.5(修复) | 15min | 告警 Owner |
| Stage 3(玄知架构) | 15min | 告警 Owner |
| Stage 4(墨涵知识) | 5min | 告警 Owner |
| Stage 5(Owner) | 无限制 | - |

**超时常数统一存储位置**:`pipeline_state.json` 中 meta 字段,调度脚本生成时自动写入。

### TMPL-005 调度脚本参考片段

```json
{
  "task_id": "fix_xxx",
  "pipeline": [
    {
      "stage": "stage_1_001",
      "agent": "moheng",
      "task": "编码 sub_task_001",
      "timeout_min": 30,
      "deps": [],
      "dynamic_next": {
        "SUCCESS": "stage_1.5_001",
        "FAILURE": "stage_1_001",
        "default": "__OWNER__"
      }
    },
    {
      "stage": "stage_1.5_001",
      "agent": "moheng",
      "task": "自检 sub_task_001",
      "timeout_min": 25,
      "deps": ["stage_1_001.done"],
      "dynamic_next": {
        "SUCCESS": "stage_2_001",
        "FAILURE": "stage_1_001",
        "REJECT": "__OWNER__",
        "default": "__OWNER__"
      }
    },
    {
      "stage": "stage_2_001",
      "agent": "moxuan",
      "task": "墨萱审查 sub_task_001",
      "timeout_min": 15,
      "deps": ["stage_1.5_001.done"],
      "dynamic_next": {
        "SUCCESS": "stage_1_002",
        "FAILURE": "stage_1_001",
        "REJECT": "__OWNER__",
        "default": "__OWNER__"
      }
    },
    {
      "stage": "stage_1_002",
      "agent": "moheng",
      "task": "编码 sub_task_002",
      "timeout_min": 30,
      "deps": ["stage_2_001.done"],
      "dynamic_next": {
        "SUCCESS": "stage_1.5_002",
        "FAILURE": "stage_1_002",
        "default": "__OWNER__"
      }
    }
  ]
}
```

**dynamic_next 取值说明**:
- `stage_X` → 跳到对应阶段
- `"__OWNER__"` → 告警 Owner,流程暂停
- `null` → 流程终止

---

## 6. 依赖文件清单

| 文件 | 位置 | 用途 |
|:----|:-----|:-----|
| `.split_draft` | `schedules/split_draft_{task_id}.json` | 墨衡拆分草案 |
| `.split_final` | `schedules/split_final_{task_id}.json` | 锁定后的拆分方案 |
| 调度脚本 | `schedules/coding_pipeline_{task_id}.json` | TMPL-005 格式 |
| 状态文件 | `schedules/pipeline_XXXX_state.json` | 流水线状态 |
| Stage N .done | `signals/tasks/{task_id}_stage_N.done` | 阶段完成信号 |
| KID | `knowledge_entries/{draft\|active}/KID-*.json` | 知识条目 |

---

## 7. 变更记录

| 版本 | 日期 | 作者 | 变更 |
|:---:|:----|:-----|:-----|
| v1.0 | 2026-05-28 | mohan | 初始发布(签署归档:coding_process_v1.0.md) |
| **v1.1** | **2026-05-28** | **mohan** | Owner简化后更新：全任务强制走Phase P0（去条件分支）+ 移除对比表§3 + 统一单线性流程 |
| **v1.3** | **2026-05-31** | **mohan** | **同步职责规约 v1.2 三项：编码边界定义、复核通过客观标准(阻断清零/测试覆盖/无静默失败)、审查结论记录要求 + 约束清单新增 CR-001~003** |

---

_文档基于 coding_process_v1.0.md + coding_process_phase_p0_v0.1.md 合并梳理。
同步自 coding_responsibility_code_of_conduct_v1.2.md。_
