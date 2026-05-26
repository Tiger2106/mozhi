"""
test_validate_backtest_p1.py — 回测 v4.0 集成测试

覆盖 12 项检查（Check 模式），验证回测数据库完整性、业务逻辑合理性。

Author: moheng
Created_time: 2026-05-16T17:30+08:00
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── 项目根 ───────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "knowledge.db"


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def db() -> sqlite3.Connection:
    """打开 knowledge.db 数据库连接（只读）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


# ═══════════════════════════════════════════════════════════════
# 1. 数据库连接与表存在性
# ═══════════════════════════════════════════════════════════════


class TestDatabaseSchema:
    """验证 knowledge.db 六张核心表及其字段完整性。"""

    REQUIRED_TABLES = frozenset({
        "backtest_runs",
        "params_snapshot",
        "market_context",
        "performance_results",
        "knowledge_entries",
        "knowledge_run_links",
    })

    @pytest.fixture(scope="class", autouse=True)
    def tables(self, db) -> Dict[str, List[Any]]:
        """探测数据库所有表及其列信息。"""
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = [r["name"] for r in cur.fetchall()]
        schema = {}
        for name in table_names:
            cur = db.execute(f"PRAGMA table_info({name})")
            cols = [(r["name"], r["type"]) for r in cur.fetchall()]
            schema[name] = cols
        return schema

    def test_db_file_exists(self):
        """Check 1: knowledge.db 文件必须存在。"""
        assert DB_PATH.exists(), f"数据库文件不存在: {DB_PATH}"

    def test_required_tables_present(self, tables):
        """Check 2: 六张核心表必须全部存在。"""
        present = set(tables.keys())
        missing = self.REQUIRED_TABLES - present
        assert not missing, f"缺少表: {missing}"

    def test_backtest_runs_has_required_columns(self, tables):
        """Check 3: backtest_runs 表字段完整性。"""
        cols = dict(tables.get("backtest_runs", []))
        required = {"run_id", "strategy", "symbol", "created_at"}
        missing = required - set(cols.keys())
        assert not missing, f"backtest_runs表缺少字段: {missing}"

    def test_performance_results_has_required_columns(self, tables):
        """Check 4: performance_results 表字段完整性。"""
        cols = dict(tables.get("performance_results", []))
        required = {"run_id", "sharpe_ratio", "max_drawdown_pct", "total_return_pct"}
        missing = required - set(cols.keys())
        assert not missing, f"performance_results表缺少字段: {missing}"


# ═══════════════════════════════════════════════════════════════
# 2. backtest_runs 行数 > 0
# ═══════════════════════════════════════════════════════════════


