"""
三级数据质量门禁框架

等级划分：
  Level 1 — ETL级（采集时校验）
  Level 2 — 因子级（IC计算前校验）
  Level 3 — IC 级（IC计算后校验）

author: 墨衡
created_time: 2026-05-31T19:09:00+08:00
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# ──────────────────────────────────────────────
# 常数定义
# ──────────────────────────────────────────────
BASE_DIR = Path("C:/Users/17699/mozhi_platform")
DEFAULT_REPORT_DIR = BASE_DIR / "reports" / "dq"

TZ_OFFSET = timezone(timedelta(hours=8))  # +08:00


# ──────────────────────────────────────────────
# 输出数据结构
# ──────────────────────────────────────────────
@dataclass
class GateResult:
    level: int  # 1=ETL, 2=Factor, 3=IC
    passed: bool
    gates: Dict[str, bool]
    details: Dict[str, Any]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# ──────────────────────────────────────────────
# 三级门禁校验函数
# ──────────────────────────────────────────────

def _now_str() -> str:
    """返回 +08:00 时区的 ISO8601 时间戳字符串。"""
    return datetime.now(TZ_OFFSET).isoformat(timespec="seconds")


# ── Level 1: ETL级 ────────────────────────────

def run_level1(data: Dict[str, Any]) -> GateResult:
    """
    采集时校验（ETL 级）。

    期望 data 结构（示例）：
        {
            "ps_ttm": 15.2,           # 个股单次采集的市盈率
            "pcf_ttm": 8.5,           # 个股单次采集的市现率
            "null_count": 3,          # 本批采集空值数
            "total_count": 100,       # 本批采集总数
            "prev_ps_ttm": 14.8,      # 前一交易日 ps_ttm（相邻日校验用）
        }
    """
    passed = True
    gates: Dict[str, bool] = {}
    details: Dict[str, Any] = {}

    # Gate 1a: ps_ttm >= 0
    ps_ttm = data.get("ps_ttm")
    gate_1a = (ps_ttm is not None) and (ps_ttm >= 0)
    gates["l1_ps_ttm_nonneg"] = gate_1a
    details["ps_ttm"] = ps_ttm
    if not gate_1a:
        passed = False

    # Gate 1b: pcf_ttm >= 0
    pcf_ttm = data.get("pcf_ttm")
    gate_1b = (pcf_ttm is not None) and (pcf_ttm >= 0)
    gates["l1_pcf_ttm_nonneg"] = gate_1b
    details["pcf_ttm"] = pcf_ttm
    if not gate_1b:
        passed = False

    # Gate 1c: 单次采集非空率 >= 90%
    null_count = data.get("null_count", 0)
    total_count = data.get("total_count", 1)
    non_null_rate = (total_count - null_count) / max(total_count, 1)
    gate_1c = non_null_rate >= 0.90
    gates["l1_non_null_rate"] = gate_1c
    details["non_null_rate"] = round(non_null_rate, 4)
    details["null_count"] = null_count
    details["total_count"] = total_count
    if not gate_1c:
        passed = False

    # Gate 1d: 相邻日 ps_ttm 变化 <= 50%
    prev_ps_ttm = data.get("prev_ps_ttm")
    if ps_ttm is not None and prev_ps_ttm is not None and prev_ps_ttm != 0:
        change_ratio = abs(ps_ttm - prev_ps_ttm) / abs(prev_ps_ttm)
        gate_1d = change_ratio <= 0.50
        details["ps_ttm_change_ratio"] = round(change_ratio, 4)
    else:
        gate_1d = True  # 无前一交易日数据时跳过
        details["ps_ttm_change_ratio"] = None
    gates["l1_ps_ttm_change"] = gate_1d
    if not gate_1d:
        passed = False

    return GateResult(
        level=1,
        passed=passed,
        gates=gates,
        details=details,
        timestamp=_now_str(),
    )


# ── Level 2: 因子级 ───────────────────────────

def run_level2(data: Dict[str, Any]) -> GateResult:
    """
    IC 计算前校验（因子级）。

    期望 data 结构（示例）：
        {
            "ps_ttm_series": [15.2, 14.8, None, 16.1, ...],    # 截面内 ps_ttm 数组
            "pcf_ttm_series": [8.5, 7.9, None, 8.8, ...],       # 截面内 pcf_ttm 数组
        }
    """
    passed = True
    gates: Dict[str, bool] = {}
    details: Dict[str, Any] = {}

    ps_series: Optional[List[Optional[float]]] = data.get("ps_ttm_series")
    pcf_series: Optional[List[Optional[float]]] = data.get("pcf_ttm_series")

    # 合并两个序列检查非空占比
    all_vals: List[Optional[float]] = []
    if ps_series:
        all_vals.extend(ps_series)
    if pcf_series:
        all_vals.extend(pcf_series)

    total = len(all_vals)
    non_null = sum(1 for v in all_vals if v is not None)
    non_null_ratio = non_null / max(total, 1)

    gate_2a = non_null_ratio >= 0.80
    gates["l2_non_null_ratio"] = gate_2a
    details["non_null_ratio"] = round(non_null_ratio, 4)
    details["total"] = total
    details["non_null"] = non_null
    if not gate_2a:
        passed = False

    # Gate 2b: 剔除 ±3σ 后剩余样本 >= 30
    non_null_vals = [v for v in all_vals if v is not None]
    if len(non_null_vals) >= 3:
        arr = np.array(non_null_vals, dtype=float)
        mean = np.nanmean(arr)
        std = np.nanstd(arr, ddof=1)
        lower = mean - 3.0 * std
        upper = mean + 3.0 * std
        filtered = arr[(arr >= lower) & (arr <= upper)]
        remaining = int(len(filtered))
    else:
        remaining = len(non_null_vals)

    gate_2b = remaining >= 30
    gates["l2_remaining_after_3sigma"] = gate_2b
    details["remaining_after_3sigma"] = remaining
    if not gate_2b:
        passed = False

    # Gate 2c: 截面标准差 > 0（因子值存在差异，避免常量序列）
    if len(non_null_vals) >= 2:
        arr_2 = np.array(non_null_vals, dtype=float)
        std_val = float(np.nanstd(arr_2, ddof=1))
        gate_2c = std_val > 1e-8
        details["std_dev"] = round(std_val, 6)
    else:
        gate_2c = False
        details["std_dev"] = None
    gates["l2_std_dev_positive"] = gate_2c
    if not gate_2c:
        passed = False

    return GateResult(
        level=2,
        passed=passed,
        gates=gates,
        details=details,
        timestamp=_now_str(),
    )


# ── Level 3: IC 级 ────────────────────────────

def run_level3(data: Dict[str, Any]) -> GateResult:
    """
    IC 计算后校验（IC 级）。

    期望 data 结构（示例）：
        {
            "ic": 0.15,            # IC 值（Pearson/Spearman）
            "rank_ic": 0.12,       # Rank IC
            "p_value": 0.03,       # IC 显著性 p-value
        }
    """
    passed = True
    gates: Dict[str, bool] = {}
    details: Dict[str, Any] = {}

    ic = data.get("ic")
    rank_ic = data.get("rank_ic")
    p_value = data.get("p_value")

    # Gate 3a: IC 绝对值 <= 1.0
    if ic is not None:
        gate_3a = abs(ic) <= 1.0
        details["ic"] = ic
    else:
        gate_3a = False
        details["ic"] = None
    gates["l3_ic_abs"] = gate_3a
    if not gate_3a:
        passed = False

    # Gate 3b: rank_ic <= 1.0
    if rank_ic is not None:
        gate_3b = abs(rank_ic) <= 1.0
        details["rank_ic"] = rank_ic
    else:
        # 若 rank_ic 未提供，仍以通过处理（业务可选字段）
        gate_3b = True
        details["rank_ic"] = None
    gates["l3_rank_ic_abs"] = gate_3b
    if not gate_3b:
        passed = False

    # Gate 3c: p-value 非 NaN
    if p_value is not None:
        gate_3c = not (isinstance(p_value, float) and math.isnan(p_value))
        details["p_value"] = p_value
    else:
        gate_3c = False
        details["p_value"] = None
    gates["l3_p_value_not_nan"] = gate_3c
    if not gate_3c:
        passed = False

    return GateResult(
        level=3,
        passed=passed,
        gates=gates,
        details=details,
        timestamp=_now_str(),
    )


# ──────────────────────────────────────────────
# 统一入口
# ──────────────────────────────────────────────

def run_all_gates(
    level1_data: Dict[str, Any],
    level2_data: Dict[str, Any],
    level3_data: Optional[Dict[str, Any]] = None,
    task_id: str = "default",
    date: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> List[GateResult]:
    """
    依次执行 Level1、Level2 及可选的 Level3 门禁校验。

    Parameters
    ----------
    level1_data : Dict
        Level1（ETL级）输入数据。
    level2_data : Dict
        Level2（因子级）输入数据。
    level3_data : Dict, optional
        Level3（IC级）输入数据。若为 None 则跳过 Level3。
    task_id : str
        任务标识，用于输出文件名。
    date : str, optional
        日期字符串 YYYYMMDD。默认取当前日期。
    output_dir : Path, optional
        输出目录。默认: reports/dq/{date}/

    Returns
    -------
    List[GateResult]
        各层级校验结果列表。
    """
    if date is None:
        date = datetime.now(TZ_OFFSET).strftime("%Y%m%d")

    results: List[GateResult] = []

    # Level 1
    r1 = run_level1(level1_data)
    results.append(r1)

    # Level 2
    r2 = run_level2(level2_data)
    results.append(r2)

    # Level 3 (optional)
    if level3_data is not None:
        r3 = run_level3(level3_data)
        results.append(r3)

    # ── 写入输出文件 ──
    if output_dir is None:
        output_dir = DEFAULT_REPORT_DIR / date
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"valuation_gate_{task_id}.json"
    output_payload = {
        "status": "READY",
        "task_id": task_id,
        "date": date,
        "levels": [r.to_dict() for r in results],
        "overall_passed": all(r.passed for r in results),
        "completed_time": _now_str(),
    }
    with open(str(output_path), "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    return results


# ──────────────────────────────────────────────
# 简单入口（仅校验，不写文件）
# ──────────────────────────────────────────────

def validate(
    level1_data: Dict[str, Any],
    level2_data: Dict[str, Any],
    level3_data: Optional[Dict[str, Any]] = None,
) -> List[GateResult]:
    """不写文件仅返回校验结果。"""
    results = [run_level1(level1_data), run_level2(level2_data)]
    if level3_data is not None:
        results.append(run_level3(level3_data))
    return results


# ──────────────────────────────────────────────
# 自测 / 示例
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import random

    # Level 1 示例数据
    l1_data = {
        "ps_ttm": 15.2,
        "pcf_ttm": 8.5,
        "null_count": 3,
        "total_count": 100,
        "prev_ps_ttm": 14.8,
    }

    # Level 2 示例数据（模拟 100 只股票截面）
    n = 100
    l2_data = {
        "ps_ttm_series": [random.uniform(5, 30) if random.random() > 0.08 else None for _ in range(n)],
        "pcf_ttm_series": [random.uniform(2, 20) if random.random() > 0.08 else None for _ in range(n)],
    }

    # Level 3 示例数据
    l3_data = {
        "ic": 0.15,
        "rank_ic": 0.12,
        "p_value": 0.03,
    }

    # 完整运行（含文件输出）
    results = run_all_gates(l1_data, l2_data, l3_data, task_id="self_test")
    for r in results:
        tag = "[PASS]" if r.passed else "[FAIL]"
        print(f"[Level {r.level}] {tag}  passed={r.passed}  gates={r.gates}")
        print(f"    details: {r.details}")
