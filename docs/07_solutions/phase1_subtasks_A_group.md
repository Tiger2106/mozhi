---
author: 墨衡
created_time: 2026-05-31T13:23+08:00
status: READY
version: v1.1
---

# Phase 1 — A组内存防御子任务拆解

## 基准：已有 T21_FIX 三层防御（均已实现）

| Layer | 文件位置 | 关键方法 | Coder | 验收状态 |
|:-----:|:---------|:---------|:-----:|:--------:|
| Layer1 (拒启) | `src/pipeline/cross_sectional_ic_pipeline.py` | `_check_environment_health()` — psutil 可用内存 < 4GB 抛 RuntimeError | 墨衡 | ✅ 已实现 |
| Layer2 (流式) | `src/pipeline/cross_sectional_ic_pipeline.py` | `run_batch_streaming()` — yield + gc.collect() + `_generate_schedule_iter` 生成器 | 墨衡 | ✅ 已实现 |
| Layer3 (恢复) | `src/pipeline/cross_sectional_ic_pipeline.py` | `_write_checkpoint()` / `_read_checkpoint()` / `_clear_checkpoint()` — 每截面写入 + resume | 墨衡 | ✅ 已实现 |

**附加实现**：
- 配套内存快照工具：`src/utils/memory_profiler.py` — `MemorySnapshot` 类，记录进程 RSS + 系统内存
- 流式聚合器：`src/pipeline/scheduler.py` 的 `ICBatchScheduler._compute_streaming_summary()` — 使用 **真实的 Welford 在线算法** 对 IC 值的均值和 M2 做流式聚合（**注：这是聚合层用 Welford，IC 计算本身仍用 np.corrcoef/spearmanr**）

---

## 总览：Phase 1 = A-0 ~ A-4（12 个子任务）

```
A-0 (验证已有层)        A-1 (运行时监控)         A-2 (预算匹配)        A-3 (集成测试)       A-4 (文档修正)
  ├─ A-0a [P0]           ├─ A-1a [P0]            ├─ A-2a [P1]           ├─ A-3a [P1]          └─ A-4a [P2]
  ├─ A-0b [P0]           ├─ A-1b [P0]            └─ A-2b [P1]           └─ A-3b [P1]              └─ A-4b [P2]
  └─ A-0c [P0]           └─ A-1c [P0]                                                       

依赖链：
  A-0a → A-0b → A-0c                                    (串行，逐步验证)
  A-1a → A-1b → A-1c                                    (串行，编码)
  A-2a → A-2b                                            (串行，编码)
  A-3a → A-3b                                            (串行，编码)
  A-0(全) + A-1(全) + A-2(全) → A-3a                     (集成合并点)
  A-4a / A-4b 独立（任何时候可执行）
```

**推荐执行顺序**：
```
A-0a → A-0b → A-0c → A-1a → A-1b → A-1c → A-2a → A-2b → A-3a → A-3b → A-4a → A-4b
```

---

## A-0: 验证已有 T21_FIX 三层防御（Pre-work，仅验证不编码）

> ⚠️ **前提条件**：当前三层防御在正常运行中不会被触发（Layer1 阈值 4GB > 系统常态 ~1.5GB，本机必然拒启）。墨衡代码审查确认实现正确，需墨萱独立验证。

---

### A-0a — 验证 Layer 1：环境健康检查（psutil 拒启）

- **文件**：`src/pipeline/cross_sectional_ic_pipeline.py`
- **核心定位**：
  - 方法 `_check_environment_health(min_available_gb=4.0)`
  - 被 `run_batch()` (line ~640) 和 `run_batch_streaming()` 在入口第一行调用
- **墨萱复核要点**：
  1. ✅ 两个批量入口均有调用
  2. ✅ 硬编码 4.0 为默认值，可被 `config` 覆盖
  3. ✅ 低于阈值抛 `RuntimeError` 而非静默返回
  4. ✅ psutil 未安装时同样抛 `RuntimeError`
- **验收标准**：
  ```
  with unittest.mock.patch('psutil.virtual_memory') as mock_vm:
      mock_vm.return_value.available = 3.0 * (1024**3)
      CrossSectionalICPipeline._check_environment_health(4.0)
      # → RuntimeError: "Insufficient memory: 3.00 GB available, need at least 4.00 GB"
  ```
