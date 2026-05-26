"""
knowledge_search.py — 知识条目检索组件

Phase 2 核心产出：搜索/标签/过滤引擎。

支持：
  1. 按标签搜索（tags 精确匹配/部分匹配）
  2. 按字段过滤（method_name, symbol, regime, timeframe）
  3. 按指标排序（quality_score, total_return, sharpe, max_drawdown, win_rate, confidence）
  4. 按日期范围过滤（completed_time）
  5. 全文搜索（insight_summary 关键词匹配）
  6. 组合查询（标签+字段+排序+分页）

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Callable, Optional

# ─── 常量定义 ──────────────────────────────────────────────

SORTABLE_FIELDS = frozenset({
    "quality_score",
    "total_return",
    "sharpe",
    "max_drawdown",
    "win_rate",
    "confidence",
})

FILTERABLE_FIELDS = frozenset({
    "method_name",
    "symbol",
    "regime",
    "timeframe",
})

# ════════════════════════════════════════════════════════════
# Delay-import wrapper for KnowledgeEntry (avoid bootstrap issues)
# ════════════════════════════════════════════════════════════

def _load_entry_module():
    """延迟加载 KnowledgeEntry，避免循环导入或 init 时依赖。"""
    from src.backtest.engine.knowledge_entry import KnowledgeEntry as KE
    return KE


def _make_entry_from_dict(data: dict) -> Any:
    """从 dict 重建 KnowledgeEntry 实例。"""
    KE = _load_entry_module()
    return KE(
        task_id=data.get("task_id", ""),
        method_name=data.get("method_name", ""),
        symbol=data.get("symbol", ""),
        completed_time=data.get("completed_time", ""),
        regime=data.get("regime", ""),
        timeframe=data.get("timeframe", ""),
        tags=data.get("tags", []),
        source_run_id=data.get("source_run_id", ""),
        quality_score=data.get("quality_score", 0.0),
        total_return=data.get("total_return"),
        sharpe=data.get("sharpe"),
        max_drawdown=data.get("max_drawdown"),
        win_rate=data.get("win_rate"),
        insight_summary=data.get("insight_summary", ""),
        insight_category=data.get("insight_category", ""),
        confidence=data.get("confidence", 0.0),
        parameters=data.get("parameters", {}),
        statistics=data.get("statistics", {}),
        normalized_params=data.get("normalized_params", {}),
    )


# ════════════════════════════════════════════════════════════
# KnowledgeSearch
# ════════════════════════════════════════════════════════════


class KnowledgeSearch:
    """知识条目检索组件。

    支持：
    1. 按标签搜索（tags 精确匹配/部分匹配）
    2. 按字段过滤（method_name, symbol, regime, timeframe）
    3. 按指标排序（quality_score, total_return, sharpe, max_drawdown, win_rate, confidence）
    4. 按日期范围过滤（completed_time）
    5. 全文搜索（insight_summary 关键词匹配）
    6. 组合查询（标签+字段+关键词+排序+分页）

    Examples:
        >>> ks = KnowledgeSearch(data_dir="data/knowledge_entries")
        >>> results = ks.search_by_tags(["trend"], mode="any")
        >>> results = ks.combined_query(
        ...     tags=["trend"],
        ...     field_filters={"method_name": "ma_cross"},
        ...     sort_field="sharpe",
        ...     limit=10,
        ... )
        >>> stats = ks.get_statistics()
    """

    def __init__(self, data_dir: str = "data/knowledge_entries"):
        """初始化检索组件，加载目录下所有 JSON 知识条目。

        Args:
            data_dir: 知识条目 JSON 文件目录路径。
                      相对于当前工作目录，或绝对路径。
        """
        self._entries: list[Any] = []
        self._data_dir = data_dir
        self._load_entries()

    # ─── 私有方法 ──────────────────────────────────────────

    def _resolve_path(self) -> str:
        """解析 data_dir 为绝对路径。"""
        path = self._data_dir
        if not os.path.isabs(path):
            # 尝试从项目根目录解析
            candidates = [
                os.path.join(os.getcwd(), path),
                os.path.join(os.path.dirname(__file__), "..", "..", "..", path),
                os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge_entries"),
            ]
            for c in candidates:
                resolved = os.path.normpath(c)
                if os.path.isdir(resolved):
                    return resolved
            # 回退到第一个候选
            return os.path.normpath(candidates[0])
        return path

    def _load_entries(self) -> None:
        """从 data_dir 加载所有 JSON 文件为 KnowledgeEntry 实例。"""
        path = self._resolve_path()
        self._entries = []

        if not os.path.isdir(path):
            return

        for fname in os.listdir(path):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(path, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = _make_entry_from_dict(data)
                self._entries.append(entry)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                # 跳过格式错误的文件
                continue

    # ─── 标签搜索 ──────────────────────────────────────────

    def search_by_tags(
        self, tags: list[str], mode: str = "any"
    ) -> list[Any]:
        """按标签搜索知识条目。

        Args:
            tags: 要搜索的标签列表。
            mode: 匹配模式。
                  "any" — 匹配任意一个标签即返回（OR 逻辑）。
                  "all" — 必须匹配所有标签（AND 逻辑）。

        Returns:
            匹配的知识条目列表。
        """
        if not tags:
            return self._entries[:]

        tag_set = set(tags)
        results = []

        for entry in self._entries:
            entry_tags = set(entry.tags)
            if mode == "all":
                if tag_set.issubset(entry_tags):
                    results.append(entry)
            else:
                if tag_set & entry_tags:
                    results.append(entry)

        return results

    # ─── 字段精确过滤 ──────────────────────────────────────

    def filter_by_field(
        self, field: str, value: str
    ) -> list[Any]:
        """按字段精确匹配过滤。

        支持的字段：method_name, symbol, regime, timeframe。

        Args:
            field: 字段名。
            value: 要匹配的值（精确匹配，区分大小写）。

        Returns:
            过滤后的知识条目列表。
        """
        if field not in FILTERABLE_FIELDS:
            raise ValueError(
                f"不支持的过滤字段 '{field}'。"
                f"支持的字段: {sorted(FILTERABLE_FIELDS)}"
            )

        return [e for e in self._entries if getattr(e, field, "") == value]

    # ─── 全文搜索 ──────────────────────────────────────────

    def search_text(self, keyword: str) -> list[Any]:
        """全文搜索 insight_summary 关键词。

        Args:
            keyword: 搜索关键词（大小写不敏感）。

        Returns:
            包含关键词的知识条目列表。
        """
        if not keyword:
            return self._entries[:]

        keyword_lower = keyword.lower()
        return [
            e
            for e in self._entries
            if keyword_lower in e.insight_summary.lower()
        ]

    # ─── 排序 ──────────────────────────────────────────────

    def sort_by(
        self,
        entries: list[Any],
        field: str,
        ascending: bool = False,
    ) -> list[Any]:
        """按某个指标排序。

        支持的排序字段：quality_score, total_return, sharpe,
        max_drawdown, win_rate, confidence。

        Args:
            entries: 待排序的条目列表。
            field: 排序字段名。
            ascending: True=升序，False=降序（默认）。

        Returns:
            排序后的新列表。
        """
        if field not in SORTABLE_FIELDS:
            raise ValueError(
                f"不支持的排序字段 '{field}'。"
                f"支持的字段: {sorted(SORTABLE_FIELDS)}"
            )

        def _sort_key(e: Any) -> float:
            val = getattr(e, field, None)
            if val is None:
                return float("-inf") if ascending else float("-inf")
            return float(val)

        return sorted(
            entries,
            key=_sort_key,
            reverse=not ascending,
        )

    # ─── 日期范围过滤 ──────────────────────────────────────

    def filter_date_range(
        self,
        entries: list[Any],
        start: str,
        end: str,
    ) -> list[Any]:
        """按 completed_time 日期范围过滤。

        Args:
            entries: 待过滤的条目列表。
            start: 起始日期（含），格式 "YYYY-MM-DD" 或 ISO 8601。
            end: 结束日期（含），格式 "YYYY-MM-DD" 或 ISO 8601。

        Returns:
            在日期范围内的条目列表。
        """
        if not entries:
            return []

        def _parse_date(dt_str: str) -> str:
            """提取 YYYY-MM-DD 日期部分。"""
            return dt_str[:10] if dt_str else ""

        start_date = _parse_date(start)
        end_date = _parse_date(end)

        if not start_date and not end_date:
            return entries[:]

        results = []
        for e in entries:
            dt = _parse_date(e.completed_time)
            if not dt:
                continue
            if start_date and dt < start_date:
                continue
            if end_date and dt > end_date:
                continue
            results.append(e)

        return results

    # ─── 组合查询 ──────────────────────────────────────────

    def combined_query(
        self,
        tags: Optional[list[str]] = None,
        field_filters: Optional[dict[str, str]] = None,
        keyword: Optional[str] = None,
        sort_field: Optional[str] = None,
        ascending: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Any]:
        """组合查询：标签+字段+关键词+排序+分页。

        各过滤条件之间是 AND 逻辑。

        Args:
            tags: 可选标签列表（默认 any 模式）。
            field_filters: 可选字段过滤字典，如 {"method_name": "ma_cross"}。
            keyword: 可选全文搜索关键词。
            sort_field: 可选排序字段。
            ascending: 排序方向（默认降序）。
            limit: 返回条目数量上限（默认 50）。
            offset: 分页偏移量（默认 0）。

        Returns:
            查询结果列表。
        """
        # 从全量开始逐步过滤
        results = self._entries[:]

        # 1. 标签过滤
        if tags:
            tag_set = set(tags)
            filtered = []
            for e in results:
                if tag_set & set(e.tags):
                    filtered.append(e)
            results = filtered

        # 2. 字段过滤
        if field_filters:
            for field, value in field_filters.items():
                if field in FILTERABLE_FIELDS:
                    results = [e for e in results if getattr(e, field, "") == value]

        # 3. 全文搜索
        if keyword:
            kw_lower = keyword.lower()
            results = [
                e for e in results if kw_lower in e.insight_summary.lower()
            ]

        # 4. 排序
        if sort_field and sort_field in SORTABLE_FIELDS:
            results = self.sort_by(results, sort_field, ascending=ascending)

        # 5. 分页
        return results[offset : offset + limit]

    # ─── 知识库统计 ────────────────────────────────────────

    def get_statistics(self) -> dict[str, dict[str, int]]:
        """知识库统计。

        按以下维度分别分组计数：
        - method_name: 各策略方法数量
        - symbol: 各标的数量
        - regime: 各市场状态数量
        - timeframe: 各时间框架数量

        Returns:
            四层嵌套的统计字典：
            {
                "method_name": {"ma_cross": 5, "grid": 3, ...},
                "symbol": {"601857": 4, "000001": 2, ...},
                "regime": {"bull": 3, "bear": 1, ...},
                "timeframe": {"1d": 6, "4h": 2, ...},
            }
        """
        stat = {
            "method_name": {},
            "symbol": {},
            "regime": {},
            "timeframe": {},
        }

        for e in self._entries:
            for dim in ("method_name", "symbol", "regime", "timeframe"):
                val = getattr(e, dim, "")
                if val:
                    stat[dim][val] = stat[dim].get(val, 0) + 1

        return stat

    # ─── Top-K 排名 ────────────────────────────────────────

    def get_top_k(
        self,
        field: str,
        k: int = 10,
    ) -> list[Any]:
        """获取某个指标排名前 k 的条目。

        只返回该指标值不为空的条目。
        降序排列（值越大越靠前）。

        Args:
            field: 排序指标字段名。
            k: 返回条目数（默认 10）。

        Returns:
            排名前 k 的条目列表。
        """
        if field not in SORTABLE_FIELDS:
            raise ValueError(
                f"不支持的字段 '{field}'。"
                f"支持的字段: {sorted(SORTABLE_FIELDS)}"
            )

        # 过滤掉该指标为 None 的条目
        valid = [e for e in self._entries if getattr(e, field, None) is not None]
        return self.sort_by(valid, field, ascending=False)[:k]

    # ─── 属性 ──────────────────────────────────────────────

    @property
    def entries(self) -> list[Any]:
        """返回所有已加载的知识条目（只读视图）。"""
        return list(self._entries)

    @property
    def count(self) -> int:
        """知识条目总数。"""
        return len(self._entries)

    def reload(self) -> None:
        """重新加载知识条目 JSON 文件。"""
        self._load_entries()
