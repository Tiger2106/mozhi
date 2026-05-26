<!--
author: 墨衡
version: E-001 v1.0
created_time: 2026-05-20T22:43+08:00
based_on: E001_cross_source_validation.md (v1.1 定稿)
-->

# E-001 数据库结构变更方案

> 本方案基于 E-001 多源数据交叉验证算法（v1.1 定稿）设计，覆盖 staging_raw 表、validation_audit_log 表、现有表适配及迁移计划。

---

## 一、设计原则

| 原则 | 说明 |
|:-----|:-----|
| **非阻断写入** | 验证失败数据写入 staging_raw，主表对应字段写 NULL，pipeline 不停 |
| **审计必记** | 每次验证无论 verdict 均写入 audit log |
| **向前兼容** | 现有表只增列不删列，现有查询不受影响 |
| **SQLite 优先** | 当前基础设施使用 SQLite，新表以 SQLite DDL 定义，预留迁移至 PostgreSQL 的路径 |

---

## 二、新增表：staging_raw

### 2.1 用途

存放所有**未通过主表校验**的原始数据。核心原则：

- **任意字段的原始值** → 使用 JSON 列存储 flexible key-value
- **每条记录绑定一个数据源** → 通过 `source_name` 字段标识
- **记录验证 verdict 和 diff_reason** → 与 audit log 关联

### 2.2 DDL

```sql
CREATE TABLE IF NOT EXISTS staging_raw (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- ── 身份标识 ────────────────────────────────────────────
    trade_date          TEXT    NOT NULL,   -- 交易日 (YYYY-MM-DD)
    symbol              TEXT    NOT NULL,   -- 股票代码 (纯数字，如 601857)
    metric_name         TEXT    NOT NULL,   -- 字段名 (volume/amount/open/high/low/close)

    -- ── 数据来源 ────────────────────────────────────────────
    source_name         TEXT    NOT NULL,   -- API 源名称 (eastmoney/baostock/sina)
    source_type         TEXT    NOT NULL DEFAULT 'api',   -- api / minute_aggregate / manual
    api_priority        INTEGER NOT NULL DEFAULT 0,        -- 该源的优先级序号

    -- ── 原始数据 ────────────────────────────────────────────
    raw_json            TEXT    NOT NULL,   -- JSON: 完整原始 response（保留所有字段用于追溯）
    raw_value           TEXT,               -- 原始值（未归一化的字符串形式）
    raw_unit            TEXT,               -- 原始单位 (shares/lots/yuan/fens)

    -- ── 归一化数据 ──────────────────────────────────────────
    normalized_value    REAL,               -- 单位归一化后的数值
    standard_unit       TEXT,               -- 归一化后的标准单位 (shares/yuan)

    -- ── 验证结果 ────────────────────────────────────────────
    verdict             TEXT    NOT NULL DEFAULT 'PENDING',
                    -- PENDING / PASS / PASS_WITH_NOTE / REPORT / UNIT_ERROR
    diff_ab_pct         REAL,               -- A↔B 差异百分比
    diff_ac_pct         REAL,               -- A↔C 差异百分比
    diff_bc_pct         REAL,               -- B↔C 差异百分比
    diff_reason         TEXT,               -- 枚举值 (参考 E-001 §2.4)
    threshold_pct       REAL    NOT NULL DEFAULT 0.3,  -- 使用的阈值

    -- ── 审计关联 ────────────────────────────────────────────
    audit_log_id        INTEGER,            -- FK → validation_audit_log.id

    -- ── 元数据 ──────────────────────────────────────────────
    rule_version        TEXT,               -- E-001 规则版本哈希
    triggered_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_staging_raw_date_symbol
    ON staging_raw(trade_date, symbol);

CREATE INDEX IF NOT EXISTS idx_staging_raw_verdict
    ON staging_raw(verdict);

CREATE INDEX IF NOT EXISTS idx_staging_raw_source
    ON staging_raw(source_name);

CREATE INDEX IF NOT EXISTS idx_staging_raw_metric
    ON staging_raw(metric_name);

CREATE INDEX IF NOT EXISTS idx_staging_raw_audit
    ON staging_raw(audit_log_id);
```

