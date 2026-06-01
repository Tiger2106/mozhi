# 设计审查意见 — 墨萱

**文档**: `design_v1.md` (v1.0, 2026-05-29)
**审查时间**: 2026-05-29
**审查人**: 墨萱 (QA Lead)

---

## 📊 评分：**FAIL** (4/10)

设计整体框架合理，但发现 **3个必须修复** 的严重问题，不可进入Schema冻结阶段。

---

## 🔴 FAIL — 必须修复

### F1. DDL: `close REAL NOT NULL` 与停牌逻辑矛盾

**位置**: §1.2.1 `a50_daily_ohlcv` DDL + §3.3 `identify_suspensions()`

`close` 定义为 `NOT NULL`，但停牌逻辑 (§3.3 Step 5) 将停牌日 `close` 置为 `None(NULL)`。**SQLite会在INSERT时抛ConstraintViolation异常**。

**修改建议**:
- 方案A：`close` 改为 `REAL`（可空），SQL逻辑确保停牌日因子计算跳过该行
- 方案B：保留 `NOT NULL`，停牌日不插入该行（但会破坏ts_code+trade_date连续索引语义）
- **推荐方案A**，与 `null_reason` 的标记体系一致

### F2. Step 5 回看窗口SQL缺失下限

**位置**: §2.4 `get_dynamic_cross_section()` Step 5

```sql
WHERE trade_date <= ? AND ts_code IN ({})
```

没有设置 `trade_date` 的下界，导致每次加载**全部历史数据**（50只×4710天 ≈ 235,500行），严重拖慢性能且随运行次数增加持续恶化。

**修改建议**: 使用 `trade_date BETWEEN ? AND ?`，下界为 `trade_date - 120个交易日`。

### F3. IPO首日识别逻辑有误

**位置**: §3.3 `identify_suspensions()` Step 2

```python
is_ipo_first_day = df_sorted['adj_prev'].isna() & is_suspected_suspend
```

`adj_prev.isna()` 为 True 的不仅仅是IPO首日——还包括每个股票在数据集中的**第一行**（即2007-01-04的数据）。当提取范围不覆盖股票上市首日时，此条件会误判。

**修改建议**:
- 从 `a50_universe` 的 `in_date` 判断：`is_ipo_first_day = (trade_date == in_date)` 且满足退化条件
- 或：仅在 `ts_code` 最早交易日距今 > 20日时才标记为停牌

---

## 🟡 WARN — 需关注

### W1. float_share 未纳入 DDL

`turnover_20d_avg` 依赖 `float_share`，但 `a50_daily_ohlcv` DDL中无此字段。需决定：在ETL时join源表存储，还是在IC计算时跨库join。

### W2. forward_window 未持久化

`a50_cross_ic_result` 表没有 `forward_window` 字段。若默认5日窗口将来调整，新老数据无法区分。

### W3. volume_20d_change 公式描述与实现不匹配

文档公式写 `avg(volume[t-5:t])`（含当日），实现用 `.shift(1)` 排除当日。实现正确（无前视偏差），但需修文档公式一致。

### W4. Step 5 SQL注入风险

`','.join(['?'] * len(df))` 使用字符串格式化拼接参数化占位符，在 `df` 为空时生成 `IN ()` 语法错误。建议使用 `pandas.read_sql` 的 `params` 传参保证安全。

### W5. reversal_1d 除零风险无保护

`close / open` 在 `open≈0` 时产生Inf。A50成分股概率低，但建议加 `np.where(open > 0, ...)` 保护。

### W6. min_stocks=30 覆盖率未见预评估

摸底报告显示仅28.64%日期全50股完整。建议在Schema冻结前，统计 `min_stocks=30` 可保留的截面比例。若 < 70%，建议下调阈值。

---

## 📋 结论

**3个FAIL必须在 Schema冻结前修复**。F1是最严重的问题——当前DDL+代码逻辑不自洽，直接不可运行。修复后重新提交审查。修正后预期可升至 CONDITIONAL_PASS。
