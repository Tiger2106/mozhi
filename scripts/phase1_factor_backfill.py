#!/usr/bin/env python3
"""
墨枢 Phase 1 — 因子回填脚本（TASK-2）
===========================================
Author: 墨衡
Created: 2026-05-22T22:20+08:00

用途：从 stock_daily 表读取行情数据，计算 50+ 个因子值，
      写入 daily_factors 表（基于 factor_repository 扩展）。

因子类别：
  - 价格动量 (12) : RSI, MACD, 价格变化率, 动量, 加速度
  - 趋势品质 (8)  : ADX, 趋势强度, 趋势一致性, MA斜率/排列/宽度
  - 波动率  (6)  : 布林带宽度, 压缩标识, RSI标准差, 收益率标准差
  - 超买超卖 (5) : RSI/KDJ 区间分级, 极端标识
  - 量价    (8)  : 量比, 量均线穿越, 聪明钱评分, 量能趋势, VWAP偏离
  - 结构    (5)  : 结构评分, 支撑阻力, Volume Profile, LVN
  - 衍生    (6)  : 跳空, KDJ, MA交叉, 综合趋势评分

写入表：daily_factors（扩展自 factor_repository 表结构，支持动态列）

执行：
  python scripts/phase1_factor_backfill.py

依赖：
  - analysis.db 的 stock_daily, adj_factor 表（由 TASK-1 填充）
  - src.backtest.factors.* 因子模块
"""

import os
import sys
import sqlite3
import logging
import math
import numpy as np
import pandas as pd

# ── 项目路径 ──────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

ANALYSIS_DB = os.path.join(PROJECT_ROOT, "data", "db", "analysis.db")

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 所有标的（6位代码，不含后缀）
STOCK_CODES = [
    "601857", "000001", "600519", "601318",
    "600036", "300750", "600276", "600887",
    "600030", "000333", "002415", "600436",
]


# ════════════════════════════════════════════════════════
# DB 操作
# ════════════════════════════════════════════════════════

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(ANALYSIS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_factors_table(conn: sqlite3.Connection):
    """创建 daily_factors 表（扩展自 factor_repository）"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_factors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL,
            date        TEXT NOT NULL,

            -- === P层：价格动量类 ===
            p_mom_rsi               REAL,    -- RSI14  [0,100]
            p_mom_macd_dir          INTEGER, -- MACD_DIF方向 [-1,0,1]
            p_mom_macd_hist_rate    REAL,    -- MACD_HIST变化率
            p_mom_price_velocity    REAL,    -- 5日价格变化率
            p_mom_roc5              REAL,    -- 5日变动率
            p_mom_roc10             REAL,    -- 10日变动率
            p_mom_roc20             REAL,    -- 20日变动率
            p_mom_acceleration      REAL,    -- 价格加速度
            p_mom_mtm               REAL,    -- 动量 (close - close[10])
            p_mom_williams_r        REAL,    -- Williams %R
            p_mom_cci               REAL,    -- CCI
            p_mom_tsi               REAL,    -- True Strength Index

            -- === L层：趋势品质类 ===
            l_trd_adx               REAL,    -- ADX
            l_trd_strength          REAL,    -- 归一化趋势强度 [0,1]
            l_trd_consistency       REAL,    -- 趋势一致性 [0,1]
            l_trd_ma_slope          REAL,    -- MA斜率
            l_trd_alignment         REAL,    -- MA均线排列评分 [0,100]
            l_trd_width             REAL,    -- MA5/MA20偏离度
            l_trd_breadth           REAL,    -- MA5-MA20距离
            l_trd_composite_score   REAL,    -- 综合趋势评分

            -- === L层：波动率类 ===
            l_vol_bb_width          REAL,    -- 布林带宽度/mid(%)
            l_vol_bb_squeeze        INTEGER, -- 布林带压缩标识 [0,1]
            l_vol_rsi_std           REAL,    -- RSI14标准差(20d)
            l_vol_price_std         REAL,    -- 5日收益率标准差
            l_vol_atr               REAL,    -- ATR(14)
            l_vol_atr_ratio         REAL,    -- ATR比率(短期/长期)
            l_vol_log_ret_std       REAL,    -- 20日对数收益率标准差
            l_vol_skew              REAL,    -- 收益率偏度(20d)
            l_vol_kurt              REAL,    -- 收益率峰度(20d)

            -- === L层：超买超卖类 ===
            l_obo_rsi_level         INTEGER, -- RSI区间 [0=超卖,1=中性,2=超买]
            l_obo_rsi_extreme       INTEGER, -- RSI极端 [-1=超卖,0=正常,1=超买]
            l_obo_kdj_level         INTEGER, -- KDJ_J区间
            l_obo_kdj_extreme       INTEGER, -- KDJ_J极端
            l_obo_cci_level         INTEGER, -- CCI区间

            -- === L层：量价类 ===
            l_vol_ratio             REAL,    -- 量比 [0,10]
            l_vol_ma5_cross         INTEGER, -- 量均线穿越 [-1,0,1]
            l_vol_smart_money       REAL,    -- 聪明钱评分 [-1,1]
            l_vol_trend             REAL,    -- 量能趋势评分 [-1,1]
            l_vol_vwap_dev          REAL,    -- VWAP偏离度(%)
            l_vol_vwap_5_dev        REAL,    -- VWAP5偏离度
            l_vol_vwap_20_dev       REAL,    -- VWAP20偏离度
            l_vol_dollar_vol        REAL,    -- 成交额(亿)

            -- === L层：特殊结构类 ===
            l_str_structure_quality REAL,    -- 结构完整度 [0,1]
            l_str_gap_up            INTEGER, -- 向上跳空
            l_str_gap_down          INTEGER, -- 向下跳空
            l_str_ma5_ma20_cross    INTEGER, -- MA5上穿MA20 [-1,0,1]
            l_str_ma20_ma60_cross   INTEGER, -- MA20上穿MA60 [-1,0,1]
            l_str_kdj_k             REAL,    -- KDJ K值
            l_str_kdj_d             REAL,    -- KDJ D值
            l_str_kdj_j             REAL,    -- KDJ J值
            l_str_bb_position       REAL,    -- 价格在布林带中的位置 [0,1]
            l_str_close_vs_vwap     REAL,    -- 收盘价 vs VWAP方向

            -- 审计字段
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(code, date)
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_df_code_date
        ON daily_factors(code, date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_df_date
        ON daily_factors(date)
    """)
    conn.commit()
    logger.info("daily_factors 表就绪")


