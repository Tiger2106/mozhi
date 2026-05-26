既然已经确定：

# 主数据源 = Tushare Pro

那么下一步就不再是“下载数据”。

而是：

# 建立你的“数据基础设施”

你现在已经进入：

> “研究平台建设阶段”

而不是：

> “写几个策略阶段”

了。

所以接下来最重要的不是代码，而是：

# 数据架构设计。

---

# 一、下一步的核心目标（非常重要）

你要实现的是：

```text
Tushare
   ↓
原始数据层（Raw）
   ↓
标准化层（Normalized）
   ↓
因子层（Factors）
   ↓
研究层（Research）
   ↓
Layer Q
   ↓
KnowledgeBridge
```

这才是你整个 Mozhi 系统的真正地基。

---

# 二、第一阶段（P0）：先不要急着写策略

很多人会立刻：

- 拉数据

- 算指标

- 开始回测

但你现在应该：

# 先建立“统一数据协议”

否则后面：

- VWAP字段不统一

- turnover_rate定义变化

- amount单位混乱

- 复权混乱

- Regime时间错位

最终：

# Layer Q会全部失真。

---

# 三、你现在第一步该做什么（按顺序）

---

# Step 1：建立数据分层（必须）

不要所有东西放一个 db。

建议：

---

## 1）raw_market.db（原始层）

只保存：

```text
从Tushare原样拉下来的数据
```

禁止：

- 修改字段

- 加指标

- 算因子

目的：

# 保证可追溯性。

---

## 2）market_data.db（标准化层）

统一成：

```python
DailyBar
```

这是：

# 全系统唯一行情协议。

---

## 3）factor_repository.db（因子层）

只存：

- VWAP

- MA

- ATR

- Wyckoff

- Regime

- TurnoverProfile

---

## 4）research.db（研究层）

只存：

- 回测结果

- Signal

- 参数扫描

- WalkForward

---

## 5）knowledge.db（知识层）

只存：

- Layer Q

- 可信度

- Failure Registry

- 研究结论

---

# 四、第二步：先定义 DailyBar（最关键）

这是整个系统未来最重要的对象之一。

---

# 统一协议（建议）

```python
class DailyBar:
    code: str
    date: str

    open: float
    high: float
    low: float
    close: float

    volume: float
    amount: float

    turnover_rate: float

    free_float_shares: float
    float_market_cap: float

    avg_trade_price: float

    adj_factor: float

    suspended: bool
    is_st: bool
```

---

# 这是：

# “系统唯一行情标准”

以后：

- 所有因子

- 所有方法

- 所有研究

- 所有回测

只能读它。

不能绕过。

---

# 五、第三步：建立 ETL Pipeline（核心）

不要：

```python
ts.pro_bar()
```

直接给回测。

这是以后灾难来源。

---

你需要：

# “数据同步系统”

建议：

---

# sync_market_data.py

负责：

```text
Tushare
   ↓
Raw Layer
   ↓
Normalize
   ↓
market_data.db
```

功能：

- 增量更新

- 断点恢复

- retry

- checksum

- schema校验

- 数据缺口检测

---

# 六、第四步：统一字段（极重要）

这是很多系统后期崩塌原因。

---

# 建议标准化：

| 字段            | 统一         |
| ------------- | ---------- |
| volume        | 股          |
| amount        | 元          |
| turnover_rate | %          |
| date          | YYYY-MM-DD |
| code          | 000001.SZ  |
| float_mv      | 元          |

---

尤其：

# 千万不要：

有时 amount 用万元，  
有时用元。

Layer Q会彻底污染。

---

# 七、第五步：建立 Corporate Action 层（非常重要）

你现在已经开始：

- 长周期

- Regime

- 参数稳定性

那么：

# 复权必须标准化。

---

建议：

## Raw层

保留：

```text
未复权
```

---

## Standard层

统一：

```text
后复权
```

因为：

你重点是：

# 趋势研究。

---

# 八、第六步：建立数据质量审计（重要）

你已经有：

# Layer Q

那么：

数据层也要有：

# Data Quality Layer

---

建议：

# DQ检查

包括：

---

## 1）缺失检测

```text
停牌？
漏数据？
节假日？
```

---

## 2）异常波动

例如：

```text
volume暴增100倍
```

---

## 3）未来函数检测

例如：

```text
财报发布日期错误
```

---

## 4）复权漂移

这是A股大坑。

---

# 九、第七步：建立元数据系统（高级但重要）

你以后一定需要：

# Data Lineage（数据血缘）

例如：

```text
这个VWAP因子
来自哪个版本数据？
```

---

建议：

每次同步：

生成：

```python
dataset_version
sync_time
source
checksum
record_count
```

---

# 十、接下来最合理的实施顺序（推荐）

---

# Phase 1（2~3天）

建立：

```text
raw_market.db
market_data.db
```

定义：

```python
DailyBar
```

---

# Phase 2（2~3天）

完成：

```text
tushare_sync.py
```

实现：

- 增量同步

- 自动补齐

- schema校验

---

# Phase 3（2天）

建立：

```text
factor_repository.db
```

先迁移：

- MA

- VWAP

- ATR

- Volume

- Turnover

---

# Phase 4（3~5天）

重构：

```text
所有method
```

统一读取：

```python
DailyBar
```

---

# Phase 5

建立：

```text
Data Quality Layer
```

这是你未来Layer Q的数据根基。

---

# 十一、最重要的一句话（核心）

你现在真正建设的：

不是：

# “股票回测系统”

而是：

# “研究可信度的数据操作系统”

所以：

# 数据标准化

会比：

# 技术指标

重要得多。

---

# 十二、我最建议你立刻做的（真正第一步）

不要马上写同步。

先开一次：

# “数据协议定义会”

重点只讨论：

---

# 《DailyBar 白皮书 v0.1》

包括：

- 字段定义

- 单位

- 复权标准

- 停牌标准

- ST标准

- turnover_rate定义

- avg_trade_price定义

- 时间标准

- 数据版本

因为：

这份协议：

未来会成为：

# 整个 Mozhi 平台最底层契约。