- **代码参照线**：run_batch 约 line 640, run_batch_streaming 约 line 730, `_check_environment_health` 约 line 500
- **预估时间**：5 分钟（验证，不编码）


### A-0b — 验证 Layer 2：流式生成器

- **文件**：`src/pipeline/cross_sectional_ic_pipeline.py`
- **核心定位**：
  - `run_batch_streaming()` 返回类型为 `Iterator[dict]`（含 `yield` 关键字）
  - 每次 `yield` 后调用 `gc.collect()`
  - 不构建 `all_ic_records` / 全量累积列表
  - `_generate_schedule_iter()` 是生成器 (`Iterator[str]`)，非预创建整个日期列表
- **墨萱复核要点**：
  1. ✅ `run_batch_streaming` 含有 `yield` 关键字
  2. ✅ `gc.collect()` 在每次 yield 后调用（确认位置在 yield 之后）
  3. ✅ 区别于 `run_batch()` — `run_batch` 使用 `results.append()` + `all_ic_records.append()`
  4. ✅ `_generate_schedule_iter` 使用 `yield` 生成日期，与 `_generate_schedule`（返回 `List[str]`）并存
- **验收标准**：
  ```python
  results = list(pipeline.run_batch_streaming(...))
  # 流式返回的全部数据应等价于 run_batch 的全量结果（功能对等）
  # 通过 MemorySnapshot 验证峰值内存显著低于 run_batch（长周期运行时）
  ```
- **代码参照线**：`run_batch_streaming` (line 722), `_generate_schedule_iter` (line 1023)
- **预估时间**：5 分钟（验证，不编码）


### A-0c — 验证 Layer 3：Checkpoint / Resume

- **文件**：`src/pipeline/cross_sectional_ic_pipeline.py`
- **核心定位**：
  - `_write_checkpoint()` — 每完成一个截面写入 JSON
  - `_read_checkpoint()` — 读取后跳过 `all_completed_dates`
  - `_clear_checkpoint()` — 标记 status=completed 而非删除
  - resume 场景：`completed_set` 正确过滤
- **墨萱复核要点**：
  1. ✅ checkpoint JSON 包含 `pipeline_id` / `processed_count` / `last_completed_date` / `all_completed_dates` / `started_at` / `updated_at`
  2. ✅ `_read_checkpoint` 忽略 `status != "in_progress"` 的文件（包括 completed）
  3. ✅ resume 后剩余日期 = 全部日期 - completed_set
  4. ✅ `clear_checkpoint` 不删除文件，改为标记 completed（可审计）
- **验收标准**：
  ```python
  # 模拟中断
  pipe1 = CrossSectionalICPipeline(...)
  results1 = list(pipe1.run_batch_streaming(start, end, resume_from=None))
  # 中断后在中间某点停止（如上一步已完成 N 个）
  
  pipe2 = CrossSectionalICPipeline(...)
  results2 = list(pipe2.run_batch_streaming(start, end, resume_from=pipe1._pipeline_run_id))
  # results1 + results2 应等价于全量运行，无重复无遗漏
  ```
- **代码参照线**：`_write_checkpoint` (line ~280), `_read_checkpoint` (line ~340), `_clear_checkpoint` (line ~390), resume 逻辑 (line ~770-790)
- **预估时间**：5 分钟（验证，不编码）


---

## A-1: 运行时自适应内存监控（新防御层 Layer 4）

在已有 Layer 1（拒启 4GB 阈值）基础上，增加**运行中**的逐截面内存水位监控。

**设计原则**：与 Layer 1 互补，Layer 1 负责运行前过滤，Layer 4 负责运行中监控。

### A-1a — 在 memory_profiler.py 新增 MemoryMonitor 类

