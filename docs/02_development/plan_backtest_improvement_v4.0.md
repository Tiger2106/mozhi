<!--
author: 墨衡
created_time: 2026-05-15 23:17
task_id: plan_backtest_improvement
version: v4.0
-->

# 回测改进方案（v4.0 — 路径修正+迁移前置版）

**起草**: 墨衡
**时间**: 2026-05-15 23:17
**目的**: 严格按主人提出的 4 项要求制定改动方案
**v4.0 修正**: 新增第0项（引擎迁移）+ 全部路径改为新平台 `mozhi_platform/src/backtest/`
**来源**: 群聊指令（report_improvements_todo.md） 评审会意见 + 主人的路径归约指令
**备注**: v3.0 所有 `backtest_engine/` 路径已改为 `mozhi_platform/src/backtest/`。v3.0 的 `reports/backtest/` 路径：生成脚本(.py)迁移至新平台，报告模板(.md)暂时保留原位待迁移步骤统一处理。

---

## 新规约（由主人明确指定）

| 类型 | 路径规则 | 示例 |
|:-----|:---------|:-----|
| **程序文件 (.py)** | `mozhi_platform/src/backtest/` 对应子目录 | `benchmark.py` → `mozhi_platform/src/backtest/benchmark.py` |
| **中间文件 (文档/方案/报告)** | `mozhi_platform/incoming/` | 本方案文档 → `incoming/plan_backtest_improvement_v4.0.md` |
| **.done 信号** | `signals/tasks/`（不变） | — |

### 核心原则
- **旧文件保留不动**（copy-not-move），确保旧库 `mo_zhi_sharereports/backtest_engine/` 读路径不中断
- **新平台引入后，import 指向新库**，旧库不再修改
- 所有 .py 文件统一走新平台，杜绝双写

---

## 第0项：回测引擎迁移到新平台（新增前置项）

**约 1h，所有改动的先决条件**

### 背景
方案中涉及改动的核心 .py 文件仍位于旧库 `mo_zhi_sharereports/backtest_engine/`，而 `mozhi_platform/src/backtest/` 已有部分文件（strategies/、pipeline/、charts/），核心引擎文件缺失。必须先补齐迁移。

### 需迁移的文件清单

以下文件目前在 `mo_zhi_sharereports/backtest_engine/` 中，**尚未复制到** `mozhi_platform/src/backtest/`：

#### 核心引擎（预计迁移）
| # | 旧路径 | 新路径 | 说明 |
|:-:|:-------|:-------|:----|
| M-01 | `backtest_engine/benchmark.py` | `mozhi_platform/src/backtest/benchmark.py` | 类: BenchmarkIndex, BenchmarkProvider, BenchmarkPoint |
| M-02 | `backtest_engine/trade_logger.py` | `mozhi_platform/src/backtest/trade_logger.py` | 类: TradeRecord, DailySnapshot, TradeLogger |
| M-03 | `backtest_engine/backtest_engine.py` | `mozhi_platform/src/backtest/backtest_engine.py` | 回测引擎核心 |
| M-04 | `backtest_engine/order_executor.py` | `mozhi_platform/src/backtest/order_executor.py` | 订单执行 |
| M-05 | `backtest_engine/performance.py` | `mozhi_platform/src/backtest/performance.py` | 绩效计算 |
| M-06 | `backtest_engine/data_filler.py` | `mozhi_platform/src/backtest/data_filler.py` | 数据填充 |
| M-07 | `backtest_engine/date_aligner.py` | `mozhi_platform/src/backtest/date_aligner.py` | 日期对齐 |
| M-08 | `backtest_engine/backtest_context.py` | `mozhi_platform/src/backtest/backtest_context.py` | 上下文管理 |
| M-09 | `backtest_engine/capital_manager.py` | `mozhi_platform/src/backtest/capital_manager.py` | 资金管理 |
| M-10 | `backtest_engine/equity_curve.py` | `mozhi_platform/src/backtest/equity_curve.py` | 净值曲线 |
| M-11 | `backtest_engine/fee_model.py` | `mozhi_platform/src/backtest/fee_model.py` | 手续费模型 |
| M-12 | `backtest_engine/position_manager.py` | `mozhi_platform/src/backtest/position_manager.py` | 仓位管理 |
| M-13 | `backtest_engine/signal_bridge.py` | `mozhi_platform/src/backtest/signal_bridge.py` | 信号桥接 |
| M-14 | `backtest_engine/slippage_model.py` | `mozhi_platform/src/backtest/slippage_model.py` | 滑点模型 |

#### 测试文件（需新建 tests/ 目录）
| M-15 | `backtest_engine/tests/test_benchmark.py` | `mozhi_platform/src/backtest/tests/test_benchmark.py` |
| M-16 | `backtest_engine/tests/test_data_filler.py` | `mozhi_platform/src/backtest/tests/test_data_filler.py` |
| M-17 | `backtest_engine/tests/test_date_aligner.py` | `mozhi_platform/src/backtest/tests/test_date_aligner.py` |
| M-18 | `backtest_engine/tests/test_fee_model.py` | `mozhi_platform/src/backtest/tests/test_fee_model.py` |
| M-19 | `backtest_engine/tests/test_fifo_cost.py` | `mozhi_platform/src/backtest/tests/test_fifo_cost.py` |
| M-20 | `backtest_engine/tests/test_grid_position.py` | `mozhi_platform/src/backtest/tests/test_grid_position.py` |
| M-21 | `backtest_engine/tests/test_grid_strategy.py` | `mozhi_platform/src/backtest/tests/test_grid_strategy.py` |
| M-22 | `backtest_engine/tests/test_integration.py` | `mozhi_platform/src/backtest/tests/test_integration.py` |
| M-23 | `backtest_engine/tests/test_order_executor.py` | `mozhi_platform/src/backtest/tests/test_order_executor.py` |
| M-24 | `backtest_engine/tests/test_performance.py` | `mozhi_platform/src/backtest/tests/test_performance.py` |
| M-25 | `backtest_engine/tests/test_performance_baseline.py` | `mozhi_platform/src/backtest/tests/test_performance_baseline.py` |
| M-26 | `backtest_engine/tests/test_reversal_signal.py` | `mozhi_platform/src/backtest/tests/test_reversal_signal.py` |
| M-27 | `backtest_engine/tests/test_signal_bridge.py` | `mozhi_platform/src/backtest/tests/test_signal_bridge.py` |
| M-28 | `backtest_engine/tests/test_slippage_model.py` | `mozhi_platform/src/backtest/tests/test_slippage_model.py` |
| M-29 | `backtest_engine/tests/test_trend_backtest.py` | `mozhi_platform/src/backtest/tests/test_trend_backtest.py` |
| M-30 | `backtest_engine/tests/test_trend_position.py` | `mozhi_platform/src/backtest/tests/test_trend_position.py` |
| M-31 | `backtest_engine/tests/test_trend_signal.py` | `mozhi_platform/src/backtest/tests/test_trend_signal.py` |
| M-32 | `backtest_engine/tests/test_backtest_engine.py` | `mozhi_platform/src/backtest/tests/test_backtest_engine.py` |

