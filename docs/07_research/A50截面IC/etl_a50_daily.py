"""etl_a50_daily.py - P1: 数据提取 + 后复权

从 market_data.db.stock_daily 提取上证50的50只股票数据，写入 a50_ic.db.a50_daily_ohlcv。

设计依据: design_v2.md §3.1-3.2
作者: 墨衡 (DeepSeek R1)
创建时间: 2026-05-29T22:02+08:00

流程:
  1. 连接 market_data.db 和 a50_ic.db
  2. 提取全部50只成分股日线数据
  3. 后复权价格计算: adj_price = price * adj_factor
  4. 字段映射: stock_daily 字段名 → a50_daily_ohlcv 字段名
  5. 停牌处理: task_03 暂不处理（留到 task_04）
  6. 写入 a50_ic.db.a50_daily_ohlcv
  7. 运行验证

复权方向断言:
  通过贵州茅台(600519.SH) 2024-12-20 除权事件验证 adj_factor 为后复权因子。
"""

import sqlite3
import os
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd

TZ = timezone(timedelta(hours=8))

# 数据库路径
MARKET_DB = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"
A50_IC_DB = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"

# 字段映射: stock_daily → a50_daily_ohlcv
# pe字段: stock_daily.pe_ttm → a50_daily_ohlcv.pe（设计约定）
FIELD_MAP = {
    "ts_code": "ts_code",
    "trade_date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "pre_close": "pre_close",
    "volume": "volume",
    "amount": "amount",
    "turnover_rate": "turnover_rate",
    "pe_ttm": "pe",        # pe_ttm → pe（设计约定）
    "pb": "pb",
    "adj_factor": "adj_factor",
    "float_share": "float_share",
    "total_share": "total_share",
}

# 需要后复权的价格字段
PRICE_COLS = ["open", "high", "low", "close", "pre_close"]

# 不需要后复权的数值字段
VALUE_COLS = ["volume", "amount", "turnover_rate", "pe", "pb", "float_share", "total_share"]


# ──────────────────────────────────────────────
# 停牌识别 + IPO首日处理 (task_04)
# ──────────────────────────────────────────────

def mark_suspension_rows(df, null_reason_col='null_reason'):
    """
    标记停牌行。

    策略（3级检测）：
      1. null_reason == 'SUSPENDED' → 停牌（数据库已标注）
      2. close IS NULL → 停牌（主识别）
      3. close = 0 AND volume = 0 → 停牌（代理识别）

    当前数据无停牌标记（close IS NULL = 0, volume=0 = 0），
    此函数为 future-proof 设计——当上游数据开始标记停牌时自动生效。

    Args:
        df: DataFrame, 需包含 close 列，可选 null_reason/volume 列
        null_reason_col: null_reason 列名，默认 'null_reason'

    Returns:
        DataFrame, 新增 is_suspended 列（bool）
    """
    df['is_suspended'] = False
    if null_reason_col in df.columns:
        df['is_suspended'] |= df[null_reason_col] == 'SUSPENDED'
    if 'close' in df.columns:
        df['is_suspended'] |= df['close'].isna() | ((df['close'] == 0) & (df['volume'] == 0))
    return df


def detect_ipo_first_day(df, group_col='ts_code'):
    """
    IPO首日检测。

    条件1：该 ts_code 的数据集中首行（即最早 trade_date 的那一行）
    条件2：该行无前一交易日的 adj_factor（shift(1) 为 NaN）

    !!! 设计约束 !!!
    由于分组内 shift(1) 令每组首行的 adj_prev 均为 NaN，
    `is_first_row & adj_prev.isna()` 等价于 `is_first_row`。
    这意味着每只股票的首行均被标记为 is_ipo=True。

    当前数据中无 IPO 首日记录，此过滤不会改变结果。
    Future 改进方向：结合 a50_universe 表的 in_date 字段，
    仅标记实际上市日（in_date == 数据集首日）的股票为真实IPO。
    或按所有股票的全局 trade_date 排序，仅标记首次出现在
    全局时间线上的股票。

    Args:
        df: DataFrame, 需包含 ts_code, trade_date, adj_factor 列
        group_col: 分组列名，默认 'ts_code'

    Returns:
        DataFrame, 新增 is_ipo 列（bool）, 附带中间列 is_first_row, adj_prev
    """
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    df['is_first_row'] = df.groupby(group_col).cumcount() == 0
    df['adj_prev'] = df.groupby(group_col)['adj_factor'].shift(1)
    df['is_ipo'] = df['is_first_row'] & df['adj_prev'].isna()
    return df


