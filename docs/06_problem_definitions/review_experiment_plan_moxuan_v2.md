---
author: 墨萱 (moxuan)
reviewed: experiment_plan_U2_repro_v2.md
date: 2026-05-31T10:35:00+08:00
type: qa_review_v2
status: PASS
overall: PASS
---

# 墨萱 QA 审查报告 — 故障复现试验方案 v2

## 总体结论：PASS ✅

v2 已完整修复 v1 审查发现的所有 4 项缺陷，新增 P1.9/P1.10/P2.4 量化标准到位，核心设计决策（唯一索引含 run_id）经评估同意。

**结论**：v2 方案可进入下一环节（玄知架构确认 → 墨涵知识审查 → Owner签署）。

---

## 一、v1 缺陷修复逐项验证

### 1.1 C1-1：_build_null_record 硬编码 v1 → 改为实例方法 ✅ FIXED

| 维度 | v1 状态 | v2 修复 | 验证 |
|:-----|:---------|:---------|:----:|
| 方法签名 | `@staticmethod`，返回固定 `SOURCE_VERSION` | 改为实例方法，使用 `self.source_version` | ✅ |
| 调用方式 | 无变化（见第 503/521 行） | `self._build_null_record(date, factor, n)` 调用方式不变，内部正确使用 `self.source_version` | ✅ |
| null 记录中的 run_id | v1 未提及 | v2 新增 `"run_id": self.run_id` 字段 | ✅ |
| 关联影响 | null 记录混入 v1 基线数据 | `_build_null_record` 中 `source_version` 跟随实例，保证 null 记录正确落入 `v1_repro` 隔离空间 | ✅ |

**验证结论**：v2 改动点③ 完整修复。`self.source_version` + `self.run_id` 双修正保证了 null 记录不会污染基线数据。

---

### 1.2 SIGKILL-1：WSL2 taskkill 不可用 → 文件信号自杀法 ✅ FIXED

| 维度 | v1 问题 | v2 修复 | 评价 |
|:-----|:---------|:---------|:----:|
| 主方案 | `taskkill /F /PID` 在 WSL2 中不返回内部进程 | 文件信号自杀（方案B）：创建 KILL_NOW.signal 文件触发进程自检测 + `os.kill(os.getpid(), signal.SIGKILL)` | ✅ |
| 信号检测位置 | 未定义 | 插入 `run_batch_streaming` 每截面循环开头，检测到信号后先写 checkpoint 再自杀 | ✅ |
| 备用方案 | 无 | WSL 内部 `wsl kill -9 <PID>` | ✅ |
| 退出码验证 | "控制台观察"模糊 | v2 P1.3 精确化：`exit code = 137`（128+9 SIGKILL） | ✅ |
| 可靠性 | 方案不可执行 | 文件信号法在 WSL2 和原生 Linux 均可靠——检测逻辑完全在 Python 进程内部，不依赖外部指令 | ✅ |

**可靠性评估**：

**优势**：
- 信号检测在每截面循环开头，检测粒度 = 1 截面处理时间（最坏情况：当前截面处理完才检测到）
- 先写 checkpoint 再自杀，确保 resume 时有完整进度记录
- 不依赖外部工具链，WSL2 和原生 Linux 行为一致

**潜在边缘情况**：
- 如果 KILL_NOW.signal 在 checkpoint 写入后、`os.kill()` 前被意外触发（如另一个信号文件被创建），当前设计会正确重走自杀路径（`os.remove` 已清理前一个信号）
- 若进程在 `os.remove(KILL_FILE)` 后、checkpoint 写入前崩溃（非 SIGKILL），信号文件已清失。重启后进程将正常恢复，不会进入自杀路径。此场景概率极低，且不影响测试结论

**结论**：信号文件法正确、可靠，纳入 v2 完全适合。

---

### 1.3 C2-1：跳过截面时 yield 断裂 → 跳过时 yield 占位结果 ✅ FIXED

| 维度 | v1 问题 | v2 修复 | 评价 |
|:-----|:---------|:---------|:----:|
| 跳过行为 | `continue` 不执行任何 yield | `yield` 占位结果 + `continue` | ✅ |
| 占位结果字段 | 未定义 | `date` / `status="SKIPPED"` / `computed_factors=0` / `ic_results=[]` / `errors` / `mem_check` / `run_id` | ✅ |
| 对聚合器的影响 | `total_dates` < 预期截面数 | 跳过截面也计入迭代次数，聚合器计数准确 | ✅ |
| L3 写入 null 记录后仍 yield | 未定义 | 先写 null 记录 + `gc.collect()` 再 yield | ✅ |

**验证结论**：v2 修复完整。跳过时的 yield 占位保证了生成器的连续性未被截断，所有必需字段均已包含。

---

### 1.4 C1-2：--no-run 无实现说明 → 新增 §9 覆盖 ✅ FIXED

