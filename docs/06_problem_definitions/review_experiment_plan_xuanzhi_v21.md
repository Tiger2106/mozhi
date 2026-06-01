---
author: 玄知 (xuanzhi)
created_time: 2026-05-31T10:43:00+08:00
type: architecture_review_v21
review_for: experiment_plan_U2_repro_v2.1.md
version: v2.1
status: PASS_WITH_CONDITIONS
based_on_v2_review: review_experiment_plan_xuanzhi_v2.md
---

# 试验方案架构审查报告 v2.1（Windows修正版）

**审查对象**：`experiment_plan_U2_repro_v2.1.md`
**审查者**：玄知（架构+数据一致性）
**审查时间**：2026-05-31T10:43+08:00
**审查维度**：环境迁移彻底性、代码改动平台相关性、附录C完整性、taskkill方案、OOM防护、Windows新增风险

---

## 总体结论：✅ PASS WITH CONDITIONS

v2.1已**全线完成**WSL2→原生Windows 11的环境假设修正，包含：
- 全文术语替换（SIGKILL/exit 137 → Windows退出码 / MemoryError）
- 附录C全量重写（6项WSL2删除 + 8项Windows原生项）
- §六终止方案恢复为taskkill主方案
- U1结论双场景修正（MemoryError可捕获 + TerminateProcess边界）

**架构和数据一致性层面：无结构缺陷，V2评审批准的验收项（A2/A4/A7）不受环境迁移影响。**

> ⚠️ 条件性通过的3项条件见§六"条件性通过条款"。

---

## 一、环境迁移影响：C1~C7是否受影响？

逐一检查C1~C7代码改动在Windows下的兼容性：

| 改动 | 内容 | 平台相关性 | 结论 |
|:----:|:-----|:----------:|:----:|
| **C1** | 管线新增run_id参数/写入 | 纯Python逻辑，无sys调用 | ✅ 零影响 |
| **C1a** | _build_null_record→实例方法 | 纯Python OOP改动 | ✅ 零影响 |
| **C2** | psutil逐截面内存保护 | psutil在Windows上使用GlobalMemoryStatusEx API，行为与Linux一致 | ✅ 临界值定义不变，可靠性≥Linux |
| **C3** | 文件日志 | logging.RotatingFileHandler跨平台 | ✅ 零影响 |
| **C4** | Scheduler透传run_id | 纯Python逻辑 | ✅ 零影响 |
| **C5** | DB Schema变更 | SQLite跨平台，SQL语法无平台差异 | ✅ 零影响 |
| **C6** | 配置/环境变量 | 字符串赋值 | ✅ 零影响 |
| **C7** | 入口脚本参数 | argparse跨平台 | ✅ 零影响 |

**结论**：C1~C7全部为纯Python逻辑改动，**零平台依赖**。环境迁移对其无影响。✅

**穿透验证**：v2评审中确认的A2（最小侵入）✅ / A4（数据隔离完整）✅ 两项验收在Windows下同样成立。

---

## 二、附录C完整性审查

### 2.1 WSL2检查项删除确认

v2.0附录C含以下WSL2特有项，v2.1已**全部删除**：

| v2.0 WSL2项 | v2.1状态 | 判断 |
|:------------|:--------:|:----:|
| `/var/log/dmesg`（内核环形缓冲区） | ❌ 已删除 | ✅ 正确 |
| `ulimit -v`（进程虚拟内存限制） | ❌ 已删除 | ✅ 正确 |
| `cgroup memory limit`（容器内存限制） | ❌ 已删除 | ✅ 正确 |
| 跨文件系统IO性能（WSL2 /mnt/ → ext4） | ❌ 已删除 | ✅ 正确 |
| `.wslconfig`（WSL2全局配置） | ❌ 已删除 | ✅ 正确 |
| SIGKILL行为（信号不可捕获） | ❌ 已删除 | ✅ 正确，替换为MemoryError可捕获 |

### 2.2 Windows原生新增项覆盖确认

v2.1附录C新增8项Windows检查：

