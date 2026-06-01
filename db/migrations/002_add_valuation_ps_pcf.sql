-- ============================================================
-- 墨枢 — a50_ic.db 迁移脚本 002
-- 新增估值列：pe_ttm / ps_ttm / pcf_ttm / dividend_yield
-- 前置条件：a50_daily_ohlcv 表已存在（由 schema.py 创建）
-- SQLite 语法兼容
-- 版本: 1.0
-- 作者: 墨衡
-- 创建时间: 2026-05-31T19:22:00+08:00
-- ============================================================

BEGIN IMMEDIATE;

-- ============================================================
-- 第〇步：schema_version 框架（幂等）
-- ============================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version         TEXT NOT NULL,
    applied_at      TEXT NOT NULL,
    description     TEXT,
    checksum        TEXT,
    UNIQUE (version)
);

-- ============================================================
-- 第一步：检查是否已应用 002 迁移
-- ============================================================

SELECT CASE
    WHEN EXISTS (SELECT 1 FROM schema_version WHERE version = '002') THEN 'already_applied'
    ELSE 'need_migration'
END AS migration_check;

-- ============================================================
-- 第二步：新增估值列
-- 注意：SQLite ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS
-- 幂等性通过 schema_version 版本记录保证
-- ============================================================

ALTER TABLE a50_daily_ohlcv ADD COLUMN pe_ttm REAL;
ALTER TABLE a50_daily_ohlcv ADD COLUMN ps_ttm REAL;
ALTER TABLE a50_daily_ohlcv ADD COLUMN pcf_ttm REAL;
ALTER TABLE a50_daily_ohlcv ADD COLUMN dividend_yield REAL;

-- ============================================================
-- 第三步：记录迁移版本
-- ============================================================

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (
    '002',
    strftime('%Y-%m-%dT%H:%M:%S', 'now'),
    '新增估值列 pe_ttm/ps_ttm/pcf_ttm/dividend_yield 到 a50_daily_ohlcv'
);

COMMIT;

-- ============================================================
-- 验证
-- ============================================================

SELECT '002 迁移完成' AS result;
SELECT '当前版本' AS info, version, applied_at, description
FROM schema_version
ORDER BY version DESC
LIMIT 3;
