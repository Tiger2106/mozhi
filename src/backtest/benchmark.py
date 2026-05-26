"""
墨枢 - Benchmark
基准指数接入：沪深300 / 上证指数净值比照。
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 内置默认数据目录
# ═══════════════════════════════════════════════════════════════

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "data", "benchmark"
)


# ═══════════════════════════════════════════════════════════════
# BenchmarkPoint
# ═══════════════════════════════════════════════════════════════


@dataclass
class BenchmarkPoint:
    """单日基准数据点"""

    date: str            # YYYY-MM-DD
    close: float         # 收盘价/点位
    nav: float           # 净值（基准日 = 1.0）
    daily_return_pct: float = 0.0   # 日收益率 (%)
    cumulative_return_pct: float = 0.0  # 累计收益率 (%)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "close": round(self.close, 4),
            "nav": round(self.nav, 6),
            "daily_return_pct": round(self.daily_return_pct, 4),
            "cumulative_return_pct": round(self.cumulative_return_pct, 4),
        }


@dataclass
class BenchmarkIndex:
    """一个完整的基准指数数据"""

    name: str               # 名称（如 "沪深300", "上证指数"）
    code: str               # 代码（如 "000300.SH", "000001.SH"）
    points: List[BenchmarkPoint] = field(default_factory=list)
    _nav_map: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self._build_nav_map()

    def _build_nav_map(self) -> None:
        self._nav_map = {p.date: p.nav for p in self.points}

    def get_nav(self, date: str) -> Optional[float]:
        """获取指定日期的净值。"""
        return self._nav_map.get(date)

    def get_point(self, date: str) -> Optional[BenchmarkPoint]:
        """获取指定日期的完整数据点。"""
        for p in self.points:
            if p.date == date:
                return p
        return None

    @property
    def date_range(self) -> tuple:
        """返回 (start_date, end_date)。"""
        if not self.points:
            return ("", "")
        return (self.points[0].date, self.points[-1].date)

    @property
    def total_return_pct(self) -> float:
        """整个序列的总收益率。"""
        if len(self.points) < 2:
            return 0.0
        first = self.points[0].close
        last = self.points[-1].close
        if first == 0:
            return 0.0
        return (last - first) / first * 100.0

    def to_nav_curve(self) -> List[Dict[str, float]]:
        """转为 EquityCurve / Performance 可接受的 benchmark_curve 格式。"""
        return [{"date": p.date, "nav": p.nav} for p in self.points]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "code": self.code,
            "total_return_pct": round(self.total_return_pct, 4),
            "date_range": list(self.date_range),
            "point_count": len(self.points),
            "points": [p.to_dict() for p in self.points],
        }


# ═══════════════════════════════════════════════════════════════
# BenchmarkProvider
# ═══════════════════════════════════════════════════════════════


class BenchmarkProvider:
    """
    基准指数提供者。

    支持从多个来源加载指数数据：
      1. 内嵌的预存迷你数据集（内置少数典型值用于测试）
      2. CSV 文件（本地数据目录）
      3. JSON 文件
      4. 内存字典直接注入

    可复用的指数实例::

        provider = BenchmarkProvider()
        csi300 = provider.get_csi300()
        sh = provider.get_shanghai()
        curve = csi300.to_nav_curve()   # 用于 EquityCurve
    """

    # ── 内置迷你数据（用于测试 / 演示） ──────────────────────
    # 格式: (date, close)  沪深300 2024年代表性点位
    _BUILTIN_CSI300: List[tuple] = [
        ("2024-01-02", 3386.11),
        ("2024-02-01", 3215.35),
        ("2024-03-01", 3537.80),
        ("2024-04-01", 3567.55),
        ("2024-05-06", 3657.77),
        ("2024-06-03", 3578.23),
        ("2024-07-01", 3478.18),
        ("2024-08-01", 3383.99),
        ("2024-09-02", 3265.01),
        ("2024-10-08", 4017.87),
        ("2024-11-01", 3890.02),
        ("2024-12-02", 3935.01),
        ("2024-12-31", 3934.91),
    ]

    _BUILTIN_SH: List[tuple] = [
        ("2024-01-02", 2962.28),
        ("2024-02-01", 2788.55),
        ("2024-03-01", 3041.17),
        ("2024-04-01", 3074.22),
        ("2024-05-06", 3140.72),
        ("2024-06-03", 3078.49),
        ("2024-07-01", 2994.73),
        ("2024-08-01", 2932.39),
        ("2024-09-02", 2811.04),
        ("2024-10-08", 3489.78),
        ("2024-11-01", 3272.01),
        ("2024-12-02", 3363.98),
        ("2024-12-31", 3351.76),
    ]

    # 内置默认配置
    _DEFAULT_INDICES: Dict[str, tuple] = {
        "csi300": ("沪深300", "000300.SH", _BUILTIN_CSI300),
        "shanghai": ("上证指数", "000001.SH", _BUILTIN_SH),
    }

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir or DEFAULT_DATA_DIR
        self._cache: Dict[str, BenchmarkIndex] = {}
        self._ensure_data_dir()

    def _ensure_data_dir(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)

    # ── 公开获取接口 ────────────────────────────────────────

    def get_csi300(self) -> BenchmarkIndex:
        """
        获取沪深300指数净值数据。

        优先级: cache > CSV/JSON数据文件 > 内置迷你数据
        """
        return self._get_or_load("csi300")

    def get_shanghai(self) -> BenchmarkIndex:
        """
        获取上证指数净值数据。

        优先级: cache > CSV/JSON数据文件 > 内置迷你数据
        """
        return self._get_or_load("shanghai")

    def get(self, name: str) -> Optional[BenchmarkIndex]:
        """
        按名称/代码获取任意基准指数。

        参数
        ----------
        name : str
            名称（"csi300", "shanghai", "沪深300" 等）或代码（"000300.SH"）

        返回
        -------
        BenchmarkIndex 或 None（未找到）
        """
        # 先查缓存
        if name in self._cache:
            return self._cache[name]

        # 别名映射
        aliases = {
            "csi300": self.get_csi300,
            "沪深300": self.get_csi300,
            "hs300": self.get_csi300,
            "000300.SH": self.get_csi300,
            "shanghai": self.get_shanghai,
            "上证指数": self.get_shanghai,
            "上证综指": self.get_shanghai,
            "000001.SH": self.get_shanghai,
        }
        loader = aliases.get(name.lower())
        if loader:
            return loader()

        return None

    # ── 注册自定义数据 ──────────────────────────────────────

    def register(
        self,
        key: str,
        name: str,
        code: str,
        data: List[tuple],
    ) -> BenchmarkIndex:
        """
        注册一个自定义基准指数（从内存数据注入）。

        参数
        ----------
        key : str
            缓存键（如 "my_index"）
        name : str
            显示名称
        code : str
            指数代码
        data : List[tuple]
            数据列表 [(date_str, close_price), ...]
            日期格式: YYYY-MM-DD

        返回
        -------
        BenchmarkIndex
        """
        index = self._build_index(name, code, data)
        self._cache[key] = index
        return index

    def register_from_csv(self, key: str, filepath: str) -> BenchmarkIndex:
        """
        从 CSV 文件注册基准指数。

        CSV 格式（无表头）::

            date,close
            2024-01-02,3386.11
            2024-01-03,3390.25
            ...

        参数
        ----------
        key : str
            缓存键
        filepath : str
            CSV 文件路径

        返回
        -------
        BenchmarkIndex
        """
        data: List[tuple] = []
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    continue  # skip header
                if len(row) >= 2:
                    data.append((row[0].strip(), float(row[1])))
        name = os.path.splitext(os.path.basename(filepath))[0]
        index = self._build_index(name, key, data)
        self._cache[key] = index
        return index

    def register_from_json(self, key: str, filepath: str) -> BenchmarkIndex:
        """
        从 JSON 文件注册基准指数。

        JSON 格式::

            [
                {"date": "2024-01-02", "close": 3386.11},
                {"date": "2024-01-03", "close": 3390.25}
            ]

        参数
        ----------
        key : str
            缓存键
        filepath : str
            JSON 文件路径

        返回
        -------
        BenchmarkIndex
        """
        with open(filepath, "r", encoding="utf-8") as f:
            records = json.load(f)
        data = [(r["date"], r["close"]) for r in records]
        name = os.path.splitext(os.path.basename(filepath))[0]
        index = self._build_index(name, key, data)
        self._cache[key] = index
        return index

    # ── 数据保存 ────────────────────────────────────────────

    def save_to_csv(
        self,
        index: BenchmarkIndex,
        filepath: Optional[str] = None,
    ) -> str:
        """
        将基准数据保存为 CSV 文件。

        参数
        ----------
        index : BenchmarkIndex
        filepath : str, optional
            保存路径，默认为 data/benchmark/{code}.csv

        返回
        -------
        str: 实际文件路径
        """
        if filepath is None:
            filepath = os.path.join(self._data_dir, f"{index.code}.csv")
        self._ensure_data_dir()
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "close", "nav"])
            for p in index.points:
                writer.writerow([p.date, p.close, p.nav])
        return filepath

    # ── 内部方法 ────────────────────────────────────────────

    def _get_or_load(self, key: str) -> BenchmarkIndex:
        """从缓存或文件或内置数据获取指数。"""
        if key in self._cache:
            return self._cache[key]

        # 尝试从文件加载
        if key == "csi300":
            candidates = ["000300.SH.csv", "csi300.csv", "沪深300.csv"]
        else:
            candidates = ["000001.SH.csv", "shanghai.csv", "上证指数.csv"]

        for fname in candidates:
            fpath = os.path.join(self._data_dir, fname)
            if os.path.isfile(fpath):
                return self.register_from_csv(key, fpath)

        # 回退到内置迷你数据
        if key in self._DEFAULT_INDICES:
            name, code, data = self._DEFAULT_INDICES[key]
            index = self._build_index(name, code, data)
            self._cache[key] = index
            return index

        raise ValueError(f"未找到基准指数: {key}")

    @staticmethod
    def _build_index(
        name: str,
        code: str,
        data: List[tuple],
    ) -> BenchmarkIndex:
        """
        从原始 [(date, close)] 构建 BenchmarkIndex，包括净值计算。
        """
        if not data:
            return BenchmarkIndex(name=name, code=code)

        # 去重并按日期排序
        seen: Dict[str, float] = {}
        for date, close in data:
            if date not in seen:
                seen[date] = close
        sorted_dates = sorted(seen.keys())
        sorted_closes = [seen[d] for d in sorted_dates]

        base_close = sorted_closes[0]
        points: List[BenchmarkPoint] = []

        for i, (date, close) in enumerate(zip(sorted_dates, sorted_closes)):
            nav = close / base_close
            daily_ret = 0.0
            if i > 0 and sorted_closes[i - 1] > 0:
                daily_ret = (close - sorted_closes[i - 1]) / sorted_closes[i - 1] * 100.0
            cum_ret = (close - base_close) / base_close * 100.0

            points.append(
                BenchmarkPoint(
                    date=date,
                    close=close,
                    nav=nav,
                    daily_return_pct=daily_ret,
                    cumulative_return_pct=cum_ret,
                )
            )

        return BenchmarkIndex(name=name, code=code, points=points)


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def get_csi300() -> BenchmarkIndex:
    """便捷函数：获取沪深300指数。"""
    return BenchmarkProvider().get_csi300()


def get_shanghai() -> BenchmarkIndex:
    """便捷函数：获取上证指数。"""
    return BenchmarkProvider().get_shanghai()


def get_benchmark(name: str) -> Optional[BenchmarkIndex]:
    """便捷函数：按名称获取基准指数。"""
    return BenchmarkProvider().get(name)