| # | Windows检查项 | 新增状态 | 完整性判断 |
|:-:|:--------------|:--------:|:-----------|
| 1 | 页面文件(pagefile.sys) | ✅ 新增 | `wmic pagefile list /format:list` — ❗`wmic` 在Windows 11 24H2+中已弃用（需管理员权限），建议补充PowerShell替代：`Get-CimInstance Win32_PageFileSetting` |
| 2 | Windows Event Log | ✅ 新增 | 进程被终止时，eventvwr → System log中可能有Resource-Exhaustion事件。⏳ 需确认该行为的实际触发条件（并非所有OOM都记录） |
| 3 | perfmon可用性 | ✅ 新增 | `perfmon /sys` 可附加python.exe。**注意**：perfmon需要operator手动附加，非自动化。建议补充：若Phase 2执行时间较长，可提前配置Data Collector Set自动记录 |
| 4 | Python x64寻址 | ✅ 新增 | `python -c "import sys; print(sys.maxsize)"` 验证（>2^31为64位）✅ |
| 5 | 进程终止行为（MemoryError vs SIGKILL） | ✅ 新增 | Windows下OOM→MemoryError可捕获 ✅ |
| 6 | 父进程退出码捕获 | ✅ 新增 | Node.js `child.on('exit', code => ...)` ✅ |
| 7 | 进程层次（OpenClaw→Python） | ✅ 新增 | 任务管理器可见python.exe为node.exe子进程 ✅ |
| 8 | 文件路径类型（Windows路径） | ✅ 新增 | 全部使用 `C:\Users\...`，无交叉IO ✅ |

### 2.3 补充建议（不阻塞，可附录记录）

1. **`wmic` → PowerShell替代**：`wmic pagefile list /format:list` 在Windows 11 24H2+中已弃用。建议补充：
   ```powershell
   Get-CimInstance Win32_PageFileSetting | Select-Object Name, InitialSize, MaximumSize
   Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
   # 页面文件总大小 = MaximumSize × 系统页面文件数量
   ```

2. **Event Log验证**：建议在附录C备注"进程终止后优先查看System Log中`Resource-Exhaustion`或`Application Popup`事件（Event ID 26/1014/2004），但**并非所有OOM场景都产生日志**——如果OOM表现为Python MemoryError而非系统级TerminateProcess，Event Log可能无记录。"

3. **perfmon自动化**：如果Phase 2执行时间较长（>30min），建议预配置Data Collector Set以自动记录Memory\Available MBytes + Process(python)\Working Set。

**结论**：✅ **附录C重写完整。** WSL2项全部删除，Windows原生项覆盖全面。上述3项补充建议均为友好优化，不阻塞评审通过。

---

## 三、Phase 1手动kill方案审查

### 3.1 主方案：taskkill /F /PID

**方案评估**：
- ✅ 在原生Windows上直接可用，无需WSL桥接或其他间接方案
- ✅ taskkill使用TerminateProcess API（NTAPI），相当于Linux的SIGKILL——进程无通知机会
- ✅ 退出码语义已修正（§6.3），不再引用Linux 137码

**未验证的问题**：
- ⚠️ **文档未提及taskkill前预验证步骤**。建议在Phase 1步骤-1中增加：
  
  ```powershell
  # 预验证：确认taskkill行为符合预期
  # (1) 启动一个测试Python进程（模拟pipeline运行）
  python -c "import time; time.sleep(60)" &
  # (2) 获取PID
  tasklist /FI "IMAGENAME eq python*"
  # (3) 强制终止
  taskkill /F /PID <实际PID>
  # (4) 确认进程消失
  # (5) 在真正pipeline上执行相同操作
  ```

- ⚠️ **若同时运行多个python.exe（如IDE或其他工具）**，operator需精确识别目标PID。建议在C7入口脚本启动时打印其PID到终端

### 3.2 备用方案：KILL_NOW.signal文件信号

**代码可用性问题**（重要）：

§6.2中描述的KILL_NOW.signal检测代码引用 `self._checkpoint_dir`：

```python
KILL_FILE = os.path.join(self._checkpoint_dir, "KILL_NOW.signal")
```

但**C1~C7代码改动清单中未包含该检测逻辑**（检查C2代码，只有`_memguard_check`，没有KILL_NOW.signal检测循环）。这是一个**实现缺口**：

- 若Phase 1使用taskkill主方案 → 无需此代码，无影响 ✅
- 若operator想使用备用方案 → ❌ **KILL_NOW.signal检测尚未实现**，需要额外改动（在`run_batch_streaming`的`for dt_str in dates_iter`循环内添加检测代码）

**建议**：
1. 在§6.2中明确标注：KILL_NOW.signal检测逻辑**尚未纳入C1~C7改动清单**，如最终决定使用备用方案，需在Phase 0补充该代码
2. 或者，在C7入口脚本中加入该检测（更合理，startup时检查不阻塞）

### 3.3 总体kill方案判断

