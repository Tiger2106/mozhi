# 回测系统数据库表结构文档

> 生成时间: 2026-05-18
> 覆盖范围: 10 个主库（含空库）、2 个实验库（仅注明表名）
> 备注: `sqlite_sequence` 为 SQLite 内部自增序列表，已排除

---

## 行情 & 因子

### market_data.db

路径: `C:\Users\17699\mozhi_platform\data\market\market_data.db`
大小: 464 KB | 用途: 存储 A50 主要标的日线行情数据（OHLCV + 换手率）

#### market_daily → [9 行]

说明: 日线行情主表。数据采集进程写入，策略引擎和信号生成模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| symbol | TEXT | YES | NULL | PK |
| trade_date | TEXT | YES | NULL | PK |
| open | REAL | | NULL | |
| high | REAL | | NULL | |
| low | REAL | | NULL | |
| close | REAL | | NULL | |
| volume | REAL | | NULL | |
| amount | REAL | | NULL | |
| turnover_rate | REAL | | NULL | |

---

### factor_repository.db

路径: `C:\Users\17699\mo_zhi_sharereports\factor_repository.db`
大小: 7,796 KB | 用途: 因子仓库，存储计算好的多品种日频技术因子

#### daily_factors → [25 行]

说明: 股票日频因子表，含动量、趋势、波动率、超买超卖、成交量等因子字段。因子计算引擎写入，策略信号模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| code | TEXT | YES | NULL | |
| date | TEXT | YES | NULL | |
| momentum_rsi | REAL | | NULL | |
| momentum_macd_dir | INTEGER | | NULL | |
| momentum_macd_hist_rate | REAL | | NULL | |
| momentum_price_velocity | REAL | | NULL | |
| trend_score | REAL | | NULL | |
| trend_ma_alignment | REAL | | NULL | |
| trend_ma_width | REAL | | NULL | |
| trend_ma_breadth | REAL | | NULL | |
| volatility_bb_width | REAL | | NULL | |
| volatility_bb_squeeze | INTEGER | | NULL | |
| volatility_rsi_std | REAL | | NULL | |
| volatility_price_std | REAL | | NULL | |
| obo_rsi_level | INTEGER | | NULL | |
| obo_kdj_level | INTEGER | | NULL | |
| obo_rsi_extreme | INTEGER | | NULL | |
| obo_kdj_extreme | INTEGER | | NULL | |
| volume_ratio | REAL | | NULL | |
| volume_ma5_cross | INTEGER | | NULL | |
| gap_day | INTEGER | | NULL | |
| gap_day_up | INTEGER | | NULL | |
| gap_day_down | INTEGER | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |

#### oil_daily_factors → [20 行]

说明: 原油日频因子表，与 daily_factors 结构相似，另含期限结构（contango/backwardation）和季节性字段。因子计算引擎写入，原油策略模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| code | TEXT | YES | NULL | |
| date | TEXT | YES | NULL | |
| momentum_return | REAL | | NULL | |
| momentum_rsi | REAL | | NULL | |
| momentum_macd_dir | INTEGER | | NULL | |
| momentum_macd_hist_rate | REAL | | NULL | |
| trend_ma_alignment | REAL | | NULL | |
| trend_ma_width | REAL | | NULL | |
| trend_ma_breadth | REAL | | NULL | |
| volatility_bb_width | REAL | | NULL | |
| volatility_bb_squeeze | INTEGER | | NULL | |
| volatility_std | REAL | | NULL | |
| structure_contango | INTEGER | | NULL | |
| structure_backwardation | INTEGER | | NULL | |
| structure_roll_return | REAL | | NULL | |
| seasonal_month | INTEGER | | NULL | |
| seasonal_quarter | INTEGER | | NULL | |
| seasonal_holiday_effect | INTEGER | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |

---

### knowledge.db

路径: `C:\Users\17699\mozhi_platform\data\knowledge.db`
大小: 3,556 KB | 用途: 策略知识库，存储回测运行的详细信息、分析结果和积累的交易洞见

#### backtest_equity_series → [7 行]

