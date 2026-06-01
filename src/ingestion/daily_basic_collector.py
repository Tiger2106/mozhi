"""
daily_basic_collector.py — A50估值数据采集脚本

从 Tushare daily_basic API 获取估值指标（pe/pe_ttm/pb/ps_ttm等），
写入 a50_daily_basic 表，支持单标的/批量/全历史回填。

Author: moheng, 2026-05-31
"""

import csv
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data', 'market', 'a50_ic.db'
)

# 可从 Tushare daily_basic 获得的字段
ALL_FIELDS = [
    'ts_code', 'trade_date',
    'pe',           # 动态市盈率
    'pe_ttm',       # 滚动市盈率
    'pb',           # 市净率
    'ps_ttm',       # 市销率（TTM，需2000积分）
    'pcf_ttm',      # 市现率（TTM，需2000积分）
    'dividend_yield', # dv_ratio 是 Tushare API 实际字段名；股息率（需2000积分）
    'float_share',  # 流通股本
    'total_share',  # 总股本
    'circ_mv',      # 流通市值
]

# 必需字段（缺失则跳过该 stocks 的采集）
REQUIRED_FIELDS = ['ts_code', 'trade_date']

# A50 成分股代码（含后缀）
A50_CONSTITUENTS = [
    '601857.SH',  # 中国石油
    '600519.SH',  # 贵州茅台
    '000333.SZ',  # 美的集团
    '600036.SH',  # 招商银行
    '601318.SH',  # 中国平安
    '300750.SZ',  # 宁德时代
    '000858.SZ',  # 五粮液
    '601166.SH',  # 兴业银行
    '600900.SH',  # 长江电力
    '600276.SH',  # 恒瑞医药
    '002594.SZ',  # 比亚迪
    '600887.SH',  # 伊利股份
    '002415.SZ',  # 海康威视
    '601012.SH',  # 隆基绿能
    '600030.SH',  # 中信证券
    '000001.SZ',  # 平安银行
    '600585.SH',  # 海螺水泥
    '601398.SH',  # 工商银行
    '601939.SH',  # 建设银行
    '601288.SH',  # 农业银行
    '601328.SH',  # 交通银行
    '600028.SH',  # 中国石化
    '601088.SH',  # 中国神华
    '600104.SH',  # 上汽集团
    '600690.SH',  # 海尔智家
    '000002.SZ',  # 万科A
    '002304.SZ',  # 洋河股份
    '601668.SH',  # 中国建筑
    '601601.SH',  # 中国太保
    '601211.SH',  # 国泰君安
    '600016.SH',  # 民生银行
    '600000.SH',  # 浦发银行
    '600048.SH',  # 保利发展
    '002142.SZ',  # 宁波银行
    '601229.SH',  # 上海银行
    '601169.SH',  # 北京银行
    '601818.SH',  # 光大银行
    '000725.SZ',  # 京东方A
    '600009.SH',  # 上海机场
    '600031.SH',  # 三一重工
    '000568.SZ',  # 泸州老窖
    '002714.SZ',  # 牧原股份
    '601138.SH',  # 工业富联
    '688981.SH',  # 中芯国际
    '300760.SZ',  # 迈瑞医疗
    '300124.SZ',  # 汇川技术
    '002230.SZ',  # 科大讯飞
    '603259.SH',  # 药明康德
    '300274.SZ',  # 阳光电源
    '000651.SZ',  # 格力电器
]


# ── Token 加载 ────────────────────────────────────────────

class TokenLoader:
    """Tushare Token 加载器"""

    _token_cache: Optional[str] = None

    @classmethod
    def get_token(cls) -> str:
        if cls._token_cache is not None:
            return cls._token_cache

        # 检查 ~/tk.csv
        home_csv = os.path.join(os.path.expanduser('~'), 'tk.csv')
        if not os.path.exists(home_csv):
            raise FileNotFoundError(f'Token file not found: {home_csv}')

        with open(home_csv, 'r', encoding='utf-8') as f:
            rows = list(csv.reader(f))

        if len(rows) < 2:
            raise ValueError(f'Invalid token file format: {home_csv}')

        token = rows[1][0].strip()
        if not token:
            raise ValueError('Empty token value')

        cls._token_cache = token
        return token

    @classmethod
    def get_pro_api(cls):
        """获取 Tushare Pro API 实例"""
        import tushare as ts
        token = cls.get_token()
        ts.set_token(token)
        return ts.pro_api()


