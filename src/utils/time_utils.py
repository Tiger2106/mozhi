"""time_utils — 时间抽象层（P1-6 / P0-MH-2）

提供统一时间获取接口：
  - TimeProvider：生产环境使用系统时钟
  - FixedTimeProvider：测试环境可注入固定时间

所有模块通过此模块获取时间，不直接调用 datetime.now()。

交易窗口定义：
  - 晨间窗口：08:01 - 08:59（含左不含右）
  - 午间窗口：12:01 - 12:59（含左不含右）

Author: moheng
Created: 2026-05-12
"""

from datetime import datetime, date, time, timedelta, timezone
from typing import Optional
import logging
from src.config import SHANGHAI_TZ

logger = logging.getLogger("paper_trade.time_utils")

# ============================================================
# 常量
# ============================================================

TZ_SHANGHAI = SHANGHAI_TZ

# 晨间交易窗口 08:01 ~ 08:59
MORNING_WINDOW_START = time(8, 1)
MORNING_WINDOW_END = time(9, 0)

# 午间交易窗口 12:01 ~ 12:59
MIDDAY_WINDOW_START = time(12, 1)
MIDDAY_WINDOW_END = time(13, 0)

TRADING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})  # Mon=0 ... Fri=4


# ============================================================
# TimeProvider
# ============================================================

class TimeProvider:
    """生产环境时间提供者——返回系统时钟的当前时间。

    所有时间相关模块通过此类获取时间，便于测试时替换。
    """

    def now(self) -> datetime:
        """返回当前时间（+08:00 时区aware）。"""
        return datetime.now(TZ_SHANGHAI)

    def today(self) -> date:
        """返回今天日期（+08:00 时区aware）。"""
        return self.now().date()

    def is_trading_window(self, dt: Optional[datetime] = None) -> bool:
        """判断当前是否在交易窗口内。

        交易窗口定义：
          - 晨间：08:01 ≤ time < 09:00 且在交易日
          - 午间：12:01 ≤ time < 13:00 且在交易日

        参数：
            dt — 待判断的时间，None 表示当前时间

        返回：
            True 若在任一交易窗口期内且当天为交易日
        """
        now = dt if dt is not None else self.now()
        t = now.time()
        # 先判断时间范围
        in_morning = MORNING_WINDOW_START <= t < MORNING_WINDOW_END
        in_midday = MIDDAY_WINDOW_START <= t < MIDDAY_WINDOW_END
        if not in_morning and not in_midday:
            return False
        # 再判断交易日
        return self.is_trading_day(now.date())

    def is_trading_day(self, d: date) -> bool:
        """判断某天是否为交易日——周一~周五。

        参数：
            d — 待判断的日期

        返回：
            True 若为周一~周五

        注意：
            MVP 暂不引入节假日逻辑，仅做周一~周五判断。
        """
        return d.weekday() in TRADING_WEEKDAYS

    def get_trading_weekday(self, dt: Optional[datetime] = None) -> int:
        """获取当前交易日对应的星期数（0=Mon, 1=Tue, ..., 4=Fri）。

        若当前在交易窗口内，返回当天星期数；
        否则返回最近一个交易日的星期数。

        参数：
            dt — 待判断的时间，None 表示当前时间
        """
        trading_date = self.get_trading_date(dt)
        return trading_date.weekday()

    def get_trading_date(self, dt: Optional[datetime] = None) -> date:
        """获取交易日期——若dt在交易窗口内，返回dt当天；否则返回最近一个交易日。

        信号有效期绑定到交易日期而非自然日期。
        """
        now = dt if dt is not None else self.now()
        # 如果正在交易窗口内，返回当天
        if self.is_trading_window(now):
            return now.date()
        # 如果在晨间窗口结束之后但没开午盘，仍属当天信号
        if now.time() >= MORNING_WINDOW_END and now.time() < MIDDAY_WINDOW_START:
            return now.date()
        # 如果在午间窗口结束之后，返回当天
        if now.time() >= MIDDAY_WINDOW_END:
            return now.date()
        # 如果在08:01之前，返回上一个交易日
        return self._prev_trading_day(now.date())

    def _prev_trading_day(self, d: date) -> date:
        """获取前一个交易日。"""
        cursor = d - timedelta(days=1)
        while cursor.weekday() not in TRADING_WEEKDAYS:
            cursor -= timedelta(days=1)
        return cursor


