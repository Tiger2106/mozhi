# Stage 2 P1 回归对比报告 v1.0

**审核人**: 墨萱 🔍  
**审核日期**: 2026-05-27  
**基线**: `experiments/baselines/backtest_golden_baseline_bc5f464.json`  
**P1 Commit**: `bc5f464` (已含 P1 修复，新引擎为 untracked 文件)

---

## 1. 回归对比结果: ❌ FAIL

### 1.1 核心指标对比

| 指标 | 基线 (bc5f464) | 当前引擎 | 差异 | 容差 | 判定 |
|---|---|---|---|---|---|
| total_return_pct | 20.3278% | 19.5103% | 0.8175% | <0.01% | ❌ FAIL |
| total_trades | 86 | 86 | 0 | 0 | ✅ PASS |
| win_rate_pct | 34.8837% | 3.4900% | 31.3937% | <0.01% | ❌ FAIL |
| final_equity (NAV) | 1,203,277.93 | 1,195,102.87 | 8,175.06 (0.6794%) | <0.01% | ❌ FAIL |

### 1.2 数据指纹对比

| 来源 | 数据指纹 | 数据行数 | 数据源 |
|---|---|---|---|
| 基线 | `92ca7e9b569875fc` | 1540 | `601857_SH.csv` (CSV) |
| 当前引擎 | `b4b6612ae2ffef5b` | 1540 | `market_data.db` (SQLite) |

---
**结论**: 回归对比 FAIL。当前引擎与基线之间存在显著差异，数据指纹不匹配。  
**阈值要求**: IC < 1e-6 (指标差异), NAV < 0.01% → 均未满足。

---

## 2. 差异归因分析

### 2.1 根本原因: 数据源不一致

- **基线生成路径**: `_run_golden_baseline.py` → 从 CSV 加载 → 旧引擎 `BacktestEngine.run()`
- **当前引擎路径**: `engine.py run_backtest()` → DataLayer 从 SQLite DB 加载 → 三层新引擎

即使约束和滑点相同，数据源不同也会导致:
- 部分 bar 数据存在四舍五入/精度差异
- 数据指纹不一致
- 传递到 MA 交叉计算的收盘价序列有细微差异

### 2.2 次要原因: P1 修复改变行为

即使数据源一致，P1 修复也会微调回测行为:
- **P1-2** (TieredSlippageModel): 大盘股 0.1% 与基线固定 0.1% 可对齐
- **P1-1** (涨跌停限价): 用 `prev_close` 计算明确价格边界
- **P1-3** (成交量容量): 每笔 ≤ 5% 日成交量，对 601857（高流动性大盘股）影响有限

但 `win_rate` 从 34.88% 降至 3.49% 暗示信号触发的交易盈亏计算方式不同。

---

## 3. P1 代码质量评估: ✅ PASS

### 3.1 三层分离架构 (BT-001)

```
engine/
├── engine.py          ── 主入口: run_backtest() + compare_with_baseline()
├── data_layer/        ── 数据层
│   ├── __init__.py    ── 导出 DataLayer
│   ├── loader.py      ── 数据加载 (GP-001: 一次性加载)
│   ├── contract.py    ── BacktestData 合约 (BT-004)
│   └── guard.py       ── 前视偏差检测 (P0-FIX-002)
├── calc_layer/        ── 计算层
│   ├── __init__.py    ── 导出 compute()
│   └── signals.py     ── 信号计算 (BT-003, GP-002, GP-004)
└── sim_layer/         ── 模拟层
    ├── __init__.py    ── 导出 simulate()
    ├── simulator.py   ── 模拟引擎 + P1-2 滑点模型 (BT-005/008)
    ├── constraints.py ── 约束管理器 + P1-1/P1-3 (BT-008)
    └── logger.py      ── 交易审计日志 (BT-005)
```

**合规检查**:
- ✅ 数据层 → 计算层 → 模拟层 单向依赖
- ✅ BT-001: 三层职责分离清晰
- ✅ GP-001: DataLayer 一次性加载保护
- ✅ GP-004: ComputeEngine 固定种子 seed=42

### 3.2 P1-1: 涨跌停板约束