def load_stock_data(conn: sqlite3.Connection, code: str) -> pd.DataFrame:
    """从 stock_daily 加载单只标的的全量数据，按日期升序"""
    df = pd.read_sql_query(
        "SELECT * FROM stock_daily WHERE code=? ORDER BY date ASC",
        conn,
        params=(code,),
    )
    if df.empty:
        return df
    # 类型统一
    for col in ["open", "high", "low", "close", "pre_close", "adj_factor"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(np.int64)
    return df


def write_factors(conn: sqlite3.Connection, records: list):
    """批量写入 daily_factors（UPSERT 幂等）"""
    if not records:
        return
    conn.executemany(
        """INSERT OR REPLACE INTO daily_factors
           (code, date,
            p_mom_rsi, p_mom_macd_dir, p_mom_macd_hist_rate, p_mom_price_velocity,
            p_mom_roc5, p_mom_roc10, p_mom_roc20, p_mom_acceleration, p_mom_mtm,
            p_mom_williams_r, p_mom_cci, p_mom_tsi,
            l_trd_adx, l_trd_strength, l_trd_consistency, l_trd_ma_slope,
            l_trd_alignment, l_trd_width, l_trd_breadth, l_trd_composite_score,
            l_vol_bb_width, l_vol_bb_squeeze, l_vol_rsi_std, l_vol_price_std,
            l_vol_atr, l_vol_atr_ratio, l_vol_log_ret_std, l_vol_skew, l_vol_kurt,
            l_obo_rsi_level, l_obo_rsi_extreme,
            l_obo_kdj_level, l_obo_kdj_extreme, l_obo_cci_level,
            l_vol_ratio, l_vol_ma5_cross, l_vol_smart_money, l_vol_trend,
            l_vol_vwap_dev, l_vol_vwap_5_dev, l_vol_vwap_20_dev, l_vol_dollar_vol,
            l_str_structure_quality, l_str_gap_up, l_str_gap_down,
            l_str_ma5_ma20_cross, l_str_ma20_ma60_cross,
            l_str_kdj_k, l_str_kdj_d, l_str_kdj_j,
            l_str_bb_position, l_str_close_vs_vwap)
           VALUES (?,?,
            ?,?,?,?,
            ?,?,?,?,?,
            ?,?,?,
            ?,?,?,?,
            ?,?,?,?,
            ?,?,?,?,
            ?,?,?,?,?,
            ?,?,
            ?,?,?,
            ?,?,?,?,
            ?,?,?,?,
            ?,?,?,
            ?,?,
            ?,?,?,
            ?,?)""",
        records,
    )
    conn.commit()


# ════════════════════════════════════════════════════════
# 核心因子计算
# ════════════════════════════════════════════════════════

def compute_all_factors(code: str, df: pd.DataFrame) -> list:
    """
    对单只标的全量日线数据计算因子。
    返回 [(code, date, v1, v2, ..., v52), ...] 列表。
    """
    if df.empty or len(df) < 30:
        logger.warning("[%s] 数据不足 (%d行), 跳过因子计算", code, len(df))
        return []

    n = len(df)
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    o = df["open"].values.astype(float)
    v = df["volume"].values.astype(float)
    a = df["amount"].values.astype(float)

    dates = df["date"].tolist()

    # ── 1. 价格动量因子 ───────────────────────────────
    rsi14 = _calc_rsi(c, 14)
    macd_dif, macd_dea, macd_hist = _calc_macd(c)
    macd_dir = _calc_macd_dir(macd_dif)
    macd_hist_rate = _calc_macd_hist_rate(macd_hist)
    price_velocity = _calc_change_rate(c, 5)
    roc5 = _calc_change_rate(c, 5)
    roc10 = _calc_change_rate(c, 10)
    roc20 = _calc_change_rate(c, 20)
    acceleration = _calc_acceleration(c)
    mtm = _calc_mtm(c, 10)
    wr = _calc_williams_r(h, l, c, 14)
    cci = _calc_cci(h, l, c, 20)
    tsi = _calc_tsi(c, 25, 13)

    # ── 2. 趋势品质因子 ───────────────────────────────
    adx = _calc_adx_pure(h, l, c, 14)
    trd_strength = _calc_trend_strength(adx)
    trd_consistency = _calc_trend_consistency(c, 10)
    ma_slope = _calc_ma_slope(c, 20, 5)
    ma5 = _calc_sma(c, 5)
    ma10 = _calc_sma(c, 10)
    ma20 = _calc_sma(c, 20)
    ma60 = _calc_sma(c, 60)

    ma_alignment = _calc_ma_alignment(ma5, ma10, ma20, ma60)
    ma_width = _calc_ma_width(ma5, ma20)
    ma_breadth = _calc_ma_breadth(ma5, ma20)
    composite_score = _calc_composite_trend_score(adx, ma_slope, c, 5, 20)

    # ── 3. 波动率因子 ─────────────────────────────────
    bb_mid, bb_upper, bb_lower = _calc_bollinger(c, 20, 2.0)
    bb_width = _calc_bb_width(bb_upper, bb_lower, bb_mid)
    bb_squeeze = _calc_bb_squeeze(bb_width)
    rsi_std = _calc_rolling_std(rsi14, 20)
    price_std = _calc_rolling_std(_returns(c), 5)
    atr = _calc_atr(h, l, c, 14)
    atr_ratio = _calc_atr_ratio(atr, 14, 60)
    log_ret_std = _calc_rolling_std(_log_returns(c), 20)
    skew = _calc_rolling_skew(c, 20)
    kurt = _calc_rolling_kurt(c, 20)

    # ── 4. 超买超卖因子 ───────────────────────────────
    obo_rsi_level = _calc_rsi_level(rsi14)
    obo_rsi_extreme = _calc_rsi_extreme(rsi14)
    kdj_k, kdj_d, kdj_j = _calc_kdj(h, l, c, 9)
    obo_kdj_level = _calc_kdj_level(kdj_j)
    obo_kdj_extreme = _calc_kdj_extreme(kdj_j)
    obo_cci_level = _calc_cci_level(cci)

    # ── 5. 量价因子 ───────────────────────────────────
    v_ma5 = _calc_sma(v, 5)
    v_ma20 = _calc_sma(v, 20)
    vol_ratio = _calc_series_div(v, v_ma20)
    vol_ma5_cross = _calc_ma_cross(v_ma5, v_ma20)
    smart_money = _calc_smart_money_score(c, v, 10)
    vol_trend = _calc_volume_trend(v, 20)
    vwap = _calc_vwap(h, l, c, v)
    vwap_dev = _calc_vwap_deviation(c, vwap)
    vwap_5 = _calc_vwap_rolling(h, l, c, v, 5)
    vwap_20 = _calc_vwap_rolling(h, l, c, v, 20)
    vwap_5_dev = _calc_series_div(c, vwap_5)
    vwap_20_dev = _calc_series_div(c, vwap_20)
    dollar_vol = _calc_dollar_volume(a)

    # ── 6. 结构因子 ───────────────────────────────────
    structure_quality = _calc_structure_quality(h, l, c, 30)
    gap_up, gap_down = _calc_gaps(o, c, h, l)
    ma5_ma20_cross = _calc_ma_cross(ma5, ma20)
    ma20_ma60_cross = _calc_ma_cross(ma20, ma60)
    bb_position = _calc_bb_position(c, bb_upper, bb_lower)
    close_vs_vwap = _calc_close_vs_vwap(c, vwap)

    # ── 组装记录 ─────────────────────────────────────
    records = []
    for i in range(n):
        ri = _safe(i)
        records.append((
            code, dates[i],
            ri(rsi14, i), ri(macd_dir, i), ri(macd_hist_rate, i), ri(price_velocity, i),
            ri(roc5, i), ri(roc10, i), ri(roc20, i), ri(acceleration, i), ri(mtm, i),
            ri(wr, i), ri(cci, i), ri(tsi, i),
            ri(adx, i), ri(trd_strength, i), ri(trd_consistency, i), ri(ma_slope, i),
            ri(ma_alignment, i), ri(ma_width, i), ri(ma_breadth, i), ri(composite_score, i),
            ri(bb_width, i), ri(bb_squeeze, i), ri(rsi_std, i), ri(price_std, i),
            ri(atr, i), ri(atr_ratio, i), ri(log_ret_std, i), ri(skew, i), ri(kurt, i),
            ri(obo_rsi_level, i), ri(obo_rsi_extreme, i),
            ri(obo_kdj_level, i), ri(obo_kdj_extreme, i), ri(obo_cci_level, i),
            ri(vol_ratio, i), ri(vol_ma5_cross, i), ri(smart_money, i), ri(vol_trend, i),
            ri(vwap_dev, i), ri(vwap_5_dev, i), ri(vwap_20_dev, i), ri(dollar_vol, i),
            ri(structure_quality, i), ri(gap_up, i), ri(gap_down, i),
            ri(ma5_ma20_cross, i), ri(ma20_ma60_cross, i),
            ri(kdj_k, i), ri(kdj_d, i), ri(kdj_j, i),
            ri(bb_position, i), ri(close_vs_vwap, i),
        ))

    return records


# ════════════════════════════════════════════════════════
# 基础技术指标实现
# ════════════════════════════════════════════════════════

def _safe(arr):
    """返回索引取值函数，处理 None/NaN"""
    def _get(arr_val, idx):
        if arr_val is None:
            return None
        if isinstance(arr_val, (list, tuple, np.ndarray)):
            if idx < len(arr_val):
                v = arr_val[idx]
                return None if (v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))) else float(v)
            return None
        return None
    return _get


