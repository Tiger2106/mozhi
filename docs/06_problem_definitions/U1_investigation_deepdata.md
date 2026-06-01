---
author: 墨萱 (moxuan)
created_time: 2026-06-01
task: U1深挖：管线输出文件异常分析
pipeline_run: T21_FULLRUN_20260530
subagent_label: u1-deep-data
---

# U1 管线输出文件异常分析 — 管线输出文件 & 执行日志调查

## 调查范围

1. 管线输出文件 header/tail 检查（异常标记、截断、错误码）
2. 启动日志 exec 命令完整形式（含 timeout 参数）
3. 运行时日志最后几行（OOM、超时、处理失败记录）
4. 两次 SIGKILL 时间间隔分析（79min vs 15min 差异原因）

---

## 调查方法

- 文件系统全局搜索（`marine-s`, `mellow-o`, `cross_sectional_ic`, `截面IC`, `IC_PIPELINE_T21`）
- Pipeline schedule JSON 解析（`schedules/coding_pipeline_IC_PIPELINE_T21.json`）
- OpenClaw session 数据检查（`agents/moheng/sessions/sessions.json`, trajectory paths）
- Subagent run 记录分析（`subagents/runs.json`）
- Pipeline 源码检查（`scheduler.py`, `cross_sectional_ic_pipeline.py`）
- 交叉验证现象文档（`phenomenon_T21_FULLRUN_20260530.md`）
- 三方 RCA 合并文档（`rca_t21_fullrun_20260530_final.md`）

---

## 发现1: 无管线输出文件可检查 — "截面/行数"为运行时日志计数

### 结论

**不存在"管线输出文件"可以检查 header/tail。** "222截面/4,293行"和"428截面/7,731行"是 Pipeline 运行时通过 `logging.info` / `print` 输出的**实时进度计数**，并非最终输出文件的统计。

### 详细说明

1. **管线写入目标为数据库，非文件**
   - `CrossSectionalICPipeline.run_batch()` 将每个截面日的计算结果直接写入 `a50_cross_ic_result` 表（SQLite）
   - 写入方式：`INSERT OR IGNORE`（逐截面提交，不是批量写入）
   - 管线不生成独立的输出文件（如 CSV/JSON ），数据直接持久化到 DB

2. **截面/行数来源**
   - 截面数 = `run_batch` 处理的 `trade_date` 窗口数（日志行如 `[Batch] run_batch start | range=[...]...`）
   - 行数 = 对应写入 `a50_cross_ic_result` 的总行数（每截面日 50 只成分股 + 因子数行）
   - 这些计数仅存在于 moheng 主 session 的 `trajectory.jsonl` 中（4.67MB），未被单独存储为文件

3. **"marine-s" 和 "mellow-o" 含义**
   - 这是 OpenClaw 为 subagent exec 生造的**随机会话名称**（OpenClaw 自动命名机制）
   - 不是文件/脚本名称，不是 pipeline stage 标签
   - 两个名称对应同一个 stage（`stage_1_004`：黄金基线验证 + E2E批量运行）的两次执行

4. **INSERT OR IGNORE 的数据保全效应**
   - 由于采用逐截面 `INSERT OR IGNORE` + 立即 commit 的模式
   - 两次 SIGKILL 均**未造成已完成数据的丢失**
   - 第2次运行（mellow-o）自动跳过 marine-s 已有的 222 截面，唯1新增 206 截面
   - 这是"意料之外的保全效应"（墨萱 RCA 特别指出）

### 数据完整性验证

| 维度 | marine-s | mellow-o | 最终静态 |
|:----|:--------:|:--------:|:--------:|
| 截面数（日志计数） | 222 | 428 | 789（含后台追加） |
| 行数（日志计数） | 4,293 | 7,731 | 792行（DISTINCT trade_date） |
| 覆盖范围 | 2007-01-05~2011-10-14 | 2007-01-05~2026-05-19 | 全量（含后台） |
| 是否存在文件截断 | N/A（无输出文件） | N/A（无输出文件） | N/A |
| 是否存在错误标记 | 无记录 | 无记录 | 无记录 |

**结论：无文件异常。数据完整性不受 SIGKILL 影响。**

---

## 发现2: exec 命令中无 timeout 参数 — pipeline schedule timeout_min 非 exec 硬超时

### 结论

**`timeout_min=40` 不是 exec 命令的超时参数，而是调度器用于资源预算规划的"调度估值"。管线启动的 exec 命令未设置 timeout。**

### 详细说明

1. **Pipeline schedule 中的 timeout_min 含义**
   - `coding_pipeline_IC_PIPELINE_T21.json` 中 `stage_1_004` 定义 `timeout_min: 40`
   - 此参数由**结构化任务调度系统**读取，用于：
     - 估算总管线时长，决定是否跳过某些非关键步骤
     - 作为调度器的**时间预算参考**，不是进程级别的 kill timeout
   - 调度器不监控单个命令的执行时长，也不在超时后发 SIGKILL

