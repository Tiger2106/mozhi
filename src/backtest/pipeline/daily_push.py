"""
墨枢 - P5b-07 日报自动推送流程

职责：每日收盘后执行，生成日报并推送至飞书群。

流程：
1. 加载最新回测结果（MultiStrategyResult）
2. DailyReportExtractor 提取数据
3. KnowledgeExtractor 提取洞察
4. ReportRenderer 渲染日报 Markdown
5. ChartGenerator 生成图表
6. 推送至飞书群

Author: 墨涵
Created: 2026-05-15
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# ── 路径配置 ──────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("daily_push")

# ── 默认路径 ──────────────────────────────────────────────
DEFAULT_RESULT_DIR = os.path.join(PROJECT_ROOT, "reports", "backtest")
DEFAULT_CHART_DIR = os.path.join(PROJECT_ROOT, "reports", "charts")
REPORT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "reports", "daily")


class DailyPushPipeline:
    """
    日报自动推送流水线。

    用法::

        pipeline = DailyPushPipeline()
        pipeline.run(symbol="601857.SH", date="20260515")
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
        date: Optional[str] = None,
        multi_result: Optional[Any] = None,
    ):
        """
        执行日报推送全流程。

        参数
        ----------
        symbol : str
            股票代码。
        date : str, optional
            日期（YYYYMMDD）。默认最新交易日。
        multi_result : MultiStrategyResult, optional
            外部传入回测结果。不传入时尝试从文件加载。
        """
        report_date = date or (datetime.now() - timedelta(hours=4)).strftime("%Y%m%d")

        logger.info(f"[DailyPush] 🚀 启动日报推送: {symbol} | {report_date}")

        # ── Step 1: 加载或获取 MultiStrategyResult ──────
        result = multi_result or self._load_result(symbol)
        if result is None:
            logger.error("无法获取回测结果，推送终止")
            return False

        # ── Step 2: 提取日报数据 ────────────────────────
        from backtest.pipeline.daily_extractor import DailyReportExtractor

        extractor = DailyReportExtractor()
        daily_data = extractor.extract_daily(report_date, result)
        logger.info(f"  数据提取完成: {len(daily_data.get('signals', {}))} 个策略")

        # ── Step 3: 提取知识洞察 ────────────────────────
        try:
            from backtest.pipeline.knowledge_extractor import KnowledgeExtractor

            ke = KnowledgeExtractor()
            insights = ke.extract_insights(result, daily_data)
            daily_data["insights"] = [i.to_dict() if hasattr(i, "to_dict") else i for i in insights]
            logger.info(f"  知识提取: {len(insights)} 条洞察")
        except ImportError:
            logger.warning("  KnowledgeExtractor 未就绪，跳过")
            daily_data["insights"] = []

        # ── Step 4: 渲染日报 Markdown ────────────────────
        from backtest.pipeline.report_renderer import ReportRenderer

        renderer = ReportRenderer()
        report_md = renderer.render_daily(daily_data)
        logger.info("  报告渲染完成")

        # ── Step 5: 生成图表 ─────────────────────────────
        try:
            from backtest.pipeline.chart_generator import ChartGenerator

            symbol_dir = os.path.join(self.chart_dir, symbol)
            cg = ChartGenerator()
            charts = cg.generate_all(result, symbol_dir)
            daily_data["charts"] = charts
            logger.info(f"  图表生成: {len(charts)} 张")
        except ImportError:
            logger.warning("  ChartGenerator 未就绪，跳过")
            daily_data["charts"] = {}

        # ── Step 6: 保存报告文件 ────────────────────────
        report_path = os.path.join(self.output_dir, f"{symbol}_{report_date}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        logger.info(f"  报告已保存: {report_path}")

        # ── Step 7: 推送至飞书 ──────────────────────────
        push_ok = self._push_to_feishu(report_md, report_date, symbol)
        if push_ok:
            logger.info(f"[DailyPush] ✅ 日报推送成功: {report_date}")
        else:
            logger.warning(f"[DailyPush] ⚠️ 推送失败，报告已保存至: {report_path}")

        return push_ok

    # ── 内部方法 ─────────────────────────────────────────

    def _load_result(self, symbol: str):
        """
        尝试从保存的 JSON 文件中加载 MultiStrategyResult。

        回退策略：扫描 result_dir 下最新的结果文件。
        """
        # 预留：加载序列化的回测结果
        search_paths = [
            os.path.join(self.result_dir, f"{symbol}_multi_result.json"),
            os.path.join(self.result_dir, f"{symbol}_result.json"),
            os.path.join(self.result_dir, f"{symbol}_result.pkl"),
        ]
        for path in search_paths:
            if os.path.exists(path):
                logger.info(f"  加载回测结果: {path}")
                # TODO: 反序列化 MultiStrategyResult
                return None  # 占位
        logger.warning(f"  未找到回测结果文件: {symbol}")
        return None

    def _push_to_feishu(self, report_md: str, date: str, symbol: str) -> bool:
        """
        通过飞书 API 推送报告。
        预留对接 openclaw 的 message 推送通道。
        """
        # TODO: 实际飞书推送逻辑
        # - 使用 feishu message API
        # - 或通过 openclaw 的消息通道
        logger.warning("  飞书推送占位，需配置 Webhook 或 Bot Token")
        return False


# ── CLI 入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="墨枢日报推送")
    parser.add_argument("--symbol", default="601857.SH", help="股票代码")
    parser.add_argument("--date", default=None, help="日期 (YYYYMMDD)")
    args = parser.parse_args()

    pipeline = DailyPushPipeline()
    success = pipeline.run(symbol=args.symbol, date=args.date)
    sys.exit(0 if success else 1)
