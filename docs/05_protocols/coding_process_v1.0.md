# 编码流程 v1.1 — 调度脚本驱动

> 作者：墨涵（MiniMax-M2.7）
> 签署：2026-05-27 四方面签（墨衡/墨萱/玄知/Owner）
> 工时调整：2026-05-28 Owner指令（自检50%/审查50%/调度50%）
> 版本变更：v1.0→v1.1 增加调度脚本机制 + 修复墨萱/墨衡/玄知三方审查WARN（2026-05-28）
> 元数据路径：schedules/ | 状态文件：schedules/pipeline_{id}_state.json
> 位置：docs/05_protocols/

---

## 一、核心理念

**问题**：墨涵同时维护"流程调度"和"子任务调度"两条线，状态丢失风险高。

**方案**：细化方案到达后，墨涵先生成结构化调度脚本，玄知审查通过后按脚本执行。墨涵降维为"脚本解释器"——只读脚本+查文件+调spawn，不做独立判断。

```
细化方案抵达
    ↓
Step A  墨涵 → 生成任务调度脚本（JSON结构化文件）
    ↓
Step B  玄知审查脚本（依赖/顺序/工时/产出/循环回退）
    ↓
Step C  通过？ → 按脚本执行为主
    ↓  否
修正脚本后重复 Step B
    ↓
Step D  墨涵按脚本调度：读当前step → 查.done → spawn下一步
```

---

## 二、改动等级定义（P0~P3）

| 等级 | 定义 | 示例 |
|:----:|:----|:-----|
| **P0** | 导致结果错误的阻断性缺陷 | 资金重复扣减、信号方向算反、公式错误 |
| **P1** | 功能不完整的严重问题，影响管线推进 | 缺失核心逻辑、接口不兼容、依赖未处理 |
| **P2** | 边界问题或可绕过的缺陷 | 某参数未覆盖、某标的异常、格式不统一 |
| **P3** | 可推迟的改进项 | 文档完善、代码风格、性能优化 |

---

## 三、调度脚本格式规范（TMPL-005）

### 3.1 文件命名
```
schedules/coding_pipeline_{pipeline_id}_{task_id}.json
```

### 3.2 核心设计：动态状态机脚本

为解决**线性JSON无法表达循环回退**的问题，引入 `dynamic_next` + `branch` 字段，让脚本能通过读取 `.done` 状态决定下一步走向。

