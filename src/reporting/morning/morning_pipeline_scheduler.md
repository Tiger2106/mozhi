# 早报管线调度脚本 — morning_pipeline_scheduler
<!-- author: 墨衡 (moheng) | created_time: 2026-05-15T01:15+08:00 -->

**用途**: 供墨涵在 08:00 cron 触发后按本脚本**串行 spawn** 各子 agent 执行早报。
**调度模式**: 严格串行。前一步完成（收到 Announce + 验证 .done）后，再启动下一步。

---

## 0. 管线总览

| 步骤 | 子任务名 | 子Agent | 预估耗时 | 说明 |
|:----:|----------|:-------:|:--------:|------|
| **预检** | is_trading_day | 墨涵 | 即时 | 交易日历检查，非交易日跳过 |
| **Step0** | morning_scan | 玄知 | 5min | 市场数据采集（油价/大盘/板块） |
| **Step1** | morning_analysis | 墨衡 | 10min | 结构化深度分析 |
| **Step2** | morning_draft | 墨萱 | 5min | 报告草稿撰写 |
| **Step3** | morning_review | 墨衡 | 5min | 质量审查 |
| **Step3.5** | morning_strategic_review | 玄知 | 5min | 战略复核（历史验证） |
| **Step4** | morning_finalize | 墨萱 | 5min | 汇总定稿 |
| **Step5** | morning_push | 墨涵 | 2min | 飞书推送 |
| **总计** | 8个环节 | — | ~37min | 08:00→08:37（含15%缓冲） |

### 关键管线规则

| 规则 | 值 | 说明 |
|:----|:---|:------|
| **总超时** | 1800s（30min） | 08:00→08:30 完成 |
| **预检** | 交易日历检查 | 非交易日 → 终止管线 |
| **错误传播** | FAIL → 立即终止 | 任何子任务 FAIL 均中断后续 |
| **超时重试** | 1次（相同step） | 超时后可选重试1次，仍超时 → FAIL |
| **跳过策略** | 仅 WARN 可跳过 | 子任务 verdict=WARN 时可选继续，FAIL 不可跳过 |
| **熔断** | 2次超时/3次总尝试 | 同一子任务最多执行3次（含重试），熔断后通知主人 |

---

## 1. 预检：交易日历判断

**执行者**: 墨涵（自身，不需要 spawn）
**时机**: 08:00 cron 触发后，第一件事

```python
# 伪代码 — 墨涵执行
from datetime import datetime
import json
from pathlib import Path

CALENDAR_PATH = r"C:\Users\17699\mo_zhi_sharereports\scheduler\trading_calendar.json"
# 或调用:
# python C:\Users\17699\mo_zhi_sharereports\scheduler\trading_calendar.py check

today = datetime.now().strftime("%Y%m%d")
# 检查 is_trading_day()
if not is_trading_day(today):
    # 非交易日 — 写入 skip 记录，终止管线
    skip_file = Path(r"C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_skip.done")
    skip_content = {"task_id":"morning_skip","agent":"mochen","date":today,"status":"SKIPPED","reason":"not_trading_day","timestamp":datetime.now().isoformat()}
    skip_file.write_text(json.dumps(skip_content, ensure_ascii=False))
    print(f"[SKIP] {today} 非交易日，早报管线跳过")
    return  # 终止
```

**产出**: 无（只做检查）
**交易日历文件**: `C:\Users\17699\mo_zhi_sharereports\scheduler\trading_calendar.json` 或 python 脚本检查

---

## 2. 步骤详细 spawn 模板

### 通用约定

所有步骤共享以下约定：

| 项目 | 约定 |
|:----|:------|
| **task_id 格式** | `morning_report_{YYYYMMDD}_step{X}` |
| **trigger 文件路径** | `C:\Users\17699\mo_zhi_sharereports\signals\triggers\trigger_step{X}_{task_id}.json` |
| **.done 文件路径** | `C:\Users\17699\mo_zhi_sharereports\signals\tasks\{task_id}_{agent}.done` |
| **等待机制** | 先等 Announce → 再读 .done 验证，.done 文件优先 |
| **后台轮询** | 启动 `background_poll.py` 轮询 .done 文件（可选加速） |
| **Announce 处理** | Announce 到达后立即读 .done 验证 status，以 .done 为准 |
| **时间戳** | 统一 +08:00 时区 |
| **失败文件** | `.failed` 代替 `.done`，与 `.done` 互斥 |