| 评估维度 | 判断 |
|:---------|:-----|
| taskkill主方案可行性 | ✅ 原生Windows可信赖方案 |
| 退出码验证覆盖 | ✅ §6.3已全面修正 |
| KILL_NOW.signal备用方案可执行性 | ⚠️ 需额外代码改动（§6.2已描述，但非C1~C7一部分） |
| 预验证步骤 | ❌ 缺失，建议补充 |

---

## 四、OOM防护可靠性审查（Windows vs Linux）

### 4.1 psutil跨平台可靠性

| 场景 | Windows行为 | Linux行为 | 一致性 |
|:-----|:------------|:----------|:-------|
| `psutil.virtual_memory().available` | 调用`GlobalMemoryStatusEx` → Available Pages + 缓存 | `MemAvailable`（内核估算） | ✅ 数据含义一致，Windows读数可能更保守 |
| `psutil.Process().memory_info().rss` | 调用`GetProcessMemoryInfo` → WorkingSetSize | `/proc/self/status VmRSS` | ✅ 语义一致，Windows称为Working Set |
| memguard阈值2GB/3GB/4GB | 与Linux无差异 | 同左 | ✅ 阈值定义跨平台一致 |

**结论**：✅ **psutil内存监控在Windows上的可靠性 ≥ Linux**。Windows API的"可用内存"指标更直接（不涉及内核估算逻辑），阈值设计保持有效。

### 4.2 Windows特有优势

| 优势 | 说明 |
|:-----|:------|
| **MemoryError可捕获** | 原生Windows上Python OOM通常引发`MemoryError`（try/except可捕获），精度可提升至**截面内** ✅ |
| **§7.2页面文件检查** | 替代Linux `ulimit -v`，在实践中更有意义 ✅ |
| **§7.2 Python x64寻址** | 确认64位Python无2GB单进程限制 ✅ |

### 4.3 特别注意点

| 问题 | 说明 | 建议 |
|:-----|:------|:-----|
| **信号处理**（L4层） | §7.1 L4提到`signal.SIGTERM handler`。Windows上`signal`模块支持SIGTERM，但行为与Linux不同——SIGTERM在Windows上由Ctrl+C模拟，**不是真正的信号** | ✅ 对L4影响不大（极低概率触发该层级），但建议备注此差异 |
| **VirtualAlloc vs malloc碎片** | Windows堆管理器和Linux glibc不同，极端场景下内存碎片模式不同 → OOM触发位置可能不同 | ⏳ 属于认知边界，试验不涉及此深度分析，但可备注在结论文档中 |
| **Private Bytes vs Working Set** | psutil.rss = Working Set（物理驻留页），Windows上Process Private Bytes（VirtualAlloc总量）可能远大于Working Set。**潜在危险**：avail_gb看似充足，但大量Committed Bytes导致页面文件爆满 | ⚠️ 建议在`_memguard_check`中补充`psutil.Process().memory_full_info().uss`或`private`监控，或至少备注此差异 |
| **磁盘占用（巨页/页面文件膨胀）** | 如果pipeline频繁alloc+free大对象，页面文件可能随之膨胀（可回收空间被占用），ssd剩余空间减少 | ✅ 现有C3 RotatingFileHandler + 备份空间≥1GB已考虑，一般场景无问题 |

### 4.4 综合判断

✅ **OOM防护在Windows上同样可靠**，且因MemoryError可捕获而具有轻微优势。§7.2中`ulimit -v`→页面文件检查的替换正确。L1~L4四层防线均对Windows生效。

⚠️ 建议补充：`_memguard_check`中增加`psutil.Process().memory_full_info().uss`（或Windows上等价指标）的采样，用于更精确诊断内存压力源头。

---

## 五、Windows原生环境新增风险分析

### 5.1 风险矩阵补充（v2.1未覆盖项）