def _calc_sma(values, period):
    """简单移动平均"""
    values = np.asarray(values, dtype=float)
    n = len(values)
    result = np.full(n, np.nan)
    if n < period:
        return result
    cumsum = np.cumsum(values)
    result[period - 1] = cumsum[period - 1] / period
    for i in range(period, n):
        result[i] = (cumsum[i] - cumsum[i - period]) / period
    return result


# ============================================================
# ⚠️ DEPRECATED (2026-05-24): 已由 src.core.ema_nan_safe 的 ema_nan_safe()
# 统一替代。保留仅用于兼容旧代码，新代码应直接使用 ema_nan_safe。
# _ema_np (phase1_factor_backfill._calc_ema) — 保留期至下个大版本清理
# ============================================================
def _calc_ema(values, period):
    """指数移动平均（带NaN隔离防护）。"""
    from src.core.ema_nan_safe import ema_nan_safe
    result_list = ema_nan_safe(values, period, min_periods=period, use_pandas=False)
    return np.array([np.nan if v is None else v for v in result_list], dtype=float)


def _returns(closes):
    """简单收益率"""
    closes = np.asarray(closes, dtype=float)
    ret = np.full(len(closes), np.nan)
    ret[1:] = (closes[1:] - closes[:-1]) / closes[:-1]
    return ret


