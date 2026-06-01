---
author: 墨衡 (moheng)
created_time: 2026-05-31T10:25:00+08:00
type: experiment_plan_v1
problem_id: U2_T21_FULLRUN
version: v1.0
status: DRAFT
review_required: [moxuan, xuanzhi]
---

# 故障复现试验方案 — U1/U2 可观测性边界确认

## 一、试验目标

通过**受控复现**T+21全量运行故障，确认以下两个不确定项的边界：

| 不确定项 | 原始问题 | 试验确认目标 |
|:--------:|:---------|:------------|
| **U1** | 内存快照系统限制（WSL2+SIGKILL无法捕获精确时刻内存） | psutil运行时监控能否在OOM场景下捕获"杀前最后一截面"的内存记录？趋势数据能否辅助诊断？ |
| **U2** | 三次运行（marine-s/mellow-o/--no-run）使用相同source_version，DB无法区分各自精确写入量 | run_id新增列能否精确区分多次运行的写入归属？调度器重启时run_id传递链是否畅通？ |

### 试验定位

> ⚠️ 本次试验是"验证新监控/标识机制有效性"而非"还原历史现场"。不追求精确复现OOM条件，但追求**在OOM及正常两种场景下均能验证新机制行为**。

---

## 二、总体策略

### 分阶段执行

```
Phase 0: 代码改动（~45 min） 
  → Phase 1: Small-scale验证（~15 min） 
    [PASS →] Phase 2: 近5年重跑（~60 min） 
    [可选 →] Phase 3: 全量重跑（~180 min，仅Phase 2 PASS后决定是否执行）
```

### 约束确认清单

| # | 约束项 | 确认状态 |
|:-:|:-------|:--------:|
| 1 | 先small-scale再全量 | ✅ 三方共识 |
| 2 | run_id列新增（非覆写source_version） | ✅ 方案B2采用 |
| 3 | 独立source_version='v1_repro'隔离 | ✅ 墨萱建议采纳 |
| 4 | psutil逐截面内存检查 + <3GB告警/<2GB跳过 | ✅ 三方共识 |
| 5 | logging输出到文件，不依赖stdout | ✅ 需配置 |
| 6 | 明确定义PASS标准 | ✅ 见各阶段 |

---

## 三、代码改动清单（Phase 0）

### 3.1 改动总览

| # | 文件 | 改动内容 | 类型 | 预估耗时 |
|:-:|:-----|:---------|:----:|:--------:|
| C1 | `src/pipeline/cross_sectional_ic_pipeline.py` | 新增run_id参数，写入时携带 | 核心 | 15 min |
| C2 | `src/pipeline/cross_sectional_ic_pipeline.py` | 新增运行时psutil逐截面内存保护 | 核心 | 10 min |
| C3 | `src/pipeline/cross_sectional_ic_pipeline.py` | 新增文件日志handler配置 | 配置 | 5 min |
| C4 | `src/pipeline/scheduler.py` | 透传run_id到管线实例 | 整合 | 5 min |
| C5 | DB Schema变更（先读再改） | ALTER TABLE + 确认 | 数据 | 5 min |
| C6 | 配置文件/环境变量 | source_version='v1_repro' | 配置 | 2 min |
| C7 | 入口脚本改动 | 新增--run-id命令行参数 | 整合 | 3 min |

### 3.2 C1：管线新增run_id参数和写入

**文件**: `cross_sectional_ic_pipeline.py`

**改动点①** — 构造函数新增 `run_id` 参数（第112行附近）：

```python
def __init__(
    self,
    db_manager: DatabaseManager,
    ic_engine: IC_Engine,
    forward_returns: ForwardReturns,
    factor_registry: FactorRegistry,
    horizon: int = DEFAULT_HORIZON,
    source_version: str = SOURCE_VERSION,
    run_id: Optional[str] = None,           # ← 新增
    config: Optional[Dict[str, Any]] = None,
):
    # ... 现有代码 ...
    self.run_id = run_id                     # ← 新增
```