#### 报告生成脚本
`reports/backtest/generate_comparison.py` → `mozhi_platform/src/backtest/reports/generate_comparison.py`

> ⚠️ 报告模板文件（`multi_comparison.md`、`grid_full_report.md`）为非 .py 文件，暂保留在 `reports/backtest/`，由第1~3项改动时统一处理路径映射。

### 迁移步骤

1. **复制文件**（copy-only）：
   - 将上述 M-01~M-14 复制到 `mozhi_platform/src/backtest/`
   - 新建 `mozhi_platform/src/backtest/tests/` 目录，复制 M-15~M-32
   - 新建 `mozhi_platform/src/backtest/reports/` 目录，复制 `reports/backtest/generate_comparison.py`
2. **修复 import 路径**（关键步骤）：
   - 梳理所有 .py 文件中形如 `from backtest_engine.xxx import ...` 的 import
   - 统一改为 `from mozhi_platform.src.backtest.xxx import ...`（或基于 sys.path 简化后的相对/绝对导入）
   - 检查 `__init__.py` 中的 __all__ 引用
3. **跑一遍测试**：
   - `cd mozhi_platform/src/backtest/ && python -m pytest tests/ -v`
   - 确保迁移后所有测试通过

> **旧文件保留不动**：`mo_zhi_sharereports/backtest_engine/` 原库不改，仅读不改。后续所有改动仅在 `mozhi_platform/src/backtest/` 中进行。

### 预估工时
- **1h**（含 copy 15min + import 修复 30min + 测试验证 15min）
- 工时可控制在 1h 以内，因为只改 import 路径，不改业务逻辑

---

## 第1项：基准对标

### 需求: 每个策略旁边加 买入持有 601857"同期表现。策略必须跑赢基准才有价值。
### 关键修正说明（评审要求）

#### 🛠 复权处理
股票股息会导致价格缺口，5年累计约 **20% 差异**。必须处理：
- **后复权**：将历史价格按除权除息向后修正，使价格曲线连续，买入持有收益率反映实际回报
- 使用 `akshare.stock_zh_a_hist(symbol, adjust="qfq")` 获取前复权数据（前复权 vs 后复权对本方案买入持有收益影响可控，选择前复权便于操作）
- 若 akshare 接口返回原始不复权数据，需在 `calc_buy_hold_return` 中手动计算复权因子
#### 🛠 口径说明 — 基准对标是方向性参考
- 策略收益率 = 净值收益率（含交易成本、滑点、资金管理）
- 买入持有收益率 = **价格收益率**（基于复权价格，不含股息再投资）
- 两者口径不同，直接绝对值对比不严谨
- **正确定位**：基准对标的**方向性参考**，用于判断策略是否在统计意义上超越"不做判断的简单持有"，而非精确超越几个百分点
- 报告中需明确标注口径差异

### 需要改动的文件

| # | 文件路径 | 改动类型 | 具体改动内容 |
|:-:|:---------|:--------:|:------------|
| 1a | `mozhi_platform/src/backtest/benchmark.py` | **修改** | 复用已有 `BenchmarkProvider`，新增 `register_from_akshare(symbol, start_date, end_date)` 方法，通过 akshare 获取个股日线行情并构建 `BenchmarkIndex`；新增 `calc_buy_hold_return(symbol, start_date, end_date)` 类方法 |
| 1b | `mozhi_platform/src/backtest/reports/generate_comparison.py` | **新建**（迁移后） | 导入 `BenchmarkProvider`，新增 `add_buy_hold_column(comparison_data, symbol, start, end)` 函数，在对比表每行旁插入"买入持有(601857)"六指标（同期总收益率、年化收益率、最大回撤、夏普比率、胜率、交易笔数） |
| 1c | `mozhi_platform/src/backtest/strategies/run_grid.py` | 修改 | 回测完成后调用 `BenchmarkProvider` 获取 601857 同期买入持有 KPI，写入单策略报告 |
| 1d | `mozhi_platform/src/backtest/strategies/run_trend.py` | 修改 | 同上 |
| 1e | `mozhi_platform/src/backtest/strategies/run_reversal.py` | 修改 | 同上 |
| 1f | `reports/backtest/multi_comparison.md` | 修改 | 对比表行旁新增"买入持有(601857)"列 |
| 1g | `reports/backtest/grid_full_report.md` | 修改 | 单策略报告 KPI 表旁新增买入持有对比行 |

### 数据结构设计

