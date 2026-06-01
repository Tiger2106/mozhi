# 墨萱审查：task_04 停牌识别 + IPO首日处理

**审查时间**: 2026-05-29T22:09+08:00
**审查人**: 墨萱
**审查对象**: 
- `etl_a50_daily.py`（新增的3个函数）
- `test_suspension_ipo.py`（单元测试）

**审查标准**: TMPL-003 回测QA验证清单（适配版）

---

## 1. `mark_suspension_rows()` — 3级检测逻辑审查

### 实现代码

```python
if null_reason_col in df.columns:
    df['is_suspended'] = df[null_reason_col] == 'SUSPENDED'
elif 'close' in df.columns:
    df['is_suspended'] = df['close'].isna() | ((df['close'] == 0) & (df['volume'] == 0))
else:
    df['is_suspended'] = False
```

### 🔴 问题1: 3级检测使用 `if/elif/else`，导致各层级互斥而非累加

**严重程度: 中**

文档声明"策略（3级检测）"，但实现使用 `if/elif/else`，意味着：
- 如果 `null_reason_col` 存在于 DataFrame 中，**只检测 level 1**，level 2 和 level 3 被跳过
- 如果 `close` 存在于 DataFrame 中（且 `null_reason_col` 不存在），**只检测 level 2+3**，level 1 被跳过
- 如果两者都不在，返回 False

"3级检测"的语义应是所有检测条件的 **OR 组合**，而非排他分支。正确的实现应是：

```python
# 建议改为累积式：
df['is_suspended'] = False
if null_reason_col in df.columns:
    df['is_suspended'] |= (df[null_reason_col] == 'SUSPENDED')
if 'close' in df.columns:
    df['is_suspended'] |= df['close'].isna() | ((df['close'] == 0) & (df['volume'] == 0))
```

**当前影响**: 在现有 ETL 流程中，`stock_daily` 表无 `null_reason` 列（已验证），且 FIELD_MAP 中未映射该字段，因此 `null_reason_col in df.columns` 始终为 False，代码走 level 2+3 分支。**当前无实际影响**，但如果未来上游数据开始提供 `null_reason` 列，3级检测将退化为1级检测，丢失 close/volume 的防护。

### ⚠️ 问题2: Level 1 (`null_reason`) 在当前流程中是死代码

**严重程度: 低**

经查验：
- `stock_daily` 表**无** `null_reason` 列（共26列，无该字段）
- FIELD_MAP 中未映射 `null_reason`
- SQL SELECT 语句只选取 FIELD_MAP 的 key

因此，`null_reason == 'SUSPENDED'` 分支在当前永久不可达。`a50_daily_ohlcv` 表虽然定义了 `null_reason TEXT` 列，但 ETL 流程从未写入该列（始终为 NULL）。

如果能确认上游 `stock_daily` 永远不会提供 `null_reason` 列，建议：**降级为2级检测并移除 level 1**，简化代码；或者保留 level 1 作为 future-proof，但修复 if/elif 问题。

---

## 2. `detect_ipo_first_day()` — 双重判断审查

### 🔴 问题3: 每组首行被错误标记为 IPO（设计缺陷）

**严重程度: 中**

```python
df['is_first_row'] = df.groupby(group_col).cumcount() == 0
df['adj_prev'] = df.groupby(group_col)['adj_factor'].shift(1)
df['is_ipo'] = df['is_first_row'] & df['adj_prev'].isna()
```

作者已在文档字符串中主动说明了此问题（值得肯定 ✅）：

> "由于分组内 shift(1) 令每组首行的 adj_prev 均为 NaN，is_first_row & adj_prev.isna() 等价于 is_first_row。这意味着每只股票的首行均被标记为 is_ipo=True。"

**实际影响**: 每个股票的数据丢失第一行。对于上证50的50只股票，合计丢失50行（约 0.02%）。现有断言 `expected_min = 50 * 4000` 仍能通过，属于未被验证到的数据损失。

