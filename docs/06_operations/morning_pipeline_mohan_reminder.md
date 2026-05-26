---
author: moheng
created_time: 2026-05-16T15:00+08:00
status: READY
version: 1.0
---

# 早报管线 — 墨涵执行流程手册

> 💡 这是为墨涵（mochen）准备的早报管线执行指南。配合 `scheduler_agent.py` 使用。

---

## 1. 收到 Cron 消息时

每天 08:00 CST，cron `ce760f90` 会启动一个 `isolated session`，并将启动消息发送给你。

**消息内容**:
```
执行早报管线。使用调度器:
  from morning_pipeline.scheduler_agent import MorningPipeline
  pipeline = MorningPipeline()
  result = pipeline.run()
```

---

## 2. 执行流程

### 第一步：确认状态

```python
from morning_pipeline.scheduler_agent import MorningPipeline
pipeline = MorningPipeline()

# 检查是否是交易日
if not MorningPipeline._precheck(pipeline):
    # 非交易日 → 跳过，任务结束
    return
```

### 第二步：运行全管线

```python
result = pipeline.run()
```

这会自动执行以下串行流程:

```
08:00  [Precheck]  交易日判断（墨涵自检）
        ↓ 交易日 → 继续
08:00  [Step0]     spawn 玄知 → 市场扫描           (5min, 超时8min)
        ↓ .done 到达
08:05  [Step1]     spawn 墨衡 → 结构化分析           (10min, 超时13min)
        ↓ .done 到达
08:15  [Step2]     spawn 墨萱 → 报告草稿             (5min, 超时8min)
        ↓ .done 到达
08:20  [Step3]     spawn 墨衡 → 质量审查（含 Kill Switch） (5min, 超时8min)
        ↓ .done 到达
08:25  [Step3.5]   spawn 玄知 → 战略复核             (5min, 超时8min)
        ↓ .done 到达
08:30  [Step4]     spawn 墨萱 → 汇总定稿             (5min, 超时8min)
        ↓ .done 到达
08:35  [Step5]     墨涵 → 飞书推送                  (2min, 超时3min)
        ↓ .done 到达
08:37  [完成]      写 pipeline.done ✓
```

### 第三步：查看结果摘要

```python
print(json.dumps(result, ensure_ascii=False, indent=2))
# → {"task_id":"morning_report_20260516","status":"COMPLETED","total_minutes":33.2,...}
```

---

## 3. 异常场景

### 3.1 Cron session 重启（状态恢复）

> 你可以在任何时候重新 import 调度器。`pipeline.run()` 会自动扫描 checkpoint：
> 1. 读 `signals/checkpoints/` 检查哪些步骤已完成
> 2. 跳过已完成的步骤
> 3. 从第一个未完成的步骤继续

```python
# 重启后继续
from morning_pipeline.scheduler_agent import MorningPipeline
pipeline = MorningPipeline()
result = pipeline.run()       # 自动跳步
# 或显式调用:
result = pipeline.resume()
```

### 3.2 某步 FAIL

管线会自动熔断。你会看到 result 中 status = "ABORTED"：

```json
{
  "task_id": "morning_report_20260516",
  "status": "ABORTED",
  "abort_reason": "step3 FAIL: timeout_after_2_attempts",
  "failed_step": "step3"
}
```

**你需要做的事**:
1. 分析失败原因（看信号文件 `{task_id}_{agent}.failed` 或 `{task_id}_ABORT.json`）
2. 通知@主人
3. 修复问题后删除 `signals/checkpoints/{task_id}_ABORT.json`
4. 重新 `pipeline.run()` 恢复

```
通知模板:
  @主人  早报管线异常终止
  失败步骤: Step3（墨衡质量审查）
  原因: 超时（两次尝试均未完成）
  建议: 检查墨衡状态后重新运行
```

### 3.3 Step5 飞书推送失败

Step5 需要你（墨涵）手动操作。调度器会打印推送指令到日志：

```python
# 推送指令摘要:
# 1. 读取 reports/morning/{date}/final_report_{task_id}_step4.md
# 2. 提取核心观点（≤200字）
# 3. 发送到飞书群 oc_72bacde2a63f824bd011718fbe58f48a
# 4. 写 .done 文件
```

如果推送失败（重试3次后）:
1. 手动复制 final_report 内容发送到飞书群
2. 写 .done 文件标记完成

### 3.4 可选步骤超时

Step2（报告草稿）和 Step3.5（战略复核）是可选步骤：
- **Step2 超时**: 跳过草稿，Step3/4 会直接基于结构化分析工作
- **Step3.5 超时**: 跳过战略复核，Step4 仅基于质量审查和草稿定稿

调度器会自动跳过并继续。

---

## 4. 日常检查清单

每天早上收到 cron 消息后，你可以快速检查：

```python
# 1. 检查非交易日跳过
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
today = datetime.now(TZ).strftime("%Y%m%d")

skip_file = Path(r"C:\Users\17699\mo_zhi_sharereports\signals\tasks\morning_skip.done")
if skip_file.exists():
    data = json.loads(skip_file.read_text(encoding="utf-8"))
    print(f"非交易日跳过: {data['date']}")

# 2. 检查上次管线完成状态
pipeline_done = Path(r"C:\Users\17699\mo_zhi_sharereports\signals\tasks") / f"morning_report_{today}_pipeline.done"
if pipeline_done.exists():
    print(f"昨日管线已完成: {json.loads(pipeline_done.read_text(encoding='utf-8'))['completed_time']}")
```

---

## 5. 常见问题

### Q: 为什么我的 session 中没有 "MorningPipeline" 类？
A: 确保已执行 `from morning_pipeline.scheduler_agent import MorningPipeline`。
   脚本路径: `C:\Users\17699\mozhi_platform\src\morning_pipeline\scheduler_agent.py`

### Q: run() 自动跳步的逻辑是什么？
A: 调度器启动时会扫描 `signals/checkpoints/{task_id}_step{N}_done.json` 文件。
   - 如果某步的 checkpoint 存在且 status 为 SUCCESS/SKIPPED → 跳过
   - 如果 `{task_id}_ABORT.json` 存在 → 不执行，提示已熔断
   - 否则 → 执行该步

### Q: 我想手动指定只在某步开始执行？
A: 删除不需要步骤的 checkpoint 文件，然后：
   ```python
   pipeline = MorningPipeline()
   result = pipeline.run()   # 会跳步到第一个缺失的 checkpoint
   ```

### Q: 如何查看当前管线进度？
A: ```python
   checkpoints = pipeline.checkpoints.get_completed_steps()
   print(f"已完成: {checkpoints}")
   ```

### Q: 管线完成后的文件在哪里？
A:
   - 全流程标记: `signals/tasks/{task_id}_pipeline.done`
   - 最终报告: `reports/morning/{date}/final_report_{task_id}_step4.md`
   - 各步产出: `reports/morning/{date}/` 目录下
