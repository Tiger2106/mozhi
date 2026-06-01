---
author: 墨衡 (moheng)
created_time: 2026-05-31T10:39:00+08:00
type: experiment_plan_v2.1
problem_id: U2_T21_FULLRUN
version: v2.1
status: DRAFT
review_required: [moxuan, xuanzhi]
previous_version: v2.0
fixes:
  - D2: 唯一索引包含run_id（方案A）
  - C1-1/D5: _build_null_record source_version实例化
  - SIGKILL-1.1: 原生Windows下恢复taskkill方案（supersedes v2.0 SIGKILL-1）
  - D1: from_config透传run_id + 入口脚本--resume-from
  - C1-2: --no-run模式实现说明
  - C2-1: 跳过截面时yield占位结果
  - D3: psutil截面计算前后双检
  - P1.9/P1.10/P2.4量化: 新增/修正PASS标准
  - ENV-v2.1: 全线修正运行环境假设从WSL2→原生Windows（术语、工具、附录C重写）
---

# 故障复现试验方案 v2.1 — U1/U2 可观测性边界确认
## （修正运行环境：原生Windows）

## 关于v2.1版本

v2.0方案基于错误假设（OpenClaw在WSL2上运行）编写。实际上OpenClaw和Python管线都运行在**原生Windows 11 x64**上（sys.platform=win32）。v2.1全线修正了WSL2相关假设，包括：

- **所有SIGKILL/exit code 137术语** → 替换为Windows/Python退出码描述
- **§六手动终止方案** → 从"文件信号自杀"恢复为 `taskkill /F /PID`
- **附录C** → 从WSL2检查项重写为Windows原生检查项
- **内存监控补充** → 增加Windows特有工具（perfmon、ETW）
- 保留v2.0已修复的所有其他缺陷（D2/C1-1/D1/C1-2/C2-1/D3/P1.9/P1.10/P2.4）

---

## 一、试验目标

通过**受控复现**T+21全量运行故障，确认以下两个不确定项的边界：

| 不确定项 | 原始问题 | 试验确认目标 |
|:--------:|:---------|:------------|
| **U1** | 内存快照系统限制（Windows+进程终止无法捕获精确时刻内存） | psutil运行时监控能否在OOM场景下捕获"杀前最后一截面"的内存记录？趋势数据能否辅助诊断？ |
| **U2** | 三次运行（marine-s/mellow-o/--no-run）使用相同source_version，DB无法区分各自精确写入量 | run_id新增列能否精确区分多次运行的写入归属？调度器重启时run_id传递链是否畅通？ |

### 试验定位

> ⚠️ 本次试验是"验证新监控/标识机制有效性"而非"还原历史现场"。不追求精确复现OOM条件，但追求**在OOM及正常两种场景下均能验证新机制行为**。

---

## 二、总体策略

### 分阶段执行

```
Phase 0: 代码改动（~50 min，含D2唯一索引重构）
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

| # | 文件 | 改动内容 | 类型 | 缺陷关联 | 预估耗时 |
|:-:|:-----|:---------|:----:|:--------:|:--------:|
| C1 | `cross_sectional_ic_pipeline.py` | 新增run_id参数，写入时携带 | 核心 | — | 15 min |
| C1a | `cross_sectional_ic_pipeline.py` | **_build_null_record** 改为实例方法，使用 `self.source_version` | **修复** | C1-1/D5 | 3 min |
| C2 | `cross_sectional_ic_pipeline.py` | 新增运行时psutil逐截面内存保护 + **跳过时yield占位结果** | 核心+修复 | C2-1/D3 | 12 min |
| C3 | `cross_sectional_ic_pipeline.py` | 新增文件日志handler配置 | 配置 | — | 5 min |
| C4 | `scheduler.py` | 透传run_id到管线实例 + **from_config增加run_id参数** | 修复 | D1 | 8 min |
| C5 | DB Schema变更 | ALTER TABLE + **DROP旧唯一索引→创建含run_id的新唯一索引** | 修复 | D2 | 5 min |
| C6 | 配置文件/环境变量 | source_version='v1_repro' | 配置 | — | 2 min |
| C7 | 入口脚本改动 | 新增`--run-id`/`--resume-from`/`--min-memory`参数 + --no-run实现 | 核心+修复 | D1/C1-2 | 10 min |

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

**改动点③** — `_build_null_record` 改为实例方法，使用 `self.source_version`（v2.1保留，同v2.0）：

```python
def _build_null_record(
    self,
    date: str,
    factor_name: str,
    n_stocks: int,
) -> Dict[str, Any]:
    """构建 IC 值为 NULL 的记录（样本不足或计算失败时使用）。
    
    v2改动：改为实例方法，使用self.source_version代替硬编码SOURCE_VERSION。
    v2.1保留：逻辑不变，仅术语修正（本文档）。
    """
    return {
        "trade_date": date,
        "factor_name": factor_name,
        "ic_value": None,
        "rank_ic": None,
        "p_value": None,
        "num_stocks": n_stocks,
        "adjusted_ic": None,
        "source_version": self.source_version,
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "run_id": self.run_id,
    }
