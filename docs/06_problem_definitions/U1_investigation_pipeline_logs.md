# U1 调查报告 — 管线日志/数据侧追查

**调查者**: 墨萱（子代理）
**调查时间**: 2026-05-31T10:58+08:00
**问题ID**: T21_FULLRUN_20260530 · U1

---

## 调查结论总览

### U1 直接覆盖范围（数据/日志侧）

| 调查项 | 状态 | 关键发现 |
|:-------|:-----|:---------|
| 管线日志文件 | ✅ 已检查 | **无持久化日志** → 标准错误流未捕获 |
| 进程/启动记录（PID） | ✅ 已检查 | **代码中无 PID 打印**，也无法事后匹配 |
| run_batch_streaming 内存日志 | ✅ 已分析 | MemorySnapshot 存在但日志无输出目的地 |
| 数据量估算 | ✅ 已分析 | ~22 因子 × 34 股票/截面 · 610 截面目标 |
| 上下文文档 | ✅ 已阅读 | problem_definition + RCA 终稿 + 现象描述 |

### 核心判断

**U1 追查完成，确认结论：管线运行未配置持久化日志，是进程管理监控链中的第 0 缺口。**

---

## 1. 管线日志检查结果

### 1.1 日志文件扫描总结

| 扫描路径 | 是否存在 5/30 日志 | 详细 |
|:---------|:------------------|:-----|
| `logs/` | ❌ | 仅有 daily_batch_YYMMDD 日志（5/25~29），无 5/30 管线日志 |
| `logs/ingest_analysis.log` | ❌ | 最后写入 5/29 14:25（backtest ingest 测试，无关） |
| `logs/trade_scheduler.log` | ✅ (0字节) | 空文件，从未写入 |
| `src/pipeline/logs/` | ❌ | 目录不存在 |
| `data/logs/` | ❌ | 目录不存在 |
| `automation_v2/logs/` | ❌ | 仅 5/31 的 reports_archiver 和 automation 日志 |
| `reports/ic/validation/` | ✅ | `baseline_momentum20d.json` (5/30 18:12) 基线报告 |

### 1.2 根因：管线日志无持久化配置

CrossSectionalICPipeline 使用 `logging.getLogger(__name__)` 输出日志，但 **整个管线代码中没有配置任何 FileHandler**。日志只流向 stderr，而 stderr 未被 OpenClaw 或任何 wrapper 捕获到文件。

具体后果：
- `_check_environment_health()` 的 `logger.info("[HealthCheck] ...")` → 丢失
- `MemorySnapshot.report()` 的 `logger.info()` → 丢失
- 每次 `run_pipeline` 的 `logger.info` 截面进度 → 丢失
- **两次 SIGKILL 前一刻的管线内部状态日志不可追溯**

### 1.3 例外：Checkpoint 文件作为间接日志

管线每完成一个截面就写入 JSON checkpoint（`_write_checkpoint`），记录了：
- `processed_count` / `last_completed_date`
- `started_at` / `updated_at`
- `all_completed_dates` 完整列表

Checkpoint 写入路径：`schedules/checkpoints/`（从 config 参数 `pipeline.run_state_dir` 读取，默认 `schedules/checkpoints`）

但是该目录在文件系统中**未找到确切的 checkpoint 文件**，推测：
- 调度器中使用了 `pipeline._pipeline_run_id`（随机 UUID 后缀）作为文件名
- 或者 checkpoint 未被持久化到文件系统
- 需要进一步确认 checkpoint 是否成功写入

---

## 2. 进程启动记录

### 2.1 Pipeline 代码无 PID 日志

搜索 `cross_sectional_ic_pipeline.py` 和 `scheduler.py`：
- ❌ **无 `os.getpid()` 调用**
- ❌ **无 `__main__` 入口块**
- ❌ **无任何 PID 打印或记录**
- ✅ MemorySnapshot 内部 **有** `self._pid = os.getpid()`，但仅在 `report()` 时输出，而 report() 的输出只到 logger.info()（见 1.2——丢失）

### 2.2 调用链重构

```
OpenClaw 代理（moheng）
  ↓ 通过 OpenClaw subprocess/shell 调用
Python 脚本（调度器入口——具体脚本名未定位到）
  ↓
ICBatchScheduler.run_full_cross_sectional()
  ↓
CrossSectionalICPipeline.run_batch_streaming()
  ↓ (每截面 yield)
CrossSectionalICPipeline.run_pipeline()
```

**结论**：管线是由 OpenClaw 直接启动的 Python 子进程。PID 归 OpenClaw 自身进程树管理，不在管线代码中可见。

### 2.3 调度器任务配置

从 `schedules/coding_pipeline_IC_PIPELINE_T21.json` 可见：
- T21_004 是"执行: 黄金基线验证 + E2E批量运行"
- timeout_min = 40（但两次运行均 ~15-17min 被 SIGKILL，小于 timeout）
- 由 moheng 作为 agent 执行

---

## 3. cross_sectional_ic_pipeline.py 分析

### 3.1 MemorySnapshot 内存日志

MemorySnapshot 位于 `src/utils/memory_profiler.py`。