**改动点②** — `_write_ic_result` 增加run_id列（第881~906行）：

```python
def _write_ic_result(self, record: Dict[str, Any]) -> bool:
    conn = self.db_manager.get()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO a50_cross_ic_result
                (trade_date, factor_name, ic_value, rank_ic, p_value,
                 num_stocks, adjusted_ic, source_version, created_at
                 , run_id)          -- ← 新增列
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?
                    , ?)            -- ← 新增占位
            """,
            (
                record["trade_date"],
                record["factor_name"],
                record.get("ic_value"),
                record.get("rank_ic"),
                record.get("p_value"),
                record["num_stocks"],
                record.get("adjusted_ic"),
                record["source_version"],
                record["created_at"],
                record.get("run_id"),       # ← 新增参数
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        # ...
```

**改动点③** — `_build_null_record` 增加run_id字段（第920~936行）：

```python
@staticmethod
def _build_null_record(date, factor_name, n_stocks, run_id=None):  # ← 新增参数
    return {
        # ... 现有字段 ...
        "source_version": SOURCE_VERSION,
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "run_id": run_id,              # ← 新增
    }
```

**改动点④** — 调用 `_build_null_record` 和 `_build_ic_record` 处传入 `self.run_id`：

```python
# 在 run_pipeline 内，大约第503/521行构造null_record时：
null_record = self._build_null_record(date_std, factor_name, n_stocks, self.run_id)

# 大约第535行构造ic_record时加run_id字段：
ic_record = {
    # ... 现有字段 ...
    "run_id": self.run_id,            # ← 新增
}
```

**改动点⑤** — 模块级 `SOURCE_VERSION` 不变，但实例化时支持传入新版本：

```python
# 新增 run_source_version 常量（与旧v1共存）
REPRO_SOURCE_VERSION = "v1_repro"
```

### 3.3 C2：运行时psutil内存保护

**文件**: `cross_sectional_ic_pipeline.py`，`run_batch_streaming` 方法内

在**每个截面处理前**插入内存检查（约第757行 `for dt_str in dates_iter:` 之后）：

```python
for dt_str in dates_iter:
    # ── psutil运行时内存检查 ──────────────────────
    try:
        avail_gb = psutil.virtual_memory().available / (1024 ** 3)
        rss_gb = psutil.Process().memory_info().rss / (1024 ** 3)
        logger.info(
            "[MemGuard] Section=%s | RSS=%.2f GB | Avail=%.2f GB",
            dt_str, rss_gb, avail_gb,
        )
        if avail_gb < 2.0:
            logger.warning(
                "[MemGuard] Avail=%.2f GB < 2GB, SKIPPING section=%s",
                avail_gb, dt_str,
            )
            # 跳过当前截面：写入一条标记性NULL记录
            for factor_name in self.factor_registry.list():
                null_record = self._build_null_record(
                    dt_str, factor_name, 0, self.run_id,
                )
                self._write_ic_result(null_record)
            self.mem_profiler.take(f'skip_{dt_str}')
            gc.collect()
            continue
        elif avail_gb < 3.0:
            logger.warning(
                "[MemGuard] Avail=%.2f GB < 3GB, WARNING section=%s",
                avail_gb, dt_str,
            )
            # 不跳过，但记录告警
    except Exception as e:
        logger.error("[MemGuard] Error checking memory: %s", e)
    
    # ── 原逻辑继续 ──
    batch_idx += 1
    # ...
```

**关联改动**：`_check_environment_health` 已存在（启动时检查≥4GB），保持不变。

### 3.4 C3：文件日志配置

**文件**: `cross_sectional_ic_pipeline.py` 或新增独立的 `src/utils/logging_config.py`

在管线初始化时（或模块级别）配置文件日志：

