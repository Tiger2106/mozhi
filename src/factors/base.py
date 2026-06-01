"""
因子基类定义 — FactorBase 抽象类 + SuspensionHandler 停牌处理工具

所有因子子类继承 FactorBase，实现 calculate(df) 方法即可。

Author: 墨衡
Created: 2026-05-30T10:54:00+08:00
Version: v1
"""

from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import logging

from src.db.connection import DatabaseManager, get_manager

logger = logging.getLogger(__name__)


class SuspensionHandler:
    """停牌处理工具。

    处理规则（§4.0 / §3.1.4.2）：
    - null_reason == 'SUSPENDED'：因子值 = None，不参与IC计算
    - null_reason == 'MISSING'：因子值 = None（数据缺失，不参与回测）
    - 窗口内停牌 > 50%：排除该截面样本
    - 窗口内停牌 ≤ 50%：跳过停牌日，用实际交易日计算
    - 连续停牌导致回看窗口无任何有效价格：排除
    - 退化逻辑：volume=0 AND amount=0 视为停牌（当 null_reason 未设置时）

    返回时附带 mask 信息（哪些股票被停牌/缺失排除）。
    """

    @staticmethod
    def is_suspended_row(row: pd.Series) -> bool:
        """判断单行是否停牌或缺失。

        优先使用 null_reason 字段；退化使用 volume=0 AND amount=0。
        """
        null_reason = row.get('null_reason')
        if null_reason == 'SUSPENDED':
            return True
        if null_reason == 'MISSING':
            return True
        # 退化逻辑：null_reason 未设置时 volume=0 AND amount=0 视为停牌
        if null_reason is None or pd.isna(null_reason):
            vol = row.get('volume', np.nan)
            amt = row.get('amount', np.nan)
            if not pd.isna(vol) and not pd.isna(amt):
                if vol == 0 and amt == 0:
                    return True
        return False

    @staticmethod
    def get_suspension_mask(
        df: pd.DataFrame,
        date: str,
        lookback: int,
        max_ratio: float = 0.5,
    ) -> pd.Series:
        """计算每只股票的排除掩码（True=需排除）。

        参数：
            df: 包含 ts_code, trade_date, null_reason, volume, amount 等字段的 DataFrame
            date: 截面日期 (YYYYMMDD)
            lookback: 回看窗口长度（交易日数）
            max_ratio: 停牌占比上限（默认 50%），超过则排除

        返回：
            pd.Series, index=ts_code, values=True=排除, False=保留
        """
        mask = pd.Series(dtype=bool)

        for ts_code, grp in df.groupby('ts_code'):
            grp = grp.sort_values('trade_date').reset_index(drop=True)
            # 获取回看窗口数据（含当日，足够历史）
            window = grp[grp['trade_date'] <= date].tail(lookback + 1)

            if len(window) == 0:
                mask[ts_code] = True
                continue

            # 判断截面当日是否停牌
            today_rows = window[window['trade_date'] == date]
            if len(today_rows) > 0:
                if SuspensionHandler.is_suspended_row(today_rows.iloc[0]):
                    mask[ts_code] = True
                    continue

            # 统计窗口内（不含当日）的停牌比例
            historical = window[window['trade_date'] < date]
            if len(historical) == 0:
                mask[ts_code] = True
                continue

            suspended_count = sum(
                SuspensionHandler.is_suspended_row(row)
                for _, row in historical.iterrows()
            )

            # 窗口内停牌 > 50% → 排除
            ratio = suspended_count / len(historical)
            if ratio > max_ratio:
                mask[ts_code] = True
                continue

            # 连续停牌无有效价格 → 排除
            if suspended_count == len(historical):
                mask[ts_code] = True
                continue

            mask[ts_code] = False

        return mask

    @staticmethod
    def filter_valid_data(df_stock: pd.DataFrame, date: str, lookback: int) -> pd.DataFrame:
        """过滤出有效（非停牌、非缺失）的交易数据。

        返回按 trade_date 正序排列的 DataFrame，仅含有效交易日。
        """
        df = df_stock.sort_values('trade_date').reset_index(drop=True)
        window = df[df['trade_date'] <= date].tail(lookback + 1)
        valid_mask = ~window.apply(SuspensionHandler.is_suspended_row, axis=1)
        return window[valid_mask].reset_index(drop=True)