### 2.3 raw_json 结构约定

```json
{
    "source_url": "https://push2his.eastmoney.com/api/qt/stock/kline/get?...",
    "request_params": {"secid": "1.601857", ...},
    "response_body": {"data": {"klines": [...]}},
    "extracted_value": "1234567890",
    "extraction_path": "data.klines[0].split(',')[2]",
    "retrieved_at": "2026-05-20T14:30:00+08:00"
}
```

保留 raw_json 的目的是实现 E-001 中 **"差异可解释即通过"** 原则：当溯源发现数据差异的原因时（如 API 返回了不同格式的数据），可回放原始响应确认问题来源。

---

## 三、新增表：validation_audit_log

### 3.1 用途

每次验证的**完整审计记录**。严格对应 E-001 §2.6 中的 `_build_audit_entry()` 输出结构。

### 3.2 DDL

```sql
CREATE TABLE IF NOT EXISTS validation_audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- ── 身份标识 (P0 字段) ─────────────────────────────────
    trade_date          TEXT    NOT NULL,   -- 交易日 (YYYY-MM-DD)
    symbol              TEXT    NOT NULL,   -- 股票代码 (纯数字)
    metric_name         TEXT    NOT NULL,   -- 被验证的字段名

    -- ── 源 A 信息 ──────────────────────────────────────────
    source_a_name       TEXT    NOT NULL,   -- 源 A 名称
    source_a_val        REAL,               -- 源 A 归一化值
    source_a_unit       TEXT,               -- 源 A 原始单位
                                           -- P2 策略：volume/amount 的 unit 在 Phase 1 填充
                                           -- 其余字段（open/high/low/close/pct_chg）的 unit 标记为 P2
                                           -- 理由：volume/amount 有手↔股风险，必须记录；价格单位各源一致无需单元转换

    -- ── 源 B 信息 ──────────────────────────────────────────
    source_b_name       TEXT    NOT NULL,   -- 源 B 名称
    source_b_val        REAL,               -- 源 B 归一化值
    source_b_unit       TEXT,               -- 源 B 原始单位（P2 策略同上）

    -- ── 源 C 信息（可选） ──────────────────────────────────
    source_c_name       TEXT,               -- 源 C 名称（可选）
    source_c_val        REAL,               -- 源 C 归一化值（可选）
    source_c_unit       TEXT,               -- 源 C 原始单位（P2 策略同上，可选）

    -- ── 比对结果 ──────────────────────────────────────────
    threshold_pct       REAL    NOT NULL,   -- 使用的阈值 (0.3%)
    diff_ab             REAL,               -- A↔B 差异百分比
    diff_ac             REAL,               -- A↔C 差异百分比（可选）
    diff_bc             REAL,               -- B↔C 差异百分比（可选）

    -- ── 裁决 ──────────────────────────────────────────────
    verdict             TEXT    NOT NULL,
                    -- PASS / PASS_WITH_NOTE / REPORT / UNIT_ERROR
    diff_reason         TEXT,               -- 枚举值
                    -- UNIT_CONVERTED / SPLIT_DIFF / DIVIDEND_ADJUSTED /
                    -- AFTER_HOUR_TRADE / DELAYED_SOURCE / AGGREGATION_ANCHOR / OTHER / NULL

    -- ── 分钟聚合信息 ──────────────────────────────────────
    minute_data_source  TEXT,               -- 分钟数据来源（如 eastmoney_minute / sina_minute）
    minute_aggregated   REAL,               -- 分钟聚合生成的日线值
    minute_detail_json  TEXT,               -- 分钟明细摘要 JSON（审计用）
    is_self_consistency INTEGER DEFAULT 0,  -- 0=独立仲裁 1=自洽性检查（同源分钟 vs 日线）

    -- ── 最终采用值 ────────────────────────────────────────
    selected_source     TEXT,               -- 最终采用的源名
    selected_value      REAL,               -- 最终采用的值

    -- ── 规则版本 ──────────────────────────────────────────
    rule_version        TEXT    NOT NULL,   -- E-001 规则版本哈希 (git commit sha)

    -- ── 时间戳 ────────────────────────────────────────────
    triggered_at        TEXT    NOT NULL,   -- 验证发生时间 (ISO8601, +08:00)
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_audit_log_date_symbol
    ON validation_audit_log(trade_date, symbol);

CREATE INDEX IF NOT EXISTS idx_audit_log_metric
    ON validation_audit_log(metric_name);

CREATE INDEX IF NOT EXISTS idx_audit_log_verdict
    ON validation_audit_log(verdict);

CREATE INDEX IF NOT EXISTS idx_audit_log_source_a
    ON validation_audit_log(source_a_name);

CREATE INDEX IF NOT EXISTS idx_audit_log_triggered
    ON validation_audit_log(triggered_at);

CREATE INDEX IF NOT EXISTS idx_audit_log_diff_reason
    ON validation_audit_log(diff_reason);

-- 复合索引：按股票+日期查最近验证记录
CREATE INDEX IF NOT EXISTS idx_audit_log_lookup
    ON validation_audit_log(symbol, trade_date, metric_name);

-- 复合索引：按 verdict 和日期查未解决的问题
CREATE INDEX IF NOT EXISTS idx_audit_log_report
    ON validation_audit_log(verdict, trade_date);
```