> ⚠️ **.done 文件是单一真相源**：即使收到 Announce，也必须读回 .done 验证 status 字段。若 Announce 丢失但 .done 存在，以 .done 为准继续推进。

---

### Step0：晨间市场扫描（玄知）

| 字段 | 值 |
|:----|:---|
| **agentId** | `xuanzhi` |
| **task_id** | `morning_report_{YYYYMMDD}_step0` |
| **预估耗时** | 5min |
| **建议超时** | 480s（8min，含3min缓冲） |
| **产出文件** | `data/analysis/macro_analysis_{YYYYMMDD}HHMMSS.json` |
| **重试策略** | 超时后重试1次，仍超时 → FAIL，终止管线 |

#### Trigger 文件内容模板
```json
{
  "task_id": "morning_report_{YYYYMMDD}_step0",
  "step": 0,
  "agent": "xuanzhi",
  "report_type": "morning",
  "date": "{YYYYMMDD}",
  "priority": "normal",
  "triggered_by": "mochen",
  "depends_on": [],
  "expected_duration": 300,
  "created_at": "{ISO8601}",
  "version": "2.1",
  "status": "PENDING"
}
```

#### spawn TASK 命令模板
```
# 墨枢任务分配 — morning_report_{YYYYMMDD}_step0

## 任务描述
执行晨间市场数据采集（Step0），采集当前国际油价、A股大盘、板块热点等实时数据。

## 具体要求
1. 必须联网采集最新数据
2. 采集内容如下（每条逻辑不超过3句话）：
   - 国际油价（WTI/布伦特）：最新价、涨跌幅
   - A股大盘（上证/沪深300）：最新价、涨跌幅（盘前则标注"盘前无成交"）
   - 今日最强板块 Top 3-5：板块名+涨幅+核心驱动逻辑
   - 资金轮动方向：主流流入方向，抱团特征
   - 今日市场情绪：偏多/中性/偏空，附简要依据
   - 潜在风险 1-2 个
3. 产出文件写入 reports/{report_type}/{date}/ 目录
4. 完成时写入 .done 文件

## 参考文件
- (无前置依赖)

## 输出文件
- C:\Users\17699\mo_zhi_sharereports\reports\morning\{YYYYMMDD}\macro_analysis_{YYYYMMDD}HHMMSS.json
- C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_report_{YYYYMMDD}_step0_xuanzhi.done

## 你需要做的事
1. 理解上述任务
2. 评估工作量
3. 回复 Announce（含预估时间）
```

#### 等待条件
- 收到 Announce (completion) 或 .done 文件出现
- 读取 `.done` 验证 `status == "SUCCESS"`（或 `COMPLETED`）
- 若超时 480s 无响应：重试1次（重新写入 trigger 文件）
- 若重试仍超时：写入 FAILED 日志，终止管线，通知主人

---

### Step1：结构化深度分析（墨衡）

| 字段 | 值 |
|:----|:---|
| **agentId** | `moheng` |
| **task_id** | `morning_report_{YYYYMMDD}_step1` |
| **预估耗时** | 10min |
| **建议超时** | 780s（13min，含3min缓冲） |
| **前置依赖** | Step0 完成（需要玄知数据） |
| **产出文件** | `reports/morning/{YYYYMMDD}/structured_analysis_{task_id}.json` |
| **重试策略** | 超时后重试1次，仍超时 → FAIL，终止管线 |

#### Trigger 文件内容模板
```json
{
  "task_id": "morning_report_{YYYYMMDD}_step1",
  "step": 1,
  "agent": "moheng",
  "report_type": "morning",
  "date": "{YYYYMMDD}",
  "priority": "normal",
  "triggered_by": "mochen",
  "depends_on": ["morning_report_{YYYYMMDD}_step0"],
  "expected_duration": 600,
  "created_at": "{ISO8601}",
  "version": "2.1",
  "status": "PENDING"
}
```

