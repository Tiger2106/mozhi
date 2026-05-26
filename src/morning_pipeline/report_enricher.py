"""
墨枢 - C1: ReportEnricher
报告增强器 — 将 knowledge.db 知识融入日报管线数据流。

工作流程：
1. 读取 Step1 产出的 structured_analysis.json
2. 从中提取标的符号（scope/标的字段）
3. 查询 KnowledgeService 获取历史知识
4. 生成 knowledge_context_{task_id}.json 供 Step2/Step4 消费

设计原则：
- 零侵入：不修改 structured_analysis 原始文件
- 输出独立：知识上下文以独立文件输出
- 容错：knowledge.db 不可用时优雅跳过（不影响管线）

Author: 墨衡
Created: 2026-05-16T15:52+08:00
"""

from __future__ import annotations

from src.config import SHANGHAI_TZ

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.morning_pipeline.knowledge_service import KnowledgeService, KnowledgeServiceError

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

TZ_CST = SHANGHAI_TZ

REPORT_TYPES = {"morning", "midday"}

# ═══════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════

def _extract_symbols(analysis: dict) -> List[str]:
    """从结构化分析中提取可能的标的概念

    支持从以下字段提取：
    - analysis["signal_mapping"]["symbol"]
    - analysis["operation_framework"]["scope"]
    - analysis["datacollection"]["scope"]
    - 策略信号中的标的字段

    返回 ["601857", "000001.SZ", ...] 或空列表。
    """
    symbols = []

    # 从 signal_mapping
    sm = analysis.get("signal_mapping", {})
    if isinstance(sm, dict):
        sym = sm.get("symbol")
        if sym and isinstance(sym, str):
            symbols.append(sym)

    # 从 scope 字段（可能为字符串或列表）
    for scope_field in ["scope", "symbols", "target"]:
        val = analysis.get(scope_field, analysis.get("datacollection", {}).get(scope_field))
        if isinstance(val, str):
            symbols.append(val)
        elif isinstance(val, list):
            symbols.extend(val)

    # 从 datacollection 根字段
    dc = analysis.get("datacollection", {})
    if isinstance(dc, dict):
        for k in ["symbol", "scope", "target"]:
            v = dc.get(k)
            if isinstance(v, str) and v not in symbols:
                symbols.append(v)
            elif isinstance(v, list):
                for item in v:
                    if item not in symbols:
                        symbols.append(item)

    # 去重，保留顺序
    seen: set = set()
    deduped = []
    for sym in symbols:
        if sym not in seen:
            seen.add(sym)
            deduped.append(sym)

    return deduped

def _normalize_symbol(sym: str) -> str:
    """标的概念标准化

    - 移除 .SH .SZ 后缀后匹配
    - "601857" → "601857"、"601857.SH"、"601857.SZ" 视为同一标的
    """
    bare = sym.replace(".SH", "").replace(".SZ", "")
    return bare

def _expand_symbols(variants: List[str]) -> List[str]:
    """将 short 标的扩展为完整变体，提高匹配率

    例: ["601857"] → ["601857", "601857.SH", "601857.SZ"]
    """
    expanded = []
    for sym in variants:
        bare = _normalize_symbol(sym)
        expanded.append(bare)
        if bare == sym:
            expanded.append(f"{bare}.SH")
            expanded.append(f"{bare}.SZ")
        else:
            expanded.append(bare)
    return list(dict.fromkeys(expanded))  # dedup preserving order

# ═══════════════════════════════════════════════════════════════
# 核心类
# ═══════════════════════════════════════════════════════════════