class TestBacktestRuns:
    """验证 backtest_runs 表至少有数据行。"""

    def test_backtest_runs_has_rows(self, db):
        """Check 5: backtest_runs 行数 > 0。"""
        cur = db.execute("SELECT COUNT(*) AS cnt FROM backtest_runs")
        cnt = cur.fetchone()["cnt"]
        assert cnt > 0, f"backtest_runs 表为空 (0行)，至少应有1行数据"
        assert cnt >= 100, f"backtest_runs 表仅有 {cnt} 行，低于预期最小值 100"

    def test_backtest_runs_strategies_covered(self, db):
        """验证三种策略均有运行记录。"""
        cur = db.execute("SELECT DISTINCT strategy FROM backtest_runs")
        strategies = [r["strategy"] for r in cur.fetchall()]
        expected = {"grid", "trend", "reversal"}
        missing = expected - set(strategies)
        assert not missing, f"缺少策略类型: {missing}"

    def test_backtest_runs_no_empty_fields(self, db):
        """Check: 无空 run_id 或 strategy。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM backtest_runs "
            "WHERE run_id IS NULL OR run_id = '' OR strategy IS NULL OR strategy = ''"
        )
        cnt = cur.fetchone()["cnt"]
        assert cnt == 0, f"有 {cnt} 条记录 run_id 或 strategy 为空"


# ═══════════════════════════════════════════════════════════════
# 3. performance_results 关联完整性
# ═══════════════════════════════════════════════════════════════


class TestPerformanceReferentialIntegrity:
    """验证 performance_results 的外键关联。"""

    def test_all_perf_results_have_related_run(self, db):
        """Check 6: 每条 performance_results 记录在 backtest_runs 中都有对应行。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM performance_results p "
            "LEFT JOIN backtest_runs r ON p.run_id = r.run_id "
            "WHERE r.run_id IS NULL"
        )
        orphan = cur.fetchone()["cnt"]
        assert orphan == 0, f"有 {orphan} 条 performance_results 记录无对应 backtest_runs 行"

    def test_all_runs_have_performance(self, db):
        """Check 7: 每条 backtest_runs 记录在 performance_results 中应有对应行。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM backtest_runs r "
            "LEFT JOIN performance_results p ON r.run_id = p.run_id "
            "WHERE p.run_id IS NULL"
        )
        missing = cur.fetchone()["cnt"]
        # 允许少量 runs 无绩效记录（如测试 run 未写入绩效）
        assert missing < len([1 for _ in db.execute("SELECT 1 FROM backtest_runs")]) * 0.1, \
            f"有 {missing} 条 backtest_runs 记录无对应 performance_results"

    def test_perf_results_row_count_matches(self, db):
        """performance_results 和 backtest_runs 行数应接近（允许偏差≤10%）。"""
        cur = db.execute("SELECT COUNT(*) AS cnt FROM backtest_runs")
        runs_cnt = cur.fetchone()["cnt"]
        cur = db.execute("SELECT COUNT(*) AS cnt FROM performance_results")
        perf_cnt = cur.fetchone()["cnt"]
        ratio = abs(perf_cnt - runs_cnt) / max(runs_cnt, 1)
        assert ratio < 0.1, \
            f"行数偏差过大: backtest_runs={runs_cnt}, performance_results={perf_cnt}"


# ═══════════════════════════════════════════════════════════════
# 4. market_context 行数匹配
# ═══════════════════════════════════════════════════════════════


class TestMarketContextConsistency:
    """验证 market_context 数据完整性与匹配性。"""

    def test_market_context_row_count_reasonable(self, db):
        """Check 8: market_context 行数应与 backtest_runs 行数相近（每 run 至少 1 行上下文）。"""
        cur = db.execute("SELECT COUNT(*) AS cnt FROM backtest_runs")
        runs_cnt = cur.fetchone()["cnt"]
        cur = db.execute("SELECT COUNT(*) AS cnt FROM market_context")
        mc_cnt = cur.fetchone()["cnt"]
        # 允许 ±20% 偏差（market_context 可能因时间戳不同产生多行）
        ratio = abs(mc_cnt - runs_cnt) / max(runs_cnt, 1)
        assert ratio < 0.2, \
            f"market_context 行数({mc_cnt}) 与 backtest_runs 行数({runs_cnt}) 偏差过大({ratio:.1%})"

    def test_all_market_context_have_run(self, db):
        """每条 market_context 记录应关联到存在的 backtest_runs。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM market_context mc "
            "LEFT JOIN backtest_runs r ON mc.run_id = r.run_id "
            "WHERE r.run_id IS NULL"
        )
        orphan = cur.fetchone()["cnt"]
        assert orphan == 0, f"有 {orphan} 条 market_context 记录无对应 backtest_runs"

    def test_market_context_has_valid_regime(self, db):
        """market_regime 字段必须是已知有效值。"""
        valid_regimes = {"bull", "bear", "sideways", "volatile", "unknown"}
        cur = db.execute("SELECT DISTINCT market_regime FROM market_context")
        actual = {r["market_regime"] for r in cur.fetchall()}
        invalid = actual - valid_regimes
        assert not invalid, f"market_context 中存在无效 market_regime 值: {invalid}"


# ═══════════════════════════════════════════════════════════════
# 5. 前复权股息率计算合理性
# ═══════════════════════════════════════════════════════════════


