#!/usr/bin/env python3
"""
墨枢 Phase 1 — IC/IR 检验框架（TASK-3）
===========================================
Author: 墨衡
Created: 2026-05-22T22:20+08:00

用途：对 daily_factors 表中的各因子进行 IC/IR 检验。

检验指标：
  - Rank IC（截面秩相关）：每交易日因子值与下一期收益率的 Spearman 相关系数
  - IR：IC 均值 / IC 标准差（信息比率）
  - IC 累计曲线：滚动累加
  - 因子相关性矩阵：因子间的 Pearson/Spearman 相关
  - 分层回测：按因子值分 3 层，统计各层收益

输入：daily_factors 表（由 TASK-2 填充）
输出：
  - reports/phase1_icir_*.png 可视化图表
  - reports/phase1_icir_report.md 检验报告

执行：
  python scripts/phase1_icir_test.py

依赖：
  - numpy, pandas, matplotlib
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ── 项目路径 ──────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

ANALYSIS_DB = os.path.join(PROJECT_ROOT, "data", "db", "analysis.db")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports")

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# matplotlib 中文字体
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# 因子列表（按类别分组）
FACTOR_GROUPS = OrderedDict({
    "价格动量": [
        "p_mom_rsi", "p_mom_roc5", "p_mom_roc10", "p_mom_roc20",
        "p_mom_williams_r", "p_mom_cci", "p_mom_tsi",
        "p_mom_price_velocity", "p_mom_mtm", "p_mom_acceleration",
    ],
    "趋势品质": [
        "l_trd_adx", "l_trd_strength", "l_trd_consistency",
        "l_trd_ma_slope", "l_trd_alignment", "l_trd_width",
        "l_trd_breadth", "l_trd_composite_score",
    ],
    "波动率": [
        "l_vol_bb_width", "l_vol_bb_squeeze", "l_vol_rsi_std",
        "l_vol_price_std", "l_vol_atr", "l_vol_atr_ratio",
        "l_vol_log_ret_std", "l_vol_skew", "l_vol_kurt",
    ],
    "超买超卖": [
        "l_obo_rsi_level", "l_obo_rsi_extreme",
        "l_obo_kdj_level", "l_obo_kdj_extreme", "l_obo_cci_level",
    ],
    "量价": [
        "l_vol_ratio", "l_vol_smart_money", "l_vol_trend",
        "l_vol_vwap_dev", "l_vol_vwap_5_dev", "l_vol_vwap_20_dev",
        "l_vol_dollar_vol",
    ],
    "结构": [
        "l_str_structure_quality", "l_str_gap_up", "l_str_gap_down",
        "l_str_ma5_ma20_cross", "l_str_kdj_k", "l_str_kdj_d", "l_str_kdj_j",
        "l_str_bb_position",
    ],
})

# 所有因子扁平列表
ALL_FACTORS = [f for group_factors in FACTOR_GROUPS.values() for f in group_factors]
# 排除分类变量（非数值因子）
CATEGORICAL_FACTORS = {
    "p_mom_macd_dir", "l_vol_bb_squeeze", "l_obo_rsi_level",
    "l_obo_rsi_extreme", "l_obo_kdj_level", "l_obo_kdj_extreme",
    "l_obo_cci_level", "l_vol_ma5_cross", "l_str_gap_up", "l_str_gap_down",
    "l_str_ma5_ma20_cross", "l_str_ma20_ma60_cross", "l_str_close_vs_vwap",
}
NUMERIC_FACTORS = [f for f in ALL_FACTORS if f not in CATEGORICAL_FACTORS]


# ════════════════════════════════════════════════════════
# 数据加载
# ════════════════════════════════════════════════════════

def load_panel_data() -> pd.DataFrame:
    """
    加载因子 + 收益率的面板数据。

    返回 MultiIndex DataFrame: (date, code) × factor_values + forward_return
    forward_return = 下一交易日的对数收益率（日频）。
    """
    logger.info("加载因子数据...")
    conn = sqlite3.connect(ANALYSIS_DB)

    feature_cols = ", ".join(ALL_FACTORS)
    query = f"""
        SELECT f.code, f.date, f.{feature_cols},
               s.close
        FROM daily_factors f
        JOIN stock_daily s ON f.code = s.code AND f.date = s.date
        ORDER BY f.date, f.code
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        logger.error("无因子数据可加载")
        return df

    # 计算下一期收益率
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["returns"] = df.groupby("code")["close"].pct_change(-1) * 100  # 下一期%收益率
    df["log_returns"] = np.log(df["close"] / df.groupby("code")["close"].shift(1))

    # 移除 NaN 收益率
    df = df.dropna(subset=["returns", "log_returns"])

    # 按 (date, code) 排序
    df = df.set_index(["date", "code"]).sort_index()
    df.index.names = ["date", "code"]

    logger.info("面板数据: %d 行 (日期x标的), %d 因子", len(df), len(ALL_FACTORS))
    return df


