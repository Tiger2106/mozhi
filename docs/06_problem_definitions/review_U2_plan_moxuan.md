# 方案B2审查报告 — 墨萱

- **审查日期**: 2026-05-31T10:08+08:00
- **审查人**: 墨萱（第三方测试）
- **方案版本**: plan_solve_U2_20260531.md v1.0
- **审查范围**: 方案B2（新增run_id列+重跑）

---

## 结论：**PASS**（附3项WARN）

方案B2整体可行，代码改动量小且精确度高。以下为逐项审查详情。

---

## 1️⃣ 代码改动量评估

| 改动位置 | 改动内容 | 量级 |
|:---------|:---------|:----:|
| `CrossSectionalICPipeline.__init__` | 新增 `run_id` 参数存储 | +1行 |
| `CrossSectionalICPipeline.run_pipeline` Step 3f | ic_record中增加 `"run_id": self.run_id` | +1行 |
| `CrossSectionalICPipeline._build_null_record` | 新增 `run_id` 参数 + 写入返回字典 | +2行 |
| `CrossSectionalICPipeline._write_ic_result` | INSERT加入run_id字段与占位符 | +2行 |
| `ICBatchScheduler.__init__` | 新增 `run_id` 参数 | +1行 |
| `ICBatchScheduler.run_full_cross_sectional` | 透传 `run_id` 给pipeline | +1行 |
| CLI entrypoint（需创建） | `run_pipeline.py` 接收 `--run-id` | 新文件~30行 |

**结论：PASS ✅** — 纯机械改动，无复杂逻辑，熟练开发者10~15分钟可完成。

> ⚠️ **WARN-01**: 方案中引用 `python run.py --run-id marine-s`，但当前 `src/pipeline/` 下无 `run.py` 或 `run_pipeline.py` 入口脚本。需创建CLI入口文件。

---

## 2️⃣ ALTER TABLE加run_id列影响分析

**结论：PASS ✅** — SQLite `ALTER TABLE ADD COLUMN` 安全无副作用：

| 维度 | 分析 | 影响 |
|:-----|:-----|:----:|
| 表文件重写 | ❌ 不会重写 | 无IO开销 |
| 索引重建 | ❌ 不会重建 | `idx_ic_uniq` 完好 |
| 现有行数据 | 全部填充 `NULL` | 旧数据 `run_id=NULL` 可区分 |
| NOT NULL约束 | ADD COLUMN不支持NOT NULL | 无需约束，业务上NULL=旧数据 |
| `INSERT OR IGNORE` 幂等性 | 不受影响 | UNIQUE约束不变，去重逻辑不变 |

**唯一索引不受影响**：`idx_ic_uniq` on `(trade_date, factor_name, source_version)` 不涉及run_id，加列不改索引定义。

---

## 3️⃣ 重跑时间评估与部分重跑可行性

### 全量重跑（~180分钟）

上次实际运行窗口（含2次OOM）：16:37~19:55 = **~198分钟**。
方案估计180分钟**合理**，因干净运行（无OOM中断）应略快于含OOM的窗口。

### 部分重跑选项

| 范围 | 覆盖年数 | 占比 | 预估耗时 | 是否满足验证目的 |
|:----|:--------:|:----:|:--------:|:----------------:|
| 2007-01 ~ 2026-05（全量） | ~19.5年 | 100% | ~180min | ✅ 完整验证 |
| 2021-01 ~ 2026-05（近5年） | ~5.5年 | ~28% | **~50min** | ⚠️ 满足run_id标记验证，但无法复现原始DB全量状态 |

**结论：PASS ✅** — 180分钟估计合理。部分重跑（近5年）可节省~70%时间，但需明确验证目的：
- 若仅验证run_id标记机制正确 → 部分重跑足够
- 若需完全复现原始DB状态用于后续分析 → 需全量重跑

---

## 4️⃣ OOM防护措施审查

### 现状代码能力

| 措施 | 代码中有无 | 生效时机 | 说明 |
|:-----|:---------:|:--------:|:-----|
| 启动内存检查 ≥4GB | ✅ | 运行开始时 | `_check_environment_health()` |
| MemorySnapshot记录 | ✅ | 每10个截面+首尾 | 仅记录，不干预 |
| gc.collect() | ✅ | 每yield后 | `run_batch_streaming`中被动释放 |
| 运行时内存≥4GB自动减速 | ❌ **未实现** | — | 方案中提到但代码无对应逻辑 |

