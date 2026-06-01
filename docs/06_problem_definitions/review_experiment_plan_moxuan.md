---
author: 墨萱 (moxuan)
reviewed: experiment_plan_U2_repro_v1.md
date: 2026-05-31T10:28:00+08:00
type: qa_review_v1
status: FAIL (with conditions for re-review)
overall: FAIL
---

# 墨萱 QA 审查报告 — 故障复现试验方案 v1

## 总体结论：FAIL

**方案结构和思路正确，但发现 4 处缺陷（2 处数据污染级 + 1 处流程级 + 1 处可观测性级），需修复后重新提交审查。**

---

## 一、代码改动审查（C1~C7）

### 🔴 DEFECT-C1-1（数据污染）：`_build_null_record` 静态方法硬编码 source_version

**严重性**：数据污染 — 高

**问题描述**：

`_build_null_record` 是 `@staticmethod`，其内部使用模块级常量 `SOURCE_VERSION = "v1"`：

```python
@staticmethod
def _build_null_record(date, factor_name, n_stocks, run_id=None):
    return {
        "source_version": SOURCE_VERSION,    # ← 永远＝'v1'
        # ...
    }
```

当管线以 `source_version='v1_repro'` 实例化运行时（C4/C6），所有正常写入的 `ic_record` 使用 `self.source_version='v1_repro'`，但所有 null record（样本不足/计算失败时写入）仍然使用 `'v1'`。

**后果**：
- Phase 1/2 运行期间，部分记录（null_record）的 `source_version='v1'` 混入生产数据
- 备份后校验 `P1.6` 的 `COUNT(*) WHERE run_id IS NULL` 将出现额外行
- `P2.3` 的旧数据隔离校验将失败（v1 总量增加）
- 下游查询 `WHERE source_version='v1'` 将混入实验期的 null 记录

**建议修复**：`_build_null_record` 需要接受 `source_version` 参数，或改为非静态方法使用 `self.source_version`。注意 `run_pipeline` 内对 `_build_null_record` 的调用也要一并传入 `source_version`。

**关联**：此缺陷与现有代码 `run_pipeline`（约第 510 行）中构造 `ic_record` 使用 `self.source_version` 的行为不一致。现有代码中 null_record 和 ic_record 就已经存在 source_version 差异。

---

### 🔴 DEFECT-SIGKILL-1（流程不可行）：WSL2 下 `taskkill /F /PID` 无法找到 Python 进程

**严重性**：流程阻塞 — 高

**问题描述**：

方案推荐方案 A：在 Windows PowerShell 中执行 `Get-Process python | Where-Object { $_.CommandLine -match "test_marine" }` 查找 PID，然后 `taskkill /F /PID $pid` 杀进程。

**根本原因**：WSL2 是轻量级虚拟机，Linux 进程运行在隔离的 VM 中，**从 Windows 侧看不到个体 Linux 进程**。Windows 的 `Get-Process python` 不会返回 WSL2 内部运行的 Python 进程。`taskkill` 无法定位。

**验证方法**：可以用以下 PowerShell 命令在当前 WSL2 环境测试：

```powershell
# 在 WSL2 内部启动 python
wsl python3 -c "import time; time.sleep(30)" &

# 从 Windows PowerShell 检查
Get-Process -Name python*   # 空的或只有 Windows 原生 python

# 正确做法
wsl ps aux | Select-String "python"
```

**建议修复**：在 WSL2 内部执行 SIGKILL。正确命令流程：

```bash
# 在 WSL2 bash 终端（或通过 wsl 命令）：
ps aux | grep test_marine
kill -9 <PID>
```

或一步到位：

```powershell
# 从 Windows PowerShell 执行 WSL 内部命令
$pid = wsl ps aux | Select-String "test_marine" | ForEach-Object { ($_ -split '\s+')[1] }
wsl kill -9 $pid
```

