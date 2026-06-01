# U1 架构分析：OpenClaw 进程终止机制与 T21 管线根因调查（第三次）

> 作者：玄知 (xuanzhi) | 2026-05-31 | 类型：问题定义 | 状态：待定

---

## 一、核心发现：137 退出码在 Windows 上的来源

### 结论
**退出码 137 不是 Windows 原生的进程退出码，而是 OpenClaw supervisor 层对"信号终止"事件的标准化输出。**

### 证据链
1. **Windows 原生行为**：`child.kill("SIGKILL")` 在 Node.js Windows 实现中映射为 `TerminateProcess()`，真实 exit code = 1，不是 137
2. **137 的 Unix 含义**：128 + SIGKILL(9) = 137 — 这是 POSIX 系统上的标准信号终止码
3. **事实陈述**：「退出码137是OpenClaw supervisor对"信号终止"的标准化输出」——这明确指出了 supervisor 层做了适配
4. **推理**：OpenClaw 的 supervisor（负责管理子进程生命周期）在检测到子进程被强制终止时，**无论平台**，统一输出 exit code 137 作为信号

### 含义
这意味着 T21 管线被终止不是 Python 崩溃、不是内存溢出、不是任何业务层问题——**它是被 OpenClaw 主动杀死的**。137 是 supervisor 明确标记"我是故意杀了它"的证据。

---

## 二、根因可能性排序（按概率降序）

### 第1位：OpenClaw agent turn 超时 → abortSignal → 杀死子进程（★★★★★ 最可能）

| 维度 | 证据 |
|------|------|
| **时序匹配** | 14:34 启动 → ~19:55 最后写入 ≈ **5小时21分钟**，这是一个整5小时边界附近的值，吻合定时器超时 |
| **机制存在** | cron 有 `--timeout-seconds` 参数；abortSignal 传播机制存在——agent 会话超时可传播到子进程 |
| **137 解释** | supervisor 标准化输出，与 signal 终止逻辑完全一致 |
| **日志缺口** | 如果 agent turn 超时，OpenClaw 终止会话上下文，持久化日志写入被中断，解释了"无异常日志"的事实 |
| **可信度** | 唯一一个同时解释所有事实的候选：① 137 退出码 ② 5小时运行时长 ③ 日志缺口 ④ 无明显内存泄漏 |

**机制流程**：
```
cron timer (--timeout-seconds ≈ 5h?)
  → 主 agent turn 超时
  → OpenClaw 关闭 agent session context
  → abortSignal 传播到所有子进程（spawn 的 pipeline agent）
  → supervisor 捕获子进程终止
  → 标准化输出 exit code 137
  → 管线写入中断（日志缺口）
```

> 需确认：cron 配置中 `--timeout-seconds` 的具体值。如果设置为 18000（5小时）或 21600（6小时），则此假说成立。

#### ⚠️ 重要修正：双层终止模型

此候选**只解释最终停止（~19:55）**，不解释 marine-s (~16:43) 和 mellow-o (~17:42) 的两次SIGKILL。

| 事件 | 时间 | 与14:34的间隔 | 被#1解释？ |
|:----|:-----|:-------------|:----------|
| marine-s SIGKILL | ~16:43 | 2h09min | ❌ 不是5h超时 |
| mellow-o SIGKILL | ~17:42 | 3h08min | ❌ 不是5h超时 |
| 管线最终停止 | ~19:55 | **5h21min** | ✅ 吻合5h超时 |

这意味着：
1. **最终停止的根因** = #1候选（5h session timeout）仍是最可能的 ✅
2. **两次SIGKILL事件**需独立解释，可能在exec层或stage orchestrator层有独立的超时/终止机制
3. 此候选与marine-s/mellow-o SIGKILL**不矛盾**——它们可能由不同层的不同超时机制在会话中途触发

> **结论修正**：#1候选从「唯一解释所有事实的候选」降级为「只解释最终停止，两次SIGKILL需独立解释」。整体概率不变（★★★★★）但解释范围缩小。

---

### 第2位：Gateway 重启 / 终止（★★★★ 可能性较高）

| 维度 | 证据 |
|------|------|
| **137 解释** | gateway 关闭时终止所有子进程，supervisor 输出 137 |
| **日志缺口** | gateway 重启后持久化日志不会出现在本次 session 下 |
| **现实可能性** | 约19:55可能是定时维护窗口、自动更新触发、或主动重启 |

