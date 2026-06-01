---
author: 墨萱 (moxuan)
reviewed: experiment_plan_U2_repro_v2.1.md
date: 2026-05-31T10:43:00+08:00
type: qa_review_v21
status: PASS
overall: PASS
---

# 墨萱 QA 审查报告 — 故障复现试验方案 v2.1（Windows 修正版）

## 总体结论：PASS ✅

v2.1 全线修正了 v2 基于错误 WSL2 假设编写的运行环境描述。所有环境相关的术语、工具、退出码语义、附录 C 均已正确替换为原生 Windows 11 对应项。

**结论**：v2.1 可完全取代 v2 成为最终方案。无需条件。

---

## 一、SIGKILL-1 修复评估：taskkill 主方案恢复 ✅

### 变更内容

| 维度 | v2（WSL2 假设） | v2.1（原生 Windows） |
|:-----|:----------------|:---------------------|
| 主方案 | 文件信号自杀法（方案B） | **taskkill /F /PID（方案A）** |
| 备用方案 | WSL 内部 kill -9 | 文件信号优雅退出（raise SystemExit） |
| 退出码语义 | 137 (128+9 SIGKILL) | Windows NTSTATUS / Python 异常码 |
| 文件信号代码 | `os.kill(os.getpid(), signal.SIGKILL)` | `raise SystemExit("模拟进程终止")` |

### 评估结论

**✅ 正确修复。** 要点如下：

1. **主方案对换正确**：原生 Windows 上 `taskkill /F /PID` 直接可用，切为主方案合理
2. **备用方案保留合理**：文件信号法改为 `SystemExit` 优雅退出，作为"温和终止"替代方案
3. **退出码彻底剥离 Linux 语义**：§6.3 从 "137=128+9" 重写为 Windows/Python 语义表

---

## 二、术语修正评估：Linux→Windows 替换 ✅

### 逐项核查

| Linux 术语（v2） | 替换为（v2.1） | 状态 |
|:----------------|:--------------|:----:|
| SIGKILL | taskkill / TerminateProcess | ✅ |
| exit 137 / 128+9 | Windows NTSTATUS / 异常退出码 | ✅ |
| OOM killer（内核机制） | Python MemoryError（可捕获异常） | ✅ |
| ulimit -v / ulimit 降级 | 页面文件检查 / Windows Memory Diagnostic | ✅ |
| dmesg（内核日志） | Windows Event Log / eventvwr.msc | ✅ |
| cgroup 内存限制 | 无对应概念，已删除 | ✅ |
| .wslconfig | 无对应概念，已删除 | ✅ |
| WSL 内部 `kill -9` | 备用方案：文件信号 `raise SystemExit` | ✅ |
| 跨文件系统 IO 性能损失 | Windows 原生文件路径，无交叉文件系统 | ✅ |
| `wsl ps aux` 查看进程 | `tasklist /FI "IMAGENAME eq python.exe"` | ✅ |

### 残余检查

全文搜索 "SIGKILL"、"exit.*137"、"OOM killer"、"ulimit"、"dmesg"、"cgroup" — 只在附录 D 的**历史对照表**中以"已废弃/已替换"标注出现，无任何当前活跃引用。

**✅ 术语修正彻底。**

---

## 三、附录 C 评估：WSL2→Windows 重写 ✅

### v2 附录 C 遗留项（v2.1 已全部替换）

| 遗留项（v2，WSL2） | 替换项（v2.1，Windows） |
|:-------------------|:------------------------|
| dmesg 检查 | Windows Event Log |
| ulimit 支持 | 页面文件(pagefile.sys) |
| cgroup 内存限制 | ✅ 已删除（无对应概念） |
| 跨文件系统 IO 性能 | 文件路径类型检查 |
| .wslconfig | ✅ 已删除（无对应概念） |
| SIGKILL 行为 | Python MemoryError + TerminateProcess |
| WSL2 内存回收 | 无对应概念，已删除 |

### v2.1 新增 Windows 检查项

- ✅ 页面文件(pagefile.sys) 大小确认
- ✅ Windows Event Log 配置
- ✅ perfmon 可用性
- ✅ 进程终止行为（MemoryError vs TerminateProcess）
- ✅ 父进程退出码捕获（OpenClaw Node.js 子进程）
- ✅ 进程层次（node.exe→python.exe taskkill 可见）
- ✅ 文件路径类型（Windows 原生路径）

**✅ 附录 C 重写完整，无 WSL2 残余项。**

---

## 四、PASS 标准评估：环境修正后调整检查

### Phase 1 PASS 标准（P1.1 ~ P1.10）

| 标准 | 环境相关？ | v2 → v2.1 变化 | 状态 |
|:----:|:----------:|:---------------|:----:|
| P1.1 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P1.2 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P1.3 | **✅ 环境相关** | v2: `exit code = 137` → v2.1: `tasklist /FI "PID eq <pid>" + 日志检查` | **✅ 正确修正** |
| P1.4 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P1.5 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P1.6 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P1.7 | ❌ 中性 | `[MemGuard]` 日志，无变化 | ✅ |
| P1.8 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P1.9 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P1.10 | ❌ 中性 | SQL 查询，无变化 | ✅ |

### Phase 2 PASS 标准（P2.1 ~ P2.6）