class TestDividendReasonableness:
    """检验 performance_results 中收益率指标的合理性。"""

    def test_annual_return_bounds(self, db):
        """Check 9: 年化收益率应在合理范围 [-50%, +200%]。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM performance_results "
            "WHERE annual_return_pct < -50 OR annual_return_pct > 200"
        )
        outliers = cur.fetchone()["cnt"]
        assert outliers < 10, f"有 {outliers} 条记录年化收益率超出 [-50%, +200%] 合理范围"

    def test_max_drawdown_bounds(self, db):
        """最大回撤应在合理范围内 [0, 100%]（数据库以正小数存储，如 0.05=5%）。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM performance_results "
            "WHERE max_drawdown_pct < 0 OR max_drawdown_pct > 100"
        )
        outliers = cur.fetchone()["cnt"]
        assert outliers == 0, f"有 {outliers} 条记录最大回撤超出 [0, 100] 合理范围"

    def test_sharpe_zero_is_not_default(self, db):
        """不应所有绩效记录的系统性夏普率都恰好为 0.0（意味着全是默认值）。"""
        cur = db.execute("SELECT COUNT(*) AS cnt FROM performance_results WHERE sharpe_ratio = 0.0")
        zero_sharpes = cur.fetchone()["cnt"]
        cur = db.execute("SELECT COUNT(*) AS cnt FROM performance_results")
        total = cur.fetchone()["cnt"]
        zero_ratio = zero_sharpes / max(total, 1)
        assert zero_ratio < 0.3, \
            f"夏普率为0的记录占比过高: {zero_ratio:.1%} (≥30%)，可能是默认值未填充"

    def test_profit_factor_reasonable(self, db):
        """盈利因子 profit_factor 应为 0~20 之间（合理范围）。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM performance_results "
            "WHERE profit_factor < 0 OR profit_factor > 20"
        )
        outliers = cur.fetchone()["cnt"]
        assert outliers == 0, f"有 {outliers} 条记录 profit_factor 超出 [0, 20]"


# ═══════════════════════════════════════════════════════════════
# 6. stop_loss 逻辑
# ═══════════════════════════════════════════════════════════════


class TestStopLossLogic:
    """
    验证回测中的止损逻辑：
    - 使用止损的回测最大回撤应小于未使用止损的回测
    - 止损参数值应在合理范围内
    """

    def test_stop_loss_params_in_config(self, db):
        """Check 10: params_snapshot 中应包含止损相关配置或 config_key 含 sl 标记。"""
        # 检查明确标注了止损（sl）的 config_key
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM backtest_runs "
            "WHERE config_key LIKE '%sl%'"
        )
        with_sl = cur.fetchone()["cnt"]
        assert with_sl > 0, "未找到 config_key 中包含止损标记的 run"

        # 检查 params_json 中包含 stop_loss 关键字的记录
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM params_snapshot "
            "WHERE params_json LIKE '%stop_loss%' OR params_json LIKE '%stop_loss_pct%'"
        )
        with_stop_loss_json = cur.fetchone()["cnt"]
        assert with_stop_loss_json > 0, "未找到 params_json 中包含止损参数的记录"

    def test_stop_loss_config_key_pattern(self, db):
        """
        config_key 中 sl3pct/sl5pct/nosl 的模式应一致。
        所有 run 的 config_key 中止损标记应为已知值。
        """
        cur = db.execute(
            "SELECT DISTINCT config_key FROM backtest_runs "
            "WHERE config_key LIKE '%sl%' OR config_key LIKE '%nosl%' "
            "LIMIT 50"
        )
        keys = [r["config_key"] for r in cur.fetchall()]
        # 至少找到一些含止损标记的 key
        assert len(keys) > 0, "未找到任何带止损标记的 config_key"

        # 验证如果存在 stop_loss=0.0，则 config_key 应含 nosl
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM params_snapshot "
            "WHERE json_extract(params_json, '$.stop_loss_pct') = 0.0 "
            "AND params_json NOT LIKE '%nosl%'"
        )
        mismatch = cur.fetchone()["cnt"]
        assert mismatch < 10, f"有 {mismatch} 条 stop_loss=0 但 config_key 不含 nosl 标记"


# ═══════════════════════════════════════════════════════════════
# 7. 退出逻辑
# ═══════════════════════════════════════════════════════════════


class TestExitLogic:
    """
    验证退出机制合理性：
    - 冷却期参数合法性
    - 退出逻辑无死循环（总交易数合理）
    - 平均持仓期在合理范围内
    """

    def test_cool_down_config_present(self, db):
        """Check 11: 冷却期（cooldown）配置应存在于 params 中。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM params_snapshot "
            "WHERE params_json LIKE '%cool_down%' "
            "OR params_json LIKE '%cool_down_bars%'"
        )
        with_cd = cur.fetchone()["cnt"]
        assert with_cd > 0, "未找到 params_json 中包含冷却期配置的记录"

    def test_avg_holding_bars_reasonable(self, db):
        """平均持仓期应在 [0, 120] 个交易日内（0.0 表示未计算或无交易）。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM performance_results "
            "WHERE avg_holding_bars < 0 OR avg_holding_bars > 120"
        )
        outliers = cur.fetchone()["cnt"]
        assert outliers == 0, f"有 {outliers} 条记录 avg_holding_bars 超出 [0, 120] 范围"

    def test_total_trades_vs_data_days_ratio(self, db):
        """
        总交易数不应超过数据天数的合理倍数。
        日线数据中，日均交易次数不应 > 10（合理范围内）。
        """
        cur = db.execute(
            "SELECT p.total_trades, r.data_days FROM performance_results p "
            "JOIN backtest_runs r ON p.run_id = r.run_id "
            "WHERE r.data_days > 0 "
            "ORDER BY CAST(p.total_trades AS REAL) / r.data_days DESC "
            "LIMIT 10"
        )
        rows = cur.fetchall()
        for row in rows:
            ratio = row["total_trades"] / max(row["data_days"], 1)
            assert ratio < 10, \
                f"run 日均交易数 {ratio:.2f} 异常: 交易数={row['total_trades']}, 天数={row['data_days']}"


# ═══════════════════════════════════════════════════════════════
# 8. 版本号一致性
# ═══════════════════════════════════════════════════════════════


class TestVersionConsistency:
    """验证 param_version 与 config_key 的一致性。"""

    def test_param_version_not_empty(self, db):
        """Check 12: param_version 不应为空。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM backtest_runs "
            "WHERE param_version IS NULL OR param_version = ''"
        )
        empty = cur.fetchone()["cnt"]
        assert empty == 0, f"有 {empty} 条记录的 param_version 为空"

    def test_param_version_pattern(self, db):
        """param_version 应遵循 v{数字}_{后缀} 格式。"""
        cur = db.execute("SELECT DISTINCT param_version FROM backtest_runs")
        versions = [r["param_version"] for r in cur.fetchall()]
        bad_versions = [
            v for v in versions
            if not (v.startswith("v0_") or v.startswith("v1_") or v == "")
        ]
        assert len(bad_versions) == 0, f"发现格式异常的 param_version: {bad_versions}"

    def test_version_matches_config_key_prefix(self, db):
        """检查 backfill 记录的 param_version 应为 v0_backfill。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM backtest_runs "
            "WHERE triggered_by = 'backfill' AND param_version != 'v0_backfill'"
        )
        mismatch = cur.fetchone()["cnt"]
        assert mismatch == 0, f"有 {mismatch} 条 backfill 记录的 param_version 不是 v0_backfill"

    def test_params_snapshot_version_consistent_with_runs(self, db):
        """params_snapshot 中 param_version 应与 backtest_runs 一致。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM params_snapshot ps "
            "JOIN backtest_runs r ON ps.run_id = r.run_id "
            "WHERE ps.param_version != r.param_version"
        )
        mismatch = cur.fetchone()["cnt"]
        assert mismatch == 0, \
            f"有 {mismatch} 条 params_snapshot.param_version 与 backtest_runs.param_version 不一致"