#### spawn TASK 命令模板
```
# 墨枢任务分配 — morning_report_{YYYYMMDD}_step1

## 任务描述
基于玄知 Step0 的市场扫描数据，进行结构化深度分析（Step1）。

## 上下文
前置任务 Step0（玄知市场扫描）已完成，数据文件位于：
reports/morning/{YYYYMMDD}/macro_analysis_{*}.json

## 具体要求
1. 读取玄知 Step0 产出数据
2. 进行全面结构化分析（SOUL.md Step2 规范）：
   - 数据验证：玄知数据与资金流一致性
   - 深度逻辑推演：宏观驱动因素、资金可持续性
   - 风险量化：等级（低/中/高）+ 主要风险来源
   - 操作建议框架：进取/均衡/保守三档
3. 整体用时控制在10分钟以内
4. 产出完整分析后写入 .done 文件

## 参考文件
- reports/morning/{YYYYMMDD}/macro_analysis_{*}.json

## 输出文件
- C:\Users\17699\mo_zhi_sharereports\reports\morning\{YYYYMMDD}\structured_analysis_morning_report_{YYYYMMDD}_step1.json
- C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_report_{YYYYMMDD}_step1_moheng.done

## 你需要做的事
1. 理解上述任务
2. 读取前置产出
3. 执行分析并产出文件
4. 回复 Announce
```

#### 等待条件
- 收到 Announce 或 .done 文件出现
- 读取 `.done` 验证 `status == "SUCCESS"`（或 `COMPLETED`）
- 若超时 780s 无响应：重试1次
- 若重试仍超时：写入 FAILED 日志，终止管线

---

### Step2：报告草稿（墨萱）

| 字段 | 值 |
|:----|:---|
| **agentId** | `moxuan` |
| **task_id** | `morning_report_{YYYYMMDD}_step2` |
| **预估耗时** | 5min |
| **建议超时** | 480s（8min，含3min缓冲） |
| **前置依赖** | Step1 完成 |
| **产出文件** | `mohan/「股票名称」投资策略分析报告（早报）_{task_id}_draft.md` |
| **重试策略** | 超时后重试1次，仍超时 → 可选跳过（仅草稿步骤） |

#### Trigger 文件内容模板
```json
{
  "task_id": "morning_report_{YYYYMMDD}_step2",
  "step": 2,
  "agent": "moxuan",
  "report_type": "morning",
  "date": "{YYYYMMDD}",
  "priority": "normal",
  "triggered_by": "mochen",
  "depends_on": ["morning_report_{YYYYMMDD}_step1"],
  "expected_duration": 300,
  "created_at": "{ISO8601}",
  "version": "2.1",
  "status": "PENDING"
}
```

#### spawn TASK 命令模板
```
# 墨枢任务分配 — morning_report_{YYYYMMDD}_step2

## 任务描述
基于墨衡 Step1 结构化分析，撰写早报草稿（Step2）。

## 上下文
前置任务 Step1（墨衡分析）已完成，数据文件位于：
reports/morning/{YYYYMMDD}/structured_analysis_morning_report_{YYYYMMDD}_step1.json

## 具体要求
1. 严格基于结构化分析撰写，不添加未经支撑的结论
2. 早报格式：有吸引力的标题 + 核心观点摘要 + 详细分析 + 操作建议
3. 语言简洁专业，面向飞书群读者
4. 草稿阶段不需要完美格式，但逻辑必须完整
5. 产出后写入 .done 文件

## 参考文件
- reports/morning/{YYYYMMDD}/structured_analysis_morning_report_{YYYYMMDD}_step1.json

## 输出文件
- C:\Users\17699\mo_zhi_sharereports\reports\morning\{YYYYMMDD}\morning_draft_{task_id}.md
- C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_report_{YYYYMMDD}_step2_moxuan.done

## 你需要做的事
1. 理解上述任务
2. 读取墨衡分析数据
3. 撰写草稿并产出
4. 回复 Announce
```

#### 等待条件
- 收到 Announce 或 .done 文件出现
- 读取 `.done` 验证成功
- 若超时：重试1次
- 若仍失败：草稿步骤可跳过（后续审查步骤无法执行则需要通知主人人工处理）

---

### Step3：质量审查（墨衡）

| 字段 | 值 |
|:----|:---|
| **agentId** | `moheng` |
| **task_id** | `morning_report_{YYYYMMDD}_step3` |
| **预估耗时** | 5min |
| **建议超时** | 480s（8min，含3min缓冲） |
| **前置依赖** | Step2 完成 |
| **产出文件** | `reports/morning/{YYYYMMDD}/review_feedback_{task_id}.md` |
| **重试策略** | 超时后重试1次，仍超时 → FAIL（质量审查不能跳过） |

