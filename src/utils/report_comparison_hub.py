# -*- coding: utf-8 -*-
"""
report_comparison_hub.py — 跨报告比较工具

横向比较 P 系列报告（原始版 + MODIFIED 版）的结论一致性、版本差异、
以及 Q9a Q_FAILURES 分布。

支持三种比较维度:
  1. compare_by_strategy(strategy_name)
     — 同一策略在不同报告中的结论一致性检测
  2. compare_versions(report_base)
     — 原始版 vs MODIFIED 版差异对比
  3. q_failure_distribution()
     — Q9a Q_FAILURES 记录在各报告中的分布

输入数据源:
  - reports/research/ 下的 P*_MODIFIED.md 文件（约 8 份）
  - reports/research/ 下的对应 P*.md 原始文件（约 13 份）
  - q_failures/q_failures.db (Q9a Q_FAILURES 数据库)

设计原则:
  - 解析 Markdown 中的关键维度和结论（非全文语义分析）
  - 通过结构化标记（表格关键数字、Observation 块标记）提取可比指标
  - 逐项比较：夏普比率、总收益率、年化收益率、最大回撤、交易次数、结论方向
  - 版本差异：同一报告原始版与 MODIFIED 版之间的数字变化

作者：墨衡 (moheng)
创建时间：2026-05-19 16:46 GMT+8
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from q9a_failure_registry import Q9aFailureRegistry


# ============================================================
# 时区与路径
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # mozhi_platform
_REPORTS_DIR = _PROJECT_ROOT / "reports" / "research"


# ============================================================
# 提取的数据结构
# ============================================================

@dataclass
class ReportMetric:
    """从报告中提取的可量化指标"""
    total_return_pct: Optional[float] = None      # 总收益率 (%)
    annualized_return_pct: Optional[float] = None  # 年化收益率 (%)
    sharpe_ratio: Optional[float] = None           # 夏普比率
    max_drawdown_pct: Optional[float] = None       # 最大回撤 (%)
    win_rate_pct: Optional[float] = None           # 胜率 (%)
    n_trades: Optional[int] = None                 # 交易次数
    n_days: Optional[int] = None                   # 回测天数
    trading_years: Optional[float] = None           # 回测年数

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ReportConclusion:
    """报告结论摘要"""
    strategy_id: str          # 策略标识（如 "grid_601857_n5")
    signal: str               # 信号方向: "BULLISH" / "BEARISH" / "NEUTRAL" / "MIXED"
    confidence: str           # 置信度: "HIGH" / "MEDIUM" / "LOW"
    key_risk: str             # 核心风险
    verdict: str              # 总体结论（抽取最后一段的判定语句）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedReport:
    """解析后的结构化报告摘要"""
    report_name: str          # 文件名（不含 .md）
    report_path: str          # 完整路径
    version_tag: str          # "ORIGINAL" 或 "MODIFIED"
    base_name: str            # 基础报告名（不含 v2/_MODIFIED 后缀）
    strategy_id: str          # 策略 ID
    metrics: ReportMetric
    conclusion: Optional[ReportConclusion] = None
    sections: list[str] = field(default_factory=list)  # 报告中的主要章节标题
    observation_blocks: int = 0     # Observation 块数量
    speculative_blocks: int = 0     # Speculative 块数量
    warnings: list[str] = field(default_factory=list)  # 报告中的警告标记

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConsistencyResult:
    """同一策略跨报告的结论一致性检测结果"""
    strategy_id: str
    n_reports: int
    signals: list[str]
    signal_consensus: str           # "AGREED" / "DISAGREED" / "PARTIAL"
    confidence_scores: list[str]
    metric_variance: dict           # 各指标在不同报告中的差异统计
    conflict_details: list[str]     # 具体冲突描述


@dataclass
class VersionDiff:
    """原始版 vs MODIFIED 版的差异"""
    report_base: str              # 基础报告名
    original: Optional[ParsedReport]
    modified: Optional[ParsedReport]
    metric_diffs: dict[str, Any]  # 指标变化
    same_verdict: bool            # 结论是否一致
    added_sections: list[str]     # MODIFIED 版新增的章节
    removed_sections: list[str]   # MODIFIED 版移除的章节
    warning_diffs: list[str]      # 警告标记差异


@dataclass
class FailureDistribution:
    """Q9a Q_FAILURES 分布统计"""
    by_report: dict[str, int]          # report_id → count
    by_failure_type: dict[str, int]    # failure_type → count
    by_strategy: dict[str, int]        # strategy_id → count
    total_failures: int
    most_common_report: str
    most_common_type: str
    most_common_strategy: str


# ============================================================
# Markdown 解析器
# ============================================================

class ReportParser:
    """P 系列 Markdown 报告的解析器

    从报告的 Markdown 文本中提取结构化信息：
    指标数字、表格、警告块、章节结构。
    """

    # 常见的指标模式（Markdown 表格中）
    _METRIC_PATTERNS: dict[str, list[re.Pattern]] = {
        "total_return_pct": [
            re.compile(r"(?:总[^]*?收(?:益|益率)|总收益率)[^:]*?[:：]\s*([+-]?\d+\.?\d*)%"),
            re.compile(r"\|\s*(?:总收益(?:率)?|Total Return)\s*\|\s*([+-]?\d+\.?\d*)%"),
            re.compile(r"总收益[^%]*?([+-]?\d+\.?\d*)%"),
        ],
        "annualized_return_pct": [
            re.compile(r"(?:年化[^]*?收(?:益|益率)|年化收益率)[^:]*?[:：]\s*([+-]?\d+\.?\d*)%"),
            re.compile(r"\|\s*(?:年化(?:收益(?:率)?)|Annual Return)\s*\|\s*([+-]?\d+\.?\d*)%"),
            re.compile(r"年化收益率[^%]*?([+-]?\d+\.?\d*)%"),
            re.compile(r"年化[^%]*?([+-]?\d+\.?\d*)%"),
        ],
        "sharpe_ratio": [
            re.compile(r"(?:夏普[^]*?比(?:率)?|Sharpe)[^:]*?[:：]?\s*([+-]?\d+\.?\d*)"),
            re.compile(r"\|\s*(?:夏普比率|Sharpe)\s*\|\s*([+-]?\d+\.?\d*)"),
            re.compile(r"夏普[^]*?([+-]?\d+\.\d+)"),
        ],
        "max_drawdown_pct": [
            re.compile(r"(?:最大回撤|Max DD|Max Drawdown)[^:]*?[:：]?\s*([+-]?\d+\.?\d*)%"),
            re.compile(r"\|\s*(?:最大回撤|Max Drawdown|回撤率)\s*\|\s*([+-]?\d+\.?\d*)%"),
            re.compile(r"最大回撤[^%]*?([+-]?\d+\.?\d*)%"),
        ],
        "win_rate_pct": [
            re.compile(r"(?:胜率|Win Rate)[^:]*?[:：]?\s*(\d+\.?\d*)%"),
            re.compile(r"\|\s*(?:胜率|Win Rate)\s*\|\s*(\d+\.?\d*)%"),
        ],
        "n_trades": [
            re.compile(r"(?:交易[次数笔]|Trades)[^:]*?[:：]?\s*(\d+)"),
            re.compile(r"\|\s*(?:交易[次数笔]|Trades)\s*\|\s*(\d+)"),
            re.compile(r"(\d+)\s*(?:笔|次)[^]*?交易"),
            re.compile(r"n\s*=\s*(\d+)"),
        ],
        "n_days": [
            re.compile(r"(?:(\d+)\s*(?:个|个交易|个日历)\s*(?:交易日|日|天))"),
            re.compile(r"(\d+)\s*(?:个|个)?\s*(?:交易日|日|天)"),
            re.compile(r"(\d+)\s*days?"),
        ],
    }

    # 标准信号/结论方向关键词
    _SIGNAL_PATTERNS = [
        ("BULLISH", re.compile(r"(?:正向|看多|上涨|积极|买入|做多|bullish|positive)", re.IGNORECASE)),
        ("BEARISH", re.compile(r"(?:负向|看空|下跌|消极|卖出|做空|bearish|negative)", re.IGNORECASE)),
        ("NEUTRAL", re.compile(r"(?:中性|观望|谨慎|neutral|cautious|观望|横盘)", re.IGNORECASE)),
    ]

    # 置信度关键词
    _CONFIDENCE_PATTERNS = [
        ("HIGH", re.compile(r"置信度[^。]*?(?:高|强|显著|强烈|明确)")),
        ("MEDIUM", re.compile(r"置信度[^。]*?(?:中|中等|一般|有限)")),
        ("LOW", re.compile(r"置信度[^。]*?(?:低|不足|弱|不确定|不显著)")),
    ]

    # 警告标记模式
    _WARNING_PATTERNS = [
        re.compile(r"⚠.*?样本量警告"),
        re.compile(r"重要限制"),
        re.compile(r"不具有统计显著性"),
        re.compile(r"⚠.*?(?:核心发现|发现)"),
        re.compile(r"⚠.*?(?:数据不足|样本不足)"),
    ]

    @classmethod
    def parse(cls, filepath: str | Path) -> ParsedReport:
        """解析单个报告文件

        Parameters
        ----------
        filepath : str | Path
            Markdown 报告路径

        Returns
        -------
        ParsedReport
            解析后的结构化报告
        """
        path = Path(filepath)
        report_name = path.stem
        content = path.read_text(encoding="utf-8")

        # 版本标签
        version_tag = "MODIFIED" if "_MODIFIED" in report_name else "ORIGINAL"

        # 基础名称（去掉 v2 / _MODIFIED 等后缀）
        base_name = report_name
        base_name = re.sub(r"_v\d+$", "", base_name)
        base_name = re.sub(r"_MODIFIED$", "", base_name)

        # 策略 ID（从文件名推断）
        strategy_id = cls._infer_strategy_id(report_name)

        # 提取指标
        metrics = cls._extract_metrics(content)

        # 提取章节
        sections = cls._extract_sections(content)

        # 统计 Observation/Speculative 块
        observation_blocks = len(re.findall(r"> 📊 \*\*Empirical\*\*", content))
        speculative_blocks = len(re.findall(r"> 🔮 \*\*Speculative\*\*", content))

        # 提取警告
        warnings = cls._extract_warnings(content)

        # 提取结论
        conclusion = cls._extract_conclusion(report_name, content)

        return ParsedReport(
            report_name=report_name,
            report_path=str(path.resolve()),
            version_tag=version_tag,
            base_name=base_name,
            strategy_id=strategy_id,
            metrics=metrics,
            conclusion=conclusion,
            sections=sections,
            observation_blocks=observation_blocks,
            speculative_blocks=speculative_blocks,
            warnings=warnings,
        )

    @classmethod
    def _infer_strategy_id(cls, report_name: str) -> str:
        """从文件名推断策略 ID"""
        # 典型格式: P1_return_decomposition_601857_20260518_v2_MODIFIED
        # 提取 601857
        code_match = re.search(r"(\d{6})", report_name)
        if code_match:
            code = code_match.group(1)
            # 推断策略类型
            if "grid" in report_name.lower() or any(
                p in report_name for p in ["P1", "P2", "P3", "P4", "P5", "P6"]
            ):
                return f"grid_{code}"
            return f"strategy_{code}"

        # 回退：文件名本身
        return report_name.replace("_MODIFIED", "").replace("_v2", "")

    @classmethod
    def _extract_metrics(cls, content: str) -> ReportMetric:
        """从内容中提取指标"""
        metrics = ReportMetric()
        for attr, patterns in cls._METRIC_PATTERNS.items():
            for pat in patterns:
                match = pat.search(content)
                if match:
                    try:
                        value = float(match.group(1))
                        setattr(metrics, attr, value)
                        break  # 已匹配到该指标
                    except (ValueError, IndexError):
                        continue
        return metrics

    @classmethod
    def _extract_sections(cls, content: str) -> list[str]:
        """提取章节标题（## 级别）"""
        return re.findall(r"^##\s+(.+)$", content, re.MULTILINE)

    @classmethod
    def _extract_warnings(cls, content: str) -> list[str]:
        """提取警告标记"""
        warnings = []
        for pat in cls._WARNING_PATTERNS:
            match = pat.search(content)
            if match:
                # 提取警告前后的关键文本
                start = max(0, match.start() - 100)
                end = min(len(content), match.end() + 200)
                context = content[start:end].strip()
                warnings.append(context[:200])
        return warnings

    @classmethod
    def _extract_conclusion(cls, report_name: str, content: str) -> Optional[ReportConclusion]:
        """提取报告的结论"""
        strategy_id = cls._infer_strategy_id(report_name)
        text_lower = content.lower()

        # 信号方向: 用计数法加权
        signal_scores: dict[str, int] = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
        for signal_name, pattern in cls._SIGNAL_PATTERNS:
            matches = pattern.findall(text_lower)
            signal_scores[signal_name] += len(matches)

        # 取得分最高的信号
        signal = max(signal_scores, key=signal_scores.get)

        # 置信度
        confidence_scores: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for conf_name, pattern in cls._CONFIDENCE_PATTERNS:
            matches = pattern.findall(text_lower)
            confidence_scores[conf_name] += len(matches)
        confidence = max(confidence_scores, key=confidence_scores.get)

        # 核心风险（取最后一个带"风险"或"风险"的段落句子）
        risk_sentences = re.findall(
            r"[^。]*?(?:核心发现|关键发现|风险|risk|注意|注意)[^。]*。",
            content,
        )
        key_risk = risk_sentences[-1].strip() if risk_sentences else "N/A"

        # 总体结论（取最后一段非空文本或核心发现）
        verdict_sentences = re.findall(
            r"> 📊 \*\*Empirical\*\*[^。]*。[^。]*。",
            content,
        )
        verdict = verdict_sentences[-1] if verdict_sentences else "See report body"

        return ReportConclusion(
            strategy_id=strategy_id,
            signal=signal,
            confidence=confidence,
            key_risk=key_risk,
            verdict=verdict.strip()[:200],
        )