```python
# mozhi_platform/src/backtest/benchmark.py 新增方法

def calc_buy_hold_return(self, symbol: str, start_date: str, end_date: str) -> dict:
    """计算买入持有的 KPI 和净值曲线（前复权处理）

    流程:
    1. 调用 akshare.stock_zh_a_hist(symbol, adjust="qfq")
       获取前复权日线数据
    2. 筛选 [start_date, end_date] 区间
    3. 首日开盘价买入，最后一日收盘价卖出
    4. 计算 KPI（同现有 BenchmarkIndex 格式）
    5. 返回 dict: {total_return, annual_return, max_drawdown, sharpe_ratio,
       win_rate(固定100%), trades(固定1笔), equity_series}
    """
```

### 基准指数扩展（可选）
- 除 601857 外可增加：沪深300（00300.SH）、上证指数（000001.SH）
- 通过 `BenchmarkProvider.register_from_akshare()` 统一接入

### 复权/口径说明（报告中标注模板）
```markdown
> **🖍 基准对标说明**
> - 策略收益率为净值收益率（已扣除交易成本），买入持有收益率为前复权价格收益率（不含股息再投资）
> - 两者口径不同，基准对标的**方向性参考**，不代表策略需严格超越基准 X%
> - 买入持有采用前复权价格，已消除除权除息造成的价格缺口
```

### 预估工时
- **8h**（含 akshare 数据接入 2h + BenchmarkProvider 扩展 2h + 对比表渲染改造 2h + 单策略报告集成 1h + 复权口径测试验证 1h）
### 依赖/阻塞项
- **依赖**: akshare 已安装（v1.18.55），可直接使用
- **依赖**: `mozhi_platform/src/backtest/benchmark.py` 的 `BenchmarkProvider` 类复用改造（需先完成第0项迁移）
- **阻塞项**: akshare 网络接口不稳定时需加重试 + 本地缓存

### 推荐实现顺序
- **第 1 位**：优先完成。这是最基础的改进，其他项改动时也需要基准线做参考。

---

## 第2项：历史数据补全

### 需求: 当前回测仅84天（2026-01-05~2026-05-14），需扩展至至少3-5年。
### 数据源选择（评审确认）
| 方案 | 结论 |
|:----|:----:|
| akshare | ✅ **采用**。已安装 v1.18.55，`stock_zh_a_hist` 可获取日线历史数据。直接在新模块中使用 |
| tushare | ❌ 不推荐。无需额外安装，akshare 已满足需求 |

**akshare 数据获取示例**：
```python
import akshare as ak
df = ak.stock_zh_a_hist(symbol="601857", period="daily",
                        start_date="20210101", end_date="20260515",
                        adjust="qfq")
# 返回 columns: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 换手率
```

### 需要改动的文件

| # | 文件路径 | 改动类型 | 具体改动内容 |
|:-:|:---------|:--------:|:------------|
| 2a | `mozhi_platform/src/backtest/data_source.py` | **新建** | `AkshareDataSource` 类，封装 akshare 数据获取：`fetch_daily(symbol, start, end)`, `fetch_benchmark(symbol, start, end)`，含重试、缓存、限流 |
| 2b | `mozhi_platform/src/backtest/data_filler.py` | 修改 | 扩展 `DataFiller` 或新增接口，支持从 `AkshareDataSource` 获取历史数据并灌入回测引擎数据库 |
| 2c | `mozhi_platform/src/backtest/strategies/run_grid.py` | 修改 | 确认 `GridRunnerConfig` 中 `start_date`/`end_date` 参数已从入参传递到 `BacktestConfig`（需检查 `_persist_result` 中是否保存），若无则补充 |
| 2d | `mozhi_platform/src/backtest/strategies/run_trend.py` | 修改 | 同上，`TrendBacktestConfig` 已有 start_date/end_date，验证传递链路 |
| 2e | `mozhi_platform/src/backtest/strategies/run_reversal.py` | 修改 | 同上 |
| 2f | `reports/backtest/multi_comparison.md` | 修改 | 报告头部明确标注回测起止日期及总天数 |
| 2g | `mozhi_platform/src/backtest/reports/generate_comparison.py` | 修改 | 消除硬编码日期和模拟 KPI，改为从回测结果读取实际指标 |

### 数据范围建议
| 周期 | 日历天数 | 交易日约 | 说明 |
|:----:|:--------:|:--------:|:----|
| 6个月 | ~180天 | ~126天 | 最低可接受 |
| 1年 | ~365天 | ~250天 | 短期合理 |
| 3年 | ~1095天 | ~750天 | **推荐最低标准** |
| 5年 | ~1825天 | ~1250天 | 理想覆盖完整牛熊 |

### 预估工时
- **12h**（含 `AkshareDataSource` 模块 3h + DataFiller 扩展 3h + 回测参数验证 2h + 全量数据回滚运行 2h + 报告适配 2h）
### 依赖/阻塞项
- **依赖**: akshare 已安装
- **依赖**: 回测引擎 `BacktestEngine` 需支持 3-5 年长周期稳定运行（需先完成第0项迁移）
- **阻塞项**: 长达 5 年的日线全量回测可能运行较慢，需评估性能
- **阻塞项**: 数据库 schema 若仅支持近 84 天需扩展

### 推荐实现顺序
- **第 2 位**：在基准对标之后。本项改动最大、影响面最广，完成后第3项（逐笔交易明细）才有足够的样本支撑统计意义。

---

## 第3项：买卖过程盈利概率

### 需求: 逐笔交易明细（entry/exit价格、盈亏金额/比例、持仓天数）+ 盈亏分布统计（盈利/亏损笔数、平均收益/亏损、盈亏比）。
### 关键修正说明（评审要求）

#### 🛠 交易配对设计（新增设计小节，v3.0 新增）
现有 `TradeRecord` 是**单边记录**（只有 buy 或 sell 中的一个方向），没有"开仓→平仓"配对概念。
网格策略可能多空共存、部分卖出、多次加仓。
**需新增 `TradePair` 数据类用于配对追踪：**