### 3.3 diff_reason 枚举值说明

| 枚举值 | 说明 | 触发条件 |
|:-------|:-----|:---------|
| `NULL` | PASS 时无差异原因 | 两源 ≤ 0.3% |
| `UNIT_CONVERTED` | 单位已转换后一致 | 第三源仲裁后单位归一化 |
| `SPLIT_DIFF` | 除权除息差异 | 单源包含/不包含除权信息 |
| `DIVIDEND_ADJUSTED` | 分红调整差异 | 复权算法差异 |
| `AFTER_HOUR_TRADE` | 盘后交易差异 | 收盘价含盘后数据 |
| `DELAYED_SOURCE` | 数据源延迟差异 | 数据更新批次不同 |
| `AGGREGATION_ANCHOR` | 分钟聚合验证锚定 | 分钟聚合与某源一致 |
| `OTHER` | 其他 | 默认值，需附注 |

### 3.4 幂等性与清理策略

#### 3.4.1 幂等键（防重复写入）

`validation_audit_log` 表新增**幂等唯一索引**，防止每日滚动批量录入产生重复行：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_log_idempotent
    ON validation_audit_log(trade_date, symbol, metric_name, source_a_name, source_b_name);
```

**幂等逻辑**：
- 同一天、同一标的、同一字段、同源对的验证结果，仅保留最新一条
- 重复写入使用 `INSERT OR REPLACE` 语义
- `triggered_at` 字段用于判断最新性，保留 `triggered_at` 最大的那条

#### 3.4.2 TTL 清理策略

**目标**：控制 `validation_audit_log` 和 `staging_raw` 的表大小，避免线性膨胀影响查询性能。

| 表 | 策略 | 说明 |
|:---|:-----|:-----|
| `validation_audit_log` | **保留 90 天** | 90 天前的审计记录可归档至压缩 JSON，表中只保留摘要 |
| `staging_raw` | **保留 30 天** | REPORT 数据超过 30 天后问题通常已被排查，不再需要保留原始行 |

**清理脚本**（建议由 cron 每日执行）：

```sql
-- validation_audit_log：删除 90 天前记录
DELETE FROM validation_audit_log
WHERE triggered_at < datetime('now', '-90 days', 'localtime');