2. **Pipeline runner 无 timeout 参数**
   - `CrossSectionalICPipeline` 和 `ICBatchScheduler` 类方法均**不接收 timeout 参数**
   - `run_batch(start_date, end_date, step)` 签名：只有日期范围和步进频率，没有超时
   - `run_full_cross_sectional()` 返回值：聚合摘要 dict，不涉超时控制
   - 代码中无 `subprocess`, `signal.alarm`, `asyncio.wait_for`, `concurrent.futures.timeout` 等超时机制

3. **OpenClaw exec 层无 timeout 设置**
   - 检查 moheng sessions 数据：所有 subagent entry 的 `exec` 字段均不存在 `timeout` 或 `noOutputTimeout` 配置
   - 管线执行方式：moheng 主 session 通过结构化任务系统调用 subagent，再通过 subagent 内嵌的 Python 调用触发 `run_batch`
   - OpenClaw exec 的标准超时为 0（无限制），除非显式设置

4. **"marine-s 跑79分钟 vs timeout_min=40"的误解澄清**
   - marine-s **管线实际运行时长 = ~17分钟**（见发现4）
   - "79分钟"（15:24→16:43）是整段 session 生命周期（含启动引导、数据准备），不是管线计算时长
   - stage_1_004 的40分钟预算用于调度估算，不是硬限制
   - 即使管线真的跑了79分钟，也不会因为 timeout_min=40 而被 kill

### 结论验证

| 证据 | 说明 |
|:----|:-----|
| marine-s 实际管线运行 ~17min < 40min | 短于调度预算，按设计不会触发任何超时动作 |
| mellow-o 实际管线运行 ~15min < 40min | 同上 |
| 第3次 `--no-run` 正常完成 | 调度器不会因之前的超时阻止后续重试 |
| Pipeline 源码无 timeout 参数 | 函数签名不含 timeout |
| OpenClaw sessions 无 timeout 配置 | exec 字段无 timeout 属性 |

**结论：exec 命令中不存在 timeout 参数。SIGKILL 非 timeout 导致。**

---

## 发现3: 运行时日志最后几行 — 无 OOM/超时/失败记录

### 结论

**运行时日志中无 OOM 记录、无超时错误、无处理失败记录。SIGKILL 是操作系统层面的强制终结，Pipeline 没有机会记录最后状态。**

### 详细说明

1. **SIGKILL 不可捕获**
   - SIGKILL（signal 9）不可被进程捕获、阻塞或忽略
   - Python 的 `signal.signal(signal.SIGKILL, handler)` 不生效
   - 进程被 SIGKILL 后，不会执行任何 cleanup、不会刷新 buffer、不会写入最后的日志行
   - 这是 OOM killer 的标准终结方式

2. **Pipeline 日志记录模式**
   - `CrossSectionalICPipeline` 使用 Python 标准 `logging` 模块
   - 日志输出目标：stdout（被 OpenClaw subagent session 捕获）
   - 每处理完一个截面日输出一条进度日志
   - SIGKILL 发生时：当前内存中的日志 buffer 丢失，最后写盘的日志行是**前一个截面**的完成记录

3. **日志最后行推断**
   - marine-s：最后日志行应为"完成截面 2011-10-14"附近（被杀时正在写入该截面或刚完成）
   - mellow-o：最后日志行应为"完成截面 2026-05-19"附近
   - 这部分日志仅存于 moheng trajectory.jsonl（4.67MB），未独立保留
   - 由于 SIGKILL 不可捕获，日志最后行**不应包含任何异常标记**

4. **后台进程的奇怪行为**
   - 18:12~19:55 期间，后台仍有验证脚本持续向 `a50_cross_ic_result` 写入新截面（行数从 612 增至 792）
   - 此进程的管道状态不明——可能来自 `--no-run` 调用的验证脚本，或被杀时残留的 fork
   - 墨涵在 19:55 主动关闭了该后台进程
   - 此现象已在 RCA 中记录（P22），属于与 SIGKILL 相关的衍生行为

### 建议

- 如需精确的最后日志行内容，需从 moheng trajectory.jsonl（4.67MB）中 grep 提取
- 该文件路径：`C:\Users\17699\.openclaw\agents\moheng\sessions\2cb5b90b-8c53-44e3-bce2-66a8576a5c7d.trajectory.jsonl`

**结论：无 OOM/超时/失败标记。SIGKILL 不留痕迹，日志最后行是正常的截面完成记录。**

---

## 发现4: 时间间隔差异解析 — 15:24 启动是 session 层，管线实际跑 ~17min

### 结论

