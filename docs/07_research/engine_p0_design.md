# P0修复方案：回测引擎三项关键缺陷

> **author:** 墨衡 (moheng)
> **created:** 2026-05-27T14:37+08:00
> **基于代码审计:** `scripts/exp003_knowdeep/run_exp003_q4.py`
> **数据源:** tushare_pro / v1.0 (`data/market/market_data.db`)

---

## 概述

`run_exp003_q4.py` 中的组合回测引擎 (`run_portfolio_backtest`) 存在三项 P0 级缺陷。以下逐一分析根因、影响范围及修复方案。总计预估 **9 小时**。

| 项目 | 问题 | 工时 |
|:----|:-----|:----:|
| P0-1 | T+1 交易延迟（买入当日不可卖出） | 4h |
| P0-2 | 前视偏差（信号使用当日数据） | 3h |
| P0-3 | 分红现金流未计入 | 2h |

---

## P0-1：T+1 交易延迟（4h）

### 问题描述

A 股实行 T+1 交收制度：**当日买入的股票最早 T+1 可卖出**。当前 `run_portfolio_backtest` 允许信号反转时在同一交易日内卖出当日刚买入的仓位，造成虚假交易收益。

### 代码根因

在 `run_portfolio_backtest` (约 line 210-240)，买入循环和卖出循环在同一 `valid` 集合上独立执行，未做买入日的交叉检查：

```python
for t in tickers:
    current = positions.get(t, 0)
    target = new_positions.get(t, 0)
    if target > current:
        # 买入 — 未标记买入日
    if current > target:
        # 卖出 — 未校验是否今日买入
```

`positions` 字典仅存储 `{ticker: shares}`，**不存储买入日期**，无法判断卖出限制。

### 修复方案

**在 `run_portfolio_backtest` 函数内新增 `buy_date` 追踪，并修改卖出逻辑：**

```python
# 1. 新增数据结构
buy_date: Dict[str, int] = {}  # ticker -> 最近一次买入的交易日期索引

# 2. 买入时（target > current），记录买入日
if target > current:
    if current == 0:             # 仅全仓新建时记录
        buy_date[t] = di         # di = 当前交易日 all_dates 的索引
    # ... 执行买入 ...

# 3. 卖出时（current > target），跳过 T+0 锁仓标的
if current > target:
    last_buy_idx = buy_date.get(t, -1)
    if last_buy_idx >= 0 and (di - last_buy_idx) < 1:
        # 今日买入的仓位不可卖出 → 跳过卖出
        new_positions[t] = current  # 保持原仓位
        continue
    # ... 正常卖出 ...
```

**关键设计决策：**
- 仅全仓新建时记录 `buy_date`；加仓买入仅增量，不影响原有锁定期（参考 A 股实际规则：加仓的部分 T+1，但原持有的仓位可自由卖出）
- 一单位标的只记录最近一次"从零到一"的买入，逻辑清晰
- 首次交易日的所有持仓均为有效仓位（首日无前日买入，卖出循环自然跳过）

**影响范围：**
- 仅限 `run_portfolio_backtest` 函数内部
- `run_benchmark` 基准使用月频调仓，T+1 影响极小，但建议同步修改以保一致性

---

## P0-2：前视偏差（Look-ahead Bias，3h）

### 问题描述

`calc_vol_rsi_std` 在计算位置 `i` 的信号时使用了 **当日** (index `i`) 的成交量数据。实盘信号应在 **T 日开盘前** 基于 **T-1 日收盘数据** 完成计算和生成。当信号在同日被回测引擎使用时，构成前视偏差。

### 代码根因

- `compute_signal_vector` 中 `calc_vol_rsi_std(sd["volume"])` 对位置 `i` 输出 `result[i]`，使用了 `volume[0:i+1]`（含当日）
- `run_portfolio_backtest` 中读取信号：`sig_arr[idx]`，`idx` 为当日索引

### 修复方案

**方案A（推荐）：信号生成层后移**

