# 墨萱审查：task_02 DDL修复 + task_03 ETL-P1

**审查时间**: 2026-05-29T22:04+08:00
**审查人**: 墨萱
**审查对象**: 
- `create_tables.py` (修复版)
- `etl_a50_daily.py`

---

## task_02 DDL修复审查

### C1-C7 修复逐项核对

| 编号 | 修复项 | 状态 | 证据 |
|------|--------|------|------|
| C1 | a50_daily_ohlcv → 新增 `null_reason TEXT` | ✅ PASS | 定义中存在 `null_reason TEXT`，注释说明语义 |
| C2 | a50_cross_ic_result → `section_date` → `trade_date` | ✅ PASS | 字段名为 `trade_date，r` 注释"截面日期YYYYMMDD" |
| C3 | a50_cross_ic_result → 新增 `rank_ic REAL` | ✅ PASS | 定义中存在，注释"Spearman秩相关IC" |
| C4 | a50_cross_ic_result → 新增 `adjusted_ic REAL` | ✅ PASS | 定义中存在，注释"剔除极值±3σ" |
| C5 | a50_cross_ic_result → 新增 `idx_ic_factor`, `idx_ic_date` | ✅ PASS | 两个索引均定义且独立 |
| C6 | a50_daily_ohlcv → 新增 `idx_a50_daily_date`, `idx_a50_daily_code` | ✅ PASS | 两个索引均定义且独立 |
| C7 | a50_universe → 新增 `created_at` | ✅ PASS | 定义中存在，带 DEFAULT |

### N1-N3 附加修复核对

| 编号 | 修复项 | 状态 | 证据 |
|------|--------|------|------|
| N1 | UNIQUE约束列顺序统一 | ✅ PASS | `a50_daily_ohlcv`: (ts_code, trade_date); `a50_cross_ic_result`: (trade_date, factor_name, source_version, forward_window); `a50_universe`: (ts_code, in_date) |
| N2 | ic_value 注释修正为 Pearson | ✅ PASS | 注释为"Pearson截面IC" |
| N3 | 索引命名统一 | ✅ PASS | 命名风格一致: idx_<表简称>_<列名>；TABLES_AND_INDICES 验证清单正确 |

### 索引清单核对

| 索引名 | 所属表 | 存在 |
|--------|--------|------|
| idx_a50_daily_pk | a50_daily_ohlcv | ✅ 唯一索引 (ts_code, trade_date) |
| idx_a50_daily_date | a50_daily_ohlcv | ✅ |
| idx_a50_daily_code | a50_daily_ohlcv | ✅ |
| idx_ic_factor | a50_cross_ic_result | ✅ |
| idx_ic_date | a50_cross_ic_result | ✅ |
| idx_universe_code_in_date | a50_universe | ✅ |
| idx_universe_in_out_date | a50_universe | ✅ |

### 结论

**task_02 DDL修复: ✅ PASS**

C1-C7 全部修复，索引命名规范，UNIQUE约束顺序正确。文件头注释清晰记录了修复清单。

---

## task_03 ETL-P1 审查

### 数据提取逻辑

```python
codes = src.execute("SELECT DISTINCT ts_code FROM stock_daily ORDER BY ts_code").fetchall()
assert len(code_list) == 50
```
- 从源表提取所有 DISTINCT ts_code
- assert 断言50只，防止意外数据
- 逐股 SELECT + 按 trade_date 排序
- ✅ 提取逻辑正确

**注意点**: 代码注释假设 `market_data.db` 恰好只包含50只A50股票。断言提供了防护。

### 字段映射

FIELD_MAP 共16个字段映射：
- `pe_ttm → pe` 符合设计约定
- `null_reason` 未在映射中（预期行为，留到task_04）
- `source_version` 在写入时手动设置为 `'v1'`（不在FIELD_MAP中，使用DEFAULT）
- `created_at` 未在映射中（使用DEFAULT datetime）
- ✅ 字段映射完整正确

### 后复权公式

```python
PRICE_COLS = ["open", "high", "low", "close", "pre_close"]
if adj_factor is not None and adj_factor > 0:
    for pc in PRICE_COLS:
        if record[pc] is not None:
            record[pc] = record[pc] * adj_factor
```
- 公式: `adj_price = price * adj_factor` ✅
- 5个价格列全部复权 ✅
- 保护逻辑：adj_factor非空且>0时执行，price非空时执行 ✅

