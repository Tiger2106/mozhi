# ============================================================
# unified_ingestion.py — 统一股票日线灌入程序
# E-002 P0 Implementation
# Author: 墨衡
# Version: v2.0
# Created: 2026-05-26T07:20:00+08:00
# Updated: 2026-05-26T07:20:00+08:00
# Fixes:
#   Fix 1: QC 规则编号对齐设计文档 §2.5
#   Fix 2: staging_raw 增加 REPORT 状态判定
#   Fix 3: backup 每标的级触发
#   Fix 4: 审计记录放回主事务内
# Description: 标的池配置 → Tushare API 限流获取 → QC 校验 →
#              Staging 原子写入 → 审计日志，完整 ETL 流水线
# ============================================================
"""
Usage:
    # Dry-run (不写入数据库)
    python -m src.data.unified_ingestion --dry-run

    # 全量重灌 (FULL_RELOAD)
    python -m src.data.unified_ingestion --mode FULL_RELOAD

    # 增量灌入 (INCREMENTAL)
    python -m src.data.unified_ingestion --mode INCREMENTAL

    # 指定单标的
    python -m src.data.unified_ingestion --symbol 601857.SH
"""

import os
import sys
import json
import time
import yaml
import sqlite3
import logging
import hashlib
import argparse
import statistics
import random
from datetime import datetime, timedelta, timezone, date
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from pathlib import Path
from enum import Enum

TZ = timezone(timedelta(hours=8))

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("unified_ingestion")

# ============================================================
# Config paths
# ============================================================
BASE_DIR = Path(__file__).resolve().parents[2]  # mo_zhi_sharereports
CONFIG_PATH = BASE_DIR / "config" / "ingestion_config.yaml"
DB_PATH = BASE_DIR / "market_data.db"


# ============================================================
# IngestionTask — 灌入任务数据类
# ============================================================
@dataclass
class IngestionTask:
    """单个标的的灌入任务描述"""
    ts_code: str
    name: str
    market: str
    symbol_type: str          # "stock" | "index"
    start_date: str           # YYYY-MM-DD
    end_date: str             # YYYY-MM-DD
    fields: List[str]
    mode: str                 # "FULL_RELOAD" | "INCREMENTAL"
    batch_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.batch_id:
            ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
            self.batch_id = f"E002_{self.ts_code.replace('.','_')}_{ts}"
        if not self.created_at:
            self.created_at = datetime.now(TZ).isoformat()


# ============================================================
# Stage 1: SymbolRegistry — 标的池配置读取
# ============================================================
class SymbolRegistry:
    """从 ingestion_config.yaml 读取标的池配置。支持按 market/type/active 筛选。"""

    def __init__(self, config_path: str = str(CONFIG_PATH)):
        self.config_path = config_path
        self._config: Optional[dict] = None
        self._symbols: List[dict] = []
        self._load()

    def _load(self):
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f)
        self._symbols = self._config.get("symbols", [])

    @property
    def ingestion_config(self) -> dict:
        return self._config.get("ingestion", {})

    def get_active_symbols(self) -> List[dict]:
        return [s for s in self._symbols if s.get("active", False)]

    def get_symbol(self, ts_code: str) -> Optional[dict]:
        for s in self._symbols:
            if s["ts_code"] == ts_code:
                return s
        return None

    def get_tushare_config(self) -> dict:
        return self.ingestion_config.get("tushare", {})

    def get_qc_config(self) -> dict:
        return self.ingestion_config.get("qc", {})

    def get_audit_config(self) -> dict:
        return self.ingestion_config.get("audit", {})

    def get_staging_config(self) -> dict:
        return self.ingestion_config.get("staging", {})


