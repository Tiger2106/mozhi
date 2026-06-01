"""
质量因子计算模块

基于财务报表/交易数据计算 6 个质量类因子（反映公司质地）：
  1. ROE（净资产收益率）：TTM净利润 / 净资产，从财务数据计算
  2. ProfitMargin（净利润率）：净利润 / 营业总收入
  3. AssetTurnover（资产周转率）：营业总收入 / 总资产
  4. Leverage（杠杆率）：总负债 / 总资产（负债率）
  5. EarningsVariability（盈利稳定性）：近20个季度ROE的标准差倒数
  6. SalesGrowth（营收增长）：同比营业总收入增长率

所有因子继承 FactorBase，注册类别为 'quality'。
因子方向统一为高值=高质量（低杠杆率反向后统一为高值=低负债=高质量）。
财务数据披露日期对齐：使用财务报表的披露日（ann_date）作为因子时间戳，
而非财报截止日（end_date），以避免前视偏差。
数据源不存在或无数据返回 None。

验收标准（IC_PIPELINE_T14_009）：
  - 6个质量因子的因子方向统一（高值=高质量），时间戳按披露日期对齐
  - 停牌股票返回 None
  - 字段缺失或财务数据表不存在时返回 None 不崩溃

Author: 墨衡
Created: 2026-05-30T11:20:00+08:00
Version: v1
"""

import logging
from typing import Optional, Any

import pandas as pd
import numpy as np

from src.factors.base import FactorBase

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 财务数据加载工具
# ═══════════════════════════════════════════════════════════════
#
# 质量因子需要从财务数据表读取季度/年度数据。
# 支持的财务表名（按优先级）：
#   1. a50_financial      — 标准化财务数据表
#   2. stock_financial    — 源表股票财务数据
#
# 财务表预期字段：
#   ts_code, end_date(财报截止日), ann_date(披露日),
#   net_profit(净利润), net_assets(净资产), total_revenue(营业总收入),
#   total_assets(总资产), total_liabilities(总负债)
#
# 若财务表不存在，所有质量因子返回 None。
# ═══════════════════════════════════════════════════════════════

FINANCIAL_TABLES_CANDIDATES = [
    "a50_financial",
    "stock_financial",
    "fin_data",
    "a50_fin_quarterly",
]


def _detect_financial_table(db_manager: Any) -> Optional[str]:
    """检测可用的财务数据表名。

    遍历候选表名，返回第一个存在的表；不存在返回 None。

    Args:
        db_manager: DatabaseManager 实例

    Returns:
        str or None: 存在的财务表名
    """
    conn = db_manager.get()
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        existing = {row[0] for row in cursor.fetchall()}
        for tbl in FINANCIAL_TABLES_CANDIDATES:
            if tbl in existing:
                return tbl
        return None
    except Exception:
        return None
    finally:
        db_manager.put(conn)


def _detect_daily_basic_fields(db_manager: Any) -> dict:
    """检测 a50_daily_ohlcv 表中是否存在 roe / profit_margin 字段。

    daily_basic 接口下发的字段有时会直接写入 ohlcv 表。
    返回 {'roe': bool, 'profit_margin': bool}。

    Returns:
        dict: 各字段是否存在
    """
    conn = db_manager.get()
    try:
        cursor = conn.execute("PRAGMA table_info(a50_daily_ohlcv)")
        columns = {row[1] for row in cursor.fetchall()}
        return {
            'roe': 'roe' in columns,
            'profit_margin': 'profit_margin' in columns,
        }
    except Exception:
        return {'roe': False, 'profit_margin': False}
    finally:
        db_manager.put(conn)