def _log_returns(closes):
    """对数收益率"""
    closes = np.asarray(closes, dtype=float)
    lr = np.full(len(closes), np.nan)
    mask = closes[:-1] > 0
    lr[1:][mask] = np.log(closes[1:][mask] / closes[:-1][mask])
    return lr


def _calc_change_rate(values, period):
    """变化率 (%)"""
    values = np.asarray(values, dtype=float)
    n = len(values)
    result = np.full(n, np.nan)
    if n <= period:
        return result
    for i in range(period, n):
        if values[i - period] > 0:
            result[i] = (values[i] - values[i - period]) / values[i - period] * 100
        else:
            result[i] = 0.0
    return result


def _calc_rolling_std(values, period):
    """滚动标准差"""
    values = np.asarray(values, dtype=float)
    n = len(values)
    result = np.full(n, np.nan)
    if n < period:
        return result
    for i in range(period - 1, n):
        window = values[i - period + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) >= 2:
            result[i] = np.std(valid, ddof=1)
    return result


def _calc_rsi(closes, period=14):
    """RSI(14)"""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    if n <= period:
        return result
    gains = np.zeros(n)
    losses = np.zeros(n)
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = -diff
    avg_gain = _calc_sma(gains, period)
    avg_loss = _calc_sma(losses, period)
    for i in range(period, n):
        if avg_loss[i] > 0:
            rs = avg_gain[i] / avg_loss[i]
            result[i] = 100.0 - 100.0 / (1.0 + rs)
        elif avg_loss[i] == 0 and avg_gain[i] > 0:
            result[i] = 100.0
        else:
            result[i] = 50.0
    return result


def _calc_macd(closes, fast=12, slow=26, signal=9):
    """MACD（pandas ewm，NaN-safe）"""
    s = pd.Series(closes).astype(float)
    n = len(s)
    # 第一层 EMA（含预热 NaN）
    ema_fast = s.ewm(span=fast, min_periods=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, min_periods=slow, adjust=False).mean()
    # DIF：只取两者都有值的位置
    dif = pd.Series(np.full(n, np.nan))
    valid = ema_fast.notna() & ema_slow.notna()
    dif[valid] = ema_fast[valid] - ema_slow[valid]
    # 第二层 DEA：只喂非 NaN 值
    dea = dif.dropna().ewm(span=signal, min_periods=signal, adjust=False).mean()
    dea = dea.reindex(dif.index, fill_value=np.nan)
    # HIST
    hist = pd.Series(np.full(n, np.nan))
    both_valid = dif.notna() & dea.notna()
    hist[both_valid] = 2.0 * (dif[both_valid] - dea[both_valid])
    return dif.values, dea.values, hist.values


def _calc_macd_dir(dif):
    """MACD DIF方向"""
    if dif is None or len(dif) == 0:
        return None
    result = np.full(len(dif), 0, dtype=np.int8)
    for i in range(1, len(dif)):
        if dif[i] is not None and dif[i - 1] is not None and not np.isnan(dif[i]) and not np.isnan(dif[i - 1]):
            if dif[i] > dif[i - 1]:
                result[i] = 1
            elif dif[i] < dif[i - 1]:
                result[i] = -1
    return result


def _calc_macd_hist_rate(hist):
    """MACD柱状图变化率"""
    if hist is None or len(hist) == 0:
        return None
    result = np.full(len(hist), np.nan)
    for i in range(2, len(hist)):
        if hist[i] is not None and hist[i - 1] is not None and not np.isnan(hist[i]) and not np.isnan(hist[i - 1]):
            if abs(hist[i - 1]) > 1e-10:
                result[i] = (hist[i] - hist[i - 1]) / abs(hist[i - 1])
                result[i] = np.clip(result[i], -1.0, 1.0)
    return result


def _calc_mtm(closes, period=10):
    """动量：close - close[period]"""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(period, n):
        result[i] = closes[i] - closes[i - period]
    return result


def _calc_williams_r(highs, lows, closes, period=14):
    """Williams %R"""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period:
        return result
    for i in range(period - 1, n):
        hh = np.max(highs[i - period + 1:i + 1])
        ll = np.min(lows[i - period + 1:i + 1])
        if hh > ll:
            result[i] = -100.0 * (hh - closes[i]) / (hh - ll)
    return result


def _calc_cci(highs, lows, closes, period=20):
    """CCI - Commodity Channel Index"""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    tp = (highs + lows + closes) / 3.0
    result = np.full(n, np.nan)
    if n < period:
        return result
    sma_tp = _calc_sma(tp, period)
    for i in range(period - 1, n):
        if np.isnan(sma_tp[i]):
            continue
        mad = np.mean(np.abs(tp[i - period + 1:i + 1] - sma_tp[i]))
        if mad > 0:
            result[i] = (tp[i] - sma_tp[i]) / (0.015 * mad)
    return result


