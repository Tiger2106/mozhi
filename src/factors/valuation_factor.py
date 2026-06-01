"""
估值因子计算模块

基于 a50_daily_ohlcv 表中的估值字段直接读取 4 个估值类因子：
  1. PE_TTM（市盈率TTM）：从 pe 字段直接读取
  2. PB（市净率）：从 pb 字段直接读取
  3. PS_TTM（市销率TTM）：从 ps_ttm 字段直接读取（若有）
  4. PCF_TTM（市现率TTM）：从 pcf_ttm 字段直接读取（若有）

所有因子继承 FactorBase，注册类别为 'valuation'。
因子方向统一（低值=优秀，即 Low PE、Low PB 等表现好），
但因子值保持原始读数不变（IC 计算时由 direction 标注处理）。
停牌股票返回 None（由基类 SuspensionHandler 自动处理）。

验收标准（IC_PIPELINE_T14_010）：
  - 4个估值因子在计算日期均有非None的因子值（表中有数据即可）
  - 停牌股票返回 None

Author: 墨衡
Created: 2026-05-30T11:31:00+08:00
Version: v1
"""

from typing import Optional

import pandas as pd
import numpy as np
import logging

from src.factors.base import FactorBase

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ValuationFactorBase — 估值因子基类
# ═══════════════════════════════════════════════════════════════
#
# 估值因子直接从 a50_daily_ohlcv 表的对应字段读取，无需计算。
# 每个因子对应一个源表字段（如 pe → PE_TTM, pb → PB 等）。
# 覆盖 _load_data 以扩展查询字段，确保 ps_ttm / pcf_ttm 等
# 可选字段也被加载。
#
# calculate 方法返回该股票在截面日期（或最近交易日）的对应字段值。
# 字段缺失或为 None 时返回 None。
# ═══════════════════════════════════════════════════════════════

# 估值因子扩展字段列表
_VALUATION_EXTRA_FIELDS = [
    'pe_ttm',
    'pb',
    'ps_ttm',
    'pcf_ttm',
]


class ValuationFactorBase(FactorBase):
    """估值因子基类。

    估值因子直接从 a50_daily_ohlcv 表的对应字段读取，无需计算。
    每个子类指定一个 `_field` 属性，指明从哪列读取因子值。

    子类只需定义 `_field` 属性和 `name` 即可。

    用法：
        class PE_TTM(ValuationFactorBase):
            def __init__(self, db_manager=None):
                super().__init__(
                    db_manager=db_manager,
                    name='pe_ttm',
                    field='pe',  # 从 pe 列读取
                )
    """

    def __init__(
        self,
        db_manager=None,
        name: Optional[str] = None,
        lookback: int = 5,
        field: str = '',
    ):
        """初始化估值因子。

        Args:
            db_manager: DatabaseManager 实例
            name: 因子名称（如 'pe_ttm'）
            lookback: 回看窗口（估值因子只需最近值，设为 5）
            field: 源表字段名（如 'pe', 'pb' 等）
        """
        super().__init__(
            db_manager=db_manager,
            name=name,
            lookback=lookback,
        )
        self._field = field

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """从最新一行读取对应字段的因子值。

        Args:
            df: 该股票的有效历史数据 DataFrame，按 trade_date 正序排列，
                包含 _field 指定的列。

        Returns:
            float or None: 字段值。字段缺失或为 None/NaN 时返回 None。
        """
        if df is None or len(df) == 0:
            return None

        try:
            # 取最近一行（即截面日期/最近交易日）
            latest_row = df.iloc[-1]

            if self._field not in latest_row.index:
                logger.debug("[%s] Field '%s' not found in data", self.name, self._field)
                return None

            value = latest_row[self._field]

            if value is None:
                return None
            if isinstance(value, float) and np.isnan(value):
                return None

            return float(value)

        except (IndexError, KeyError, TypeError) as e:
            logger.debug("[%s] calculate error: %s", self.name, e)
            return None

    def _load_data(self, date: str) -> Optional[pd.DataFrame]:
        """重写基类 _load_data：扩展估值字段查询。

        在基类加载的标准字段基础上，额外加载 pe_ttm / ps_ttm / pcf_ttm 等字段。
        若某字段在表中不存在，SQLite 返回 NULL，因子值自然为 None。
        """
        import logging
        logger = logging.getLogger(__name__)

        buffer_calendar = max(self.lookback * 3, 120)
        try:
            from datetime import datetime, timedelta
            dt = datetime.strptime(date, '%Y%m%d')
            start_dt = dt - timedelta(days=buffer_calendar)
            start_date = start_dt.strftime('%Y%m%d')
        except ValueError:
            logger.error("[%s] Invalid date format: %s", self.name, date)
            return None

        conn = self.db_manager.get()
        try:
            # 动态构建 SELECT 子句：标准字段 + 估值扩展字段
            # 实时查询表结构，仅添加存在的列
            cursor = conn.execute("PRAGMA table_info(a50_daily_ohlcv)")
            table_columns = {row[1] for row in cursor.fetchall()}

            # 确认存在的估值字段
            available_extra = [
                col for col in _VALUATION_EXTRA_FIELDS
                if col in table_columns
            ]
            extra_cols_sql = ', '.join(
                [f'"{col}"' for col in available_extra]
            ) if available_extra else ''

            # 标准字段
            standard_cols = (
                "ts_code, trade_date, "
                "adj_close_b, adj_open_b, adj_high_b, adj_low_b, "
                "close, pre_close, "
                "volume, amount, turnover_rate, "
                "pe, pb, adj_factor, "
                "total_share, float_share, "
                "null_reason"
            )

            select_cols = standard_cols
            if extra_cols_sql:
                select_cols = standard_cols + ', ' + extra_cols_sql

            query = f"""
                SELECT {select_cols}
                FROM a50_daily_ohlcv
                WHERE trade_date >= ? AND trade_date <= ?
                ORDER BY ts_code, trade_date
            """
            df = pd.read_sql_query(query, conn, params=(start_date, date))
            return df

        except Exception as e:
            logger.error("[%s] _load_data error for %s: %s", self.name, date, e)
            return None
        finally:
            self.db_manager.put(conn)


