-- ============================================================
-- 墨枢回测结果数据库 — SQLite DDL v4
-- 基于 v3 执行层 + v4 分析层（会议定调 2026-05-23）
-- v3→v4 变更：新增 5 张分析层表，不修改 v3 执行层表
-- 生成时间: 2026-05-23
-- 版本: v4.1
-- 作者: 墨衡
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA encoding = 'UTF-8';

-- ============================================================
-- 第一部分：v3 执行层（保留完整）
-- ============================================================

-- ------------------------------------------------------------
-- 1. BACKTEST_RUN — 根节点，每次回测一行
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_run (
    id              TEXT PRIMARY KEY,               -- UUID，每次回测唯一标识
    run_name        TEXT NOT NULL,                  -- 可读名称，如 "trend_ma5_20_601857_20260523"
    version_tag     TEXT,                           -- 代码版本标签，如 git commit hash
    created_at      TEXT NOT NULL                   -- ISO 8601
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    status          TEXT NOT NULL                   -- pending / running / done / failed
                    DEFAULT 'pending'
                    CHECK (status IN ('pending','running','done','failed')),
    triggered_by    TEXT,                           -- 触发来源，如 "墨衡" / "scheduler"
    periods         TEXT,                           -- JSON: 回测时间段
                                                     -- [{"label":"全周期","start":"20200101","end":"20260522","trading_days":1545}]
                                                     -- periods[0].start 对应引擎 BacktestConfig.actual_start
    notes           TEXT                            -- 自由文本备注
);

-- ------------------------------------------------------------
-- 2. STRATEGY_CONFIG — 策略层参数
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strategy_config (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    strategy_type       TEXT NOT NULL,              -- "single_factor" / "multi_factor" / "combined"
    signal_defined_path TEXT,                       -- signal_defined_{task_id}.json 路径
    entry_rules         TEXT,                       -- JSON: 入场规则描述
    exit_rules          TEXT,                       -- JSON: 出场规则描述（含止损/止盈）
    initial_capital     REAL NOT NULL DEFAULT 1000000.0,
    commission_rate     REAL NOT NULL DEFAULT 0.0003,
    min_fee             REAL NOT NULL DEFAULT 5.0,  -- 最低手续费（引擎 BacktestConfig.min_fee 默认 5.0）
    slippage_rate       REAL NOT NULL DEFAULT 0.001,
    position_sizing     TEXT NOT NULL DEFAULT 'equal',  -- "equal" / "volatility" / "factor_weight"
    max_positions       INTEGER NOT NULL DEFAULT 5
);

-- ------------------------------------------------------------
-- 3. FACTOR_CONFIG — 因子层参数（每因子一行）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_config (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    factor_name     TEXT NOT NULL,                  -- 如 "tsi" / "adx" / "ma_slope"
    factor_version  TEXT,                           -- 因子代码版本
    params          TEXT,                           -- JSON: 因子计算参数
    data_source     TEXT NOT NULL DEFAULT 'tushare',
    adj_method      TEXT NOT NULL DEFAULT 'qfq',    -- "qfq" / "hfq" / "none"
    adj_base_date   TEXT,                           -- 复权基准日 YYYYMMDD
    free_float_src  TEXT,                           -- 自由流通股本数据源
    weight          REAL DEFAULT 1.0,               -- 在策略中的权重
    UNIQUE (run_id, factor_name)
);

-- ------------------------------------------------------------
-- 4. UNIVERSE — 标的池
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS universe (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    ts_code             TEXT NOT NULL,              -- 如 "601857.SH"
    name                TEXT,
    market              TEXT,                       -- "SH" / "SZ" / "BJ"
    industry            TEXT,                       -- 申万行业
    free_float_shares   REAL,                       -- 自由流通股本（万股）
    free_float_source   TEXT,
    added_date          TEXT,
    removed_date        TEXT,
    UNIQUE (run_id, ts_code)
);