**根本原因**: 双重判断形同虚设——`shift(1)` 产生的 NaN 是 **分组结构导致的必然结果**，而非 IPO 的标志。真正的 IPO 判断需要结合：
- `a50_universe.in_date`（该股票实际纳入A50或上市日期）
- 或者全局时间线首次出现的 trade_date

### ⚠️ 调用位置导致分组判断的内在局限性

```python
for i, code in enumerate(code_list):
    ...
    df_batch = pd.DataFrame(batch)
    df_batch = filter_suspended_and_ipo(df_batch)
```

`filter_suspended_and_ipo` 在**单股票批次内**被调用。每个 `df_batch` 只有一只股票的数据，分组 `group_col='ts_code'` 只有一组，每组的第一行就是该股票的第一行。因此 `is_ipo` 无条件为 True。

如果改为在**所有股票合并后**全局调用，则可以通过排序识别真正首次出现的 trade_date，但会增加代码复杂度。

### ✅ 没有误报停牌行被标记为 IPO

单元测试验证了：600000.SH 的停牌行（close=0, volume=0）没有被额外标记为 IPO。正确 ✅

---

## 3. `filter_suspended_and_ipo()` — 集成逻辑审查

### 执行流程

```python
df = mark_suspension_rows(df)
df = detect_ipo_first_day(df)
filtered = df[~df['is_suspended'] & ~df['is_ipo']].copy()
filtered.drop(columns=['is_suspended', 'is_ipo', 'is_first_row', 'adj_prev'], ...)
```

### ✅ 流程清晰，列清理正确

- 有序调用两个子函数 ✅
- 布尔索引过滤，`copy()` 防止视图链 ✅
- 中间列 `errors='ignore'` 安全清理 ✅
- 打印统计信息便于日志追踪 ✅

### ✅ 与主流程集成正确

在 `extract_a50_data()` 中，`filter_suspended_and_ipo` 被放在后复权计算后、executemany 写入前：

```python
if batch:
    df_batch = pd.DataFrame(batch)
    df_batch = filter_suspended_and_ipo(df_batch)
    if df_batch.empty:
        print(f"...全部被过滤，跳过")
        continue
```

- 复权后的 close=0 仍是 0（0×adj_factor=0），检测正确 ✅
- 空DataFrame处理正确 ✅
- 过滤后使用 `df_batch[dst_cols]` 确保只写入目标列 ✅

---

## 4. 单元测试覆盖度分析

### 测试数据集

| ts_code | 行数 | 特征 | 预期处理 |
|---------|------|------|---------|
| 600519.SH | 3 | 正常 | 全部保留 |
| 601857.SH | 2 | 正常 | 全部保留 |
| 000001.SZ | 2 | 正常 | 全部保留 |
| 600000.SH | 3 | 中间行 close=0, volume=0 | 首行(IPO)+中行(停牌)排除→留1行 |
| 688999.SH | 1 | 单独一只，新上市 | 标记IPO→排除 |
| 688888.SH | 2 | 正常 | 全部保留 |

### 覆盖度评估

| 测试场景 | 状态 | 说明 |
|----------|------|------|
| ✅ 停牌检测: close=0, volume=0 | ✅ 已覆盖 | 600000.SH 中间行 |
| ❌ 停牌检测: close IS NULL | ❌ 未覆盖 | 需要对某行 close 设为 None |
| ❌ 停牌检测: null_reason == 'SUSPENDED' | ❌ 未覆盖 | `make_test_df` 无 null_reason 列 |
| ❌ 停牌检测: close=0, volume>0（不应标记） | ❌ 未覆盖 | 边界情况缺失 |
| ❌ 停牌检测: close>0, volume=0（不应标记） | ❌ 未覆盖 | 边界情况缺失 |
| ✅ IPO检测: 每组首行标记 | ✅ 已覆盖 | 6组首行均被标记 |
| ❌ IPO检测: 非首行不应标记 | ❌ 未明确断言 | 代码隐含，但无显式断言 |
| ✅ 集成过滤: 正常行保留 | ✅ 已覆盖 | 各正常标的 |
| ✅ 集成过滤: 列清理 | ✅ 已覆盖 | 确认中间列不存在于过滤后数据 |
| ❌ 空DataFrame处理 | ❌ 未覆盖 | 所有行都被过滤的边界情况 |
| ❌ 不含必须列的场景 | ❌ 未覆盖 | 缺少 close/volume/adj_factor 等 |