- **文件**：`src/utils/memory_profiler.py`
- **改动量**：新增约 100 行（不修改已有 `MemorySnapshot`）
- **核心接口**：
  ```python
  class MemoryMonitor:
      """运行中自适应内存监控器。
      
      后台线程每秒检查一次可用内存，低于阈值触发回调。
      
      基于系统常态内存（~1.5GB 可用）和已有 Layer1（4GB 拒启）设计：
        GREEN  > 2.0 GB — 正常（不触发）
        YELLOW  1.5~2.0 GB — 告警（logging.warning），不阻塞
        RED     1.0~1.5 GB — 降级（调用 degrade_callback）
        CRIT   < 1.0 GB — 紧急终止（抛 RuntimeError）
      
      Thread-safe：内部用 threading.Lock 保护状态变量。
      """
      def __init__(self, 
                   check_interval: float = 1.0,
                   yellow_gb: float = 2.0,
                   red_gb: float = 1.5,
                   critical_gb: float = 1.0,
                   degrade_callback: Optional[Callable] = None):
          ...
      
      def start(self) -> None          # 启动后台线程
      def stop(self) -> None           # 停止后台线程
      def check_once(self) -> str      # 单次同步检查，返回 'GREEN'|'YELLOW'|'RED'|'CRIT'|'UNKNOWN'
      @property
      def current_level(self) -> str   # 最近一次检查的级别
      @property
      def last_check_gb(self) -> float # 最近一次可用内存(GB)
  ```
- **墨萱复核要点**：
  1. ✅ psutil 未安装时 `start()` 不抛异常，仅 `logging.warning`，`current_level` 返回 `"UNKNOWN"`
  2. ✅ 后台线程是 daemon 线程，不会阻止进程退出
  3. ✅ check_once 内部使用 `threading.Lock`，多线程安全
  4. ✅ RED/CRIT 阈值的默认值符合系统常态分析（~1.5GB 可用）
- **验收标准**：
  ```python
  monitor = MemoryMonitor()
  # 未 start 时 check_once 可正常工作（同步模式）
  level = monitor.check_once()  # 返回实际级别
  assert level in ('GREEN','YELLOW','RED','CRIT','UNKNOWN')
  
  # 后台模式
  monitor.start()
  import time; time.sleep(2)
  assert monitor.current_level is not None
  monitor.stop()
  ```
- **依赖**：无（新增类，不修改现有代码）
- **预估时间**：12 分钟


### A-1b — 定义降级行为与回调函数

- **文件**：`src/utils/memory_profiler.py`（追加到 `MemoryMonitor` 下方）
- **改动量**：新增约 35 行
- **核心内容**：
  ```python
  # 降级策略枚举
  # RED 级别依次尝试：(1) force_gc → (2) step 降级
  # CRIT 级别：立即中止

  def default_degrade_callback(level: str, config: dict) -> str:
      """
      默认降级回调。
      
      YELLOW: logging.warning 仅告警
      RED:    从 config 中降低 step 频率，触发 gc.collect()
      CRIT:   抛 RuntimeError
      
      Returns: action_taken 描述字符串
      """
      ...
  ```
- **墨萱复核要点**：
  1. ✅ YELLOW（1.5~2.0GB）仅 `logging.warning`，不阻塞管线
  2. ✅ RED（1.0~1.5GB）降级 step：`1W` → `2W`（减半处理量），强制 `gc.collect()` 两次
  3. ✅ CRIT（<1.0GB）抛 `RuntimeError("CRITICAL: available memory < 1GB")`
  4. ✅ 回调函数签名允许外部替换（`degrade_callback` 参数注入）
- **验收标准**：
  ```python
  config = {"pipeline.step": "1W"}
  result = default_degrade_callback("RED", config)
  assert config["pipeline.step"] == "2W"
  assert "降级" in result
  ```
- **依赖**：A-1a（回调不需要，但 A-1c 集成时需要）
- **预估时间**：10 分钟


### A-1c — 集成 MemoryMonitor 到管线入口