-- ------------------------------------------------------------
-- 5. FACTOR_RESULT — 因子 IC/IR 检验结果
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor_result (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    factor_id           TEXT NOT NULL REFERENCES factor_config(id),
    ts_code             TEXT,                       -- NULL 表示全标的汇总
    mean_ic             REAL,
    std_ic              REAL,
    ir                  REAL,                       -- mean_ic / std_ic
    ic_positive_ratio   REAL,                       -- IC > 0 的天数占比
    test_days           INTEGER,
    ic_ts               TEXT,                       -- JSON: 每日IC时序
    ic_cumulative       TEXT                        -- JSON: 累计IC时序
);

-- ------------------------------------------------------------
-- 6. PERFORMANCE_SUMMARY — 绩效汇总
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS performance_summary (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    ts_code             TEXT,                       -- NULL 表示组合整体
    total_return        REAL,                       -- 区间总收益率（小数）
    annualized_return   REAL,                       -- 年化收益率
    benchmark_return    REAL,                       -- 基准收益率
    excess_return       REAL,                       -- 超额收益
    max_drawdown        REAL,                       -- 最大回撤
    max_drawdown_start  TEXT,
    max_drawdown_end    TEXT,
    sharpe_ratio        REAL,
    calmar_ratio        REAL,
    sortino_ratio       REAL,
    win_rate            REAL,                       -- 盈利交易占比
    profit_factor       REAL,                       -- 总盈利 / 总亏损绝对值
    total_trades        INTEGER,
    avg_holding_days    REAL,
    turnover_rate       REAL,                       -- 年化换手率
    -- v3 新增风险指标
    volatility          REAL,                       -- 年化波动率
    downside_volatility REAL,                       -- 年化下行波动率
    var_95_pct          REAL,                       -- 95% VaR
    max_consecutive_wins     INTEGER DEFAULT 0,
    max_consecutive_losses   INTEGER DEFAULT 0,
    final_equity        REAL,                       -- 最终权益
    equity_curve        TEXT,                       -- JSON: 净值曲线 [{date, equity}]
    daily_returns       TEXT                        -- JSON: 日收益率序列 [{date, return_pct}]
);

-- ------------------------------------------------------------
-- 7. TRADE_LOG — 交易明细
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_log (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    ts_code         TEXT NOT NULL,
    signal_date     TEXT NOT NULL,                  -- 信号产生日期
    entry_date      TEXT NOT NULL,                  -- 实际成交日期
    exit_date       TEXT,                           -- NULL 表示持仓中
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    avg_trade_price REAL,                           -- amount / volume 成交均价
    volume          REAL NOT NULL,                  -- 成交量（股数）
    amount          REAL,                           -- 成交金额
    direction       TEXT NOT NULL DEFAULT 'buy'
                    CHECK (direction IN ('buy','sell','short')),  -- 匹配引擎 OrderSide
    order_type      TEXT NOT NULL DEFAULT 'market'
                    CHECK (order_type IN ('market','limit')),     -- v3: 新增
    pnl             REAL,
    pnl_pct         REAL,
    commission      REAL,
    slippage        REAL,
    exit_reason     TEXT                            -- "signal" / "stop_loss" / "take_profit" / "limit_up" / "limit_down" / "end_of_period"
);

-- ------------------------------------------------------------
-- 8. DAILY_SNAPSHOT — 逐日持仓快照
--   对应 TradeLogger.DailySnapshot，补齐未成交信号追溯与组合重构能力
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_snapshot (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    ts_code         TEXT NOT NULL,
    trade_date      TEXT NOT NULL,
    holding_shares  REAL NOT NULL DEFAULT 0,        -- 持仓股数
    avg_cost        REAL,                           -- 持仓成本
    market_value    REAL NOT NULL DEFAULT 0,         -- 市值
    daily_pnl       REAL,                           -- 当日盈亏
    cumulative_pnl  REAL,                           -- 累计盈亏
    weight_pct      REAL,                           -- 占组合市值比例（%）
    UNIQUE (run_id, ts_code, trade_date)
);