# ============================================================
# FixedTimeProvider
# ============================================================

class FixedTimeProvider(TimeProvider):
    """测试用固定时间提供者——构造函数接收固定 datetime，返回固定值。

    使用方式：
        from paper_trade import time_utils
        fixed = FixedTimeProvider(datetime(2026, 5, 12, 8, 30, tzinfo=TZ_SHANGHAI))
        time_utils.set_time_provider(fixed)
        # 或者直接替换模块变量
        time_utils.time_provider = fixed
    """

    def __init__(self, fixed_dt: Optional[datetime] = None):
        if fixed_dt is not None and fixed_dt.tzinfo is None:
            fixed_dt = fixed_dt.replace(tzinfo=TZ_SHANGHAI)
        self._fixed = fixed_dt or datetime(2026, 1, 1, 8, 30, tzinfo=TZ_SHANGHAI)

    def set_fixed_time(self, dt: datetime) -> None:
        """更新固定时间（用于测试中模拟时间推移）。"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_SHANGHAI)
        self._fixed = dt

    def now(self) -> datetime:
        return self._fixed

    def today(self) -> date:
        return self._fixed.date()


# ============================================================
# 默认全局单例
# ============================================================

time_provider: TimeProvider = TimeProvider()

# 注册状态标记
_provider_registered: bool = False


# ============================================================
# 全局时间源注册
# ============================================================

def set_time_provider(provider: TimeProvider) -> None:
    """注册自定义时间提供者。

    主要用于测试环境：注入 FixedTimeProvider 替代系统时钟，
    使所有 time_utils.now() 调用返回可控时间。

    生产环境不建议调用此函数，使用默认 TimeProvider() 即可。

    参数：
        provider — 实现 TimeProvider 接口的实例

    注意：
        - 覆盖已注册的 provider 会记录 warning 日志
        - 此操作不可逆（无 unset 机制），测试结束后应重新启动进程
    """
    global time_provider, _provider_registered
    if _provider_registered:
        logger.warning("Overwriting existing TimeProvider: %s -> %s",
                       type(time_provider).__name__, type(provider).__name__)
    time_provider = provider
    _provider_registered = True
    logger.info("Set TimeProvider: %s", type(provider).__name__)


def get_time_provider() -> TimeProvider:
    """获取当前使用的时间提供者。"""
    return time_provider


# ============================================================
# 便捷函数（模块内各组件通过此接口获取时间）
# ============================================================

def now() -> datetime:
    """获取当前时间（+08:00）。

    等效于 time_provider.now()，提供了更简洁的调用方式。
    """
    return time_provider.now()


def today() -> date:
    """获取今天日期。"""
    return time_provider.today()


def is_trading_window(dt: Optional[datetime] = None) -> bool:
    """判断当前是否在交易窗口内。

    交易窗口定义：
      - 晨间：08:01 ≤ time < 09:00 且在交易日
      - 午间：12:01 ≤ time < 13:00 且在交易日
    """
    return time_provider.is_trading_window(dt)


def is_trading_day(d: date) -> bool:
    """判断是否为交易日（周一~周五）。"""
    return time_provider.is_trading_day(d)


def get_trading_weekday(dt: Optional[datetime] = None) -> int:
    """获取当前交易日对应的星期数（0=Mon, 1=Tue, ..., 4=Fri）。"""
    return time_provider.get_trading_weekday(dt)


def get_trading_date(dt: Optional[datetime] = None) -> date:
    """获取交易日期。"""
    return time_provider.get_trading_date(dt)