说明: 回测权益曲线，记录每个回测运行的每日净值/权益/回撤序列。知识引擎写入，分析面板和可视化模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| run_id | TEXT | YES | NULL | |
| date_idx | INTEGER | YES | 0 | |
| date | TEXT | YES | '' | |
| equity | REAL | YES | 0.0 | |
| nav | REAL | YES | 0.0 | |
| drawdown | REAL | YES | 0.0 | |

#### backtest_runs → [14 行]

说明: 回测运行主记录，包含策略名、标的、配置键、参数版本、触发人等元信息。回测调度器写入，知识分析模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| run_id | TEXT | | NULL | PK |
| strategy | TEXT | YES | NULL | |
| symbol | TEXT | YES | NULL | |
| config_key | TEXT | YES | '' | |
| strategy_tag | TEXT | YES | '' | |
| start_date | TEXT | YES | '' | |
| end_date | TEXT | YES | '' | |
| data_days | INTEGER | YES | 0 | |
| param_version | TEXT | YES | '' | |
| run_by | TEXT | YES | 'auto' | |
| triggered_by | TEXT | YES | '' | |
| report_path | TEXT | YES | '' | |
| created_at | TEXT | YES | datetime('now', 'localtime') | |
| updated_at | TEXT | YES | datetime('now', 'localtime') | |

#### backtest_trades → [11 行]

说明: 回测逐笔交易记录，包含进出场日期、方向、价格、数量、盈亏。回测引擎写入，绩效分析模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| run_id | TEXT | YES | NULL | |
| trade_idx | INTEGER | YES | 0 | |
| entry_date | TEXT | YES | '' | |
| exit_date | TEXT | YES | '' | |
| direction | TEXT | YES | '' | |
| entry_price | REAL | YES | 0.0 | |
| exit_price | REAL | YES | 0.0 | |
| quantity | REAL | YES | 0.0 | |
| pnl | REAL | YES | 0.0 | |
| pnl_pct | REAL | YES | 0.0 | |

#### knowledge_entries → [17 行]

说明: 结构化策略洞见。由知识引擎在回测完成后自动提取关键结论（如"趋势跟踪策略在高波动阶段有效"），供策略决策模块查询。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| symbol | TEXT | YES | NULL | |
| strategy | TEXT | YES | NULL | |
| param_version | TEXT | YES | '' | |
| market_regime | TEXT | YES | 'any' | |
| insight_category | TEXT | YES | NULL | |
| confidence | TEXT | YES | 'medium' | |
| sample_size | INTEGER | YES | 0 | |
| avg_return_pct | REAL | YES | 0.0 | |
| avg_sharpe | REAL | YES | 0.0 | |
| avg_max_dd_pct | REAL | YES | 0.0 | |
| insight_summary | TEXT | YES | '' | |
| source_run_ids | TEXT | YES | '[]' | |
| status | TEXT | YES | 'active' | |
| activated_at | TEXT | YES | datetime('now', 'localtime') | |
| last_updated_at | TEXT | YES | datetime('now', 'localtime') | |
| deprecated_at | TEXT | | NULL | |

#### knowledge_run_links → [2 行]

说明: 知识条目与回测运行的多对多关联表，联合主键。知识引擎在生成洞见时自动建立链接。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| knowledge_id | INTEGER | YES | NULL | PK |
| run_id | TEXT | YES | NULL | PK |

#### market_context → [11 行]

说明: 回测运行期间的市场环境快照，含市场体制、波动水平、趋势强度、板块百分位等。知识引擎写入，回放和策略评估模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| run_id | TEXT | YES | NULL | |
| date_key | TEXT | YES | NULL | |
| symbol | TEXT | YES | '' | |
| market_regime | TEXT | YES | 'unknown' | |
| volatility_level | TEXT | YES | 'medium' | |
| trend_strength | REAL | YES | 0.0 | |
| sector_percentile | REAL | | NULL | |
| macro_events | TEXT | | '[]' | |
| notes | TEXT | | '' | |
| created_at | TEXT | YES | datetime('now', 'localtime') | |

#### params_snapshot → [6 行]

说明: 参数版本快照，记录每次回测的完整参数 JSON 及变更 diff。知识引擎每次回测后写入，用于参数版本回溯。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| run_id | TEXT | YES | NULL | |
| param_version | TEXT | YES | 'v0_initial' | |
| params_json | TEXT | YES | NULL | |
| diff_from_prev | TEXT | YES | '{}' | |
| snapshot_time | TEXT | YES | datetime('now', 'localtime') | |

