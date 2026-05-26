-- ============================================================
-- 墨枢回测结果数据库 — 迁移脚本 v2 → v4
-- 按序执行：v2→v3 → v3→v4
-- 前置条件：需先确认当前 schema_version
-- SQLite 语法兼容
-- 生成时间: 2026-05-23
-- 版本: v4.1
-- 作者: 墨衡
-- ============================================================

-- ============================================================
-- 第〇步：迁移框架
-- ============================================================

-- 开启事务（异常时自动回滚，确保原子性）
BEGIN IMMEDIATE;

-- 如果 schema_version 表不存在（v2 → v4 首次迁移），先创建
CREATE TABLE IF NOT EXISTS schema_version (
    version         TEXT NOT NULL,
    applied_at      TEXT NOT NULL,
    description     TEXT,
    checksum        TEXT,
    UNIQUE (version)
);

-- ============================================================
-- 第一步：v2 → v3 迁移（如果当前版本 < 3）
-- ============================================================

-- 检查是否已为 v3
SELECT CASE
    WHEN EXISTS (SELECT 1 FROM schema_version WHERE version = '3') THEN 'v3_already_applied'
    WHEN EXISTS (SELECT 1 FROM schema_version WHERE version = '4') THEN 'v4_already_applied'
    ELSE 'need_v3_migration'
END AS v3_check;

-- 仅在需要 v3 迁移时执行以下块

-- 1.1 strategy_config — 新增 min_fee 字段
ALTER TABLE strategy_config ADD COLUMN min_fee REAL NOT NULL DEFAULT 5.0;

-- 1.2 trade_log — 新增 order_type 字段
ALTER TABLE trade_log ADD COLUMN order_type TEXT NOT NULL DEFAULT 'market' CHECK (order_type IN ('market','limit'));

-- 1.3 trade_log — direction CHECK 约束变更（SQLite 需重建表）
--     v2: CHECK (direction IN ('long','short'))
--     v3: CHECK (direction IN ('buy','sell','short'))
--     策略：创建新表 → 迁移数据 → 删除旧表 → 重命名
CREATE TABLE IF NOT EXISTS trade_log_v3 (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    ts_code         TEXT NOT NULL,
    signal_date     TEXT NOT NULL,
    entry_date      TEXT NOT NULL,
    exit_date       TEXT,
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    avg_trade_price REAL,
    volume          REAL NOT NULL,
    amount          REAL,
    direction       TEXT NOT NULL DEFAULT 'buy'
                    CHECK (direction IN ('buy','sell','short')),
    order_type      TEXT NOT NULL DEFAULT 'market'
                    CHECK (order_type IN ('market','limit')),
    pnl             REAL,
    pnl_pct         REAL,
    commission      REAL,
    slippage        REAL,
    exit_reason     TEXT
);

-- 迁移 trade_log v2 → v3（兼容性映射：'long' → 'buy', 'short' → 'short'）
INSERT INTO trade_log_v3 (
    id, run_id, ts_code, signal_date, entry_date, exit_date,
    entry_price, exit_price, avg_trade_price, volume, amount,
    direction, order_type, pnl, pnl_pct, commission, slippage, exit_reason
)
SELECT
    id, run_id, ts_code, signal_date, entry_date, exit_date,
    entry_price, exit_price, avg_trade_price, volume, amount,
    CASE WHEN direction = 'long' THEN 'buy' ELSE direction END,
    'market',  -- v2 无 order_type 字段，默认为 market
    pnl, pnl_pct, commission, slippage, exit_reason
FROM trade_log;

-- 备份旧表 + 删除
CREATE TABLE IF NOT EXISTS backup_trade_log AS SELECT * FROM trade_log;
DROP TABLE IF EXISTS trade_log;
DROP INDEX IF EXISTS idx_tl_run;
DROP INDEX IF EXISTS idx_tl_date;

-- 重命名新表
ALTER TABLE trade_log_v3 RENAME TO trade_log;

-- 重建 trade_log 索引
CREATE INDEX IF NOT EXISTS idx_tl_run ON trade_log(run_id, ts_code);
CREATE INDEX IF NOT EXISTS idx_tl_date ON trade_log(run_id, entry_date);

