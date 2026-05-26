#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S005 — 合规受益链策略模块

策略定位
--------
利用合规评分框架识别合规优势企业，通过 BFS 三级传导链
追踪监管趋严背景下的受益传导路径，结合催化剂信号库
形成事件驱动交易信号。

模块架构
--------
┌─────────────────────────────────────────────────────┐
│                    S005 Orchestrator                 │
├──────────┬──────────┬──────────┬────────────────────┤
│ 合规评分  │ BFS传导  │ 催化剂    │ 输出格式对齐       │
│ (5维度)   │ (3级链)  │ (信号库)  │ (S002规范)         │
└──────────┴──────────┴──────────┴────────────────────┘

子模块
------
- compliance_scorer.py : 五维度合规评分计算框架
- bfs_chain.py         : BFS三级传导链引擎
- catalyst_signal.py   : 催化剂信号库框架
- config.py            : 配置常量与默认参数

格式对齐
--------
- S002 v1.0 (2026-05-25 墨衡发布): 输出 mismatch_heatmap_{date}.json
  → {date, symbol, channel_pair, mismatch_intensity, z_score}

外部依赖
--------
- S004 (Phase1, 墨衡 5/29 交付): grey_routes_{date}.json
  → 读取 compliance_flag 字段映射为灰色关联度评分
  → 接口格式: {route_id, supply_label, demand_label, route_topology, flow_volume, compliance_flag}

作者: 墨萱 (moxuan)
创建时间: 2026-05-25 10:48 +08:00
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from src.strategies.S005.config import S005Config, MISMATCH_HEATMAP_CONFIG
from src.strategies.S005.compliance_scorer import ComplianceScorer, ComplianceReport
from src.strategies.S005.bfs_chain import BFSChainEngine, BFSChainReport
from src.strategies.S005.catalyst_signal import CatalystSignalLibrary, CatalystMatchReport

logger = logging.getLogger("S005")