# ── 数据库操作 ────────────────────────────────────────────

def ensure_a50_daily_basic_table(db_path: str) -> bool:
    """确保 a50_daily_basic 表存在（CREATE TABLE IF NOT EXISTS）

    Args:
        db_path: SQLite 数据库路径

    Returns:
        True 创建成功
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS a50_daily_basic (
                code            TEXT    NOT NULL,
                date            TEXT    NOT NULL,  -- YYYYMMDD
                pe              REAL,
                pe_ttm          REAL,
                pb              REAL,
                ps_ttm          REAL,
                pcf_ttm         REAL,
                dividend_yield  REAL,
                float_share     REAL,
                total_share     REAL,
                circ_mv         REAL,
                source_version  TEXT    NOT NULL DEFAULT 'v1',
                created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (code, date)
            )
        ''')
        conn.commit()
        logger.info('Table a50_daily_basic ensured')
        return True
    except Exception as e:
        logger.error(f'Failed to create a50_daily_basic table: {e}')
        return False
    finally:
        conn.close()


def get_existing_dates(db_path: str, code: str) -> set:
    """查询某标的已有数据日期

    Args:
        db_path: 数据库路径
        code: 标的代码（6位，不含后缀）

    Returns:
        已写入的 date 集合
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            'SELECT date FROM a50_daily_basic WHERE code = ?',
            (code,)
        )
        return {row[0] for row in cur.fetchall()}
    except Exception:
        return set()
    finally:
        conn.close()


