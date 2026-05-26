<!--
author: 墨衡
created_time: 2026-05-20T21:20+08:00
-->

# stock_daily.volume 单位混用问题调查报告

> 调查时间：2026-05-20 21:10+08:00
> 调查人：墨衡

---

## 一、核心结论

1. **影响范围有限但严重**：4,620 条记录中 **83 条（1.8%）存在单位混用**，集中在 601857（中国石油）2026年后的数据
2. **根因明确**：`data_source.py` 中东方财富 API（股）和新浪 fallback API（手）的单位不一致，`data_loader.py` 未做归一化
3. **market_daily 是权威表**：volume 单位一致（均为"股"），且覆盖标的可直接替代 stock_daily
4. **建议方案**：**优先废弃 stock_daily，统一使用 market_daily**；如需保留，修复数据写入层

---

## 二、影响范围（量化）

### 2.1 表统计概览

| 项目 | stock_daily | market_daily |
|:-----|:----------:|:------------:|
| 总行数 | 4,620 | 3,080 |
| 标的数 | 3 | 2 |
| 标的列表 | 000001, 600519, 601857 | 000001.SZ, 601857.SH |
| 时间范围 | 20200102 ~ 20260515 | 2020-01-02 ~ 2026-05-15 |
| volume 类型 | INTEGER | REAL |
| 数据来源 | 东方财富(主) + 新浪(fallback) | 未明确（来源单一，单位一致） |

### 2.2 单位混用逐标的分析

| 标的 | 总行数 | 股(股) | 手(手) | 手占比 | 判定依据 |
|:----|:-----:|:------:|:------:|:-----:|:---------|
| 000001（平安银行） | 1,540 | **1,540** | 0 | **0%** | 与 market_daily 完全一致 (ratio=1.0) |
| 600519（贵州茅台） | 1,540 | **1,540**(推定) | 0 | **0%** | amount/volume=implied_price≈close，验证为股 |
| 601857（中国石油） | 1,540 | 1,456 | **83** | **5.4%** | 2026/1/5 前为股，之后切换为手 |

**总计受影响：83 条记录，占 stock_daily 全量的 1.8%。**

### 2.3 时间集中度

**单位不统一数据全部集中在 2026-01-05 之后，且仅限 601857。**

- 2020-01-02 ~ 2025-12-31：所有标的 volume 均为"股"（一致）
- 2026-01-05 起：601857 的 stock_daily.volume 切换为"手"（×100 换算关系）
- 000001 始终保持在"股"（未受影响）

### 2.4 volume 量级分布

| 量级区间 | stock_daily | market_daily |
|:---------|:-----------:|:-----------:|
| <1K | 0 | 0 |
| 1K~1M | 0 | 0 |
| 1M~10M | **1,606 (35%)** | 0 |
| 10M~50M | 100 (2%) | **82 (3%)** |
| 50M~100M | 1,179 (26%) | **1,179 (38%)** |
| 100M~500M | 1,718 (37%) | **1,794 (58%)** |
| 500M~1B | 17 (0%) | **24 (1%)** |
| >=1B | 0 | 1 (<0.1%) |

stock_daily 中 35% 的数据落在 1M~10M 区间（对应 601857 切换前后的"手"数据和 600519 正常"股"数据），这些在 market_daily 中不存在，说明 stock_daily 覆盖了更多小成交量的标的/时段。

---

## 三、根因分析

### 3.1 写入链路

```
akshare API 调用
├─ ak.stock_zh_a_hist (东方财富) → volume 单位：股 (shares) ★ 主路径
└─ ak.stock_zh_a_daily (新浪)    → volume 单位：手 (lots, 1手=100股) ★ fallback 路径
         ↓
data_source.py fetch_daily() 返回未归一化的 DataFrame
         ↓
data_loader.py populate_stock_daily() → int(row["volume"]) 直接写入
```

### 3.2 关键问题点

**问题 1**：`data_source.py` 的 `fetch_daily()` 中，东方财富失败后切换新浪 fallback，**但未对不同 API 的 volume 单位差异做任何处理**。

关键源码（data_source.py）：
```python
# 东方财富重试耗尽 → 新浪 fallback（一次，不重复重试）
try:
    import akshare as ak
    sina_symbol = _to_sina_symbol(symbol)
    df = ak.stock_zh_a_daily(...)  # ← volume 是"手"
    used_sina = True
except Exception as e2:
    raise ConnectionError(...)
```

**问题 2**：`data_loader.py` 写入时直接 `int(row["volume"])`，**无单位检测或转换**：
```python
int(row["volume"])  # ← 盲写，不知是股还是手
```

**问题 3**：`data_source.py` 仅进行了列名映射（中文→英文），未做量纲归一化。

### 3.3 为何仅影响 601857 且仅影响 2026 年后？

从数据表现推断：2026 年起，东方财富 API 针对 601857（中国石油）开始出现失败或返回异常，触发新浪 fallback 路径。000001（平安银行）未触发 fallback，600519 可能是新采集的数据。

