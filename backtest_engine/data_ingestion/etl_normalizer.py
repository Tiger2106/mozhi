# -*- coding: utf-8 -*-
"""
ETL 写入层归一化 —— ETL Normalizer

基于 docs/data_ingestion_standard.md §2 实现。
处理流程：
  Tushare 原始数据
    → 字段映射（Tushare 字段名 → DB 字段名）
    → 归一化转换（vol: 手→股, amount: 千元→元, date: 校验）
    → 版本标记 + 来源标记
    → 写入 stock_daily 表（同时写入 stock_daily_raw 原始副本）

作者: 墨衡 (moheng)
创建时间: 2026-05-22T16:52+08:00
版本: v1.0
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .data_contract import (
    CURRENT_VERSION,
    DB_FIELD_NAMES,
    FIELD_BY_DB,
    FIELD_BY_TUSHARE,
    TUSHARE_FIELD_NAMES,
    generate_ddl,
    generate_raw_ddl,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 1. 归一化常量
# ──────────────────────────────────────────────

VOLUME_FACTOR: int = 100       # 手 → 股
AMOUNT_FACTOR: int = 1000      # 千元 → 元


# ──────────────────────────────────────────────
# 2. 核心归一化函数
# ──────────────────────────────────────────────

def normalize_volume(vol: Any) -> Optional[int]:
    """
    成交量归一化：手 → 股

    - Tushare 原始字段 vol 为"手"单位
    - 统一 ×100 转为"股"
    - 非数值或 NaN 返回 None
    """
    if pd.isna(vol):
        return None
    try:
        v = int(float(vol))
        return v * VOLUME_FACTOR
    except (ValueError, TypeError):
        logger.warning(f"无法转换 volume 值: {vol!r}")
        return None


def normalize_amount(amount: Any) -> Optional[float]:
    """
    成交额归一化：千元 → 元

    - Tushare 原始字段 amount 为"千元"单位
    - 统一 ×1000 转为"元"
    - 非数值或 NaN 返回 None
    """
    if pd.isna(amount):
        return None
    try:
        a = float(amount)
        return round(a * AMOUNT_FACTOR, 2)
    except (ValueError, TypeError):
        logger.warning(f"无法转换 amount 值: {amount!r}")
        return None


def normalize_trade_date(trade_date: Any) -> Optional[int]:
    """
    日期格式校验与转换

    - 确保输出为 8 位整数 YYYYMMDD
    - 支持 int / str / datetime 输入
    - 格式校验完毕后返回 INT 或 None
    """
    if pd.isna(trade_date):
        return None
    try:
        if isinstance(trade_date, (int, float)):
            d = int(trade_date)
            if 19000101 <= d <= 20991231:
                return d
            return None
        if isinstance(trade_date, str):
            # 支持 "YYMMDD"（无分隔符） 和 "YYYY-MM-DD" 两种格式
            cleaned = trade_date.replace("-", "").replace("/", "").replace(" ", "")
            if len(cleaned) == 8 and cleaned.isdigit():
                return int(cleaned)
            return None
        if isinstance(trade_date, datetime):
            return int(trade_date.strftime("%Y%m%d"))
        return None
    except (ValueError, TypeError) as e:
        logger.warning(f"无法转换 trade_date 值: {trade_date!r}, error: {e}")
        return None


# ──────────────────────────────────────────────
# 3. DataFrame 级归一化
# ──────────────────────────────────────────────

def normalize_dataframe(
    df: pd.DataFrame,
    version: str = CURRENT_VERSION,
    data_source: str = "tushare_pro",
    raw_mode: bool = False,
) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    """
    对 Tushare 原始 DataFrame 执行全量归一化。

    参数
    ----
    df : pd.DataFrame
        从 Tushare Pro daily 接口拉取的原始数据。
        列名应为 Tushare 原始字段名（ts_code, trade_date, open, ..., vol, amount, ...）。
    version : str
        当前清洗版本号（如 v1.0）。
    data_source : str
        数据来源标记。
    raw_mode : bool
        是否同时生成原始数据副本 DataFrame（stock_daily_raw 格式）。
        为 True 时返回 (normalized_df, raw_df)，否则返回 (normalized_df, None)。

    返回
    ----
    Tuple[norm_df, raw_df_or_None]
        norm_df: 已归一化的 stock_daily 格式 DataFrame
        raw_df:  原始副本 stock_daily_raw 格式 DataFrame（raw_mode=True 时）
    """
    if df is None or df.empty:
        logger.warning("输入 DataFrame 为空，跳过归一化")
        return pd.DataFrame(), None

    # 备份原始数据（如果需要）
    raw_df = None
    if raw_mode:
        raw_df = df.copy()
        raw_df["batch_id"] = _generate_batch_id()
        raw_df["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Step 1: 字段映射与类型转换 ──
    norm_data: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        record: Dict[str, Any] = {}

        # 映射 Tushare 字段 → DB 字段
        for tushare_field, meta in FIELD_BY_TUSHARE.items():
            raw_val = row.get(tushare_field)
            db_field = meta.db_name

            # 对特殊字段进行归一化转换
            if tushare_field == "vol":
                record[db_field] = normalize_volume(raw_val)
            elif tushare_field == "amount":
                record[db_field] = normalize_amount(raw_val)
            elif tushare_field == "trade_date":
                record[db_field] = normalize_trade_date(raw_val)
            else:
                # 直接映射（处理 NaN → None）
                record[db_field] = None if pd.isna(raw_val) else raw_val

        # ── Step 2: 补充系统字段 ──
        record["data_source"] = data_source
        record["version"] = version
        record["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        norm_data.append(record)

    norm_df = pd.DataFrame(norm_data, columns=DB_FIELD_NAMES)

    # ── Step 3: 类型安全 ──
    _coerce_types(norm_df)

    logger.info(
        f"归一化完成: {len(norm_df)} 行, "
        f"ts_code 范围: {norm_df['ts_code'].nunique()} 个标的, "
        f"trade_date 范围: {norm_df['trade_date'].min()} ~ {norm_df['trade_date'].max()}"
    )

    return norm_df, raw_df


def _generate_batch_id() -> str:
    """生成批次 ID（格式：YYYYMMDD_HHMMSS_XXXX）"""
    now = datetime.now()
    return f"{now.strftime('%Y%m%d_%H%M%S')}_{id(now) % 10000:04d}"


_DECIMAL_FIELDS = {
    "open", "high", "low", "close", "pre_close", "change",
    "amount", "total_mv", "circ_mv",
}
_DECIMAL_PCT_FIELDS = {"pct_chg", "turnover_rate", "turnover_rate_f", "volume_ratio"}
_DECIMAL_VAL_FIELDS = {"pe", "pe_ttm", "pb"}
_DECIMAL_SHARE_FIELDS = {"total_share", "float_share", "free_float_share"}


def _coerce_types(df: pd.DataFrame) -> None:
    """强制列类型，确保写入一致性"""
    for col in _DECIMAL_FIELDS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    for col in _DECIMAL_PCT_FIELDS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
    for col in _DECIMAL_VAL_FIELDS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
    for col in _DECIMAL_SHARE_FIELDS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(2)

    # volume 为整数类型
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

    # trade_date 为整数
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_numeric(df["trade_date"], errors="coerce").fillna(0).astype("int32")


# ──────────────────────────────────────────────
# 4. 质量校验（QC Checker）
# ──────────────────────────────────────────────

# QC-004 默认容忍度（可配置，墨萱审查要求改为可配置参数）
DEFAULT_QC004_TOLERANCE: float = 0.02  # 2%


def run_quality_checks(
    df: pd.DataFrame,
    qc004_tolerance: float = DEFAULT_QC004_TOLERANCE,
) -> Dict[str, Any]:
    """
    运行 §3 定义的质量校验。

    参数
    ----
    df : pd.DataFrame
        已归一化的 stock_daily 格式 DataFrame。
    qc004_tolerance : float
        QC-004 (volume × close ≈ amount) 容忍度，默认 2%。
        墨萱审查建议改为可配置参数，推荐 5% 用于交叉校验。

    返回
    ----
    Dict 包含每项校验结果。
    """
    if df.empty:
        return {"status": "SKIP", "reason": "empty dataframe"}

    results: Dict[str, Any] = {
        "total_rows": len(df),
        "checks": {},
        "passed": True,
        "warnings": [],
        "qc004_tolerance_used": qc004_tolerance,
    }

    # QC-001: volume > 0
    vol_positive = (df["volume"] > 0).sum()
    vol_zero = len(df) - vol_positive
    results["checks"]["QC-001"] = {
        "name": "volume > 0",
        "passed": vol_zero == 0,
        "failed_rows": int(vol_zero),
    }
    if vol_zero > 0:
        results["passed"] = False

    # QC-002: amount > 0
    amt_positive = (df["amount"] > 0).sum()
    amt_zero = len(df) - amt_positive
    results["checks"]["QC-002"] = {
        "name": "amount > 0",
        "passed": amt_zero == 0,
        "failed_rows": int(amt_zero),
    }
    if amt_zero > 0:
        results["passed"] = False

    # QC-003: close > 0
    close_positive = (df["close"] > 0).sum()
    close_zero = len(df) - close_positive
    results["checks"]["QC-003"] = {
        "name": "close > 0",
        "passed": close_zero == 0,
        "failed_rows": int(close_zero),
    }
    if close_zero > 0:
        results["passed"] = False

    # QC-004: volume × close ≈ amount
    mask_vol_close = df["volume"] > 0
    ratio = (df.loc[mask_vol_close, "volume"] * df.loc[mask_vol_close, "close"]).abs()
    denom = df.loc[mask_vol_close, "amount"].abs()
    # 防除零
    dev = (ratio - denom).abs() / denom.replace(0, float("inf"))
    dev_pass = dev < qc004_tolerance
    dev_fail = len(dev) - int(dev_pass.sum())
    results["checks"]["QC-004"] = {
        "name": f"volume × close ≈ amount (tolerance={qc004_tolerance:.1%})",
        "passed": dev_fail <= int(len(df) * 0.01),  # 允许 ≤1% 行失败
        "failed_rows": dev_fail,
    }
    if dev_fail > int(len(df) * 0.01):
        results["passed"] = False

    # QC-005: turnover_rate ∈ [0, 100]（允许 NULL）
    if "turnover_rate" in df.columns:
        tr_non_null = df["turnover_rate"].notna()
        tr_valid = (df.loc[tr_non_null, "turnover_rate"] >= 0) & \
                   (df.loc[tr_non_null, "turnover_rate"] <= 100)
        tr_fail = int(tr_non_null.sum() - tr_valid.sum())
        results["checks"]["QC-005"] = {
            "name": "turnover_rate ∈ [0, 100] (NULL allowed)",
            "passed": tr_fail == 0,
            "failed_rows": tr_fail,
        }
        if tr_fail > 0:
            results["passed"] = False
    else:
        results["checks"]["QC-005"] = {"name": "turnover_rate ∈ [0, 100]", "skipped": True}

    # QC-006: trade_date 格式校验
    td_valid = (df["trade_date"] >= 19000101) & (df["trade_date"] <= 20991231)
    td_fail = int(len(df) - td_valid.sum())
    results["checks"]["QC-006"] = {
        "name": "trade_date 格式校验（YYYYMMDD INT）",
        "passed": td_fail == 0,
        "failed_rows": td_fail,
    }
    if td_fail > 0:
        results["passed"] = False

    # QC-007: high >= low
    hl_fail = int((df["high"] < df["low"]).sum())
    results["checks"]["QC-007"] = {
        "name": "high >= low",
        "passed": hl_fail == 0,
        "failed_rows": hl_fail,
    }
    if hl_fail > 0:
        results["passed"] = False

    # QC-008: close ∈ [low, high]（允许 ≤1% 行失败）
    close_in_range = (df["close"] >= df["low"]) & (df["close"] <= df["high"])
    ci_fail = int(len(df) - close_in_range.sum())
    results["checks"]["QC-008"] = {
        "name": "close ∈ [low, high]",
        "passed": ci_fail <= int(len(df) * 0.01),
        "failed_rows": ci_fail,
    }
    if ci_fail > int(len(df) * 0.01):
        results["passed"] = False

    # QC-009: data_source 和 version 均非空
    ds_fail = int(df["data_source"].isna().sum() + df["version"].isna().sum())
    results["checks"]["QC-009"] = {
        "name": "data_source 和 version 均非空",
        "passed": ds_fail == 0,
        "failed_rows": ds_fail,
    }
    if ds_fail > 0:
        results["passed"] = False

    # QC-010: (ts_code, trade_date) 无重复
    dup_count = int(df.duplicated(subset=["ts_code", "trade_date"]).sum())
    results["checks"]["QC-010"] = {
        "name": "(ts_code, trade_date) 无重复主键",
        "passed": dup_count == 0,
        "failed_rows": dup_count,
    }
    if dup_count > 0:
        results["passed"] = False

    # ── 汇总 ──
    hard_fail_count = sum(
        1 for c in results["checks"].values()
        if not c.get("passed", True) and not c.get("skipped", False)
    )
    if hard_fail_count > 0:
        results["status"] = "INVALID"
    else:
        results["status"] = "VALIDATED"

    return results


def format_quality_result(result: Dict[str, Any]) -> str:
    """将质量校验结果格式化为可读字符串"""
    lines = [
        f"质量校验结果: {result.get('status', 'UNKNOWN')}",
        f"  总行数: {result.get('total_rows', 0)}",
        f"  QC-004 容忍度: {result.get('qc004_tolerance_used', 0.02):.1%}",
    ]
    for check_id, check in result.get("checks", {}).items():
        if check.get("skipped"):
            lines.append(f"  {check_id}: SKIPPED - {check['name']}")
        elif check.get("passed"):
            lines.append(f"  {check_id}: ✅ PASS - {check['name']}")
        else:
            lines.append(f"  {check_id}: ❌ FAIL ({check.get('failed_rows', '?')} rows) - {check['name']}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 5. SQL INSERT 生成
# ──────────────────────────────────────────────

def build_insert_sql(table: str = "stock_daily") -> str:
    """生成 INSERT INTO 语句（适用于批处理写入）"""
    columns = ", ".join(f"`{c}`" for c in DB_FIELD_NAMES)
    placeholders = ", ".join(["?" for _ in DB_FIELD_NAMES])
    return f"INSERT OR REPLACE INTO `{table}` ({columns}) VALUES ({placeholders})"