#### Trigger 文件内容模板
```json
{
  "task_id": "morning_report_{YYYYMMDD}_step3",
  "step": 3,
  "agent": "moheng",
  "report_type": "morning",
  "date": "{YYYYMMDD}",
  "priority": "normal",
  "triggered_by": "mochen",
  "depends_on": ["morning_report_{YYYYMMDD}_step2"],
  "expected_duration": 300,
  "created_at": "{ISO8601}",
  "version": "2.1",
  "status": "PENDING"
}
```

#### spawn TASK 命令模板
```
# 墨枢任务分配 — morning_report_{YYYYMMDD}_step3

## 任务描述
对墨萱 Step2 草稿报告进行质量审查（Step3）。

## 上下文
前置任务 Step2（墨萱草稿）已完成，数据文件位于：
- reports/morning/{YYYYMMDD}/morning_draft_morning_report_{YYYYMMDD}_step2.md（草稿）
- reports/morning/{YYYYMMDD}/structured_analysis_morning_report_{YYYYMMDD}_step1.json（分析原文）

## 具体要求
1. 审阅以下维度：
   - 事实准确性：草稿结论与结构化分析是否一致
   - 逻辑完整性：论证链条有无跳跃
   - 风险披露充分性：风险是否如实呈现
   - 操作建议合规性：有无过激表述
2. 给出具体、可操作的修改意见（禁止泛化评语）
3. verdict 定义：PASS / WARN / FAIL
   - PASS：可直接进 Step4
   - WARN：有问题但可修
   - FAIL：重大错误，不可发布
4. 若 verdict=FAIL，管线终止
5. 产出 review_feedback 后写入 .done 文件

## 参考文件
- reports/morning/{YYYYMMDD}/morning_draft_morning_report_{YYYYMMDD}_step2.md
- reports/morning/{YYYYMMDD}/structured_analysis_morning_report_{YYYYMMDD}_step1.json

## 输出文件
- C:\Users\17699\mo_zhi_sharereports\reports\morning\{YYYYMMDD}\review_feedback_morning_report_{YYYYMMDD}_step3.md
- C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_report_{YYYYMMDD}_step3_moheng.done

## 你需要做的事
1. 理解上述任务
2. 读取草稿和分析文件
3. 执行审查并产出 review_feedback
4. 回复 Announce
```

#### 等待条件
- 收到 Announce 或 .done 文件出现
- 读取 review_feedback 文件中 `verdict` 字段：
  - **PASS**: 继续管线
  - **WARN**: 继续管线（附修改指令给 Step4）
  - **FAIL**: **终止管线**，通知主人
- 若超时：重试1次

---

### Step3.5：战略复核（玄知）

| 字段 | 值 |
|:----|:---|
| **agentId** | `xuanzhi` |
| **task_id** | `morning_report_{YYYYMMDD}_step3_5` |
| **预估耗时** | 5min |
| **建议超时** | 480s（8min，含3min缓冲） |
| **前置依赖** | Step3 完成（需要墨衡的结构化分析） |
| **产出文件** | `signals/strategic_review_{task_id}.json` |
| **重试策略** | 超时后可跳过（战略复核为可选但高推荐） |

#### Trigger 文件内容模板
```json
{
  "task_id": "morning_report_{YYYYMMDD}_step3_5",
  "step": 3.5,
  "agent": "xuanzhi",
  "report_type": "morning",
  "date": "{YYYYMMDD}",
  "priority": "normal",
  "triggered_by": "mochen",
  "depends_on": ["morning_report_{YYYYMMDD}_step3"],
  "expected_duration": 300,
  "created_at": "{ISO8601}",
  "version": "2.1",
  "status": "PENDING"
}
```

#### spawn TASK 命令模板
```
# 墨枢任务分配 — morning_report_{YYYYMMDD}_step3_5

## 任务描述
对墨衡的结构化分析进行战略复核（Step3.5），聚焦历史验证。

## 上下文
前置任务 Step3（墨衡审查）已完成，分析文件位于：
reports/morning/{YYYYMMDD}/structured_analysis_morning_report_{YYYYMMDD}_step1.json

## 具体要求
1. 复核墨衡的推理链路（宏观→个股传导逻辑）
2. 核心问题："这个结论，在历史上是否站得住？"
3. 输出方式（"灵魂层"摘要格式）：
   ```
   战略复核：
   当前判断属于"<逻辑分类>"
   历史胜率：XX%
   关键风险：<风险描述>
   ```
4. 同时产出完整 JSON 格式（含详细历史验证）
5. verdict 定义：PASS / PASS_WITH_NOTES / FAIL
   - FAIL：不可推送，需人工介入

## 参考文件
- reports/morning/{YYYYMMDD}/structured_analysis_morning_report_{YYYYMMDD}_step1.json

## 输出文件
- C:\Users\17699\mo_zhi_sharereports\signals\strategic_review_morning_report_{YYYYMMDD}_step3_5.json
- C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_report_{YYYYMMDD}_step3_5_xuanzhi.done

## 你需要做的事
1. 理解上述任务
2. 读取墨衡分析
3. 执行战略复核
4. 回复 Announce
```