---

## 四、统一难度评估

### 4.1 通过数值量级自动判断可行吗？

**不完全可靠**。原因：

| 方案 | 可靠性 | 说明 |
|:----|:------:|:-----|
| 阈值检测（volume < 10M → 手） | ❌ 中 | 600519 正常 volume 在 1M~19M 之间，与 601857 切换后的 手 数据（1M~3M）量级重叠 |
| price × volume × 100 ≈ amount 检测 | ✅ 高 | 可精确区分：amount / volume ≈ close × 100 → 手；amount / volume ≈ close → 股 |
| 与 market_daily 交叉验证 | ✅ 最高 | 相同 date + symbol 的 ratio 判定 |

**边界情况**：量级在 1M~5M 区间存在重叠（600519 正常股数据 vs 601857 手数据），纯阈值无法区分。

### 4.2 跨表对比

| 对比维度 | stock_daily | market_daily | 结论 |
|:---------|:-----------|:------------|:-----|
| 覆盖标的 | 3（含 600519） | 2（无 600519） | market_daily 缺失 600519 |
| 时间跨度 | 一致 | 一致 | ✅ 相同 |
| volume 单位一致性 | ❌ 混用 | ✅ 一致（均为股） | market_daily 优 |
| 数据覆盖完整性 | ⚠️ 含填充（停牌日 volume=0） | 未见填充标记 | market_daily 更干净 |

---

## 五、权威数据源对比

### 5.1 数据一致性

对 000001（平安银行）进行逐日对比（共 1,540 天）：
- stock_daily.volume == market_daily.volume 比例：**100%**
- 两表数据**完全相同**，说明数据源重叠

对 601857（中国石油）进行逐日对比：
- 股 vs 股 一致比例：**94.5%**（1,456/1,540）
- 83 条差异 = 切换到手

### 5.2 建议权威选择

**market_daily 更适合作为因子计算的标准数据源**：
1. ✔ volume 单位一致（均为股）
2. ✔ 数据更干净（无填充标记污染）
3. ✔ 与 stock_daily 数据完全一致（对 000001）

**stock_daily 的剩余价值**：提供 600519（贵州茅台）的数据，但不含 601857 的 2026 年前数据（市场必需）。

---

## 六、具体建议方案

### 方案 A（推荐）：废弃 stock_daily，统一使用 market_daily

```
操作：
1. 因子计算统一读取 market_daily 表
2. market_daily 新增 600519 标的（从 stock_daily 同步或重采）
3. stock_daily 标记为 deprecated，迁移期后删除

优点：
- 零单位问题
- 数据更干净
- 与已有验证结果一致

成本：
- 需要补充 600519 到 market_daily
- 现有依赖 stock_daily 的代码需要迁移
```

### 方案 B（短期修复）：修复 data_source + data_loader

```
操作：
1. data_source.py fetch_daily() 统一输出为"股"：
   - 检测 API 来源
   - 若来自新浪（手）→ ×100 转换为股
2. data_loader.py 写入前校验单位一致性：
   - amount / (close × volume) 应该在 [0.8, 1.2] 范围
   - 若约等于 0.01 → 手，自动 ×100 转换

优点：
- 存量数据可通过重跑修复
- 不改变表结构

缺点：
- 存量 83 条错误数据需要重新采集
- 多一层检测逻辑增加的维护成本
```

### 方案 C（推荐组合）：方案 A + 修复混合

```
操作：
1. 因子计算层切换到 market_daily（方案 A）
2. 同步修复 stock_daily 写入链路（方案 B），作为兼容层保留
3. stock_daily 作为 market_daily 的数据源备份保留

优点：
- 主链路无风险
- stock_daily 可作为离线数据源可用
```

---

## 七、附录：数据取证详细过程

### 7.1 SQL 验证

```sql
-- 确认单位混用行
SELECT sd.date, sd.volume AS sd_vol, md.volume AS md_vol,
       ROUND(CAST(sd.volume AS REAL) / md.volume, 4) AS ratio
FROM stock_daily sd
JOIN market_daily md 
  ON sd.code = SUBSTR(md.symbol, 1, 6) 
 AND SUBSTR(sd.date, 1, 4) || '-' || SUBSTR(sd.date, 5, 2) || '-' || SUBSTR(sd.date, 7, 2) = md.trade_date
WHERE sd.code = '601857' AND md.volume > 0
  AND CAST(sd.volume AS REAL) / md.volume < 0.02
ORDER BY sd.date DESC;
```

### 7.2 引用源文件

- `C:\Users\17699\mozhi_platform\src\backtest\data_source.py` — 数据源（双API）
- `C:\Users\17699\mozhi_platform\src\backtest\data_loader.py` — 数据灌入
- `C:\Users\17699\mozhi_platform\data\market\market_data.db` — 数据库
- `C:\Users\17699\mozhi_platform\src\backtest\data_historical_fill.py` — 批量采集脚本