```

**改动点④** — 调用 `_build_null_record` 处（第503/521行）更新调用方式（同v2.0）：

```python
null_record = self._build_null_record(date_std, factor_name, n_stocks)
```

**改动点⑤** — 构造 `ic_record` 处（第535行）新增 `run_id` 字段：

```python
ic_record = {
    # ... 现有字段 ...
    "source_version": self.source_version,
    "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    "run_id": self.run_id,            # ← 新增
}
```

**改动点⑥** — 模块级 `SOURCE_VERSION` 不变，但新增试验版本常量：

```python
# 新增 run_source_version 常量（与旧v1共存）
REPRO_SOURCE_VERSION = "v1_repro"
```

### 3.3 C2：运行时psutil内存保护（v2.1保留，同v2.0增强版）

**文件**: `cross_sectional_ic_pipeline.py`，`run_batch_streaming` 方法内

在**每个截面处理前**和后插入内存检查（v2修复D3：计算前后各检查一次）：

```python
# ── C2：psutil运行时内存保护 ──────────────────────
def _memguard_check(self, dt_str: str, phase: str = "pre") -> Dict[str, Any]:
    """单次内存检查，返回检查摘要。phase: 'pre'|'post'"""
    result = {
        "avail_gb": None,
        "rss_gb": None,
        "action": "ok",
        "phase": phase,
    }
    try:
        avail_gb = psutil.virtual_memory().available / (1024 ** 3)
        rss_gb = psutil.Process().memory_info().rss / (1024 ** 3)
        result["avail_gb"] = avail_gb
        result["rss_gb"] = rss_gb
        logger.info(
            "[MemGuard] Section=%s phase=%s | RSS=%.2f GB | Avail=%.2f GB",
            dt_str, phase, rss_gb, avail_gb,
        )
        if avail_gb < 2.0:
            result["action"] = "skip"
            logger.warning(
                "[MemGuard] Avail=%.2f GB < 2GB, SKIPPING section=%s",
                avail_gb, dt_str,
            )
        elif avail_gb < 3.0:
            result["action"] = "warn"
            logger.warning(
                "[MemGuard] Avail=%.2f GB < 3GB, WARNING section=%s",
                avail_gb, dt_str,
            )
    except Exception as e:
        logger.error("[MemGuard] Error checking memory: %s", e)
        result["action"] = "error"
    return result

# ===== 在run_batch_streaming的for循环内使用 =====

for dt_str in dates_iter:
    # ── pre-check：截面计算前 ──
    pre_check = self._memguard_check(dt_str, phase="pre")
    
    if pre_check["action"] == "skip":
        # 跳过当前截面：写入标记性NULL记录 + yield占位结果
        for factor_name in self.factor_registry.list():
            null_record = self._build_null_record(dt_str, factor_name, 0)
            self._write_ic_result(null_record)
        self.mem_profiler.take(f'skip_{dt_str}')
        gc.collect()
        # v2修复（C2-1）：跳过时仍yield占位结果，保证生成器连续性
        yield {
            "date": dt_str,
            "status": "SKIPPED",
            "total_factors": len(list(self.factor_registry.list())),
            "computed_factors": 0,
            "ic_results": [],
            "errors": {
                "memory": f"Available {pre_check['avail_gb']:.2f}GB < 2GB",
            },
            "mem_check": pre_check,
            "run_id": self.run_id,
        }
        continue
    
    if pre_check["action"] == "warn":
        # 不跳过，但记录告警后续继续
        pass
    
    # ── 原逻辑：截面计算 ──
    batch_idx += 1
    # ... run_pipeline(dt_str) ...
    
    # v2优化（D3）：截面计算后再检查一次，捕获计算过程中的内存变化
    post_check = self._memguard_check(dt_str, phase="post")
    if post_check["action"] in ("skip", "warn"):
        logger.info(
            "[MemGuard] Post-check: section=%s action=%s "
            "RSS=%.2fGB Avail=%.2fGB (pre-avail was %.2fGB)",
            dt_str, post_check["action"],
            post_check["rss_gb"], post_check["avail_gb"],
            pre_check.get("avail_gb", "N/A"),
        )
    
    # day_result中附加内存检查信息
    day_result["mem_check"] = {"pre": pre_check, "post": post_check}
    
    yield day_result
    # ...
```

**关联改动**：`_check_environment_health` 已存在（启动时检查≥4GB），保持不变。

### 3.4 C3：文件日志配置（同v2.0）

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

### 3.5 C4：Scheduler透传run_id + from_config修复（同v2.0）

**改动点①** — `__init__` 新增 `run_id` 参数：

```python
class ICBatchScheduler:
    def __init__(
        self,
        db_manager: DatabaseManager,
        factor_registry: FactorRegistry,
        ic_engine: IC_Engine,
        forward_returns: ForwardReturns,
        horizon: int = DEFAULT_HORIZON,
        source_version: str = DEFAULT_SOURCE_VERSION,
        run_id: Optional[str] = None,           # ← 新增
    ):
        self.run_id = run_id
```

**改动点②** — `run_full_cross_sectional` 中实例化管线时传入 `run_id`：

```python
pipeline = CrossSectionalICPipeline(
    db_manager=self.db_manager,
    ic_engine=self.ic_engine,
    forward_returns=self.forward_returns,
    factor_registry=self.factor_registry,
    horizon=self.horizon,
    source_version=self.run_source_version or REPRO_SOURCE_VERSION,
    run_id=self.run_id,
)
```

**改动点③** — `from_config()` 工厂方法新增 `run_id` 参数：

```python
@classmethod
def from_config(
    cls,
    db_config: Optional[Dict[str, Any]] = None,
    horizon: int = DEFAULT_HORIZON,
    source_version: str = DEFAULT_SOURCE_VERSION,
    run_id: Optional[str] = None,
) -> "ICBatchScheduler":
    return cls(
        db_manager=dm,
        factor_registry=reg,
        ic_engine=engine,
        forward_returns=fr,
        horizon=horizon,
        source_version=source_version,
        run_id=run_id,
    )
```

### 3.6 C5：DB Schema变更（同v2.0，方案A）

#### 3.6.1 决策：唯一索引包含run_id（方案A）

**选择理由**：同v2.0。试验目标是**验证U2中run_id能否精确区分三次运行的写入量**，三次运行使用相同的截面日期范围。方案A才是正确复现U2场景。

#### 3.6.2 执行步骤

```sql
-- Step 1: 查询当前唯一索引名称
SELECT name FROM sqlite_master 
WHERE type='index' AND sql LIKE '%UNIQUE%a50_cross_ic_result%';