# ============================================================
# Stage 2: TushareRateLimiter — Tushare API 限流管理
# ============================================================
class TushareRateLimiter:
    """
    Tushare Pro API 限流器。
    - 按标的串行请求
    - 请求间隔 0.3~0.8s
    - 失败重试 ×3 + 指数退避
    - 连续 3 次失败标记 SOURCE_UNAVAILABLE
    """

    def __init__(self, config: dict):
        self.retry_max = config.get("retry_max", 3)
        self.delay_min = config.get("retry_delay_min", 0.3)
        self.delay_max = config.get("retry_delay_max", 0.8)
        self.backoff_factor = config.get("backoff_factor", 2.0)
        self._last_request_time: float = 0.0
        self._consecutive_failures: Dict[str, int] = defaultdict(int)
        self._circuit_breaker: Dict[str, bool] = defaultdict(bool)
        self._pro = None

    def _import_api(self):
        if self._pro is None:
            import tushare as ts
            tk_path = os.path.join(BASE_DIR, "config", "tk.csv")
            if os.path.exists(tk_path):
                with open(tk_path, "r") as f:
                    ts.set_token(f.read().strip())
            self._pro = ts.pro_api()
        return self._pro

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay_min:
            time.sleep(random.uniform(self.delay_min, self.delay_max))
        self._last_request_time = time.time()

    def fetch_daily(self, ts_code: str, start_date: str, end_date: str,
                    fields: Optional[List[str]] = None) -> Optional[Any]:
        """获取单标的日线数据，带限流 + 重试 + 熔断。"""
        pro = self._import_api()

        if self._circuit_breaker.get(ts_code, False):
            logger.warning(f"[CIRCUIT_BREAKER] {ts_code} 已熔断，跳过")
            return None

        symbol_key = ts_code.split(".")[0]

        for attempt in range(1, self.retry_max + 1):
            self._rate_limit_wait()
            try:
                df = pro.daily(ts_code=ts_code, start_date=start_date,
                               end_date=end_date, fields=fields)
                if df is None or df.empty:
                    self._consecutive_failures[symbol_key] += 1
                    if self._consecutive_failures[symbol_key] >= 3:
                        self._circuit_breaker[ts_code] = True
                        logger.error(f"[SOURCE_UNAVAILABLE] {ts_code}: 连续 3 次失败，标记熔断")
                    time.sleep(self.delay_min * (self.backoff_factor ** (attempt - 1)))
                    continue
                self._consecutive_failures[symbol_key] = 0
                return df
            except Exception as e:
                logger.warning(f"[ATTEMPT {attempt}/{self.retry_max}] {ts_code}: {e}")
                self._consecutive_failures[symbol_key] += 1
                if self._consecutive_failures[symbol_key] >= 3:
                    self._circuit_breaker[ts_code] = True
                    logger.error(f"[SOURCE_UNAVAILABLE] {ts_code}: 连续 3 次失败，标记熔断")
                time.sleep(self.delay_min * (self.backoff_factor ** (attempt - 1)))

        logger.error(f"[FAILED] {ts_code}: 所有重试均失败")
        return None

    def fetch_adj_factor(self, ts_code: str, start_date: str, end_date: str) -> Optional[Any]:
        """获取单个标的的复权因子数据。调用 pro.adj_factor() 独立接口。"""
        pro = self._import_api()
        symbol_key = ts_code.split(".")[0]

        if self._circuit_breaker.get(ts_code, False):
            logger.warning(f"[CIRCUIT_BREAKER] {ts_code} adj_factor 已熔断，跳过")
            return None

        for attempt in range(1, self.retry_max + 1):
            self._rate_limit_wait()
            try:
                df = pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is None or df.empty:
                    self._consecutive_failures[symbol_key] += 1
                    if self._consecutive_failures[symbol_key] >= 3:
                        self._circuit_breaker[ts_code] = True
                        logger.error(f"[SOURCE_UNAVAILABLE] {ts_code} adj_factor: 连续 3 次失败")
                    time.sleep(self.delay_min * (self.backoff_factor ** (attempt - 1)))
                    continue
                self._consecutive_failures[symbol_key] = 0
                return df
            except Exception as e:
                logger.warning(f"[adj_factor ATTEMPT {attempt}/{self.retry_max}] {ts_code}: {e}")
                self._consecutive_failures[symbol_key] += 1
                if self._consecutive_failures[symbol_key] >= 3:
                    self._circuit_breaker[ts_code] = True
                    logger.error(f"[SOURCE_UNAVAILABLE] {ts_code} adj_factor: 连续 3 次失败")
                time.sleep(self.delay_min * (self.backoff_factor ** (attempt - 1)))

        logger.error(f"[FAILED] {ts_code} adj_factor: 所有重试均失败")
        return None

    def get_source_status(self, ts_code: str) -> str:
        return "SOURCE_UNAVAILABLE" if self._circuit_breaker.get(ts_code, False) else "AVAILABLE"