### 缺口分析

**WARN-02: "自动减速"未实现** 🔴

方案中提到"使用psutil阈值告警，>4GB时自动减速"，但当前代码：
- `_check_environment_health()` 仅在管线启动时执行一次，运行时无持续监控
- 无自适应降速（reduce batch size / add sleep / throttle）逻辑
- MemorySnapshot是profiling工具，无干预能力

**风险**：若重跑时数据规模变化或内存压力增大，仍可能重复U2的OOM问题。

### 增强建议（不代修，仅供参考）

如需真正的运行时防护，至少需要：
1. 每截面后检查内存，超阈值时 `gc.collect()` + `time.sleep(N)`
2. 若连续N次超阈值，主动放弃当前进程并写日志

---

## 5️⃣ 遗漏风险评估

### ⚠️ WARN-03: 调度器自动重启逻辑假设

方案中提到：

> "mellow-o: 同上 --run-id mellow-o（调度器检测到失败后自动重启）"
> "scheduler重启时自动递增run_id"

**但 `ICBatchScheduler` 无进程监督/Watchdog能力** — OOM SIGKILL会杀死整个进程，调度器无法"检测到失败后自动重启"。这需要：

- **外部监督进程**（如 systemd, PM2, 或简单的wrapper脚本 `while true; do python run.py --start ... --run-id X; [ $? -eq 137 ] && break; done`）
- 或当前流程设计为手动重跑（方案中已有标注）

**实际影响**：方案执行路径中"自动重启+自动递增run_id"无法开箱即用。需要明确写为手动重跑流程：

```
# 手动流程
Step 3a: python run_pipeline.py --start 20070104 --end 20260526 --run-id marine-s   # 若OOM，继续
Step 3b: python run_pipeline.py --start 20070104 --end 20260526 --run-id mellow-o    # 手动重跑
Step 3c: python run_pipeline.py --start 20070104 --end 20260526 --run-id norun       # 完成剩余
```

### ⚠️ Schema.py未更新

`src/db/schema.py` 中的 `DDL_A50_CROSS_IC_RESULT` 未包含 `run_id` 列。若在测试/CI环境通过schema.py重建表，run_id列会丢失。建议同步更新schema.py。

### ⚠️ 备份步骤非强制

备份命令 `cp a50_ic.db a50_ic_20260530_backup.db` 在方案中为说说明性描述，不是执行路径中的必选步骤。建议改为强制前序步骤，避免操作失误。

### ✅ 其他检查项 — 未发现问题

| 检查项 | 结论 |
|:-------|:----:|
| 旧数据`run_id=NULL`的查询兼容性 | ✅ 正确，`WHERE run_id IS NOT NULL` 可准确筛选新数据 |
| `INSERT OR IGNORE`与旧数据去重 | ✅ 不受影响，UNIQUE约束不变 |
| 方案B2 vs B1的选择 | ✅ B2正确，run_id列比source_version侵入方案更清晰 |
| 数据总量核验（SELECT GROUP BY run_id） | ✅ 方案中已有SQL模板 |

---

## 摘要

| 审查项 | 结论 | 说明 |
|:-------|:----:|:-----|
| 1. 代码改动量 | **PASS** | ~15分钟，机械改动 |
| 2. ALTER TABLE影响 | **PASS** | 安全无副作用 |
| 3. 重跑时间 | **PASS** | 180分钟合理，部分重跑~50分钟可选 |
| 4. OOM防护 | **WARN** | 运行时自动减速未实现，健康检查仅启动时触发 |
| 5. 遗漏风险 | **WARN** | ①无run_pipeline.py入口脚本 ②调度器无自动重启能力 ③schema.py未更新 ④备份非强制 |

### 最终结论

**PASS** — 方案B2可行，改造方向正确，改动量小，精确度高。

**但需注意3项WARN（非阻塞，建议执行前修复）**：
- **WARN-01**: 创建CLI入口脚本 `run_pipeline.py`（代替假设的 `run.py`）
- **WARN-02**: 运行时OOM防护（自动减速）未实现，建议至少加截面级内存检查
- **WARN-03**: 明确重跑流程为手动而非自动重启

---

*审查人：墨萱 | 2026-05-31 10:08 CST*