#### performance_results → [12 行]

说明: 回测绩效汇总，含总收益率、年化收益、夏普、最大回撤、胜率、盈亏比等核心指标。回测引擎写入，绩效评估和报告模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| run_id | TEXT | YES | NULL | |
| total_return_pct | REAL | YES | 0.0 | |
| annual_return_pct | REAL | YES | 0.0 | |
| sharpe_ratio | REAL | YES | 0.0 | |
| max_drawdown_pct | REAL | YES | 0.0 | |
| win_rate_pct | REAL | YES | 0.0 | |
| profit_factor | REAL | YES | 0.0 | |
| total_trades | INTEGER | YES | 0 | |
| avg_holding_bars | REAL | YES | 0.0 | |
| validity_grade | TEXT | YES | 'C' | |
| extra_metrics | TEXT | YES | '{}' | |
| created_at | TEXT | YES | datetime('now', 'localtime') | |

---

## 交易引擎

### trade_engine.db

路径: `C:\Users\17699\mo_zhi_sharereports\trade_engine.db`
大小: 92 KB | 用途: 实盘（模拟）交易引擎主库，管理账户、持仓、交易流水、网格策略和信号冲突
> 备注: 以下副本与主库 schema 一致，仅用途不同：`trade_engine_readonly.db`（只读备份）、`trade_engine_test_settlement.db`（结算测试）、`trade_engine_backup_*.db`（定期备份）

#### account_balance → [11 行]

说明: 账户资金总览，含总资产、可用余额、冻结金额、持仓市值、已实现盈亏等。交易引擎自动更新，风控和界面模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| total_assets | REAL | YES | 0.0 | |
| available_balance | REAL | YES | 0.0 | |
| frozen_amount | REAL | YES | 0.0 | |
| position_market_value | REAL | YES | 0.0 | |
| initial_capital | REAL | YES | 0.0 | |
| realized_pnl | REAL | YES | 0.0 | |
| updated_at | TEXT | | datetime('now', 'localtime') | |
| loss_streak | INTEGER | YES | 0 | |
| account_id | TEXT | | "1" | |
| last_settlement_time | TEXT | | NULL | |

#### daily_pnl → [18 行]

说明: 每日盈亏明细，含已实现/未实现盈亏、累计盈亏、最大回撤、交易次数、手续费/税费等。交易引擎每结算日写入，绩效分析模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| date | DATE | YES | NULL | |
| realized_pnl | REAL | YES | 0 | |
| unrealized_pnl | REAL | YES | 0 | |
| total_pnl | REAL | YES | 0 | |
| cumulative_pnl | REAL | YES | 0 | |
| max_drawdown | REAL | YES | 0 | |
| trade_count | INTEGER | YES | 0 | |
| win_count | INTEGER | YES | 0 | |
| loss_count | INTEGER | YES | 0 | |
| created_at | DATETIME | | CURRENT_TIMESTAMP | |
| updated_at | DATETIME | | CURRENT_TIMESTAMP | |
| closed_pnl | REAL | | 0.0 | |
| open_pnl | REAL | | 0.0 | |
| realized_gross_pnl | REAL | | 0.0 | |
| realized_net_pnl | REAL | | 0.0 | |
| total_commission | REAL | | 0.0 | |
| total_tax | REAL | | 0.0 | |

#### fund_flow → [10 行]

说明: 资金流水明细，记录每笔资金变动的原因、前后余额和关联订单 ID。交易引擎执行模块写入，审计和对账模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| flow_type | TEXT | YES | NULL | |
| amount | REAL | YES | NULL | |
| balance_before | REAL | YES | NULL | |
| balance_after | REAL | YES | NULL | |
| order_id | TEXT | | NULL | |
| position_id | INTEGER | | NULL | |
| description | TEXT | | NULL | |
| account_id | TEXT | YES | '1' | |
| created_at | TEXT | | datetime('now', 'localtime') | |

#### grid_config → [9 行]

