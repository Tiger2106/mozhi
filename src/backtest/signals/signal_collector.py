"""
墨枢 - Signal Collector Module

Phase 1-A: Signal Distribution — signal_events 采集体系

提供：
  - BacktestEventHook ABC — 回测引擎事件钩子基类
  - SignalEventCollector — 信号事件采集器，写入 signal_events.db
  - SignalEventDB — 数据库管理（批量写入 + WAL 模式）

用法（集成到回测流水线）:

    from backtest.signals.signal_collector import (
        SignalEventCollector, BacktestEventHook,
        SignalEvent, FilterResult, DecisionResult, PositionUpdate,
    )

    collector = SignalEventCollector(batch_id="bt_20260518")

    # 在策略 on_bar 中信号产生后:
    collector.on_signal_created(SignalEvent(...))

    # 每层过滤器执行后:
    collector.on_filter_check(signal_id, FilterResult(...))

    # 最终决策后:
    collector.on_decision_made(signal_id, DecisionResult(...))

    # 持仓变动后:
    collector.on_position_update(PositionUpdate(...))

    # 回测结束时刷新:
    collector.flush()
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from backtest.backtest_engine import Bar, Strategy

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════


@dataclass
class SignalEvent:
    """信号原始事件。"""
    signal_id: str
    symbol: str
    signal_type: str          # 'grid_trigger', 'breakout', 'volume_signal', 'ma_cross', etc.
    raw_score: float
    timestamp: str            # ISO8601
    strategy_id: str = ""
    batch_id: str = ""
    extra_context: Dict[str, Any] = None


@dataclass
class FilterResult:
    """单次过滤器检查结果。"""
    filter_name: str
    status: str               # 'pass' | 'reject' | 'bypass'
    reason: Optional[str] = None
    elapsed_ms: float = 0.0
    input_state: Optional[str] = None


@dataclass
class DecisionResult:
    """最终决策结果。"""
    final_decision: str       # 'executed' | 'filtered' | 'confidence_low' | 'bypass'
    fusion_score: float = 0.0
    executed_price: Optional[float] = None
    executed_qty: Optional[int] = None
    reject_reason: Optional[str] = None


@dataclass
class PositionUpdate:
    """持仓变动。"""
    symbol: str
    direction: str            # 'open_long' | 'close_long' | 'open_short' | 'close_short'
    price: float
    qty: int
    position_before: int
    position_after: int

# ═══════════════════════════════════════════════════════════════
# BacktestEventHook ABC
# ═══════════════════════════════════════════════════════════════


class BacktestEventHook(ABC):
    """回测引擎事件钩子基类。

    所有钩子实现必须继承此类。钩子之间无顺序依赖，执行失败不影响主流程。
    """

    @abstractmethod
    def on_signal_created(self, event: SignalEvent) -> None:
        """策略模块产生判定结果时触发。

        Args:
            event: 信号原始事件。
        """
        ...

    @abstractmethod
    def on_filter_check(self, signal_id: str, result: FilterResult) -> None:
        """每个过滤器执行完毕后触发。

        Args:
            signal_id: 关联的信号 ID。
            result: 过滤器检查结果。
        """
        ...

    @abstractmethod
    def on_pre_decision(self, signal_id: str, fusion_score: float,
                        filter_summary: Dict[str, FilterResult],
                        regime: Optional[str]) -> None:
        """所有过滤器执行完毕、最终决策前触发。

        Args:
            signal_id: 关联的信号 ID。
            fusion_score: SignalFusion 加权评分。
            filter_summary: 过滤器摘要（filter_name → FilterResult）。
            regime: 当前市场状态。
        """
        ...

    @abstractmethod
    def on_decision_made(self, signal_id: str, decision: DecisionResult) -> None:
        """最终决策已产生时触发。

        Args:
            signal_id: 关联的信号 ID。
            decision: 最终决策。
        """
        ...

    @abstractmethod
    def on_position_update(self, update: PositionUpdate) -> None:
        """持仓变动时触发。

        Args:
            update: 持仓变动详情。
        """
        ...

# ═══════════════════════════════════════════════════════════════
# SignalEventDB — 数据库管理
# ═══════════════════════════════════════════════════════════════


class SignalEventDB:
    """signal_events 数据库管理。

    特性:
      - 批量写入：缓存到阈值后 flush，减少 I/O 次数
      - WAL 模式：读写不互斥
      - 单例模式：全局共享一个连接
    """

    _instance: Optional['SignalEventDB'] = None

    @classmethod
    def get_instance(cls, db_path: Optional[str] = None) -> 'SignalEventDB':
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）。"""
        if cls._instance is not None:
            try:
                cls._instance.close()
            except Exception:
                pass
            cls._instance = None

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base = Path(__file__).resolve().parent.parent.parent.parent
            db_path = str(base / "data" / "signals" / "signal_events.db")
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

        # 批量写入缓存
        self._signal_buffer: List[tuple] = []
        self._filter_buffer: List[tuple] = []
        self._trade_buffer: List[tuple] = []
        self._buffer_size = 100

        self._init_db()

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=OFF")
            self._conn.execute("PRAGMA cache_size=-64000")
        return self._conn

    def _init_db(self) -> None:
        """创建表结构（幂等）。"""
        conn = self._ensure_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signal_events (
                event_id            TEXT PRIMARY KEY,
                batch_id            TEXT,
                timestamp           TEXT NOT NULL,
                symbol              TEXT NOT NULL,
                signal_type         TEXT NOT NULL,
                confidence          REAL,
                strategy_id         TEXT,
                filter_chain_status TEXT,
                decision            TEXT NOT NULL,
                rejection_reason    TEXT,
                created_at          TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS filter_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id        TEXT,
                timestamp       TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                filter_name     TEXT NOT NULL,
                input_state     TEXT,
                output_decision TEXT NOT NULL,
                reason          TEXT,
                latency_ms      REAL
            );
            CREATE TABLE IF NOT EXISTS trade_decisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id        TEXT,
                timestamp       TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                order_type      TEXT,
                quantity        INTEGER,
                price           REAL,
                position_before INTEGER,
                position_after  INTEGER,
                risk_metrics    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_se_symbol ON signal_events(symbol);
            CREATE INDEX IF NOT EXISTS idx_se_timestamp ON signal_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_se_batch ON signal_events(batch_id);
            CREATE INDEX IF NOT EXISTS idx_fl_symbol ON filter_logs(symbol, timestamp);
            CREATE INDEX IF NOT EXISTS idx_fl_batch ON filter_logs(batch_id);
            CREATE INDEX IF NOT EXISTS idx_td_symbol ON trade_decisions(symbol, timestamp);
        """)
        conn.commit()

    # ── 插入方法（批量缓存） ──────────────────────────────────

    def insert_signal_event(self, event_id: str, batch_id: str,
                            timestamp: str, symbol: str,
                            signal_type: str, confidence: float,
                            strategy_id: str,
                            filter_chain_status: Optional[Dict],
                            decision: str,
                            rejection_reason: Optional[str]) -> None:
        self._signal_buffer.append((
            event_id, batch_id, timestamp, symbol, signal_type,
            confidence, strategy_id,
            json.dumps(filter_chain_status, ensure_ascii=False) if filter_chain_status else None,
            decision, rejection_reason,
            datetime.now(timezone.utc).isoformat(),
        ))
        if len(self._signal_buffer) >= self._buffer_size:
            self._flush_signal_events()

    def insert_filter_log(self, batch_id: str, timestamp: str,
                          symbol: str, filter_name: str,
                          input_state: Optional[str],
                          output_decision: str,
                          reason: Optional[str],
                          latency_ms: float) -> None:
        self._filter_buffer.append((
            batch_id, timestamp, symbol, filter_name,
            input_state, output_decision, reason, latency_ms,
        ))
        if len(self._filter_buffer) >= self._buffer_size:
            self._flush_filter_logs()

    def insert_trade_decision(self, batch_id: str, timestamp: str,
                              symbol: str, order_type: str,
                              quantity: int, price: float,
                              position_before: int, position_after: int,
                              risk_metrics: Optional[Dict]) -> None:
        self._trade_buffer.append((
            batch_id, timestamp, symbol, order_type, quantity,
            price, position_before, position_after,
            json.dumps(risk_metrics, ensure_ascii=False) if risk_metrics else None,
        ))
        if len(self._trade_buffer) >= self._buffer_size:
            self._flush_trade_decisions()

    # ── 批量刷新 ──────────────────────────────────────────────

    def _flush_signal_events(self) -> None:
        if not self._signal_buffer:
            return
        conn = self._ensure_conn()
        conn.executemany("""
            INSERT INTO signal_events
                (event_id, batch_id, timestamp, symbol, signal_type,
                 confidence, strategy_id, filter_chain_status,
                 decision, rejection_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, self._signal_buffer)
        conn.commit()
        self._signal_buffer.clear()

    def _flush_filter_logs(self) -> None:
        if not self._filter_buffer:
            return
        conn = self._ensure_conn()
        conn.executemany("""
            INSERT INTO filter_logs
                (batch_id, timestamp, symbol, filter_name,
                 input_state, output_decision, reason, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, self._filter_buffer)
        conn.commit()
        self._filter_buffer.clear()

    def _flush_trade_decisions(self) -> None:
        if not self._trade_buffer:
            return
        conn = self._ensure_conn()
        conn.executemany("""
            INSERT INTO trade_decisions
                (batch_id, timestamp, symbol, order_type, quantity,
                 price, position_before, position_after, risk_metrics)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, self._trade_buffer)
        conn.commit()
        self._trade_buffer.clear()

    def flush_all(self) -> None:
        """强制刷新所有缓冲区。"""
        self._flush_signal_events()
        self._flush_filter_logs()
        self._flush_trade_decisions()

    def close(self) -> None:
        """关闭数据库连接。"""
        self.flush_all()
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── 查询接口（用于测试验证） ──────────────────────────────

    def query_signal_events(self, batch_id: Optional[str] = None,
                            symbol: Optional[str] = None,
                            limit: int = 100) -> List[Dict[str, Any]]:
        """查询信号事件。"""
        self.flush_all()
        conn = self._ensure_conn()
        conditions, params = [], []
        if batch_id:
            conditions.append("batch_id = ?"); params.append(batch_id)
        if symbol:
            conditions.append("symbol = ?"); params.append(symbol)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        cursor = conn.execute(
            f"SELECT * FROM signal_events {where} ORDER BY timestamp LIMIT ?",
            params + [limit]
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]

    def query_filter_logs(self, batch_id: Optional[str] = None,
                          filter_name: Optional[str] = None,
                          limit: int = 100) -> List[Dict[str, Any]]:
        """查询过滤器日志。"""
        self.flush_all()
        conn = self._ensure_conn()
        conditions, params = [], []
        if batch_id:
            conditions.append("batch_id = ?"); params.append(batch_id)
        if filter_name:
            conditions.append("filter_name = ?"); params.append(filter_name)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        cursor = conn.execute(
            f"SELECT * FROM filter_logs {where} ORDER BY timestamp LIMIT ?",
            params + [limit]
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]

    def query_trade_decisions(self, batch_id: Optional[str] = None,
                              limit: int = 100) -> List[Dict[str, Any]]:
        """查询交易决策。"""
        self.flush_all()
        conn = self._ensure_conn()
        conditions, params = [], []
        if batch_id:
            conditions.append("batch_id = ?"); params.append(batch_id)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        cursor = conn.execute(
            f"SELECT * FROM trade_decisions {where} ORDER BY timestamp LIMIT ?",
            params + [limit]
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]

    def count_rows(self, table: str) -> int:
        """返回表中总行数。"""
        self.flush_all()
        conn = self._ensure_conn()
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    @property
    def db_path(self) -> str:
        return self._db_path