```python
@dataclass
class TradePair:
    """一次完整的交易配对（开仓→平仓）"""
    pair_id: str                # 配对流水号
    symbol: str
    direction: str              # "long" | "short"
    
    # 开仓侧
    entry_trade_id: str         # 开仓 TradeRecord.trade_id
    entry_date: str             # 开仓日期
    entry_price: float          # 开仓均价
    entry_quantity: int         # 开仓数量
    
    # 平仓侧
    exit_trade_id: str          # 平仓 TradeRecord.trade_id（部分平仓时为首笔平仓ID）
    exit_date: str              # 平仓日期（完全平仓日期）
    exit_price: float           # 平仓均价
    exit_quantity: int          # 平仓数量
    
    # 衍生指标
    hold_days: int              # 持仓天数
    profit_amount: float        # 盈亏金额
    profit_pct: float           # 盈亏比例
    is_partial: bool = False    # 是否部分平仓
```

**配对算法说明（复杂度于此）：**
1. **FIFO 规则**：平仓时以最早未平仓的开仓单为准（先进先出）
2. **部分平仓**：一笔卖出可能对应多笔买入，按比例拆分
3. **网格多仓**：网格策略可能同时持有多笔同一标的的开仓（不同价格），平仓时需逐个匹配
4. **多空方向**：支持 long/short 双向配对
5. **无平仓的残仓**：期末未平仓标记为"OPEN"状态
**配对方法定义**：
```python
def build_trade_pairs(trades: List[TradeRecord]) -> List[TradePair]:
    """
    从单边 TradeRecord 流构建完整的开平配对。
    算法：
    1. 按时间排序所有交易记录
    2. 维护两个队列：long_open_queue, short_open_queue（用于未平仓的多/空头）
    3. 遍历每笔 TradeRecord:
       - direction="buy" → push 到 long_open_queue
       - direction="sell" → 从 long_open_queue 中 FIFO 弹出匹配，生成 TradePair
       - direction="short" → push 到 short_open_queue
       - direction="cover" → 从 short_open_queue 中 FIFO 弹出匹配，生成 TradePair
    4. 遍历结束后，队列中剩余的标记为 OPEN 状态
    5. 返回 TradePair 列表
    """
```

#### 🛠 工时修正
原方案预估 **8h** 严重低估。交易配对算法（FIFO + 部分配对 + 网格多仓 + 多空方向）的复杂度和字段追迹远超一般报表生成。
**修正为 16h**。
### 需要改动的文件

| # | 文件路径 | 改动类型 | 具体改动内容 |
|:-:|:---------|:--------:|:------------|
| 3a | `mozhi_platform/src/backtest/trade_logger.py` | **修改** | 新增 `TradePair` dataclass、`build_trade_pairs()` 配对算法函数、`TradePairStats` 统计分析类 |
| 3b | `mozhi_platform/src/backtest/strategies/run_grid.py` | 修改 | `_persist_result()` 中保存 TradeRecord 时确保 entry_price/exit_price 字段完整 |
| 3c | `mozhi_platform/src/backtest/strategies/run_trend.py` | 修改 | 同上 |
| 3d | `mozhi_platform/src/backtest/strategies/run_reversal.py` | 修改 | 同上 |
| 3e | `mozhi_platform/src/backtest/reports/generate_comparison.py` | **修改** | 新增 `generate_trade_detail_section(result, strategy_name)` 函数，读取 TradeRecord → 运行配对算法 → 生成交易明细表 + 盈亏分布统计 |
| 3f | `reports/backtest/multi_comparison.md` | 修改 | 在对比表下方新增"各策略交易明细"章节（按策略分组，含配对明细 + 分布统计） |
| 3g | `reports/backtest/grid_full_report.md` | 修改 | 单策略报告新增"交易明细"章节 |

### 输出格式

#### 逐笔配对交易明细表（追加到报告末页）

```markdown
### 逐笔交易明细 — 网格策略

| # | 方向 | 开仓日期 | 平仓日期 | 开仓价 | 平仓价 | 数量 | 持仓天数 | 盈亏金额 | 盈亏比例 | 状态 |
|:-:|:----:|:--------:|:--------:|:------:|:------:|:---:|:--------:|:--------:|:--------:|:----:|
| 1 | LONG | 2026-01-07 | 2026-01-15 | 8.12 | 8.35 | 1000 | 8 | +230.00 | +2.83% | ✅ |
| 2 | LONG | 2026-01-20 | 2026-02-03 | 8.28 | 8.10 | 500 | 14 | -90.00 | -2.17% | ✅ |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |
| N | LONG | 2026-03-10 | - | 8.50 | - | 200 | - | - | - | ⏳ |
```

#### 盈亏分布统计

```markdown
### 盈亏分布 — 网格策略

| 指标 | 数值 |
|:----|:----:|
| 总配对笔数 | 20 |
| 已平仓笔数 | 18 |
| 未平仓笔数 | 2 |
| 盈利笔数 | 12 |
| 亏损笔数 | 6 |
| 胜率 | 66.7% |
| 盈利交易平均收益 | +385.00 |
| 亏损交易平均亏损 | -210.00 |
| 平均盈亏比 | 1.83 |
| 最大单笔盈利 | +1200.00 |
| 最大单笔亏损 | -560.00 |
| 平均持仓天数 | 9.5 天 |
| 单笔最大持仓天数 | 22 天 |
```

### 统计意义说明
- 当回测数据从 84 天扩展至 3-5 年（第2项完成后），配对交易笔数从目前的个位数增至上百笔，盈亏分布统计才具有实际参考价值
- 建议按年度分组统计，展示不同市场环境下的策略表现差异

### 预估工时
- **16h**（含 TradePair 配对算法设计实现 6h + trade_logger 字段完整性改造 2h + generate_trade_detail 逻辑 3h + 报告渲染改造 3h + 配对算法测试验证 2h）
### 依赖/阻塞项
- **依赖**: 第2项（历史数据补全）完成，确保有足够配对样本
- **依赖**: TradeRecord 字段完整（price, quantity 等），pairing 算法需要准确的持仓时序
- **依赖**: 第0项迁移完成，`trade_logger.py` 在新平台中
- **阻塞项**: 若 trade_log 字段缺失或方向不完整，需重新回测或追溯修正历史记录
- **阻塞项**: 配对算法在多网格场景下（部分卖出+多次加仓）的正确性需充分测试

