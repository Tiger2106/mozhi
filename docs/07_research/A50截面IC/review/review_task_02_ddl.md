# task_02 DDL审查意见

> **审查者**: 墨萱 🔍
> **文件**: `create_tables.py`
> **设计依据**: `design_v2.md §1.2`
> **审查时间**: 2026-05-29T21:59+08:00
> **审查结论**: **退回**

---

## 1. 审查清单逐项核验

### 1.1 DDL字段类型、约束与design_v2一致性

#### a50_daily_ohlcv

| # | 字段 | design_v2 | create_tables.py | 结论 |
|:--|:-----|:----------|:-----------------|:----:|
| 1 | id | INTEGER PK AUTO | ✅ | OK |
| 2 | ts_code | TEXT NOT NULL | ✅ | OK |
| 3 | trade_date | TEXT NOT NULL | ✅ | OK |
| 4 | open | REAL | ✅ | OK |
| 5 | high | REAL | ✅ | OK |
| 6 | low | REAL | ✅ | OK |
| 7 | close | REAL (可NULL) | ✅ | OK |
| 8 | pre_close | REAL | ✅ | OK |
| 9 | volume | REAL | ✅ | OK |
| 10 | amount | REAL | ✅ | OK |
| 11 | turnover_rate | REAL | ✅ | OK |
| 12 | pe | REAL | ✅ | OK |
| 13 | pb | REAL | ✅ | OK |
| 14 | adj_factor | REAL NOT NULL | ✅ | OK |
| 15 | float_share | REAL | ✅ | OK |
| 16 | **null_reason** | **TEXT (设计§1.2.1)** | **❌ 缺失** | **FAIL** |
| 17 | **total_share** | **设计DDL无此字段** | **REAL (额外添加)** | **WARN** |
| 18 | source_version | TEXT NOT NULL | ✅ DEFAULT 'v1' | OK |
| 19 | created_at | TEXT NOT NULL DEFAULT | ✅ | OK |

#### a50_cross_ic_result

| # | 字段 | design_v2 | create_tables.py | 结论 |
|:--|:-----|:----------|:-----------------|:----:|
| 1 | id | INTEGER PK AUTO | ✅ | OK |
| 2 | **trade_date** | **TEXT NOT NULL** | **`section_date` ❌ 命名不符** | **FAIL** |
| 3 | factor_name | TEXT NOT NULL | ✅ | OK |
| 4 | ic_value | REAL (Pearson IC) | ✅ (注释误标为Spearman) | WARN |
| 5 | **rank_ic** | **REAL (Spearman)** | **❌ 缺失** | **FAIL** |
| 6 | p_value | REAL | ✅ | OK |
| 7 | num_stocks | INTEGER NOT NULL | ✅ | OK |
| 8 | **adjusted_ic** | **REAL (±3σ后重算)** | **❌ 缺失** | **FAIL** |
| 9 | **icir** | **设计DDL无此字段** | **REAL (额外添加)** | **MINOR** |
| 10 | **ic_std** | **设计DDL无此字段** | **REAL (额外添加)** | **MINOR** |
| 11 | **ic_positive_ratio** | **设计DDL无此字段** | **REAL (额外添加)** | **MINOR** |
| 12 | forward_window | INTEGER NOT NULL DEFAULT 5 | ✅ NOT NULL (无DEFAULT) | OK |
| 13 | source_version | TEXT NOT NULL | ✅ DEFAULT 'v1' | OK |
| 14 | created_at | TEXT NOT NULL DEFAULT | ✅ | OK |

#### a50_universe

| # | 字段 | design_v2 | create_tables.py | 结论 |
|:--|:-----|:----------|:-----------------|:----:|
| 1 | id | INTEGER PK AUTO | ✅ | OK |
| 2 | ts_code | TEXT NOT NULL | ✅ | OK |
| 3 | stock_name | TEXT | ✅ | OK |
| 4 | in_date | TEXT NOT NULL | ✅ | OK |
| 5 | out_date | TEXT (可NULL) | ✅ | OK |
| 6 | weight | REAL | ✅ | OK |
| 7 | source | TEXT NOT NULL | ✅ DEFAULT 'tushare' | MINOR |
| 8 | **created_at** | **TEXT NOT NULL DEFAULT** | **❌ 缺失** | **FAIL** |

### 1.2 NULL语义检查 ✅

- `close` 可NULL ✅（注释说明停牌日置NULL）
- `pre_close` 非NULL约束未设（设计亦未要求 NOT NULL）✅
- `out_date` 可NULL（代表仍在成分股中）✅

### 1.3 索引设计

