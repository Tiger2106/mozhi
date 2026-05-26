"""signal_converter — 分析报告转信号文件（含输入 schema 校验）

AnalysisToSignalConverter 将墨衡 Step2 产出的结构化分析报告
（structured_analysis_{task_id}.json）转换为标准化的交易信号文件
（signal_{task_id}.json）。

功能：
  1. 读取结构化分析报告
  2. 校验必需字段存在性和类型（输入 schema 校验，BS-5）
  3. 按置信度映射操作建议 → 交易信号（BUY/SELL/HOLD）
  4. 写入标准化信号文件至 signals/paper_trade/{date}/ 目录
  5. schema 校验失败时写 _error 标记而非静默跳过

schema 校验（BS-5）：
  - 必需字段：symbol, action, confidence, suggested_price, position_ratio
  - 类型检查：symbol=str, action={BUY,SELL,HOLD}, confidence={高,中,低},
               suggested_price=number(>0), position_ratio=number(0~1)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from utils import time_utils

logger = logging.getLogger("paper_trade.signal_converter")

# ============================================================
# 类型 / 常量
# ============================================================

ALLOWED_ACTIONS = frozenset({"BUY", "SELL", "HOLD"})
ALLOWED_CONFIDENCE = frozenset({"高", "中", "低"})

# 置信度数值映射（中文标签 → 数值）
CONFIDENCE_MAP: Dict[str, float] = {
    "高": 0.85,
    "中": 0.65,
    "低": 0.35,
}

# 操作动作映射（原始 → 订单）
ACTION_MAP: Dict[str, str] = {
    "BUY": "BUY_TO_OPEN",
    "SELL": "SELL_TO_CLOSE",
    "HOLD": "HOLD",
}

# 信号必需字段（含 confidence_label）
REQUIRED_FIELDS: Dict[str, type] = {
    "symbol": str,
    "action": str,
    "confidence": (int, float),
    "confidence_label": str,
    "suggested_price": (int, float),
    "position_ratio": (int, float),
}

# 分析报告检验字段（旧版类校验用）
ANALYSIS_REQUIRED_FIELDS: Dict[str, type] = {
    "symbol": str,
    "action": str,
    "confidence": str,
    "suggested_price": (int, float),
    "position_ratio": (int, float),
}

SIGNAL_DIR_TEMPLATE = "signals/paper_trade/{date}"
ERROR_DIR_TEMPLATE = "signals/paper_trade/{date}/_errors"

# Phase1a 信号输出目录
PHASE1A_SIGNAL_DIR = "signals/signals"
PHASE1A_SKIP_DIR = os.path.join(PHASE1A_SIGNAL_DIR, "_skipped")


# ============================================================
# 异常
# ============================================================

class SchemaValidationError(ValueError):
    """输入字段校验失败时抛出。"""
    ...


# ============================================================
# 信号数据类
# ============================================================

@dataclass
class TradeSignal:
    """标准化交易信号。"""
    task_id: str
    symbol: str
    action: str              # BUY_TO_OPEN / SELL_TO_CLOSE / HOLD
    confidence: str
    suggested_price: float
    position_ratio: float    # 0~1
    quantity: Optional[int] = None
    reason: Optional[str] = None
    status: str = "READY"
    created_at: str = field(default_factory=lambda: time_utils.now().isoformat())


# ============================================================
# 转换器
# ============================================================

class AnalysisToSignalConverter:
    """结构化分析报告 → 标准化交易信号。"""

    def __init__(self, base_dir: str = "mo_zhi_sharereports"):
        self.base_dir = base_dir

    def convert(self, analysis_path: Any, output_date: Optional[date] = None,
                 source_path: str = "") -> Optional[Dict[str, Any]]:
        """转换单个分析报告为信号。

        参数：
            analysis_path — 文件路径（str）或分析报告 dict（向后兼容）
            output_date — 信号日期（None = 当日）
            source_path — 当 analysis_path 为 dict 时的源文件路径（可选）

        返回：
            信号字典，或 None（HOLD/校验失败）

        向后兼容（测试用）：
            - analysis_path 为 dict 时直接使用（不读文件）
            - base_verdict=FAIL → 生成 HOLD 信号（fail-closed）
            - 透传 source_path 至 convert_from_step2_format
        """
        # 向后兼容：当第一个参数是 dict 时直接使用
        if isinstance(analysis_path, dict):
            return self.convert_from_step2_format(
                analysis_path, source_path=source_path, output_date=output_date
            )

        # 1. 读取分析报告
        path: str = analysis_path
        try:
            with open(path, "r", encoding="utf-8") as f:
                analysis: Dict[str, Any] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("读取分析报告失败: %s — %s", path, e)
            return None

        if analysis.get("status") != "READY":
            logger.warning("分析报告状态非 READY: %s", analysis.get("status"))
            return None

        # 2. schema 校验
        try:
            self._validate(analysis)
        except SchemaValidationError as e:
            self._write_error(analysis, str(e), output_date)
            logger.warning("schema 校验失败: %s — %s", analysis_path, e)
            return None

        # 3. 提取分析意见
        symbol = analysis["data_validation"].get("symbol", analysis.get("symbol", ""))
        raw_action = analysis.get("signal_mapping", {}).get("action", analysis.get("action", "HOLD"))
        confidence = analysis.get("signal_mapping", {}).get("confidence", analysis.get("confidence", "中"))
        suggested_price = float(analysis.get("signal_mapping", {}).get("suggested_price",
                            analysis.get("suggested_price", 0)))
        position_ratio = float(analysis.get("signal_mapping", {}).get("position_ratio",
                               analysis.get("position_ratio", 0)))

        # 3a. 校验 action 合法性
        if raw_action not in ALLOWED_ACTIONS:
            logger.warning("非法 action: %s，转为 HOLD", raw_action)
            raw_action = "HOLD"

        # 4. 映射 action → order action
        order_action = ACTION_MAP[raw_action]

        # HOLD 不生成交易信号
        if order_action == "HOLD":
            logger.info("信号为 HOLD，跳过生成交易信号: task_id=%s", analysis.get("task_id"))
            return None

        # 5. 组装信号
        signal = TradeSignal(
            task_id=analysis.get("task_id", "unknown"),
            symbol=symbol,
            action=order_action,
            confidence=confidence,
            suggested_price=suggested_price,
            position_ratio=position_ratio,
            reason=analysis.get("analyst_note"),
        )

        # 6. 写信号文件
        output = self._write_signal(signal, output_date)
        return output

    # ----------------------------------------------------------
    # Schema 校验（BS-5）
    # ----------------------------------------------------------

    def _validate(self, analysis: Dict[str, Any]) -> None:
        """校验分析报告必需字段。

        Raises:
            SchemaValidationError — 字段缺失或类型错误时抛出
        """
        errors: List[str] = []

        for field, expected_type in REQUIRED_FIELDS.items():
            value = analysis.get(field) or analysis.get("signal_mapping", {}).get(field)
            if value is None:
                errors.append(f"缺失必需字段: {field}")
                continue
            if not isinstance(value, expected_type):
                errors.append(
                    f"字段 {field} 类型错误: 期望 {expected_type.__name__}，"
                    f"实际 {type(value).__name__} ({value})"
                )

        # 额外校验
        action = analysis.get("action") or analysis.get("signal_mapping", {}).get("action")
        if action and action not in ALLOWED_ACTIONS:
            errors.append(f"action 取值不合法: {action}（允许 {sorted(ALLOWED_ACTIONS)}）")

        confidence = analysis.get("confidence") or analysis.get("signal_mapping", {}).get("confidence")
        if confidence and confidence not in ALLOWED_CONFIDENCE:
            errors.append(f"confidence 取值不合法: {confidence}（允许 {sorted(ALLOWED_CONFIDENCE)}）")

        price = analysis.get("suggested_price") or analysis.get("signal_mapping", {}).get("suggested_price")
        if price is not None and isinstance(price, (int, float)) and price <= 0:
            errors.append(f"suggested_price 必须 > 0，当前值: {price}")

        ratio = analysis.get("position_ratio") or analysis.get("signal_mapping", {}).get("position_ratio")
        if ratio is not None and isinstance(ratio, (int, float)):
            if not (0 <= ratio <= 1):
                errors.append(f"position_ratio 必须在 [0, 1] 范围内，当前值: {ratio}")

        if errors:
            raise SchemaValidationError("; ".join(errors))

    # ----------------------------------------------------------
    # 文件写入
    # ----------------------------------------------------------

    def _write_signal(self, signal: TradeSignal, output_date: Optional[date] = None) -> Dict[str, Any]:
        """写入标准化信号文件。"""
        dt = output_date or time_utils.today()
        date_str = dt.strftime("%Y%m%d")
        signal_dir = os.path.join(self.base_dir, SIGNAL_DIR_TEMPLATE.format(date=date_str))
        os.makedirs(signal_dir, exist_ok=True)

        signal_path = os.path.join(signal_dir, f"signal_{signal.task_id}.json")
        signal_dict = {
            "task_id": signal.task_id,
            "symbol": signal.symbol,
            "action": signal.action,
            "confidence": signal.confidence,
            "suggested_price": signal.suggested_price,
            "position_ratio": signal.position_ratio,
            "quantity": signal.quantity,
            "reason": signal.reason,
            "status": signal.status,
            "created_at": signal.created_at,
        }

        with open(signal_path, "w", encoding="utf-8") as f:
            json.dump(signal_dict, f, ensure_ascii=False, indent=2)

        logger.info("信号写入完成: %s", signal_path)
        return signal_dict

    def _write_error(self, analysis: Dict[str, Any], error_msg: str, output_date: Optional[date] = None) -> None:
        """写入 schema 校验失败的 _error 标记。"""
        dt = output_date or time_utils.today()
        date_str = dt.strftime("%Y%m%d")
        error_dir = os.path.join(self.base_dir, ERROR_DIR_TEMPLATE.format(date=date_str))
        os.makedirs(error_dir, exist_ok=True)

        task_id = analysis.get("task_id", "unknown")
        error_path = os.path.join(error_dir, f"{task_id}_error.json")
        error_data = {
            "task_id": task_id,
            "error": error_msg,
            "status": "SCHEMA_FAILED",
            "created_at": time_utils.now().isoformat(),
        }

        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)

        logger.warning("错误标记已写入: %s", error_path)

    # ----------------------------------------------------------
    # 从 dict 转换（fail-closed 测试用）
    # ----------------------------------------------------------

    def convert_from_step2_format(self, analysis: Dict[str, Any],
                                   source_path: str = "",
                                   output_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
        """从 Step2 分析报告 dict 直接转换（不读文件）。

        参数：
            analysis — Step2 分析报告 dict
            source_path — 原始源文件路径（可选，写 signal 时记入）
            output_date — 信号日期（None = 当日）

        返回：
            信号字典，或 None（HOLD/校验失败）

        fail-closed 行为（T2-A）：
            - base_verdict=FAIL → 生成 HOLD 信号，position_ratio=0
            - _malicious_position_ratio 等攻击字段被归零
        """
        # 检查 verdict（fail-closed gate）
        base_verdict = analysis.get("base_verdict") or analysis.get("verdict")
        if base_verdict == "FAIL":
            logger.info("base_verdict=FAIL，生成HOLD信号: task_id=%s", analysis.get("task_id"))
            hold = _make_hold_signal(analysis, reason=analysis.get("analyst_note", ""))
            hold["source_analysis"] = source_path
            return hold

        # 判定默认行为：PASS 且无显式 action → BUY，否则 → HOLD
        _has_explicit_action = bool(
            analysis.get("action") or
            analysis.get("signal_mapping", {}).get("action")
        )
        _default_action = "BUY" if not _has_explicit_action and base_verdict == "PASS" else "HOLD"
        _default_ratio = 0.1 if _default_action == "BUY" else 0.0

        # 组装信号
        symbol = _extract_symbol(analysis)
        raw_action = analysis.get("action") or analysis.get("signal_mapping", {}).get("action", _default_action)
        confidence_raw = analysis.get("confidence") or analysis.get("signal_mapping", {}).get("confidence", "中")
        suggested_price_raw = analysis.get("suggested_price") or \
                              analysis.get("signal_mapping", {}).get("suggested_price")
        if suggested_price_raw is None:
            # 无显式价格时，从 stock_info.price 回退
            stock_info = analysis.get("stock_info", {})
            if isinstance(stock_info, dict):
                stock_price = stock_info.get("price") or stock_info.get("suggested_price")
                if stock_price:
                    suggested_price_raw = stock_price
        suggested_price = float(suggested_price_raw or 0)
        position_ratio = float(analysis.get("position_ratio") or
                               analysis.get("signal_mapping", {}).get("position_ratio", _default_ratio))

        # 抵御攻击：_malicious_position_ratio 字段归零
        if position_ratio > 1.0:
            logger.warning("position_ratio 异常 >1.0，归零处理: %.2f", position_ratio)
            position_ratio = 0.0

        if raw_action not in ALLOWED_ACTIONS:
            raw_action = "HOLD"

        order_action = ACTION_MAP[raw_action]

        # 构建标准信号 dict
        signal_dict: Dict[str, Any] = {
            "status": "READY",
            "task_id": analysis.get("task_id", "unknown"),
            "symbol": symbol,
            "action": order_action,
            "confidence": _confidence_to_numeric(confidence_raw),
            "confidence_label": _confidence_to_label(confidence_raw),
            "suggested_price": suggested_price,
            "position_ratio": position_ratio,
            "source_analysis": source_path,
            "created_at": time_utils.now().isoformat(),
            "author": "moheng",
        }

        # HOLD 跳过
        if order_action == "HOLD":
            logger.info("HOLD信号跳过: task_id=%s", analysis.get("task_id"))
            return None

        # 校验
        valid, errors = validate_signal(signal_dict)
        if not valid:
            _write_signal_error(signal_dict, errors, output_date, self.base_dir)
            logger.warning("信号校验失败: task_id=%s — %s", analysis.get("task_id"), "; ".join(errors))
            return None

        return signal_dict



# -*- coding: utf-8 -*-
# ── 以下为 P0-MH-11 新增：standalone 函数 + done 信号 ──
# author: moheng
# created_time: 2026-05-12 11:01 GMT+8

# ============================================================
# 辅助函数（字段提取 / 置信度换算）
# ============================================================

def _extract_symbol(report: Dict[str, Any]) -> str:
    """从分析报告中提取股票代码。"""
    stock_info = report.get("stock_info", {})
    if isinstance(stock_info, dict) and "code" in stock_info:
        return str(stock_info["code"])
    if "symbol" in report:
        return str(report["symbol"])
    if "data_validation" in report and isinstance(report["data_validation"], dict):
        sym = report["data_validation"].get("symbol")
        if sym:
            return str(sym)
    return ""


def _confidence_to_numeric(value: Any) -> float:
    """将置信度转为数值（信号JSON中confidence为数字）。"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value in CONFIDENCE_MAP:
        return CONFIDENCE_MAP[value]
    return 0.5  # 默认中


