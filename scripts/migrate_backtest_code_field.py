#!/usr/bin/env python3
"""
墨枢 — P6: backtest_results 表迁移脚本
=============================================
添加 code TEXT 字段，兼容旧记录（code=NULL 时通过 strategy_name 反解析）。

执行: python scripts/migrate_backtest_code_field.py
回滚: python scripts/migrate_backtest_code_field.py --revert

Author: 墨衡
Created: 2026-05-16
"""

import sqlite3
import re
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 配置 ──────────────────────────────────────────────────────
DB_PATH = Path.home() / "mo_zhi_sharereports" / "analysis.db"

# strategy_name 反解析模式：匹配 "XXX_601857"、"XXX_601857.SH"、"601857_xxx" 等
_CODE_RE = re.compile(r"(?P<code>\d{6})")

# grid 网格策略的 symbol 硬编码
_GRID_SYMBOL = "601857"


def extract_code_from_strategy_name(strategy_name: str) -> Optional[str]:
    """从 strategy_name 反解析标的代码"""
    if not strategy_name:
        return None
    m = _CODE_RE.search(strategy_name)
    if m:
        return m.group("code")
    return None


def extract_code_from_params(params_json: str) -> Optional[str]:
    """从 parameters JSON 中解析 code/symbol 字段"""
    if not params_json:
        return None
    try:
        params = json.loads(params_json)
        if isinstance(params, dict):
            # 优先检查 symbol 字段
            for key in ("symbol", "code", "stock_code", "underlying"):
                val = params.get(key)
                if val and isinstance(val, str) and _CODE_RE.match(val):
                    m = _CODE_RE.match(val)
                    return m.group("code")
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def migrate_add_code_field(db_path: Path) -> dict:
    """对 backtest_results 表执行 ALTER TABLE ADD COLUMN code TEXT"""
    result = {
        "status": "",
        "total_rows": 0,
        "migrated_count": 0,
        "unresolved_count": 0,
        "error": "",
    }

    if not db_path.exists():
        result["status"] = "FAILED"
        result["error"] = f"数据库不存在: {db_path}"
        return result

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 1. 检查列是否已存在
        cur = conn.execute("PRAGMA table_info(backtest_results)")
        existing_cols = {r["name"] for r in cur.fetchall()}
        if "code" in existing_cols:
            result["status"] = "SKIPPED"
            result["error"] = "code 字段已存在，无需迁移"
            return result

        # 2. ALTER TABLE 添加列
        conn.execute("ALTER TABLE backtest_results ADD COLUMN code TEXT")
        conn.commit()
        print("[migrate] ADD COLUMN code TEXT -> OK")

        # 3. 反解析旧记录：code 为 NULL 的通过 strategy_name / parameters 填充
        cur = conn.execute(
            "SELECT id, strategy_name, parameters, total_trades FROM backtest_results WHERE code IS NULL"
        )
        rows = cur.fetchall()
        result["total_rows"] = len(rows)

        resolved = 0
        unresolved = 0
        for row in rows:
            rid = row["id"]
            code = None

            # 策略 A: strategy_name 反解析
            code = extract_code_from_strategy_name(row["strategy_name"])

            # 策略 B: parameters JSON 反解析
            if not code:
                code = extract_code_from_params(row["parameters"])

            # 策略 C: 已知策略按默认值
            if not code:
                sname = (row["strategy_name"] or "").lower()
                if "grid" in sname or "601857" in sname:
                    code = _GRID_SYMBOL

            if code:
                conn.execute(
                    "UPDATE backtest_results SET code = ? WHERE id = ?",
                    (code, rid),
                )
                resolved += 1
                print(f"[migrate]   id={rid}: strategy_name={row['strategy_name']!r} -> code={code}")
            else:
                unresolved += 1
                print(f"[migrate]   id={rid}: cannot resolve code (strategy_name={row['strategy_name']!r})")

        conn.commit()
        result["migrated_count"] = resolved
        result["unresolved_count"] = unresolved
        result["status"] = "READY"
        print(f"[migrate] done: resolve={resolved}, unresolved={unresolved}")

    except Exception as e:
        conn.rollback()
        result["status"] = "FAILED"
        result["error"] = str(e)
        print(f"[migrate] error: {e}")
    finally:
        conn.close()

    return result


# ── 旧 schema（不含 code 字段，用于回滚）─────────────────────────
_OLD_SCHEMA_SQL = """CREATE TABLE backtest_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT,
    start_date      TEXT,
    end_date        TEXT,
    initial_capital REAL,
    final_value     REAL,
    total_return    REAL,
    annual_return   REAL,
    max_drawdown    REAL,
    sharpe_ratio    REAL,
    win_rate        REAL,
    total_trades    INTEGER,
    parameters      TEXT,
    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
)"""


def revert_add_code_field(db_path: Path) -> dict:
    """回滚：移除 code 字段（RENAME+CREATE 策略）"""
    result = {"status": "", "error": ""}
    if not db_path.exists():
        result["status"] = "FAILED"
        result["error"] = f"数据库不存在: {db_path}"
        return result
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("PRAGMA table_info(backtest_results)")
        existing_cols = {r["name"] for r in cur.fetchall()}
        if "code" not in existing_cols:
            result["status"] = "SKIPPED"
            result["error"] = "code 字段已不存在，无需回滚"
            return result
        conn.execute("ALTER TABLE backtest_results RENAME TO backtest_results_old")
        conn.execute(_OLD_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO backtest_results ("
            "    id, strategy_name, start_date, end_date,"
            "    initial_capital, final_value, total_return, annual_return,"
            "    max_drawdown, sharpe_ratio, win_rate, total_trades,"
            "    parameters, created_at"
            ") "
            "SELECT"
            "    id, strategy_name, start_date, end_date,"
            "    initial_capital, final_value, total_return, annual_return,"
            "    max_drawdown, sharpe_ratio, win_rate, total_trades,"
            "    parameters, created_at "
            "FROM backtest_results_old"
        )
        conn.execute("DROP TABLE backtest_results_old")
        conn.commit()
        result["status"] = "READY"
        print("[revert] 回滚成功: 已移除 code 字段")
    except Exception as e:
        conn.rollback()
        result["status"] = "FAILED"
        result["error"] = str(e)
        print(f"[revert] error: {e}")
    finally:
        conn.close()
    return result


def main():
    """命令行入口"""
    # --revert 回滚模式
    if "--revert" in sys.argv:
        print("[revert] 开始回滚 backtest_results 表（移除 code 字段）")
        print(f"[revert] 数据库: {DB_PATH}")
        result = revert_add_code_field(DB_PATH)
        summary = {
            "script": "migrate_backtest_code_field.py",
            "mode": "revert",
            "completed_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            **result,
        }
        summary_path = DB_PATH.parent / f"revert_code_field_{datetime.now():%Y%m%d_%H%M%S}_result.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[revert] 结果已写入: {summary_path}")
        if result["status"] == "FAILED":
            sys.exit(1)
        print("[revert] OK")
        return

    print("[migrate] 开始迁移 backtest_results 表 (code 字段)")
    print(f"[migrate] 数据库: {DB_PATH}")
    result = migrate_add_code_field(DB_PATH)

    # 写入结果摘要
    summary = {
        "script": "migrate_backtest_code_field.py",
        "completed_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        **result,
    }
    summary_path = DB_PATH.parent / f"migrate_code_field_{datetime.now():%Y%m%d_%H%M%S}_result.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[migrate] 结果已写入: {summary_path}")

    if result["status"] == "FAILED":
        sys.exit(1)
    print(f"[migrate] OK: {result['status']}")


if __name__ == "__main__":
    main()