def write_batch(db_path: str, records: List[dict]):
    """批量写入 a50_daily_basic（INSERT OR REPLACE）

    Args:
        db_path: 数据库路径
        records: 写入记录列表
    """
    if not records:
        return

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            '''INSERT OR REPLACE INTO a50_daily_basic
               (code, date, pe, pe_ttm, pb, ps_ttm, float_share, total_share, circ_mv, dividend_yield)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [(r['code'], r['date'],
              r.get('pe'), r.get('pe_ttm'), r.get('pb'), r.get('ps_ttm'),
              r.get('float_share'), r.get('total_share'), r.get('circ_mv'), r.get('dividend_yield'))
             for r in records]
        )
        conn.commit()
        logger.info(f'Wrote {len(records)} rows to a50_daily_basic')
    except Exception as e:
        logger.error(f'Write batch failed: {e}')
        conn.rollback()
    finally:
        conn.close()


# ── 采集核心 ──────────────────────────────────────────────

def collect_single(
    pro_api,
    symbol: str,
    start_date: str,
    end_date: str,
    db_path: str,
    batch_size: int = 500,
    skip_existing: bool = True,
) -> Tuple[int, int]:
    """采集单只 A50 成分股估值数据

    Args:
        pro_api: Tushare Pro API 实例
        symbol: 标的代码（含后缀，如 601857.SH）
        start_date: 起始日期 YYYYMMDD
        end_date: 截止日期 YYYYMMDD
        db_path: 数据库路径
        batch_size: 每批写入行数
        skip_existing: 跳过已存在的日期

    Returns:
        (写入行数, 跳过行数)
    """
    code_6 = symbol.split('.')[0]  # 6位代码

    # 检查已存在的日期
    existing = set()
    if skip_existing:
        existing = get_existing_dates(db_path, code_6)

    # 构造 fields 参数（只请求可用字段）
    # pcf_ttm / dividend_yield 需要 premium 积分
    fields_param = 'ts_code,trade_date,pe,pe_ttm,pb,ps_ttm,dv_ratio,float_share,total_share,circ_mv'

    try:
        df = pro_api.daily_basic(
            ts_code=symbol,
            fields=fields_param,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.warning(f'daily_basic failed for {symbol}: {e}')
        return 0, 0

    if df is None or df.empty:
        logger.info(f'No daily_basic data for {symbol} in {start_date}~{end_date}')
        return 0, 0

    # 标准化：trade_date → date
    df['date'] = df['trade_date'].astype(str)

    # 构建 records
    records = []
    skipped = 0
    for _, row in df.iterrows():
        date = row['date']
        if skip_existing and date in existing:
            skipped += 1
            continue

        record = {
            'code': code_6,
            'date': date,
            'pe': _safe_float(row.get('pe')),
            'pe_ttm': _safe_float(row.get('pe_ttm')),
            'pb': _safe_float(row.get('pb')),
            'ps_ttm': _safe_float(row.get('ps_ttm')),
            'float_share': _safe_float(row.get('float_share')),
            'total_share': _safe_float(row.get('total_share')),
            'circ_mv': _safe_float(row.get('circ_mv')),
            'dividend_yield': _safe_float(row.get('dv_ratio')),  # dv_ratio → dividend_yield 映射
        }
        records.append(record)

    # 分批写入
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        write_batch(db_path, batch)

    return len(records), skipped


def collect_batch(
    symbols: List[str],
    start_date: str,
    end_date: str,
    db_path: str,
    rate_limit_delay: float = 0.6,
) -> Dict[str, Tuple[int, int]]:
    """批量采集多只成分股估值数据

    Args:
        symbols: 标的代码列表
        start_date: 起始日期
        end_date: 截止日期
        db_path: 数据库路径
        rate_limit_delay: 两次 API 调用间隔（秒），免费版 120次/分钟 → 0.5s

    Returns:
        {symbol: (写入行数, 跳过行数)}
    """
    pro_api = TokenLoader.get_pro_api()
    results = {}

    for i, symbol in enumerate(symbols):
        logger.info(f'[{i+1}/{len(symbols)}] Collecting {symbol}...')
        written, skipped = collect_single(
            pro_api=pro_api,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            db_path=db_path,
        )
        results[symbol] = (written, skipped)

        # 限流延时
        if i < len(symbols) - 1:
            time.sleep(rate_limit_delay)

    return results


# ── 回填到 a50_daily_ohlcv ───────────────────────────────

def backfill_valuation(db_path: str, options: Optional[List[str]] = None) -> dict:
    """从 a50_daily_basic 回填估值数据到 a50_daily_ohlcv

    通过 (code, date) 匹配 UPDATE pe, pe_ttm, pb, ps_ttm 等列。
    依赖 ALTER TABLE 事先执行（sub_task_005）。

    Args:
        db_path: 数据库路径
        options: 要回填的字段列表，默认全部可用估值字段
                 ['pe', 'pe_ttm', 'pb', 'ps_ttm', 'dividend_yield']
                 （pcf_ttm 仍为 premium 字段，当前不可用）

    Returns:
        统计信息
    """
    if options is None:
        options = ['pe', 'pe_ttm', 'pb', 'ps_ttm', 'dividend_yield']

    stats = {'total_ohlcv': 0, 'updated': 0, 'non_null': {}}

    conn = sqlite3.connect(db_path)
    try:
        # 确认 a50_daily_ohlcv 列存在
        cur = conn.execute('PRAGMA table_info(a50_daily_ohlcv)')
        ohlcv_cols = {row[1] for row in cur.fetchall()}

        # 确认 a50_daily_basic 列存在
        cur = conn.execute('PRAGMA table_info(a50_daily_basic)')
        basic_cols = {row[1] for row in cur.fetchall()}

        # 取交集：只在两个表都存在的字段上进行回填
        available = [c for c in options if c in ohlcv_cols and c in basic_cols]
        if not available:
            logger.warning(f'No target columns available in both tables: {options}')
            logger.warning('Run ALTER TABLE migration first (sub_task_005) if columns missing in ohlcv')
            conn.close()
            return stats

        # 动态构建 SELECT 查询（只取 available 字段）
        select_cols = ', '.join(available)
        where_conditions = ' OR '.join(f'{c} IS NOT NULL' for c in available)
        query = f'SELECT code, date, {select_cols} FROM a50_daily_basic WHERE {where_conditions}'

        cur = conn.execute(query)
        rows = cur.fetchall()
        logger.info(f'Found {len(rows)} rows with non-null valuation data in a50_daily_basic')
        logger.info(f'Available backfill fields: {available}')

        # 批量 UPDATE
        update_count = 0
        for row in rows:
            code = row[0]
            date = row[1]
            val_values = row[2:]  # 从索引2开始是估值数据

            set_parts = []
            params = []

            for i, col in enumerate(available):
                val = val_values[i]
                if val is not None:
                    set_parts.append(f'{col} = ?')
                    params.append(val)

            if not set_parts:
                continue

            set_clause = ', '.join(set_parts)

            # 只更新 OHLCV 中已有的行（code+date 匹配）
            # a50_daily_basic 存 6位code, a50_daily_ohlcv 存带后缀的 ts_code
            # 用 SUBSTR 匹配 6 位前缀
            params.extend([code, date])
            cur = conn.execute(
                f'UPDATE a50_daily_ohlcv SET {set_clause} '
                f'WHERE SUBSTR(ts_code, 1, 6) = ? AND trade_date = ?',
                params
            )
            if cur.rowcount > 0:
                update_count += 1

        conn.commit()
        stats['updated'] = update_count
        stats['non_null'] = {c: 0 for c in available}
        for c in available:
            cur = conn.execute(
                f'SELECT COUNT(*) FROM a50_daily_ohlcv WHERE {c} IS NOT NULL'
            )
            stats['non_null'][c] = cur.fetchone()[0]

    except Exception as e:
        logger.error(f'Backfill failed: {e}')
        stats['error'] = str(e)
    finally:
        conn.close()

    return stats


# ── 工具 ──────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    """安全转为 float，NaN/None 返回 None"""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (ValueError, TypeError):
        return None


def check_token_integral() -> dict:
    """检查 Tushare Token 积分状态

    Tushare 免费版（2000积分以下）无法获取 ps_ttm/pcf_ttm/dividend_yield。

    Returns:
        检查结果
    """
    try:
        pro_api = TokenLoader.get_pro_api()

        # 尝试获取 premium 字段以判断积分
        df = pro_api.daily_basic(
            ts_code='601857.SH',
            fields='ts_code,trade_date,ps_ttm,pcf_ttm,dv_ratio',
            start_date='20260520',
            end_date='20260520',
        )

        has_ps_ttm = df is not None and 'ps_ttm' in df.columns and not df['ps_ttm'].isna().all()
        has_pcf_ttm = df is not None and 'pcf_ttm' in df.columns and not df['pcf_ttm'].isna().all()
        has_dividend = df is not None and 'dv_ratio' in df.columns and not df['dv_ratio'].isna().all()

        return {
            'token_valid': True,
            'premium_fields_available': {
                'ps_ttm': bool(has_ps_ttm),
                'pcf_ttm': bool(has_pcf_ttm),
                'dv_ratio': bool(has_dividend),
            },
        }
    except Exception as e:
        return {
            'token_valid': False,
            'error': str(e),
        }


# ── 独立入口 ──────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    parser = argparse.ArgumentParser(description='A50估值数据采集')
    parser.add_argument('--db', default=DEFAULT_DB_PATH, help='数据库路径')
    parser.add_argument('--start', default='20070101', help='起始日期 YYYYMMDD')
    parser.add_argument('--end', default=datetime.now().strftime('%Y%m%d'), help='截止日期')
    parser.add_argument('--symbol', default='', help='单标的代码（不指定则全量A50）')
    parser.add_argument('--check-token', action='store_true', help='仅检查Token状态')
    parser.add_argument('--backfill', action='store_true', help='回填到 a50_daily_ohlcv')

    args = parser.parse_args()

    if args.check_token:
        result = check_token_integral()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        exit(0)

    # 确保表存在
    if not ensure_a50_daily_basic_table(args.db):
        print('Failed to ensure table')
        exit(1)

    # 确定采集清单
    if args.symbol:
        symbols = [args.symbol]
    else:
        symbols = A50_CONSTITUENTS

    # 执行采集
    print(f'Starting daily_basic collection: {len(symbols)} symbols, {args.start}~{args.end}')
    results = collect_batch(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        db_path=args.db,
    )

    total_written = sum(w for w, _ in results.values())
    total_skipped = sum(s for _, s in results.values())
    total_errors = sum(1 for w, _ in results.values() if w == 0)

    print(f'\nCollection complete:')
    print(f'  Written: {total_written} rows')
    print(f'  Skipped: {total_skipped} rows')
    print(f'  Symbols with 0 writes: {total_errors}')
    print(f'  DB: {args.db}')

    # 回填（可选）
    if args.backfill:
        print('\nBackfilling to a50_daily_ohlcv...')
        stats = backfill_valuation(args.db)
        print(f'  Updated: {stats.get("updated", 0)} rows')
        print(f'  Non-null columns: {stats.get("non_null", {})}')
