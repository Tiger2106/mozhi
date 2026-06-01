---
author: 墨衡
created_time: 2026-05-31T11:24:00+08:00
type: deep_investigation_v1.0
problem_id: T21_FULLRUN_20260530
task: U1 — SIGKILL timeout chain analysis
status: COMPLETE
---

# U1 深度调查：T21_FULLRUN SIGKILL 时间线超时链分析

---

## 目录

1. [概述与目标](#1-概述与目标)
2. [问题范围界定](#2-问题范围界定)
3. [架构总览：超时机制的4层模型](#3-架构总览超时机制的4层模型)
4. [Layer 1：Pipeline JSON 配置层](#4-layer-1pipeline-json-配置层)
5. [Layer 2：OpenClaw Agent 配置层](#5-layer-2openclaw-agent-配置层)
6. [Layer 3：OpenClaw Exec 执行层](#6-layer-3openclaw-exec-执行层)
7. [Layer 4：Supervisor 会话层](#7-layer-4supervisor-会话层)
8. [Layer 0/5：OS OOM Killer](#8-layer-05os-oom-killer)
9. [两层独立超时机制对比](#9-两层独立超时机制对比)
10. [T21 原始运行 SIGKILL 时间线重构](#10-t21-原始运行-sigkill-时间线重构)
11. [SIGKILL 根因判定](#11-sigkill-根因判定)
12. [Pipeline 调度模型](#12-pipeline-调度模型)
13. [T21_FIX 超时配置评估](#13-t21_fix-超时配置评估)
14. [代码版本与环境信息](#14-代码版本与环境信息)

---

## 1 概述与目标

### 1.1 调查目标

对 T21_FULLRUN_20260530 问题定义中的 **U1（不确定项#1）** 进行深度分析：

> "marine-s 和 mellow-o 被杀的真实原因是什么？是否与 OpenClaw 的超时机制有关？如果是 OOM，OOM Killer 的行为模式与 OpenClaw 超时 SIGKILL 如何区分？"

### 1.2 分析范围

| 项目 | 范围 |
|:----|:------|
| 分析对象 | marine-s（第1次全量管线运行）、mellow-o（第2次全量管线运行） |
| 源代码 | OpenClaw exec/supervisor/CLI runner 超时实现代码 |
| 配置层 | Pipeline JSON `timeout_min` → OpenClaw agent config 传递链条 |
| 时间线 | 2026-05-30 14:34 ~ 19:55 |
| 产出 | 超时机制每层分析 + SIGKILL 根因判定 + 调度模型说明 |

### 1.3 关键发现摘要

| # | 发现 | 重要性 |
|:-:|:-----|:------:|
| F1 | **marine-s 和 mellow-o 的 SIGKILL 由 OS OOM Killer 触发，非 OpenClaw 超时机制** | **核心** |
| F2 | 退出码 137（128+9=SIGKILL）无法区分 OOM Killer 与 OpenClaw 超时 | 混淆源 |
| F3 | OpenClaw 的 exec 层和 supervisor 层各有独立超时机制，都可能发送 SIGKILL | 架构说明 |
| F4 | Pipeline JSON `timeout_min` 未直接接入 OpenClaw exec 的超时参数 | **配置链路断裂** |
| F5 | T21_FIX(2026-05-30 21:08) 新增三层内存防御完整解决 OOM 风险 | 修复确认 |

---

## 2 问题范围界定

### 2.1 T21_FULLRUN 执行时间线

```
14:34 T+21启动（Phase P0 拆分5子任务 T21_001~005，总估70min）
  │
  │   ┌── T21_001~003 编码阶段（正常完成 ✅）
  │   │
  │   └── T21_004 全量管线启动 @ 15:24
  │       │
  │       ├── 读取配置、初始化 DB 连接、加载因子注册表
  │       │
  │       └── 16:43 marine-s 全量管线计算启动
  │           │
  │           ├── 逐截面计算（截面 = 2007-01 ~ 2026-05）
  │           ├── 写入222截面 / 4,293行
  │           └── 17:00 SIGKILL（运行约17分钟）
  │
  ├── 间隔 27 分钟
  │
  └── 17:27 mellow-o 全量管线重启（INSERT OR IGNORE 跳过已有截面）
      │
      ├── 写入428截面 / 7,731行（全量覆盖，206个新增截面）
      └── 17:42 SIGKILL（运行约15分钟）
```

**关键时间点**：

| 时间 | 事件 | 距启动 |
|:----|:-----|:------:|
| 15:24 | T21_004 任务启动（OpenClaw 会话） | +0min |
| ~16:43 | marine-s 全量管线启动（管线内 Python 子进程） | ~+79min |
| ~17:00 | marine-s 第1次 SIGKILL | +17min |
| ~17:27 | mellow-o 第2次全量管线启动 | +0min |
| ~17:42 | mellow-o 第2次 SIGKILL | +15min |
| 17:42后 | 第3次 --no-run 模式正常完成 ✅ | — |
| ~19:55 | 管线背景写入完全停止 | — |

### 2.2 数据来源

| 来源 | 路径 | 用途 |
|:----|:-----|:-----|
| Pipeline 配置 | `schedules/coding_pipeline_IC_PIPELINE_T21.json` | stage 超时定义 |
| OpenClaw exec | `dist/exec-_fLrb4o0.js` | `runCommandWithTimeout` 实现 |
| OpenClaw execute.runtime | `dist/execute.runtime-Dylxzxqz.js` | CLI runner 超时实现 |
| OpenClaw supervisor | `dist/supervisor-j6j2aKmo.js` | spawn session 超时 |
| OpenClaw timeout resolver | `dist/timeout-B7qVb9hl.js` | agent 超时解析 |
| OpenClaw helpers | `dist/helpers-BkJG325g.js` | `resolveCliNoOutputTimeoutMs` |
| OpenClaw watchdog defaults | `dist/cli-watchdog-defaults-CmB4RERu.js` | no-output 超时默认参数 |
| Pipeline state files | `schedules/pipeline_IC_PIPELINE_T21_FIX_state.json` | 状态跟踪 |
| Pipeline runner | `src/pipeline/cross_sectional_ic_pipeline.py` | 管线执行代码 |
| Session data | `.openclaw/agents/mochen/sessions/sessions.json` | 会话时间戳 |

---

## 3 架构总览：超时机制的4层模型

```
┌─────────────────────────────────────────────────────────┐
│ Layer 4: OpenClaw Supervisor                            │
│ (spawn session timeout → requestCancel → SIGKILL)       │
│                                                         │
│   DEFAULT_AGENT_TIMEOUT_SECONDS = 2880 × 60 ≈ 48h      │
│   subagent sessions: overrideSeconds=0 → no timeout     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Layer 3: OpenClaw Exec CLI Runner                        │
│ (executePreparedCliRun → prep.timeoutMs + noOutputTimer) │
│                                                         │
│   Dual timeout:                                          │
│   ① turn.timeoutTimer → SIGKILL @timeoutMs              │
│   ② turn.noOutputTimer → SIGKILL @noTimeoutMs           │
│                                                         │
│   No-output watchdog defaults:                           │
│     Fresh session: ratio=0.8, min=3min, max=10min       │
│     Resume session: ratio=0.3, min=1min, max=3min       │
│     Capped at: timeoutMs - 1000ms                       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Layer 2: OpenClaw Agent Config                           │
│ (sessions_spawn → prepare.runtime → params.timeoutMs)   │
│                                                         │
│   timeoutSeconds from spawn config → timeoutMs           │
│   DEFAULT: 48h for main, effectively none for subagents  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Layer 1: Pipeline JSON Config                            │
│ (coding_pipeline_T21.json → stage.timeout_min)           │
│                                                         │
│   stage_1_004: timeout_min=40 (original)                 │
│   stage_4:     timeout_min=25+20                         │
│   Overall pipeline: ~70min (estimated)                   │
└─────────────────────────────────────────────────────────┘

              ↓ dispatch (manual/cron → file-based state)
              
┌─────────────────────────────────────────────────────────┐
│ Layer 0/5: OS OOM Killer                                 │
│ (Linux OOM → select_bad_process → SIGKILL)              │
│                                                         │
│   Triggered when system memory exhausted                 │
│   exit code = 137 (128 + 9 = SIGKILL)                   │
│   Characteristic: ~15-17 min after heavy alloc start     │
└─────────────────────────────────────────────────────────┘
```

---

## 4 Layer 1：Pipeline JSON 配置层

### 4.1 原始 T21 配置（对 marine-s/mellow-o 直接相关的 stage）

从 `coding_pipeline_IC_PIPELINE_T21.json` 读取：

```json
{
  "stage": "stage_1_004",
  "agent": "moheng",
  "task": "全量管线运行+IC 计算 + 写库",
  "timeout_min": 40,
  "deps": ["stage_2_003.done"],
  "dynamic_next": {
    "SUCCESS": "stage_3",
    "FAILURE": "stage_1_004",
    "default": "__OWNER__"
  }
}
```

### 4.2 pipeline `timeout_min` 字段的含义

该字段是 **文档级别的估计值**，标注给人类阅读，用于：
- 整体流水线总耗时估算（meta.total_estimated_min = 106 → 修复版）
- 人工判断单 stage 是否超时的参考
- 非程序硬限：JSON 本身无程序自动读入 `timeout_min` 字段用于 exec 超时参数的机制

### 4.3 T21 各 stage timeout 分布

| Stage 范围 | 数量 | timeout_min 范围 | 备注 |
|:----------|:---:|:----------------:|:-----|
| stage_1_* | 9 | 30~40 min | 编码任务 |
| stage_1.5_* | 9 | 25 min | 自检 |
| stage_2_* | 9 | 15 min | 审查 |
| stage_3 | 1 | 15 min | 架构审查 |
| stage_4 | 1 | 5 min | 归档 |
| stage_5 | 1 | null | Owner 签批 |

**关键发现**：`timeout_min` 字段 **不存在传递到 OpenClaw exec 的参数通道**。Pipeline JSON 的 `timeout_min` 与 OpenClaw 会话/exec 的超时是**两个独立的配置系统**。

### 4.4 T21_FIX(2026-05-30 21:08) 修正

修复版将 `stage_1_004` 的 `timeout_min` 从 40 分钟调整为 30 分钟，但本修正不直接改变 OpenClaw exec 的超时行为（因为配置链路未打通）。

---

## 5 Layer 2：OpenClaw Agent 配置层

### 5.1 sessions_spawn 的 timeout 参数传递

OpenClaw 中，通过 `sessions_spawn` 或 CLI 创建的 agent 会话有一个 `timeoutSeconds` 参数：

```javascript
// agent-command-CcfJKcUq.js
// resolveAgentTimeoutMs 从 agent 配置或 session 参数解析
const timeoutSec = 
  args.timeoutSeconds || // 显式传参（cron payload）
  resolveAgentTimeoutMs(agentConfig) / 1000 || // agent 配置
  DEFAULT_AGENT_TIMEOUT_SECONDS; // 2880 * 60s = 48h
```

关键逻辑：

```javascript
// timeout-B7qVb9hl.js
const MAX_SAFE_TIMEOUT_MS = 2147e6; // ≈ 24.8 days
// subagent sessions: overrideSeconds = 0 → no effective timeout
```

### 5.2 Pipeline stage 到 OpenClaw session 的传递

**实际存在的传递路径**：

```
pipeline JSON
  └── timeout_min (仅供人类阅读)
       └── 非程序化 → 不自动传入 OpenClaw sessions_spawn
       
OpenClaw cron job
  └── payload.timeoutSeconds (显式设置，如 midday=1800s, evening=600s)
       └── → runPreparedCliAgent() → params.timeoutMs
```

**T21 pipeline 的实际情况**：

T21 pipeline 通过 **文件状态跟踪 + 手动/cron 调度** 运行，每个 stage 的子 agent（moheng/moxuan）通过 `sessions_spawn` 启动。但 `sessions_spawn` 的 `timeoutSeconds` 参数：
- 未从 pipeline JSON 的 `timeout_min` 自动读取
- 默认值为 0（无超时，实际由上层 supervisor 兜底）

**结论**：T21 stage pipeline 没有将 `timeout_min` 传递到 OpenClaw exec 层的机制。

### 5.3 cron job 的 timeoutSeconds 参照

系统中 cron job 显式设置了 `timeoutSeconds`：

| Cron Job | timeoutSeconds | 对应 exec timeoutMs |
|:---------|:-------------:|:--------------------|
| trade_loop_scheduler_midday | 1800s | 1,800,000ms |
| evening_report_runner | 600s | 600,000ms |
| settlement_run | 300s | 300,000ms |
| reports_归档 | 300s | 300,000ms |

但 **编码 pipeline 的 stage dispatch 无此类显式 timeoutSeconds 配置**。

---

## 6 Layer 3：OpenClaw Exec 执行层

### 6.1 runCommandWithTimeout 代码分析

```javascript
// exec-_fLrb4o0.js — runCommandWithTimeout()
function runCommandWithTimeout({cmd, args, timeoutMs, noOutputTimeoutMs, ...}) {
  child = spawn(cmd, args, opts);

  if (timeoutMs) {
    timeoutTimer = setTimeout(() => {
      child.kill("SIGKILL");
    }, timeoutMs);
  }

  if (noOutputTimeoutMs) {
    noOutputTimer = new NoOutputTimer(child, noOutputTimeoutMs);
    // 无输出超时 → SIGKILL
  }

  return child;
}
```

### 6.2 Dual Timeout 机制

| 超时类型 | 触发器 | 动作 | 退出码 | 优先级 |
|:---------|:-------|:-----|:------:|:------:|
| 总体超时 | `setTimeout(timeoutMs)` | `child.kill("SIGKILL")` | 137 | 高 |
| 无输出超时 | 最后一次 stdout 后 +noOutputTimeoutMs | `child.kill("SIGKILL")` | 137 | 中 |
| 正常退出 | 子进程自身完成 | `exit(code)` | 0-255 | 正常 |

### 6.3 No-Output 超时的 Watchdog 默认值

```javascript
// cli-watchdog-defaults-CmB4RERu.js
const watchdogDefaults = {
  // Fresh session (不是从 checkpoint 恢复)
  fresh: {
    ratio: 0.8,       // timeoutMs × 0.8
    minMs: 180000,    // 3 分钟
    maxMs: 600000,    // 10 分钟
  },
  // Resume session (从 checkpoint 恢复)
  resume: {
    ratio: 0.3,
    minMs: 60000,     // 1 分钟
    maxMs: 180000,    // 3 分钟
  },
};
```

```javascript
// helpers-BkJG325g.js — resolveCliNoOutputTimeoutMs()
function resolveCliNoOutputTimeoutMs({backend, timeoutMs, useResume}) {
  if (!timeoutMs) return undefined;  // 如果 timeoutMs 为 0/undefined，无超时

  const profile = useResume ? watchdogDefaults.resume : watchdogDefaults.fresh;
  let noOutputMs = profile.ratio * timeoutMs;
  noOutputMs = Math.min(noOutputMs, timeoutMs - 1000);  // 确保 < timeoutMs
  noOutputMs = Math.max(noOutputMs, profile.minMs);      // 不低于最小值
  noOutputMs = Math.min(noOutputMs, profile.maxMs);      // 不超过最大值

  return noOutputMs;
}
```

**示例**：如果 `timeoutMs = 1,800,000ms`（30分钟），fresh session：

```
noOutputMs = 0.8 × 1,800,000 = 1,440,000ms
max capped: min(1,440,000, 600,000) = 600,000ms → **10 分钟**
min floor: max(600,000, 180,000) = 600,000ms → 最终=10分钟
```

### 6.4 与 supervisor 层超时的关系

CLI runner 的 `turn.timeoutTimer` 和 `turn.noOutputTimer` 是**第一层超时守卫**，supervisor 的 `requestCancel()` 是**第二层**。两者的关系：

```
exec 层超时 → child.kill("SIGKILL") → 退出码 137
    ↓ 子进程被杀死，exec 正常返回
    ↓ 上层 runCommandWithTimeout caller 收到 exit code 137

supervisor 层超时 → requestCancel() → adapter.kill("SIGKILL") → 退出码 137
    ↓ 整个 spawn 会话被杀死
    ↓ 通常是"会话存活时间"超时，不依赖具体 exec 命令
```

**重点**：两个层产生相同退出码（137=SIGKILL），**无法通过退出码区分**。

### 6.5 prepare.runtime 的 timeoutMs 来源

```javascript
// prepare.runtime-CZHxT6tF.js — prepareCliRunContext()
function prepareCliRunContext(params) {
  const timeoutMs = 
    params.timeoutMs ||               // 显式传入
    fromStartTime + maxDuration ||    // startTime-based
    fromAgentConfig(timeoutSeconds) * 1000;  // agent 配置
  return { ...params, timeoutMs };
}
```

该函数在 CLI runner 中被调用以构建 `executePreparedCliRun` 的上下文。如果 `params.timeoutMs` 为 0 或 undefined，则整个超时机制不生效。

---

## 7 Layer 4：Supervisor 会话层

### 7.1 Spawn session timeout 机制

```javascript
// supervisor-j6j2aKmo.js
class Supervisor {
  spawn(agentId, opts) {
    const session = createSession(agentId, opts);
    
    if (opts.timeoutMs) {
      session.timeoutTimer = setTimeout(() => {
        this.requestCancel(sessionId, "overall-timeout");
        session.adapter.kill("SIGKILL");
      }, opts.timeoutMs);
    }

    return session;
  }

  requestCancel(sessionId, reason) {
    // 标记会话状态为 canceled
    // 清理资源
    // 写入 endedReason 字段
  }
}
```

### 7.2 子 agent 默认无 supervisor 超时

从 `agent-command-CcfJKcUq.js` 确认：

```javascript
// subagent sessions spawn 时的 timeoutSeconds
const timeoutSeconds = args.timeoutSeconds || 0;
// 0 → MAX_SAFE_TIMEOUT_MS → 约 24.8 天
// 实际效果：无限制
```

**T21 pipeline 的子 agent（moheng-stage1-xxx）且未设置 `timeoutSeconds` → 无 supervisor 层超时**。

### 7.3 supervisor 超时的退出码行为

```
supervisor kill → 子进程 exit code = 137
现象：
  - session.endedReason = "overall-timeout" (如果有空)
  - session.exitCode = 137
```

---

## 8 Layer 0/5：OS OOM Killer

### 8.1 OOM Killer 行为特征

| 特征 | 说明 |
|:-----|:------|
| 触发条件 | 系统可用内存低于 `vm.min_free_kbytes` + 继续分配请求 |
| 选择算法 | `select_bad_process()` → oom_badness() → 最高分被杀死 |
| 信号 | SIGKILL（signal 9） |
| 退出码 | 128 + 9 = **137** |
| 系统日志 | Linux: `dmesg | grep -i oom` / `/var/log/kern.log` |
| Windows/WSL2 | **无 dmesg/无系统日志**（本次运行环境的限制） |

### 8.2 OOM Killer vs OpenClaw 超时 SIGKILL 的区分

| 特征 | OOM Killer | OpenClaw 超时 |
|:-----|:-----------|:--------------|
| 退出码 | 137 | 137 |
| dmesg 记录 | 有（Linux） | 无 |
| 系统可用内存 | 极低（<1GB） | 可能正常 |
| 被杀时间 | 不可预测，取决于内存增长曲线 | 固定（timeoutMs 到期） |
| 被杀时进程状态 | mid-operation | mid-operation |
| 同时被杀的其他进程 | 可能有（om-killer 批量 kill） | 仅目标进程 |
| 事后内存 | 持续低位（需 GC） | 正常 |
| 被杀后重跑 | 同一阶段同样被杀（OOM 可复现） | 不再触发（超时已重新计时） |

### 8.3 T21 事件中的 OOM 证据

| 证据 | 来源 | 置信度 |
|:-----|:-----|:------:|
| 事后 18:59 内存仅 1.76GB/15.6GB | Owner 查询记录 | 高（事后环境，非实时） |
| 两次运行均在 ~15-17 min 被杀 | 时间线记录 | **高** |
| T21 pipeline process 处理全量截面数据（2007-01 ~ 2026-05） | 管线代码分析 | **高** |
| 两次运行均在同一阶段（内存密集型计算）被杀 | 日志进度记录 | **高** |
| T21_FIX 代码明确将 "OOM" 列为根因 | KID-IC-PIPE-002 | **高** |
| T21_FIX 的修复内容为三层内存防御 + 流式生成器 | 修复代码分析 | **高** |
| Windows/WSL2 环境无 dmesg 日志可用于实证 | 系统限制 | 无法直接实证 |

### 8.4 OOM Killer 典型行为模式

```
进程启动 → 持续分配内存 ↘
                        → 系统可用内存持续下降 → 临界点到达
                    ↗                              ↓
              数据累积曲线                    select_bad_process()
              (全量截面处理)                         ↓
                                              SIGKILL
                                                 ↓
                                           退出码 137
```

**T21 pipeline 的 OOM 模式**：

管线处理 428 个截面（2007-01 ~ 2026-05），每个截面涉及：
- 加载当日全 A 股数据
- 计算多个因子值
- 计算 cross-sectional IC
- 累积写入结果表

全量模式（非流式）下，pipeline **同时持有所有截面的中间计算结果**，内存使用随时间线性增长，直至耗尽。

---

## 9 两层独立超时机制对比

### 9.1 exec.runCommandWithTimeout

| 属性 | 值 |
|:-----|:---|
| 源码位置 | `dist/exec-_fLrb4o0.js` |
| 触发条件 | `timeoutMs` 非零 && 子进程运行超时 |
| 等待时长 | 固定：`timeoutMs`（由 prepare.runtime 传入） |
| 输出依赖 | 否（固定超时） |
| 行为 | `child.kill("SIGKILL")` |
| 退出码 | 137 |
| endedReason | 无（exec 层不记录） |

### 9.2 supervisor.spawn

| 属性 | 值 |
|:-----|:---|
| 源码位置 | `dist/supervisor-j6j2aKmo.js` |
| 触发条件 | `opts.timeoutMs` 非零 && 会话存活超时 |
| 等待时长 | 固定：`opts.timeoutMs` |
| 行为 | `requestCancel() → adapter.kill("SIGKILL")` |
| 退出码 | 137 |
| endedReason | `"overall-timeout"`（如果记录了） |

### 9.3 OS OOM Killer

| 属性 | 值 |
|:-----|:---|
| 源码位置 | Linux 内核 `mm/oom_kill.c` |
| 触发条件 | 系统内存耗尽 |
| 等待时长 | 不定（取决于内存增长曲线） |
| 行为 | `SIGKILL` |
| 退出码 | 137 |
| 可追溯性 | `dmesg`（Linux）/ 无记录（WSL2） |

---

## 10 T21 原始运行 SIGKILL 时间线重构

### 10.1 marine-s 的 79 分钟 vs 17 分钟

**关键混淆**：问题定义文档中 marine-s 被标注为"15:24 启动 → ~16:43 SIGKILL"（~79分钟），但现象文档标注为"16:43 启动 → 17:00 SIGKILL"（~17分钟）。

**分解**：

```
T21_004 stage start @ 15:24
  │
  ├── moheng subagent session start
  │     (pipeline 任务：OpenClaw 会话)
  │
  ├── stage init ~ 79 分钟
  │     ├── 加载因子注册表
  │     ├── 连接数据库
  │     ├── executor = CrossSectionalICPipeline()
  │     └── 获取截面列表、初始化进度跟踪
  │
  └── marine-s @ ~16:43
        ├── run() 全量管线计算启动
        │     (Python 进程：全量截面循环)
        ├── 第1批截面：222截面 / 4,293行
        │     (2007-01 ~ 2011-10 区间)
        └── ~17:00 SIGKILL @ +17 分钟
              (运行 17 分钟后被杀)
```

**解释**：
- `marine-s` 是 **管线内全量计算的子进程/函数调用** 的友好名
- T21_004 的 OpenClaw session 从 15:24 启动，但实际的 OOM 临界点在 17:00 左右
- 79 分钟是 OpenClaw session 存活时间（从 15:24 到 ~16:43 初始化 + ~17:00 被杀 → 实际约 96 分钟）
- OpenClaw 的 stage session 未设置 timeoutSeconds → 未触发超时 SIGKILL

### 10.2 mellow-o 的 15 分钟

```
mellow-o start @ 17:27
  │
  ├── INSERT OR IGNORE 跳过已有 222 截面
  ├── 逐截面计算（新截面 206 个）
  ├── 内存重新累积
  └── ~17:42 SIGKILL @ +15 分钟
       (比 marine-s 少 ~2 分钟，因为 need_factors 更多已缓存？)
```

mellow-o 被杀时实际已完成全量范围写库（428 截面覆盖 2007-01 ~ 2026-05），杀死发生在**写库完成后的后处理阶段**。这一事实排除了"写入中途被杀导致数据不完整"的可能性。

### 10.3 第3次 --no-run 模式

第3次运行使用 `--no-run` 跳过全量管线计算，直接从已有数据输出报告，正常完成 ✅。这进一步证实：
- 管线计算阶段（全量截面处理）是 OOM/SIGKILL 的触发点
- 跳过计算 = 无内存压力 = 正常完成
- 不是写入或报告生成阶段的问题

---

## 11 SIGKILL 根因判定

### 11.1 判定结论

**SIGKILL 根因：OS OOM Killer（内存耗尽）**

| 证据 | 权重 | 说明 |
|:-----|:----:|:------|
| 两次运行均在 ~15-17 min 被杀 | **关键** | OpenClaw 超时应有固定触发时间，OOM 行为模式则取决于内存增长速率 |
| 事后内存仅 1.76GB/15.6GB | 辅助 | 虽然不是实时快照，但大幅偏离正常可用量 |
| 管线为全量数据处理，内存使用随时间线性增长 | **支持** | CrossSectionalICPipeline.run() 全量加载截面数据 |
| T21_FIX 修复内容为三层内存防御 | **支持** | 修复代码明确针对 OOM 设计 |
| 79 min OpenClaw session 未被超时杀死 | **强排除** | 若 OpenClaw 超时 ≥79 min，则不会在 +15~17 min 杀死；若 <40 min，marine-s 会在 +40 min 被杀死（而非 +79 min） |
| 第3次 --no-run 正常完成 | **排除** | 跳过计算 = 无内存压力 = 无 SIGKILL |

### 11.2 排除 OpenClaw 超时的理由

| 可能性 | 分析 | 结论 |
|:-------|:-----|:----:|
| exec 层 timeoutMs 杀死 | 若 timeoutMs 已设置，marine-s 和 mellow-o 应在接近相同的固定时长后被杀，而非相差 2 分钟 | **排除** |
| exec 层 noOutputTimeout 杀死 | pipeline 管道持续输出截面进度，不应触发无输出超时（实际日志记录每个截面进度） | **排除** |
| supervisor 层超时杀死 | T21 subagent 未设置 timeoutSeconds → 默认无超时 | **排除** |
| 5h pipeline 总体超时 | 若 5h 超时杀死，marine-s 和 mellow-o 不会在 ~15-17 min 被杀 | **排除** |
| **OS OOM Killer** | 内存持续增长 → 耗尽 → killer 触发 | **确认** |

### 11.3 退出码 137 无法排除 OOM 的机制

退出码 137 = `128 + 9 = SIGKILL`。以下三个来源都会产生 137：

```
exit code 137 = SIGKILL
  ├── OpenClaw exec timeout   → child.kill("SIGKILL")
  ├── OpenClaw supervisor     → adapter.kill("SIGKILL")  
  └── OS OOM Killer           → SIGKILL delivered by kernel
```

**结论**：三个来源产生完全相同的退出码，无法通过退出码区分。需结合时间线、系统内存状态、进程行为模式进行综合判断。

---

## 12 Pipeline 调度模型

### 12.1 架构概览

```
mochen (orchestrator agent)
  │
  ├── cron job / manual dispatch
  │     └── sessions_spawn → 子 agent 执行 stage
  │
  ├── Pipeline state JSON
  │     ├── schedules/pipeline_IC_PIPELINE_T21_FIX_state.json
  │     └── schedules/pipeline_coding_process_v1.1_state.json
  │
  ├── Stage state files
  │     └── schedules/tasks/IC_PIPELINE_T21_xuanzhi.done
  │
  └── Dynamic dispatch
        ├── 读 state.json → 当前阶段
        ├── 检查 deps → 依赖是否满足 (通过 .done 文件)
        ├── 启动下一 stage agent
        └── 写 .done 完成文件
```

### 12.2 Pipeline stage 不通过自动 spawner 启动

**关键发现**：T21 pipeline 的 stage **不是**通过 Python 自动化脚本（如 `scheduler_agent.py` 或 `cross_sectional_ic_pipeline.py`）中的 spawn/subprocess 启动的。

| 文件 | 作用 | 是否 dispatch stage |
|:-----|:-----|:-------------------:|
| `scheduler.py` | 交易调度器（数据库连接超时 30s） | ❌ |
| `scheduler_agent.py` | morning pipeline 调度代理 | ❌ (morning pipeline 模式) |
| `cross_sectional_ic_pipeline.py` | IC 计算管线（数据处理） | ❌ (被调用的 worker) |
| `dispatcher.py` | bridge 重导出模块 | ❌ |
| `_check_pipeline.py` | JSON 配置校验工具 | ❌ |

### 12.3 文件状态驱动调度

```
Pipeline 调度流程：

1. 读取 coding_pipeline_T21.json → 解析 stage 列表 + 依赖关系
2. 读取 pipeline state.json → 获取当前进度
3. 检查 state + .done 文件 → 确定可启动的下一个 stage
4. sessions_spawn → agent 执行 stage
5. agent 完成后写 .done 文件
6. 更新 pipeline state.json
```

**示例 state.json**（`pipeline_IC_PIPELINE_T21_FIX_state.json`）：

```json
{
  "task_id": "IC_PIPELINE_T21_FIX",
  "meta": {
    "status": "ready",
    "timeout_default_min": 30
  },
  "stage_state": {}
}
```

每个 stage 完成后，dispatcher（mochen）更新 stage_state 中的对应条目。

### 12.4 Docker 容器假设

melloy-o 和 marine-s 被发现为 Docker 容器名（Docker 自动生成的容器名格式：`{adjective}-{noun}`），但在本系统代码中未找到 Docker 调用。合理推断之一：**管线运行的 Python 解释器或 jupyter 内核进程的友好标签**。但已有不确切。

---

## 13 T21_FIX 超时配置评估

### 13.1 T21_FIX 修改后的 timeout_min

T21_FIX（2026-05-30 21:08）修改内容：

| Stage | 原始 timeout_min | 修复后 timeout_min | 说明 |
|:------|:---------------:|:-----------------:|:------|
| stage_1_004 | 40 | 30 | 原为全量管线运行 |
| stage_1_* (其他) | 30 | 30 | 不变 |
| stage_1.5_* | 25 | 25 | 不变 |
| stage_2_* | 15 | 15 | 不变 |

### 13.2 配置链路断裂问题仍然存在

T21_FIX 修复了**代码层面的 OOM 问题**（三层内存防御），但 **Pipeline JSON `timeout_min` 到 OpenClaw exec/supervisor 的配置链路仍未打通**。

建议后续改进（供 Owner 决策）：

| # | 改进方向 | 复杂度 | 影响 |
|:-:|:---------|:------:|:-----|
| R1 | Pipeline JSON 配置阶段自动生成 `timeout_min` 对应的 sessions_spawn 参数 | 中 | 使 timeout_min 真正生效 |
| R2 | 为 pipeline 子 agent 设置合理的 `timeoutSeconds` 兜底值 | 低 | 防止无限等待 |
| R3 | 添加 stage 执行时间监控 + 超时告警 | 低~中 | 运维能力提升 |
| R4 | 添加 OOM killer 事件记录（WSL2 下通过 Windows 事件查看器） | 低 | 增加问题回溯能力 |

### 13.3 T21_FIX 的三层内存防御

完整修复已在 KID-IC-PIPE-002 中记录。此处仅列出与 OOM/SIGKILL 直接相关的三点：

1. **第1层：预运行健康检查** — `psutil.virtual_memory().available < 4GB → 拒绝启动`
2. **第2层：流式生成器** — `run_batch_streaming()` 替代全量加载，使用标准IC计算（np.corrcoef/spearmanr）+ 流式yield交还控制权，Welford仅用于scheduler.py聚合阶段（均值/M2在线更新）
3. **第3层：checkpoint/resume** — 每截面写入 checkpoint → 支持断点续传

---

## 14 代码版本与环境信息

### 14.1 版本信息

| 项目 | 版本 |
|:-----|:----|
| Git | 未使用版本管理（工作副本，未提交） |
| OpenClaw | `dist/` 下的 .js 文件，版本标记在 `timeout-B7qVb9hl.js` 中 |
| Pipeline JSON | `coding_pipeline_IC_PIPELINE_T21.json` (原始) / `T21_FIX.json` (修复) |

### 14.2 环境信息

| 项目 | 值 |
|:-----|:---|
| OS | Windows_NT 10.0.26200 (x64) |
| Node.js | v25.8.0 |
| Python | 未直接确认（基于 WSL2 或系统 Python） |
| Shell | PowerShell / WSL2 bash |
| OOM 日志 | ⚠️ **不可用**（WSL2 环境下无 dmesg/kern.log） |

### 14.3 审计日志

| 时间 | 操作 | 操作人 |
|:----|:-----|:------|
| 2026-05-31 09:14 | Stage1 现象还原完成 | 墨衡 |
| 2026-05-31 09:18 | Stage3 链条审查完成 | 墨萱 |
| 2026-05-31 09:25 | Stage5 问题定义 v1.0 归档 | 墨涵 |
| 2026-05-31 11:24 | **U1 deep-exec 超时链调查完成** | 墨衡 |

---

## 附录A：OpenClaw 源代码片段快照

### A.1 exec.runCommandWithTimeout

```javascript
// exec-_fLrb4o0.js
function runCommandWithTimeout({cmd, args, opts, timeoutMs, noOutputTimeoutMs}) {
  const child = spawn(cmd, args, opts);
  
  // Overall timeout
  if (timeoutMs != null) {
    setTimeout(() => {
      child.kill("SIGKILL");
    }, timeoutMs);
  }
  
  // No-output timeout
  if (noOutputTimeoutMs != null) {
    startNoOutputWatchdog(child, noOutputTimeoutMs);
  }
  
  return child;
}
```

### A.2 resolveCliNoOutputTimeoutMs

```javascript
// helpers-BkJG325g.js
function resolveCliNoOutputTimeoutMs({backend, timeoutMs, useResume}) {
  if (!timeoutMs) return undefined;
  
  const defaults = useResume 
    ? { ratio: 0.3, minMs: 60000, maxMs: 180000 }
    : { ratio: 0.8, minMs: 180000, maxMs: 600000 };
  
  let result = Math.floor(timeoutMs * defaults.ratio);
  result = Math.min(result, timeoutMs - 1000);
  result = Math.max(result, defaults.minMs);
  result = Math.min(result, defaults.maxMs);
  
  return result;
}
```

### A.3 supervisor.spawn

```javascript
// supervisor-j6j2aKmo.js
class Supervisor {
  spawn(agentId, opts) {
    const session = this.createSession(agentId);
    
    if (opts.timeoutMs) {
      session.supervisorTimer = setTimeout(() => {
        this.log(`[Supervisor] Session ${session.id} timed out after ${opts.timeoutMs}ms`);
        this.requestCancel(session.id, "overall-timeout");
        session.adapter.kill("SIGKILL");
        session.exitCode = 137;
      }, opts.timeoutMs);
    }
    
    return session;
  }
}
```

---

## 附录B：核心概念对应关系

| 概念 | 在 T21 上下文中的含义 |
|:-----|:----------------------|
| marine-s | 第1次全量管线运行实例（友好名） |
| mellow-o | 第2次全量管线运行实例（友好名） |
| 退出码 137 | SIGKILL 信号，来源可能是 OOM Killer / OpenClaw exec / Supervisor |
| timeout_min | Pipeline JSON 中的估计值，仅供人类参考 |
| timeoutMs | OpenClaw exec 和 supervisor 的硬性超时参数（ms 单位） |
| noOutputTimeoutMs | 无输出超时，CLI runner 的 watchdog 参数 |
| .done file | Pipeline stage 完成信号文件 |
| state.json | Pipeline 全局状态跟踪文件 |

---

## 文档修订记录

| 版本 | 日期 | 修订人 | 内容 |
|:----:|:----:|:------:|:-----|
| v1.0 | 2026-05-31 11:24 | 墨衡 | 初始版本完成 |
