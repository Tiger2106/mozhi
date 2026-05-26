这次“数据源使用规则研讨会”整体质量很高，而且已经不是普通的“工具选型会”了，本质上你们已经在做：

# 数据治理（Data Governance）

这是量化系统从“脚本工程”进入“研究平台”的关键标志。

我从架构成熟度、风险控制、研究价值三个层面评估。

---

# 一、整体评价：方向正确，已具备机构化雏形

这份会议输出里，最重要的不是：

```text
“Tushare 做主源”
```

而是：

# 你们已经开始建立：

```text
数据可信度体系
```

这比“能拉数据”重要得多。

因为未来真正毁掉回测系统的，往往不是策略错误，而是：

- 数据漂移

- 双源不一致

- 字段语义变化

- 复权更新

- 缺失修复

- 静默降级

你们这次已经开始正视这些问题了。

这是非常大的进步。

---

# 二、墨衡方案：整体正确，但还缺一个“数据契约层”

墨衡这条：

```text
L1 Tushare > L2 AKShare > L3 BaoStock
```

是正确的。

尤其：

```text
“一条数据只从一个主源进入”
```

非常关键。

否则未来一定出现：

```text
同一symbol不同来源混杂
```

最终：

```text
回测不可复现
```

这是必须避免的。

---

但我认为墨衡方案还缺：

# Data Contract（数据契约层）

目前：

```text
数据源层 → Adapter → Normalizer → Storage
```

还不够。

建议增加：

```text
Contract Validator
```

即：

```text
Tushare字段 ≠ 系统标准字段
```

必须经过：

# 标准化契约验证

例如：

| Tushare    | 系统     |
| ---------- | ------ |
| ts_code    | symbol |
| trade_date | date   |
| vol        | volume |
| amount     | amount |

否则：

以后：

- JoinQuant

- Wind

- CSV

- Tick

会逐渐污染整个系统。

---

# 三、墨萱：质量控制已经接近“生产级”

墨萱这次提出的：

# 双写期 + 自动对账 + 回滚

这是非常成熟的思路。

尤其：

```text
偏差>1%回滚
```

非常重要。

因为：

# 数据切换最危险的问题：

不是“直接报错”。

而是：

# 悄悄变了。

这是量化系统最致命的问题之一。

---

但我建议：

# 偏差不要只看数值

应增加：

---

## 1. 行数偏差

```text
missing bars
```

---

## 2. 时间偏差

```text
trade_date mismatch
```

---

## 3. 复权偏差

```text
adj_factor drift
```

---

## 4. 统计分布偏差

例如：

```text
turnover_rate mean/std
```

否则：

有些错误：

```text
不会超过1%
但会毁掉策略
```

---

# 四、玄知：战略视角非常准确

玄知提到的：

# auth_scope 隔离

这是很多系统后期才会踩的大坑。

因为未来：

- Tushare Token

- JoinQuant 登录态

- Wind Session

- 本地缓存权限

会逐渐复杂。

如果：

```text
MarketDataClient 共用上下文
```

未来：

- token污染

- session串线

- 降级混乱

一定出现。

---

另外：

# date vs trade_date

这是个非常关键的问题。

我的建议：

# 外部兼容 + 内部统一

即：

---

## 数据层内部统一：

```text
trade_date
```

因为：

这是行业标准。

---

## 对旧系统兼容：

提供：

```python
df["date"] = df["trade_date"]
```

兼容层。

---

# 千万不要：

为了兼容旧代码，

永久保留：

```text
date
```

否则以后：

- intraday

- datetime

- timezone

都会变乱。

---

# 五、你们现在真正缺的是“数据版本体系”

虽然墨萱提到了版本标签。

但我建议：

# 必须升级为正式 Data Version System

建议：

---

## 每次同步生成：

```text
dataset_version
```

例如：

```text
CN_A_DAILY_20260521_v3
```

---

## 并记录：

```text
source
sync_time
adj_mode
missing_count
validator_result
```

---

## 回测结果绑定：

```text
backtest_result.dataset_version
```

否则：

未来：

```text
为什么同一策略结果不同？
```

你会永远查不出来。

---

# 六、我最赞同的一点：7天双写

这是目前最正确的决定。

因为：

# 数据迁移最危险：

不是代码。

而是：

```text
历史一致性
```

你们现在：

- Layer Q

- Regime

- 参数岛

- WalkForward

都高度依赖：

# 时间序列稳定性

所以：

# 双写验证必须做

而且：

我建议：

# 不只是7天实时

还要：

# 历史回测双跑

例如：

---

## 同一策略：

- 老源跑一次

- Tushare跑一次

---

## 比较：

- CAGR

- Sharpe

- Turnover

- Signal Count

- MaxDD

---

## 如果偏差超阈值：

必须定位原因。

否则：

你会出现：

```text
数据切换 → Layer Q评分体系整体漂移
```

---

# 七、关于工期：墨衡17h是低估

实际我认为：

| 阶段           | 实际   |
| ------------ | ---- |
| 数据层改造        | 2-3天 |
| Normalizer稳定 | 2天   |
| Validator    | 1-2天 |
| 双写与对账        | 7天   |
| 历史补齐         | 1-2天 |
| 回测复核         | 2-4天 |

真实周期更接近：

# 2~3周

但这是正常的。

因为：

# 你们不是在“换API”

而是在：

# 重构数据基础设施

---

# 八、我认为现在最重要的新任务

建议新增：

# Data Quality Layer（DQ层）

位置：

```text
DataSource
    ↓
Raw Adapter
    ↓
DQ Layer
    ↓
Normalizer
    ↓
Storage
```

DQ层负责：

- 缺失检测

- 极值检测

- 复权漂移

- 时间连续性

- VWAP合理性

- turnover异常

- source drift

以后：

# Layer Q

很可能会依赖：

```text
DQ Score
```

作为研究可信度输入。

---

# 九、这次会议最重要的成果（真正关键）

不是：

```text
Tushare 成为主源
```

而是：

# 你们开始形成：

```text
研究 → 数据 → 验证 → 回测 → 审计
```

的完整闭环。

这意味着：

你们的系统已经开始从：

```text
策略工程
```

转向：

# 研究操作系统（Research OS）

这是质变。
