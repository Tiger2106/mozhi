# U1 技术讨论背景 — T+21全量运行OOM/进程终止 内存问题

**问题ID**：T21_FULLRUN_20260530 / U1
**作者**：墨涵（墨枢产品负责人）
**日期**：2026-05-31（v2 修正运行环境）
**用途**：与系统专家讨论的材料

---

## 一句话摘要

原生Windows 11环境下管线两次因OOM被终止（退出码？），被杀时刻无内存快照。想知道Windows上进程被OOM终止时如何捕获事件，以及16GB机器为什么单线程管线能耗尽内存。

---

## 问题场景

A50截面IC管线（Python 3.14+, SQLite）在Windows 11 x64上全量运行（约20年/4710交易日数据），两次被系统终止：

| 运行 | 启动 | 被杀 | 产出截面 | 行数 |
|:----|:----:|:----:|:-------:|:----:|
| marine-s | ~16:37 | ~16:43（约6min） | 222 | 4,293 |
| mellow-o | ~17:27 | ~17:42（约15min） | 428 | 7,731 |

**事后快照**（~18:59，距首次被杀已>2h）：可用内存1.76GB / 总量15.6GB。

**被杀时刻的内存快照不可获取** — 这就是U1待解决的问题。

---

## 环境信息

| 项目 | 值 |
|:-----|:---|
| 操作系统 | Windows 11 x64（build 26200） |
| 运行时 | Python 3.14+（原生Windows，非WSL2） |
| 数据库 | SQLite（a50_ic.db, ~38.5 MB） |
| 管线模式 | 单线程流式（streaming mode），逐截面gc.collect() |
| 物理内存 | 15.6 GB（启动前检查需可用≥4GB） |
| 过程管理 | OpenClaw Node.js进程管理器（subprocess启动Python） |

**关键澄清**：所有进程均运行在原生Windows上，非WSL2/Linux环境。之前的WSL2假设是错误的。

---

## Windows vs Linux OOM行为差异

| 维度 | Linux（原假设WSL2） | Windows（实际环境） |
|:-----|:-------------------|:-------------------|
| OOM时 | OOM killer选进程SIGKILL | Windows不主动杀进程，进程自身分配失败抛出MemoryError，或页面文件耗尽时系统稳定下降 |
| 进程终止 | exit code 137 (128+9) | MemoryError或TerminateProcess退出码（NTSTATUS） |
| 内核日志 | dmesg可看到OOM killer记录 | Windows Event Viewer → Windows Logs → System，记录内存事件 |
| 监控工具 | /proc/meminfo, sar, atop | 任务管理器/资源监视器/性能监视器(perfmon)/ETW |
| 虚拟内存 | SWAP分区 | 页面文件(pagefile.sys) |

**注**：之前文档中记录的"SIGKILL"和"退出码137"来自OpenClaw进程管理器的统一标准输出，可能已标准化为类Unix格式。

---

## 管线内存特征

管线逐截面计算（约20年/4710交易日，实际处理798个有效截面），每截面执行：

```
Step 1: 因子计算（20个因子 × 50成分股 → DataFrame）
Step 2: 前向收益计算（4个窗口：1D/5D/10D/20D）
Step 3: IC计算（RankIC/Pearson + 分组IC）
Step 4: IC结果写入SQLite（INSERT OR IGNORE）
Step 5: checkpoint写文件
```

**已有防护**：
- 启动时一次性内存检查（psutil，可用内存需≥4GB，否则拒绝启动）
- 流式模式（`run_batch_streaming`），每截面 `gc.collect()`
- 每10截面记录内存快照（仅记录，无保护动作）

**防护缺口**（所有缺口在原生Windows环境下均可通过psutil或系统API解决）：
- 无运行时内存保护
- 无自动减速/放弃机制
- 因子batch_compute不可控

---

## 需要讨论的问题

### 1. 进程终止的可观测性

- 管线两度被终止，退出码是多少？
- Windows Event Viewer 中是否有相关记录（Application/System日志）？
- 是否可以配置Windows Error Reporting(WER)或AppCrash来捕获进程终止时的内存转储？
- 可以在OpenClaw侧（Node.js父进程）捕获子进程的退出码和内存峰值吗？

### 2. 内存监控的最佳实践

- 原生Windows下，最佳的内存峰值监控方案是什么？
  - Python侧psutil（每截面采样）
  - Windows Performance Monitor (perfmon) 实时计数器
  - Windows Resource Monitor（可看进程历史内存）
  - ETW (Event Tracing for Windows) 详细轨迹
- psutil在Windows下的内存指标是否准确（working set vs private bytes vs virtual size）？
- 是否有"杀前最后一刻"的内存捕获手段——如Windows的Task Manager自动生成dump？

### 3. 根因：为什么16GB机器跑的管线会OOM？

| 截面数 | 798 |
|:------|:---|
| 每截面因子计算 | 20因子 × 50股票 |
| 每截面输出 | 约18行数据（18因子 × 1行IC结果） |
| 总输出 | ~14,364行（SQLite, ~38MB） |

管线使用单线程流式模式 + 逐截面GC，理论上不应该累积持续增长的内存。

- 是什么导致了渐进式内存增长，在约6分钟（~222截面）后耗尽可用内存？
- Python的GC回收不及时还是存在循环引用？
- pandas/NumPy的中间对象是否被正确释放？
- SQLite的INSERT OR IGNORE + checkpoint写文件是否有内存泄漏？
- Windows下Python单进程的虚拟地址空间限制（64位应该不受限，但需确认）

### 4. 后续优化建议

- Python侧：检查是否有未释放的对象引用（weakref / __del__ / 循环引用）
- Windows侧：考虑增加页面文件(pagefile.sys)大小，或使用`psutil`设置每截面内存上限
- 进程管理侧：OpenClaw作为父进程，是否可以提前检测内存异常并主动告警/降级

---

## 已完成的排查工作

1. **问题定义流水线** — 已完成Incident模式5阶段，31条现象完整记录
2. **双人查证** — 10项查证，8/10已确认，U1待查
3. **计划** — 管线增加psutil运行时内存监控 + 自动减速机制

---

*本文件仅供内部分析，不包含敏感数据。v2 修正：运行环境为原生Windows 11，非WSL2。*