```python
import logging
import logging.handlers
import os

def setup_pipeline_logging(
    log_dir: str = "pipeline_logs",
    run_id: Optional[str] = None,
) -> logging.Logger:
    """配置管线日志：同时输出到文件和控制台。"""
    os.makedirs(log_dir, exist_ok=True)
    
    run_tag = run_id or "default"
    log_file = os.path.join(
        log_dir,
        f"pipeline_{run_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    )
    
    # File handler（RotatingFileHandler，最大10MB，保留5个备份）
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    ))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
    ))
    
    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info("Log initialized: %s", log_file)
    return logger
```

> **关键日志要点**：每次INSERT前打印 `[IC_WRITE] {截面} {因子} {run_id}`，每次截面循环结束打印 `[MEM] {截面} RSS={rss_gb}GB Avail={avail_gb}GB`。这些结构化日志可事后解析为CSV统计。

### 3.5 C4：Scheduler透传run_id

**文件**: `scheduler.py`

```python
class ICBatchScheduler:
    def __init__(
        self,
        db_manager: DatabaseManager,
        # ... 其他参数 ...
        source_version: str = DEFAULT_SOURCE_VERSION,
        run_id: Optional[str] = None,           # ← 新增
    ):
        # ... 现有代码 ...
        self.run_id = run_id                     # ← 新增
```

在 `run_full_cross_sectional` 中实例化管线时传入：

```python
pipeline = CrossSectionalICPipeline(
    db_manager=self.db_manager,
    ic_engine=self.ic_engine,
    forward_returns=self.forward_returns,
    factor_registry=self.factor_registry,
    horizon=self.horizon,
    source_version=self.run_source_version or REPRO_SOURCE_VERSION,
    run_id=self.run_id,                       # ← 新增
)
```

**新增 `run_source_version` 属性**：当指定 `run_id` 时自动使用 `source_version='v1_repro'`，当 `run_id=None` 时使用旧 `source_version='v1'`（向后兼容）。

### 3.6 C5：DB Schema变更

```sql
-- 在试验开始前执行一次
ALTER TABLE a50_cross_ic_result ADD COLUMN run_id TEXT;

-- 验证
SELECT run_id, COUNT(*) FROM a50_cross_ic_result GROUP BY run_id;
-- 旧数据 run_id = NULL（仅1行），新数据按run_id分组
```

> SQLite的 `ALTER TABLE ADD COLUMN` 是 O(1) 操作，不重建表，不影响线上数据和查询性能。
> 旧脚本 `SELECT *` 仍然兼容（新列出现在最后）。

### 3.7 C7：入口脚本改动

**参考脚本模式**（在 `scripts/` 中新增 `run_pipeline_experiment.py`）：

```python
import argparse

parser = argparse.ArgumentParser(description="U2复现试验管线启动器")
parser.add_argument("--start-date", required=True)
parser.add_argument("--end-date", required=True)
parser.add_argument("--step", default="1W")
parser.add_argument("--run-id", required=True, help="运行标识，如 marine-s / mellow-o / norun")
parser.add_argument("--source-version", default="v1_repro")
parser.add_argument("--log-dir", default="pipeline_logs")
parser.add_argument("--no-run", action="store_true", help="跳过管线计算，仅从已有数据出报告")

args = parser.parse_args()

# 初始化组件...
scheduler = ICBatchScheduler(
    dm, registry, ic_engine, fr,
    source_version=args.source_version,
    run_id=args.run_id,
)
```

---

## 四、Phase 1：Small-scale验证

### 4.1 目的

验证代码改动的核心机制——run_id传递链、ALTER TABLE兼容性、psutil监控——在**最小、可控**的场景下是否正常工作。

### 4.2 步骤