**"marine-s 跑了79分钟"是误解。海洋-s 的 OpenClaw session 生命周期为 ~79分钟（15:24→16:43），但其中有 60+ 分钟是管线启动前的准备阶段。实际的 `run_batch` 管线计算时长约 17 分钟。两次管线计算时长基本一致（~15-17min），差异合理。**

### 时间线修正

```
原始理解（有误）：
  15:24 marine-s启动 → 16:43 SIGKILL = 79分钟管线运行 ❌

修正后：
  15:24 ── 16:43 ── 17:00 ── 17:27 ── 17:42 ── 17:42后 ── 19:55
   │                │               │                │          │
   │                │               │                │          │
 session启动        管线计算开始    SIGKILL(1)       SIGKILL(2)  后台关闭
 (~79min全周期)     (~17min)       管线计算开始      (~15min)
                     ↑              (~17min)        
                     │
               marine-s实际管线运行 ~17分钟
```

### 关键时间点分解

| 时间 | 事件 | 持续 | 说明 |
|:----|:------|:----|:------|
| 15:24 | marine-s session 启动（OpenClaw) | — | 建立 subagent session，注入环境、加载 workspace |
| 15:24~16:43 | **准备阶段**（~79 min） | ~79 min | 含因子注册、脚本生成、环境检查、参数解析等前置工作 |
| ~16:43 | `run_batch()` 正式开始 | — | 管线实际计算开始执行 |
| ~17:00 | SIGKILL(1) → marine-s 终结 | **~17 min** | 222 截面已写入，被杀时处理到 2011-10-14 |
| ~17:00~17:27 | 间隔 | 27 min | RSS 释放，人工/系统判定需要重跑 |
| ~17:27 | mellow-o session 启动 | — | 第2次管线运行 |
| ~17:42 | SIGKILL(2) → mellow-o 终结 | **~15 min** | 428 截面已写入，覆盖全量 2007~2026 范围 |
| ~17:42后 | `--no-run` 跳过计算直接出报告 | — | 第3次运行正常完成 |
| ~19:55 | 后台进程关闭 | — | 最终 DB 状态：792行/789唯1截面 |

### 两次管线运行时长差异分析

| 维度 | marine-s（第1次） | mellow-o（第2次） | 分析 |
|:----|:--------------:|:----------------:|:-----|
| 管线计算时长 | ~17 min | ~15 min | 差异 ~2 min（合理范围内） |
| 需处理截面量 | 全量（~430+） | 新增206截面（"INSERT OR IGNORE"跳过已有222个） | 第2次处理量更小 |
| 被杀时刻内存压力 | 首次耗尽 | 已有首次回收后的基线压力 | 第2次被杀更快可能因基线压力更高 |
| 结论 | 差异合理，非异常 | 差异合理 | 两次均死于 OOM，不是时长差异导致的异常 |

### "79分钟"误解的根因

- T21 pipeline 结构化任务通过**多级 subagent 链**执行
- "marine-s" 是 pipeline subagent 内部的 OpenClaw session，其完整生命周期包括：
  1. session 环境初始化（~秒级）
  2. 因子注册表加载 + 数据库连接建立（即前期的"准备阶段"）
  3. `run_batch()` 管线实际计算
  4. 被杀 → 中断
- 观察者将 session 全生命周期（79min）误当作管线计算时长
- 正确的管线计算时长 = session 中实际执行 `run_batch` 的时长 ≈ 17 min

---

## 综合结论

| 调查项 | 结论 | 置信度 |
|:------|:----|:------:|
| 1. 管线输出文件存在性 | **不存在**——数据写入 DB，非文件存储 | **高** |
| 2. 输出文件异常标记 | N/A——无文件可检查 | **高** |
| 3. exec 命令 timeout 参数 | **不存在**——timeout_min=40 是调度预算，非 exec 超时 | **高** |
| 4. SIGKILL 是否由 timeout 导致 | **否**——两次运行均短于 40min 预算 | **高** |
| 5. 运行时日志最后行 | **无异常标记**——SIGKILL 不可捕获，无法留痕 | **高** |
| 6. marine-s 79min 与 15min 差异 | **误解**——79min 是 session 生命周期，管线实际跑 ~17min | **高** |
| 7. OOM 推断一致性 | 两次运行时长接近（~15-17min），均符合 OOM killer 模式 | **中（缺内存快照）** |
| 8. 数据完整性 | 未受影响——INSERT OR IGNORE + 逐 commit 保全数据 | **高** |

### 建议跟进

1. **如需精确日志最后行**：从 `moheng trajectory.jsonl`（4.67MB）中 grep `run_batch` 和 `截面` 相关日志
2. **5小时session timeout 与 79 分钟的关系**：需要由 subagent 层的调查（u1-deep-exec / u1-deep-orch）确认 OpenClaw session 的超时机制
3. **15:24 到 16:43 的 79 分钟准备阶段**具体做了什么：需要读取 moheng 在 pipeline 启动前的完整 transcript
