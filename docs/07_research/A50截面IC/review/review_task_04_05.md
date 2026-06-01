# 墨萱审查报告：task_04修复 + task_05

**审查时间**: 2026-05-29T22:14+08:00
**审查人员**: 墨萱 🔍
**审查文件**: `docs/07_research/A50截面IC/etl_a50_daily.py`（task_04修复 + task_05均在此文件内，无独立 build_a50_universe.py）

---

## task_04修复：T04-01 — PASS ✅

### 审查对象
`mark_suspension_rows()` 函数中的停牌检测逻辑。

### 修复前（假设状态）
```python
# 伪代码
if null_reason_col存在:
    is_suspended = condition_1
elif close列存在:
    is_suspended = condition_2
```
→ 上述 `elif` 会导致：当 `null_reason_col` 存在但值非 `SUSPENDED` 时，即使 `close IS NULL` 也无法捕获停牌。

### 修复后（当前代码 L68-L78）
```python
df['is_suspended'] = False
if null_reason_col in df.columns:
    df['is_suspended'] |= df[null_reason_col] == 'SUSPENDED'
if 'close' in df.columns:
    df['is_suspended'] |= df['close'].isna() | ((df['close'] == 0) & (df['volume'] == 0))
```

### 验证结论
1. **`if/elif` → `if/if` 已修改** ✅ — 两个条件使用独立 `if`，分别通过 `|=` 累加到 `is_suspended`
2. **逻辑正确性** ✅ — 任何一条条件为真即标记为停牌（OR语义），符合需求
3. **不影响其他逻辑** ✅ — `mark_suspension_rows` 返回值结构不变（仍返回带 `is_suspended` 列的 DataFrame），`filter_suspended_and_ipo` 调用方式不变，下游消费逻辑不变

---

## task_05：a50_universe构建 — PASS（带非阻塞建议）✅

### 审查对象
`etl_a50_daily.py` 中以下函数（L315-478）：
- `create_a50_universe_table()` — 建表（幂等）
- `build_a50_universe_from_tushare()` — 首选方案
- `build_a50_universe_by_define()` — 降级方案
- `verify_a50_universe()` — 验证
- `build_a50_universe()` — 入口（含升降级路由）

### 1. tushare API方案 — 合理 ✅
- 调用 `pro.index_member(index_code='000016.SH')` 获取上证50历史成分股变动
- 完整处理了无权限降级：
  - `try/except ImportError` → tushare 未安装
  - `try/except Exception` → API 请求失败（含免费版无权限）
  - 返回 `None` 触发降级
- **发现**: `ts.pro_api()` 未显式设置 token。若用户配置了 `TUSHARE_TOKEN` 环境变量则正常工作；若未配置，自动降级到 `by_define`。建议在函数注释中补充说明。

### 2. by_define降级方案 — 可接受 ✅
- 逻辑：从 `market_data.db` 取每只股票最小 `trade_date` 作为 `in_date`
- **合理性评估**：作为降级方案，这是一个合理的近似值。`MIN(trade_date)` 表示"该股票在数据集中最早可用的交易日期"，对于回测场景而言足够。缺点是对历史上较晚调入上证50的成分股，此日期偏早（近似于数据保留起始日而非真实纳入日）。建议文档中标注此精度限制。

### 3. 50条记录验证 — 完整 ✅
- `build_a50_universe_by_define()` L420: `assert len(rows) == 50` 保障源数据完整性
- `verify_a50_universe()` 覆盖以下检查：
  - ✅ 总记录数 ≥ 50
  - ✅ 当前成分股数（out_date IS NULL）> 0
  - ✅ in_date 完整性（缺失 = 0）
  - ✅ source 完整性（缺失 = 0）
  - ✅ 展示最早/最晚纳入样本

### 4. 建表接口幂等 — 正确 ✅
- `create_a50_universe_table()`: 使用 `CREATE TABLE IF NOT EXISTS`，索引使用 `CREATE INDEX IF NOT EXISTS`，完全幂等
- 数据写入方案：先 `DELETE FROM a50_universe` 再 `INSERT`，确保每次构建结果为完整替换
- 多次调用不会产生重复数据

---

## 发现的问题汇总

| # | 类型 | 描述 | 严重程度 |
|---|------|------|---------|
| 1 | ✅ 已修复 | T04-01 `if/elif` 问题已改为 `|=` 累加 | 原有缺陷已修复 |
| 2 | ⚠️ 建议 | tushare token 配置方式需补充文档说明 | 非阻塞（有降级） |
| 3 | ⚠️ 建议 | by_define 降级方案的 in_date 精度限制需文档标注 | 非阻塞 |

---

## 总评

| 审查项 | 结论 |
|--------|------|
| task_04修复（T04-01） | **PASS** ✅ |
| task_05（a50_universe构建） | **PASS** ✅ |

task_04修复干净利落，`if/elif` → `|=` 累加逻辑正确，不破坏现有结构。
task_05实现完整，双方案 + 降级路由 + 验证闭环，95分。建议补充tushare token配置说明文档。

---

*本报告由墨萱 🔍 出具，遵守TMPL-003审查规范*