def _load_financial_data(
    db_manager: Any,
    table: str,
    date: str,
    quarters: int = 4,
) -> Optional[pd.DataFrame]:
    """从财务数据表加载季度财务数据。

    加载范围：截至 date 的前 quarters 个季度的财务数据。
    所有数据按 ts_code + ann_date 排序返回。

    Args:
        db_manager: DatabaseManager 实例
        table: 财务表名
        date: 截面日期 (YYYYMMDD)
        quarters: 所需季度数

    Returns:
        pd.DataFrame or None:
            columns: ts_code, end_date, ann_date, net_profit, net_assets,
                     total_revenue, total_assets, total_liabilities
            若表不存在或查询失败返回 None。
    """
    conn = db_manager.get()
    try:
        # 确定可查询的字段
        cursor = conn.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}

        # 构建安全的 SELECT 子句（只查询存在的字段）
        col_map = {
            'end_date': 'end_date',
            'ann_date': 'ann_date',
            'net_profit': 'net_profit',
            'net_assets': 'net_assets',
            'total_revenue': 'total_revenue',
            'total_assets': 'total_assets',
            'total_liabilities': 'total_liabilities',
        }
        select_cols = ['ts_code']
        available_cols = {}
        for key, col_name in col_map.items():
            if col_name in columns:
                select_cols.append(col_name)
                available_cols[key] = col_name

        if len(available_cols) < 2:
            logger = __import__('logging').getLogger(__name__)
            logger.warning(
                "[quality] Financial table %s has insufficient columns: %s",
                table, columns,
            )
            return None

        select_sql = ', '.join(select_cols)

        # 粗略估算：quarters 个季度 ≈ quarters * 90 天前
        # 前推 quarters * 100 天以保证覆盖，用 ann_date 过滤
        start_buffer = quarters * 100 + 30  # 额外30天缓冲

        try:
            from datetime import datetime, timedelta
            dt = datetime.strptime(date, '%Y%m%d')
            start_dt = dt - timedelta(days=start_buffer)
            start_date = start_dt.strftime('%Y%m%d')
        except ValueError:
            return None

        # 只查询 ann_date <= 截面日期的已披露数据
        # 用 ann_date 对齐避免前视偏差
        query = f"""
            SELECT {select_sql}
            FROM {table}
            WHERE ann_date <= ? AND ann_date >= ?
            ORDER BY ts_code, ann_date
        """
        df = pd.read_sql_query(query, conn, params=(date, start_date))
        return df if len(df) > 0 else None

    except Exception:
        return None
    finally:
        db_manager.put(conn)


def _load_daily_quality_fields(
    db_manager: Any,
    date: str,
    lookback: int = 20,
) -> Optional[pd.DataFrame]:
    """从 a50_daily_ohlcv 表加载日常质量相关字段。

    用于当财务数据表不存在时，尝试从日线表的 pe/pb 反算。
    加载范围从前推 lookback*3 的日历日开始。

    Returns:
        pd.DataFrame: 含 ts_code, trade_date, pe, pb 等字段，或 None
    """
    from datetime import datetime, timedelta

    conn = db_manager.get()
    try:
        buffer_calendar = max(lookback * 3, 120)
        dt = datetime.strptime(date, '%Y%m%d')
        start_dt = dt - timedelta(days=buffer_calendar)
        start_date = start_dt.strftime('%Y%m%d')

        query = """
            SELECT ts_code, trade_date, pe, pb, total_mv, circ_mv
            FROM a50_daily_ohlcv
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code, trade_date
        """
        df = pd.read_sql_query(query, conn, params=(start_date, date))
        return df if len(df) > 0 else None
    except Exception:
        return None
    finally:
        db_manager.put(conn)


# ═══════════════════════════════════════════════════════════════
# 辅助函数：计算 TTM（滚动4季度合计）
# ═══════════════════════════════════════════════════════════════

def _compute_ttm(df_quarterly: pd.DataFrame) -> float:
    """计算滚动4季度合计值（TTM）。

    Args:
        df_quarterly: 按 end_date 正序排列的季度数据，至少4行。

    Returns:
        float: 最近4个季度合计
    """
    return df_quarterly['net_profit'].tail(4).sum()


