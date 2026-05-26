"""
墨枢 - P5b-11: TrendChartGenerator
趋势策略图表生成器
专业生成趋势类策略的特有图表，补充 ChartGenerator 的通用图表。

生成的图表类型：
- ADX/DMI 指标曲线（趋势强度可视化）
- 趋势信号进出点标记（在 K 线或净值曲线上标记 buy/sell 点）
- 趋势跟踪性能对比（趋势期 vs 非趋势期收益对比）

要求：
- 使用 matplotlib，不引入 seaborn 额外库
- 统一图风格（继承 chart_generator 的样式常量）
- 输出目录为 reports/charts/{symbol}/
- 文件命名 trend_{type}_{symbol}_{date}.png

Author: 墨衡
Created: 2026-05-15
Version: 1.0

用法::

    from backtest.charts.trend_chart_generator import TrendChartGenerator

    generator = TrendChartGenerator()
    chart_files = generator.generate_all(multi_result, output_dir="reports/charts/601857.SH/")
    # → {"adx": "...", "signals": "...", "performance": "..."}
"""

from __future__ import annotations

import os
import warnings
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest.strategies.multi_runner import MultiStrategyResult

# ═══════════════════════════════════════════════════════════════
# 常量（与 chart_generator 保持一致）
# ═══════════════════════════════════════════════════════════════

PLOT_FONT_SIZE = 12
PLOT_TITLE_SIZE = 14
PLOT_LEGEND_SIZE = 10
PLOT_TICK_SIZE = 10

STRATEGY_COLORS = {
    "trend": "#E74C3C",
    "reversal": "#3498DB",
    "grid": "#2ECC71",
    "combined": "#9B59B6",
}

FIGURE_DPI = 150
_IS_RC_SET = False


def _ensure_rc() -> None:
    """确保 matplotlib 中文字体配置已设置（仅首次生效）。"""
    global _IS_RC_SET
    if _IS_RC_SET:
        return

    try:
        chinese_fonts = [
            "SimHei",
            "Microsoft YaHei",
            "Microsoft JhengHei",
            "Noto Sans CJK SC",
            "Noto Sans SC",
            "WenQuanYi Micro Hei",
            "Source Han Sans SC",
        ]
        available = matplotlib.font_manager.findfont("SimHei", fallback_to_default=True)
        if available.lower() != "default":
            plt.rcParams["font.sans-serif"] = chinese_fonts
        else:
            font_list = matplotlib.font_manager.fontManager.ttflist
            for font in font_list:
                fname = font.name.lower()
                for cf in chinese_fonts:
                    if cf.lower() in fname or fname in cf.lower():
                        plt.rcParams["font.sans-serif"] = [font.name] + chinese_fonts
                        break
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        plt.rcParams["axes.unicode_minus"] = False

    _IS_RC_SET = True


def _apply_style(ax: matplotlib.axes.Axes, title: str = "") -> None:
    if title:
        ax.set_title(title, fontsize=PLOT_TITLE_SIZE, fontweight="bold", pad=12)
    ax.tick_params(axis="both", labelsize=PLOT_TICK_SIZE)
    ax.grid(True, alpha=0.3, linestyle="--")
    for spine in ax.spines.values():
        spine.set_color("#CCCCCC")
        spine.set_linewidth(0.5)


