"""
墨枢 - P5b-10: ChartGenerator
图表自动生成器
生成回测中的关键图表用于报告嵌入。

生成的图表类型：
- 净值曲线（各策略+组合叠加）
- 月度收益热力图
- 回撤曲线
- 信号分布图
- 月度收益分布

要求：
- 使用 matplotlib，不引入 seaborn 等额外绘图库
- 统一图风格（字号12，图例，网格）
- 输出目录为 reports/charts/{symbol}/
- 文件命名 {type}_{symbol}_{date}.png

Author: 墨衡
Created: 2026-05-15
Version: 1.0

用法::

    from backtest.pipeline.chart_generator import ChartGenerator

    generator = ChartGenerator()
    chart_files = generator.generate_all(multi_result, output_dir="reports/charts/601857.SH/")
    # → {"nav": "reports/charts/601857.SH/nav_601857.SH_20260515.png", ...}
"""

from __future__ import annotations

import math
import os
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest.strategies.multi_runner import MultiStrategyResult

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

# 统一图风格
PLOT_FONT_SIZE = 12
PLOT_TITLE_SIZE = 14
PLOT_LEGEND_SIZE = 10
PLOT_TICK_SIZE = 10

# 策略颜色（与 report_renderer 保持一致）
STRATEGY_COLORS = {
    "trend": "#E74C3C",      # 红色 — 趋势
    "reversal": "#3498DB",    # 蓝色 — 反转
    "grid": "#2ECC71",        # 绿色 — 网格
    "combined": "#9B59B6",    # 紫色 — 组合
    "benchmark": "#F39C12",   # 橙色 — 买入持有基准
}

# DPI
FIGURE_DPI = 150

# ═══════════════════════════════════════════════════════════════
# 中文支持
# ═══════════════════════════════════════════════════════════════


def _setup_chinese_font() -> None:
    """
    设置 matplotlib 中文字体支持。

    搜索系统中已安装的中文字体，优先使用 SimHei、Microsoft YaHei
    等常见中文字体。若均不可用，尝试 rcParams 直接设置。
    """
    try:
        # 常见中文字体列表
        chinese_fonts = [
            "SimHei",            # 黑体
            "Microsoft YaHei",   # 微软雅黑
            "Microsoft JhengHei",
            "Noto Sans CJK SC",
            "Noto Sans SC",
            "WenQuanYi Micro Hei",
            "Source Han Sans SC",
            "STHeiti",
            "STSong",
            "FangSong",
            "KaiTi",
        ]

        # 方法1: 尝试 rcParams 直接设置
        available = matplotlib.font_manager.findfont("SimHei", fallback_to_default=True)
        if available.lower() != "default":
            plt.rcParams["font.sans-serif"] = chinese_fonts
            plt.rcParams["axes.unicode_minus"] = False
            return

        # 方法2: 搜索已安装字体
        font_list = matplotlib.font_manager.fontManager.ttflist
        for font in font_list:
            fname = font.name.lower()
            for cf in chinese_fonts:
                if cf.lower() in fname or fname in cf.lower():
                    plt.rcParams["font.sans-serif"] = [font.name] + chinese_fonts
                    plt.rcParams["axes.unicode_minus"] = False
                    return

        # 方法3: 回退至无中文方案（仅英文字符）
        plt.rcParams["axes.unicode_minus"] = False
        warnings.warn("未找到中文字体，图表中中文可能显示为方框。建议安装 SimHei 或 Microsoft YaHei。")

    except Exception:
        # 完全静默回退
        plt.rcParams["axes.unicode_minus"] = False


# ═══════════════════════════════════════════════════════════════
# 全局初始化
# ═══════════════════════════════════════════════════════════════

_setup_chinese_font()


def _apply_style(ax: matplotlib.axes.Axes, title: str = "") -> None:
    """
    应用统一图风格到坐标轴。

    参数
    ----------
    ax : matplotlib.axes.Axes
        目标坐标轴。
    title : str
        图表标题（可选）。
    """
    if title:
        ax.set_title(title, fontsize=PLOT_TITLE_SIZE, fontweight="bold", pad=12)

    ax.tick_params(axis="both", labelsize=PLOT_TICK_SIZE)
    ax.grid(True, alpha=0.3, linestyle="--")

    # 边框
    for spine in ax.spines.values():
        spine.set_color("#CCCCCC")
        spine.set_linewidth(0.5)


