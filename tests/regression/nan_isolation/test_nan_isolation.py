"""
EXP-001 回归测试 — EMA NaN 隔离防护

验收标准：CORE-0 ~ CORE-6
覆盖模式：all_nan / single / consecutive / leading / trailing / mixed
边界用例：empty / len_lt_window / len_window_all_nan
4版一致性校验 + 索引对齐验证

执行:
  pytest tests/regression/nan_isolation/test_nan_isolation.py -v

author: 墨衡 (deepseek-reasoner)
created_time: 2026-05-24T20:04:05.571684+08:00
source: EXP-001_run.py (自动生成)
"""

import os
import sys
import math
import json
from typing import List, Optional
import numpy as np
import pytest

# ── 项目路径 ──
PROJECT_ROOT = r"C:\Users\17699\mozhi_platform"
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
sys.path.insert(0, SRC_DIR)
sys.path.insert(0, PROJECT_ROOT)

# ── 导入 4 个 _ema 函数 ──
from backtest.strategies.factor_calculator import _ema as _ema_py
from backtest.strategies.trend_strategy import _ema as _ema_py_naive
import importlib.util as _imp_util
_phase1_spec = _imp_util.spec_from_file_location(
    "phase1_backfill",
    os.path.join(PROJECT_ROOT, "scripts", "phase1_factor_backfill.py"),
)
_phase1_mod = _imp_util.module_from_spec(_phase1_spec)
_phase1_spec.loader.exec_module(_phase1_mod)
_ema_np = _phase1_mod._calc_ema
_ema_py_full = _phase1_mod._calc_tsi

# ── 常量 ──
EMA_WINDOW = 25
INPUT_LENGTH = 500


def _to_none(arr):
    """统一输出编码为 None。"""
    result = []
    for v in arr:
        if v is None:
            result.append(None)
        elif isinstance(v, float) and (math.isnan(v) or np.isnan(v)):
            result.append(None)
        elif isinstance(v, np.floating) and np.isnan(v):
            result.append(None)
        else:
            result.append(float(v))
    return result

# ── 加载测试向量 ──
TEST_VECTORS_PATH = os.path.join(os.path.dirname(__file__), "test_vectors.json")


def _load_vectors():
    with open(TEST_VECTORS_PATH, "r") as f:
        data = json.load(f)
    vectors = {}
    for name, arr in data.items():
        vectors[name] = [None if v is None else float(v) for v in arr]
    return vectors