| 步骤 | 操作 | 预期 | 验证方法 |
|:----:|:-----|:-----|:---------|
| 1.1 | DB备份 + ALTER TABLE加run_id列 | 成功，旧数据run_id=NULL | SQL查询验证 |
| 1.2 | 跑2~3个截面：`python run_pipeline_experiment.py --start-date 20260525 --end-date 20260527 --run-id test_run1` | 正常完成，写入带run_id的记录 | SQL: GROUP BY run_id |
| 1.3 | 手动模拟SIGKILL（见§六）中断进程 | 进程终止 | 观察进程退出 |
| 1.4 | 重启：`--run-id test_run2`（含--resume）继续跑 | 重启后使用新run_id，INSERT OR IGNORE跳过已有截面 | SQL: GROUP BY run_id确认两条记录 |
| 1.5 | 验证查询 | 正确区分两次写入 | 见下方PASS标准 |

### 4.3 手动模拟SIGKILL的方法

**方案A（推荐）：`taskkill /F /PID`**

```powershell
# 在另一个终端执行
$pid = (Get-Process -Name python | Where-Object { $_.CommandLine -match "test_run1" }).Id
taskkill /F /PID $pid
```

**方案B（备用）：Python内置`os.kill()`**

```python
# 在管线内插桩：检测到某个标记文件存在时自杀
import os, signal, time

KILL_FILE = "signals/KILL_NOW.signal"
if os.path.exists(KILL_FILE):
    logger.warning("[KillSim] KILL_NOW signal detected, self-terminating")
    os.remove(KILL_FILE)  # 清理信号
    # 模拟随机延时后杀进程（模拟实际OOM时刻不确定性）
    time.sleep(random.uniform(0.1, 2.0))
    os.kill(os.getpid(), signal.SIGKILL)
```

**方案C（极端）：ulimit限制**

```bash
# 在启动前限制虚拟内存，触发真实OOM
ulimit -v 4194304  # 4GB虚拟内存上限
python run_pipeline_experiment.py --run-id test_oom
```

> **推荐方案A**：最接近原始故障场景（外部进程直接SIGKILL），且不需要代码插桩。

### 4.4 PASS标准

| # | 检查项 | PASS条件 | 验证方式 |
|:-:|:-------|:---------|:---------|
| P1.1 | run_id列创建 | `SELECT run_id FROM a50_cross_ic_result LIMIT 5` 返回含NULL列，不报错 | SQL直接执行 |
| P1.2 | 第一次写入 | `SELECT run_id, COUNT(*) FROM a50_cross_ic_result WHERE run_id='test_run1' GROUP BY run_id` 返回值>0 | SQL COUNT |
| P1.3 | SIGKILL后新run_id | 进程被终止，无Python异常栈 | 控制台观察 |
| P1.4 | 重启后新写入 | `SELECT run_id, COUNT(*) FROM a50_cross_ic_result WHERE run_id='test_run2' GROUP BY run_id` 返回值>0 | SQL COUNT |
| P1.5 | 两条run_id不重复 | `SELECT COUNT(DISTINCT run_id) FROM a50_cross_ic_result WHERE run_id IS NOT NULL` = 2 | SQL聚合 |
| P1.6 | 旧数据没被污染 | `SELECT COUNT(*) FROM a50_cross_ic_result WHERE run_id IS NULL` = 备份前旧数据行数 | 对比备份 |
| P1.7 | psutil日志存在 | 日志文件中包含 `[MemGuard]` 标记行 | grep检查 |
| P1.8 | 新source_version隔离 | `SELECT source_version, COUNT(*) FROM a50_cross_ic_result GROUP BY source_version` 区分v1和v1_repro | SQL聚合 |

### 4.5 预估耗时

| 步骤 | 耗时 | 说明 |
|:----|:----:|:------|
| 代码改动部署 | 5 min | 已先做则不计入 |
| DB备份 + ALTER TABLE | 1 min | cp操作 + SQL执行 |
| 第一次运行（3截面） | ~2 min | 极少量数据 |
| SIGKILL + 重启 | 1 min | 手动kill + 重跑 |
| 验证查询 | 3 min | SQL执行 + 检查 |
| **总计** | **~12 min** | 不含代码改动 |