def _compute_last_4_avg(df_quarterly: pd.DataFrame, col: str) -> float:
    """计算最近4个季度的均值。

    Args:
        df_quarterly: 按 end_date 正序排列的季度数据
        col: 列名

    Returns:
        float: 最近4个季度的均值
    """
    return df_quarterly[col].tail(4).mean()


# ═══════════════════════════════════════════════════════════════
# Roe — 净资产收益率（TTM）
# ═══════════════════════════════════════════════════════════════
#
# 公式：ROE = TTM净利润 / 净资产
# 说明：TTM净利润 = 最近4个季度净利润合计
#       净资产 = 最近一期净资产
# 方向：高值=高质量（高ROE = 盈利能力强）
# 需至少 4 行季度数据（如使用 pe/eps 反算则需 pe 字段）。
# ═══════════════════════════════════════════════════════════════

class QualityFactorBase(FactorBase):
    """质量因子基类。

    质量因子直接从财务表加载数据（而非 OHLCV 日线表），
    因此需要独立于 FactorBase.compute() 的处理流程。

    子类只需实现 calculate(df) 方法，数据加载和停牌处理由本类负责。

    停牌处理策略（适配财务数据场景）：
    - 截面日期当天：从 a50_daily_ohlcv 加载当日 null_reason 判断停牌
    - 历史财务数据：按 ann_date 对齐，不做逐日停牌过滤
      （财务数据是季度数据集，停牌只影响截面日期的样本有效性）
    """

    def compute(self, date: str) -> list[dict]:
        """计算截面上所有成分股的因子值。

        参数：
            date: 截面日期 (YYYYMMDD)

        返回：
            list[dict]: [{"ts_code": ..., "value": (float|None), "mask": (bool)}, ...]
                - value: 因子值（停牌/缺失为 None）
                - mask: True=该股票被排除（不参与 IC 计算）
        """
        # 1. 加载财务数据
        df = self._load_data(date)
        if df is None or len(df) == 0:
            logger.warning("[%s] No financial data loaded for date=%s", self.name, date)
            return []

        # 2. 获取当日成分股列表
        universe = self._get_universe(date)
        if not universe:
            logger.warning("[%s] Empty universe for date=%s", self.name, date)
            return []

        # 3. 仅保留成分股财务数据
        universe_set = set(universe)
        df = df[df['ts_code'].isin(universe_set)].copy()
        if len(df) == 0:
            logger.warning("[%s] No universe stocks in financial data for %s", self.name, date)
            return []

        # 4. 从 OHLCV 表加载截面日期的停牌信息
        suspension_map = self._load_daily_suspension_map(date, universe_set)

        # 5. 按 ts_code 分组，逐只股票计算因子值
        results = []
        for ts_code in universe:
            # 停牌检查：该股票在截面日期是否停牌
            if suspension_map.get(ts_code, False):
                results.append({'ts_code': ts_code, 'value': None, 'mask': True})
                continue

            # 获取该股票的财务数据，按 ann_date 排序
            stock_df = df[df['ts_code'] == ts_code].sort_values('ann_date').reset_index(drop=True)
            if len(stock_df) == 0:
                results.append({'ts_code': ts_code, 'value': None, 'mask': False})
                continue

            try:
                value = self.calculate(stock_df)
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

    def _load_daily_suspension_map(
        self,
        date: str,
        universe_set: set,
    ) -> dict[str, bool]:
        """加载截面日期的停牌信息。

        从 a50_daily_ohlcv 表查询当日成分股的 null_reason 字段，
        按 ts_code 返回 {ts_code: True(停牌/缺失)}。
        未在表中找到的股票默认视为非停牌（mask=False）。

        Args:
            date: 截面日期 (YYYYMMDD)
            universe_set: 当日成分股集合（仅查询这些股票以提升性能）

        Returns:
            dict: ts_code → True(停牌或缺失) / False(正常交易)
        """
        suspension: dict[str, bool] = {}
        conn = self.db_manager.get()
        try:
            query = """
                SELECT ts_code, null_reason, volume, amount
                FROM a50_daily_ohlcv
                WHERE trade_date = ?
            """
            df_daily = pd.read_sql_query(query, conn, params=(date,))
            for _, row in df_daily.iterrows():
                ts_code = row['ts_code']
                if ts_code not in universe_set:
                    continue

                null_reason = row.get('null_reason')
                if null_reason in ('SUSPENDED', 'MISSING'):
                    suspension[ts_code] = True
                elif pd.isna(null_reason) or null_reason is None:
                    vol = row.get('volume', 0)
                    amt = row.get('amount', 0)
                    if vol == 0 and amt == 0:
                        suspension[ts_code] = True
                    else:
                        suspension[ts_code] = False
                else:
                    suspension[ts_code] = False
        except Exception as e:
            logger.warning("[%s] _load_daily_suspension_map error for %s: %s",
                           self.name, date, e)
        finally:
            self.db_manager.put(conn)

        # 未在 OHLCV 表中找到的股票 → 非停牌（默认通过）
        for ts_code in universe_set:
            if ts_code not in suspension:
                suspension[ts_code] = False

        return suspension