```json
{
  "meta": {
    "pipeline_id": "coding_process_v1.1",
    "generated_by": "mohan",
    "generated_at": "ISO8601",
    "task_description": "任务简要描述",
    "version": "1.0",
    "retry_counters": {
      "stage_2_retry": {"key": "stage_2_retry", "max": 2, "description": "Stage 2退修次数计数器"},
      "stage_1_5_failure": {"key": "stage_1_5_failure", "max": 2, "description": "Stage 1.5自检失败次数计数器"}
    },
    "state_file": "schedules/pipeline_{pipeline_id}_state.json"
  },
  "steps": [
    {
      "step_id": "stage_1",
      "step_name": "编码+黄金基线+回归",
      "agent": "moheng",
      "dependencies": [],
      "timeout_min": 30,
      "action": {
        "type": "spawn",
        "task_template": "按TMPL-001格式填写编码任务",
        "inputs": [],
        "expected_outputs": [
          "代码已提交",
          ".done status=SUCCESS",
          "golden_baseline已更新"
        ]
      },
      "output_checks": [
        "check:done_exists|path:stage_1.done",
        "check:field_equals|path:stage_1.done|field:status|value:SUCCESS",
        "check:file_exists|path:golden_baseline_snapshot.json"
      ],
      "rollback": {
        "retry_count": 0,
        "escalate_on_fail": false
      },
      "dynamic_next": "stage_1.5"
    },
    {
      "step_id": "stage_1.5",
      "step_name": "自检（Q1~Q6强制门禁）",
      "agent": "moheng",
      "dependencies": ["stage_1.done"],
      "timeout_min": 20,
      "action": {
        "type": "spawn",
        "task_template": "自检清单模板（见附录 TMPL-006）",
        "expected_outputs": [
          "self_check_pass.json 含 Q1~Q6 完整记录"
        ]
      },
      "output_checks": [
        "check:done_exists|path:stage_1.5.done",
        "check:field_equals|path:stage_1.5.done|field:status|value:SUCCESS"
      ],
      "rollback": {
        "retry_count": -1,
        "escalate_on_fail": false,
        "rule": "不通过则退回Stage 1修正"
      },
      "dynamic_next": {
        "branch_on": "stage_1.5.done.status",
        "SUCCESS": "stage_2",
        "FAILURE": "stage_1",
        "default": "stage_1"
      }
    },
    {
      "step_id": "stage_2",
      "step_name": "回归对比+代码审查",
      "agent": "moxuan",
      "dependencies": ["stage_1.5.done"],
      "timeout_min": 15,
      "action": {
        "type": "spawn",
        "task_template": "TMPL-003 QA验证模板",
        "inputs": ["回归结果", "代码diff"],
        "expected_outputs": [
          ".done status=SUCCESS 或 REJECT",
          "回归报告",
          "CR意见"
        ]
      },
      "output_checks": [
        "check:done_exists|path:stage_2.done",
        "check:field_equals|path:stage_2.done|field:status|value:SUCCESS"
      ],
      "rollback": {
        "retry_count": 2,
        "escalate_on_fail": true,
        "escalation_step": 3,
        "escalation_target": "owner"
      },
      "dynamic_next": {
        "branch_on": "stage_2.done.status",
        "SUCCESS": "stage_3",
        "REJECT": "stage_2.5",
        "default": "escalate_owner"
      }
    },
    {
      "step_id": "stage_2.5",
      "step_name": "退回修复+回归验证",
      "agent": "moheng",
      "dependencies": ["stage_2.done"],
      "timeout_min": 25,
      "action": {
        "type": "spawn",
        "task_template": "修复任务模板（含GP-003回归验证）",
        "inputs": ["墨萱退回意见"],
        "expected_outputs": [
          "修复代码",
          ".done status=RETRY"
        ]
      },
      "output_checks": [
        "check:done_exists|path:stage_2.5.done",
        "check:field_equals|path:stage_2.5.done|field:status|value:SUCCESS"
      ],
      "rollback": {
        "retry_count": 1,
        "escalate_on_fail": true,
        "escalation_step": 3,
        "escalation_target": "owner"
      },
      "dynamic_next": {
        "branch_on": {"from": "pipeline_state.retry_counters.stage_2_retry", "compare": "<"},
        "condition_max": {
          "write_state": {"counter": "stage_2_retry", "action": "increment"},
          "goto": "stage_1.5"
        },
        "reached_max": {
          "goto": "escalate_owner"
        }
      },
      "note": "修复后必须重新走 Stage 1.5 自检 + Stage 2 审查。退修计数器从 pipeline_state.json 读取，墨涵 spawn 前写入。"
    },
    {
      "step_id": "stage_3",
      "step_name": "架构把关",
      "agent": "xuanzhi",
      "dependencies": ["stage_2.done"],
      "timeout_min": 15,
      "action": {
        "type": "spawn",
        "task_template": "架构审查模板",
        "inputs": ["代码变更", "数据指纹", "测试结果"],
        "expected_outputs": [
          ".done status=SUCCESS 或 REJECT"
        ]
      },
      "output_checks": [
        "check:done_exists|path:stage_3.done",
        "check:field_equals|path:stage_3.done|field:status|value:SUCCESS"
      ],
      "rollback": {
        "retry_count": 1,
        "escalate_on_fail": true,
        "escalation_step": 3,
        "escalation_target": "owner"
      },
      "dynamic_next": "stage_4"
    },
    {
      "step_id": "stage_4",
      "step_name": "知识归档+四方会签",
      "agent": "mohan",
      "dependencies": ["stage_3.done"],
      "timeout_min": 5,
      "action": {
        "type": "internal",
        "task": "知识条目创建/更新、四方会签协调"
      },
      "expected_outputs": [
        "归档报告",
        "会签记录"
      ],
      "rollback": {
        "retry_count": 0,
        "escalate_on_fail": false
      },
      "dynamic_next": "stage_5"
    },
    {
      "step_id": "stage_5",
      "step_name": "Owner签批",
      "agent": "owner",
      "dependencies": ["stage_4.done"],
      "timeout_min": 5,
      "action": {
        "type": "notify",
        "message": "编码流程完成，请Owner签批"
      },
      "output_checks": [
        "check:done_exists|path:stage_5.done",
        "check:field_equals|path:stage_5.done|field:status|value:SUCCESS"
      ],
      "rollback": {
        "retry_count": -1,
        "escalate_on_fail": false,
        "rule": "Owner驳回则退回Stage 1"
      },
      "dynamic_next": {
        "branch_on": "stage_5.done.status",
        "SUCCESS": null,
        "REJECT": "stage_1",
        "default": "escalate_owner"
      }
    }
  ],
  "rollback_rules": {
    "max_retries_per_step": 2,
    "escalation_step_threshold": 3,
    "escalation_target": "owner",
    "auto_alert_on_timeout": true,
    "timeout_action": "通知Owner + 暂停流程，等待指示"
  }
}
```