-- Step 2: DROP旧唯一索引
DROP INDEX IF EXISTS idx_ic_uniq;

-- Step 3: 创建包含run_id的新唯一索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_ic_uniq_v2
ON a50_cross_ic_result (trade_date, factor_name, forward_window, source_version, run_id);

-- Step 4: ADD COLUMN run_id（如尚未添加）
ALTER TABLE a50_cross_ic_result ADD COLUMN run_id TEXT;

-- Step 5: 验证新索引
PRAGMA index_list(a50_cross_ic_result);
PRAGMA index_info(idx_ic_uniq_v2);

-- Step 6: 验证旧数据兼容性
SELECT run_id, COUNT(*) FROM a50_cross_ic_result 
WHERE source_version = 'v1' GROUP BY run_id;
-- 旧数据run_id=NULL（仅1行汇总）
```

#### 3.6.3 数据行为说明

| 场景 | INSERT OR IGNORE行为 | 解释 |
|:-----|:---------------------|:-----|
| 首次写入（run_id='repro_p1'） | ✅ 插入成功 | 唯一索引组合不存在 |
| 相同run_id重复写入同截面 | ❌ IGNORE跳过 | 五列组合完全相同 |
| 不同run_id写入同截面 | ✅ 插入成功 | run_id不同 → 索引组合不同 |
| 重启后新run_id写入未完成截面 | ✅ 插入成功 | 已完成的被旧run_id占据，未完成的被新run_id写入 |
| 重启后新run_id写入已完成截面 | ✅ 插入成功（一条旧run_id + 一条新run_id） | run_id不同，索引不冲突 |

### 3.7 C7：入口脚本改动（同v2.0）

**新增脚本** `scripts/run_pipeline_experiment.py`（内容同v2.0，仅术语修正）：

- `--start-date` / `--end-date` / `--step` 参数
- `--run-id`：运行标识
- `--source-version`：默认 `v1_repro`
- `--log-dir`：日志目录
- `--min-memory`：启动时最低可用内存阈值，默认4.0 GB
- `--resume-from`：恢复已中止的pipeline_run_id
- `--no-run`：跳过管线计算，仅写入run_id标记汇总记录
- `--checkpoint-dir`：checkpoint目录

> **v2.1环境相关修正**：入口脚本无代码层面改动——与运行环境无关。

---

## 四、Phase 1：Small-scale验证

### 4.1 目的

验证代码改动的核心机制——run_id传递链、ALTER TABLE兼容性、唯一索引含run_id、psutil监控——在**最小、可控**的场景下是否正常工作。

### 4.2 步骤

| 步骤 | 操作 | 预期 | 验证方法 |
|:----:|:-----|:-----|:---------|
| 1.1 | DB备份 + ALTER TABLE + DROP旧索引→CREATE新索引 | 成功，旧数据run_id=NULL | SQL查询 + PRAGMA index_info |
| 1.2 | 跑2~3个截面：`--start-date 20260525 --end-date 20260527 --run-id test_run1` | 正常完成，写入带run_id的记录 | SQL: GROUP BY run_id |
| 1.3 | 手动模拟进程终止（使用taskkill，见§六）中断进程 | 进程被终止 | tasklist确认进程消失 / ERRORLEVEL非零 |
| 1.4 | 重启：`--run-id test_run2 --resume-from <checkpoint_id>` | 新run_id写入未完成截面，INSERT OR IGNORE跳过已有截面 | SQL: GROUP BY run_id确认两条记录 |
| 1.5 | 验证查询 | 正确区分两次写入 | 见下方PASS标准 |
| 1.6 | 验证--no-run模式（可选） | `--no-run --run-id test_norun`写入标记记录 | SQL |

### 4.3 PASS标准

| # | 检查项 | PASS条件 | 验证方式 |
|:-:|:-------|:---------|:---------|
| P1.1 | run_id列创建 | `SELECT run_id FROM a50_cross_ic_result LIMIT 5` 返回含NULL列，不报错 | SQL直接执行 |
| P1.2 | 第一次写入 | `SELECT run_id, COUNT(*) FROM a50_cross_ic_result WHERE run_id='test_run1' GROUP BY run_id` 返回值>0 | SQL COUNT |
| P1.3 | 进程终止后新run_id | 进程被终止（退出码非零或tasklist中进程消失），无Python异常栈残留 | `tasklist /FI "PID eq <pid>"` + 父进程日志检查 |
| P1.4 | 重启后新写入 | `SELECT run_id, COUNT(*) FROM a50_cross_ic_result WHERE run_id='test_run2' GROUP BY run_id` 返回值>0 | SQL COUNT |
| P1.5 | 两条run_id不重复 | `SELECT COUNT(DISTINCT run_id) FROM a50_cross_ic_result WHERE run_id IS NOT NULL` = 2 | SQL聚合 |
| P1.6 | 旧数据没被污染 | `SELECT COUNT(*) FROM a50_cross_ic_result WHERE run_id IS NULL` = 备份前旧数据行数 | 对比备份 |
| P1.7 | psutil日志存在 | 日志文件中包含 `[MemGuard]` 标记行 | grep检查 |
| P1.8 | 新source_version隔离 | `SELECT source_version, COUNT(*) FROM a50_cross_ic_result GROUP BY source_version` 区分v1和v1_repro | SQL聚合 |
| **P1.9** | **null_record source_version验证**（v2新增，v2.1保留） | `SELECT source_version, COUNT(*) FROM a50_cross_ic_result WHERE ic_value IS NULL AND source_version='v1_repro' GROUP BY source_version` → COUNT > 0 | SQL聚合确认v1_repro下存在null记录 |
| **P1.10** | **唯一索引不受run_id影响**（v2新增，v2.1保留） | `SELECT trade_date, factor_name, forward_window, source_version, COUNT(DISTINCT run_id), COUNT(*) FROM a50_cross_ic_result WHERE source_version='v1_repro' GROUP BY trade_date, factor_name, forward_window, source_version HAVING COUNT(*) > 1` → 返回0行（相同run_id不重复，不同run_id共存） | SQL聚合确认相同五列中最多1行/同run_id |

### 4.4 预估耗时

| 步骤 | 耗时 | 说明 |
|:----|:----:|:------|
| 代码改动部署 | 5 min | 已先做则不计入 |
| DB备份 + ALTER TABLE + 索引重建 | 2 min | cp操作 + 3条SQL |
| 第一次运行（3截面） | ~2 min | 极少量数据 |
| taskkill + 重启 | 1 min | taskkill终止进程 + 恢复 |
| 验证查询（含P1.9/P1.10） | 3 min | SQL执行 + 检查 |
| **总计** | **~13 min** | 不含代码改动 |

---

## 五、Phase 2：近5年重跑

### 5.1 前置条件

- Phase 1 **全部10项PASS标准均通过**（含P1.9和P1.10）
- DB已备份（`backup/a50_ic_{YYYYMMDD_HHMMSS}_pre_U2_repro.db`）
- 确认可用内存 ≥ 6GB（启动前检查，可在C7入口脚本通过`--min-memory 6.0`指定）

### 5.2 步骤

| 步骤 | 操作 | 说明 |
|:----:|:-----|:------|
| 2.1 | 备份 + 确认 | 与Phase 1同一备份DB，无需重复 |
| 2.2 | 首次运行：`--start-date 20210101 --end-date 20260526 --run-id repro_p1 --min-memory 6.0` | 覆盖近5年数据 |
| 2.3 | 若进程被终止：查看checkpoint获取pipeline_id → `--run-id repro_p2 --resume-from <pipeline_id>` | 调度器检测到非零退出码后手动执行 |
| 2.4 | 若完成：验证U1/U2 | 见PASS标准 |
| 2.5 | 若未触发OOM：跑 `--no-run --run-id repro_norun` | 模拟第三阶段写入 |

### 5.3 PASS标准

| # | 检查项 | PASS条件 | 验证方式 |
|:-:|:-------|:---------|:---------|
| P2.1 | run_id传递链 | 所有新写入行的run_id均不为NULL且等于传入值 | SQL COUNT run_id IS NOT NULL |
| P2.2 | run_id精确区分 | `SELECT run_id, COUNT(*) FROM a50_cross_ic_result WHERE source_version='v1_repro' GROUP BY run_id` = 预期（各进程行数可精确统计） | SQL聚合 |
| P2.3 | 旧数据隔离 | `SELECT COUNT(*) FROM a50_cross_ic_result WHERE source_version='v1'` = 备份前总量 | 对比快照 |
| **P2.4** | **psutil监控记录（v2量化标准，v2.1保留）** | **(a)** 日志中 `[MemGuard]` 标记出现次数 ≥ 总处理截面数 × 80%；**(b)** 日志可解析为CSV包含字段 [截面日期, phase, RSS_GB, Avail_GB] | 日志解析脚本统计 |
| P2.5 | OOM场景U1验证 | （若触发OOM）日志中最后一条 `[MemGuard]` 记录的时间 ≈ 进程被终止时的时间，证实杀前最后一截面已记录 | 时间戳对比 |
| P2.6 | --no-run的run_id | `SELECT COUNT(*) FROM a50_cross_ic_result WHERE run_id='repro_norun'` >0 | SQL |

### 5.4 预估耗时

| 场景 | 耗时 | 说明 |
|:----|:----:|:------|
| 近5年正常完成（不触发OOM） | ~60 min | 约5年数据，运行效率约2截面/min |
| 近5年 + 一次进程终止 + resume | ~80 min | 被杀1次 + 重启耗时 |
| 近5年 + 两次进程终止 | ~100 min | 最坏情况 |
| --no-run模式 | ~5 min | 跳过计算，仅写入 |

---

## 六、手动模拟进程终止方法（v2.1修正：原生Windows）

### 6.1 环境确认

| 维度 | v2.0假设（WSL2） | v2.1事实（原生Windows） |
|:-----|:----------------|:----------------------|
| 进程可见性 | WSL2内部进程从Windows侧不可见 | ✅ 原生Windows进程，tasklist/taskkill完全可见 |
| 终止指令 | 文件中杀法 / WSL内部kill -9 | ✅ taskkill /F /PID 直接可用 |
| 退出码语义 | 137 (128+9 SIGKILL) | Windows退出码（NTSTATUS）；Python MemoryError时退出码为1或特定异常码 |
| WSL内部进程 | 需 `wsl ps aux` 查看 | ❌ 不适用 |

### 6.2 v2.1推荐方案：taskkill（方案A）

**理由**：在原生Windows上，`taskkill /F /PID` 直接可用且最可靠，无需文件信号或其他间接方案。

**实现**：

在 `run_batch_streaming` 的每截面开头，插入可选的终止检测逻辑（备用，防止taskkill被杀死前未写入checkpoint）：

```python
import os