# ═══════════════════════════════════════════════════════════════
# SignalEventCollector
# ═══════════════════════════════════════════════════════════════


class SignalEventCollector(BacktestEventHook):
    """信号事件采集器。

    实现所有 BacktestEventHook 钩子方法，将数据写入 signal_events.db。
    使用 SignalEventDB 的批量写入机制最小化 I/O 影响。

    Args:
        db_path: 数据库路径（默认 data/signals/signal_events.db）。
        batch_id: 回测批号。未提供则自动生成。

    Usage:
        collector = SignalEventCollector(batch_id="bt_20260518")
        collector.on_signal_created(SignalEvent(...))
        ...
        collector.flush()
    """

    def __init__(self, db_path: Optional[str] = None,
                 batch_id: Optional[str] = None):
        self.db = SignalEventDB.get_instance(db_path)
        self.batch_id = batch_id or f"bt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._active_signals: Dict[str, Dict[str, Any]] = {}
        """signal_id → {symbol, signal_type, timestamp, strategy_id, filter_chain_status}"""

    # ── 钩子实现 ─────────────────────────────────────────────

    def on_signal_created(self, event: SignalEvent) -> None:
        """信号产生时写入 signal_events 初始记录。

        decision= 'pending'，待后续 on_decision_made 更新。
        """
        event_id = event.signal_id or f"sig_{uuid.uuid4().hex[:12]}"
        ts = event.timestamp or datetime.now(timezone.utc).isoformat()

        self._active_signals[event_id] = {
            "symbol": event.symbol,
            "signal_type": event.signal_type,
            "raw_score": event.raw_score,
            "timestamp": ts,
            "strategy_id": event.strategy_id or "",
            "filter_chain_status": {},
        }

        self.db.insert_signal_event(
            event_id=event_id,
            batch_id=self.batch_id,
            timestamp=ts,
            symbol=event.symbol,
            signal_type=event.signal_type,
            confidence=float(event.raw_score),
            strategy_id=event.strategy_id or "",
            filter_chain_status={},
            decision="pending",
            rejection_reason=None,
        )

    def on_filter_check(self, signal_id: str, result: FilterResult) -> None:
        """记录过滤器检查日志并更新 filter_chain_status。"""
        signal = self._active_signals.get(signal_id)
        if signal:
            signal["filter_chain_status"][result.filter_name] = {
                "status": result.status,
                "reason": result.reason,
            }

        self.db.insert_filter_log(
            batch_id=self.batch_id,
            timestamp=signal.get("timestamp", "") if signal else "",
            symbol=signal.get("symbol", "") if signal else "",
            filter_name=result.filter_name,
            input_state=result.input_state or (
                "signal_active=True" if signal else "signal_active=False"
            ),
            output_decision=result.status,
            reason=result.reason,
            latency_ms=result.elapsed_ms,
        )

    def on_pre_decision(self, signal_id: str, fusion_score: float,
                        filter_summary: Dict[str, FilterResult],
                        regime: Optional[str]) -> None:
        """更新 filter_chain_status（添加 fusion_score 和 regime）。"""
        signal = self._active_signals.get(signal_id)
        if not signal:
            return
        fcs = signal["filter_chain_status"]
        for name, fr in filter_summary.items():
            if name not in fcs:
                fcs[name] = {"status": fr.status, "reason": fr.reason}
        fcs["_fusion_score"] = fusion_score
        if regime:
            fcs["_regime"] = regime

    def on_decision_made(self, signal_id: str, decision: DecisionResult) -> None:
        """更新信号事件的最终决策。先 flush 缓冲区确保 INSERT 已落盘。"""
        signal = self._active_signals.get(signal_id)
        filter_status = signal.get("filter_chain_status") if signal else None

        # 先 flush 缓冲区，确保 INSERT 已落盘，UPDATE 才能命中
        self.db.flush_all()

        conn = self.db._ensure_conn()
        conn.execute("""
            UPDATE signal_events SET
                decision = ?,
                filter_chain_status = ?,
                rejection_reason = ?
            WHERE event_id = ?
        """, (
            decision.final_decision,
            json.dumps(filter_status, ensure_ascii=False) if filter_status else None,
            decision.reject_reason,
            signal_id,
        ))
        conn.commit()

        if signal_id in self._active_signals:
            del self._active_signals[signal_id]

    def on_position_update(self, update: PositionUpdate) -> None:
        """记录持仓变动到 trade_decisions 表。"""
        timestamp = datetime.now(timezone.utc).isoformat()
        self.db.insert_trade_decision(
            batch_id=self.batch_id,
            timestamp=timestamp,
            symbol=update.symbol,
            order_type=update.direction,
            quantity=update.qty,
            price=update.price,
            position_before=update.position_before,
            position_after=update.position_after,
            risk_metrics=None,
        )

    def flush(self) -> None:
        """强制刷新所有缓冲区到数据库。"""
        self.db.flush_all()

    def close(self) -> None:
        """刷新并释放资源。"""
        self.flush()

