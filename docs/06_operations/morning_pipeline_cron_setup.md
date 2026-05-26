---
author: moheng
created_time: 2026-05-16T15:00+08:00
status: READY
version: 1.0
---

# 早报管线 Cron 配置说明

## 1. 现有 Cron 配置

当前已有 cron（ID: `ce760f90`），已配置为 `isolated` session，墨涵接收启动消息后执行 spawn 编排。

| 项目 | 当前值 |
|:----|:-------|
| cron ID | `ce760f90-3cd8-4594-a80a-0f7fb1743085` |
| 名称 | `早报管线-main` |
| 调度 | `0 8 * * 1-5` (周一到周五 08:00 CST) |
| 时区 | `Asia/Shanghai` |
| 责任人 | `mochen` |
| session 模式 | `isolated` |
| wake 模式 | `now` |
| 超时 | `1800s` (30min) |
| delivery mode | `announce` |
| delivery channel | `last` |
| delivery target | `feishu:chat:oc_72bacde2a63f824bd011718fbe58f48a` |

> ⚠️ **已知问题**: delivery.to 使用了 `feishu:chat:` 前缀而非 `chat:`，导致 delivery 失败。需修复。

---

## 2. Cron 配置模板

### 2.1 推荐配置（直接使用 `openclaw cron` CLI）

```bash
# 注意: 目标 chat_id 应为裸 chat: 前缀，非 feishu:chat:
# 修复 delivery target（移除 feishu: 前缀）
openclaw cron update ce760f90 \
  --delivery-to "chat:oc_72bacde2a63f824bd011718fbe58f48a" \
  --delivery-mode announce
```

### 2.2 payload.message 内容

墨涵收到 cron 消息后，应看到以下指令以启动早报管线：

```
执行早报管线。使用以下调度器:
  from morning_pipeline.scheduler_agent import MorningPipeline
  pipeline = MorningPipeline()
  result = pipeline.run()

若 cron session 重启，使用 resume:
  from morning_pipeline.scheduler_agent import MorningPipeline
  pipeline = MorningPipeline()
  result = pipeline.resume()
  # pipeline.run() 内部自动调用 resume 逻辑（跳过已完成步骤）

今日日期: {YYYYMMDD}（由 cron 模板填充）
task_id: morning_report_{YYYYMMDD}
步骤: Step0(玄知) → Step1(墨衡) → Step2(墨萱) → Step3(墨衡) → Step3.5(玄知) → Step4(墨萱) → Step5(墨涵-飞书推送)

每步规则:
- .done 文件存在 → 跳过该步
- .failed 文件存在 → 熔断管线
- 超时 → 重试1次 → 仍超时 → 熔断(或跳过可选步)
- 全部完成后写 pipeline.done
```

### 2.3 完整配置 JSON

```json
{
  "id": "ce760f90-3cd8-4594-a80a-0f7fb1743085",
  "agentId": "mochen",
  "name": "早报管线-main",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "0 8 * * 1-5",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "执行早报管线。使用调度器: from morning_pipeline.scheduler_agent import MorningPipeline; pipeline = MorningPipeline(); result = pipeline.run()",
    "timeoutSeconds": 1800
  },
  "delivery": {
    "mode": "announce",
    "channel": "feishu",
    "to": "chat:oc_72bacde2a63f824bd011718fbe58f48a",
    "bestEffort": false
  }
}
```

---

## 3. 日期生成与 task_id 规则

### task_id 格式

| 场景 | task_id |
|:----|:--------|
| 普通早报 | `morning_report_20260516` |
| 午报 | `midday_report_20260516` |
| 测试 | `test_morning_report_20260516` |

### 日期格式

- `YYYYMMDD` 格式（无分隔符），e.g. `20260516`
- 由墨涵在 session 中通过 `datetime.now(TZ)` 自动生成

---

## 4. 文件路径总览

### 调度脚本相关

