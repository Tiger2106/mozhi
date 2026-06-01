"""
约束管理器 (BT-008) — 停牌 > 涨跌停 > 成交量容量 > T+1
========================================================
BT-008 约束优先级:
    1. 停牌检查（volume == 0 → 无法交易）
    2. 涨跌停检查（涨跌达到限制 → 无法交易）
    3. 交易量容量约束（每笔不超过日成交量的比例）
    4. T+1 检查（当日买入 → 次日才可卖出）

实现:
    - 停牌 + 涨跌停: 基于 BacktestBar 的量价判断
    - 涨跌停价格: 用 prev_close 计算 ±10% 限价（主板）
    - T+1: 挂单队列机制，买入记录缓存
    - P0-FIX-001: 分时闸门 + 挂单自动重试

用法:
    from engine.sim_layer.constraints import ConstraintManager
    mgr = ConstraintManager()
    can_buy, reason = mgr.check_buy(bar, prev_close)
    can_sell, reason = mgr.check_sell(bar, prev_close, buy_date, sell_date)
    qty_capped = mgr.check_volume_capacity(requested_qty, bar_volume, volume_pct)

P1 修复:
    - P1-1: 涨跌停板约束增强（从 prev_close 计算明确的价格边界）
    - P1-3: 交易量容量约束（每笔不超过日成交量的 volume_capacity_pct）

作者: moheng
版本: v1.1
"""
from typing import Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from ...contracts.backtest_data_contract import BacktestBar


# BT-008 约束常量
LIMIT_UP_RATIO_MAIN = 0.10     # 主板 ±10%
LIMIT_UP_RATIO_GEM = 0.20      # 科创/创业板 ±20%
LIMIT_UP_RATIO_ST = 0.05       # ST ±5%

# P1-3: 交易量容量默认值
VOLUME_CAPACITY_PCT = 0.05     # 每笔不超过日成交量 5%


@dataclass
class ConstraintResult:
    """约束检查结果"""
    can_trade: bool              # 是否允许交易
    blocked_by: str              # 被哪个约束阻挡（空字符串=通过）
    detail: str = ""             # 详细信息