**单元测试覆盖度评估: 约 6/12 = 50%**，关键路径覆盖但边界情况和分支覆盖不足。

---

## 5. 与现有ETL流程兼容性

### 集成点审查

| 集成点 | 工作方式 | 兼容性 |
|--------|---------|--------|
| DDL兼容性 | `a50_daily_ohlcv` 表有 `null_reason TEXT` 列 | ✅ 兼容（即便当前不写入） |
| 字段映射 | 无新增字段，复用已有字段 | ✅ 兼容 |
| 处理顺序 | 后复权 → 过滤 → 写入 | ✅ 兼容（过滤在复权后） |
| 数据库schema | 无变更 | ✅ 兼容 |
| 断言一致性 | `verify_extraction` 中的行数断言 `> 200,000` | ⚠️ 通过但未验证数据丢失 |

### ⚠️ 问题4: `main()` 函数的注释存在歧义

```python
print(f"  请继续执行 task_04 （停牌处理）")
```

task_03 的 main 函数中写了"请继续执行 task_04"，但 task_04 的过滤逻辑实际已在 `extract_a50_data()` 中调用 `filter_suspended_and_ipo` 时被执行。**task_04 的代码已直接集成到 task_03 的 ETL 流程中**，不是"继续执行"的关系，而是"已包含"的关系。

---

## 总结

### 审查结论

| 审查项 | 结论 |
|--------|------|
| `mark_suspension_rows()` — 3级检测逻辑 | ⚠️ **WARN**（if/elif 排他而非累加） |
| `detect_ipo_first_day()` — 双重判断 | ⚠️ **WARN**（失效的设计，每组首行被误标) |
| `filter_suspended_and_ipo()` — 集成逻辑 | ✅ **PASS** |
| 单元测试覆盖度 | ⚠️ **WARN**（~50%，缺边界条件） |
| 与ETL流程兼容性 | ✅ **PASS** |

### 发现的问题清单

| 编号 | 类型 | 严重程度 | 描述 | 建议修复 |
|------|------|---------|------|---------|
| T04-01 | 逻辑缺陷 | 中 | `mark_suspension_rows` 的3级检测用 if/elif 排他，应改为 |= 累加 | 改为累积式 OR 赋值 |
| T04-02 | 逻辑缺陷 | 中 | `detect_ipo_first_day` 每组首行均被误标为 IPO | 需要结合 `a50_universe.in_date` 或全局 trade_date 判断真实上市日 |
| T04-03 | 死代码 | 低 | Level 1（null_reason）在当前 ETL 流程中永久不可达 | 确认上游策略后确认是否保留或移除 |
| T04-04 | 测试不足 | 低 | 单元测试边界覆盖不全（close IS NULL, null_reason, 边界条件） | 补充 6 个缺失的测试场景 |
| T04-05 | 注释歧义 | 低 | main() 中说"请继续执行 task_04"但代码已集成 | 更新注释 |

### 最终结论

**审查：WARN — 有条件通过**

T04-02（IPO误判）是影响数据正确性的设计缺陷，但当前影响面可控（每只股票丢失首行）。如果在验证阶段发现截面IC值存在系统性偏差，需要回溯此过滤逻辑。建议在 ETL-P2（task_05 或 task_06）中结合 `a50_universe.in_date` 修复IPO首日判断。

T04-01（if/elif排他）建议立即修复，改动仅2行，不影响功能但保证未来扩展性。

---

*审查人: 墨萱*
*审查时间: 2026-05-29T22:09+08:00*
*审查标准: TMPL-003 回测QA验证清单（适配版）*