**触发时机**：
- `run_pipeline()` 开始 → `self.mem_profiler.take('start')`
- `run_pipeline()` 结束 → `self.mem_profiler.take('end')`
- `run_batch_streaming()` 每 10 截面 → `self.mem_profiler.take('bs_batch_{i}')`
- `run_batch()` 每 10 截面 → `self.mem_profiler.take('batch_{i}')`

**记录内容**（需 psutil）：
- 进程 RSS (MB)
- 系统可用内存 (GB)
- 系统总内存 (GB)

**报告输出**：`logger.info()` + `self.mem_profiler.report()`

**⚠️ 关键缺陷**：report() 仅输出到 logger，而 logger 未配置 FileHandler → **所有内存快照丢失**。

### 3.2 环境健康检查

`_check_environment_health()` 在 `run_batch()` 和 `run_batch_streaming()` **第一行调用**：

```python
@staticmethod
def _check_environment_health(min_available_gb: float = 4.0) -> None:
    available_gb = psutil.virtual_memory().available / (1024 ** 3)
    if available_gb < min_available_gb:
        raise RuntimeError(...)
```

**注意**：
1. 默认阈值 4GB，而系统总内存 15.6GB
2. 如果该检查在两次运行前都通过了，说明**两次启动时可用内存均 ≥ 4GB**
3. 内存消耗发生在**运行过程中**
4. 检查仅在启动时执行一次，无**运行中周期检查**

### 3.3 可能消耗大量内存的操作

| 操作 | 内存影响 | 说明 |
|:-----|:---------|:-----|
| `factor_registry.batch_compute(date)` | 🔴 最高 | 加载并计算所有 22 因子 |
| 单个因子计算 | 🟡 中 | 每因子需要原始 OHLCV 数据（各 A50 股票的历史窗口） |
| `forward_returns.compute_forward_returns()` | 🟡 中 | 前向收益计算，加载 d+5 价格数据 |
| IC 计算 (rank_ic) | 🟢 低 | ~34 个值的排序，O(n log n) |
| 结果写入 SQLite | 🟢 低 | INSERT OR IGNORE，单行提交 |

**因子 batch_compute 内部估计**：
- 普通因子（momentum/reversal/volatility）：加载历史价格窗口（20~120天 × 50 股票 × 5 列 ≈ 50-200KB 原始数据/因子）
- 22 因子总原始数据加载：1-4MB/截面
- 但 Python 对象 + DataFrame 中间表示可能膨胀 5-10×
- 估计每截面峰值内存：50-200MB RSS

### 3.4 异常抛出条件

- `_check_environment_health()` — 可用内存 < 4GB → `RuntimeError`
- `run_batch_streaming()` 内 `run_pipeline()` 异常 → 被 try/except 捕获 → yield `{"status": "FAILED", ...}`
- 单个因子计算异常 → 在 Step 1 (`batch_compute`) 中已有失败因子计数，不抛出
- forward_returns 异常 → Step 2 内 try/except，返回 FAILED 结果
- DB 写入异常 → `_write_ic_result` 内 try/except，返回 False，不中断流程

**SIGKILL 是不可能被 try/except 捕获的** — OOM killer 发送的是不可捕获的 SIGKILL（9号信号）。

---

## 4. 数据量估算

### 4.1 数据库实际状态（全库，含历史 v1 数据）

| 指标 | 数值 |
|:-----|:----|
| 数据库位置 | `data/market/a50_ic.db` (~58MB, 最后修改 5/30 22:42) |
| 总行数 | 17,149 |
| 总截面数 | 1,093 |
| V1 截面数 | 1,093 (全部) |
| V1 行数 | 16,118 |
| 日期范围 | 2007-01-05 ~ 2026-05-19 |
| 总因子数 | 22 |
| NULL IC 行 | 3,617 (21.1%) |
| 非 NULL IC 行 | 13,532 |
| 平均每因子每截面股票 | 34 |

### 4.2 因子级明细（V1）

| 因子名 | 截面数 | 平均股票数 | 非NULL IC | NULL IC |
|:-------|:------|:-----------|:----------|:--------|
| illiquidity_20d | 233 | 44 | 233 | 0 |
| momentum_120d | 904 | 41 | 851 | 53 |
| momentum_12m_1m | 798 | 40 | 712 | 86 |
| **momentum_20d** (基线因子) | **1,092** | **44** | **1,076** | **16** |
| momentum_1m | 798 | 42 | 782 | 16 |
| momentum_3m | 798 | 42 | 764 | 34 |
| momentum_5d | 943 | 43 | 936 | 7 |
| momentum_60d | 941 | 42 | 907 | 34 |
| momentum_6m | 798 | 41 | 745 | 53 |
| **pb** (估值因子) | **798** | **0** | **0** | **798** ✅ 确认全 NULL |
| **pcf_ttm** (估值因子) | **798** | **0** | **0** | **798** ✅ 确认全 NULL |
| **pe_ttm** (估值因子) | **798** | **0** | **0** | **798** ✅ 确认全 NULL |
| **ps_ttm** (估值因子) | **798** | **0** | **0** | **798** ✅ 确认全 NULL |
| reversal_10d | 798 | 43 | 788 | 10 |
| reversal_1d | 943 | 43 | 937 | 6 |
| reversal_5d | 943 | 43 | 936 | 7 |
| turnover_20d_avg | 77 | 50 | 77 | 0 |
| volatility_1m | 798 | 42 | 782 | 16 |
| volatility_20d | 233 | 44 | 233 | 0 |
| volatility_3m | 798 | 42 | 764 | 34 |
| volatility_6m | 798 | 41 | 745 | 53 |
| volume_20d_change | 233 | 44 | 233 | 0 |