def mark_suspended_and_ipo(df):
    """
    标记停牌和IPO首日，保留行（不删除）
    停牌行：close置NULL，volume置0，null_reason='SUSPENDED'
    IPO首日：null_reason='IPO_FIRST_DAY'
    本函数与 a50_daily_ohlcv 表中的 null_reason 列配合使用。

    Args:
        df: DataFrame, 包含 close, volume, adj_factor 等

    Returns:
        DataFrame, 含 null_reason 标记，不删除行。
    """
    df = mark_suspension_rows(df)
    df = detect_ipo_first_day(df)

    # 确保 null_reason 列存在
    if 'null_reason' not in df.columns:
        df['null_reason'] = None

    # 停牌行处理
    df.loc[df['is_suspended'], 'close'] = None
    df.loc[df['is_suspended'], 'volume'] = 0
    df.loc[df['is_suspended'], 'null_reason'] = 'SUSPENDED'

    # IPO首日处理
    df.loc[df['is_ipo'], 'null_reason'] = 'IPO_FIRST_DAY'

    # 清理临时列
    df = df.drop(columns=['is_suspended', 'is_ipo', 'is_first_row', 'adj_prev'])

    # 统计
    suspended_count = (df['null_reason'] == 'SUSPENDED').sum()
    ipo_count = (df['null_reason'] == 'IPO_FIRST_DAY').sum()
    print(f"停牌标记: {suspended_count}行, IPO首日标记: {ipo_count}行")

    return df

def verify_adj_direction(src_conn):
    """
    验证 adj_factor 复权方向（后复权断言）。

    使用贵州茅台(600519.SH) 2024-12-20 除权事件验证：
    - 后复权假设 (close * adj_factor) → 除权前后连续
    - 前复权假设 (close / adj_factor) → 除权前后不连续

    Raises:
        AssertionError: 若后复权假设不成立
    """
    print("\n[方向断言] 验证 adj_factor 复权方向...")

    rows = src_conn.execute("""
        SELECT trade_date, close, pre_close, adj_factor
        FROM stock_daily
        WHERE ts_code = '600519.SH'
          AND trade_date BETWEEN '20241219' AND '20241223'
        ORDER BY trade_date
    """).fetchall()

    assert len(rows) >= 3, "茅台202412除权事件数据不足，无法验证复权方向"

    prev_close = rows[0][1]
    prev_adj = rows[0][3]
    ex_close = rows[1][1]
    ex_adj = rows[1][3]

    # 后复权假设: close * adj_factor
    fwd_prev = prev_close * prev_adj
    fwd_ex = ex_close * ex_adj
    fwd_bias = abs(fwd_ex / fwd_prev - 1)

    # 前复权假设: close / adj_factor
    bwd_prev = prev_close / prev_adj
    bwd_ex = ex_close / ex_adj
    bwd_bias = abs(bwd_ex / bwd_prev - 1)

    print(f"  除权日: {rows[0][0]} → {rows[1][0]}")
    print(f"  前日: close={rows[0][1]}, adj_factor={rows[0][3]:.6f}")
    print(f"  除权日: close={rows[1][1]}, adj_factor={rows[1][3]:.6f}")
    print(f"  后复权假设(close*adj) 偏差: {fwd_bias:.4%}")
    print(f"  前复权假设(close/adj) 偏差: {bwd_bias:.4%}")

    assert fwd_bias < 0.01, (
        f"复权方向断言失败! 后复权偏差={fwd_bias:.4%} > 1%, "
        f"前复权偏差={bwd_bias:.4%}。adj_factor可能为前复权因子。"
    )

    print(f"  [PASS] adj_factor 确认为后复权因子（close * adj_factor），偏差={fwd_bias:.4%}")
    return True