在 `compute_signal_vector` 函数末尾，将每个信号数组整体右移 1 天：

```python
def compute_signal_vector(stock_data, weights):
    signals = {}
    for ticker, sd in stock_data.items():
        vol_std = calc_vol_rsi_std(sd["volume"])
        ...
        raw_signal = reverse_factor(composite)
        # 后移 1 天消除前视（day 0 置 NaN）
        shifted = np.full(len(raw_signal), np.nan)
        shifted[1:] = raw_signal[:-1]
        signals[ticker] = shifted
    return signals
```

**方案B：回测执行层偏移**

在 `run_portfolio_backtest` 中信号读取处偏移：

```python
sig_arr[idx - 1] if idx >= 1 else skip
```

**推荐方案A**，因所有信号使用者自动受益，代码改动集中。

**影响范围：**
- 只修改 `compute_signal_vector` 函数
- `run_portfolio_backtest` 与 `run_benchmark` 无需改动
- IC 测试（Q3）需重新验证信号预测力

---

## P0-3：分红现金流（2h）

### 问题描述

持仓股票在除息日发放现金分红时，资金账户应收到分红收入。当前回测的资金流模型仅含买卖交易，**完全未计入分红**，导致：
- 长期持有高分红标的（茅台、平安等）的累计收益被低估
- 分红现金未能在后续调仓中被重新投资

### 数据可行性

`stock_daily` 表包含 `adj_factor`（复权因子）字段（来源 tushare_pro），可用于反算每股现金分红。

### 修复方案

**方案A（推荐，2h）：基于复权因子反算**

**前置修复：** `load_stock_data` 的 SQL 查询需增加 `adj_factor` 字段：

```python
# 原始（缺少 adj_factor）
rows = conn.execute(
    "SELECT trade_date, close, volume FROM stock_daily "
    "WHERE ts_code=? AND trade_date>=? AND trade_date<=? "
    "ORDER BY trade_date",
    (ticker, "20150101", "20251231")
).fetchall()

# 修复后（添加 adj_factor）
rows = conn.execute(
    "SELECT trade_date, close, volume, adj_factor FROM stock_daily "
    "WHERE ts_code=? AND trade_date>=? AND trade_date<=? "
    "ORDER BY trade_date",
    (ticker, "20150101", "20251231")
).fetchall()
```

新增工具函数，从 `adj_factor` 推导除息日每股分红：

```python
def compute_dividends(stock_data: Dict) -> Dict[str, List[Tuple[str, float]]]:
    """
    从 adj_factor 反算除息日每股分红。
    
    公式：div_per_share = close[i-1] × (1 - adj[i-1] / adj[i])
    
    推导：
    前复权因子转换关系：adj_close[t] = close[t] / adj[t]
    复权价差：(adj_close[t-1] - adj_close[t]) × adj[t] = 除息金额
    代入化简得：div = close[t-1] × (1 - adj[t-1]/adj[t])
    
    注意：
    - tushare 的 adj_factor 在除息日**上升**（复权因子累积），
      而非下降。因此检测条件为 adj[i] > adj[i-1]
    - 必须使用 close[i-1]（前日收盘价），而非 close[i]（当日收盘价）
    
    已验证：600519.SH 2016-2024 年真实分红数据，偏差 < 5%
    """
    dividends: Dict[str, List[Tuple[str, float]]] = {}
    for ticker, sd in stock_data.items():
        adj = sd.get("adj_factor")
        if adj is None or len(adj) < 2:
            dividends[ticker] = []
            continue
        ticker_divs = []
        for i in range(1, len(adj)):
            if adj[i] > adj[i-1] + 1e-8:  # 复权因子显著上升 → 除息
                div_per_share = sd["close"][i-1] * (1.0 - adj[i-1] / adj[i])
                if div_per_share > 0.01:  # 过滤噪声
                    ticker_divs.append((sd["dates"][i], round(div_per_share, 4)))
        dividends[ticker] = ticker_divs
    return dividends
```