# 在for dt_str in dates_iter: 循环开头插入
KILL_FILE = os.path.join(self._checkpoint_dir, "KILL_NOW.signal")
if os.path.exists(KILL_FILE):
    logger.warning(
        "[KillSim] KILL_NOW.signal detected at section=%s, "
        "writing emergency checkpoint then exiting",
        dt_str,
    )
    os.remove(KILL_FILE)  # 清理信号
    # 写入紧急checkpoint标记当前断面
    self._write_checkpoint(
        processed_count=processed_count,
        last_completed_date=dt_str,
        all_completed_dates=completed_dates,
        start_date=date_std_start,
        end_date=date_std_end,
        step=step,
        pipeline_id=checkpoint_id,
        note="KILL_NOW_signal_termination",
    )
    import random, time
    time.sleep(random.uniform(0.1, 2.0))  # 模拟OOM时刻不确定性
    # 抛异常使进程优雅退出，让父进程捕获到退出码
    raise SystemExit("模拟进程终止 - KILL_NOW信号触发")
```

**触发方式（主方案：taskkill）**：

```powershell
# Step 1: 查找Python进程PID
tasklist /FI "IMAGENAME eq python*"
# 或通过日志找到PID

# Step 2: 强制终止
taskkill /F /PID <PID>

# Step 3: 确认进程已终止
tasklist /FI "PID eq <PID>"
# 应返回 "INFO: No tasks are running..."
```

**触发方式（备用方案：文件信号）**：

```powershell
# 创建信号文件触发优雅退出（比taskkill更温和，确保checkpoint写完）
# PowerShell
New-Item -Path schedules/checkpoints/KILL_NOW.signal -ItemType File -Force