# ════════════════════════════════════════════════════════
# Rank IC 计算
# ════════════════════════════════════════════════════════

def spearman_rank_corr(x: pd.Series, y: pd.Series) -> float:
    """手工计算 Spearman 秩相关（避免 scipy 依赖）"""
    x = x.dropna()
    y = y.dropna()
    common = x.index.intersection(y.index)
    if len(common) < 3:
        return 0.0
    xc = x.loc[common].rank()
    yc = y.loc[common].rank()
    n = len(common)
    d = (xc - yc) ** 2
    return 1.0 - 6.0 * d.sum() / (n * (n * n - 1))


def calc_daily_rank_ic(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算每日截面 Rank IC。

    对每个交易日：
      - 取该日因子值（全截面）
      - 取该日标的的 forward_return
      - 计算 Spearman 秩相关

    返回：Date × FactorName 的 IC 矩阵
    """
    logger.info("计算每日 Rank IC...")
    dates = sorted(df.index.get_level_values("date").unique())
    ic_records = []

    for date in dates:
        cross = df.xs(date, level="date")
        if len(cross) < 3:
            continue
        ic_row = {"date": date}
        for factor in NUMERIC_FACTORS:
            if factor not in cross.columns:
                continue
            # 因子前向收益率
            ic_val = spearman_rank_corr(cross[factor], cross["returns"])
            ic_row[factor] = ic_val
        ic_records.append(ic_row)

    ic_df = pd.DataFrame(ic_records).set_index("date")
    logger.info("IC 表: %d 交易日 x %d 因子", len(ic_df), len(NUMERIC_FACTORS))
    return ic_df


# ════════════════════════════════════════════════════════
# IC/IR 统计
# ════════════════════════════════════════════════════════

def calc_icir_stats(ic_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算各因子的 IC/IR 统计量。

    返回 DataFrame:
      factor, mean_ic, std_ic, ir, ic_positive_ratio, ic_abs_mean, ic_win_rate
    """
    stats = []
    for factor in NUMERIC_FACTORS:
        if factor not in ic_df.columns:
            continue
        series = ic_df[factor].dropna()
        if len(series) < 10:
            continue
        mean_ic = series.mean()
        std_ic = series.std()
        ir = mean_ic / std_ic if std_ic > 0 else 0.0
        pos_ratio = (series > 0).sum() / len(series)
        abs_mean = series.abs().mean()

        stats.append({
            "factor": factor,
            "mean_ic": round(mean_ic, 4),
            "std_ic": round(std_ic, 4),
            "ir": round(ir, 4),
            "ic_positive_ratio": round(pos_ratio, 4),
            "ic_abs_mean": round(abs_mean, 4),
            "t_count": len(series),
        })

    return pd.DataFrame(stats).sort_values("ir", ascending=False)


def calc_factor_corr(ic_df: pd.DataFrame) -> pd.DataFrame:
    """计算 IC 序列间的相关性矩阵"""
    corr = ic_df[NUMERIC_FACTORS].corr(method=lambda x, y: spearman_rank_corr(pd.Series(x), pd.Series(y)))
    return corr


# ════════════════════════════════════════════════════════
# 分层回测
# ════════════════════════════════════════════════════════

def calc_layer_returns(df: pd.DataFrame, factor: str, n_layers: int = 3) -> pd.DataFrame:
    """
    按因子值分 n_layers 层，计算各层的每日收益。

    每一层内的标的等权配置。
    """
    dates = sorted(df.index.get_level_values("date").unique())
    layer_rets = []

    for date in dates:
        cross = df.xs(date, level="date").dropna(subset=[factor])
        if len(cross) < n_layers * 2:
            continue

        # 按因子值排序分桶
        sorted_cross = cross.sort_values(factor, ascending=True)
        bin_size = len(sorted_cross) // n_layers
        remainder = len(sorted_cross) % n_layers

        rets_for_day = {}
        start = 0
        for layer in range(n_layers):
            end = start + bin_size + (1 if layer < remainder else 0)
            if end > start:
                layer_ret = sorted_cross.iloc[start:end]["returns"].mean()
                rets_for_day[f"L{layer+1}"] = layer_ret
            start = end

        # L3 - L1（多空组合）
        if "L1" in rets_for_day and "L3" in rets_for_day:
            rets_for_day["L3-L1"] = rets_for_day["L3"] - rets_for_day["L1"]

        rets_for_day["date"] = date
        layer_rets.append(rets_for_day)

    layer_df = pd.DataFrame(layer_rets).set_index("date")
    return layer_df


def calc_all_layer_returns(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """计算所有因子的分层收益"""
    layer_results = {}
    for factor in NUMERIC_FACTORS:
        if factor == "l_str_gap_up" or factor == "l_str_gap_down":
            continue  # 跳过极端稀疏因子
        layer_df = calc_layer_returns(df, factor)
        if not layer_df.empty:
            layer_results[factor] = layer_df
    return layer_results


# ════════════════════════════════════════════════════════
# 可视化
# ════════════════════════════════════════════════════════

def plot_ic_strip(ic_df: pd.DataFrame, icir_stats: pd.DataFrame, filepath: str):
    """IC 热力图（各因子 IC 时间序列）"""
    n_factors = min(len(NUMERIC_FACTORS), 40)
    fig, axes = plt.subplots(n_factors, 1, figsize=(14, n_factors * 0.6), sharex=True)
    if n_factors == 1:
        axes = [axes]

    dates = ic_df.index

    for idx, factor in enumerate(NUMERIC_FACTORS[:n_factors]):
        ax = axes[idx]
        if factor in ic_df.columns:
            series = ic_df[factor].dropna()
            ax.fill_between(
                pd.to_datetime(series.index),
                0, series.values, where=series.values > 0,
                color="red", alpha=0.4, linewidth=0.3
            )
            ax.fill_between(
                pd.to_datetime(series.index),
                0, series.values, where=series.values < 0,
                color="green", alpha=0.4, linewidth=0.3
            )
            ax.axhline(y=0, color="black", linewidth=0.3)
        ax.set_ylabel(factor[-20:], fontsize=5)
        ax.set_ylim(-0.8, 0.8)
        ax.tick_params(labelsize=4)

    fig.suptitle("各因子每日 IC 时间序列", fontsize=10, y=1.01)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("IC 时序图已保存: %s", filepath)


def plot_icir_bar(icir_stats: pd.DataFrame, filepath: str, top_n: int = 30):
    """IC/IR 柱状图（Top-N）"""
    top = icir_stats.head(top_n)
    if top.empty:
        return

    fig, axes = plt.subplots(3, 1, figsize=(12, 12))

    # Mean IC
    colors = ["red" if v > 0 else "green" for v in top["mean_ic"]]
    axes[0].barh(range(len(top)), top["mean_ic"], color=colors, height=0.6)
    axes[0].set_yticks(range(len(top)))
    axes[0].set_yticklabels(top["factor"].apply(lambda x: x[-24:]), fontsize=7)
    axes[0].axvline(x=0, color="black", linewidth=0.5)
    axes[0].set_title("Mean IC", fontsize=10)

    # IR
    colors2 = ["red" if v > 0 else "green" for v in top["ir"]]
    axes[1].barh(range(len(top)), top["ir"], color=colors2, height=0.6)
    axes[1].set_yticks(range(len(top)))
    axes[1].set_yticklabels(top["factor"].apply(lambda x: x[-24:]), fontsize=7)
    axes[1].axvline(x=0, color="black", linewidth=0.5)
    axes[1].set_title("IR (Information Ratio)", fontsize=10)

    # IC Positive Ratio
    colors3 = ["red" if v > 0.5 else "green" for v in top["ic_positive_ratio"]]
    axes[2].barh(range(len(top)), top["ic_positive_ratio"], color=colors3, height=0.6)
    axes[2].set_yticks(range(len(top)))
    axes[2].set_yticklabels(top["factor"].apply(lambda x: x[-24:]), fontsize=7)
    axes[2].axvline(x=0.5, color="black", linewidth=0.5, linestyle="--")
    axes[2].set_title("IC Positive Ratio", fontsize=10)
    axes[2].set_xlim(0, 1)

    fig.suptitle(f"因子 IC/IR 检验 — Top {top_n}", fontsize=12, y=1.01)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("IC/IR 柱状图已保存: %s", filepath)


def plot_cumulative_ic(ic_df: pd.DataFrame, filepath: str):
    """IC 累计曲线（按类别分组）"""
    fig, axes = plt.subplots(3, 2, figsize=(16, 12))
    axes_flat = axes.flatten()

    for idx, (group_name, factors) in enumerate(FACTOR_GROUPS.items()):
        if idx >= len(axes_flat):
            break
        ax = axes_flat[idx]

        for factor in factors:
            if factor not in ic_df.columns:
                continue
            cumic = ic_df[factor].dropna().cumsum()
            ax.plot(pd.to_datetime(cumic.index), cumic.values, label=factor[-12:], linewidth=0.6)

        ax.axhline(y=0, color="black", linewidth=0.3)
        ax.set_title(f"IC 累计 — {group_name}", fontsize=9)
        ax.legend(fontsize=5, ncol=2)
        ax.tick_params(labelsize=6)

    # 隐藏多余子图
    for idx in range(len(FACTOR_GROUPS), len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle("因子 IC 累计曲线（按类别）", fontsize=12)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("IC 累计曲线已保存: %s", filepath)


def plot_factor_corr(corr_mat: pd.DataFrame, filepath: str, top_n: int = 20):
    """因子相关性矩阵热力图"""
    # 取 IR top N
    top_factors = NUMERIC_FACTORS[:top_n]
    valid = [f for f in top_factors if f in corr_mat.columns]
    sub_corr = corr_mat.loc[valid, valid]

    fig, ax = plt.subplots(figsize=(14, 12))
    im = ax.imshow(sub_corr.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")

    ax.set_xticks(range(len(valid)))
    ax.set_yticks(range(len(valid)))
    ax.set_xticklabels([f[-12:] for f in valid], rotation=90, fontsize=5)
    ax.set_yticklabels([f[-12:] for f in valid], fontsize=5)

    plt.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(f"因子 IC 相关性矩阵 (Top {top_n})", fontsize=10)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("因子相关性矩阵已保存: %s", filepath)


def plot_layer_returns(layer_results: Dict[str, pd.DataFrame], filepath: str, top_n: int = 10):
    """Top-N 因子的分层收益累计曲线 + 多空收益"""
    # 按多空收益IR排序
    l3l1_ir = {}
    for factor, ldf in layer_results.items():
        if "L3-L1" in ldf.columns and len(ldf) > 10:
            l3l1 = ldf["L3-L1"].dropna()
            ir = l3l1.mean() / l3l1.std() if l3l1.std() > 0 else 0
            l3l1_ir[factor] = (ir, ldf)

    sorted_factors = sorted(l3l1_ir.items(), key=lambda x: abs(x[1][0]), reverse=True)
    top_factors = sorted_factors[:top_n]

    fig, axes = plt.subplots(min(top_n, 10), 2, figsize=(16, min(top_n, 10) * 2.5))
    if top_n == 1:
        axes = [axes]

    for idx, (factor, (ir_val, ldf)) in enumerate(top_factors[:10]):
        ax1 = axes[idx][0] if top_n > 1 else axes[0]
        ax2 = axes[idx][1] if top_n > 1 else axes[1]

        # 累计收益
        for layer in ["L1", "L2", "L3"]:
            if layer in ldf.columns:
                cum = ldf[layer].dropna().cumsum()
                ax1.plot(pd.to_datetime(cum.index), cum.values, label=layer, linewidth=0.6)

        ax1.set_title(f"{factor[-24:]} 分层累计收益", fontsize=7)
        ax1.legend(fontsize=5)
        ax1.tick_params(labelsize=5)
        ax1.axhline(y=0, color="gray", linewidth=0.3)

        # 多空收益
        if "L3-L1" in ldf.columns:
            cum_l3l1 = ldf["L3-L1"].dropna().cumsum()
            ax2.plot(pd.to_datetime(cum_l3l1.index), cum_l3l1.values, color="purple", linewidth=0.8)
            ax2.set_title(f"L3-L1 累计多空收益 (IR={ir_val:.3f})", fontsize=7)
            ax2.tick_params(labelsize=5)
            ax2.axhline(y=0, color="gray", linewidth=0.3)

    fig.suptitle(f"分层回测收益（Top {min(top_n, 10)} × IR）", fontsize=10)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("分层回测图已保存: %s", filepath)


# ════════════════════════════════════════════════════════
# 报告生成
# ════════════════════════════════════════════════════════

def generate_markdown_report(icir_stats: pd.DataFrame, ic_df: pd.DataFrame, layer_results: Dict[str, pd.DataFrame]) -> str:
    """生成 Markdown 检验报告"""
    lines = [
        "# 墨枢 Phase 1 — 因子 IC/IR 检验报告",
        f"**报告时间:** {datetime.now().strftime('%Y-%m-%d %H:%M')} +08:00",
        f"**标的数:** 12  |  **因子数:** {len(NUMERIC_FACTORS)}  |  **交易日:** {len(ic_df)}",
        "",
        "---",
        "## 一、IC/IR 总览",
        "",
        "| 指标 | 值 | 评价 |",
        "|------|-----|------|",
    ]

    # 全局统计
    all_ic = ic_df[NUMERIC_FACTORS].values.flatten()
    all_ic = all_ic[~np.isnan(all_ic)]
    global_mean = np.mean(all_ic)
    global_std = np.std(all_ic)
    global_ir = global_mean / global_std if global_std > 0 else 0
    global_pos = np.sum(all_ic > 0) / len(all_ic)

    lines.append(f"| 全局平均 IC | {global_mean:.4f} | {'✓ 正向预测力' if global_mean > 0 else '✗ 负向或随机'} |")
    lines.append(f"| 全局 IC 标准差 | {global_std:.4f} | — |")
    lines.append(f"| 全局 IR | {global_ir:.4f} | {'✓ > 0.5 可用' if abs(global_ir) > 0.5 else 'ℹ 需改进'} |")
    lines.append(f"| IC 正值比例 | {global_pos:.2%} | {'✓ 偏正向' if global_pos > 0.5 else 'ℹ 正向不足'} |")

    lines += [
        "",
        "---",
        "## 二、Top 20 因子（按 IR 排序）",
        "",
        "| 排名 | 因子名 | Mean IC | Std IC | IR | 正值比 | 检验天数 |",
        "|------|--------|---------|--------|-----|--------|---------|",
    ]

    top20 = icir_stats.head(20)
    for idx, (_, row) in enumerate(top20.iterrows()):
        lines.append(
            f"| {idx+1} | {row['factor']} | {row['mean_ic']:.4f} | "
            f"{row['std_ic']:.4f} | {row['ir']:.4f} | "
            f"{row['ic_positive_ratio']:.2%} | {row['t_count']} |"
        )

    lines += [
        "",
        "---",
        "## 三、Bottom 10 因子（按 IR 排序）",
        "",
        "| 排名 | 因子名 | Mean IC | Std IC | IR | 正值比 |",
        "|------|--------|---------|--------|-----|--------|",
    ]

    bottom10 = icir_stats.tail(10).iloc[::-1]
    for idx, (_, row) in enumerate(bottom10.iterrows()):
        lines.append(
            f"| {idx+1} | {row['factor']} | {row['mean_ic']:.4f} | "
            f"{row['std_ic']:.4f} | {row['ir']:.4f} | "
            f"{row['ic_positive_ratio']:.2%} |"
        )

    lines += [
        "",
        "---",
        "## 四、分层回测（L3-L1 多空收益）",
        "",
        "| 因子名 | L1 均值 | L2 均值 | L3 均值 | L3-L1 均值 | L3-L1 IR |",
        "|--------|---------|---------|---------|-----------|---------|",
    ]

    # 按 |IR| 降序排列分层结果
    layer_rows = []
    for factor, ldf in layer_results.items():
        if "L1" not in ldf.columns or "L3-L1" not in ldf.columns:
            continue
        l3l1 = ldf["L3-L1"].dropna()
        l1_mean = ldf["L1"].mean()
        l2_mean = ldf["L2"].mean()
        l3_mean = ldf["L3"].mean()
        l3l1_mean = l3l1.mean()
        l3l1_ir = l3l1.mean() / l3l1.std() if l3l1.std() > 0 else 0
        layer_rows.append((abs(l3l1_ir), factor, l1_mean, l2_mean, l3_mean, l3l1_mean, l3l1_ir))

    layer_rows.sort(key=lambda x: x[0], reverse=True)
    for _, factor, l1, l2, l3, l3l1_m, l3l1_ir in layer_rows[:20]:
        lines.append(
            f"| {factor[-24:]} | {l1:.4f} | {l2:.4f} | {l3:.4f} | "
            f"{l3l1_m:.4f} | {l3l1_ir:.3f} |"
        )

    lines += [
        "",
        "---",
        "## 五、检验结论",
        "",
    ]

    # 综合评估
    strong_factors = icir_stats[icir_stats["ir"].abs() > 0.5]
    weak_factors = icir_stats[icir_stats["ir"].abs() < 0.1]

    lines.append(f"- **有效因子数 (IR > 0.5):** {len(strong_factors)} / {len(icir_stats)}")
    lines.append(f"- **无效因子数 (IR < 0.1):** {len(weak_factors)} / {len(icir_stats)}")
    lines.append(f"- **全局 IR:** {global_ir:.4f}")
    lines.append("")

    if len(strong_factors) > 5:
        lines.append("🟢 **结论:** 有效因子数量充足，因子体系初步可用。建议进一步优化其中 5-10 个最佳因子用于实盘信号。")
    elif len(strong_factors) > 0:
        lines.append("🟡 **结论:** 部分因子有效，但整体预测力有限。建议分析因子构造或数据质量。")
    else:
        lines.append("🔴 **结论:** 无明显有效因子。建议检查数据质量、因子计算逻辑或市场结构是否发生变化。")

    lines += [
        "",
        "---",
        "*报告由 墨枢 Phase 1 IC/IR 检验框架自动生成*",
    ]

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════

def main():
    os.makedirs(REPORT_DIR, exist_ok=True)

    logger.info("=" * 60)
    logger.info("  墨枢 Phase 1 — IC/IR 检验 （TASK-3）")
    logger.info("=" * 60)

    # 1. 加载面板数据
    df = load_panel_data()
    if df.empty:
        logger.error("无数据可分析")
        return 1

    # 2. 计算每日 Rank IC
    ic_df = calc_daily_rank_ic(df)
    if ic_df.empty:
        logger.error("IC 计算无产出")
        return 1

    # 3. IC/IR 统计
    icir_stats = calc_icir_stats(ic_df)
    logger.info("IC/IR 统计完成")
    logger.info("Top 5 by IR:\n%s", icir_stats.head(5).to_string())

    # 4. 因子相关性矩阵
    corr_mat = calc_factor_corr(ic_df)
    logger.info("因子相关性矩阵完成")

    # 5. 分层回测
    layer_results = calc_all_layer_returns(df)
    logger.info("分层回测完成: %d 个因子", len(layer_results))

    # 6. 可视化
    plot_ic_strip(ic_df, icir_stats, os.path.join(REPORT_DIR, "phase1_icir_ts.png"))
    plot_icir_bar(icir_stats, os.path.join(REPORT_DIR, "phase1_icir_bar.png"), top_n=30)
    plot_cumulative_ic(ic_df, os.path.join(REPORT_DIR, "phase1_icir_cumulative.png"))
    plot_factor_corr(corr_mat, os.path.join(REPORT_DIR, "phase1_icir_corr.png"), top_n=20)
    plot_layer_returns(layer_results, os.path.join(REPORT_DIR, "phase1_icir_layers.png"), top_n=10)

    # 7. 生成报告
    report_md = generate_markdown_report(icir_stats, ic_df, layer_results)
    report_path = os.path.join(REPORT_DIR, "phase1_icir_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    logger.info("检验报告已保存: %s", report_path)

    # 8. CSV 导出
    csv_path = os.path.join(REPORT_DIR, "phase1_icir_stats.csv")
    icir_stats.to_csv(csv_path, index=False)
    logger.info("IC/IR 统计表已导出: %s", csv_path)

    logger.info("\n" + "=" * 60)
    logger.info("  IC/IR 检验完成!")
    logger.info("  产出文件:")
    logger.info("    - reports/phase1_icir_ts.png")
    logger.info("    - reports/phase1_icir_bar.png")
    logger.info("    - reports/phase1_icir_cumulative.png")
    logger.info("    - reports/phase1_icir_corr.png")
    logger.info("    - reports/phase1_icir_layers.png")
    logger.info("    - reports/phase1_icir_report.md")
    logger.info("    - reports/phase1_icir_stats.csv")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