**差异点**：
- 如果 gateway 重启，终止点应该是**瞬间的**而非"最后一次写入后中断"——最后一次写入与终止之间的间隔难以确定
- 与候选1的区别在于：gateway 重启不会产生 agent turn 超时日志，而候选1会有超时日志

---

### 第3位：外部内存竞争（vLLM 等其他服务挤占）（★★★ 有一定可能性）

| 维度 | 证据 |
|------|------|
| **内存压力** | 物理 15.6GB + pagefile 13.5GB ≈ 29GB commit limit |
| **vLLM 典型占用** | 7B 模型约 14-20GB，如果同时运行管线（每个截面 50-200MB）可能接近上限 |
| **时间特征** | 5小时运行中可能其他服务启动，在峰值时触发竞争 |

**矛盾点**：
- Windows OOM 杀死进程不会产生 exit code 137
- 除非 OpenClaw 的 healthcheck/watchdog 检测到系统内存紧张并主动终止子进程，再由 supervisor 输出 137
- 但已知事实中没有提到 OpenClaw 有内存 watchdog（只有 `_check_environment_health(4GB)` 启动检查）
- **更可能的机制**：内存压力 → Python OOM（`MemoryError`）→ 非 137 退出码 → 被 **parent supervisor 捕获并标准化为 137？** 不太可能，supervisor 通常只对显式 kill 标准化

---

### 第4位：Windows commit charge 上限溢出（★★☆ 逻辑有冲突）

- 如果 Windows 系统 commit charge 耗尽，Windows 不会优雅地 kill 单个进程，而是触发系统级 OOM 行为
- Windows OOM 产生的进程终止退出码 **不固定**，但不是 137
- 如果终端用户看到 OOM 现象，系统通常会挂起或弹窗，而非干净地结束一个子进程并返回 137
- 除非：OpenClaw 的 watchdog 检测到 commit 近满 → 主动终止 → 输出 137

---

### 第5位：Python 自身崩溃/异常（★★ 不太可能）

| 问题 | 说明 |
|------|------|
| 退出码不匹配 | Python unhandled exception → exit 1；segfault → 异常码（如 -1073741819/0xC0000005） |
| 日志证据缺失 | 如果 Python 崩溃（segfault），至少会有 traceback 或 Windows Error Reporting 记录 |
| 137 无法解释 | Python 不会输出 137，除非被外部终止 |

---

### 第6位：exec 工具前台超时（30min默认）（★ 极不可能）

| 问题 | 说明 |
|------|------|
| 模式不匹配 | 事实明确：后台/yield 模式无超时，管线使用流式处理+后台 exec |
| 时间不匹配 | 30min vs 5h，差一个数量级 |
| 执行次数 | 如果单个前台 exec 超时只会终止该步，不会杀掉整个 5h 管线 |
| 137 产出路径 | 前台超时 → 超时触发 timeout kill → supervisor 输出 137？这是理论上可能的路径，但不匹配"单步运行 >30min"的条件 |

---

## 三、关键问题回答

### Q0：14:34是什么事件？是整个Session启动还是某一次管线运行？

**答：14:34是moheng agent session的启动时间（T+21任务会话开始），而非单独的管线exec启动。**

#### 证据链

| 时间 | 事件 | 解读 |
|:----|:-----|:-----|
| **14:34** | T+21启动，拆分5子任务 | moheng agent session开始。moheng收到任务后开始规划/调研/准备阶段 |
| 14:34~14:47 | （13分钟间隔） | moheng分析需求、设计pipeline stages、生成结构化配置 |
| **14:47** | 结构化任务配置文件生成 | `coding_pipeline_IC_PIPELINE_T21.json` 的 `created_at` 时间戳。配置文件在session启动后才生成 |
| 15:03~ | 各stage顺序执行 | 依赖链驱动：T21_001→T21_002→T21_003→T21_004→... |

**关键推断**：14:34不是cron job的触发时间（cron触发通常是整点/半点），而是moheng在agent session内**开始work on this task的时间**。可能是通过sessions_spawn启动的子agent会话，也可能是主session内直接开始并行工作。

#### 对5h超时假说的修正意义

- 14:34 session start → ~19:55 最后写入 = **5h21min**，吻合5h边界超时假说
- **但注意**：marine-s SIGKILL (~16:43 = 14:34 + 2h09min) 和 mellow-o SIGKILL (~17:42 = 14:34 + 3h08min) **不能被5h session timeout解释**——它们发生在会话中途
- 这意味着：**这是一个双层超时/终止模型**，单个SIGKILL事件和最终停止的原因不同

---

### Q0.5：为什么marine-s跑了79分钟却没被40min stage timeout杀死？