| 表 | 设计索引 | create_tables.py | 结论 |
|:---|:---------|:-----------------|:----:|
| a50_daily_ohlcv | `idx_a50_daily_pk` UNIQUE(ts_code,trade_date) | `UNIQUE(ts_code,trade_date)` (等价) | ✅ |
|  | `idx_a50_daily_date` ON (trade_date) | **❌ 缺失** | **FAIL** |
|  | `idx_a50_daily_code` ON (ts_code) | **❌ 缺失** | **FAIL** |
| a50_cross_ic_result | `idx_ic_uniq` UNIQUE(trade_date,factor_name,source_version,forward_window) | UNIQUE(section_date,factor_name,forward_window,source_version) (列顺序不一致) | WARN |
|  | `idx_ic_factor` ON (factor_name) | **❌ 缺失** | **FAIL** |
|  | `idx_ic_date` ON (trade_date) | **❌ 缺失** | **FAIL** |
| a50_universe | `idx_universe_code_in_date` ON (ts_code,in_date) | `idx_universe_code_in` (名不同，列同) | ✅ |
|  | `idx_universe_in_out_date` ON (in_date,out_date) | `idx_universe_in_out` (名不同，列同) | ✅ |

### 1.4 PRAGMA foreign_keys=ON ✅

脚本中已设置：
```python
conn.execute("PRAGMA foreign_keys = ON;")
```
且设置后通过查询确认状态为ON。✅

### 1.5 异常处理 ✅

- try/except 包装完整操作
- 失败时 `sys.exit(1)`，非静默失败
- finally 确保 conn.close()
- 各步骤自带状态打印和断言验证

---

## 2. 问题汇总

### ❌ CRITICAL（必须修复）

| ID | 表 | 问题 | 依据 |
|:--:|:---|:-----|:------|
| C1 | a50_daily_ohlcv | **缺失 `null_reason` 字段** | design_v2 §1.2.1 明确列出该字段，用于停牌/缺失区分（SUSPENDED/MISSING/null）。后续ETL代码(§3.3)依赖此字段。 |
| C2 | a50_cross_ic_result | **字段名 `section_date` 应改为 `trade_date`** | design_v2 §1.2.2 全篇使用 `trade_date`，命名一致性。 |
| C3 | a50_cross_ic_result | **缺失 `rank_ic` (REAL)** | design_v2 §1.2.2 设计默认同时输出Pearson IC + Spearman秩相关。缺失则损失信息。 |
| C4 | a50_cross_ic_result | **缺失 `adjusted_ic` (REAL)** | design_v2 §1.2.2 设计剔除±3σ极端值后重算。缺失则无法评估极端值影响。 |
| C5 | a50_cross_ic_result | **缺失 `idx_ic_factor`、`idx_ic_date` 索引** | design_v2 §1.2.2 明确列出按factor_name和trade_date的独立索引，无则该表大查询无索引可用。 |
| C6 | a50_daily_ohlcv | **缺失 `idx_a50_daily_date`(trade_date)、`idx_a50_daily_code`(ts_code)** | design_v2 §1.2.1 明确列出这两个索引。`idx_a50_daily_date` 对日期范围查询至关重要（UNIQUE复合索引无法单独覆盖trade_date）。 |
| C7 | a50_universe | **缺失 `created_at` 字段** | design_v2 §1.2.3 明确列出 `created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))`。 |

### ⚠️ MAJOR（建议修复）

| ID | 表 | 问题 | 说明 |
|:--:|:---|:-----|:------|
| M1 | a50_cross_ic_result | `icir`、`ic_std`、`ic_positive_ratio` 为设计DDL未列出的额外字段 | 虽然这些字段在管线中可能计算，但设计DDL中未列出，建议先在design_v2中补充说明再加入，或移除后另建统计表。 |
| M2 | a50_daily_ohlcv | `total_share` 设计DDL中未列出 | 设计§3.1.1提到作为float_share的降级方案，但未在正式DDL中列出。建议在design_v2 DDL中补充说明。 |

### 📝 MINOR（建议修改）

| ID | 问题 | 建议 |
|:--:|:-----|:-----|
| N1 | `a50_cross_ic_result` 中 `UNIQUE` 列顺序与设计不一致 | 设计：`(trade_date, factor_name, source_version, forward_window)`；实现：`(section_date, factor_name, forward_window, source_version)`。源头是C2的命名问题，修复C2后列顺序也需核对。 |
| N2 | `ic_value` 注释误标 "Spearman rank correlation" | 按设计，`ic_value` 为Pearson IC，`rank_ic` 为Spearman IC。 |
| N3 | `a50_universe` 索引名与设计不完全一致 | 功能等价，建议统一命名便于后续维护。 |

---

## 3. 审查结论

```
审查：❌ 退回
严重问题数:  7 (CRITICAL)
建议修复数:  2 (MAJOR)
轻微问题数:  3 (MINOR)
```

**退回理由**：`create_tables.py` 在字段定义和索引设计上与 `design_v2.md §1.2` 存在7项关键偏差，包括3个必选字段缺失、1个字段重命名、3个设计索引未创建。这些偏差将直接导致后续ETL流程（依赖 `null_reason`）和IC计算管线（依赖 `rank_ic`、`adjusted_ic`）无法按设计运行。

**请墨衡修复后重新提交**（≤2次退回机会，第3次升级Owner介入）。
