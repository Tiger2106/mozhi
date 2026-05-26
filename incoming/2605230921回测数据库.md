好，基于SQLite + 单因子/策略组合两级结构，给你设计一套完整的schema。数据库结构适合用ERD来展示，用mermaid渲染。11张表，设计思路说明如下。

---

### 核心设计决策

**`BACKTEST_RUN` 作为根节点**，所有表通过 `run_id` 关联。每次回测（包括参数扫描的每个参数组合）生成独立的 `run_id`，这样跨标的横向比较和因子版本迭代追踪都可以直接通过 `run_id` 过滤，不需要复杂的联表。

**单因子和策略组合的分离**通过 `FACTOR_CONFIG`（多行，每因子一行）和 `STRATEGY_CONFIG`（单行，整体策略参数）实现。单因子回测时 `STRATEGY_CONFIG` 可为空或最简配置；策略组合回测时 `FACTOR_CONFIG` 里的 `weight` 字段记录各因子权重。

**几个关键字段的设计意图：**

`FACTOR_CONFIG` 里保留了 `adj_method` 和 `adj_base_date`——这是之前讨论过的数据层对齐问题，直接入库，每次回测的复权口径可追溯。

`TRADE_LOG` 里的 `avg_trade_price` 对应你们正在建设的 `amount/volume` 因子，和信号日期、成交日期分开记录，支持滑点/成交价偏差分析。

`SIGNAL_LOG` 里的 `factor_contributions` 是 JSON 字段，记录每个信号由哪些因子贡献了多少权重，方便事后归因。

`VALIDATION_CHECK` 专门存自洽性检验结果（P2跑两次对比、复权因子校验等），`check_type` 区分自洽性/数据质量/逻辑验证，`threshold_value` 对应你们定的定量标准（价格误差<0.1%、IC相关系数>0.999等）。

---

### SQLite 建议索引

```sql
CREATE INDEX idx_factor_result_run ON FACTOR_RESULT(run_id, factor_name);
CREATE INDEX idx_trade_log_run_code ON TRADE_LOG(run_id, ts_code);
CREATE INDEX idx_daily_position_date ON DAILY_POSITION(run_id, trade_date);
CREATE INDEX idx_signal_log_date ON SIGNAL_LOG(run_id, signal_date);
```

需要建表的DDL脚本我可以直接生成，或者有字段需要调整的告诉我。

DDL已生成，几个设计说明：

**初始化方式**

```bash
sqlite3 mosu_backtest.db < backtest_schema.sql
```

**几处和设计图的差异说明**

`performance_summary` 补充了 `benchmark_return`、`excess_return`、`max_drawdown_start/end`、`sortino_ratio`、`turnover_rate`——回测分析高频需要，不加后来会返工。

`trade_log` 里把 `commission` 和 `slippage` 分开存——方便事后单独分析交易成本，也和你们的滑点/成交价偏差验证对齐。

`validation_check` 的 `check_name` 建议统一命名规范，例如 `p2_self_consistency_price`、`p2_self_consistency_ic`、`data_adj_factor_601857`，方便用前缀批量查询。

**4个视图**直接可用：有效因子概览（IR>0.05）、跨run绩效对比、验证失败清单、交易成本分析。需要加其他视图告诉我。