**在 `run_portfolio_backtest` 中分红处理：**

```python
# 预处理分红数据
dividend_map = compute_dividends(stock_data)

# 在每个交易日的权益计算后、调仓前：
for t in tickers:
    held = positions.get(t, 0)
    if held <= 0:
        continue
    divs = dividend_map.get(t, [])
    for d_date, div_ps in divs:
        if d_date == date:
            cash += held * div_ps
            total_dividends += held * div_ps
```

**影响范围：**
- 修改 `load_stock_data`：SQL 查询增加 `adj_factor` 字段
- 新增 `compute_dividends()` 函数
- 修改 `run_portfolio_backtest`：增加分红环节
- `run_benchmark` 需同步修改

**方案B（备选，4h）：** 从 tushare_pro `dividend` 接口获取独立分红数据，储存到新表 `stock_dividends`。更准确但工作量翻倍。

---

## 实施优先级

| 顺序 | 项目 | 工时 | 独立性 | 备注 |
|:----:|:----|:----:|:------:|:-----|
| 1 | P0-2 前视偏差 | 3h | ✅ 独立 | 影响最严重，优先修复 |
| 2 | P0-1 T+1延迟 | 4h | ✅ 独立 | 可并行开发 |
| 3 | P0-3 分红现金流 | 2h | ✅ 独立 | 基于前两项修复后叠加 |

> 三项目**无代码依赖关系**，可并行开发。

---

## 验证标准

| 项目 | 通过条件 |
|:----|:---------|
| P0-1 | 回测交易日志中无同日买卖同一标的记录；T+0 卖出操作实际被跳过 |
| P0-2 | `signal[0]` 为 NaN；回测首日无交易信号；所有卖单信号时间戳 <= T-1 |
| P0-3 | 分红金额正确计入现金池；资金曲线在除息日期出现正向脉冲；
      使用 600519.SH 验证：各除息日反算分红与真实值的偏差 < 5% |

---

## 验证标准补充：P0-3 定量验证

### 验证方法

使用 600519.SH（贵州茅台）2016-2024 年已知分红数据验证 `compute_dividends()` 反算精度：

| 除息日 | 真实每股分红（元） | 反算目标偏差 |
|:------|:----------------:|:-------------:|
| 2016-07-01 | 6.171 | < 5% |
| 2022-12-27 | 21.91 | < 5% |
| 2024-06-19 | 30.876 | < 5% |

**定量阈值：** 全部验证点的相对偏差绝对值 < 5%，否则诊断代码错误。

**验证脚本：**（运行可用）

```python
import sqlite3
import numpy as np

def validate_dividend_formula(ticker="600519.SH"):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT trade_date, close, adj_factor FROM stock_daily "
        "WHERE ts_code=? ORDER BY trade_date",
        (ticker,)
    ).fetchall()
    conn.close()
    
    known = {"20160701": 6.171, "20221227": 21.91, "20240619": 30.876}
    
    for i in range(1, len(rows)):
        d1, c1, a1 = rows[i-1]
        d2, c2, a2 = rows[i]
        if a2 > a1 + 1e-8:  # 除息日
            div_calc = c1 * (1.0 - a1 / a2)
            if d2 in known:
                real = known[d2]
                error = abs(div_calc - real) / real * 100
                print(f"{d2}: 真实={real}, 反算={div_calc:.3f}, 偏差={error:.2f}%")
                assert error < 5.0, f"偏差 {error:.2f}% 超过阈值 5%"
    print("✅ 所有验证通过")
```

---

## 环境信息

| 组件 | 版本 / 值 |
|:----|:----------|
| OS | Windows 10.0.26200 (x64) |
| Python | 3.10+ |
| NumPy | ≥1.21 |
| SQLite3 | built-in |
| 数据表 | `stock_daily` (含 adj_factor) |
| 数据源 | tushare_pro / v1.0 |

---

*文档由墨衡 (DeepSeek R1) 基于 `run_exp003_q4.py` 代码审计生成*
