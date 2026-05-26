"""
墨枢 - FactorRegistry（R1 阶段二：任务7）

6 因子族统一注册与调度工厂。

功能：
  1. register_factor(name, calc_fn, category) — 注册因子到工厂
  2. compute_all(df, symbol, date) — 计算所有因子评分

6 因子族分类：
  - trend      : 趋势因子（MA, MACD, TrendQuality）
  - volume     : 量能因子（VolumeFlow, OBV, VWAP, VolumeProfile）
  - volatility : 波动率因子（ATR, BollingerBandwidth）
  - structure  : 结构因子（SupportResistance, StructureQuality）
  - regime     : 市场状态因子（RegimeClassification）
  - momentum   : 动量因子（RSI, KDJ, Bias）— 来自 methods/momentum/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.factors.base import BaseFactor
from src.backtest.factors.volume.anchored_vwap import calc_anchored_vwap_score, AnchoredVWAPFactor

# ─── 因子族分类 ────────────────────────────────────────────────

FACTOR_CATEGORIES = {
    "trend": "趋势因子",
    "volume": "量能因子",
    "volatility": "波动率因子",
    "structure": "结构因子",
    "regime": "市场状态因子",
    "momentum": "动量因子",
}


@dataclass
class RegisteredFactor:
    """已注册的因子元信息"""
    name: str
    calc_fn: Callable
    category: str
    description: str = ""

    def __post_init__(self):
        if self.category not in FACTOR_CATEGORIES:
            raise ValueError(f"未知因子分类: {self.category}，可用: {list(FACTOR_CATEGORIES.keys())}")


# ─── FactorRegistry 单例工厂 ─────────────────────────────────

class FactorRegistry:
    """因子注册与调度工厂（单例模式）。"""

    _instance: Optional["FactorRegistry"] = None
    _factors: Dict[str, RegisteredFactor] = {}
    _category_index: Dict[str, List[str]] = {}

    def __new__(cls) -> "FactorRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._factors = {}
            cls._instance._category_index = {cat: [] for cat in FACTOR_CATEGORIES}
            cls._instance._register_default_factors()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置注册表（清空已注册因子）。"""
        if cls._instance is not None:
            cls._instance._factors = {}
            cls._instance._category_index = {cat: [] for cat in FACTOR_CATEGORIES}
            cls._instance._register_default_factors()

    # ─── 注册 ────────────────────────────────────────────────

    def register_factor(
        self,
        name: str,
        calc_fn: Callable,
        category: str,
        description: str = "",
    ) -> None:
        """注册一个因子到工厂。

        Args:
            name: 因子名称（唯一标识）
            calc_fn: 计算函数，签名 calc_fn(df: pd.DataFrame) -> float
            category: 因子分类（trend / volume / volatility / structure / regime / momentum）
            description: 描述信息

        Raises:
            ValueError: 如果 name 已注册或 category 未知
        """
        if name in self._factors:
            raise ValueError(f"因子 '{name}' 已注册")

        rf = RegisteredFactor(
            name=name,
            calc_fn=calc_fn,
            category=category,
            description=description,
        )
        self._factors[name] = rf
        self._category_index[category].append(name)

    def unregister(self, name: str) -> None:
        """注销一个因子。"""
        if name in self._factors:
            cat = self._factors[name].category
            del self._factors[name]
            if name in self._category_index.get(cat, []):
                self._category_index[cat].remove(name)

    def get_factor(self, name: str) -> Optional[RegisteredFactor]:
        """获取注册的因子信息。"""
        return self._factors.get(name)

    def list_factors(self, category: Optional[str] = None) -> List[str]:
        """列出已注册的因子名列表。

        Args:
            category: 若提供，只返回该分类下的因子

        Returns:
            List[str]: 因子名称列表
        """
        if category:
            return self._category_index.get(category, []).copy()
        return list(self._factors.keys())

    def list_by_category(self) -> Dict[str, List[str]]:
        """按分类列出所有因子"""
        return {cat: names.copy() for cat, names in self._category_index.items()}

    def count(self, category: Optional[str] = None) -> int:
        """因子数量统计"""
        if category:
            return len(self._category_index.get(category, []))
        return len(self._factors)

    # ─── 计算 ────────────────────────────────────────────────

    def compute_all(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        date: str = "",
    ) -> Dict[str, float]:
        """计算所有已注册因子的评分。

        每个因子的 calc_fn(df) → float 评分，
        返回 {factor_name: score} 字典。

        Args:
            df: OHLCV DataFrame
            symbol: 标的代码（仅记录用）
            date: 日期字符串（仅记录用）

        Returns:
            Dict[str, float]: {因子名: 评分} 字典
        """
        scores: Dict[str, float] = {}
        errors: List[str] = []

        for name, rf in self._factors.items():
            try:
                result = rf.calc_fn(df)
                if isinstance(result, (int, float, np.floating)):
                    scores[name] = float(result)
                elif isinstance(result, pd.Series):
                    scores[name] = float(result.iloc[-1]) if not result.empty else 0.0
                elif isinstance(result, dict) and "score" in result:
                    scores[name] = float(result["score"])
                else:
                    # 尝试取最后一个数值
                    try:
                        scores[name] = float(result[-1] if hasattr(result, '__getitem__') else result)
                    except (TypeError, IndexError):
                        scores[name] = 0.0
            except Exception as e:
                errors.append(f"{name}: {e}")
                scores[name] = 0.0

        # 添加元信息
        scores["_meta_symbol"] = symbol
        scores["_meta_date"] = date
        scores["_meta_error_count"] = float(len(errors))

        return scores

    def compute_category(
        self,
        df: pd.DataFrame,
        category: str,
    ) -> Dict[str, float]:
        """计算指定分类下的所有因子评分。

        Args:
            df: OHLCV DataFrame
            category: 因子分类

        Returns:
            Dict[str, float]: {因子名: 评分}
        """
        if category not in FACTOR_CATEGORIES:
            raise ValueError(f"未知分类: {category}")

        scores: Dict[str, float] = {}
        for name in self._category_index.get(category, []):
            rf = self._factors.get(name)
            if rf is None:
                continue
            try:
                result = rf.calc_fn(df)
                if isinstance(result, (int, float)):
                    scores[name] = float(result)
                elif isinstance(result, pd.Series):
                    scores[name] = float(result.iloc[-1]) if not result.empty else 0.0
                else:
                    scores[name] = 0.0
            except Exception:
                scores[name] = 0.0

        return scores

    # ─── 内置默认因子注册 ────────────────────────────────

    def _register_default_factors(self) -> None:
        """注册系统内置的默认因子。"""
        # trend 族
        self._register_fn("ma_trend", _calc_ma_trend, "trend", "均线排列趋势强度")
        self._register_fn("macd_bull", _calc_macd_bull_power, "trend", "MACD 多头动能")

        # volume 族
        self._register_fn("volume_ratio", _calc_volume_ratio_score, "volume", "量比评分")
        self._register_fn("vwap_deviation", _calc_vwap_dev, "volume", "VWAP 偏离度")
        self._register_fn("anchored_vwap", _calc_anchored_vwap_score_wrapper, "volume", "锚定 VWAP + 通道偏离度")

        # volatility 族
        self._register_fn("volatility", _calc_volatility_score, "volatility", "波动率评分")
        self._register_fn("bollinger_pos", _calc_bollinger_pos, "volatility", "布林带位置评分")

        # structure 族
        self._register_fn("structure", _calc_structure_score, "structure", "结构完整度")

        # regime 族
        self._register_fn("regime_strength", _calc_regime_strength, "regime", "市场状态强度")

        # momentum 族
        self._register_fn("momentum", _calc_momentum_score, "momentum", "动量评分")

    def _register_fn(
        self, name: str, fn: Callable, category: str, desc: str = ""
    ) -> None:
        self._factors[name] = RegisteredFactor(
            name=name, calc_fn=fn, category=category, description=desc
        )
        self._category_index[category].append(name)