# ═══════════════════════════════════════════════════════════════
# Roe — 净资产收益率（TTM）
# ═══════════════════════════════════════════════════════════════
#
# 公式：ROE = TTM净利润 / 净资产
# 说明：TTM净利润 = 最近4个季度净利润合计
#       净资产 = 最近一期净资产
# 方向：高值=高质量（高ROE = 盈利能力强）
# 需至少 4 行季度数据（如使用 pe/eps 反算则需 pe 字段）。
# ═══════════════════════════════════════════════════════════════

class ROE(QualityFactorBase):
    """净资产收益率（TTM）因子。

    ROE = TTM净利润 / 净资产
    TTM净利润 = 最近4个季度净利润合计，净资产 = 最近一期净资产。
    数据来源优先级：
      1. a50_financial 财务表（最准确，按 ann_date 对齐）
      2. a50_daily_ohlcv 的 pe/pb 字段（反算：ROE ≈ EPS / BPS … 但缺少 eps/bps 则不可行）
      3. 均不可用时返回 None

    因子方向：正值=高质量（高ROE = 盈利能力强）。

    数据依赖：
      - 财务表字段：net_profit, net_assets, end_date, ann_date
    """

    def __init__(self, db_manager=None, lookback: int = 20):
        super().__init__(
            db_manager=db_manager,
            name='roe',
            lookback=lookback,
        )
        self._fin_table: Optional[str] = None

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 ROE 因子值。

        Args:
            df: 该股票的财务数据（含 net_profit, net_assets 等字段），
                按 ann_date 正序排列。

        Returns:
            float or None: ROE 因子值。财务数据不足4个季度返回 None。
        """
        if df is None or len(df) < 4:
            return None

        try:
            # 取最近4个季度的净利润合计（TTM）
            ttm_net_profit = df['net_profit'].tail(4).sum()
            # 取最近一期的净资产
            latest_net_assets = df['net_assets'].iloc[-1]

            if ttm_net_profit is None or latest_net_assets is None:
                return None
            if isinstance(ttm_net_profit, float) and np.isnan(ttm_net_profit):
                return None
            if isinstance(latest_net_assets, float) and np.isnan(latest_net_assets):
                return None
            if latest_net_assets == 0:
                return None

            result = ttm_net_profit / latest_net_assets
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """重写基类 _load_data：从财务表加载数据。

        优先从财务数据表加载；若财务表不存在，尝试从日线表
        的 pe/pb 字段反算（极为有限，通常返回 None）。
        """
        if self._fin_table is None:
            self._fin_table = _detect_financial_table(self.db_manager)

        if self._fin_table:
            df = _load_financial_data(
                self.db_manager, self._fin_table, date, quarters=8,
            )
            if df is not None and len(df) > 0:
                return df

        # 回退：检测 daily 表是否有 roe 字段
        daily_fields = _detect_daily_basic_fields(self.db_manager)
        if daily_fields.get('roe'):
            df = _load_daily_quality_fields(self.db_manager, date)
            if df is not None and len(df) > 0:
                return df

        # 二者均不可用
        return None


# ═══════════════════════════════════════════════════════════════
# ProfitMargin — 净利润率
# ═══════════════════════════════════════════════════════════════
#
# 公式：ProfitMargin = TTM净利润 / TTM营业总收入
# 说明：TTM口径计算（最近4个季度的净利润合计 / 营业总收入合计）
# 方向：高值=高质量（高利润率 = 盈利空间大）
# 需至少 4 行季度数据。
# ═══════════════════════════════════════════════════════════════

class ProfitMargin(QualityFactorBase):
    """净利润率（TTM）因子。

    ProfitMargin = TTM净利润 / TTM营业总收入
    TTM净利润 = 最近4个季度净利润合计
    TTM营业总收入 = 最近4个季度营业总收入合计
    按 ann_date 对齐。

    因子方向：正值=高质量（高利润率 = 盈利空间大）。

    数据依赖：
      - 财务表字段：net_profit, total_revenue, ann_date
    """

    def __init__(self, db_manager=None, lookback: int = 20):
        super().__init__(
            db_manager=db_manager,
            name='profit_margin',
            lookback=lookback,
        )
        self._fin_table: Optional[str] = None

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 ProfitMargin 因子值。

        Args:
            df: 该股票的财务数据（含 net_profit, total_revenue 等字段），
                按 ann_date 正序排列。

        Returns:
            float or None: 净利润率因子值。财务数据不足4个季度返回 None。
        """
        if df is None or len(df) < 4:
            return None

        try:
            # TTM净利润
            ttm_net_profit = df['net_profit'].tail(4).sum()
            # TTM营业总收入
            ttm_revenue = df['total_revenue'].tail(4).sum()

            if ttm_net_profit is None or ttm_revenue is None:
                return None
            if isinstance(ttm_net_profit, float) and np.isnan(ttm_net_profit):
                return None
            if isinstance(ttm_revenue, float) and np.isnan(ttm_revenue):
                return None
            if ttm_revenue == 0:
                return None

            result = ttm_net_profit / ttm_revenue
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """从财务表加载数据。

        优先使用财务数据表；若财务表不存在，回退到 daily 表
        的 profit_margin 字段（若有）。
        """
        if self._fin_table is None:
            self._fin_table = _detect_financial_table(self.db_manager)

        if self._fin_table:
            df = _load_financial_data(
                self.db_manager, self._fin_table, date, quarters=8,
            )
            if df is not None and len(df) > 0:
                return df

        # 回退：检测 daily 表是否有 profit_margin 字段
        daily_fields = _detect_daily_basic_fields(self.db_manager)
        if daily_fields.get('profit_margin'):
            df = _load_daily_quality_fields(self.db_manager, date)
            if df is not None and len(df) > 0:
                return df

        return None


