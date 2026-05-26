你的方向是对的，而且这套安装流程基本已经覆盖了「数据源切换」的关键准备步骤。  
但如果你的目标是：

> “把 Tushare Pro 正式接入你的量化研究/回测系统，作为长期可靠主数据源”

那么下一步不能只是“能拉数据”，而是要进入：

# 从“能用”升级到“可研究、可回测、可审计”

你现在应该进入 Phase 1：数据基础设施建设。

我建议按下面顺序推进。

---

# 一、不要直接改现有回测系统

先建立：

```text
datahub/
    tushare_client.py
    fetchers/
    validators/
    storage/
    sync/
```

原因：

你现在最危险的事，是：

```text
回测系统直接调用 tushare
```

以后会出现：

- API限流

- Token失效

- 字段变更

- 停牌数据异常

- 前复权变化

- 数据版本不一致

导致：

```text
同一策略今天回测结果 ≠ 下周回测结果
```

这是研究系统的大忌。

所以：

# Tushare 只能进入“数据层”

不能直接进入策略层。

---

# 二、建立“标准市场数据协议”

这是你现在最重要的一步。

建议统一成：

```python
MarketDailyBar
```

标准字段：

```python
symbol
trade_date

open
high
low
close

volume
amount
turnover_rate

vwap
adj_factor

pct_chg

source
version
updated_at
```

原因：

以后：

- Tushare

- JoinQuant

- Wind

- 同花顺

- CSV历史库

都能映射到同一个结构。

这是你未来支持：

- 多数据源

- 数据校验

- 数据对比

- 回测复现

的基础。

---

# 三、先解决“换手率”问题

你前面已经意识到：

> volume 不够，真实量能应看 turnover_rate

这是非常关键的升级。

建议：

# 把换手率作为一级核心字段

不要再把它当附属字段。

你的回测系统未来很多分析：

- 趋势可信度

- 量价共振

- 筹码换手

- 威科夫吸筹

- 假突破

- 机构参与度

都会依赖它。

---

# 四、建议新增 VWAP（日均成交价）

你前面问得非常对。

仅 OHLC 不够。

建议数据层直接生成：

```python
vwap = amount / volume
```

（注意单位统一）

以后：

- VWAP偏离

- 主力成本

- Volume Profile

- Anchored VWAP

- 机构执行分析

都会用到。

这是你未来走向：

```text
机构级研究
```

的重要一步。

---

# 五、建立“原始层”和“研究层”

不要只保留一个表。

建议：

# 原始层（不可修改）

```sql
raw_stock_daily
```

保存：

- Tushare原始字段

- 原始复权

- 原始时间戳

作用：

```text
审计 + 可复现
```

---

# 研究层（标准化）

```sql
market_daily
```

保存：

- 统一字段

- 清洗后数据

- 衍生字段

- vwap

- turnover_rate

- regime_tag（以后）

作用：

```text
策略研究
```

---

# 六、建立数据质量检查（非常重要）

机构系统最核心的不是策略。

而是：

# 数据可信度

建议每日同步后自动检查：

---

## 1. 缺失检查

```text
是否缺交易日
```

---

## 2. 异常成交量

```text
volume=0但价格变化
```

---

## 3. OHLC合法性

```text
low <= open/close <= high
```

---

## 4. VWAP合理性

```text
low <= vwap <= high
```

---

## 5. 换手率异常

```text
turnover > 60%
```

可能：

- 数据错

- 次新

- 异常行情

---

# 七、数据库结构建议（你现在已经接近正确）

你现在：

```sql
PRIMARY KEY(code, date)
```

是正确的。

但建议升级：

---

## 追加：

```sql
turnover_rate REAL
vwap REAL
source TEXT
data_version TEXT
updated_at TEXT
```

---

## 建索引：

```sql
INDEX idx_date(date)
INDEX idx_code_date(code, date)
```

---

# 八、先别急着上分钟级

很多人会犯错：

```text
一上来搞tick/minute
```

但你当前最缺的是：

# 日线研究框架稳定性

建议顺序：

---

## 第一阶段（日线）

先完成：

- 趋势研究

- Regime

- 换手率

- VWAP

- Layer Q可信度

---

## 第二阶段（30m/5m）

研究：

- 假突破

- VWAP回踩

- 量能衰减

---

## 第三阶段（逐笔）

研究：

- 主力行为

- 打板

- 龙虎榜行为

- 微观结构

---

# 九、你现在最应该做的具体任务

建议本周只做4件事：

---

# Task 1

建立：

```text
market_data.db
```

标准化表。

---

# Task 2

写：

```python
tushare_client.py
```

统一所有API调用。

---

# Task 3

写：

```python
sync_daily.py
```

每日自动更新。

---

# Task 4

写：

```python
data_validator.py
```

数据质量检查。

---

# 十、不要忽视“数据版本”

这是绝大多数个人量化系统完全没有的。

建议：

每次同步：

```text
source=tushare_pro
version=2026-05-21
```

否则未来：

```text
为什么今天结果和3个月前不同？
```

你永远查不出来。

---

# 十一、你当前最合理的发展路线

你现在已经不再是：

```text
写几个指标回测
```

而是在进入：

# “研究基础设施建设”

路线已经开始接近：

```text
研究平台 → 信号系统 → 可信度系统 → 执行系统
```

而：

# 数据层

就是整个体系的地基。

如果地基不标准：

以后：

- Layer Q

- Regime

- WalkForward

- Capacity

- Wyckoff

- Volume Profile

都会失真。

---

你现在这一步（Tushare标准化接入），其实是整个系统演化中的一个关键拐点。