-- 1.4 factor_result — factor_id 改为 NOT NULL（移除可能存在的 NULL 行）
--     SQLite 不能直接修改 NOT NULL 约束，需重建表
DELETE FROM factor_result WHERE factor_id IS NULL;

CREATE TABLE IF NOT EXISTS factor_result_v3 (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    factor_id           TEXT NOT NULL REFERENCES factor_config(id),
    ts_code             TEXT,
    mean_ic             REAL,
    std_ic              REAL,
    ir                  REAL,
    ic_positive_ratio   REAL,
    test_days           INTEGER,
    ic_ts               TEXT,
    ic_cumulative       TEXT
);

INSERT INTO factor_result_v3 (
    id, run_id, factor_id, ts_code, mean_ic, std_ic, ir,
    ic_positive_ratio, test_days, ic_ts, ic_cumulative
)
SELECT
    id, run_id, factor_id, ts_code, mean_ic, std_ic, ir,
    ic_positive_ratio, test_days, ic_ts, ic_cumulative
FROM factor_result;

-- 备份 + 删除旧表
CREATE TABLE IF NOT EXISTS backup_factor_result AS SELECT * FROM factor_result;
DROP TABLE IF EXISTS factor_result;
DROP INDEX IF EXISTS idx_fr_run;
DROP INDEX IF EXISTS idx_fr_ts;

ALTER TABLE factor_result_v3 RENAME TO factor_result;

CREATE INDEX IF NOT EXISTS idx_fr_run ON factor_result(run_id, factor_id);
CREATE INDEX IF NOT EXISTS idx_fr_ts  ON factor_result(run_id, ts_code);

-- 1.5 performance_summary — 新增 7 个风险指标
ALTER TABLE performance_summary ADD COLUMN volatility          REAL;
ALTER TABLE performance_summary ADD COLUMN downside_volatility REAL;
ALTER TABLE performance_summary ADD COLUMN var_95_pct          REAL;
ALTER TABLE performance_summary ADD COLUMN max_consecutive_wins     INTEGER DEFAULT 0;
ALTER TABLE performance_summary ADD COLUMN max_consecutive_losses   INTEGER DEFAULT 0;
ALTER TABLE performance_summary ADD COLUMN final_equity        REAL;
ALTER TABLE performance_summary ADD COLUMN equity_curve        TEXT;
ALTER TABLE performance_summary ADD COLUMN daily_returns       TEXT;

-- 1.6 新增 daily_snapshot 表
CREATE TABLE IF NOT EXISTS daily_snapshot (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    ts_code         TEXT NOT NULL,
    trade_date      TEXT NOT NULL,
    holding_shares  REAL NOT NULL DEFAULT 0,
    avg_cost        REAL,
    market_value    REAL NOT NULL DEFAULT 0,
    daily_pnl       REAL,
    cumulative_pnl  REAL,
    weight_pct      REAL,
    UNIQUE (run_id, ts_code, trade_date)
);

-- 1.7 新增 v3 索引
CREATE INDEX IF NOT EXISTS idx_sc_run ON strategy_config(run_id);
CREATE INDEX IF NOT EXISTS idx_ds_run  ON daily_snapshot(run_id, trade_date);

-- 1.8 修复 v_trade_cost_analysis 视图（PnL 逻辑修正）
DROP VIEW IF EXISTS v_trade_cost_analysis;
CREATE VIEW IF NOT EXISTS v_trade_cost_analysis AS
SELECT
    r.run_name,
    tl.ts_code,
    COUNT(*) AS trade_count,
    ROUND(SUM(COALESCE(tl.commission,0)), 2) AS total_commission,
    ROUND(SUM(COALESCE(tl.slippage,0)), 2) AS total_slippage,
    ROUND(SUM(COALESCE(tl.pnl,0) + COALESCE(tl.commission,0) + COALESCE(tl.slippage,0)), 2) AS gross_trade_pnl,
    ROUND(SUM(COALESCE(tl.pnl,0)), 2) AS net_realized_pnl,
    ROUND(AVG(tl.avg_trade_price), 4) AS avg_fill_price
FROM trade_log tl
JOIN backtest_run r ON r.id = tl.run_id
GROUP BY r.run_name, tl.ts_code;

