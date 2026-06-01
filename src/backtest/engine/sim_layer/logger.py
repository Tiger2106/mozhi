"""
交易日志审计 (BT-005) — 完整可审计
====================================
职责:
    - 记录每笔交易的完整信息
    - 支持多种输出格式 (JSON / CSV / 内存)
    - 审计追踪: 交易 ID → 信号 ID → 订单 ID

BT-005 要求:
    每笔交易必须记录:
    - trade_id, symbol, direction
    - entry/exit price, quantity, amount
    - fee, pnl, pnl_pct
    - signal_date, exec_date, signal_id
    - constraint_hit (触发的约束)
    - status (filled/pending/failed)

用法:
    from engine.sim_layer.logger import TradeLogger
    logger = TradeLogger()
    logger.log(trade_record)
    logger.log_batch(trade_records)
    audit_report = logger.summary()

作者: moheng
版本: v1.0
"""
import json
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

_TZ_CN = timezone(timedelta(hours=8))

# P2-4: 审计日志路径 → 项目根目录/audit/
# 原路径: src/backtest/audit/（三层分离后偏移）
# logger.py: src/backtest/engine/sim_layer/logger.py
# parent×5 = 项目根目录
_AUDIT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "audit"


class TradeLogger:
    """BT-005 交易日志审计器

    记录所有交易到审计日志文件（JSON Lines 格式）。

    日志文件命名: audit_{date}_{seq}.jsonl
    """

    def __init__(self, audit_dir: Optional[str] = None):
        self._audit_dir = Path(audit_dir) if audit_dir else _AUDIT_DIR
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._records: List[Dict[str, Any]] = []

    def log(self, trade: Any) -> None:
        """记录单笔交易

        Args:
            trade: TradeRecord 对象（须包含 BT-005 要求的所有字段）
        """
        record = self._to_dict(trade)
        self._records.append(record)
        self._flush(record)

    def log_batch(self, trades: List[Any]) -> None:
        """批量记录交易"""
        for t in trades:
            self.log(t)

    def summary(self) -> Dict[str, Any]:
        """返回审计摘要"""
        return {
            "total_trades": len(self._records),
            "filled": len([r for r in self._records if r.get("status") == "filled"]),
            "pending": len([r for r in self._records if r.get("status") == "pending"]),
            "failed": len([r for r in self._records if r.get("status") == "failed"]),
            "first_trade": self._records[0] if self._records else None,
            "last_trade": self._records[-1] if self._records else None,
            "timestamp": datetime.now(_TZ_CN).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }

    def get_all_records(self) -> List[Dict[str, Any]]:
        """获取所有交易记录"""
        return self._records.copy()

    def _to_dict(self, trade: Any) -> Dict[str, Any]:
        """将 TradeRecord 转换为字典"""
        if hasattr(trade, "__dataclass_fields__"):
            return {k: getattr(trade, k) for k in trade.__dataclass_fields__}
        if isinstance(trade, dict):
            return trade
        return {"error": f"unsupported trade type: {type(trade)}"}

    def _flush(self, record: Dict[str, Any]) -> None:
        """写入审计日志文件"""
        date_str = datetime.now(_TZ_CN).strftime("%Y%m%d")
        log_path = self._audit_dir / f"audit_{date_str}.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


__all__ = ["TradeLogger"]