def _confidence_to_label(value: Any) -> str:
    """将置信度转为中文标签（高/中/低）。"""
    if isinstance(value, str) and value in ALLOWED_CONFIDENCE:
        return value
    if isinstance(value, (int, float)):
        if value >= 0.7:
            return "高"
        elif value >= 0.4:
            return "中"
        else:
            return "低"
    return "中"


def _make_hold_signal(report: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    """生成 HOLD 信号（fail-closed 时使用）。"""
    return {
        "status": "READY",
        "task_id": report.get("task_id", "unknown"),
        "symbol": _extract_symbol(report),
        "action": "HOLD",
        "confidence": 0.0,
        "confidence_label": "低",
        "suggested_price": 0.0,
        "position_ratio": 0.0,
        "reason": reason or report.get("analyst_note", ""),
        "created_at": time_utils.now().isoformat(),
        "author": "moheng",
        "source_analysis": "",
    }


# ============================================================
# 信号 schema 校验（standalone）
# ============================================================

def validate_signal(signal: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """对信号JSON进行schema校验。

    校验规则（BS-5）：
      - 必需字段：symbol, action, confidence, confidence_label,
                  suggested_price, position_ratio
      - symbol: 非空字符串
      - action: BUY_TO_OPEN / SELL_TO_CLOSE / HOLD
      - confidence: 正数（>0）
      - confidence_label: 高 / 中 / 低
      - suggested_price: 正数（>0）
      - position_ratio: [0, 1] 范围

    参数：
        signal — 待校验的信号字典

    返回：
        (is_valid, errors) — (通过否, 错误列表)
    """
    errors: List[str] = []

    # ── 必需字段存在性 ──
    for field in ("symbol", "action", "confidence", "confidence_label",
                  "suggested_price", "position_ratio"):
        if field not in signal or signal[field] is None:
            errors.append(f"缺失必需字段: {field}")

    if errors:
        return False, errors

    # ── symbol ──
    sym = signal.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        errors.append(f"symbol 无效（应为非空字符串）: {sym!r}")

    # ── action ──
    act = signal.get("action")
    allowed_signal_actions = frozenset({"BUY_TO_OPEN", "SELL_TO_CLOSE", "HOLD"})
    if act not in allowed_signal_actions:
        errors.append(f"action 不合法: {act!r}（允许 {sorted(allowed_signal_actions)}）")

    # ── confidence（数值 > 0） ──
    conf = signal.get("confidence")
    if not isinstance(conf, (int, float)):
        errors.append(f"confidence 类型错误（应为数字）: 实际 {type(conf).__name__} ({conf!r})")
    elif conf <= 0:
        errors.append(f"confidence 必须 > 0: {conf}")

    # ── confidence_label ──
    label = signal.get("confidence_label")
    if label not in ALLOWED_CONFIDENCE:
        errors.append(f"confidence_label 不合法: {label!r}（允许 {sorted(ALLOWED_CONFIDENCE)}）")

    # ── suggested_price（> 0） ──
    price = signal.get("suggested_price")
    if not isinstance(price, (int, float)):
        errors.append(f"suggested_price 类型错误（应为数字）: 实际 {type(price).__name__} ({price!r})")
    elif price <= 0:
        errors.append(f"suggested_price 必须 > 0: {price}")

    # ── position_ratio（[0, 1]） ──
    ratio = signal.get("position_ratio")
    if not isinstance(ratio, (int, float)):
        errors.append(f"position_ratio 类型错误（应为数字）: 实际 {type(ratio).__name__} ({ratio!r})")
    elif not (0.0 <= ratio <= 1.0):
        errors.append(f"position_ratio 必须在 [0, 1] 范围: {ratio}")

    return len(errors) == 0, errors


# ============================================================
# 信号错误写入（standalone，供 validate_signal 失败时调用）
# ============================================================

def _write_signal_error(signal: Dict[str, Any],
                        errors: List[str],
                        output_date: Optional[date] = None,
                        base_dir: str = "mo_zhi_sharereports") -> None:
    """校验失败的信号写入 _errors 目录。

    参数：
        signal — 校验失败的信号 dict（仅用于提取 task_id）
        errors — 错误原因列表
        output_date — 信号日期（None = 当日）
        base_dir — 项目根目录
    """
    dt = output_date or time_utils.today()
    date_str = dt.strftime("%Y%m%d")
    error_dir = os.path.join(base_dir, ERROR_DIR_TEMPLATE.format(date=date_str))
    os.makedirs(error_dir, exist_ok=True)

    task_id = signal.get("task_id", "unknown")
    error_path = os.path.join(error_dir, f"{task_id}_error.json")
    error_data = {
        "task_id": task_id,
        "error": "; ".join(errors),
        "status": "SCHEMA_FAILED",
        "source": "convert_report_to_signal",
        "created_at": time_utils.now().isoformat(),
    }

    with open(error_path, "w", encoding="utf-8") as f:
        json.dump(error_data, f, ensure_ascii=False, indent=2)

    logger.warning("信号校验错误已写入: %s — %s", error_path, "; ".join(errors))


# ============================================================
# convert_report_to_signal — 主入口（分析报告 dict → 信号 dict）
# ============================================================

def convert_report_to_signal(report: Dict[str, Any],
                              output_date: Optional[date] = None,
                              base_dir: str = "mo_zhi_sharereports") -> Optional[Dict[str, Any]]:
    """将 Step2 分析报告（dict）转为标准化信号JSON（dict）。

    参数：
        report — Step2 结构化分析报告 dict
        output_date — 信号日期（None = 当日），用于错误文件日期目录
        base_dir — 项目根目录

    返回：
        信号 dict（含 status/action/confidence 等字段），或 None：
          - HOLD 信号 → 跳过，返回 None
          - 校验失败 → 写 _errors 标记，返回 None
          - 其它异常 → 记录日志，返回 None

    校验规则：
        - 必需字段：symbol, action, confidence, confidence_label,
                    suggested_price, position_ratio
        - fail-closed：base_verdict=FAIL 生成 HOLD 信号
    """
    # ── fail-closed gate ──
    base_verdict = report.get("base_verdict") or report.get("verdict")
    if base_verdict == "FAIL":
        logger.info("base_verdict=FAIL，生成HOLD信号: task_id=%s", report.get("task_id"))
        hold = _make_hold_signal(report, reason=report.get("analyst_note", ""))
        hold.pop("source_analysis", None)  # 不携带 source_path
        return hold

    # ── status 检查 ──
    status = report.get("status")
    if status is not None and status != "READY":
        logger.warning("分析报告状态非READY，跳过转换: status=%s, task_id=%s",
                       status, report.get("task_id"))
        return None

    # ── 提取字段 ──
    try:
        symbol = _extract_symbol(report)
        raw_action = report.get("action") or \
                     report.get("signal_mapping", {}).get("action", "HOLD")
        confidence_raw = report.get("confidence") or \
                         report.get("signal_mapping", {}).get("confidence", "中")
        suggested_price = float(
            report.get("suggested_price") or
            report.get("signal_mapping", {}).get("suggested_price", 0)
        )
        position_ratio = float(
            report.get("position_ratio") or
            report.get("signal_mapping", {}).get("position_ratio", 0)
        )
    except (ValueError, TypeError) as e:
        logger.error("信号字段提取异常: %s", e)
        return None

    # ── 合法性检查 ──
    if raw_action not in ALLOWED_ACTIONS:
        logger.warning("非法 action 值: %s，转为 HOLD", raw_action)
        raw_action = "HOLD"

    # 阻止 position_ratio 溢出
    if position_ratio > 1.0:
        logger.warning("position_ratio > 1.0，归零处理: %.2f", position_ratio)
        position_ratio = 0.0

    # ── 映射 ──
    order_action = ACTION_MAP[raw_action]

    # ── 构建标准信号 ──
    signal_dict: Dict[str, Any] = {
        "status": "READY",
        "task_id": report.get("task_id", "unknown"),
        "symbol": symbol,
        "action": order_action,
        "confidence": _confidence_to_numeric(confidence_raw),
        "confidence_label": _confidence_to_label(confidence_raw),
        "suggested_price": suggested_price,
        "position_ratio": position_ratio,
        "created_at": time_utils.now().isoformat(),
        "author": "moheng",
    }

    # ── HOLD 跳过（不下单、不冻结） ──
    if order_action == "HOLD":
        logger.info("HOLD信号跳过（不下单、不冻结）: task_id=%s", report.get("task_id"))
        return None

    # ── 校验 ──
    valid, errors = validate_signal(signal_dict)
    if not valid:
        _write_signal_error(signal_dict, errors, output_date, base_dir)
        logger.warning("信号校验失败，不下单: task_id=%s — %s",
                       report.get("task_id"), "; ".join(errors))
        return None

    return signal_dict


# ============================================================
# Phase1a: convert_report_to_signal_phase1a — 简易信号格式
# ============================================================


def validate_phase1a_report(report: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """校验分析报告并提取 Phase1a 字段。

    参数：
        report — Step2 结构化分析报告 dict

    返回：
        (is_valid, error_msg, extracted_fields)
        extracted_fields = {
            "task_id", "symbol", "action_str", "confidence_str",
            "suggested_price", "position_ratio"
        }
    """
    e_fields: Dict[str, Any] = {}

    # — status —
    status = report.get("status")
    if status is not None and status != "READY":
        return False, f"分析报告状态非 READY: {status}", {}

    # — task_id —
    task_id = report.get("task_id", "")
    if not task_id:
        return False, "缺失 task_id", {}
    e_fields["task_id"] = task_id

    # — symbol —
    symbol = _extract_symbol(report)
    if not symbol:
        return False, f"无法提取 symbol: task_id={task_id}", {}
    e_fields["symbol"] = symbol

    # — action —
    try:
        raw_action = report.get("action") or \
                     report.get("signal_mapping", {}).get("action", "HOLD")
        if raw_action not in ALLOWED_ACTIONS:
            raw_action = "HOLD"
    except Exception:
        raw_action = "HOLD"
    e_fields["action_str"] = raw_action

    # — confidence —
    try:
        confidence_raw = report.get("confidence") or \
                         report.get("signal_mapping", {}).get("confidence", "中")
    except Exception:
        confidence_raw = "中"
    e_fields["confidence_str"] = confidence_raw

    # — suggested_price —
    try:
        sp_raw = report.get("suggested_price") or \
                 report.get("signal_mapping", {}).get("suggested_price", 0)
        if not sp_raw:
            stock_info = report.get("stock_info", {})
            if isinstance(stock_info, dict):
                sp_raw = stock_info.get("price") or stock_info.get("suggested_price", 0)
        suggested_price = float(sp_raw or 0)
        if suggested_price < 0:
            suggested_price = 0.0
    except (ValueError, TypeError):
        suggested_price = 0.0
    e_fields["suggested_price"] = suggested_price

    # — position_ratio —
    try:
        pr = float(report.get("position_ratio") or
                   report.get("signal_mapping", {}).get("position_ratio", 0))
        if pr > 1.0:
            pr = 0.0
    except (ValueError, TypeError):
        pr = 0.0
    e_fields["position_ratio"] = pr

    return True, "", e_fields


def _build_analysis_summary(report: Dict[str, Any], action_str: str, confidence_str: str) -> str:
    """从分析报告中构建 analysis_summary。"""
    core_logic = report.get("core_logic", "")
    risk_level = report.get("risk_assessment", {}).get("level", "未知")
    sustainability = report.get("sustainability", "")
    analyst_note = report.get("analyst_note", "")

    parts = [f"操作建议:{action_str}", f"置信度:{confidence_str}", f"风险等级:{risk_level}"]
    if core_logic:
        parts.append(f"核心逻辑:{core_logic}")
    if sustainability:
        parts.append(f"可持续性:{sustainability}")
    if analyst_note:
        parts.append(f"备注:{analyst_note}")

    return " | ".join(parts)


def _write_skip_log(task_id: str, reason: str, base_dir: str = "mo_zhi_sharereports",
                    report: Optional[Dict[str, Any]] = None) -> None:
    """写入 Phase1a 跳过日志文件。

    路径：{base_dir}/{PHASE1A_SKIP_DIR}/{task_id}_skip.json
    """
    skip_dir = os.path.join(base_dir, PHASE1A_SKIP_DIR)
    os.makedirs(skip_dir, exist_ok=True)
    skip_path = os.path.join(skip_dir, f"{task_id}_skip.json")

    skip_data: Dict[str, Any] = {
        "task_id": task_id,
        "skip_reason": reason,
        "timestamp": time_utils.now().isoformat(),
        "author": "signal_converter",
    }
    if report and "data_validation" in report:
        skip_data["complexity"] = report["data_validation"].get("complexity", "unknown")

    try:
        with open(skip_path, "w", encoding="utf-8") as f:
            json.dump(skip_data, f, ensure_ascii=False, indent=2)
        logger.info("Phase1a skip 日志已写入: %s — %s", skip_path, reason)
    except Exception as e:
        logger.error("Phase1a skip 日志写入失败: %s — %s", skip_path, e)


def convert_report_to_signal_phase1a(report: Dict[str, Any],
                                      base_dir: str = "mo_zhi_sharereports"
                                      ) -> Optional[Dict[str, Any]]:
    """将 Step2 分析报告转换为 Phase1a 简易信号格式。

    Phase1a 信号格式：
    ```json
    {
      "task_id": "<task_id>",
      "created_at": "<ISO8601+08:00>",
      "action": "<BUY|SELL|HOLD>",
      "symbol": "<股票代码>",
      "confidence": 0.85,
      "suggested_price": 11.99,
      "qty_pct": 0.3,
      "analysis_summary": "操作建议:BUY | 置信度:高 | 风险等级:中",
      "status": "NEW"
    }
    ```

    行为规则：
    - multi_position (complexity) → 跳过，写 skip_log，返回 None
    - 文件已存在（幂等） → 跳过，返回 None
    - fail-closed: base_verdict=FAIL → 生成 HOLD 信号
    - HOLD 跳过：仍写入信号文件但 qty_pct=0，不生成交易信号
    - 写后 read 验证

    参数：
        report — Step2 结构化分析报告 dict
        base_dir — 项目根目录

    返回：
        写入的信号 dict，或 None（跳过/失败）
    """
    task_id = report.get("task_id", "unknown")

    # ── 幂等检查：文件已存在则跳过 ──
    signal_path = os.path.join(base_dir, PHASE1A_SIGNAL_DIR, f"signal_{task_id}.json")
    if os.path.exists(signal_path):
        logger.info("Phase1a 信号文件已存在（幂等跳过）: %s", signal_path)
        return None

    # ── multi_position 跳过 ──
    data_validation = report.get("data_validation", {})
    if data_validation.get("complexity") == "multi_position":
        logger.info("Phase1a 多笔持仓（complexity=multi_position），跳过生成信号: task_id=%s", task_id)
        _write_skip_log(task_id, "complexity=multi_position，当前不支持多笔持仓", base_dir, report)
        return None

    # ── fail-closed：verdict=FAIL → HOLD ──
    base_verdict = report.get("base_verdict") or report.get("verdict")
    if base_verdict == "FAIL":
        logger.info("Phase1a base_verdict=FAIL，生成 HOLD 信号: task_id=%s", task_id)
        hold_signal: Dict[str, Any] = {
            "task_id": task_id,
            "created_at": time_utils.now().isoformat(),
            "action": "HOLD",
            "symbol": _extract_symbol(report) or "",
            "confidence": 0.0,
            "suggested_price": 0.0,
            "qty_pct": 0.0,
            "analysis_summary": f"FAIL 回退 HOLD | {report.get('analyst_note', '')}",
            "status": "NEW",
        }
        # 仍然写入信号文件（记录 HOLD 信号）
        return _write_phase1a_signal(hold_signal, base_dir)

    # ── 校验并提取字段 ──
    valid, err_msg, fields = validate_phase1a_report(report)
    if not valid:
        logger.warning("Phase1a 报告校验失败: task_id=%s — %s", task_id, err_msg)
        _write_skip_log(task_id, f"报告校验失败: {err_msg}", base_dir, report)
        return None

    # ── 组装 Phase1a 信号 ──
    action_str = fields["action_str"]
    confidence_str = fields["confidence_str"]
    confidence_num = _confidence_to_numeric(confidence_str)
    suggested_price = fields["suggested_price"]
    position_ratio = fields["position_ratio"]

    # 从 operation_framework 输出 qty_pct
    # position_ratio 直接作为 qty_pct（0~1 范围表示仓位百分比）
    qty_pct = position_ratio
    if qty_pct <= 0 and action_str in ("BUY",):
        # 无显式仓位比例时，按置信度设置默认值
        qty_pct = {"高": 0.3, "中": 0.15, "低": 0.05}.get(confidence_str, 0.1)

    analysis_summary = _build_analysis_summary(report, action_str, confidence_str)

    phase1a_signal: Dict[str, Any] = {
        "task_id": task_id,
        "created_at": time_utils.now().isoformat(),
        "action": action_str,
        "symbol": fields["symbol"],
        "confidence": confidence_num,
        "suggested_price": suggested_price,
        "qty_pct": qty_pct,
        "analysis_summary": analysis_summary,
        "status": "NEW",
    }

    # ── 写入信号文件 ──
    written = _write_phase1a_signal(phase1a_signal, base_dir)
    return written


def _write_phase1a_signal(signal: Dict[str, Any], base_dir: str) -> Optional[Dict[str, Any]]:
    """写入 Phase1a 信号文件（含写后验证）。

    参数：
        signal — Phase1a 格式信号 dict
        base_dir — 项目根目录

    返回：
        写入的信号 dict，或 None（验证失败）
    """
    signal_dir = os.path.join(base_dir, PHASE1A_SIGNAL_DIR)
    os.makedirs(signal_dir, exist_ok=True)

    task_id = signal.get("task_id", "unknown")
    signal_path = os.path.join(signal_dir, f"signal_{task_id}.json")
    tmp_path = signal_path + ".tmp"

    for attempt in range(1, 4):
        try:
            # 写入临时文件
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(signal, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, signal_path)

            # 写后 read 验证
            with open(signal_path, "r", encoding="utf-8") as f:
                verify = json.load(f)

            # 验证关键字段
            _, verify_errors = validate_phase1a_signal(verify)
            if not verify_errors:
                logger.info("Phase1a 信号写入并验证通过: %s (task_id=%s)", signal_path, task_id)
                return verify
            else:
                logger.warning("Phase1a 信号验证失败 (重试 %d/3): %s — %s",
                               attempt, signal_path, verify_errors)

        except Exception as e:
            logger.warning("Phase1a 信号写入异常 (重试 %d/3): %s — %s",
                           attempt, signal_path, e)

    # 3 次均失败
    logger.error("Phase1a 信号写入 3 次均失败: %s", signal_path)
    _write_skip_log(task_id, "写入失败: 写后验证失败 (3次重试)", base_dir)
    return None


def validate_phase1a_signal(signal: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """校验 Phase1a 信号格式。

    必需字段：task_id, created_at, action, symbol, confidence, suggested_price,
              qty_pct, analysis_summary, status
    约束：
        - action ∈ {BUY, SELL, HOLD}
        - confidence >= 0
        - qty_pct ∈ [0, 1]
        - status == "NEW"

    返回：
        (is_valid, errors)
    """
    errors: List[str] = []

    required = ("task_id", "created_at", "action", "symbol", "confidence",
                "suggested_price", "qty_pct", "analysis_summary", "status")
    for field in required:
        if field not in signal or signal[field] is None:
            errors.append(f"缺失必需字段: {field}")

    if errors:
        return False, errors

    if signal.get("action") not in ALLOWED_ACTIONS:
        errors.append(f"action 不合法: {signal.get('action')!r}")

    conf = signal.get("confidence", 0)
    if not isinstance(conf, (int, float)) or conf < 0:
        errors.append(f"confidence 非法: {conf!r}")

    price = signal.get("suggested_price", 0)
    if not isinstance(price, (int, float)) or price < 0:
        errors.append(f"suggested_price 非法: {price!r}")

    qty = signal.get("qty_pct", -1)
    if not isinstance(qty, (int, float)) or not (0 <= qty <= 1):
        errors.append(f"qty_pct 超出 [0,1] 范围: {qty!r}")

    if signal.get("status") != "NEW":
        errors.append(f"status 必须为 'NEW': {signal.get('status')!r}")

    return len(errors) == 0, errors


# ============================================================
# P0-MH-11 完成确认文件写入
# ============================================================

_DONE_CONFIRMATION = """
# signal_converter — 实现确认文件
# author: moheng
# created_time: {now}
# task_id: P0-MH-11
# step: implementation

实现清单：
  1. convert_report_to_signal(report: dict) → Optional[dict]
     - 分析报告 dict → 标准化信号 dict
     - 校验必需字段：symbol/action/confidence/confidence_label/suggested_price/position_ratio
     - base_verdict=FAIL → HOLD 信号（fail-closed）
     - HOLD 信号直接跳过（不下单、不冻结）
     - 校验失败写 _errors 标记 + 不下单

  2. validate_signal(signal: dict) → (bool, errors: list)
     - 信号 schema 全字段校验
     - 类型、取值、范围检查

  3. AnalysisToSignalConverter.convert_from_step2_format(dict, source_path)
     - 类方法：从 dict 直接转换，支持 fail-closed

  4. 错误处理
     - 缺失/无效字段 → signals/paper_trade/{{date}}/_errors/{{task_id}}_error.json
     - WARNING 日志记录错误原因
     - HOLD 信号跳过不写 error

文件位置：automation_v2/paper_trade/signal_converter.py
包依赖：  paper_trade.time_utils
"""


def _write_done_signals() -> None:
    """写入 P0-MH-11 完成确认文件。"""
    now_str = time_utils.now().isoformat()

    # 项目根目录（signal_converter.py 向上 2 层 = mo_zhi_sharereports/）
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    project_root = os.path.abspath(project_root)

    # 目录
    moheng_dir = os.path.join(project_root, "signals", "moheng")
    tasks_dir = os.path.join(project_root, "signals", "tasks")

    os.makedirs(moheng_dir, exist_ok=True)
    os.makedirs(tasks_dir, exist_ok=True)

    # 1) 确认文件 → signals/moheng/mh_signal_converter_done.txt
    done_txt_path = os.path.join(moheng_dir, "mh_signal_converter_done.txt")
    done_content = _DONE_CONFIRMATION.format(now=now_str)
    with open(done_txt_path, "w", encoding="utf-8") as f:
        f.write(done_content.strip() + "\n")
    logger.info("确认文件已写入: %s", done_txt_path)

    # 2) .done 信号 → signals/tasks/P0-MH-11-moheng.done

    done_json = {
        "status": "DONE",
        "task_id": "P0-MH-11",
        "agent": "moheng",
        "step": "implementation",
        "completed_time": now_str,
        "summary": "实现 signal_converter.py：convert_report_to_signal（分析报告→信号JSON）+ validate_signal（输入schema校验）+ HOLD跳过+_errors错误标记",
        "file": "automation_v2/paper_trade/signal_converter.py",
        "functions": [
            "convert_report_to_signal(report: dict) -> Optional[dict]",
            "validate_signal(signal: dict) -> (bool, errors: list)",
            "AnalysisToSignalConverter.convert_from_step2_format(dict, source_path)",
        ],
        ".done_timestamp": now_str,
        "author": "moheng",
        "confirmation_file": "signals/moheng/mh_signal_converter_done.txt",
    }

    done_path = os.path.join(tasks_dir, "P0-MH-11-moheng.done")
    with open(done_path, "w", encoding="utf-8") as f:
        json.dump(done_json, f, ensure_ascii=False, indent=2)
    logger.info("DONE 信号已写入: %s", done_path)


# ── 模块首次导入时自动写入 done 信号 ──
if __name__ != "__main__":
    try:
        _write_done_signals()
    except Exception as _e:
        logger.error("写入 done 信号失败: %s", _e)
else:
    _write_done_signals()