# ═══════════════════════════════════════════════════════════
# 内置默认因子计算函数
# ═══════════════════════════════════════════════════════════


def _calc_ma_trend(df: pd.DataFrame) -> float:
    """均线排列趋势强度 [-1, 1]"""
    close = df['close']
    n = len(close)
    if n < 60:
        return 0.0
    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    if pd.isna(ma5) or pd.isna(ma60):
        return 0.0

    # 多头排列：5>10>20>60 → +1
    if ma5 > ma10 > ma20 > ma60:
        return 1.0
    # 空头排列：5<10<20<60 → -1
    if ma5 < ma10 < ma20 < ma60:
        return -1.0
    # 部分排列
    score = 0.0
    if ma5 > ma10:
        score += 0.25
        if ma10 > ma20:
            score += 0.25
            if ma20 > ma60:
                score += 0.25
    if ma5 < ma10:
        score -= 0.25
        if ma10 < ma20:
            score -= 0.25
            if ma20 < ma60:
                score -= 0.25
    return round(score, 4)


def _calc_macd_bull_power(df: pd.DataFrame) -> float:
    """MACD 多头动能 [-1, 1]"""
    close = df['close']
    if len(close) < 26:
        return 0.0
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    macd_hist = (dif - dea) * 2
    last_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0.0

    if pd.isna(last_hist):
        return 0.0
    power = last_hist / (close.iloc[-1] * 0.01)
    # 趋势方向加分
    if last_hist > prev_hist > 0:
        power += 0.3
    elif last_hist < prev_hist < 0:
        power -= 0.3
    return round(float(np.clip(power, -1.0, 1.0)), 4)