### 3.3 关键设计决策

#### dynamic_next：解决循环回退
- `dynamic_next` 可以是字符串（固定下一步）或对象（条件分支）
- 分支条件读取 `.done` 文件状态或 `pipeline_state.json` 中的计数器
- 每个可回退步骤都必须有 FAILURE/REJECT 分支，不允许未覆盖的回退路径
- 每个 dynamic_next 对象必须包含 `default` 分支作为 catch-all（.done 异常时使用）

#### output_checks：从虚函数名到可执行检查
- 不再使用 `verify_Q1~Q6_all_ok` 这种虚函数名
- 改用结构化检查指令：`check:done_exists|path:XXX`
- 墨涵逐条执行检查，不做主观判断

#### timeout 处理
- `auto_alert_on_timeout: true` — 超时后不自动失败，而是通知Owner
- `timeout_action` 定义超时后的具体处理
- 与 Stage 1 "超时30min拆路"不矛盾：拆路 = 通知Owner + 分拆任务

### 3.4 依赖键格式统一
- 所有依赖统一为 `.done` 文件路径
- `.done` 文件结构始终包含 `status` 字段
- `dynamic_next` 通过读 `.done` 中的 `status` 决定分支
- 不使用 `_with_REJECT` 变体后缀

---

## 四、墨涵调度执行规则

### 4.1 单步执行流程

```
载入脚本 → 找到当前 step
    ↓
读 current_step.output_checks 确认上一步完成
    ↓
检查 meta.retry_counters（如有）
    ↓
检查 current_step.dependencies 全部 .done 且 status=SUCCESS
    ↓
调用 sessions_spawn（按 action.type）
    ↓
等待子agent Announce
    ↓
读 .done 确认 status
    ↓
执行 output_checks 逐项验证
    ↓
全部通过？ → 读 dynamic_next 确定下一步
    ↓  否
按 rollback 规则处理（retry / escalate）
```

**墨涵只做五个原子动作**：
1. **读脚本** — 加载当前 step 定义
2. **查文件** — 检查 .done 和 pipeline_state.json
3. **写状态** — spawn 前更新 pipeline_state.json 中的计数器
4. **调spawn** — 按 action 类型执行
5. **读dynamic_next** — 确定下一步

**不做任何流程判断。**

### 4.2 退修计数器 — pipeline_state.json 独立文件管理

**不从脚本 meta 中维护计数器**。改为独立状态文件，墨涵只做原子写入，不做判断。

#### pipeline_state.json 结构
```json
{
  "pipeline_id": "coding_pipeline_xxx",
  "current_step": "stage_2.5",
  "retry_counters": {
    "stage_2_retry": 0,
    "stage_1_5_failure": 0
  },
  "updated_at": "ISO8601"
}
```

#### 墨涵操作规则
1. **每次 spawn 前**：读 state 文件 → 脚本定义了 `write_state.increment` → 写入递增后的值
2. **不做上限判断**：dynamic_next 的 `branch_on` 自动比对 state 中的值与脚本中的 `max`
3. **不修改脚本**：state 文件是唯一可变的状态载体，脚本是静态的（审查后锁定）
4. **暂停后恢复**：从 state 文件的 `current_step` 读取恢复起点