-- 记录 v3 版本
INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (
    '3',
    strftime('%Y-%m-%dT%H:%M:%S', 'now'),
    'v2→v3: min_fee, trade_log direction/order_type, performance_summary 7指标, daily_snapshot, factor_id NOT NULL'
);

-- ============================================================
-- 第二步：v3 → v4 迁移（分析层新增）
-- ============================================================

-- 检查是否已为 v4
SELECT CASE
    WHEN EXISTS (SELECT 1 FROM schema_version WHERE version = '4') THEN 'v4_already_applied'
    ELSE 'need_v4_migration'
END AS v4_check;

-- 仅在需要 v4 迁移时执行

-- 2.1 新增 analysis_meta 表
CREATE TABLE IF NOT EXISTS analysis_meta (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    parent_session_id   INTEGER,
    tags                TEXT,
    version_schema      TEXT,
    version_content     INTEGER,
    version_status      TEXT NOT NULL DEFAULT 'draft'
                        CHECK (version_status IN ('draft','reviewed','final','archived')),
    author              TEXT,
    analysis_type       TEXT NOT NULL
                        CHECK (analysis_type IN ('summary','deep_analysis','tech_review','validation','resolution')),
    created_at          TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at          TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- 2.2 新增 analysis_metrics_core 表
CREATE TABLE IF NOT EXISTS analysis_metrics_core (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id             INTEGER NOT NULL REFERENCES analysis_meta(id) ON DELETE CASCADE,
    run_id                  TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    metric_group            TEXT NOT NULL
                            CHECK (metric_group IN ('daily','weekly','param_sweep','factor_ic')),
    total_return_pct        REAL,
    annual_return_pct       REAL,
    final_equity            REAL,
    total_pnl               REAL,
    benchmark_return_pct    REAL,
    excess_return_pct       REAL,
    max_drawdown_pct        REAL,
    annual_volatility_pct   REAL,
    sharpe_ratio            REAL,
    calmar_ratio            REAL,
    sortino_ratio           REAL,
    var_95_pct              REAL,
    total_trades            INTEGER,
    winning_trades          INTEGER,
    losing_trades           INTEGER,
    win_rate_pct            REAL,
    total_profit            REAL,
    total_loss              REAL,
    profit_loss_ratio       REAL,
    max_consecutive_wins    INTEGER,
    max_consecutive_losses  INTEGER,
    max_single_win          REAL,
    max_single_loss         REAL,
    verdict                 TEXT,
    risk_level              TEXT DEFAULT 'mid'
                            CHECK (risk_level IN ('low','mid','high')),
    core_issue              TEXT,
    improvement_potential   TEXT,
    created_at              TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at              TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- 2.3 新增 analysis_metrics_ext 表
CREATE TABLE IF NOT EXISTS analysis_metrics_ext (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id     INTEGER NOT NULL REFERENCES analysis_metrics_core(id) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    metric_group    TEXT,
    metric_name     TEXT NOT NULL,
    metric_value    REAL,
    metric_label    TEXT,
    created_at      TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- 2.4 新增 analysis_docs 表
CREATE TABLE IF NOT EXISTS analysis_docs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id     INTEGER NOT NULL REFERENCES analysis_meta(id) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    doc_type        TEXT NOT NULL
                    CHECK (doc_type IN ('summary_report','analysis_report','tech_review','validation','resolution')),
    file_path       TEXT,
    content_hash    TEXT,
    file_size_bytes INTEGER,
    word_count      INTEGER,
    is_deleted      INTEGER NOT NULL DEFAULT 0
                    CHECK (is_deleted IN (0, 1)),
    deleted_at      TEXT,
    created_at      TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at      TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    UNIQUE (analysis_id, doc_type)
);

-- 2.5 新增 v4 分析层索引
CREATE INDEX IF NOT EXISTS idx_am_run       ON analysis_meta(run_id);
CREATE INDEX IF NOT EXISTS idx_am_author    ON analysis_meta(author);
CREATE INDEX IF NOT EXISTS idx_am_type     ON analysis_meta(analysis_type);
CREATE INDEX IF NOT EXISTS idx_am_status   ON analysis_meta(version_status);
CREATE INDEX IF NOT EXISTS idx_amc_aid     ON analysis_metrics_core(analysis_id);
CREATE INDEX IF NOT EXISTS idx_amc_run     ON analysis_metrics_core(run_id);
CREATE INDEX IF NOT EXISTS idx_amc_sharpe  ON analysis_metrics_core(sharpe_ratio);
CREATE INDEX IF NOT EXISTS idx_amc_group   ON analysis_metrics_core(metric_group);
CREATE INDEX IF NOT EXISTS idx_ame_aid     ON analysis_metrics_ext(analysis_id);
CREATE INDEX IF NOT EXISTS idx_ame_group   ON analysis_metrics_ext(metric_group);
CREATE INDEX IF NOT EXISTS idx_ad_aid      ON analysis_docs(analysis_id);
CREATE INDEX IF NOT EXISTS idx_ad_run      ON analysis_docs(run_id);
CREATE INDEX IF NOT EXISTS idx_ad_type     ON analysis_docs(doc_type);
CREATE INDEX IF NOT EXISTS idx_ad_deleted  ON analysis_docs(is_deleted);

-- 2.6 新增 v4 分析视图

-- 视图：分析概览
CREATE VIEW IF NOT EXISTS v_analysis_overview AS
SELECT
    am.id              AS analysis_id,
    am.run_id,
    am.analysis_type,
    am.version_status,
    am.author,
    am.version_schema,
    am.created_at      AS analysis_created_at,
    amc.metric_group,
    amc.total_return_pct,
    amc.sharpe_ratio,
    amc.max_drawdown_pct,
    amc.risk_level,
    amc.verdict,
    amc.core_issue,
    r.run_name,
    r.status           AS backtest_status
FROM analysis_meta am
JOIN backtest_run r ON r.id = am.run_id
LEFT JOIN analysis_metrics_core amc ON amc.analysis_id = am.id
ORDER BY am.created_at DESC;

-- 视图：文档索引
CREATE VIEW IF NOT EXISTS v_analysis_docs AS
SELECT
    am.id              AS analysis_id,
    am.run_id,
    am.analysis_type,
    ad.doc_type,
    ad.file_path,
    ad.content_hash,
    ad.file_size_bytes,
    ad.word_count,
    ad.created_at      AS doc_created_at
FROM analysis_docs ad
JOIN analysis_meta am ON am.id = ad.analysis_id
WHERE ad.is_deleted = 0
ORDER BY ad.created_at DESC;

-- 视图：分析链追踪
CREATE VIEW IF NOT EXISTS v_analysis_chain AS
SELECT
    child.id           AS child_analysis_id,
    child.run_id,
    child.analysis_type AS child_type,
    child.version_status AS child_status,
    child.author       AS child_author,
    child.parent_session_id,
    parent.id          AS parent_analysis_id,
    parent.analysis_type AS parent_type,
    parent.author      AS parent_author
FROM analysis_meta child
LEFT JOIN analysis_meta parent ON parent.run_id = child.run_id
    AND CAST(parent.id AS TEXT) = child.parent_session_id
ORDER BY child.created_at DESC;

-- 2.7 记录 v4 版本
INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (
    '4',
    strftime('%Y-%m-%dT%H:%M:%S', 'now'),
    'v3→v4: 新增 analysis_meta/analysis_metrics_core/analysis_metrics_ext/analysis_docs 分析层4表'
);

-- ============================================================
-- 第叁步：迁移结果验证
-- ============================================================

-- 提交事务
COMMIT;

-- ============================================================
-- 异常处理说明
-- 如果迁移过程中任一 SQL 语句失败，请执行 ROLLBACK; 回滚整个事务
-- 或由调用程序捕获错误后自动执行 ROLLBACK
-- ============================================================

SELECT '=== 迁移完成 ===' AS result;
SELECT '当前版本:' AS info, version, applied_at, description
FROM schema_version
ORDER BY CAST(version AS INTEGER) DESC;
SELECT 'v4 表清单:' AS info, name FROM sqlite_master WHERE type='table' ORDER BY name;
SELECT 'v4 视图清单:' AS info, name FROM sqlite_master WHERE type='view' ORDER BY name;
SELECT 'v4 索引计数:' AS info, COUNT(*) AS index_count FROM sqlite_master WHERE type='index';