| 维度 | v1 问题 | v2 修复 | 评价 |
|:-----|:---------|:---------|:----:|
| 实现伪代码 | 不存在 | §9.2 完整伪代码：`run_no_run_mode()` | ✅ |
| 写入逻辑 | 未定义 | 从 DB 读取已有 `source_version='v1_repro'` 的截面列表 → 每 (date, factor) 写入一条 null 标记 | ✅ |
| 执行前提 | 不明确 | §9.3 规定需先完成正常重跑 | ✅ |
| phase/scenario 对应 | 仅在 Phase 2 步骤 2.5 提及 | §9.3 明确"重跑完成后执行" | ✅ |

**验证结论**：§9 完整覆盖了 --no-run 模式的目的、实现、执行前提，关闭了 v1 的此缺陷。

---

## 二、新增 PASS 标准评估（P1.9 / P1.10 / P2.4）

### 2.1 P1.9 — null_record source_version 一致性 ✅ ADDED

| 检查项 | 条件 | v2 状态 |
|:-------|:-----|:--------|
| 验证什么 | null 记录的 `source_version` 是否为 `v1_repro` | ✅ SQL 聚合确认 COUNT > 0 |
| 为何必要 | 防止 C1-1 修复后仍存在遗漏路径 | ✅ 已覆盖 |
| 验证方式 | `SELECT source_version, COUNT(*) FROM a50_cross_ic_result WHERE ic_value IS NULL AND source_version='v1_repro' GROUP BY source_version` | ✅ 可执行 |

**结论**：P1.9 条件合理、SQL 明确、预期可测量。**通过**。

### 2.2 P1.10 — 唯一索引含 run_id 正确性 ✅ ADDED

| 检查项 | 条件 | v2 状态 |
|:-------|:-----|:--------|
| 验证什么 | 同 run_id 内部同一截面不重复 | ✅ `HAVING COUNT(*) > 1 AND COUNT(DISTINCT run_id) = 1` 预期 0 行 |
| 为何必要 | 确认 INSERT OR IGNORE 在新唯一索引下行为正确 | ✅ 已覆盖 |
| 与 P1.5 的区别 | P1.5 检查 DISTINCT run_id 总数；P1.10 检查**单截面级别**的 run_id 不重复 | ✅ |

**结论**：P1.10 条件精确、SQL 可执行。**通过**。

### 2.3 P2.4 — psutil 监控量化标准 ✅ FIXED

| 维度 | v1 模糊表述 | v2 量化标准 | 评价 |
|:-----|:-------------|:------------|:----:|
| 覆盖率 | "形成完整内存曲线" | (a) `[MemGuard]` 出现次数 ≥ 总截面数 × 80% | ✅ 可量化 |
| 数据格式 | 不可解析 | (b) 日志可解析为 CSV（截面日期, phase, RSS_GB, Avail_GB） | ✅ 可自动化验证 |

**补充建议**：建议在 Phase 1 准备一个简单的日志解析脚本（如 `grep '[MemGuard]' pipeline.log | awk '{print ...}'`），在 Phase 2 执行后一键运行验证 P2.4a/b，避免人工数日志行数。

**结论**：P2.4 从定性升级为定量标准，可执行。**通过**。

---

## 三、核心设计决策评估：唯一索引含 run_id（方案A）

### 3.1 决策内容

墨衡选择 **方案A（唯一索引含 run_id）** 而非玄知建议的方案B（date_range 分段运行）。

### 3.2 决策合理性评估

我**同意方案A**，理由如下：

```
┌────────────────────────────────────────────────────────────┐
│ U2 验证的核心场景：                                        │
│                                                             │
│   原始故障中，三次运行（marine-s / mellow-o / --no-run）   │
│   覆盖的是 完全相同 的截面日期范围 —— T0~T+21。            │
│                                                             │
│   U2 要验证的是：在这些相同截面被多进程写入后，run_id 能否 │
│   ╔══════════════════════════════════╗                      │
│   ║ 精确区分 各自 的写入量。        ║ ← 核心验证目标       │
│   ╚══════════════════════════════════╝                      │
└────────────────────────────────────────────────────────────┘
```

| 对比维度 | 方案A（含 run_id 索引） | 方案B（date_range 分段） |
|:---------|:------------------------|:-------------------------|
| **与 U2 验证目标对齐** | ✅ **完全对齐**：同截面多 run_id 共存的场景正是原始故障 | ❌ **错失核心**：各段日期互不重叠，回退至"无竞争写入"场景 |
| **数据竞争验证** | ✅ 可验证 INSERT OR IGNORE 在含 run_id 索引下的行为 | ❌ 规避了数据竞争条件 |
| **代码改动量** | 2 条 SQL（DROP + CREATE） | 0 条 SQL（流程层面调整） |
| **数据膨胀风险** | 每次重启新增同截面新行（预期行为，可接受） | 无膨胀 |
| **resume 依赖** | 需要--resume-from 指针到 checkpoint | 隐含在 date_range 设计（每段独立重启） |

**核心判定**：方案B 是"规避问题"而非"验证修复"。U2 的原始问题陈述就是"相同 source_version + 相同截面日期 → 无法区分三次运行的写入量"。如果各段日期互不重叠，那 U2 的验证前提就不存在了。方案A 才是正确的复现方式。

