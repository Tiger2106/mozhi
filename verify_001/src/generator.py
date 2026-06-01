import numpy as np


def generate_prices(n=61, start=100.0, step=2.0):
    """生成线性增长价格序列 P(n) = start + (n-1) × step"""
    return start + np.arange(n, dtype=float) * step


def generate_prices_nonlinear(pattern="sin", n=61, **params):
    """预留：其他价格形态"""
    raise NotImplementedError("扩展形态待实现")
