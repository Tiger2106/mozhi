"""
IC计算引擎（RankIC计算引擎）
提供跨截面因子收益分析的核心计算功能：
  - Spearman秩相关系数计算（Rank IC）
  - IC时间序列滚动计算（按日/月/季聚合）
  - 分组IC计算（如按行业分组）
  - 支持p-value和t-stat统计显著性输出
  - Adjusted IC（剔除±3σ极端值后重算）

依赖：scipy.stats.spearmanr, numpy, pandas
Design: pure math 核心 + DBManager 参数注入

用法:
    from src.ic.engine import IC_Engine

    engine = IC_Engine()
    result = engine.compute_rank_ic(factor_values, forward_returns, date="2026-05-26")
    series = engine.compute_ic_series(factor_name="momentum_20d", daily_ics=[...], start_date="2026-01-01", end_date="2026-05-26", step="1M")

Author: 墨衡
Created: 2026-05-30T11:59:00+08:00
"""

import logging
import warnings
from typing import Optional, Union, List, Dict, Any, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from src.db.connection import DatabaseManager

logger = logging.getLogger(__name__)


class IC_Engine:
    """RankIC计算引擎：跨截面因子收益分析。

    核心能力：
      1. compute_rank_ic — 单截面 Spearman 秩相关系数
      2. compute_ic_series — 按频率聚合的 IC 时间序列
      3. compute_grouped_ic — 分组 IC（如按行业/市值分桶）

    Parameters
    ----------
    db_manager : DatabaseManager, optional
        数据库连接管理器，用于后续与管线集成（纯计算场景可为 None）
    min_obs : int
        有效样本量下限，低于此值返回 None（默认 5）
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        min_obs: int = 5,
    ):
        self.db_manager = db_manager
        self.min_obs = min_obs

    # ── 公共接口 ──────────────────────────────────────

    def compute_rank_ic(
        self,
        factor_values: Sequence[float],
        forward_returns: Sequence[float],
        date: Optional[str] = None,
        compute_adjusted: bool = False,
        adjusted_sigma: float = 3.0,
    ) -> Optional[Dict[str, Any]]:
        """计算单截面 Spearman 秩相关系数（Rank IC）。

        同时输出 Pearson IC、p-value、t-stat、样本量。
        可选输出 adjusted_ic（剔除±3σ 极端值后重算 Pearson）。

        Parameters
        ----------
        factor_values : list[float] | numpy.ndarray
            截面因子的值序列（如 50 只成分股的因子值）
        forward_returns : list[float] | numpy.ndarray
            对应前向收益值的序列
        date : str, optional
            截面日期（YYYY-MM-DD 或 YYYYMMDD）
        compute_adjusted : bool
            是否计算 adjusted_ic（剔除极端值，默认 False）
        adjusted_sigma : float
            极端值阈值，默认 3.0（±3σ）

        Returns
        -------
        dict or None
            {
                "date": "2026-05-26",
                "ic_value": 0.10,       # Pearson 相关系数
                "rank_ic": 0.12,         # Spearman 秩相关系数
                "p_value": 0.01,         # Spearman p-value
                "t_stat": 2.5,           # t 统计量
                "n_obs": 50,             # 有效样本数
                "adjusted_ic": 0.11      # 剔除极端值后（可选）
            }
        """
        x = np.asarray(factor_values, dtype=np.float64)
        y = np.asarray(forward_returns, dtype=np.float64)

        # ── 过滤 NaN/Inf ──────────────────────────
        mask = np.isfinite(x) & np.isfinite(y)
        x_clean = x[mask]
        y_clean = y[mask]
        n_obs = len(x_clean)

        if n_obs < self.min_obs:
            logger.warning(
                "Insufficient observations for Rank IC: %d < %d",
                n_obs, self.min_obs,
            )
            return None

        # ── Spearman 秩相关系数 ──────────────────
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            rank_ic, p_value = stats.spearmanr(x_clean, y_clean)

        # ── Pearson 相关系数 ─────────────────────
        ic_value = float(np.corrcoef(x_clean, y_clean)[0, 1])

        # ── t-statistic ──────────────────────────
        # t = r * sqrt((n-2) / (1-r^2))  under H0: rho=0
        if abs(rank_ic) < 1.0 - 1e-15:
            t_stat = rank_ic * np.sqrt((n_obs - 2) / max(1 - rank_ic**2, 1e-15))
        else:
            t_stat = float("inf") if rank_ic > 0 else float("-inf")

        result: Dict[str, Any] = {
            "date": date or "",
            "ic_value": float(ic_value),
            "rank_ic": float(rank_ic),
            "p_value": float(p_value),
            "t_stat": float(t_stat),
            "n_obs": n_obs,
        }

        # ── Adjusted IC（剔除 ±3σ 极端值） ───────
        if compute_adjusted:
            adjusted_ic = self._compute_adjusted_ic(x_clean, y_clean, adjusted_sigma)
            result["adjusted_ic"] = adjusted_ic

        logger.info(
            "Rank IC | date=%s ic_value=%.4f rank_ic=%.4f p_value=%.4f "
            "t_stat=%.4f n_obs=%d",
            date, result["ic_value"], result["rank_ic"],
            result["p_value"], result["t_stat"], n_obs,
        )

        return result

    def compute_ic_series(
        self,
        factor_name: str,
        daily_ics: List[Dict[str, Any]],
        start_date: str,
        end_date: str,
        step: str = "1M",
    ) -> List[Dict[str, Any]]:
        """按指定频率聚合 IC 时间序列。

        Parameters
        ----------
        factor_name : str
            因子名称（仅用于日志标注）
        daily_ics : list[dict]
            逐日 IC 结果列表，每个元素格式同 compute_rank_ic 返回值
        start_date : str
            开始日期（YYYYMMDD 或 YYYY-MM-DD）
        end_date : str
            结束日期（YYYYMMDD 或 YYYY-MM-DD）
        step : str
            聚合步长：
              - '1D'：逐日（原样返回）
              - '1M'：月底（取每月最后一个交易日的 IC）
              - '1Q'：季末（取每季度最后一个交易日的 IC）

        Returns
        -------
        list[dict]
            按频率聚合后的 IC 序列，每个元素含
            date / ic_value / rank_ic / p_value / t_stat / n_obs
        """
        if not daily_ics:
            logger.warning("compute_ic_series: empty daily_ics input")
            return []

        # ── 转为 DataFrame ────────────────────────
        df = pd.DataFrame(daily_ics)

        # 标准化日期格式为 YYYY-MM-DD
        df["_date"] = pd.to_datetime(df["date"])

        # 日期范围过滤
        mask = (df["_date"] >= pd.to_datetime(start_date)) & (
            df["_date"] <= pd.to_datetime(end_date)
        )
        df = df[mask].copy()
        if df.empty:
            logger.warning(
                "compute_ic_series: no data in range [%s, %s]", start_date, end_date
            )
            return []

        # ── 按频率筛选 ────────────────────────────
        if step == "1D":
            # 逐日：原样返回（已按日期过滤）
            result_df = df.sort_values("_date")

        elif step == "1M":
            # 月底：取每月最后一个交易日的 IC
            result_df = (
                df.sort_values("_date")
                .groupby(df["_date"].dt.to_period("M"))
                .last()
                .reset_index(drop=True)
            )

        elif step == "1Q":
            # 季末：取每季度最后一个交易日的 IC
            result_df = (
                df.sort_values("_date")
                .groupby(df["_date"].dt.to_period("Q"))
                .last()
                .reset_index(drop=True)
            )
        else:
            raise ValueError(f"Unsupported step='{step}'. Use '1D', '1M', or '1Q'.")

        # ── 输出 ──────────────────────────────────
        columns = ["date", "ic_value", "rank_ic", "p_value", "t_stat", "n_obs"]
        out = result_df[columns].to_dict(orient="records")

        logger.info(
            "IC series | factor=%s step=%s range=[%s,%s] periods=%d",
            factor_name, step, start_date, end_date, len(out),
        )

        return out

    def compute_grouped_ic(
        self,
        factor_df,
        forward_returns_df,
        groups: Union[Dict[str, List[str]], pd.Series],
    ) -> Dict[str, Dict[str, Any]]:
        """分组 IC 计算。

        对每个分组（如行业/市值分桶），计算组内的 Rank IC。

        Parameters
        ----------
        factor_df : pd.DataFrame | list[dict]
            截面因子数据，必须包含 stock_code 列和 factor_value 列
        forward_returns_df : pd.DataFrame | list[dict]
            前向收益数据，必须包含 stock_code 列和 forward_return 列
        groups : dict | pd.Series
            分组映射。dict: {group_name: [stock_code_list]}
            或 pd.Series: index=stock_code, value=group_name

        Returns
        -------
        dict[str, dict]
            {group_name: {rank_ic, p_value, t_stat, n_obs, ic_value}}
        """
        # ── 统一为 DataFrame ─────────────────────
        if isinstance(factor_df, list):
            factor_df = pd.DataFrame(factor_df)
        if isinstance(forward_returns_df, list):
            forward_returns_df = pd.DataFrame(forward_returns_df)

        # ── 合并因子和收益 ────────────────────────
        merged = pd.merge(
            factor_df,
            forward_returns_df,
            on="stock_code",
            suffixes=("_factor", "_return"),
            how="inner",
        )

        if merged.empty:
            logger.warning("compute_grouped_ic: merged result is empty")
            return {}

        # ── 构建分组 Series ───────────────────────
        if isinstance(groups, dict):
            # 展开 dict → Series
            group_series = pd.Series(
                {code: g for g, codes in groups.items() for code in codes}
            )
        else:
            group_series = groups

        merged["_group"] = merged["stock_code"].map(group_series)

        # 剔除未分组的股票
        merged = merged.dropna(subset=["_group"])
        if merged.empty:
            logger.warning("compute_grouped_ic: no stocks with group assignment")
            return {}

        # ── 逐组计算 IC ──────────────────────────
        results: Dict[str, Dict[str, Any]] = {}
        factor_col = [c for c in merged.columns if "factor" in c or c == "factor_value"]
        return_col = [c for c in merged.columns if "return" in c or c == "forward_return"]

        f_col = factor_col[0] if factor_col else "factor_value"
        r_col = return_col[0] if return_col else "forward_return"

        for grp_name, grp_df in merged.groupby("_group"):
            ic_result = self.compute_rank_ic(
                grp_df[f_col].values,
                grp_df[r_col].values,
                compute_adjusted=False,
            )
            if ic_result is not None:
                results[str(grp_name)] = {
                    "rank_ic": ic_result["rank_ic"],
                    "ic_value": ic_result["ic_value"],
                    "p_value": ic_result["p_value"],
                    "t_stat": ic_result["t_stat"],
                    "n_obs": ic_result["n_obs"],
                }
            else:
                results[str(grp_name)] = {"rank_ic": None, "n_obs": len(grp_df)}

        logger.info(
            "Grouped IC | groups=%d stocks=%d",
            len(results), len(merged),
        )

        return results

    # ── 内部方法 ──────────────────────────────────────

    @staticmethod
    def _compute_adjusted_ic(
        x: np.ndarray,
        y: np.ndarray,
        sigma: float = 3.0,
    ) -> Optional[float]:
        """剔除以 x 为中心的 ±3σ 极端值后重算 Pearson 相关系数。"""
        mean_x = np.mean(x)
        std_x = np.std(x, ddof=1)
        if std_x == 0:
            return None

        lower = mean_x - sigma * std_x
        upper = mean_x + sigma * std_x

        mask_adj = (x >= lower) & (x <= upper)
        x_adj = x[mask_adj]
        y_adj = y[mask_adj]

        if len(x_adj) < 5:
            return None

        return float(np.corrcoef(x_adj, y_adj)[0, 1])