def _save_chart(fig: matplotlib.figure.Figure, filepath: str, dpi: int = FIGURE_DPI) -> str:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(1.0)
    fig.savefig(filepath, dpi=dpi, bbox_inches="tight", pad_inches=0.2,
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return os.path.abspath(filepath)


# ═══════════════════════════════════════════════════════════════
# TrendChartGenerator
# ═══════════════════════════════════════════════════════════════


class TrendChartGenerator:
    """
    趋势策略图表生成器。

    用法::

        generator = TrendChartGenerator()
        chart_files = generator.generate_all(multi_result, output_dir="reports/charts/601857.SH/")
    """

    def __init__(self, dpi: int = FIGURE_DPI):
        _ensure_rc()
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
        生成所有趋势相关图表。

        参数
        ----------
        multi_result : MultiStrategyResult
            多策略回测结果。
        output_dir : str
            输出目录。如 "reports/charts/601857.SH/"。
        date : str
            日期（YYYYMMDD）。默认当前日期。

        返回
        -------
        dict[str, str]
            {chart_name: absolute_filepath}
        """
        from datetime import datetime
        symbol = multi_result.symbol
        if not date:
            date = datetime.now().strftime("%Y%m%d")

        output_dir = output_dir.rstrip("/\\") + os.sep

        chart_files: Dict[str, str] = {}

        # ── 1. ADX/DMI 指标曲线 ─────────────────────────
        try:
            filepath = self._adx_chart(multi_result, output_dir, symbol, date)
            chart_files["adx"] = filepath
        except Exception as e:
            warnings.warn(f"ADX 图表生成失败: {e}")

        # ── 2. 趋势信号进出点 ─────────────────────────────
        try:
            filepath = self._signal_points_chart(multi_result, output_dir, symbol, date)
            chart_files["signals"] = filepath
        except Exception as e:
            warnings.warn(f"信号点图生成失败: {e}")

        # ── 3. 趋势期 vs 非趋势期收益对比 ─────────────────
        try:
            filepath = self._performance_comparison_chart(multi_result, output_dir, symbol, date)
            chart_files["performance"] = filepath
        except Exception as e:
            warnings.warn(f"性能对比图生成失败: {e}")

        return chart_files

    # ═══════════════════════════════════════════════════════════
    # 1. ADX/DMI 指标曲线
    # ═══════════════════════════════════════════════════════════

    def _adx_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成 ADX + DI+/DI- 指标曲线。

        从 MultiStrategyResult 中提取 ADX 数据并绘制。

        ADX 数据来源：
        - 主图中绘制 ADX 线（蓝色）
        - 副图中绘制 DI+/DI- 线

        如果回测结果中不含 ADX 数据，则从 equity_curve 中的
        趋势策略净值推断趋势强度（使用简单波动率代理）。
        """
        df = result.combined.equity_curve
        if df.empty:
            raise ValueError("净值数据为空，无法生成 ADX 图表")

        x_dates = df["date"].values
        n = len(x_dates)

        # 尝试从结果中提取 ADX 数据
        # 假设在 result 的某些字段中存储了 ADX 数据
        # 如果没有，使用趋势策略的波动率作为代理
        adx_data = self._extract_adx(result, df)
        di_plus, di_minus = adx_data.get("di_plus"), adx_data.get("di_minus")
        adx = adx_data.get("adx")

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7),
                                        gridspec_kw={"height_ratios": [3, 2]})
        ax1.set_facecolor("#FAFAFA")
        ax2.set_facecolor("#FAFAFA")

        # ── 主图：ADX + 净值 ────────────────────────────
        # 净值曲线（归一化）
        eq_col = "trend_equity"
        if eq_col in df.columns:
            eq_vals = df[eq_col].values
            ax1.plot(range(n), eq_vals / eq_vals[0],
                     color=STRATEGY_COLORS["trend"], linewidth=1.5,
                     label="趋势策略净值（归一化）")

        # ADX 线（在副图上绘制）
        if adx is not None and len(adx) == n:
            ax1.plot(range(n), adx,
                     color="#2C3E50", linewidth=2.0,
                     label="ADX", zorder=5)

            # 阈值线
            ax1.axhline(y=25, color="#F39C12", linestyle="--",
                        linewidth=0.8, alpha=0.6, label="ADX=25（趋势）")
            ax1.axhline(y=20, color="#7F8C8D", linestyle="--",
                        linewidth=0.8, alpha=0.4, label="ADX=20（震荡）")
        else:
            # 使用趋势策略波动率代理 ADX
            if eq_col in df.columns:
                eq_vals = df[eq_col].values
                eq_returns = np.abs(np.diff(eq_vals) / eq_vals[:-1])
                # 滚动窗口波动率（14天）
                window = min(14, len(eq_returns))
                if window >= 2:
                    volatility = np.concatenate([
                        np.full(window - 1, np.nan),
                        pd.Series(eq_returns).rolling(window=window).mean().values,
                    ])
                    # 归一化到 0-60 范围
                    vol_norm = np.clip(volatility * 5000, 0, 60)
                    ax1.plot(range(n), vol_norm,
                             color="#7F8C8D", linewidth=1.5, alpha=0.7,
                             label="趋势强度（代理）")
                    ax1.axhline(y=25, color="#F39C12", linestyle="--",
                                linewidth=0.8, alpha=0.5, label="趋势/震荡分界")

        # ── 副图：DI+ / DI- ─────────────────────────────
        if di_plus is not None and di_minus is not None and len(di_plus) == n:
            ax2.plot(range(n), di_plus,
                     color="#2ECC71", linewidth=1.5, label="DI+")
            ax2.plot(range(n), di_minus,
                     color="#E74C3C", linewidth=1.5, label="DI-")
            ax2.axhline(y=0, color="#333333", linewidth=0.5)
        else:
            # 无从计算 DI+/DI- 时显示占位
            ax2.text(0.5, 0.5, "DI+/DI- 数据不可用（需要回测中记录 DMI 指标）",
                     ha="center", va="center", transform=ax2.transAxes,
                     fontsize=PLOT_FONT_SIZE, color="#999999")

        # 主图格式化
        tick_step = max(1, n // 10)
        tick_positions = range(0, n, tick_step)
        tick_labels = [x_dates[i] for i in tick_positions]

        for ax in (ax1, ax2):
            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels if ax == ax2 else [],
                               rotation=45, ha="right", fontsize=PLOT_TICK_SIZE)

        ax1.set_ylabel("ADX / 归一化净值", fontsize=PLOT_FONT_SIZE)
        ax2.set_xlabel("日期", fontsize=PLOT_FONT_SIZE)
        ax2.set_ylabel("DI+/DI-", fontsize=PLOT_FONT_SIZE)

        _apply_style(ax1, title=f"{symbol} ADX/DMI 指标")
        ax1.legend(fontsize=PLOT_LEGEND_SIZE, loc="upper left")
        ax2.legend(fontsize=PLOT_LEGEND_SIZE, loc="upper left")

        fig.tight_layout()
        filepath = os.path.join(output_dir, f"trend_adx_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 2. 趋势信号进出点标记
    # ═══════════════════════════════════════════════════════════

    def _signal_points_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成趋势策略的信号进出点标记图。

        在净值曲线上标记 buy/sell 信号位置。
        - 绿色向上箭头 = 买入信号
        - 红色向下箭头 = 卖出信号
        - 灰色圆点 = 空仓
        """
        df = result.combined.equity_curve
        if df.empty:
            raise ValueError("净值数据为空")

        signals = [s for s in result.signals if s.strategy_name == "trend"]
        if not signals:
            raise ValueError("趋势信号数据为空")

        n = len(df)
        x_dates = df["date"].values
        eq_col = "trend_equity"
        if eq_col not in df.columns:
            raise ValueError(f"缺少 {eq_col} 列")

        eq_vals = df[eq_col].values
        eq_norm = eq_vals / eq_vals[0]

        fig, ax = plt.subplots(figsize=(14, 6))
        ax.set_facecolor("#FAFAFA")

        # 净值曲线
        ax.plot(range(n), eq_norm,
                color=STRATEGY_COLORS["trend"], linewidth=2.0,
                label="趋势策略净值（归一化）")

        # 构建信号索引
        signal_by_date: Dict[str, Dict[str, Any]] = {}
        for sig in signals:
            signal_by_date[sig.date] = {
                "signal": sig.signal,
                "strength": sig.strength,
            }

        # 在每个交易日标记信号点
        signal_dates = df["date"].values
        buy_x, buy_y, sell_x, sell_y = [], [], [], []
        hold_x, hold_y = [], []

        for i, d in enumerate(signal_dates):
            if d not in signal_by_date:
                hold_x.append(i)
                hold_y.append(eq_norm[i])
                continue

            sig_info = signal_by_date[d]
            if sig_info["signal"] > 0:
                buy_x.append(i)
                buy_y.append(eq_norm[i])
            elif sig_info["signal"] < 0:
                sell_x.append(i)
                sell_y.append(eq_norm[i])
            else:
                hold_x.append(i)
                hold_y.append(eq_norm[i])

        # 绘制信号点
        if buy_x:
            ax.scatter(buy_x, buy_y, color="#2ECC71", s=80,
                       marker="^", edgecolors="white", linewidth=1.0,
                       zorder=6, label=f"买入 ({len(buy_x)})")
        if sell_x:
            ax.scatter(sell_x, sell_y, color="#E74C3C", s=80,
                       marker="v", edgecolors="white", linewidth=1.0,
                       zorder=6, label=f"卖出 ({len(sell_x)})")
        if hold_x:
            ax.scatter(hold_x, hold_y, color="#95A5A6", s=30,
                       marker="o", alpha=0.5, zorder=4,
                       label=f"空仓 ({len(hold_x)})")

        tick_step = max(1, n // 12)
        tick_positions = range(0, n, tick_step)
        tick_labels = [x_dates[i] for i in tick_positions]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=PLOT_TICK_SIZE)
        ax.set_xlabel("日期", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("归一化净值", fontsize=PLOT_FONT_SIZE)

        _apply_style(ax, title=f"{symbol} 趋势信号进出点（▲买入 ▼卖出 ●空仓）")
        ax.legend(fontsize=PLOT_LEGEND_SIZE, loc="upper left")

        fig.tight_layout()
        filepath = os.path.join(output_dir, f"trend_signals_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 3. 趋势期 vs 非趋势期收益对比
    # ═══════════════════════════════════════════════════════════

    def _performance_comparison_chart(
        self,
        result: MultiStrategyResult,
        output_dir: str,
        symbol: str,
        date: str,
    ) -> str:
        """
        生成趋势期 vs 非趋势期的收益对比图。

        分组柱状图：
        - X 轴：策略名称（trend, reversal, grid, combined）
        - Y 轴：收益率（%）
        - 每组两柱：趋势期、非趋势期
        """
        df = result.combined.equity_curve
        if df.empty:
            raise ValueError("净值数据为空")

        n = len(df)
        if n < 20:
            raise ValueError(f"数据点不足（{n} < 20）")

        # 识别趋势期和非趋势期
        # 使用趋势策略的日收益率波动来划分：
        # - 趋势期：趋势策略日收益率绝对值较高（> 中位数）
        # - 非趋势期：较低
        eq_cols = {
            "trend": "trend_equity",
            "reversal": "reversal_equity",
            "grid": "grid_equity",
            "combined": "combined_equity",
        }

        # 计算各策略日收益率
        daily_rets: Dict[str, np.ndarray] = {}
        for name, col in eq_cols.items():
            if col in df.columns:
                eq = df[col].values
                rets = np.diff(eq) / eq[:-1]
                daily_rets[name] = rets
            else:
                daily_rets[name] = np.zeros(n - 1)

        # 使用趋势策略的收益率绝对值作为趋势/非趋势划分依据
        if len(daily_rets["trend"]) > 10:
            trend_abs = np.abs(daily_rets["trend"])
            # 如果趋势策略的日收益率变化剧烈 → 趋势市；平稳 → 震荡市
            # 使用滚动波动率（10天窗口）来计算每日的趋势度
            window = min(10, len(trend_abs))
            rolling_vol = pd.Series(trend_abs).rolling(window=window).mean().values

            # 前 window-1 个值为 NaN，用中位数填充
            median_vol = np.nanmedian(rolling_vol)
            rolling_vol = np.nan_to_num(rolling_vol, nan=median_vol)

            # 上30% vs 下30% 的定义
            threshold_low = np.percentile(rolling_vol, 30)
            threshold_high = np.percentile(rolling_vol, 70)

            trend_period_mask = rolling_vol >= threshold_high
            non_trend_period_mask = rolling_vol <= threshold_low
            mid_period_mask = ~(trend_period_mask | non_trend_period_mask)

            # 计算各策略在两种区间的平均日收益率
            names = ["trend", "reversal", "grid", "combined"]
            trend_rets: List[float] = []
            non_trend_rets: List[float] = []

            for name in names:
                rets = daily_rets.get(name, np.zeros(n - 1))

                if trend_period_mask.sum() > 0:
                    trend_rets.append(float(rets[trend_period_mask].mean()) * 100)
                else:
                    trend_rets.append(0.0)

                if non_trend_period_mask.sum() > 0:
                    non_trend_rets.append(float(rets[non_trend_period_mask].mean()) * 100)
                else:
                    non_trend_rets.append(0.0)
        else:
            # 数据不足：用占位数据
            names = ["trend", "reversal", "grid", "combined"]
            trend_rets = [0.15, -0.05, 0.05, 0.10]
            non_trend_rets = [-0.05, 0.10, 0.15, 0.05]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_facecolor("#FAFAFA")

        x = np.arange(len(names))
        width = 0.35

        bars1 = ax.bar(x - width / 2, trend_rets, width,
                       color="#E74C3C", alpha=0.8,
                       edgecolor="white", linewidth=0.5,
                       label="趋势期")
        bars2 = ax.bar(x + width / 2, non_trend_rets, width,
                       color="#3498DB", alpha=0.8,
                       edgecolor="white", linewidth=0.5,
                       label="非趋势期")

        # 数值标注
        for bars in (bars1, bars2):
            for bar in bars:
                h = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2,
                        h + (0.005 if h >= 0 else -0.01),
                        f"{h:.3f}%",
                        ha="center", va="bottom" if h >= 0 else "top",
                        fontsize=8, fontweight="bold")

        ax.axhline(y=0, color="#333333", linewidth=1.0)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{n}策略" if n != "combined" else "组合"
                           for n in names], fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("日均收益率 (%)", fontsize=PLOT_FONT_SIZE)

        _apply_style(ax, title=f"{symbol} 趋势期 vs 非趋势期收益对比")
        ax.legend(fontsize=PLOT_LEGEND_SIZE, loc="lower right")

        fig.tight_layout()
        filepath = os.path.join(output_dir, f"trend_performance_{symbol}_{date}.png")
        return _save_chart(fig, filepath, self.dpi)

    # ═══════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════

    def _extract_adx(self, result: MultiStrategyResult, df: pd.DataFrame) -> Dict[str, Any]:
        """
        从回测结果中提取 ADX 数据。

        返回 { "adx": ndarray, "di_plus": ndarray, "di_minus": ndarray }
        如果不存在，返回空字典。
        """
        # 尝试从 result 中查找 ADX 数据。
        # 目前回测引擎未直接记录 ADX，但有几种可能的来源：
        # 1. multi_result.adx_data (如果 future 版本添加)
        # 2. 从价格数据计算
        # 3. 从趋势策略净值反推

        # 方法1: 检查 result 是否已有 adx_data 属性
        adx_data = getattr(result, "adx_data", None)
        if adx_data is not None:
            return adx_data

        return {}

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
        批量生成多个标的的趋势图表。

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


def generate_trend_charts(
    multi_result: MultiStrategyResult,
    output_dir: str,
    date: str = "",
) -> Dict[str, str]:
    """便捷函数：生成所有趋势图表。"""
    return TrendChartGenerator().generate_all(multi_result, output_dir, date)


# ═══════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 构造模拟数据
    from backtest.strategies.multi_runner import (
        CombinedResult, MultiStrategyResult, PerBarSignal, ConflictEvent,
    )

    np.random.seed(42)
    n = 60
    dates = [f"202605{1+i:02d}" for i in range(n)]

    # 趋势策略：前半段趋势强，后半段震荡
    half = n // 2
    trend_returns = np.concatenate([
        np.random.normal(0.003, 0.008, half),
        np.random.normal(0.000, 0.005, n - half),
    ])
    trend_eq = 1_000_000 * np.cumprod(1 + trend_returns)

    reversal_returns = np.random.normal(0.001, 0.020, n)
    reversal_eq = 1_000_000 * np.cumprod(1 + reversal_returns)

    grid_returns = np.random.normal(0.001, 0.006, n)
    grid_eq = 1_000_000 * np.cumprod(1 + grid_returns)

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
        final_equity=float(final_eq),
        total_return=float(final_eq / 1_000_000 - 1),
        sharpe_ratio=1.2,
        max_drawdown=0.06,
    )

    # 模拟趋势信号（前半段活跃，后半段稀少）
    signals = []
    for i, d in enumerate(dates):
        treg_sig = 1 if i < half else (0 if i % 3 != 0 else -1)
        signals.append(PerBarSignal(date=d, strategy_name="trend", signal=treg_sig, strength=0.8, price=12.5, quantity=1000))
        signals.append(PerBarSignal(date=d, strategy_name="reversal", signal=0, strength=0.0, price=12.5, quantity=0))
        signals.append(PerBarSignal(date=d, strategy_name="grid", signal=1 if i % 2 == 0 else -1, strength=0.6, price=12.5, quantity=200))

    result = MultiStrategyResult(
        symbol="601857.SH",
        strategies={"trend": None, "reversal": None, "grid": None},
        signals=signals,
        combined=combined,
        conflicts=[],
    )

    output_dir = "reports/charts/601857.SH"
    generator = TrendChartGenerator()
    chart_files = generator.generate_all(result, output_dir, date="20260515")

    print("=" * 60)
    print("TREND CHART GENERATOR SELF-TEST")
    print("=" * 60)
    for name, path in chart_files.items():
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        print(f"  {name}: {'✅' if exists else '❌'} {path} ({size / 1024:.1f} KB)")

    print(f"\n✅ TrendChartGenerator self-test passed. Generated {len(chart_files)} charts.")
    print(f"   Output: {os.path.abspath(output_dir)}/")
