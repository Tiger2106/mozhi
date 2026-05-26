"""
mozhi_platform.src.backtest.runners.method_backtest_runner — MethodBacktestRunner

统一回测运行器，支持 A/B 双模式自动切换。

Phase 4 — Runner 构建。

设计参考: plugin_system_final_design_20260517.md §5.4

逻辑概要:
  1. 通过 discover_methods() 动态加载方法
  2. 根据 METHOD_META.capabilities.requires_state 自动选择执行模式:
     - 模式 A (requires_state=False): 全跑 on_bar → 最后 generate_signal
       适用于 MA / MACD / RSI / KDJ / BIAS / Bollinger / VolumeProfile / Wyckoff
     - 模式 B (requires_state=True): on_bar 逐 Bar 驱动，累积信号
       适用于 GridMethod / ReversalMethod (有状态方法)
  3. 执行完成后填充 MethodResult（耗时、时间戳、元数据）
  4. 通过 KnowledgeBridge 收割知识条目

使用示例:
    >>> from backtest.runners.method_backtest_runner import MethodBacktestRunner
    >>> from backtest.context import StrategyContext
    ... 
    >>> ctx = StrategyContext(symbol="601857", config={"ma_fast":5, "ma_slow":20})
    >>> runner = MethodBacktestRunner("ma_cross", ctx)
    >>> result = runner.run(df)
    >>> result.method_name
    'ma_cross'
    >>> result.n_bars > 0
    True

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Type
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.context import StrategyContext
from backtest.methods.base import BaseMethod, MethodResult
from backtest.methods.registry import discover_methods, check_requires_state_on_bar

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)

# ─── METHODS_DIR 自动推断 ────────────────────────────────────

_METHODS_DIR: str = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "methods")
)
"""方法目录的自动推断路径。"""


# ──────────────────────────────────────────────────────────────────────
# Helpers: 递归扫描方法模块
# ──────────────────────────────────────────────────────────────────────


def _walk_method_files(methods_dir: str) -> List[str]:
    """递归扫描 methods_dir 下所有 ``_method.py`` 文件的绝对路径。

    与 discover_methods() 的 flat 扫描不同，此函数支持子目录递归。

    Args:
        methods_dir: 方法根目录。

    Returns:
        List[str]: 模块文件的绝对路径列表，按文件名排序。
    """
    files: List[str] = []
    for root, dirs, filenames in os.walk(methods_dir):
        for fname in sorted(filenames):
            if fname.endswith("_method.py") and not fname.startswith("_"):
                files.append(os.path.join(root, fname))
    return files


def _import_method_class(filepath: str) -> Optional[Type[BaseMethod]]:
    """从文件路径动态导入 BaseMethod 子类。

    内部方法。直接使用 importlib 加载单个文件模块，
    然后查找 BaseMethod 子类。

    Args:
        filepath: 方法文件的绝对路径。

    Returns:
        Type[BaseMethod] 或 None（导入失败）。
    """
    mod_name = os.path.splitext(os.path.basename(filepath))[0]
    try:
        spec = importlib.util.spec_from_file_location(mod_name, filepath)
        if spec is None or spec.loader is None:
            logger.warning("无法加载 module spec: %s", filepath)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        logger.warning("导入方法模块失败 %s: %s", filepath, e)
        return None

    # 查找 BaseMethod 子类
    from backtest.methods.base import BaseMethod as _BM

    candidates: List[Type[BaseMethod]] = []
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            inspect.isclass(attr)
            and issubclass(attr, _BM)
            and attr is not _BM
            and not attr_name.startswith("_")
        ):
            candidates.append(attr)

    if len(candidates) == 0:
        logger.warning("模块 %s 中未发现 BaseMethod 子类", mod_name)
        return None
    if len(candidates) == 1:
        return candidates[0]

    # 多个候选：优先找方法名匹配
    expected = "".join(
        p.capitalize() for p in mod_name.replace("_method", "").split("_")
    )
    for c in candidates:
        if c.__name__ == expected:
            return c
    logger.warning(
        "模块 %s 发现 %d 个子类，自动选择首个: %s",
        mod_name, len(candidates), candidates[0].__name__,
    )
    return candidates[0]


def discover_methods_recursive(
    methods_dir: Optional[str] = None,
) -> Dict[str, Tuple[Type[BaseMethod], Optional[Dict]]]:
    """递归发现所有方法（支持子目录）。

    扫描 methods_dir（或自动推断）下所有 ``_method.py`` 文件，
    动态导入并返回 {方法名: (类, META)} 字典。

    Args:
        methods_dir: 方法根目录（可选，默认自动推断）。

    Returns:
        Dict[str, Tuple[Type[BaseMethod], Optional[Dict]]]: 方法名到 (类, META) 的映射。
    """
    scan_dir = methods_dir or _METHODS_DIR
    if not os.path.isdir(scan_dir):
        logger.warning("方法目录不存在: %s", scan_dir)
        return {}

    discovered: Dict[str, Tuple[Type[BaseMethod], Optional[Dict]]] = {}

    for filepath in _walk_method_files(scan_dir):
        module = _import_method_class(filepath)
        if module is None:
            continue

        # 提取 META
        meta = getattr(module, "METHOD_META", None)
        method_name_part = (
            meta.get("name", "") if meta else ""
        )

        if not method_name_part:
            # 从文件名推导方法名
            basename = os.path.splitext(os.path.basename(filepath))[0]
            method_name_part = basename.replace("_method", "")

        if method_name_part in discovered:
            logger.warning("方法名重复 '%s'，覆盖: %s", method_name_part, filepath)

        discovered[method_name_part] = (module, meta)

    return discovered


# ──────────────────────────────────────────────────────────────────────
# 数据预检函数（Phase 0 / R1 — NaN/空数据/Bar数不足）
# ──────────────────────────────────────────────────────────────────────


def _validate_input_data(ctx, method_cls, df: pd.DataFrame) -> None:
    """Runner.run() 入口数据预检。

    三项检查：
    1. 非空：DataFrame 行数 > 0
    2. 列存在：required_columns 全部存在
    3. Bar数足够：len(df) >= data_min_bars

    Raises:
        ValueError: 任一项检查未通过。
    """
    # ── 1. 非空检查 ────────────────────────────────────────
    if df is None or len(df) == 0:
        raise ValueError(
            f"[{ctx.method_name}] 数据预检失败：DataFrame 为空。"
        )

    # ── 2. 列存在检查 ────────────────────────────────────────
    meta = getattr(method_cls, "METHOD_META", {})
    required = meta.get("required_columns", [])
    if required:
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(
                f"[{ctx.method_name}] 数据预检失败：缺少必要列 {missing}。"
                f"现有列: {list(df.columns)}"
            )

    # ── 3. Bar数检查 ─────────────────────────────────────────
    min_bars = meta.get("data_min_bars", 20)
    if len(df) < min_bars:
        raise ValueError(
            f"[{ctx.method_name}] 数据预检失败：数据行数 {len(df)} "
            f"不足最低要求 {min_bars} 根K线。"
        )

    # ── 4. NaN 检查（仅警告，不阻断）────────────────────────
    nan_cols = [c for c in df.columns if df[c].isna().any()]
    if nan_cols:
        logger.warning(
            "数据预检：发现NaN列 %s（前5行NaN位置）", nan_cols
        )


# ──────────────────────────────────────────────────────────────────────
# MethodBacktestRunner
# ──────────────────────────────────────────────────────────────────────


class MethodBacktestRunner:
    """统一回测运行器。



    调用 ``run(df)`` 即可完成一次完整的方法执行，支持无状态和有状态双模式。

    Attributes:
        method_name: 运行的方法名。
        ctx: 策略上下文。
        method_cls: 方法类。
        method_meta: 方法元信息（METHOD_META，可能为 None）。
        method: 方法实例。
        logger: 方法专属 logger。
    """

    def __init__(
        self,
        method_name: str,
        ctx: StrategyContext,
        methods_dir: Optional[str] = None,
        enable_knowledge_collection: bool = True,
    ):
        """初始化运行器。

        动态加载 method_name 对应的方法类。方法必须存在于 methods_dir 下，
        或通过 discover_methods_recursive() 可发现。

        Args:
            method_name: 方法标识名（如 "ma_cross"、"grid"、"reversal"）。
            ctx: 策略上下文 StrategyContext 实例。
            methods_dir: 方法根目录（可选，默认自动推断）。
            enable_knowledge_collection: 完成后自动调用 KnowledgeBridge 收割知识（默认 True）。

        Raises:
            ValueError: 当 method_name 未被发现时抛 ValueError。
        """
        self.enable_knowledge_collection = enable_knowledge_collection
        self.method_name: str = method_name
        self.ctx: StrategyContext = ctx

        # ── 1. 动态加载方法 ──────────────────────────────────────
        discovered = discover_methods_recursive(methods_dir)

        if method_name not in discovered:
            # 后备：使用 methods.registry.discover_methods（但 flat 扫描）
            discovered_fallback = discover_methods()
            if method_name in discovered_fallback:
                cls_fallback = discovered_fallback[method_name]
                meta_fallback = getattr(cls_fallback, "METHOD_META", {})
                self.method_cls: Type[BaseMethod] = cls_fallback
                self.method_meta: Optional[Dict] = meta_fallback
            else:
                raise ValueError(
                    f"未知方法 '{method_name}'。"
                    f"可用方法: {sorted(discovered.keys())}"
                )
        else:
            self.method_cls, found_meta = discovered[method_name]
            self.method_meta: Optional[Dict] = found_meta if found_meta else {}
            if not self.method_meta:
                self.method_meta = getattr(self.method_cls, "METHOD_META", {})

        # ── 2. 初始化方法实例 ────────────────────────────────────
        self.method: BaseMethod = self.method_cls()

        # ── 3. 日志 ──────────────────────────────────────────────
        self.logger = ctx.get_logger()

        # C6 检查：requires_state=True 但 on_bar 未覆写
        check_warning = check_requires_state_on_bar(self.method_cls)
        if check_warning:
            self.logger.warning(check_warning)

    # ─── run() 主入口 ─────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        symbol: Optional[str] = None,
        task_id: Optional[str] = None,
        harvest: bool = False,
        bridge_kwargs: Optional[Dict[str, Any]] = None,
    ) -> MethodResult:
        """执行完整回测流程。

        Args:
            df: OHLCV DataFrame，索引为 DatetimeIndex。
            symbol: 标的代码（可选，用于日志和 KnowledgeBridge）。
            task_id: 任务标识（可选，用于 KnowledgeBridge）。
            harvest: 完成后是否调用 KnowledgeBridge 收割知识。
            bridge_kwargs: KnowledgeBridge 额外参数（可选）。

        Returns:
            MethodResult: 执行结果。
        """
        start = time.perf_counter()
        result: MethodResult

        # ═════════════════════════════════════════════════════
        # Phase 0: 数据预检（R1 — NaN/空数据/Bar数不足）
        # ═════════════════════════════════════════════════════
        _validate_input_data(self.ctx, self.method_cls, df)

        # ═════════════════════════════════════════════════════
        # Phase 1: setup
        # ═════════════════════════════════════════════════════
        self.method.setup(self.ctx)

        # ═════════════════════════════════════════════════════
        # Phase 2: 执行（A/B 模式自动切换）
        #
        # 通过 METHOD_META.capabilities.requires_state 判断：
        #   requires_state=False（默认）→ 模式 A（纯指标）
        #   requires_state=True        → 模式 B（有状态 / 事件驱动）
        # ═════════════════════════════════════════════════════
        requires_state = (
            self.method_meta.get("capabilities", {}).get("requires_state", False)
            if self.method_meta
            else False
        )

        if requires_state:
            # ── 模式 B: on_bar 逐 Bar 驱动，累积信号 ──────────
            # generate_signal(df) **不在此调用**，避免 O(n²)。
            # 有状态方法通过 on_bar(row) 逐 Bar 返回信号字典，
            # Runner 在此累积构建完整信号序列。
            # 参见墨萱技术验收报告 §1.2 / §4.2 (v1.3→v1.4 P0 修复)
            signal_values: List[int] = []
            for idx, row in df.iterrows():
                bar_result = self.method.on_bar(row)
                if isinstance(bar_result, dict):
                    signal_values.append(bar_result.get("signal", 0))
                else:
                    signal_values.append(0)

            result = MethodResult(
                signals=pd.DataFrame(
                    {"signal": signal_values},
                    index=df.index,
                ),
                indicators=None,
                method_name=self.ctx.method_name or self.method_name,
                params=self.ctx.config,
            )
        else:
            # ── 模式 A: on_bar 全跑完 → generate_signal 批量生成 ──
            # 适用于 MA、MACD、RSI、KDJ、BIAS、Bollinger 等无状态方法
            for idx, row in df.iterrows():
                self.method.on_bar(row)

            signal_df = self.method.generate_signal(df)

            # 将 generate_signal() 返回的 DF 转为 MethodResult
            if isinstance(signal_df, pd.DataFrame):
                indicators_df = None
                # 分离 signal 列与指标列
                if "signal" in signal_df.columns:
                    indicators_df = signal_df.drop(columns=["signal"])
                result = MethodResult(
                    signals=signal_df,
                    indicators=indicators_df,
                    method_name=self.ctx.method_name or self.method_name,
                    params=self.ctx.config,
                    statistics=self._extract_statistics_from_df(signal_df),
                )
            else:
                # generate_signal() 直接返回 MethodResult
                result = signal_df

        # ═════════════════════════════════════════════════════
        # Phase 3: cleanup
        # ═════════════════════════════════════════════════════
        self.method.cleanup()

        # ═════════════════════════════════════════════════════
        # Phase 4: 填充 MethodResult 元数据
        # ═════════════════════════════════════════════════════
        result.duration_ms = (time.perf_counter() - start) * 1000.0
        result.completed_time = (
            pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%dT%H:%M:%S+08:00")
        )

        self.logger.info(
            "Runner.run: method=%s bars=%d signals=%d duration=%.1fms mode=%s",
            self.method_name,
            result.n_bars,
            result.n_signals,
            result.duration_ms,
            "B" if requires_state else "A",
        )

        # ═════════════════════════════════════════════════════
        # Phase 4b: KnowledgeBridge 集成 (v2)
        # ═════════════════════════════════════════════════════
        should_harvest = harvest or self.enable_knowledge_collection
        if should_harvest:
            try:
                from backtest.engine.knowledge_bridge import KnowledgeBridge as BridgeV2

                bridge = BridgeV2(
                    output_dir=(
                        bridge_kwargs.get("output_dir", "data/knowledge_entries")
                        if bridge_kwargs else "data/knowledge_entries"
                    ),
                    sync_to_bitable=(
                        bridge_kwargs.get("sync_to_bitable", True)
                        if bridge_kwargs else True
                    ),
                )
                _ = bridge.harvest(
                    result=result,
                    method_name=self.method_name,
                    symbol=(
                        (bridge_kwargs or {}).get("symbol", "")
                        or symbol
                        or self.ctx.symbol
                    ),
                    config=self.ctx.config,
                    vix_level=(bridge_kwargs or {}).get("vix_level"),
                )
                self.logger.info(
                    "KnowledgeBridge v2 harvest: method=%s symbol=%s",
                    self.method_name,
                    symbol or self.ctx.symbol,
                )
            except Exception as e:
                self.logger.warning("KnowledgeBridge harvest 失败（非阻塞）: %s", e)

        return result

    # ─── run_batch(): 多时间框架批量运行 ────────────────────

    def run_batch(
        self,
        data_dict: Dict[str, pd.DataFrame],
        symbol: Optional[str] = None,
        task_id: Optional[str] = None,
        harvest: bool = False,
    ) -> Dict[str, MethodResult]:
        """多时间框架批量运行。

        方法可以接收不同频率的数据（如日线 + 分钟线），
        Runner 对每个数据帧独立调用 run()。

        Args:
            data_dict: {数据频率名: DataFrame}，如 {"daily": df_daily, "minute": df_minute}。
            symbol: 标的代码（可选）。
            task_id: 任务标识（可选）。
            harvest: 每个数据帧完成后是否收割知识。

        Returns:
            Dict[str, MethodResult]: {数据频率名: 执行结果}。
        """
        results: Dict[str, MethodResult] = {}
        for freq, df in data_dict.items():
            try:
                sub_task = f"{task_id}_{freq}" if task_id else None
                results[freq] = self.run(
                    df=df,
                    symbol=symbol,
                    task_id=sub_task,
                    harvest=harvest,
                )
            except Exception as e:
                self.logger.error("run_batch 失败 [%s]: %s", freq, e)
                results[freq] = MethodResult(
                    signals=pd.DataFrame({"signal": []}),
                    method_name=self.method_name,
                    params=self.ctx.config,
                    errors=[str(e)],
                )
        return results

    # ─── 内部辅助 ─────────────────────────────────────────────

    @staticmethod
    def _extract_statistics_from_df(signal_df: pd.DataFrame) -> Dict[str, float]:
        """从信号 DataFrame 中提取基础统计指标。

        Args:
            signal_df: 包含 signal 列的 DataFrame。

        Returns:
            Dict[str, float]: 统计指标字典。
        """
        stats: Dict[str, float] = {}
        if "signal" not in signal_df.columns:
            return stats

        sig = signal_df["signal"]
        n_bars = len(sig)
        n_signals = int((sig != 0).sum())
        n_buy = int((sig > 0).sum())
        n_sell = int((sig < 0).sum())

        stats["n_bars"] = float(n_bars)
        stats["n_signals"] = float(n_signals)
        stats["n_buy"] = float(n_buy)
        stats["n_sell"] = float(n_sell)
        stats["signal_ratio"] = n_signals / n_bars if n_bars > 0 else 0.0

        return stats

    # ─── 字符串显示 ──────────────────────────────────────────

    def __repr__(self) -> str:
        requires_state = (
            self.method_meta.get("capabilities", {}).get("requires_state", False)
            if self.method_meta else False
        )
        return (
            f"<MethodBacktestRunner method={self.method_name!r} "
            f"requires_state={requires_state}>"
        )