> 注意：方案 B（文件信号 + `os.kill(os.getpid(), signal.SIGKILL)`）不存在此问题，因为它在 WSL2 内部 self-kill。**推荐改选方案 B 或更改为 WSL 内部 kill。**

---

### 🟡 DEFECT-C2-1（可观测性）：C2 内存保护跳过截面时未 yield 结果

**严重性**：流程级 — 中

**问题描述**：

`run_batch_streaming` 是一个生成器（`yield` 方式输出结果）。C2 计划在 `for dt_str in dates_iter:` 循环开头插入内存检查，当 `avail_gb < 2GB` 时 `continue` 跳过当前截面。

但 `continue` 意味着当前迭代**不执行任何 yield**，调用方（`scheduler.py` 中的 `_aggregate_summary_streaming`）将少收到一个结果。聚合逻辑中的 `total_dates` 计数依赖 `for r in result_iter:`，跳过截面将导致 `total_dates` < 预期截面数。

**建议修复**：跳过截面时同样需要 `yield` 一个占位结果：

```python
if avail_gb < 2.0:
    logger.warning(...)
    # 写入 NULL 记录
    # ...
    yield {
        "date": dt_str,
        "status": "SKIPPED",
        "total_factors": n_factors,
        "computed_factors": 0,
        "ic_results": [],  # 或包含已写入的 NULL 记录
        "errors": {"memory": f"Available {avail_gb:.2f}GB < 2GB"},
    }
    gc.collect()
    continue
```

---

### 🟡 DEFECT-C1-2（一致性问题）：`--no-run` 模式的实现不明确

**严重性**：可执行性 — 低

**问题描述**：

方案在 C7 入口脚本中声明了 `--no-run` 参数，Phase 2 步骤 2.5 和 P2.6 也引用了 `run_id='repro_norun'`。但没有任何代码改动描述 `--no-run` 模式的实际实现——管线如何在不计算 IC 的情况下只写入 run_id 标记？Plan 说"跳过管线计算，仅从已有数据出报告"，但报告的来源和格式未定义。

**建议**：在方案中补充 `--no-run` 模式的实现说明，或在 Phase 1 验证后明确是否需要此模式（如果可以跳过 Phase 2.5，P2.6 也相应移除）。

---

## 二、Phase 1 PASS 标准评估（P1.1~P1.8）

### ✅ 已通过的 STANDARD

| 编号 | 结论 | 说明 |
|:----:|:----:|:------|
| P1.1 | ✅ 合理 | run_id 列存在性检查 |
| P1.2 | ✅ 合理 | 第一次写入计数 |
| P1.3 | ⚠️ 需调整 | PASS 条件"控制台观察"太模糊。建议改为：`$LASTEXITCODE -eq 137`（SIGKILL 的标准退出码）或进程消失的证据 |
| P1.4 | ✅ 合理 | 重启后新写入计数 |
| P1.5 | ✅ 合理 | DISTINCT run_id = 2 |
| P1.6 | ✅ 合理 | 旧数据未被污染（但见 DEFECT-C1-1，此检查会失败除非修复） |
| P1.7 | ✅ 合理 | psutil 日志存在性 |
| P1.8 | ✅ 合理 | source_version 隔离检查 |

### 🔴 缺失的 PASS STANDARD

**P1.9 — null_record source_version 一致性验证**（新增）

```
条件：SELECT source_version, COUNT(*) FROM a50_cross_ic_result 
      WHERE source_version='v1_repro' 
      AND ic_value IS NULL 
      GROUP BY source_version

预期：COUNT > 0（v1_repro 下有 null 记录）
防止：null_record 混入 v1
```

**缺失理由**：DEFECT-C1-1 的存在使此检查成为必要。修复后需验证 null 记录也被正确标记为 v1_repro。

**P1.10 — run_id 不影响 INSERT OR IGNORE 唯一性**（新增）