# 或 cmd
# echo. > schedules/checkpoints/KILL_NOW.signal
```

### 6.3 退出码说明（v2.1修正）

| 场景 | 预期退出码/行为 | 检查方式 |
|:-----|:---------------|:---------|
| taskkill /F 终止 | 进程被TerminateProcess终止，退出码由Windows设置 | 父进程日志或 `$LASTEXITCODE` |
| Python MemoryError | Python抛出MemoryError，退出码通常为1 | 日志中可见MemoryError异常栈 |
| 文件信号优雅退出 | 0（SystemExit视为正常退出） | `$LASTEXITCODE` |
| 正常完成 | 0 | 日志中无异常标记 |

> **注意**：原生Windows下进程被OOM终止时，Python抛出`MemoryError`（可捕获），而不是收到类似Linux SIGKILL的不可处理信号。这与WSL2/Linux的行为有根本差异，也是U1中"杀前最后一截面"可捕获的关键前提。

---

## 七、OOM防护措施（贯穿所有阶段）

### 7.1 防护层级

| 层级 | 阈值 | 动作 | 实施位置 | 缺陷关联 |
|:----:|:----:|:-----|:--------|:--------:|
| L1 | 启动时 < 4GB（可配置） | 报错退出，不启动 | `_check_environment_health()` + C7 `--min-memory` | — |
| L2 | 运行时 < 3GB | 日志告警 + 内存采样 | 每截面开头 `[MemGuard]` | — |
| L3 | 运行时 < 2GB | 跳过当前截面（写标记NULL记录 + yield占位结果） | 每截面开头 `[MemGuard]` | C2-1 |
| L3.5 | 截面计算后异常低 | 截面后 `[MemGuard]` 双检告警（v2新增D3） | 每截面计算后 | D3 |
| L4 | 极端情况（接近0） | 写紧急日志 + 尝试优雅退出 | `signal.SIGTERM` handler | — |

### 7.2 额外防护（v2.1修正：Windows特有）

| 防护措施 | 说明 |
|:---------|:------|
| **降低并行度** | 单线程流式模式（已有），不改变 |
| **减少checkpoint IO** | checkpoint仅跟踪进度（已有）无需修改 |
| **页面文件检查** | 确认 `pagefile.sys` 大小 ≥ 系统推荐值（通常为物理内存的100%~150%）。若页面文件过小，即使大量物理内存可用也可能触发内存不足。通过 `wmic pagefile list /format:list` 或 `systeminfo` 查看 |
| **Windows Memory Diagnostic** | 若OOM频繁，运行 `mdsched.exe` 排除硬件问题 |
| **Python x64寻址确认** | Python 3.14+ 是64位，虚拟地址空间 > 16GB，单进程应无寻址限制。通过 `python -c "import sys; print(sys.maxsize)"` 确认（> 2^31 为64位） |

> v2.0中的`ulimit -v`降级方案仅在Linux/WSL2中有效，在原生Windows上无对应概念。已替换为Windows页面文件检查。

### 7.3 D3偏移说明（认知边界，v2.1保留但修正术语）

psutil检查点设置在截面循环开头（pre-check）和计算完成之后（post-check），而内存峰值可能发生在截面计算**中间**（因子加载、IC引擎计算）。
- pre-check → 看到充足内存→进入计算→因子数据加载→内存骤降→OOM
- post-check → 计算完成→内存已释放→看到健康状态

**认知边界**：psutil监控只能提供截面间的采样点数据，而非计算过程中的实时监控。"精确杀前内存"精度为**1截面偏差**（≈截面处理时长）。

**v2.1补充**：在原生Windows上，若OOM表现为Python `MemoryError`（而非TerminateProcess），则在try/except中可捕获异常并记录最后一截面的内存值——精度可提升至**同一截面内**。

---

## 八、数据隔离方案（同v2.0）

### 8.1 双重隔离策略

| 维度 | 隔离方式 | 值 |
|:-----|:---------|:----|
| **source_version** | 独立版本标识 | 旧：`'v1'` → 新：`'v1_repro'` |
| **run_id** | 逐运行标识 | `'repro_p1'` / `'repro_p2'` / `'repro_norun'` |

### 8.2 查询隔离规则

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

### 8.3 保险措施

| 措施 | 触发条件 | 操作 |
|:-----|:---------|:-----|
| DB全量备份 | Phase 1开始前 | `cp a50_ic.db backup/a50_ic_{timestamp}_pre_U2_repro.db` |
| 增量备份 | 每次重启前 | `cp a50_ic.db backup/a50_ic_{timestamp}_pre_restart{seq}.db` |
| SQLite元数据检查 | Phase 0执行前 | `SELECT sql FROM sqlite_master WHERE type IN ('view','trigger') AND sql LIKE '%a50_cross_ic_result%';`（确认无未过滤视图/触发器） |

---

## 九、--no-run模式实现说明（同v2.0，v2.1保留）

### 9.1 模式定位

`--no-run` 模式**不执行IC计算、不调用因子引擎**，仅用于模拟原始故障中的第三阶段（--no-run）写入场景。

### 9.2 实现伪代码（同v2.0）

```python
def run_no_run_mode(dm, run_id, source_version):
    conn = dm.get()
    existing = conn.execute("""
        SELECT DISTINCT trade_date, factor_name 
        FROM a50_cross_ic_result 
        WHERE source_version = ?
    """, (source_version,)).fetchall()
    for trade_date, factor_name in existing:
        conn.execute(
            """
            INSERT OR IGNORE INTO a50_cross_ic_result
                (trade_date, factor_name, ic_value, rank_ic, p_value,
                 num_stocks, adjusted_ic, source_version, created_at, run_id)
            VALUES (?, ?, NULL, NULL, NULL, 0, NULL, ?, datetime('now'), ?)
            """,
            (trade_date, factor_name, source_version, run_id),
        )
    conn.commit()
