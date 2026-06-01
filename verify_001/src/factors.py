import numpy as np


def momentum(prices, day_idx, window):
    """动量因子 (P₀ - P₋ₖ)/P₋ₖ，越界返回 None"""
    if day_idx < window:
        return None
    return (prices[day_idx] - prices[day_idx - window]) / prices[day_idx - window]


def reversal(prices, day_idx, window):
    """反转因子 = −momentum，越界返回 None"""
    if day_idx < window:
        return None
    return -momentum(prices, day_idx, window)


def forward_return(prices, day_idx, window):
    """前向收益 (P₊ₖ - P₀)/P₀，越界返回 None"""
    if day_idx + window >= len(prices):
        return None
    return (prices[day_idx + window] - prices[day_idx]) / prices[day_idx]


def volatility(prices, day_idx, window=20, ddof=1):
    """波动率 std(日收益率) × √window，越界返回 None"""
    if day_idx < window:
        return None
    returns = np.diff(prices[day_idx - window:day_idx + 1]) / prices[day_idx - window:day_idx]
    return float(np.std(returns, ddof=ddof) * np.sqrt(window))