```
条件：SELECT trade_date, factor_name, forward_window, source_version, 
             COUNT(DISTINCT run_id) 
      FROM a50_cross_ic_result 
      WHERE source_version='v1_repro' 
      GROUP BY trade_date, factor_name, forward_window, source_version 
      HAVING COUNT(*) > 1

预期：返回 0 行（INSERT OR IGNORE 防止了重复）
确认：唯一约束 (trade_date, factor_name, forward_window, source_version) 不受 run_id 影响
```

**缺失理由**：需要显式确认 `run_id` 不在唯一约束中，防止开发者错误理解 run_id 可以突破 unique constraint。

---

## 三、Phase 2 PASS 标准评估（P2.1~P2.6）

### ✅ 已通过的 STANDARD

| 编号 | 结论 | 说明 |
|:----:|:----:|:------|
| P2.1 | ✅ 合理 | run_id 非空检查 |
| P2.2 | ✅ 合理 | run_id 精确区分 |
| P2.3 | ✅ 合理 | 旧数据隔离（但见 DEFECT-C1-1） |
| P2.4 | ⚠️ 需加量化标准 | "形成完整内存曲线"太模糊，见下方建议 |
| P2.5 | ✅ 合理 | 时间戳对比确认杀前截面 |
| P2.6 | ✅ 合理 | --no-run 记录存在（但需先解决 C1-2 的实现问题） |

### 🟡 P2.4 建议增加量化阈值

当前条件"形成完整内存曲线"不可测量。建议改为：

```
P2.4a: [MemGuard] 日志条目数 ≥ 总截面数 × 80%（允许因 OOM 中断导致的部分缺失）
P2.4b: 日志可解析为 CSV，包含字段 [截面日期, RSS_GB, Avail_GB]
```

---

## 四、U1 的 psutil 趋势数据确认方案评估

方案 §9.1 对 U1 的三种结果场景（触发 OOM+有最后记录 / 触发 OOM+缺失 / 未触发 OOM）均有明确处理逻辑。其中对 OOM 场景的预期：

> "若触发 OOM，日志中最后一条 [MemGuard] 记录的时间 ≈ 被杀时间"

**合理性**：✅ 合理。由于 psutil 检查在每个截面开头执行，而非实时轮询，确实只能保证"截面级精度"而非"秒级精度"。误差 = 当前截面开始到被杀的时长（≤ 1 截面处理时间）。

**补充建议**：建议在日志中同时记录 `[MemGuard]` 的监控开始时间和最后一条记录的时间差，作为"杀前存活截面数"的度量。

---

## 五、数据隔离方案评估

### 方案架构：source_version + run_id 双重隔离

| 维度 | 评估 | 结论 |
|:-----|:-----|:------|
| `source_version='v1_repro'` | 与生产 `'v1'` 隔离，机制清晰 | ✅ |
| `run_id` 逐运行标识 | 精确区分各次写入 | ✅ |
| 查询隔离规则（§7.2） | SQL 明确，可执行 | ✅ |
| DB 全量备份（§7.3） | 恢复能力 | ✅ |

### 风险点（已列在方案 R4 中）

方案已识别 R4"重跑数据污染生产查询"，缓解措施为 source_version 隔离 + 查询脚本显式过滤。此措施足够，但需额外确认：

**额外需要确认的污染路径**：

1. **检查 `_aggregate_summary_streaming`**：在 `scheduler.py` 中，聚合方法对所有 `result_iter` 输出的 ic_results 进行统计。由于 pipeline 实例只处理 `source_version='v1_repro'` 的数据，**聚合只在 `v1_repro` 范围内**，不影响旧数据。 ✅

2. **检查现有 SQL 视图**：建议在 Phase 0 中检查 `a50_cross_ic_result` 上是否有未过滤 `source_version` 的视图或触发器等对象。如果你的环境中有监控面板或导出脚本使用 `SELECT * FROM a50_cross_ic_result`，可能会抓到 `v1_repro` 数据。 → **建议**：在执行 ALTER TABLE 前，运行以下检查：