- **文件**：`src/pipeline/cross_sectional_ic_pipeline.py`
- **改动量**：修改约 15 行（`run_batch_streaming` 入口 + 循环内）
- **具体改动**：

  1. **在 `__init__` 增加属性**：
     ```python
     self.memory_monitor: Optional[MemoryMonitor] = None
     ```
  
  2. **在 `run_batch_streaming` 的 `_check_environment_health()` 之后**：
     ```python
     # ── 1. 启动运行时内存监控 ─────────────────
     self.memory_monitor = MemoryMonitor(
         degrade_callback=lambda level: default_degrade_callback(
             level, self._config
         )
     )
     self.memory_monitor.start()
     ```

  3. **在每个截面 yield 前**：
     ```python
     # ── 运行时内存检查 ──
     level = self.memory_monitor.check_once()
     if level == 'RED':
         # 触发降级回调
         action = default_degrade_callback(level, self._config)
         logger.warning("[MemoryMonitor] RED: %s", action)
     elif level == 'CRIT':
         # 写 checkpoint 后终止
         self._write_checkpoint(...)
         self.memory_monitor.stop()
         raise RuntimeError("CRITICAL: available memory < 1GB, pipeline aborted")
     ```

  4. **在 `run_batch_streaming` 的 `finally` 块中**：
     ```python
     finally:
         if self.memory_monitor:
             self.memory_monitor.stop()
     ```

- **墨萱复核要点**：
  1. ✅ `run_batch_streaming` 入口启动 MemoryMonitor，退出时停止
  2. ✅ CRIT 级别时写入 checkpoint 后再抛出异常（有序终止）
  3. ✅ RED 级别不影响已通过的计算结果
  4. ✅ 不影响现有 T21_FIX 三层防御的正常工作
  5. ✅ `run_batch()`（非流式版本）独立，无需集成 MemoryMonitor
- **验收标准**：
  - 正常运行时管线不中断
  - Mock 内存为 CRIT 时管线在下一个截面前写入 checkpoint 后终止
- **依赖**：A-1a, A-1b
- **预估时间**：15 分钟


---

## A-2: 内存预算匹配检测（新防御层 Layer 5）

在运行前预算当前可用内存能支持多大处理量，提前降级 step 频率。

### A-2a — 实现 batch_size 预算估算器

- **文件**：`src/utils/memory_profiler.py`（追加在 `default_degrade_callback` 之后）
- **改动量**：新增约 60 行
- **核心函数**：
  ```python
  def estimate_safe_batch_size(
      available_gb: float,
      n_factors: int = 15,
      n_stocks: int = 50,
      bytes_per_element: float = 8.0,     # float64 每元素 8 字节
      overhead_ratio: float = 3.0,        # pandas/numpy 额外开销
      reserve_gb: float = 0.5,            # 保留给系统和其他进程
  ) -> int:
      """
      估算安全可处理的截面数量。
      
      每截面内存 = n_factors * n_stocks * bytes_per_element * overhead_ratio
      安全数量 = floor((available_gb - reserve_gb) / per_section_gb)
      
      Returns: 建议的 max_concurrent_sections（至少 0）
      """
      ...

  def estimate_safe_step(
      available_gb: float,
      n_factors: int = 15,
      n_stocks: int = 50,
      original_step: str = "1W",
  ) -> str:
      """
      根据内存预算估算安全的步长。
      
        预算充足 (≥5 sections) → 保持 original_step
        有限     (2~4 sections) → "2W"
        极低     (0~1 sections) → "1M"
      """
      ...
  ```
- **墨萱复核要点**：
  1. ✅ `n_factors=15, n_stocks=50` 为保守默认值（A50 → 最多 50 只成分股）
  2. ✅ `reserve_gb=0.5` 保留缓冲，防止一次性把内存吃光
  3. ✅ `available_gb <= reserve_gb` 时返回 0（完全无能力）
  4. ✅ 内存估算上限 100 个截面（防止整数溢出）
- **验收标准**：
  ```python
  # 充足预算 → 保持步长
  s1 = estimate_safe_step(8.0, 15, 50, "1W")
  assert s1 == "1W"
  
  # 有限预算 → 降级 2W
  s2 = estimate_safe_step(1.0, 15, 50, "1W")
  assert s2 in ("2W", "1M")
  
  # 极低预算 → 降级 1M
  s3 = estimate_safe_step(0.4, 15, 50, "1W")
  assert s3 == "1M"
  ```
- **依赖**：无
- **预估时间**：10 分钟


### A-2b — 集成预算检查到管线预检

