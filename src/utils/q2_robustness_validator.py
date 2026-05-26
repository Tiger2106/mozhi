# -*- coding: utf-8 -*-
"""
q2_robustness_validator.py — Q2 Robustness Validator 参数稳定性验证器

检查策略在最优参数邻域内微调时的性能衰减是否平缓。
通过在最优参数周围 ±20% 范围内扰动，评估 Sharpe/收益/回撤等关键指标
的敏感性。若性能衰减剧烈 → 标记为 PARAMETER_PEAK（参数尖峰风险）。

定位：
  Layer Q — Transverse Governance Layer（横向治理层）
  Q2 Robustness — 参数稳健性维度质量审计

设计说明：
  - 输入：TradeRecord 列表 + 参数邻域描述（param_ranges 字典）
  - 方法：在最优参数周围 ±20% 扫描，检查性能衰减曲线是否平缓
  - 输出：RobustnessResult 包含 is_robust, confidence, sensitivity_scores, plateau, fail_reason
  - 使用 P3_param_stability 数据验证概念：热力图分析 + 边际衰减检查
  - 当 ParamGrid 完整数据可用时使用敏感性分析；数据稀疏时使用保守评估

数据来源：
  - 理想输入：P3_param_stability 报告的热力图 JSON 数据
  - 通用输入：TradeRecord 列表（逐笔交易记录）
  - 参数：param_ranges 描述参数邻域及最优参数点

作者：墨衡 (moheng)
创建时间：2026-05-19 17:13 GMT+8
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    from src.utils.existence_validator import TradeRecord
except ImportError:
    from existence_validator import TradeRecord


# ============================================================
# 常量
# ============================================================

# 默认扰动幅度（最优参数 ± %）
_DEFAULT_PERTURBATION_PCT: float = 0.20

# 性能衰减阈值（超过此值标记为敏感）
_DEFAULT_DECAY_THRESHOLD_SHARPE: float = 0.30
_DEFAULT_DECAY_THRESHOLD_RETURN: float = 0.35
_DEFAULT_DECAY_THRESHOLD_DRAWDOWN: float = 0.25

# 平台判定：若 ±5% 扰动内的性能波动 < 此值，视为存在稳定平台
_PLATEAU_THRESHOLD_SHARPE: float = 0.10

# 置信度计算权重
_CONFIDENCE_SENSITIVITY_WEIGHT: float = 0.50
_CONFIDENCE_PLATEAU_WEIGHT: float = 0.20
_CONFIDENCE_SAMPLE_WEIGHT: float = 0.30


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ParamPoint:
    """单个参数点的绩效快照"""
    config_key: str          # 参数组合标识（如 "arit_n5_cd1_fixed_nosl_vt0.5"）
    params: dict[str, Any]   # 参数字典
    sharpe: float            # 夏普比率
    annual_return: float     # 年化收益率
    max_drawdown: float      # 最大回撤
    n_trades: int            # 交易次数


@dataclass
class SensitivityScore:
    """单参数的敏感性评分"""
    param_name: str          # 参数名称
    sensitivity: float       # 敏感性 [0, 1]，越高越敏感（脆弱）
    decay_sharpe: float      # 夏普衰减比例
    decay_return: float      # 收益衰减比例
    decay_drawdown: float    # 回撤恶化比例
    is_influential: bool     # 是否属于"关键参数"
    analysis_note: str       # 分析说明


@dataclass
class RobustnessResult:
    """参数稳定性验证结果

    Attributes
    ----------
    is_robust : bool
        True = 参数整体鲁棒（性能衰减平缓，无明显尖峰）
    confidence : float
        稳定性置信度 [0.0, 1.0]
    sensitivity_scores : dict[str, SensitivityScore]
        各参数的敏感性评分，key 为参数名称
    plateau : bool
        是否存在稳定平台（±5% 扰动内性能波动 < 阈值）
    dominant_sensitive_param : str | None
        最敏感的参数的名称（若存在）
    decay_summary : str
        衰减情况的一句话总结
    fail_reason : str | None
        不通过时的原因说明
    details : dict
        详细辅助信息
    """
    is_robust: bool
    confidence: float
    sensitivity_scores: dict[str, SensitivityScore]
    plateau: bool
    dominant_sensitive_param: Optional[str]
    decay_summary: str
    fail_reason: Optional[str]
    details: dict[str, Any]


@dataclass
class RobustnessConfig:
    """Robustness Validator 配置参数"""
    perturbation_pct: float = _DEFAULT_PERTURBATION_PCT
    decay_threshold_sharpe: float = _DEFAULT_DECAY_THRESHOLD_SHARPE
    decay_threshold_return: float = _DEFAULT_DECAY_THRESHOLD_RETURN
    decay_threshold_drawdown: float = _DEFAULT_DECAY_THRESHOLD_DRAWDOWN
    plateau_threshold_sharpe: float = _PLATEAU_THRESHOLD_SHARPE


# ============================================================
# 核心验证函数
# ============================================================

def _calc_decay_ratio(optimal_value: float, perturbed_value: float) -> float:
    """计算性能衰减比例

    正值表示衰减（性能下降），负值表示改善（扰动后更好）。

    Parameters
    ----------
    optimal_value : float
        最优参数点的性能指标值
    perturbed_value : float
        扰动后的性能指标值

    Returns
    -------
    float
        衰减比例，范围 [0.0, ~)，
        其中 0 = 无衰减，0.3 = 衰减 30%
    """
    if abs(optimal_value) < 1e-12:
        return abs(perturbed_value) if abs(perturbed_value) > 1e-12 else 0.0
    # 对夏普/收益：下降是衰减
    if optimal_value > 0:
        return max(0.0, (optimal_value - perturbed_value) / optimal_value)
    # 最优为负（罕见）：上升反而是衰减
    return max(0.0, (perturbed_value - optimal_value) / abs(optimal_value))


def _calc_drawdown_worsening(optimal_dd: float, perturbed_dd: float) -> float:
    """计算回撤恶化比例（回撤增大为恶化）"""
    if optimal_dd <= 0:
        # 无回撤基线
        return perturbed_dd if perturbed_dd > 0 else 0.0
    return max(0.0, (perturbed_dd - optimal_dd) / optimal_dd)


def _compute_sensitivity(
    param_name: str,
    param_points: list[ParamPoint],
    optimal_point: ParamPoint,
    config: RobustnessConfig,
) -> SensitivityScore:
    """计算单个参数的敏感性评分

    通过对比扰动参数点与最优参数点的绩效差异，
    评估该参数的敏感程度。

    Parameters
    ----------
    param_name : str
        参数名称
    param_points : list[ParamPoint]
        该参数所有扰动点的绩效数据
    optimal_point : ParamPoint
        全局最优参数点的绩效

    Returns
    -------
    SensitivityScore
    """
    if not param_points:
        return SensitivityScore(
            param_name=param_name,
            sensitivity=0.0,
            decay_sharpe=0.0,
            decay_return=0.0,
            decay_drawdown=0.0,
            is_influential=False,
            analysis_note="无扰动数据，无法评估",
        )

    # 计算各指标的平均衰减
    sharpes = [p.sharpe for p in param_points]
    returns = [p.annual_return for p in param_points]
    drawdowns = [p.max_drawdown for p in param_points]

    avg_sharpe = statistics.mean(sharpes) if sharpes else 0.0
    avg_return = statistics.mean(returns) if returns else 0.0
    avg_drawdown = statistics.mean(drawdowns) if drawdowns else 0.0

    decay_sharpe = _calc_decay_ratio(optimal_point.sharpe, avg_sharpe)
    decay_return = _calc_decay_ratio(optimal_point.annual_return, avg_return)
    decay_drawdown = _calc_drawdown_worsening(optimal_point.max_drawdown, avg_drawdown)

    # 综合敏感性（各衰减比例的平均）
    sensitivity = (decay_sharpe + decay_return + decay_drawdown) / 3.0
    sensitivity = min(max(sensitivity, 0.0), 1.0)

    # 是否为关键参数：任一衰减超过阈值
    is_influential = any([
        decay_sharpe > config.decay_threshold_sharpe,
        decay_return > config.decay_threshold_return,
        decay_drawdown > config.decay_threshold_drawdown,
    ])

    # 生成分析说明
    notes: list[str] = []
    if decay_sharpe > config.decay_threshold_sharpe:
        notes.append(f"夏普衰减 {decay_sharpe:.1%}（超阈值 {config.decay_threshold_sharpe:.0%})")
    if decay_return > config.decay_threshold_return:
        notes.append(f"收益衰减 {decay_return:.1%}（超阈值 {config.decay_threshold_return:.0%})")
    if decay_drawdown > config.decay_threshold_drawdown:
        notes.append(f"回撤恶化 {decay_drawdown:.1%}（超阈值 {config.decay_threshold_drawdown:.0%})")
    if not notes:
        notes.append(f"各指标衰减均在阈值内（S={decay_sharpe:.1%}, R={decay_return:.1%}, D={decay_drawdown:.1%})")

    analysis_note = "; ".join(notes)

    return SensitivityScore(
        param_name=param_name,
        sensitivity=round(sensitivity, 4),
        decay_sharpe=round(decay_sharpe, 4),
        decay_return=round(decay_return, 4),
        decay_drawdown=round(decay_drawdown, 4),
        is_influential=is_influential,
        analysis_note=analysis_note,
    )


def _detect_plateau(
    sensitivity_scores: dict[str, SensitivityScore],
    narrow_points: list[ParamPoint],
    optimal_point: ParamPoint,
    config: RobustnessConfig,
) -> bool:
    """检测最优参数附近是否存在稳定平台

    检查 ±5% 邻域内（窄扰动）的夏普波动是否 < 阈值。
    若存在平台 → 参数鲁棒性加分。

    Parameters
    ----------
    sensitivity_scores : dict
        各参数敏感性评分
    narrow_points : list[ParamPoint]
        ±5% 窄扰动范围内的参数点
    optimal_point : ParamPoint
        最优参数点
    config : RobustnessConfig

    Returns
    -------
    bool
        是否存在稳定平台
    """
    if not narrow_points:
        return False

    # 检查窄邻域内的夏普波动
    sharpes = [p.sharpe for p in narrow_points] + [optimal_point.sharpe]
    if len(sharpes) < 3:
        return False

    try:
        sharpe_std = statistics.stdev(sharpes)
    except statistics.StatisticsError:
        return False

    avg_sharpe = abs(statistics.mean(sharpes))
    if avg_sharpe < 1e-12:
        # 夏普接近零，无法用相对值衡量
        return sharpe_std < 0.05

    cv = sharpe_std / avg_sharpe  # 变异系数
    return cv < config.plateau_threshold_sharpe


def validate_robustness(
    optimal_param_point: ParamPoint,
    perturbed_param_points: list[ParamPoint],
    param_ranges: Optional[dict[str, Any]] = None,
    *,
    config: Optional[RobustnessConfig] = None,
) -> RobustnessResult:
    """对参数点列表执行参数稳定性验证

    核心逻辑：
      1. 将扰动参数点按参数名称分组
      2. 计算各参数的敏感性评分
      3. 检测最优参数附近是否存在稳定平台
      4. 综合判定参数是否鲁棒

    Parameters
    ----------
    optimal_param_point : ParamPoint
        全局最优参数点
    perturbed_param_points : list[ParamPoint]
        所有扰动参数点的绩效数据
    param_ranges : dict[str, Any] | None
        参数范围描述（可选），如
        {"n_levels": [5, 10, 15, 20], "grid_type": ["arithmetic", "geometric"]}
    config : RobustnessConfig | None
        验证器配置

    Returns
    -------
    RobustnessResult
    """
    if config is None:
        config = RobustnessConfig()

    if not perturbed_param_points:
        return RobustnessResult(
            is_robust=False,
            confidence=0.0,
            sensitivity_scores={},
            plateau=False,
            dominant_sensitive_param=None,
            decay_summary="无扰动参数点数据",
            fail_reason="无扰动参数点数据，无法评估参数稳定性",
            details={"n_perturbed_points": 0, "n_parameters": 0},
        )

    # 按参数名称分组扰动点
    # 使用 param_ranges 中的参数名作为分组依据（若提供）
    # 若未提供，尝试从 config_key 中提取
    if param_ranges:
        param_names = list(param_ranges.keys())
    else:
        # 从第一个扰动点的 params 字典推断参数名
        param_names = list(perturbed_param_points[0].params.keys()) if perturbed_param_points else []

    # 分组：查找每个扰动点的 dominant 参数变化
    # 策略：当某个参数值相对于最优参数变化时，将其归入该参数组
    grouped: dict[str, list[ParamPoint]] = {name: [] for name in param_names}

    for point in perturbed_param_points:
        # 对于每个扰动点，找到它与最优参数的不同之处
        changed_params = []
        for name in param_names:
            opt_val = optimal_param_point.params.get(name)
            cur_val = point.params.get(name)
            if opt_val is not None and cur_val is not None and opt_val != cur_val:
                changed_params.append(name)

        # 如果唯一变化参数可识别，归入该组
        if len(changed_params) == 1:
            grouped.setdefault(changed_params[0], []).append(point)
        elif len(changed_params) > 1:
            # 多参数同时变化，归入所有涉及参数组（各+0.5权重）
            for name in changed_params:
                grouped.setdefault(name, []).append(point)

    # 计算各参数敏感性
    sensitivity_scores: dict[str, SensitivityScore] = {}
    dominant_sensitive: Optional[str] = None
    max_sensitivity = 0.0

    for param_name in param_names:
        param_points = grouped.get(param_name, [])
        score = _compute_sensitivity(param_name, param_points, optimal_param_point, config)
        sensitivity_scores[param_name] = score

        if score.sensitivity > max_sensitivity and score.is_influential:
            max_sensitivity = score.sensitivity
            dominant_sensitive = param_name

    # 平台检测（窄扰动点列表）
    narrow_points = [p for p in perturbed_param_points if
                     _is_narrow_perturbation(p, optimal_param_point)]
    plateau = _detect_plateau(sensitivity_scores, narrow_points, optimal_param_point, config)

    # 综合鲁棒性判定
    influential_count = sum(1 for s in sensitivity_scores.values() if s.is_influential)
    total_params = len(sensitivity_scores)

    # 通过条件：
    #   (a) 关键参数个数 ≤ 1（最多一个参数较为敏感）
    #   (b) 存在稳定平台（加分项，非强制）
    #   (c) 最敏感参数的敏感性 < 0.8（低于极端尖峰阈值）
    is_robust = influential_count <= 1 and max_sensitivity < 0.8
    if total_params == 0:
        is_robust = False

    # 置信度计算
    # 基础：未超阈值的参数比例
    robust_param_ratio = (total_params - influential_count) / total_params if total_params > 0 else 0.0

    # 平台加分
    plateau_bonus = 0.15 if plateau else 0.0

    # 样本量修正：扰动点越多越可信
    n_sample = len(perturbed_param_points)
    sample_factor = min(n_sample / 20.0, 1.0)

    confidence = (
        robust_param_ratio * _CONFIDENCE_SENSITIVITY_WEIGHT
        + plateau_bonus * _CONFIDENCE_PLATEAU_WEIGHT
        + sample_factor * _CONFIDENCE_SAMPLE_WEIGHT
    )
    confidence = min(max(confidence, 0.0), 1.0)

    # 衰减摘要
    decay_parts: list[str] = []
    for name, score in sensitivity_scores.items():
        decay_parts.append(f"{name}: S={score.sensitivity:.2f}")
    decay_summary = f"各参数敏感性: {' | '.join(decay_parts)}"
    if plateau:
        decay_summary += " [存在稳定平台]"

    # 失败原因
    fail_reason: Optional[str] = None
    if not is_robust:
        if total_params == 0:
            fail_reason = "无参数信息，无法评估鲁棒性"
        else:
            sensitive_list = [
                name for name, s in sensitivity_scores.items() if s.is_influential
            ]
            fail_reason = (
                f"参数稳定性不足：{influential_count}/{total_params} 个参数超出衰减阈值"
                f"（{', '.join(sensitive_list)}）；"
                f"最高敏感性 {max_sensitivity:.2f}"
            )
            if max_sensitivity >= 0.8:
                fail_reason += "（PARAMETER_PEAK 风险）"

    details = {
        "n_perturbed_points": n_sample,
        "n_parameters": total_params,
        "n_influential_parameters": influential_count,
        "dominant_sensitive_param": dominant_sensitive,
        "max_sensitivity": round(max_sensitivity, 4),
        "plateau": plateau,
        "optimal_point": {
            "config_key": optimal_param_point.config_key,
            "sharpe": optimal_param_point.sharpe,
            "annual_return": optimal_param_point.annual_return,
            "max_drawdown": optimal_param_point.max_drawdown,
            "n_trades": optimal_param_point.n_trades,
        },
        "narrow_perturbation_count": len(narrow_points),
    }

    return RobustnessResult(
        is_robust=is_robust,
        confidence=round(confidence, 4),
        sensitivity_scores=sensitivity_scores,
        plateau=plateau,
        dominant_sensitive_param=dominant_sensitive,
        decay_summary=decay_summary,
        fail_reason=fail_reason,
        details=details,
    )


def _is_narrow_perturbation(point: ParamPoint, optimal: ParamPoint) -> bool:
    """判断是否为窄扰动（单一参数微调 ≤ ±5% 偏差）"""
    narrow_params = {"n_levels", "cool_down_bars", "stop_loss_pct", "vote_threshold"}
    for key in narrow_params:
        opt_val = optimal.params.get(key)
        cur_val = point.params.get(key)
        if opt_val is not None and cur_val is not None and opt_val != cur_val:
            # 检查数值偏差是否 ≤ ±5%
            if abs(opt_val) > 1e-12:
                deviation = abs(cur_val - opt_val) / abs(opt_val)
                if deviation > 0.05:
                    return False
            else:
                # 零值比较
                if abs(cur_val) > 1e-12:
                    return False
        # categorical 参数的变化不影响
    return True


# ============================================================
# 从参数扫描历史数据构建验证
# ============================================================

def validate_from_scan_records(
    all_param_points: list[ParamPoint],
    optimal_key: str,
    param_ranges: dict[str, Any],
    *,
    config: Optional[RobustnessConfig] = None,
) -> RobustnessResult:
    """从参数扫描历史数据构建验证

    适用于已有完整参数扫描数据（如 P3 热力图输出）的场景。
    自动筛选最优点和扰动点。

    Parameters
    ----------
    all_param_points : list[ParamPoint]
        所有参数点的绩效数据
    optimal_key : str
        最优参数点的 config_key
    param_ranges : dict[str, Any]
        参数范围描述
    config : RobustnessConfig | None
        验证器配置

    Returns
    -------
    RobustnessResult
    """
    # 查找最优参数点
    optimal_point = None
    for p in all_param_points:
        if p.config_key == optimal_key:
            optimal_point = p
            break

    if optimal_point is None:
        # 如果找不到精确匹配，按 Sharpe 排序取最高
        sorted_points = sorted(all_param_points, key=lambda x: x.sharpe, reverse=True)
        if sorted_points:
            optimal_point = sorted_points[0]
        else:
            return RobustnessResult(
                is_robust=False,
                confidence=0.0,
                sensitivity_scores={},
                plateau=False,
                dominant_sensitive_param=None,
                decay_summary="无可用参数扫描数据",
                fail_reason="无可用参数点",
                details={"n_points": 0},
            )

    # 过滤扰动点（排除最优本身）
    perturbed = [p for p in all_param_points if p.config_key != optimal_point.config_key]

    return validate_robustness(
        optimal_param_point=optimal_point,
        perturbed_param_points=perturbed,
        param_ranges=param_ranges,
        config=config,
    )


# ============================================================
# TradeRecord 迁移适配（使用 pnl_pct 列评估稳定性）
# ============================================================

def validate_robustness_from_trades(
    trades_by_param: dict[str, list[TradeRecord]],
    optimal_config_key: str,
    param_ranges: dict[str, Any],
    *,
    config: Optional[RobustnessConfig] = None,
) -> RobustnessResult:
    """从按参数分组的 TradeRecord 列表验证参数稳定性

    当有逐笔交易的按参数分组数据时使用。

    Parameters
    ----------
    trades_by_param : dict[str, list[TradeRecord]]
        key = config_key, value = 该参数配置下的交易记录列表
    optimal_config_key : str
        最优参数配置的 key
    param_ranges : dict[str, Any]
        参数范围描述
    config : RobustnessConfig | None
        验证器配置

    Returns
    -------
    RobustnessResult
    """
    # 从 TradeRecord 构建 ParamPoint
    param_points: list[ParamPoint] = []

    for config_key, trades in trades_by_param.items():
        if not trades:
            continue

        pnls = [t.pnl_pct for t in trades]
        n_trades = len(pnls)

        # 计算绩效指标
        # 注：这里只能从 TradeRecord 的 pnl_pct 估算可用指标
        # 更精确的 Sharpe 需要回测引擎输出，此处使用简化估计
        if n_trades >= 2:
            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            daily_sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0
            sharpe = daily_sharpe * math.sqrt(252)  # 年化夏普（简化估算）
        else:
            sharpe = sum(pnls) if n_trades == 1 else 0.0

        annual_return = sum(pnls) * (252 / max(n_trades, 1))

        # 回撤无法从 TradeRecord 直接计算，用平均负收益估算
        negative_pnls = [p for p in pnls if p < 0]
        max_drawdown = abs(sum(negative_pnls)) / max(n_trades, 1) if negative_pnls else 0.0

        # 从 config_key 提取参数（简化解析）
        params = _parse_config_key_simple(config_key)

        param_points.append(ParamPoint(
            config_key=config_key,
            params=params,
            sharpe=round(sharpe, 4),
            annual_return=round(annual_return, 4),
            max_drawdown=round(max_drawdown, 4),
            n_trades=n_trades,
        ))

    if not param_points:
        return RobustnessResult(
            is_robust=False,
            confidence=0.0,
            sensitivity_scores={},
            plateau=False,
            dominant_sensitive_param=None,
            decay_summary="无可用交易分组数据",
            fail_reason="所有参数分组的交易记录均为空",
            details={"n_groups": 0},
        )

    return validate_from_scan_records(
        all_param_points=param_points,
        optimal_key=optimal_config_key,
        param_ranges=param_ranges,
        config=config,
    )


def _parse_config_key_simple(config_key: str) -> dict[str, Any]:
    """简化版 config_key 解析（从 P3/P4 格式提取参数）"""
    params: dict[str, Any] = {}
    if not config_key:
        return params

    parts = config_key.split("_")
    # 格式: {grid_type}_n{n_levels}_cd{cool_down}_{position_mode}_{stop_loss}_vt{vote}
    # 例: arit_n5_cd1_fixed_nosl_vt0.5

    if parts:
        params["grid_type"] = parts[0]

    for part in parts:
        if part.startswith("n") and part[1:].isdigit():
            params["n_levels"] = int(part[1:])
        elif part.startswith("cd") and part[2:].isdigit():
            params["cool_down_bars"] = int(part[2:])
        elif part in ("fixed", "layer", "batcher"):
            params["position_mode"] = part
        elif part == "nosl":
            params["stop_loss_pct"] = 0.0
        elif part.startswith("sl") and "pct" in part:
            try:
                pct_val = int(part.replace("sl", "").replace("pct", ""))
                params["stop_loss_pct"] = pct_val / 100.0
            except ValueError:
                pass
        elif part.startswith("vt"):
            try:
                params["vote_threshold"] = float(part[2:])
            except ValueError:
                pass

    return params


# ============================================================
# 快速 PASS/FAIL 判定
# ============================================================

def is_robust(
    optimal_param_point: ParamPoint,
    perturbed_param_points: list[ParamPoint],
    *,
    config: Optional[RobustnessConfig] = None,
) -> bool:
    """快速判定参数稳定性是否通过

    Parameters
    ----------
    optimal_param_point : ParamPoint
        最优参数点
    perturbed_param_points : list[ParamPoint]
        扰动参数点
    config : RobustnessConfig | None
        验证器配置

    Returns
    -------
    bool
    """
    return validate_robustness(
        optimal_param_point, perturbed_param_points, config=config
    ).is_robust


def format_robustness_summary(result: RobustnessResult) -> str:
    """格式化鲁棒性验证结果"""
    lines: list[str] = [
        "=" * 56,
        "  参数稳定性验证报告 (Q2 Robustness Validator)",
        "=" * 56,
        f"  鲁棒性判定:    {'✅ 通过' if result.is_robust else '🔴 不通过'}",
        f"  置信度:        {result.confidence:.1%}",
        f"  稳定平台:      {'✅ 存在' if result.plateau else '⚠️ 不明显'}",
        f"  最敏感参数:    {result.dominant_sensitive_param or '无'}",
        f"  失败原因:      {result.fail_reason or '无'}",
        "=" * 56,
        "  各参数敏感性:",
        f"  {'参数':<15} | {'敏感性':>8} | {'夏普衰减':>8} | {'收益衰减':>8} | {'关键参数':>8}",
        "  " + "-" * 52,
    ]
    for name, score in result.sensitivity_scores.items():
        lines.append(
            f"  {name:<15} | {score.sensitivity:>8.2f} | {score.decay_sharpe:>7.1%} | "
            f"{score.decay_return:>7.1%} | {'⚠️' if score.is_influential else '✅':>8}"
        )
    lines.extend([
        "=" * 56,
        f"  最优参数:      {result.details.get('optimal_point', {}).get('config_key', 'N/A')}",
        f"  最优夏普:      {result.details.get('optimal_point', {}).get('sharpe', 0):.2f}",
        f"  扰动点数量:    {result.details.get('n_perturbed_points', 0)}",
        "=" * 56,
    ])
    return "\n".join(lines)