# ═══════════════════════════════════════════════════════════════
# AssetTurnover — 资产周转率
# ═══════════════════════════════════════════════════════════════
#
# 公式：AssetTurnover = TTM营业总收入 / 总资产
# 说明：TTM营业总收入 = 最近4个季度营业总收入合计
#       总资产 = 最近一期总资产
# 方向：高值=高质量（高周转率 = 资产利用效率高）
# 需至少 4 行季度数据。
# ═══════════════════════════════════════════════════════════════

class AssetTurnover(QualityFactorBase):
    """资产周转率因子。

    AssetTurnover = TTM营业总收入 / 总资产
    TTM营业总收入 = 最近4个季度营业总收入合计
    总资产 = 最近一期总资产
    按 ann_date 对齐。

    因子方向：高值=高质量（高周转率 = 资产利用效率高）。

    数据依赖：
      - 财务表字段：total_revenue, total_assets, ann_date
    """

    def __init__(self, db_manager=None, lookback: int = 20):
        super().__init__(
            db_manager=db_manager,
            name='asset_turnover',
            lookback=lookback,
        )
        self._fin_table: Optional[str] = None

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 AssetTurnover 因子值。

        Args:
            df: 该股票的财务数据（含 total_revenue, total_assets 等字段），
                按 ann_date 正序排列。

        Returns:
            float or None: 资产周转率。财务数据不足4个季度返回 None。
        """
        if df is None or len(df) < 4:
            return None

        try:
            # TTM营业总收入
            ttm_revenue = df['total_revenue'].tail(4).sum()
            # 最近一期总资产
            latest_total_assets = df['total_assets'].iloc[-1]

            if ttm_revenue is None or latest_total_assets is None:
                return None
            if isinstance(ttm_revenue, float) and np.isnan(ttm_revenue):
                return None
            if isinstance(latest_total_assets, float) and np.isnan(latest_total_assets):
                return None
            if latest_total_assets == 0:
                return None

            result = ttm_revenue / latest_total_assets
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """从财务表加载数据。"""
        if self._fin_table is None:
            self._fin_table = _detect_financial_table(self.db_manager)
        if not self._fin_table:
            return None
        return _load_financial_data(
            self.db_manager, self._fin_table, date, quarters=8,
        )


# ═══════════════════════════════════════════════════════════════
# Leverage — 杠杆率（资产负债率）
# ═══════════════════════════════════════════════════════════════
#
# 公式：Leverage = 总负债 / 总资产
# 说明：直接使用的资产负债率
# 方向反向后统一：低杠杆率 = 高质量（财务更稳健）
#     输出值 = 1 - (总负债 / 总资产) = 净资产率
#     即高值 = 低负债率 = 高质量
# 需至少 1 行季度数据（最近一期）。
# ═══════════════════════════════════════════════════════════════

class Leverage(QualityFactorBase):
    """杠杆率（资产负债率）因子。

    Leverage = 总负债 / 总资产
    因子方向反向后统一：实际输出 1 - Leverage（净资产率），
    使高值 = 低负债率 = 高质量（财务更稳健）。

    因子方向：高值=高质量（低负债率 = 财务风险低）。

    数据依赖：
      - 财务表字段：total_liabilities, total_assets, ann_date
    """

    def __init__(self, db_manager=None, lookback: int = 10):
        super().__init__(
            db_manager=db_manager,
            name='leverage',
            lookback=lookback,
        )
        self._fin_table: Optional[str] = None

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Leverage 因子值（方向反转后）。

        公式：quality_score = 1 - (total_liabilities / total_assets)
        高值 = 低杠杆 = 高质量

        Args:
            df: 该股票的财务数据，按 ann_date 正序排列。

        Returns:
            float or None: 经过方向反转的杠杆因子值。
        """
        if df is None or len(df) < 1:
            return None

        try:
            # 最近一期的总负债和总资产
            latest_liabilities = df['total_liabilities'].iloc[-1]
            latest_assets = df['total_assets'].iloc[-1]

            if latest_liabilities is None or latest_assets is None:
                return None
            if isinstance(latest_liabilities, float) and np.isnan(latest_liabilities):
                return None
            if isinstance(latest_assets, float) and np.isnan(latest_assets):
                return None
            if latest_assets == 0:
                return None

            # 资产负债率
            leverage = latest_liabilities / latest_assets
            # 方向反转：1 - 负债率 = 净资产率（高值=高质量）
            result = 1.0 - leverage
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """从财务表加载数据。"""
        if self._fin_table is None:
            self._fin_table = _detect_financial_table(self.db_manager)
        if not self._fin_table:
            return None
        return _load_financial_data(
            self.db_manager, self._fin_table, date, quarters=4,
        )