说明: 网格交易策略参数设置，含网格中轴、波动率、上下界、总资金、启停状态等。网格策略模块写入和维护。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| mid | REAL | YES | NULL | |
| sigma | REAL | YES | NULL | |
| upper | REAL | YES | NULL | |
| lower | REAL | YES | NULL | |
| total_capital | REAL | YES | NULL | |
| active | BOOLEAN | | 1 | |
| calc_date | DATE | YES | NULL | |
| created_at | TIMESTAMP | | CURRENT_TIMESTAMP | |

#### grid_state → [13 行]

说明: 网格各层状态，追踪每个网层的触发状态、买卖订单号、盈亏、打断计数等。网格策略模块实时更新。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| grid_index | INTEGER | YES | NULL | |
| status | TEXT | YES | 'empty' | |
| buy_price | REAL | YES | NULL | |
| sell_price | REAL | YES | NULL | |
| quantity | REAL | YES | NULL | |
| buy_order_id | TEXT | | NULL | |
| sell_order_id | TEXT | | NULL | |
| placed_at | TIMESTAMP | | NULL | |
| filled_at | TIMESTAMP | | NULL | |
| pnl | REAL | | 0.0 | |
| break_count | INTEGER | | 0 | |
| updated_at | TIMESTAMP | | CURRENT_TIMESTAMP | |

#### positions → [25 行]

说明: 持仓明细，含标的、方向、数量、开平仓价、已实现/未实现盈亏、保证金、结算组等完整持仓信息。交易引擎执行模块写入，风控和界面模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| symbol | TEXT | | NULL | |
| direction | TEXT | | 'LONG' | |
| quantity | INTEGER | | NULL | |
| entry_price | REAL | | NULL | |
| entry_time | TEXT | | NULL | |
| status | TEXT | | 'OPEN' | |
| close_price | REAL | | NULL | |
| close_time | TEXT | | NULL | |
| pnl | REAL | | NULL | |
| stop_loss_price | REAL | | NULL | |
| account_id | TEXT | | "1" | |
| avg_price | REAL | | NULL | |
| total_cost | REAL | | NULL | |
| current_price | REAL | | NULL | |
| market_value | REAL | | NULL | |
| unrealized_pnl | REAL | | NULL | |
| realized_pnl | REAL | | 0.0 | |
| cost_basis | REAL | | NULL | |
| total_fees | REAL | | NULL | |
| daily_pnl | REAL | | NULL | |
| total_pnl | REAL | | NULL | |
| margin_required | REAL | | NULL | |
| settlement_group | TEXT | | NULL | |
| updated_at | TEXT | | NULL | |
| notes | TEXT | | NULL | |

#### signal_conflicts → [10 行]

说明: 信号冲突记录，当趋势/反转/网格三类信号产生矛盾时，记录各子信号动作、冲突类型和最终裁决结果。信号仲裁模块写入。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| code | TEXT | YES | NULL | |
| date | TEXT | YES | NULL | |
| trend_action | TEXT | YES | NULL | |
| reversal_action | TEXT | YES | NULL | |
| grid_action | TEXT | | NULL | |
| conflict_type | TEXT | YES | NULL | |
| resolved_action | TEXT | | NULL | |
| resolved_at | DATETIME | | NULL | |
| created_at | DATETIME | | CURRENT_TIMESTAMP | |

#### system_state → [3 行]

说明: 系统状态 KV 存储，用于持久化各种运行时状态标记（如"是否已初始化"、"当前交易日"等）。交易引擎各模块读写。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| key | TEXT | | NULL | PK |
| value | TEXT | YES | NULL | |
| updated_at | DATETIME | | CURRENT_TIMESTAMP | |

#### tech_signals → [23 行]

说明: 技术信号明细，含信号任务 ID、标的、日期、动作、置信度、建议价格/仓位、趋势评分、因子复合得分、前向收益、市场体制等完整字段。信号生成模块写入，交易执行模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| task_id | TEXT | YES | NULL | |
| code | TEXT | YES | NULL | |
| date | TEXT | YES | NULL | |
| action | TEXT | YES | NULL | |
| confidence | TEXT | | '中' | |
| suggested_price | REAL | | NULL | |
| position_ratio | REAL | | NULL | |
| quantity | INTEGER | | NULL | |
| reason | TEXT | | NULL | |
| status | TEXT | | 'READY' | |
| account_id | TEXT | | 'acct_tech_trend' | |
| order_id | TEXT | | NULL | |
| trend_score | REAL | | NULL | |
| factor_composite | REAL | | NULL | |
| current_position_pct | REAL | | NULL | |
| signal_hit | INTEGER | | 0 | |
| forward_return_5d | REAL | | NULL | |
| forward_return_10d | REAL | | NULL | |
| forward_return_20d | REAL | | NULL | |
| market_regime | TEXT | | NULL | |
| created_at | TEXT | YES | datetime('now', 'localtime') | |
| updated_at | TEXT | YES | datetime('now', 'localtime') | |