class FactorBase(ABC):
    """因子基类。

    所有因子子类必须继承此类并实现 calculate(df) 方法，框架自动处理：
    - 数据加载（从 a50_daily_ohlcv 表）
    - 成分股过滤（基于 a50_universe 表）
    - 停牌/缺失数据排除

    用法：
        class Momentum5D(FactorBase):
            def __init__(self, db_manager=None):
                super().__init__(db_manager=db_manager, name='momentum_5d', lookback=5)

            def calculate(self, df):
                # df 是该股票的有效历史数据
                return df['adj_close_b'].iloc[-1] / df['adj_close_b'].iloc[0] - 1

    返回值格式（compute 方法）：
        [
            {"ts_code": "600000.SH", "value": 0.023, "mask": False},
            {"ts_code": "600519.SH", "value": None,   "mask": True},   # 停牌排除
            ...
        ]
    """

    # SQL 单次查询行数安全上限
    # A50 面板：~50 只股票 × ~260 个交易日 = 13,000 行
    # 设 50,000 为安全余量，防止异常查询内存膨胀
    MAX_LOAD_ROWS: int = 50000

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        name: Optional[str] = None,
        lookback: int = 20,
    ):
        self.db_manager = db_manager or get_manager()
        self.name = name or self.__class__.__name__.lower()
        self.lookback = lookback

    def compute(self, date: str) -> list[dict]:
        """计算截面上所有成分股的因子值。

        参数：
            date: 截面日期 (YYYYMMDD)

        返回：
            list[dict]: [{"ts_code": ..., "value": (float|None), "mask": (bool)}, ...]
                - value: 因子值（停牌/缺失为 None）
                - mask: True=该股票被排除（不参与 IC 计算）
        """
        # 1. 加载面板数据
        df = self._load_data(date)
        if df is None or len(df) == 0:
            logger.warning("[%s] No data loaded for date=%s", self.name, date)
            return []

        # 2. 获取当日成分股列表
        universe = self._get_universe(date)
        if not universe:
            logger.warning("[%s] Empty universe for date=%s", self.name, date)
            return []

        # 3. 仅保留成分股数据
        universe_set = set(universe)
        df = df[df['ts_code'].isin(universe_set)].copy()
        if len(df) == 0:
            logger.warning("[%s] No universe stocks in OHLCV data for %s", self.name, date)
            return []

        # 4. 计算停牌排除掩码
        mask = SuspensionHandler.get_suspension_mask(df, date, self.lookback)

        # 5. 逐只股票计算因子值
        results = []
        for ts_code in universe:
            if ts_code not in mask.index or mask[ts_code]:
                results.append({'ts_code': ts_code, 'value': None, 'mask': True})
                continue

            stock_df = df[df['ts_code'] == ts_code]

            # 获取有效交易数据（跳过停牌日）
            valid_data = SuspensionHandler.filter_valid_data(stock_df, date, self.lookback)
            if len(valid_data) == 0:
                results.append({'ts_code': ts_code, 'value': None, 'mask': True})
                continue

            try:
                value = self.calculate(valid_data)
                # NaN → None
                if isinstance(value, float) and np.isnan(value):
                    value = None
                results.append({
                    'ts_code': ts_code,
                    'value': value,
                    'mask': False,
                })
            except Exception as e:
                logger.error("[%s] compute error for %s on %s: %s",
                             self.name, ts_code, date, e)
                results.append({'ts_code': ts_code, 'value': None, 'mask': True})

        return results

    @abstractmethod
    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算单只股票的因子值。

        子类必须实现此方法。框架会在调用前完成：
        - 停牌/缺失日过滤
        - 按 trade_date 正序排列
        - 回看窗口截取

        参数：
            df: 该股票的有效历史数据 DataFrame（列包含：
                ts_code, trade_date, adj_close_b, adj_open_b,
                adj_high_b, adj_low_b, adj_pre_close_b,
                volume, amount, turnover_rate, pe, pb, null_reason 等）

        返回：
            float or None: 因子值（None 表示无法计算）
        """
        ...

    # ── 数据加载方法 ──────────────────────────────────

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """从 a50_daily_ohlcv 表加载历史面板数据。

        加载范围：从 date 向前推 max(lookback*3, 120) 个日历日，
        确保有足够历史数据（即使有长假/停牌）。
        """
        buffer_calendar = max(self.lookback * 3, 120)
        try:
            dt = datetime.strptime(date, '%Y%m%d')
            start_dt = dt - timedelta(days=buffer_calendar)
            start_date = start_dt.strftime('%Y%m%d')
        except ValueError:
            logger.error("[%s] Invalid date format: %s", self.name, date)
            return None

        conn = self.db_manager.get()
        try:
            query = """
                SELECT ts_code, trade_date,
                       adj_close_b, adj_open_b, adj_high_b, adj_low_b,
                       close, pre_close,
                       volume, amount, turnover_rate,
                       pe, pb, adj_factor,
                       total_share, float_share,
                       null_reason
                FROM a50_daily_ohlcv
                WHERE trade_date >= ? AND trade_date <= ?
                ORDER BY ts_code, trade_date
                LIMIT ?
            """
            df = pd.read_sql_query(
                query, conn,
                params=(start_date, date, self.MAX_LOAD_ROWS),
            )
            return df
        except Exception as e:
            logger.error("[%s] _load_data error for %s: %s", self.name, date, e)
            return None
        finally:
            self.db_manager.put(conn)

    def _get_universe(self, date: str) -> list[str]:
        """获取指定日期的成分股列表（消除前视偏差）。"""
        conn = self.db_manager.get()
        try:
            query = """
                SELECT ts_code FROM a50_universe
                WHERE in_date <= ? AND (out_date IS NULL OR out_date > ?)
                ORDER BY ts_code
            """
            rows = conn.execute(query, (date, date)).fetchall()
            return [r[0] for r in rows]
        except Exception as e:
            logger.error("[%s] _get_universe error for %s: %s", self.name, date, e)
            return []
        finally:
            self.db_manager.put(conn)

    def __repr__(self) -> str:
        return f"<FactorBase name={self.name} lookback={self.lookback}>"