- **文件**：`src/pipeline/cross_sectional_ic_pipeline.py`
- **改动量**：修改 `run_batch_streaming` 中 `_check_environment_health()` 后的约 5 行
- **集成位置**：
  ```python
  # ── 0. 预运行健康检查 ───────────────────────
  self._check_environment_health()
  
  # ── 0.5 内存预算匹配 ────────────────────────
  import psutil
  if "@memory" not in locals():  # 首次检查
      available_gb = psutil.virtual_memory().available / (1024 ** 3)
      n_factors = self.factor_registry.count()
      n_stocks = self._get_universe_count(date_std_start)
      safe_step = estimate_safe_step(available_gb, n_factors, n_stocks, step)
      if safe_step != step:
          logger.warning(
              "[BudgetCheck] Memory budget insufficient for step=%s. "
              "Downgrading to %s (avail=%.2f GB, factors=%d, stocks=%d)",
              step, safe_step, available_gb, n_factors, n_stocks,
          )
          step = safe_step
  ```
- **墨萱复核要点**：
  1. ✅ 可用内存充足时步长不变
  2. ✅ 降级有清晰日志，包含 avail/factors/stocks 信息
  3. ✅ 不修改 `run_batch()`（非流式版本，保留原样）
  4. ✅ 预算检查在 `_check_environment_health` 之后，不干扰已有 Layer1
- **验收标准**：
  - Mock 低内存环境下 `run_batch_streaming` 的 step 参数自动降级
- **依赖**：A-2a
- **预估时间**：8 分钟


---

## A-3: 集成测试（验证所有防御层的联动）

### A-3a — 创建 test_memory_defense.py 核心测试

- **文件**：`src/pipeline/tests/test_memory_defense.py`（新建）
- **测试框架**：pytest
- **代码量**：约 120 行
- **Mock 工具类**：
  ```python
  class MockVirtualMemory:
      """可动态修改的 psutil.virtual_memory() mock。"""
      def __init__(self, initial_avail_gb: float = 8.0):
          self._avail_bytes = initial_avail_gb * (1024 ** 3)
          self.total = 16 * (1024 ** 3)  # 固定 16GB
      
      @property
      def available(self):
          return self._avail_bytes
      
      def reduce_to(self, gb: float):
          self._avail_bytes = gb * (1024 ** 3)
  ```
- **核心测试用例**：

  | ID | 场景 | Mock 条件 | 期望结果 |
  |:--:|:-----|:----------|:---------|
  | **T1** | 正常启动 | avail=8GB | Layer1 PASS, run_batch_streaming 正常迭代 |
  | **T2** | Layer1 拒启 | avail=3GB | `_check_environment_health(4.0)` 抛 RuntimeError |
  | **T3** | 运行中 RED | avail=8GB → 第 2 次迭代后降至 1.2GB | MemoryMonitor 触发 RED，step 降级（若在 streaming 中） |
  | **T4** | 运行中 CRIT | avail=8GB → 第 3 次迭代后降至 0.8GB | 抛 RuntimeError，checkpoint 正确写入 last_completed_date |
  | **T5** | 预算不足降级 | avail=2GB, factors=15, stocks=50 | `estimate_safe_step` 返回非 "1W"，日志含降级信息 |
  | **T6** | checkpoint resume | 模拟 T4 中断 + 用相同的 pipeline_id resume | 跳过已完成的日期，剩余日期正常运行 |

- **墨萱复核要点**：
  1. ✅ T1-T6 各自独立可运行
  2. ✅ T6 测试后清理 checkpoint 文件，不影响后续测试
  3. ✅ mock.patch 使用 `autospec=True` 确保签名匹配
  4. ✅ 测试不依赖真实数据库（mock 管线内部依赖）
- **预估时间**：15 分钟


### A-3b — 完善测试覆盖（边界场景）