#### transactions → [14 行]

说明: 交易执行流水，含订单 ID、标的、买卖、数量、价格、手续费、税费、状态、关联信号 ID 和持仓 ID。交易引擎执行模块写入，审计模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| order_id | TEXT | | NULL | |
| symbol | TEXT | | NULL | |
| action | TEXT | | NULL | |
| quantity | INTEGER | | NULL | |
| price | REAL | | NULL | |
| commission | REAL | | 0.0 | |
| tax | REAL | | 0.0 | |
| trade_time | TEXT | | NULL | |
| status | TEXT | | 'PENDING' | |
| signal_id | TEXT | | NULL | |
| position_id | INTEGER | | NULL | |
| notes | TEXT | | NULL | |
| account_id | TEXT | | "1" | |

---

### analysis.db (旧路径 — 有数据)

路径: `C:\Users\17699\mo_zhi_sharereports\analysis.db`
大小: 4,404 KB | 用途: 旧版分析库，存储历史回测结果、日线行情、技术指标和交易日历（功能逐步迁移至 knowledge.db 和 factor_repository.db）

#### backtest_equity_series → [6 行]

说明: 旧版回测权益曲线，按 result_id 关联 backtest_results。旧版回测引擎写入，已逐步废弃。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| result_id | INTEGER | | NULL | |
| date | TEXT | | NULL | |
| equity | REAL | | NULL | |
| drawdown | REAL | | NULL | |
| position | TEXT | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |

#### backtest_results → [15 行]

说明: 旧版回测结果主表，含策略名、起止日期、初始/终值、收益率、夏普、最大回撤、参数等。旧版回测引擎写入。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| strategy_name | TEXT | | NULL | |
| start_date | TEXT | | NULL | |
| end_date | TEXT | | NULL | |
| initial_capital | REAL | | NULL | |
| final_value | REAL | | NULL | |
| total_return | REAL | | NULL | |
| annual_return | REAL | | NULL | |
| max_drawdown | REAL | | NULL | |
| sharpe_ratio | REAL | | NULL | |
| win_rate | REAL | | NULL | |
| total_trades | INTEGER | | NULL | |
| parameters | TEXT | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |
| code | TEXT | | NULL | |

#### cache_metadata → [4 行]

说明: 行情缓存元数据，记录每个品种最近一次缓存更新日期、时间和行数。数据采集模块写入和维护。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| symbol | TEXT | | NULL | PK |
| cache_date | TEXT | | NULL | |
| cache_time | TEXT | | NULL | |
| row_count | INTEGER | | NULL | |

#### oil_daily → [8 行]

说明: 原油日线行情（OHLCV），联合主键 (code, date)。数据采集模块写入，旧版原油策略读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| code | TEXT | YES | NULL | PK |
| date | TEXT | YES | NULL | PK |
| open | REAL | | NULL | |
| high | REAL | | NULL | |
| low | REAL | | NULL | |
| close | REAL | | NULL | |
| volume | INTEGER | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |

#### stock_daily → [10 行]

说明: 股票日线行情（含复权因子），联合主键 (code, date)。数据采集模块写入，旧版策略引擎读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| code | TEXT | YES | NULL | PK |
| date | TEXT | YES | NULL | PK |
| open | REAL | | NULL | |
| high | REAL | | NULL | |
| low | REAL | | NULL | |
| close | REAL | | NULL | |
| volume | INTEGER | | NULL | |
| amount | REAL | | NULL | |
| adj_factor | REAL | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |

#### stock_daily_unadjusted → [9 行]

说明: 未复权股票日线行情，结构与 stock_daily 一致但无 adj_factor。数据采集模块写入，需要原始价格的分析场景读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| code | TEXT | YES | NULL | PK |
| date | TEXT | YES | NULL | PK |
| open | REAL | | NULL | |
| high | REAL | | NULL | |
| low | REAL | | NULL | |
| close | REAL | | NULL | |
| volume | INTEGER | | NULL | |
| amount | REAL | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |

