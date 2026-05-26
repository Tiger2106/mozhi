---
title: ingest_analysis.py 技术设计方案
author: 墨衡
version: v1.1
created: 2026-05-23T15:10:00+08:00
status: reviewed
updated: 2026-05-23T15:16:00+08:00
reviewer: 墨萱
changelog: "6项修复: DataSource接口+根路径+时间戳+外键检查+perf_row错误+测试路径"
based_on: ingest_analysis_requirements_v1.0.md
supersedes: finalize_v4.py
---

# ingest_analysis.py 技术设计方案 v1.0

---

## 目录

1. [架构总览](#一架构总览)
2. [模块设计与接口签名](#二模块设计与接口签名)
3. [Pipeline.run() 完整流程图](#三pipelinerun-完整流程图)
4. [数据模型（model.py）](#四数据模型modelpy)
5. [SQL 读写语句示例](#五sql-读写语句示例)
6. [错误处理链路](#六错误处理链路)
7. [日志格式模板](#七日志格式模板)
8. [归档实现细节](#八归档实现细节)
9. [CLI 主入口](#九cli-主入口)
10. [幂等性与事务实现](#十幂等性与事务实现)
11. [文件结构一览](#十一文件结构一览)
12. [与 pyproject.toml 集成](#十二与-pyprojecttoml-集成)

---

## 一、架构总览

### 1.1 四阶段管道

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Pipeline.run()                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│  │DataSource│ →  │Transform │ →  │Validator │ →  │ Writer   │      │
│  │          │    │          │    │          │    │          │      │
│  │ 从DB读取 │    │ 字段映射 │    │ 前置校验 │    │ 事务写入 │      │
│  │ 回测指标 │    │ 类型转换 │    │ 空值校验 │    │ 5张表   │      │
│  │ 发现文件 │    │ model填充 │   │ 交叉核验 │    │ 归档文件 │      │
│  │ 计算hash│    │          │    │ 权力等级 │    │ .done信号 │     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 模块依赖关系

```
pipeline.py
  ├── model.py      ← Pydantic BaseModel 定义
  ├── transformer.py ← 使用 model.py
  ├── validator.py   ← 使用 model.py, transformer.py 的输出
  └── writer.py      ← 使用 model.py，执行 DB + 归档
```

### 1.3 松耦合原则

- 所有模块 **不 import** `backtest_engine.py`、`trade_logger`、`position_manager` 等运行时模块
- 只通过 SQLite SELECT 读取 `backtest_run`、`performance_summary` 等 V3 表
- 只写入 5 张分析层表（V4）：`analysis_meta`、`analysis_metrics_core`、`analysis_metrics_ext`、`analysis_docs`、`schema_version`

---

## 二、模块设计与接口签名

### 2.1 `pipeline.py` — 主入口 / Pipeline 协调器

```python
class Pipeline:
    """四阶段管道协调器"""

    def __init__(self, db_path: str | Path, run_id: str, analysis_type: str,
                 dry_run: bool = False, qa_verify: bool = False,
                 force: bool = False, timeout: int = 65, verbose: bool = False):
        ...

    def run(self) -> PipelineResult:
        """执行完整管道，返回结构化结果"""

class PipelineResult(TypedDict, total=False):
    status: str                    # "SUCCESS" | "WARN" | "ERROR" | "FATAL"
    run_id: str
    analysis_type: str
    operation: str                 # "INSERT" | "UPDATE" | "SKIP"
    analysis_meta_id: int | None
    rows_written: dict[str, int]   # 各表行数
    qa_report: dict | None         # --qa-verify 时输出
    total_duration_ms: float
    error: str | None
    warnings: list[str]
```

**public API**（在 `__init__.py` 暴露）：

```python
def ingest(run_id: str, analysis_type: str, **kwargs) -> PipelineResult:
    """便捷入口函数"""
```

### 2.2 `model.py` — 数据模型 / Pydantic 定义

```python
class AnalysisMeta(BaseModel):
    run_id: str
    analysis_type: Literal["summary", "deep_analysis", "tech_review", "validation", "resolution"]
    author: str = "moheng"
    version_schema: str = "1.0"
    version_content: int = 1
    version_status: str = "draft"    # draft | reviewed | final | archived
    parent_session_id: int | None = None
    tags: list[str] = Field(default_factory=list)

class MetricsCore(BaseModel):
    analysis_id: int | None = None    # 写入前未知
    run_id: str
    metric_group: Literal["daily", "weekly", "param_sweep", "factor_ic"]
    total_return_pct: float | None = None
    annual_return_pct: float | None = None
    final_equity: float | None = None
    total_pnl: float | None = None
    benchmark_return_pct: float | None = None
    excess_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    annual_volatility_pct: float | None = None
    sharpe_ratio: float | None = None
    calmar_ratio: float | None = None
    sortino_ratio: float | None = None
    var_95_pct: float | None = None
    total_trades: int | None = None
    winning_trades: int | None = None
    losing_trades: int | None = None
    win_rate_pct: float | None = None
    total_profit: float | None = None
    total_loss: float | None = None
    profit_loss_ratio: float | None = None
    max_consecutive_wins: int | None = None
    max_consecutive_losses: int | None = None
    max_single_win: float | None = None
    max_single_loss: float | None = None
    verdict: str | None = None
    risk_level: Literal["low", "mid", "high"] | None = None
    core_issue: str | None = None
    improvement_potential: str | None = None

class MetricsExt(BaseModel):
    analysis_id: int | None = None
    run_id: str
    metric_group: str | None = None
    metric_name: str
    metric_value: float
    metric_label: str | None = None

class AnalysisDoc(BaseModel):
    analysis_id: int | None = None
    run_id: str
    doc_type: Literal["summary_report", "analysis_report", "tech_review", "validation", "resolution"]
    file_path: str
    content_hash: str | None = None
    file_size_bytes: int = 0
    word_count: int | None = None

class PipelineInput(BaseModel):
    """管道输入 —— 所有阶段共享的上下文"""
    meta: AnalysisMeta
    metrics_core: list[MetricsCore]         # 1~5行
    metrics_ext: list[MetricsExt]           # N行
    docs: list[AnalysisDoc]                 # 1~6行
```

### 2.3 `transformer.py` — 字段映射 / 类型转换

```python
class Transformer:
    """从 V3 层表数据 → PipelineInput"""

    def __init__(self, db_path: str | Path):
        ...

    def transform(self, run_id: str, analysis_type: str,
                  perf_row: dict | None = None) -> PipelineInput:
        """
        从 performance_summary 表行 + 人工补充参数，
        转换为 PipelineInput 供后续阶段使用。

        返回 Pydantic 校验后的 PipelineInput 实例。

        Raises:
            DataSourceError: 当 perf_row 为 None 时，抛出语义化错误
                             "未找到 performance_summary 记录：run_id={run_id}"
        """
        if perf_row is None:
            raise DataSourceError(f"未找到 performance_summary 记录：run_id={run_id}")

    def _map_perf_to_metrics_core(self, perf_row: dict, metric_group: str = "daily") -> MetricsCore:
        """将 performance_summary 的一行映射到 MetricsCore"""

    def _compute_content_hash(self, file_path: str | Path) -> str:
        """计算 SHA256 哈希"""
```

**字段映射对照表（performance_summary → analysis_metrics_core）：**

| performance_summary | analysis_metrics_core | 类型转换 |
|:--------------------|:---------------------|:---------|
| total_return | total_return_pct | direct (float) |
| annualized_return | annual_return_pct | direct |
| benchmark_return | benchmark_return_pct | direct |
| excess_return | excess_return_pct | direct |
| max_drawdown | max_drawdown_pct | direct |
| sharpe_ratio | sharpe_ratio | direct |
| calmar_ratio | calmar_ratio | direct |
| sortino_ratio | sortino_ratio | direct |
| volatility | annual_volatility_pct | direct |
| var_95_pct | var_95_pct | direct |
| win_rate | win_rate_pct | direct |
| total_trades | total_trades | int conversion |
| max_consecutive_wins | max_consecutive_wins | direct |
| max_consecutive_losses | max_consecutive_losses | direct |
| final_equity | final_equity | direct |
| - | total_pnl | final_equity - 初始资金 |
| - | total_profit | NULL (需从 trade_log 聚合) |
| - | total_loss | NULL |
| - | profit_loss_ratio | NULL |
| - | verdict | 从上下文推导 |
| - | risk_level | 从上下文设置 |
| - | core_issue | 从分析报告提取 |
| - | improvement_potential | 从分析报告提取 |

### 2.4 `validator.py` — 数据校验 / 交叉核验

```python
class ValidationResult(BaseModel):
    passed: bool
    level: Literal["PASS", "WARN", "ERROR"]   # 错误等级
    checks: list[CheckResult]                  # 每条检查明细

class CheckResult(BaseModel):
    name: str
    passed: bool
    level: Literal["PASS", "WARN", "ERROR"]
    detail: str
    value: Any = None
    expected: Any = None

class Validator:
    def __init__(self, db_path: str | Path):
        ...

    def validate(self, input_data: PipelineInput) -> ValidationResult:
        """
        执行所有校验项目，每条检查独立评分。
        """
        ...

    # ——— 内部检查方法 ———

    def _check_run_id_exists(self, run_id: str) -> CheckResult:
        """前置校验1: run_id 在 backtest_run 中存在且 status='done'"""

    def _check_not_null(self, input_data: PipelineInput) -> CheckResult:
        """前置校验2: 必填字段非空 (run_id, analysis_type, version_status)"""

    def _check_enum_values(self, input_data: PipelineInput) -> CheckResult:
        """校验3: analysis_type 枚举值合法"""

    def _check_cross_validate(self, input_data: PipelineInput,
                              perf_row: dict) -> CheckResult:
        """
        校验5: 输入指标 vs performance_summary 交叉核验
        - 偏差 ≤ 0.01% → PASS
        - 偏差 0.01% ~ 0.1% → WARN
        - 偏差 > 0.1% → ERROR
        """

    def _check_docs_exist(self, input_data: PipelineInput) -> CheckResult:
        """校验6: analysis_docs.file_path 对应文件存在于磁盘"""

    def _check_idempotent(self, run_id: str, analysis_type: str) -> CheckResult:
        """幂等性检查: 返回已存在记录的状态"""

    def _check_foreign_key(self, analysis_id: int, run_id: str) -> CheckResult:
        """
        校验7: analysis_metrics_core.analysis_id → analysis_meta.id 外键存在性
        确保 metrics_core 的 analysis_id 在 analysis_meta 中有对应记录。

        注意：本检查在写入阶段（Writer.write）中获得 analysis_id 后执行，
        不在前置校验阶段（Validator.validate）中提前触发（因为此时 analysis_id 尚未分配）。
        """
```

### 2.5 `writer.py` — SQLite 事务写入 / 归档

```python
class WriteResult(BaseModel):
    status: str                         # "SUCCESS" | "WARN" | "ERROR"
    operation: str                      # "INSERT" | "UPDATE" | "SKIP"
    analysis_meta_id: int | None
    rows_written: dict[str, int]
    doc_archive_results: list[dict]
    qa_report: dict | None

class Writer:
    def __init__(self, db_path: str, archive_root: str | Path):
        self.db_path = db_path
        self.archive_root = Path(archive_root)  # e.g., mozhi_platform/archive/
        ...

    def write(self, input_data: PipelineInput,
              validation: ValidationResult,
              force: bool = False, dry_run: bool = False) -> WriteResult:
        """
        事务包裹全部写入 + 归档。

        流程:
        1. 检查幂等性 (SELECT run_id + analysis_type)
        2. 确定操作类型 (INSERT / UPDATE / SKIP)
        3. 开启事务 BEGIN
        4. 写入/更新 analysis_meta
        5. CASCADE 删除旧附属记录 (如果UPDATE)
        6. 写入 analysis_metrics_core (1~5行)
        7. 写入 analysis_metrics_ext (N行)
        8. 写入 analysis_docs (1~6行)
        9. 写入 schema_version (UPSERT)
        10. COMMIT
        11. 执行文件归档 (先DB后文件)
        12. 归档失败时 UPDATE analysis_docs SET file_size_bytes=-1
        """

    # ——— 内部方法 ———

    def _check_idempotent(self, run_id: str, analysis_type: str) -> dict | None:
        """SELECT 查重"""

    def _write_meta(self, tx: sqlite3.Connection, meta: ...) -> int:
        """INSERT or UPDATE analysis_meta, 返回 new_id"""

    def _write_metrics_core(self, tx: sqlite3.Connection,
                            analysis_id: int, metrics: ...) -> int:
        """批量 INSERT analysis_metrics_core"""

    def _write_metrics_ext(self, tx: sqlite3.Connection,
                           analysis_id: int, metrics: ...) -> int:
        """批量 INSERT analysis_metrics_ext"""

    def _write_docs(self, tx: sqlite3.Connection,
                    analysis_id: int, docs: ...) -> int:
        """批量 INSERT analysis_docs (UNIQUE分析ID+类型)"""

    def _upsert_schema_version(self, tx: sqlite3.Connection) -> None:
        """schema_version UPSERT"""

    def _archive_docs(self, new_docs: list[AnalysisDoc],
                      existing_meta: dict | None) -> list[dict]:
        """
        归档文件（先DB后文件策略中的第二步）。

        返回每份文档的归档结果：
        [{doc_type, src, dst, status, content_hash, file_size_bytes, error}]
        """

    def _archive_single_file(self, src: Path, dst_root: Path) -> dict:
        """单文件归档，含版本化重命名逻辑"""

    def _handle_archive_failure(self, analysis_id: int, new_docs: list) -> None:
        """归档失败: UPDATE analysis_docs SET file_size_bytes=-1"""

    def _write_failed_signal(self, run_id: str, analysis_type: str,
                             error: str) -> None:
        """写入 .failed 信号文件"""
```

### 2.6 `datasource.py` — 数据源读取 / 文件发现

```python
class DataSource:
    """从 V3 层数据库读取回测指标 + 自动发现分析报告文件"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ...

    def fetch(self, run_id: str) -> tuple[dict | None, list[dict]]:
        """
        读取 performance_summary + 自动发现分析报告文件。

        返回:
            perf_row: 从 performance_summary 读取的指标行 (dict), 无记录时返回 None
            doc_files: 自动发现的报告文件列表
                       [{doc_type, file_path, content_hash, file_size_bytes}, ...]
        """

    # ——— 内部方法 ———

    def _fetch_perf_row(self, run_id: str) -> dict | None:
        """从 performance_summary 读取指标行 (WHERE run_id=? ORDER BY id DESC LIMIT 1)"""

    def _discover_report_files(self, run_id: str) -> list[dict]:
        """
        目录轮询: 扫描 reports/{analysis_type}/{run_id}/ 下按 doc_type 约定命名的文件
        返回每个匹配文件的元信息 (含 content_hash + 文件大小)
        """

    def _compute_content_hash(self, file_path: str | Path) -> str:
        """计算 SHA256 文件哈希"""
```

**关于 DataSource 的设计要点：**

1. **单次读取**：`fetch()` 执行 1 次 SQL SELECT + 1 次目录扫描，不维持 DB 连接状态
2. **perf_row 为空**：直接返回 `None`，由 Transformer 阶段处理语义化错误
3. **文件发现策略**：按 `doc_type` 在 `reports/{analysis_type}/{run_id}/` 目录下模糊匹配（命名规则：`{doc_type}_{run_id}.md`）
4. **可测试性**：通过 mock `db_path`（指向测试 SQLite 文件）和 mock 目录结构，可在无真实数据时单元测试

---

## 三、Pipeline.run() 完整流程图

```
Pipeline.run(run_id, analysis_type, ...)
│
├─ 1. INIT
│    ├─ 初始化 DataSource
│    ├─ 初始化 Transformer
│    ├─ 初始化 Validator
│    ├─ 初始化 Writer
│    ├─ 记录 start_time
│    └─ 写入日志: [START] ingest pipeline
│
├─ 2. DATA SOURCE PHASE
│    ├─ 连接 DB, 从 backtest_run 读取 run_id 验证
│    ├─ 从 performance_summary 读取指标行 (WHERE run_id=?)
│    ├─ 自动发现分析报告文件 (目录轮询, 匹配 doc_type)
│    ├─ 计算每个文件的 SHA256 content_hash
│    ├─ 计算文件大小
│    └─ 输出: perf_row (dict) + 文件列表
│
├─ 3. TRANSFORM PHASE
│    ├─ Transformer.transform(perf_row) → PipelineInput
│    ├─ 字段映射 + 类型转换
│    ├─ Pydantic 校验 (自动触发)
│    ├─ 若校验失败 → raise TransformError
│    └─ 输出: validated PipelineInput
│
├─ 4. VALIDATE PHASE
│    ├─ Validator.validate(PipelineInput) → ValidationResult
│    │    ├─ _check_run_id_exists
│    │    ├─ _check_not_null
│    │    ├─ _check_enum_values
│    │    ├─ _check_cross_validate (perf_row vs input)
│    │    └─ _check_docs_exist
│    │
│    ├─ 输出: ValidationResult
│    │
│    ├─ [WARN] 等级检查 → 记录警告, 继续
│    ├─ [ERROR] 等级检查 → raise ValidationError
│    └─ [PASS] → 继续
│
├─ 5. [DRY-RUN] 判定
│    ├─ if dry_run:
│    │    ├─ 输出完整校验报告 (含 ValidationResult)
│    │    ├─ 写入日志: [DRY-RUN] completed
│    │    ├─ 计算总耗时
│    │    └─ return PipelineResult(status="DRY_RUN", ...)
│    └─ else: 继续
│
├─ 6. IDEMPOTENT CHECK (Writer 内部)
│    ├─ SELECT FROM analysis_meta WHERE run_id=? AND analysis_type=?
│    │
│    ├─ 情况 A: 不存在 → 操作 = INSERT
│    ├─ 情况 B: 存在 draft → 操作 = UPDATE (version_content+1)
│    │    └─ 同时检查 docs.file_size_bytes==-1 → 计划重试归档
│    ├─ 情况 C: 存在 final → 操作 = SKIP
│    │    └─ unless force=True → 操作 = UPDATE (标记为 reviewed)
│    │
│    └─ 写入日志: [IDEMPOTENT] action=INSERT|UPDATE|SKIP
│
├─ 7. WRITE PHASE (事务包裹)
│    ├─ BEGIN TRANSACTION
│    │
│    ├─ step 7a: INSERT/UPDATE analysis_meta
│    ├─ step 7b: CASCADE DELETE metrics_core/ext/docs WHERE analysis_id=?
│    │            (仅 UPDATE 时, 清除旧行再插入)
│    ├─ step 7c: INSERT analysis_metrics_core (1~5行)
│    ├─ step 7d: INSERT analysis_metrics_ext (N行)
│    ├─ step 7e: INSERT analysis_docs (1~6行)
│    │            (注意 UNIQUE(analysis_id, doc_type) 约束)
│    ├─ step 7f: UPSERT schema_version (version="4.0")
│    │
│    └─ COMMIT
│         ├─ 成功: 继续步骤8
│         └─ 失败 (sqlite3.Error): ROLLBACK, raise WriteError
│
├─ 8. ARCHIVE PHASE (DB 事务外)
│    ├─ 收集待归档文件列表 (来自 analysis_docs)
│    ├─ 对每份文件:
│    │    ├─ 计算目标路径: archive/reports/{filename}
│    │    ├─ 文件已存在且 hash 一致 → SKIP
│    │    ├─ 文件已存在但 hash 不同 → 版本化重命名
│    │    ├─ 文件不存在 → 正常 copy2
│    │    └─ 失败 → 记录错误, UPDATE file_size_bytes=-1
│    ├─ 归档 DDL 文件 (从 Downloads 发现)
│    └─ 输出: 归档结果列表
│
├─ 9. [QA-VERIFY] 判定
│    ├─ if qa_verify:
│    │    ├─ 重新 SELECT 各表行数
│    │    ├─ 交叉验证 (meta id vs metrics_core.analysis_id)
│    │    ├─ 幂等对比 (前/后数据差异)
│    │    ├─ 输出 QA 报告
│    │    └─ 写入日志: [QA] report generated
│    └─ else: 跳过
│
├─ 10. COMPLETION
│    ├─ 写入 .done 信号文件
│    │    ├─ 路径: {task_id}_moheng.done (仅被调度场景)
│    │    └─ 格式: {status, run_id, analysis_type, timestamp}
│    ├─ 写入成功日志: [END] pipeline completed
│    ├─ 计算 total_duration_ms
│    └─ return PipelineResult(status="SUCCESS"|"WARN", ...)
│
└─ ERROR HANDLING (任意阶段)
     ├─ WARN level: 记录警告, 继续
     ├─ ERROR level:
     │    ├─ 如果已开启事务 → ROLLBACK
     │    ├─ 写入 .failed 信号文件
     │    ├─ 写入错误日志 (含堆栈+数据)
     │    └─ raise PipelineError / return ERROR
     └─ FATAL level (DB连接失败/磁盘满):
          ├─ 写入 ERROR 日志 (无 .failed)
          └─ 告警墨涵 (仅日志标记)
```

---

## 四、数据模型（model.py）

### 4.1 `PipelineInput` 完整定义

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from datetime import datetime, timezone, timedelta

# ——— 辅助函数 ———

def _now_iso() -> str:
    """返回 ISO8601 +08:00 时间戳"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S%z")

# ——— Enum 常量 ———

ANALYSIS_TYPES = Literal["summary", "deep_analysis", "tech_review", "validation", "resolution"]
METRIC_GROUPS = Literal["daily", "weekly", "param_sweep", "factor_ic"]
DOC_TYPES = Literal["summary_report", "analysis_report", "tech_review", "validation", "resolution"]
VERSION_STATUSES = Literal["draft", "reviewed", "final", "archived"]
RISK_LEVELS = Literal["low", "mid", "high"]

# ——— 模型 ———

class AnalysisMeta(BaseModel):
    run_id: str = Field(..., min_length=1)
    analysis_type: ANALYSIS_TYPES
    author: str = "moheng"
    version_schema: str = "1.0"
    version_content: int = 1
    version_status: VERSION_STATUSES = "draft"
    parent_session_id: int | None = None
    tags: list[str] = Field(default_factory=list)

class MetricsCore(BaseModel):
    run_id: str
    metric_group: METRIC_GROUPS = "daily"
    total_return_pct: float | None = None
    annual_return_pct: float | None = None
    final_equity: float | None = None
    total_pnl: float | None = None
    benchmark_return_pct: float | None = None
    excess_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    annual_volatility_pct: float | None = None
    sharpe_ratio: float | None = None
    calmar_ratio: float | None = None
    sortino_ratio: float | None = None
    var_95_pct: float | None = None
    total_trades: int | None = None
    winning_trades: int | None = None
    losing_trades: int | None = None
    win_rate_pct: float | None = None
    total_profit: float | None = None
    total_loss: float | None = None
    profit_loss_ratio: float | None = None
    max_consecutive_wins: int | None = None
    max_consecutive_losses: int | None = None
    max_single_win: float | None = None
    max_single_loss: float | None = None
    verdict: str | None = None
    risk_level: RISK_LEVELS | None = None
    core_issue: str | None = None
    improvement_potential: str | None = None

class MetricsExt(BaseModel):
    run_id: str
    metric_group: str | None = None
    metric_name: str
    metric_value: float
    metric_label: str | None = None

class AnalysisDoc(BaseModel):
    run_id: str
    doc_type: DOC_TYPES
    file_path: str = Field(..., min_length=1)
    content_hash: str | None = None
    file_size_bytes: int = 0
    word_count: int | None = None

class PipelineInput(BaseModel):
    meta: AnalysisMeta
    metrics_core: list[MetricsCore] = Field(..., min_length=1, max_length=5)
    metrics_ext: list[MetricsExt] = Field(default_factory=list)
    docs: list[AnalysisDoc] = Field(..., min_length=1, max_length=6)

    @field_validator("metrics_core")
    @classmethod
    def check_metrics_core_dedup(cls, v):
        groups = [m.metric_group for m in v]
        if len(groups) != len(set(groups)):
            raise ValueError("metrics_core: duplicate metric_group")
        return v

    @field_validator("docs")
    @classmethod
    def check_docs_dedup(cls, v):
        types = [d.doc_type for d in v]
        if len(types) != len(set(types)):
            raise ValueError("docs: duplicate doc_type")
        return v
```

---

## 五、SQL 读写语句示例

> **时间戳策略**（统一选择 Python 侧 `_now_iso()` 生成）：
> - `created_at`、`updated_at`、`applied_at` 等时间戳字段**不**由 SQL `strftime` 自动生成
> - Writer 在写入时调用 `from model import _now_iso` 生成 `2026-05-23T15:10:00+08:00` 格式字符串
> - 所有 SQL INSERT/UPDATE/UPSERT 的对应位置均使用 `?` 绑定参数，接收 Python 侧生成的值
> - 理由：时区显式控制、可 mock 测试、不受 SQLite 本地时区配置影响

### 5.1 前置校验 SELECT

```sql
-- 检查 run_id 存在且完成
SELECT id, run_name, status, created_at
FROM backtest_run
WHERE id = ? AND status = 'done';

-- 检查幂等 (SELECT 查重)
SELECT id, run_id, analysis_type, version_status, version_content, author, created_at, updated_at
FROM analysis_meta
WHERE run_id = ? AND analysis_type = ?;

-- 交叉核验: 读取 performance_summary 指标
SELECT total_return, annualized_return, benchmark_return, excess_return,
       max_drawdown, sharpe_ratio, calmar_ratio, sortino_ratio,
       volatility, var_95_pct, win_rate, total_trades,
       max_consecutive_wins, max_consecutive_losses, final_equity
FROM performance_summary
WHERE run_id = ?
ORDER BY id DESC LIMIT 1;
```

### 5.2 事务写入

```sql
-- ============== 1. INSERT analysis_meta ==============
INSERT INTO analysis_meta
    (run_id, parent_session_id, tags, version_schema, version_content,
     version_status, author, analysis_type, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        -- created_at, updated_at 由 Writer 传入 _now_iso() 值

-- 取 last_insert_rowid()
SELECT last_insert_rowid();


-- ============== 2. UPDATE analysis_meta (幂等 draft) ==============
UPDATE analysis_meta
SET version_content = version_content + 1,
    version_status   = ?,
    tags             = ?,
    author           = ?,
    updated_at       = ?
WHERE id = ?;
        -- updated_at 由 Writer 传入 _now_iso() 值


-- ============== 3. CASCADE DELETE 旧附属记录 ==============
-- (由 ON DELETE CASCADE 外键自动处理, 但需要先确保外键开启)
PRAGMA foreign_keys = ON;

-- 或者显式删除:
DELETE FROM analysis_metrics_core WHERE analysis_id = ?;
DELETE FROM analysis_metrics_ext WHERE analysis_id = ?;
DELETE FROM analysis_docs WHERE analysis_id = ?;


-- ============== 4. INSERT analysis_metrics_core ==============
INSERT INTO analysis_metrics_core (
    analysis_id, run_id, metric_group,
    total_return_pct, annual_return_pct, final_equity, total_pnl,
    benchmark_return_pct, excess_return_pct,
    max_drawdown_pct, annual_volatility_pct,
    sharpe_ratio, calmar_ratio, sortino_ratio, var_95_pct,
    total_trades, winning_trades, losing_trades, win_rate_pct,
    total_profit, total_loss, profit_loss_ratio,
    max_consecutive_wins, max_consecutive_losses,
    max_single_win, max_single_loss,
    verdict, risk_level, core_issue, improvement_potential
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);


-- ============== 5. INSERT analysis_metrics_ext (批量) ==============
INSERT INTO analysis_metrics_ext (
    analysis_id, run_id, metric_group, metric_name, metric_value, metric_label
) VALUES (?, ?, ?, ?, ?, ?);
-- 批量: executemany


-- ============== 6. INSERT analysis_docs ==============
INSERT INTO analysis_docs (
    analysis_id, run_id, doc_type, file_path,
    content_hash, file_size_bytes, word_count
) VALUES (?, ?, ?, ?, ?, ?, ?);
-- 注意: UNIQUE(analysis_id, doc_type) 约束
-- UPDATE 场景需先 DELETE 旧行


-- ============== 7. UPSERT schema_version ==============
INSERT INTO schema_version (version, description, applied_at)
VALUES ('4.0', 'Analysis layer: meta+metrics_core+metrics_ext+docs+schema_version', ?)
ON CONFLICT(version) DO UPDATE SET
    applied_at = ?,
        -- applied_at 由 Writer 传入 _now_iso() 值
    description = excluded.description,
    checksum = excluded.checksum;
```

### 5.3 QA 验证 SELECT

```sql
-- 写入前后对比: 各表行数
SELECT 'analysis_meta' AS table_name, COUNT(*) AS cnt FROM analysis_meta WHERE run_id = ? AND analysis_type = ?
UNION ALL
SELECT 'analysis_metrics_core', COUNT(*) FROM analysis_metrics_core WHERE run_id = ?
UNION ALL
SELECT 'analysis_metrics_ext', COUNT(*) FROM analysis_metrics_ext WHERE run_id = ?
UNION ALL
SELECT 'analysis_docs', COUNT(*) FROM analysis_docs WHERE run_id = ?
UNION ALL
SELECT 'schema_version', COUNT(*) FROM schema_version;

-- 交叉验证: metrics_core 的 analysis_id 与 meta.id 一致
SELECT mc.analysis_id, am.id
FROM analysis_metrics_core mc
JOIN analysis_meta am ON mc.run_id = am.run_id AND mc.run_id = ?
WHERE mc.analysis_id != am.id;

-- 幂等对比: 同一 run_id+analysis_type 的 version_content 变化
SELECT id, run_id, analysis_type, version_status, version_content, author, created_at, updated_at
FROM analysis_meta
WHERE run_id = ? AND analysis_type = ?
ORDER BY id DESC;
```

### 5.4 归档失败标记 UPDATE

```sql
UPDATE analysis_docs
SET file_size_bytes = -1,
    updated_at = ?
WHERE analysis_id = ? AND doc_type = ?;
        -- updated_at 由 Writer 传入 _now_iso() 值
```

### 5.5 归档重入检测（归档失败重试查询）

```sql
-- 查询需要重试归档的文档
SELECT ad.id, ad.analysis_id, ad.run_id, ad.doc_type, ad.file_path
FROM analysis_docs ad
JOIN analysis_meta am ON ad.analysis_id = am.id
WHERE am.run_id = ? AND am.analysis_type = ? AND ad.file_size_bytes = -1;
```

---

## 六、错误处理链路

### 6.1 三级失败阶梯

```
FATAL ──────────────────────────────────────────────────────────────
├─ DB 连接失败 (sqlite3.OperationalError: unable to open database)
├─ 磁盘满 (OSError)
├─ 文件系统权限不足 (PermissionError)
└─ 行为: 写 ERROR 日志 → 不做任何恢复 → 标记 FATAL → 返回
         (不写 .failed, 需要人工介入)

ERROR ──────────────────────────────────────────────────────────────
├─ 交叉核验偏差 > 0.1%
├─ run_id 在 backtest_run 中不存在或 status != 'done'
├─ 事务写入失败 (sqlite3.IntegrityError / sqlite3.OperationalError)
├─ Pydantic 校验失败
├─ 前置校验严重不通过 (必填字段为空, 枚举非法)
└─ 行为: ROLLBACK(如果已开事务) → 写 ERROR 日志(含SQL+数据+堆栈)
         → 写 .failed 信号文件 → return status="ERROR"

WARN ──────────────────────────────────────────────────────────────
├─ 交叉核验偏差 0.01% ~ 0.1%
├─ 单份文档文件缺失 (磁盘删除但 DB 有记录)
├─ 文档 content_hash 不一致 (旧归档与本地不一致)
├─ 归档失败 (如目标目录无权限, 但不是系统级)
└─ 行为: 记录警告到 warnings 列表 → 继续写入 → 在最终结果中输出
         return status="WARN"
```

### 6.2 阶段错误冒泡

```
DataSourceError     (阶段1)   →   Pipeline.run() 捕获 → ERROR
TransformError      (阶段2)   →   Pipeline.run() 捕获 → ERROR
ValidationError     (阶段3)   →   Pipeline.run() 捕获 → [级别决定]
WriteError          (阶段4)   →   内部回滚 → 冒泡 → ERROR
ArchiveError        (归档)    →   记录警告 → 标记 doc → WARN
```

### 6.3 异常类定义 (可选)

```python
class PipelineError(Exception):
    """Pipeline 基类异常"""
    def __init__(self, message: str, level: str = "ERROR",
                 phase: str = "", details: dict | None = None):
        ...

class DataSourceError(PipelineError):
    """数据源阶段异常"""
    pass

class TransformError(PipelineError):
    """转换阶段异常"""
    pass

class ValidationError(PipelineError):
    """校验阶段异常"""
    pass

class WriteError(PipelineError):
    """写入阶段异常"""
    pass
```

---

## 七、日志格式模板

### 7.1 JSON Lines 格式

日志路径: `logs/ingest_analysis.log`（相对于 mozhi_platform 项目根目录）

每行一个完整 JSON 对象, 追加写入, 自动轮转（使用 `logging.handlers.RotatingFileHandler`, 10MB/文件, 保留5个备份）。

```json
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"pipeline","message":"[START] ingest pipeline","run_id":"65787f51-dffe-4090-9456-803ec0991441","analysis_type":"summary","action":"start","meta":{"timeout":35,"dry_run":false,"qa_verify":false,"force":false,"verbose":false}}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"datasource","message":"[START] data source phase: reading performance_summary","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"start"}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"datasource","message":"[END] data source phase: found 1 perf row, 2 doc files","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"end","duration_ms":12.34}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"transformer","message":"[START] transform phase: mapping perf row to PipelineInput","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"start"}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"transformer","message":"[END] transform phase: validated PipelineInput ready","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"end","duration_ms":5.67}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"validator","message":"[START] validate phase","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"start"}
{"ts":"2026-05-23T15:10:00+08:00","level":"WARN","component":"validator","message":"[CHECK_WARN] cross validation: sharpe_ratio deviation 0.05% exceeds 0.01% threshold","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"check","check_name":"cross_validate","detail":"input=0.1376 vs DB=0.1375, deviation=0.05%"}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"validator","message":"[END] validate phase: 5 checks passed (4 PASS, 1 WARN)","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"end","duration_ms":15.89}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[IDEMPOTENT] analysis_meta action=INSERT reason=no_existing_record","run_id":"65787f51-dffe-4090-9456-803ec0991441","analysis_type":"summary","action":"idempotent_check","existing_status":null,"result":"INSERT"}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[START] write phase: BEGIN transaction","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"begin_tx"}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[INSERT] analysis_meta: id=5 run_id=65787f51-... analysis_type=summary","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"insert","table":"analysis_meta","rows":1}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[INSERT] analysis_metrics_core: 1 rows (metric_group=daily)","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"insert","table":"analysis_metrics_core","rows":1}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[INSERT] analysis_docs: 2 rows (summary_report, analysis_report)","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"insert","table":"analysis_docs","rows":2}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[UPSERT] schema_version: version=4.0","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"upsert","table":"schema_version"}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[END] write phase: COMMIT transaction","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"commit","duration_ms":45.21}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[START] archive phase","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"archive_start"}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[ARCHIVE] summary_report → archive/reports/tsi_backtest_summary_report_20260523.md (7344 bytes, hash=abc...)","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"archive_file","doc_type":"summary_report","status":"copied","size_bytes":7344}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[ARCHIVE] analysis_report → archive/reports/tsi_backtest_analysis_report_20260523.md (10118 bytes, hash=def...)","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"archive_file","doc_type":"analysis_report","status":"skipped_hash_match","size_bytes":10118}
{"ts":"2026-05-23T15:10:00+08:00","level":"INFO","component":"writer","message":"[END] archive phase: 2 files processed (1 copied, 1 skipped)","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"archive_end","duration_ms":89.01}
{"ts":"2026-05-23T15:10:01+08:00","level":"INFO","component":"pipeline","message":"[END] pipeline completed: status=SUCCESS operation=INSERT analysis_meta_id=5","run_id":"65787f51-dffe-4090-9456-803ec0991441","analysis_type":"summary","action":"end","total_duration_ms":234.56,"rows_written":{"analysis_meta":1,"analysis_metrics_core":1,"analysis_metrics_ext":0,"analysis_docs":2,"schema_version":1},"warnings":["cross_val_deviation: sharpe_ratio 0.05%"]}
```

### 7.2 ERROR 日志示例

```json
{"ts":"2026-05-23T15:10:00+08:00","level":"ERROR","component":"writer","message":"[ERROR] write phase: sqlite3.IntegrityError - FOREIGN KEY constraint failed","run_id":"65787f51-dffe-4090-9456-803ec0991441","action":"error","phase":"write","sql":"INSERT INTO analysis_metrics_core (analysis_id, run_id, ...) VALUES (?, ?, ...)","data":{"analysis_id":5,"run_id":"65787f51-dffe-4090-9456-803ec0991441","metric_group":"daily"},"traceback":"Traceback (most recent call last):\n  File \".../writer.py\", line 142, in _write_metrics_core\n    ..."}
{"ts":"2026-05-23T15:10:00+08:00","level":"ERROR","component":"pipeline","message":"[ERROR] pipeline failed: status=ERROR reason=write_phase_failure","run_id":"65787f51-dffe-4090-9456-803ec0991441","analysis_type":"summary","action":"fail","total_duration_ms":150.12}
```

### 7.3 Logger 配置

```python
import json, logging, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logger(log_dir: str | Path = "logs") -> logging.Logger:
    log_dir = Path(log_dir)
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger("ingest_analysis")
    logger.setLevel(logging.DEBUG)

    # JSON Lines 文件 Handler (10MB, 保留5)
    file_handler = RotatingFileHandler(
        log_dir / "ingest_analysis.log",
        maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)

    # ——— JSON Formatter ———
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            log_obj = {
                "ts": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%S+08:00"),
                "level": record.levelname,
                "component": getattr(record, "component", "ingest"),
                "message": record.getMessage(),
                "run_id": getattr(record, "run_id", ""),
                "action": getattr(record, "action", ""),
            }
            # 附加 extra fields
            for key in ("duration_ms", "phase", "table", "rows",
                        "check_name", "detail", "sql", "data", "traceback",
                        "status", "existing_status", "result"):
                val = getattr(record, key, None)
                if val is not None:
                    log_obj[key] = val
            return json.dumps(log_obj, ensure_ascii=False)

    file_handler.setFormatter(JsonFormatter())

    # 控制台 Handler (verbose 时)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
```

---

## 八、归档实现细节

### 8.1 归档路径结构

```
mozhi_platform/
  └── archive/
      ├── reports/
      │   ├── tsi_backtest_summary_report_20260523.md
      │   ├── tsi_backtest_analysis_report_20260523.md
      │   └── ... (按报告文件名扁平存储)
      └── ddl/
          ├── backtest_schema_v4.sql
          └── migrate_v2_to_v4.sql
```

### 8.2 归档逻辑 (writer._archive_docs)

```python
def _archive_single_file(self, src: Path, dst_root: Path) -> dict:
    """单文件归档, 返回结果"""
    dst = dst_root / src.name

    if not src.exists():
        return {"status": "missing_source", "error": f"source not found: {src}"}

    if dst.exists():
        # 计算哈希比较
        src_hash = self._hash_file(src)
        dst_hash = self._hash_file(dst)
        if src_hash == dst_hash:
            return {"status": "skipped_hash_match", "size": src.stat().st_size}
        else:
            # 版本化重命名
            version = 1
            while dst.with_name(f"{dst.stem}_v{version}{dst.suffix}").exists():
                version += 1
            dst = dst.with_name(f"{dst.stem}_v{version}{dst.suffix}")

    shutil.copy2(str(src), str(dst))
    return {"status": "copied", "dst": str(dst), "size": src.stat().st_size,
            "content_hash": self._hash_file(src)}
```

### 8.3 content_hash 计算

```python
import hashlib

def _hash_file(self, path: str | Path) -> str:
    """SHA256 文件哈希"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
```

### 8.4 归档失败重入 (需求 §3.6 — 归档失败标记)

当归档失败时:
1. DB 事务已提交 (文件已写入, 但文件未复制到 archive/)
2. UPDATE analysis_docs SET file_size_bytes = -1 WHERE analysis_id=? AND doc_type=?
3. 写入警告日志

下次以同一 run_id+analysis_type 重入时:
1. 幂等检查: draft 版本 → UPDATE 路径
2. 检查 analysis_docs.file_size_bytes == -1 → 自动触发重试归档
3. 归档成功 → UPDATE file_size_bytes = 正确值

### 8.5 --archive-cleanup 模式

```python
def archive_cleanup(self, dry_run: bool = False) -> list[dict]:
    """
    清理 archive/ 目录中的 orphan 文件。

    Orphan 定义：不在 analysis_docs 表中被引用的归档文件。
    """
    orphan_files = []
    # 1. 扫描 archive/reports/ 和 archive/ddl/ 所有文件
    # 2. 查询 analysis_docs 中所有 file_path (已归档到 archive/ 的)
    # 3. 对比, 标记不在 DB 中引用的文件为 orphan
    # 4. dry_run 仅输出, 否则删除

    return orphan_files
```

---

## 九、CLI 主入口

### 9.1 `__init__.py` — public API

```python
"""src/backtest/analysis/ingest/__init__.py"""

from .pipeline import Pipeline, PipelineResult, ingest

__all__ = ["Pipeline", "PipelineResult", "ingest"]
```

### 9.2 `__main__.py` — CLI 入口

```python
"""python -m src.backtest.analysis.ingest --run-id ..."""

import argparse, sys
from .pipeline import ingest

def main():
    parser = argparse.ArgumentParser(
        description="ingest_analysis: 回测分析数据入库管道"
    )
    parser.add_argument("--run-id", required=True,
                        help="回测运行 UUID")
    parser.add_argument("--analysis-type", required=True,
                        choices=["summary", "deep_analysis", "tech_review",
                                 "validation", "resolution"],
                        help="分析类型")
    parser.add_argument("--dry-run", action="store_true",
                        help="试运行模式: 只校验不写入")
    parser.add_argument("--qa-verify", action="store_true",
                        help="输出 QA 校验报告 (JSON)")
    parser.add_argument("--force", action="store_true",
                        help="强制覆盖已存在 final 记录")
    parser.add_argument("--timeout", type=int, default=65,
                        help="管道超时秒数 (default: 65)")
    parser.add_argument("--verbose", action="store_true",
                        help="详细日志输出")
    parser.add_argument("--archive-cleanup", action="store_true",
                        help="清理 orphan 归档文件")
    parser.add_argument("--db-path", default=None,
                        help="数据库路径 (默认: data/backtest.db)")
    parser.add_argument("--archive-root", default=None,
                        help="归档根目录 (默认: archive/)")

    args = parser.parse_args()

    if args.archive_cleanup:
        # 仅清理模式
        result = _run_archive_cleanup(args)
    else:
        result = ingest(
            run_id=args.run_id,
            analysis_type=args.analysis_type,
            dry_run=args.dry_run,
            qa_verify=args.qa_verify,
            force=args.force,
            timeout=args.timeout,
            verbose=args.verbose,
            db_path=args.db_path,
            archive_root=args.archive_root,
        )

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") in ("SUCCESS", "WARN", "DRY_RUN") else 1)

if __name__ == "__main__":
    main()
```

### 9.3 `ingest()` 便捷函数

```python
def ingest(run_id: str, analysis_type: str,
           dry_run: bool = False, qa_verify: bool = False,
           force: bool = False, timeout: int = 65,
           verbose: bool = False,
           db_path: str | None = None,
           archive_root: str | None = None) -> PipelineResult:
    """便捷入口函数, 自动推断默认路径"""

    # 默认路径: 搜索 pyproject.toml 定位项目根
    _current = Path(__file__).resolve()
    for parent in _current.parents:
        if (parent / "pyproject.toml").exists():
            project_root = parent
            break
    else:
        raise FileNotFoundError(f"找不到 pyproject.toml，无法确定项目根目录（从 {_current} 向上搜索）")../
    if db_path is None:
        db_path = str(project_root / "data" / "backtest.db")
    if archive_root is None:
        archive_root = str(project_root / "archive")

    pipeline = Pipeline(
        db_path=db_path,
        run_id=run_id,
        analysis_type=analysis_type,
        dry_run=dry_run,
        qa_verify=qa_verify,
        force=force,
        timeout=timeout,
        verbose=verbose,
    )
    return pipeline.run()
```

---

## 十、幂等性与事务实现

### 10.1 幂等性检查流程 (writer._check_idempotent)

```python
def _check_idempotent(self, run_id: str, analysis_type: str) -> dict | None:
    """
    SELECT 查重, 返回已有记录或 None。

    返回 dict:
        {id, version_status, version_content, author, ...}
    """
    cur = self._conn.execute("""
        SELECT id, run_id, analysis_type, version_status,
               version_content, author, created_at, updated_at,
               parent_session_id, tags
        FROM analysis_meta
        WHERE run_id = ? AND analysis_type = ?
        ORDER BY id DESC LIMIT 1
    """, (run_id, analysis_type))

    row = cur.fetchone()
    if row is None:
        return None  # 不存在 → INSERT
    return dict(row)
```

### 10.2 幂等操作判定表

| 已有状态 | force=False | force=True |
|:---------|:------------|:-----------|
| 无记录 | INSERT | INSERT |
| draft | UPDATE (version_content+1) | UPDATE (version_content+1) |
| final | SKIP | UPDATE → 标记 reviewed |
| archived | SKIP | SKIP (archive 不可覆盖, force 也不覆盖) |

### 10.3 UPDATE 级联清理

```python
def _cascade_delete_old(self, tx: sqlite3.Connection, analysis_id: int):
    """
    UPDATE 时: 清除旧附属记录, 再重新 INSERT。
    利用 ON DELETE CASCADE 或显式 DELETE。
    """
    tx.execute("PRAGMA foreign_keys = ON")
    tx.execute("DELETE FROM analysis_docs WHERE analysis_id = ?", (analysis_id,))
    tx.execute("DELETE FROM analysis_metrics_ext WHERE analysis_id = ?", (analysis_id,))
    tx.execute("DELETE FROM analysis_metrics_core WHERE analysis_id = ?", (analysis_id,))
```

### 10.4 事务实现 (writer.write)

```python
def write(self, input_data: PipelineInput,
          validation: ValidationResult,
          force: bool = False, dry_run: bool = False) -> WriteResult:
    if dry_run:
        return WriteResult(status="DRY_RUN", operation="NONE", ...)

    tx = self._conn
    try:
        # 1. 幂等检查
        existing = self._check_idempotent(input_data.meta.run_id,
                                          input_data.meta.analysis_type)

        # 2. 确定操作
        if existing is None:
            operation = "INSERT"
            new_meta = input_data.meta
        elif existing["version_status"] in ("draft",):
            operation = "UPDATE"
            new_meta = input_data.meta.model_copy()
            new_meta.version_content = existing["version_content"] + 1
            analysis_id = existing["id"]
        elif existing["version_status"] == "final" and force:
            operation = "UPDATE"
            new_meta = input_data.meta.model_copy()
            new_meta.version_content = existing["version_content"] + 1
            new_meta.version_status = "reviewed"
            analysis_id = existing["id"]
        elif existing["version_status"] in ("final", "archived"):
            operation = "SKIP"
            # ... 已存在 final, 跳过后续步骤
            return WriteResult(status="SUCCESS", operation="SKIP",
                               analysis_meta_id=existing["id"])
        else:
            raise WriteError(f"unexpected version_status: {existing['version_status']}")

        tx.execute("BEGIN IMMEDIATE")

        if operation == "INSERT":
            analysis_id = self._write_meta(tx, new_meta)
        elif operation == "UPDATE":
            self._cascade_delete_old(tx, analysis_id)
            self._update_meta(tx, analysis_id, new_meta)

        # 写 metrics_core
        for mc in input_data.metrics_core:
            self._write_metrics_core(tx, analysis_id, mc)

        # 写 metrics_ext
        for me in input_data.metrics_ext:
            self._write_metrics_ext(tx, analysis_id, me)

        # 写 docs (先计算 content_hash + 文件大小)
        doc_results = []
        for doc in input_data.docs:
            computed_hash, fsize = self._compute_doc_meta(doc.file_path)
            doc.content_hash = computed_hash
            doc.file_size_bytes = fsize
            self._write_doc(tx, analysis_id, doc)
            doc_results.append(doc)

        # UPSERT schema_version
        self._upsert_schema_version(tx)

        tx.commit()
        # ——— DB 提交成功至此 ———

        # 归档 (DB 外)
        archive_results = self._archive_docs(doc_results)

        # 处理归档失败
        for i, ar in enumerate(archive_results):
            if ar["status"] in ("missing_source", "error"):
                self._mark_archive_failed(analysis_id, doc_results[i].doc_type)
                # 仍然记录 WARN

        # QA 验证
        qa = None
        if self._qa_verify:
            qa = self._generate_qa_report(input_data, analysis_id, existing)

        return WriteResult(
            status="SUCCESS",
            operation=operation,
            analysis_meta_id=analysis_id,
            rows_written={
                "analysis_meta": 1,
                "analysis_metrics_core": len(input_data.metrics_core),
                "analysis_metrics_ext": len(input_data.metrics_ext),
                "analysis_docs": len(input_data.docs),
                "schema_version": 1,
            },
            doc_archive_results=archive_results,
            qa_report=qa,
        )

    except sqlite3.Error as e:
        tx.rollback()
        self._log_error("write_phase_failure", str(e), sql_data=input_data)
        self._write_failed_signal(...)
        raise WriteError(f"SQL transaction failed: {e}") from e
```

---

## 十一、文件结构一览

### 最终文件树

```
src/backtest/analysis/ingest/
  ├── __init__.py       # public API: ingest() 便捷函数
  ├── __main__.py       # CLI 入口: python -m src.backtest.analysis.ingest ...
  ├── pipeline.py       # Pipeline 协调器 + PipelineResult
  ├── model.py          # Pydantic 数据模型 (PipelineInput, AnalysisMeta, ...)
  ├── transformer.py    # 字段映射 + 类型转换 + SHA256 计算
  ├── validator.py      # 5项校验 + 三级失败阶梯判定
  ├── writer.py         # SQLite 事务写入 + 归档 + 幂等检查 + .done/.failed
  ├── config.py         # 默认路径、常量、analysis_type TTL 映射
  └── _version.py       # 模块版本号 (可选)
```

### 配套文件

```
docs/ingest_analysis_design_v1.0.md   ← 本文件
logs/ingest_analysis.log               ← 运行时日志 (自动创建)
archive/reports/                        ← 报告归档
archive/ddl/                            ← DDL 归档
```

### 测试文件

```
src/backtest/tests/test_ingest_analysis.py
```

测试文件遵循项目约定路径 `src/backtest/tests/`，与目标模块 `src/backtest/analysis/ingest/` 保持同级命名空间。测试内容覆盖：
- DataSource.fetch() 正常/空数据路径
- Transformer.transform() 字段映射 + 空 perf_row DataSourceError
- Validator.validate() 各检查项（含 `_check_foreign_key`）
- Writer.write() 事务提交/回滚 + 幂等判定

---

## 十二、与 pyproject.toml 集成

```toml
# 在 pyproject.toml 的 [tool.setuptools.packages.find] 中
# ingest 模块已被 "backtest*" 通配符覆盖, 无需额外配置。
# 
# 可选: 注册 CLI 入口点
[project.scripts]
ingest-analysis = "src.backtest.analysis.ingest.__main__:main"
```

---

## 附录 A: 与 finalize_v4.py 行为对照

| 维度 | finalize_v4.py | ingest_analysis.py | 迁移说明 |
|:-----|:---------------|:-------------------|:---------|
| run_id | 硬编码 | CLI `--run-id` | 命令行参数化 |
| 指标来源 | 代码内拼写 | 从 performance_summary SELECT | 自动读取 |
| 文件路径 | 硬编码 | 目录自动发现 + doc_type 匹配 | 约定文件名命名规则 |
| content_hash | 不计算 | SHA256 计算并存库 | 保障文件完整性 |
| 版本管理 | 写死 4.1 | version_schema + version_content | 自动递增 |
| 幂等检查 | 无 | SELECT 查重 | 防重复写入 |
| 事务 | 无 | BEGIN/COMMIT/ROLLBACK | ACID 保障 |
| 归档 | 混入脚本 | 先DB后文件, 两步分离 | 降级安全 |
| 错误处理 | 无 | WARN/ERROR/FATAL 三级 | 可审计重入 |
| QA | 无 | --qa-verify 输出 | 可验证性 |
| 信号文件 | 无 | .done / .failed | 调度集成 |

---

## 附录 B: 关键设计决策记录

| 决策项 | 方案 | 理由 |
|:-------|:-----|:-----|
| Pydantic v1 vs v2 | Pydantic v2 (BaseModel, Field, validator) | 项目已用 Python3.14, v2 性能更好 |
| 事务隔离级别 | BEGIN IMMEDIATE | 防并发写冲突 |
| 归档失败处理 | file_size_bytes=-1 标记 | 不阻塞主流程, 重试友好 |
| 文件发现 | 按 doc_type 在 reports/ 目录模糊匹配 | 灵活, 不依赖硬编码路径 |
| 哈希算法 | SHA256 | 防碰撞性足够, 标准库支持 |
| .done 格式 | JSON oneliner | 与管道信号规范一致 |
| 超时机制 | `signal.alarm` 或线程 Timer | 防止管道挂死 |

---

## 附录 C: 迭代计划建议

| 阶段 | 内容 | 预计工时 |
|:----|:-----|:--------:|
| P0 (MVP) | pipeline + model + transformer + validator + writer 核心 + CLI | 2h |
| P1 | 归档实现 + content_hash | 0.5h |
| P2 | --qa-verify + 交叉核验细节完善 | 0.5h |
| P3 | --archive-cleanup + orphan 清理 | 0.5h |
| P4 | 单元测试 + 集成测试 | 1h |
| P5 | 集成到 Stage 4 回测会议流程 | 0.5h |

---

*文档完毕。*