#### 等待条件
- 收到 Announce 或 .done 文件出现
- 读取 strategic_review 文件中 `verdict`：
  - **PASS / PASS_WITH_NOTES**: 继续管线
  - **FAIL**: **终止管线**，通知主人
- 若超时：可跳过（不影响后续定稿）

---

### Step4：汇总定稿（墨萱）

| 字段 | 值 |
|:----|:---|
| **agentId** | `moxuan` |
| **task_id** | `morning_report_{YYYYMMDD}_step4` |
| **预估耗时** | 5min |
| **建议超时** | 480s（8min，含3min缓冲） |
| **前置依赖** | Step3 + Step3.5 |
| **产出文件** | `mohan/「股票名称」投资策略分析报告（早报）_{task_id}.md` |
| **重试策略** | 超时后重试1次，仍超时 → FAIL（定稿不可跳过） |

#### Trigger 文件内容模板
```json
{
  "task_id": "morning_report_{YYYYMMDD}_step4",
  "step": 4,
  "agent": "moxuan",
  "report_type": "morning",
  "date": "{YYYYMMDD}",
  "priority": "normal",
  "triggered_by": "mochen",
  "depends_on": ["morning_report_{YYYYMMDD}_step3", "morning_report_{YYYYMMDD}_step3_5"],
  "expected_duration": 300,
  "created_at": "{ISO8601}",
  "version": "2.1",
  "status": "PENDING"
}
```

#### spawn TASK 命令模板
```
# 墨枢任务分配 — morning_report_{YYYYMMDD}_step4

## 任务描述
基于墨衡审查意见和玄知战略复核，汇总输出早报定稿（Step4）。

## 上下文
前置任务已完成，参考文件位于：
- reports/morning/{YYYYMMDD}/morning_draft_morning_report_{YYYYMMDD}_step2.md（草稿）
- reports/morning/{YYYYMMDD}/review_feedback_morning_report_{YYYYMMDD}_step3.md（审查意见）
- signals/strategic_review_morning_report_{YYYYMMDD}_step3_5.json（战略复核）

## 具体要求
1. 逐条落实墨衡审查意见（修改指令）
2. 整合玄知战略复核的置信度修正（仓位、时间止损等）
3. 自检清单：
   - [ ] 墨衡审查意见已落实
   - [ ] 战略复核置信度修正已整合
   - 整体自检结论：PASS / WARN
4. 产出最终定稿报告
5. 定稿应包含"核心观点摘要"部分（≤200字，供墨涵推送用）

## 参考文件
- reports/morning/{YYYYMMDD}/morning_draft_morning_report_{YYYYMMDD}_step2.md
- reports/morning/{YYYYMMDD}/review_feedback_morning_report_{YYYYMMDD}_step3.md
- signals/strategic_review_morning_report_{YYYYMMDD}_step3_5.json

## 输出文件
- C:\Users\17699\mo_zhi_sharereports\reports\morning\{YYYYMMDD}\final_report_morning_report_{YYYYMMDD}_step4.md
- C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_report_{YYYYMMDD}_step4_moxuan.done

## 你需要做的事
1. 理解上述任务
2. 读取审查意见和战略复核
3. 整合定稿并产出
4. 回复 Announce
```

#### 等待条件
- 收到 Announce 或 .done 文件出现
- 读取 `.done` 验证成功
- 确认最终报告文件存在
- 若超时：重试1次，仍超时 → FAIL

---

### Step5：飞书推送（墨涵）

| 字段 | 值 |
|:----|:---|
| **agentId** | `mochen`（墨涵自身执行，不需 spawn） |
| **task_id** | `morning_report_{YYYYMMDD}_step5` |
| **预估耗时** | 2min |
| **建议超时** | 180s（3min） |
| **前置依赖** | Step4 完成 |
| **产出文件** | 飞书群消息（无文件产出） |
| **重试策略** | 发送失败重试3次，间隔2s，仍失败则保存本地 |