# ============================================================
# Stage 3: QCEngine — 质量校验引擎（13 条规则，编号对齐设计文档 §2.5）
# ============================================================
class QCEngine:
    """
    13 条 QC 规则实现 (QC-001 ~ QC-013)，编号对齐设计文档 §2.5。

    三值判定：
    - PASS ✓:   正常写入 stock_daily 主表
    - REPORT ⚠️: 写入 stock_daily 主表 + 同时写入 staging_raw（不阻断）
    - FAIL ❌:   不写入主表，仅写入 staging_raw
    """

    def __init__(self, config: dict):
        self.config = config
        self.results: List[dict] = []

    def run_all(self, df) -> dict:
        """运行全部 13 条 QC 规则 + 3 条非标准额外检查"""
        self.results = []
        import pandas as pd

        # ──────────────────────────────────────────────
        # QC-001: 批次行数完整性（行数变化率，P0 固定阈值不阻断）
        # 状态：非阻断 → REPORT（当有异常时）
        # ──────────────────────────────────────────────
        row_count = len(df)
        threshold = self.config.get("row_count_change_threshold", 0.50)
        # P0 阶段：无法依赖 trading_calendar，仅记录阈值
        self.results.append({
            "qc_id": "QC-001", "name": "行数变化率",
            "status": "REPORT",
            "failed_rows": 0,
            "actual": row_count,
            "threshold": threshold
        })

        # ──────────────────────────────────────────────
        # QC-002: 单日无重复日期
        # 状态：硬损伤 → FAIL
        # ──────────────────────────────────────────────
        qc2_fail = 0
        if 'ts_code' in df.columns and 'trade_date' in df.columns:
            qc2_fail = int(df.duplicated(subset=['ts_code', 'trade_date']).sum())
        self.results.append({
            "qc_id": "QC-002", "name": "无重复主键",
            "status": "PASS" if qc2_fail == 0 else "FAIL",
            "failed_rows": qc2_fail
        })

        # ──────────────────────────────────────────────
        # QC-003: 关键字段非NULL（open/high/low/close/adj_factor）
        # 状态：硬损伤 → FAIL
        # ──────────────────────────────────────────────
        qc3_fail = 0
        for col in ['open', 'high', 'low', 'close', 'adj_factor']:
            if col in df.columns:
                qc3_fail += int(df[col].isna().sum())
        self.results.append({
            "qc_id": "QC-003", "name": "关键字段非NULL",
            "status": "PASS" if qc3_fail == 0 else "FAIL",
            "failed_rows": qc3_fail
        })

        # ──────────────────────────────────────────────
        # QC-004: 辅助字段非NULL（volume/amount）
        # 状态：硬损伤 → FAIL
        # ──────────────────────────────────────────────
        qc4_fail = 0
        for col in ['vol', 'volume', 'amount']:
            if col in df.columns:
                qc4_fail += int(df[col].isna().sum())
        self.results.append({
            "qc_id": "QC-004", "name": "辅助字段非NULL",
            "status": "PASS" if qc4_fail == 0 else "FAIL",
            "failed_rows": qc4_fail
        })

        # ──────────────────────────────────────────────
        # QC-005: 非关键字段 NULL < 5%
        # 状态：非阻断 → REPORT（NULL > 5% 时）
        # ──────────────────────────────────────────────
        qc5_fail = 0
        qc5_total = 0
        for col in ['turnover_rate', 'turnover_rate_f', 'volume_ratio',
                     'pe', 'pe_ttm', 'pb']:
            if col in df.columns:
                qc5_total += len(df)
                qc5_fail += int(df[col].isna().sum())
        qc5_null_rate = qc5_fail / max(qc5_total, 1)
        self.results.append({
            "qc_id": "QC-005", "name": "非关键字段NULL<5%",
            "status": "PASS" if qc5_null_rate < 0.05 else "REPORT",
            "failed_rows": qc5_fail,
            "null_rate": round(qc5_null_rate, 4)
        })

        # ──────────────────────────────────────────────
        # QC-006: OHLC 逻辑一致性
        #   high >= low, high >= open, high >= close
        #   low  <= open, low  <= close
        #   close ∈ [low, high]（99%+ pass rate）
        # 状态：硬损伤 → FAIL
        # ──────────────────────────────────────────────
        qc6_fail = 0
        if all(c in df.columns for c in ['high', 'low']):
            qc6_fail += int((df['high'].astype(float) < df['low'].astype(float)).sum())
        if all(c in df.columns for c in ['high', 'open']):
            qc6_fail += int((df['high'].astype(float) < df['open'].astype(float)).sum())
        if all(c in df.columns for c in ['high', 'close']):
            qc6_fail += int((df['high'].astype(float) < df['close'].astype(float)).sum())
        if all(c in df.columns for c in ['low', 'open']):
            qc6_fail += int((df['low'].astype(float) > df['open'].astype(float)).sum())
        if all(c in df.columns for c in ['low', 'close']):
            qc6_fail += int((df['low'].astype(float) > df['close'].astype(float)).sum())
        # close ∈ [low, high] (99%+ pass rate)
        if all(c in df.columns for c in ['close', 'low', 'high']):
            close_f = df['close'].astype(float)
            low_f = df['low'].astype(float)
            high_f = df['high'].astype(float)
            qc6_fail += int(((close_f < low_f) | (close_f > high_f)).sum())
        self.results.append({
            "qc_id": "QC-006", "name": "OHLC逻辑一致性",
            "status": "PASS" if qc6_fail == 0 else "FAIL",
            "failed_rows": qc6_fail
        })

        # ──────────────────────────────────────────────
        # QC-007: volume > 0
        # 状态：硬损伤 → FAIL
        # ──────────────────────────────────────────────
        vol_col = 'vol' if 'vol' in df.columns else 'volume'
        qc7_cnt = len(df[df[vol_col].astype(float) <= 0]) if vol_col in df.columns else 0
        self.results.append({
            "qc_id": "QC-007", "name": "volume>0",
            "status": "PASS" if qc7_cnt == 0 else "FAIL",
            "failed_rows": qc7_cnt
        })

        # ──────────────────────────────────────────────
        # QC-008: amount > 0
        # 状态：硬损伤 → FAIL
        # ──────────────────────────────────────────────
        qc8_cnt = len(df[df['amount'].astype(float) <= 0]) if 'amount' in df.columns else 0
        self.results.append({
            "qc_id": "QC-008", "name": "amount>0",
            "status": "PASS" if qc8_cnt == 0 else "FAIL",
            "failed_rows": qc8_cnt
        })

        # ──────────────────────────────────────────────
        # QC-009: close ∈ [0.01, 10000]
        # 状态：硬损伤 → FAIL
        # ──────────────────────────────────────────────
        qc9_cnt = 0
        if 'close' in df.columns:
            close_f = df['close'].astype(float)
            qc9_cnt = int(((close_f < 0.01) | (close_f > 10000)).sum())
        self.results.append({
            "qc_id": "QC-009", "name": "close∈[0.01,10000]",
            "status": "PASS" if qc9_cnt == 0 else "FAIL",
            "failed_rows": qc9_cnt
        })

        # ──────────────────────────────────────────────
        # QC-010: adj_factor 日变化率 < 50%
        # P0 阶段固定 50% 兜底，不阻断。
        # 状态：非阻断 → REPORT
        # ──────────────────────────────────────────────
        qc10_issues = []
        if 'adj_factor' in df.columns and len(df) >= 2:
            df_sorted = df.sort_values('trade_date').reset_index(drop=True)
            for i in range(1, len(df_sorted)):
                af_prev = float(df_sorted.iloc[i - 1]['adj_factor'])
                af_curr = float(df_sorted.iloc[i]['adj_factor'])
                if af_prev > 0:
                    change = abs(af_curr - af_prev) / af_prev
                    if change > 0.50:
                        qc10_issues.append(str(df_sorted.iloc[i]['trade_date']))
        self.results.append({
            "qc_id": "QC-010", "name": "adj_factor变化率<50%",
            "status": "REPORT" if len(qc10_issues) > 0 else "PASS",
            "failed_rows": len(qc10_issues),
            "issue_dates": qc10_issues[:10]
        })

        # ──────────────────────────────────────────────
        # QC-011: adj_factor 与除权除息日对齐（P1 阶段，P0 留空桩）
        # 状态：PASS（P1 实现）
        # ──────────────────────────────────────────────
        self.results.append({
            "qc_id": "QC-011", "name": "adj_factor与除权除息日对齐",
            "status": "PASS",
            "failed_rows": 0
        })

        # ──────────────────────────────────────────────
        # QC-012: 涨跌幅 ±20%（close vs pre_close）
        # 状态：非阻断 → REPORT
        # ──────────────────────────────────────────────
        qc12_gaps = []
        if all(c in df.columns for c in ['close', 'pre_close']):
            df_sorted = df.sort_values('trade_date')
            close_f = df_sorted['close'].astype(float)
            pre_close_f = df_sorted['pre_close'].astype(float)
            mask = (pre_close_f > 0) & ((close_f - pre_close_f).abs() / pre_close_f > 0.20)
            qc12_gaps = df_sorted[mask]['trade_date'].tolist()
        self.results.append({
            "qc_id": "QC-012", "name": "涨跌幅±20%",
            "status": "PASS" if len(qc12_gaps) == 0 else "REPORT",
            "failed_rows": len(qc12_gaps),
            "gap_dates": qc12_gaps[:10]
        })

        # ──────────────────────────────────────────────
        # QC-013: 成交量不超过 30 日均值 50 倍
        # 阈值：50x（与设计文档一致）
        # 状态：非阻断 → REPORT
        # ──────────────────────────────────────────────
        qc13_surge = []
        if vol_col in df.columns and len(df) >= 30:
            df_sorted = df.sort_values('trade_date')
            vol_f = df_sorted[vol_col].astype(float) * 100
            for i in range(29, len(df_sorted)):
                window = vol_f.iloc[i - 29:i + 1]
                current = vol_f.iloc[i]
                mean_prev = window.iloc[:-1].mean()
                if mean_prev > 0 and current > mean_prev * 50:
                    qc13_surge.append(str(df_sorted.iloc[i]['trade_date']))
        self.results.append({
            "qc_id": "QC-013", "name": "成交量≤50x均值",
            "status": "PASS" if len(qc13_surge) == 0 else "REPORT",
            "failed_rows": len(qc13_surge),
            "surge_dates": qc13_surge[:10]
        })

        # ═══════════════════════════════════════════════
        # 额外（非标准）检查 — 编号 QC-9xx
        # ═══════════════════════════════════════════════

        # QC-901: volume × close ≈ amount (2% tolerance, 99%+ pass rate)
        vol_amt_tol = self.config.get("volume_amount_tolerance", 0.02)
        qc901_fail = 0
        if all(c in df.columns for c in [vol_col, 'close', 'amount']):
            vol_norm = df[vol_col].astype(float) * 100
            amt_norm = df['amount'].astype(float) * 1000
            close_f = df['close'].astype(float)
            for i in range(len(df)):
                if amt_norm.iloc[i] > 0:
                    ratio = abs(vol_norm.iloc[i] * close_f.iloc[i] - amt_norm.iloc[i]) / amt_norm.iloc[i]
                    if ratio > vol_amt_tol:
                        qc901_fail += 1
        qc901_pass_rate = (len(df) - qc901_fail) / max(len(df), 1)
        self.results.append({
            "qc_id": "QC-901", "name": "vol×close≈amt",
            "status": "PASS" if qc901_pass_rate >= 0.99 else "REPORT",
            "failed_rows": qc901_fail
        })

        # QC-902: turnover_rate ∈ [0, 100]
        qc902_fail = 0
        if 'turnover_rate' in df.columns:
            tr = df['turnover_rate'].dropna()
            qc902_fail = len(tr[(tr < 0) | (tr > 100)])
        self.results.append({
            "qc_id": "QC-902", "name": "turnover_rate∈[0,100]",
            "status": "PASS" if qc902_fail == 0 else "REPORT",
            "failed_rows": qc902_fail
        })

        # QC-903: trade_date 格式 YYYYMMDD
        qc903_fail = 0
        if 'trade_date' in df.columns:
            for td in df['trade_date']:
                td_str = str(td)
                if not (len(td_str) == 8 and td_str.isdigit()):
                    qc903_fail += 1
                    continue
                y, m, d = int(td_str[:4]), int(td_str[4:6]), int(td_str[6:8])
                if not (1900 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31):
                    qc903_fail += 1
        self.results.append({
            "qc_id": "QC-903", "name": "trade_date格式",
            "status": "PASS" if qc903_fail == 0 else "REPORT",
            "failed_rows": qc903_fail
        })

        # ═══════════════════════════════════════════════
        # 综合 verdict
        # 有 FAIL → FAIL；无 FAIL 但有 REPORT → REPORT；全 PASS → PASS
        # ═══════════════════════════════════════════════
        has_fail = any(r["status"] == "FAIL" for r in self.results)
        has_report = any(r["status"] == "REPORT" for r in self.results)
        if has_fail:
            verdict = "FAIL"
        elif has_report:
            verdict = "REPORT"
        else:
            verdict = "PASS"

        return {"verdict": verdict, "rules": self.results}

    def results_summary(self) -> List[str]:
        return [f"{r['qc_id']}({r['name']}):{r['status']}" for r in self.results]


