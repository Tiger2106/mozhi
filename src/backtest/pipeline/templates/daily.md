<!--
author: 墨涵
created_time: 2026-05-15 10:43
task_id: p5b_batch1_daily_template
-->
# 📋 {{date}} 墨枢日度报告

---

## 一、市场概览

| 指标 | 数值 |
|:----|:----:|
| 上证指数 | {{market.index.sh}} |
| 深证成指 | {{market.index.sz}} |
| 中国石油(601857) | {{market.price}} |
| 沪深300涨跌幅 | {{market.chg_range}} |

---

## 二、策略信号

| 策略 | 当日信号 | 方向 | 信号强度 |
|:----|:--------:|:----:|:--------:|
| 趋势 | {{signals.trend.signal}} | {{signals.trend.direction}} | {{signals.trend.strength}} |
| 反转 | {{signals.reversal.signal}} | {{signals.reversal.direction}} | {{signals.reversal.strength}} |
| 网格 | {{signals.grid.signal}} | {{signals.grid.direction}} | {{signals.grid.strength}} |

> 信号：1=做多，-1=做空，0=空仓。冲突标记：{{conflict_flag}}

---

## 三、持仓情况

| 策略 | 当日持仓 | 持仓市值 | 占用资金 | 浮盈 |
|:----|:--------:|:--------:|:--------:|:----:|
| 趋势 | {{positions.trend.holdings}} | ¥{{positions.trend.market_value}} | ¥{{positions.trend.capital_used}} | {{positions.trend.pnl}} |
| 反转 | {{positions.reversal.holdings}} | ¥{{positions.reversal.market_value}} | ¥{{positions.reversal.capital_used}} | {{positions.reversal.pnl}} |
| 网格 | {{positions.grid.holdings}} | ¥{{positions.grid.market_value}} | ¥{{positions.grid.capital_used}} | {{positions.grid.pnl}} |
| **合计** | **—** | **¥{{positions.total.market_value}}** | **¥{{positions.total.capital_used}}** | **{{positions.total.pnl}}** |

---

## 四、策略净值

| 策略 | 当日净值 | 日收益率 | 累计收益 | 夏普(20日) |
|:----|:--------:|:--------:|:--------:|:----------:|
| 趋势 | {{equity.trend.value}} | {{equity.trend.daily_return}} | {{equity.trend.cumulative}} | {{equity.trend.sharpe_20d}} |
| 反转 | {{equity.reversal.value}} | {{equity.reversal.daily_return}} | {{equity.reversal.cumulative}} | {{equity.reversal.sharpe_20d}} |
| 网格 | {{equity.grid.value}} | {{equity.grid.daily_return}} | {{equity.grid.cumulative}} | {{equity.grid.sharpe_20d}} |
| **组合** | **{{equity.combined.value}}** | **{{equity.combined.daily_return}}** | **{{equity.combined.cumulative}}** | **{{equity.combined.sharpe_20d}}** |

---

## 五、风控指标

| 指标 | 当前 | 阈值 | 状态 |
|:----|:---:|:----:|:----:|
| 组合最大回撤 | {{risk.max_drawdown}} | {{risk.drawdown_limit}} | {{risk.drawdown_status}} |
| 总资金使用率 | {{risk.capital_usage}} | {{risk.capital_limit}} | {{risk.capital_status}} |
| 持仓集中度 | {{risk.concentration}} | {{risk.concentration_limit}} | {{risk.concentration_status}} |
| VaR(95%) | {{risk.var_95}} | — | — |

---

## 六、关键事件

{{events}}

---

## 七、操作建议

{{recommendations}}

---

---

## 八、逐笔交易明细（本日 entry→exit 配对）

{{#if pnl_stats.combined}}
| 策略 | 入场日期 | 出场日期 | 入场价 | 出场价 | 持仓天数 | 数量 | 盈亏(元) | 盈亏比例(%) |
|:----:|:--------:|:--------:|:-----:|:-----:|:--------:|:---:|:--------:|:----------:|
{{#each trade_pairs}}
| {{this.strategy}} | {{this.entry_date}} | {{this.exit_date}} | {{this.entry_price}} | {{this.exit_price}} | {{this.holding_days}} | {{this.quantity}} | {{this.pnl}} | {{this.pnl_pct}}% |
{{/each}}
{{else}}
*今日无完整 entry→exit 交易配对（需同一日内既有买入又有卖出）。*
{{/if}}

---

## 九、盈亏分布统计

{{#if pnl_stats.combined}}
| 指标 | 趋势 | 反转 | 网格 | **组合** |
|:----|:----:|:----:|:----:|:--------:|
| 胜率 | {{pnl_stats.per_strategy.trend.win_rate}} | {{pnl_stats.per_strategy.reversal.win_rate}} | {{pnl_stats.per_strategy.grid.win_rate}} | **{{pnl_stats.combined.win_rate}}** |
| 总交易次数 | {{pnl_stats.per_strategy.trend.total_trades}} | {{pnl_stats.per_strategy.reversal.total_trades}} | {{pnl_stats.per_strategy.grid.total_trades}} | **{{pnl_stats.combined.total_trades}}** |
| 盈利/亏损次数 | {{pnl_stats.per_strategy.trend.winning_trades}}/{{pnl_stats.per_strategy.trend.losing_trades}} | {{pnl_stats.per_strategy.reversal.winning_trades}}/{{pnl_stats.per_strategy.reversal.losing_trades}} | {{pnl_stats.per_strategy.grid.winning_trades}}/{{pnl_stats.per_strategy.grid.losing_trades}} | **{{pnl_stats.combined.winning_trades}}/{{pnl_stats.combined.losing_trades}}** |
| 平均盈利(元) | {{pnl_stats.per_strategy.trend.avg_win}} | {{pnl_stats.per_strategy.reversal.avg_win}} | {{pnl_stats.per_strategy.grid.avg_win}} | **{{pnl_stats.combined.avg_win}}** |
| 平均亏损(元) | {{pnl_stats.per_strategy.trend.avg_loss}} | {{pnl_stats.per_strategy.reversal.avg_loss}} | {{pnl_stats.per_strategy.grid.avg_loss}} | **{{pnl_stats.combined.avg_loss}}** |
| 盈亏比 | {{pnl_stats.per_strategy.trend.profit_loss_ratio}} | {{pnl_stats.per_strategy.reversal.profit_loss_ratio}} | {{pnl_stats.per_strategy.grid.profit_loss_ratio}} | **{{pnl_stats.combined.profit_loss_ratio}}** |
{{else}}
| 指标 | 数值 |
|:----|:----:|
| 总交易次数 | 0 |
{{/if}}

---

## 十、策略参数配置

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