#### tech_indicators → [23 行]

说明: 技术指标计算结果，含 MA5/10/20/60/120、RSI、MACD、布林带、KDJ、趋势评分等。因子计算引擎写入，旧版策略引擎读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| code | TEXT | YES | NULL | PK |
| date | TEXT | YES | NULL | PK |
| ma5 | REAL | | NULL | |
| ma10 | REAL | | NULL | |
| ma20 | REAL | | NULL | |
| ma60 | REAL | | NULL | |
| rsi14 | REAL | | NULL | |
| macd_dif | REAL | | NULL | |
| macd_dea | REAL | | NULL | |
| macd_hist | REAL | | NULL | |
| bb_upper | REAL | | NULL | |
| bb_mid | REAL | | NULL | |
| bb_lower | REAL | | NULL | |
| kdj_k | REAL | | NULL | |
| kdj_d | REAL | | NULL | |
| kdj_j | REAL | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |
| ma120 | REAL | | NULL | |
| trend_score | REAL | | NULL | |
| trend_summary | TEXT | | NULL | |
| bb_squeeze | INTEGER | | 0 | |
| is_gap_day | INTEGER | | 0 | |

#### trading_calendar → [6 行]

说明: 交易日历，记录每个市场每日是否为交易日。数据采集模块写入，回测调度和信号生成模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| date | TEXT | YES | NULL | PK |
| market | TEXT | YES | NULL | PK |
| is_trading_day | INTEGER | YES | 0 | |
| market_type | TEXT | | '' | |
| note | TEXT | | '' | |
| created_at | TEXT | | datetime('now', 'localtime') | |

---

### analysis.db (新路径 — 空库)

路径: `C:\Users\17699\mozhi_platform\data\analysis.db`
大小: 0 KB | 用途: 新版分析库占位文件，当前无任何表。预留用作新版分析引擎的仓库。

---

## 辅助 & 测试

### file_registry.db

路径: `C:\Users\17699\mozhi_platform\registry\file_registry.db`
大小: 5,740 KB | 用途: 文件注册表，跟踪所有导入/生成文件的生命周期（位置、分类、校验和、标签）

#### files → [13 行]

说明: 文件索引主表，记录每个文件的原始路径、当前路径、分类、来源、校验和、标签等。文件导入和归档模块写入，所有需要文件索引的模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| filename | TEXT | | NULL | |
| original_path | TEXT | | NULL | |
| current_path | TEXT | | NULL | |
| category | TEXT | | NULL | |
| source | TEXT | YES | 'incoming' | |
| status | TEXT | | NULL | |
| checksum | TEXT | | NULL | |
| source_type | TEXT | YES | 'unknown' | |
| created_at | TEXT | | NULL | |
| imported_at | TEXT | | NULL | |
| tags | TEXT | | NULL | |
| note | TEXT | | NULL | |

---

### trading_calendar.db

路径: `C:\Users\17699\mo_zhi_sharereports\db\trading_calendar.db`
大小: 28 KB | 用途: 交易日历专用库，管理多市场的交易日、时段定义和异常申请审批

#### approval_records → [11 行]

说明: 交易日异常审批记录，用于申请/审批非标准交易日（如临时休市）。人工或自动流程写入，交易日历模块读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| request_id | TEXT | | NULL | PK |
| market | TEXT | | NULL | |
| cal_date | TEXT | | NULL | |
| anomaly_type | TEXT | | NULL | |
| note | TEXT | | NULL | |
| source | TEXT | | NULL | |
| reviewed_at | TEXT | | NULL | |
| approved_at | TEXT | | NULL | |
| written_at | TEXT | | NULL | |
| status | TEXT | | NULL | |
| created_at | TEXT | | NULL | |

#### trading_calendar → [7 行]

说明: 交易日历主表，记录每个市场每日是否为交易日、成交量类型、节假日类型。数据采集模块写入，全系统查询交易日使用。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| market | TEXT | YES | NULL | PK |
| cal_date | TEXT | YES | NULL | PK |
| is_trading | INTEGER | YES | 0 | |
| is_workday | INTEGER | YES | 1 | |
| volume_type | TEXT | YES | 'normal' | |
| holiday_type | TEXT | YES | 'none' | |
| created_at | TEXT | YES | datetime('now', 'localtime') | |