---

## 五、Phase 2：近5年重跑

### 5.1 前置条件

- Phase 1 **全部8项PASS标准均通过**
- DB已备份（`backup/a50_ic_{YYYYMMDD_HHMMSS}_pre_U2_repro.db`）
- 确认可用内存 ≥ 6GB（启动前检查）

### 5.2 步骤

| 步骤 | 操作 | 说明 |
|:----:|:-----|:------|
| 2.1 | 备份 + 确认 | 与Phase 1同一备份DB，无需重复 |
| 2.2 | 首次运行：`--start-date 20210101 --end-date 20260526 --run-id repro_p1` | 覆盖近5年数据 |
| 2.3 | 若被杀：自动重启 `--run-id repro_p2` | 调度器检测到非零退出码后手动执行 |
| 2.4 | 若完成：验证U1/U2 | 见PASS标准 |
| 2.5 | 若未触发OOM：跑 `--no-run --run-id repro_norun` | 模拟第三阶段写入 |

### 5.3 PASS标准

| # | 检查项 | PASS条件 | 验证方式 |
|:-:|:-------|:---------|:---------|
| P2.1 | run_id传递链 | 所有新写入行的run_id均不为NULL且等于传入值 | SQL COUNT run_id IS NOT NULL |
| P2.2 | run_id精确区分 | `SELECT run_id, COUNT(*) FROM a50_cross_ic_result WHERE source_version='v1_repro' GROUP BY run_id` = 预期（各进程行数可精确统计） | SQL聚合 |
| P2.3 | 旧数据隔离 | `SELECT COUNT(*) FROM a50_cross_ic_result WHERE source_version='v1'` = 备份前总量 | 对比快照 |
| P2.4 | psutil监控记录 | 日志文件包含每截面 `[MemGuard]` 记录，形成完整内存曲线 | 日志解析 |
| P2.5 | OOM场景U1验证 | （若触发OOM）日志中最后一条 `[MemGuard]` 记录的时间 ≈ 被杀时间，证实杀前最后一截面已记录 | 时间戳对比 |
| P2.6 | --no-run的run_id | `SELECT COUNT(*) FROM a50_cross_ic_result WHERE run_id='repro_norun'` >0 | SQL |

### 5.4 预估耗时

| 场景 | 耗时 | 说明 |
|:----|:----:|:------|
| 近5年正常完成（不触发OOM） | ~60 min | 约5年数据，运行效率约2截面/min |
| 近5年 + 一次SIGKILL | ~80 min | 被杀1次 + 重启耗时 |
| 近5年 + 两次SIGKILL | ~100 min | 最坏情况 |
| --no-run模式 | ~5 min | 跳过计算，仅写入 |

---

## 六、OOM防护措施（贯穿所有阶段）

### 6.1 防护层级

| 层级 | 阈值 | 动作 | 实施位置 |
|:----:|:----:|:-----|:--------|
| L1 | 启动时 < 4GB | 报错退出，不启动 | `_check_environment_health()`（已有） |
| L2 | 运行时 < 3GB | 日志告警 + 内存采样 | 每截面开头 `[MemGuard]` |
| L3 | 运行时 < 2GB | 跳过当前截面（写标记NULL记录） | 每截面开头 `[MemGuard]` |
| L4 | 极端情况（接近0） | 写紧急日志 + 尝试优雅退出 | `signal.SIGTERM` handler |

### 6.2 额外防护

- **降低并行度**：单线程流式模式（已有），不改变
- **减少checkpoint IO**：checkpoint仅跟踪进度（已有）无需修改
- **ulimit降级**：必要时在WSL2中设置 `ulimit -v 8388608`（8GB虚拟内存上限）防止整机拖慢
- **Windows侧**：确认 `.wslconfig` 中 `memory=12GB` 或 `14GB` 预留1~2GB给主机

---

## 七、数据隔离方案

