# P0-3 分红 adj_factor 公式修正 — 问题分析

> author: moheng (investigation)
> author: mohan (registration)
> date: 2026-05-28
> status: DRAFT → REVIEW_PENDING
> location: docs/07_research/P0-3_adj_factor_analysis.md

---

## 一、问题描述

分红复权因子（adj_factor）在回测中存在三个层面的错误：

### Bug A — compute_dividend_cash() 公式本身错误

文件：`src/backtest/p0_fixes/dividend_alignment.py`

```python
# 当前错误实现：
ratio = (d.pre_adj_factor - d.post_adj_factor) / d.pre_adj_factor  # ← 符号反转
cash = ratio * shares_held * 100  # ← 硬编码 *100，无财务含义
```

adj_factor 在除息日增大（例：601857 从 1.448 → 1.4754），因此 `pre - post` 为负值，计算出现金分红的负数。即使符号修正为 `(post - pre)/pre`，该比值只是 adj_factor 的变化率，无法得出真正的每股分红金额。正确公式需要除权前价格 P 通过 `P * ((post/pre) - 1) = D/(1+R)` 推导。

### Bug B — detect_dividends_from_adj_factor() 同源错误

同上文件：
```python
cash_dividend_per_share=round((prev - curr) / prev * 100, 4)  # ← 符号+量纲均错
```

### Bug C — P0-FIX-003 未被集成至回测引擎

`dividend_alignment.py` 虽存在于 `p0_fixes/` 目录，但没有任何 executor 调用它。

---

## 二、影响范围

| 指标 | 影响程度 | 说明 |
|:----|:--------:|:-----|
| 等权曲线 | **严重** | 分红现金从未注入 equity_curve，系统性地低估收益率 |
| 最大回撤 MDD | **严重** | 除息日价格跳变被错误记为回撤 |
| 夏普比率 | **中度** | 原始价格序列包含除息伪波动 |
| 技术指标信号 | **中度** | 短周期内影响有限，跨年信号不可比 |

长期回测（如 601857 18年）中，adj_factor 从 1.0 累积到 1.797（约 80%），未计入分红现金对总收益率造成系统性低估。

---

## 三、根因追溯

**第一层（公式层）**：compute_dividend_cash() 符号反转 + 缺失价格因子 + *100 无依据

**第二层（集成层）**：P0-FIX-003 编写后未在任何 executor 中调用

**第三层（数据使用层）**：系统存储 adj_factor 但回测引擎选择"存而不用"

---

## 四、问题陈述

分红现金流对齐逻辑（P0-FIX-003）公式错误且从未被集成到回测执行路径，导致回测期间分红现金从未注入权益曲线。

---

## 五、修复方案

### 5.1 公式修正（~15min）
- 修正 `compute_dividend_cash()` 公式，改为从外部数据源获取每股分红金额
- `detect_dividends_from_adj_factor()` 仅做事件检测，不从 adj_factor 推算金额

### 5.2 引擎集成（~20-30min）
- 在 executor 中增加分红事件检测 + 分红现金注入步骤
- 需从 Tushare / akShare 加载分红事件数据
- 除息日向 cash 余额注入 `cash_dividend_per_share × position_qty`

### 5.3 回归验证（~15-20min）
- 测试标的：601857（分红频率高、历史长）
- 验证回测前后 equity 变化与分红金额一致

---

## 六、编码技术规格（直接可编码）

### 6.1 公式修正 — dividend_alignment.py

```python
# 目标修正：
def compute_dividend_cash(shares_held: int, cash_dividend_per_share: float) -> float:
    """
    计算分红现金注入金额。
    
    Args:
        shares_held: 持仓股数
        cash_dividend_per_share: 每股现金分红（从外部数据源获取，不通过adj_factor推算）
    
    Returns:
        dividend_cash: 该笔分红现金总额
    """
    return shares_held * cash_dividend_per_share
    
# 删除原有错误的符号+*100公式
```

`detect_dividends_from_adj_factor()` 改为仅做事件检测（返回 True/False + 除息日期），不从 adj_factor 推算分红金额。

### 6.2 引擎集成 — executor

在 `execute_signals()` 中，日终结算前增加：

```python
# 伪代码：
def process_dividends(self, date, positions):
    """处理当日除息事件"""
    for symbol, pos in positions.items():
        if self.data_layer.is_dividend_date(symbol, date):
            cash_dividend = self.data_layer.get_dividend_per_share(symbol, date)
            if cash_dividend > 0:
                dividend_cash = pos.qty * cash_dividend
                self.cash += dividend_cash
                self.audit_log.append({
                    "type": "dividend",
                    "symbol": symbol,
                    "date": date,
                    "qty": pos.qty,
                    "per_share": cash_dividend,
                    "total": dividend_cash
                })
```

### 6.3 数据依赖
- 外部数据源（Tushare pro.dividend / akShare）提供 `cash_dividend_per_share`
- DataLayer 需提供 `is_dividend_date()` 和 `get_dividend_per_share()` 接口
- 若无外部数据源，退化为：不作分红现金处理（保持当前行为，非退化）