| # | 新增风险 | 概率 | 影响 | 说明 | 缓解建议 |
|:-:|:---------|:----:|:----:|:-----|:---------|
| **R7** | **Windows Defender实时扫描** | 🟡中 | 🟡中 | Defender扫描python.exe的pagefile/临时文件/DB文件，CPU/IO突发导致pipeline执行时间延长，极端情况下引发内存压力 | Phase 2执行时暂时排除 `a50_ic.db` 和 `pipeline_logs/` 目录的Defender扫描：`Add-MpPreference -ExclusionPath "C:\path\to\mozhi_platform\data","C:\path\to\pipeline_logs"` |
| **R8** | **Windows Update自动重启** | 🟢低 | 🔴高 | 夜间执行时（建议的01:00~05:00）恰好是自动更新维护窗口。若Phase 2过程中重启，run_id传递链无影响（因为重启后是操作系统级别，Python进程不会得resume的信号） | 执行前检查 `Get-WUInstall -list`；或临时暂停更新 `Stop-Service wuauserv`（执行后恢复） |
| **R9** | **OpenClaw网关崩溃** | 🟢低 | 🟡中 | OpenClaw Node.js作为父进程，若自身崩溃或重启，子Python进程在Windows上**不会自动退出**（孤儿进程被system接管）。但operator可能不知道Python仍在跑，导致Phase 2失控 | 在C7入口脚本中添加 `try: sys.stdin.read()` 阻塞（检测父进程存活），或定期检查父进程PID的存活：`parent_pid = os.getppid()`，Windows上getppid()返回父进程PID |
| **R10** | **多实例python.exe混淆** | 🟡中 | 🟡中 | 若同时有IDE/其他Python进程在运行，`tasklist /FI "IMAGENAME eq python*"` 返回多个结果，operator可能kill错进程 | C7入口脚本启动时打印PID到终端+日志：`logger.info("PIPELINE_STARTED pid=%d run_id=%s", os.getpid(), run_id)` |
| **R11** | **路径分隔符不一致** | 🟢低 | 🟢低 | 代码中若混合使用 `os.path.join` 和字符串拼接 `"/"`，在Windows下可能产生混合分隔符路径 | 确认代码全部使用 `os.path.join` 或 `pathlib.Path`。检查C7入口脚本中的路径构造方式 |
| **R12** | **系统资源争抢（cron/research GUI）** | 🟡中 | 🟡中 | Phase 2近5年重跑期间（~60min），若当前用户也在使用同一台机器进行开发/研究，资源竞争可能导致运行时间延长或触发不必要的OOM防护 | 建议Phase 2在无人值守时段执行（原计划01:00~05:00合理），执行前通知相关用户 |

**风险等级定义**：概率(高>50% / 中5-50% / 低<5%)，影响(高阻塞 / 中可恢复 / 低可忽略)

### 5.2 v2.1已有风险的重审

| # | 已有风险 | v2.1修正 | 加重/减轻 |
|:-:|:---------|:---------|:---------:|
| **R3** | 重跑触发OOM | ✅ 未变化 | 在Windows上因MemoryError可捕获，实际监控效果**更佳**，风险减轻 🟢减轻 |
| **R5** | Windows vs Linux结论可推广性 | ✅ 新增附录C + §10.1双场景结论 | 明确标注后，风险在可接受范围 🟢减轻 |
| **R4** | 数据污染生产查询 | ✅ 未变 | 不受平台影响 🟢不变 |
| **R1** | Phase 1发现run_id传递链断裂 | ✅ 未变 | 不受平台影响 🟢不变 |

### 5.3 新增风险总体判断

🟡 **中等关注度**。R7（Defender扫描）和R10（多实例混淆）是实际执行中可能遇到的问题，建议在Phase 1开始前完成缓解措施。R8（Windows Update）需要确认执行时间窗口。

**不阻塞通过**，但建议在Phase 1启动前：
1. 添加pipeline日志打印PID
2. 检查Defender排除路径
3. 确认Windows Update未处于等待重启状态

---

## 六、条件性通过条款

v2.1通过需满足以下3项条件（执行前完成即可，不修改方案）：

### C1：taskkill预验证

**在执行Phase 1之前**，先用独立短进程验证taskkill行为：

```powershell
# (1) 启动测试进程
Start-Process python -ArgumentList "-c", "import time; time.sleep(120)" -NoNewWindow
# (2) 获取PID
Get-Process python* | Select-Object Id, ProcessName
# (3) 强制终止
taskkill /F /PID <实际PID>
# (4) 确认进程消失
$LASTEXITCODE  # 应返回0表示成功
taskkill /F /PID <实际PID>  # 应返回"INFO: No tasks running..."
```

确认 `$LASTEXITCODE` 行为后，记录到Phase 1日志中。

### C2：Defender排除 + Windows Update检查

Phase 1前执行：

```powershell
# Defender排除（以实际路径为准）
Add-MpPreference -ExclusionPath "C:\Users\17699\mozhi_platform"
# 检查Windows Update状态
Get-WUInstall -ListOnly
(Get-Service wuauserv).Status
# 若需暂停更新
# Stop-Service wuauserv -Force
```

### C3：pipeline启动打印PID

确认C7入口脚本在启动时打印PID到终端+日志：

```python
import os, sys, logging
logger = logging.getLogger("pipeline")
pid = os.getpid()
logger.info("PIPELINE_STARTED pid=%d run_id=%s", pid, args.run_id)
print(f"PIPELINE_STARTED pid={pid} run_id={args.run_id}", flush=True)
```

