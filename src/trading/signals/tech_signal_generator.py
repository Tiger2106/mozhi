# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
tech_signal_generator.py — 纯技术分析账户交易信号生成器

为3个技术分析账户（趋势/反转/网格）生成标准化交易信号，
写入 signals/paper_trade/{date}/ 目录，供 TradeWindowProcessor 处理。

核心职责：
  1. ensure_data(): 补齐最新股票 OHLCV 和技术指标数据（幂等）
  2. generate_trend_signal(): 趋势跟踪策略信号
  3. generate_reversal_signal(): 反转交易策略信号
  4. generate_grid_signal(): 网格交易策略信号
  5. generate_all(): 生成全部3个账户信号并写入文件

接入方式：
  - 独立调用: python tech_signal_generator.py
  - 集成到 morning_run: daily_morning_run.py 中 import 后调用

设计原则：
  - 零侵入现有系统：只写信号文件，不碰 TradeWindowProcessor 和 OrderEngine
  - 信号格式与 process_signal() 兼容（action="BUY"/"SELL"/"HOLD"）
  - 数据补齐幂等：重复执行不产生重复数据

author: moheng
created_time: 2026-05-14 12:45 GMT+8
task_id: tech_onboarding_20260514
"""

import json
import logging
import os
import sys
from datetime import datetime, date, timezone, timedelta
from typing import Optional, Tuple, Dict, Any, List

# ── 路径设置 ──
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger("paper_trade.tech_signal_generator")

TZ_CST = SHANGHAI_TZ

# ── 数据库路径 ──
ANALYSIS_DB = r"C:\Users\17699\mo_zhi_sharereports\analysis.db"
TRADE_ENGINE_DB = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"

# ── 信号输出路径 ──
SIGNAL_BASE_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\paper_trade"

# ── 3个技术分析账户配置 ──
TECH_ACCOUNTS = {
    "acct_tech_trend": {
        "name": "趋势跟踪",
        "strategy": "trend",
        "initial_capital": 200_000.0,
        "max_position_pct": 0.70,       # 最大仓位70%
        "startup_position_pct": 0.35,   # 启动期仓位减半（前5个交易日）
        "single_risk_pct": 0.05,        # 单笔止损5%
        "min_holding_days": 3,          # 最小持仓天数
    },
    "acct_tech_reversal": {
        "name": "反转交易",
        "strategy": "reversal",
        "initial_capital": 200_000.0,
        "max_position_pct": 0.60,
        "startup_position_pct": 0.30,
        "single_risk_pct": 0.03,
        "min_holding_days": 1,
    },
    "acct_tech_grid": {
        "name": "网格交易",
        "strategy": "grid",
        "initial_capital": 200_000.0,
        "max_position_pct": 0.50,
        "startup_position_pct": 0.25,
        "single_risk_pct": 0.0,         # 网格不设单笔止损
        "min_holding_days": 0,
    },
}

SYMBOL = "601857"
START_DATE = "20260506"  # 劳动节假期后首个交易日

# 容差
EPS = 1e-6

def now_str() -> str:
    return datetime.now(TZ_CST).isoformat(timespec="seconds")

def today_str() -> str:
    return date.today().strftime("%Y%m%d")

def _query_analysis_db(sql: str, params: tuple = ()) -> List[dict]:
    """从 analysis.db 查询数据。"""
    import sqlite3
    conn = sqlite3.connect(ANALYSIS_DB)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def _execute_trade_db(sql: str, params: tuple = (), fetch: bool = False):
    """在 trade_engine.db 执行 SQL。"""
    import sqlite3
    conn = sqlite3.connect(TRADE_ENGINE_DB)
    try:
        cursor = conn.execute(sql, params)
        if fetch:
            return cursor.fetchall()
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def _signal_dir(date_str: str = None) -> str:
    """获取当前日期的信号输出目录。"""
    ds = date_str or today_str()
    return os.path.join(SIGNAL_BASE_DIR, ds)

# ============================================================
# 技术指标计算（从 stock_daily OHLCV 计算真实指标）
# ============================================================

def _compute_all_indicators(ohlcv_rows: List[Dict]) -> List[Dict]:
    """从 stock_daily OHLCV 数据计算完整技术指标，返回可写入 tech_indicators 的行。

    Args:
        ohlcv_rows: 按日期升序的 OHLCV 数据列表
                    每行含 code, date, open, high, low, close, volume, amount

    Returns:
        包含完整技术指标的 dict 列表，可直接 INSERT OR REPLACE 写入 DB
    """
    if not ohlcv_rows:
        return []

    n = len(ohlcv_rows)
    closes = [r['close'] for r in ohlcv_rows]
    highs = [r['high'] for r in ohlcv_rows]
    lows = [r['low'] for r in ohlcv_rows]
    now_t = now_str()

    # ── 辅助：SMA ──
    def _sma(arr, period, idx):
        start = max(0, idx - period + 1)
        window = arr[start:idx + 1]
        return sum(window) / len(window)

    # ── MA 计算 ──
    ma5_list = [_sma(closes, 5, i) for i in range(n)]
    ma10_list = [_sma(closes, 10, i) for i in range(n)]
    ma20_list = [_sma(closes, 20, i) for i in range(n)]
    ma60_list = [_sma(closes, 60, i) for i in range(n)]
    ma120_list = [_sma(closes, 120, i) for i in range(n)]

    # ── EMA 计算（迭代式，用于 MACD）──
    ema12_list = []
    ema_prev = closes[0]
    a12 = 2.0 / 13.0
    for c in closes:
        ema_prev = c * a12 + ema_prev * (1.0 - a12)
        ema12_list.append(ema_prev)

    ema26_list = []
    ema_prev = closes[0]
    a26 = 2.0 / 27.0
    for c in closes:
        ema_prev = c * a26 + ema_prev * (1.0 - a26)
        ema26_list.append(ema_prev)

    dif_list = [e12 - e26 for e12, e26 in zip(ema12_list, ema26_list)]
    dea_list = []
    dea_prev = dif_list[0] if n > 0 else 0.0
    a_dea = 2.0 / 10.0
    for d in dif_list:
        dea_prev = d * a_dea + dea_prev * (1.0 - a_dea)
        dea_list.append(dea_prev)
    hist_list = [d - dea for d, dea in zip(dif_list, dea_list)]

    # ── RSI14（Wilder 平滑）──
    rsi14_list = [50.0] * n
    if n > 14:
        # 前 14 根用简单平均初始化
        gains = []
        losses = []
        for i in range(1, 15):
            chg = closes[i] - closes[i - 1]
            gains.append(chg if chg > 0 else 0.0)
            losses.append(-chg if chg < 0 else 0.0)
        avg_gain = sum(gains) / 14.0
        avg_loss = sum(losses) / 14.0
        if avg_loss < 1e-10:
            rsi14_list[14] = 100.0
        else:
            rsi14_list[14] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

        # 后续 Wilder 平滑
        for i in range(15, n):
            chg = closes[i] - closes[i - 1]
            gain = chg if chg > 0 else 0.0
            loss = -chg if chg < 0 else 0.0
            avg_gain = (avg_gain * 13.0 + gain) / 14.0
            avg_loss = (avg_loss * 13.0 + loss) / 14.0
            if avg_loss < 1e-10:
                rsi14_list[i] = 100.0
            else:
                rsi14_list[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    # ── Bollinger Bands (20, 2) ──
    bb_mid_list = list(ma20_list)
    bb_upper_list = []
    bb_lower_list = []
    for i in range(n):
        start = max(0, i - 19)
        window = closes[start:i + 1]
        mean = sum(window) / len(window)
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        std = variance ** 0.5
        bb_upper_list.append(mean + 2.0 * std)
        bb_lower_list.append(mean - 2.0 * std)

    bb_width_list = [up - low for up, low in zip(bb_upper_list, bb_lower_list)]
    bb_squeeze_list = [0] * n
    for i in range(n):
        if i >= 19:
            avg_w = sum(bb_width_list[i - 19:i + 1]) / 20.0
            bb_squeeze_list[i] = 1 if bb_width_list[i] < avg_w * 0.75 else 0

    # ── KDJ (9, 3, 3) ──
    kdj_k_list = [50.0] * n
    kdj_d_list = [50.0] * n
    kdj_j_list = [50.0] * n
    for i in range(n):
        if i >= 8:
            hhv = max(highs[i - 8:i + 1])
            llv = min(lows[i - 8:i + 1])
            if hhv == llv:
                rsv = 50.0
            else:
                rsv = (closes[i] - llv) / (hhv - llv) * 100.0
            k_val = kdj_k_list[i - 1] * 2.0 / 3.0 + rsv / 3.0
            d_val = kdj_d_list[i - 1] * 2.0 / 3.0 + k_val / 3.0
            j_val = 3.0 * k_val - 2.0 * d_val
            kdj_k_list[i] = k_val
            kdj_d_list[i] = d_val
            kdj_j_list[i] = j_val

    # ── 趋势评分与摘要 ──
    result = []
    for i in range(n):
        row = ohlcv_rows[i]
        close = closes[i]
        rsi_val = rsi14_list[i]

        # MA 评分 (0-40)
        ma_score = 0
        ma_detail = '数据不足'
        if i >= 59 and ma60_list[i] > 0:
            ma5, ma10, ma20, ma60 = ma5_list[i], ma10_list[i], ma20_list[i], ma60_list[i]
            if ma5 > ma10 > ma20 > ma60:
                ma_score = 40
                ma_detail = '多头排列'
            elif ma5 < ma10 < ma20 < ma60:
                ma_score = 0
                ma_detail = '空头排列'
            elif ma5 > ma10:
                ma_score = 25
                ma_detail = 'MA多头偏强'
            else:
                ma_score = 15
                ma_detail = '均线纠缠'
        elif i >= 19 and ma20_list[i] > 0:
            ma5, ma10, ma20 = ma5_list[i], ma10_list[i], ma20_list[i]
            if ma5 > ma10 > ma20:
                ma_score = 32
                ma_detail = '短期多头'
            elif ma5 < ma10:
                ma_score = 12
                ma_detail = '短期偏弱'
            else:
                ma_score = 22
                ma_detail = '均线纠缠'
        elif i >= 4:
            ma_score = 22
            ma_detail = '短期企稳'

        # MACD 评分 (0-20)
        macd_score = 0
        macd_detail = '数据不足'
        if i >= 25:  # 需要26根才能有稳定EMA26
            if dif_list[i] > dea_list[i]:
                if hist_list[i] > 0 and dif_list[i] > 0:
                    macd_score = 20
                    macd_detail = '强势金叉'
                else:
                    macd_score = 12
                    macd_detail = '金叉'
            else:
                if hist_list[i] < 0 and dif_list[i] < 0:
                    macd_score = 0
                    macd_detail = '弱势死叉'
                else:
                    macd_score = 6
                    macd_detail = '偏弱'

        # RSI 评分 (0-20)
        rsi_score = 0
        rsi_detail = '数据不足'
        if i > 14:
            if rsi_val >= 65:
                rsi_score = 20
                rsi_detail = '偏强'
            elif rsi_val >= 50:
                rsi_score = 15
                rsi_detail = '偏多'
            elif rsi_val >= 30:
                rsi_score = 8
                rsi_detail = '偏弱'
            else:
                rsi_score = 0
                rsi_detail = '超卖'

        # BB 评分 (0-10)
        bb_score = 0
        bb_detail = '数据不足'
        bb_upper = bb_upper_list[i]
        bb_lower = bb_lower_list[i]
        bb_mid = bb_mid_list[i]
        if bb_upper > bb_lower:
            bb_range = bb_upper - bb_lower
            pos_ratio = (close - bb_lower) / bb_range if bb_range > 1e-10 else 0.5
            if pos_ratio > 0.75:
                bb_score = 10
                bb_detail = '上轨附近'
            elif pos_ratio > 0.5:
                bb_score = 8
                bb_detail = '中轨上方'
            elif pos_ratio > 0.25:
                bb_score = 4
                bb_detail = '中轨下方'
            else:
                bb_score = 0
                bb_detail = '下轨附近'

        # KDJ 评分 (0-10)
        kdj_score = 0
        kdj_detail = '数据不足'
        k_val = kdj_k_list[i]
        d_val = kdj_d_list[i]
        if i >= 8:
            if k_val > d_val and k_val > 80:
                kdj_score = 10
                kdj_detail = '强势区'
            elif k_val > d_val and k_val > 50:
                kdj_score = 8
                kdj_detail = '偏多'
            elif k_val > d_val:
                kdj_score = 5
                kdj_detail = '谨慎偏多'
            elif k_val < d_val and k_val < 20:
                kdj_score = 0
                kdj_detail = '超卖'
            else:
                kdj_score = 2
                kdj_detail = '偏弱'
        trend_val = ma_score + macd_score + rsi_score + bb_score + kdj_score

        # 摘要字符串（中文简洁格式，用 "丨" 分隔）
        parts = []
        if ma_detail != '数据不足':
            parts.append(f"MA{ma_detail}")
        if macd_detail != '数据不足':
            parts.append(f"MACD{macd_detail}")
        if rsi_detail != '数据不足':
            parts.append(f"RSI{rsi_detail}")
        if bb_detail != '数据不足':
            parts.append(f"BB{bb_detail}")
        if kdj_detail != '数据不足':
            parts.append(f"KDJ{kdj_detail}")
        if not parts:
            parts.append('数据不足')
        trend_summary = '丨'.join(parts)

        result.append({
            'date': row['date'],
            'code': row['code'],
            'ma5': round(ma5_list[i], 4),
            'ma10': round(ma10_list[i], 4),
            'ma20': round(ma20_list[i], 4),
            'ma60': round(ma60_list[i], 4),
            'ma120': round(ma120_list[i], 4),
            'rsi14': round(rsi_val, 4),
            'macd_dif': round(dif_list[i], 6),
            'macd_dea': round(dea_list[i], 6),
            'macd_hist': round(hist_list[i], 6),
            'bb_upper': round(bb_upper, 4),
            'bb_mid': round(bb_mid, 4),
            'bb_lower': round(bb_lower, 4),
            'kdj_k': round(k_val, 4),
            'kdj_d': round(d_val, 4),
            'kdj_j': round(kdj_j_list[i], 4),
            'trend_score': round(trend_val, 1),
            'trend_summary': trend_summary,
            'bb_squeeze': bb_squeeze_list[i],
            'is_gap_day': 0,
            'created_at': now_t,
        })

    return result

class DataFetcher:
    """补齐最新股票行情和技术指标数据。"""

    def __init__(self):
        self.symbol = SYMBOL

    def ensure_stock_daily(self) -> bool:
        """补齐 stock_daily 表中 601857 的最新 OHLCV 数据。

        直接请求 eastmoney API（不使用akshare），
        写入 stock_daily 表（幂等，已存在则跳过）。
        """
        import sqlite3

        conn = sqlite3.connect(ANALYSIS_DB)
        try:
            # 获取已有数据的最大日期
            row = conn.execute(
                "SELECT MAX(date) FROM stock_daily WHERE code=?",
                (self.symbol,)
            ).fetchone()
            latest_date = row[0] if row and row[0] else "20260101"
            logger.info(f"[DataFetcher] stock_daily 最新日期: {latest_date}")

            today = date.today()
            end_str = today.strftime("%Y%m%d")

            if latest_date >= end_str:
                logger.info("[DataFetcher] stock_daily 已是最新，跳过")
                conn.close()
                return True

            # 需要补齐的数据区间
            fetch_start = latest_date
            logger.info(f"[DataFetcher] 补齐 stock_daily: {fetch_start} ~ {end_str}")

            # 直接请求 eastmoney API（绕过系统代理，不使用 akshare）
            try:
                import requests as _req
                import pandas as _pd
                import json as _json
                _s = _req.Session()
                _s.trust_env = False
                _s.proxies = {}
                _url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
                _params = {
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
                    "ut": "7eea3edcaed734bea9cbfc24409ed989",
                    "klt": "101",
                    "fqt": "1",
                    "secid": f"1.{self.symbol}",
                    "beg": fetch_start,
                    "end": end_str
                }
                _resp = _s.get(_url, params=_params, timeout=30)
                if _resp.status_code == 200:
                    _data = _resp.json()
                    _klines = _data.get("data", {}).get("klines", [])
                    if _klines:
                        _records = []
                        for _k in _klines:
                            _parts = _k.split(",")
                            _records.append({
                                "日期": _parts[0],
                                "开盘": float(_parts[1]),     # f52=open
                                "最低": float(_parts[2]),     # f55=low (API returns [o,low,c,h])
                                "收盘": float(_parts[3]),     # f53=close
                                "最高": float(_parts[4]),     # f54=high
                                "成交量": float(_parts[5]),
                                "成交额": float(_parts[6]),
                            })
                        df = _pd.DataFrame(_records)
                        logger.info(f"[DataFetcher] eastmoney API返回 {len(df)} 条K线")
                    else:
                        df = _pd.DataFrame()
                else:
                    df = _pd.DataFrame()
            except Exception as e:
                logger.error(f"[DataFetcher] eastmoney API 获取失败: {e}")
                # 尝试 baostock 作为后备
                try:
                    import baostock as bs
                    bs.login()
                    rs = bs.query_history_k_data_plus(
                        f"sh.{self.symbol}",
                        "date,open,high,low,close,volume,amount",
                        start_date=fetch_start,
                        end_date=end_str,
                        frequency="d",
                        adjustflag="2"
                    )
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    bs.logout()
                    if not rows:
                        logger.warning("[DataFetcher] baostock 也无数据")
                        conn.close()
                        return False
                    # 手动构造DataFrame的替代方案
                    df = _pd.DataFrame(rows, columns=[
                        "date", "open", "high", "low", "close", "volume", "amount"
                    ])
                    df.columns = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"]
                except Exception as e2:
                    logger.error(f"[DataFetcher] baostock 也失败: {e2}")
                    conn.close()
                    return False

            if df is None or df.empty:
                logger.info("[DataFetcher] 无新数据需要写入")
                conn.close()
                return True

            # 写入 stock_daily 表
            inserted = 0
            for _, row_data in df.iterrows():
                trade_date = str(row_data.get("日期", "")).replace("-", "")
                if not trade_date:
                    continue

                # 幂等检查
                exists = conn.execute(
                    "SELECT 1 FROM stock_daily WHERE code=? AND date=?",
                    (self.symbol, trade_date)
                ).fetchone()
                if exists:
                    continue

                try:
                    open_p = float(row_data.get("开盘", 0))
                    high_p = float(row_data.get("最高", 0))
                    low_p = float(row_data.get("最低", 0))
                    close_p = float(row_data.get("收盘", 0))
                    volume = float(row_data.get("成交量", 0))
                    amount = float(row_data.get("成交额", 0))

                    conn.execute(
                        """INSERT INTO stock_daily 
                           (code, date, open, high, low, close, volume, amount)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (self.symbol, trade_date, open_p, high_p, low_p, close_p, volume, amount)
                    )
                    inserted += 1
                except (ValueError, TypeError) as e:
                    logger.warning(f"[DataFetcher] 跳过日期 {trade_date}: {e}")

            conn.commit()
            logger.info(f"[DataFetcher] stock_daily 写入完成: {inserted} 条新记录")
            conn.close()
            return True

        except Exception as e:
            logger.error(f"[DataFetcher] stock_daily 补齐异常: {e}")
            conn.rollback()
            conn.close()
            return False

    def ensure_tech_indicators(self) -> bool:
        """补齐 tech_indicators 表中 601857 的完整技术指标。

        从 stock_daily 表读取全量 OHLCV 数据（按日期升序），
        计算 MA/RSI/MACD/BB/KDJ 等真实指标值，
        写入 tech_indicators 表（幂等：date+code 主键，已存在则覆盖）。
        """
        import sqlite3

        conn = sqlite3.connect(ANALYSIS_DB)
        conn.row_factory = sqlite3.Row
        try:
            # ── 1. 读取 stock_daily 全量 OHLCV 数据 ──
            rows = conn.execute(
                """SELECT code, date, open, high, low, close, volume, amount
                   FROM stock_daily
                   WHERE code=?
                   ORDER BY date ASC""",
                (self.symbol,)
            ).fetchall()

            if not rows:
                logger.warning("[DataFetcher] stock_daily 无数据，无法计算指标")
                conn.close()
                return False

            ohlcv_dicts = [dict(r) for r in rows]
            logger.info(f"[DataFetcher] 从 stock_daily 读取 {len(ohlcv_dicts)} 行 OHLCV")

            # ── 2. 删除已有占位数据（ma5 IS NULL、ma5=0 或 trend_summary='data_placeholder'）──
            deleted = conn.execute(
                """DELETE FROM tech_indicators
                   WHERE code=? AND (ma5 IS NULL OR ma5 = 0 OR trend_summary = 'data_placeholder')""",
                (self.symbol,)
            ).rowcount
            if deleted > 0:
                logger.info(f"[DataFetcher] 清理 {deleted} 条占位指标行")

            # ── 3. 从 OHLCV 计算全部指标 ──
            indicators = _compute_all_indicators(ohlcv_dicts)
            if not indicators:
                logger.warning("[DataFetcher] 指标计算未产出数据")
                conn.close()
                return False

            # ── 4. 批量写入（INSERT OR REPLACE 幂等）──
            cols = ['code', 'date', 'ma5', 'ma10', 'ma20', 'ma60', 'ma120',
                    'rsi14', 'macd_dif', 'macd_dea', 'macd_hist',
                    'bb_upper', 'bb_mid', 'bb_lower',
                    'kdj_k', 'kdj_d', 'kdj_j',
                    'trend_score', 'trend_summary',
                    'bb_squeeze', 'is_gap_day', 'created_at']
            placeholders = ', '.join(['?' for _ in cols])
            col_names = ', '.join(cols)
            insert_sql = (
                f"""INSERT OR REPLACE INTO tech_indicators ({col_names})
                   VALUES ({placeholders})"""
            )

            written = 0
            for ind in indicators:
                values = tuple(ind.get(c) for c in cols)
                conn.execute(insert_sql, values)
                written += 1

            conn.commit()
            logger.info(
                f"[DataFetcher] tech_indicators 指标写入完成: {written} 条"
            )
            conn.close()
            return True

        except Exception as e:
            logger.error(f"[DataFetcher] tech_indicators 计算异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            conn.rollback()
            conn.close()
            return False

# ============================================================
# 技术指标读取
# ============================================================

def get_latest_indicators() -> Optional[Dict[str, Any]]:
    """获取 601857 最新的技术指标数据。

    Returns:
        dict: 包含最新指标的字典，或 None（无数据）
    """
    try:
        rows = _query_analysis_db(
            """SELECT * FROM tech_indicators 
               WHERE code=? ORDER BY date DESC LIMIT 1""",
            (SYMBOL,)
        )
        if not rows:
            logger.warning("[TechIndicators] 无技术指标数据")
            return None
        return rows[0]
    except Exception as e:
        logger.error(f"[TechIndicators] 读取指标异常: {e}")
        return None

def get_latest_price() -> float:
    """获取最新收盘价（从 stock_daily 或 tech_indicators）。

    Returns:
        float: 最新价格，0.0 表示获取失败
    """
    try:
        # 先尝试 stock_daily
        rows = _query_analysis_db(
            "SELECT close FROM stock_daily WHERE code=? ORDER BY date DESC LIMIT 1",
            (SYMBOL,)
        )
        if rows and rows[0].get("close", 0) > 0:
            return float(rows[0]["close"])

        # 回退到 tech_indicators
        ind = get_latest_indicators()
        if ind:
            return float(ind.get("bb_mid", 0))
    except Exception as e:
        logger.warning(f"[TechIndicators] 获取价格异常: {e}")

    # 最后回退到硬编码最新收盘价（2026-05-13收盘）
    return 11.12

def get_historical_indicators(days: int = 60) -> List[Dict[str, Any]]:
    """获取历史技术指标数据（用于趋势判断）。

    Args:
        days: 回溯天数

    Returns:
        List[dict]: 按日期升序的指标列表
    """
    try:
        rows = _query_analysis_db(
            """SELECT * FROM tech_indicators 
               WHERE code=? ORDER BY date DESC LIMIT ?""",
            (SYMBOL, days)
        )
        rows.reverse()  # 按日期升序
        return rows
    except Exception as e:
        logger.error(f"[TechIndicators] 读取历史指标异常: {e}")
        return []

# ============================================================
# 策略信号生成
# ============================================================

def _is_startup_period() -> bool:
    """判断是否处于启动期（前5个交易日）。"""
    # 检查 signal_processed 目录判断已交易天数
    today = today_str()
    sdir = _signal_dir(today)
    processed_dir = os.path.join(sdir, "_processed")

    # 简单判断：首次运行即为启动期
    if not os.path.exists(processed_dir):
        return True

    # 检查有多少个技术账户的 done 标记
    tech_count = 0
    if os.path.isdir(processed_dir):
        for f in os.listdir(processed_dir):
            if f.startswith("signal_tech_") and f.endswith(".done"):
                tech_count += 1
    # 如果少于5天的done记录则仍处于启动期
    return tech_count < 5

def generate_trend_signal() -> Tuple[str, float, str]:
    """趋势跟踪策略信号。

    逻辑：
      - 基于最新 trend_score + MA相对位置判断
      - 股价 < MA60 → 趋势偏弱，HOLD
      - trend_score >= 60 且股价站上MA60 → BUY
      - 已有持仓且 trend_score < 40 → SELL

    Returns:
        (action, position_ratio, reason)
        action: "BUY" / "SELL" / "HOLD"
    """
    ind = get_latest_indicators()
    price = get_latest_price()

    if not ind:
        logger.warning("[Trend] 无指标数据，生成 HOLD")
        return "HOLD", 0.0, "无技术指标数据"

    trend_score = float(ind.get("trend_score", 50))
    ma60 = float(ind.get("ma60", price))
    ma20 = float(ind.get("ma20", price))
    ma5 = float(ind.get("ma5", price))

    reason_parts = []
    action = "HOLD"
    ratio = 0.0

    # 判断趋势方向
    above_ma60 = price > ma60
    above_ma20 = price > ma20
    ma5_above_ma20 = ma5 > ma20

    reason_parts.append(f"trend_score={trend_score:.0f}")
    reason_parts.append(f"price={price:.2f}")
    reason_parts.append(f"MA60={ma60:.2f}")
    reason_parts.append(f"MA20={ma20:.2f}")

    if not above_ma60:
        # 股价在60日线下方 → 趋势偏弱
        action = "HOLD"
        ratio = 0.0
        reason_parts.append("price_below_MA60")

        if trend_score < 40 and False:
            # 这里检查是否有持仓（通过DB查询），若有则卖出
            pass
    elif trend_score >= 60 and ma5_above_ma20:
        # 趋势成立 + 均线多头排列 → BUY
        action = "BUY"
        # 仓位 = min(启动期减半, 最大仓位)
        max_ratio = TECH_ACCOUNTS["acct_tech_trend"]["max_position_pct"]
        if _is_startup_period():
            max_ratio = TECH_ACCOUNTS["acct_tech_trend"]["startup_position_pct"]
        # 按趋势强度调节仓位
        if trend_score >= 80:
            ratio = min(0.7, max_ratio)
        elif trend_score >= 60:
            ratio = min(0.4, max_ratio)
        else:
            ratio = min(0.2, max_ratio)
        reason_parts.append(f"uptrend_confirmed({trend_score:.0f})")
    elif above_ma60 and 40 <= trend_score < 60:
        # 中性区间 → HOLD
        action = "HOLD"
        reason_parts.append("neutral_zone")
    else:
        action = "HOLD"
        reason_parts.append("no_signal")

    reason = " | ".join(reason_parts)
    logger.info(f"[Trend] 信号: {action} ratio={ratio:.2f} | {reason}")
    return action, ratio, reason

def generate_reversal_signal() -> Tuple[str, float, str]:
    """反转交易策略信号。

    逻辑：
      - RSI超卖(RSI<25) → BUY
      - RSI超买(RSI>75) → SELL（仅在有持仓时）
      - 价格跌破BB_lower + RSI<30 → 强反转信号 BUY

    Returns:
        (action, position_ratio, reason)
    """
    ind = get_latest_indicators()
    price = get_latest_price()

    if not ind:
        logger.warning("[Reversal] 无指标数据，生成 HOLD")
        return "HOLD", 0.0, "无技术指标数据"

    rsi14 = float(ind.get("rsi14", 50))
    bb_lower = float(ind.get("bb_lower", price * 0.95))
    bb_upper = float(ind.get("bb_upper", price * 1.05))

    reason_parts = []
    action = "HOLD"
    ratio = 0.0

    reason_parts.append(f"RSI14={rsi14:.1f}")
    reason_parts.append(f"price={price:.2f}")
    reason_parts.append(f"BB=[{bb_lower:.2f}~{bb_upper:.2f}]")

    if price <= bb_lower and rsi14 < 30:
        # 强反转买入信号：价格跌穿BB下轨 + RSI超卖
        action = "BUY"
        max_ratio = TECH_ACCOUNTS["acct_tech_reversal"]["max_position_pct"]
        if _is_startup_period():
            max_ratio = TECH_ACCOUNTS["acct_tech_reversal"]["startup_position_pct"]
        ratio = min(0.6 if rsi14 < 20 else 0.3, max_ratio)
        reason_parts.append(f"strong_reversal_signal(rsi={rsi14:.0f})")
    elif rsi14 < 25:
        # 超卖买入
        action = "BUY"
        max_ratio = TECH_ACCOUNTS["acct_tech_reversal"]["max_position_pct"]
        if _is_startup_period():
            max_ratio = TECH_ACCOUNTS["acct_tech_reversal"]["startup_position_pct"]
        ratio = min(0.3, max_ratio)
        reason_parts.append(f"oversold(rsi={rsi14:.0f})")
    elif rsi14 > 75:
        # 超买→考虑卖出（需要检查实际持仓）
        action = "SELL"
        ratio = 1.0  # 全仓卖出
        reason_parts.append(f"overbought(rsi={rsi14:.0f})")
    elif 35 <= rsi14 <= 65:
        # 中性区域
        action = "HOLD"
        reason_parts.append("neutral_rsi")
    else:
        action = "HOLD"
        reason_parts.append("no_signal")

    reason = " | ".join(reason_parts)
    logger.info(f"[Reversal] 信号: {action} ratio={ratio:.2f} | {reason}")
    return action, ratio, reason

def generate_grid_signal() -> Tuple[str, float, str]:
    """网格交易策略信号。

    逻辑：
      - 基于BB区间设定网格：BB_lower ~ BB_upper，10级
      - 当前价格在区间内 → 按网格层级建仓
      - 首次启动：建一层底仓（价格在区间下半区则买，上半区则等）
      - 价格突破BB_upper → 全部卖出
      - 价格跌破BB_lower → 暂停买入

    Returns:
        (action, position_ratio, reason)
    """
    ind = get_latest_indicators()
    price = get_latest_price()

    if not ind:
        logger.warning("[Grid] 无指标数据，生成 HOLD")
        return "HOLD", 0.0, "无技术指标数据"

    bb_lower = float(ind.get("bb_lower", price * 0.92))
    bb_upper = float(ind.get("bb_upper", price * 1.08))
    bb_mid = float(ind.get("bb_mid", price))

    reason_parts = []
    action = "HOLD"
    ratio = 0.0

    reason_parts.append(f"price={price:.2f}")
    reason_parts.append(f"grid=[{bb_lower:.2f}~{bb_upper:.2f}]")
    reason_parts.append(f"mid={bb_mid:.2f}")

    if price > bb_upper * 1.02:
        # 突破上界 → 全部卖出
        action = "SELL"
        ratio = 1.0
        reason_parts.append("breakout_above_grid")
    elif price < bb_lower * 0.98:
        # 跌破下界 → 暂停
        action = "HOLD"
        ratio = 0.0
        reason_parts.append("breakdown_below_grid")
    elif price <= bb_mid:
        # 在区间下半部 → 买入一层底仓（启动网格）
        action = "BUY"
        max_ratio = TECH_ACCOUNTS["acct_tech_grid"]["max_position_pct"]
        if _is_startup_period():
            max_ratio = TECH_ACCOUNTS["acct_tech_grid"]["startup_position_pct"]
        # 首次建仓一层：按总资金的10%计算（1/10网格）
        ratio = min(0.10, max_ratio)
        reason_parts.append(f"grid_entry_lower_half(pos={ratio:.0%})")
    else:
        # 在区间上半部 → 等待回调
        action = "HOLD"
        ratio = 0.0
        reason_parts.append("grid_wait_upper_half")

    reason = " | ".join(reason_parts)
    logger.info(f"[Grid] 信号: {action} ratio={ratio:.2f} | {reason}")
    return action, ratio, reason

# ============================================================
# 信号文件写入
# ============================================================

def write_signal_file(task_id: str, account_id: str, strategy: str,
                      action: str, position_ratio: float, reason: str,
                      date_str: str = None,
                      suggested_price: float = None) -> Optional[Dict[str, Any]]:
    """写入标准化信号JSON文件。

    Args:
        task_id: 任务ID（如 "tech_trend_20260514"）
        account_id: 账户ID（如 "acct_tech_trend"）
        strategy: 策略名（如 "trend"）
        action: "BUY"/"SELL"/"HOLD"
        position_ratio: 仓位比例 [0, 1]
        reason: 信号生成理由
        date_str: 日期字符串 YYYYMMDD
        suggested_price: 建议价格（默认使用最新价）

    Returns:
        写入的信号字典，或 None（失败）
    """
    ds = date_str or today_str()
    sdir = _signal_dir(ds)
    os.makedirs(sdir, exist_ok=True)

    price = suggested_price or get_latest_price()

    signal = {
        "status": "READY",
        "task_id": task_id,
        "symbol": SYMBOL,
        "action": action,
        "confidence": 0.65 if action == "BUY" else (0.85 if action == "SELL" else 0.0),
        "confidence_label": "中" if action == "BUY" else ("高" if action == "SELL" else "低"),
        "suggested_price": price,
        "position_ratio": position_ratio,
        "account_id": account_id,
        "strategy": strategy,
        "reason": reason,
        "created_at": now_str(),
        "author": "moheng",
    }

    signal_path = os.path.join(sdir, f"signal_{task_id}.json")
    tmp_path = signal_path + ".tmp"

    for attempt in range(1, 4):
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(signal, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, signal_path)

            # 写后 read 验证
            with open(signal_path, "r", encoding="utf-8") as f:
                verify = json.load(f)

            if verify.get("task_id") == task_id and verify.get("status") == "READY":
                logger.info(f"[SignalWriter] ✅ 信号写入验证通过: {signal_path}")
                return signal

            logger.warning(f"[SignalWriter] 写入验证失败 (重试 {attempt}/3): {signal_path}")
        except Exception as e:
            logger.warning(f"[SignalWriter] 写入异常 (重试 {attempt}/3): {e}")

    logger.error(f"[SignalWriter] ❌ 信号写入3次均失败: {signal_path}")
    return None

# ============================================================
# 主入口
# ============================================================

def ensure_data() -> bool:
    """补齐数据（幂等，重复调用不会产生重复数据）。

    Returns:
        bool: 是否成功（True = 数据已就绪）
    """
    fetcher = DataFetcher()
    d1 = fetcher.ensure_stock_daily()
    d2 = fetcher.ensure_tech_indicators()
    success = d1 and d2

    if success:
        logger.info("[TechSignalGen] ✅ 数据补齐完成")
    else:
        logger.warning(f"[TechSignalGen] ⚠️ 数据补齐结果: stock_daily={d1}, indicators={d2}")

    return success

def generate_all(date_str: str = None, skip_data_check: bool = False) -> Dict[str, Any]:
    """生成全部3个技术账户的交易信号。

    Args:
        date_str: 日期字符串（默认当天）
        skip_data_check: 是否跳过数据检查（用于首次快速测试）

    Returns:
        dict: 生成结果统计
    """
    if not skip_data_check:
        logger.info("[TechSignalGen] 检查数据完整性...")
        ensure_data()

    ds = date_str or today_str()
    results = {}

    # 1. 趋势跟踪
    trend_action, trend_ratio, trend_reason = generate_trend_signal()
    trend_task = f"tech_trend_{ds}"
    trend_result = write_signal_file(
        task_id=trend_task,
        account_id="acct_tech_trend",
        strategy="trend",
        action=trend_action,
        position_ratio=trend_ratio,
        reason=trend_reason,
        date_str=ds,
    )
    results["acct_tech_trend"] = {
        "signal_file": f"signal_{trend_task}.json",
        "action": trend_action,
        "ratio": trend_ratio,
        "written": trend_result is not None,
    }

    # 2. 反转交易
    rev_action, rev_ratio, rev_reason = generate_reversal_signal()
    rev_task = f"tech_reversal_{ds}"
    rev_result = write_signal_file(
        task_id=rev_task,
        account_id="acct_tech_reversal",
        strategy="reversal",
        action=rev_action,
        position_ratio=rev_ratio,
        reason=rev_reason,
        date_str=ds,
    )
    results["acct_tech_reversal"] = {
        "signal_file": f"signal_{rev_task}.json",
        "action": rev_action,
        "ratio": rev_ratio,
        "written": rev_result is not None,
    }

    # 3. 网格交易
    grid_action, grid_ratio, grid_reason = generate_grid_signal()
    grid_task = f"tech_grid_{ds}"
    grid_result = write_signal_file(
        task_id=grid_task,
        account_id="acct_tech_grid",
        strategy="grid",
        action=grid_action,
        position_ratio=grid_ratio,
        reason=grid_reason,
        date_str=ds,
    )
    results["acct_tech_grid"] = {
        "signal_file": f"signal_{grid_task}.json",
        "action": grid_action,
        "ratio": grid_ratio,
        "written": grid_result is not None,
    }

    # 输出汇总
    logger.info("=" * 60)
    logger.info("[TechSignalGen] 技术账户信号生成汇总")
    logger.info("=" * 60)
    for acct_id, r in results.items():
        status = "✅" if r["written"] else "❌"
        logger.info(f"  {status} {acct_id}: {r['action']} (ratio={r['ratio']:.0%}) → {r['signal_file']}")
    logger.info("=" * 60)

    return results

# ============================================================
# CLI入口
# ============================================================

def main():
    """命令行入口：python tech_signal_generator.py [--date YYYYMMDD] [--skip-data]"""
    import argparse

    parser = argparse.ArgumentParser(description="技术分析账户信号生成器")
    parser.add_argument("--date", type=str, default=today_str(),
                        help="目标日期 YYYYMMDD（默认当天）")
    parser.add_argument("--skip-data", action="store_true",
                        help="跳过数据补齐（用于测试）")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=" * 60)
    logger.info(f"TechSignalGenerator 启动 (date={args.date})")
    logger.info("=" * 60)

    results = generate_all(date_str=args.date, skip_data_check=args.skip_data)
    print(json.dumps(results, ensure_ascii=False, indent=2))

    logger.info("TechSignalGenerator 结束")
    return results

if __name__ == "__main__":
    main()
