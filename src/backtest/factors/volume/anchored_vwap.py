"""
墨枢 - AnchoredVWAP 因子（P1 实施）

基于锚点（Anchor）的成交量加权平均价计算，从指定的起始点开始
累积计算 VWAP，并构建 ±1σ/±2σ 价格通道。

锚点类型：
  - first_bar: 从第一个 bar 开始锚定
  - custom_date: 从指定日期开始锚定
  - high_volume: 从最近高成交量 bar 开始锚定
  - regime_switch: 从最近市场状态切换点开始锚定

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd


# ─── Anchor 配置 ──────────────────────────────────────────────


@dataclass
class AnchorConfig:
    """锚点配置。

    Attributes:
        type: 锚点类型
            - first_bar: 从数据开始（首个 bar）锚定
            - custom_date: 从指定日期锚定
            - high_volume: 从最近高成交量 bar（成交量 > 均量×vol_threshold）锚定
            - regime_switch: 从最近市场状态切换点锚定（需额外传入 regime_series）
        date: 自定义日期字符串（YYYY-MM-DD），仅 type="custom_date" 时使用
        vol_threshold: 高成交量阈值倍数（相对 20 日均量），仅 type="high_volume" 时使用
    """
    type: Literal["first_bar", "custom_date", "high_volume", "regime_switch"] = "first_bar"
    date: Optional[str] = None
    vol_threshold: float = 2.0


# ─── 核心计算函数 ──────────────────────────────────────────


def find_anchor_index(
    df: pd.DataFrame,
    config: AnchorConfig,
    regime_series: Optional[pd.Series] = None,
) -> int:
    """根据配置确定锚点索引。

    Args:
        df: OHLCV DataFrame（DatetimeIndex 或 RangeIndex）。
        config: 锚点配置。
        regime_series: 市场状态序列（仅 type="regime_switch" 时需要）。

    Returns:
        int: 锚点 bar 索引（相对于 df）。

    Raises:
        ValueError: 无法确定锚点时。
    """
    n = len(df)
    if n == 0:
        raise ValueError("空 DataFrame，无法确定锚点")

    if config.type == "first_bar":
        return 0

    elif config.type == "custom_date":
        if config.date is None:
            raise ValueError("type='custom_date' 时必须提供 date 参数")
        if isinstance(df.index, pd.DatetimeIndex):
            matches = df.index >= config.date
            if not matches.any():
                return 0
            return int(matches.argmax())
        else:
            # 非日期索引，尝试按 iloc
            return 0

    elif config.type == "high_volume":
        if "volume" not in df.columns:
            return 0
        volumes = df["volume"].values.astype(np.float64)
        vol_mean_20 = (
            pd.Series(volumes).rolling(20, min_periods=5).mean().iloc[-1]
            if n >= 5 else volumes.mean()
        )
        if vol_mean_20 <= 0:
            return 0
        threshold_vol = vol_mean_20 * config.vol_threshold
        # 从最近往前找第一个超过阈值的 bar
        for i in range(n - 1, -1, -1):
            if volumes[i] >= threshold_vol:
                return i
        return 0

    elif config.type == "regime_switch":
        if regime_series is None or len(regime_series) < 2:
            return 0
        # 从后往前找第一个状态切换点
        for i in range(n - 1, 0, -1):
            s_idx = i if i < len(regime_series) else len(regime_series) - 1
            p_idx = (i - 1) if (i - 1) < len(regime_series) else len(regime_series) - 1
            if regime_series.iloc[s_idx] != regime_series.iloc[p_idx]:
                return i
        return 0

    else:
        raise ValueError(f"未知锚点类型: {config.type}")


def calc_anchored_vwap(
    df: pd.DataFrame,
    config: Optional[AnchorConfig] = None,
    regime_series: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """计算 Anchored VWAP 及标准差通道。

    从锚定索引开始累积计算 VWAP，并计算：
      - VWAP 值
      - ±1σ 上/下轨（1 倍标准差）
      - ±2σ 上/下轨（2 倍标准差）
      - 偏离度（当前价格距 VWAP 的标准化标准差距离）

    Args:
        df: OHLCV DataFrame（需含 high, low, close, volume 列）。
        config: 锚点配置（默认 first_bar）。
        regime_series: 市场状态序列（可选，仅 regime_switch 类型需要）。

    Returns:
        pd.DataFrame: 与 df 等长，含以下列：
            - anchored_vwap: VWAP 值
            - vwap_upper_1: +1σ 上轨
            - vwap_lower_1: -1σ 下轨
            - vwap_upper_2: +2σ 上轨
            - vwap_lower_2: -2σ 下轨
            - vwap_deviation: 当前价格距 VWAP 的标准化标准差距离（z-score）
            - anchor_index: 锚点索引（int）
    """
    cfg = config or AnchorConfig()

    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = typical_price * df["volume"]

    n = len(df)

    # 确定锚点索引
    anchor_idx = find_anchor_index(df, cfg, regime_series)

    # 从锚点开始累积
    cum_tp_vol = tp_vol.iloc[anchor_idx:].cumsum()
    cum_vol = df["volume"].iloc[anchor_idx:].cumsum()

    vwap_series = pd.Series(np.nan, index=df.index)
    mask = cum_vol > 0
    vwap_series.iloc[anchor_idx:] = cum_tp_vol[mask] / cum_vol[mask]

    # 锚点之前的 VWAP 值：用整个数据集的累积 VWAP 填充
    if anchor_idx > 0:
        total_tp_vol = tp_vol.cumsum()
        total_vol = df["volume"].cumsum()
        pre_mask = total_vol > 0
        vwap_series.iloc[:anchor_idx] = (
            total_tp_vol[pre_mask] / total_vol[pre_mask]
        ).iloc[:anchor_idx]

    # 计算残差（价格 - VWAP）
    residuals = df["close"] - vwap_series

    # 从锚点开始计算标准差
    rolling_std = pd.Series(np.nan, index=df.index)
    anchor_residuals = residuals.iloc[anchor_idx:].copy()

    # 基于锚点后数据的累积标准差
    expanding_residuals = anchor_residuals.expanding(min_periods=1)
    anchor_std = expanding_residuals.std(ddof=1)

    rolling_std.iloc[anchor_idx:] = anchor_std.values
    # 锚点前用整体标准差替代
    if anchor_idx > 0:
        total_std = residuals.expanding(min_periods=1).std(ddof=1)
        rolling_std.iloc[:anchor_idx] = total_std.iloc[:anchor_idx]

    # 通道
    upper_1 = vwap_series + rolling_std * 1.0
    lower_1 = vwap_series - rolling_std * 1.0
    upper_2 = vwap_series + rolling_std * 2.0
    lower_2 = vwap_series - rolling_std * 2.0

    # 偏离度：当前价格距 VWAP 的标准化标准差距离
    deviation = residuals / rolling_std.replace(0, np.nan)
    deviation = deviation.fillna(0.0)

    result = pd.DataFrame({
        "anchored_vwap": vwap_series,
        "vwap_upper_1": upper_1,
        "vwap_lower_1": lower_1,
        "vwap_upper_2": upper_2,
        "vwap_lower_2": lower_2,
        "vwap_deviation": deviation,
        "anchor_index": anchor_idx,
    }, index=df.index)

    return result


def calc_anchored_vwap_score(
    df: pd.DataFrame,
    config: Optional[AnchorConfig] = None,
    regime_series: Optional[pd.Series] = None,
) -> Dict[str, float]:
    """计算 AnchoredVWAP 综合评分（适配 factor_registry 的 calc_fn 签名）。

    Returns:
        Dict[str, float]: {
            "score": float,           # [-1, 1] 综合评分
            "vwap_deviation": float,  # 标准化偏离度
            "band_position": float,   # [-2, 2] 在通道中的位置
            "anchor_index": float,    # 锚点索引
        }
    """
    result_df = calc_anchored_vwap(df, config, regime_series)
    if result_df.empty:
        return {"score": 0.0, "vwap_deviation": 0.0, "band_position": 0.0, "anchor_index": 0.0}

    dev = result_df["vwap_deviation"].iloc[-1]
    if pd.isna(dev):
        dev = 0.0

    # 偏离度评分：标准化偏离度 [-3, 3] 映射到 [-1, 1]
    score = float(np.clip(dev / 3.0, -1.0, 1.0))

    return {
        "score": round(score, 4),
        "vwap_deviation": round(float(dev), 4),
        "band_position": round(float(np.clip(dev, -2.0, 2.0)), 4),
        "anchor_index": float(result_df["anchor_index"].iloc[0]),
    }


# ─── AnchoredVWAPFactor 类封装 ──────────────────────────────


class AnchoredVWAPFactor:
    """AnchoredVWAP 因子类封装。

    适配 FactorCache / BaseFactor 调用模式。

    Examples:
        >>> factor = AnchoredVWAPFactor(params={"anchor_type": "first_bar"})
        >>> result_df = factor.compute(df)
        >>> result_df["anchored_vwap"].iloc[-1]
        100.25
    """

    FACTOR_META = {
        "name": "anchored_vwap",
        "version": "1.0.0",
        "author": "墨衡",
        "description": "锚定 VWAP 及 ±1σ/±2σ 通道",
        "category": "volume",
        "default_params": {
            "anchor_type": "first_bar",
            "anchor_date": None,
            "vol_threshold": 2.0,
        },
        "tags": ["volume", "vwap", "anchor"],
    }

    def __init__(self, params: Optional[dict] = None) -> None:
        self.params = dict(self.FACTOR_META["default_params"])
        if params:
            self.params.update(params)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 Anchored VWAP 及通道。

        Args:
            df: OHLCV DataFrame。

        Returns:
            pd.DataFrame: 含 anchored_vwap 及通道列。
        """
        config = AnchorConfig(
            type=self.params.get("anchor_type", "first_bar"),
            date=self.params.get("anchor_date"),
            vol_threshold=self.params.get("vol_threshold", 2.0),
        )
        return calc_anchored_vwap(df, config=config)

    def get_score(self, df: pd.DataFrame) -> Dict[str, float]:
        """获取综合评分（适配 factor_registry 用）。"""
        return calc_anchored_vwap_score(
            df,
            AnchorConfig(
                type=self.params.get("anchor_type", "first_bar"),
                date=self.params.get("anchor_date"),
                vol_threshold=self.params.get("vol_threshold", 2.0),
            ),
        )

    def __repr__(self) -> str:
        return f"<AnchoredVWAPFactor type={self.params['anchor_type']}>"