# ═══════════════════════════════════════════════════════════════
# EarningsVariability — 盈利稳定性
# ═══════════════════════════════════════════════════════════════
#
# 公式：EarningsVariability = 1 / (std(ROE_q) + epsilon)
# 说明：近20个季度单季ROE的标准差倒数
#       单季ROE = 单季净利润 / 单季净资产
#       epsilon = 1e-10（防零除）
# 方向：高值=高质量（盈利更稳定）
# 需至少 20 行季度数据。
# ═══════════════════════════════════════════════════════════════

class EarningsVariability(QualityFactorBase):
    """盈利稳定性因子。

    EarningsVariability = 1 / (std(ROE_q) + 1e-10)
    近20个季度单季ROE的标准差倒数。
    单季ROE = 单季净利润 / 单季净资产。
    盈利越稳定（标准差越小），因子值越高。

    因子方向：高值=高质量（盈利稳定 = 经营风险低）。

    数据依赖：
      - 财务表字段：net_profit, net_assets, end_date, ann_date
      - 需至少20个连续季度的财务数据
    """

    def __init__(self, db_manager=None, lookback: int = 20):
        super().__init__(
            db_manager=db_manager,
            name='earnings_variability',
            lookback=lookback,
        )
        self._fin_table: Optional[str] = None

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 EarningsVariability 因子值。

        Args:
            df: 该股票的财务数据（含 net_profit, net_assets 等字段），
                按 ann_date 正序排列。

        Returns:
            float or None: 盈利稳定性因子值。数据不足20个季度返回 None。
        """
        if df is None or len(df) < 20:
            return None

        try:
            # 取最近20行计算单季ROE
            last_20 = df.tail(20)

            roe_series = []
            for _, row in last_20.iterrows():
                np_val = row.get('net_profit')
                na_val = row.get('net_assets')
                if np_val is None or na_val is None:
                    continue
                if isinstance(np_val, float) and np.isnan(np_val):
                    continue
                if isinstance(na_val, float) and np.isnan(na_val):
                    continue
                if na_val == 0:
                    continue
                roe_series.append(np_val / na_val)

            if len(roe_series) < 12:  # 至少60%有效
                return None

            roe_std = float(np.std(roe_series, ddof=1))
            epsilon = 1e-10
            result = 1.0 / (roe_std + epsilon)

            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """从财务表加载数据（需较长时间范围以覆盖20个季度）。"""
        if self._fin_table is None:
            self._fin_table = _detect_financial_table(self.db_manager)
        if not self._fin_table:
            return None
        # 20个季度 ≈ 5年，预加载24个季度（6年）确保覆盖
        return _load_financial_data(
            self.db_manager, self._fin_table, date, quarters=24,
        )


# ═══════════════════════════════════════════════════════════════
# SalesGrowth — 营收增长（同比增长率）
# ═══════════════════════════════════════════════════════════════
#
# 公式：SalesGrowth = (本期营业总收入 - 上年同期营业总收入) / 上年同期营业总收入
# 说明：同比口径，取最近一期季度报告数据与4个季度前的同期数据比较
# 方向：高值=高质量（收入增长 = 成长性好）
# 需至少 5 行季度数据（最近1期 + 4个季度前同期）。
# ═══════════════════════════════════════════════════════════════

class SalesGrowth(QualityFactorBase):
    """营收增长（同比）因子。

    SalesGrowth = (revenue_t / revenue_t-4) - 1
    同比口径：最近一期季度营业总收入 / 4个季度前的同期收入 - 1。
    按 ann_date 对齐。

    因子方向：高值=高质量（高营收增长 = 成长性好）。

    数据依赖：
      - 财务表字段：total_revenue, end_date, ann_date
    """

    def __init__(self, db_manager=None, lookback: int = 20):
        super().__init__(
            db_manager=db_manager,
            name='sales_growth',
            lookback=lookback,
        )
        self._fin_table: Optional[str] = None

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 SalesGrowth 因子值。

        Args:
            df: 该股票的财务数据（含 total_revenue, end_date 等字段），
                按 ann_date 正序排列。

        Returns:
            float or None: 营收同比增长率。数据不足5行返回 None。
        """
        if df is None or len(df) < 5:
            return None

        try:
            # 最近一期营业收入
            latest_revenue = df['total_revenue'].iloc[-1]
            # 4个季度前的同期营业收入
            revenue_4q_ago = df['total_revenue'].iloc[-5]

            if latest_revenue is None or revenue_4q_ago is None:
                return None
            if isinstance(latest_revenue, float) and np.isnan(latest_revenue):
                return None
            if isinstance(revenue_4q_ago, float) and np.isnan(revenue_4q_ago):
                return None
            if revenue_4q_ago == 0:
                return None

            result = latest_revenue / revenue_4q_ago - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """从财务表加载数据（需覆盖同比所需的时间范围）。"""
        if self._fin_table is None:
            self._fin_table = _detect_financial_table(self.db_manager)
        if not self._fin_table:
            return None
        return _load_financial_data(
            self.db_manager, self._fin_table, date, quarters=8,
        )


