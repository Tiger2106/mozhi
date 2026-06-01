"""
migrate_daily_basic.py — ALTER TABLE a50_daily_ohlcv 新增估值字段

Ring 3a: 为 a50_daily_ohlcv 表添加缺失的估值列：
  - pe_ttm       DECIMAL(12,4)  — 滚动市盈率
  - ps_ttm       DECIMAL(12,4)  — 市销率（TTM）
  - pcf_ttm      DECIMAL(12,4)  — 市现率（TTM，premium）
  - dividend_yield DECIMAL(9,4) — 股息率（premium）
  - ps_ttm_category TEXT        — ps_ttm 数据质量标记

修复引用：cross_sectional_ic_pipeline.py → a50_daily_ohlcv 表

Author: moheng, 2026-05-31
"""

import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 待新增的估值列（列名, 类型, 注释）
NEW_COLUMNS = [
    ('pe_ttm',          'REAL',         '滚动市盈率（TTM）'),
    ('ps_ttm',          'REAL',         '市销率（TTM，需≥2000积分）'),
    ('pcf_ttm',         'REAL',         '市现率（TTM，需≥2000积分）'),
    ('dividend_yield',  'REAL',         '股息率（%，需≥2000积分）'),
    ('ps_ttm_category', 'TEXT',         'ps_ttm 数据质量标记：available/missing_premium/null_value'),
]


def get_db_path() -> str:
    """获取 a50_ic.db 路径"""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'data', 'market', 'a50_ic.db'
    )


def get_existing_columns(db_path: str) -> set:
    """获取 a50_daily_ohlcv 现有列名"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute('PRAGMA table_info(a50_daily_ohlcv)')
        return {row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def migrate_schema(db_path: str, dry_run: bool = False) -> Dict[str, list]:
    """执行 ALTER TABLE ADD COLUMN 迁移

    Args:
        db_path: 数据库路径
        dry_run: 仅检查不做改动

    Returns:
        迁移结果统计
    """
    existing = get_existing_columns(db_path)
    stats = {'added': [], 'skipped': [], 'errors': []}

    for col_name, col_type, comment in NEW_COLUMNS:
        if col_name in existing:
            stats['skipped'].append(f'{col_name} (already exists)')
            continue

        if dry_run:
            stats['added'].append(f'{col_name} {col_type} (dry-run, not executed)')
            continue

        sql = f'ALTER TABLE a50_daily_ohlcv ADD COLUMN {col_name} {col_type}'
        if col_type == 'TEXT':
            sql += ' DEFAULT NULL'
        elif col_type == 'REAL':
            sql += ' DEFAULT NULL'

        try:
            conn = sqlite3.connect(db_path)
            conn.execute(sql)
            conn.commit()
            stats['added'].append(f'{col_name} {col_type}')
            logger.info(f'Added column {col_name} {col_type} to a50_daily_ohlcv')
        except Exception as e:
            conn.rollback()
            stats['errors'].append(f'{col_name}: {e}')
            logger.error(f'Failed to add {col_name}: {e}')
        finally:
            conn.close()

    return stats


def verify_migration(db_path: str) -> dict:
    """验证迁移后包含所有目标列"""
    existing = get_existing_columns(db_path)
    target_cols = {c[0] for c in NEW_COLUMNS}
    present = target_cols & existing
    missing = target_cols - existing

    return {
        'target': list(target_cols),
        'present': list(present),
        'missing': list(missing),
        'complete': len(missing) == 0,
    }


def count_valuation_non_null(db_path: str, column: str) -> int:
    """统计某列非 NULL 行数"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            f'SELECT COUNT(*) FROM a50_daily_ohlcv WHERE {column} IS NOT NULL'
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    parser = argparse.ArgumentParser(description='a50_daily_ohlcv 估值字段迁移')
    parser.add_argument('--db', default=None, help='数据库路径')
    parser.add_argument('--dry-run', action='store_true', help='仅检查不做改动')
    parser.add_argument('--verify', action='store_true', help='验证迁移结果')
    parser.add_argument('--count', action='store_true', help='统计非空数据行数')

    args = parser.parse_args()
    db_path = args.db or get_db_path()

    print(f'DB: {db_path}')
    print(f'Exists: {os.path.exists(db_path)}\n')

    if args.verify:
        result = verify_migration(db_path)
        print('Verification:')
        print(f'  Target columns: {result["target"]}')
        print(f'  Present:       {result["present"]}')
        print(f'  Missing:       {result["missing"]}')
        print(f'  Complete:      {result["complete"]}')
        exit(0)

    if args.count:
        for col_name, _, _ in NEW_COLUMNS:
            count = count_valuation_non_null(db_path, col_name)
            print(f'  {col_name}: {count} non-null rows')
        exit(0)

    stats = migrate_schema(db_path, dry_run=args.dry_run)
    print('Migration results:')
    print(f'  Added:   {stats["added"]}')
    print(f'  Skipped: {stats["skipped"]}')
    print(f'  Errors:  {stats["errors"]}')
    print(f'  Status:  {"SUCCESS" if not stats["errors"] else "PARTIAL"}')