# ============================================================
# Stage 4: 审计日志表
# ============================================================
class AuditDB:
    """审计日志表管理：batch_audit / batch_audit_detail / staging_raw / backup"""

    STOCK_DAILY_COLS = [
        "ts_code", "trade_date", "open", "high", "low", "close",
        "pre_close", "change", "pct_chg", "volume", "amount",
        "turnover_rate", "turnover_rate_f", "volume_ratio",
        "pe", "pe_ttm", "pb", "total_share", "float_share",
        "free_float_share", "total_mv", "circ_mv",
        "adj_factor", "data_source", "version", "created_at"
    ]

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # stock_daily 主表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                ts_code      TEXT NOT NULL,
                trade_date   TEXT NOT NULL,
                open         REAL,
                high         REAL,
                low          REAL,
                close        REAL,
                pre_close    REAL,
                change       REAL,
                pct_chg      REAL,
                volume       INTEGER,
                amount       REAL,
                turnover_rate    REAL,
                turnover_rate_f  REAL,
                volume_ratio REAL,
                pe           REAL,
                pe_ttm       REAL,
                pb           REAL,
                total_share  REAL,
                float_share  REAL,
                free_float_share REAL,
                total_mv     REAL,
                circ_mv      REAL,
                adj_factor   REAL,
                data_source  TEXT NOT NULL DEFAULT 'tushare_pro',
                version      TEXT NOT NULL DEFAULT 'v1.0',
                created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (ts_code, trade_date)
            )
        """)

        # batch_audit 主表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS batch_audit (
                batch_id        TEXT PRIMARY KEY,
                e001_batch_id   TEXT,
                mode            TEXT NOT NULL DEFAULT 'UNKNOWN',
                symbol_count    INTEGER NOT NULL DEFAULT 0,
                rows_total      INTEGER NOT NULL DEFAULT 0,
                rows_inserted   INTEGER NOT NULL DEFAULT 0,
                rows_report     INTEGER NOT NULL DEFAULT 0,
                qc_verdict      TEXT NOT NULL DEFAULT 'PENDING',
                qc_summary      TEXT,
                started_at      TEXT,
                completed_at    TEXT,
                status          TEXT NOT NULL DEFAULT 'RUNNING',
                error           TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)

        # batch_audit_detail 明细表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS batch_audit_detail (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id        TEXT NOT NULL,
                ts_code         TEXT NOT NULL,
                rows_fetched    INTEGER NOT NULL DEFAULT 0,
                rows_written    INTEGER NOT NULL DEFAULT 0,
                rows_report     INTEGER NOT NULL DEFAULT 0,
                qc_verdict      TEXT NOT NULL,
                qc_details      TEXT,
                source_status   TEXT DEFAULT 'AVAILABLE',
                started_at      TEXT,
                completed_at    TEXT,
                error           TEXT,
                e001_batch_id   TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)

        # staging_raw 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staging_raw (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id        TEXT NOT NULL,
                ts_code         TEXT NOT NULL,
                trade_date      TEXT NOT NULL,
                raw_json        TEXT NOT NULL,
                qc_reason       TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                e001_batch_id   TEXT
            )
        """)

        # stock_daily_backup 备份表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily_backup (
                ts_code      TEXT NOT NULL,
                trade_date   TEXT NOT NULL,
                volume       INTEGER,
                amount       REAL,
                close        REAL,
                adj_factor   REAL,
                data_source  TEXT,
                version      TEXT,
                backup_batch_id TEXT,
                backed_up_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        conn.commit()
        conn.close()

    def create_batch(self, batch_id: str, mode: str, symbol_count: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT OR IGNORE INTO batch_audit
                (batch_id, mode, symbol_count, started_at, status)
                VALUES (?, ?, ?, datetime('now','localtime'), 'RUNNING')
            """, (batch_id, mode, symbol_count))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"create_batch failed: {e}")
            return False
        finally:
            conn.close()

    def update_batch(self, batch_id: str, **kwargs):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        sets = {k: v for k, v in kwargs.items() if v is not None}
        if not sets:
            return
        try:
            cur.execute("UPDATE batch_audit SET {sets}, completed_at=datetime('now','localtime') "
                        "WHERE batch_id=?".format(
                            sets=", ".join(f"{k}=?" for k in sets)),
                        list(sets.values()) + [batch_id])
            conn.commit()
        except Exception as e:
            logger.error(f"update_batch failed: {e}")
        finally:
            conn.close()

    # ────────────────────────────────────────────────────────
    # Fix 4: create_detail 接受可选 conn 参数
    # conn=None 时使用内部连接（保持向后兼容）
    # ────────────────────────────────────────────────────────
    def create_detail(self, batch_id: str, ts_code: str,
                      conn: Optional[sqlite3.Connection] = None, **kwargs) -> int:
        """创建审计明细记录。接受外部 conn 以参与主事务。"""
        if conn is not None:
            return self._create_detail_with_conn(conn, batch_id, ts_code, **kwargs)
        # 无外部 conn：使用内部连接（保持向后兼容）
        conn_inner = sqlite3.connect(self.db_path)
        try:
            return self._create_detail_with_conn(conn_inner, batch_id, ts_code, **kwargs)
        finally:
            conn_inner.close()

    def _create_detail_with_conn(self, conn: sqlite3.Connection,
                                  batch_id: str, ts_code: str, **kwargs) -> int:
        cur = conn.cursor()
        keys = list(kwargs.keys())
        try:
            cur.execute("""
                INSERT INTO batch_audit_detail
                (batch_id, ts_code, started_at, {keys})
                VALUES (?, ?, datetime('now','localtime'), {vals})
            """.format(keys=", ".join(keys), vals=", ".join(["?" for _ in keys])),
                        [batch_id, ts_code] + [kwargs[k] for k in keys])
            return cur.lastrowid or 0
        except Exception as e:
            logger.error(f"create_detail failed: {e}")
            return 0

    # ────────────────────────────────────────────────────────
    # Fix 4: write_staging_row 接受可选 conn 参数
    # ────────────────────────────────────────────────────────
    def write_staging_row(self, batch_id: str, ts_code: str, trade_date: str,
                           raw_json: str, qc_reason: str = "",
                           conn: Optional[sqlite3.Connection] = None):
        """写入 staging_raw。接受外部 conn 以参与主事务。"""
        if conn is not None:
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO staging_raw (batch_id, ts_code, trade_date, raw_json, qc_reason)
                    VALUES (?, ?, ?, ?, ?)
                """, (batch_id, ts_code, trade_date, raw_json, qc_reason))
            except Exception as e:
                logger.error(f"write_staging_row failed: {e}")
            return

        # 无外部 conn：使用内部连接
        conn_inner = sqlite3.connect(self.db_path)
        cur = conn_inner.cursor()
        try:
            cur.execute("""
                INSERT INTO staging_raw (batch_id, ts_code, trade_date, raw_json, qc_reason)
                VALUES (?, ?, ?, ?, ?)
            """, (batch_id, ts_code, trade_date, raw_json, qc_reason))
            conn_inner.commit()
        except Exception as e:
            logger.error(f"write_staging_row failed: {e}")
        finally:
            conn_inner.close()

    # ────────────────────────────────────────────────────────
    # Fix 3 + Fix 4:
    # backup_snapshot 接受可选 conn + ts_code 参数
    # 有 ts_code 时只备份该标的的数据（DELETE+INSERT 范围限制）
    # ────────────────────────────────────────────────────────
    def backup_snapshot(self, batch_id: str,
                         ts_code: Optional[str] = None,
                         conn: Optional[sqlite3.Connection] = None) -> bool:
        """备份指定标的（或全部）的数据到 stock_daily_backup。"""
        if conn is not None:
            return self._backup_with_conn(conn, batch_id, ts_code)
        # 无外部 conn：使用内部连接
        conn_inner = sqlite3.connect(self.db_path)
        try:
            result = self._backup_with_conn(conn_inner, batch_id, ts_code)
            conn_inner.commit()
            return result
        except Exception as e:
            logger.error(f"backup failed: {e}")
            return False
        finally:
            conn_inner.close()

    def _backup_with_conn(self, conn: sqlite3.Connection,
                           batch_id: str,
                           ts_code: Optional[str] = None) -> bool:
        cur = conn.cursor()
        try:
            if ts_code:
                # 标的级备份：先删除该标的的旧备份，再插入当前数据
                cur.execute("DELETE FROM stock_daily_backup WHERE ts_code=?", (ts_code,))
                cur.execute("""
                    INSERT INTO stock_daily_backup
                    (ts_code, trade_date, volume, amount, close,
                     adj_factor, data_source, version, backup_batch_id)
                    SELECT ts_code, trade_date, volume, amount, close,
                           adj_factor, data_source, version, ?
                    FROM stock_daily
                    WHERE ts_code=?
                """, (batch_id, ts_code))
                logger.info(f"  [BACKUP] {ts_code}: per-symbol backup done")
            else:
                # 全量备份：先清空，再全部插入
                cur.execute("DELETE FROM stock_daily_backup")
                cur.execute("""
                    INSERT INTO stock_daily_backup
                    (ts_code, trade_date, volume, amount, close,
                     adj_factor, data_source, version, backup_batch_id)
                    SELECT ts_code, trade_date, volume, amount, close,
                           adj_factor, data_source, version, ?
                    FROM stock_daily
                """, (batch_id,))
                logger.info(f"  [BACKUP] 全量备份完成")
            return True
        except Exception as e:
            logger.error(f"backup_snapshot failed: {e}")
            return False

    def write_many(self, conn: sqlite3.Connection, table: str, rows: List[dict]):
        """批量写入行字典列表到指定表"""
        if not rows:
            return
        cols = list(rows[0].keys())
        cur = conn.cursor()
        cur.executemany(
            f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join(['?' for _ in cols])})",
            [[r.get(c) for c in cols] for r in rows]
        )

    def batch_insert_stock_daily(self, conn: sqlite3.Connection, rows: List[dict]):
        """批量写入 stock_daily（事务内）"""
        if not rows:
            return
        # 只取 stock_daily 有的列
        cols = [c for c in self.STOCK_DAILY_COLS if c in rows[0]]
        cur = conn.cursor()
        cur.executemany(
            f"INSERT OR REPLACE INTO stock_daily ({','.join(cols)}) "
            f"VALUES ({','.join(['?' for _ in cols])})",
            [[r.get(c) for c in cols] for r in rows]
        )