- **文件**：`src/pipeline/tests/test_memory_defense.py`（追加）
- **代码量**：追加约 100 行
- **额外测试用例**：

  | ID | 场景 | Mock 条件 | 期望结果 |
  |:--:|:-----|:----------|:---------|
  | **T7** | psutil 未安装 | mock ImportError | Layer1 抛 RuntimeError, MemoryMonitor 不抛异常但标记 UNKNOWN |
  | **T8** | MemoryMonitor 性能基准 | 循环 100 次 check_once | 单次检查 < 5ms（基线记录） |
  | **T9** | 预算边界 = 0 | avail=0.3GB, factors=15, stocks=50 | `estimate_safe_batch_size` 返回 0 |
  | **T10** | 降级后恢复 | RED → 手动释放内存 → GREEN | degrade_callback 恢复正常（step 还原到原始值） |
  | **T11** | multi-factor 场景验证 | avail=1.8GB, 15 factors, n_stocks 不同值 | n_stocks 增长时 estimate_safe_step 正确降级 |
  | **T12** | checkpoint 幂等 | 同一日期写 2 次 checkpoint | 文件内容一致，无字段冲突 |

- **墨萱复核要点**：
  1. ✅ T7 验证 psutil 缺失场景下各组件行为（Layer1 正常抛异常，Monitor 不崩溃）
  2. ✅ T8 记录性能基线供后续比较
  3. ✅ T10 验证降级后的恢复路径（虽然当前没有自动恢复，但回调接口预留了可能性）
- **依赖**：A-3a
- **预估时间**：12 分钟


---

## A-4: 文档修正

### A-4a — 修正 Welford 在线算法的夸大描述（文档篇）

- **根因**：多份文档描述 Layer 2 使用 "Welford 在线算法实现 streaming IC 计算"，但实际上 IC 计算 = `np.corrcoef` / `scipy.stats.spearmanr`（批量计算）。真正的 Welford 算法存在于 `scheduler.py` 中的 IC 统计量**聚合**层（均值/方差流式更新），而非 IC 计算本身。
- **需修正的文件**：

  | # | 文件路径 | 问题定位 | 修正方向 |
  |:-:|:---------|:---------|:---------|
  | 1 | `docs/06_problem_definitions/U1_investigation_deepexec.md:742` | "使用 Welford 在线算法" | 明确：流式生成器+标准计算，Welford 仅用于聚合 |
  | 2 | `src/pipeline/scheduler.py:440` | docstring "使用 Welford 在线算法计算均值/标准差" | **保留**（此处 Welford 真实存在），但注明"聚合阶段 Welford"，与计算阶段区隔 |
  | 3 | `src/pipeline/scheduler.py:463` | 注释 "流式统计：Welford 在线算法" | **保留**（正确的实际实现） |
  | 4 | `src/pipeline/scheduler.py:500,510` | 注释 "计算 IC 值：Welford 算法" | 模糊：建议改为 "聚合 IC 统计量：Welford 在线算法（流式均值/M2）" |

- **修正模板**（用于文件 1）：
  ```
  - 原文：Layer 2——流式生成器...使用 Welford 在线算法实现流式 IC 计算
  + 修正：Layer 2——流式生成器...IC 计算本身使用标准 scipy.stats.spearmanr / np.corrcoef，
  +       流式内存管理通过 yield + gc.collect() 实现；
  +       后续聚合阶段（scheduler.py）使用 Welford 在线算法计算流式均值/M2。
  ```

- **墨萱复核要点**：
  1. ✅ 所有 `.md` 文件中关于 Welford 的错误描述被移除或更正
  2. ✅ `scheduler.py` 中正确的 Welford 实现被保留（勿误删）
  3. ✅ IC 计算（engine.py）的正确表述是 "标准 numpy/scipy 批量计算"
- **搜索命令**：`findstr /s /i "welford" *.py *.md`（根目录 `mozhi_platform`）
- **预估时间**：5 分钟


### A-4b — 修正 `_build_null_record` 文档误导

