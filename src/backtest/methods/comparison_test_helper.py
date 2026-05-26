"""
comparison_test_helper — 新旧系统对比验证辅助工具

author: 墨衡
version: 2.0.0

为 test_method_comparison.py 提供以下工具函数：
- df_to_bars: DataFrame → list of SimpleNamespace (兼容旧系统 b.close 风格)
- df_to_dicts: DataFrame → list of dict (兼容 test 代码 b["close"] 风格)
- make_mock_context: 从 dict 创建简易 MockContext（兼容 setup() 参数来源）
- extract_signals: 从方法返回数据中提取 signal 列
- compute_deviation: 计算新旧信号偏差
- assert_deviation_under_threshold: 断言偏差低于阈值
"""

import pandas as pd
import numpy as np
from types import SimpleNamespace


class MockContext:
    """简易 Mock Context，替代 StrategyContext

    兼容 dict 风格的 config 注入，提供 get_config() 接口。
    """
    def __init__(self, config: dict = None):
        self._config = config or {}

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)


def make_mock_context(config: dict = None) -> MockContext:
    """从 dict 创建 MockContext"""
    return MockContext(config)


def _col_resolver(df: pd.DataFrame):
    """创建列名解析器（大小写不敏感）"""
    cols_lower = {c.lower(): c for c in df.columns}

    def resolve(name: str) -> str:
        if name in df.columns:
            return name
        if name.upper() in df.columns:
            return name.upper()
        if name.lower() in cols_lower:
            return cols_lower[name.lower()]
        raise KeyError(f"找不到列: {name}（可用列: {list(df.columns)}）")

    return resolve


def df_to_bars(df: pd.DataFrame) -> list:
    """将 DataFrame 转换为旧系统兼容的 bar object 列表

    旧系统（trend_strategy 等）期望 b.close 风格（属性访问）。
    """
    resolve = _col_resolver(df)
    has_open = any(c.lower() == "open" for c in df.columns)

    bars = []
    for idx, row in df.iterrows():
        bar = SimpleNamespace()
        bar.open = float(row[resolve("open")]) if has_open else (
            float(row[resolve("high")]) + float(row[resolve("low")])) / 2.0
        bar.high = float(row[resolve("high")])
        bar.low = float(row[resolve("low")])
        bar.close = float(row[resolve("close")])
        bar.volume = float(row[resolve("volume")])
        bar.date = str(idx) if hasattr(idx, "strftime") else str(idx)
        bar.datetime = bar.date
        bars.append(bar)
    return bars


def df_to_dicts(df: pd.DataFrame) -> list:
    """将 DataFrame 转换为 dict 列表（兼容 test 代码 b['close'] 风格）"""
    resolve = _col_resolver(df)
    has_open = any(c.lower() == "open" for c in df.columns)

    bars = []
    for idx, row in df.iterrows():
        bar = {
            "open": float(row[resolve("open")]) if has_open else (
                float(row[resolve("high")]) + float(row[resolve("low")])) / 2.0,
            "high": float(row[resolve("high")]),
            "low": float(row[resolve("low")]),
            "close": float(row[resolve("close")]),
            "volume": float(row[resolve("volume")]),
            "datetime": str(idx) if hasattr(idx, "strftime") else str(idx),
        }
        bars.append(bar)
    return bars


def extract_signals(result) -> pd.Series:
    """从方法输出中提取 signal 序列

    MethodResult.signals.signal → pd.Series
    """
    if hasattr(result, "signals"):       # MethodResult
        return result.signals["signal"]
    elif isinstance(result, pd.DataFrame):
        if "signal" in result.columns:
            return result["signal"]
        return result.iloc[:, 0]
    elif isinstance(result, pd.Series):
        return result
    elif isinstance(result, dict):
        return pd.Series(result.get("signal", []))
    raise TypeError(f"不支持的返回类型: {type(result)}")


def compute_deviation(old_result, new_result) -> float:
    """计算新旧信号偏差（平均绝对差）"""
    old_signal = extract_signals(old_result)
    new_signal = extract_signals(new_result)

    # 对齐长度
    min_len = min(len(old_signal), len(new_signal))
    old_signal = old_signal.iloc[:min_len]
    new_signal = new_signal.iloc[:min_len]

    old_signal = old_signal.astype(float)
    new_signal = new_signal.astype(float)

    diff = (old_signal - new_signal).abs()
    return float(diff.mean())


def assert_deviation_under_threshold(old_result, new_result,
                                     threshold: float = 0.005,
                                     method_name: str = "") -> None:
    """断言新旧信号偏差低于阈值

    Args:
        old_result: 旧系统输出
        new_result: 新插件方法输出
        threshold: 偏差阈值（默认 0.5%）
        method_name: 方法名（仅用于报错消息）
    """
    dev = compute_deviation(old_result, new_result)
    assert dev < threshold, (
        f"{method_name}: 偏差 {dev:.6f} 超过阈值 {threshold}"
    )
