"""
mozhi_platform.src.backtest.engine.knowledge_entry — KnowledgeEntry v2 协议数据类

Phase 1a 核心产出：结构化知识条目标准协议。

与 v1（knowledge_bridge.KnowledgeEntry）的主要区别：
  - 核心指标独立列（total_return, sharpe, max_drawdown, win_rate）
  - 新增 regime / timeframe / tags / source_run_id / quality_score
  - normalized_params 存标准化器产出
  - schema_version 追踪协议版本

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class KnowledgeEntry:
    """知识条目 v2 协议数据类。

    支持 Bitable 展示与知识消费。
    核心标识：(task_id, method_name, symbol) 三元组全局唯一。

    Examples:
        >>> entry = KnowledgeEntry(
        ...     task_id="bt_001",
        ...     method_name="ma_cross",
        ...     symbol="601857",
        ...     regime="bull",
        ...     timeframe="1d",
        ... )
        >>> entry.validate()
        True
    """

    # ─── 必填核心 ──────────────────────────────────────────────
    task_id: str
    """回测/任务的唯一标识 ID。"""

    method_name: str
    """执行的方法名（如 "ma_cross", "grid"）。"""

    symbol: str
    """交易标的代码。"""

    completed_time: str
    """执行完成时间（ISO 格式，+08:00）。"""

    # ─── 新增核心字段 ──────────────────────────────────────────
    regime: str = ""
    """市场状态标签: bull / bear / sideways / volatile / unknown。"""

    timeframe: str = ""
    """时间框架: 1d / 4h / 1h / 15m / 5m / 1m。"""

    tags: list[str] = field(default_factory=list)
    """多维标签列表（搜索/过滤用）。"""

    source_run_id: str = ""
    """追溯原始回测 run_id（可跳转到 knowledge.db 记录）。"""

    quality_score: float = 0.0
    """知识质量自动评分（Normalizer 计算），范围 [0, 1]。"""

    # ─── 核心指标独立列 ────────────────────────────────────────
    total_return: float | None = None
    """总收益率（独立列，不塞 JSON）。"""

    sharpe: float | None = None
    """夏普比率。"""

    max_drawdown: float | None = None
    """最大回撤率（负值表示亏损）。"""

    win_rate: float | None = None
    """胜率 [0, 100] 或 [0, 1]。"""

    # ─── 知识内容 ──────────────────────────────────────────────
    insight_summary: str = ""
    """结构化摘要文本。"""

    insight_category: str = ""
    """知识类别（如 "parameter_robustness", "regime_insight"）。"""

    confidence: float = 0.0
    """置信度分数 [0, 1]（KnowledgeBridge 计算，单次回测先验）。"""

    # ─── 参数与统计 ────────────────────────────────────────────
    parameters: dict[str, Any] = field(default_factory=dict)
    """原始参数快照。"""

    statistics: dict[str, Any] = field(default_factory=dict)
    """复杂统计内容（distribution / equity_curve / heatmap 等）。"""

    normalized_params: dict[str, Any] = field(default_factory=dict)
    """Normalizer 标准化后的参数字典。"""

    # ─── 运行时 ────────────────────────────────────────────────
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    )
    """条目创建时间。"""

    updated_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    )
    """条目最后更新时间。"""

    # ─── 版本 ──────────────────────────────────────────────────
    schema_version: str = "2.0"
    """数据结构协议版本号。"""

    def validate(self) -> bool:
        """校验必填字段。

        检查 task_id / method_name / symbol 是否为空。
        任一缺失时抛出 ValueError。

        Returns:
            bool: 恒为 True（校验通过）。

        Raises:
            ValueError: 必填字段缺失。
        """
        if not self.task_id:
            raise ValueError("task_id 是必填字段，不能为空")
        if not self.method_name:
            raise ValueError("method_name 是必填字段，不能为空")
        if not self.symbol:
            raise ValueError("symbol 是必填字段，不能为空")
        return True