-- ------------------------------------------------------------
-- 9. VALIDATION_CHECK — 自洽性与数据质量验证
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS validation_check (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    check_name      TEXT NOT NULL,                  -- 如 "p2_self_consistency" / "price_rmse" / "ic_pearson"
    check_type      TEXT NOT NULL
                    CHECK (check_type IN ('self_consistency','data_quality','factor_logic')),
    result          TEXT NOT NULL
                    CHECK (result IN ('pass','fail','warning')),
    actual_value    REAL,
    threshold_value REAL,
    detail          TEXT,
    checked_at      TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- ============================================================
-- 第二部分：v4 分析层（新增 5 张表）
-- ============================================================

-- ------------------------------------------------------------
-- 10. ANALYSIS_META — 分析入口
--    每行代表一次分析会话（人工或自动触发）
--    parent_session_id 支持自引用，形成分析链
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_meta (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    parent_session_id   INTEGER,                    -- 自引用 SELF-REFERENCE，父分析 ID
    tags                TEXT,                       -- JSON: 分类标签数组
    version_schema      TEXT,                       -- 如 "1.0"
    version_content     INTEGER,                    -- 内容迭代版本号
    version_status      TEXT NOT NULL               -- draft / reviewed / final / archived
                        DEFAULT 'draft'
                        CHECK (version_status IN ('draft','reviewed','final','archived')),
    author              TEXT,                       -- 分析人/Agent 名称
    analysis_type       TEXT NOT NULL               -- summary / deep_analysis / tech_review / validation / resolution
                        CHECK (analysis_type IN ('summary','deep_analysis','tech_review','validation','resolution')),
    created_at          TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at          TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- ------------------------------------------------------------
-- 11. ANALYSIS_METRICS_CORE — 核心通用指标
--    每个 analysis_id 五行（对应 metric_group 枚举）或仅一行
--    包含约 25 个预定义指标字段
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_metrics_core (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id             INTEGER NOT NULL REFERENCES analysis_meta(id) ON DELETE CASCADE,
    run_id                  TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    metric_group            TEXT NOT NULL            -- daily / weekly / param_sweep / factor_ic
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
    verdict                 TEXT,                   -- 分析结论
    risk_level              TEXT DEFAULT 'mid',     -- low / mid / high
                            CHECK (risk_level IN ('low','mid','high')),
    core_issue              TEXT,                   -- 核心问题描述
    improvement_potential   TEXT,                   -- 改进潜力描述
    created_at              TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at              TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- ------------------------------------------------------------
-- 12. ANALYSIS_METRICS_EXT — 扩展指标
--    存储 analysis_metrics_core 未覆盖的自定义指标
--    K-V 结构，支持任意扩展
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_metrics_ext (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id     INTEGER NOT NULL REFERENCES analysis_metrics_core(id) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    metric_group    TEXT,                           -- 可选的扩展分组
    metric_name     TEXT NOT NULL,                  -- 指标名称
    metric_value    REAL,                           -- 指标数值
    metric_label    TEXT,                           -- 可读标签/单位
    created_at      TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- ------------------------------------------------------------
-- 13. ANALYSIS_DOCS — 文档索引
--    记录每次分析生成的各类文档
--    软删除支持（is_deleted + deleted_at）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_docs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id     INTEGER NOT NULL REFERENCES analysis_meta(id) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES backtest_run(id) ON DELETE CASCADE,
    doc_type        TEXT NOT NULL                   -- summary_report / analysis_report / tech_review / validation / resolution
                    CHECK (doc_type IN ('summary_report','analysis_report','tech_review','validation','resolution')),
    file_path       TEXT,                           -- 文件相对/绝对路径
    content_hash    TEXT,                           -- SHA256 文件内容哈希
    file_size_bytes INTEGER,                        -- 文件大小（字节）
    word_count      INTEGER,                        -- 文档字数
    is_deleted      INTEGER NOT NULL DEFAULT 0      -- 0=正常, 1=已删除
                    CHECK (is_deleted IN (0, 1)),
    deleted_at      TEXT,                           -- 软删除时间
    created_at      TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at      TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    UNIQUE (analysis_id, doc_type)
);

-- ------------------------------------------------------------
-- 14. SCHEMA_VERSION — 数据库版本追踪
--    记录架构变更历史，支撑迁移脚本确定性执行
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version         TEXT NOT NULL,                  -- 如 "2", "3", "4"
    applied_at      TEXT NOT NULL,                  -- 应用的 ISO 8601 时间戳
    description     TEXT,                           -- 版本说明
    checksum        TEXT,                           -- DDL SHA256 校验（可选）
    UNIQUE (version)
);

-- ============================================================
-- 执行层索引（v3 保留）
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_fc_run ON factor_config(run_id);
CREATE INDEX IF NOT EXISTS idx_fr_run ON factor_result(run_id, factor_id);
CREATE INDEX IF NOT EXISTS idx_fr_ts  ON factor_result(run_id, ts_code);
CREATE INDEX IF NOT EXISTS idx_tl_run ON trade_log(run_id, ts_code);
CREATE INDEX IF NOT EXISTS idx_tl_date ON trade_log(run_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_ps_run ON performance_summary(run_id);
CREATE INDEX IF NOT EXISTS idx_vc_type ON validation_check(run_id, check_type, result);
CREATE INDEX IF NOT EXISTS idx_sc_run ON strategy_config(run_id);
CREATE INDEX IF NOT EXISTS idx_ds_run  ON daily_snapshot(run_id, trade_date);

-- ============================================================
-- 分析层索引（v4 新增）
-- ============================================================
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

-- ============================================================
-- 视图（v3 保留，v4 新增分析视图）
-- ============================================================

-- 视图1：有效因子概览（IR > 0.05）
CREATE VIEW IF NOT EXISTS v_effective_factors AS
SELECT
    r.run_name,
    r.version_tag,
    fr.ts_code,
    fc.factor_name,
    fr.mean_ic,
    fr.ir,
    fr.ic_positive_ratio,
    fr.test_days
FROM factor_result fr
JOIN backtest_run r ON r.id = fr.run_id
LEFT JOIN factor_config fc ON fc.id = fr.factor_id
WHERE fr.ir > 0.05
ORDER BY fr.ir DESC;

-- 视图2：回测绩效对比（跨 run 横向比较）
CREATE VIEW IF NOT EXISTS v_run_comparison AS
SELECT
    r.run_name,
    r.version_tag,
    r.created_at,
    ps.ts_code,
    ps.total_return,
    ps.annualized_return,
    ps.excess_return,
    ps.max_drawdown,
    ps.sharpe_ratio,
    ps.win_rate,
    ps.total_trades
FROM performance_summary ps
JOIN backtest_run r ON r.id = ps.run_id
WHERE r.status = 'done'
ORDER BY r.created_at DESC;

-- 视图3：验证失败清单
CREATE VIEW IF NOT EXISTS v_validation_failures AS
SELECT
    r.run_name,
    vc.check_name,
    vc.check_type,
    vc.result,
    vc.actual_value,
    vc.threshold_value,
    vc.detail,
    vc.checked_at
FROM validation_check vc
JOIN backtest_run r ON r.id = vc.run_id
WHERE vc.result IN ('fail', 'warning')
ORDER BY vc.checked_at DESC;

-- 视图4：交易成本分析（v3 修复 PnL 逻辑）
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

-- ------------------------------------------------------------
-- v4 新增视图

-- 视图5：分析概览 — 关联 analysis_meta 与 core 指标
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

-- 视图6：文档索引快照
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

-- 视图7：分析链追踪 — 通过 parent_session_id 追溯
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
