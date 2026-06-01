"""create_tables.py - 创建A50截面IC数据库表结构

设计依据: design_v2.md §1.2
作者: 墨衡 (DeepSeek R1)
创建时间: 2026-05-29T21:57+08:00
修复时间: 2026-05-29T22:01+08:00
修复内容:
  - C1: a50_daily_ohlcv 新增 null_reason TEXT 字段
  - C2: a50_cross_ic_result 字段名 section_date → trade_date
  - C3: a50_cross_ic_result 新增 rank_ic REAL（Spearman秩相关）
  - C4: a50_cross_ic_result 新增 adjusted_ic REAL（剔除±3σ极端值）
  - C5: a50_cross_ic_result 新增 idx_ic_factor 和 idx_ic_date 索引
  - C6: a50_daily_ohlcv 新增 idx_a50_daily_date 和 idx_a50_daily_code 索引
  - C7: a50_universe 新增 created_at 字段
  - N1: UNIQUE约束列顺序按设计文档统一
  - N2: ic_value注释修正为 Pearson
  - N3: 索引命名按设计文档统一

数据库: C:/Users/17699/mozhi_platform/data/market/a50_ic.db
"""

import sqlite3
import os
import sys
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

# 数据库路径
DB_DIR = os.path.dirname(r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db")
DB_PATH = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"
DESIGN_REF = "design_v2.md §1.2"

# ============================================================
# DDL 定义
# ============================================================

DDL_A50_DAILY_OHLCV = """
CREATE TABLE IF NOT EXISTS a50_daily_ohlcv (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code         TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,  -- YYYYMMDD
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,              -- 可NULL，停牌日置NULL；后复权价格
    pre_close       REAL,              -- 后复权前收盘价
    volume          REAL,              -- 成交量（股）
    amount          REAL,              -- 成交金额（元）
    turnover_rate   REAL,              -- 换手率（%），自计算
    pe              REAL,              -- 动态市盈率（PE TTM）
    pb              REAL,              -- 市净率
    adj_factor      REAL    NOT NULL,  -- 当日复权因子
    null_reason     TEXT,              -- NULL语义：NULL=正常, 'MISSING'=缺失, 'SUSPENDED'=停牌
    float_share     REAL,              -- 自由流通股
    total_share     REAL,              -- 总股本（可为NULL）
    source_version  TEXT    NOT NULL DEFAULT 'v1',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_a50_daily_pk
    ON a50_daily_ohlcv(ts_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_a50_daily_date
    ON a50_daily_ohlcv(trade_date);
CREATE INDEX IF NOT EXISTS idx_a50_daily_code
    ON a50_daily_ohlcv(ts_code);
"""

DDL_A50_CROSS_IC_RESULT = """
CREATE TABLE IF NOT EXISTS a50_cross_ic_result (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT    NOT NULL,  -- 截面日期YYYYMMDD
    factor_name     TEXT    NOT NULL,  -- 因子名，全小写+下划线
    ic_value        REAL,              -- Pearson截面IC（计算失败=NULL）
    rank_ic         REAL,              -- Spearman秩相关IC（计算失败=NULL）
    p_value         REAL,              -- p-value显著性检验
    num_stocks      INTEGER NOT NULL,  -- 有效样本数
    adjusted_ic     REAL,              -- 剔除极值±3σ后重算的Pearson IC（未剔除=NULL）
    forward_window  INTEGER NOT NULL DEFAULT 5,  -- 预测窗口（交易日数）
    source_version  TEXT    NOT NULL,  -- 版本锚定
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(trade_date, factor_name, source_version, forward_window)
);

CREATE INDEX IF NOT EXISTS idx_ic_factor
    ON a50_cross_ic_result(factor_name);
CREATE INDEX IF NOT EXISTS idx_ic_date
    ON a50_cross_ic_result(trade_date);
"""

DDL_A50_UNIVERSE = """
CREATE TABLE IF NOT EXISTS a50_universe (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code         TEXT    NOT NULL,
    stock_name      TEXT,
    in_date         TEXT    NOT NULL,  -- YYYYMMDD
    out_date        TEXT,              -- YYYYMMDD, NULL=仍在成分股中
    weight          REAL,              -- 权重（若可用）
    source          TEXT    NOT NULL DEFAULT 'tushare',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(ts_code, in_date)
);

CREATE INDEX IF NOT EXISTS idx_universe_code_in_date ON a50_universe(ts_code, in_date);
CREATE INDEX IF NOT EXISTS idx_universe_in_out_date ON a50_universe(in_date, out_date);
"""

# 验证用索引列表
TABLES_AND_INDICES = {
    "a50_daily_ohlcv": ["idx_a50_daily_pk", "idx_a50_daily_date", "idx_a50_daily_code"],
    "a50_cross_ic_result": ["idx_ic_factor", "idx_ic_date"],
    "a50_universe": ["idx_universe_code_in_date", "idx_universe_in_out_date"],
}

# ============================================================
# 验证 SQL
# ============================================================

CHECK_TABLES_SQL = """
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;
"""

CHECK_INDICES_FOR_TABLE = """
SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? ORDER BY name;
"""

PRAGMA_FOREIGN_KEYS_SQL = "PRAGMA foreign_keys;"

# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("A50截面IC数据库表结构创建 - create_tables.py")
    print(f"设计依据: {DESIGN_REF}")
    print(f"时间: {datetime.now(TZ).strftime('%Y-%m-%dT%H:%M:%S+08:00')}")
    print("=" * 60)

    # 确保目录存在
    os.makedirs(DB_DIR, exist_ok=True)

    # 连接数据库（会自动创建文件）
    conn = sqlite3.connect(DB_PATH)
    print(f"\n[1/4] 数据库文件: {DB_PATH}")

    try:
        # 开启外键约束
        conn.execute("PRAGMA foreign_keys = ON;")
        foreign_keys_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        print(f"\n[PRAGMA] foreign_keys: {'ON' if foreign_keys_status else 'OFF'}")

        # Step 1: 创建 a50_daily_ohlcv（含索引）
        print("\n[2/4] 创建表: a50_daily_ohlcv（含索引）...")
        conn.executescript(DDL_A50_DAILY_OHLCV)
        print("  [OK] a50_daily_ohlcv 创建成功")

        # Step 2: 创建 a50_cross_ic_result（含索引）
        print("\n[2/4] 创建表: a50_cross_ic_result（含索引）...")
        conn.executescript(DDL_A50_CROSS_IC_RESULT)
        print("  [OK] a50_cross_ic_result 创建成功")

        # Step 3: 创建 a50_universe（含索引）
        print("\n[2/4] 创建表: a50_universe（含索引）...")
        conn.executescript(DDL_A50_UNIVERSE)
        print("  [OK] a50_universe 创建成功")

        conn.commit()

        # Step 4: 验证
        print("\n[3/4] 验证表结构...")

        # 验证3表完整
        tables = conn.execute(CHECK_TABLES_SQL).fetchall()
        table_names = [t[0] for t in tables]
        print(f"  表列表 (.tables): {table_names}")
        for expected in ["a50_daily_ohlcv", "a50_cross_ic_result", "a50_universe"]:
            assert expected in table_names, f"{expected} 不存在!"
        print("  [OK] 3张表均已创建")

        # 验证索引完整
        all_indices_pass = True
        for table_name, expected_indices in TABLES_AND_INDICES.items():
            indices = conn.execute(CHECK_INDICES_FOR_TABLE, (table_name,)).fetchall()
            index_names = [i[0] for i in indices]
            print(f"  {table_name} 索引 (.indices): {index_names}")
            for idx_name in expected_indices:
                if idx_name not in index_names:
                    print(f"    [FAIL] 缺少索引: {idx_name}")
                    all_indices_pass = False
                else:
                    print(f"    [OK] {idx_name}")
        assert all_indices_pass, "索引验证失败!"

        fk_status = conn.execute(PRAGMA_FOREIGN_KEYS_SQL).fetchone()[0]
        print(f"\n  PRAGMA foreign_keys: {'ON' if fk_status else 'OFF'}")
        assert fk_status == 1, "PRAGMA foreign_keys 不为 ON!"

        print(f"\n[4/4] [OK] 全部完成。数据库已就绪: {DB_PATH}")
        file_size_kb = os.path.getsize(DB_PATH) / 1024
        print(f"  文件大小: {file_size_kb:.1f} KB")
        print(f"  表数量: {len(table_names)}")
        print(f"  索引总数: {sum(len(v) for v in TABLES_AND_INDICES.values())}")

    except Exception as e:
        print(f"\n[FAILED] 建表失败: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