### 推荐实现顺序
- **第 3 位**：在第2项之后。样本不足时配对统计意义有限。

---

## 第4项：模型参数随产出文件
### 需求: 每次回测产出的报告附带策略参数配置（趋势MA周期、网格间距、反转阈值等）。
### 关键修正说明（评审确认）
- Config 类已存在（`GridRunnerConfig`, `TrendBacktestConfig`, `ReversalBacktestConfig`），嵌入在各 `run_*.py` 文件中
- 无需新建 `*_config.py`，直接在已有 Config dataclass 上追加 `to_params_dict()` 方法
- 报告渲染中增加参数摘要章节
### 需要改动的文件

| # | 文件路径 | 改动类型 | 具体改动内容 |
|:-:|:---------|:--------:|:------------|
| 4a | `mozhi_platform/src/backtest/strategies/run_grid.py` | 修改 | `GridRunnerConfig` 新增 `to_params_dict()` 方法，序列化核心参数（grid_spacing, grid_levels, base_price 等） |
| 4b | `mozhi_platform/src/backtest/strategies/run_trend.py` | 修改 | `TrendBacktestConfig` 新增 `to_params_dict()` 方法，序列化核心参数（ma_short/long_period, entry/exit_threshold 等） |
| 4c | `mozhi_platform/src/backtest/strategies/run_reversal.py` | 修改 | `ReversalBacktestConfig` 新增 `to_params_dict()` 方法，序列化核心参数（lookback_period, oversold/overbought_threshold 等） |
| 4d | `mozhi_platform/src/backtest/strategies/run_grid.py` | 修改 | `_persist_result()` 中保存参数配置到持久化 payload |
| 4e | `mozhi_platform/src/backtest/strategies/run_trend.py` | 修改 | `_persist_result()` 中保存参数配置 |
| 4f | `mozhi_platform/src/backtest/strategies/run_reversal.py` | 修改 | `_persist_result()` 中保存参数配置 |
| 4g | `mozhi_platform/src/backtest/reports/generate_comparison.py` | 修改 | 对比报告中列出每个策略的参数配置摘要 |
| 4h | `reports/backtest/grid_full_report.md` | 修改 | 报告新增"模型参数配置"章节 |

### 参数清单（各策略）
#### 网格策略参数
```json
{
  "strategy": "grid",
  "symbol": "601857",
  "version": "P4-11",
  "params": {
    "signal_type": "StaticGridSignal",
    "grid_spacing": 0.02,
    "grid_levels": 10,
    "base_price": 8.00,
    "position_mode": "fixed",
    "position_per_grid": 0.1,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.03,
    "max_open_orders": 5,
    "initial_capital": 1000000,
    "fee_rate": 0.0003,
    "slippage_rate": 0.001
  }
}
```

#### 趋势策略参数
```json
{
  "strategy": "trend",
  "symbol": "601857",
  "version": "P4-11",
  "params": {
    "ma_short_period": 5,
    "ma_long_period": 20,
    "entry_threshold": 0.02,
    "exit_threshold": -0.01,
    "stop_loss_pct": 0.05,
    "initial_capital": 1000000,
    "fee_rate": 0.0003,
    "slippage_rate": 0.001
  }
}
```

#### 反转策略参数
```json
{
  "strategy": "reversal",
  "symbol": "601857",
  "version": "P4-11",
  "params": {
    "lookback_period": 10,
    "oversold_threshold": -2.0,
    "overbought_threshold": 2.0,
    "entry_confidence": 0.7,
    "stop_loss_pct": 0.04,
    "take_profit_pct": 0.06,
    "max_hold_days": 5,
    "initial_capital": 1000000,
    "fee_rate": 0.0003,
    "slippage_rate": 0.001
  }
}
```

### 输出格式（报告中）
```markdown
## 模型参数配置

### 网格策略参数 (v1.2)

| 参数 | 值 | 说明 |
|:-----|:--:|:----:|
| 信号类型 | StaticGridSignal | 静态等距网格 |
| 网格间距 | 0.02 (2%) | 上下各 2% 开一档 |
| 网格层数 | 10 层 | 双边各 5 层 |
| 基准价 | ¥8.00 | 网格对称中心 |
| 仓位模式 | fixed | 固定数量 |
| 每格仓位 | 10% | 占总资金比例 |
| 止损 | -5% | 单格 max loss |
| 止盈 | +3% | 单格 take profit |
| 最大开仓 | 5 单 | 同时持仓上限 |
| 初始资金 | ¥1,000,000 | |
| 手续费率 | 0.03% | |
| 滑点率 | 0.1% | |
```

### 版本管理建议
- 参数配置附加版本号（如 v1.0, v1.1, v2.0）
- 每次参数优化后更新版本号
- 报告中记录使用的参数版本，便于追踪
### 预估工时
- **4h**（含 Config.to_params_dict() 实现 1.5h + runner/persist 集成 1h + 报告渲染适配 1.5h）
### 依赖/阻塞项
- **依赖**: 各 `run_*.py` 中现有 Config dataclass 结构清晰，可直接扩展 `to_params_dict()`
- **无阻塞项**: 本项改动独立，不依赖其他项
### 推荐实现顺序
- **第 4 位**：最后完成。独立性强，可与前 3 项并行开发，但建议排最后以避免参数格式在回测改造过程中变动。

---

## 执行顺序总览

| 顺序 | 项名 | 预估工时 | 关键依赖 |
|:----:|:----|:--------:|:---------|
| 0 | 第0项：回测引擎迁移到新平台 | 1h | —（先决条件） |
| 1 | 第1项：基准对标 | 8h | 行情数据（akshare）、基准口径说明 |
| 2 | 第2项：历史数据补全 | 12h | akshare 数据源 + 回测引擎长周期支持 |
| 3 | 第3项：买卖过程盈利概率 | **16h** | 第2项完成 + 交易配对算法设计（**复杂**） |
| 4 | 第4项：模型参数随产出文件 | 4h | 无（可并行） |
| **合计** | | **41h** | |