# ═══════════════════════════════════════════════════════════════
# PE_TTM — 市盈率TTM
# ═══════════════════════════════════════════════════════════════
#
# 公式：直接从 pe 字段读取
# 说明：市盈率 TTM = 总市值 / TTM净利润
#       源表 pe 字段即 TTM 口径市盈率
# 数据依赖：a50_daily_ohlcv.pe 字段
# 方向：低值=优秀（Low PE），因子值保持原始读数不变
# ═══════════════════════════════════════════════════════════════

class PE_TTM(ValuationFactorBase):
    """市盈率TTM因子。

    直接从 a50_daily_ohlcv 的 pe 字段读取。
    因子方向为负（低PE=优秀），但因子值保持原始读数不变。

    数据依赖：
      - a50_daily_ohlcv.pe 字段
    """

    def __init__(self, db_manager=None):
        super().__init__(
            db_manager=db_manager,
            name='pe_ttm',
            lookback=5,
            field='pe',
        )


# ═══════════════════════════════════════════════════════════════
# PB — 市净率
# ═══════════════════════════════════════════════════════════════
#
# 公式：直接从 pb 字段读取
# 说明：市净率 = 总市值 / 净资产
# 数据依赖：a50_daily_ohlcv.pb 字段
# 方向：低值=优秀（Low PB），因子值保持原始读数不变
# ═══════════════════════════════════════════════════════════════

class PB(ValuationFactorBase):
    """市净率因子。

    直接从 a50_daily_ohlcv 的 pb 字段读取。
    因子方向为负（低PB=优秀），但因子值保持原始读数不变。

    数据依赖：
      - a50_daily_ohlcv.pb 字段
    """

    def __init__(self, db_manager=None):
        super().__init__(
            db_manager=db_manager,
            name='pb',
            lookback=5,
            field='pb',
        )


# ═══════════════════════════════════════════════════════════════
# PS_TTM — 市销率TTM
# ═══════════════════════════════════════════════════════════════
#
# 公式：直接从 ps_ttm 字段读取（若有）
# 说明：市销率 TTM = 总市值 / TTM营业总收入
# 数据依赖：a50_daily_ohlcv.ps_ttm 字段（可选，表中可能不存在）
# 方向：低值=优秀（Low PS），因子值保持原始读数不变
# ═══════════════════════════════════════════════════════════════