```

### 9.3 执行前提（同v2.0）

- 必须先完成正常重跑，确保 `source_version='v1_repro'` 已有数据
- 应在正常重跑完成后再执行 `--no-run`

---

## 十、预期产出与U1/U2确认

### 10.1 U1确认：psutil内存监控

| 结果场景 | 对U1的影响 | 结论 |
|:---------|:-----------|:-----|
| 触发OOM（MemoryError）+ 日志有最后一条[MemGuard]记录 | ✅ U1边界清晰：psutil可捕获"杀前最后一截面"数据，或MemoryError异常中记录的内存值 | U1从"系统限制"→"系统限制+单截面偏差" |
| 触发OOM（MemoryError）+ 日志在异常处理中捕获内存值 | ✅ U1边界大幅改善：可在异常处理中记录精确到截面内的内存状态 | 验证Windows下MemoryError可捕获 |
| 触发OOM + 日志缺失最后一条 | ⚠️ U1边界不变（进程被TerminateProcess瞬间终止，无通知机会） | 仅TerminateProcess场景存在此限制 |
| 未触发OOM | U1的定性不变：系统限制还是系统限制 | 但可通过小脚本独立验证psutil行为 |

**U1最终结论格式**：

```
U1：原生Windows环境下，Python进程被OOM终止时通常表现为MemoryError（可捕获），
    psutil运行时监控可提供"杀前最后一截面"内存记录（RSS+系统可用内存），
    形成完整内存增长曲线。
    即使被TerminateProcess直接终止，最后一条checkpoint + [MemGuard]记录
    仍可提供≈1截面精度的内存快照。
    → 信息缺口从"完全盲区"缩小为"0~1截面偏差"（优于WSL2的1~2截面偏差）。
```

### 10.2 U2确认：run_id精确区分

| 结果场景 | 对U2的影响 | 结论 |
|:---------|:-----------|:-----|
| Phase 1通过（含P1.9/P1.10） | ✅ run_id传递链+唯一索引含run_id+NULL数据隔离均验证通过 | U2从"需日志"→"可精确区分" |
| Phase 2通过 | ✅ 全量运行下run_id精确区分能力确认 | run_id是可靠的行级写入标识 |
| 未触发OOM | U2验证**不依赖OOM**，结论不变 | run_id的价值不依赖于运行是否异常 |
| 进程终止场景下run_id正确递增 | ✅ 验证调度器重启传递链畅通 | 覆盖了原始故障场景 |

**U2最终结论格式**：

```
U2：新增run_id列 + 独立source_version(v1_repro) + 唯一索引含run_id可精确区分多次运行的写入量。
    SELECT GROUP BY run_id 可精确报告各进程行数。
    调度器重启时通过传入不同run_id + --resume-from实现传递链。
    → 原始故障中U2所列的"不确定性"已被消除。
    【注意】根因（OOM）未被修复，仅可观测性边界被清除。