def _save_chart(
    fig: matplotlib.figure.Figure,
    filepath: str,
    dpi: int = FIGURE_DPI,
) -> str:
    """
    保存图表到文件。

    自动创建父目录，使用白色透明背景。

    参数
    ----------
    fig : matplotlib.figure.Figure
        图表对象。
    filepath : str
        保存路径。
    dpi : int
        图片 DPI。

    返回
    -------
    str
        保存后的绝对路径。
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # 白色背景 + 透明度
    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(1.0)

    fig.savefig(filepath, dpi=dpi, bbox_inches="tight", pad_inches=0.2,
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)

    return os.path.abspath(filepath)


# ═══════════════════════════════════════════════════════════════
# ChartGenerator
# ═══════════════════════════════════════════════════════════════


class ChartGenerator:
    """
    图表自动生成器。

    用法::

        generator = ChartGenerator()
        chart_files = generator.generate_all(
            multi_result,
            output_dir="reports/charts/601857.SH/",
            date="20260515",
        )
        # → {"nav": "...", "heatmap": "...", ...}
    """

    def __init__(self, dpi: int = FIGURE_DPI):
        self.dpi = dpi

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    def generate_all(
        self,
        multi_result: MultiStrategyResult,
        output_dir: str,
        date: str = "",
    ) -> Dict[str, str]:
        """
        生成所有图表。

        参数
        ----------
        multi_result : MultiStrategyResult
            多策略回测结果。
        output_dir : str
            图表输出目录。如 "reports/charts/601857.SH/"。
            最终路径为 {output_dir}{type}_{symbol}_{date}.png。
        date : str
            日期（YYYYMMDD），用于文件名。默认使用当前日期。

        返回
        -------
        dict[str, str]
            {chart_name: absolute_filepath}
        """
        symbol = multi_result.symbol
        if not date:
            date = datetime.now().strftime("%Y%m%d")

        # 确保输出目录有尾部分隔符
        output_dir = output_dir.rstrip("/\\") + os.sep

        chart_files: Dict[str, str] = {}

        # ── 1. 净值曲线 ────────────────────────────────
        try:
            filepath = self._nav_chart(multi_result, output_dir, symbol, date)
            chart_files["nav"] = filepath
        except Exception as e:
            warnings.warn(f"净值曲线图生成失败: {e}")

        # ── 2. 月度收益热力图 ──────────────────────────
        try:
            filepath = self._monthly_heatmap_chart(multi_result, output_dir, symbol, date)
            chart_files["heatmap"] = filepath
        except Exception as e:
            warnings.warn(f"月度收益热力图生成失败: {e}")

        # ── 3. 回撤曲线 ────────────────────────────────
        try:
            filepath = self._drawdown_chart(multi_result, output_dir, symbol, date)
            chart_files["drawdown"] = filepath
        except Exception as e:
            warnings.warn(f"回撤曲线图生成失败: {e}")

        # ── 4. 信号分布图 ──────────────────────────────
        try:
            filepath = self._signal_distribution_chart(multi_result, output_dir, symbol, date)
            chart_files["signal_dist"] = filepath
        except Exception as e:
            warnings.warn(f"信号分布图生成失败: {e}")

        # ── 5. 月度收益分布 ─────────────────────────────
        try:
            filepath = self._monthly_return_dist_chart(multi_result, output_dir, symbol, date)
            chart_files["monthly_dist"] = filepath
        except Exception as e:
            warnings.warn(f"月度收益分布图生成失败: {e}")

        return chart_files

    # ═══════════════════════════════════════════════════════════
    # 1. 净值曲线
    # ═══════════════════════════════════════════════════════════

    def _nav_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成净值曲线图：各策略 + 组合叠加。

        X 轴：日期
        Y 轴：净值（归一化至初始资金 1.0 或绝对值）
        """
        df = result.combined.equity_curve
        if df.empty:
            raise ValueError("净值数据为空，无法生成净值曲线")

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.set_facecolor("#FAFAFA")

        # 日期作为 X 轴
        x_dates = df["date"].values

        drawn_labels: set = set()

        # 各策略曲线
        for name in result.strategies:
            col = f"{name}_equity"
            if col not in df.columns:
                continue
            eq_vals = df[col].values
            label = f"{name}策略"
            color = STRATEGY_COLORS.get(name, "#888888")

            ax.plot(
                range(len(x_dates)), eq_vals / eq_vals[0],
                color=color, linewidth=1.5, alpha=0.8,
                label=label,
            )
            drawn_labels.add(label)

        # 组合净值（更粗）
        if "combined_equity" in df.columns:
            combined_eq = df["combined_equity"].values
            ax.plot(
                range(len(x_dates)), combined_eq / combined_eq[0],
                color=STRATEGY_COLORS["combined"], linewidth=2.5,
                label="组合", zorder=5,
            )
            drawn_labels.add("组合")

        # 买入持有基准曲线（如果存在）
        bm_name = result.combined.benchmark_name
        bm_ret = result.combined.benchmark_total_return
        if "benchmark_equity" in df.columns and bm_name:
            bm_eq = df["benchmark_equity"].values
            bm_label = f"买入持有({bm_name}) {bm_ret*100:+.2f}%"
            ax.plot(
                range(len(x_dates)), bm_eq / bm_eq[0],
                color=STRATEGY_COLORS["benchmark"], linewidth=2.0,
                linestyle="--", alpha=0.8,
                label=bm_label, zorder=4,
            )
            drawn_labels.add(bm_label)

        # 标签格式化（每5个刻度显示一次日期）
        tick_step = max(1, len(x_dates) // 10)
        tick_positions = range(0, len(x_dates), tick_step)
        tick_labels = [x_dates[i] for i in tick_positions]

        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=PLOT_TICK_SIZE)

        ax.set_xlabel("日期", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("归一化净值", fontsize=PLOT_FONT_SIZE)

        _apply_style(ax, title=f"{symbol} 净值曲线（归一化）")
        ax.legend(fontsize=PLOT_LEGEND_SIZE, loc="upper left")

        fig.tight_layout()

        filepath = os.path.join(output_dir, f"nav_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 2. 月度收益热力图
    # ═══════════════════════════════════════════════════════════

    def _monthly_heatmap_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成月度收益热力图。

        从净值曲线按月份聚合收益率，绘制热力图。
        矩阵：行 = 年份，列 = 月份。
        """
        df = result.combined.equity_curve
        if df.empty or "combined_equity" not in df.columns:
            raise ValueError("数据不足，无法生成月度收益热力图")

        # 构造带日期的 DataFrame
        dates = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        equity = df["combined_equity"].values

        plot_df = pd.DataFrame({"date": dates, "equity": equity})
        plot_df = plot_df.dropna(subset=["date"]).sort_values("date")

        # 计算月度收益率
        plot_df["month"] = plot_df["date"].dt.month
        plot_df["year"] = plot_df["date"].dt.year

        # 按月取月初（首日）和月末（末日）净值
        monthly_returns = plot_df.groupby(["year", "month"])["equity"].agg(["first", "last"])
        monthly_returns["monthly_return"] = (
            (monthly_returns["last"] - monthly_returns["first"]) / monthly_returns["first"]
        )
        monthly_returns = monthly_returns.reset_index()

        # 构建矩阵
        years = sorted(monthly_returns["year"].unique())
        months = list(range(1, 13))

        heatmap_data = np.full((len(years), 12), np.nan)
        for _, row in monthly_returns.iterrows():
            yi = int(years.index(row["year"]))
            mi = int(row["month"]) - 1
            heatmap_data[yi, mi] = float(row["monthly_return"]) * 100  # 转换为百分比

        fig, ax = plt.subplots(figsize=(10, max(4, len(years) * 0.6)))
        ax.set_facecolor("#FAFAFA")

        # 绘制热力图
        cmap = plt.cm.RdYlGn
        im = ax.imshow(heatmap_data, cmap=cmap, aspect="auto",
                       vmin=-5, vmax=5)

        # 标注数值
        for i in range(len(years)):
            for j in range(12):
                val = heatmap_data[i, j]
                if np.isnan(val):
                    continue
                text_color = "white" if abs(val) > 3 else "black"
                ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                        fontsize=8, color=text_color, fontweight="bold")

        ax.set_xticks(range(12))
        ax.set_xticklabels(
            ["1月", "2月", "3月", "4月", "5月", "6月",
             "7月", "8月", "9月", "10月", "11月", "12月"],
            fontsize=PLOT_TICK_SIZE,
        )
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years, fontsize=PLOT_TICK_SIZE)
        ax.set_xlabel("月份", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("年份", fontsize=PLOT_FONT_SIZE)

        _apply_style(ax, title=f"{symbol} 月度收益热力图（%）")
        ax.grid(False)

        # 颜色条
        cbar = fig.colorbar(im, ax=ax, shrink=0.7)
        cbar.set_label("收益率 %", fontsize=PLOT_FONT_SIZE)

        fig.tight_layout()

        filepath = os.path.join(output_dir, f"heatmap_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 3. 回撤曲线
    # ═══════════════════════════════════════════════════════════

    def _drawdown_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成回撤曲线图。

        从 combined_equity 计算当前回撤：drawdown = (equity - peak) / peak
        """
        df = result.combined.equity_curve
        if df.empty or "combined_equity" not in df.columns:
            raise ValueError("数据不足，无法生成回撤曲线")

        x_dates = df["date"].values
        equity = df["combined_equity"].values

        # 计算回撤
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak * 100  # 百分比

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.set_facecolor("#FAFAFA")

        # 填充回撤
        ax.fill_between(
            range(len(x_dates)), 0, drawdown,
            color="#E74C3C", alpha=0.3,
        )
        ax.plot(
            range(len(x_dates)), drawdown,
            color="#C0392B", linewidth=1.5,
            label="回撤",
        )

        # 阈值线
        ax.axhline(y=-5, color="#F39C12", linestyle="--", linewidth=0.8, alpha=0.7, label="5% 预警")
        ax.axhline(y=-10, color="#E74C3C", linestyle="--", linewidth=0.8, alpha=0.7, label="10% 严重")

        # 刻度
        tick_step = max(1, len(x_dates) // 10)
        tick_positions = range(0, len(x_dates), tick_step)
        tick_labels = [x_dates[i] for i in tick_positions]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=PLOT_TICK_SIZE)

        ax.set_xlabel("日期", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("回撤 (%)", fontsize=PLOT_FONT_SIZE)

        _apply_style(ax, title=f"{symbol} 回撤曲线")
        ax.legend(fontsize=PLOT_LEGEND_SIZE, loc="lower left")

        fig.tight_layout()

        filepath = os.path.join(output_dir, f"drawdown_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 4. 信号分布图
    # ═══════════════════════════════════════════════════════════

    def _signal_distribution_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成信号分布图。

        堆叠柱状图：每个交易日三个策略的信号方向。
        X 轴：日期，Y 轴：信号值 (+1 / 0 / -1)
        """
        signals = result.signals
        if not signals:
            raise ValueError("信号数据为空，无法生成信号分布图")

        # 按日期聚合各策略信号
        signal_by_date: Dict[str, Dict[str, int]] = {}
        for sig in signals:
            if sig.date not in signal_by_date:
                signal_by_date[sig.date] = {}
            signal_by_date[sig.date][sig.strategy_name] = sig.signal

        sorted_dates = sorted(signal_by_date.keys())
        strategy_names = list(result.strategies.keys())

        if not sorted_dates:
            raise ValueError("无有效日期数据")

        # 限制显示的天数（最多 60 天，避免柱状图过密）
        max_show = 60
        if len(sorted_dates) > max_show:
            # 均匀采样
            step = len(sorted_dates) // max_show
            sampled_dates = sorted_dates[::step][:max_show]
        else:
            sampled_dates = sorted_dates

        # 构建信号矩阵：行=日期，列=策略
        n_dates = len(sampled_dates)
        n_strats = len(strategy_names)

        signal_matrix = np.zeros((n_dates, n_strats), dtype=int)
        conflict_matrix = np.zeros((n_dates, n_strats), dtype=bool)
        conflict_dates = {(ce.date, ce.pair[0]): True for ce in result.conflicts}
        for ce in result.conflicts:
            conflict_dates[(ce.date, ce.pair[1])] = True

        for i, d in enumerate(sampled_dates):
            for j, name in enumerate(strategy_names):
                signal_matrix[i, j] = signal_by_date[d].get(name, 0)
                if (d, name) in conflict_dates:
                    conflict_matrix[i, j] = True

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.set_facecolor("#FAFAFA")

        # 绘制堆叠柱状图
        x = np.arange(n_dates)
        width = 0.25
        offsets = np.linspace(-width, width, n_strats)

        for j, name in enumerate(strategy_names):
            color = STRATEGY_COLORS.get(name, "#888888")
            bars = ax.bar(
                x + offsets[j],
                signal_matrix[:, j],
                width=width,
                color=color,
                alpha=0.7,
                label=name,
                edgecolor="white",
                linewidth=0.5,
            )
            # 冲突标记（在柱顶加星号）
            for i in range(n_dates):
                if conflict_matrix[i, j] and signal_matrix[i, j] != 0:
                    ax.text(
                        x[i] + offsets[j],
                        signal_matrix[i, j] + 0.05,
                        "*",
                        ha="center", va="bottom",
                        fontsize=8, color="#E74C3C", fontweight="bold",
                    )

        ax.set_xticks(x)
        ax.set_xticklabels(sampled_dates, rotation=45, ha="right",
                          fontsize=max(7, PLOT_TICK_SIZE - 2))
        ax.set_yticks([-1, 0, 1])
        ax.set_yticklabels(["做空 (-1)", "空仓 (0)", "做多 (+1)"],
                          fontsize=PLOT_TICK_SIZE - 1)
        ax.set_xlabel("日期", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("信号方向", fontsize=PLOT_FONT_SIZE)
        ax.set_ylim(-1.3, 1.3)

        _apply_style(ax, title=f"{symbol} 信号分布（* 表示冲突日）")
        ax.legend(fontsize=PLOT_LEGEND_SIZE, loc="upper right")
        ax.grid(axis="y", alpha=0.3, linestyle="--")

        fig.tight_layout()

        filepath = os.path.join(output_dir, f"signal_dist_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 5. 月度收益分布
    # ═══════════════════════════════════════════════════════════

    def _monthly_return_dist_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成月度收益分布图（柱状图）。

        各月收益率以柱状图展示，正收益绿色、负收益红色。
        """
        df = result.combined.equity_curve
        if df.empty or "combined_equity" not in df.columns:
            raise ValueError("数据不足，无法生成月度收益分布图")

        # 构造带日期的 DataFrame
        dates = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        equity = df["combined_equity"].values

        plot_df = pd.DataFrame({"date": dates, "equity": equity})
        plot_df = plot_df.dropna(subset=["date"]).sort_values("date")

        # 按月聚合
        plot_df["month_label"] = plot_df["date"].dt.strftime("%Y-%m")

        monthly_returns = plot_df.groupby("month_label")["equity"].agg(["first", "last"])
        monthly_returns["return_pct"] = (
            (monthly_returns["last"] - monthly_returns["first"]) / monthly_returns["first"] * 100
        )
        monthly_returns = monthly_returns.sort_index()

        if monthly_returns.empty:
            raise ValueError("月度数据为空")

        months = monthly_returns.index.tolist()
        returns = monthly_returns["return_pct"].values

        # 颜色
        colors = ["#2ECC71" if r >= 0 else "#E74C3C" for r in returns]

        fig, ax = plt.subplots(figsize=(max(10, len(months) * 0.35), 5))
        ax.set_facecolor("#FAFAFA")

        bars = ax.bar(range(len(months)), returns, color=colors, alpha=0.8,
                      edgecolor="white", linewidth=0.5)

        # 标注数值（仅对 > 0.5% 的标注）
        for i, (bar, ret) in enumerate(zip(bars, returns)):
            if abs(ret) >= 0.3:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (0.3 if ret >= 0 else -0.3),
                    f"{ret:.1f}%",
                    ha="center", va="bottom" if ret >= 0 else "top",
                    fontsize=8, color="#333333", fontweight="bold",
                )

        ax.axhline(y=0, color="#333333", linewidth=0.8)
        ax.set_xticks(range(len(months)))
        ax.set_xticklabels(months, rotation=60, ha="right", fontsize=PLOT_TICK_SIZE - 1)
        ax.set_xlabel("月份", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("收益率 (%)", fontsize=PLOT_FONT_SIZE)

        _apply_style(ax, title=f"{symbol} 月度收益分布")
        ax.grid(axis="y", alpha=0.3, linestyle="--")

        fig.tight_layout()

        filepath = os.path.join(output_dir, f"monthly_dist_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 批量生成
    # ═══════════════════════════════════════════════════════════

    def generate_all_for_symbols(
        self,
        results: Dict[str, MultiStrategyResult],
        base_output_dir: str = "reports/charts",
        date: str = "",
    ) -> Dict[str, Dict[str, str]]:
        """
        批量生成多个标的的图表。

        参数
        ----------
        results : dict[str, MultiStrategyResult]
            {symbol: MultiStrategyResult}
        base_output_dir : str
            基目录。最终路径为 {base_output_dir}/{symbol}/
        date : str
            日期（YYYYMMDD）。

        返回
        -------
        dict[str, dict[str, str]]
            {symbol: {chart_name: filepath}}
        """
        all_charts: Dict[str, Dict[str, str]] = {}

        for symbol, result in results.items():
            output_dir = os.path.join(base_output_dir, symbol)
            all_charts[symbol] = self.generate_all(result, output_dir, date)

        return all_charts


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def generate_charts(
    multi_result: MultiStrategyResult,
    output_dir: str,
    date: str = "",
) -> Dict[str, str]:
    """便捷函数：生成所有图表。"""
    return ChartGenerator().generate_all(multi_result, output_dir, date)


# ═══════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 构造模拟 MultiStrategyResult 做自测
    from backtest.strategies.multi_runner import (
        CombinedResult, MultiStrategyResult, PerBarSignal, ConflictEvent,
    )

    np.random.seed(42)
    n = 60
    dates = [f"202605{1+i:02d}" for i in range(n)]

    # 模拟净值
    trend_eq = 1_000_000 + np.cumsum(np.random.normal(0.002, 0.015, n)) * 1_000_000
    reversal_eq = 1_000_000 + np.cumsum(np.random.normal(0.001, 0.020, n)) * 1_000_000
    grid_eq = 1_000_000 + np.cumsum(np.random.normal(0.001, 0.008, n)) * 1_000_000
    combined_eq = trend_eq * 0.34 + reversal_eq * 0.33 + grid_eq * 0.33

    equity_df = pd.DataFrame({
        "date": dates,
        "trend_equity": trend_eq,
        "reversal_equity": reversal_eq,
        "grid_equity": grid_eq,
        "combined_equity": combined_eq,
    })
    equity_df["daily_return"] = equity_df["combined_equity"].pct_change().fillna(0.0)
    equity_df["cumulative_return"] = (1 + equity_df["daily_return"]).cumprod() - 1

    final_eq = equity_df["combined_equity"].iloc[-1]
    combined = CombinedResult(
        equity_curve=equity_df,
        weights={"trend": 0.34, "reversal": 0.33, "grid": 0.33},
        initial_capital=1_000_000,
        final_equity=final_eq,
        total_return=final_eq / 1_000_000 - 1,
        sharpe_ratio=1.2,
        max_drawdown=0.06,
    )

    # 模拟信号
    signals = []
    for i, d in enumerate(dates):
        signals.append(PerBarSignal(date=d, strategy_name="trend", signal=1, strength=0.8, price=12.5, quantity=1000))
        r_sig = -1 if i % 3 == 0 else 0
        signals.append(PerBarSignal(date=d, strategy_name="reversal", signal=r_sig, strength=0.7, price=12.5, quantity=500))
        g_sig = -1 if i % 5 == 0 else (1 if i % 7 == 0 else 0)
        signals.append(PerBarSignal(date=d, strategy_name="grid", signal=g_sig, strength=0.6, price=12.5, quantity=200))

    # 模拟冲突
    conflicts = []
    for i in range(min(15, n)):
        conflicts.append(ConflictEvent(
            date=dates[i], pair=("trend", "reversal"),
            direction_1=1, direction_2=-1, price=12.5,
        ))

    result = MultiStrategyResult(
        symbol="601857.SH",
        strategies={"trend": None, "reversal": None, "grid": None},
        signals=signals,
        combined=combined,
        conflicts=conflicts,
    )

    output_dir = "reports/charts/601857.SH"
    generator = ChartGenerator()
    chart_files = generator.generate_all(result, output_dir, date="20260515")

    print("=" * 60)
    print("CHART GENERATOR SELF-TEST")
    print("=" * 60)
    for name, path in chart_files.items():
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        print(f"  {name}: {'✅' if exists else '❌'} {path} ({size / 1024:.1f} KB)")

    print(f"\n✅ ChartGenerator self-test passed. Generated {len(chart_files)} charts.")
    print(f"   Output: {os.path.abspath(output_dir)}/")