---

## 五、流程总览

```
Stage 1  墨衡编码（含黄金基线+后端.done+回归）
    ↓
Stage 1.5  墨衡自检（强制门禁，Q1~Q6清单）
    ↓
Stage 2  墨萱回归对比+CR（GP-003: IC<1e-6 / NAV<0.01% + BT合规）
    ↓
Stage 2.5  退回修复+回归验证（≤2次，循环回退至 Stage 1.5）
    ↓
Stage 3  玄知架构把关（综合通道/版本/复现/全通路）
    ↓
Stage 4  墨涵知识归档（含墨萱/玄知/墨涵/Owner 四方会签）
    ↓
Stage 5  Owner签批
```

### 工时基准（2026-05-28 调整后）

| 阶段 | 活动 | 调整系数 | 调整后工时 | 说明 |
|:---:|:----|:--------:|:---------:|:-----|
| Stage 1 | 墨衡编码（含设计） | 100% | 30min | 超时自动拆路+通知Owner |
| Stage 1.5 | 墨衡自检 | 50% | **20min** | 含+5min弹性缓冲 |
| Stage 2 | 墨萱审查 | 50% | **15min** | 严重问题可延长至30min |
| Stage 2.5 | 退回修复（如有） | 100% | **25min** | 含回归验证时间 |
| Stage 3 | 玄知架构把关 | 100% | 15min | 不变 |
| Stage 4 | 墨涵知识归档 | 100% | 5min | 不变 |
| Stage 5 | Owner签批 | 100% | 5min | 不变 |
| **调度** | 各阶段间串行调度 | 50% | **15min** | 总间隙上限 |

---

## 六、Stage 1：墨衡编码

### 职责
1. 编写代码实现需求
2. 跑黄金基线（如适用）
3. 写入 `.done` 文件（含回归基线数据）
4. 确保回归通过的基线版本

### 产出
- 代码变更（git diff / PR）
- 黄金基线快照（golden_baseline_snapshot.json）
- `.done` 状态文件（含 status=SUCCESS）

### 约束
- 编码时间 ≤30min，超时自动拆路 + 通知Owner
- 黄金基线必须更新（P0级改动后）
- 迁移日志必须更新

---

## 七、Stage 1.5：墨衡自检（强制门禁）

### 自检要求

#### Q1 公式正确性—边界值手算验证（6个标准点定义）

6个标准点按以下规则选取（适用于任意数学公式）：

| 序号 | 点类型 | 选取规则 | 示例（y = f(x)） |
|:---:|:------|:---------|:-----------------|
| 1 | **最大值输入** | 输入域的最大有效值 | x = max_allowable |
| 2 | **最小值输入** | 输入域的最小有效值 | x = min_allowable |
| 3 | **零值** | 输入 = 0 | x = 0 |
| 4 | **中值** | 输入域的中间值 | x = (max+min)/2 |
| 5 | **边界外一个值** | 输入域之外最近的整数值 | x = max+1（验证异常处理） |
| 6 | **极端值/NaN** | 系统能接受的最极端输入或NaN | x = NaN 或 x = inf |

计算公式后，手算每个点的预期输出，与代码输出对比。如公式含条件分支或多段函数，每个分支至少覆盖2个点。

#### Q2 数据完整性验证
- 1只标的 × 30个交易日真实数据（最低标准）
- 覆盖算法所有分支（若实际分支 > 3，则全分支覆盖，不以3为硬性下限）
- 使用 grep 确认变更影响的全部模块和调用链

#### Q3 边界角度
- 空值/异常/极值三种场景，每种至少1个测试用例
- 测试用例记录在 self_check_pass.json 中

#### Q4 回归完整性
- 与黄金基线对比，计算差值
- 记录差异分析结果

#### Q5 实际耗时报告
- 报告编码实际耗时（分钟）和自检实际耗时（分钟）
- **不作为通过/不通过判定**，仅作为审计信息
- 超时由调度器 timer 监控管理，不由自检声称

