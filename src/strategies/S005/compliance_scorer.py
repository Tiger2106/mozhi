#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S005/compliance_scorer.py — 合规评分五维度计算框架

五维度评分体系
--------------
1. 内控合规投入 (0.25) : 财报合规费用 / 总营收
2. 治理结构评分 (0.20) : ESG评级 + 董事会结构
3. 历史合规记录 (0.20) : 行政处罚记录（扣分制）
4. 灰色关联度 (0.20) : 与S004联动接口占位
5. 信息透明度 (0.15) : 信息披露质量

评分范围
--------
各维度 0-100，总分 0-100
50 为基准线，>70 为合规优势，<30 为合规风险

作者: 墨萱 (moxuan)
创建时间: 2026-05-25 10:48 +08:00
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from pathlib import Path
from typing import Optional

from src.strategies.S005.config import S005Config

logger = logging.getLogger("S005.compliance_scorer")


# ============================================================
# 合规评分结果数据类型
# ============================================================

@dataclass
class ComplianceScore:
    """单只标的合规评分结果

    Attributes
    ----------
    symbol : str
        标的代码
    total_score : float
        总分 (0-100)
    dimension_scores : dict[str, float]
        各维度评分 {维度名: 分数}
    dimension_details : dict[str, Any]
        各维度评分明细
    source : str
        评分来源 ("mock" | "live")
    scored_at : str
        评分时间
    """
    symbol: str
    total_score: float = 0.0
    dimension_scores: dict[str, float] = field(default_factory=dict)
    dimension_details: dict[str, Any] = field(default_factory=dict)
    source: str = "mock"
    scored_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ComplianceReport:
    """合规评分报告

    Attributes
    ----------
    run_date : date | str
        运行日期
    total_count : int
        评分标的总数
    scored_count : int
        成功评分数
    failed_count : int
        失败评分数
    scores : list[ComplianceScore]
        评分结果列表
    top_scores : list[dict]
        Top-N 评分摘要
    score_distribution : dict
        分数分布统计
    source : str
        "mock" | "live"
    """
    run_date: str = ""
    total_count: int = 0
    scored_count: int = 0
    failed_count: int = 0
    scores: list[ComplianceScore] = field(default_factory=list)
    top_scores: list[dict] = field(default_factory=list)
    score_distribution: dict[str, int] = field(default_factory=dict)
    source: str = "mock"


# ============================================================
# 合规评分器
# ============================================================