#### trading_session → [6 行]

说明: 交易时段定义，记录每个市场每日各时段的开闭时间。交易日历模块写入。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| market | TEXT | YES | NULL | PK |
| cal_date | TEXT | YES | NULL | PK |
| session_name | TEXT | YES | NULL | PK |
| open_time | TEXT | YES | NULL | |
| close_time | TEXT | YES | NULL | |
| timezone | TEXT | YES | 'Asia/Shanghai' | |

---

### \_integration_test.db

路径: `C:\Users\17699\mo_zhi_sharereports\automation_v2\paper_trade\_integration_test.db`
大小: 260 KB | 用途: 集成测试专用数据库，用于 paper_trade 模块的自动化测试，schema 与生产版 trade_engine 一致
> 备注: 该库表中不含 `account_id` 字段，结构比生产版精简

#### account_balance → [8 行]

说明: 测试用账户资金表。集成测试框架写入和读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| total_assets | REAL | YES | 0.0 | |
| available_balance | REAL | YES | 0.0 | |
| frozen_amount | REAL | YES | 0.0 | |
| position_market_value | REAL | YES | 0.0 | |
| initial_capital | REAL | YES | 0.0 | |
| realized_pnl | REAL | YES | 0.0 | |
| updated_at | TEXT | | datetime('now', 'localtime') | |

#### backtest_account → [6 行]

说明: 测试用历史回放模式账户。集成测试写入，验证回放执行逻辑。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| total_assets | REAL | YES | 0.0 | |
| available_balance | REAL | YES | 0.0 | |
| realized_pnl | REAL | YES | 0.0 | |
| initial_capital | REAL | YES | 0.0 | |
| updated_at | TEXT | | NULL | |

#### backtest_fund_flow → [9 行]

说明: 测试用资金流水，含 signal_task_id 和 symbol。集成测试写入，验证资金流向对应信号。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| flow_type | TEXT | YES | NULL | |
| amount | REAL | YES | NULL | |
| balance_before | REAL | YES | NULL | |
| balance_after | REAL | YES | NULL | |
| signal_task_id | TEXT | | NULL | |
| symbol | TEXT | | NULL | |
| description | TEXT | | NULL | |
| created_at | TEXT | | NULL | |

#### backtest_report → [15 行]

说明: 测试用回测报告，汇总日期范围、信号/交易数量、胜率、收益率、最大回撤、夏普等指标。集成测试框架写入。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| date_range_start | TEXT | | NULL | |
| date_range_end | TEXT | | NULL | |
| signals_loaded | INTEGER | | NULL | |
| trades_executed | INTEGER | | NULL | |
| win_count | INTEGER | | NULL | |
| loss_count | INTEGER | | NULL | |
| win_rate_pct | REAL | | NULL | |
| total_return_pct | REAL | | NULL | |
| max_drawdown_pct | REAL | | NULL | |
| sharpe_ratio | REAL | | NULL | |
| final_assets | REAL | | NULL | |
| initial_capital | REAL | | NULL | |
| total_pnl | REAL | | NULL | |
| created_at | TEXT | | NULL | |

#### backtest_trades → [13 行]

说明: 测试用逐笔交易详情，含 signal_task_id、symbol、action、价格、数量、盈亏、信号置信度等。集成测试框架写入。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| signal_task_id | TEXT | | NULL | |
| symbol | TEXT | | NULL | |
| action | TEXT | | NULL | |
| quantity | INTEGER | | NULL | |
| price | REAL | | NULL | |
| commission | REAL | | NULL | |
| tax | REAL | | NULL | |
| pnl | REAL | | NULL | |
| pnl_pct | REAL | | NULL | |
| signal_confidence | TEXT | | NULL | |
| signal_time | TEXT | | NULL | |
| trade_time | TEXT | | NULL | |

#### fund_flow → [9 行]

