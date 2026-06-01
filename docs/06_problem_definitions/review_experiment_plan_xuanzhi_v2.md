---
author: 玄知 (xuanzhi)
created_time: 2026-05-31T10:40:00+08:00
type: architecture_review_v2
review_for: experiment_plan_U2_repro_v2.md
version: v2.0
status: APPROVED
based_on_v1_review: review_experiment_plan_xuanzhi.md
---

# 试验方案架构审查报告 v2

**审查对象**：`experiment_plan_U2_repro_v2.md`（v2.0）
**审查者**：玄知（架构+数据一致性）
**审查时间**：2026-05-31T10:40+08:00
**v1缺陷清单**：D1(严重) / D2(严重) / D5(中) / D4(中)

---

## 总体结论：✅ APPROVED

v2已修复v1审查中发现的全部4项缺陷（D1、D2、D5、D4），并新增了P1.9/P1.10两项PASS标准、量化了P2.4阈值、补充了--no-run实现说明（C1-2）、修复了跳过截面不yield问题（C2-1）、改写了SIGKILL模拟方案。**架构和数据一致性层面无残留阻塞项。**

> 验收：A2（代码改动最小侵入）✅ / A4（数据隔离完整）✅ / A7（环境差异覆盖）✅

---

## 一、缺陷逐项审查

### 1. D2（严重）：唯一索引不含run_id — ✅ 确认修复，同意方案A

**v1发现**：唯一索引 `(trade_date, factor_name, forward_window, source_version)` 不含 `run_id`，不同run_id写入相同截面时被 `INSERT OR IGNORE` 静默跳过，导致 `GROUP BY run_id` 计数偏差。

**v2修复**：
- 方案A：DROP旧唯一索引 → CREATE含run_id的新唯一索引 `(trade_date, factor_name, forward_window, source_version, run_id)`
- 附完整执行SQL序列（Step 1~6）+ PRAGMA验证步骤
- C5标记为D2专项修复，预估5 min改动
- 附录A新增A6/A7/A9查询验证索引行为

**关于拒绝date_range方案（方案B）的判断**：✅ **同意墨衡的选择。**

墨衡给出的理由充分：
- U2的**核心验证目标**是"三个进程（marine-s/mellow-o/norun）使用相同截面日期范围（T0~T+21），run_id能否精确区分各自写入量"
- 使用date_range分段运行会让各段日期互不重叠 → U2验证失去意义 → 等于跳过核心测试条件
- 方案A直接在唯一索引层面区分run_id，数据虽膨胀（N个run_id对应N条），但这是验证U2的必要代价

**额外确认项**：

**a) SQLite中NULL在UNIQUE索引中的行为** — 需确认旧数据run_id=NULL在新索引下不冲突。

SQLite的UNIQUE约束中，NULL值被视为互不相等的（每个NULL都唯一）。但更关键的是：旧数据在旧唯一索引 `(trade_date, factor_name, forward_window, source_version)` 下已保证每个组合仅1行。迁移到新索引时，这些行的run_id=NULL，每个组合 `(..., NULL)` 在新索引中也只出现1次，不会产生冲突。

**b) 新旧数据如何在索引中共存**

| 数据 | run_id | 索引行为 |
|:-----|:-------|:---------|
| 旧v1数据 | NULL | 旧数据各组合唯一，新索引作为扩展键无冲突 |
| 新v1_repro/repro_p1 | 'repro_p1' | 与旧数据run_id=NULL不同，不冲突 |
| 新v1_repro/repro_p2 | 'repro_p2' | 与repro_p1的run_id不同，不冲突 |

新索引正常工作，无需NULL兼容性处理。v2方案Step 6的验证SQL可确认。

---

### 2. D1（严重）：run_id未透传工厂方法/checkpoint恢复 — ✅ 确认修复

**v1发现**：
1. `from_config()` 工厂方法未传递 `run_id` 参数
2. 入口脚本未定义resume参数，checkpoint恢复路径断裂
3. `run_id` 与 `pipeline_run_id` 双ID系统混淆

**v2修复检查表**：

| v1缺陷点 | v2改动 | 状态 |
|:---------|:-------|:----:|
| `from_config()` 缺run_id | C4改动点③：`from_config()` 新增 `run_id` 参数 ✅ | ✅ |
| 入口脚本无resume | C7：新增 `--resume-from` 参数 + `find_checkpoint_id()` 辅助函数 | ✅ |
| run_id vs pipeline_run_id混淆 | C7中补充ID系统说明文档（两套独立ID系统+映射关系） | ✅ |
| 重启流程不清晰 | Phase 1步1.4：明确写为 `--resume-from <checkpoint_id>`，附录B明确run_id=新值 | ✅ |