def _calc_tsi(closes, long_period=25, short_period=13):
    """True Strength Index（使用 ema_nan_safe(use_pandas=True) 统一封装）"""
    from src.core.ema_nan_safe import ema_nan_safe
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    if n < 2:
        return result
    # 变化率
    s = pd.Series(closes)
    chg = s.diff().fillna(0)  # chg[0]=0，与原实现一致
    abs_chg = chg.abs()
    # 第一层 EMA（使用统一封装）
    ema1_list = ema_nan_safe(chg.tolist(), long_period, min_periods=long_period, use_pandas=True)
    ema_abs1_list = ema_nan_safe(abs_chg.tolist(), long_period, min_periods=long_period, use_pandas=True)
    # 转换回 numpy
    ema1 = np.array([np.nan if v is None else v for v in ema1_list], dtype=float)
    ema_abs1 = np.array([np.nan if v is None else v for v in ema_abs1_list], dtype=float)
    # 第二层 EMA（使用统一封装）
    ema2_list = ema_nan_safe(ema1.tolist(), short_period, min_periods=short_period, use_pandas=True)
    ema_abs2_list = ema_nan_safe(ema_abs1.tolist(), short_period, min_periods=short_period, use_pandas=True)
    ema2 = np.array([np.nan if v is None else v for v in ema2_list], dtype=float)
    ema_abs2 = np.array([np.nan if v is None else v for v in ema_abs2_list], dtype=float)
    # 计算 TSI
    for i in range(n):
        v = ema2[i]
        denom = ema_abs2[i]
        if not np.isnan(v) and not np.isnan(denom) and abs(denom) > 1e-10:
            result[i] = 100.0 * v / denom
    # NaN隔离：输入NaN位置 → 输出NaN
    result[np.isnan(closes)] = np.nan
    return result


def _calc_acceleration(closes):
    """价格加速度 = 变化率的变化率"""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    if n < 6:
        return result
    ror = _calc_change_rate(closes, 5)
    for i in range(10, n):
        if not np.isnan(ror[i]) and not np.isnan(ror[i - 5]):
            result[i] = ror[i] - ror[i - 5]
    return result


# ── 趋势品质 ────────────────────────────────────────────


def _calc_adx_pure(highs, lows, closes, period=14):
    """纯 numpy 版 ADX"""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(highs)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result

    tr = np.zeros(n)
    up_move = np.zeros(n)
    down_move = np.zeros(n)

    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        up_move[i] = max(up, 0) if up > down else 0
        down_move[i] = max(down, 0) if down > up else 0

    def _wilder_smooth(raw, p):
        out = np.full(n, 0.0)
        out[p] = np.sum(raw[1:p+1])
        for i in range(p+1, n):
            out[i] = out[i-1] - out[i-1]/p + raw[i]
        return out

    tr_s = _wilder_smooth(tr, period)
    up_s = _wilder_smooth(up_move, period)
    down_s = _wilder_smooth(down_move, period)

    for i in range(period, n):
        if tr_s[i] > 1e-10:
            pdi = 100.0 * up_s[i] / tr_s[i]
            ndi = 100.0 * down_s[i] / tr_s[i]
            di_sum = pdi + ndi
            if di_sum > 0:
                dx = 100.0 * abs(pdi - ndi) / di_sum
                if np.isnan(result[i-1]) or result[i-1] == 0:
                    result[i] = dx
                else:
                    result[i] = (result[i-1] * (period-1) + dx) / period

    return result


def _calc_trend_strength(adx):
    """ADX → [0,1] 归一化"""
    if adx is None or len(adx) == 0:
        return None
    result = np.full(len(adx), np.nan)
    for i, a in enumerate(adx):
        if a is not None and not np.isnan(a):
            if a < 20:
                result[i] = a / 20.0 * 0.3
            elif a < 40:
                result[i] = 0.3 + (a - 20) / 20.0 * 0.4
            else:
                result[i] = 0.7 + (a - 40) / 60.0 * 0.3
            result[i] = min(max(result[i], 0.0), 1.0)
    return result


def _calc_trend_consistency(closes, lookback=10):
    """趋势方向一致性"""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    if n < 2:
        return result
    direction = np.zeros(n)
    for i in range(1, n):
        direction[i] = 1 if closes[i] > closes[i-1] else (-1 if closes[i] < closes[i-1] else 0)
    for i in range(1, n):
        start = max(0, i - lookback + 1)
        window = direction[start:i+1]
        non_zero = window[window != 0]
        if len(non_zero) > 0:
            pos_ratio = np.sum(non_zero > 0) / len(non_zero)
            result[i] = 2.0 * abs(pos_ratio - 0.5)
    return result


def _calc_ma_slope(closes, ma_period=20, slope_period=5):
    """均线斜率（归一化）"""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    ma = _calc_sma(closes, ma_period)
    start = ma_period + slope_period - 1
    if start >= n:
        return result
    for i in range(start, n):
        seg = ma[i - slope_period + 1:i + 1]
        valid = seg[~np.isnan(seg)]
        if len(valid) >= 2:
            x = np.arange(len(valid))
            xy_mean = np.mean(x * valid)
            x_mean = np.mean(x)
            y_mean = np.mean(valid)
            num = xy_mean - x_mean * y_mean
            den = np.mean(x**2) - x_mean**2
            if den > 1e-10 and closes[i] > 1e-10:
                result[i] = num / den / closes[i]
    return result


def _calc_ma_alignment(ma5, ma10, ma20, ma60):
    """MA排列评分：MA5 > MA10 > MA20 > MA60 → 强势多头排列"""
    if ma5 is None or ma10 is None or ma20 is None or ma60 is None:
        return None
    n = min(len(ma5), len(ma10), len(ma20), len(ma60))
    result = np.full(n, np.nan)
    for i in range(n):
        if any(np.isnan(x[i]) for x in [ma5, ma10, ma20, ma60]):
            continue
        score = 0.0
        if ma5[i] > ma10[i]: score += 25
        if ma10[i] > ma20[i]: score += 25
        if ma20[i] > ma60[i]: score += 25
        if ma5[i] > ma20[i]: score += 25
        result[i] = score
    return result


