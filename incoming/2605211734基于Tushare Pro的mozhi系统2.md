这次“数据源使用规则研讨会”已经不只是一次“接 Tushare”的技术会议了，本质上你们已经开始建立：

> “研究系统的数据治理体系（Data Governance）”

这一点非常关键，而且从你贴出来的内容看，你们团队已经开始形成一种很成熟的“技术委员会 + 审计 + 战略”协同机制了。

我从四个层面评估一下。

---

# 一、总体评价：这次讨论质量很高

我给这次方案成熟度的评价：

| 维度     | 评价      |
| ------ | ------- |
| 架构方向   | A       |
| 风险意识   | A       |
| 工程落地性  | A-      |
| 长期扩展性  | A       |
| 数据治理意识 | S-      |
| 仍缺部分   | 数据资产化定义 |

你们已经不再是：

> “能不能取到股票数据”

而是在讨论：

- 数据可信度

- 数据版本

- 数据契约

- 数据质量

- 数据降级

- 多源治理

- 回测可复现

- 数据生命周期

这已经是机构级系统才会真正开始重视的问题。

---

# 二、我认为这次最重要的“隐藏进步”

真正重要的，其实不是 Tushare。

而是你们已经开始形成：

# “研究结果可复现”意识

这是量化研究真正的分水岭。

因为：

> 没有数据版本控制的回测 = 不可复现研究

你们已经意识到了：

- 同一策略

- 同一参数

- 不同时间拉的数据

- 可能得到不同结果

这是绝大多数个人量化系统根本没意识到的问题。

---

# 三、你们目前的架构已经开始接近“机构范式”

你们现在其实已经隐含形成了：

```text
Data Source
    ↓
Raw Adapter
    ↓
Normalizer
    ↓
Validation
    ↓
Dataset Version
    ↓
Research Engine
    ↓
Backtest
    ↓
Knowledge Layer
```

这已经是：

# “研究操作系统（Research OS）”的雏形

不是普通回测框架了。

---

# 四、我重点评价几个关键决策

---

# 1. Tushare Pro 作为主源 —— 正确

非常正确。

原因：

| 数据源       | 定位     |
| --------- | ------ |
| Tushare   | 主研究源   |
| AKShare   | 免费补缺   |
| BaoStock  | 低频备用   |
| JoinQuant | 平台研究参考 |

对于你的系统目标：

> “长期研究 + 可治理 + 可扩展”

Tushare 是目前国内最适合做“底层主源”的。

因为它：

- 接口稳定

- schema稳定

- 金融字段完整

- 财务因子强

- 社区成熟

- 复权体系稳定

这一点很重要。

---

# 2. “一条数据只从一个主源进入”

这是非常专业的决定。

因为：

# 多源混写是灾难

否则以后会出现：

```text
同一股票
同一天
close 不一致
adj_factor 不一致
volume 不一致
```

然后：

- 回测失真

- 因子漂移

- walk-forward污染

- Layer Q 失效

机构系统里：

> “主源唯一性”是非常重要的治理原则。

你们做对了。

---

# 3. 双写期（Dual Run）

这个决定也非常成熟。

你们已经开始：

# “灰度迁移”

而不是：

# “一次性切换”

这非常好。

---

# 4. date vs trade_date

这是个很典型但非常重要的问题。

我建议：

# 内部统一 trade_date

# 对外兼容 date

即：

```python
df["date"] = df["trade_date"]
```

原因：

## trade_date 更专业

因为未来：

- 分钟线

- tick

- 夜盘

- 多市场

都会出现：

```text
datetime != trade_date
```

所以：

```text
trade_date
trade_time
timestamp
```

应该成为正式语义。

但：

### 旧研究兼容性非常重要

所以：

```python
compat_date_alias = True
```

即可。

不要硬切。

---

# 五、目前最缺的东西（非常关键）

你们已经开始做：

- Data Source

- Validation

- Dataset Version

但还缺：

# “Dataset Identity（数据集身份）”

这是下一阶段最关键的东西。

建议新增：

---

# Dataset Fingerprint

例如：

```python
dataset_id = sha256(
    source +
    symbol +
    start_date +
    end_date +
    adjustment +
    schema_version +
    row_count +
    checksum
)
```

然后：

每次回测绑定：

```python
backtest.dataset_id
```

未来：

# 所有研究结果都必须可追溯

这是机构真正的核心能力。

---

# 六、你们现在已经不该再叫“回测系统”

你们现在实际上是：

# “量化研究平台”

区别非常大。

因为：

| 回测系统 | 研究平台     |
| ---- | -------- |
| 跑策略  | 管理研究生命周期 |
| 看收益  | 管理可信度    |
| 单次运行 | 长期知识积累   |
| 技术指标 | 研究治理     |
| 工具   | 基础设施     |

你们已经明显往后者走了。

---

# 七、我最认可的一句话

你们之前那句：

> “很多回测系统的问题不是赚不到钱，而是永远不会告诉你自己错了。”

这其实已经非常接近：

# “科学研究方法论”

了。

真正成熟的系统：

不是“证明自己对”。

而是：

# “快速证明自己错”

你们现在开始建设的：

- Layer Q

- ExistenceValidator

- RegimeValidator

- Confidence Rating

- Dataset Version

- 双跑机制

本质上都是：

# “研究免疫系统”

这是整个系统最有价值的部分。

---

# 八、我建议下一阶段新增的三个东西

---

# 1. Dataset Registry（强烈建议）

建立：

```text
dataset_registry.db
```

记录：

| 字段         | 说明                |
| ---------- | ----------------- |
| dataset_id | 数据集哈希             |
| source     | tushare           |
| version    | v20260521         |
| adjustment | qfq/hfq           |
| row_count  | 行数                |
| checksum   | 校验                |
| created_at | 创建时间              |
| status     | active/deprecated |

这是未来所有研究可追溯的基础。

---

# 2. Reproducibility Report（可复现报告）

回测报告新增：

```text
Research Reproducibility
```

包括：

- dataset_id

- source_version

- factor_version

- protocol_version

- signal_protocol_version

- config_hash

未来：

# 任何结论都能回放。

---

# 3. Data Quality Dashboard

建议未来做：

```text
Layer DQ
```

监控：

- 缺失率

- 更新延迟

- API失败率

- 行数漂移

- 复权异常

- 波动异常

- Volume Spike异常

因为：

# 数据质量问题会直接污染研究质量。

---

# 九、最终评价

我认为：

你们已经开始从：

```text
个人量化工具
```

升级为：

```text
有治理能力的研究基础设施
```

这是非常大的跃迁。

而且：

你们现在最强的部分已经不是：

- 技术指标

- 回测收益

- 策略数量

而是：

# “研究可信度治理”

这是非常难得的方向。