class ReportEnricher:
    """报告增强器 — 为结构化分析添加知识库上下文

    用法::

        enricher = ReportEnricher()
        ctx = enricher.generate_knowledge_context(structured_analysis_data)
        enricher.write_knowledge_context(output_path, ctx)
    """

    def __init__(self, ks: Optional[KnowledgeService] = None):
        self.ks = ks or KnowledgeService()

    # ── 核心方法 ──────────────────────────────────────

    def generate_knowledge_context(self, analysis: dict) -> dict:
        """从结构化分析数据生成知识上下文

        参数
        ----------
        analysis : dict
            structured_analysis JSON 数据（Step1 产出）

        返回
        -------
        dict
            {
                "status": "READY" | "SKIPPED",
                "task_id": str (optional),
                "knowledge_insights": [...],
                "market_context": {...},
                "strategy_summaries": [...],
                "generated_at": str,
                "enriched_symbols": [...],
            }
        """
        # 提取标的
        raw_symbols = _extract_symbols(analysis)
        enriched_symbols = _expand_symbols(raw_symbols) if raw_symbols else ["601857"]

        # 查询知识库（容错）
        try:
            insights = self.ks.get_knowledge_insights_for_report(enriched_symbols)
            market_ctx = self.ks.get_market_context_summary()
        except KnowledgeServiceError as e:
            return {
                "status": "SKIPPED",
                "error": str(e),
                "knowledge_insights": [],
                "market_context": {},
                "strategy_summaries": [],
                "generated_at": datetime.now(TZ_CST).isoformat(),
            }

        # 生成策略总结（按标准化后的 symbol 去重）
        seen_normalized: set = set()
        strategy_summaries = []
        seen_symbols = set(_normalize_symbol(s) for s in enriched_symbols)
        for insight in insights:
            sym = insight.get("symbol", "?")
            norm = _normalize_symbol(sym)
            if norm in seen_symbols and norm not in seen_normalized:
                seen_normalized.add(norm)
                perf = self.ks.get_strategy_performance_summary(sym)
                if perf:
                    strategy_summaries.append(perf)

        return {
            "status": "READY",
            "task_id": analysis.get("task_id", ""),
            "knowledge_insights": insights,
            "market_context": market_ctx,
            "strategy_summaries": strategy_summaries,
            "enriched_symbols": enriched_symbols,
            "generated_at": datetime.now(TZ_CST).isoformat(),
        }

    # ── 文件读写 ──────────────────────────────────────

    def write_knowledge_context(self, output_path: Union[str, Path], ctx: dict) -> str:
        """写入 knowledge_context 文件

        参数
        ----------
        output_path : str | Path
            输出文件路径
        ctx : dict
            generate_knowledge_context 的返回值

        返回
        -------
        str
            实际写入的文件路径（用于验证）
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(ctx, f, ensure_ascii=False, indent=2)

        return str(output_path)

    def enrich_analysis_file(
        self,
        analysis_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        task_id: Optional[str] = None,
        report_type: str = "morning",
        date: Optional[str] = None,
    ) -> Optional[str]:
        """从文件读入结构化分析，写入 enhanced/knowledge_context 文件

        参数
        ----------
        analysis_path : str | Path
            structured_analysis.json 路径

        返回
        -------
        str | None
            写入文件路径，失败返回 None
        """
        analysis_path = Path(analysis_path)
        if not analysis_path.exists():
            print(f"[ReportEnricher] 文件不存在: {analysis_path}")
            return None

        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                analysis = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[ReportEnricher] 文件读取失败: {e}")
            return None

        # 生成知识上下文
        ctx = self.generate_knowledge_context(analysis)

        # 确定输出路径
        if output_dir is None:
            output_dir = analysis_path.parent

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # task_id 优先级: 参数 > 分析文件中的 task_id > 文件名中提取
        if not task_id:
            task_id = analysis.get("task_id", "")
        if not task_id:
            # 从文件名提取: structured_analysis_{task_id}.json
            match = re.search(r"structured_analysis_(.+)\.json", analysis_path.name)
            if match:
                task_id = match.group(1)
            else:
                task_id = "unknown"

        # 日期: 从 analysis 或参数
        if not date:
            date = analysis.get("date", datetime.now(TZ_CST).strftime("%Y%m%d"))

        output_path = output_dir / f"knowledge_context_{task_id}.json"
        written = self.write_knowledge_context(output_path, ctx)
        print(f"[ReportEnricher] 知识上下文已写入: {written}")
        print(f"  → 知识点: {len(ctx.get('knowledge_insights', []))}")
        print(f"  → 策略总结: {len(ctx.get('strategy_summaries', []))}")
        print(f"  → 标的: {ctx.get('enriched_symbols', [])}")
        return written

# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def enrich_report(
    analysis_path: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
    task_id: Optional[str] = None,
    report_type: str = "morning",
    date: Optional[str] = None,
) -> Optional[str]:
    """快捷入口"""
    enricher = ReportEnricher()
    return enricher.enrich_analysis_file(
        analysis_path=analysis_path,
        output_dir=output_dir,
        task_id=task_id,
        report_type=report_type,
        date=date,
    )

# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # 用法: python -m morning_pipeline.report_enricher <analysis_path>
    if len(sys.argv) > 1:
        result = enrich_report(sys.argv[1])
        if result:
            print(f"[Done] 知识上下文已写入: {result}")
        else:
            print("[FAIL] 增强失败")
    else:
        # 无参时：用模拟数据进行自检
        print("=== ReportEnricher 自检 ===")

        sample_analysis = {
            "status": "READY",
            "task_id": "morning_report_20260516_step1",
            "step": 1,
            "signal_mapping": {
                "symbol": "601857",
                "action": "BUY",
                "confidence": "中",
            },
            "data_validation": {"passed": True, "conflicts": []},
            "core_logic": "油价短期波动不改上行趋势",
            "risk_assessment": {
                "level": "中",
                "primary_risks": ["油价回落"],
            },
            "operation_framework": {
                "aggressive": "做多 601857",
                "balanced": "持仓观察",
                "conservative": "减仓",
            },
            "date": "20260516",
        }

        enricher = ReportEnricher()
        ctx = enricher.generate_knowledge_context(sample_analysis)
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
        print("\nReportEnricher 自检完成 ✅")