# ═══════════════════════════════════════════════════════════════
# HookedRiskPipeline — 过滤器日志接入
# ═══════════════════════════════════════════════════════════════


class HookedRiskPipeline:
    """带钩子注入的风险流水线包装器。

    包装现有的 RiskPipeline，在其每个过滤器执行前后自动调用钩子方法。
    使用观察者模式：维护 List[BacktestEventHook]，在关键节点遍历调用。

    用法:
        pipeline = RiskPipeline(...)
        collector = SignalEventCollector(batch_id="bt_001")
        hooked = HookedRiskPipeline(pipeline, signal_id="sig_001")
        hooked.register_hook(collector)

        # 执行过滤器 → 自动记录 filter_logs
        result = hooked.run_market_filter(signals_df, df_ohlcv)
    """

    def __init__(self, pipeline: Any, signal_id: str = ""):
        self._pipeline = pipeline
        self._signal_id = signal_id
        self._hooks: List[BacktestEventHook] = []

    def register_hook(self, hook: BacktestEventHook) -> None:
        """注册钩子实例。"""
        self._hooks.append(hook)

    def remove_hook(self, hook: BacktestEventHook) -> None:
        """移除已注册的钩子。"""
        if hook in self._hooks:
            self._hooks.remove(hook)

    # ── 过滤器包装方法 ───────────────────────────────────────

    def run_market_filter(self, signals: pd.DataFrame,
                          df_ohlcv: pd.DataFrame) -> pd.DataFrame:
        """运行 MarketStateFilter 并触发钩子。"""
        start = time.perf_counter()
        result = self._pipeline.process_pre_filter(signals, df_ohlcv)
        elapsed = (time.perf_counter() - start) * 1000

        # 检查是否有被过滤的信号
        filtered_count = 0
        if "signal" in result.columns and "signal" in signals.columns:
            before = signals["signal"].sum()
            after = result["signal"].sum()
            filtered_count = int(before - after)

        status = "reject" if filtered_count > 0 else "pass"
        reason = f"MarketStateFilter 过滤了 {filtered_count} 个信号" if filtered_count > 0 else None

        for hook in self._hooks:
            try:
                hook.on_filter_check(self._signal_id, FilterResult(
                    filter_name="MarketStateFilter",
                    status=status,
                    reason=reason,
                    elapsed_ms=elapsed,
                    input_state=f"signals_in={len(signals)}, filtered={filtered_count}",
                ))
            except Exception as e:
                logger.warning("Hook on_filter_check failed: %s", e)

        return result

    def run_volatility_sizing(self, signals: pd.DataFrame,
                              df_ohlcv: pd.DataFrame,
                              equity: Optional[float] = None) -> pd.DataFrame:
        """运行 VolatilityRiskManager 并触发钩子。"""
        start = time.perf_counter()
        result = self._pipeline.process_position_sizing(signals, df_ohlcv, equity)
        elapsed = (time.perf_counter() - start) * 1000

        avg_ratio = 1.0
        if "position_ratio" in result.columns:
            avg_ratio = float(result["position_ratio"].mean())

        for hook in self._hooks:
            try:
                hook.on_filter_check(self._signal_id, FilterResult(
                    filter_name="VolatilityRiskMgr",
                    status="bypass" if avg_ratio >= 1.0 else "pass",
                    reason=f"平均仓位比例: {avg_ratio:.3f}",
                    elapsed_ms=elapsed,
                    input_state=f"position_ratio_avg={avg_ratio:.3f}",
                ))
            except Exception as e:
                logger.warning("Hook on_filter_check failed: %s", e)
        return result

    def run_drawdown_guard(self, equity: float, timestamp: str,
                           signal: int) -> int:
        """运行 DrawdownGuard 并触发钩子。"""
        start = time.perf_counter()
        safe_signal = self._pipeline.get_drawdown_guard().update(equity, timestamp, signal)
        elapsed = (time.perf_counter() - start) * 1000

        status = "reject" if safe_signal != signal else "pass"
        state = self._pipeline.get_drawdown_guard().get_state()

        for hook in self._hooks:
            try:
                hook.on_filter_check(self._signal_id, FilterResult(
                    filter_name="DrawdownGuard",
                    status=status,
                    reason=f"回撤={state.current_drawdown:.4f}, breach={state.breach_level}" if status == "reject" else None,
                    elapsed_ms=elapsed,
                    input_state=f"drawdown={state.current_drawdown:.4f}, breach={state.breach_level}",
                ))
            except Exception as e:
                logger.warning("Hook on_filter_check failed: %s", e)

        return safe_signal

    def run_cooldown_check(self, signal: int) -> int:
        """运行冷却期检查并触发钩子。"""
        guard = self._pipeline.get_drawdown_guard()
        state = guard.get_state()
        in_cooldown = state.cooldown_remaining > 0

        status = "reject" if (in_cooldown and signal != -1) else "pass"

        for hook in self._hooks:
            try:
                hook.on_filter_check(self._signal_id, FilterResult(
                    filter_name="CoolingPeriod",
                    status=status,
                    reason=f"冷却剩余={state.cooldown_remaining} bars" if in_cooldown else None,
                    elapsed_ms=0.0,
                    input_state=f"cooldown_remaining={state.cooldown_remaining}",
                ))
            except Exception as e:
                logger.warning("Hook on_filter_check failed: %s", e)

        return signal if status == "pass" else 0

    def fire_pre_decision(self, fusion_score: float,
                          regime: Optional[str] = None) -> None:
        """触发 on_pre_decision 钩子。"""
        for hook in self._hooks:
            try:
                hook.on_pre_decision(self._signal_id, fusion_score, {}, regime)
            except Exception as e:
                logger.warning("Hook on_pre_decision failed: %s", e)

    def fire_decision_made(self, decision: DecisionResult) -> None:
        """触发 on_decision_made 钩子。"""
        for hook in self._hooks:
            try:
                hook.on_decision_made(self._signal_id, decision)
            except Exception as e:
                logger.warning("Hook on_decision_made failed: %s", e)

    def fire_position_update(self, update: PositionUpdate) -> None:
        """触发 on_position_update 钩子。"""
        for hook in self._hooks:
            try:
                hook.on_position_update(update)
            except Exception as e:
                logger.warning("Hook on_position_update failed: %s", e)

    @property
    def pipeline(self) -> Any:
        return self._pipeline