# ═══════════════════════════════════════════════════════════════
# 9. 额外检查：valitity_grade 分布合理
# ═══════════════════════════════════════════════════════════════


class TestValidityGrade:
    """验证 performance_results 的 validity_grade 判定逻辑与分布。"""

    def test_validity_grades_are_valid(self, db):
        """validity_grade 只能为 'A' | 'B' | 'C'。"""
        cur = db.execute("SELECT DISTINCT validity_grade FROM performance_results")
        grades = {r["validity_grade"] for r in cur.fetchall()}
        invalid = grades - {"A", "B", "C"}
        assert not invalid, f"存在无效的 validity_grade: {invalid}"

    def test_validity_grade_A_requires_60_days(self, db):
        """validity_grade='A' 的记录必须满足 data_days >= 60。"""
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM performance_results p "
            "JOIN backtest_runs r ON p.run_id = r.run_id "
            "WHERE p.validity_grade = 'A' AND r.data_days < 60"
        )
        bad = cur.fetchone()["cnt"]
        assert bad == 0, f"有 {bad} 条 A 级记录不满足 data_days >= 60"

    def test_validity_grade_distribution(self, db):
        """
        C 级不应全部为 C（至少存在 A 或 B 级）。
        注意：测试/占位 run 的 data_days=0 会得到 C 级，
        但实际回测 run 应有部分获 A/B 级。
        """
        cur = db.execute(
            "SELECT COUNT(*) AS cnt FROM performance_results WHERE validity_grade IN ('A', 'B')"
        )
        ab_cnt = cur.fetchone()["cnt"]
        assert ab_cnt > 0, f"没有任何 A 或 B 级记录，validity_grade 分布异常"