### 7.1 双重隔离策略

| 维度 | 隔离方式 | 值 |
|:-----|:---------|:----|
| **source_version** | 独立版本标识 | 旧：`'v1'` → 新：`'v1_repro'` |
| **run_id** | 逐运行标识 | `'repro_p1'` / `'repro_p2'` / `'repro_norun'` |

### 7.2 查询隔离规则

```sql
-- 生产/基线相关查询仍用v1
SELECT * FROM a50_cross_ic_result WHERE source_version = 'v1';

-- 复试验证查询用v1_repro
SELECT run_id, COUNT(*) FROM a50_cross_ic_result 
WHERE source_version = 'v1_repro' 
GROUP BY run_id;

-- 交叉验证：确认不存在混合
SELECT source_version, COUNT(*) FROM a50_cross_ic_result 
GROUP BY source_version;
```

### 7.3 保险措施

| 措施 | 触发条件 | 操作 |
|:-----|:---------|:-----|
| DB全量备份 | Phase 1开始前 | `cp a50_ic.db backup/a50_ic_{timestamp}_pre_U2_repro.db` |
| 增量备份 | 每次重启前 | `cp a50_ic.db backup/a50_ic_{timestamp}_pre_restart{seq}.db` |

---

## 八、手动模拟SIGKILL完整流程

### 8.1 步骤清单

```bash
# Step 1: 启动试验管线（背景运行）
python run_pipeline_experiment.py \
  --start-date 20260525 \
  --end-date 20260527 \
  --run-id test_marine \
  --source-version v1_repro \
  --log-dir pipeline_logs

# Step 2: 在另一个终端窗口查找PID
Get-Process python | Where-Object { $_.CommandLine -match "test_marine" }

# Step 3: 观察日志中出现 ~2-3 个截面后，执行SIGKILL
taskkill /F /PID <PID>

# Step 4: 确认进程已终止（退出码 137 或 1）
echo $LASTEXITCODE

# Step 5: 重启新运行
python run_pipeline_experiment.py \
  --start-date 20260525 \
  --end-date 20260527 \
  --run-id test_mellow \
  --source-version v1_repro \
  --log-dir pipeline_logs
```

### 8.2 验证查询（模拟真实故障场景）

```sql
-- 模拟T+21的验证场景
-- 精确回答：test_marine 写入了多少行？
SELECT COUNT(*) as marine_rows
FROM a50_cross_ic_result
WHERE source_version = 'v1_repro' AND run_id = 'test_marine';

-- 精确回答：test_mellow 写入了多少行？
SELECT COUNT(*) as mellow_rows
FROM a50_cross_ic_result
WHERE source_version = 'v1_repro' AND run_id = 'test_mellow';

-- 精确回答：各次运行贡献了哪些截面？
SELECT run_id, COUNT(DISTINCT trade_date) as unique_dates
FROM a50_cross_ic_result
WHERE source_version = 'v1_repro'
GROUP BY run_id;
```

> ✅ **核心验证**：以上三个查询在原始故障中**不可执行**（因为 marine-s、mellow-o、norun 使用相同 `source_version='v1'` 且 time精度只到秒级）。复现后若可执行，即证明U2可解。

---

## 九、预期产出与U1/U2确认

### 9.1 U1确认：psutil内存监控

| 结果场景 | 对U1的影响 | 结论 |
|:---------|:-----------|:-----|
| 触发OOM + 日志有最后一条[MemGuard]记录 | ✅ U1边界清晰：psutil可捕获"杀前最后一截面"数据 | U1从"系统限制"→"系统限制+部分缓解" |
| 触发OOM + 日志缺失最后一条 | ⚠️ U1边界不变（psutil所在线程也随进程被杀而中断） | 佐证了"SIGKILL时用户态无最后机会"的原理 |
| 未触发OOM | U1的定性不变：系统限制还是系统限制 | 但可通过小脚本独立验证psutil行为 |