# ============================================================
# DataNormalizer — 归一化层
# ============================================================
class DataNormalizer:
    """归一化：vol(手→股×100), amount(千元→元×1000), 标记版本"""

    VERSION = "v1.0"
    DATA_SOURCE = "tushare_pro"

    @classmethod
    def normalize(cls, df, ts_code: str) -> List[dict]:
        """将 Tushare daily DataFrame 归一化为行字典列表"""
        import pandas as pd
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        rows = []

        for _, row in df.iterrows():
            r = {}
            r["ts_code"] = ts_code
            r["trade_date"] = str(row.get("trade_date", ""))
            # 价格字段
            for price_col in ["open", "high", "low", "close", "pre_close", "change", "pct_chg"]:
                val = row.get(price_col)
                r[price_col] = float(val) if val is not None else None
            # 归一化 volume: 手→股
            vol_raw = row.get("vol")
            r["volume"] = int(float(vol_raw) * 100) if vol_raw is not None else None
            # 归一化 amount: 千元→元
            amt_raw = row.get("amount")
            r["amount"] = float(amt_raw) * 1000 if amt_raw is not None else None
            # 可选字段
            for opt_col in ["turnover_rate", "turnover_rate_f", "volume_ratio",
                            "pe", "pe_ttm", "pb", "total_share", "float_share",
                            "free_float_share", "total_mv", "circ_mv"]:
                val = row.get(opt_col)
                r[opt_col] = float(val) if val is not None else None
            # adj_factor 字段
            af_val = row.get("adj_factor")
            if af_val is not None:
                r["adj_factor"] = float(af_val)
            # 标记
            r["data_source"] = cls.DATA_SOURCE
            r["version"] = cls.VERSION
            r["created_at"] = now
            rows.append(r)
        return rows