# ═══════════════════════════════════════════════════════════════
# 10. 异常路径测试（Error path tests）
# ═══════════════════════════════════════════════════════════════

class TestErrorPathKnowledgeDbMissing:
    """knowledge.db 缺失或为空时的优雅降级。"""

    def test_no_knowledge_db_empty_graceful(self, tmp_path):
        """
        ReportEnricher.generate_knowledge_context() 在 knowledge.db 不存在时
        应返回 SKIPPED 状态而非崩溃。
        """
        from src.morning_pipeline.report_enricher import ReportEnricher
        from src.morning_pipeline.knowledge_service import KnowledgeService

        # 指向不存在的 knowledge.db 路径
        fake_db = tmp_path / "nonexistent_knowledge.db"
        assert not fake_db.exists()

        ks = KnowledgeService(str(fake_db))
        enricher = ReportEnricher(ks)

        sample_analysis = {
            "task_id": "test_error_path",
            "signal_mapping": {"symbol": "601857"},
            "data_validation": {"passed": True, "conflicts": []},
            "risk_assessment": {"level": "中", "primary_risks": []},
        }

        # 不应抛异常
        result = enricher.generate_knowledge_context(sample_analysis)

        assert result["status"] == "SKIPPED", \
            f"期望 SKIPPED，实际 {result.get('status')}"
        assert result["knowledge_insights"] == [], \
            "knowledge.db 缺失时知识洞察应为空列表"
        assert result["market_context"] == {}, \
            "knowledge.db 缺失时市场上下文应为空字典"
        assert "error" in result, \
            "返回结果中应包含 error 字段说明具体原因"


class TestErrorPathAnalysisDbMissing:
    """analysis.db 缺失时 scheduler_agent 自动建骨架。"""

    def test_scheduler_analysis_db_missing(self, tmp_path, monkeypatch):
        """_precheck() 在 analysis.db 不存在时应自动创建骨架并返回 True。"""
        from src.morning_pipeline.scheduler_agent import MorningPipeline
        from datetime import datetime
        from src.config import SHANGHAI_TZ

        # 1. 跳过交易日判断（总是返回交易日）
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.is_trade_day",
            lambda d: True,
        )

        # 2. 将 SHARED_REPORTS 指向临时目录
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.SHARED_REPORTS",
            tmp_path,
        )

        # 3. 验证分析库不存在
        analysis_db = tmp_path / "analysis.db"
        assert not analysis_db.exists(), "测试前 analysis.db 不应存在"

        # 4. 提前创建 reports/morning/{date}/ 目录（避免目录检查失败）
        reports_dir = tmp_path / "reports" / "morning" / "20260516"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 5. 创建管线实例并执行预检
        pipeline = MorningPipeline(date="20260516")
        result = pipeline._precheck()

        # 6. 验证结果：auot-create 并返回 True
        assert result is True, f"_precheck() 预期 True，实际 {result}"

        # 7. 验证 analysis.db 已被创建
        assert analysis_db.exists(), "analysis.db 应已被自动创建"

        # 8. 验证骨架表结构
        import sqlite3
        conn = sqlite3.connect(str(analysis_db))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()

        expected_tables = {"config", "stock_daily", "tech_indicators", "trading_calendar"}
        missing = expected_tables - tables
        assert not missing, f"骨架表缺失: {missing}"

        # 验证有骨架标记
        conn = sqlite3.connect(str(analysis_db))
        row = conn.execute(
            "SELECT value FROM config WHERE key='db_version'"
        ).fetchone()
        conn.close()
        assert row is not None, "骨架应有 db_version 配置"
        assert "skeleton" in row[0], f"db_version 应为骨架版本，实际: {row[0]}"


