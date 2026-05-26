<!--
author: 墨涵
created_time: 2026-05-15 10:43
updated_time: 2026-05-15 14:52
updated_by: 墨衡
-->
# 📊 墨枢周度报告 — {{week_range}}

---

## 一、本周市场回顾

| 指标 | 本周 | 上周 | 周环比 |
|:----|:---:|:---:|:------:|
| 上证指数 | {{market.sh.this_week}} | {{market.sh.last_week}} | {{market.sh.change}} |
| 中国石油(601857) | {{market.price.this_week}} | {{market.price.last_week}} | {{market.price.change}} |
| 周成交量(万手) | {{market.volume}} | — | — |

---

## 二、周度策略表现

| 策略 | 周收益 | 月累计 | 周胜率 | 本周夏普 | 上周夏普 | 夏普变化 |
|:----|:------:|:------:|:-----:|:--------:|:--------:|:--------:|
| 趋势 | {{weekly.trend.return}} | {{weekly.trend.mtd}} | {{weekly.trend.win_rate}} | {{weekly.trend.sharpe}} | {{weekly.trend.last_sharpe}} | {{weekly.trend.sharpe_change}} |
| 反转 | {{weekly.reversal.return}} | {{weekly.reversal.mtd}} | {{weekly.reversal.win_rate}} | {{weekly.reversal.sharpe}} | {{weekly.reversal.last_sharpe}} | {{weekly.reversal.sharpe_change}} |
| 网格 | {{weekly.grid.return}} | {{weekly.grid.mtd}} | {{weekly.grid.win_rate}} | {{weekly.grid.sharpe}} | {{weekly.grid.last_sharpe}} | {{weekly.grid.sharpe_change}} |
| **组合** | **{{weekly.combined.return}}** | **{{weekly.combined.mtd}}** | **{{weekly.combined.win_rate}}** | **—** | **—** | **—** |

---

## 三、本周交易记录