class ComplianceScorer:
    """合规评分五维度计算框架

    当前版本为框架实现，实际数据来源使用模拟数据。
    上线后需替换各维度数据获取方式。

    调用流程:
        1. score_all() → 批量评分
        2. score_single() → 单只评分
        3. score_by_dimension() → 指定维度评分
    """

    # 维度名称与权重映射
    DIMENSIONS: list[str] = [
        "inner_control",
        "governance",
        "history",
        "grey_overlap",
        "transparency",
    ]

    DIMENSION_LABELS: dict[str, str] = {
        "inner_control": "内控合规投入",
        "governance": "治理结构评分",
        "history": "历史合规记录",
        "grey_overlap": "灰色关联度",
        "transparency": "信息透明度",
    }

    def __init__(self, config: Optional[S005Config] = None):
        self.config = config or S005Config()
        self._validate_weights()

    def _validate_weights(self) -> None:
        """验证权重配置"""
        warnings = self.config.validate()
        if warnings:
            logger.warning(f"配置警告: {'; '.join(warnings)}")

    # ── 批量评分 ────────────────────────────────────────

    def score_all(
        self,
        run_date: date | None = None,
        universe: list[str] | None = None,
    ) -> ComplianceReport:
        """批量评分全/指定标的

        Parameters
        ----------
        run_date : date | None
        universe : list[str] | None
            标的列表（None → 模拟全市场）

        Returns
        -------
        ComplianceReport
        """
        run_date = run_date or date.today()
        universe = universe or self._default_universe()

        logger.info(
            f"评分标的数: {len(universe)} | "
            f"权重: {self.config.weights_summary}"
        )

        scores: list[ComplianceScore] = []
        failures = 0

        for symbol in universe:
            try:
                score = self.score_single(symbol, run_date)
                scores.append(score)
            except Exception as e:
                logger.error(f"评分失败 [{symbol}]: {e}")
                failures += 1

        # 排序
        scores.sort(key=lambda x: x.total_score, reverse=True)

        report = ComplianceReport(
            run_date=run_date.isoformat(),
            total_count=len(universe),
            scored_count=len(scores),
            failed_count=failures,
            scores=scores,
            top_scores=self._build_top_scores(scores),
            score_distribution=self._build_distribution(scores),
            source="mock",  # TODO: 上线后改为 "live"
        )

        return report

    # ── 单只评分 ────────────────────────────────────────

    def score_single(
        self,
        symbol: str,
        run_date: date | None = None,
    ) -> ComplianceScore:
        """单只标的五维度合规评分

        Parameters
        ----------
        symbol : str
        run_date : date | None

        Returns
        -------
        ComplianceScore
        """
        run_date = run_date or date.today()

        # 各维度评分（当前为模拟实现）
        inner_control = self._score_inner_control(symbol, run_date)
        governance = self._score_governance(symbol, run_date)
        history = self._score_history(symbol, run_date)
        grey_overlap = self._score_grey_overlap(symbol, run_date)
        transparency = self._score_transparency(symbol, run_date)

        dimension_scores = {
            "inner_control": inner_control["score"],
            "governance": governance["score"],
            "history": history["score"],
            "grey_overlap": grey_overlap["score"],
            "transparency": transparency["score"],
        }

        # 加权总分
        w = self.config.weights
        total_score = (
            w["inner_control"] * dimension_scores["inner_control"]
            + w["governance"] * dimension_scores["governance"]
            + w["history"] * dimension_scores["history"]
            + w["grey_overlap"] * dimension_scores["grey_overlap"]
            + w["transparency"] * dimension_scores["transparency"]
        )

        return ComplianceScore(
            symbol=symbol,
            total_score=round(total_score, 2),
            dimension_scores=dimension_scores,
            dimension_details={
                "inner_control": inner_control,
                "governance": governance,
                "history": history,
                "grey_overlap": grey_overlap,
                "transparency": transparency,
            },
        )

    # ── 各维度评分实现 ── ──────────────────────────────

    def _score_inner_control(self, symbol: str, run_date: date) -> dict:
        """维度1: 内控合规投入 — 财报合规费用/总营收

        公式: compliance_cost_ratio = (合规费用 + 审计费用) / 总营收
        评分: 100 * clamp(ratio / 0.05, 0, 1)
              即合规费用占比5%以上得满分，超过3%算良好

        TODO: 接入财报数据来源
        """
        # ===== 模拟实现 =====
        ratio = self._mock_compliance_ratio(symbol)
        score = min(100.0, 100.0 * ratio / 0.05)

        return {
            "score": round(score, 2),
            "ratio": round(ratio, 4),
            "formula": "compliance_cost / total_revenue",
            "source": "mock",
            "note": "模拟: 合规费用占比",
        }

    def _score_governance(self, symbol: str, run_date: date) -> dict:
        """维度2: 治理结构评分 — ESG评级 + 董事会结构

        子维度:
          - ESG评级 (50%): 外部评级映射为分数
          - 独立董事占比 (30%): 独立董事/董事会总人数
          - 董事长/CEO分离 (20%): 两职分离加分

        TODO: 接入ESG评级数据源 (中证/商道融绿/MSCI)
        """
        # ===== 模拟实现 =====
        esg_score = self._mock_esg_score(symbol)
        independence_ratio = self._mock_independence_ratio(symbol)
        separation_bonus = self._mock_separation_bonus(symbol)

        score = 0.5 * esg_score + 0.3 * (100 * independence_ratio) + 0.2 * separation_bonus

        return {
            "score": round(score, 2),
            "esg_score": round(esg_score, 2),
            "independence_ratio": round(independence_ratio, 4),
            "separation_bonus": separation_bonus,
            "source": "mock",
            "note": "模拟: ESG + 董事会结构",
        }

    def _score_history(self, symbol: str, run_date: date) -> dict:
        """维度3: 历史合规记录 — 行政处罚记录（扣分制）

        基准分100，每次行政处罚扣减：
          - 重大处罚（通报批评/罚款 > 100万）: -30分
          - 一般处罚（警告/罚款 < 100万）: -15分
          - 轻微处罚（监管关注函）: -5分
        最低0分，扣满为止。

        TODO: 接入证监会/交易所处罚数据
        """
        # ===== 模拟实现 =====
        base = 100.0
        major_penalties = self._mock_major_penalties(symbol)
        minor_penalties = self._mock_minor_penalties(symbol)
        warnings_count = self._mock_warnings_count(symbol)

        deduction = (major_penalties * 30) + (minor_penalties * 15) + (warnings_count * 5)
        score = max(0.0, base - deduction)

        return {
            "score": round(score, 2),
            "major_penalties": major_penalties,
            "minor_penalties": minor_penalties,
            "warnings_count": warnings_count,
            "total_deduction": deduction,
            "source": "mock",
            "note": "模拟: 行政处罚记录扣分制",
        }

    def _score_grey_overlap(self, symbol: str, run_date: date) -> dict:
        """维度4: 灰色关联度 — 读取S004灰色资金链路由 compliance_flag

        数据流:
          1. 读取 S004 Phase1 输出的 grey_routes_{date}.json
          2. 若文件存在, 从 active_routes 列表中提取包含 symbol 的路由
          3. 取 compliance_flag → 映射为评分 (compliant=100, grey=40, black=0)
          4. 多路由命中时取加权平均值

        S004 6字段接口格式:
          {route_id, supply_label, demand_label, route_topology, flow_volume, compliance_flag}

        Fallback:
          - 文件不存在 -> 返回基准分60 (占位模式)
          - 文件存在但无匹配symbol -> 返回基准分70 (无灰色线索视为相对合规)
        """
        endpoint = self.config.s004_grey_overlap_endpoint
        mapping = self.config.s004_compliance_mapping

        # 1. 尝试读取 S004 输出文件
        _run_date = run_date or date.today()
        try:
            from src.config import PROJECT_ROOT
            import json as _json
            endpoint_path = PROJECT_ROOT / endpoint.format(date=_run_date.isoformat())

            if endpoint_path.exists():
                with open(endpoint_path, "r", encoding="utf-8") as f:
                    s004_data = _json.load(f)

                # S004 输出格式: { active_routes: [{route_id, supply_label, demand_label, route_topology, flow_volume, compliance_flag}] }
                active_routes = s004_data.get("active_routes", [])

                # 查找包含目标 symbol 的路由
                matching_routes = []
                for route in active_routes:
                    route_topology = route.get("route_topology", "")
                    supply_label = route.get("supply_label", "")
                    demand_label = route.get("demand_label", "")

                    # 检查 symbol 是否出现在路由的 supply/demand/topology 中
                    if any(
                        symbol in str(field)
                        for field in [route_topology, supply_label, demand_label]
                    ):
                        matching_routes.append(route)

                if not matching_routes:
                    # 无匹配 → 无灰色线索，视为相对合规
                    return {
                        "score": 70.0,
                        "source": "s004",
                        "note": (
                            f"S004数据存在但无{ symbol }关联路由，"
                            f"视为无灰色线索(相对合规)"
                        ),
                        "matching_routes_found": 0,
                        "grey_overlap_raw": None,
                        "from_s004": True,
                    }

                # 多条路由命中时取加权平均
                total_score = 0.0
                total_volume = 0.0
                route_details = []

                for route in matching_routes:
                    cf = route.get("compliance_flag", "grey")
                    route_score = mapping.get(cf, 40.0)
                    volume = abs(float(route.get("flow_volume", 1.0)))
                    if volume <= 0:
                        volume = 1.0
                    total_score += route_score * volume
                    total_volume += volume
                    route_details.append({
                        "route_id": route.get("route_id", ""),
                        "compliance_flag": cf,
                        "route_score": route_score,
                        "volume": volume,
                    })

                avg_score = round(total_score / total_volume, 2) if total_volume > 0 else 60.0

                return {
                    "score": avg_score,
                    "source": "s004",
                    "note": (
                        f"从S004读取{len(matching_routes)}条关联路由，"
                        f"compliance_flag映射后加权评分"
                    ),
                    "matching_routes_found": len(matching_routes),
                    "matching_details": route_details,
                    "grey_overlap_raw": matching_routes,
                    "from_s004": True,
                }

        except FileNotFoundError:
            pass
        except _json.JSONDecodeError as e:
            logger.warning(f"S004数据文件解析失败: {e}")
        except Exception as e:
            logger.warning(f"读取S004数据异常: {e}")

        # 2. 文件不存在或读取失败 → fallback
        return {
            "score": 60.0,
            "source": "placeholder",
            "note": (
                f"S004数据文件不存在或读取失败: {endpoint}。"
                f"使用fallback基准分60。"
                f"S004 Phase1预计5/29交付。"
            ),
            "grey_overlap_raw": None,
            "from_s004": False,
        }

    def _score_transparency(self, symbol: str, run_date: date) -> dict:
        """维度5: 信息透明度 — 信息披露质量评分

        子维度:
          - 年报及时性 (25%): 是否在规定期限内发布
          - 更正/补充公告频率 (25%): 负向指标
          - 交易所信披评级 (30%): A/B/C/D评级映射
          - 分析师覆盖度 (20%): 覆盖机构数量

        TODO: 接入交易所信披评级数据
        """
        # ===== 模拟实现 =====
        timeliness = self._mock_timeliness(symbol)
        correction_penalty = self._mock_correction_penalty(symbol)
        disclosure_rating = self._mock_disclosure_rating(symbol)
        coverage_score = self._mock_analyst_coverage(symbol)

        score = (
            0.25 * timeliness
            + 0.25 * correction_penalty
            + 0.30 * disclosure_rating
            + 0.20 * coverage_score
        )

        return {
            "score": round(score, 2),
            "timeliness": timeliness,
            "correction_penalty": correction_penalty,
            "disclosure_rating": disclosure_rating,
            "coverage_score": coverage_score,
            "source": "mock",
            "note": "模拟: 信息披露质量",
        }

    # ── 模拟数据生成器 ──────────────────────────────────

    def _default_universe(self) -> list[str]:
        """返回默认标的池（模拟）"""
        # 银行+券商+保险+科技 典型标的
        return [
            "601398.SH",  # 工商银行
            "601939.SH",  # 建设银行
            "601288.SH",  # 农业银行
            "600036.SH",  # 招商银行
            "600030.SH",  # 中信证券
            "601688.SH",  # 华泰证券
            "600837.SH",  # 海通证券
            "601318.SH",  # 中国平安
            "601628.SH",  # 中国人寿
            "600519.SH",  # 贵州茅台
            "000858.SZ",  # 五粮液
            "300750.SZ",  # 宁德时代
            "601166.SH",  # 兴业银行
            "600900.SH",  # 长江电力
            "601857.SH",  # 中国石油
        ]

    def _mock_compliance_ratio(self, symbol: str) -> float:
        """模拟合规费用占比"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        # 大行5-8%，中小行2-5%，券商3-6%
        if "SH" in symbol:
            base = 0.05 if symbol.startswith(("601", "600")) else 0.03
        else:
            base = 0.03
        return max(0.01, base + ((seed % 50) / 1000))

    def _mock_esg_score(self, symbol: str) -> float:
        """模拟ESG评级分数"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        # 银行ESG评级通常较高
        if any(symbol.startswith(p) for p in ("601398", "601939", "601288", "600036")):
            return 45 + (seed % 40)
        return 30 + (seed % 55)

    def _mock_independence_ratio(self, symbol: str) -> float:
        """模拟独立董事占比"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        return 0.33 + (seed % 20) / 100

    def _mock_separation_bonus(self, symbol: str) -> float:
        """模拟董事长/CEO两职分离加分"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        # 60%概率两职分离
        return 80.0 if (seed % 10) < 6 else 20.0

    def _mock_major_penalties(self, symbol: str) -> int:
        """模拟重大处罚次数"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        # 80%概率没有重大处罚
        if (seed % 10) < 8:
            return 0
        return 1 + ((seed // 10) % 2)

    def _mock_minor_penalties(self, symbol: str) -> int:
        """模拟一般处罚次数"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        return (seed % 3)

    def _mock_warnings_count(self, symbol: str) -> int:
        """模拟监管关注次数"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        return (seed // 10) % 4

    def _mock_timeliness(self, symbol: str) -> float:
        """模拟报告及时性评分"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        return 70 + (seed % 31)

    def _mock_correction_penalty(self, symbol: str) -> float:
        """模拟更正/补充公告处罚"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        corrections = (seed // 100) % 5
        return max(0, 100 - corrections * 15)

    def _mock_disclosure_rating(self, symbol: str) -> float:
        """模拟交易所信披评级"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        # A(90+), B(70), C(50), D(30)
        ratings = [90, 70, 50, 30]
        idx = min(3, (seed % 4))
        return float(ratings[idx])

    def _mock_analyst_coverage(self, symbol: str) -> float:
        """模拟分析师覆盖评分"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        num_analysts = 5 + (seed % 25)  # 5-30家
        return min(100, num_analysts * 4)

    # ── 辅助方法 ────────────────────────────────────────

    def _build_top_scores(self, scores: list[ComplianceScore], top_n: int = 10) -> list[dict]:
        """构建Top-N评分摘要（BFS种子输入）"""
        top = scores[:top_n]
        return [
            {
                "rank": i + 1,
                "symbol": s.symbol,
                "total_score": s.total_score,
                "dimension_scores": s.dimension_scores,
            }
            for i, s in enumerate(top)
        ]

    @staticmethod
    def _build_distribution(scores: list[ComplianceScore]) -> dict[str, int]:
        """构建分数分布统计"""
        buckets = {"0-30": 0, "30-50": 0, "50-70": 0, "70-90": 0, "90-100": 0}
        for s in scores:
            if s.total_score < 30:
                buckets["0-30"] += 1
            elif s.total_score < 50:
                buckets["30-50"] += 1
            elif s.total_score < 70:
                buckets["50-70"] += 1
            elif s.total_score < 90:
                buckets["70-90"] += 1
            else:
                buckets["90-100"] += 1
        return buckets

    # ── 维度工具 ────────────────────────────────────────

    def get_dimension_label(self, dim: str) -> str:
        """获取维度中文名"""
        return self.DIMENSION_LABELS.get(dim, dim)

    @classmethod
    def list_dimensions(cls) -> list[dict[str, Any]]:
        """列出所有维度信息"""
        return [
            {"key": d, "label": cls.DIMENSION_LABELS.get(d, d)}
            for d in cls.DIMENSIONS
        ]


# ── 测试入口 ──────────────────────────────────────────

def demo() -> None:
    """演示合规评分完整流程"""
    scorer = ComplianceScorer()
    report = scorer.score_all()

    print("=" * 60)
    print("S005 合规评分演示")
    print("=" * 60)
    print(f"运行日期: {report.run_date}")
    print(f"评分标的: {report.total_count} | 成功: {report.scored_count} | 失败: {report.failed_count}")
    print(f"来源: {report.source}")
    print(f"\n分数分布: {report.score_distribution}")
    print(f"\nTop-10:")
    print(f"{'排名':<5} {'标的':<15} {'总分':<8} {'内控':<8} {'治理':<8} {'历史':<8} {'灰色':<8} {'透明':<8}")
    print("-" * 68)
    for entry in report.top_scores:
        ds = entry["dimension_scores"]
        print(f"{entry['rank']:<5} {entry['symbol']:<15} {entry['total_score']:<8.2f} "
              f"{ds['inner_control']:<8.1f} {ds['governance']:<8.1f} {ds['history']:<8.1f} "
              f"{ds['grey_overlap']:<8.1f} {ds['transparency']:<8.1f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
