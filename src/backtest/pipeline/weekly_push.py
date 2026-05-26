"""
墨枢 - P5b-08 周报自动推送流程

职责：每周五收盘后执行，生成周报并推送至飞书群。

流程：
1. 加载最新一周的回测结果
2. WeeklyReportExtractor 提取周数据
3. KnowledgeExtractor 提取洞察
4. ReportRenderer 渲染周报 Markdown
5. ChartGenerator 生成周度图表
6. 推送至飞书群

Author: 墨涵
Created: 2026-05-15
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Any

# ── 路径配置 ──────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("weekly_push")

# ── 默认路径 ──────────────────────────────────────────────
DEFAULT_RESULT_DIR = os.path.join(PROJECT_ROOT, "reports", "backtest")
DEFAULT_CHART_DIR = os.path.join(PROJECT_ROOT, "reports", "charts")
REPORT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "reports", "weekly")


def get_week_start(date_str: str) -> str:
    """获取给定日期所在周的周一日期（YYYYMMDD）。"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y%m%d")


def is_friday(date_str: str) -> bool:
    """判断给定日期是否为周五。"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return dt.weekday() == 4


class WeeklyPushPipeline:
    """
    周报自动推送流水线。

    用法::

        pipeline = WeeklyPushPipeline()
        pipeline.run(symbol="601857.SH", week_start="20260511")
    """

    def __init__(
        self,
        result_dir: str = DEFAULT_RESULT_DIR,
        chart_dir: str = DEFAULT_CHART_DIR,
        output_dir: str = REPORT_OUTPUT_DIR,
    ):
        self.result_dir = result_dir
        self.chart_dir = chart_dir
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def run(
        self,
        symbol: str = "601857.SH",
        week_start: Optional[str] = None,
        multi_result: Optional[Any] = None,
    ):
        """
        执行周报推送全流程。

        参数
        ----------
        symbol : str
            股票代码。
        week_start : str, optional
            周起始日（YYYYMMDD，周一）。默认当前周的周一。
        multi_result : MultiStrategyResult, optional
            外部传入回测结果。
        """
        # ── 确定周起始日 ──────────────────────────────────
        today = datetime.now() - timedelta(hours=4)  # 调整为收盘后
        today_str = today.strftime("%Y%m%d")

        if week_start:
            ws = week_start
        else:
            ws = get_week_start(today_str)

        # 周范围描述
        we = datetime.strptime(ws, "%Y%m%d") + timedelta(days=4)
        week_label = f"{ws[:4]}-{ws[4:6]}-{ws[6:]} ~ {we.strftime('%m-%d')}"

        logger.info(f"[WeeklyPush] 🚀 启动周报推送: {symbol} | 第{ws[4:6]}周 ({week_label})")

        # ── Step 1: 加载结果 ──────────────────────────────
        result = multi_result or self._load_result(symbol)
        if result is None:
            logger.error("无法获取回测结果，推送终止")
            return False

        # ── Step 2: 提取周报数据 ──────────────────────────
        from backtest.pipeline.weekly_extractor import WeeklyReportExtractor

        extractor = WeeklyReportExtractor()
        weekly_data = extractor.extract_weekly(ws, result)
        logger.info(f"  数据提取完成: {len(weekly_data.get('summary', {}))} 项汇总")

        # ── Step 3: 提取知识洞察 ──────────────────────────
        try:
            from backtest.pipeline.knowledge_extractor import KnowledgeExtractor

            ke = KnowledgeExtractor()
            insights = ke.extract_insights(result, weekly_data)
            weekly_data["insights"] = [
                i.to_dict() if hasattr(i, "to_dict") else i for i in insights
            ]
            logger.info(f"  知识提取: {len(insights)} 条洞察")
        except ImportError:
            logger.warning("  KnowledgeExtractor 未就绪，跳过")
            weekly_data["insights"] = []

        # ── Step 4: 渲染周报 Markdown ──────────────────────
        from backtest.pipeline.report_renderer import ReportRenderer

        renderer = ReportRenderer()
        report_md = renderer.render_weekly(weekly_data)
        logger.info("  报告渲染完成")

        # ── Step 5: 生成周度图表 ───────────────────────────
        try:
            from backtest.pipeline.chart_generator import ChartGenerator

            symbol_dir = os.path.join(self.chart_dir, symbol)
            cg = ChartGenerator()
            charts = cg.generate_all(result, symbol_dir)
            weekly_data["charts"] = charts
            logger.info(f"  图表生成: {len(charts)} 张")
        except ImportError:
            logger.warning("  ChartGenerator 未就绪，跳过")
            weekly_data["charts"] = {}

        # ── Step 6: 保存报告文件 ──────────────────────────
        report_path = os.path.join(self.output_dir, f"{symbol}_week{ws[4:6]}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        logger.info(f"  报告已保存: {report_path}")

        # ── Step 7: 推送至飞书 ────────────────────────────
        push_ok = self._push_to_feishu(report_md, week_label, symbol)
        if push_ok:
            logger.info(f"[WeeklyPush] ✅ 周报推送成功: 第{ws[4:6]}周")
        else:
            logger.warning(f"[WeeklyPush] ⚠️ 推送失败，报告已保存至: {report_path}")

        return push_ok

    def _load_result(self, symbol: str):
        """加载回测结果（同日报）。"""
        search_paths = [
            os.path.join(self.result_dir, f"{symbol}_multi_result.json"),
            os.path.join(self.result_dir, f"{symbol}_result.json"),
        ]
        for path in search_paths:
            if os.path.exists(path):
                logger.info(f"  加载周报回测结果: {path}")
                return None
        logger.warning(f"  未找到周报回测结果: {symbol}")
        return None

    def _push_to_feishu(self, report_md: str, week_label: str, symbol: str) -> bool:
        """推送至飞书群（同日报预留）。"""
        logger.warning("  飞书推送占位，需配置 Webhook 或 Bot Token")
        return False

    @staticmethod
    def check_run_day(date_str: Optional[str] = None) -> bool:
        """
        检查当前是否应执行周报（周五则执行）。
        用于 cron 调度时的守卫判断。
        """
        check_date = date_str or (datetime.now() - timedelta(hours=4)).strftime("%Y%m%d")
        return is_friday(check_date)


# ── CLI 入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="墨枢周报推送")
    parser.add_argument("--symbol", default="601857.SH", help="股票代码")
    parser.add_argument("--week-start", default=None, help="周起始日 (YYYYMMDD, 周一)")
    parser.add_argument("--force", action="store_true", help="允许非周五执行")
    args = parser.parse_args()

    if not args.force and not WeeklyPushPipeline.check_run_day():
        today = (datetime.now() - timedelta(hours=4)).strftime("%Y%m%d")
        logger.info(f"[WeeklyPush] 非执行日（{today}），跳过")
        sys.exit(0)

    pipeline = WeeklyPushPipeline()
    success = pipeline.run(symbol=args.symbol, week_start=args.week_start)
    sys.exit(0 if success else 1)