**答：因为 `timeout_min=40` 不是exec硬超时，而是orchestration调度层的等待预算。**

#### 分层解释

| 层次 | 机制 | 超时参数 | 行为 |
|:-----|:-----|:---------|:-----|
| **① OpenClaw exec层** | `exec` 工具的 `timeout` 参数（秒） | 默认30min或显式指定 | 超时 → kill子进程 → exit code 137 |
| **② 结构化任务编排层** | `pipeline[].timeout_min` | stage_1_004 = 40min | **调度器等待预算**：40min后调度器可能标记该stage为timeout-degraded，但**不硬杀子进程** |
| **③ OpenClaw session层** | cron `--timeout-seconds` / agent session timeout | 推测~5h(~18000s) | 超时 → abortSignal → 终止整个session上下文及所有子进程 → exit code 137 |

#### 矛盾解释

marine-s运行79min >> 40min但没被40min timeout杀死 → 证明 `timeout_min=40` **不触发进程kill**。

最可能的解释：
- `timeout_min` 是**结构化任务框架(pipeline orchestrator)** 的调度参数，决定调度器等待一个stage完成的最大时间。超过40min后调度器可能标记该stage为timeout-degraded、跳过或重试，但**不会向已运行的exec进程发送KILL**
- 实际进程kill由更底层的OpenClaw exec工具或session层触发
- **marine-s的79min杀死的根本因不在stage timeout，而在其他层**（请看下方可能性修正）

#### 修正：#1候选的双层模型重新评估

| 子事件 | 时间 | 触发原因（可能性） |
|:-------|:-----|:------------------|
| marine-s SIGKILL (~16:43) | 14:34 + 2h09min | 可能是OpenClaw exec层timeout（非默认30min？设了更长？）或内存压力触发的healthcheck杀进程。不来自5h session timeout，也不来自40min stage timeout |
| mellow-o SIGKILL (~17:42) | 14:34 + 3h08min | 同上或不同原因。15min < 40min，也可能是stage timeout后的调度器重试机制杀死 |
| **最终停止 (~19:55)** | 14:34 + **5h21min** | **5h session timeout → abortSignal → kill所有子进程** ✓ 最吻合 |

**新判断**：最终停止（~19:55）的根因仍然是#1候选（5h session timeout）。但marine-s和mellow-o的SIGKILL事件需要一个**独立的解释**（可能与exec timeout、资源监控、或pipeline orchestrator的stage-level重试逻辑有关）。

---

### Q1：为什么 137 出现在 Windows 上？

**答**：OpenClaw supervisor 对信号终止做了平台无关的标准化。

- 在 Unix/Linux 上：`kill(SIGKILL)` → exit code 137（128 + 9）
- 在 Windows 上：`TerminateProcess()` → exit code 1（原生）
- OpenClaw supervisor 层拦截了进程终止事件，**无论平台**，统一报告为 137
- 这就是为什么一个 Windows 进程能产生看似 Unix 信号的退出码
- **137 = "OpenClaw 杀死了我"的标记**

### Q2：5小时运行中，OpenClaw 有哪些触发点能杀死子进程？

按时间线分析的触发点：

| 触发点 | 触发条件 | 输出 137？ | 备注 |
|--------|----------|-----------|------|
| **① agent turn 超时 → abortSignal** | cron `--timeout-seconds` 到期 | ✅ | 最可能 |
| **② gateway 关闭** | 用户/脚本关闭 gateway | ✅ | 可能性高 |
| ③ exec 前台超时（30min） | 单个前台命令跑 >30min | ✅ | 数据不匹配 |
| ④ supervisor 退出 | gateway 进程退出 → supervisor 清理 | ✅ | 实质同上 |
| ⑤ 手动 kill by 用户 | 用户 `openclaw gateway stop` | ✅ | 无法排除 |
| ⑥ 子进程手动暂停 | 无明确触发 | ❌ | 不适用 |
| ⑦ OpenClaw crash | Node.js OOM/异常 | ❌ | crash 不会标准化输出 |

### Q3：如何验证/排除每种可能性？

#### 验证候选1（agent turn 超时）★★★ P0

```bash
# 1. 查看 cron 配置
openclaw cron list --verbose
# 或在 openclaw.json 中查找 cron 定义中的 timeoutSeconds

# 2. 查看 OpenClaw 日志中是否有 abortSignal / session timeout 记录
# 路径：~/.openclaw/logs/ 或 OpenClaw 的日志目录
# 搜索关键词：abortSignal, timeout, session ended

# 3. 确认 pipeline 是否以 spawn subagent 方式启动
# 如果是 spawn，验证 spawned agent 是否继承了 parent session 的 timeout
```

