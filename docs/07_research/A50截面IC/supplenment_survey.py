"""supplenment_survey.py - A50截面IC T+0补充摸底
设计版本: design_v2 §5.1
作者: 墨衡 (DeepSeek R1)
创建时间: 2026-05-29T21:50+08:00

必须跑通的5项查询:
  Q1: pe/pb/float_share 缺失率统计
  Q2: min_stocks截面覆盖率
  Q3: 复权方向实盘验证（贵州茅台600519.SH，2023年除权日）
  Q4: 停牌日分布统计
"""

import sqlite3
import os
import sys
from datetime import datetime, timezone, timedelta

# ============================================================
# 配置
# ============================================================
DB_PATH = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"
OUTPUT_DIR = r"C:\Users\17699\mozhi_platform\reports\survey"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TZ = timezone(timedelta(hours=8))


def fmt_ts():
    return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def fmt_date():
    return datetime.now(TZ).strftime("%Y%m%d")


def get_conn():
    """连接数据库"""
    if not os.path.exists(DB_PATH):
        print(f"[FATAL] 数据库不存在: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def safe_close(conn):
    """安全关闭数据库连接"""
    if conn:
        try:
            conn.close()
        except Exception as e:
            print(f"[WARN] 关闭数据库连接时出错: {e}")


# ============================================================
# Q1: pe/pb/float_share 缺失率统计
# ============================================================
def q1_pe_pb_float_null(conn):
    """Q1: 各股票的pe/pb/float_share/total_share缺失率"""
    sql = """
        SELECT ts_code,
            COUNT(1) as total,
            SUM(CASE WHEN pe IS NULL THEN 1 ELSE 0 END) as pe_null,
            SUM(CASE WHEN pb IS NULL THEN 1 ELSE 0 END) as pb_null,
            SUM(CASE WHEN float_share IS NULL THEN 1 ELSE 0 END) as float_null,
            SUM(CASE WHEN total_share IS NULL THEN 1 ELSE 0 END) as total_share_null,
            ROUND(100.0 * SUM(CASE WHEN pe IS NULL THEN 1 ELSE 0 END) / MAX(COUNT(1), 1), 2) as pe_null_pct,
            ROUND(100.0 * SUM(CASE WHEN pb IS NULL THEN 1 ELSE 0 END) / MAX(COUNT(1), 1), 2) as pb_null_pct,
            ROUND(100.0 * SUM(CASE WHEN float_share IS NULL THEN 1 ELSE 0 END) / MAX(COUNT(1), 1), 2) as float_null_pct,
            ROUND(100.0 * SUM(CASE WHEN total_share IS NULL THEN 1 ELSE 0 END) / MAX(COUNT(1), 1), 2) as total_share_null_pct
        FROM stock_daily
        GROUP BY ts_code
        ORDER BY pe_null_pct DESC;
    """
    rows = conn.execute(sql).fetchall()
    return rows


# ============================================================
# Q2: min_stocks截面覆盖率
# ============================================================
def q2_min_stocks_coverage(conn):
    """Q2: 每日可用成分股数（排除停牌）"""
    sql = """
        SELECT trade_date,
            SUM(CASE WHEN close IS NOT NULL AND volume > 0 THEN 1 ELSE 0 END) as available
        FROM stock_daily
        GROUP BY trade_date
        ORDER BY trade_date;
    """
    rows = conn.execute(sql).fetchall()

    total_days = len(rows)
    days_ge_30 = sum(1 for r in rows if r["available"] >= 30)
    ratio = round(100.0 * days_ge_30 / total_days, 2) if total_days > 0 else 0

    stats = {
        "total_days": total_days,
        "days_ge_30": days_ge_30,
        "ratio": ratio,
        "min_available": min(r["available"] for r in rows) if rows else 0,
        "max_available": max(r["available"] for r in rows) if rows else 0,
        "avg_available": round(sum(r["available"] for r in rows) / total_days, 1) if total_days > 0 else 0,
    }
    return rows, stats


# ============================================================
# Q3: 复权方向实盘验证（贵州茅台600519.SH，2023年除权日）
# ============================================================
def q3_adj_factor_validation(conn):
    """Q3: 复权方向实盘验证 - 贵州茅台 2023年除权日前后

    设计指定目标日期为 20230613，但实际复权调整可能在其它日期发生。
    逻辑改进：自动检测 adj_factor 变化发生的位置，以此作为分析基准点。
    """
    TARGET_CODE = "600519.SH"
    TASK_EX_DATE = "20230613"  # 任务指定的除权日（设计参考）

    # 取2023年中时段数据，覆盖全范围以检测adj_factor变化
    sql = """
        SELECT trade_date, close, pre_close, adj_factor, change, pct_chg, volume
        FROM stock_daily
        WHERE ts_code = ?
          AND trade_date BETWEEN '20230501' AND '20230731'
        ORDER BY trade_date;
    """
    rows = conn.execute(sql, (TARGET_CODE,)).fetchall()

    if not rows:
        return [], None, TARGET_CODE, TASK_EX_DATE

    # 计算两种复权方式
    results = []
    prev_adj = None
    adj_change_dates = []  # 记录adj_factor变化的日期
    for r in rows:
        close = r["close"]
        adj = r["adj_factor"] if r["adj_factor"] != 0 else 1

        # 检测adj_factor变化（过滤0.1%以下微小波动，即舍入误差）
        if prev_adj is not None and prev_adj > 0:
            adj_change_pct = abs(adj - prev_adj) / prev_adj
            if adj_change_pct > 0.001:  # 0.1% 阈值
                adj_change_dates.append({
                    "date": r["trade_date"],
                    "prev_adj": prev_adj,
                    "new_adj": adj,
                    "change_pct": round(adj_change_pct * 100, 4),
                })
        prev_adj = adj

        # 方案A: close * adj_factor (后复权价格 = 原始收盘价 * 复权因子)
        post_adj = round(close * adj, 2) if close is not None else None
        # 方案B: close / adj_factor (前复权价格 = 原始收盘价 / 复权因子)
        pre_adj = round(close / adj, 2) if close is not None else None

        results.append({
            "trade_date": r["trade_date"],
            "close": close,
            "pre_close": r["pre_close"],
            "adj_factor": adj,
            "post_adj_close": post_adj,
            "pre_adj_close": pre_adj,
            "change": r["change"],
            "pct_chg": r["pct_chg"],
            "volume": r["volume"],
        })

    # 使用第一个 detected adj_factor 变化日期作为分析基准
    actual_adj_date = adj_change_dates[0]["date"] if adj_change_dates else TASK_EX_DATE

    # 检查任务指定的除权日
    task_ex_row = next((r for r in results if r["trade_date"] == TASK_EX_DATE), None)

    # 检查实际调整日
    actual_ex_row = next((r for r in results if r["trade_date"] == actual_adj_date), None)

    analysis = {}

    # 分析实际调整日的复权连续性
    if actual_ex_row and len(results) > 1:
        adj_idx = next(i for i, r in enumerate(results) if r["trade_date"] == actual_adj_date)
        if adj_idx > 0:
            prev_row = results[adj_idx - 1]

            # 后复权连续性
            post_adj_prev = prev_row["post_adj_close"]
            post_adj_curr = actual_ex_row["post_adj_close"]
            if post_adj_prev and post_adj_curr and post_adj_prev > 0:
                post_diff_pct = abs(post_adj_curr - post_adj_prev) / post_adj_prev
                post_cont = post_diff_pct < 0.01  # 波动<1%视为连续
            else:
                post_cont = False
                post_diff_pct = 999

            # 前复权连续性
            pre_adj_prev = prev_row["pre_adj_close"]
            pre_adj_curr = actual_ex_row["pre_adj_close"]
            if pre_adj_prev and pre_adj_curr and pre_adj_prev > 0:
                pre_diff_pct = abs(pre_adj_curr - pre_adj_prev) / pre_adj_prev
                pre_cont = pre_diff_pct < 0.01
            else:
                pre_cont = False
                pre_diff_pct = 999

            analysis = {
                "ex_div_date": actual_adj_date,
                "task_target_date": TASK_EX_DATE,
                "prev_date": prev_row["trade_date"],
                "prev_close": prev_row["close"],
                "prev_adj_factor": prev_row["adj_factor"],
                "ex_adj_factor": actual_ex_row["adj_factor"],
                "ex_div_close": actual_ex_row["close"],
                "prev_post_adj": prev_row["post_adj_close"],
                "ex_div_post_adj": actual_ex_row["post_adj_close"],
                "prev_pre_adj": prev_row["pre_adj_close"],
                "ex_div_pre_adj": actual_ex_row["pre_adj_close"],
                "post_adj_change_pct": round(post_diff_pct * 100, 4),
                "pre_adj_change_pct": round(pre_diff_pct * 100, 4),
                "post_adj_continuous": post_cont,
                "pre_adj_continuous": pre_cont,
                "adj_change_dates": [d["date"] for d in adj_change_dates],
                "adj_change_count": len(adj_change_dates),
            }

    return results, analysis, TARGET_CODE, TASK_EX_DATE


# ============================================================
# Q4: 停牌日分布统计
# ============================================================
def q4_suspension_stats(conn):
    """Q4: 停牌日分布统计（按年份）

    停牌判断标准：close IS NULL（SQLite层面）。
    补充停牌判断说明（Warning #03 评估结果）：
    - 检查了 stock_daily 中 close=0 的记录数: 0
    - 检查了 stock_daily 中 volume=0 的记录数: 0
    - 当前数据集不存在 close=0 或 volume=0 的数据质量问题
    - 因此仅使用 close IS NULL 判断停牌在此数据集中足够准确
    - 若未来数据集变更，建议增加退化条件: (close IS NULL OR volume=0 OR close=0)
    """
    # SQLite strftime with YYYYMMDD format
    sql = """
        SELECT substr(trade_date, 1, 4) as year,
            COUNT(1) as suspension_days
        FROM stock_daily
        WHERE close IS NULL
        GROUP BY year
        ORDER BY year;
    """
    rows = conn.execute(sql).fetchall()

    # 额外: 按ts_code统计停牌天数
    sql2 = """
        SELECT ts_code, COUNT(1) as suspension_days,
            ROUND(100.0 * COUNT(1) / (SELECT COUNT(1) FROM stock_daily WHERE ts_code = s.ts_code), 2) as suspension_pct
        FROM stock_daily s
        WHERE close IS NULL
        GROUP BY ts_code
        ORDER BY suspension_days DESC;
    """
    rows_by_code = conn.execute(sql2).fetchall()

    total_suspensions = sum(r["suspension_days"] for r in rows)

    return rows, rows_by_code, total_suspensions


# ============================================================
# 全局统计
# ============================================================
def global_stats(conn):
    """获取数据库全局统计"""
    sql = """
        SELECT
            COUNT(DISTINCT ts_code) as total_stocks,
            COUNT(DISTINCT trade_date) as total_days,
            MIN(trade_date) as first_date,
            MAX(trade_date) as last_date,
            COUNT(1) as total_rows
        FROM stock_daily;
    """
    row = conn.execute(sql).fetchone()
    return dict(row)


# ============================================================
# 报告生成
# ============================================================
def write_report(q1_rows, q2_rows, q2_stats, q3_results, q3_analysis,
                 q3_code, q3_ex_date, q4_rows, q4_rows_by_code,
                 q4_total_susp, global_info):
    """生成markdown报告"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    report_path = os.path.join(OUTPUT_DIR, f"supplenment_survey_{fmt_date()}.md")

    lines = []
    lines.append(f"# A50截面IC T+0补充摸底报告")
    lines.append(f"")
    lines.append(f"- **生成时间**: {fmt_ts()}")
    lines.append(f"- **数据源**: `{DB_PATH}`")
    lines.append(f"- **设计版本**: design_v2 §5.1")
    lines.append(f"- **全局统计**: {global_info['total_stocks']}支股票, "
                 f"{global_info['total_days']}个交易日, "
                 f"日期范围 {global_info['first_date']} ~ {global_info['last_date']}")
    lines.append(f"")

    # ---- Q1 ----
    lines.append(f"## Q1: pe/pb/float_share 缺失率统计")
    lines.append(f"")
    # 整体缺失率
    total_records = sum(r["total"] for r in q1_rows)
    total_pe_null = sum(r["pe_null"] for r in q1_rows)
    total_pb_null = sum(r["pb_null"] for r in q1_rows)
    total_float_null = sum(r["float_null"] for r in q1_rows)
    total_ts_null = sum(r["total_share_null"] for r in q1_rows)
    lines.append(f"| 字段 | 缺失记录数 | 缺失率 |")
    lines.append(f"|:----|:----------:|:------:|")
    lines.append(f"| pe | {total_pe_null} | {round(100*total_pe_null/total_records,2)}% |")
    lines.append(f"| pb | {total_pb_null} | {round(100*total_pb_null/total_records,2)}% |")
    lines.append(f"| float_share | {total_float_null} | {round(100*total_float_null/total_records,2)}% |")
    lines.append(f"| total_share | {total_ts_null} | {round(100*total_ts_null/total_records,2)}% |")
    lines.append(f"")

    # 缺失率前10的股票
    lines.append(f"### 缺失率TOP10（按pe_null_pct降序）")
    lines.append(f"")
    lines.append(f"| ts_code | total | pe_null | pb_null | float_null | total_share_null | pe_null_pct | pb_null_pct | float_null_pct | total_share_null_pct |")
    lines.append(f"|:-------|:----:|:-------:|:-------:|:----------:|:----------------:|:-----------:|:-----------:|:--------------:|:--------------------:|")
    for r in q1_rows[:10]:
        lines.append(f"| {r['ts_code']} | {r['total']} | {r['pe_null']} | {r['pb_null']} | {r['float_null']} | {r['total_share_null']} | {r['pe_null_pct']}% | {r['pb_null_pct']}% | {r['float_null_pct']}% | {r['total_share_null_pct']}% |")
    lines.append(f"")

    # 缺失率=0的股票数
    clean_stocks = sum(1 for r in q1_rows if r["pe_null"] == 0 and r["pb_null"] == 0 and r["float_null"] == 0 and r["total_share_null"] == 0)
    lines.append(f"- 四项关键字段完全无缺失的股票数: **{clean_stocks}** / {len(q1_rows)}")
    lines.append(f"")

    # ---- Q2 ----
    lines.append(f"## Q2: min_stocks截面覆盖率")
    lines.append(f"")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|:----|:---:|")
    lines.append(f"| 总交易日数 | {q2_stats['total_days']} |")
    lines.append(f"| 可用数≥30的交易日 | {q2_stats['days_ge_30']} |")
    lines.append(f"| 覆盖率 | **{q2_stats['ratio']}%** |")
    lines.append(f"| 最小可用成分股数 | {q2_stats['min_available']} |")
    lines.append(f"| 最大可用成分股数 | {q2_stats['max_available']} |")
    lines.append(f"| 平均可用成分股数 | {q2_stats['avg_available']} |")
    lines.append(f"")

    # 每日可用数详情（截取首尾各10条）
    lines.append(f"### 每日可用成分股数（首10日 + 尾10日）")
    lines.append(f"")
    lines.append(f"| trade_date | available |")
    lines.append(f"|:----------|:---------:|")
    for r in q2_rows[:10] + q2_rows[-10:]:
        lines.append(f"| {r['trade_date']} | {r['available']} |")
    lines.append(f"")

    # ---- Q3 ----
    lines.append(f"## Q3: 复权方向实盘验证（{q3_code} 除权日 {q3_ex_date}前后）")
    lines.append(f"")
    if q3_results:
        if q3_analysis:
            adj_change_str = ", ".join(q3_analysis['adj_change_dates'])
            lines.append(f"### 复权因子变化分析")
            lines.append(f"")
            lines.append(f"- 任务指定的除权日: {q3_analysis['task_target_date']}")
            lines.append(f"- adj_factor 变化日期 ({q3_analysis['adj_change_count']}次): {adj_change_str}")
            lines.append(f"- 实际分析基准日（第一个adj_factor变化日）: **{q3_analysis['ex_div_date']}**")
            lines.append(f"")
            lines.append(f"### 除权日分析（基准: {q3_analysis['ex_div_date']}）")
            lines.append(f"")
            lines.append(f"| 项目 | 值 |")
            lines.append(f"|:----|:---:|")
            lines.append(f"| 前一日 | {q3_analysis['prev_date']} |")
            lines.append(f"| 前日收盘价(不复权) | {q3_analysis['prev_close']} |")
            lines.append(f"| 前日adj_factor | {q3_analysis['prev_adj_factor']} |")
            lines.append(f"| 基准日adj_factor | {q3_analysis['ex_adj_factor']} |")
            lines.append(f"| 基准日收盘价(不复权) | {q3_analysis['ex_div_close']} |")
            lines.append(f"| 后复权价格变化率 | {q3_analysis['post_adj_change_pct']}% |")
            lines.append(f"| 后复权价格是否连续 | {'YES' if q3_analysis['post_adj_continuous'] else 'NO'} |")
            lines.append(f"| 前复权价格变化率 | {q3_analysis['pre_adj_change_pct']}% |")
            lines.append(f"| 前复权价格是否连续 | {'YES' if q3_analysis['pre_adj_continuous'] else 'NO'} |")
            lines.append(f"")
            lines.append(f"**结论**: ")
            if q3_analysis['post_adj_continuous'] and not q3_analysis['pre_adj_continuous']:
                lines.append("后复权(`close * adj_factor`)在adj_factor调整日前后连续，前复权(`close / adj_factor`)存在明显跳变。"
                             "确认复权方向为 **后复权**。")
            elif q3_analysis['pre_adj_continuous'] and not q3_analysis['post_adj_continuous']:
                lines.append("前复权(`close / adj_factor`)在adj_factor调整日前后连续，后复权(`close * adj_factor`)存在明显跳变。"
                             "确认复权方向为 **前复权**。")
            elif q3_analysis['post_adj_continuous'] and q3_analysis['pre_adj_continuous']:
                lines.append("两种复权方式在adj_factor调整日前后均连续，需要进一步分析。")
            else:
                lines.append("两种复权方式在adj_factor调整日前后均不连续，可能存在数据问题。")
            lines.append(f"")

        lines.append(f"### 日线数据详情")
        lines.append(f"")
        lines.append(f"| trade_date | close | adj_factor | post_adj(close*adj) | pre_adj(close/adj) | change | pct_chg | volume |")
        lines.append(f"|:----------|:----:|:----------:|:------------------:|:------------------:|:-----:|:-------:|:------:|")
        for r in q3_results:
            pa = r["post_adj_close"]
            pr = r["pre_adj_close"]
            lines.append(f"| {r['trade_date']} | {r['close']} | {r['adj_factor']} | {pa} | {pr} | {r['change']} | {r['pct_chg']}% | {r['volume']} |")
        lines.append(f"")
    else:
        lines.append(f"⚠️ 未找到 {q3_code} 的数据")
        lines.append(f"")

    # ---- Q4 ----
    lines.append(f"## Q4: 停牌日分布统计")
    lines.append(f"")
    lines.append(f"总停牌记录数: **{q4_total_susp}**")
    lines.append(f"")

    lines.append(f"### 按年份分布")
    lines.append(f"")
    lines.append(f"| 年份 | 停牌天数 |")
    lines.append(f"|:----:|:---------:|")
    for r in q4_rows:
        lines.append(f"| {r['year']} | {r['suspension_days']} |")
    lines.append(f"")

    lines.append(f"### 停牌天数TOP10股票")
    lines.append(f"")
    lines.append(f"| ts_code | 停牌天数 | 占该股总记录比 |")
    lines.append(f"|:-------|:--------:|:--------------:|")
    for r in q4_rows_by_code[:10]:
        lines.append(f"| {r['ts_code']} | {r['suspension_days']} | {r['suspension_pct']}% |")
    lines.append(f"")

    # Footer
    lines.append(f"---")
    lines.append(f"*报告由 supplenment_survey.py 自动生成 | {fmt_ts()}*")

    content = "\n".join(lines)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[OK] 报告已生成: {report_path}")
    return report_path


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("A50截面IC T+0补充摸底 - supplenment_survey.py")
    print(f"时间: {fmt_ts()}")
    print(f"数据库: {DB_PATH}")
    print("=" * 60)

    conn = None
    try:
        conn = get_conn()

        # 全局统计
        print("\n[1/5] 读取全局统计...")
        global_info = global_stats(conn)
        print(f"  股票数: {global_info['total_stocks']}, "
              f"交易日: {global_info['total_days']}, "
              f"范围: {global_info['first_date']} ~ {global_info['last_date']}")

        # Q1
        print("\n[2/5] Q1: pe/pb/float_share 缺失率统计...")
        q1_rows = q1_pe_pb_float_null(conn)
        print(f"  完成, 共 {len(q1_rows)} 支股票")

        # Q2
        print("\n[3/5] Q2: min_stocks截面覆盖率...")
        q2_rows, q2_stats = q2_min_stocks_coverage(conn)
        print(f"  总交易日: {q2_stats['total_days']}, 可用≥30: {q2_stats['days_ge_30']} ({q2_stats['ratio']}%)")

        # Q3
        print("\n[4/5] Q3: 复权方向实盘验证（贵州茅台 600519.SH 2023年除权日）...")
        q3_results, q3_analysis, q3_code, q3_ex_date = q3_adj_factor_validation(conn)
        if q3_analysis:
            cont = q3_analysis['post_adj_continuous']
            adj_changes = q3_analysis['adj_change_dates']
            print(f"  adj_factor 变化次数: {q3_analysis['adj_change_count']}")
            print(f"  adj_factor 变化日期: {adj_changes}")
            print(f"  实际分析基准日: {q3_analysis['ex_div_date']}")
            print(f"  后复权连续性: {'YES' if cont else 'NO'}")
        else:
            print(f"  [WARN] 未找到除权日数据")

        # Q4
        print("\n[5/5] Q4: 停牌日分布统计...")
        q4_rows, q4_rows_by_code, q4_total_susp = q4_suspension_stats(conn)
        print(f"  总停牌记录: {q4_total_susp}, 涉及 {len(q4_rows)} 个年份")

        # 生成报告
        print("\n---\n生成报告...")
        report_path = write_report(q1_rows, q2_rows, q2_stats, q3_results, q3_analysis,
                                   q3_code, q3_ex_date, q4_rows, q4_rows_by_code,
                                   q4_total_susp, global_info)

        print(f"\n[OK] 全部完成。报告: {report_path}")
    finally:
        safe_close(conn)


if __name__ == "__main__":
    main()