def _calc_ma_width(ma5, ma20):
    """MA5/MA20偏离度 (%)"""
    if ma5 is None or ma20 is None:
        return None
    n = min(len(ma5), len(ma20))
    result = np.full(n, np.nan)
    for i in range(n):
        if ma20[i] > 0 and not np.isnan(ma5[i]) and not np.isnan(ma20[i]):
            result[i] = (ma5[i] - ma20[i]) / ma20[i] * 100
            result[i] = np.clip(result[i], -10, 10)
    return result


def _calc_ma_breadth(ma5, ma20):
    """MA5-MA20距离 (标准化)"""
    if ma5 is None or ma20 is None:
        return None
    n = min(len(ma5), len(ma20))
    result = np.full(n, np.nan)
    for i in range(n):
        if ma20[i] > 0 and not np.isnan(ma5[i]) and not np.isnan(ma20[i]):
            result[i] = (ma5[i] - ma20[i]) / ma20[i]
            result[i] = np.clip(result[i], -2, 2)
    return result


def _calc_composite_trend_score(adx, ma_slope, closes, short_period=5, long_period=20):
    """综合趋势评分 [0,1]"""
    if adx is None or ma_slope is None:
        return None
    n = min(len(adx), len(ma_slope))
    result = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(adx[i]) or np.isnan(ma_slope[i]):
            continue
        adx_s = min(adx[i] / 50.0, 1.0) if not np.isnan(adx[i]) else 0.0
        slope_s = min(abs(ma_slope[i]) / 0.005, 1.0) if not np.isnan(ma_slope[i]) else 0.0
        result[i] = 0.5 * adx_s + 0.5 * slope_s
    return result


# ── 波动率 ──────────────────────────────────────────────


def _calc_bollinger(closes, period=20, std_dev=2.0):
    """布林带"""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    mid = _calc_sma(closes, period)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(period - 1, n):
        std = np.std(closes[i - period + 1:i + 1], ddof=1)
        upper[i] = mid[i] + std_dev * std
        lower[i] = mid[i] - std_dev * std
    return mid, upper, lower


def _calc_bb_width(upper, lower, mid):
    """布林带宽度"""
    if upper is None or lower is None or mid is None:
        return None
    n = min(len(upper), len(lower), len(mid))
    result = np.full(n, np.nan)
    for i in range(n):
        if mid[i] > 0 and not np.isnan(upper[i]) and not np.isnan(lower[i]) and not np.isnan(mid[i]):
            result[i] = (upper[i] - lower[i]) / mid[i] * 100
            result[i] = np.clip(result[i], 0, 20)
    return result


def _calc_bb_squeeze(bb_width):
    """布林带压缩 [0,1]"""
    if bb_width is None:
        return None
    n = len(bb_width)
    result = np.zeros(n, dtype=np.int8)
    if n < 20:
        return result
    # 取最近20期的宽度均值，低于均值的0.5倍视为压缩
    for i in range(19, n):
        recent = bb_width[max(0, i-19):i+1]
        valid = recent[~np.isnan(recent)]
        if len(valid) >= 10:
            mean_w = np.mean(valid)
            if bb_width[i] is not None and not np.isnan(bb_width[i]) and mean_w > 0:
                result[i] = 1 if bb_width[i] <= mean_w * 0.5 else 0
    return result


def _calc_atr(highs, lows, closes, period=14):
    """ATR"""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(highs)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    atr = _calc_ema(tr, period)
    return atr


def _calc_atr_ratio(atr, short_period=14, long_period=60):
    """ATR比率（短期ATR均值 / 长期ATR均值）"""
    if atr is None:
        return None
    n = len(atr)
    result = np.full(n, np.nan)
    for i in range(long_period - 1, n):
        short_mean = np.nanmean(atr[max(0, i - short_period + 1):i + 1])
        long_mean = np.nanmean(atr[max(0, i - long_period + 1):i + 1])
        if long_mean > 0 and not np.isnan(long_mean):
            result[i] = short_mean / long_mean
    return result


def _calc_rolling_skew(closes, period=20):
    """收益率偏度"""
    closes = np.asarray(closes, dtype=float)
    rets = _returns(closes)
    n = len(rets)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = rets[i - period + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) >= 3:
            s = np.std(valid, ddof=1)
            if s > 1e-10:
                result[i] = np.mean((valid - np.mean(valid)) ** 3) / (s ** 3)
    return result


def _calc_rolling_kurt(closes, period=20):
    """收益率峰度"""
    closes = np.asarray(closes, dtype=float)
    rets = _returns(closes)
    n = len(rets)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = rets[i - period + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) >= 4:
            s = np.std(valid, ddof=1)
            if s > 1e-10:
                result[i] = np.mean((valid - np.mean(valid)) ** 4) / (s ** 4) - 3.0
    return result


# ── 超买超卖 ────────────────────────────────────────────


def _calc_rsi_level(rsi):
    """RSI区间 [0=超卖, 1=中性, 2=超买]"""
    if rsi is None:
        return None
    result = np.full(len(rsi), 1, dtype=np.int8)
    for i in range(len(rsi)):
        if rsi[i] is not None and not np.isnan(rsi[i]):
            if rsi[i] <= 30:
                result[i] = 0
            elif rsi[i] >= 70:
                result[i] = 2
    return result


def _calc_rsi_extreme(rsi):
    """RSI极端 [-1=超卖, 0=正常, 1=超买]"""
    if rsi is None:
        return None
    result = np.zeros(len(rsi), dtype=np.int8)
    for i in range(len(rsi)):
        if rsi[i] is not None and not np.isnan(rsi[i]):
            if rsi[i] <= 20:
                result[i] = -1
            elif rsi[i] >= 80:
                result[i] = 1
    return result