#### 执行要求（墨涵自身步骤）

墨涵自行执行以下操作（不需要 spawn 其他 agent）：

1. **读取定稿**：`reports/morning/{YYYYMMDD}/final_report_morning_report_{YYYYMMDD}_step4.md`
2. **准备推送内容**：
   - 从定稿文件中提取核心摘要（≤200字）
   - 推送格式：核心观点 + 操作建议 + 风险提示
   - 可附带完整报告文件链接（file upload）
3. **发送到飞书群**：
   - 群 ID: `oc_72bacde2a63f824bd011718fbe58f48a`
   - 格式要求：结论优先，不使用 markdown 表格
   - 语气: 专业、克制、有依据
4. **写入完成标记**:
   ```json
   {
     "task_id": "morning_report_{YYYYMMDD}_step5",
     "agent": "mochen",
     "step": 5,
     "status": "SUCCESS",
     "timestamp": "{ISO8601}",
     "summary": "早报已推送至飞书群",
     "push_status": "sent"
   }
   ```
   写入 `C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_report_{YYYYMMDD}_step5_mochen.done`
5. **通知主人**：可选在飞书群补充 @主人 提醒

#### 推送模板
```
（墨涵）各位早 ☀️

【核心观点】
<从定稿中提取的1-2句核心判断>

【操作建议】
进取型：<建议>
均衡型：<建议>
保守型：<建议>

【风险提示】
<如实表述主要风险>

<完整报告已上传>
```

---

## 3. 管线总体控制

### 3.1 整体流程

```
08:00 cron 触发（墨涵）
  │
  ├─ [预检] 交易日历判断
  │    ├─ 非交易日 → 跳过，写 morning_skip.done → 结束
  │    └─ 交易日 → 继续
  │
  ├─ [Step0] spawn 玄知 → 市场扫描
  │    ├─ 写入 trigger_step0_{task_id}.json
  │    ├─ 等待 .done（超时 480s）
  │    └─ 成功 → 继续；失败 → retry → 终止
  │
  ├─ [Step1] spawn 墨衡 → 结构化分析
  │    ├─ 写入 trigger_step1_{task_id}.json
  │    ├─ 等待 .done（超时 780s）
  │    └─ 成功 → 继续；失败 → retry → 终止
  │
  ├─ [Step2] spawn 墨萱 → 报告草稿
  │    ├─ 写入 trigger_step2_{task_id}.json
  │    ├─ 等待 .done（超时 480s）
  │    └─ 成功 → 继续；失败 → 可选跳过
  │
  ├─ [Step3] spawn 墨衡 → 质量审查
  │    ├─ 写入 trigger_step3_{task_id}.json
  │    ├─ 等待 .done（超时 480s）
  │    ├─ verdict=PASS → 继续
  │    ├─ verdict=WARN → 继续（带修改指令）
  │    └─ verdict=FAIL → 终止管线
  │
  ├─ [Step3.5] spawn 玄知 → 战略复核
  │    ├─ 写入 trigger_step3.5_{task_id}.json
  │    ├─ 等待 .done（超时 480s）
  │    ├─ verdict=PASS/PASS_WITH_NOTES → 继续
  │    ├─ verdict=FAIL → 终止管线
  │    └─ 超时 → 可选跳过
  │
  ├─ [Step4] spawn 墨萱 → 汇总定稿
  │    ├─ 写入 trigger_step4_{task_id}.json
  │    ├─ 等待 .done（超时 480s）
  │    └─ 成功 → 继续；失败 → retry → 终止
  │
  └─ [Step5] 墨涵 → 飞书推送
       ├─ 读取定稿，提取摘要
       ├─ 发送到飞书群
       └─ 写 .done → 完成
```

### 3.2 错误传播规则

| 错误类型 | 说明 | 传播规则 |
|:---------|:-----|:---------|
| **Step FAIL** | 子任务明确 FAIL | **终止管线**。墨涵通知主人 |
| **Step WARN** | 审查给出 WARN 但可修 | **继续管线**，修改指令附加到下一步 |
| **Step 超时** | 超时未完成 | **重试1次**。重试仍超时视为 FAIL |
| **Step 跳过** | 非关键步骤（Step2/3.5） | **可跳过**，跳过记录写入日志 |
| **Step3 FAIL** | 质量审查不通过 | **终止管线**。FAIL 报告严禁发布 |
| **Step3.5 FAIL** | 战略复核不通过 | **终止管线**。需人工复核 |
| **Step 文件缺失** | 产出文件不存在 | **视为 FAIL**，终止管线 |