**额外确认**：C7中 `find_checkpoint_id()` 通过文件名匹配 `run_id` 查找checkpoint文件，解决了"重启后operator不知道pipeline_id"的实践问题。流程清晰，可执行。

---

### 3. D5（中）：_build_null_record硬编码source_version — ✅ 确认修复

**v1发现**：`_build_null_record` 为 `@staticmethod`，内部使用模块级常量 `SOURCE_VERSION`（永久等于 `'v1'`），导致实验产生的NULL记录污染基线数据。

**v2修复**：
- C1a（第3.2节改动点③）：改为实例方法，使用 `self.source_version` ✅
- 调用方式无需变更（第改动点④）✅
- 同时新增 `self.run_id` 添加到null_record ✅
- 新增P1.9（v1_repro下NULL记录的source_version验证）✅

**穿透验证**：P1.9的SQL保证v1_repro下的NULL记录确实使用了'v1_repro'而非'v1'。

---

### 4. D4（中）：WSL2环境差异遗漏 — ✅ 确认修复

**v1发现**：附录C遗漏5项关键环境差异。

**v2修复**：附录C补充了全部5项：

| 遗漏项 | v2状态 | 备注 |
|:-------|:------:|:-----|
| SIGKILL行为差异 | ✅ 已补充 | 影响U1结论可移植性，结论文档需加注 |
| ulimit -v支持度 | ✅ 已补充 | 若无效则OOM模拟方案C不可用 |
| WSL2内存回收策略 | ✅ 已补充 | 影响Avail读数有效性 |
| 文件系统IO差异 | ✅ 已补充 | 建议全部使用WSL2内部路径 |
| Python psutil WSL2准确性 | ✅ 已补充 | 运行前先 `python -c` 验证 |

**建议保留**：结论文档需明确标注所有U1结论的适用范围为"WSL2环境"，不可直接外推至原生Linux。

---

## 二、核心设计决策确认：唯一索引含run_id的NULL兼容性

### 问题：新唯一索引 `(..., run_id)` 对旧数据（run_id=NULL）的影响

**分析**：

SQLite中，UNIQUE约束对NULL的处理遵循SQL标准——NULL被视为互不相等。因此：

1. **旧数据内部**：旧数据在旧索引下已保证 `(trade_date, factor_name, forward_window, source_version)` 组合唯一。迁移到新索引后，每行变为 `(..., NULL)`，各行的NULL被视为不同值，不会产生冲突。
2. **旧数据 vs 新数据**：新数据的run_id为 `'repro_p1'` 等非NULL字符串，与旧数据的 `NULL` 不同，索引不冲突。
3. **INSERT OR IGNORE行为**：
   - 新run_id写旧run_id已存在的截面 → 插入成功（run_id不同，索引组合不同）
   - 同run_id重复写同截面 → IGNORE跳过（五列组合相同）
   - 旧数据插入NULL run_id + 新数据的五列组合 → 新索引允许共存（run_id: NULL vs 'repro_p1'）

**结论**：✅ **兼容性无问题。** 无需为NULL做特殊处理。v2方案的Step 6验证SQL（`SELECT ... WHERE run_id IS NULL GROUP BY run_id`）已覆盖验证。

### 额外建议（可选，不阻塞）

如果后续有其他试验需要向 `a50_cross_ic_result` 表中插入 `run_id=NULL` 的新数据，建议在管线层做一次防御性校验：

```python
if self.run_id is None:
    logger.warning(
        "run_id is None. New records will have run_id=NULL, "
        "potentially conflicting with old data."
    )
```

本次试验不需要此改动，因为所有试验运行均传入非空run_id。

---

## 三、v1其他缺陷回顾

v1审查共识别6项缺陷（含墨萱和玄知的合并清单）。v2方案已在附录D中清晰列出v1→v2变更对照，逐一确认：