def _calc_kdj(highs, lows, closes, period=9):
    """KDJ"""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    k = np.full(n, np.nan)
    d = np.full(n, np.nan)
    j = np.full(n, np.nan)
    if n < period:
        return k, d, j
    for i in range(period - 1, n):
        hh = np.max(highs[i - period + 1:i + 1])
        ll = np.min(lows[i - period + 1:i + 1])
        if hh > ll:
            rsv = (closes[i] - ll) / (hh - ll) * 100
        else:
            rsv = 50
        if np.isnan(k[i - 1]):
            k[i] = rsv
            d[i] = rsv
        else:
            k[i] = 2.0 / 3.0 * k[i - 1] + 1.0 / 3.0 * rsv
            d[i] = 2.0 / 3.0 * d[i - 1] + 1.0 / 3.0 * k[i]
        j[i] = 3.0 * k[i] - 2.0 * d[i]
    return k, d, j


def _calc_kdj_level(kdj_j):
    """KDJ_J区间"""
    if kdj_j is None:
        return None
    result = np.full(len(kdj_j), 1, dtype=np.int8)
    for i in range(len(kdj_j)):
        if kdj_j[i] is not None and not np.isnan(kdj_j[i]):
            if kdj_j[i] <= 20:
                result[i] = 0
            elif kdj_j[i] >= 80:
                result[i] = 2
    return result


def _calc_kdj_extreme(kdj_j):
    """KDJ_J极端"""
    if kdj_j is None:
        return None
    result = np.zeros(len(kdj_j), dtype=np.int8)
    for i in range(len(kdj_j)):
        if kdj_j[i] is not None and not np.isnan(kdj_j[i]):
            if kdj_j[i] <= 10:
                result[i] = -1
            elif kdj_j[i] >= 90:
                result[i] = 1
    return result


def _calc_cci_level(cci):
    """CCI区间 [-1=超卖, 0=正常, 1=超买]"""
    if cci is None:
        return None
    result = np.zeros(len(cci), dtype=np.int8)
    for i in range(len(cci)):
        if cci[i] is not None and not np.isnan(cci[i]):
            if cci[i] <= -100:
                result[i] = -1
            elif cci[i] >= 100:
                result[i] = 1
    return result


# ── 量价 ────────────────────────────────────────────────


def _calc_series_div(numer, denom):
    """除法：numer / denom (避免除0)"""
    if numer is None or denom is None:
        return None
    n = min(len(numer), len(denom))
    result = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(numer[i]) and not np.isnan(denom[i]) and denom[i] > 0:
            result[i] = numer[i] / denom[i]
    return result


def _calc_ma_cross(fast_ma, slow_ma):
    """均线穿越 [-1=下穿, 0=无, 1=上穿]"""
    if fast_ma is None or slow_ma is None:
        return None
    n = min(len(fast_ma), len(slow_ma))
    result = np.zeros(n, dtype=np.int8)
    for i in range(1, n):
        if any(np.isnan(x[i]) or np.isnan(x[i-1]) for x in [fast_ma, slow_ma]):
            continue
        if fast_ma[i] > slow_ma[i] and fast_ma[i-1] <= slow_ma[i-1]:
            result[i] = 1
        elif fast_ma[i] < slow_ma[i] and fast_ma[i-1] >= slow_ma[i-1]:
            result[i] = -1
    return result


