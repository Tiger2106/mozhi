"""
mozhi_platform.src.backtest.engine.knowledge_bridge — 知识收割桥梁 v2

Phase 1c 核心产出：MethodResult → KnowledgeEntry(v2) → KnowledgeNormalizer → BitableSync

v2 升级内容（与 v1 共存）：
  - 新增 v2 KnowledgeBridge 类，集成 KnowledgeNormalizer + BitableSync
  - 保留 v1 KnowledgeBridge 和 v1 KnowledgeEntry 作为 Legacy 兼容
  - harvest() 方法仍为入口，但内部使用 v2 组件

作者: 墨衡
创建时间: 2026-05-17 (v2 升级: 2026-05-17)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backtest.engine.knowledge_entry import KnowledgeEntry as KnowledgeEntryV2
from backtest.engine.knowledge_normalizer import KnowledgeNormalizer
from backtest.engine.bitable_sync import BitableSync
from backtest.methods.base import MethodResult

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# v1 兼容: LegacyKnowledgeEntry（原 KnowledgeEntry 数据类）
# ──────────────────────────────────────────────────────────────────────


@dataclass
class KnowledgeEntry:
    """v1 知识条目数据类 — 保持向后兼容。

    ⚠️ 已废弃：新代码请使用 KnowledgeEntryV2（from knowledge_entry.py）。
    此数据类仅用于旧版 test_knowledge_bridge.py 等已有依赖的兼容。

    迁移计划：Phase 2 将移除此数据类。
    """

    # ─── 标识 ──────────────────────────────────────────────
    task_id: str
    """回测/任务的唯一标识 ID。"""

    method_name: str
    """执行的方法名。"""

    symbol: str
    """交易标的代码。"""

    # ─── 参数上下文 ────────────────────────────────────────
    params: Dict[str, Any] = field(default_factory=dict)
    """方法执行时的参数快照。"""

    # ─── 结果摘要 ──────────────────────────────────────────
    insight_summary: str = ""
    """结构化摘要文本（从 statistics 字段映射）。"""

    data_range: str = ""
    """数据覆盖范围描述（如 "2025-01-01~2025-12-31"）。"""

    data_frequency: str = "daily"
    """数据频率（"daily" / "minute"）。"""

    completed_time: str = ""
    """执行完成时间（ISO格式，+08:00）。"""

    # ─── 质量信号 ──────────────────────────────────────────
    confidence: float = 0.5
    """置信度分数 [0, 1]。"""

    source_file: str = ""
    """来源文件路径（如 JSON 结果文件路径）。"""

    review_status: str = "pending"
    """审核状态（"pending" / "reviewed" / "rejected"）。"""

    # ─── 扩展存储 ──────────────────────────────────────────
    metadata: Dict[str, Any] = field(default_factory=dict)
    """扩展元数据（预留，可挂载任意信息）。"""

    # ─── 运行时 ────────────────────────────────────────────
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    )
    """条目创建时间。"""

    updated_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    )
    """条目最后更新时间。"""


# ──────────────────────────────────────────────────────────────────────
# v1 兼容: 字段映射函数
# ──────────────────────────────────────────────────────────────────────

# 映射表: {统计字段名: (目标字段模式, 格式化模板)}
# 用于将 MethodResult.statistics 字典中的键映射到 KnowledgeEntry 的文本摘要
STATISTICS_MAPPING: Dict[str, tuple] = {
    "total_return_pct": ("total_return_pct", "总收益率 {value:.2f}%"),
    "annual_return_pct": ("annual_return_pct", "年化收益率 {value:.2f}%"),
    "sharpe_ratio": ("sharpe_ratio", "夏普比率 {value:.2f}"),
    "max_drawdown_pct": ("max_drawdown_pct", "最大回撤 {value:.2f}%"),
    "win_rate_pct": ("win_rate_pct", "胜率 {value:.2f}%"),
    "profit_factor": ("profit_factor", "盈亏比 {value:.2f}"),
    "total_trades": ("total_trades", "总交易次数 {value:.0f}"),
    "avg_holding_bars": ("avg_holding_bars", "平均持仓 K 线数 {value:.1f}"),
}


def _map_statistics_to_insight(
    statistics: Dict[str, float],
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """将 MethodResult.statistics 字段映射为 insight_summary 文本。

    Args:
        statistics: MethodResult.statistics 字典。
        extra: 额外字段（如 signal_ratio）。

    Returns:
        str: 结构化摘要文本。
    """
    parts: List[str] = []

    for stat_key, (target, template) in STATISTICS_MAPPING.items():
        if stat_key in statistics:
            value = statistics[stat_key]
            if isinstance(value, (int, float)):
                parts.append(template.format(value=value))

    # 额外字段：signal_density
    if extra and "signal_ratio" in extra:
        ratio = extra["signal_ratio"]
        if isinstance(ratio, (int, float)):
            parts.append(f"信号密度 {ratio * 100:.1f}%")

    return "; ".join(parts) if parts else "无统计数据"


def _compute_confidence(
    n_bars: int,
    data_frequency: str = "daily",
    signal_ratio: float = 0.0,
    alpha: float = 0.6,
    historical_confidence: Optional[float] = None,
) -> float:
    """计算知识条目的置信度分数。

    基础置信度 = 0.5（默认）:
    - 数据长度因子: n_bars / 100（上限 +0.3），短数据时扣分
    - 数据频率调整: 日频 +0.0，分钟级 +0.05
    - 信号密度因子: signal_ratio > 0 时 +0.05，高密度 > 0.3 时 +0.05
    - 截断至 [0.05, 0.95]

    当提供了 historical_confidence 时，使用 α 动态加权融合:
        final = α × new_confidence + (1-α) × historical_confidence

    Args:
        n_bars: 数据 K 线数。
        data_frequency: "daily" 或 "minute"。
        signal_ratio: 信号密度 [0, 1]。
        alpha: 新置信度权重（默认 0.6）。
        historical_confidence: 历史加权平均置信度（可选）。

    Returns:
        float: [0.05, 0.95] 范围内的置信度。
    """
    base = 0.5

    # 数据长度因子
    if n_bars <= 0:
        base -= 0.2
    elif n_bars < 20:
        base -= 0.15  # 极短数据扣分
    elif n_bars < 60:
        base -= 0.05  # 短数据轻微扣分
    elif n_bars <= 200:
        base += 0.10  # 较充足数据加分
    else:
        base += min(0.30, n_bars / 1000 * 0.30)  # 长数据逐步加分

    # 数据频率调整
    if data_frequency == "minute":
        base += 0.05

    # 信号密度因子
    if signal_ratio > 0:
        base += 0.05
    if signal_ratio > 0.3:
        base += 0.05

    new_confidence = max(0.05, min(0.95, base))

    # D4: α 动态加权融合
    if historical_confidence is not None:
        final = alpha * new_confidence + (1 - alpha) * historical_confidence
        return max(0.05, min(0.95, final))

    return new_confidence


# ──────────────────────────────────────────────────────────────────────
# v1 兼容: 内存存储
# ──────────────────────────────────────────────────────────────────────

_STORE: Dict[str, KnowledgeEntry] = {}
"""v1 内存中的知识条目存储，以 task_id 为键。"""


# ══════════════════════════════════════════════════════════════════════
# v2 KnowledgeBridge — MethodResult → KnowledgeEntry(v2) → BitableSync
# ══════════════════════════════════════════════════════════════════════


class KnowledgeBridge:
    """知识收割桥梁 v2：MethodResult → KnowledgeEntry(v2) → BitableSync

    v2 升级内容：
      - 接收 MethodResult，通过 KnowledgeNormalizer 标准化
      - 产出 KnowledgeEntry v2（from knowledge_entry.py）
      - 调用 BitableSync.sync() 同步到飞书
      - 保持对 v1 harvest() 接口的兼容

    Examples:
        >>> bridge = KnowledgeBridge(sync_to_bitable=False)
        >>> result = MethodResult(signals=pd.DataFrame({"signal": [1, 0, -1]}))
        >>> entry = bridge.harvest(result, "ma_cross", "601857")
        >>> isinstance(entry, KnowledgeEntryV2)
        True
    """

    def __init__(
        self,
        output_dir: str = "data/knowledge_entries",
        sync_to_bitable: bool = True,
    ):
        """初始化 KnowledgeBridge v2。

        Args:
            output_dir: 知识条目 JSON 存储目录（相对/绝对路径）。
            sync_to_bitable: 是否同步到飞书 Bitable（默认 True）。
        """
        self.normalizer = KnowledgeNormalizer()
        self.sync = BitableSync() if sync_to_bitable else None
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # v1 兼容存储（供旧版 test_knowledge_bridge.py 使用）
        self._v1_store: Dict[str, KnowledgeEntry] = _STORE
        self._v1_storage_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "knowledge_entries",
        )
        os.makedirs(self._v1_storage_dir, exist_ok=True)

    # ─── v2 harvest() 主接口 ─────────────────────────────────

    def harvest(
        self,
        result: MethodResult,
        method_name: str,
        symbol: str,
        config: Optional[Dict[str, Any]] = None,
        vix_level: Optional[float] = None,
    ) -> KnowledgeEntryV2:
        """从 MethodResult 收割知识，产出 KnowledgeEntry v2。

        流程：
          1. 从 MethodResult 提取核心统计指标
          2. 构建 KnowledgeEntry v2 数据类
          3. 调用 KnowledgeNormalizer.normalize() 标准化
          4. 保存到 knowledge_entries 文件
          5. 调用 BitableSync.sync() 同步到飞书

        Args:
            result: MethodResult 实例。
            method_name: 执行的方法名。
            symbol: 交易标的代码。
            config: 方法配置参数（可选）。
            vix_level: VIX 波动率水平（可选，影响 regime 判定）。

        Returns:
            KnowledgeEntryV2: 标准化后的知识条目。

        Raises:
            TypeError: result 不是 MethodResult 实例。
        """
        if not isinstance(result, MethodResult):
            raise TypeError(
                f"result 必须是 MethodResult 实例，收到 {type(result).__name__}"
            )

        # 1. 提取核心指标
        stats = self._extract_stats(result)

        # 2. 构建 v2 KnowledgeEntry
        entry = KnowledgeEntryV2(
            task_id=f"{method_name}_{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            method_name=method_name,
            symbol=symbol,
            completed_time=(
                result.completed_time
                or datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            ),
            total_return=stats.get("total_return_pct"),
            sharpe=stats.get("sharpe_ratio"),
            max_drawdown=stats.get("max_drawdown_pct"),
            win_rate=stats.get("win_rate_pct"),
            parameters=config or result.params or {},
            statistics=result.statistics,
            insight_summary=self._build_insight_summary(result.statistics),
            insight_category=self._infer_insight_category(method_name),
            confidence=self._compute_v2_confidence(result),
            quality_score=0.0,  # Normalizer 会填充
            regime="",
            timeframe="",
            tags=[],
            source_run_id=task_id_from_result(result),
        )

        # 3. Normalizer 标准化
        entry = self.normalizer.normalize(entry)

        # 4. 如果有 vix_level，覆盖 regime
        if vix_level is not None:
            entry.regime = self.normalizer._detect_regime(vix_level)

        # 5. 保存到文件
        self._save_to_file(entry)

        # 6. 同步到 Bitable
        if self.sync:
            try:
                self.sync.sync(entry)
            except Exception as e:
                logger.warning("Bitable sync 失败（非阻塞）: %s", e)

        logger.info(
            "KnowledgeBridge v2 harvest: method=%s symbol=%s regime=%s confidence=%.3f",
            method_name, symbol, entry.regime, entry.confidence,
        )
        return entry

    # ─── 批量收割 ─────────────────────────────────────────────

    def batch_harvest(
        self,
        results: List[Tuple[MethodResult, str, str, Optional[Dict], Optional[float]]],
    ) -> List[KnowledgeEntryV2]:
        """批量收割知识条目。

        每项为 (result, method_name, symbol, config, vix_level) 元组。

        Args:
            results: (MethodResult, method_name, symbol, config, vix_level) 列表。

        Returns:
            List[KnowledgeEntryV2]: 收割的知识条目列表。
        """
        entries: List[KnowledgeEntryV2] = []
        for item in results:
            if len(item) == 3:
                res, mname, sym = item
                cfg, vix = None, None
            elif len(item) == 4:
                res, mname, sym, cfg = item
                vix = None
            else:
                res, mname, sym, cfg, vix = item

            try:
                entry = self.harvest(
                    result=res,
                    method_name=mname,
                    symbol=sym,
                    config=cfg,
                    vix_level=vix,
                )
                entries.append(entry)
            except Exception as e:
                logger.error(
                    "批量 harvest 失败: method=%s symbol=%s error=%s",
                    mname, sym, e,
                )
        return entries

    # ─── 内部方法 ─────────────────────────────────────────────


    def _extract_stats(self, result: MethodResult) -> Dict[str, Any]:
        """从 MethodResult 提取核心统计指标。

        从 result.statistics 字典中提取已知指标，
        同时补充 signal_ratio/n_bars/n_signals 等基础信息。

        Args:
            result: MethodResult 实例。

        Returns:
            Dict[str, Any]: 提取的核心指标字典。
        """
        known_keys = list(STATISTICS_MAPPING.keys()) + [
            "n_bars", "n_signals", "signal_ratio",
            "total_return", "sharpe", "max_drawdown", "win_rate",
        ]
        extracted: Dict[str, Any] = {}

        for key in known_keys:
            if key in result.statistics:
                extracted[key] = result.statistics[key]

        # 补充 MethodResult 的内置字段
        extracted.setdefault("n_bars", result.n_bars)
        extracted.setdefault("n_signals", result.n_signals)
        extracted.setdefault("signal_ratio", result.signal_ratio)

        # 兼容命名：total_return → total_return_pct 等
        mapping_aliases = {
            "total_return": "total_return_pct",
            "sharpe": "sharpe_ratio",
            "max_drawdown": "max_drawdown_pct",
            "win_rate": "win_rate_pct",
        }
        for new_key, old_key in mapping_aliases.items():
            if new_key in extracted and old_key not in extracted:
                extracted[old_key] = extracted[new_key]

        return extracted

    def _build_insight_summary(self, statistics: Dict[str, float]) -> str:
        """从统计指标构建 insight_summary 文本。

        Args:
            statistics: 统计指标字典。

        Returns:
            str: 结构化摘要文本。
        """
        return _map_statistics_to_insight(
            statistics,
            extra={"signal_ratio": statistics.get("signal_ratio", 0.0)},
        )

    def _infer_insight_category(self, method_name: str) -> str:
        """根据方法名推断 insight 类别。

        Args:
            method_name: 方法名。

        Returns:
            str: insight_category 字符串。
        """
        category_map: Dict[str, str] = {
            "ma_cross": "technical_signal",
            "macd": "technical_signal",
            "bollinger": "technical_signal",
            "rsi": "technical_signal",
            "kdj": "technical_signal",
            "bias": "technical_signal",
            "grid": "grid_parameter",
            "reversal": "technical_signal",
            "volume_profile": "volume_analysis",
            "wyckoff": "volume_analysis",
        }
        return category_map.get(method_name, "general_signal")

    def _compute_v2_confidence(self, result: MethodResult) -> float:
        """为 v2 KnowledgeEntry 计算置信度。

        使用已有的 _compute_confidence 函数，
        用 result.n_bars 和 result.signal_ratio 计算。

        Args:
            result: MethodResult 实例。

        Returns:
            float: [0, 1] 置信度。
        """
        return _compute_confidence(
            n_bars=result.n_bars,
            data_frequency="daily",
            signal_ratio=result.signal_ratio,
        )

    def _save_to_file(self, entry: KnowledgeEntryV2) -> str:
        """将知识条目持久化到 JSON 文件。

        Args:
            entry: KnowledgeEntry v2 实例。

        Returns:
            str: 写入的文件路径。
        """
        filepath = self.output_dir / f"knowledge_{entry.task_id}.json"
        data = {
            "task_id": entry.task_id,
            "method_name": entry.method_name,
            "symbol": entry.symbol,
            "completed_time": entry.completed_time,
            "regime": entry.regime,
            "timeframe": entry.timeframe,
            "tags": entry.tags,
            "source_run_id": entry.source_run_id,
            "quality_score": entry.quality_score,
            "total_return": entry.total_return,
            "sharpe": entry.sharpe,
            "max_drawdown": entry.max_drawdown,
            "win_rate": entry.win_rate,
            "insight_summary": entry.insight_summary,
            "insight_category": entry.insight_category,
            "confidence": entry.confidence,
            "parameters": entry.parameters,
            "statistics": entry.statistics,
            "normalized_params": entry.normalized_params,
            "schema_version": entry.schema_version,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.debug("知识条目已保存: %s", filepath)
        return str(filepath)

    # ─── v1 兼容接口（供旧版 method_backtest_runner 使用） ──

    def harvest_v1(
        self,
        task_id: str,
        method_result: MethodResult,
        context: Optional[Any] = None,
        source_file: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeEntry:
        """v1 兼容的 harvest 接口。

        保留旧的 (task_id, method_result, context) 签名，
        为旧版 method_backtest_runner 提供过渡。

        Args:
            task_id: 任务/回测的唯一标识。
            method_result: 方法执行结果。
            context: StrategyContext（可选）。
            source_file: 来源文件路径（可选）。
            metadata: 扩展元数据（可选）。

        Returns:
            KnowledgeEntry: v1 知识条目。
        """
        from backtest.methods.base import MethodResult as MR

        if not isinstance(method_result, MR):
            raise TypeError(
                f"method_result 必须是 MethodResult 实例，"
                f"收到 {type(method_result).__name__}"
            )

        # ── 提取策略上下文信息 ────────────────────────────────
        symbol = context.symbol if context else ""
        method_name = method_result.method_name or ""
        params = method_result.params or {}
        data_frequency = context.data_frequency if context else "daily"

        # ── 日期范围 ──────────────────────────────────────────
        data_range = ""
        if context and context.date_range:
            data_range = f"{context.date_range[0]}~{context.date_range[1]}"
        elif method_result.completed_time:
            data_range = method_result.completed_time

        # ── 数据长度 ──────────────────────────────────────────
        n_bars = method_result.n_bars

        # ── 字段映射 → insight_summary ──────────────────────
        insight = _map_statistics_to_insight(
            method_result.statistics,
            extra={"signal_ratio": method_result.signal_ratio},
        )

        # ── 置信度计算 ───────────────────────────────────────
        existing = self._v1_store.get(task_id)
        historical_confidence = existing.confidence if existing else None

        confidence = _compute_confidence(
            n_bars=n_bars,
            data_frequency=data_frequency,
            signal_ratio=method_result.signal_ratio,
            historical_confidence=historical_confidence,
        )

        # ── 幂等 upsert ──────────────────────────────────────
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

        if task_id in self._v1_store:
            existing_entry = self._v1_store[task_id]
            existing_entry.params = params
            existing_entry.insight_summary = insight
            existing_entry.data_range = data_range
            existing_entry.data_frequency = data_frequency
            existing_entry.completed_time = (
                method_result.completed_time or now_str
            )
            existing_entry.confidence = confidence
            if source_file:
                existing_entry.source_file = source_file
            if metadata:
                existing_entry.metadata.update(metadata)
            existing_entry.updated_at = now_str
            entry = existing_entry
        else:
            entry = KnowledgeEntry(
                task_id=task_id,
                method_name=method_name,
                symbol=symbol,
                params=params,
                insight_summary=insight,
                data_range=data_range,
                data_frequency=data_frequency,
                completed_time=method_result.completed_time or now_str,
                confidence=confidence,
                source_file=source_file,
                metadata=metadata or {},
                created_at=now_str,
                updated_at=now_str,
            )
            self._v1_store[task_id] = entry

        # ── 持久化到文件 ──────────────────────────────────────
        self._persist_v1_entry(entry)

        logger.info(
            "KnowledgeBridge v1 harvest: task_id=%s method=%s symbol=%s confidence=%.3f",
            task_id, method_name, symbol, confidence,
        )
        return entry

    def _persist_v1_entry(self, entry: KnowledgeEntry) -> str:
        """将 v1 知识条目持久化到 JSON 文件。

        Args:
            entry: v1 KnowledgeEntry。

        Returns:
            str: 文件路径。
        """
        filename = f"knowledge_{entry.task_id}.json"
        filepath = os.path.join(self._v1_storage_dir, filename)
        data = asdict(entry)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filepath

    def get_v1_entry(self, task_id: str) -> Optional[KnowledgeEntry]:
        """按 task_id 查询 v1 知识条目。

        Args:
            task_id: 任务/回测的唯一标识。

        Returns:
            KnowledgeEntry or None: 未找到时返回 None。
        """
        return self._v1_store.get(task_id)

    def list_v1_entries(self) -> List[KnowledgeEntry]:
        """列出所有 v1 知识条目。

        Returns:
            List[KnowledgeEntry]: 所有条目列表。
        """
        return list(self._v1_store.values())

    def clear_v1(self) -> int:
        """清空 v1 内存存储（测试用）。

        Returns:
            int: 清空的条目数。
        """
        count = len(self._v1_store)
        self._v1_store.clear()
        return count

    # ─── v2 查询方法 ─────────────────────────────────────────

    def get_entry(self, task_id: str) -> Optional[KnowledgeEntryV2]:
        """按 task_id 查询 v2 知识条目（仅内存）。

        Args:
            task_id: 任务 ID。

        Returns:
            KnowledgeEntryV2 or None
        """
        # 当前不做内存缓存，返回 None（v2 查文件将来实现）
        return None

    def clear(self) -> int:
        """清空 v1 存储（v2 兼容）。

        Returns:
            int: 清空的条目数。
        """
        return self.clear_v1()

    def list_entries(self) -> List[KnowledgeEntry]:
        """列出所有 v1 知识条目（v2 兼容）。

        Returns:
            List[KnowledgeEntry]
        """
        return self.list_v1_entries()


# ─── 辅助函数 ──────────────────────────────────────────────


def task_id_from_result(result: MethodResult) -> str:
    """从 MethodResult 生成 task_id 用于 source_run_id。

    Args:
        result: MethodResult 实例。

    Returns:
        str: 自动生成的 task-like ID。
    """
    method = result.method_name or "unknown"
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{method}_{ts}"


# ─── v1 兼容适配器 ─────────────────────────────────────────

# 为了旧版 test_knowledge_bridge.py 不中断导入，
# 保留 v1 KnowledgeBridge 别名
KnowledgeBridgeV1 = KnowledgeBridge  # 类型别名，供旧版导入用