class PS_TTM(ValuationFactorBase):
    """市销率TTM因子。

    直接从 a50_daily_ohlcv 的 ps_ttm 字段读取。
    若 ps_ttm 字段在表中不存在，因子值返回 None。
    因子方向为负（低PS=优秀），但因子值保持原始读数不变。

    数据依赖：
      - a50_daily_ohlcv.ps_ttm 字段（可选）
    """

    def __init__(self, db_manager=None):
        super().__init__(
            db_manager=db_manager,
            name='ps_ttm',
            lookback=5,
            field='ps_ttm',
        )


# ═══════════════════════════════════════════════════════════════
# PCF_TTM — 市现率TTM
# ═══════════════════════════════════════════════════════════════
#
# 公式：直接从 pcf_ttm 字段读取（若有）
# 说明：市现率 TTM = 总市值 / TTM经营活动现金流净额
# 数据依赖：a50_daily_ohlcv.pcf_ttm 字段（可选，表中可能不存在）
# 方向：低值=优秀（Low PCF），因子值保持原始读数不变
# ═══════════════════════════════════════════════════════════════

class PCF_TTM(ValuationFactorBase):
    """市现率TTM因子。

    直接从 a50_daily_ohlcv 的 pcf_ttm 字段读取。
    若 pcf_ttm 字段在表中不存在，因子值返回 None。
    因子方向为负（低PCF=优秀），但因子值保持原始读数不变。

    数据依赖：
      - a50_daily_ohlcv.pcf_ttm 字段（可选）
    """

    def __init__(self, db_manager=None):
        super().__init__(
            db_manager=db_manager,
            name='pcf_ttm',
            lookback=5,
            field='pcf_ttm',
        )


# ═══════════════════════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════════════════════

def create_valuation_factors(db_manager=None) -> list:
    """创建所有4个估值因子实例列表。

    Args:
        db_manager: 可选的 DatabaseManager 实例

    Returns:
        list[FactorBase]: [PE_TTM, PB, PS_TTM, PCF_TTM]
    """
    return [
        PE_TTM(db_manager=db_manager),
        PB(db_manager=db_manager),
        PS_TTM(db_manager=db_manager),
        PCF_TTM(db_manager=db_manager),
    ]


# ═══════════════════════════════════════════════════════════════
# 因子元数据
# ═══════════════════════════════════════════════════════════════

VALUATION_FACTORS_META = [
    {
        "name": "pe_ttm",
        "class": "PE_TTM",
        "category": "valuation",
        "description": "市盈率TTM：从 a50_daily_ohlcv.pe 字段直接读取",
        "min_valid_rows": 1,
        "lookback": 5,
        "direction": "负（低PE=优秀），因子值保持原始读数",
        "data_dependency": "a50_daily_ohlcv.pe 字段",
    },
    {
        "name": "pb",
        "class": "PB",
        "category": "valuation",
        "description": "市净率：从 a50_daily_ohlcv.pb 字段直接读取",
        "min_valid_rows": 1,
        "lookback": 5,
        "direction": "负（低PB=优秀），因子值保持原始读数",
        "data_dependency": "a50_daily_ohlcv.pb 字段",
    },
    {
        "name": "ps_ttm",
        "class": "PS_TTM",
        "category": "valuation",
        "description": "市销率TTM：从 a50_daily_ohlcv.ps_ttm 字段直接读取",
        "min_valid_rows": 1,
        "lookback": 5,
        "direction": "负（低PS=优秀），因子值保持原始读数",
        "data_dependency": "a50_daily_ohlcv.ps_ttm 字段（可选）",
    },
    {
        "name": "pcf_ttm",
        "class": "PCF_TTM",
        "category": "valuation",
        "description": "市现率TTM：从 a50_daily_ohlcv.pcf_ttm 字段直接读取",
        "min_valid_rows": 1,
        "lookback": 5,
        "direction": "负（低PCF=优秀），因子值保持原始读数",
        "data_dependency": "a50_daily_ohlcv.pcf_ttm 字段（可选）",
    },
]