说明: 测试用资金流水，结构与生产版相同，但无 account_id。集成测试框架写入和读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| flow_type | TEXT | YES | NULL | |
| amount | REAL | YES | NULL | |
| balance_before | REAL | YES | NULL | |
| balance_after | REAL | YES | NULL | |
| order_id | TEXT | | NULL | |
| position_id | INTEGER | | NULL | |
| description | TEXT | | NULL | |
| created_at | TEXT | | datetime('now', 'localtime') | |

#### positions → [11 行]

说明: 测试用持仓表，结构精简，不含 account_id 等扩展字段。集成测试框架写入和读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| symbol | TEXT | | NULL | |
| direction | TEXT | | 'LONG' | |
| quantity | INTEGER | | NULL | |
| entry_price | REAL | | NULL | |
| entry_time | TEXT | | NULL | |
| status | TEXT | | 'OPEN' | |
| close_price | REAL | | NULL | |
| close_time | TEXT | | NULL | |
| pnl | REAL | | NULL | |
| stop_loss_price | REAL | | NULL | |

#### transactions → [13 行]

说明: 测试用交易流水，结构与生产版一致但无 account_id。集成测试框架写入和读取。

| 列名 | 类型 | 非空 | 默认值 | 主键 |
|------|------|:----:|:------:|:----:|
| id | INTEGER | | NULL | PK |
| order_id | TEXT | | NULL | |
| symbol | TEXT | | NULL | |
| action | TEXT | | NULL | |
| quantity | INTEGER | | NULL | |
| price | REAL | | NULL | |
| commission | REAL | | 0.0 | |
| tax | REAL | | 0.0 | |
| trade_time | TEXT | | NULL | |
| status | TEXT | | 'PENDING' | |
| signal_id | TEXT | | NULL | |
| position_id | INTEGER | | NULL | |
| notes | TEXT | | NULL | |

---

### trade_engine_empty.db (空壳)

路径: `C:\Users\17699\mo_zhi_sharereports\data\trade_engine.db`
大小: 0 KB | 用途: 空壳文件，无任何表，可忽略或清理。

---

## 实验库（仅注明表名和用途）

### exp01_trade.db

路径: `C:\Users\17699\mo_zhi_sharereports\experiments\exp01_reverse_collision\database\exp01_trade.db`
大小: 84 KB | 用途: 反向撞击实验的交易数据库

表名列表:
- `account_balance` — 交易账户资金快照
- `collision_events` — 撞击事件记录
- `daily_pnl` — 每日盈亏
- `db_stats_snapshots` — 数据库统计快照
- `experiment_runs` — 实验运行记录
- `fund_flow` — 资金流水
- `positions` — 持仓明细
- `system_state` — 系统状态 KV
- `transactions` — 交易流水

### exp02_trade.db

路径: `C:\Users\17699\mo_zhi_sharereports\experiments\exp02_concurrent_trade\database\exp02_trade.db`
大小: 176 KB | 用途: 并发交易实验的数据库

表名列表:
- `account_balance` — 交易账户资金快照
- `collision_events` — 撞击事件记录
- `daily_pnl` — 每日盈亏
- `db_stats_snapshots` — 数据库统计快照
- `experiment_runs` — 实验运行记录
- `fund_flow` — 资金流水
- `order_id_registry` — 订单 ID 注册表（实验2独有，用于管理并发订单 ID 分配）
- `positions` — 持仓明细
- `system_state` — 系统状态 KV
- `transactions` — 交易流水

---

## 汇总

| 数据库 | 表数 | 大小 | 状态 |
|--------|:----:|:----:|:----:|
| market_data.db | 1 | 464 KB | 活跃 |
| factor_repository.db | 2 | 7,796 KB | 活跃 |
| knowledge.db | 8 | 3,556 KB | 活跃 |
| trade_engine.db | 10 | 92 KB | 活跃（主库） |
| analysis.db (旧) | 8 | 4,404 KB | 逐步废弃 |
| analysis.db (新) | 0 | 0 KB | 空库 |
| file_registry.db | 1 | 5,740 KB | 活跃 |
| trading_calendar.db | 3 | 28 KB | 活跃 |
| _integration_test.db | 8 | 260 KB | 测试用 |
| trade_engine_empty.db | 0 | 0 KB | 空壳 |
| exp01_trade.db | 9 | 84 KB | 实验 |
| exp02_trade.db | 10 | 176 KB | 实验 |
| **合计** | **60** | **22.6 MB** | |