| 文件 | 路径 |
|:----|:-----|
| 调度器主模块 | `C:\Users\17699\mozhi_platform\src\morning_pipeline\scheduler_agent.py` |
| 设计文档 | `C:\Users\17699\mozhi_platform\docs\02_development\morning_pipeline_refactor_plan.md` |
| 现有调度 MD | `C:\Users\17699\mozhi_platform\src\reporting\morning\morning_pipeline_scheduler.md` |
| 执行流程提醒 | `C:\Users\17699\mozhi_platform\docs\06_operations\morning_pipeline_mohan_reminder.md` |
| Cron 配置说明 | `C:\Users\17699\mozhi_platform\docs\06_operations\morning_pipeline_cron_setup.md` |

### 信号文件

| 类型 | 路径 |
|:----|:-----|
| trigger 文件 | `C:\Users\17699\mo_zhi_sharereports\试验信息库\signals\triggers\trigger_step{N}_{task_id}.json` |
| .done 文件 | `C:\Users\17699\mo_zhi_sharereports\signals\tasks\{task_id}_step{N}_{agent}.done` |
| .failed 文件 | `C:\Users\17699\mo_zhi_sharereports\signals\tasks\{task_id}_step{N}_{agent}.failed` |
| .blocked 文件 | `C:\Users\17699\mo_zhi_sharereports\signals\tasks\{task_id}_step{N}_{agent}.blocked` |
| checkpoint | `C:\Users\17699\mo_zhi_sharereports\signals\checkpoints\{task_id}_step{N}_{status}.json` |
| ABORT 标记 | `C:\Users\17699\mo_zhi_sharereports\signals\checkpoints\{task_id}_ABORT.json` |
| 管线全流程完成 | `C:\Users\17699\mo_zhi_sharereports\signals\tasks\{task_id}_pipeline.done` |
| 心跳文件 | `C:\Users\17699\mo_zhi_sharereports\signals\consensus\heartbeat\mochen_hb_*.json` |

---

## 5. 步骤时间预估

| 步骤 | 子任务 | Agent | 预估 | 超时 | 重试 | 可否跳过 |
|:----:|:------|:-----:|:----:|:----:|:----:|:--------:|
| Precheck | 交易日判断 | 墨涵 | 即时 | — | — | — |
| Step0 | 市场扫描 | 玄知 | 5min | 8min | 1次 | ❌ |
| Step1 | 结构化分析 | 墨衡 | 10min | 13min | 1次 | ❌ |
| Step2 | 报告草稿 | 墨萱 | 5min | 8min | 1次 | ⚠️ 可选 |
| Step3 | 质量审查 | 墨衡 | 5min | 8min | 1次 | ❌ |
| Step3.5 | 战略复核 | 玄知 | 5min | 8min | 1次 | ⚠️ 可选 |
| Step4 | 汇总定稿 | 墨萱 | 5min | 8min | 1次 | ❌ |
| Step5 | 飞书推送 | 墨涵 | 2min | 3min | 2次 | ❌ |
| **总计** | 8个阶段 | — | **~37min** | **~56min** | — | — |

> 实际全流程目标: 08:00 → 08:37 完成（含 15% 缓冲）

---

## 6. 故障处理

### 6.1 delivery 格式问题

现有 cron 配置中 delivery.to 使用了 `feishu:chat:` 前缀而非裸 `chat:` 前缀。
**修复方法:** `openclaw cron update ce760f90 --delivery-to "chat:oc_72bacde2a63f824bd011718fbe58f48a"`

### 6.2 cron session 超时

若 1800s (30min) 超时到期但管线未完成：
1. 检查 `signals/checkpoints/` 查看已完成的步骤
2. 重新触发 cron（或手动 import 调度器执行 `pipeline.resume()`）
3. 检查哪个步骤耗时异常

### 6.3 子 agent 未响应

1. 检查子 agent 的心跳: `signals/consensus/heartbeat/{agent}_hb_*.json`
2. 检查 trigger 文件是否存在
3. 如果子 agent cron 未运行，手动调度

### 6.4 熔断恢复

1. 分析 `{task_id}_ABORT.json` 中的失败原因
2. 解决问题后删除 ABORT checkpoint
3. 重新执行 `pipeline.run()`（会扫描 .done 跳步）