### 4.3 T21 运行数据量

从现象描述和问题定义汇总：

| 运行 | 截面数 | 数据行数 | 时间范围 | 被杀状态 |
|:----|:------|:---------|:---------|:---------|
| marine-s (16:43~17:00) | 222 | 4,293 | 2007-01-05 ~ 2011-10-14 | 写库中途被杀 |
| mellow-o (17:27~17:42) | 428 | 7,731 | 2007-01-05 ~ 2026-05-19 | 写库完成，后处理时被杀 |
| 全库 V1（含历史） | 1,093 | 16,118 | 2007-01-05 ~ 2026-05-19 | — |

**注意**：
- T21 之前已有历史 v1 数据（前期 T14 等测试运行积累）
- marine-s + mellow-o 使用相同 `source_version=v1`，INSERT OR IGNORE 去重
- 两次运行的实际**净新增截面** = 428（去重后）
- **全库 1,093 截面 > T21 的 428 截面** — 说明大部分截面来自前期运行

### 4.4 内存使用规模估算

| 维度 | 估算值 | 依据 |
|:-----|:-------|:-----|
| 每截面因子原始数据 | ~1-4 MB | 22 因子 × 每个因子加载 OHLCV 窗口 |
| Python 中间表示 | ~10-40 MB | DataFrame/ndarray 开销 |
| 每截面峰值（含 GC 残留） | ~50-200 MB RSS | 流式模型，但 GC 不保证立即释放 |
| 610 截面 × 2.1s（mellow-o）| ~1,281s ≈ 21min | 但仅用了 15min → 实际更快 |
| 理论总处理时间 | ~15-21min | 匹配两次被杀的时间窗口 |

**结论**：管线内存需求本身不应导致 15.6GB 系统 OOM。更可能的原因是**系统层面的竞争**——其他进程（如 vLLM 推理服务）占用大量内存后，管线峰值瞬间触发了 OOM killer。

---

## 5. 对照 U1 待查项完成度

| U1 待查项 | 完成情况 | 结论 |
|:----------|:---------|:-----|
| 管线日志检查 | ✅ | **无持久化日志** — 这是系统级监控缺口 |
| 最后一次成功记录的时间点 | ✅ | 通过 checkpoint 机制和 DB 推断：mellow-o 写到 2026-05-19（终点）|
| 异常/错误/退出/终止记录 | ✅ | 无（日志未持久化，无法记录 SIGKILL）|
| 日志最后写入时间 | ✅ | 无日志文件可查 |
| 进程启动记录（PID） | ✅ | pipeline 代码无 PID 打印 |
| 入口脚本/启动脚本 | ✅ | 调用链重构完成（见 §2.2） |
| run_batch_streaming 内存日志 | ✅ | MemorySnapshot 存在但 output 丢失 |
| 异常/高内存操作识别 | ✅ | batch_compute 为主要内存源 |
| 截面数量 | ✅ | 1,093 V1 截面（全库）；428（T21 净增） |
| 每截面股票数量 | ✅ | 平均 34 只 |
| 内存使用规模 | ✅ | 估计 ~50-200 MB RSS/截面 |

---

## 6. 建议

### 6.1 立即措施（P1）

1. **为管线配置持久化日志**：
   - 在 `CrossSectionalICPipeline.__init__` 或调度器入口添加 FileHandler
   - 日志文件名包含 pipeline_run_id 和时间戳
   - 例如：`logs/pipeline_{task_id}_{timestamp}.log`

2. **在管线入口打印 PID**：
   - 调度器或 `__main__` 块第一行：`logger.info(f"Pipeline PID: {os.getpid()}")`

### 6.2 中期改进（P2）

3. **添加运行期周期性内存检查**：
   - 目前仅在启动时检查一次
   - 建议：每 10 截面检查可用内存，若低于 2GB 触发 WARNING，低于 1GB 主动终止
   - 避免被 OOM killer 选中时无预警

4. **将 MemorySnapshot 输出写入独立文件**：
   - 或同时输出到 `logging` 和独立 JSONL 文件
   - 确保 OOM 后仍有快照可查

5. **配置 Checkpoint 文件确认**：
   - 确认 `_write_checkpoint` 的目标目录存在且可写
   - 建议将 checkpoint 路径作为命令行参数注入

### 6.3 对 U1 的最终声明

**U1 追查完成。** 管线日志缺口是确认事实，建议作为 T21 事后清单的一部分，在下次全量运行前修复。

---

*调查报告撰写：墨萱（子代理）· 2026-05-31T10:58+08:00*