**U1最终结论格式**：

```
U1：WSL2+SIGKILL场景下，psutil运行时监控可提供"杀前最后一截面"内存记录
    （RSS+系统可用内存），形成完整内存增长曲线。
    无法提供"精确被杀时刻"的快照（架构性限制）。
    → 系统限制未消除，但信息缺口从"完全盲区"缩小为"1~2截面偏差"。
```

### 9.2 U2确认：run_id精确区分

| 结果场景 | 对U2的影响 | 结论 |
|:---------|:-----------|:-----|
| Phase 1通过 | ✅ run_id传递链+ALTER TABLE兼容性均验证通过 | U2从"需日志"→"可精确区分" |
| Phase 2通过 | ✅ 全量运行下run_id精确区分能力确认 | run_id是可靠的行级写入标识 |
| 未触发OOM | U2验证**不依赖OOM**，结论不变 | run_id的价值不依赖于运行是否异常 |
| SIGKILL场景下run_id正确递增 | ✅ 验证调度器重启传递链畅通 | 覆盖了原始故障场景 |

**U2最终结论格式**：

```
U2：新增run_id列 + 独立source_version(v1_repro)可精确区分多次运行的写入量。
    SELECT GROUP BY run_id 可精确报告各进程行数。
    调度器重启时通过传入不同run_id实现传递链。
    → 原始故障中U2所列的"不确定性"已被消除。
    【注意】根因（OOM）未被修复，仅可观测性边界被清除。
```

### 9.3 产出物清单

| # | 产出物 | 说明 |
|:-:|:-------|:-----|
| 1 | 代码改动diff | `src/pipeline/cross_sectional_ic_pipeline.py` + `scheduler.py` 的diff |
| 2 | 运行日志 | `pipeline_logs/` 目录下的各次运行日志 |
| 3 | SQL验证结果 | run_id分组统计 + source_version隔离确认 |
| 4 | psutil内存曲线 | 从日志提取 `[MemGuard]` 记录形成的截面索引→RSS曲线 |
| 5 | 结论报告 | U1/U2的最终可观测性边界声明 |
| 6 | 代码检讨建议 | 针对OOM根因（内存泄露趋势）的分析代码修改建议 |

---

## 十、风险管理

### 10.1 风险矩阵

| # | 风险 | 概率 | 影响 | 缓解措施 |
|:-:|:-----|:----:|:----:|:---------|
| R1 | Phase 1发现run_id传递链断裂 | 中 | 高——全量白跑 | Phase 1的定位就是发现此问题，修复后重试 |
| R2 | ALTER TABLE失败或报错 | 低 | 高——阻塞所有后续 | SQLite ALTER TABLE ADD COLUMN测试先行 |
| R3 | 重跑触发OOM导致测试环境不稳定 | 高 | 中——近5年也可能OOM | 严格执行L2/L3内存保护；降低checkpoint频率 |
| R4 | 重跑数据污染生产查询 | 低 | 高——基线/IC计算错误 | source_version隔离 + 查询脚本显式过滤 |
| R5 | WSL2环境差异导致复现假阴性 | 中 | 中——结论不可推广至原生Linux | 结论文档中明确标注环境差异 |
| R6 | 日志文件过大撑满磁盘 | 低 | 低 | RotatingFileHandler + 每截面日志量很小 |

### 10.2 失败预案

| 场景 | 处理方式 |
|:-----|:---------|
| Phase 1 FAIL | 检查错误，修复对应代码改动，重走Phase 1 |
| Phase 2 连续三次OOM | 缩小范围到最近2年；或接受OOM场景下U1验证直接完成，启动--no-run验证U2 |
| Phase 2 正常完成（不触发OOM） | U2验证不受影响，U1走小脚本独立验证 |
| DB损坏 | 从备份恢复，检查前一次备份的完整性 |

---

## 十一、验收条目