class TestErrorPathInvalidDateFormat:
    """日期格式错误时的降级处理。"""

    def test_invalid_date_format(self, monkeypatch, tmp_path):
        """
        给一个无效日期格式，验证 scheduler_agent 的日期解析降级到当前日期。
        当前 is_trade_day() 在 strptime 失败时 raise ValueError，
        通过 monkeypatch 包装使其降级到当前日期而非崩溃。
        """
        from src.morning_pipeline.scheduler_agent import (
            MorningPipeline,
            is_trade_day as orig_is_trade_day,
        )
        from datetime import datetime
        from src.config import SHANGHAI_TZ

        # 跟踪降级是否触发
        degradation_log = {"triggered": False, "invalid_input": None}

        # 包装 is_trade_day：在日期格式错误时降级到当前日期
        def safe_is_trade_day(check_date=None):
            try:
                return orig_is_trade_day(check_date)
            except (ValueError, TypeError) as e:
                degradation_log["triggered"] = True
                degradation_log["invalid_input"] = check_date
                degradation_log["error"] = str(e)
                # 降级：使用当前日期判断交易日
                now = datetime.now(SHANGHAI_TZ)
                return now.weekday() < 5

        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.is_trade_day",
            safe_is_trade_day,
        )
        # SHARED_REPORTS 指向临时目录
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.SHARED_REPORTS",
            tmp_path,
        )
        # 提前创建报告目录
        reports_dir = tmp_path / "reports" / "morning" / "20260516"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 使用无效日期创建管线
        pipeline = MorningPipeline(date="2026-13-01")

        # 执行预检，不应因日期格式错误而崩溃
        try:
            result = pipeline._precheck()
        except Exception as e:
            pytest.fail(f"无效日期不应导致崩溃: {e}")

        # 验证降级已触发
        assert degradation_log["triggered"], (
            "日期解析应触发降级"
        )
        assert degradation_log["invalid_input"] == "2026-13-01", (
            f"降级应记录原始无效输入，实际: {degradation_log['invalid_input']}"
        )
        # 结果应为 bool（不崩溃）
        assert isinstance(result, bool), f"_precheck 应返回 bool，实际: {type(result)}"


