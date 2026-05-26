"""
墨枢 - False Breakout Profile（Phase 1-B）

假突破画像模块。提供：
  - BreakoutEventDB — breakout_events 数据库管理（B1）
  - BreakoutFeatureExtractor — 假突破特征提取（B2）
  - BreakoutScoringCard — 真假突破评分卡（B3）
  - generate_breakout_report — 假突破报告生成（B4）

设计参考：
  - report_upgrade_v2_design.md §2.5
  - backtest_report_20260518_research_v2.md §17

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── 系统路径 ──────────────────────────────────────────────────

MOZHI_BASE = Path(r"C:\Users\17699\mozhi_platform")

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════


@dataclass
class BreakoutEvent:
    """突破事件数据模型。"""
    breakout_id: str
    batch_id: str
    timestamp: str
    symbol: str
    price: float
    volume: float
    direction: str  # 'up', 'down'
    # 特征
    volume_ratio: float
    vwap_deviation: float
    regime: str
    trend_quality: float
    volume_ratio_20: float
    atr_value: float
    atr_expansion: float
    obv_value: float
    obv_change: float
    breakout_persistence: int
    # 判定
    is_false_breakout: bool
    breakout_score: float
    confidence: float  # 评分卡置信度
    # 原始特征（JSON 保存）
    features_json: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def to_db_row(self) -> Tuple:
        return (
            self.breakout_id, self.batch_id, self.timestamp, self.symbol,
            self.price, self.volume, self.direction,
            self.volume_ratio, self.vwap_deviation,
            self.regime, self.trend_quality,
            self.volume_ratio_20, self.atr_value, self.atr_expansion,
            self.obv_value, self.obv_change,
            self.breakout_persistence,
            1 if self.is_false_breakout else 0,
            self.breakout_score, self.confidence,
            self.features_json,
        )


@dataclass
class FeatureSet:
    """单次突破事件的特征向量。"""
    volume_ratio: float = 0.0        # 成交量放大倍数（突破日/前20日均量）
    vwap_deviation: float = 0.0      # 相对于 VWAP 的偏离度（%）
    regime_at_breakout: str = ""     # 突破时的市场状态
    trend_quality: float = 0.0       # 趋势质量 [0, 1]
    volume_ratio_20: float = 0.0     # 20 日量比
    atr_value: float = 0.0           # ATR 值
    atr_expansion: float = 0.0       # ATR 扩张率（突破日ATR/前20日均ATR）
    obv_value: float = 0.0           # OBV 值
    obv_change: float = 0.0          # OBV 变化方向 (-1, 0, 1)
    breakout_persistence: int = 0    # 突破后续持续日数
    price: float = 0.0               # 突破价格
    volume: float = 0.0              # 突破日成交量

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 评分卡常量 — 权重与阈值（参照设计文档 §2.5）
# ═══════════════════════════════════════════════════════════════

SCORECARD_WEIGHTS = {
    "volume_signal": 0.35,       # 成交量信号权重
    "vwap_deviation": 0.20,      # VWAP 偏离权重
    "regime_alignment": 0.25,    # 市场状态对齐权重
    "persistence": 0.20,         # 持续性权重
}

SCORECARD_THRESHOLDS = {
    "true_breakout": 0.60,       # ≥0.60 → 真突破
    "uncertain_high": 0.40,      # 0.40~0.60 → 待观察/不确定
    "false_breakout": 0.40,      # <0.40 → 假突破
}

# ═══════════════════════════════════════════════════════════════
# B1: BreakoutEventDB — 数据库管理
# ═══════════════════════════════════════════════════════════════


class BreakoutEventDB:
    """breakout_events 数据库管理。

    SQLite 数据库，存储在 data/signals/breakout_events.db。
    支持批量写入、WAL 模式。

    表结构:
        breakout_events (
            breakout_id      TEXT PRIMARY KEY,
            batch_id         TEXT,
            timestamp        TEXT NOT NULL,
            symbol           TEXT NOT NULL,
            price            REAL NOT NULL,
            volume           REAL,
            direction        TEXT,
            volume_ratio     REAL,
            vwap_deviation   REAL,
            regime           TEXT,
            trend_quality    REAL,
            volume_ratio_20  REAL,
            atr_value        REAL,
            atr_expansion    REAL,
            obv_value        REAL,
            obv_change       REAL,
            breakout_persistence INTEGER,
            is_false_breakout    INTEGER,
            breakout_score       REAL,
            confidence           REAL,
            features_json        TEXT,
            created_at           TEXT DEFAULT (datetime('now'))
        );
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(MOZHI_BASE / "data" / "signals" / "breakout_events.db")
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
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
            CREATE TABLE IF NOT EXISTS breakout_events (
                breakout_id         TEXT PRIMARY KEY,
                batch_id            TEXT,
                timestamp           TEXT NOT NULL,
                symbol              TEXT NOT NULL,
                price               REAL NOT NULL,
                volume              REAL,
                direction           TEXT,
                volume_ratio        REAL,
                vwap_deviation      REAL,
                regime              TEXT,
                trend_quality       REAL,
                volume_ratio_20     REAL,
                atr_value           REAL,
                atr_expansion       REAL,
                obv_value           REAL,
                obv_change          REAL,
                breakout_persistence INTEGER,
                is_false_breakout   INTEGER,
                breakout_score      REAL,
                confidence          REAL,
                features_json       TEXT,
                created_at          TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_bo_batch ON breakout_events(batch_id);
            CREATE INDEX IF NOT EXISTS idx_bo_symbol ON breakout_events(symbol);
            CREATE INDEX IF NOT EXISTS idx_bo_timestamp ON breakout_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_bo_label ON breakout_events(is_false_breakout);
        """)
        conn.commit()

    def insert_breakout(self, event: BreakoutEvent) -> None:
        """单条插入。"""
        conn = self._ensure_conn()
        conn.execute("""
            INSERT OR REPLACE INTO breakout_events
                (breakout_id, batch_id, timestamp, symbol,
                 price, volume, direction,
                 volume_ratio, vwap_deviation,
                 regime, trend_quality, volume_ratio_20,
                 atr_value, atr_expansion,
                 obv_value, obv_change,
                 breakout_persistence,
                 is_false_breakout, breakout_score, confidence,
                 features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?,
                    ?, ?, ?, ?)
        """, event.to_db_row())
        conn.commit()

    def insert_batch(self, events: List[BreakoutEvent]) -> None:
        """批量插入。"""
        if not events:
            return
        conn = self._ensure_conn()
        rows = [e.to_db_row() for e in events]
        conn.executemany("""
            INSERT OR REPLACE INTO breakout_events
                (breakout_id, batch_id, timestamp, symbol,
                 price, volume, direction,
                 volume_ratio, vwap_deviation,
                 regime, trend_quality, volume_ratio_20,
                 atr_value, atr_expansion,
                 obv_value, obv_change,
                 breakout_persistence,
                 is_false_breakout, breakout_score, confidence,
                 features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?,
                    ?, ?, ?, ?)
        """, rows)
        conn.commit()

    def query_breakouts(self, batch_id: Optional[str] = None,
                        symbol: Optional[str] = None,
                        label: Optional[bool] = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
        """查询突破事件。"""
        conn = self._ensure_conn()
        conditions, params = [], []
        if batch_id:
            conditions.append("batch_id = ?"); params.append(batch_id)
        if symbol:
            conditions.append("symbol = ?"); params.append(symbol)
        if label is not None:
            conditions.append("is_false_breakout = ?"); params.append(1 if label else 0)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        cursor = conn.execute(
            f"SELECT * FROM breakout_events {where} ORDER BY timestamp LIMIT ?",
            params + [limit]
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]

    def count_breakouts(self, batch_id: Optional[str] = None,
                        label: Optional[bool] = None) -> int:
        """统计突破事件数量。"""
        conn = self._ensure_conn()
        conditions, params = [], []
        if batch_id:
            conditions.append("batch_id = ?"); params.append(batch_id)
        if label is not None:
            conditions.append("is_false_breakout = ?"); params.append(1 if label else 0)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return conn.execute(
            f"SELECT COUNT(*) FROM breakout_events {where}", params
        ).fetchone()[0]

    def get_summary_stats(self, batch_id: Optional[str] = None) -> Dict[str, Any]:
        """获取突破事件汇总统计。"""
        conn = self._ensure_conn()
        cond = "WHERE batch_id = ?" if batch_id else ""
        params = [batch_id] if batch_id else []
        row = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_false_breakout=0 THEN 1 ELSE 0 END) as true_count,
                SUM(CASE WHEN is_false_breakout=1 THEN 1 ELSE 0 END) as false_count,
                AVG(breakout_score) as avg_score,
                AVG(volume_ratio) as avg_vol_ratio,
                AVG(vwap_deviation) as avg_vwap_dev,
                AVG(breakout_persistence) as avg_persistence
            FROM breakout_events {cond}
        """, params).fetchone()

        if not row or row[0] == 0:
            return {"total": 0}

        total = row[0]
        true_cnt = row[1] or 0
        false_cnt = row[2] or 0
        return {
            "total": total,
            "true_breakout_count": true_cnt,
            "false_breakout_count": false_cnt,
            "true_ratio": round(true_cnt / total * 100, 1),
            "false_ratio": round(false_cnt / total * 100, 1),
            "avg_score": round(row[3] or 0.0, 4),
            "avg_vol_ratio": round(row[4] or 0.0, 4),
            "avg_vwap_dev": round(row[5] or 0.0, 4),
            "avg_persistence": round(row[6] or 0.0, 2),
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def db_path(self) -> str:
        return self._db_path


# ═══════════════════════════════════════════════════════════════
# B2: BreakoutFeatureExtractor — 假突破特征提取
# ═══════════════════════════════════════════════════════════════


class BreakoutFeatureExtractor:
    """假突破特征提取器。

    从 bar 数据中提取假突破相关特征，使用已有因子模块
    (ATRFactor, VwapFactor, VolumeRatioFactor, OBVFactor, RegimeFactor)。

    Usage:
        extractor = BreakoutFeatureExtractor()
        features = extractor.extract_all(df, breakout_idx=42)

    或批量提取:
        all_features = extractor.batch_extract(df, breakout_indices=[10, 25, 42])
    """

    def __init__(self):
        # 延迟导入因子模块（避免循环依赖）
        from backtest.factors.volume.volume_ratio_factor import VolumeRatioFactor
        from backtest.factors.volume.vwap_factor import VwapFactor, calc_vwap_deviation
        from backtest.factors.volatility.atr_factor import ATRFactor
        from backtest.factors.volume.obv_factor import OBVFactor
        from backtest.factors.regime.regime_factor import classify_regime
        from backtest.factors.trend.trend_quality_factor import calc_adx, calc_trend_strength

        self.VolumeRatioFactor = VolumeRatioFactor
        self.VwapFactor = VwapFactor
        self.calc_vwap_deviation = calc_vwap_deviation
        self.ATRFactor = ATRFactor
        self.OBVFactor = OBVFactor
        self.classify_regime = classify_regime
        self.calc_adx = calc_adx
        self.calc_trend_strength = calc_trend_strength

        # 缓存的因子值
        self._cached_features: Dict[str, pd.DataFrame] = {}

    def precompute_factors(self, df: pd.DataFrame) -> None:
        """预计算所有因子，避免重复计算。

        Args:
            df: 标准 OHLCV DataFrame（含 open, high, low, close, volume）。
        """
        # ATR
        atr_result = self.ATRFactor(params={"period": 14, "use_ema": True}).compute(df)
        self._cached_features["atr"] = atr_result

        # VWAP
        vwap_result = self.VwapFactor.compute(df)
        self._cached_features["vwap"] = vwap_result

        # VWAP 偏离度
        vwap_dev = self.calc_vwap_deviation(df)
        self._cached_features["vwap_deviation"] = vwap_dev

        # 量比
        vr_result = self.VolumeRatioFactor(params={"windows": [5, 20]}).compute(df)
        self._cached_features["volume_ratio"] = vr_result

        # OBV
        obv_result = self.OBVFactor(params={"signal_period": 20, "ma_type": "sma"}).compute(df)
        self._cached_features["obv"] = obv_result

        # ADX / 趋势强度
        adx = self.calc_adx(df)
        ts = self.calc_trend_strength(adx)
        self._cached_features["adx"] = adx
        self._cached_features["trend_strength"] = ts

        # ATR 20日均值（用于扩张率）
        atr_ma20 = atr_result["atr"].rolling(20, min_periods=5).mean()
        self._cached_features["atr_ma20"] = atr_ma20

        # OBV 变化率
        obv = obv_result["obv"]
        obv_change = obv.diff().fillna(0)
        self._cached_features["obv_delta"] = obv_change

        # OBV 方向 (1=上升, -1=下降, 0=不变)
        obv_direction = pd.Series(0, index=df.index)
        obv_direction[obv_change > 0] = 1
        obv_direction[obv_change < 0] = -1
        self._cached_features["obv_direction"] = obv_direction

    def extract_at(self, df: pd.DataFrame, idx: int) -> FeatureSet:
        """提取指定索引处的特征。

        Args:
            df: OHLCV DataFrame。
            idx: 突破事件对应的行索引。

        Returns:
            FeatureSet: 特征向量。
        """
        if not self._cached_features:
            self.precompute_factors(df)

        n = len(df)
        fs = FeatureSet()

        # 基础数据
        fs.price = float(df.iloc[idx]["close"])
        fs.volume = float(df.iloc[idx]["volume"])

        # 量比
        vr_col = self._cached_features["volume_ratio"]
        fs.volume_ratio = float(vr_col.iloc[idx].get("volume_ratio_5", np.nan) or 0)
        fs.volume_ratio_20 = float(vr_col.iloc[idx].get("volume_ratio_20", np.nan) or 0)

        # VWAP 偏离 — 取突破后 3 日均值（参照设计文档 §2.5）
        vwap_dev = self._cached_features["vwap_deviation"]
        end_idx = min(idx + 3, n - 1)
        post_break_devs = vwap_dev.iloc[idx:end_idx + 1].dropna()
        fs.vwap_deviation = float(post_break_devs.mean()) if len(post_break_devs) > 0 else 0.0

        # 市场状态 — 取突破日的 regime
        regime_result = self.classify_regime(df.iloc[:idx + 1])
        fs.regime_at_breakout = regime_result.get("regime", "UNKNOWN")

        # 趋势质量
        ts = self._cached_features.get("trend_strength")
        if ts is not None and idx < len(ts):
            fs.trend_quality = float(ts.iloc[idx]) if pd.notna(ts.iloc[idx]) else 0.0

        # ATR 值 + ATR 扩张率
        atr_df = self._cached_features["atr"]
        atr_ma20 = self._cached_features["atr_ma20"]
        fs.atr_value = float(atr_df.iloc[idx]["atr"]) if pd.notna(atr_df.iloc[idx]["atr"]) else 0.0
        ma20_val = float(atr_ma20.iloc[idx]) if pd.notna(atr_ma20.iloc[idx]) else 1.0
        fs.atr_expansion = (fs.atr_value / ma20_val) if ma20_val > 0 else 1.0

        # OBV
        obv_df = self._cached_features["obv"]
        fs.obv_value = float(obv_df.iloc[idx]["obv"]) if pd.notna(obv_df.iloc[idx]["obv"]) else 0.0

        obv_dir = self._cached_features.get("obv_direction")
        if obv_dir is not None and idx < len(obv_dir):
            fs.obv_change = float(obv_dir.iloc[idx])

        # 突破持续性 — 从突破日向前找持续同向的天数（穿透回调不算反转）
        # 简化版：统计突破日后收盘价持续不低于突破价的连续天数
        fs.breakout_persistence = self._calc_persistence(df, idx)

        return fs

    def extract_batch(self, df: pd.DataFrame, indices: List[int]) -> List[FeatureSet]:
        """批量提取特征。

        Args:
            df: OHLCV DataFrame。
            indices: 突破事件索引列表。

        Returns:
            List[FeatureSet]: 特征向量列表。
        """
        self.precompute_factors(df)
        return [self.extract_at(df, i) for i in indices]

    def _calc_persistence(self, df: pd.DataFrame, idx: int) -> int:
        """计算突破后续持续日数。

        从 idx 日开始，统计后续连续满足"收盘价 >= 突破价"的日数。
        """
        if idx >= len(df) - 1:
            return 0
        break_price = float(df.iloc[idx]["close"])
        persistence = 0
        for i in range(idx + 1, len(df)):
            if df.iloc[i]["close"] >= break_price * 0.995:  # 允许 0.5% 的回调容差
                persistence += 1
            else:
                break
        return persistence


# ═══════════════════════════════════════════════════════════════
# B3: BreakoutScoringCard — 真假突破评分卡
# ═══════════════════════════════════════════════════════════════


class BreakoutScoringCard:
    """真假突破评分卡。

    基于加权特征组合的输出真假突破分类。

    公式:
        真突破置信度 = 0.35×VolumeSignal + 0.20×VWAPDeviation
                      + 0.25×RegimeAlignment + 0.20×Persistence

    阈值:
        > 0.60 → 真突破
        0.40~0.60 → 待观察/不确定
        < 0.40 → 假突破

    Usage:
        card = BreakoutScoringCard()
        result = card.score(features)
        # result = {"score": 0.72, "classification": "true_breakout"}
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None,
                 thresholds: Optional[Dict[str, float]] = None):
        self.weights = weights or SCORECARD_WEIGHTS
        self.thresholds = thresholds or SCORECARD_THRESHOLDS

    def score(self, features: FeatureSet) -> Dict[str, Any]:
        """对单个特征向量评分。

        Args:
            features: 特征向量。

        Returns:
            Dict with keys:
                - score: 综合评分 [0, 1]
                - classification: str ("true_breakout" | "uncertain" | "false_breakout")
                - components: Dict[str, float] 各分量分数
                - confidence: float 置信度 [0, 1]
        """
        components = {}

        # 1. VolumeSignal — 成交量信号 (0~1)
        components["volume_signal"] = self._score_volume_signal(features)

        # 2. VWAPDeviation — VWAP 偏离 (0~1)
        components["vwap_deviation"] = self._score_vwap_deviation(features)

        # 3. RegimeAlignment — 市场状态对齐 (0~1)
        components["regime_alignment"] = self._score_regime_alignment(features)

        # 4. Persistence — 持续日数 (0~1)
        components["persistence"] = self._score_persistence(features)

        # 加权综合
        score = sum(
            self.weights[k] * components[k]
            for k in components
        )

        # 分类
        if score >= self.thresholds["true_breakout"]:
            classification = "true_breakout"
        elif score >= self.thresholds["uncertain_high"]:
            classification = "uncertain"
        else:
            classification = "false_breakout"

        # 置信度 — 距离最近阈值的距离映射到 [0, 1]
        confidence = self._calc_confidence(score, classification)

        return {
            "score": round(score, 4),
            "classification": classification,
            "components": {k: round(v, 4) for k, v in components.items()},
            "confidence": round(confidence, 4),
            "is_false_breakout": classification == "false_breakout",
        }

    def batch_score(self, features_list: List[FeatureSet]) -> List[Dict[str, Any]]:
        """批量评分。

        Args:
            features_list: 特征向量列表。

        Returns:
            List[Dict]: 评分结果列表。
        """
        return [self.score(f) for f in features_list]

    def _score_volume_signal(self, features: FeatureSet) -> float:
        """成交量信号评分。

        真突破特征：volume_ratio_20 > 1.5（明显放量）
        假突破特征：volume_ratio_20 ~ 1.0（无明显放量）
        """
        vr = features.volume_ratio_20
        if pd.isna(vr) or vr <= 0:
            return 0.0
        # vr >= 2.0 → 1.0, vr = 1.0 → 0.3, vr <= 0.7 → 0.0
        if vr >= 2.0:
            return 1.0
        elif vr >= 1.5:
            return 0.7 + (vr - 1.5) / 0.5 * 0.3  # 0.7 ~ 1.0
        elif vr >= 1.0:
            return 0.3 + (vr - 1.0) / 0.5 * 0.4  # 0.3 ~ 0.7
        elif vr >= 0.7:
            return 0.0 + (vr - 0.7) / 0.3 * 0.3  # 0.0 ~ 0.3
        else:
            return 0.0

    def _score_vwap_deviation(self, features: FeatureSet) -> float:
        """VWAP 偏离度评分。

        真突破特征：持续正向偏离（>+3%）
        假突破特征：偏离度小（<±1%）
        """
        dev = features.vwap_deviation
        if pd.isna(dev):
            return 0.0
        abs_dev = abs(dev)
        # 方向: 正向偏离才是真突破信号
        directional_factor = 1.0 if dev > 0 else 0.3
        # 幅度
        if abs_dev >= 5.0:
            amp_factor = 1.0
        elif abs_dev >= 3.0:
            amp_factor = 0.7 + (abs_dev - 3.0) / 2.0 * 0.3
        elif abs_dev >= 1.0:
            amp_factor = 0.3 + (abs_dev - 1.0) / 2.0 * 0.4
        elif abs_dev >= 0.5:
            amp_factor = 0.1 + (abs_dev - 0.5) / 0.5 * 0.2
        else:
            amp_factor = 0.0

        return directional_factor * amp_factor

    def _score_regime_alignment(self, features: FeatureSet) -> float:
        """市场状态对齐评分。

        真突破特征：TREND_UP 或 BREAKOUT
        假突破特征：RANGE
        """
        regime = features.regime_at_breakout
        tq = features.trend_quality

        if regime in ("UPTREND", "TREND_UP", "BREAKOUT"):
            base = 0.8
            # 趋势质量加强
            if tq >= 0.8:
                base = min(base + 0.2, 1.0)
            elif tq >= 0.5:
                base = min(base + 0.1, 1.0)
            return base
        elif regime in ("CLIMAX", "DOWNTREND"):
            return 0.3
        elif regime == "RANGE":
            return 0.15
        else:
            return 0.2

    def _score_persistence(self, features: FeatureSet) -> float:
        """持续日数评分。

        真突破特征：持续 > 5 天
        假突破特征：持续 1~2 天
        """
        p = features.breakout_persistence
        if p >= 10:
            return 1.0
        elif p >= 5:
            return 0.7 + (p - 5) / 5.0 * 0.3
        elif p >= 3:
            return 0.4 + (p - 3) / 2.0 * 0.3
        elif p >= 1:
            return 0.1 + (p - 1) / 2.0 * 0.3
        else:
            return 0.0

    def _calc_confidence(self, score: float, classification: str) -> float:
        """计算置信度——距离最近阈值的距离映射到 [0, 1]。"""
        if classification == "true_breakout":
            # 离 0.60 越远置信度越高
            dist = score - self.thresholds["true_breakout"]
            return min(dist / 0.3, 1.0)
        elif classification == "false_breakout":
            # 离 0.40 越远置信度越高
            dist = self.thresholds["false_breakout"] - score
            return min(dist / 0.3, 1.0)
        else:
            # 不确定：离 0.50 越近置信度越低
            dist = abs(score - 0.5)
            return 1.0 - min(dist / 0.1, 1.0)


# ═══════════════════════════════════════════════════════════════
# 突破事件检测（辅助）
# ═══════════════════════════════════════════════════════════════


def detect_breakout_points(df: pd.DataFrame,
                           lookback: int = 20,
                           vol_threshold: float = 1.3) -> List[int]:
    """从价格序列中检测突破点。

    规则：
      1. 当日收盘价突破过去 lookback 日的最高点（向上突破）
      2. 成交量 > vol_threshold × 20日均量（成交量配合）
      3. 或当日收盘价跌破过去 lookback 日的最低点（向下突破）

    Args:
        df: OHLCV DataFrame。
        lookback: 回溯窗口（默认 20）。
        vol_threshold: 成交量阈值（默认 1.3 = 放量30%以上）。

    Returns:
        List[int]: 突破点索引列表。
    """
    n = len(df)
    if n < lookback + 5:
        return []

    indices = []
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values

    # 20日均量
    vol_ma20 = pd.Series(volume).rolling(20, min_periods=5).mean().values

    for i in range(lookback, n):
        prev_high = float(np.max(high[i - lookback:i]))
        prev_low = float(np.min(low[i - lookback:i]))
        curr_close = float(close[i])
        curr_vol = float(volume[i])
        avg_vol = float(vol_ma20[i]) if pd.notna(vol_ma20[i]) else curr_vol

        # 向上突破：突破过去 lookback 日最高点（且成交量配合）
        if curr_close > prev_high * 1.001:
            if avg_vol > 0 and curr_vol > avg_vol * vol_threshold:
                indices.append(i)
            elif avg_vol <= 0:
                indices.append(i)

        # 向下突破
        elif curr_close < prev_low * 0.999:
            if avg_vol > 0 and curr_vol > avg_vol * vol_threshold:
                indices.append(i)
            elif avg_vol <= 0:
                indices.append(i)

    return indices


# ═══════════════════════════════════════════════════════════════
# B4: 假突破报告生成
# ═══════════════════════════════════════════════════════════════


def generate_breakout_report(
    df: pd.DataFrame,
    breakout_indices: List[int],
    batch_id: str,
    symbol: str = "601857",
    output_dir: Optional[str] = None,
    persist_db: bool = True,
) -> Dict[str, Any]:
    """生成假突破画像报告。

    Args:
        df: OHLCV DataFrame。
        breakout_indices: 突破点索引列表。
        batch_id: 回测批号。
        symbol: 标的代码。
        output_dir: 输出目录（默认 reports/backtest/）。
        persist_db: 是否写数据库（默认 True）。

    Returns:
        Dict: 完整报告内容，包括：
            - meta: 元信息
            - events: 每个突破事件的详情
            - summary_stats: 汇总统计
            - feature_comparison: 真假突破特征对比矩阵
    """
    base_dir = MOZHI_BASE / "reports" / "backtest"
    output_dir = Path(output_dir) if output_dir else base_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # 特征提取
    extractor = BreakoutFeatureExtractor()
    extractor.precompute_factors(df)
    features_list = [extractor.extract_at(df, i) for i in breakout_indices]

    # 评分
    card = BreakoutScoringCard()
    scores = card.batch_score(features_list)

    # 构建突破事件
    events: List[BreakoutEvent] = []
    event_dicts: List[Dict[str, Any]] = []

    for idx, features, score_result in zip(breakout_indices, features_list, scores):
        ts = str(df.index[idx]) if isinstance(df.index, pd.DatetimeIndex) else f"bar_{idx}"
        event = BreakoutEvent(
            breakout_id=f"brk_{batch_id}_{symbol}_{idx}",
            batch_id=batch_id,
            timestamp=ts,
            symbol=symbol,
            price=features.price,
            volume=features.volume,
            direction="up",
            volume_ratio=features.volume_ratio,
            vwap_deviation=features.vwap_deviation,
            regime=features.regime_at_breakout,
            trend_quality=features.trend_quality,
            volume_ratio_20=features.volume_ratio_20,
            atr_value=features.atr_value,
            atr_expansion=features.atr_expansion,
            obv_value=features.obv_value,
            obv_change=features.obv_change,
            breakout_persistence=features.breakout_persistence,
            is_false_breakout=score_result["is_false_breakout"],
            breakout_score=score_result["score"],
            confidence=score_result["confidence"],
            features_json=features.to_json(),
        )
        events.append(event)

        event_dicts.append({
            "timestamp": ts,
            "bar_index": idx,
            "price": features.price,
            "volume": features.volume,
            "direction": "up",
            "features": {
                "volume_ratio": features.volume_ratio,
                "vwap_deviation": features.vwap_deviation,
                "regime": features.regime_at_breakout,
                "trend_quality": features.trend_quality,
                "volume_ratio_20": features.volume_ratio_20,
                "atr_value": features.atr_value,
                "atr_expansion": features.atr_expansion,
                "obv_value": features.obv_value,
                "obv_change": features.obv_change,
                "breakout_persistence": features.breakout_persistence,
            },
            "score_card": {
                "score": score_result["score"],
                "classification": score_result["classification"],
                "is_false_breakout": score_result["is_false_breakout"],
                "confidence": score_result["confidence"],
                "components": score_result["components"],
            },
        })

    # 写数据库
    if persist_db:
        db = BreakoutEventDB()
        db.insert_batch(events)
        db.close()

    # 汇总统计
    total = len(events)
    true_events = [e for e in event_dicts if not e["score_card"]["is_false_breakout"]]
    false_events = [e for e in event_dicts if e["score_card"]["is_false_breakout"]]
    uncertain_events = [e for e in event_dicts if e["score_card"]["classification"] == "uncertain"]

    # 真假突破特征对比矩阵
    def _avg_feature(evts: List[Dict], key: str) -> float:
        vals = [e["features"][key] for e in evts if not np.isnan(e["features"][key])]
        return round(float(np.mean(vals)), 4) if vals else 0.0

    feature_comparison = {}
    feature_keys = ["volume_ratio", "vwap_deviation", "atr_expansion",
                    "breakout_persistence", "trend_quality", "volume_ratio_20"]
    for key in feature_keys:
        feature_comparison[key] = {
            "true_breakout_avg": _avg_feature(true_events, key) if true_events else None,
            "false_breakout_avg": _avg_feature(false_events, key) if false_events else None,
            "uncertain_avg": _avg_feature(uncertain_events, key) if uncertain_events else None,
        }

    # 构建完整报告
    report = {
        "meta": {
            "report_type": "false_breakout_profile",
            "batch_id": batch_id,
            "symbol": symbol,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0",
            "author": "墨衡",
            "data_range": {
                "start": str(df.index[0]) if len(df) > 0 else "",
                "end": str(df.index[-1]) if len(df) > 0 else "",
                "total_bars": len(df),
            },
            "data_limitation": "基于规则评分卡，非统计模型。评分仅供参考，需结合业务判断。",
        },
        "summary_stats": {
            "total_breakouts": total,
            "true_breakout_count": len(true_events),
            "false_breakout_count": len(false_events),
            "uncertain_count": len(uncertain_events),
            "true_ratio": round(len(true_events) / total * 100, 1) if total > 0 else 0.0,
            "false_ratio": round(len(false_events) / total * 100, 1) if total > 0 else 0.0,
            "uncertain_ratio": round(len(uncertain_events) / total * 100, 1) if total > 0 else 0.0,
        },
        "events": event_dicts,
        "feature_comparison_matrix": feature_comparison,
    }

    # 写 JSON 报告
    report_path = output_dir / f"false_breakout_profile_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    logger.info("假突破报告已生成: %s", report_path)

    return report