### 3.3 重试限制

```
单步骤最大重试次数: 1
单步骤最大执行次数: 2（含首次）
整条管线熔断次数: 3（累计3次FAIL后整条管线终止）
```

### 3.4 超时仲裁（四级流程）

墨涵在 spawn 每个子 agent 时，设 timer = 预估时间 + 3min 缓冲。timer 到期时：

```
1. 检查 signals/tasks/{task_id}_{agent}.done
   → 存在则跳过 2-4，直接推进下一步

2. 检查 signals/tasks/{task_id}_{agent}.failed
   → 存在则标记失败，按错误传播规则处理

3. 检查 signals/tasks/{task_id}_{agent}.progress（进度文件）
   → 存在且最近更新 < 2min → 说明仍在工作，延长 timer

4. 以上都没有 → 调用子 agent session 查看日志:
   - 已完全成（日志有最终输出但 Announce 丢失）→ 推进
   - 仍在处理 → 延长 timer
   - 卡住或异常 → 重试或终止
```

---

## 4. 输出文件约定

### 4.1 .done 文件格式

**路径**: `C:\Users\17699\mo_zhi_sharereports\signals\tasks\{task_id}_{agent}.done`

**格式（JSON）**:
```json
{
  "task_id": "morning_report_{YYYYMMDD}_stepX",
  "agent": "{agent_name}",
  "step": {step_number},
  "timestamp": "{ISO8601}",
  "status": "SUCCESS|FAIL|COMPLETED",
  "summary": "<完成摘要>",
  "output_file": "<产出文件路径（相对或绝对）>",
  "verdict": "PASS|WARN|FAIL"   // 仅审查/复核步骤有
}
```

**status 字段取值**:
| 值 | 含义 |
|:---|:------|
| `SUCCESS` | 成功完成（标准） |
| `COMPLETED` | 成功完成（玄知/v2 兼容格式） |
| `FAIL` | 执行失败 |

### 4.2 .failed 文件格式（互斥）

**路径**: `C:\Users\17699\mo_zhi_sharereports\signals\tasks\{task_id}_{agent}.failed`

```json
{
  "task_id": "morning_report_{YYYYMMDD}_stepX",
  "agent": "{agent_name}",
  "step": {step_number},
  "timestamp": "{ISO8601}",
  "status": "FAIL",
  "error": "<错误原因>",
  "reason": "timeout|data_error|logic_error|cognitive_block"
}
```

### 4.3 所有产出文件路径汇总

| 产出 | 路径（相对于 mo_zhi_sharereports） |
|:-----|:----------------------------------|
| 玄知市场扫描 | `reports/morning/{YYYYMMDD}/macro_analysis_*.json` |
| 墨衡结构化分析 | `reports/morning/{YYYYMMDD}/structured_analysis_{task_id}.json` |
| 墨萱草稿 | `reports/morning/{YYYYMMDD}/morning_draft_{task_id}.md` |
| 墨衡审查反馈 | `reports/morning/{YYYYMMDD}/review_feedback_{task_id}.md` |
| 玄知战略复核 | `signals/strategic_review_{task_id}.json` |
| 墨萱定稿 | `reports/morning/{YYYYMMDD}/final_report_{task_id}.md` |
| Step0 .done | `signals/tasks/morning_report_{YYYYMMDD}_step0_xuanzhi.done` |
| Step1 .done | `signals/tasks/morning_report_{YYYYMMDD}_step1_moheng.done` |
| Step2 .done | `signals/tasks/morning_report_{YYYYMMDD}_step2_moxuan.done` |
| Step3 .done | `signals/tasks/morning_report_{YYYYMMDD}_step3_moheng.done` |
| Step3.5 .done | `signals/tasks/morning_report_{YYYYMMDD}_step3_5_xuanzhi.done` |
| Step4 .done | `signals/tasks/morning_report_{YYYYMMDD}_step4_moxuan.done` |
| Step5 .done | `signals/tasks/morning_report_{YYYYMMDD}_step5_mochen.done` |

---

## 5. 墨涵执行速查清单

墨涵在 08:00 cron 触发后，按以下清单逐步执行：