| 标准 | 环境相关？ | v2 → v2.1 变化 | 状态 |
|:----:|:----------:|:---------------|:----:|
| P2.1 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P2.2 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P2.3 | ❌ 中性 | SQL 查询，无变化 | ✅ |
| P2.4 | ❌ 中性 | psutil 日志量化标准，环境无关 | ✅ |
| P2.5 | **✅ 环境相关** | v2: SIGKILL 场景 → v2.1: "MemoryError 可捕获 + TerminateProcess 边界" 双场景 | **✅ 正确修正** |
| P2.6 | ❌ 中性 | SQL 查询，无变化 | ✅ |

**✅ PASS 标准中仅 P1.3 和 P2.5 需要修正，均已正确调整。其余环境无关标准无需变动。**

---

## 五、v2 残余风险在 v2.1 中的状态

### R1：文件信号 race window（低风险）— 未修复，不触及

v2.1 将文件信号降为备用方案（主方案已恢复为 taskkill），race window 问题只在执行备用方案时才相关。不影响主执行路径。**建议接受。**

### R2：P2.4 日志解析脚本建议预写（低风险）— 未实现

v2.1 仍为人工验证描述。建议在 Phase 0 预写解析脚本，但非强制。

### R3：无 checkpoint 时的 --resume-from 行为（低风险）— 未修复，推荐补丁

入口脚本缺失 `if not resume_pipeline_id:` 的显式检查。v2.1 未纳入修复列表（属于保险性建议，非阻塞缺陷）。

---

## 六、关于 v2.1 版本定位

### 版本关系

```
v1 ──[缺陷排查]──→ v2 ──[运行环境误判修正]──→ v2.1
                      ↑                  ↑
                      含 D1-C2-1/D2/D3   SIGKILL-1.1回退
                      P1.9/P1.10/P2.4    术语全线修正
                                         附录C重写
```

### v2.1 内容分析

| 内容分类 | 来自 v2 | v2.1 新增/修改 | 状态 |
|:---------|:--------|:---------------|:----:|
| 核心设计（唯一索引含 run_id、方案A） | ✅ 保留 | — | ✅ |
| 代码改动（C1~C7） | ✅ 保留 | 入口脚本 v2.1 标注"无代码改动" | ✅ |
| Phase 1 PASS 标准 | ✅ 保留 | P1.3 修正 | ✅ |
| Phase 2 PASS 标准 | ✅ 保留 | P2.5 修正 | ✅ |
| §六 终止方法 | ⚠️ 覆盖（文件信号→taskkill） | 全文重写 | ✅ |
| §七 OOM 防护 | ⚠️ 覆盖（ulimit→页面文件） | §7.2 替换 + Windows 特有措施 | ✅ |
| §十 U1/U2 结论 | ⚠️ 覆盖（SIGKILL→MemoryError） | U1 结论重写 | ✅ |
| 附录 C | ❌ 替换 | 全文重写（Windows 原生） | ✅ |
| 附录 D | ✅ 保留 + 新增 D2 表 | 新增 v2→v2.1 变更对照 | ✅ |

---

## 七、发现的小问题（非阻塞）

| # | 位置 | 问题描述 | 严重程度 |
|:-:|:-----|:---------|:--------:|
| N1 | §6.2 触发方式 Step 1 | `tasklist /FI "IMAGENAME eq python*"` — 在 Windows tasklist 中 `eq` 过滤器需要精确匹配扩展名，应改为 `IMAGENAME eq python.exe` 或使用 `LIKE` 操作符 | **微小** — 操作人员会自行修正，不影响方案有效性 |
| N2 | §6.2 文件信号代码注释 | 仍使用"清理信号"等中文术语，虽可理解但"信号"一词在 Linux 语境有歧义 | **微小** — 可接受，代码中不涉及系统调用 |
| N3 | 附录 D D1 表 "SIGKILL-1" 条目 | 引用 v2 的"文件信号自杀法"，标注为"v2.1已废弃" ✓。但紧随其后的 D2 表用 "SIGKILL-1.1" 重新编号，可能造成编号混乱 | **微小** — 不影响理解 |

---

## 八、验收清单

| # | 验收项 | 状态 | 说明 |
|:-:|:-------|:----:|:-----|
| A1 | SIGKILL-1 修复：taskkill 已恢复为主方案 | ✅ | 文件信号降为备用，`os.kill`→`raise SystemExit` |
| A2 | 术语修正：Linux 术语已全线替换 | ✅ | 仅附录 D 历史对照中以"废弃"标记残留 |
| A3 | 附录 C：WSL2 检查项已替换为 Windows 原生项 | ✅ | 新增 5 项 Windows 特有检查 |
| A4 | PASS 标准：环境修正后调整充分 | ✅ | P1.3/P2.5 已修正；其余环境无关 |
| A5 | 总体：v2.1 可取代 v2 为最终方案 | **✅ PASS** | 无条件，直接推进至玄知技术评审 |

---

## 结论

**PASS ✅ — v2.1 可取代 v2 成为最终方案。**

墨衡的 v2.1 修正工作彻底：SIGKILL-1.1（taskkill 方案恢复）、全线术语替换（Linux→Windows）、附录 C 重写（WSL2→Windows）三项核心修正全部到位。v2 的其他修复（D1/C1-1/C1-2/C2-1/D2/D3/P1.9/P1.10/P2.4）均完整保留。

建议进入下一环节：玄知技术评审 → 墨涵知识审查 → Owner 签署。

---

*EOF — 墨萱 QA 审查报告 v2.1*
