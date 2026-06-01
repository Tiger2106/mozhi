---
author: 墨衡
created_time: 2026-05-31T10:58+08:00
type: investigation_report_v1.0
investigation_id: U1
related_problem: T21_FULLRUN_20260530
status: DRAFT
---

# U1调查：OpenClaw exec模块超时/终止机制深挖

## 核心结论

| 结论 | 摘要 |
|:-----|:------|
| C1 | OpenClaw exec工具**默认超时 = 1800秒（30分钟）**，仅对非后台（non-background）命令生效 |
| C2 | 后台/延迟（background/yield）模式下**无超时**，进程可无限运行 |
| C3 | 退出码137来源于 `SIGKILL` 信号（Unix约定：128+9=137） |
| C4 | **T21管线被杀大概率不是OpenClaw exec超时导致**——但也不能完全排除 |
| C5 | `openclaw.json` 中可配置 `tools.exec.timeoutSec` 覆盖默认值，当前未设置 |

---

## 1. OpenClaw exec模块架构

OpenClaw的exec机制分为两条独立的代码路径：

### 路径A：exec工具（模型调用用）

```
bash-tools.schemas.js          # 工具schema定义
    ↓
bash-tools-BBNmvkSq.js         # createExecTool() → 工具handler → runExecProcess()
    ↓
bash-tools.exec-runtime.js     # runExecProcess() → supervisor.spawn()
    ↓
supervisor-j6j2aKmo.js         # createProcessSupervisor() → 进程管理 + 超时定时器
```

**此路径是T21管线被调用时**走的路径。

### 路径B：内部工具函数

```
exec-_fLrb4o0.js               # runCommandWithTimeout() / runExec()
```

此路径**不被exec工具使用**，被bonjour-discovery、browser-open、doctor-sandbox等内部模块调用。

---

## 2. 默认超时值

### 2.1 exec工具超时（路径A）

**默认值：1800秒 = 30分钟**

推导链条：
1. `bash-tools-BBNmvkSq.js` 行1855:
   ```javascript
   const defaultTimeoutSec = typeof defaults?.timeoutSec === "number" && defaults.timeoutSec > 0
     ? defaults.timeoutSec
     : 1800;
   ```
2. 用户可传参 `timeout`，若传则用该值；否则 `effectiveTimeout = explicitTimeoutSec ?? defaultTimeoutSec`
3. **关键例外**：若 `background=true || yieldMs` 被请求且无显式timeout，则 `effectiveTimeout = null`（无超时）：
   ```javascript
   const effectiveTimeout = allowBackground && explicitTimeoutSec === null && (backgroundRequested || yieldRequested)
     ? null
     : explicitTimeoutSec ?? defaultTimeoutSec;
   ```
4. `runExecProcess()` 将 `timeoutSec` 转为 `timeoutMs` 传给 supervisor：
   ```javascript
   const timeoutMs = typeof opts.timeoutSec === "number" && opts.timeoutSec > 0
     ? Math.floor(opts.timeoutSec * 1e3)
     : void 0;
   ```
5. supervisor仅当 `clampTimeout(timeoutMs)` 返回非undefined值才设置超时定时器。

### 2.2 默认超时生效条件矩阵

| 模式 | 超时生效？ | 默认值 |
|:----|:----------|:-------|
| 前台（默认） | ✅ | 30分钟 |
| `background=true` | ❌ 无超时 | — |
| `yieldMs=10000` | ❌ 无超时 | — |
| 前台 + 显式 `timeout=7200` | ✅ 使用指定值 | 2小时 |
| 后台 + 显式 `timeout=7200` | ✅ 使用指定值 | 2小时 |

### 2.3 等效替代机制

**`DEFAULT_JOB_TTL_MS`** = 30分钟（`bash-tools.exec-runtime.js`），但此TTL**仅对已结束的进程会话**生效（pruneFinishedSessions清理过期记录），不杀死运行中进程。

**`DEFAULT_EXEC_APPROVAL_TIMEOUT_MS`** = 1800000ms = 30分钟（`exec-approvals-DWLAklWZ.js`），但这是**批准等待超时**（等待用户批准），不是进程执行超时。

**`runExec()` 函数**（`exec-_fLrb4o0.js`）默认超时10000ms = 10秒，但此函数不被exec工具使用。

---

## 3. 退出码137的精确来源

### 3.1 Unix/SIGKILL惯例

| 信号 | 信号值 | 退出码公式 | 结果 |
|:----|:------|:----------|:-----|
| SIGKILL | 9 | 128 + 9 | **137** |

Node.js 的 `child_process` 在捕获到进程因信号终止时，`child.on('exit', (code, signal) => ...)` 中 `code = null`、`signal = 'SIGKILL'`。然后 supervisor 和 `runExecProcess` 的 `buildExecExitOutcome()` 会处理此状态。

### 3.2 supervisor的kill路径

当超时触发：
```
setTimeout → requestCancel("overall-timeout") → cancelAdapter → child.kill("SIGKILL")
```

- 在**Windows**：`child.kill("SIGKILL")` 调用 `TerminateProcess()`，子进程退出码通常为 1，**非137**
- 在**WSL2**：WSL2 Linux 进程收到真实 SIGKILL，退出码 = 137
- 在**Linux**：退出码 = 137

### 3.3 Windows退出码shim

