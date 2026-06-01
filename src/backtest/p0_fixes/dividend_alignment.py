"""
P0-FIX-003: 分红现金流对齐
===========================
A股分红（现金红利/送转股）对回测的影响：
1. 除息日（XD）：股价下调，但股东获得现金红利
2. 除权日（XR）：股价下调，但股东持有的股数增加
3. 复权因子（adj_factor）：用于复权价格，但需单独处理现金流

当前问题：
- 原 backtest 使用除权后的 close 价格，但复权因子未正确应用于现金流计算
- 分红日的现金增量未计入资金曲线

修复方案（v1.1）：
1. compute_dividend_cash() 改为正确的 `shares_held * cash_dividend_per_share`
2. detect_dividends_from_adj_factor() 仅做事件检测，不从 adj_factor 推算金额
3. 实际每股分红金额需从外部数据源获取（Tushare/akShare）
4. 引擎集成（在除息日向 cash 注入分红）将在后续 Stage 实现

作者: moheng
版本: v1.1 (P0-3 Stage 1 — 公式修正)
"""
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class DividendEvent:
    """分红事件

    注：cash_dividend_per_share 不由 adj_factor 推算，
    需从外部数据源（Tushare/akShare）获取。
    detect_dividends_from_adj_factor() 返回的事件中
    cash_dividend_per_share 为 0，等待外部数据填充。
    """
    date: str
    symbol: str
    cash_dividend_per_share: float = 0.0  # 每股现金分红（元）— 需从外部数据源获取
    stock_dividend_per_10: float = 0.0    # 每10股送转股数
    pre_adj_factor: float = 1.0           # 除息前复权因子
    post_adj_factor: float = 1.0          # 除息后复权因子


def detect_dividends_from_adj_factor(
    adj_factors: List[float],
    dates: List[str],
    threshold: float = 0.001
) -> List[DividendEvent]:
    """从复权因子序列检测分红事件（仅事件检测，不从adj_factor推算金额）

    当 adj_factor 发生较大变化时，通常对应分红/除权事件。
    仅检测事件发生的时间点，不计算分红金额。
    每股分红金额需从外部数据源获取（Tushare pro.dividend / akShare）。

    Args:
        adj_factors: 复权因子序列（按日期升序）
        dates: 对应日期
        threshold: 变化率阈值（默认 0.1%）

    Returns:
        检测到的分红事件列表（cash_dividend_per_share=0，待外部数据填充）
    """
    events: List[DividendEvent] = []
    for i in range(1, len(adj_factors)):
        prev = adj_factors[i - 1]
        curr = adj_factors[i]
        if prev > 0 and abs(curr / prev - 1) > threshold:
            # 复权因子变化 → 分红/复权事件
            # 仅记录事件和复权因子变化，不推算金额
            event = DividendEvent(
                date=dates[i],
                symbol="",
                cash_dividend_per_share=0.0,  # 不从 adj_factor 推算金额
                stock_dividend_per_10=0,
                pre_adj_factor=prev,
                post_adj_factor=curr,
            )
            events.append(event)
    return events


def compute_dividend_cash(dividends: List[DividendEvent],
                          shares_held: int) -> float:
    """计算分红产生的现金流入

    正确公式（P0-3 修正）：
        dividend_cash = shares_held * cash_dividend_per_share

    cash_dividend_per_share 需从外部数据源获取（Tushare/akShare），
    不由 adj_factor 推算。若 cash_dividend_per_share 为 0（未填充），
    返回 0（幂等安全）。

    Args:
        dividends: 分红事件列表（需已填充 cash_dividend_per_share）
        shares_held: 持仓股数

    Returns:
        分红现金总额
    """
    total = 0.0
    for d in dividends:
        if d.cash_dividend_per_share > 0:
            total += shares_held * d.cash_dividend_per_share
        # 若 cash_dividend_per_share == 0（未从外部数据源填充），
        # 忽略该事件（保持当前行为，非退化）
    return total