```
□ [预检] 检查今天是否为交易日
     → 非交易日 → 写 morning_skip.done → 结束
     → 交易日 → 继续

□ [Step0] spawn 玄知 — 市场扫描
     → 写 trigger → 等待 .done（最多 8min）
     → SUCCESS? → 继续    FAIL? → retry → 通知主人

□ [Step1] spawn 墨衡 — 结构化分析
     → 写 trigger → 等待 .done（最多 13min）
     → SUCCESS? → 继续    FAIL? → retry → 通知主人

□ [Step2] spawn 墨萱 — 报告草稿
     → 写 trigger → 等待 .done（最多 8min）
     → SUCCESS? → 继续    FAIL? → 可选跳过

□ [Step3] spawn 墨衡 — 质量审查
     → 写 trigger → 等待 .done（最多 8min）
     → verdict=PASS/WARN? → 继续    verdict=FAIL? → 终止管线

□ [Step3.5] spawn 玄知 — 战略复核
     → 写 trigger → 等待 .done（最多 8min）
     → verdict=PASS? → 继续    FAIL? → 终止    超时可跳过

□ [Step4] spawn 墨萱 — 汇总定稿
     → 写 trigger → 等待 .done（最多 8min）
     → SUCCESS? → 继续    FAIL? → retry → 终止

□ [Step5] 墨涵自己 — 飞书推送
     → 读定稿 → 提取核心观点（≤200字）→ 发群消息
     → 写 .done → 完成
```

---

## 6. 运行时适配注意事项

### 6.1 Task ID 动态替换

墨涵在执行时，将所有 `{YYYYMMDD}` 替换为实际日期（格式：`20260515`），所有 `{ISO8601}` 替换为实际时间戳（格式：`2026-05-15T08:00:00+08:00`）。

### 6.2 失败通知模板

当管线需要终止时，墨涵应通知主人：

```
（墨涵）⚠️ 早报管线异常终止

步骤: Step{X} — {子任务名}
原因: {超时/FAIL/文件缺失}
agent: {agent名}
task_id: {task_id}

请检查后决定是否手动推进或重试。
```

### 6.3 完整成功通知模板

```
（墨涵）✅ 早报管线完成

总耗时: {实际分钟}min（08:00→{完成时间}）
各步骤状态:
  Step0 玄知扫描: ✅
  Step1 墨衡分析: ✅
  Step2 墨萱草稿: ✅
  Step3 墨衡审查: ✅ ({verdict})
  Step3.5 玄知复核: ✅ ({verdict})
  Step4 墨萱定稿: ✅
  Step5 飞书推送: ✅

推送到群: {群名}
```

---

## 附录 A：与旧版差异说明

| 维度 | 旧版(v1) | 新版(本文件) |
|:-----|:---------|:------------|
| 调度者 | dispatcher 文件驱动 | 墨涵串行 spawn |
| 步骤数 | 7步(Step0–6) | 7步(Step0–5,含Step3.5) |
| 产出目录 | 分散在多个旧路径 | 统一 `reports/` + `signals/tasks/` |
| 操作建议 | 仅针对 601857 | 由墨衡分析决定，不限定个股 |
| 交易日检查 | scheduler 层 | 墨涵预检 |
| .done 路径 | 旧路径 | `signals/tasks/{task_id}_{agent}.done` |
| 超时仲裁 | 四级流程 | 简化版（.done优先 + 重试 + 熔断） |

---

## 附录 B：常见问题

**Q: Step3/Step3.5 不能同时在墨衡/玄知 cron 中并行吗？**
A: 设计上串行执行（Step3 → Step3.5），因为 Step3.5 复核对象是墨衡的结构化分析（已含审查修正），需要等 Step3 完成。如果某天需要优化，可考虑 Step3.5 与 Step3 并行（复核原始分析，非审查后版本），但需谨慎设计输入版本。

**Q: 如果玄知 cron 未运行怎么办？**
A: 墨涵在 spawn Step0/Step3.5 前，应先检查玄知的心跳文件（`signals/consensus/heartbeat/`）。若玄知离线，则应先手动触发或通知主人。

**Q: 晨间数据与午间数据冲突怎么办？**
A: 早报管线与中报管线使用独立的 task_id（`morning_` vs `midday_` 前缀），产出目录分开，互不干扰。

**Q: 管线执行中途收到紧急通知（如主人要开会）？**
A: 当前 pipeline 应以优先完成早报为原则。墨涵可在完成 Step5 后立即处理紧急事务。