| 缺陷ID | 严重度 | v1问题 | v2修复 | 审查结论 |
|:------:|:------:|:--------|:--------|:--------:|
| **D2** | 🔴严重 | 唯一索引不含run_id | 方案A：DROP旧→CREATE含run_id新索引 | ✅ |
| **D1** | 🔴严重 | from_config缺run_id；入口无resume | from_config新增run_id；入口新增--resume-from等 | ✅ |
| **D5** | 🟡中 | _build_null_record硬编码v1 | 改为实例方法+self.source_version | ✅ |
| **D4** | 🟡中 | 附录C遗漏5项环境差异 | 附录C补充SIGKILL/ulimit/内存回收/IO/psutil | ✅ |
| **D3** | 🟢低 | psutil检查点与内存峰值偏移 | v2无结构修复（属认知边界），但新增post-check双检+§7.3说明 | ✅ 标注为边界说明 |
| C1-2 | 🟡中 | --no-run无实现说明 | 新增§九完整实现+伪代码 | ✅ |
| C2-1 | 🟡中 | 跳过截面不yield | yield占位结果（含status=SKIPPED） | ✅ |
| SIGKILL-1 | 🔴高 | taskkill在WSL2不可用 | 文件信号自杀法（方案B）首选 | ✅ |
| 缺P1.9/P1.10 | 🟡中 | 缺失PASS标准 | 新增P1.9（null记录验证）+P1.10（索引验证） | ✅ |
| P2.4模糊 | 🟢低 | "形成完整内存曲线"不可量化 | 量化标准：≥80%截面+可解析CSV | ✅ |

---

## 四、补充观察（新发现、不阻塞）

### 4.1 文件信号自杀（KILL_NOW.signal）的竞态条件风险

v2 §6.2使用文件信号模拟SIGKILL，但在信号文件检测到 `os.remove(KILL_FILE)` 后，实际触发 `os.kill(os.getpid(), signal.SIGKILL)` 前存在约0.1~2秒的模拟延迟。如果**两个进程同时检测到同一个KILL_FILE**（极小概率），可能产生竞态。

风险极低，因为试验中只运行单个pipeline实例，信号创建也由operator手动控制。无需修复，仅作为设计文档备注。

### 4.2 Phase 1步骤1.3退出码验证的精确性

v2方案P1.3要求`$LASTEXITCODE -eq 137`作为SIGKILL的验证标准。需注意：**文件信号自杀法（方案B）**在`os.kill(os.getpid(), signal.SIGKILL)`后，进程退出码无法捕获（shell无法在kill之后捕获退出码）。正确的退出码验证只适用于**外部kill**场景（方案C或备用方案）。

建议：如果Phase 1使用文件信号自杀法，P1.3的条件应调整为"进程消失"或"日志中出现[KillSim]标记"，而非依赖退出码。

### 4.3 from_config() 的 run_id 默认值

C4改动点③中 `from_config()` 的 `run_id` 参数默认值为 `None`（`run_id: Optional[str] = None`）。这意味着：
- 正常生产使用 `from_config()` 时，run_id默认为None，不会意外开启U2验证模式 ✅
- 试验使用时，operator显式传入run_id ✅

这是一个好的默认值设计，**无需修改**。

---

## 五、条件性通过确认

v1审查中提出的3项条件性通过先决条件：

| 条件 | 状态 | v2验证 |
|:-----|:----:|:-------|
| C1（D2）：修正唯一索引或调整写入策略 | ✅ **满足** | 方案A：含run_id新索引 |
| C2（D1）：确认重启resume机制 | ✅ **满足** | --resume-from + find_checkpoint_id完整实现 |
| C3（D5）：修复_build_null_record的source_version | ✅ **满足** | 实例方法+self.source_version |

三项先决条件全部满足，v2方案可以进入Phase 0执行。

---

## 六、验收声明

| 验收项 | 审查项 | 结论 |
|:-------|:-------|:----:|
| A2（代码改动最小侵入） | 所有改动限定在管线+scheduler+入口脚本，不涉及现有v1基线路径 | ✅ PASS |
| A4（数据隔离完整） | source_version + run_id + 唯一索引含run_id三重隔离；旧数据run_id=NULL兼容 | ✅ PASS |
| A7（WSL2环境差异覆盖） | 附录C补充5项遗漏，覆盖SIGKILL/ulimit/内存回收/IO/psutil | ✅ PASS |

---

## 七、建议执行顺序（不阻塞、仅建议）

1. **先跑附录C预验证脚本**：运行 `python -c "import psutil; print(psutil.virtual_memory())"` 确认psutil在WSL2中的准确性，以及 `ulimit -v` 是否有效
2. **Phase 0执行前**：运行墨萱建议的sqlite_master检查（确认无未过滤视图/触发器）
3. **Phase 1测试文件信号自杀时**：P1.3的退出码验证改用日志检查替代
4. **Phase 2若触发两次以上SIGKILL**：考虑缩小date_range到最近2年（方案已有R2预案）

---

*EOF — 玄知架构审查报告 v2*