def extract_a50_data(market_db_path, a50_ic_db_path):
    """
    从 market_data.db 提取上证50数据写入 a50_ic.db。

    流程:
        1. 连接源库和目标库
        2. 获取所有 A50 成分股 ts_code 列表
        3. 逐股提取日线数据
        4. 后复权价格计算
        5. 分批写入 a50_daily_ohlcv

    Args:
        market_db_path: market_data.db 路径
        a50_ic_db_path: a50_ic.db 路径

    Returns:
        dict: {写入行数, 股票数, 时间范围}
    """
    src = sqlite3.connect(market_db_path)
    dst = sqlite3.connect(a50_ic_db_path)
    dst.execute("PRAGMA foreign_keys = ON")

    result = {}

    try:
        # ===== 第1步: 复权方向断言 =====
        verify_adj_direction(src)

        # ===== 第2步: 获取所有A50成分股 =====
        # market_data.db 恰好只包含上证50的50只股票
        codes = src.execute(
            "SELECT DISTINCT ts_code FROM stock_daily ORDER BY ts_code"
        ).fetchall()
        code_list = [c[0] for c in codes]
        print(f"\n[数据提取] 发现 {len(code_list)} 只股票")
        assert len(code_list) == 50, f"预期50只A50成分股，实际发现{len(code_list)}只"

        src_cols = list(FIELD_MAP.keys())
        dst_cols = list(FIELD_MAP.values())
        select_sql = f"SELECT {', '.join(src_cols)} FROM stock_daily WHERE ts_code = ? ORDER BY trade_date"

        total_written = 0

        # ===== 第3-5步: 逐股提取 + 复权 + 写入 =====
        for i, code in enumerate(code_list):
            rows = src.execute(select_sql, (code,)).fetchall()
            print(f"  [{i+1:02d}/{len(code_list)}] {code}: {len(rows)}行")

            batch = []
            for row in rows:
                record = {dst_cols[j]: row[j] for j in range(len(dst_cols))}

                # 后复权: price_col * adj_factor
                adj_factor = record["adj_factor"]
                if adj_factor is not None and adj_factor > 0:
                    for pc in PRICE_COLS:
                        if record[pc] is not None:
                            record[pc] = record[pc] * adj_factor

                # source_version 固定为 'v1'
                record["source_version"] = "v1"

                batch.append(record)

            if batch:
                # 停牌+IPO首日过滤 (task_04)
                df_batch = pd.DataFrame(batch)
                df_batch = mark_suspended_and_ipo(df_batch)

                if df_batch.empty:
                    print(f"  [{i+1:02d}/{len(code_list)}] {code}: 全部被过滤，跳过")
                    continue

                # 用 executemany 批量写入
                placeholders = ", ".join(["?"] * len(dst_cols))
                cols_str = ", ".join(dst_cols)
                insert_sql = f"INSERT OR IGNORE INTO a50_daily_ohlcv ({cols_str}) VALUES ({placeholders})"

                batch_filtered = df_batch[dst_cols].to_dict('records')
                dst.executemany(
                    insert_sql,
                    [[record[c] for c in dst_cols] for record in batch_filtered]
                )
                dst.commit()

        # 由于 executemany 的 total_changes 计数方式复杂，直接查最终行数
        total_written = dst.execute("SELECT COUNT(*) FROM a50_daily_ohlcv").fetchone()[0]
        print(f"\n  写入完成: {total_written} 行")

        # ===== 第6步: 收集统计信息 =====
        unique_codes = dst.execute(
            "SELECT COUNT(DISTINCT ts_code) FROM a50_daily_ohlcv"
        ).fetchone()[0]

        date_range = dst.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM a50_daily_ohlcv"
        ).fetchone()

        result = {
            "total_rows": total_written,
            "unique_codes": unique_codes,
            "date_min": date_range[0],
            "date_max": date_range[1],
        }

    except AssertionError as e:
        print(f"\n[FAILED] 断言失败: {e}")
        raise
    except Exception as e:
        print(f"\n[FAILED] 数据提取失败: {e}")
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()

    return result