#### Q6 一致性
- Q1/Q2/Q3 三个角度结果一致
- 若不一致，分析原因并在 self_check_pass.json 中记录

### 返回规则
- Q1~Q6 全部完成并记录在 self_check_pass.json 中 → 进入Stage 2
- 任意一项缺失或有冲突 → 修正后重跑自检
- **墨萱在 Stage 2 期间发现自检盲区，有权要求墨衡针对特定范围扩展自检**

### 工时
- 上限 **20min**（含+5min弹性缓冲）

---

## 八、Stage 2：墨萱回归对比+CR

### 职责
1. **回归对比**（GP-003强制）：
   - 黄金基线 vs 修改后结果
   - IC偏差 < 1e-6
   - NAV偏差 < 0.01%
   - 运行回归脚本，不得人工声称"看起来一样"
2. **代码审查（CR）**：BT-001~BT-008 合规检查

### 墨萱审查要点（BT合规矩阵）

| 编号 | 原则 | 检查点 |
|:----:|:-----|:-------|
| BT-001 | 参数注入 | 所有可调参数是否通过参数接口传入 |
| BT-002 | 数据与模型分离 | 硬编码路径、DB连接串是否已抽取 |
| BT-003 | 测试接口标准化 | run_xxx.py 结构是否符合模板规范 |
| BT-004 | BacktestData契约 | schema一致性、data_fingerprint验证 |
| BT-005 | 审计日志设计 | 每笔交易是否有完整审计记录 |
| BT-006 | t-1约束 | 信号生成是否使用t-1及以前数据 |
| BT-007 | TimeAlignmentGuard | 时间对齐检查是否已部署 |
| BT-008 | 约束优先级 | 停牌>涨跌停>T+1的优先级是否正确 |

### 审查产出
- `.done` 文件，status 为 SUCCESS 或 REJECT
- 回归报告（含 IC/NAV 比对数据）
- CR 意见（含 BT-001~BT-008 逐项检查结果）

### 工时
- 上限 **15min**（严重问题可延长至30min，需说明原因）

### 退回规则
- Stage 2 给出 REJECT → 触发 Stage 2.5（墨衡修复+回归验证）
- 退修计数器由墨涵在调度脚本 meta.retry_counters 中维护
- 总退回次数 ≤ 2 次
- 第3次退回 → 告警 Owner 裁决
- 退回时墨萱同时通知 Owner

---

## 九、Stage 2.5：退回修复+回归验证

**条件触发**：仅当 Stage 2 给出 REJECT

### 职责
1. 墨衡接收墨萱退回意见
2. 修复代码问题
3. 跑 GP-003 回归验证

### 循环路径
```
Stage 2 REJECT
    ↓
Stage 2.5 墨衡修复
    ↓
墨涵递增 retry_counters.stage_2_retry
    ↓
重新进入 Stage 1.5 自检
    ↓
重新进入 Stage 2 审查
    ↓
再次 REJECT → 重复（≤2次）
    ↓
第3次 REJECT → escalate_owner
```

### 工时
- 上限 **25min**（含修复+回归验证）

### 退回规则
- 最大退修次数：2次
- 第3次退回 → 立即告警 Owner 裁决
- 每次修复后必须重新经历 Stage 1.5 自检 + Stage 2 审查

---

## 十、Stage 3：玄知架构把关

### 职责
1. **全通道验证**：数据流是否完整打通（数据层→计算层→模拟层→输出层）
2. **版本一致性**：代码版本、数据指纹、基线版本三方对齐
3. **复现性确认**：seed固定、数据指纹匹配、版本标签存在
4. **全通路检查**：确保没有任何隐式依赖或未连接路径

### 工时
- 15min（上限）

---

## 十一、Stage 4：墨涵知识归档

### 职责
1. 检查是否有知识条目（KID）需创建或更新
2. 验证知识产品完整性
3. 协调四方会签：
   - 墨萱签 → 技术实现正确
   - 玄知签 → 架构+数据一致性
   - 墨涵签 → 知识产出完整、文档归档到位
   - Owner签 → 业务方向确认