-- staging_raw：删除 30 天前记录
DELETE FROM staging_raw
WHERE created_at < datetime('now', '-30 days', 'localtime');
```

> ⚠️ **幂等键与 TTL 配合**：幂等键防止同窗口内的重复写入，TTL 清理过期记录。两者互补，不做重复工作——幂等键是写入时的保护，TTL 是存储层的治理。

### 4.1 主表分析

当前系统中**没有 "stock_daily" 或 "market_daily" 的关系表** — 市场日线数据以 Parquet 文件形式存储在 `backtest_data_cache/` 中。

**存量数据存储路径：**

| 数据类别 | 存储方式 | 路径 |
|:---------|:---------|:-----|
| 日线 OHLCV | Parquet | `backtest_data_cache/{symbol}_{start}_{end}_qfq.parquet` |
| 回测结果 | SQLite (knowledge.db) | `backtest_runs`, `performance_results` |
| 交易信号 | SQLite (trade_engine.db) | `tech_signals`, `signal_conflicts` |
| 交易记录 | SQLite (trade_engine.db) | `transactions`, `positions`, `fund_flow` |

### 4.2 stock_daily 主表建议

**建议新增** `stock_daily` 表作为**验证后的权威日线数据存储**。与 Parquet 缓存形成双重机制：

- **Parquet 缓存层**：高性能读取、按需缓存、TTL 管理（当前 `MarketDataClient` 的机制）
- **stock_daily SQLite 表**：持久化权威数据、支持交叉验证结果、便于审计和查询

#### DDL

```sql
CREATE TABLE IF NOT EXISTS stock_daily (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- ── 主键 ──────────────────────────────────────────────
    trade_date          TEXT    NOT NULL,   -- 交易日 (YYYY-MM-DD)
    symbol              TEXT    NOT NULL,   -- 股票代码

    -- ── OHLCV ────────────────────────────────────────────
    open                REAL,
    high                REAL,
    low                 REAL,
    close               REAL,
    volume              REAL,               -- 统一单位为 股 (shares)
    amount              REAL,               -- 统一单位为 元 (yuan)
    pct_chg             REAL,               -- 涨跌幅 (%)

    -- ── 验证状态 ──────────────────────────────────────────
    validation_status   TEXT    NOT NULL DEFAULT 'PASS',
                    -- PASS / PASS_WITH_NOTE / REPORT / NULL
    validation_note     TEXT,               -- 验证备注（如有差异原因）

    -- ── 数据来源 ──────────────────────────────────────────
    primary_source      TEXT,               -- 最终采用的数据源
    all_sources_json    TEXT,               -- JSON: 参与验证的所有源列表

    -- ── 审计关联 ──────────────────────────────────────────
    latest_audit_id     INTEGER,            -- FK → validation_audit_log.id

    -- ── 元数据 ────────────────────────────────────────────
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 约束
    UNIQUE(trade_date, symbol)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_stock_daily_date
    ON stock_daily(trade_date);

CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol
    ON stock_daily(symbol);

CREATE INDEX IF NOT EXISTS idx_stock_daily_valid_status
    ON stock_daily(validation_status);

CREATE INDEX IF NOT EXISTS idx_stock_daily_lookup
    ON stock_daily(symbol, trade_date);
```

### 4.3 对其他现有表的影响

#### trade_engine.db 表

| 表名 | 影响 | 操作 |
|:-----|:-----|:-----|
| `tech_signals` | 无直接依赖（使用外部传入的价格） | 无变更 |
| `signal_conflicts` | 无直接依赖 | 无变更 |
| `fund_flow` | 无直接依赖 | 无变更 |
| `positions` | 持仓价格可从 stock_daily 获取 | 兼容（可做字段引用但不强制） |
| `transactions` | 交易价格可从 stock_daily 验证 | 兼容 |

#### knowledge.db 表

| 表名 | 影响 | 操作 |
|:-----|:-----|:-----|
| `market_context` | 市场因子计算依赖日线数据 | 无变更，数据源改为 stock_daily |
| `backtest_runs` | 回测使用 Parquet 缓存数据 | 无变更 |
| `knowledge_entries` | 无直接依赖 | 无变更 |

### 4.4 Schema 变更影响评估

| 维度 | 评估 | 说明 |
|:-----|:-----|:-----|
| **现有查询兼容性** | ✅ 完全兼容 | 现有查询读取 Parquet，与新表无关 |
| **现有代码兼容性** | ✅ 向后兼容 | `MarketDataClient.get_daily()` 仍走 Parquet；新管道写入 stock_daily |
| **读写分离** | ✅ 无锁冲突 | staging_raw 和 audit_log 只写不读（日常），不影响主表查询 |
| **数据一致性** | ⚠️ 短期双轨 | Parquet 缓存（旧）与 stock_daily（新）并存，需迁移策略 |

---

## 五、索引设计总结

| 表 | 索引名 | 用途 | 维度 |
|:---|:-------|:-----|:-----|
| staging_raw | idx_staging_raw_date_symbol | 按股票+日期查原始记录 | 复合 |
| staging_raw | idx_staging_raw_verdict | 按验证状态筛选 | 单列 |
| staging_raw | idx_staging_raw_source | 按数据源分组 | 单列 |
| staging_raw | idx_staging_raw_metric | 按字段类型筛选 | 单列 |
| staging_raw | idx_staging_raw_audit | 关联 audit log 回查 | 单列 |
| validation_audit_log | idx_audit_log_date_symbol | 按股票+日期查审计记录 | 复合 |
| validation_audit_log | idx_audit_log_metric | 按字段类型筛选 | 单列 |
| validation_audit_log | idx_audit_log_verdict | 按裁决筛选 REPORT 记录 | 单列 |
| validation_audit_log | idx_audit_log_source_a | 按源 A 统计 | 单列 |
| validation_audit_log | idx_audit_log_triggered | 按时间范围查询 | 单列 |
| validation_audit_log | idx_audit_log_diff_reason | 按差异原因统计 | 单列 |
| validation_audit_log | idx_audit_log_lookup | 快速检索单股票最近验证状态 | 复合 |
| validation_audit_log | idx_audit_log_report | 待人工介入的 REPORT 记录 | 复合 |
| validation_audit_log | **idx_audit_log_idempotent** | 幂等去重（trade_date+symbol+metric_name+source_pair）| **唯一复合** |
| stock_daily | idx_stock_daily_date | 按日期查多股票 | 单列 |
| stock_daily | idx_stock_daily_symbol | 按股票查全历史 | 单列 |
| stock_daily | idx_stock_daily_valid_status | 按验证状态筛选 | 单列 |
| stock_daily | idx_stock_daily_lookup | 精确匹配单条 | 复合 |

---

## 六、迁移计划

### 6.1 Phase 1 — 新表创建（预计 1 天）

```text
1. 运行 init_e001_db.py 创建三张新表
   - staging_raw
   - validation_audit_log
   - stock_daily（可选，可先创建，数据由管线填充）
2. 执行 dry-run 验证 DDL 兼容性
3. 对 trade_engine.db 执行 GRANT/权限检查
```

### 6.2 Phase 2 — 存量数据回填（预计 2-3 天）

```text
1. 对存量 Parquet 文件（如 601857、000001、600519）执行交叉验证
2. 使用现行 E-001 管线回填 stock_daily 表
3. 对比 Parquet 与 stock_daily 的差异
4. 写入 validation_audit_log 和 staging_raw（如有 REPORT 记录）
```

### 6.3 Phase 3 — 查询路径切换（预计 1 天）

```text
1. 为 MarketDataClient 增加 fallback 模式：
   stock_daily (验证后权威数据) → Parquet 缓存 (临时数据) → API (实时请求)
2. 保留 Parquet 缓存层不变（性能不降级）
3. 旧 Parquet 文件转为纯缓存，不承担权威数据角色
```

#### 6.3.1 切换触发条件（switch_condition）

Phase 2 → Phase 3 切换不是自动执行的，必须**同时满足**以下条件：

| 条件 | 指标 | 说明 |
|:-----|:-----|:-----|
| **必达条件** | 全部 P0 标的回填完成 | 601857、000001、600519 全部走完 E-001 全流程回填 |
| **必达条件** | REPORT 率 < 1% | 回填报告显示 P0 标的的 REPORT 率低于 1%（验证通过率 > 99%） |
| **建议条件** | 3 日并行验证期 | stock_daily 持续写入 + Parquet 持续读取，期间两个系统日线数据的总量级差异 < 1% |

> **切换决策人**：墨涵（技术负责人）手动确认切换指令。禁止自动切换。

#### 6.3.2 切换操作步骤

```text
[D0] 满足条件后，执行切换前检查
  1. 确认全部 P0 回填完成 + REPORT 率 < 1%
  2. 确认 3 日并行验证期内无系统性偏差
  3. 确认 stock_daily 表数据完整性（无 NULL 关键字段）

[D0] 执行切换
  1. 将 MarketDataClient 的 default_query_mode 从 'parquet' 改为 'authoritative'
     （authoritative 模式：stock_daily → Parquet → API）
  2. 输出切换日志：query_mode=authoritative, switched_at=<timestamp>

[D0+1 ~ D0+3] 观察期
  1. 监控 Query 失败率：若 > 5% 立即触发回滚
  2. 监控 stock_daily 读取延迟：若 > 200ms 发出性能警告
  3. 每日生成切换稳定性报告
```

#### 6.3.3 回滚步骤（切换失败时）

```text
[回滚触发条件] 以下任一满足则触发回滚：
  - Query 失败率 > 5%（连续 3 个检查点）
  - 发现 stock_daily 数据系统性错误（如字段映射错误、验证算法 bug）
  - 性能退化超过可接受阈值（读取延迟 > 200ms）

[回滚操作]
  1. 将 MarketDataClient 的 query_mode 切回 'parquet'_mode
     （parquet 模式：Parquet 缓存 → API，停用 stock_daily 作为查询源）
  2. 输出回滚日志：rolled_back_at=<timestamp>, reason=<原因>
  3. 修复问题后重新进入等待条件阶段

[回滚后处理]
  1. stock_daily 数据保留不动（只停用查询路径，不删除数据）
  2. 每日定时录入继续写入 stock_daily（问题修复后无需重新回填）
  3. 修复完成后重新走 6.3.1 的切换触发条件
```

### 6.4 回滚方案

```text
1. 新表创建 = 只增不改，DROP TABLE 即可回滚
2. stock_daily 写入 = 写入失败不影响 Parquet 读取
3. 迁移过程中：MarketDataClient.get_daily() 优先读 parquet，
   仅当 stock_daily 表存在且 query_mode='authoritative' 时切换
```

### 6.5 数据库文件位置

| 表 | 目标数据库 | 路径 |
|:---|:-----------|:-----|
| staging_raw | trade_engine.db | `C:\Users\17699\mo_zhi_sharereports\trade_engine.db` |
| validation_audit_log | trade_engine.db | 同上 |
| stock_daily | knowledge.db | `C:\Users\17699\mozhi_platform\data\knowledge.db` |

> ⚠️ 将交易类验证记录存放在 trade_engine.db，将权威市场数据存放在 knowledge.db，符合现有系统"职责分离"的数据库设计。

---

## 七、附录：字段映射说明

### 7.1 staging_raw ↔ validation_audit_log 关系

```text
staging_raw（N:1）←──→ validation_audit_log（1:N）

一条审计记录可能对应多条 staging_raw 记录
（例如：一次交叉验证中 A、B、C 三个源各一行原始数据）
```

### 7.2 stock_daily 与 Parquet schema 兼容性

| Parquet 列 | stock_daily 列 | 类型兼容 | 说明 |
|:-----------|:---------------|:---------|:-----|
| date | trade_date | TEXT↔TEXT | 格式均为 YYYY-MM-DD |
| open | open | float64↔REAL | ✅ |
| high | high | float64↔REAL | ✅ |
| low | low | float64↔REAL | ✅ |
| close | close | float64↔REAL | ✅ |
| volume | volume | int64↔REAL | ⚠️ Parquet 为 int，SQLite 存 REAL 兼容 |
| amount | amount | float64↔REAL | ✅ |
| pct_chg | pct_chg | float64↔REAL | ✅ |
| — | validation_status | 新增 | 现有 Parquet 无此字段 |
| — | primary_source | 新增 | 现有 Parquet 无此字段 |