```sql
SELECT sql FROM sqlite_master 
WHERE type IN ('view', 'trigger') 
  AND sql LIKE '%a50_cross_ic_result%';
```

---

## 六、其他发现

### 6.1 Phase 1 步骤 1.4 中的 `--resume` 参数

> "重启：`--run-id test_run2`（含--resume）继续跑"

入口脚本（C7）中**没有定义 `--resume` 参数**。`run_batch_streaming` 虽然支持 `resume_from` 参数接收 checkpoint_id，但入口脚本需要：
1. 读取上一轮的 checkpoint（checkpoint 以旧 run_id 命名）
2. 传入 `CrossSectionalICPipeline` 的 `resume_from` 参数

这个逻辑需要在入口脚本中实现，方案未详述。→ **建议补充 C7 中 `--resume` 的实现说明**。

### 6.2 重复运行不会增加行数（INSERT OR IGNORE 行为）

这是有意设计的行为，但值得显式说明：当 Phase 2 重启后使用 `run_id='repro_p2'`，但 `source_version='v1_repro'` 不变时，`repro_p1` 已写过的 `(trade_date, factor_name, forward_window, v1_repro)` 组合会被 `INSERT OR IGNORE` 跳过。因此 `repro_p2` 只写入 `repro_p1` 未完成的截面。这符合预期，也符合原始故障的 T+21 场景（重启后只补未完成截面）。

---

## 七、总体缺陷清单

| # | 缺陷 | 严重性 | 类型 | 影响阶段 |
|:-:|:-----|:------:|:-----|:--------|
| DEFECT-C1-1 | `_build_null_record` 静态方法硬编码 source_version='v1'，导致 null 记录污染生产数据 | 🔴 高 | 数据污染 | Phase 1/2 |
| DEFECT-SIGKILL-1 | `taskkill /F /PID` 在 WSL2 下无法找到 Python 进程 | 🔴 高 | 流程阻塞 | Phase 1 |
| DEFECT-C2-1 | C2 跳过截面时未 yield，导致聚合器计数不准确 | 🟡 中 | 可观测性缺失 | Phase 1/2 |
| DEFECT-C1-2 | --no-run 模式实现不明确，P2.6 依赖其执行 | 🟡 中 | 定义不全 | Phase 2 |
| MISS-P1 | 缺少 P1.9（null record source_version 验证）和 P1.10（unique constraint 确认） | 🟡 中 | 验证缺失 | Phase 1 |
| MISS-P2 | P2.4 缺少量化标准 | 🟢 低 | 条件模糊 | Phase 2 |

---

## 八、整改建议优先级

### 必须修复（阻塞级）

1. **DEFECT-C1-1** — 修改 `_build_null_record` 使其使用实例的 `source_version`。修改 `run_pipeline` 中所有调用 `_build_null_record` 的地方传入 `source_version`。
2. **DEFECT-SIGKILL-1** — 将方案 A 的 `taskkill` 替换为 WSL 内部 kill（`wsl kill -9 <PID>` 或使用方案 B 文件信号）。
3. **补齐 P1.9 和 P1.10** — 添加两个缺失的 PASS 标准。

### 强烈建议修复

4. **DEFECT-C2-1** — 跳过截面时 yield 占位结果。
5. **补充 C7 中 `--resume` 逻辑** — 实现 checkpoint 读取和传入 `resume_from`。

### 建议但不阻塞

6. **P2.4 加量化标准** — 明确 [MemGuard] 条目数最低比例。
7. **执行前运行 `sqlite_master` 检查** — 确认无污染风险。

---

## 九、重新审查条件

修复上述全部**必须修复**和**强烈建议修复**后，重新提交 v2 方案，墨萱会重新审查。

---

*EOF — 墨萱 QA 审查报告*