# ============================================================
# UnifiedIngestionPipeline — 统一灌入主程序
# ============================================================
class UnifiedIngestionPipeline:
    """
    五步灌入流水线：
    1. 初始化（配置 + DB 表）
    2. 数据获取（Tushare API + 限流）
    3. QC 校验（13 条规则）
    4. Staging 原子写入（主表 / staging_raw）
    5. 审计日志写入
    """

    def __init__(self, db_path: str = str(DB_PATH),
                 config_path: str = str(CONFIG_PATH),
                 mode: str = "INCREMENTAL",
                 dry_run: bool = False):
        self.db_path = db_path
        self.config_path = config_path
        self.mode = mode
        self.dry_run = dry_run

        self.registry = SymbolRegistry(config_path)
        self.limiter = TushareRateLimiter(self.registry.get_tushare_config())
        self.audit = AuditDB(db_path)
        self.qc_engine = QCEngine(self.registry.get_qc_config())

        self.batch_id = ""
        self.results: List[dict] = []
        self.total_inserted = 0
        self.total_report = 0
        self.start_time = 0.0

    def _gen_batch_id(self) -> str:
        return f"E002_BATCH_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}"

    def _get_date_range(self, symbol: dict) -> Tuple[str, str]:
        start = symbol.get("start_date", "2020-01-01").replace("-", "")
        end = datetime.now(TZ).strftime("%Y%m%d")
        if self.mode == "FULL_RELOAD":
            return start, end
        # INCREMENTAL
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT MAX(trade_date) FROM stock_daily WHERE ts_code=?", (symbol["ts_code"],))
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                last_dt = datetime.strptime(str(row[0]), "%Y%m%d")
                start = (last_dt + timedelta(days=1)).strftime("%Y%m%d")
        except Exception:
            pass
        return start, end

    def run(self, symbols: Optional[List[dict]] = None) -> dict:
        self.start_time = time.time()
        self.batch_id = self._gen_batch_id()
        self.results = []
        self.total_inserted = 0
        self.total_report = 0

        # Step 1: Init
        logger.info(f"[STEP 1/5] Init — mode={self.mode}, db={self.db_path}")
        if not self.dry_run:
            self.audit._init_tables()

        target = symbols or self.registry.get_active_symbols()
        # Dedup
        seen: Set[str] = set()
        unique = []
        for s in target:
            if s["ts_code"] not in seen:
                seen.add(s["ts_code"])
                unique.append(s)
        logger.info(f"[STEP 1/5] {len(unique)} symbols to process")

        if not self.dry_run:
            self.audit.create_batch(self.batch_id, self.mode, len(unique))

        # Step 2-4: Per symbol
        for idx, sym in enumerate(unique):
            ts_code = sym["ts_code"]
            logger.info(f"[{idx+1}/{len(unique)}] {ts_code} ({sym.get('name','')})")

            # Get date range
            start_d, end_d = self._get_date_range(sym)
            logger.info(f"  [STEP 2] Fetch: {ts_code} [{start_d}→{end_d}]")

            # Check source
            if self.limiter.get_source_status(ts_code) != "AVAILABLE":
                self.results.append({"ts_code": ts_code, "name": sym.get("name"), "status": "SKIPPED", "reason": "SOURCE_UNAVAILABLE"})
                continue

            # Fetch daily data
            df = self.limiter.fetch_daily(
                ts_code=ts_code, start_date=start_d, end_date=end_d,
                fields=sym.get("fields") or None)
            if df is None or len(df) == 0:
                self.results.append({"ts_code": ts_code, "name": sym.get("name"), "status": "NO_DATA"})
                continue
            rows_fetched = len(df)
            logger.info(f"  [STEP 2] Got {rows_fetched} rows from daily API")

            # Fetch adj_factor separately for stock types
            # (index types skip adj_factor — adj_method='none', adj_factor=NULL)
            if sym.get("type") == "stock":
                adj_df = self.limiter.fetch_adj_factor(
                    ts_code=ts_code, start_date=start_d, end_date=end_d)
                if adj_df is not None and not adj_df.empty:
                    logger.info(f"  [STEP 2] Got {len(adj_df)} adj_factor rows from adj_factor API")
                    import pandas as pd
                    # Ensure both have the same ts_code representation for merge
                    df["ts_code"] = df["ts_code"].astype(str)
                    adj_df["ts_code"] = adj_df["ts_code"].astype(str)
                    adj_df["trade_date"] = adj_df["trade_date"].astype(str)
                    # Left merge adj_factor onto daily data
                    df = df.merge(
                        adj_df[["ts_code", "trade_date", "adj_factor"]],
                        on=["ts_code", "trade_date"],
                        how="left"
                    )
                    merged_count = int(df["adj_factor"].notna().sum())
                    logger.info(f"  [STEP 2] Merged adj_factor: {merged_count}/{rows_fetched} rows matched")
                else:
                    logger.warning(f"  [STEP 2] adj_factor API returned no data for {ts_code}, will stay NULL")
            else:
                # Index type: adj_factor stays NULL (not fetched)
                logger.info(f"  [STEP 2] {ts_code} is index type, adj_factor skipped")

            # Step 3: QC
            logger.info(f"  [STEP 3] QC check...")
            qc_result = self.qc_engine.run_all(df)
            logger.info(f"  QC verdict={qc_result['verdict']}")

            # Step 4: Normalize + Write
            norm_rows = DataNormalizer.normalize(df, ts_code)

            if self.dry_run:
                self.results.append({
                    "ts_code": ts_code, "name": sym.get("name"),
                    "status": "DRY_RUN", "rows": rows_fetched,
                    "qc_verdict": qc_result["verdict"],
                    "qc_summary": ";".join(self.qc_engine.results_summary())
                })
                continue

            self._atomic_write(ts_code, norm_rows, qc_result, sym.get("name", ts_code), rows_fetched)

        # Step 5: Finalize
        elapsed = time.time() - self.start_time
        if not self.dry_run:
            qc_verdicts = [r.get("qc_verdict", "PASS") for r in self.results if "qc_verdict" in r]
            final_verdict = max(qc_verdicts) if qc_verdicts else "PASS"
            has_errors = any(r.get("status") in ("FAILED", "SOURCE_UNAVAILABLE") for r in self.results)
            self.audit.update_batch(
                self.batch_id,
                rows_total=sum(r.get("rows", 0) for r in self.results),
                rows_inserted=self.total_inserted,
                rows_report=self.total_report,
                qc_verdict=final_verdict,
                status="COMPLETED_WITH_ERRORS" if has_errors else "COMPLETED",
            )

        summary = {
            "batch_id": self.batch_id,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "symbols_processed": len(self.results),
            "total_rows_fetched": sum(r.get("rows", 0) for r in self.results),
            "total_inserted": self.total_inserted,
            "total_report": self.total_report,
            "elapsed_seconds": round(elapsed, 2),
            "results": self.results,
        }

        logger.info(f"[DONE] batch={self.batch_id} inserted={self.total_inserted} "
                     f"report={self.total_report} elapsed={elapsed:.1f}s")
        return summary

    # ────────────────────────────────────────────────────────────
    # _atomic_write — 重构版本（Fix 2 + Fix 3 + Fix 4）
    #
    # 单事务内完成所有操作（backup + 主表写入 + staging_raw + 审计明细）
    # 按 verdict 分叉：
    #   PASS   → 正常写入 stock_daily 主表
    #   REPORT → 写入 stock_daily 主表 + staging_raw
    #   FAIL   → 仅写入 staging_raw，不写主表
    #
    # Fix 3: 每个标的写入前先备份该标的现有数据
    # Fix 4: 所有 AuditDB 操作共享同一 conn，参与同一事务
    # ────────────────────────────────────────────────────────────
    def _atomic_write(self, ts_code: str, norm_rows: List[dict],
                       qc_result: dict, name: str, rows_fetched: int):
        """批次级原子写入：事务内写入全部行，失败回滚"""
        conn = sqlite3.connect(self.db_path)
        inserted = 0
        report_count = 0
        error = None

        try:
            verdict = qc_result["verdict"]

            # Fix 3: 每个标的写入前先备份该标的现有数据
            self.audit.backup_snapshot(self.batch_id, ts_code=ts_code, conn=conn)

            # 按 verdict 分叉写入路径
            if verdict == "FAIL":
                # FAIL: 仅写入 staging_raw，不写主表
                for row in norm_rows:
                    self.audit.write_staging_row(
                        self.batch_id, ts_code, row["trade_date"],
                        json.dumps(row, default=str, ensure_ascii=False),
                        qc_reason=f"FAIL({verdict})",
                        conn=conn)
                    report_count += 1
                self.total_report += report_count
                inserted = 0
                logger.info(f"  [STEP 4] FAIL: {len(norm_rows)} rows→staging_raw only")

            elif verdict == "REPORT":
                # REPORT: 写入主表 + staging_raw
                self.audit.batch_insert_stock_daily(conn, norm_rows)
                inserted = len(norm_rows)
                self.total_inserted += inserted

                for rule in qc_result.get("rules", []):
                    if rule["status"] == "REPORT":
                        for row in norm_rows:
                            self.audit.write_staging_row(
                                self.batch_id, ts_code, row["trade_date"],
                                json.dumps(row, default=str, ensure_ascii=False),
                                qc_reason=rule["qc_id"],
                                conn=conn)
                            report_count += 1
                self.total_report += report_count
                logger.info(f"  [STEP 4] REPORT: {inserted} rows→main + {report_count} staging")

            else:  # PASS
                # PASS: 正常写入主表
                self.audit.batch_insert_stock_daily(conn, norm_rows)
                inserted = len(norm_rows)
                self.total_inserted += inserted
                logger.info(f"  [STEP 4] PASS: {inserted} rows→main")

            # Fix 4: 审计明细在事务内写入（共享 conn）
            self.audit.create_detail(
                self.batch_id, ts_code,
                rows_fetched=rows_fetched, rows_written=inserted,
                rows_report=report_count,
                qc_verdict=verdict,
                qc_details=json.dumps(qc_result, default=str, ensure_ascii=False),
                source_status="AVAILABLE",
                conn=conn)

            # 提交事务
            conn.commit()
            status = "SUCCESS"

        except Exception as e:
            conn.rollback()
            error = str(e)
            status = "FAILED"
            logger.error(f"  [STEP 4] WRITE FAILED: {error}")
            # 错误时在独立连接中写入错误审计（事务已回滚）
            self.audit.create_detail(
                self.batch_id, ts_code,
                rows_fetched=rows_fetched, rows_written=0,
                rows_report=0,
                qc_verdict="FAIL",
                qc_details=json.dumps(qc_result, default=str, ensure_ascii=False),
                source_status="ERROR", error=error)
        finally:
            conn.close()

        self.results.append({
            "ts_code": ts_code, "name": name, "status": status,
            "rows": rows_fetched, "inserted": inserted,
            "qc_verdict": qc_result["verdict"],
        })