# ═══════════════════════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════════════════════

def create_quality_factors(db_manager=None) -> list:
    """创建所有6个质量因子实例列表。

    Args:
        db_manager: 可选的 DatabaseManager 实例

    Returns:
        list[FactorBase]: [ROE, ProfitMargin, AssetTurnover, Leverage,
                          EarningsVariability, SalesGrowth]
    """
    return [
        ROE(db_manager=db_manager),
        ProfitMargin(db_manager=db_manager),
        AssetTurnover(db_manager=db_manager),
        Leverage(db_manager=db_manager),
        EarningsVariability(db_manager=db_manager),
        SalesGrowth(db_manager=db_manager),
    ]


# ═══════════════════════════════════════════════════════════════
# 因子元数据
# ═══════════════════════════════════════════════════════════════

QUALITY_FACTORS_META = [
    {
        "name": "roe",
        "class": "ROE",
        "category": "quality",
        "description": "净资产收益率（TTM）：TTM净利润 / 净资产",
        "min_valid_rows": 4,
        "lookback": 20,
        "direction": "高值=高质量",
        "data_dependency": "a50_financial (net_profit, net_assets) 或 a50_daily_ohlcv.roe 字段",
    },
    {
        "name": "profit_margin",
        "class": "ProfitMargin",
        "category": "quality",
        "description": "净利润率（TTM）：TTM净利润 / TTM营业总收入",
        "min_valid_rows": 4,
        "lookback": 20,
        "direction": "高值=高质量",
        "data_dependency": "a50_financial (net_profit, total_revenue) 或 a50_daily_ohlcv.profit_margin 字段",
    },
    {
        "name": "asset_turnover",
        "class": "AssetTurnover",
        "category": "quality",
        "description": "资产周转率：TTM营业总收入 / 总资产",
        "min_valid_rows": 4,
        "lookback": 20,
        "direction": "高值=高质量",
        "data_dependency": "a50_financial (total_revenue, total_assets)",
    },
    {
        "name": "leverage",
        "class": "Leverage",
        "category": "quality",
        "description": "杠杆率（方向反转后）：1 - (总负债/总资产)，高值=低负债=高质量",
        "min_valid_rows": 1,
        "lookback": 10,
        "direction": "高值=高质量（已反转）",
        "data_dependency": "a50_financial (total_liabilities, total_assets)",
    },
    {
        "name": "earnings_variability",
        "class": "EarningsVariability",
        "category": "quality",
        "description": "盈利稳定性：1 / (近20季ROE标准差 + epsilon)，高值=盈利稳定",
        "min_valid_rows": 20,
        "lookback": 20,
        "direction": "高值=高质量",
        "data_dependency": "a50_financial (net_profit, net_assets, 至少20个季度)",
    },
    {
        "name": "sales_growth",
        "class": "SalesGrowth",
        "category": "quality",
        "description": "营收同比增长：(revenue_t / revenue_t-4) - 1",
        "min_valid_rows": 5,
        "lookback": 20,
        "direction": "高值=高质量",
        "data_dependency": "a50_financial (total_revenue, 需同比数据)",
    },
]