class ConstraintManager:
    """约束管理器 (BT-008)

    维护约束判定逻辑，供 ConstraintAwareExecutor 调用。
    """

    # P0-FIX-001: T+1 挂单缓存
    _buy_records: dict = field(default_factory=lambda: defaultdict(list))
    _pending_queue: dict = field(default_factory=lambda: defaultdict(list))

    @staticmethod
    def check_suspended(bar: BacktestBar) -> ConstraintResult:
        """BT-008 Level 1: 停牌检查

        停牌判定标准：当日成交量为 0 或收盘价为 0。
        """
        if bar.volume == 0 or bar.close == 0:
            return ConstraintResult(
                can_trade=False,
                blocked_by="SUSPENSION",
                detail=f"停牌: {bar.symbol} @ {bar.date}, volume={bar.volume}",
            )
        return ConstraintResult(can_trade=True, blocked_by="")

    @staticmethod
    def get_limit_prices(prev_close: float,
                         limit_ratio: float = LIMIT_UP_RATIO_MAIN) -> Tuple[float, float]:
        """P1-1: 从 prev_close 计算涨跌停限价

        Args:
            prev_close: 前收盘价
            limit_ratio: 涨跌停比例（主板 0.10, 科创/创业板 0.20, ST 0.05）

        Returns:
            (limit_up_price, limit_down_price): 涨停价、跌停价

        计算规则:
            涨停价 = prev_close * (1 + limit_ratio)
            跌停价 = prev_close * (1 - limit_ratio)
            保留 2 位小数（A 股价格最小变动单位 0.01 元）
        """
        limit_up = round(prev_close * (1 + limit_ratio), 2)
        limit_down = round(prev_close * (1 - limit_ratio), 2)
        return limit_up, limit_down

    @staticmethod
    def check_limit_up_by_price(exec_price: float, prev_close: float,
                                limit_ratio: float = LIMIT_UP_RATIO_MAIN) -> ConstraintResult:
        """P1-1 (改进): 涨停检查 — 基于执行价 vs 涨停限价

        P1-1 修复说明:
            原实现用 bar.close 与 prev_close 比较涨跌幅百分比。
            P1-1 改为: 从 prev_close 计算明确的价格边界（涨停价/跌停价），
            再检查执行价是否触及涨停价。

        涨停判定：exec_price >= limit_up_price → 涨停阻止买入
        买入时：涨停阻止买入，跌停不阻止买入
        """
        if prev_close <= 0:
            return ConstraintResult(can_trade=True, blocked_by="")
        limit_up, _ = ConstraintManager.get_limit_prices(prev_close, limit_ratio)
        if exec_price >= limit_up:
            return ConstraintResult(
                can_trade=False,
                blocked_by="LIMIT_UP",
                detail=f"涨停: exec_price={exec_price:.2f} >= limit_up={limit_up:.2f} (prev_close={prev_close:.2f}) @ {limit_ratio:.0%}",
            )
        return ConstraintResult(can_trade=True, blocked_by="")

    @staticmethod
    def check_limit_down_by_price(exec_price: float, prev_close: float,
                                  limit_ratio: float = LIMIT_UP_RATIO_MAIN) -> ConstraintResult:
        """P1-1 (改进): 跌停检查 — 基于执行价 vs 跌停限价

        跌停判定：exec_price <= limit_down_price → 跌停阻止卖出
        卖出时：跌停阻止卖出，涨停不阻止卖出
        """
        if prev_close <= 0:
            return ConstraintResult(can_trade=True, blocked_by="")
        _, limit_down = ConstraintManager.get_limit_prices(prev_close, limit_ratio)
        if exec_price <= limit_down:
            return ConstraintResult(
                can_trade=False,
                blocked_by="LIMIT_DOWN",
                detail=f"跌停: exec_price={exec_price:.2f} <= limit_down={limit_down:.2f} (prev_close={prev_close:.2f}) @ {limit_ratio:.0%}",
            )
        return ConstraintResult(can_trade=True, blocked_by="")

    @staticmethod
    def check_limit_up(bar: BacktestBar, prev_close: float,
                       limit_ratio: float = LIMIT_UP_RATIO_MAIN) -> ConstraintResult:
        """BT-008 Level 2: 涨停检查（兼容旧接口 — 内部委托给 check_limit_up_by_price）

        P1-1 修复：使用 prev_close 计算涨停价，用 bar.open 作为执行价判断。

        涨停判定：bar.open >= limit_up_price → 涨停阻止买入
        买入时：涨停阻止买入，跌停不阻止买入
        """
        return ConstraintManager.check_limit_up_by_price(
            bar.open, prev_close, limit_ratio,
        )

    @staticmethod
    def check_limit_down(bar: BacktestBar, prev_close: float,
                         limit_ratio: float = LIMIT_UP_RATIO_MAIN) -> ConstraintResult:
        """BT-008 Level 2: 跌停检查（兼容旧接口 — 内部委托给 check_limit_down_by_price）

        P1-1 修复：使用 prev_close 计算跌停价，用 bar.open 作为执行价判断。

        跌停判定：bar.open <= limit_down_price → 跌停阻止卖出
        卖出时：跌停阻止卖出，涨停不阻止卖出
        """
        return ConstraintManager.check_limit_down_by_price(
            bar.open, prev_close, limit_ratio,
        )

    @staticmethod
    def check_t1(buy_date: str, sell_date: str) -> ConstraintResult:
        """BT-008 Level 3: T+1 检查 (P0-FIX-001)

        A 股 T+1 规则：当日买入的股票，当日不可卖出。
        卖出日期必须晚于买入日期（>= 1 天）。

        Args:
            buy_date: 买入日期 (YYYYMMDD)
            sell_date: 卖出日期 (YYYYMMDD)

        Returns:
            ConstraintResult: can_trade=True 表示可以卖出
        """
        if buy_date >= sell_date:
            return ConstraintResult(
                can_trade=False,
                blocked_by="T+1",
                detail=f"T+1 延迟: 买入日={buy_date}, 卖出日={sell_date}",
            )
        return ConstraintResult(can_trade=True, blocked_by="")

    @staticmethod
    def check_volume_capacity(requested_quantity: int,
                              bar_volume: float,
                              max_volume_pct: float = VOLUME_CAPACITY_PCT) -> Tuple[int, ConstraintResult]:
        """P1-3: 交易量容量约束

        确保每笔交易不超过当日成交量的一定比例（默认 5%）。
        使用 BacktestBar.volume 字段作为当日成交量。

        Args:
            requested_quantity: 请求的交易数量（股）
            bar_volume: 当日成交量（股）
            max_volume_pct: 允许的最大成交量比例（默认 0.05 = 5%）

        Returns:
            (capped_quantity, ConstraintResult):
                - capped_quantity: 容量约束后的可交易数量
                - result: 约束检查结果

        示例:
            qty, result = ConstraintManager.check_volume_capacity(100000, 500000, 0.05)
            # qty = 25000 (500000 * 0.05 = 25000 < 100000), blocked_by="VOLUME_CAP"
        """
        max_quantity = int(bar_volume * max_volume_pct)
        if requested_quantity > max_quantity:
            capped = max(0, max_quantity)
            return capped, ConstraintResult(
                can_trade=True,
                blocked_by="VOLUME_CAP",
                detail=f"成交量容量约束: 请求 {requested_quantity} > 允许 {max_quantity} (volume={bar_volume:.0f} @ {max_volume_pct:.0%}), 截断至 {capped}",
            )
        return requested_quantity, ConstraintResult(can_trade=True, blocked_by="")

    def check_buy(self, bar: BacktestBar,
                  prev_close: Optional[float] = None) -> ConstraintResult:
        """买入约束检查（BT-008 优先级: 停牌 > 涨停）

        买入受约束: 停牌、涨停
        买入不受约束: 跌停、T+1
        """
        # Level 1: 停牌
        result = self.check_suspended(bar)
        if not result.can_trade:
            return result

        # Level 2: 涨停（买入时涨停意味着买不进去）
        if prev_close is not None:
            result = self.check_limit_up(bar, prev_close)
            if not result.can_trade:
                return result

        return ConstraintResult(can_trade=True, blocked_by="")

    def check_sell(self, bar: BacktestBar,
                   prev_close: Optional[float] = None,
                   buy_date: Optional[str] = None) -> ConstraintResult:
        """卖出约束检查（BT-008 优先级: 停牌 > 跌停 > T+1）

        卖出受约束: 停牌、跌停、T+1
        """
        # Level 1: 停牌
        result = self.check_suspended(bar)
        if not result.can_trade:
            return result

        # Level 2: 跌停（卖出时跌停意味着卖不出去）
        if prev_close is not None:
            result = self.check_limit_down(bar, prev_close)
            if not result.can_trade:
                return result

        # Level 3: T+1（P0-FIX-001）
        if buy_date is not None:
            result = self.check_t1(buy_date, bar.date)
            if not result.can_trade:
                return result

        return ConstraintResult(can_trade=True, blocked_by="")


__all__ = ["ConstraintManager", "ConstraintResult",
           "LIMIT_UP_RATIO_MAIN", "LIMIT_UP_RATIO_GEM", "LIMIT_UP_RATIO_ST",
           "VOLUME_CAPACITY_PCT"]