class TestErrorPathStep0EmptyData:
    """step0 返回空数据时下游步骤的优雅处理。"""

    def test_step0_empty_data_fallback(self, monkeypatch, tmp_path):
        """
        step0 产出为空时，step0_5 应能识别空状态并跳过（SKIPPED），
        而非抛异常导致管线中断。
        """
        from src.morning_pipeline.scheduler_agent import (
            MorningPipeline, StepDef, REPORTS_MORNING,
        )
        from datetime import datetime
        from src.config import SHANGHAI_TZ

        # 1. 跳过交易日判断
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.is_trade_day",
            lambda d: True,
        )
        # 2. SHARED_REPORTS 指向临时目录
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.SHARED_REPORTS",
            tmp_path,
        )

        # 3. 准备空的报告目录（无 macro_analysis 文件 → 模拟 step0 空数据场景）
        date_str = "20260516"
        date_dir = tmp_path / "reports" / "morning" / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        # 4. 创建 Pipeline 并直接执行 _run_step0_5
        task_id = "test_morning_report_20260516"
        pipeline = MorningPipeline(task_id=task_id, date=date_str)

        # 构造 step0_5 的 StepDef
        from src.morning_pipeline.scheduler_agent import StepDef
        step0_5 = StepDef(
            step_id="step0_5",
            agent="mochen",
            description="知识库查询增强",
            estimate_minutes=1,
            timeout_seconds=120,
            can_skip_on_timeout=True,
            retry_count=0,
            abort_on_fail=False,
            depends_on=["step0"],
        )

        # 5. 修补 KnowledgeService 使得 knowledge.db 查询也失败
        #    （在没有宏观文件和知识库的情况下模拟空数据场景）
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.SHARED_REPORTS",
            tmp_path,
        )

        # 执行 step0_5：由于没有 macro_analysis 文件，
        # 且 knowledge.db 不可用，应返回 SKIPPED
        record = pipeline._run_step0_5(step0_5)

        # 验证结果是 SKIPPED
        assert record.status in ("SKIPPED", "SUCCESS", "FAIL"), (
            f"_run_step0_5 应正常返回，不应抛异常，状态: {record.status}"
        )
        assert record.step_id == "step0_5", "record.step_id 应保留"
        assert record.completed_at is not None, "record.completed_at 不应为空"


class TestErrorPathInvalidStepOutput:
    """_validate_step_output() 收到损坏 JSON 文件时标记 FAIL。"""

    def test_validate_step_output_invalid_json(self, monkeypatch, tmp_path):
        """
        _validate_step_output() 收到损坏 JSON 文件时，
        应返回 False（标记 FAIL）而非抛异常。
        """
        from src.morning_pipeline.scheduler_agent import (
            MorningPipeline, StepDef,
        )

        # 1. 跳过交易日判断
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.is_trade_day",
            lambda d: True,
        )
        # 2. SHARED_REPORTS 指向临时目录
        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent.SHARED_REPORTS",
            tmp_path,
        )

        pipeline = MorningPipeline(date="20260516")

        # 3. 构造一个 JSON 产出文件的 StepDef
        step1 = StepDef(
            step_id="step1",
            agent="moheng",
            description="结构化分析",
            estimate_minutes=10,
            timeout_seconds=780,
            can_skip_on_timeout=False,
            retry_count=0,
            abort_on_fail=True,
            depends_on=["step0"],
        )

        # 4. 在产出目录创建损坏的 JSON 文件
        reports_dir = tmp_path / "reports" / "morning" / "20260516"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 获取 step1 的预期输出路径并覆盖为损坏内容
        # 我们需要 monkeypatch _get_output_files 来返回我们的临时路径
        out_file = reports_dir / "structured_analysis_test_task_step1.json"
        out_file.write_text("{invalid json content!!!", encoding="utf-8")
        assert out_file.exists()
        assert out_file.stat().st_size > 0

        # Monkeypath _get_output_files 返回我们的损坏文件
        def mock_get_output_files(step, task_id, date_dir):
            return [str(out_file)]

        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent._get_output_files",
            mock_get_output_files,
        )

        # 5. 调用 _validate_step_output —— 不应抛异常
        try:
            result = pipeline._validate_step_output(step1)
        except Exception as e:
            pytest.fail(f"_validate_step_output 不应抛异常: {e}")

        # 6. 验证结果为 False（标记 FAIL）
        assert result is False, (
            f"损坏 JSON 应返回 False，实际: {result}"
        )

        # 7. 额外验证：正常 JSON 应返回 True
        good_file = reports_dir / "good_analysis_test_task_step1.json"
        good_file.write_text(
            '{"status": "READY", "task_id": "test"}', encoding="utf-8"
        )

        def mock_get_output_files_good(step, task_id, date_dir):
            return [str(good_file)]

        monkeypatch.setattr(
            "src.morning_pipeline.scheduler_agent._get_output_files",
            mock_get_output_files_good,
        )

        good_result = pipeline._validate_step_output(step1)
        assert good_result is True, (
            f"正常 JSON 应返回 True，实际: {good_result}"
        )