| 日期 | 策略 | 操作 | 价格 | 数量 | 成交额 | 盈亏 |
|:---|:----|:----:|:---:|:---:|:-----:|:----:|
{{#each weekly.trades}}
| {{this.date}} | {{this.strategy}} | {{this.action}} | {{this.price}} | {{this.qty}} | ¥{{this.amount}} | {{this.pnl}} |
{{/each}}

---

## 四、逐笔交易复盘（entry→exit 盈亏明细）

{{#if has_trade_pairs}}
| 策略 | 入场日期 | 出场日期 | 入场价 | 出场价 | 持仓天数 | 数量 | 盈亏(元) | 盈亏比例(%) |
|:----:|:--------:|:--------:|:-----:|:-----:|:--------:|:---:|:--------:|:----------:|
{{#each trade_pairs}}
| {{this.strategy}} | {{this.entry_date}} | {{this.exit_date}} | {{this.entry_price}} | {{this.exit_price}} | {{this.holding_days}} | {{this.quantity}} | {{this.pnl}} | {{this.pnl_pct}}% |
{{/each}}
{{else}}
*本周无完整 entry→exit 交易配对。*
{{/if}}

---

## 五、盈亏分布分析

{{#if has_trade_pairs}}
### 组合总览

| 指标 | 数值 |
|:----|:----:|
| 总交易次数 | {{pnl_stats.combined.total_trades}} |
| 盈利/亏损次数 | {{pnl_stats.combined.winning_trades}} / {{pnl_stats.combined.losing_trades}} |
| 胜率 | {{pnl_stats.combined.win_rate}} |
| 总盈亏 | ¥{{pnl_stats.combined.total_pnl}} |
| 平均盈亏/笔 | ¥{{pnl_stats.combined.avg_pnl}} |
| 平均盈利 | ¥{{pnl_stats.combined.avg_win}} ({{pnl_stats.combined.avg_win_pct}}) |
| 平均亏损 | ¥{{pnl_stats.combined.avg_loss}} ({{pnl_stats.combined.avg_loss_pct}}) |
| 盈亏比 | {{pnl_stats.combined.profit_loss_ratio}} |
| 最大盈利 | ¥{{pnl_stats.combined.max_win}} |
| 最大亏损 | ¥{{pnl_stats.combined.max_loss}} |

### 各策略对比

| 指标 | 趋势 | 反转 | 网格 |
|:----|:----:|:----:|:----:|
| 交易次数 | {{pnl_stats.per_strategy.trend.total_trades}} | {{pnl_stats.per_strategy.reversal.total_trades}} | {{pnl_stats.per_strategy.grid.total_trades}} |
| 胜率 | {{pnl_stats.per_strategy.trend.win_rate}} | {{pnl_stats.per_strategy.reversal.win_rate}} | {{pnl_stats.per_strategy.grid.win_rate}} |
| 盈利/亏损 | {{pnl_stats.per_strategy.trend.winning_trades}}/{{pnl_stats.per_strategy.trend.losing_trades}} | {{pnl_stats.per_strategy.reversal.winning_trades}}/{{pnl_stats.per_strategy.reversal.losing_trades}} | {{pnl_stats.per_strategy.grid.winning_trades}}/{{pnl_stats.per_strategy.grid.losing_trades}} |
| 平均盈利 | ¥{{pnl_stats.per_strategy.trend.avg_win}} | ¥{{pnl_stats.per_strategy.reversal.avg_win}} | ¥{{pnl_stats.per_strategy.grid.avg_win}} |
| 平均亏损 | ¥{{pnl_stats.per_strategy.trend.avg_loss}} | ¥{{pnl_stats.per_strategy.reversal.avg_loss}} | ¥{{pnl_stats.per_strategy.grid.avg_loss}} |
| 盈亏比 | {{pnl_stats.per_strategy.trend.profit_loss_ratio}} | {{pnl_stats.per_strategy.reversal.profit_loss_ratio}} | {{pnl_stats.per_strategy.grid.profit_loss_ratio}} |
{{else}}
*本周无可用交易回测数据。*
{{/if}}

---

## 六、持仓周变化

| 策略 | 持仓(上周末) | 持仓(本周末) | 变化 |
|:----|:-----------:|:-----------:|:----:|
| 趋势 | {{holdings.trend.last_week}} | {{holdings.trend.this_week}} | {{holdings.trend.change}} |
| 反转 | {{holdings.reversal.last_week}} | {{holdings.reversal.this_week}} | {{holdings.reversal.change}} |
| 网格 | {{holdings.grid.last_week}} | {{holdings.grid.this_week}} | {{holdings.grid.change}} |

---

## 七、月度累计收益

| 策略 | 本月收益 | 本月最大回撤 | 本月交易次数 | 年度累计 |
|:----|:--------:|:-----------:|:-----------:|:--------:|
| 趋势 | {{mtd.trend.return}} | {{mtd.trend.max_dd}} | {{mtd.trend.trades}} | {{ytd.trend.return}} |
| 反转 | {{mtd.reversal.return}} | {{mtd.reversal.max_dd}} | {{mtd.reversal.trades}} | {{ytd.reversal.return}} |
| 网格 | {{mtd.grid.return}} | {{mtd.grid.max_dd}} | {{mtd.grid.trades}} | {{ytd.grid.return}} |
| **组合** | **{{mtd.combined.return}}** | **{{mtd.combined.max_dd}}** | **—** | **{{ytd.combined.return}}** |

---

## 八、资金分配状态

| 策略 | 当前权重 | 目标权重 | 偏差 | 操作建议 |
|:----|:--------:|:--------:|:----:|:---------|
| 趋势 | {{allocation.trend.current}} | {{allocation.trend.target}} | {{allocation.trend.deviation}} | {{allocation.trend.action}} |
| 反转 | {{allocation.reversal.current}} | {{allocation.reversal.target}} | {{allocation.reversal.deviation}} | {{allocation.reversal.action}} |
| 网格 | {{allocation.grid.current}} | {{allocation.grid.target}} | {{allocation.grid.deviation}} | {{allocation.grid.action}} |

---

## 九、风控评估

| 维度 | 状态 | 说明 |
|:----|:----:|:-----|
| 回撤风险 | {{risk.drawdown_status}} | 组合最大回撤 {{risk.drawdown_value}}，距阈值 {{risk.drawdown_margin}} |
| 连亏预警 | {{risk.loss_streak_status}} | 趋势{{risk.trend_loss_streak}}天/反转{{risk.reversal_loss_streak}}天/网格{{risk.grid_loss_streak}}天 |
| 夏普趋势 | {{risk.sharpe_trend_status}} | {{risk.sharpe_trend_detail}} |
| 资金利用率 | {{risk.capital_usage_status}} | {{risk.capital_usage_detail}} |

---

## 十、下周展望

{{outlook}}

---

## 十一、决策记录

{{decisions}}

---

## 十二、策略参数配置

| 参数 | 参数 | 值 |
|:----|:----|:---:|
| **趋势策略** | MA快线周期 | {{strategy_params.trend.ma_fast}} |
| | MA慢线周期 | {{strategy_params.trend.ma_slow}} |
| | 信号类型 | {{strategy_params.trend.signal_type}} |
| | 止损比例 | {{strategy_params.trend.stop_loss}} |
| | 止盈比例 | {{strategy_params.trend.take_profit}} |
| **反转策略** | RSI窗口 | {{strategy_params.reversal.rsi_window}} |
| | RSI超卖/超买 | {{strategy_params.reversal.rsi_oversold}} / {{strategy_params.reversal.rsi_overbought}} |
| | KDJ周期(n/m1/m2) | {{strategy_params.reversal.kdj_n}}/{{strategy_params.reversal.kdj_m1}}/{{strategy_params.reversal.kdj_m2}} |
| | 布林带窗口/标准差 | {{strategy_params.reversal.bollinger_window}} / {{strategy_params.reversal.bollinger_std}} |
| | 乖离率买入/卖出阈值 | {{strategy_params.reversal.bias_buy}}% / {{strategy_params.reversal.bias_sell}}% |
| | 多规则最小投票数 | {{strategy_params.reversal.min_votes}} |
| | 冷却期(天) | {{strategy_params.reversal.cooler_days}} |
| **网格策略** | 网格层数 | {{strategy_params.grid.n_levels}} |
| | 网格类型 | {{strategy_params.grid.grid_type}} |
| | 重建冷却(Bar数) | {{strategy_params.grid.cool_down_bars}} |
| | 每层默认数量 | {{strategy_params.grid.default_quantity}} |
| | 网格下界/上界 | {{strategy_params.grid.lower_bound}} / {{strategy_params.grid.upper_bound}} |
| **多策略调度** | 资金分配模式 | {{strategy_params.multi_runner.allocation_mode}} |
| | 冲突优先级 | {{strategy_params.multi_runner.conflict_priority}} |
| | 初始资金 | {{strategy_params.multi_runner.initial_capital}} |
| | 费率/滑点 | {{strategy_params.multi_runner.fee_rate}} / {{strategy_params.multi_runner.slippage_rate}} |

---

*Report generated at {{generated_time}} by 墨枢自动化体系*