def _calc_volume_ratio_score(df: pd.DataFrame) -> float:
    """量比评分 [-1, 1]"""
    volume = df['volume']
    if len(volume) < 20:
        return 0.0
    vol_ma20 = volume.rolling(20).mean().iloc[-1]
    current_vol = volume.iloc[-1]
    if vol_ma20 <= 0:
        return 0.0
    ratio = current_vol / vol_ma20
    score = np.clip((ratio - 1.0) * 0.5, -1.0, 1.0)
    return round(float(score), 4)


def _calc_vwap_dev(df: pd.DataFrame) -> float:
    """VWAP 偏离度 [-1, 1]"""
    if len(df) < 1 or 'close' not in df or 'volume' not in df:
        return 0.0
    vwap = (df['close'] * df['volume']).sum() / df['volume'].sum()
    if vwap == 0:
        return 0.0
    dev = (df['close'].iloc[-1] - vwap) / vwap
    return round(float(np.clip(dev * 5, -1.0, 1.0)), 4)


def _calc_volatility_score(df: pd.DataFrame) -> float:
    """波动率评分 [0, 1]"""
    close = df['close']
    if len(close) < 20:
        return 0.0
    returns = close.pct_change().dropna()
    if len(returns) < 10:
        return 0.0
    vol = returns.std()
    # 归一化：假设 A 股日波动率通常在 0.5%~3% 之间
    norm = np.clip(vol * 100 / 1.5, 0.0, 1.0)
    return round(float(norm), 4)


def _calc_bollinger_pos(df: pd.DataFrame) -> float:
    """布林带位置评分 [-1, 1]"""
    close = df['close']
    if len(close) < 20:
        return 0.0
    mid = close.rolling(20).mean().iloc[-1]
    std = close.rolling(20).std(ddof=0).iloc[-1]
    cur = close.iloc[-1]
    if pd.isna(mid) or std == 0:
        return 0.0
    # 上轨=+1, 下轨=-1
    pos = (cur - mid) / (mid * 0.02 + std * 2)  # 归一化
    return round(float(np.clip(pos, -1.0, 1.0)), 4)


def _calc_structure_score(df: pd.DataFrame) -> float:
    """结构完整度评分 [0, 1]"""
    if len(df) < 30:
        return 0.0
    high = df['high']
    low = df['low']
    close = df['close']

    tr = pd.concat([
        (high - low).abs(),
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1).dropna()

    if len(tr) < 5:
        return 0.0
    vol_cv = tr.std() / (tr.mean() + 1e-10)
    stability = 1.0 / (1.0 + vol_cv)
    return round(float(np.clip(stability, 0.0, 1.0)), 4)


def _calc_regime_strength(df: pd.DataFrame) -> float:
    """市场状态强度 [0, 1]"""
    close = df['close']
    if len(close) < 14:
        return 0.0
    # 简易 ADX-like 评分
    returns = close.pct_change().dropna()
    if len(returns) < 14:
        return 0.0
    pos_moves = (returns > 0).sum()
    neg_moves = (returns < 0).sum()
    total = pos_moves + neg_moves
    if total == 0:
        return 0.0
    # 偏向性：越接近 1 方向性越强
    directional = abs(pos_moves - neg_moves) / total
    return round(float(np.clip(directional * 1.5, 0.0, 1.0)), 4)


def _calc_momentum_score(df: pd.DataFrame) -> float:
    """动量评分 [-1, 1]"""
    close = df['close']
    if len(close) < 20:
        return 0.0
    ret_20d = (close.iloc[-1] - close.iloc[-20]) / close.iloc[-20]
    ret_5d = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] if len(close) >= 5 else ret_20d
    # 复合动量
    score = 0.6 * ret_20d + 0.4 * ret_5d
    return round(float(np.clip(score * 20, -1.0, 1.0)), 4)


def _calc_anchored_vwap_score_wrapper(df: pd.DataFrame) -> float:
    """AnchoredVWAP 综合评分适配器（供 FactorRegistry 注册用）

    调用 AnchoredVWAPFactor.get_score()，返回 score 字段（[-1, 1]）。
    若无法计算，返回 0.0。
    """
    try:
        result = calc_anchored_vwap_score(df)
        return float(result.get("score", 0.0))
    except Exception:
        return 0.0