### 产出
- 知识条目（如适用）
- 归档检查报告
- 四方会签记录

### 工时
- 5min（上限）

---

## 十二、Stage 5：Owner签批

### 职责
- Owner进行业务方向最终确认
- 签署放行或驳回

### 工时
- 5min（上限）

---

## 十三、附录 TMPL-006：self_check_pass.json 模板

```json
{
  "self_check": {
    "coder": "moheng",
    "task_id": "xxx",
    "coding_time_min": 25,
    "self_check_time_min": 12,
    "results": {
      "Q1_formula_check": {
        "status": "PASS",
        "points": [
          {"type": "max_input", "input": 100, "expected": 0.85, "actual": 0.85, "match": true},
          {"type": "min_input", "input": 0, "expected": 0, "actual": 0, "match": true},
          {"type": "zero", "input": 0, "expected": 0, "actual": 0, "match": true},
          {"type": "mid", "input": 50, "expected": 0.425, "actual": 0.425, "match": true},
          {"type": "out_of_bounds", "input": 101, "expected": "clamp_to_max", "actual": "clamp_to_max", "match": true},
          {"type": "extreme", "input": "NaN", "expected": "NaN_guard", "actual": "NaN_guard", "match": true}
        ]
      },
      "Q2_data_coverage": {
        "status": "PASS",
        "symbol": "600519.SH",
        "trading_days": 30,
        "branches_covered": 3,
        "grep_affected_modules": ["fee_model.py", "simulator.py"],
        "grep_result": "3 files, 7 lines affected"
      },
      "Q3_boundary": {
        "status": "PASS",
        "null_case": {"tested": true, "result": "handled"},
        "anomaly_case": {"tested": true, "result": "handled"},
        "extreme_case": {"tested": true, "result": "handled"}
      },
      "Q4_regression": {
        "status": "PASS",
        "baseline_path": "golden_baseline_snapshot.json",
        "IC_diff": 5.2e-7,
        "NAV_diff": 0.003
      },
      "Q5_time_report": {
        "coding_min": 25,
        "self_check_min": 12,
        "note": "超时由调度器监控，本报告仅记录实际耗时"
      },
      "Q6_consistency": {
        "status": "PASS",
        "note": "Q1/Q2/Q3 三角度结果一致"
      }
    },
    "overall": "PASS",
    "checked_by": "moheng",
    "checked_at": "ISO8601"
  }
}
```

---

## 十四、异常处理

| 异常场景 | 处理方式 |
|:--------|:---------|
| Stage 1 编码超30min | 自动拆路（通知Owner + 分拆为子任务，墨涵生成新调度脚本）|
| Stage 1.5 自检不通过 | 退回Stage 1修正，重跑自检 |
| Stage 2 退回 ≥ 3次 | 告警Owner裁决 |
| 任意阶段 .done 缺失 | 视为该阶段未完成，不可推进 |
| 代码变更后未更新基线 | Stage 2直接退回 |
| 调度脚本未通过玄知审查 | 修正脚本后重审 |
| 调度脚本执行过程中发现不符 | 暂停流程，通知Owner |
| 超时（任何阶段） | auto_alert_on_timeout → 通知Owner + 暂停等指示 |

---

## 十五、协议签署

本流程经以下四方会签确认：

| 签署方 | 角色 | 状态 | 签署日期 |
|:------|:----|:----:|:--------:|
| 墨衡 | 执行方 | ✅ v1.0 | 2026-05-27 |
| 墨萱 | QA+技术审查 | ✅ v1.0 | 2026-05-27 |
| 玄知 | 架构把关 | ✅ v1.1 → PASS（复审） | 2026-05-28 |
| 墨涵 | 知识归档+调度 | ✅ v1.1 | 2026-05-28 |
| **Owner** | 业务确认 | ✅ **签署** | **2026-05-28** |

---

*编码流程 v1.1 — 调度脚本驱动。修复墨萱WARN（循环回退→dynamic_next分支字段）、墨衡WARN（Q1 6点定义、退修计数器、黄金基线验证、Q5改为耗时报告）。墨涵角色：只读脚本+查文件+调spawn+读dynamic_next，不做独立判断。*
