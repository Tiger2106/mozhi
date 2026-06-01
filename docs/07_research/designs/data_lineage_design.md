# WI 5 数据血缘追踪 — 设计方案

> **作者**: 玄知 (xuanzhi)  
> **创建时间**: 2026-06-01T17:03+08:00  
> **版本**: v1.0  
> **所属工作项**: WI 5 — 数据血缘追踪  
> **状态**: DESIGN_READY

---

## 目录

- [1. 设计目标与范围](#1-设计目标与范围)
- [2. 数据血缘模型设计](#2-数据血缘模型设计)
- [3. 血缘标注植入点](#3-血缘标注植入点)
- [4. 血缘查询功能设计](#4-血缘查询功能设计)
- [5. 与现有组件的集成](#5-与现有组件的集成)
- [6. 实施计划](#6-实施计划)

---

## 1. 设计目标与范围

### 1.1 目标

对回测系统的数据管线建立可追溯的血缘网络，使任意输出节点（因子值、IC 结果、报告结论）可追溯到其原始数据来源和经过的每个转换步骤。

### 1.2 覆盖范围

```
Tushare API (原始数据源)
  ├─ daily API    → a50_daily_ohlcv
  └─ daily_basic API → a50_daily_basic (含 dv_ratio ÷100 修复)
       │
       ▼
  因子计算 (cross_sectional_ic.py)
  └─ 15因子值 (动量/反转/质量/估值/波动)
       │
       ▼
  IC计算 (IC-P3)
  └─ a50_cross_ic_result
       │
       ▼
  数据质量门禁 (Gate L1/L2/L3)
  └─ reports/dq/{trade_date}/cross_ic_gate.json
       │
       ▼
  管线调度 (cross_sectional_ic_pipeline.py)
  └─ 检查点 + 批量结果
       │
       ▼
  报告产出 (reports/ic/valuation/ 等)
  └─ 汇总报告、IC评估详表
```

### 1.3 核心原则

1. **可追溯性**：每个输出节点都能沿血缘链回推到原始数据源
2. **可审计性**：每个转换步骤记录版本、参数、时间戳
3. **低侵入性**：不改变现有管线主逻辑，以元数据方式嵌入
4. **轻量化**：以 JSON 元数据附加到现有数据库表/文件中，不引入新存储系统

---

## 2. 数据血缘模型设计

### 2.1 模型概览

数据血缘模型由三个核心实体构成：

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  DataSource   │     │    Step      │     │  OutputNode  │
│  (数据源)      │────▶│  (转换步骤)   │────▶│  (产出节点)   │
└──────────────┘     └──────────────┘     └──────────────┘
       │                     │                     │
       ▼                     ▼                     ▼
  lineage_source     lineage_step           lineage_output
  (血缘数据源表)      (血缘步骤表)            (血缘产出表)
```

每条血缘记录由 `source_ref → [step_ref → step_ref → ...] → output_ref` 构成有向无环图（DAG）。

### 2.2 Schema 定义

#### 2.2.1 数据源注册表 `lineage_source`

记录每个数据源的来源信息，包括 API、数据库表、文件路径等。

```sql
CREATE TABLE lineage_source (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name     TEXT    NOT NULL UNIQUE,  -- 唯一标识，如 'tushare_daily_api'
    source_type     TEXT    NOT NULL,         -- 'api' | 'db_table' | 'file' | 'derived'
    description     TEXT,                     -- 描述
    provider        TEXT,                     -- 数据提供方，如 'tushare'
    endpoint        TEXT,                     -- API endpoint 或数据库路径
    table_name      TEXT,                     -- 表名（db_table类型时）
    fields          TEXT,                     -- JSON数组：提供的字段列表
    freshness_rule  TEXT,                     -- 新鲜度规则key（与FRESHNESS_RULES对应）
    version         TEXT    NOT NULL DEFAULT 'v1',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(source_name, version)
);
```

**预注册数据源实例**：

| source_name | source_type | provider | endpoint/table | fields |
|:-----------|:-----------|:---------|:---------------|:-------|
| `tushare_daily_api` | api | tushare | pro.daily | open, high, low, close, volume, amount, adj_factor |
| `tushare_daily_basic_api` | api | tushare | pro.daily_basic | pe, pe_ttm, pb, ps_ttm, pcf_ttm, dividend_yield, float_share |
| `a50_db.a50_daily_ohlcv` | db_table | sqlite | a50_ic.db / a50_daily_ohlcv | ts_code, trade_date, open, high, low, close, ... |
| `a50_db.a50_daily_basic` | db_table | sqlite | a50_ic.db / a50_daily_basic | code, date, pe, pb, ... |
| `a50_db.a50_universe` | db_table | sqlite | a50_ic.db / a50_universe | ts_code, in_date, out_date |

#### 2.2.2 转换步骤表 `lineage_step`

记录从输入到输出之间的每个转换步骤。

```sql
CREATE TABLE lineage_step (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    step_name       TEXT    NOT NULL,          -- 步骤名称，如 'etl_ohlcv_ingest'
    step_type       TEXT    NOT NULL,          -- 'etl_ingest' | 'factor_compute' | 'ic_compute' | 'gate_check' | 'report_aggregate'
    description     TEXT,                      -- 步骤描述
    script_path     TEXT,                      -- 脚本文件路径
    function_name   TEXT,                      -- 入口函数名
    version         TEXT,                      -- 脚本版本/commit
    parameters      TEXT,                      -- JSON：运行参数模板
    input_sources   TEXT,                      -- JSON数组：输入source_name列表
    output_keys     TEXT,                      -- JSON：输出的字段/表名
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(step_name, version)
);
```

**预注册步骤实例**：

| step_name | step_type | script_path | function_name | input_sources | output_keys |
|:----------|:----------|:------------|:--------------|:-------------|:------------|
| `etl_ohlcv_ingest` | etl_ingest | src/pipeline/cross_sectional_ic.py | load_panel_data | tushare_daily_api | a50_daily_ohlcv |
| `etl_daily_basic_ingest` | etl_ingest | src/ingestion/daily_basic_collector.py | collect_daily_basic | tushare_daily_basic_api | a50_daily_basic |
| `etl_dv_ratio_fix` | etl_ingest | src/ingestion/daily_basic_collector.py:308 | (dv_ratio ÷100) | a50_db.a50_daily_basic | dividend_yield_corrected |
| `factor_compute_all` | factor_compute | src/pipeline/cross_sectional_ic.py | compute_all_factors | a50_db.a50_daily_ohlcv | momentum_5d..volume_20d_change |
| `ic_compute_cross` | ic_compute | src/pipeline/cross_sectional_ic.py | compute_cross_sectional_ic | factor_compute_all | a50_cross_ic_result |
| `gate_l1_check` | gate_check | src/pipeline/cross_sectional_ic.py | run_level1 | a50_db.a50_daily_basic | gate_report_l1 |
| `gate_l2_check` | gate_check | src/pipeline/cross_sectional_ic.py | run_level2 | factor_compute_all | gate_report_l2 |
| `gate_l3_check` | gate_check | src/pipeline/cross_sectional_ic.py | run_level3 | ic_compute_cross | gate_report_l3 |
| `report_aggregate_ic` | report_aggregate | docs/07_research/reports/... | (manual) | ic_compute_cross | 汇总报告 |

#### 2.2.3 血缘运行记录表 `lineage_record`

每一次管线运行产生的血缘绑定记录——连接具体的数据源、步骤和产出。

```sql
CREATE TABLE lineage_record (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id       TEXT    NOT NULL UNIQUE,  -- UUID，每条血缘记录唯一标识
    run_id          TEXT    NOT NULL,         -- 运行批次ID（同一轮管线调用共享）
    task_id         TEXT,                     -- 任务ID（与 dispatcher 兼容）
    
    -- 数据源
    source_id       INTEGER NOT NULL,         -- 参照 lineage_source.id
    source_record   TEXT,                     -- JSON：该来源的具体数据范围（如最小/最大日期、行数）
    
    -- 转换步骤
    step_id         INTEGER NOT NULL,         -- 参照 lineage_step.id
    step_params     TEXT,                     -- JSON：本次运行的实际参数（如 forward_window=5）
    step_started_at TEXT,                     -- 步骤开始时间
    step_completed_at TEXT,                   -- 步骤完成时间
    step_status     TEXT,                     -- 'SUCCESS' | 'FAILED' | 'SKIPPED'
    
    -- 产出节点
    output_type     TEXT,                     -- 'table' | 'file' | 'metric'
    output_ref      TEXT,                     -- 产出引用：表名/文件路径/指标名称
    output_count    INTEGER,                  -- 产出记录数
    output_sample   TEXT,                     -- JSON：产出样本摘要（前3行或统计值）
    
    -- 数据完整性
    input_row_count     INTEGER,              -- 输入行数
    output_row_count    INTEGER,              -- 输出行数
    row_diff_note       TEXT,                 -- 行数变化说明（如过滤、聚合）
    
    -- 版本
    data_version    TEXT,                     -- 数据版本
    code_version    TEXT,                     -- 代码版本（git commit）
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    
    FOREIGN KEY (source_id) REFERENCES lineage_source(id),
    FOREIGN KEY (step_id) REFERENCES lineage_step(id)
);

-- 索引：加速按产出/来源查询
CREATE INDEX idx_lineage_record_output ON lineage_record(output_type, output_ref);
CREATE INDEX idx_lineage_record_source ON lineage_record(source_id);
CREATE INDEX idx_lineage_record_run ON lineage_record(run_id);
```

#### 2.2.4 JSON Schema 嵌入字段

对于现有数据库表，为减少 schema 变更，在新数据行中嵌入 JSON 元数据字段：

```json
{
  "lineage": {
    "source_name": "tushare_daily_api",
    "step_name": "etl_ohlcv_ingest",
    "run_id": "run_20260601_001",
    "record_id": "uuid-xxxxx",
    "code_version": "v2.3.1",
    "ingested_at": "2026-06-01T10:30:00+08:00",
    "etl_params": {
      "batch_size": 50,
      "is_backfill": false,
      "dv_ratio_fixed": true
    }
  }
}
```

### 2.3 数据流向图（文本化）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        数据来源层                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Tushare Pro API               Tushare Pro API                     │
│  ┌──────────────────┐          ┌──────────────────┐               │
│  │  pro.daily        │          │  pro.daily_basic  │               │
│  │  (OHLCV+adj_factor│          │  (PE/PB/PS/PCF/DY)│               │
│  └────────┬─────────┘          └────────┬──────────┘               │
│           │                             │                          │
│           ▼                             ▼                          │
│  ┌──────────────────┐          ┌──────────────────┐               │
│  │ incoming/        │          │ incoming/        │               │
│  │ stock_data.db    │          │ stock_data.db    │               │
│  │ (raw)            │          │ (raw)            │               │
│  └────────┬─────────┘          └────────┬──────────┘               │
│           │                             │                          │
└───────────┼─────────────────────────────┼──────────────────────────┘
            │                             │
            ▼  ETL 层                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         数据存储层                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  a50_ic.db  ┌───────────────────────────────────────────────────┐  │
│             │  a50_daily_ohlcv          a50_daily_basic         │  │
│             │  ┌──────────────┐         ┌──────────────┐        │  │
│             │  │ ts_code      │         │ code         │        │  │
│             │  │ trade_date   │         │ date         │        │  │
│             │  │ close        │         │ pe           │        │  │
│             │  │ volume       │         │ pb           │        │  │
│             │  │ adj_factor   │         │ ps_ttm       │        │  │
│             │  │ pe, pb, ...  │         │ dividend_yield│       │  │
│             │  │ null_reason  │         │ (÷100 已修复) │        │  │
│             │  └──────┬───────┘         └──────┬────────┘        │  │
│             │         │                       │                  │  │
│             │         └──────┬────────────────┘                  │  │
│             │                │                                   │  │
│             │  a50_universe  │  (成分股资格验证)                   │  │
│             │  ┌─────────────┐                                   │  │
│             │  │ ts_code     │                                   │  │
│             │  │ in_date     │                                   │  │
│             │  │ out_date    │                                   │  │
│             │  └──────┬──────┘                                   │  │
│             └─────────┼───────────────────────────────────────────┘  │
│                       │                                             │
└───────────────────────┼─────────────────────────────────────────────┘
                        │
                        ▼ 计算层
┌─────────────────────────────────────────────────────────────────────┐
│                        因子 & IC 计算层                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Step 5: 加载120d回看面板数据      Step 6: 计算15因子值              │
│  ┌─────────────────────┐          ┌──────────────────────┐         │
│  │ load_panel_data()   │─────────▶│ compute_all_factors() │         │
│  │ SQL: a50_daily_ohlcv│          │ momentum_5d..        │         │
│  │ trade_date BETWEEN  │          │ volume_20d_change    │         │
│  └─────────────────────┘          └──────────┬───────────┘         │
│                                               │                     │
│  ┌─────────────────────┐                      │                     │
│  │ 前向收益计算          │                      │                     │
│  │ compute_forward_    │                      │                     │
│  │ return(t+5)         │                      │                     │
│  └──────────┬──────────┘                      │                     │
│             │                                 │                     │
│             ▼                                 ▼                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              compute_cross_sectional_ic()                    │   │
│  │  ┌──────────┬──────────┬──────────┬──────────┐              │   │
│  │  │ Gate L1  │ Gate L2  │ IC计算   │ Gate L3  │              │   │
│  │  │ (ETL)   │ (因子级) │ (Pearson │ (IC级)   │              │   │
│  │  │         │          │   +Rank) │          │              │   │
│  │  └─────────┴──────────┴──────────┴──────────┘              │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                      │
│                             ▼                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │            a50_cross_ic_result 表                            │  │
│  │  trade_date | factor_name | ic_value | rank_ic | p_value    │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                             │                                      │
└─────────────────────────────┼────────────────────────────────────────┘
                              │
                              ▼ 报告层
┌──────────────────────────────────────────────────────────────────────┐
│                           报告产出层                                  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐   ┌──────────────────┐   ┌────────────────┐  │
│  │ 门禁报告          │   │ IC评估详表        │   │ 汇总报告        │  │
│  │ reports/dq/      │   │ valuation_ic_    │   │ 估值数据源     │  │
│  │ {trade_date}/    │   │ full_history.json │   │ 摸底报告       │  │
│  │ cross_ic_gate.json│   └──────────────────┘   └────────────────┘  │
│  └──────────────────┘                                              │
│                                                                     │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.4 关键节点标注规则

| 节点类型 | 标注规则 | 标注内容 |
|:---------|:---------|:---------|
| **数据源** (API/文件) | 首次识别时写入 `lineage_source` | source_name, type, provider, endpoint |
| **数据库表** | 含 lineage JSON 元数据字段 | source_name, step_name, run_id, record_id |
| **中间结果** (DataFrame/内存) | 每次写入前记录元数据 | input_count, output_count, 转换摘要 |
| **文件产出** (JSON/MD) | 文件头部嵌入 lineage 注释 | 来源、步骤、版本、时间戳 |
| **报告结论** | 引用 `lineage_record.record_id` | 结论的来源数据版本、计算参数 |

**报告头部嵌入格式示例**：

```json
// 文件头部 lineage 元数据（JSON 报告）
{
  "_lineage": {
    "run_id": "run_20260601_001",
    "source_records": ["uuid-xxx", "uuid-yyy"],
    "steps": ["factor_compute_all", "ic_compute_cross"],
    "data_range": {"start": "20200101", "end": "20260515"}
  },
  "status": "READY",
  ...
}
```

```markdown
<!-- Markdown 报告 -->
<!-- lineage:
  run_id: run_20260601_001
  source: a50_db.a50_daily_ohlcv, a50_db.a50_daily_basic
  steps: etl_ohlcv_ingest, etl_daily_basic_ingest, factor_compute_all, ic_compute_cross
  data_version: v2.3.1
-->
```

---

## 3. 血缘标注植入点

### 3.1 植入点与标注格式

#### 3.1.1 植入点 A：ETL入口（数据采集）

**位置**：`daily_basic_collector.py` — `collect_daily_basic()` 写入 `a50_daily_basic` 表处

**植入方式**：在 INSERT 之前，为本次批处理生成 `run_id` 和 `record_id`，写入每个数据行的 `_lineage` 元数据字段（JSON text column 或 独立 `lineage_info` 列）。

**标注字段**（附加到表 或 写入 `lineage_record`）：

```python
lineage_meta = {
    "run_id": f"run_{datetime.now():%Y%m%d_%H%M%S}",
    "record_id": str(uuid4()),
    "step_name": "etl_daily_basic_ingest",
    "source": "tushare_daily_basic_api",
    "source_params": {
        "api_version": "pro",
        "fields": ["pe", "pb", "ps_ttm", "dividend_yield", "float_share"],
        "batch_start": batch_start_date,
        "batch_end": batch_end_date,
    },
    "code_version": "v2.3.1",
    "etl_transform": {
        "dv_ratio_div100": True,
        "null_reason_flagged": True,
    },
}
```

#### 3.1.2 植入点 B：中间结果写入（因子计算入口）

**位置**：`cross_sectional_ic.py` — `load_panel_data()` 返回 DataFrame 之前

**植入方式**：记录从 `a50_daily_ohlcv` 读取的行数、日期范围、停牌过滤行数。将元数据写入 `lineage_record`。

```python
lineage_meta = {
    "run_id": run_id,
    "record_id": str(uuid4()),
    "step_name": "etl_ohlcv_ingest",
    "source": "a50_db.a50_daily_ohlcv",
    "input": {
        "trade_date_sql": f"{lookback_date} ~ {trade_date}",
        "raw_rows": len(raw_df),
        "after_suspended_filter": len(post_filter_df),
        "after_null_filter": len(clean_df),
        "after_universe_filter": len(universe_df),
    },
    "sample_codes": df['ts_code'].head(3).tolist(),
}
```

#### 3.1.3 植入点 C：因子计算

**位置**：`cross_sectional_ic.py` — `compute_all_factors()` 返回之前

**植入方式**：对每个计算的因子记录覆盖情况：

```json
{
  "run_id": "run_20260601_001",
  "step_name": "factor_compute_all",
  "input_source": "a50_db.a50_daily_ohlcv",
  "factors_computed": {
    "momentum_5d": {"non_null": 48, "mean": 0.0032},
    "momentum_20d": {"non_null": 48, "mean": 0.0151},
    "pb_lf": {"non_null": 46, "direct_source": "pb"},
    "dividend_yield": {"non_null": 42, "etl_fix": "dv_ratio/100"}
  },
  "active_factor_count": 10,
  "disabled_factors": ["pe_ttm", "dividend_yield"]
}
```

#### 3.1.4 植入点 D：IC计算输出

**位置**：`cross_sectional_ic.py` — `write_ic_results()` 写入 `a50_cross_ic_result` 表之前

**植入方式**：在写入IC结果的同时，为整批IC结果创建一条 `lineage_record`：

```python
lineage_meta = {
    "run_id": run_id,
    "record_id": str(uuid4()),
    "step_name": "ic_compute_cross",
    "input": {
        "source_step": "factor_compute_all",
        "trade_date": trade_date,
        "factor_count": len(factor_names),
        "active_factor_count": len(results),
    },
    "parameters": {
        "forward_window": forward_window,
        "min_stocks": min_stocks,
        "source_version": source_version,
    },
    "output": {
        "target_table": "a50_cross_ic_result",
        "rows_written": len(ic_df),
    },
}
```

#### 3.1.5 植入点 E：门禁报告

**位置**：`cross_sectional_ic.py` — `_write_gate_report()` 写 JSON 文件处

**植入方式**：在 `cross_ic_gate.json` 文件中嵌入 `_lineage` 字段：

```python
output_payload["_lineage"] = {
    "run_id": run_id,
    "record_id": str(uuid4()),
    "steps": ["gate_l1_check", "gate_l2_check", "gate_l3_check"],
    "source_trade_date": trade_date,
}
```

### 3.2 植入点汇总矩阵

| 植入点 | 文件 | 函数 | 血缘粒度 | 侵入性 |
|:-------|:-----|:------|:---------|:-------|
| A ETL入口 | `daily_basic_collector.py` | `collect_daily_basic()` | 每批 | 低（加1列JSON） |
| B 中间结果 | `cross_sectional_ic.py` | `load_panel_data()` | 每截面 | 中（写lineage_record表） |
| C 因子计算 | `cross_sectional_ic.py` | `compute_all_factors()` | 每截面 | 低（加JSON记录） |
| D IC输出 | `cross_sectional_ic.py` | `write_ic_results()` | 每截面 | 中（写lineage_record表） |
| E 门禁报告 | `cross_sectional_ic.py` | `_write_gate_report()` | 每截面 | 低（嵌入JSON字段） |

---

## 4. 血缘查询功能设计

### 4.1 查询接口

#### 4.1.1 Python API

```python
# src/lineage/query.py

def trace_output(output_type: str, output_ref: str, **filters) -> List[LineageRecord]:
    """
    根据产出节点追溯完整数据血缘链路。

    Args:
        output_type: 'table' | 'file' | 'metric'
        output_ref: 'a50_cross_ic_result' | 'reports/dq/20260515/cross_ic_gate.json'
        filters: 可选过滤条件，如 trade_date='20260515', factor_name='momentum_20d'

    Returns:
        List[LineageRecord]: 按时间倒序的血缘记录列表，包含完整链路
    """

def trace_source(source_name: str, **filters) -> List[LineageRecord]:
    """
    从数据源查询其影响了哪些下游产出。

    Args:
        source_name: 'tushare_daily_api' 或 'a50_db.a50_daily_ohlcv'
        filters: 可选过滤条件

    Returns:
        List[LineageRecord]: 下游影响链路
    """

def lineage_graph(code: str, start_date: str, end_date: str) -> Dict:
    """
    生成指定资产代码和时间范围内的完整数据血缘图。

    Args:
        code: '601857.SH' 或 None（全市场）
        start_date: '20260101'
        end_date: '20260515'

    Returns:
        Dict: { 'nodes': [...], 'edges': [...], 'summary': {...} }
    """
```

#### 4.1.2 命令行查询

```bash
# 追溯IC产出
python -m src.lineage.query trace-output --type table --ref a50_cross_ic_result --filter trade_date=20260515

# 从数据源看下游影响
python -m src.lineage.query trace-source --name tushare_daily_basic_api

# 资产级血缘图
python -m src.lineage.query graph --code 601857.SH --start 20260101 --end 20260515
```

#### 4.1.3 查询 SQL 示例

```sql
-- 查询某个IC结果的数据来源
SELECT * FROM lineage_record
WHERE output_type = 'table'
  AND output_ref = 'a50_cross_ic_result'
  AND json_extract(output_sample, '$.trade_date') = '20260515'
ORDER BY created_at DESC
LIMIT 5;

-- 通过 step_id 链式查询
-- Step 1: 找到IC计算的运行记录
SELECT * FROM lineage_record
WHERE step_id = (SELECT id FROM lineage_step WHERE step_name = 'ic_compute_cross')
  AND output_ref = 'a50_cross_ic_result'
LIMIT 1;

-- Step 2: 用 source_id 找到该步骤的上游来源
SELECT ls.*, lr.source_record
FROM lineage_source ls
JOIN lineage_record lr ON lr.source_id = ls.id
WHERE lr.run_id = '<上一步的run_id>';

-- Step 3: 继续向上游追溯...
```

### 4.2 查询输出格式

#### `trace_output()` 返回格式

```json
{
  "query": {
    "output_type": "table",
    "output_ref": "a50_cross_ic_result",
    "filters": {"trade_date": "20260515"}
  },
  "lineage_chain": [
    {
      "step": 1,
      "node_type": "output",
      "ref": "a50_cross_ic_result",
      "detail": "IC结果，trade_date=20260515，10个因子，有效样本50只股票",
      "record_id": "uuid-001",
      "run_id": "run_20260601_001",
      "timestamp": "2026-06-01T11:00:23+08:00"
    },
    {
      "step": 2,
      "node_type": "step",
      "ref": "ic_compute_cross",
      "detail": "IC计算，forward_window=5, min_stocks=30, source_version=v1",
      "params": {"forward_window": 5, "min_stocks": 30}
    },
    {
      "step": 3,
      "node_type": "step",
      "ref": "factor_compute_all",
      "detail": "15因子计算，截面日期20260515，有效因子10个",
      "factors": ["momentum_5d", "momentum_20d", ..., "volume_20d_change"]
    },
    {
      "step": 4,
      "node_type": "step",
      "ref": "etl_ohlcv_ingest",
      "detail": "加载面板数据，120日回看窗口，50只成分股"
    },
    {
      "step": 5,
      "node_type": "source",
      "ref": "a50_db.a50_daily_ohlcv",
      "detail": "原始OHLCV数据，字段：close, volume, adj_factor, pe, pb, ...",
      "row_count": 6000,
      "date_range": "20251215 - 20260515"
    }
  ],
  "summary": "完整链路：5个节点，0个缺失，数据覆盖良好"
}
```

#### `lineage_graph()` 图形化输出

```json
{
  "code": "601857.SH",
  "date_range": "20260101-20260515",
  "nodes": [
    {"id": "src1", "type": "source", "label": "Tushare Daily API", "group": "api"},
    {"id": "src2", "type": "source", "label": "Tushare Daily Basic API", "group": "api"},
    {"id": "tbl1", "type": "table", "label": "a50_daily_ohlcv", "group": "sqlite"},
    {"id": "tbl2", "type": "table", "label": "a50_daily_basic", "group": "sqlite"},
    {"id": "stp1", "type": "step", "label": "load_panel_data", "group": "etl"},
    {"id": "stp2", "type": "step", "label": "factor_compute", "group": "compute"},
    {"id": "stp3", "type": "step", "label": "ic_compute", "group": "compute"},
    {"id": "out1", "type": "output", "label": "IC Result", "group": "output"}
  ],
  "edges": [
    {"from": "src1", "to": "tbl1", "label": "ETL ingest"},
    {"from": "src2", "to": "tbl2", "label": "ETL ingest + dv fix"},
    {"from": "tbl1", "to": "stp1", "label": "120d lookback SQL"},
    {"from": "tbl1", "to": "stp2", "label": "factor input"},
    {"from": "tbl2", "to": "stp2", "label": "valuation fields"},
    {"from": "stp1", "to": "stp2", "label": "panel data"},
    {"from": "stp2", "to": "stp3", "label": "factor values"},
    {"from": "stp3", "to": "out1", "label": "IC write"}
  ],
  "summary": {
    "total_nodes": 8,
    "total_edges": 8,
    "source_count": 2,
    "step_count": 3,
    "output_count": 1
  }
}
```

### 4.3 可选的 Web 可视化

若后续需要图形化展示，上述 `nodes/edges` 格式可直接供 D3.js / vis.js / Cytoscape.js 等工具渲染为有向图。

---

## 5. 与现有组件的集成

### 5.1 与 freshness_probe 联动

#### 5.1.1 集成方式

`freshness_probe.py` 负责检测数据新鲜度，`lineage_source` 表为其提供**配置锚点**。

**具体方案**：

```python
# src/lineage/integrations/freshness_integration.py

from src.monitoring.freshness_probe import run_freshness_check, FRESHNESS_RULES


def get_source_freshness_meta() -> dict:
    """
    从 lineage_source 表读取已注册的数据源，与 FRESHNESS_RULES 做映射。

    返回：
        {
            "sources": {
                "a50_daily_ohlcv": {
                    "lineage_source_id": 1,
                    "source_name": "a50_db.a50_daily_ohlcv",
                    "freshness_status": "OK",
                    "last_check": "2026-06-01T17:00+08:00",
                    "rule_ref": "a50_daily_ohlcv"
                },
                ...
            }
        }
    """
```

**联动流程**：

```
freshness_probe.run_freshness_check()
    │
    ▼
返回各数据源新鲜度状态
    │
    ▼
lineage_integration.enrich_with_freshness(lineage_record)
    │  ├─ 为 lineage_record 添加 freshness_status 字段
    │  └─ 若状态为 WARN/ALERT，在血缘链路中标记该数据源状态
    │
    ▼
血缘查询时，输出节点附带 freshness 信息：
  "source_freshness": {
    "a50_db.a50_daily_ohlcv": "OK (0h 延迟)",
    "a50_db.a50_daily_basic": "WARN (26h 延迟)"
  }
```

#### 5.1.2 增强 `freshness_config.py`

在 `FRESHNESS_RULES` 中为每个规则添加 `lineage_source_ref` 字段：

```python
FRESHNESS_RULES = {
    "a50_daily_ohlcv": {
        "source": "a50_ic.db/a50_daily_ohlcv",
        "type": "daily_prices",
        "lineage_source_ref": "a50_db.a50_daily_ohlcv",  # ★ 新增
        ...
    },
    "a50_daily_basic": {
        "source": "a50_ic.db/a50_daily_basic",
        "type": "daily_fundamentals",
        "lineage_source_ref": "a50_db.a50_daily_basic",  # ★ 新增
        ...
    },
    ...
}
```

#### 5.1.3 告警增强

当 `freshness_probe` 发现数据延迟时，联动血缘查询自动标记受影响的中间产物：

```
freshness_probe 触发 WARN
    │
    ▼
查询 lineage_record 中该 source 的所有下游节点
    │
    ▼
输出报告：30个IC结果使用了含延迟的数据（trade_dates: 20260510-20260515）
    │
    ▼
告警通知：数据延迟影响范围评估
```

### 5.2 与 verify_golden 管线配合

`verify_golden` 管线负责对管线输出进行端到端验证及输出校验。

#### 5.2.1 为黄金样本附加血缘锚

在 `verify_golden/golden_samples.json` 中，为每个黄金样本添加 `_lineage_ref`：

```json
{
  "samples": [
    {
      "id": "ic_20260515_momentum_20d",
      "trade_date": "20260515",
      "factor_name": "momentum_20d",
      "expected_ic": 0.142,
      "expected_rank_ic": 0.167,
      "tolerance": 0.01,
      "_lineage_ref": {
        "source_records": ["uuid-xxx", "uuid-yyy"],
        "verify_step": "e2e_golden",
        "golden_version": "v1",
        "created_at": "2026-06-01T16:21:00+08:00"
      }
    }
  ]
}
```

#### 5.2.2 验证结果与血缘绑定

在 `run_verify_pipeline.py` 的输出报告中，嵌入血缘信息：

```python
verify_result = {
    "mode": "full",
    "status": "PASS",
    "_lineage": {
        "run_id": run_id,
        "verify_source": "golden_samples.json",
        "golden_samples_used": 3,
        "data_sources": lineage_chain_summary,
        "code_version": "v2.3.1",
    },
    "e2e_result": {"status": "PASS", "details": ...},
    "output_result": {"status": "PASS", "details": ...},
}
```

#### 5.2.3 验证数据一致性

利用血缘关系，`verify_golden` 可以自动做数据一致性校验：

```python
# verify_golden 新增函数
def verify_data_consistency_via_lineage(
    lineage_records: List[LineageRecord],
    check: str = 'row_counts'
) -> bool:
    """
    利用血缘记录确认管线各阶段数据量一致。

    检查项：
    - ETL入口行数 = 因子计算入口行数（停牌过滤后合理偏差内）
    - 因子计算行数 >= IC计算行数（因子NaN过滤合理）
    - IC输入因子非空数 = 有效因子数
    - IC输出行数 * 因子数 ≈ 有效截面样本数

    返回：
        True: 所有一致性检查通过
        False: 至少一个有疑问的偏差
    """
```

### 5.3 集成架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        现有管线组件                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                │
│  │ daily_basic  │   │ cross_       │   │ cross_       │                │
│  │ _collector   │──▶│ sectional_ic │──▶│ sectional_ic │                │
│  │ .py          │   │ .py          │   │ _pipeline.py │                │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                │
│         │                 │                    │                         │
│         ▼                 ▼                    ▼                         │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                    lineage 模块 (新)                              │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐   │    │
│  │  │ model       │  │ annotations  │  │ query                │   │    │
│  │  │ (schema,    │  │ (植入点函数)  │  │ (trace_output /      │   │    │
│  │  │  DDL)       │  │             │  │  trace_source / graph)│   │    │
│  │  └─────────────┘  └─────────────┘  └──────────────────────┘   │    │
│  │  ┌─────────────────────────────────────────────────────────┐  │    │
│  │  │ integrations                                              │  │    │
│  │  │  ├─ freshness_integration.py (与探针联动)                 │  │    │
│  │  │  └─ golden_integration.py (与验证管线联动)                │  │    │
│  │  └─────────────────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                       │                                │
│                                       ▼                                │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                    数据存储                                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │    │
│  │  │ lineage_     │  │ lineage_     │  │ lineage_record    表  │  │    │
│  │  │ source     表  │  │ step         │  │ (血缘运行记录)       │  │    │
│  │  │ (数据源注册)  │  │ (转换步骤注册) │  └──────────────────────┘  │    │
│  │  └──────────────┘  └──────────────┘                             │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

血缘 - 外部联动关系：

  freshness_probe ──────────▶ freshness_integration ────▶ lineage_query
     (新鲜度检查)                 (关联血缘+新鲜度)            (查询时附带状态)

  verify_golden ────────────▶ golden_integration ──────▶ lineage_query
     (验证管线)                  (黄金样本血缘锚定)           (一致性验证)
```

---

## 6. 实施计划

### 6.1 实施阶段

| 阶段 | 内容 | 估计工时 | 依赖 |
|:-----|:-----|:---------|:-----|
| **P0** | 创建 `lineage_source` / `lineage_step` / `lineage_record` 表 DDL，在 `a50_ic.db` 中建表 | 1h | 无 |
| **P1** | 注册现有数据源和步骤到 `lineage_source` / `lineage_step` | 1h | P0 |
| **P2** | 实现植入点 A（ETL入口）和 B（中间结果）的元数据写入 | 2h | P1 |
| **P3** | 实现植入点 C（因子计算）和 D（IC输出）的元数据写入 | 2h | P2 |
| **P4** | 实现植入点 E（门禁报告）的元数据嵌入 | 0.5h | P3 |
| **P5** | 实现 `lineage/query.py`（trace_output, trace_source, lineage_graph） | 3h | P1 |
| **P6** | 实现 `freshness_integration.py` | 2h | P5 + freshness_probe |
| **P7** | 实现 `golden_integration.py` | 2h | P5 + verify_golden |
| **P8** | 端到端测试 + 文档完善 | 2h | P0~P7 |

### 6.2 文件结构

```
src/lineage/
├── __init__.py
├── model.py            # DDL + schema 常量
├── annotations.py      # 各植入点的标注函数
├── query.py            # 血缘查询接口
├── integrations/
│   ├── __init__.py
│   ├── freshness_integration.py  # 与 freshness_probe 联动
│   └── golden_integration.py     # 与 verify_golden 联动
└── tests/
    ├── test_model.py
    ├── test_annotations.py
    ├── test_query.py
    └── test_integrations.py
```

### 6.3 风险与注意事项

1. **性能影响**：`lineage_record` 表的写入每次管线运行增加 ~5 条记录，对 SQLite 影响可忽略。
2. **数据膨胀**：`lineage_record` 中的 JSON 字段（source_record, step_params）可能较大。建议对超过 1KB 的 JSON 进行压缩或外链。
3. **旧数据回溯**：已经运行的管线历史无法自动追溯。建议从实施之日起开始记录，对历史数据标记为 `version: legacy`。
4. **循环依赖**：确保血缘 DAG 中不存在循环引用（step A → step B → step A）。在写入时做环检测。
5. **版本演进**：当因子注册表或 ETL 逻辑变更时，需新增 `lineage_source`/`lineage_step` 版本记录，标记旧版本为 `deprecated`。

---

*设计文档结束 — 玄知 v1.0 / 2026-06-01*