- **根因**：问题定义和文档中描述 `_build_null_record` 函数"不存在"，但实际**存在于** `cross_sectional_ic_pipeline.py`（是 `CrossSectionalICPipeline` 的方法，用于管线数据库写入的 NULL 记录构造）。真正的断链路径是：valuation_factor 中 NaN → dropna 后空 Series → compute_cross_sectional_ic 中 `len(common) < 30 → continue` 跳过（不调用 `_build_null_record`）。
- **修正定位**：文档中描述"`_build_null_record` 函数不存在"的地方需要澄清。

  | # | 文件路径 | 问题 | 修正方向 |
  |:-:|:---------|:-----|:---------|
  | 1 | `docs/06_root_causes/root_cause_T21_FULLRUN_20260530_v1.0.md` (C5) | "`_build_null_record` 函数不存在" | 改为 "`_build_null_record` 是 CrossSectionalICPipeline 的方法，但 valuation_factor 的代码路径并未调用它，实际是 NaN→dropna→continue skip" |
  | 2 | `docs/06_problem_definitions/problem_definition_T21_FULLRUN_20260530_v1.0.md`（若存在类似描述） | 同上 | 同上 |
  | 3 | `docs/06_problem_definitions/chain_review_T21_FULLRUN_20260530.md`（若存在） | 同上 | 同上 |

- **墨萱复核要点**：
  1. ✅ 修正后不产生新的误导：确认 `_build_null_record` 确实存在（pipeline 方法），但估值因子路径没经过它
  2. ✅ 区分两个不同上下文：管线写入（存在）vs 估值因子处理（不存在/未调用）
- **搜索命令**：`findstr /s /i "_build_null_record" *.py *.md`
- **预估时间**：5 分钟


---

## 汇总表格

| 子任务 | 文件 | 改动类型 | 预估时间 | 依赖 | 优先级 | 备注 |
|:------:|:-----|:--------:|:--------:|:----:|:------:|:-----|
| A-0a | `cross_sectional_ic_pipeline.py` | 🤔 仅验证 | 5min | — | P0 | Layer1 验证 |
| A-0b | `cross_sectional_ic_pipeline.py` | 🤔 仅验证 | 5min | A-0a | P0 | Layer2 验证 |
| A-0c | `cross_sectional_ic_pipeline.py` | 🤔 仅验证 | 5min | A-0b | P0 | Layer3 验证 |
| A-1a | `memory_profiler.py` | 🔨 编码 | 12min | — | P0 | MemoryMonitor 类 |
| A-1b | `memory_profiler.py` | 🔨 编码 | 10min | A-1a | P0 | 降级回调 |
| A-1c | `cross_sectional_ic_pipeline.py` | 🔨 编码 | 15min | A-1a,b | P0 | 集成到管线 |
| A-2a | `memory_profiler.py` | 🔨 编码 | 10min | — | P1 | 预算估算器 |
| A-2b | `cross_sectional_ic_pipeline.py` | 🔨 编码 | 8min | A-2a | P1 | 预算集成 |
| A-3a | `tests/test_memory_defense.py` | 🔨 编码 | 15min | A-0+A-1+A-2 | P1 | 6 核测试用例 |
| A-3b | `tests/test_memory_defense.py` | 🔨 编码追加 | 12min | A-3a | P1 | 6 边界测试用例 |
| A-4a | 文档 / scheduler.py | 📝 修正 | 5min | — | P2 | Welford 描述 |
| A-4b | 根因文档 | 📝 修正 | 5min | — | P2 | `_build_null_record` 描述 |

**总编码时间**：约 102 分钟（~1.7 小时）  
**总验证时间**：约 30 分钟（墨萱 QA）  
**并行策略**：A-0 + A-4 验证可并行；A-1a/b → A-1c 和 A-2a → A-2b 串行；A-3 依赖前面全部完成

---

## 执行流程

```
墨衡编码 → 自测（mock 通过）→ 写入 `.done` 信号 → 通知墨萱 QA
                                           ↓
                                       墨萱验证
                                      ↙      ↘
                                   PASS      FAIL(≤2次)
                                     ↓         ↓
                                 下一子任务   退回墨衡修复 → 再提交
                                              ↓ (3次)
                                          告警Owner介入
```

**关键规则**：
1. 每子任务 ≤15 分钟，超时标记 `BLOCKED` 并求助 Owner
2. QA 不通过退回修复 ≤2 次，第三次由 Owner 裁决
3. 串行推进，禁止并行执行（A-4 可独立在任何阶段执行）
4. 墨萱 QA 时提供 mock 内存环境（MockVirtualMemory）使测试不依赖实际物理内存