### 复权方向断言逻辑

**verify_adj_direction()** — 源数据进行断言：
- 取茅台20241219-20241223（跨越除权日2024-12-20）
- 后复权: `fwd_bias = abs(ex_close*ex_adj / (prev_close*prev_adj) - 1)` 
- 前复权: `bwd_bias = abs(ex_close/ex_adj / (prev_close/prev_adj) - 1)`
- 断言 `fwd_bias < 1%`
- ✅ 逻辑清晰，且用前复权做对照，证据充分

**verify_extraction() 中验证4** — 目标数据进行断言：
- 后复权后，`pre_close(当天)` 应 ≈ `close(前一日)`
- 偏差 < 2%
- ✅ 除权连续性验证，与方向断言互补

### INSERT OR IGNORE

```python
insert_sql = f"INSERT OR IGNORE INTO a50_daily_ohlcv ({cols_str}) VALUES ({placeholders})"
dst.executemany(insert_sql, [[record[c] for c in dst_cols] for record in batch])
```
- `INSERT OR IGNORE` + UNIQUE索引 → 重复键自动忽略
- `executemany` 批量写入，性能可接受
- ✅ 处理正确

### 异常处理和数据库连接

```python
try:
    ...
except AssertionError as e:
    print(f"[FAILED] 断言失败: {e}")
    raise
except Exception as e:
    print(f"[FAILED] 数据提取失败: {e}")
    dst.rollback()
    raise
finally:
    src.close()
    dst.close()
```
- 断言异常和通用异常分离处理 ✅
- 通用异常中执行 `dst.rollback()` ✅
- `finally` 中关闭两个连接 ✅

### 发现的问题

**⚠️ 代码风格问题（非功能性缺陷）:**

1. **total_changes 累加后被覆盖**
   ```python
   total_written += dst.total_changes  # 累积计数，在循环中会重复计算
   # ...
   pass  # 空语句
   # 后续被直接覆盖:
   total_written = dst.execute("SELECT COUNT(*) FROM a50_daily_ohlcv").fetchone()[0]
   ```
   - `total_written += dst.total_changes` 在循环中会导致重复累加（因total_changes是累积的）
   - 但最终被 `SELECT COUNT(*)` 覆盖，所以逻辑上不构成bug
   - 建议直接删掉这行和 `pass`，或者改为注释

2. **`pass` 残留在循环末尾**
   ```python
   total_written += dst.total_changes  
   # 实际计数用rows
   # executemany 后通过 count 确认
   # 改用简单方式计数
   pass
   ```
   - 这是修改过程中留下的空语句，不影响功能

3. **PRAGMA foreign_keys 断言**
   ```python
   assert fk_status == 1, "PRAGMA foreign_keys 不为 ON!"
   ```
   - 三张表的DDL中均无 `REFERENCES` 外键约束
   - 断言PRAGMA foreign_keys = ON 在实际上不发挥约束作用
   - 建议要么移除该断言，要么在DDL中真正添加外键约束

**以上三点均为代码清理/风格问题，不影响功能正确性。**

### 结论

**task_03 ETL-P1: ✅ PASS**

数据提取逻辑正确，后复权公式正确，复权方向断言逻辑严谨，INSERT OR IGNORE处理正确，异常处理和数据库连接关闭完整。存在3个代码风格问题（非功能性缺陷），建议在后续修复中清理。

---

## 最终审查意见

| 审查项目 | 结论 |
|----------|------|
| task_02 DDL修复 | ✅ **PASS** |
| task_03 ETL-P1 | ✅ **PASS** |

**发现的问题**：3个代码风格问题（非功能性缺陷），不影响运行。
- `total_changes` 累加后被 `SELECT COUNT(*)` 覆盖（冗余代码）
- `pass` 残留语句
- PRAGMA foreign_keys 断言无实际FK约束可验证

**建议**：在后续修复中一并清理上述代码风格问题，当前版本可继续推进。

---

*审查人: 墨萱*
*审查标准: TMPL-003 回测QA验证清单（适配版）*