class S005Orchestrator:
    """S005 策略编排器 — 协调各子模块完成完整链路"""

    def __init__(self, config: Optional[S005Config] = None):
        self.config = config or S005Config()
        self.scorer = ComplianceScorer(config=self.config)
        self.bfs_engine = BFSChainEngine(config=self.config)
        self.catalyst_lib = CatalystSignalLibrary(config=self.config)

    # ── 完整链路 ────────────────────────────────────────

    def run_pipeline(
        self,
        run_date: date | None = None,
        universe: list[str] | None = None,
    ) -> dict[str, Any]:
        """运行完整 S005 合规受益链流水线

        Parameters
        ----------
        run_date : date | None
            运行日期（默认今天）
        universe : list[str] | None
            标的池（默认 None → 全市场）

        Returns
        -------
        dict
            {
                "run_info": {...},
                "compliance": ComplianceReport | dict,
                "bfs": BFSChainReport | dict,
                "catalyst": CatalystMatchReport | dict,
            }
        """
        run_date = run_date or date.today()
        logger.info("=" * 60)
        logger.info(f"[S005] 合规受益链流水线启动 | 运行日期: {run_date}")
        logger.info("=" * 60)

        # ── Stage 1: 合规评分 ──
        logger.info("[S005/Stage1] 合规评分五维度计算开始 ...")
        compliance_result = self.scorer.score_all(
            run_date=run_date,
            universe=universe,
        )
        logger.info(f"[S005/Stage1] 完成: {getattr(compliance_result, 'scored_count', 0)} 只标定评分")

        # ── Stage 2: BFS传导链 ──
        logger.info("[S005/Stage2] BFS三级传导链构建开始 ...")
        bfs_result = self.bfs_engine.build_chain(
            run_date=run_date,
            compliance_scores=compliance_result,
        )
        logger.info(f"[S005/Stage2] 完成: {getattr(bfs_result, 'total_nodes', 0)} 个节点 | "
                    f"种子节点: {getattr(bfs_result, 'seed_count', 0)}")

        # ── Stage 3: 催化剂匹配 ──
        logger.info("[S005/Stage3] 催化剂信号匹配开始 ...")
        catalyst_result = self.catalyst_lib.match_all(
            run_date=run_date,
            bfs_report=bfs_result,
        )
        logger.info(f"[S005/Stage3] 完成: {getattr(catalyst_result, 'matched_count', 0)} 个匹配信号")

        # ── S002 Mismatch Heatmap 输出 ──
        self.save_mismatch_heatmap(
            compliance_report=compliance_result,
            run_date=run_date,
        )

        # ── 汇总 ──
        report = self._build_report(
            run_date=run_date,
            compliance=compliance_result,
            bfs=bfs_result,
            catalyst=catalyst_result,
        )
        logger.info("[S005] 流水线完成 ✅")
        return report

    # ── 报告构建 ────────────────────────────────────────

    def _build_report(
        self,
        run_date: date,
        compliance: ComplianceReport | Any,
        bfs: BFSChainReport | Any,
        catalyst: CatalystMatchReport | Any,
    ) -> dict[str, Any]:
        """构建统一输出报告"""
        return {
            "meta": {
                "strategy": "S005",
                "strategy_name": "合规受益链",
                "run_date": run_date.isoformat(),
                "generated_at": datetime.now().isoformat(),
                "version": "1.0.0",
            },
            "compliance": self._serialize_compliance(compliance),
            "bfs_chain": self._serialize_bfs(bfs),
            "catalyst": self._serialize_catalyst(catalyst),
        }

    @staticmethod
    def _serialize_compliance(compliance: ComplianceReport | Any) -> dict:
        """合规评分序列化"""
        if isinstance(compliance, dict):
            return compliance
        return {
            "scored_count": getattr(compliance, "scored_count", 0),
            "top_scores": getattr(compliance, "top_scores", []),
            "score_distribution": getattr(compliance, "score_distribution", {}),
        }

    @staticmethod
    def _serialize_bfs(bfs: BFSChainReport | Any) -> dict:
        """BFS链序列化"""
        if isinstance(bfs, dict):
            return bfs
        return {
            "total_nodes": getattr(bfs, "total_nodes", 0),
            "seed_count": getattr(bfs, "seed_count", 0),
            "level1_count": getattr(bfs, "level1_count", 0),
            "level2_count": getattr(bfs, "level2_count", 0),
            "level3_count": getattr(bfs, "level3_count", 0),
            "nodes": getattr(bfs, "nodes", []),
        }

    @staticmethod
    def _serialize_catalyst(catalyst: CatalystMatchReport | Any) -> dict:
        """催化剂信号序列化"""
        if isinstance(catalyst, dict):
            return catalyst
        return {
            "matched_count": getattr(catalyst, "matched_count", 0),
            "signals": getattr(catalyst, "signals", []),
        }

    # ── 独立执行各子模块 ────────────────────────────────

    def run_compliance_only(
        self,
        run_date: date | None = None,
        universe: list[str] | None = None,
    ) -> ComplianceReport:
        """仅执行合规评分（独立调试用）"""
        return self.scorer.score_all(
            run_date=run_date or date.today(),
            universe=universe,
        )

    def run_bfs_only(
        self,
        compliance_scores: ComplianceReport,
        run_date: date | None = None,
    ) -> BFSChainReport:
        """仅执行BFS传导链（独立调试用）"""
        return self.bfs_engine.build_chain(
            run_date=run_date or date.today(),
            compliance_scores=compliance_scores,
        )

    def run_catalyst_only(
        self,
        bfs_report: BFSChainReport,
        run_date: date | None = None,
    ) -> CatalystMatchReport:
        """仅执行催化剂匹配（独立调试用）"""
        return self.catalyst_lib.match_all(
            run_date=run_date or date.today(),
            bfs_report=bfs_report,
        )

    # ── 永久化 ──────────────────────────────────────────

    def save_report(
        self,
        report: dict[str, Any],
        output_dir: Path | str | None = None,
    ) -> Path:
        """保存输出报告到文件"""
        import json

        out_dir = Path(output_dir) if output_dir else self.config.OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        run_date_str = report.get("meta", {}).get("run_date", "unknown")
        filename = f"S005_compliance_chain_{run_date_str}.json"
        out_path = out_dir / filename

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"[S005] 报告已保存: {out_path}")
        return out_path

    # ── Mismatch Heatmap 输出 (S002 格式对齐 v1.0) ────────

    def save_mismatch_heatmap(
        self,
        compliance_report: ComplianceReport | Any,
        run_date: date | None = None,
        output_dir: Path | str | None = None,
    ) -> Path | None:
        """生成并保存 S002 格式的 mismatch_heatmap_{date}.json

        从合规评分报告中提取各标的五维度评分，计算与基准分(50)的偏差
        作为 mismatch_intensity，并计算 Z-Score 作为相对偏离指标。

        S002 格式 (墨衡 2026-05-25 发布):
          {
            "date": "2026-05-25",
            "symbol": "601398.SH",
            "channel_pair": "inner_vs_grey",
            "mismatch_intensity": 23.5,
            "z_score": 0.87
          }

        Parameters
        ----------
        compliance_report : ComplianceReport
        run_date : date | None
        output_dir : Path | str | None

        Returns
        -------
        Path | None
        """
        import json
        import statistics

        run_date = run_date or date.today()
        out_dir = Path(output_dir) if output_dir else self.config.OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = MISMATCH_HEATMAP_CONFIG["filename_template"].format(
            date=run_date.isoformat()
        )
        out_path = out_dir / filename

        # ── 提取评分数据 ──
        scores = []
        if hasattr(compliance_report, "scores"):
            scores = compliance_report.scores
        elif isinstance(compliance_report, dict):
            # 从ComplianceReport序列化中提取
            pass

        if not scores:
            logger.warning("[S005/heatmap] 无评分数据，跳过 heatmap 生成")
            return None

        # ── 计算基准偏差 ──
        # mismatch_intensity = abs(score - 50) 偏离基准的程度
        # 附带通道对维度
        heatmap_entries = []
        all_intensities = []

        for score_obj in scores:
            symbol = score_obj.symbol if hasattr(score_obj, "symbol") else ""
            ds = getattr(score_obj, "dimension_scores", {})

            if not ds:
                continue

            # 为每个维度对生成 heatmap 条目
            dim_pairs = [
                ("inner_vs_grey", ["inner_control", "grey_overlap"]),
                ("govern_vs_trans", ["governance", "transparency"]),
                ("history_vs_avg", ["history"]),
            ]

            for pair_name, dims in dim_pairs:
                scores_in_pair = [ds.get(d, 50.0) for d in dims]
                avg_in_pair = sum(scores_in_pair) / len(scores_in_pair)

                # 错配强度 = 偏离基准分50的程度
                intensity = round(abs(avg_in_pair - 50.0), 2)
                all_intensities.append(intensity)

                heatmap_entries.append({
                    "date": run_date.isoformat(),
                    "symbol": symbol,
                    "channel_pair": pair_name,
                    "mismatch_intensity": intensity,
                    "z_score": 0.0,  # 占位，统一计算后替换
                    "source_dimension_scores": {
                        d: round(ds.get(d, 0.0), 2) for d in dims
                    },
                })

        # ── 计算 Z-Score ──
        if len(all_intensities) > 1:
            mean = statistics.mean(all_intensities)
            stdev = statistics.stdev(all_intensities) if len(all_intensities) > 1 else 1.0
            for entry in heatmap_entries:
                entry["z_score"] = round(
                    (entry["mismatch_intensity"] - mean) / stdev, 4
                )
        else:
            for entry in heatmap_entries:
                entry["z_score"] = 0.0

        # ── 构建 S002 格式输出 ──
        # 移除 'source_dimension_scores' 元数据字段（仅用于调试，不在正式接口中）
        output = []
        for entry in heatmap_entries:
            output.append({
                "date": entry["date"],
                "symbol": entry["symbol"],
                "channel_pair": entry["channel_pair"],
                "mismatch_intensity": entry["mismatch_intensity"],
                "z_score": entry["z_score"],
            })

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(
            f"[S005/heatmap] S002格式 heatmap 已保存: {out_path} | "
            f"{len(output)} 条目"
        )
        return out_path 


# ── 便捷入口 ──────────────────────────────────────────

def run(run_date: date | None = None, universe: list[str] | None = None) -> dict[str, Any]:
    """一键运行 S005 完整流水线"""
    orchestrator = S005Orchestrator()
    return orchestrator.run_pipeline(run_date=run_date, universe=universe)


def main() -> None:
    """命令行入口"""
    import json
    from datetime import date

    report = run()
    out_path = Path.cwd() / f"S005_compliance_chain_{date.today().isoformat()}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[S005] 输出文件: {out_path.resolve()}")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:500] + "...")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