```

### 10.3 产出物清单

| # | 产出物 | 说明 |
|:-:|:-------|:-----|
| 1 | 代码改动diff | `cross_sectional_ic_pipeline.py` + `scheduler.py` + `run_pipeline_experiment.py` 的diff |
| 2 | 运行日志 | `pipeline_logs/` 目录下的各次运行日志 |
| 3 | SQL验证结果 | run_id分组统计 + source_version隔离确认 + 唯一索引验证 |
| 4 | psutil内存曲线 | 从日志提取 `[MemGuard]` 记录形成的截面索引→RSS曲线 |
| 5 | 结论报告 | U1/U2的最终可观测性边界声明 |
| 6 | 代码检讨建议 | 针对OOM根因（内存泄露趋势）的分析代码修改建议 |

---

## 十一、风险管理

### 11.1 风险矩阵

| # | 风险 | 概率 | 影响 | 缓解措施 |
|:-:|:-----|:----:|:----:|:---------|
| R1 | Phase 1发现run_id传递链断裂 | 中 | 高——全量白跑 | Phase 1的定位就是发现此问题，修复后重试 |
| R2 | ALTER TABLE + DROP INDEX失败 | 低 | 高——阻塞所有后续 | SQLite测试先行；备份可回退 |
| R3 | 重跑触发OOM导致测试环境不稳定 | 高 | 中——近5年也可能OOM | 严格执行L2/L3内存保护；降低checkpoint频率 |
| R4 | 重跑数据污染生产查询 | 低 | 高——基线/IC计算错误 | source_version隔离 + 查询脚本显式过滤 + 执行前sqlite_master检查 |
| R5 | 原生Windows环境与Linux/Docker生产环境的差异导致结论不可推广 | 中 | 中——psutil行为一致，进程终止语义不同 | 结论文档中明确标注环境差异（附录C已包含完整环境说明） |
| R6 | 日志文件过大撑满磁盘 | 低 | 低 | RotatingFileHandler + 每截面日志量很小 |

### 11.2 失败预案

| 场景 | 处理方式 |
|:-----|:---------|
| Phase 1 FAIL | 检查错误，修复对应代码改动，重走Phase 1 |
| Phase 2 连续三次OOM | 缩小范围到最近2年；或接受OOM场景下U1验证直接完成，启动--no-run验证U2 |
| Phase 2 正常完成（不触发OOM） | U2验证不受影响，U1走小脚本独立验证 |
| DB损坏 | 从备份恢复，检查前一次备份的完整性 |

---

## 十二、验收条目

| # | 验收标准 | 责任方 |
|:-:|:---------|:-------|
| A1 | 试验方案是否完整覆盖U1/U2的可观测性边界 | 墨萱（QA） |
| A2 | 代码改动是否最小侵入、不破坏现有功能（含from_config透传） | 玄知（架构） |
| A3 | Phase 1的PASS标准是否合理可量化（含新增P1.9/P1.10） | 墨萱（QA） |
| A4 | 数据隔离方案是否完整（source_version + run_id + 唯一索引含run_id三重隔离） | 玄知（架构） |
| A5 | OOM防护是否足够（逐截面pre/post双检 + 三级阈值 + yield占位） | 墨萱（QA） |
| A6 | 试验结论（U1/U2边界）是否可追溯验证 | 墨萱（QA） |
| A7 | 方案是否考虑了原生Windows vs Linux/Docker的环境差异（附录C v2.1重写） | 玄知（架构） |

---

## 附录A：关键SQL查询合集（v2.1版，同v2.0）

```sql
-- A1: 备份前历史数据基准
SELECT COUNT(*) as total_rows,
       COUNT(DISTINCT trade_date) as unique_dates,
       COUNT(DISTINCT factor_name) as unique_factors
FROM a50_cross_ic_result WHERE source_version = 'v1';

-- A2: run_id列存在性 + 新唯一索引确认
PRAGMA table_info(a50_cross_ic_result);
PRAGMA index_info(idx_ic_uniq_v2);

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

-- A6: 新唯一索引正确性验证（包含run_id，同run_id内部防重）
SELECT trade_date, factor_name, forward_window, source_version, run_id, COUNT(*)
FROM a50_cross_ic_result
GROUP BY trade_date, factor_name, forward_window, source_version, run_id
HAVING COUNT(*) > 1;
-- 应返回0行（同run_id内部无重复）

-- A7: 不同run_id同截面可共存
SELECT trade_date, factor_name, forward_window, source_version, 
       COUNT(DISTINCT run_id) as run_id_count,
       COUNT(*) as total_rows
FROM a50_cross_ic_result
WHERE source_version = 'v1_repro'
GROUP BY trade_date, factor_name, forward_window, source_version
HAVING run_id_count > 1;
-- 应返回行数 > 0（不同run_id在同截面共存）

-- A8: P1.9 null_record source_version一致性（v2新增，v2.1保留）
SELECT source_version, COUNT(*) as null_records
FROM a50_cross_ic_result
WHERE ic_value IS NULL AND source_version = 'v1_repro'
GROUP BY source_version;
-- 预期：COUNT > 0

-- A9: P1.10 唯一索引不受run_id影响（v2新增，v2.1保留）
SELECT trade_date, factor_name, forward_window, source_version, 
       COUNT(DISTINCT run_id) as distinct_run_ids
