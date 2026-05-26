"""
Phase 1-A 测试：Signal Distribution — signal_events 采集体系

测试内容:
  1. A1: 数据库初始化和表结构验证
  2. A2: SignalEventCollector 钩子方法直接调用
  3. A3: 批量写入与刷新机制
  4. A4: 集成测试 — 真实回测 601857 数据 + 性能基准

用法:
    pytest src/backtest/tests/test_signal_collector.py -v
"""

from __future__ import annotations

import os
import sys
import time
import json
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pytest
import pandas as pd
import numpy as np

# ── 配置 ──────────────────────────────────────────────────────

BASE = r"C:\Users\17699\mozhi_platform"
sys.path.insert(0, BASE)
os.chdir(BASE)

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_db_singleton():
    """每个测试前重置 SignalEventDB 单例，使用临时数据库。"""
    from backtest.signals.signal_collector import SignalEventDB

    SignalEventDB.reset_instance()
    yield
    SignalEventDB.reset_instance()


@pytest.fixture
def tmp_db_path():
    """临时数据库路径。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def db(tmp_db_path):
    """已初始化的 SignalEventDB 实例。"""
    from backtest.signals.signal_collector import SignalEventDB

    return SignalEventDB.get_instance(tmp_db_path)


@pytest.fixture
def collector(tmp_db_path):
    """SignalEventCollector 实例。"""
    from backtest.signals.signal_collector import SignalEventCollector

    return SignalEventCollector(db_path=tmp_db_path, batch_id="test_batch_001")


# ================================================================
# A1: 数据库初始化测试
# ================================================================


class TestDatabaseSchema:
    """验证 signal_events.db 表结构和索引。"""

    def test_tables_created(self, db):
        """确认三张核心表已创建。"""
        conn = sqlite3.connect(db.db_path)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "signal_events" in tables, "signal_events 表缺失"
        assert "filter_logs" in tables, "filter_logs 表缺失"
        assert "trade_decisions" in tables, "trade_decisions 表缺失"

    def test_signal_events_schema(self, db):
        """验证 signal_events 表的列定义。"""
        conn = sqlite3.connect(db.db_path)
        columns = {
            r[1]: r[2] for r in conn.execute(
                "PRAGMA table_info(signal_events)"
            ).fetchall()
        }
        conn.close()
        required = {
            "event_id": "TEXT",
            "batch_id": "TEXT",
            "timestamp": "TEXT",
            "symbol": "TEXT",
            "signal_type": "TEXT",
            "confidence": "REAL",
            "strategy_id": "TEXT",
            "filter_chain_status": "TEXT",
            "decision": "TEXT",
            "rejection_reason": "TEXT",
            "created_at": "TEXT",
        }
        for col, dtype in required.items():
            assert col in columns, f"列 {col} 缺失"
            assert columns[col].upper() == dtype, f"列 {col} 类型应为 {dtype}，实际为 {columns[col]}"

    def test_filter_logs_schema(self, db):
        """验证 filter_logs 表的列定义。"""
        conn = sqlite3.connect(db.db_path)
        columns = {
            r[1]: r[2] for r in conn.execute(
                "PRAGMA table_info(filter_logs)"
            ).fetchall()
        }
        conn.close()
        required = {
            "batch_id": "TEXT",
            "timestamp": "TEXT",
            "symbol": "TEXT",
            "filter_name": "TEXT",
            "input_state": "TEXT",
            "output_decision": "TEXT",
            "reason": "TEXT",
            "latency_ms": "REAL",
        }
        for col, dtype in required.items():
            assert col in columns, f"列 {col} 缺失"

    def test_trade_decisions_schema(self, db):
        """验证 trade_decisions 表的列定义。"""
        conn = sqlite3.connect(db.db_path)
        columns = {
            r[1]: r[2] for r in conn.execute(
                "PRAGMA table_info(trade_decisions)"
            ).fetchall()
        }
        conn.close()
        required = {
            "batch_id": "TEXT",
            "timestamp": "TEXT",
            "symbol": "TEXT",
            "order_type": "TEXT",
            "quantity": "INTEGER",
            "price": "REAL",
            "position_before": "INTEGER",
            "position_after": "INTEGER",
            "risk_metrics": "TEXT",
        }
        for col, dtype in required.items():
            assert col in columns, f"列 {col} 缺失"

    def test_indices_created(self, db):
        """确认关键索引已创建。"""
        conn = sqlite3.connect(db.db_path)
        indices = {
            r[1] for r in conn.execute(
                "SELECT * FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        conn.close()
        assert "idx_se_symbol" in indices, f"idx_se_symbol 索引缺失, 现有: {indices}"
        assert "idx_se_batch" in indices, f"idx_se_batch 索引缺失, 现有: {indices}"
        assert "idx_fl_batch" in indices, f"idx_fl_batch 索引缺失, 现有: {indices}"

    def test_wal_mode_enabled(self, db):
        """确认 WAL 模式已启用。"""
        conn = sqlite3.connect(db.db_path)
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert journal == "wal", f"期望 WAL 模式，实际为 {journal}"


# ================================================================
# A2: SignalEventCollector 钩子方法测试
# ================================================================


class TestSignalEventCollector:
    """直接测试 SignalEventCollector 的各个钩子方法。"""

    def test_on_signal_created(self, collector):
        """测试信号创建钩子。"""
        from backtest.signals.signal_collector import SignalEvent

        collector.on_signal_created(SignalEvent(
            signal_id="sig_test_01",
            symbol="601857",
            signal_type="ma_cross",
            raw_score=0.85,
            timestamp="2026-01-22T09:30:00",
            strategy_id="TrendStrategy-v1",
        ))
        collector.flush()

        events = collector.db.query_signal_events(batch_id="test_batch_001")
        assert len(events) == 1, f"期望 1 条信号事件，实际 {len(events)}"
        e = events[0]
        assert e["event_id"] == "sig_test_01"
        assert e["symbol"] == "601857"
        assert e["signal_type"] == "ma_cross"
        assert e["confidence"] == 0.85
        assert e["decision"] == "pending"

    def test_on_filter_check(self, collector):
        """测试过滤器检查钩子。"""
        from backtest.signals.signal_collector import SignalEvent, FilterResult

        # 先创建信号
        collector.on_signal_created(SignalEvent(
            signal_id="sig_test_02",
            symbol="601857", signal_type="breakout",
            raw_score=0.7, timestamp="2026-01-22T10:00:00",
        ))

        # 模拟三层过滤器检查
        collector.on_filter_check("sig_test_02", FilterResult(
            filter_name="MarketStateFilter",
            status="pass", reason=None, elapsed_ms=2.5,
            input_state="regime=UPTREND",
        ))
        collector.on_filter_check("sig_test_02", FilterResult(
            filter_name="CoolingPeriod",
            status="pass", reason=None, elapsed_ms=0.5,
            input_state="cooldown=0",
        ))
        collector.on_filter_check("sig_test_02", FilterResult(
            filter_name="DrawdownGuard",
            status="pass", reason=None, elapsed_ms=1.0,
            input_state="drawdown=0.02",
        ))
        collector.flush()

        logs = collector.db.query_filter_logs(batch_id="test_batch_001")
        assert len(logs) == 3, f"期望 3 条过滤器日志，实际 {len(logs)}"

        names = [log["filter_name"] for log in logs]
        assert "MarketStateFilter" in names
        assert "CoolingPeriod" in names
        assert "DrawdownGuard" in names

        for log in logs:
            assert log["output_decision"] == "pass"

    def test_on_filter_check_with_rejection(self, collector):
        """测试过滤器拒绝信号。"""
        from backtest.signals.signal_collector import SignalEvent, FilterResult

        collector.on_signal_created(SignalEvent(
            signal_id="sig_test_03",
            symbol="601857", signal_type="volume_signal",
            raw_score=0.4, timestamp="2026-01-25T09:30:00",
        ))

        # MarketState 通过
        collector.on_filter_check("sig_test_03", FilterResult(
            filter_name="MarketStateFilter",
            status="pass", reason=None, elapsed_ms=1.0,
        ))
        # DrawdownGuard 拒绝
        collector.on_filter_check("sig_test_03", FilterResult(
            filter_name="DrawdownGuard",
            status="reject", reason="回撤超过 10%，禁止开新仓",
            elapsed_ms=0.8,
            input_state="drawdown=0.12, breach=warning",
        ))
        collector.flush()

        logs = collector.db.query_filter_logs(batch_id="test_batch_001")
        assert len(logs) == 2

        reject_logs = [l for l in logs if l["output_decision"] == "reject"]
        assert len(reject_logs) == 1
        assert reject_logs[0]["filter_name"] == "DrawdownGuard"
        assert "回撤" in (reject_logs[0]["reason"] or "")

    def test_on_decision_made(self, collector):
        """测试决策完成钩子（更新 filter_chain_status 和 decision）。"""
        from backtest.signals.signal_collector import (
            SignalEvent, FilterResult, DecisionResult,
        )

        # 完整生命周期: 创建 → 过滤 → 决策
        collector.on_signal_created(SignalEvent(
            signal_id="sig_test_04",
            symbol="601857", signal_type="breakout",
            raw_score=0.9, timestamp="2026-02-01T09:30:00",
        ))
        collector.on_filter_check("sig_test_04", FilterResult(
            filter_name="MarketStateFilter",
            status="pass", elapsed_ms=2.0,
            input_state="regime=UPTREND",
        ))
        collector.on_filter_check("sig_test_04", FilterResult(
            filter_name="VolatilityRiskMgr",
            status="pass", elapsed_ms=3.0,
            input_state="position_ratio=0.15",
        ))

        # 最终决策
        collector.on_decision_made("sig_test_04", DecisionResult(
            final_decision="executed",
            fusion_score=0.85,
            executed_price=10.16,
            executed_qty=200,
        ))
        collector.flush()

        events = collector.db.query_signal_events(batch_id="test_batch_001")
        assert len(events) == 1
        e = events[0]
        assert e["decision"] == "executed"

        # 验证 filter_chain_status 为有效 JSON 且包含过滤信息
        fcs = json.loads(e["filter_chain_status"])
        assert "MarketStateFilter" in fcs
        assert "VolatilityRiskMgr" in fcs

    def test_decision_update_from_pending(self, collector):
        """验证 decision 从 pending → executed 的更新流程。"""
        from backtest.signals.signal_collector import SignalEvent, DecisionResult

        # 阶段1: 创建（decision=pending）
        collector.on_signal_created(SignalEvent(
            signal_id="sig_test_05", symbol="000001",
            signal_type="grid_trigger", raw_score=0.6,
            timestamp="2026-03-01T10:00:00",
        ))
        collector.flush()
        events_before = collector.db.query_signal_events(batch_id="test_batch_001")
        assert events_before[0]["decision"] == "pending"

        # 阶段2: 决策更新
        collector.on_decision_made("sig_test_05", DecisionResult(
            final_decision="executed",
            fusion_score=0.6,
            executed_price=15.50,
            executed_qty=100,
        ))
        collector.flush()

        events_after = collector.db.query_signal_events(batch_id="test_batch_001")
        assert events_after[0]["decision"] == "executed"

    def test_on_position_update(self, collector):
        """测试持仓变动记录。"""
        from backtest.signals.signal_collector import PositionUpdate

        collector.on_position_update(PositionUpdate(
            symbol="601857",
            direction="open_long",
            price=10.16,
            qty=200,
            position_before=0,
            position_after=200,
        ))
        collector.on_position_update(PositionUpdate(
            symbol="601857",
            direction="close_long",
            price=10.50,
            qty=200,
            position_before=200,
            position_after=0,
        ))
        collector.flush()

        trades = collector.db.query_trade_decisions(batch_id="test_batch_001")
        assert len(trades) == 2, f"期望 2 条交易记录，实际 {len(trades)}"
        assert trades[0]["order_type"] == "open_long"
        assert trades[0]["symbol"] == "601857"
        assert trades[1]["order_type"] == "close_long"

    def test_on_pre_decision(self, collector):
        """测试决策前钩子（更新 filter_chain_status 元数据）。"""
        from backtest.signals.signal_collector import SignalEvent, FilterResult, DecisionResult

        collector.on_signal_created(SignalEvent(
            signal_id="sig_test_pre", symbol="601857",
            signal_type="breakout", raw_score=0.8,
            timestamp="2026-02-15T10:00:00",
        ))
        collector.on_filter_check("sig_test_pre", FilterResult(
            filter_name="MarketStateFilter", status="pass",
        ))

        # on_pre_decision 添加 fusion_score 和 regime
        collector.on_pre_decision(
            signal_id="sig_test_pre",
            fusion_score=0.75,
            filter_summary={
                "MarketStateFilter": FilterResult(
                    filter_name="MarketStateFilter", status="pass",
                ),
            },
            regime="UPTREND",
        )

        collector.on_decision_made("sig_test_pre", DecisionResult(
            final_decision="filtered",
            fusion_score=0.75,
            reject_reason="冷却期未过",
        ))
        collector.flush()

        events = collector.db.query_signal_events(batch_id="test_batch_001")
        assert len(events) == 1
        fcs = json.loads(events[0]["filter_chain_status"])
        assert fcs.get("_fusion_score") == 0.75
        assert fcs.get("_regime") == "UPTREND"
        assert events[0]["decision"] == "filtered"
        assert events[0]["rejection_reason"] == "冷却期未过"


# ================================================================
# A3: 批量写入与刷新测试
# ================================================================


class TestBatchWrite:
    """验证批量写入机制和性能。"""

    def test_batch_auto_flush(self, tmp_db_path):
        """超过 buffer_size 时自动刷新。"""
        from backtest.signals.signal_collector import (
            SignalEventDB, SignalEvent, SignalEventCollector,
        )

        collector = SignalEventCollector(db_path=tmp_db_path, batch_id="batch_bulk")

        # 写入 buffer_size * 2 条信号（buffer_size 默认 100）
        n = 250
        for i in range(n):
            collector.on_signal_created(SignalEvent(
                signal_id=f"sig_bulk_{i:04d}",
                symbol="601857",
                signal_type="test",
                raw_score=0.5 + (i % 50) * 0.01,
                timestamp=f"2026-01-01T09:{i//60:02d}:{i%60:02d}",
            ))

        # flush（确保全部落盘）
        collector.flush()

        count = collector.db.count_rows("signal_events")
        assert count == n, f"期望 {n} 行，实际 {count}"

    def test_batch_size_100(self, tmp_db_path):
        """验证 100 条批量插入性能。"""
        from backtest.signals.signal_collector import (
            SignalEventDB, SignalEvent, SignalEventCollector,
        )

        collector = SignalEventCollector(db_path=tmp_db_path, batch_id="batch_perf")

        n = 100
        start = time.perf_counter()
        for i in range(n):
            collector.on_signal_created(SignalEvent(
                signal_id=f"sig_perf_{i:04d}",
                symbol="601857",
                signal_type="test",
                raw_score=0.5,
                timestamp="2026-01-01T09:00:00",
            ))
        collector.flush()
        elapsed = time.perf_counter() - start

        count = collector.db.count_rows("signal_events")
        assert count == n
        # 100 条插入应 < 200ms
        assert elapsed < 0.2, f"100 条插入耗时 {elapsed:.3f}s，预期 < 0.2s"

    def test_mixed_operations(self, tmp_db_path):
        """混合写入三种表的内容。"""
        from backtest.signals.signal_collector import (
            SignalEventCollector, SignalEvent, FilterResult,
            DecisionResult, PositionUpdate,
        )

        collector = SignalEventCollector(db_path=tmp_db_path, batch_id="batch_mix")

        # 10 个信号的完整生命周期
        for i in range(10):
            sid = f"sig_full_{i}"
            collector.on_signal_created(SignalEvent(
                signal_id=sid, symbol="601857",
                signal_type="breakout", raw_score=0.7,
                timestamp=f"2026-01-01T10:{i:02d}:00",
            ))
            collector.on_filter_check(sid, FilterResult(
                filter_name="MarketStateFilter", status="pass",
                elapsed_ms=1.0,
            ))
            collector.on_filter_check(sid, FilterResult(
                filter_name="CoolingPeriod", status="pass",
            ))
            collector.on_filter_check(sid, FilterResult(
                filter_name="DrawdownGuard", status="pass",
                elapsed_ms=0.5,
            ))

            decision = "executed" if i % 2 == 0 else "filtered"
            collector.on_decision_made(sid, DecisionResult(
                final_decision=decision,
                fusion_score=0.7,
                executed_price=10.0 if decision == "executed" else None,
                executed_qty=100 if decision == "executed" else None,
                reject_reason=None if decision == "executed" else "冷却期",
            ))

            collector.on_position_update(PositionUpdate(
                symbol="601857",
                direction="open_long" if i % 2 == 0 else "close_long",
                price=10.0,
                qty=100,
                position_before=0,
                position_after=100,
            ))

        collector.flush()

        assert collector.db.count_rows("signal_events") == 10
        assert collector.db.count_rows("filter_logs") == 30  # 10×3 filters
        assert collector.db.count_rows("trade_decisions") == 10

        # 确认决策分布正确
        events = collector.db.query_signal_events(batch_id="batch_mix")
        executed = [e for e in events if e["decision"] == "executed"]
        filtered = [e for e in events if e["decision"] == "filtered"]
        assert len(executed) == 5
        assert len(filtered) == 5


# ================================================================
# A4: 集成测试 — 真实回测
# ================================================================


class TestIntegrationBacktest:
    """集成测试：用回测引擎跑 601857 数据，验证采集体系。"""

    @pytest.fixture
    def ohlcv_data(self):
        """加载 601857 的 OHLCV 数据。"""
        csv_path = os.path.join(BASE, "data", "market", "601857_SH.csv")
        if not os.path.exists(csv_path):
            pytest.skip(f"CSV 数据不存在: {csv_path}")
        df = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
        df = df.sort_index()
        return df.loc["2026-01-01":"2026-05-14"]

    @pytest.fixture
    def bars_from_csv(self, ohlcv_data):
        """将 CSV 数据转换为 Bar 列表。"""
        from backtest.backtest_engine import Bar

        bars = []
        for idx, row in ohlcv_data.iterrows():
            bars.append(Bar(
                date=idx.strftime("%Y-%m-%d"),
                symbol="601857",
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                vwap=float(row.get("vwap", 0.0) if pd.notna(row.get("vwap", 0.0)) else 0.0),
            ))
        return bars

    def create_simple_grid_strategy(self):
        """创建一个简单的网格策略，保证有信号产生。"""
        from backtest.backtest_engine import Strategy, OrderRequest
        from backtest.order_executor import OrderSide, OrderType

        class SimpleTestStrategy(Strategy):
            def __init__(self):
                self.last_close = 0.0
                self.bought = False
                self.sold = False
                self.signal_count = 0

            def on_bar(self, context, bar):
                self.last_close = bar.close
                orders = []
                price = bar.close

                # 第一次到 price > 10.5 买入
                if price > 10.5 and not self.bought:
                    qty = int(context.initial_capital * 0.15 / price / 100) * 100
                    if qty > 0:
                        orders.append(OrderRequest(
                            symbol=bar.symbol,
                            side=OrderSide.BUY,
                            quantity=qty,
                        ))
                        self.bought = True
                        self.signal_count += 1

                # price < 9.8 卖出
                elif price < 9.8 and self.bought and not self.sold:
                    pos = context.position_manager.get_position(bar.symbol)
                    if pos:
                        orders.append(OrderRequest(
                            symbol=bar.symbol,
                            side=OrderSide.SELL,
                            quantity=pos.quantity,
                        ))
                        self.sold = True
                        self.signal_count += 1

                return orders

        return SimpleTestStrategy()

    def test_simple_backtest_with_collector(self, bars_from_csv, tmp_db_path):
        """用简单策略 + 采集器跑回测，验证记录生成。"""
        from backtest.backtest_engine import (
            BacktestConfig, BacktestEngine,
        )
        from backtest.signals.signal_collector import (
            SignalEventCollector, SignalEvent, DecisionResult,
        )

        strategy = self.create_simple_grid_strategy()
        config = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-05-14",
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=config, strategy=strategy)

        # 创建采集器
        collector = SignalEventCollector(
            db_path=tmp_db_path,
            batch_id="int_test_bt_001",
        )

        # 执行回测（手动注入钩子，因为我们没有修改引擎）
        # 改为包装 strategy 的 on_bar 方法
        original_on_bar = strategy.on_bar
        wrapped_strategy = strategy

        def hooked_on_bar(context, bar):
            # 在 strategy.on_bar 执行前发出信号事件
            sig_id = f"sig_bt_{bar.date}"
            collector.on_signal_created(SignalEvent(
                signal_id=sig_id,
                symbol=bar.symbol,
                signal_type="price_trigger",
                raw_score=0.5,
                timestamp=f"{bar.date}T09:30:00",
                strategy_id="SimpleTestStrategy",
            ))

            orders = original_on_bar(context, bar)

            # 如果有下单，记录决策
            if orders:
                collector.on_decision_made(sig_id, DecisionResult(
                    final_decision="executed",
                    fusion_score=0.5,
                    executed_price=bar.close,
                    executed_qty=orders[0].quantity,
                ))

                # 记录持仓变动（从 executor 获取）
                from backtest.signals.signal_collector import PositionUpdate
                collector.on_position_update(PositionUpdate(
                    symbol=bar.symbol,
                    direction="open_long" if orders[0].side.value == "BUY" else "close_long",
                    price=bar.close,
                    qty=orders[0].quantity,
                    position_before=0,
                    position_after=orders[0].quantity,
                ))
            else:
                collector.on_decision_made(sig_id, DecisionResult(
                    final_decision="bypass",
                    fusion_score=0.5,
                ))

            return orders

        strategy.on_bar = hooked_on_bar

        # 运行回测
        result = engine.run(bars_from_csv)

        # 刷新采集器
        collector.flush()

        # ── 验证 ─────────────────────────────────────────────
        signal_count = collector.db.count_rows("signal_events")
        trade_count = collector.db.count_rows("trade_decisions")

        print(f"\n回测结果: {len(bars_from_csv)} bars, "
              f"{result.total_trades} trades, "
              f"{signal_count} signal_events, "
              f"{trade_count} trade_decisions")

        # 信号事件应等于 bar 数量
        assert signal_count == len(bars_from_csv), \
            f"期望 {len(bars_from_csv)} 条信号事件，实际 {signal_count}"

        # 成交决策数等于实际交易数
        executed_events = [
            e for e in collector.db.query_signal_events(batch_id="int_test_bt_001")
            if e["decision"] == "executed"
        ]
        assert len(executed_events) == result.total_trades, \
            f"期望 {result.total_trades} 条成交事件，实际 {len(executed_events)}"

        # 交易决策记录条数
        assert trade_count == result.total_trades, \
            f"期望 {result.total_trades} 条交易决策，实际 {trade_count}"

        print(f"集成测试通过: {signal_count} 信号事件, "
              f"{trade_count} 交易记录, "
              f"{result.total_trades} 实际成交")

    def test_backtest_performance(self, bars_from_csv, tmp_db_path):
        """测试带采集器的回测性能，验证不影响回测速度。"""
        import time
        from backtest.backtest_engine import BacktestConfig, BacktestEngine
        from backtest.signals.signal_collector import (
            SignalEventCollector, SignalEvent, DecisionResult, PositionUpdate,
        )

        strategy = self.create_simple_grid_strategy()
        config = BacktestConfig(start_date="2026-01-01", end_date="2026-05-14")
        engine = BacktestEngine(config=config, strategy=strategy)

        collector = SignalEventCollector(
            db_path=tmp_db_path,
            batch_id="perf_test",
        )

        original_on_bar = strategy.on_bar

        def hooked_on_bar(context, bar):
            sig_id = f"sig_perf_{bar.date}"
            collector.on_signal_created(SignalEvent(
                signal_id=sig_id,
                symbol=bar.symbol,
                signal_type="price_trigger",
                raw_score=0.5,
                timestamp=f"{bar.date}T09:30:00",
            ))
            orders = original_on_bar(context, bar)
            if orders:
                collector.on_decision_made(sig_id, DecisionResult(
                    final_decision="executed",
                    fusion_score=0.5,
                    executed_price=bar.close,
                    executed_qty=orders[0].quantity,
                ))
                collector.on_position_update(PositionUpdate(
                    symbol=bar.symbol,
                    direction="open_long" if orders[0].side.value == "BUY" else "close_long",
                    price=bar.close,
                    qty=orders[0].quantity,
                    position_before=0,
                    position_after=orders[0].quantity,
                ))
            else:
                collector.on_decision_made(sig_id, DecisionResult(
                    final_decision="bypass",
                    fusion_score=0.5,
                ))
            return orders

        strategy.on_bar = hooked_on_bar

        # 时间测量
        start = time.perf_counter()
        result = engine.run(bars_from_csv)
        collector.flush()
        elapsed = time.perf_counter() - start

        # 验证性能
        assert elapsed < 10.0, f"回测耗时 {elapsed:.2f}s，期望 < 10s"
        assert collector.db.count_rows("signal_events") == len(bars_from_csv)

        print(f"性能测试: {len(bars_from_csv)} bars / {result.total_trades} trades "
              f"在 {elapsed:.2f}s 完成")


# ================================================================
# A4b: HookedRiskPipeline 测试
# ================================================================


class TestHookedRiskPipeline:
    """测试带钩子的风险流水线包装器。"""

    def test_market_filter_hook(self, tmp_db_path):
        """验证 MarketStateFilter 的钩子触发。"""
        from backtest.signals.signal_collector import (
            SignalEventCollector, HookedRiskPipeline,
            SignalEvent,
        )

        # 创建 Mock RiskPipeline
        class MockPipeline:
            def process_pre_filter(self, signals, df_ohlcv):
                return signals

            def process_position_sizing(self, signals, df_ohlcv, equity=None):
                signals = signals.copy()
                signals["position_ratio"] = 1.0
                return signals

            def get_drawdown_guard(self):
                class MockGuard:
                    def update(self, eq, ts, sig):
                        return sig

                    def get_state(self):
                        from collections import namedtuple
                        S = namedtuple("DrawdownState", ["current_drawdown", "breach_level", "cooldown_remaining"])
                        return S(current_drawdown=0.0, breach_level="none", cooldown_remaining=0)

                return MockGuard()

        collector = SignalEventCollector(db_path=tmp_db_path, batch_id="hooked_test")
        pipeline = HookedRiskPipeline(MockPipeline(), signal_id="sig_hook_01")
        pipeline.register_hook(collector)

        # 模拟信号数据
        dates = pd.date_range("2026-01-01", periods=5, freq="D")
        signals = pd.DataFrame({"signal": [1, 0, 1, -1, 0]}, index=dates)
        df_ohlcv = pd.DataFrame({
            "close": [10.0, 10.1, 10.2, 10.0, 9.9],
            "high": [10.2, 10.3, 10.4, 10.2, 10.0],
            "low": [9.9, 10.0, 10.1, 9.9, 9.8],
            "volume": [1000, 1200, 1100, 900, 800],
        }, index=dates)

        # 运行过滤器
        pipeline.run_market_filter(signals, df_ohlcv)
        pipeline.run_volatility_sizing(signals, df_ohlcv)
        pipeline.run_drawdown_guard(1_000_000, "2026-01-05", 1)
        pipeline.run_cooldown_check(1)

        pipeline.fire_pre_decision(0.75, "UPTREND")
        collector.flush()

        logs = collector.db.query_filter_logs(batch_id="hooked_test")
        assert len(logs) >= 3, f"期望至少 3 条过滤器日志，实际 {len(logs)}"

        names = set(log["filter_name"] for log in logs)
        assert "MarketStateFilter" in names
        assert "VolatilityRiskMgr" in names
        assert "DrawdownGuard" in names

    def test_filter_rejection_hook(self, tmp_db_path):
        """验证过滤器拒绝信号的钩子记录。"""
        from backtest.signals.signal_collector import (
            SignalEventCollector, HookedRiskPipeline,
        )

        class MockRejectPipeline:
            def process_pre_filter(self, signals, df_ohlcv):
                # 拒绝所有买入信号
                result = signals.copy()
                result.loc[result["signal"] == 1, "signal"] = 0
                return result

            def process_position_sizing(self, signals, df_ohlcv, equity=None):
                signals = signals.copy()
                signals["position_ratio"] = 1.0
                return signals

            def get_drawdown_guard(self):
                class MockGuard:
                    def update(self, eq, ts, sig):
                        return sig

                    def get_state(self):
                        from collections import namedtuple
                        S = namedtuple("DrawdownState", ["current_drawdown", "breach_level", "cooldown_remaining"])
                        return S(current_drawdown=0.0, breach_level="none", cooldown_remaining=0)

                return MockGuard()

        collector = SignalEventCollector(db_path=tmp_db_path, batch_id="reject_test")
        pipeline = HookedRiskPipeline(MockRejectPipeline(), signal_id="sig_reject_01")
        pipeline.register_hook(collector)

        dates = pd.date_range("2026-01-01", periods=3, freq="D")
        signals = pd.DataFrame({"signal": [1, 0, 1]}, index=dates)
        df_ohlcv = pd.DataFrame({
            "close": [10.0, 10.1, 10.2],
            "high": [10.2, 10.3, 10.4],
            "low": [9.9, 10.0, 10.1],
            "volume": [1000, 1200, 1100],
        }, index=dates)

        pipeline.run_market_filter(signals, df_ohlcv)
        collector.flush()

        logs = collector.db.query_filter_logs(batch_id="reject_test")
        reject_logs = [l for l in logs if l["output_decision"] == "reject"]
        assert len(reject_logs) >= 1, "期望至少 1 条拒绝记录"

        for log in reject_logs:
            assert log["filter_name"] == "MarketStateFilter"