> 🖍 第3项工时已从原 8h 修正为 **16h**（交易配对算法复杂度严重低估），总计 **41h**。

---

## 文件改动统计

| 文件 | 改动项 |
|:-----|:------:|
| `mozhi_platform/src/backtest/benchmark.py` | 第1项（a） |
| `mozhi_platform/src/backtest/data_source.py` | 第2项（a）**新建** |
| `mozhi_platform/src/backtest/data_filler.py` | 第2项（b） |
| `mozhi_platform/src/backtest/trade_logger.py` | 第3项（a）新增 TradePair + 配对算法 |
| `mozhi_platform/src/backtest/strategies/run_grid.py` | 第1(c)、2(c)、3(b)、4(a,d)项 |
| `mozhi_platform/src/backtest/strategies/run_trend.py` | 第1(d)、2(d)、3(c)、4(b,e)项 |
| `mozhi_platform/src/backtest/strategies/run_reversal.py` | 第1(e)、2(e)、3(d)、4(c,f)项 |
| `mozhi_platform/src/backtest/reports/generate_comparison.py` | 第1(b)、2(g)、3(e)、4(g)项 |
| `reports/backtest/multi_comparison.md` | 第1(f)、2(f)、3(f)项 |
| `reports/backtest/grid_full_report.md` | 第1(g)、3(g)、4(h)项 |

### 旧库 vs 新库映射

| 旧路径（v3.0 引用） | 新路径（v4.0） |
|:---------------------|:---------------|
| `backtest_engine/benchmark.py` | `mozhi_platform/src/backtest/benchmark.py` |
| `backtest_engine/trade_logger.py` | `mozhi_platform/src/backtest/trade_logger.py` |
| `backtest_engine/data_source.py` | `mozhi_platform/src/backtest/data_source.py` |
| `backtest_engine/data_filler.py` | `mozhi_platform/src/backtest/data_filler.py` |
| `backtest_engine/strategies/run_grid.py` | `mozhi_platform/src/backtest/strategies/run_grid.py` |
| `backtest_engine/strategies/run_trend.py` | `mozhi_platform/src/backtest/strategies/run_trend.py` |
| `backtest_engine/strategies/run_reversal.py` | `mozhi_platform/src/backtest/strategies/run_reversal.py` |
| `reports/backtest/generate_comparison.py` | `mozhi_platform/src/backtest/reports/generate_comparison.py` |
| `reports/backtest/multi_comparison.md` | `reports/backtest/multi_comparison.md`（保留原位） |
| `reports/backtest/grid_full_report.md` | `reports/backtest/grid_full_report.md`（保留原位） |

---

## 细化任务清单（按优先级排列）

### P0 任务

#### 第0项：回测引擎迁移（前置，约 1h）
| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P0-00 | copy 核心引擎文件至 mozhi_platform/src/backtest/（14个 .py） | 15min | — | 墨衡 | 第0项 |
| P0-01 | copy 测试文件至 mozhi_platform/src/backtest/tests/（18个 .py） | 10min | P0-00 | 墨衡 | 第0项 |
| P0-02 | copy generate_comparison.py 至 mozhi_platform/src/backtest/reports/ | 5min | P0-00 | 墨衡 | 第0项 |
| P0-03 | 修复所有 import 路径（backtest_engine.xxx → mozhi_platform.src.backtest.xxx） | 20min | P0-01, P0-02 | 墨衡 | 第0项 |
| P0-04 | 运行 pytest 验证迁移后所有测试通过 | 10min | P0-03 | 墨衡 | 第0项 |

#### 第1项：基准对标
| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P0-05 | AkshareDataSource.fetch_daily() 封装行情接口 | 15min | P0-03 | 墨衡 | 第1项 |
| P0-06 | fetch_daily() retry+cache 机制 | 15min | P0-05 | 墨衡 | 第1项 |
| P0-07 | BenchmarkProvider.register_from_akshare() 数据解析+Index构建 | 15min | P0-06 | 墨衡 | 第1项 |
| P0-08 | calc_buy_hold_return(): 复权价格序列获取及校验 | 15min | P0-07 | 墨衡 | 第1项 |
| P0-09 | calc_buy_hold_return(): KPI计算(总收益/年化/回撤/夏普) | 15min | P0-08 | 墨衡 | 第1项 |
| P0-10 | generate_comparison.py: add_buy_hold_column() 函数 | 15min | P0-09 | 墨衡 | 第1项 |
| P0-11 | generate_comparison.py: 对比表渲染买入持有行 | 15min | P0-10 | 墨衡 | 第1项 |
| P0-12 | run_grid.py: 集成 BenchmarkProvider 调用 | 15min | P0-09 | 墨衡 | 第1项 |
| P0-13 | run_grid.py: 单策略结果保存买入持有 KPI | 10min | P0-12 | 墨衡 | 第1项 |
| P0-14 | multi_comparison.md: 买入持有列模板更新 | 5min | P0-11 | 墨衡 | 第1项 |
| P0-15 | grid_full_report.md: 买入持有对比行更新 | 5min | P0-13 | 墨衡 | 第1项 |