| # | 验收标准 | 责任方 |
|:-:|:---------|:-------|
| A1 | 试验方案是否完整覆盖U1/U2的可观测性边界 | 墨萱（QA） |
| A2 | 代码改动是否最小侵入、不破坏现有功能 | 玄知（架构） |
| A3 | Phase 1的PASS标准是否合理可量化 | 墨萱（QA） |
| A4 | 数据隔离方案是否完整（source_version + run_id双重隔离） | 玄知（架构） |
| A5 | OOM防护是否足够（逐截面检查 + 三级阈值） | 墨萱（QA） |
| A6 | 试验结论（U1/U2边界）是否可追溯验证 | 墨萱（QA） |
| A7 | 方案是否考虑了WSL2 vs 原生Linux的环境差异 | 玄知（架构） |

---

## 附录A：关键SQL查询合集

```sql
-- A1: 备份前历史数据基准
SELECT COUNT(*) as total_rows,
       COUNT(DISTINCT trade_date) as unique_dates,
       COUNT(DISTINCT factor_name) as unique_factors
FROM a50_cross_ic_result WHERE source_version = 'v1';

-- A2: run_id列存在性
PRAGMA table_info(a50_cross_ic_result);

-- A3: 旧数据兼容性（run_id应为NULL）
SELECT COUNT(*) as old_rows_with_null_run_id
FROM a50_cross_ic_result WHERE source_version = 'v1' AND run_id IS NULL;

-- A4: 新数据run_id区分（验证U2核心查询）
SELECT run_id, source_version,
       COUNT(*) as rows,
       COUNT(DISTINCT trade_date) as unique_dates
FROM a50_cross_ic_result
WHERE source_version = 'v1_repro'
GROUP BY run_id, source_version;

-- A5: 隔离确认（v1数据不受影响）
SELECT COUNT(*) FROM a50_cross_ic_result WHERE source_version = 'v1';
-- 应与A1结果相等

-- A6: 唯一索引约束不变（不会因run_id不同导致重复）
SELECT trade_date, factor_name, forward_window, source_version, COUNT(*)
FROM a50_cross_ic_result
GROUP BY trade_date, factor_name, forward_window, source_version
HAVING COUNT(*) > 1;
-- 应返回0行
```

## 附录B：预估总耗时

| 阶段 | 内容 | 耗时 | 能否并行 |
|:----:|:-----|:----:|:--------:|
| Phase 0 | 代码改动 + ALTER TABLE | ~45 min | 仅串联 |
| Phase 1 | small-scale验证 | ~15 min | 仅串联 |
| — | 中间等待（评审） | ~30 min | 可并行 |
| Phase 2 | 近5年重跑 | ~60~100 min | 仅串联 |
| Phase 3（可选） | 全量重跑 | ~180 min | 仅串联 |
| 结论整理 | 文档 + 验证报告 | ~20 min | 可与Phase 2/3并行 |
| **总耗时（含Phase 1+2）** | | **~150~190 min** | |

> 建议执行时间窗口：凌晨 01:00~05:00（避开交易时段）
> Phase 2若在夜间执行且正常完成，Phase 3可视资源情况立即跟进

## 附录C：环境确认清单

| 检查项 | 值 | 确认状态 |
|:-------|:---|:--------:|
| OS | Windows 11 x64 + WSL2 Ubuntu | ⏳ 待确认 |
| Python | 3.14+ | ⏳ 待确认 |
| psutil | 已安装 | ⏳ 待确认 |
| SQLite | 默认（ALTER TABLE ADD COLUMN 支持） | ⏳ 待确认 |
| 磁盘空间 | ≥ 1GB 可用（日志+DB备份） | ⏳ 待确认 |
| 内存 | ≥ 8GB 可用（启动后） | ⏳ 待确认 |
| 调度器 | 无自动重启机制（手动重启） | ⏳ 待确认 |
| WSL2 `.wslconfig` | memory限制检查 | ⏳ 待确认 |

---

*EOF*