```
exec-_fLrb4o0.js → resolveProcessExitCode()
```

当 `usesWindowsExitCodeShim = true` 且未超时/未收到信号时，shim将退出码回退为0（视为正常退出）。

**但在超时场景中，shim的修正逻辑被覆盖**：
```
resolveProcessExitCode 中的 timedOut/noOutputTimedOut/killIssuedByTimeout 标志
→ 使 shim 的 "return 0" 路径被旁路
→ 返回实际的子进程退出码
```

---

## 4. T21管线被杀的两种可能场景分析

### 场景A：前台运行（低可能性）

若管线命令**没有**使用 `background` 或 `yieldMs`：

| 计算 | 值 |
|:----|:---|
| 默认超时 | 30分钟 |
| marine-s 启动 | 15:24 |
| 预期超时点 | ~15:54 |
| 实际死亡 | ~16:43（79分钟后） |

**矛盾**：79分钟 >> 30分钟默认超时。如果前台运行，应该在~15:54被杀死，而非~16:43。

### 场景B：后台/延迟运行（高可能性）

若管线命令使用了 `background=true` 或 `yieldMs`：

- **无超时**设置
- 进程可无限运行
- 被杀原因**不是**OpenClaw exec超时机制

### 场景B1：OpenClaw内部的定时器冲突（需进一步验证）

存在一个反常现象：如果命令使用 `yieldMs` 运行了 79 分钟后被杀，而没有任何 OpenClaw exec 超时机制被触发，说明 kill 源来自更上层。

检查发现以下组件可能在不经意间中止进程：
- **abortSignal** 传播（agent-runner）：当 agent 会话超时或重启时，abort signal 会试图中止所有挂起的工具调用，但**对已backgrounded的exec会话不生效**
- **会话生命周期管理**：不适用

### 场景B2：外部因素（最可能）

- Windows 系统级进程终止
- WSL2 OOM killer
- Docker 容器重启
- 强制重启 OpenClaw 网关

---

## 5. 配置可设置性

### 5.1 openclaw.json 配置

代码中存在 `tools.exec.timeoutSec` 的配置通道，但**当前未设置**：

```typescript
// pi-tools-BF_cJdvo.js
timeoutSec: agentExec?.timeoutSec ?? globalExec?.timeoutSec,
// 对应 openclaw.json:
// tools.exec.timeoutSec (全局)
// agents.list[].tools.exec.timeoutSec (per-agent)
```

### 5.2 当前配置

用户当前 `openclaw.json` 的 `tools` 节：
```json
"tools": {
    "profile": "full",
    "sessions": { "visibility": "all" },
    "agentToAgent": { "enabled": true }
}
```

**未设置任何 exec 超时相关字段**。因此：
- `globalExec.timeoutSec` = undefined
- `agentExec.timeoutSec` = undefined
- 回退到硬编码默认值 1800秒（30分钟）

### 5.3 推荐修改

如需防止管线被超时中断，可在 `openclaw.json` 中添加：

```json
"tools": {
    "exec": {
        "timeoutSec": 14400
    }
}
```

（14400秒 = 4小时，覆盖一次全量运行）

或仅对特定agent设置：
```json
"agents": {
    "list": [{
        "id": "mochen",
        "tools": {
            "exec": {
                "timeoutSec": 14400
            }
        }
    }]
}
```

---

## 6. 风险等级与建议

| 项 | 评级 |
|:--|:----|
| OpenClaw exec超时机制 | ⚠️ 中等风险 |
| 默认值覆盖 | ✅ 可配置 |
| 与T21管线被杀的直接关联 | ❌ 低相关性 |

### 建议

1. **确认T21管线exec调用方式**：检查具体调用是前台还是带 `background=true`/`yieldMs`。如果是后台模式，exec超时非根因。

2. **增加exec超时配置**：无论根因是否来自exec超时，配置一个足够覆盖全量运行的 `timeoutSec` 是合理的防御性措施。

3. **监控补充**：由于Windows/WSL2无法获取dmesg，建议补充WSL2内存使用监控，以排查OOM killer可能性。

4. **代码审查点**：建议检查 `runExecProcess` 中的 `onAbortSignal` 处理路径，确认 `abortSignal` 是否会在特定条件下传播到已backgrounded的进程。

---

## 附录：关键代码位置

| 组件 | 文件 | 关键行 |
|:----|:----|:------|
| exec tool schema | `bash-tools.schemas-C65lnA79.js` | `timeout` 为可选Number |
| exec tool创建 | `bash-tools-BBNmvkSq.js` | 行1855: `defaultTimeoutSec = 1800` |
| 超时计算 | `bash-tools-BBNmvkSq.js` | 行2054-2055: `effectiveTimeout` |
| 传递给 supervisor | `bash-tools-BBNmvkSq.js` | 行2082: `timeoutSec: effectiveTimeout` |
| supervisor 超时 | `supervisor-j6j2aKmo.js` | `clampTimeout()` + `setTimeout → requestCancel` |
| approval 超时 | `exec-approvals-DWLAklWZ.js` | 行76: `DEFAULT_EXEC_APPROVAL_TIMEOUT_MS = 18e5` |
| 配置读取 | `pi-tools-BF_cJdvo.js` | 行750: `timeoutSec: agentExec?.timeoutSec ?? globalExec?.timeoutSec` |