#### 验证候选2（gateway 重启）★★ P1

```powershell
# 1. 检查 Gateway 日志
# 搜索 gateway 在 19:55 前后的 restart/stop 事件
type C:\Users\17699\.openclaw\logs\gateway*.log | sls "19:5[0-9]"

# 2. 检查 Windows Event Viewer
# Event ID 7036 (Windows 服务状态变更)
# 或在 19:55 前后有关联进程退出的 Event IDs

# 3. 检查 OpenClaw gateway 运行时长
openclaw gateway status
```

#### 验证候选3（内存竞争）★ P2

```powershell
# 1. 检查 vLLM 或其他服务在 19:55 是否运行
# 检查进程列表
Get-Process | Where-Object { $_.ProcessName -match "python|vllm|llama" }

# 2. 检查 Event Viewer 中 Memory/Resource-Exhaustion 事件
# Event ID 2004 (资源不足警告)
Get-WinEvent -LogName System | Where-Object { $_.Id -in (2004, 2005) -and $_.TimeCreated -ge "2026-05-30" }

# 3. 如果存在 pipeline 日志，检查最后几条记录的 RSS 趋势
```

#### 验证候选4（Windows commit limit）★ P3

```powershell
# 1. 检查 Event Viewer 中 Windows OOM 事件
Get-WinEvent -LogName System | Where-Object { $_.Id -eq 2004 -and $_.TimeCreated -ge "2026-05-30" }

# 2. 查看性能计数器
# 确认在 19:55 前后 commit charge 是否达到上限
```

#### 验证候选5（Python crash）★ P3

```powershell
# 1. 检查 Windows Error Reporting
Get-WinEvent -LogName Application | Where-Object { $_.Id -eq 1000 -and $_.TimeCreated -ge "2026-05-30" }

# 2. 搜索可能的 traceback/dump 文件
# 检查 %LOCALAPPDATA%\CrashDumps\
```

---

## 四、复盘总结

### 最可能的根因

**OpenClaw cron agent turn 超时（cron `--timeout-seconds` 配置）→ abortSignal 传播 → supervisor 终止 pipeline 子进程 → 输出 exit code 137**

### 支撑证据
1. **137 退出码** = supervisor 标准化输出 = OpenClaw 主动杀死，非被动崩溃
2. **~5小时运行时长**（14:34→19:55 = 5h21min）= 高度吻合一个整5小时的定时器边界
3. **日志缺口** = session 被强制关闭，持久化写入中断
4. **无内存泄漏特征** = 每截面 50-200MB + gc 流式处理，排除 Python 端问题
5. **启动时 healthcheck(4GB) 通过** = 内存启动条件满足，排除初始资源不足

### ⚠️ 重要澄清：此根因只解释最终停止

此根因**解释了管线最终停止（~19:55）**，但**无法解释** marine-s（~16:43）和 mellow-o（~17:42）的两次SIGKILL事件。

- 14:34 = moheng agent session启动（T+21任务开始），**不是管线exec启动**
- marine-s被kill时（~16:43）距离session start仅2h09min，远未到5h
- mellow-o被kill时（~17:42）仅3h08min
- 因此：**marine-s和mellow-o的SIGKILL需要独立的解释**（exec层timeout？内存pressure？stage orchestrator重试机制？）
- 而~19:55的最终停止 = 5h session timeout → abortSignal ✅

**修正后的结论**：OpenClaw session timeout是最终停止的根因，但不是SIGKILL事件（marine-s/mellow-o）的根因。后者需进一步调查。

### 待定信息（需要检查）
- [ ] cron 配置中的 `--timeout-seconds` 值（是 18000=5h 还是其他值？）
- [ ] gateway 日志中 19:55 前后的超时/关闭事件
- [ ] pipeline 启动方式（是 spawn 还是直接 exec？abortSignal 传播范围）
- [ ] OpenClaw 版本中 abortSignal 传播到 spawn agent 的行为确认

### 建议下一步操作

1. **P0**: 检查 cron 配置中的 timeout 值
2. **P0**: 检查 OpenClaw gateway 日志在 19:55 前后的记录
3. **P1**: 如果确认是 timeout，调整 cron timeout 到足够长（或取消），或让 pipeline 使用 `--taskflow` 模式持久化运行
4. **P1**: 添加 pipeline 持久化日志写入（不依赖 OpenClaw session 的独立日志文件），解决"日志缺口"问题