FROM a50_cross_ic_result
WHERE source_version = 'v1_repro'
GROUP BY trade_date, factor_name, forward_window, source_version
HAVING COUNT(*) > 1 AND COUNT(DISTINCT run_id) = 1;
-- 预期：0行（同run_id内同一截面不重复）
```

## 附录B：预估总耗时（v2.1无变化）

| 阶段 | 内容 | 耗时 | 能否并行 |
|:----:|:-----|:----:|:--------:|
| Phase 0 | 代码改动 + ALTER TABLE + DROP/CREATE索引 | ~50 min | 仅串联 |
| Phase 1 | small-scale验证（含P1.9/P1.10） | ~15 min | 仅串联 |
| — | 中间等待（评审） | ~30 min | 可并行 |
| Phase 2 | 近5年重跑 | ~60~100 min | 仅串联 |
| Phase 3（可选） | 全量重跑 | ~180 min | 仅串联 |
| 结论整理 | 文档 + 验证报告 | ~20 min | 可与Phase 2/3并行 |
| **总耗时（含Phase 1+2）** | | **~155~195 min** | |

> 建议执行时间窗口：凌晨 01:00~05:00（避开交易时段，原生Windows上无额外限制）
> Phase 2若在夜间执行且正常完成，Phase 3可视资源情况立即跟进

## 附录C：环境确认清单（v2.1重写 — 原生Windows）

| 检查项 | 值 | 确认状态 | v2.1备注 |
|:-------|:---|:--------:|:---------|
| OS | Windows 11 x64 (build 26200) | ⏳ 待确认 | ❌ v2.0误写为"WSL2" |
| Python | 3.14+（原生Windows，非WSL2） | ⏳ 待确认 | sys.platform应为win32 |
| Python x64寻址能力 | 64位，虚拟地址空间 >> 16GB | ⏳ 待确认 | `python -c "import sys; print(sys.maxsize)"` 验证（>2^31为64位） |
| psutil | 已安装，原生Windows支持 | ⏳ 待确认 | `python -c "import psutil; print(psutil.virtual_memory())"` 验证 |
| SQLite | 默认（ALTER TABLE ADD COLUMN + DROP INDEX 支持） | ⏳ 待确认 | — |
| 磁盘空间 | ≥ 1GB 可用（日志+DB备份） | ⏳ 待确认 | — |
| 内存 | ≥ 8GB 可用（启动后） | ⏳ 待确认 | — |
| 页面文件(pagefile.sys) | 大小 ≥ 系统推荐值 | ⏳ 待确认 | Windows特有；`wmic pagefile list /format:list` 或 `systeminfo` 查看 |
| 调度器 | 无自动重启机制（手动重启） | ⏳ 待确认 | — |
| **Windows Event Log**（v2.1新增） | 可配置到System日志记录内存事件 | ⏳ 待确认 | 进程被终止时，eventvwr.msc → Windows Logs → System 可能有相关记录 |
| **perfmon可用性**（v2.1新增） | Windows Performance Monitor可附加监控python.exe | ⏳ 待确认 | 可使用 `perfmon /sys` 快速添加进程计数器（Working Set, Private Bytes） |
| **进程终止行为**（v2.1新增） | OOM表现为 Python MemoryError（可捕获） | ⏳ 待确认 | ❌ v2.0误用Linux SIGKILL语义。原生Windows下Python OOM通常为MemoryError异常 |
| **父进程退出码捕获**（v2.1新增） | OpenClaw Node.js作为父进程可捕获子进程退出码 | ⏳ 待确认 | 通过 `child.on('exit', code => ...)` 捕获 |
| **进程层次**（v2.1新增） | OpenClaw→Python subprocess（不是WSL2） | ⏳ 待确认 | 任务管理器可看到python.exe为node.exe的子进程 |
| **文件路径类型**（v2.1新增） | 全部使用Windows路径（如 `C:\Users\...`），无交叉文件系统IO | ⏳ 待确认 | ❌ v2.0中WSL2跨文件系统的10x性能损失在此不适用 |

## 附录D：v1→v2→v2.1变更对照

### D1：v1→v2 变更（v2.1保留）

| 缺陷ID | v1问题 | v2修复 | 影响区域 |
|:------:|:-------|:-------|:---------|
| **D2** | 唯一索引不含run_id，重启后新run_id写同截面被INSERT OR IGNORE静默跳过 | 方案A：DROP旧索引→CREATE含run_id的新唯索引 | C5、附录A |
| **C1-1/D5** | `_build_null_record` 硬编码 `source_version='v1'`，null记录污染生产数据 | 改为实例方法，使用 `self.source_version` | C1a、§3.2改动点③ |
| **SIGKILL-1** | 推荐 `taskkill /F /PID` 在WSL2中不可用 | 文件信号自杀法（方案B）为首选，WSL内部kill为备用 | **§六（v2.1已废弃，替换为taskkill方案）** |
| **D1** | from_config未透传run_id；入口脚本无--resume-from | from_config新增run_id参数；入口脚本新增--resume-from | C4、C7 |
| **C1-2** | --no-run模式无实现说明 | 新增§九完整实现描述 + 伪代码 | §九 |
| **C2-1** | 跳过截面时直接continue不yield，聚合器计数不准确 | 跳过时yield占位结果 | C2、§3.3 |
| **D3** | psutil检查仅在截面循环开头，与计算峰值偏移 | 新增截面计算后 `[MemGuard]` post-check双检 | C2、§3.3 §7.3 |
| **缺失P1.9** | 无null record source_version验证 | 新增P1.9 | §4.3 |
| **缺失P1.10** | 无唯一约束确认 | 新增P1.10 | §4.3 |
| **P2.4模糊** | "形成完整内存曲线"不可测量 | 量化标准：≥80%截面有[MemGuard]记录 + 可解析为CSV | §5.3 |
| **D4** | 附录C遗漏5项环境差异 | 附录C补充SIGKILL行为、ulimit支持、内存回收、IO性能、psutil准确性 | 附录C（v2.1已重写） |

### D2：v2→v2.1 新增变更

| 缺陷ID | v2问题 | v2.1修复 | 影响区域 |
|:------:|:-------|:---------|:---------|
| **SIGKILL-1.1** | 基于错误假设（WSL2）选择了文件信号自杀法 | 恢复taskkill方案；保留文件信号为备用 | §六（全文重写） |
| **ENV-v2.1** | 全线使用Linux/WSL2术语（SIGKILL, exit 137, dmesg, ulimit等） | 替换为Windows/Python术语（进程终止, MemoryError, Event Log, 页面文件等） | 全文 |
| **附录C重写** | 附录C含6项WSL2特有检查（dmesg, ulimit, cgroup, 跨文件系统IO, .wslconfig, SIGKILL行为） | 替换为Windows原生项（页面文件, Event Log, perfmon, Python x64寻址, 进程层次） | 附录C |
| **U1结论修正** | U1结论基于"SIGKILL+WSL2"场景表述 | 修正为"MemoryError可捕获 + TerminateProcess边界"的双场景表述 | §10.1 |
| **§7.2防护** | ulimit降级方案（仅Linux有效） | 替换为页面文件检查 + Windows Memory Diagnostic | §7.2 |
| **§六退出码** | 含"退出码137=128+9"等Linux语义 | 修正为Windows NTSTATUS/Python异常语义 | §6.3 |

---

*EOF — v2.1 | status=DRAFT | 等待墨萱+玄知评审 | 修正运行环境：原生Windows 11 x64*