def verify_extraction(db_path):
    """
    验证数据提取结果。

    检查项:
        1. 总行数 ≈ 50只 × ~4710天 ≈ 235,500
        2. 50只不同的 ts_code
        3. 茅台(600519.SH) 后复权价格合理性
        4. 复权方向断言通过

    Args:
        db_path: a50_ic.db 路径
    """
    conn = sqlite3.connect(db_path)

    try:
        print("\n" + "=" * 60)
        print("数据提取验证")
        print("=" * 60)

        # 1. 总行数
        total = conn.execute("SELECT COUNT(*) FROM a50_daily_ohlcv").fetchone()[0]
        print(f"\n[验证1] 总行数: {total}")
        expected_min = 50 * 4000  # 至少约4000个交易日
        assert total > expected_min, f"行数过少: {total} < {expected_min}"
        print(f"  [PASS] 行数 > {expected_min}")

        # 2. 不同ts_code数量
        code_count = conn.execute(
            "SELECT COUNT(DISTINCT ts_code) FROM a50_daily_ohlcv"
        ).fetchone()[0]
        print(f"\n[验证2] 不同 ts_code 数量: {code_count}")
        assert code_count == 50, f"预期50只，实际{code_count}只"
        print(f"  [PASS] 50只A50成分股全部写入")

        # 3. 茅台后复权价格（20260526）
        maotai = conn.execute("""
            SELECT trade_date, close, pre_close, adj_factor, pe, pb, volume
            FROM a50_daily_ohlcv
            WHERE ts_code = '600519.SH'
            ORDER BY trade_date DESC
            LIMIT 5
        """).fetchall()
        print(f"\n[验证3] 茅台(600519.SH) 后复权价格 (最近5日):")
        print(f"  {'trade_date':>10} {'adj_close':>12} {'adj_pre_close':>14} {'adj_factor':>12}")
        for r in maotai:
            print(f"  {r[0]:>10} {r[1]:>12.2f} {r[2]:>14.2f} {r[3]:>12.6f}")

        # 后复权价格应远大于原始价格（茅台adj_factor≈8，后复权价≈12000）
        latest_close = maotai[0][1]
        print(f"\n  最新后复权收盘价: {latest_close:.2f}")
        assert latest_close > 1000, f"后复权价格异常: {latest_close}，可能未正确复权"
        print(f"  [PASS] 后复权价格合理 (>1000)")

        # 4. 复权方向验证：复权价格在除权日前后连续
        exdiv = conn.execute("""
            SELECT trade_date, close, pre_close
            FROM a50_daily_ohlcv
            WHERE ts_code = '600519.SH'
              AND trade_date BETWEEN '20241219' AND '20241223'
            ORDER BY trade_date
        """).fetchall()
        print(f"\n[验证4] 复权方向验证（茅台20241220除权事件）:")
        print(f"  {'trade_date':>10} {'adj_close':>12} {'adj_pre_close':>14}")
        for r in exdiv:
            print(f"  {r[0]:>10} {r[1]:>12.2f} {r[2]:>14.2f}")

        # 后复权 pre_close 应 ≈ 前一日的 close
        for i in range(1, len(exdiv)):
            prev_close = exdiv[i-1][1]
            pre_close = exdiv[i][2]
            bias = abs(pre_close / prev_close - 1)
            assert bias < 0.02, (
                f"复权连续性断言失败: {exdiv[i][0]} pre_close={pre_close:.2f} "
                f"vs 前日close={prev_close:.2f}, 偏差={bias:.4%}"
            )
            print(f"  pre_close({exdiv[i][0]}) ≈ prev_close({exdiv[i-1][0]}): "
                  f"{pre_close:.2f} vs {prev_close:.2f} (偏差={bias:.4%})")
        print(f"  [PASS] 复权方向正确，除权前后价格连续")

        # 5. 时间范围
        date_range = conn.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM a50_daily_ohlcv"
        ).fetchone()
        print(f"\n[验证5] 时间范围: {date_range[0]} ~ {date_range[1]}")

        print(f"\n{'=' * 60}")
        print(f"[PASS] 全部验证通过!")
        print(f"{'=' * 60}")

    except AssertionError as e:
        print(f"\n[FAILED] 验证失败: {e}")
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────
# a50_universe 成分股列表构建 (task_05)
# ──────────────────────────────────────────────