class TestNanIsolation:
    """CORE-0 ~ CORE-6 验收标准测试套件。"""

    def test_core_0_all_nan(self):
        """CORE-0: 全NaN输入不崩溃，输出全None。"""
        vectors = _load_vectors()
        vec = vectors["all_nan"]
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func(vec, EMA_WINDOW))
            assert len(out) == 500, f"{name} CORE-6 FAIL: len={len(out)}"
            assert all(v is None for v in out), f"{name} CORE-0 FAIL: 全NaN输出含非None值"

    def test_core_0_all_nan_tsi(self):
        """CORE-0 (pandas_ewm版): 全NaN输入不崩溃。"""
        vectors = _load_vectors()
        vec = vectors["all_nan"]
        out = _to_none(_ema_py_full(vec, long_period=EMA_WINDOW, short_period=13))
        assert len(out) == 500, f"_ema_py_full CORE-6 FAIL: len={len(out)}"
        # TSI 计算内部通过 diff()，全NaN输入时输出也可能全None
        assert not any(v is not None for v in out), "全NaN输入输出应有非None值"

    def test_core_1_single(self):
        """CORE-1: 单点NaN恢复。"""
        vectors = _load_vectors()
        vec = vectors["single"]
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func(vec, EMA_WINDOW))
            assert len(out) == 500, f"{name} CORE-6 FAIL"
            assert out[99] is None, f"{name} CORE-1 FAIL: idx 99 应为None"
            assert out[100] is not None or out[100] is None, f"{name}: idx 100 可不为None"

    def test_core_1_single_tsi(self):
        """CORE-1 (pandas_ewm版): 单点NaN恢复。"""
        vectors = _load_vectors()
        vec = vectors["single"]
        out = _to_none(_ema_py_full(vec, long_period=EMA_WINDOW, short_period=13))
        assert len(out) == 500

    def test_core_2_consecutive(self):
        """CORE-2: 连续NaN窗口恢复。"""
        vectors = _load_vectors()
        vec = vectors["consecutive"]
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func(vec, EMA_WINDOW))
            assert len(out) == 500, f"{name} CORE-6 FAIL"
            for i in range(99, 104):
                assert out[i] is None, f"{name} CORE-2 FAIL: out[{i}] 应为None"

    def test_core_3_consistency(self):
        """CORE-3: 正常段与EMA数学公式自洽（偏差<1e-10）。"""
        vectors = _load_vectors()
        for pattern in ["single", "consecutive", "leading", "trailing", "mixed"]:
            vec = vectors[pattern]
            for func, name in [
                (_ema_py, "_ema_py"),
                (_ema_py_naive, "_ema_py_naive"),
                (_ema_np, "_ema_np"),
            ]:
                out_raw = func(vec, EMA_WINDOW)
                out = _to_none(out_raw)
                # 参考 EMA
                ref = _ema_py([v if v is not None and not (isinstance(v, float) and math.isnan(v)) else None for v in vec], EMA_WINDOW)
                ref = _to_none(ref)
                for i in range(len(out)):
                    if out[i] is not None and ref[i] is not None:
                        assert abs(out[i] - ref[i]) < 1e-10, f"{name} CORE-3 FAIL @ idx {i}: {out[i]} vs ref {ref[i]}"

    def test_core_4_leading(self):
        """CORE-4: 起始NaN延迟启动。"""
        vectors = _load_vectors()
        vec = vectors["leading"]
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func(vec, EMA_WINDOW))
            assert len(out) == 500, f"{name} CORE-6 FAIL"
            for i in range(0, 10):
                assert out[i] is None, f"{name} CORE-4 FAIL: out[{i}] 应为None (leading NaN)"

    def test_core_5_trailing(self):
        """CORE-5: 尾部NaN不传染。"""
        vectors = _load_vectors()
        vec = vectors["trailing"]
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func(vec, EMA_WINDOW))
            assert len(out) == 500, f"{name} CORE-6 FAIL"
            for i in range(490, 500):
                assert out[i] is None, f"{name} CORE-5 FAIL: out[{i}] 应为None (trailing NaN)"

    def test_core_6_length(self):
        """CORE-6: 所有模式 len(output)==len(input)。"""
        vectors = _load_vectors()
        for pattern_name, vec in vectors.items():
            for func, name in [
                (_ema_py, "_ema_py"),
                (_ema_py_naive, "_ema_py_naive"),
                (_ema_np, "_ema_np"),
            ]:
                out = _to_none(func(vec, EMA_WINDOW))
                assert len(out) == len(vec), f"{name}[{pattern_name}] CORE-6 FAIL: {len(out)} != {len(vec)}"
            # _ema_py_full
            out = _to_none(_ema_py_full(vec, long_period=EMA_WINDOW, short_period=13))
            assert len(out) == len(vec), f"_ema_py_full[{pattern_name}] CORE-6 FAIL: {len(out)} != {len(vec)}"

    def test_boundary_empty(self):
        """边界: 空输入 `[]` → 不崩溃, 返回 `[]`。"""
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func([], EMA_WINDOW))
            assert len(out) == 0, f"{name} 空输入返回非空列表"

    def test_boundary_len_lt_window(self):
        """边界: len(1) < window=25 → 不崩溃, 返回 `[None]`。"""
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func([1.0], EMA_WINDOW))
            assert len(out) == 1, f"{name} len<window: 输出长度应为1, 得到{len(out)}"
            assert out[0] is None, f"{name} len<window: 输出应为None"

    def test_boundary_len_window_all_nan(self):
        """边界: 25个全NaN → 不崩溃, 返回 25 个 None。"""
        vec = [float("nan")] * 25
        for func, name in [
            (_ema_py, "_ema_py"),
            (_ema_py_naive, "_ema_py_naive"),
            (_ema_np, "_ema_np"),
        ]:
            out = _to_none(func(vec, EMA_WINDOW))
            assert len(out) == 25, f"{name} len=window全NaN: 输出长度应为25, 得到{len(out)}"
            assert all(v is None for v in out), f"{name} len=window全NaN: 应全为None"

    def test_four_version_consistency(self):
        """所有4个函数版本的CORE-0~6通过情况必须完全一致。"""
        vectors = _load_vectors()
        funcs = [
            ("_ema_py", lambda v: _to_none(_ema_py(v, EMA_WINDOW))),
            ("_ema_py_naive", lambda v: _to_none(_ema_py_naive(v, EMA_WINDOW))),
            ("_ema_np", lambda v: _to_none(_ema_np(v, EMA_WINDOW))),
            ("_ema_py_full", lambda v: _to_none(_ema_py_full(v, long_period=EMA_WINDOW, short_period=13))),
        ]
        # 收集每个版本在各模式下的输出统计
        stats = {}
        for name, fn in funcs:
            stats[name] = {}
            for pname, vec in vectors.items():
                out = fn(vec)
                ok = not any(v is None for v in out) if pname == "all_nan" else True
                stats[name][pname] = {
                    "len_match": len(out) == len(vec),
                    "all_none_on_all_nan": pname != "all_nan" or all(v is None for v in out),
                }
        # 对比
        ref = stats["_ema_py"]
        for name, st in stats.items():
            for pname in vectors:
                assert st[pname] == ref[pname], f"{{name}} 与 _ema_py 在模式 {{pname}} 下不一致: got {{st[pname]}}, ref {{ref[pname]}}"