**实现**: `constraints.py` 中:
- `get_limit_prices(prev_close, limit_ratio)` → 计算明确的价格边界
  - `limit_up = round(prev_close * (1 + 0.10), 2)`
  - `limit_down = round(prev_close * (1 - 0.10), 2)`
- `check_limit_up_by_price()` / `check_limit_down_by_price()` → 价格比较判定
- 支持主板 (±10%), 科创/创业板 (±20%), ST (±5%)

**质量评定**: ✅ 通过
- `prev_close` 而非 `bar.close` 作为基准 (正确)
- 保留 2 位小数 (A 股价格精度)
- 买入/卖出约束语义正确分离

### 3.3 P1-2: 滑点模型

**实现**: `simulator.py`:
- `BaseSlippageModel` — 基础滑点 + 成交量因子
- `TieredSlippageModel` — 继承基类，按市值分档
  - `market_cap >= 100亿` → 大盘股 0.1%
  - `market_cap < 100亿` → 小盘股 0.3%
  - 未提供 `market_cap` 时默认大盘股 0.1%
- 成交量因子: 当 `volume_pct > 2%` 时放大滑点 (max 2x)

**质量评定**: ✅ 通过
- 可扩展接口 (继承/参数化)
- 成交量因子防止大单过度影响
- 默认值与基线对齐 (0.1%)

### 3.4 P1-3: 成交量容量约束

**实现**: `constraints.py`:
- `check_volume_capacity(requested_qty, bar_volume, max_pct=5%)`
- 返回 `(capped_qty, ConstraintResult)`
  - `requested_qty <= allowed` → 不截断
  - `requested_qty > allowed` → 截断至 `int(bar_volume * 5%)`

**质量评定**: ✅ 通过
- 安全截断保证数量非负 (`max(0, capped)`)
- 约束信息可追溯 (blocked_by + detail)
- 默认 5% 合理

### 3.5 BT-008 约束优先级

```
停牌 → 涨跌停 → 成交量容量 → T+1
```

实际在 `ConstraintManager.check_buy()` / `check_sell()` 中实现。

**质量评定**: ✅ 通过
- 优先级链正确
- `check_buy` (买入受约束: 停牌 > 涨停)
- `check_sell` (卖出受约束: 停牌 > 跌停 > T+1)

### 3.6 审计日志 (BT-005)

`TradeLogger` 实现 JSON Lines 格式日志，按日期分片。
每条交易记录含: trade_id, symbol, direction, price, quantity, fee, pnl, status 等。

**质量评定**: ✅ 通过

---

## 4. 风险与建议

### 4.1 当前风险: 高

| 风险 | 等级 | 描述 |
|---|---|---|
| 数据源不统一 | 🔴 高 | 基线 CSV vs 新引擎 DB，需统一 |
| 回归基线未更新 | 🟡 中 | bc5f464 已含 P1 fix 但基线未重新生成 |
| win_rate 差异大 | 🟡 中 | 34.88% → 3.49%，需确认是否由数据差异导致 |
| 分红对齐未实现 | 🟢 低 | `TODO(P1): 除息日现金流调整逻辑待实现` |

### 4.2 建议

1. **统一数据源**: 新引擎 DataLayer 锁定使用 SQLite DB，CSV 路径废弃
2. **重新生成黄金基线**: P1 修复合入后，用新引擎重新生成基线
3. **新增 GP-003 回归用例**: 将数据指纹校验纳入回归流程
4. **对比交易级日志**: 逐笔对比基线与新引擎的 trade log，定位 win_rate 差异根因
5. **补充 unit test**: P1-1/P1-2/P1-3 各模块的单测

---

## 5. 执行记录

```python
# 执行命令 (2026-05-27 19:37)
r = run_backtest(symbol="601857.SH", start="20200101", end="20260515",
                 strategy_type="ma_cross", initial_capital=1_000_000)

# 基线: experiments/baselines/backtest_golden_baseline_bc5f464.json
```

**审核签名**: 墨萱 🔍  
**审核版本**: v1.0  
**下一步**: 墨衡修复数据源统一 + 重新生成基线 → Stage 2 复测