# ============================================================
# 核心比较器
# ============================================================

class ReportComparisonHub:
    """跨报告比较中心

    管理 P 系列报告的加载、索引、三种比较维度。

    Parameters
    ----------
    reports_dir : str | Path | None
        报告目录路径（默认为 reports/research/）
    """

    def __init__(self, reports_dir: Optional[str | Path] = None) -> None:
        self._reports_dir = Path(reports_dir) if reports_dir else _REPORTS_DIR
        self._reports: dict[str, ParsedReport] = {}
        self._loaded = False

    def load_all(self) -> int:
        """加载目录下所有 P*.md 报告

        Returns
        -------
        int
            已加载的报告数量
        """
        self._reports.clear()
        for fpath in sorted(self._reports_dir.glob("P*.md")):
            try:
                report = ReportParser.parse(fpath)
                self._reports[report.report_name] = report
            except Exception as exc:
                # 解析失败时跳过，不阻塞整体加载
                import logging
                logging.warning("解析失败: %s — %s", fpath.name, exc)
                continue

        self._loaded = True
        return len(self._reports)

    def load_single(self, filepath: str | Path) -> ParsedReport:
        """加载并解析单个报告文件

        Parameters
        ----------
        filepath : str | Path
            报告路径

        Returns
        -------
        ParsedReport
            解析后的报告
        """
        report = ReportParser.parse(filepath)
        self._reports[report.report_name] = report
        self._loaded = True
        return report

    @property
    def reports(self) -> dict[str, ParsedReport]:
        """获取所有已加载的报告"""
        if not self._loaded:
            self.load_all()
        return dict(self._reports)

    @property
    def loaded_count(self) -> int:
        return len(self._reports)

    def get_by_name(self, name: str) -> Optional[ParsedReport]:
        """按文件名获取报告"""
        return self.reports.get(name)

    def get_versions(self, base_name: str) -> tuple[Optional[ParsedReport], Optional[ParsedReport]]:
        """获取同一报告的原始版和 MODIFIED 版

        Parameters
        ----------
        base_name : str
            基础报告名（如 "P1_return_decomposition_601857_20260518"）

        Returns
        -------
        tuple[ParsedReport | None, ParsedReport | None]
            (original, modified)
        """
        all_reports = self.reports
        original: Optional[ParsedReport] = None
        modified: Optional[ParsedReport] = None

        for rname, rpt in all_reports.items():
            if rpt.base_name == base_name:
                if rpt.version_tag == "MODIFIED":
                    modified = rpt
                else:
                    original = rpt

        # 如果原始版没找到，检查确切名称
        if original is None and base_name in all_reports:
            original = all_reports[base_name]

        return original, modified

    # ==================== 维度 1: 策略比较 ====================

    def compare_by_strategy(self, strategy_name: str) -> list[ConsistencyResult]:
        """按策略 ID 比较跨报告的结论一致性

        找出所有与 strategy_name 相关的报告（通过文件名匹配），
        比较它们的计量指标和结论方向。

        Parameters
        ----------
        strategy_name : str
            策略名称/代码（如 "601857", "grid"）

        Returns
        -------
        list[ConsistencyResult]
            每个匹配策略的跨报告一致性结果
        """
        # 找出与该策略相关的报告
        matching: dict[str, list[ParsedReport]] = {}  # strategy_id → reports

        for rname, rpt in self.reports.items():
            if strategy_name.lower() in rpt.strategy_id.lower() or \
               strategy_name.lower() in rname.lower():
                sid = rpt.strategy_id
                matching.setdefault(sid, []).append(rpt)

        results: list[ConsistencyResult] = []

        for sid, reports_list in matching.items():
            n = len(reports_list)
            if n < 2:
                # 单一报告不足以做比较
                continue

            signals = [r.conclusion.signal for r in reports_list if r.conclusion]
            confidences = [r.conclusion.confidence for r in reports_list if r.conclusion]

            # 信号一致性判定
            if not signals:
                signal_consensus = "NO_DATA"
            elif len(set(signals)) == 1:
                signal_consensus = "AGREED"
            elif len(set(signals)) == 2:
                signal_consensus = "PARTIAL"
            else:
                signal_consensus = "DISAGREED"

            # 指标方差
            metric_variance = self._compute_metric_variance(reports_list)

            # 具体冲突描述
            conflicts: list[str] = []
            if signal_consensus != "AGREED":
                conflict_signals = [
                    f"{r.report_name}: {r.conclusion.signal}" if r.conclusion else f"{r.report_name}: 无结论"
                    for r in reports_list
                ]
                conflicts.append(f"信号方向不一致: {'; '.join(conflict_signals)}")

            results.append(ConsistencyResult(
                strategy_id=sid,
                n_reports=n,
                signals=signals,
                signal_consensus=signal_consensus,
                confidence_scores=confidences,
                metric_variance=metric_variance,
                conflict_details=conflicts,
            ))

        return results

    def _compute_metric_variance(
        self, reports_list: list[ParsedReport],
    ) -> dict[str, Any]:
        """计算同一策略下多份报告的指标差异统计"""
        numeric_fields = [
            "total_return_pct", "annualized_return_pct",
            "sharpe_ratio", "max_drawdown_pct",
            "n_trades", "n_days",
        ]

        result: dict[str, Any] = {}
        for field in numeric_fields:
            values: list[tuple[str, float]] = []
            for r in reports_list:
                v = getattr(r.metrics, field, None)
                if v is not None:
                    values.append((r.report_name, float(v)))

            if len(values) >= 2:
                nums = [v for _, v in values]
                mean_val = sum(nums) / len(nums)
                variance = sum((x - mean_val) ** 2 for x in nums) / (len(nums) - 1) if len(nums) > 1 else 0.0
                result[field] = {
                    "values": dict(values),
                    "mean": round(mean_val, 4),
                    "variance": round(variance, 4),
                    "std": round(variance ** 0.5, 4),
                    "range": round(max(nums) - min(nums), 4),
                    "min": round(min(nums), 4),
                    "max": round(max(nums), 4),
                    "n_reports": len(values),
                }
            elif len(values) == 1:
                result[field] = {
                    "values": dict(values),
                    "note": "仅单一报告提供此指标，无法计算差异",
                }
            else:
                result[field] = {
                    "values": {},
                    "note": "无报告提供此指标",
                }

        return result

    # ==================== 维度 2: 版本比较 ====================

    def compare_versions(self, report_base: str) -> Optional[VersionDiff]:
        """比较原始版和 MODIFIED 版的差异

        将同一基础报告的原始版本与修改版本进行逐项对比。

        Parameters
        ----------
        report_base : str
            基础报告名，如 "P1_return_decomposition_601857_20260518"

        Returns
        -------
        VersionDiff | None
            版本差异详情（未找到配对的任一版本时返回 None）
        """
        original, modified = self.get_versions(report_base)

        if original is None and modified is None:
            return None

        # 指标差异
        metric_diffs: dict[str, Any] = {}
        numeric_fields = [
            "total_return_pct", "annualized_return_pct",
            "sharpe_ratio", "max_drawdown_pct",
            "win_rate_pct", "n_trades", "n_days",
        ]

        for field in numeric_fields:
            orig_val = getattr(original.metrics, field, None) if original else None
            mod_val = getattr(modified.metrics, field, None) if modified else None

            if orig_val is not None and mod_val is not None:
                delta = round(mod_val - orig_val, 4)
                delta_pct = round(delta / abs(orig_val) * 100, 2) if orig_val != 0 else None
                metric_diffs[field] = {
                    "original": orig_val,
                    "modified": mod_val,
                    "delta": delta,
                    "delta_pct": delta_pct,
                }
            elif orig_val is not None and mod_val is None:
                metric_diffs[field] = {"original": orig_val, "modified": None, "note": "MODIFIED版未提取此指标"}
            elif orig_val is None and mod_val is not None:
                metric_diffs[field] = {"original": None, "modified": mod_val, "note": "原始版未提取此指标"}

        # 结论一致性
        same_verdict = True
        if original and modified and original.conclusion and modified.conclusion:
            same_verdict = (
                original.conclusion.signal == modified.conclusion.signal
                and original.conclusion.confidence == modified.conclusion.confidence
            )

        # 章节新增/移除
        orig_sections = set(original.sections) if original else set()
        mod_sections = set(modified.sections) if modified else set()
        added_sections = sorted(mod_sections - orig_sections)
        removed_sections = sorted(orig_sections - mod_sections)

        # 警告差异
        warning_diffs: list[str] = []
        if original and modified:
            orig_warns = set(original.warnings)
            mod_warns = set(modified.warnings)
            for w in mod_warns - orig_warns:
                warning_diffs.append(f"[新增] {w[:100]}")
            for w in orig_warns - mod_warns:
                warning_diffs.append(f"[移除] {w[:100]}")

        return VersionDiff(
            report_base=report_base,
            original=original,
            modified=modified,
            metric_diffs=metric_diffs,
            same_verdict=same_verdict,
            added_sections=added_sections,
            removed_sections=removed_sections,
            warning_diffs=warning_diffs,
        )

    def compare_all_versions(self) -> list[VersionDiff]:
        """递归比较所有有版本对的报告

        Returns
        -------
        list[VersionDiff]
            所有可比较的版本对差异列表
        """
        # 收集各基础名称
        base_names = set()
        for rname in self.reports:
            # P1_return_decomposition_601857_20260518_v2_MODIFIED
            # → base: P1_return_decomposition_601857_20260518
            base = rname
            base = re.sub(r"_v\d+$", "", base)
            base = re.sub(r"_MODIFIED$", "", base)
            base_names.add(base)

        diffs: list[VersionDiff] = []
        for base in sorted(base_names):
            diff = self.compare_versions(base)
            if diff is not None and diff.original is not None and diff.modified is not None:
                diffs.append(diff)

        return diffs

    # ==================== 维度 3: Q9a 失败分布 ====================

    def q_failure_distribution(self) -> FailureDistribution:
        """分析 Q9a Q_FAILURES 在各报告中的分布

        查询 Q9a Q_FAILURES 数据库，统计失败记录按报告、
        failure_type、strategy_id 的分布。

        需要 q_failures 数据库已存在。若数据库不可用，
        返回空分布统计。

        Returns
        -------
        FailureDistribution
            失败分布统计
        """
        try:
            registry = Q9aFailureRegistry()
            top_types = registry.top_failure_types(10)
            records = registry.list_failures(limit=10000)
            registry.close()
        except Exception:
            # 数据库不可用
            return FailureDistribution(
                by_report={}, by_failure_type={}, by_strategy={},
                total_failures=0,
                most_common_report="", most_common_type="", most_common_strategy="",
            )

        by_report: dict[str, int] = {}
        by_failure_type: dict[str, int] = {}
        by_strategy: dict[str, int] = {}

        for rec in records:
            # 按 report_id
            rid = rec.report_id or "unknown"
            by_report[rid] = by_report.get(rid, 0) + 1

            # 按 failure_type
            ft = rec.failure_type.value if hasattr(rec.failure_type, "value") else str(rec.failure_type)
            by_failure_type[ft] = by_failure_type.get(ft, 0) + 1

            # 按 strategy_id
            sid = rec.strategy_id
            by_strategy[sid] = by_strategy.get(sid, 0) + 1

        def _most_common(d: dict[str, int]) -> str:
            return max(d, key=d.get) if d else ""

        return FailureDistribution(
            by_report=by_report,
            by_failure_type=by_failure_type,
            by_strategy=by_strategy,
            total_failures=len(records),
            most_common_report=_most_common(by_report),
            most_common_type=_most_common(by_failure_type),
            most_common_strategy=_most_common(by_strategy),
        )

    # ==================== 报告清单与导出 ====================

    def list_reports(
        self, version: Optional[str] = None,
    ) -> list[ParsedReport]:
        """列出所有已加载的报告

        Parameters
        ----------
        version : str | None
            筛选版本: "ORIGINAL", "MODIFIED", None=全部

        Returns
        -------
        list[ParsedReport]
        """
        reports = self.reports.values()
        if version:
            return [r for r in reports if r.version_tag == version]
        return list(reports)

    def export_summary_to_json(self, output_path: str | Path) -> None:
        """导出所有报告的解析摘要到 JSON 文件

        Parameters
        ----------
        output_path : str | Path
            输出路径
        """
        data = {
            "export_time": datetime.now(_TZ_CST).isoformat(),
            "n_reports": self.loaded_count,
            "reports": {
                name: rpt.to_dict() for name, rpt in self.reports.items()
            },
        }
        Path(output_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ============================================================
# CLI 使用入口
# ============================================================

def main() -> None:
    """CLI 入口：提供三种比较命令"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Cross-report comparison hub for P-series reports"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["list", "compare", "versions", "failures", "export"],
        default="list",
        help="Command: list / compare / versions / failures / export",
    )
    parser.add_argument(
        "--strategy", "-s",
        default="601857",
        help="Strategy code/name for compare_by_strategy (default: 601857)",
    )
    parser.add_argument(
        "--report", "-r",
        help="Base report name for compare_versions",
    )
    parser.add_argument(
        "--output", "-o",
        default="",
        help="Export output path (for 'export' command)",
    )

    args = parser.parse_args()
    hub = ReportComparisonHub()
    hub.load_all()

    if args.command == "list":
        print(f"\n=== 已加载 {hub.loaded_count} 份报告 ===")
        for ver in ["ORIGINAL", "MODIFIED"]:
            print(f"\n--- {ver} ---")
            for rpt in hub.list_reports(version=ver):
                m = rpt.metrics
                print(f"  {rpt.report_name}")
                print(f"    策略: {rpt.strategy_id}, 交易数: {m.n_trades}, 夏普: {m.sharpe_ratio}")

    elif args.command == "compare":
        results = hub.compare_by_strategy(args.strategy)
        print(f"\n=== 策略 '{args.strategy}' 一致性比较 ===")
        for r in results:
            print(f"\n策略: {r.strategy_id} ({r.n_reports} 份报告)")
            print(f"  信号: {r.signals} → {r.signal_consensus}")
            print(f"  置信度: {r.confidence_scores}")
            if r.conflict_details:
                for c in r.conflict_details:
                    print(f"  ⚠ {c}")
            for field, stats in r.metric_variance.items():
                if "std" in stats:
                    print(f"  {field}: 均值={stats['mean']}, 标准差={stats['std']}, n={stats['n_reports']}")

    elif args.command == "versions":
        if args.report:
            diff = hub.compare_versions(args.report)
            if diff:
                print(f"\n=== 版本差异: {diff.report_base} ===")
                print(f"  结论一致: {diff.same_verdict}")
                if diff.added_sections:
                    print(f"  新增章节: {', '.join(diff.added_sections)}")
                if diff.removed_sections:
                    print(f"  移除章节: {', '.join(diff.removed_sections)}")
                print(f"\n  指标差异:")
                for field, d in diff.metric_diffs.items():
                    print(f"    {field}: {d}")
                if diff.warning_diffs:
                    print(f"\n  警告变化:")
                    for w in diff.warning_diffs:
                        print(f"    {w}")
            else:
                print(f"未找到 {args.report} 的配对版本")
        else:
            diffs = hub.compare_all_versions()
            print(f"\n=== 全部版本差异 ({len(diffs)} 对) ===")
            for d in diffs:
                status = "✅" if d.same_verdict else "❌"
                delta_str = "; ".join(
                    f"{f}: {v['delta']}" for f, v in d.metric_diffs.items()
                    if isinstance(v, dict) and "delta" in v and v["delta"] != 0
                )
                print(f"  {status} {d.report_base} — {delta_str}" if delta_str else f"  {status} {d.report_base} (无指标变化)")

    elif args.command == "failures":
        dist = hub.q_failure_distribution()
        print(f"\n=== Q9a Q_FAILURES 分布 ===")
        print(f"  总记录: {dist.total_failures}")
        print(f"  最常见策略: {dist.most_common_strategy}")
        print(f"  最常见类型: {dist.most_common_type}")
        print(f"  最常见报告: {dist.most_common_report}")
        print(f"\n  按失败类型:")
        for ft, cnt in sorted(dist.by_failure_type.items(), key=lambda x: -x[1])[:5]:
            print(f"    {ft}: {cnt}")
        print(f"\n  按策略:")
        for sid, cnt in sorted(dist.by_strategy.items(), key=lambda x: -x[1])[:5]:
            print(f"    {sid}: {cnt}")

    elif args.command == "export":
        output = args.output or str(_PROJECT_ROOT / "reports" / "research" / "_report_export.json")
        hub.export_summary_to_json(output)
        print(f"已导出 {hub.loaded_count} 份报告摘要至: {output}")


if __name__ == "__main__":
    main()