**数据膨胀接受程度**：本次试验最多 3 次运行（repro_p1 + repro_p2 + repro_norun），每个截面最多 2~3 行重复数据。以近 5 年约 1300 个交易日、~50 个因子、~3 个 forward_window 估算，膨胀最多在 2~3 倍范围内，完全可接受。

### 3.3 §3.6.3 数据行为表的正确性验证

| 场景 | v2 描述 | 实际 SQLite 行为 | 一致？ |
|:-----|:---------|:-----------------|:------:|
| 首次写入（新 run_id） | INSERT OR IGNORE 成功 | 五列组合不存在 → 插入 | ✅ |
| 同 run_id 重复写入 | IGNORE 跳过 | 五列完全相同 → IGNORE | ✅ |
| 不同 run_id 同截面 | 插入成功（新行） | run_id 不同 → 索引组合不同 → 插入 | ✅ |
| 重启后新 run_id 写入未完成截面 | 插入成功 | 未完成截面无旧 run_id 记录 → 插入 | ✅ |
| 重启后新 run_id 写入已完成截面 | 旧 + 新 各一条 | run_id 不同 → 两条记录共存 | ✅ |

**结论**：数据行为表与 SQLite UNIQUE 索引的 NULL 处理规则完全一致。✅

### 3.4 方案A决策结论

**✅ 同意方案A**。墨衡的选择正确对应了试验目标。不存在对玄知"推倒重来"的必要——事实上，方案B（date_range 分段）是在 v1 审查中作为 resume 机制的替代方案提出的（玄知条件C2），而非对唯一索引设计本身的否定。

---

## 四、其他 v2 改进点确认

### 4.1 玄知 D1：from_config + resume 机制 ✅ FIXED

| 具体要求 | v2 修复 | 验证 |
|:----------|:---------|:----:|
| from_config 透传 run_id | §3.5 改动点③：from_config 新增 run_id 参数 | ✅ |
| 入口脚本 --resume-from | §3.7 C7：新增 `--resume-from PIPELINE_ID` 参数 | ✅ |
| run_id vs pipeline_run_id 双 ID 系统说明 | §3.7 代码注释块完整说明 | ✅ |
| checkpoint 查找辅助 | §3.7 `find_checkpoint_id()` 函数 | ✅ |

### 4.2 玄知 D3：psutil post-check 双检 ✅ FIXED

v2 在每截面计算后新增 post-check，配合 §7.3 明确标注"1 截面偏差"的认知边界。

### 4.3 玄知 D4：附录 C 环境差异补充 ✅ FIXED

v2 附录 C 新增 5 项：SIGKILL 行为、ulimit 支持、WSL2 内存回收、跨文件系统 IO、psutil 准确性。并附有"运行前先用 `python -c` 验证"的操作建议。

### 4.4 附录 D：v1→v2 变更对照表 ✅ NEW

v2 新增完整的 11 项变更对照表（D2→附录D首行），覆盖了所有已知缺陷的修复状态，极大提升了可追溯性。这是超出 v1 审查要求的交付物，值得肯定。

---

## 五、残余风险提醒

尽管 v2 已完整修复，列以下 3 点作为**执行阶段的关注点**，非本轮 BLOCKER：

### R1：文件信号自杀的 race window（低风险）

`os.remove(KILL_FILE)` 在 checkpoint 写入**之前**执行。若进程在此间隔内意外崩溃，KILL_NOW.signal 已被清失而 checkpoint 未写入，恢复后的进程将不会进入自杀路径。重启时属于"正常 resume"而非"信号触发自杀"。

**影响**：极低。仅影响测试的"退出码 = 137"验证链；对 run_id 写入和数据隔离无影响。

### R2：P2.4 日志解析脚本建议预写（低风险）

P2.4b 要求日志可解析为 CSV。建议在 Phase 0 中预写一个简单的解析脚本（如 `python scripts/parse_memguard_log.py pipeline_*.log`），避免 Phase 2 执行后临时手写。

### R3：无 checkpoint 时的 --resume-from 行为（文档级）

方案 §3.7 `find_checkpoint_id()` 函数在找不到 checkpoint 时返回 None，入口脚本在 `if args.resume_from:` 分支中未处理 `None` 情况（代码中 `result_iter = pipeline.run_batch_streaming(... resume_from=args.resume_from)` 会直接传入 `None` 值）。

**建议**：入口脚本增加 `if not resume_pipeline_id:` 的显式检查并退出，避免将 `None` 隐式传递给 `resume_from`。

---

## 六、验收清单

| # | 验收项 | v1 缺陷 | v2 修复状态 | 墨萱结论 |
|:-:|:-------|:---------|:-----------:|:---------:|
| A1 | 方案完整覆盖 U1/U2 可观测性边界 | — | ✅ 完整 | PASS |
| A3 | Phase 1 PASS 标准合理可量化（含 P1.9/P1.10） | MISS-P1 | ✅ 补充 | PASS |
| A5 | OOM 防护足够（pre/post 双检 + 三级阈值 + yield 占位） | C2-1/D3 | ✅ 增强 | PASS |
| A6 | 试验结论可追溯验证 | — | ✅ 附录 D 变更表 | PASS |

---

*EOF — 墨萱 QA 审查报告 v2*