#### 第2项：历史数据补全
| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P0-16 | AkshareDataSource 类骨架搭建 + 构造函数 | 15min | P0-03 | 墨衡 | 第2项 |
| P0-17 | fetch_daily() akshare 调用+参数校验 | 15min | P0-16 | 墨衡 | 第2项 |
| P0-18 | DataFiller 扩展: 支持 AkshareDataSource 输入接口 | 15min | P0-17 | 墨衡 | 第2项 |
| P0-19 | DataFiller: 批量历史数据灌入逻辑 | 15min | P0-18 | 墨衡 | 第2项 |
| P0-20 | 数据 schema 校验 + 日期范围剪裁 | 10min | P0-19 | 墨衡 | 第2项 |
| P0-21 | 检查 run_grid.py start_date/end_date 传递链 | 15min | — | 墨衡 | 第2项 |
| P0-22 | 补全参数传递缺失 (run_grid) | 15min | P0-21 | 墨衡 | 第2项 |
| P0-23 | 全量数据回滚运行: 1年数据首次验证 | 15min | P0-19, P0-22 | 墨衡 | 第2项 |
| P0-24 | 全量数据回滚运行: 3年数据稳定性验证 | 15min | P0-23 | 墨衡 | 第2项 |
| P0-25 | generate_comparison.py: 消除硬编码日期 | 15min | P0-19 | 墨衡 | 第2项 |
| P0-26 | generate_comparison.py: 从结果读取实际指标 | 15min | P0-25 | 墨衡 | 第2项 |

#### 第3项：买卖过程盈利概率
| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P0-27 | TradePair dataclass + 字段定义 | 15min | P0-03 | 墨衡 | 第3项 |
| P0-28 | build_trade_pairs(): FIFO 队列初始化+方向分类 | 15min | P0-27 | 墨衡 | 第3项 |
| P0-29 | build_trade_pairs(): 单方向(P0-28 long)配对匹配逻辑 | 15min | P0-28 | 墨衡 | 第3项 |
| P0-30 | build_trade_pairs(): partial 部分平仓拆分逻辑 | 15min | P0-29 | 墨衡 | 第3项 |
| P0-31 | build_trade_pairs(): short/cover 双向支持 | 10min | P0-30 | 墨衡 | 第3项 |
| P0-32 | build_trade_pairs(): 残余OPEN标记+return | 10min | P0-31 | 墨衡 | 第3项 |
| P0-33 | TradePairStats 统计类: 盈利/亏损/胜率计算 | 15min | P0-32 | 墨衡 | 第3项 |
| P0-34 | TradePairStats: 平均盈亏比+持仓天数 | 10min | P0-33 | 墨衡 | 第3项 |
| P0-35 | generate_comparison.py: generate_trade_detail_section() 函数 | 15min | P0-34 | 墨衡 | 第3项 |
| P0-36 | generate_comparison.py: 配对 → 明细表渲染 | 15min | P0-35 | 墨衡 | 第3项 |
| P0-37 | generate_comparison.py: 盈亏分布统计表渲染 | 15min | P0-35 | 墨衡 | 第3项 |
| P0-38 | run_grid.py: _persist_result() 确认 entry/exit_price 完整 | 10min | P0-28 | 墨衡 | 第3项 |
| P0-39 | run_trend.py: _persist_result() 价量字段完整性检查 | 10min | P0-28 | 墨衡 | 第3项 |
| P0-40 | run_reversal.py: _persist_result() 价量字段完整性检查 | 10min | P0-28 | 墨衡 | 第3项 |
| P0-41 | multi_comparison.md: 交易明细章节模板 | 10min | P0-36, P0-37 | 墨衡 | 第3项 |
| P0-42 | grid_full_report.md: 交易明细章节模板 | 10min | P0-36, P0-37 | 墨衡 | 第3项 |

#### 第4项：模型参数随产出文件
| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P0-43 | run_grid.py: GridRunnerConfig.to_params_dict() 序列化 | 10min | P0-03 | 墨衡 | 第4项 |
| P0-44 | run_trend.py: TrendBacktestConfig.to_params_dict() | 10min | P0-03 | 墨衡 | 第4项 |
| P0-45 | run_reversal.py: ReversalBacktestConfig.to_params_dict() | 10min | P0-03 | 墨衡 | 第4项 |
| P0-46 | run_grid.py: _persist_result() 保存 params 到 payload | 10min | P0-43 | 墨衡 | 第4项 |
| P0-47 | run_trend.py: _persist_result() 保存参数配置 | 10min | P0-44 | 墨衡 | 第4项 |
| P0-48 | run_reversal.py: _persist_result() 保存参数配置 | 10min | P0-45 | 墨衡 | 第4项 |
| P0-49 | generate_comparison.py: 对比报告列出各策略参数摘要 | 15min | P0-46, P0-47, P0-48 | 墨衡 | 第4项 |
| P0-50 | grid_full_report.md: 参数配置章节模板 | 5min | P0-49 | 墨衡 | 第4项 |

#### 墨萱测试任务（P0）
| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P0-T1 | 墨萱: 验证迁移后 pytest 全部通过 | 10min | P0-04 | 墨萱 | 第0项 |
| P0-T2 | 墨萱: 验证 akshare 数据获取+复权计算准确性 | 15min | P0-06, P0-09 | 墨萱 | 第1项 |
| P0-T3 | 墨萱: 验证单策略报告基准列渲染 | 10min | P0-13, P0-15 | 墨萱 | 第1项 |
| P0-T4 | 墨萱: 验证对比报告买入持有列 | 10min | P0-11, P0-14 | 墨萱 | 第1项 |
| P0-T5 | 墨萱: 验证 1 年数据回测完整性与正确性 | 15min | P0-23 | 墨萱 | 第2项 |
| P0-T6 | 墨萱: 验证 3 年数据回测稳定性+对比报告日期 | 15min | P0-24, P0-26 | 墨萱 | 第2项 |
| P0-T7 | 墨萱: 验证交易配对算法单方向正确性 | 15min | P0-32 | 墨萱 | 第3项 |
| P0-T8 | 墨萱: 验证配对 partial 拆分+双向正确性 | 15min | P0-32 | 墨萱 | 第3项 |
| P0-T9 | 墨萱: 验证盈亏分布统计表渲染 | 10min | P0-37, P0-41 | 墨萱 | 第3项 |
| P0-T10 | 墨萱: 验证参数配置输出正确性 | 15min | P0-49, P0-50 | 墨萱 | 第4项 |

### P1 任务

| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P1-01 | run_trend.py: 集成 BenchmarkProvider | 10min | P0-09 | 墨衡 | 第1项 |
| P1-02 | run_reversal.py: 集成 BenchmarkProvider | 10min | P0-09 | 墨衡 | 第1项 |
| P1-03 | run_trend.py: 单策略结果保存买入持有 KPI | 10min | P1-01 | 墨衡 | 第1项 |
| P1-04 | run_reversal.py: 单策略结果保存买入持有 KPI | 10min | P1-02 | 墨衡 | 第1项 |
| P1-05 | 复权口径差异说明文档注释补充 | 5min | P0-09 | 墨衡 | 第1项 |
| P1-06 | 重试+限流+日志机制完善 | 15min | P0-17 | 墨衡 | 第2项 |
| P1-07 | 本地缓存层实现 (data_source cache) | 15min | P0-17 | 墨衡 | 第2项 |
| P1-08 | fetch_benchmark() 基准数据接口 | 10min | P1-06 | 墨衡 | 第2项 |
| P1-09 | 检查 run_trend.py 参数传递链 | 10min | — | 墨衡 | 第2项 |
| P1-10 | 检查 run_reversal.py 参数传递链 | 10min | — | 墨衡 | 第2项 |
| P1-11 | 补全参数传递缺失 (run_trend) | 10min | P1-09 | 墨衡 | 第2项 |
| P1-12 | 补全参数传递缺失 (run_reversal) | 10min | P1-10 | 墨衡 | 第2项 |
| P1-13 | 全量数据回滚运行: 5 年数据验收测试 | 15min | P0-24 | 墨衡 | 第2项 |
| P1-14 | multi_comparison.md: 标注回测起止日期+总天数 | 5min | P0-26 | 墨衡 | 第2项 |
| P1-15 | build_trade_pairs(): 网格多仓 multi-position 场景适配 | 15min | P0-32 | 墨衡 | 第3项 |
| P1-16 | grid_report.md: 参数配置章节模板 + 版本号管理说明 | 10min | P0-49 | 墨衡 | 第4项 |
| P1-T1 | 墨萱: 验证 trend/reversal 基准列渲染 | 10min | P1-03, P1-04 | 墨萱 | 第1项 |
| P1-T2 | 墨萱: 验证 5 年数据回测性能+稳定性 | 15min | P1-13 | 墨萱 | 第2项 |
| P1-T3 | 墨萱: 验证 DataSource 缓存命中率 | 10min | P1-07 | 墨萱 | 第2项 |
| P1-T4 | 墨萱: 端到端回测(含配对)完整链路验证 | 15min | P0-T7, P0-T8, P0-42 | 墨萱 | 第3项 |
| P1-T5 | 墨萱: 参数配置随报告输出完整验证 | 10min | P1-16 | 墨萱 | 第4项 |

### P2 任务

| # | 任务名 | 预估 | 依赖 | 执行人 | 所属项 |
|:-:|:------|:----:|:----:|:-----:|:-----:|
| P2-01 | BenchmarkProvider 支持沪深300/上证指数扩展 | 15min | P0-08 | 墨衡 | 第1项 |
| P2-02 | akshare 数据预载脚本(批量缓存全覆盖) | 15min | P1-07 | 墨衡 | 第2项 |
| P2-03 | 按年度分组配对统计(不同市场环境) | 15min | P0-34 | 墨衡 | 第3项 |
| P2-04 | 配对算法网格场景覆盖率测试(edge cases) | 15min | P1-15 | 墨衡 | 第3项 |
| P2-05 | multi_comparison.md: 模型参数章节模板 | 10min | P0-49 | 墨衡 | 第4项 |
| P2-T1 | 墨萱: 验证沪深300 benchmark 数据准确性 | 10min | P2-01 | 墨萱 | 第1项 |
| P2-T2 | 墨萱: 数据集完整性抽查(随机日期对比) | 10min | P2-02 | 墨萱 | 第2项 |
| P2-T3 | 墨萱: 年度分组统计表渲染验证 | 10min | P2-03, P0-41 | 墨萱 | 第3项 |

---

### 工时汇总

| 优先级 | 任务数 | 总工时(含测试) |
|:-----:|:-----:|:-------------:|
| P0 | 60 项（含5项迁移+55项改动） | ~12.8h |
| P1 | 25 项 | ~4.2h |
| P2 | 10 项 | ~1.8h |
| **合计** | **95 项** | **~18.8h** |

> ⚠️ 工时汇总为子任务累加，小于原方案 41h 预算。差额为集成调试、代码审查、环境准备等零散开销，在开发过程中按需分配。
> 🖍 第0项（迁移）约 1h 为新增前置成本。

### 墨涵文档归档（不计入工时，02:00 日常维护）

| # | 任务 | 执行人 |
|:-:|:-----|:-----:|
| D-01 | 归档本方案(v4.0)至 `mozhi_platform/incoming/` | 墨涵 |
| D-02 | 更新 `file_registry.db` 注册新文档索引 | 墨涵 |
| D-03 | 各子任务完成后收集开发记录/测试报告归档 | 墨涵 |

---

*本文档 v4.0 根据主人路径规约指令修正。核心变更：新增第0项（回测引擎迁移至 mozhi_platform）、全部程序文件路径改为 `mozhi_platform/src/backtest/`。v3.0（路径错误/未区分新旧库）已覆盖作废。*

---

## 会签记录

| 角色 | 结论 | 签名时间 |
|:----|:----:|:--------:|
| 墨衡（起草/执行） | ✅ 通过 | 2026-05-15 23:17 |
| 墨萱（测试验收） | ⏳ 待确认 | — |
| 玄知（技术把关） | ⏳ 待确认 | — |
| 墨涵（汇总决议） | ⏳ 待确认 | — |
| 主人（最终批准） | ⏳ 待确认 | — |

**条件说明：** 第0项（迁移）为所有改动先决条件，需先执行通过后再进入第1~4项。