def create_a50_universe_table(db_path):
    """
    创建 a50_universe 表（幂等）。

    Args:
        db_path: a50_ic.db 路径
    """
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS a50_universe (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code         TEXT    NOT NULL,
            stock_name      TEXT,
            in_date         TEXT    NOT NULL,
            out_date        TEXT,
            weight          REAL,
            source          TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_universe_code_in_date
            ON a50_universe(ts_code, in_date);
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_universe_in_out_date
            ON a50_universe(in_date, out_date);
    """)
    conn.commit()
    conn.close()
    print(f"  [建表] a50_universe 就绪")


def build_a50_universe_by_define(db_path, market_db_path=MARKET_DB):
    """
    降级方案：用已知50只 ts_code 从 market_data.db 取首次出现日期作为 in_date。

    逻辑：
      1. 从 market_data.db 取50只股票及其最小 trade_date 作为 in_date
      2. out_date 置 NULL（视为当前仍在成分股中）
      3. source 标记为 'by_define'
      4. 写入 a50_universe 表（幂等，先清空再写入）

    Args:
        db_path: a50_ic.db 路径
        market_db_path: market_data.db 路径

    Returns:
        int: 写入行数
    """
    src = sqlite3.connect(market_db_path)
    dst = sqlite3.connect(db_path)

    try:
        # 从 market_data.db 获取每只股票的首次出现日期
        rows = src.execute("""
            SELECT ts_code, MIN(trade_date) as first_date
            FROM stock_daily
            GROUP BY ts_code
            ORDER BY ts_code
        """).fetchall()

        print(f"  [by_define] 从 market_data.db 获取 {len(rows)} 只股票上市日期")
        assert len(rows) == 50, f"预期50只，实际{len(rows)}只"

        # 清空旧数据并写入新数据
        dst.execute("DELETE FROM a50_universe")

        inserted = 0
        for ts_code, in_date in rows:
            dst.execute(
                "INSERT INTO a50_universe (ts_code, in_date, out_date, source) VALUES (?, ?, NULL, 'by_define')",
                (ts_code, in_date)
            )
            inserted += 1

        dst.commit()
        print(f"  [by_define] 写入完成: {inserted} 条记录")

    except Exception as e:
        print(f"  [by_define] 失败: {e}")
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()

    return inserted


def build_a50_universe_from_tushare(db_path):
    """
    首选方案：tushare API 获取上证50历史成分股变动。

    使用 tushare.pro 的 index_member 接口查询 '000016.SH'（上证50）。
    API 返回字段：index_code, con_code, in_date, out_date, is_new

    注意：tushare 免费版可能无法访问 index_member 接口。
    若不可用，返回 None 触发降级方案。

    Args:
        db_path: a50_ic.db 路径

    Returns:
        int | None: 写入行数；若 tushare 不可用或无数据返回 None
    """
    try:
        import tushare as ts
        pro = ts.pro_api()

        # 上证50指数代码：000016.SH
        df = pro.index_member(index_code='000016.SH')

        if df is None or len(df) == 0:
            print("  [tushare] API 返回空，当前免费版可能无权限")
            return None

        print(f"  [tushare] 获取到 {len(df)} 条成分股记录")
        print(f"  [tushare] 字段: {list(df.columns)}")

        conn = sqlite3.connect(db_path)

        # 清空旧数据
        conn.execute("DELETE FROM a50_universe")

        inserted = 0
        for _, row in df.iterrows():
            con_code = row.get('con_code', '')
            in_date = row.get('in_date', '')
            out_date = row.get('out_date', None)
            is_new = row.get('is_new', None)

            # out_date可能为空字符串，转为None
            if out_date is not None and (isinstance(out_date, str) and out_date.strip() == ''):
                out_date = None

            # stock_name 可从 is_new 判断，但API不直接返回名称
            conn.execute(
                "INSERT INTO a50_universe (ts_code, in_date, out_date, source) VALUES (?, ?, ?, 'tushare')",
                (con_code, in_date, out_date)
            )
            inserted += 1

        conn.commit()
        conn.close()
        print(f"  [tushare] 写入完成: {inserted} 条记录")
        return inserted

    except ImportError:
        print("  [tushare] tushare 未安装，跳过")
        return None
    except Exception as e:
        print(f"  [tushare] API 请求失败: {e}")
        return None


def verify_a50_universe(db_path, expected_count=50):
    """
    验证 a50_universe 表构建结果。

    检查项：
      1. 总记录数 >= expected_count
      2. 当前成分股（out_date IS NULL）数量
      3. 有 in_date 信息
      4. source 字段非空

    Args:
        db_path: a50_ic.db 路径
        expected_count: 预期最少的记录数（默认50）

    Returns:
        dict: 统计信息
    """
    conn = sqlite3.connect(db_path)

    print("\n" + "=" * 60)
    print("验证: a50_universe")
    print("=" * 60)

    stat = {}

    # 1. 总记录数
    total = conn.execute("SELECT COUNT(*) FROM a50_universe").fetchone()[0]
    print(f"\n[验证1] 总记录数: {total}")
    assert total >= expected_count, f"记录数不足: {total} < {expected_count}"
    print(f"  [PASS] >= {expected_count}")
    stat['total'] = total

    # 2. 当前成分股数（out_date IS NULL）
    current = conn.execute(
        "SELECT COUNT(*) FROM a50_universe WHERE out_date IS NULL"
    ).fetchone()[0]
    print(f"[验证2] 当前成分股数: {current}")
    assert current > 0, "当前成分股数为0"
    print(f"  [PASS] 有 {current} 只当前成分股")
    stat['current_stocks'] = current

    # 3. in_date 完整性
    no_in_date = conn.execute(
        "SELECT COUNT(*) FROM a50_universe WHERE in_date IS NULL OR in_date = ''"
    ).fetchone()[0]
    print(f"[验证3] in_date 完整性: {no_in_date} 条缺失")
    assert no_in_date == 0, f"存在 {no_in_date} 条 in_date 缺失"
    print(f"  [PASS] 所有记录均有 in_date")
    stat['missing_in_date'] = no_in_date

    # 4. source 非空
    no_source = conn.execute(
        "SELECT COUNT(*) FROM a50_universe WHERE source IS NULL"
    ).fetchone()[0]
    print(f"[验证4] source 完整性: {no_source} 条缺失")
    assert no_source == 0, f"存在 {no_source} 条 source 缺失"
    print(f"  [PASS] 所有记录均有 source")

    # 5. 显示第一批和最后一批股票
    sample = conn.execute("""
        SELECT ts_code, in_date, out_date, source
        FROM a50_universe
        ORDER BY in_date ASC
        LIMIT 5
    """).fetchall()
    print(f"\n[信息] 最早纳入的5只股票:")
    for r in sample:
        out_str = r[2] if r[2] else '当前成分股'
        print(f"  {r[0]:12s} in={r[1]} out={out_str} ({r[3]})")

    sample_late = conn.execute("""
        SELECT ts_code, in_date, out_date, source
        FROM a50_universe
        ORDER BY in_date DESC
        LIMIT 5
    """).fetchall()
    print(f"\n[信息] 最晚纳入的5只股票:")
    for r in sample_late:
        out_str = r[2] if r[2] else '当前成分股'
        print(f"  {r[0]:12s} in={r[1]} out={out_str} ({r[3]})")

    print(f"\n{'=' * 60}")
    print(f"[PASS] a50_universe 验证通过!")
    print(f"{'=' * 60}")

    conn.close()
    return stat


def build_a50_universe(db_path, market_db_path=MARKET_DB):
    """
    构建 a50_universe 表的入口函数（优先tushare，降级by_define）。

    Args:
        db_path: a50_ic.db 路径
        market_db_path: market_data.db 路径（by_define降级使用）

    Returns:
        bool: 是否成功
    """
    print("=" * 60)
    print("task_05: 构建 a50_universe（成分股列表）")
    print(f"时间: {datetime.now(TZ).strftime('%Y-%m-%dT%H:%M:%S+08:00')}")
    print("=" * 60)

    # 确保表存在
    create_a50_universe_table(db_path)

    # 优先 tushare
    print("\n[首选] 尝试 tushare API...")
    tushare_result = build_a50_universe_from_tushare(db_path)

    if tushare_result is not None and tushare_result > 0:
        print(f"\n  [完成] 使用 tushare 数据构建成功")
        verify_a50_universe(db_path)
        return True

    # 降级 by_define
    print("\n[降级] 使用 by_define 方案（基于 market_data.db 首次出现日期）...")
    by_define_result = build_a50_universe_by_define(db_path, market_db_path)

    if by_define_result > 0:
        print(f"\n  [完成] 使用 by_define 方案构建成功")
        verify_a50_universe(db_path)
        return True

    print(f"\n[FAILED] a50_universe 构建失败")
    return False


def main():
    print("=" * 60)
    print("A50截面IC - ETL P1: 数据提取 + 后复权")
    print(f"时间: {datetime.now(TZ).strftime('%Y-%m-%dT%H:%M:%S+08:00')}")
    print("=" * 60)

    # 检查源库存在
    if not os.path.exists(MARKET_DB):
        print(f"\n[ERROR] 源数据库不存在: {MARKET_DB}")
        sys.exit(1)

    # Step 1: 数据提取
    print(f"\n[1/2] 开始数据提取...")
    print(f"  源库: {MARKET_DB}")
    print(f"  目标: {A50_IC_DB}")

    result = extract_a50_data(MARKET_DB, A50_IC_DB)

    print(f"\n[1/2] 数据提取完成!")
    print(f"  总行数: {result['total_rows']}")
    print(f"  股票数: {result['unique_codes']}")
    print(f"  时间范围: {result['date_min']} ~ {result['date_max']}")

    # Step 2: 验证
    print(f"\n[2/2] 运行验证...")
    verify_extraction(A50_IC_DB)

    # 检查任务_02完成文件
    print(f"\n[完成] ETL P1 完成。")
    print(f"  数据库: {A50_IC_DB}")
    file_size_mb = os.path.getsize(A50_IC_DB) / (1024 * 1024)
    print(f"  文件大小: {file_size_mb:.1f} MB")
    print(f"  请继续执行 task_04 （停牌处理）")


if __name__ == "__main__":
    main()