def _calc_smart_money_score(closes, volumes, lookback=10):
    """聪明钱评分 [-1, 1]"""
    closes = np.asarray(closes, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    price_dir = np.zeros(n)
    vol_dir = np.zeros(n)
    for i in range(1, n):
        price_dir[i] = 1 if closes[i] > closes[i-1] else (-1 if closes[i] < closes[i-1] else 0)
        vol_dir[i] = 1 if volumes[i] > volumes[i-1] else (-1 if volumes[i] < volumes[i-1] else 0)
    for i in range(lookback - 1, n):
        window = (price_dir[i - lookback + 1:i + 1] * vol_dir[i - lookback + 1:i + 1]).astype(float)
        weights = np.array([0.5 + 0.5 * j / lookback for j in range(lookback)])
        weights /= weights.sum()
        s = np.sum(window * weights)
        result[i] = np.clip(s, -1.0, 1.0)
    return result


def _calc_volume_trend(volumes, period=20):
    """量能趋势 [-1, 1]"""
    volumes = np.asarray(volumes, dtype=float)
    n = len(volumes)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = volumes[i - period + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) >= 5:
            x = np.arange(len(valid))
            y = (valid - np.mean(valid)) / (np.std(valid) + 1e-10)
            slope = np.polyfit(x, y, 1)[0]
            result[i] = np.clip(slope * 2.0, -1.0, 1.0)
    return result


def _calc_vwap(highs, lows, closes, volumes):
    """VWAP（累计）"""
    tp = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(tp * volumes)
    cum_vol = np.cumsum(volumes)
    vwap = cum_tp_vol / np.maximum(cum_vol, 1)
    return vwap


def _calc_vwap_rolling(highs, lows, closes, volumes, period):
    """滚动 VWAP"""
    tp = (highs + lows + closes) / 3.0
    n = len(tp)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        tp_sum = np.sum(tp[i - period + 1:i + 1] * volumes[i - period + 1:i + 1])
        vol_sum = np.sum(volumes[i - period + 1:i + 1])
        if vol_sum > 0:
            result[i] = tp_sum / vol_sum
    return result


def _calc_vwap_deviation(closes, vwap):
    """VWAP偏离度 (%)"""
    if closes is None or vwap is None:
        return None
    n = min(len(closes), len(vwap))
    result = np.full(n, np.nan)
    for i in range(n):
        if vwap[i] > 0 and not np.isnan(closes[i]) and not np.isnan(vwap[i]):
            result[i] = (closes[i] - vwap[i]) / vwap[i] * 100
    return result


def _calc_dollar_volume(amounts):
    """成交额(亿)"""
    amounts = np.asarray(amounts, dtype=float)
    return amounts / 1e8


def _calc_close_vs_vwap(closes, vwap):
    """收盘价相对VWAP方向 [-1=低于, 0=接近, 1=高于]"""
    if closes is None or vwap is None:
        return None
    n = min(len(closes), len(vwap))
    result = np.zeros(n, dtype=np.int8)
    for i in range(n):
        if not np.isnan(closes[i]) and not np.isnan(vwap[i]) and vwap[i] > 0:
            dev = (closes[i] - vwap[i]) / vwap[i]
            if dev > 0.005:
                result[i] = 1
            elif dev < -0.005:
                result[i] = -1
    return result


# ── 结构 ────────────────────────────────────────────────


def _calc_structure_quality(highs, lows, closes, lookback=30):
    """价格结构完整度 [0,1]"""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    if n < lookback:
        return result
    for i in range(lookback - 1, n):
        start = max(0, i - lookback + 1)
        window_h = highs[start:i + 1]
        window_l = lows[start:i + 1]
        window_c = closes[start:i + 1]
        w_len = len(window_c)
        if w_len < 20:
            result[i] = 0.5
            continue
        tr = np.maximum(
            (window_h - window_l)[1:],
            np.maximum(
                np.abs(window_h[1:] - window_c[:-1]),
                np.abs(window_l[1:] - window_c[:-1])
            )
        )
        if tr.mean() > 0:
            vol_cv = tr.std() / tr.mean()
            vol_stab = 1.0 / (1.0 + vol_cv)
        else:
            vol_stab = 0.5
        pk_cnt = 0
        for j in range(2, w_len - 2):
            if (window_h[j] >= window_h[j-2] and window_h[j] >= window_h[j-1] and
                window_h[j] >= window_h[j+1] and window_h[j] >= window_h[j+2]):
                pk_cnt += 1
            if (window_l[j] <= window_l[j-2] and window_l[j] <= window_l[j-1] and
                window_l[j] <= window_l[j+1] and window_l[j] <= window_l[j+2]):
                pk_cnt += 1
        pk_clarity = min(pk_cnt / (w_len * 0.2), 1.0)
        result[i] = 0.5 * vol_stab + 0.5 * pk_clarity
    return result


def _calc_gaps(opens, closes, highs, lows, threshold=0.005):
    """跳空检测"""
    opens = np.asarray(opens, dtype=float)
    closes = np.asarray(closes, dtype=float)
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    n = len(opens)
    gap_up = np.zeros(n, dtype=np.int8)
    gap_down = np.zeros(n, dtype=np.int8)
    for i in range(1, n):
        prev_close = closes[i - 1]
        if prev_close > 0:
            gap_ratio = (opens[i] - prev_close) / prev_close
            if gap_ratio > threshold:
                gap_up[i] = 1
                # 检测是否为真正跳空（最低价高于昨日收盘）
                if lows[i] > prev_close:
                    gap_up[i] = 1  # 向上缺口
            elif gap_ratio < -threshold:
                gap_down[i] = 1
                if highs[i] < prev_close:
                    gap_down[i] = 1  # 向下缺口
    return gap_up, gap_down


def _calc_bb_position(closes, bb_upper, bb_lower):
    """价格在布林带中的位置 [0,1]"""
    if closes is None or bb_upper is None or bb_lower is None:
        return None
    n = min(len(closes), len(bb_upper), len(bb_lower))
    result = np.full(n, np.nan)
    for i in range(n):
        if bb_upper[i] > bb_lower[i] and not np.isnan(closes[i]) and not np.isnan(bb_upper[i]) and not np.isnan(bb_lower[i]):
            result[i] = (closes[i] - bb_lower[i]) / (bb_upper[i] - bb_lower[i])
    return result


# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("  墨枢 Phase 1 — 因子回填 （TASK-2）")
    logger.info("  标的: 12只  |  因子: 50+ ")
    logger.info("=" * 60)

    conn = get_conn()
    try:
        init_factors_table(conn)

        total_records = 0
        for idx, code in enumerate(STOCK_CODES):
            logger.info("[%d/12] %s 加载行情数据...", idx + 1, code)
            df = load_stock_data(conn, code)
            if df.empty:
                logger.warning("  %s 无数据, 跳过", code)
                continue
            logger.info("  %s 共 %d 行数据", code, len(df))

            records = compute_all_factors(code, df)
            if not records:
                logger.warning("  %s 因子计算无产出", code)
                continue

            write_factors(conn, records)
            total_records += len(records)
            logger.info("  %s 因子写入 %d 条", code, len(records))

        logger.info("\n" + "=" * 60)
        logger.info("  因子回填完成!")
        logger.info("  总计写入: %d 条 x 50+ 因子", total_records)
        logger.info("=" * 60)

        # 验证
        cur = conn.execute("SELECT COUNT(*) as cnt FROM daily_factors")
        row = cur.fetchone()
        cur.execute("SELECT COUNT(DISTINCT code) as cnt FROM daily_factors")
        codes_ok = cur.fetchone()
        conn.execute("SELECT MIN(date), MAX(date) FROM daily_factors").fetchone()
        logger.info("  daily_factors 表: %d 条 / %d 只标的", row[0], codes_ok[0])
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