三条条件全部满足后，Phase 0/Phase 1可在Windows环境下按v2.1方案执行。

---

## 七、补充技术备注（不阻塞，仅归档）

### 7.1 KILL_NOW.signal后备方案缺口

§6.2描述的KILL_NOW.signal检测代码依赖 `self._checkpoint_dir` 属性，但：
- C1~C7中未包含该检测逻辑
- pipeline类中当前无 `_checkpoint_dir` 属性
- 如需使用后备方案，需：
  1. 在pipeline `__init__` 中添加 `self._checkpoint_dir = checkpoint_dir`
  2. 在 `run_batch_streaming` 的 `for` 循环开头添加KILL_NOW检测

**注意**：主方案taskkill已足够可靠，此缺口**不影响Phase 1的默认执行路径**。仅当operator明确选择使用文件信号方案时才需补全。

### 7.2 psutil监控补充建议

如在诊断时遇到"内存充足却触发OOM"的场景，建议在 `_memguard_check` 中补充：

```python
# 补充指标采样
try:
    pinfo = psutil.Process().memory_full_info()
    result["uss_gb"] = pinfo.uss / (1024 ** 3)  # Unique Set Size
    result["private_gb"] = pinfo.private / (1024 ** 3) if hasattr(pinfo, 'private') else None
except Exception:
    pass  # uss在某些平台上不可用，非阻塞
```

Windows上`memory_full_info()`会调用`GetProcessMemoryInfo`获取PagefileUsage等额外指标。

### 7.3 页面文件大小检查的精确命令

附录C中 `wmic pagefile list /format:list` 建议补充PowerShell版：

```powershell
# PowerShell v5+ 推荐
$pf = Get-CimInstance Win32_PageFileSetting
$cs = Get-CimInstance Win32_ComputerSystem
Write-Host "PageFile(s):"
$pf | Format-Table Name, InitialSize, MaximumSize
Write-Host "Total Physical Memory: $([math]::Round($cs.TotalPhysicalMemory/1GB, 1)) GB"
Write-Host "PageFile Size Recommendation: ~$([math]::Round($cs.TotalPhysicalMemory*1.5/1GB, 1)) GB total"
```

---

## 八、整体验收清单

| 维度 | 审查项 | 结论 |
|:-----|:-------|:----:|
| 环境迁移彻底性 | C1~C7在Windows下零影响 | ✅ PASS |
| 附录C完整性 | WSL2项全删，Windows项全覆；3项友好建议已备注 | ✅ PASS |
| §六kill方案 | taskkill主方案正确；退出码语义修正；KILL_NOW.signal存在代码缺口（已备注） | ✅ PASS with note |
| psutil/OOM防护 | Windows可靠性≥Linux；MemoryError可捕获为优势；建议补充uss/private采样 | ✅ PASS with suggestion |
| 新增风险 | R7(Defender) / R8(Update) / R9(网关崩溃) / R10(多实例) 已识别并附缓解 | ✅ 已覆盖 |
| v2验收继承 | A2(代码最小侵入) / A4(三重隔离) / A7(环境差异) — 不受平台迁移影响 | ✅ 继承通过 |
| **条件性条款** | **C1(taskkill预验证) / C2(Defender+Update) / C3(PID打印)** | ⏳ 执行前完成 |

---

## 九、最终判决

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│    ✅ PASS WITH CONDITIONS                                  │
│                                                             │
│    v2.1已全线完成WSL2→原生Windows 11的环境修正，            │
│    架构合理、数据隔离方案完整、C1~C7零平台依赖。            │
│                                                             │
│    条件（Phase 1前完成，无需修改方案文档）：                 │
│    C1 ✅ taskkill预验证（独立短进程）                       │
│    C2 ✅ Defender排除 + Windows Update检查                  │
│    C3 ✅ pipeline启动时打印PID                              │
│                                                             │
│    技术备注（不阻塞，归档供参考）：                          │
│    - KILL_NOW.signal备用方案需额外代码（当前无此改动）      │
│    - 建议_ memguard_check补充uss/private采样                │
│    - 附录C中wmic建议补充PowerShell替代命令                  │
│                                                             │
│    验收声明：                                               │
│    - 架构合理性  ✅ PASS                                    │
│    - 数据一致性  ✅ PASS                                    │
│    - 复现性验证  ✅ PASS（墨萱确认偏差0.00%后直接通过）     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

*EOF — 玄知架构审查报告 v2.1 | status=PASS_WITH_CONDITIONS | 填写时间：2026-05-31T10:43+08:00*