# ============================================================
# CLI Entry Point
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="E-002 统一股票日线灌入程序")
    parser.add_argument("--mode", default="INCREMENTAL", choices=["FULL_RELOAD", "INCREMENTAL"])
    parser.add_argument("--symbol", type=str, default="", help="指定单标的 (如 601857.SH)")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run 模式")
    parser.add_argument("--db-path", type=str, default=str(DB_PATH))
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    return parser.parse_args()


def main():
    args = parse_args()
    logger.info(f"=== E-002 unified_ingestion ===")
    logger.info(f"Mode={args.mode} Dry-run={args.dry_run} DB={args.db_path}")

    pp = UnifiedIngestionPipeline(
        db_path=args.db_path, config_path=args.config_path,
        mode=args.mode, dry_run=args.dry_run)

    symbols = None
    if args.symbol:
        sym = pp.registry.get_symbol(args.symbol)
        if not sym:
            logger.error(f"Symbol not found: {args.symbol}")
            return 1
        symbols = [sym]

    summary = pp.run(symbols)

    print(f"\n{'='*60}")
    print(f"  E-002 Ingestion Summary")
    print(f"  Batch: {summary['batch_id']}")
    print(f"  Mode:  {summary['mode']}  Dry-run: {summary['dry_run']}")
    print(f"  Symbols: {summary['symbols_processed']}")
    print(f"  Rows: {summary['total_rows_fetched']} fetched, "
          f"{summary['total_inserted']} inserted, "
          f"{summary['total_report']} staged")
    print(f"  Elapsed: {summary['elapsed_seconds']:.1f}s")
    print(f"{'='*60}")

    for r in summary["results"]:
        icon = {"SUCCESS": "✅", "DRY_RUN": "💡", "NO_DATA": "⚠️",
                "SKIPPED": "🔇", "FAILED": "❌"}.get(r["status"], "❓")
        print(f"  {icon} {r.get('ts_code','?')}: {r['status']}  rows={r.get('rows',0)}" +
              (f"  inserted={r.get('inserted',0)}" if "inserted" in r else "") +
              (f"  qc={r.get('qc_verdict','')}" if "qc_verdict" in r else ""))

    return 0


if __name__ == "__main__":
    sys.exit(main())
