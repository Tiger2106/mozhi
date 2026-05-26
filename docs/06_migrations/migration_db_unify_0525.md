# 统一数据库迁移方案 — analysis.db → market_data.db

> 作者: 墨衡 (moheng)  
> 创建时间: 2026-05-25T15:09+08:00  
> 版本: v1.0  
> 迁移代号: `DB_UNIFY_0525`  
> 状态: ✅ EXECUTED  
> 执行时间: 2026-05-25T16:00~16:20+08:00

---

## 0. 前置概要

### 数据库现状

当前系统存在 **3个 analysis.db 实例** 和 **1个 market_data.db**：

| 标签 | 路径 | 表数 | 行数 | 角色 |
|:----:|:----|:----:|:----:|:----|
| **A0** | `data/analysis.db` | 11 | ~50K | 管线工作库（TSI目标） |
| **A1** | `data/db/analysis.db` | 5 | ~48K | Phase1数据源 |
| **A2** | `~/mo_zhi_sharereports/analysis.db` | 11 | ~50K | 管线工作库(旧共享目录) |
| **M** | `data/market/market_data.db` | 5 | ~42K | **目标库（唯一行情源）** |

**结论：A0 与 A2 为同一数据的两份副本；A1 为独立的 Phase1 数据源。**

### 核心原则

1. **stock_daily 行情数据 → 100% 从 market_data.db 提供**（后者字段更全：19列 vs 10列）
2. **analysis.db 保留** 为非行情数据专用库（技术指标、原油、分钟线、回测结果等）
3. **迁移完成后 analysis.db 改名为 pipeline_cache.db** 消除语义歧义

---

## 1. 审计结果

### 1.1 活动引用点（排除 tests / scripts / docs / _trash）

| 引用点 | 文件 | 行 | 使用的表 | 迁移方式 |
|--------|:----:|:--:|:---------|:---------|
| config路径定义 | `src/config.py` | 56 | — | 改默认路径 |
| 新库路径函数 | `pipeline_paths.py` | 197-211 | — | **已实现** `market_data_db()` + `analysis_db_legacy()` |
| 行情数据DAO | `src/backtest/data_source.py` | 12,243,248,264 | `backtest_results` | 已部分迁移(`get_stock_prices`用market_data.db)；`get_backtest_results`保留 |
| 交易日历对齐 | `src/backtest/date_aligner.py` | 10,36 | `trading_calendar`, `stock_daily` | 替换→market_data.db |
| 数据填充 | `src/backtest/data_filler.py` | 12,39 | `stock_daily`, `trading_calendar` | 替换→market_data.db |
| 历史数据填充 | `src/backtest/data_historical_fill.py` | 7 | `stock_daily` | 替换→market_data.db |
| 漂移检测 | `src/reporting/evening/drift_detector.py` | 10,39,116,120 | `stock_daily` | 替换→market_data.db |
| 趋势日报 | `src/reporting/evening/trend_daily_report.py` | 15,41 | `tech_indicators` | **保留analysis.db** |
| 技术信号生成 | `src/trading/signals/tech_signal_generator.py` | 47,97 | `tech_indicators` | **保留analysis.db** |
| 骨架创建 | `src/morning_pipeline/scheduler_agent.py` | 626-813 | `stock_daily`, `oil_daily`, `tech_indicators`, `trading_calendar`等 | 拆分：行情骨架→market_data.db；非行情→analysis.db |
| 回测报告适配 | `src/backtest/pipeline/report_adapter.py` | 5 | `backtest_results`, `backtest_equity_series` | **保留analysis.db** |
| 数据库审计 | `data/audit_db.py` | 19 | — | 更新检查列表 |

### 1.2 backtest_engine 独立组件引用

| 引用点 | 文件 | 行 | 使用的表 | 迁移方式 |
|:-------|:----:|:--:|:---------|:---------|
| 数据质量检查 | `backtest_engine/calc/vwap_channel.py` | 222 | `stock_daily` | 替换→market_data.db |
| 分钟数据采集 | `backtest_engine/collector/minute_collector.py` | 8,28 | `stock_minute` | **保留analysis.db** |
| 管线编排 | `backtest_engine/pipeline/pipeline_orchestrator.py` | 39 | `stock_daily`, `tech_indicators` | 拆分 |
| 信号管线 | `backtest_engine/pipeline/signal_pipeline.py` | 49 | `stock_daily`, `tech_indicators` | 拆分 |
| 集成测试 | `backtest_engine/test_integration.py` | 203-266 | 多表 | 更新测试路径 |

### 1.3 非活动引用（scripts / docs / _trash / tests）

这些文件仅用于开发/验证，标记为"迁移后更新"并在迁移Step中一并处理。

---

## 2. 两库结构对照

### 2.1 stock_daily 表对照

| 字段 | analysis.db(data/) | market_data.db | 兼容性 |
|:----:|:------------------:|:--------------:|:------:|
| code | TEXT NOT NULL | TEXT | ✅ |
| date | TEXT NOT NULL | TEXT | ✅ |
| open | REAL | REAL | ✅ |
| high | REAL | REAL | ✅ |
| low | REAL | REAL | ✅ |
| close | REAL | REAL | ✅ |
| volume | INTEGER | INTEGER | ✅ |
| amount | REAL | REAL | ✅ |
| adj_factor | REAL DEFAULT 1.0 | REAL | ✅ |
| created_at | TEXT DEFAULT(...) | TEXT | ✅（忽略） |
| pre_close | — | REAL | market_data.db 额外有 |
| turnover_rate | — | REAL | market_data.db 额外有 |
| volume_ratio | — | REAL | market_data.db 额外有 |
| pe | — | REAL | market_data.db 额外有 |
| pb | — | REAL | market_data.db 额外有 |
| total_share | — | REAL | market_data.db 额外有 |
| float_share | — | REAL | market_data.db 额外有 |
| circ_mv | — | REAL | market_data.db 额外有 |
| total_mv | — | REAL | market_data.db 额外有 |

**结论：字段完全兼容（market_data.db 是分析库的严格超集）。** 所有查询 `SELECT col1, col2 FROM stock_daily ...` 可直接迁移。

### 2.2 trading_calendar 表对照

| 字段 | analysis.db(data/) | market_data.db | 兼容性 |
|:----:|:------------------:|:--------------:|:------:|
| date | TEXT NOT NULL | TEXT | ✅ |
| market | TEXT NOT NULL | TEXT | ✅ |
| is_trading_day | INTEGER NOT NULL DEFAULT 0 | INTEGER | ✅ |
| market_type | TEXT DEFAULT '' | — | analysis.db 特有，Query 未使用 |
| note | TEXT DEFAULT '' | — | analysis.db 特有，Query 未使用 |
| pretrade_date | — | TEXT | market_data.db 特有 |
| created_at | TEXT DEFAULT(...) | TEXT | ✅（忽略） |

**结论：字段基本兼容。** 现有查询 `SELECT date, market, is_trading_day FROM trading_calendar` 在两者均可工作。`pretrade_date` 为 market_data.db 额外字段。

### 2.3 需保留在 analysis.db 的表

| 表 | 列数 | 行数 | 原因 | 引用模块 |
|:---|:----:|:----:|:-----|:--------|
| tech_indicators | 23 | 1783 | 计算技术指标（MA/RSI/MACD/KDJ/BB/趋势分） | trend_daily_report, tech_signal_generator |
| oil_daily | 8 | 20548 | 原油行情数据 | pipeline_paths, scheduler_agent |
| stock_daily_raw | 10 | 4620 | 原始未处理行情 | 潜在 |
| stock_minute | 12 | 144 | 分钟级行情 | minute_collector |
| backtest_results | 15 | 0 | 回测结果记录 | data_source, report_adapter |
| backtest_equity_series | 6 | 0 | 回测权益曲线 | data_source, report_adapter |
| cache_metadata | 4 | 0 | 缓存状态 | scheduler_agent |
| stock_daily_unadjusted | 9 | 0 | 不复权日线 | scheduler_agent(骨架) |

---

## 3. 迁移策略

### 3.1 分层迁移

```
┌─────────────────────────────────────────────────────────┐
│                     市场行情层                    可全量  │
│  stock_daily (10→19列) ──→ market_data.db.stock_daily  │ 迁移
│  trading_calendar (6→5列) ──→ market_data.db.tc        │
│  adj_factor ──→ market_data.db.adj_factor              │
├─────────────────────────────────────────────────────────┤
│                     计算缓存层                    不可   │
│  tech_indicators / oil_daily / stock_minute           │ 迁移
│  stock_daily_raw / stock_daily_unadjusted              │
│  backtest_results / backtest_equity_series              │
│  cache_metadata                                         │
│  → 保留在 analysis.db (更名为 pipeline_cache.db)       │
├─────────────────────────────────────────────────────────┤
│                   Phase1 数据源层                   可   │
│  data/db/analysis.db (stock_daily 19列)                │ 整体
│  → 与 market_data.db 数据重叠，可整体废弃              │ 废弃  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 迁移分类

| 分类 | 说明 | 文件数 |
|:----:|:-----|:------:|
| **A-直接替换** | 替换 DB_PATH 指向 market_data.db，查询不变 | 6 |
| **B-适配迁移** | 替换路径 + 调整查询或结果处理 | 2 |
| **C-保留analysis.db** | 非行情表，不迁移 | 5 |
| **D-配置层** | 修改 config/pipeline_paths 默认路径 | 2 |
| **E-测试/工具** | 更新测试用例和脚本 | ~10 |

### 3.3 关键适配点

1. **trading_calendar.date 格式**  
   - market_data.db.trading_calendar.date 使用 `YYYY-MM-DD`  
   - analysis.db.trading_calendar.date 也使用 `YYYY-MM-DD`  
   - 结论：格式一致，无需转换

2. **stock_daily.date 格式**  
   - market_data.db.stock_daily.date: `TEXT`, 格式 `YYYYMMDD`（需确认）  
   - analysis.db.stock_daily.date: `TEXT`, 原始数据 `YYYYMMDD`  
   - 结论：格式一致，无需转换

3. **trading_calendar 行数差异**  
   - analysis.db: 6576 行  
   - market_data.db: 2334 行  
   - ⚠️ 需确认 market_data.db 是否覆盖了全部需要的交易日范围

---

## 4. 改动的文件清单

### 4.1 核心源文件（12 个）

| 文件 | 修改类型 | 修改内容 |
|:-----|:--------:|:---------|
| `src/config.py` | 改 | `ANALYSIS_DB` 保持不变（保留非行情数据）|
| `pipeline_paths.py` | 改 | 完善 `analysis_db_legacy()` 重命名为 `pipeline_cache_db()` |
| `src/backtest/date_aligner.py` | 改 | `DB_PATH` 改为 market_data.db；`stock_daily` 查询保持兼容 |
| `src/backtest/data_filler.py` | 改 | `DB_PATH` 改为 market_data.db |
| `src/backtest/data_historical_fill.py` | 改 | 数据源改为 market_data.db |
| `src/backtest/data_source.py` | 改 | 已部分迁移，确认 `get_backtest_results` 保留分析库引用 |
| `src/reporting/evening/drift_detector.py` | 改 | `DEFAULT_DB` 改为 market_data.db；`stock_daily` 查询兼容 |
| `src/reporting/evening/trend_daily_report.py` | 改 | `ANALYSIS_DB_PATH` 改为 `PIPELINE_CACHE_DB`（仅用于 `tech_indicators`）|
| `src/trading/signals/tech_signal_generator.py` | 改 | `ANALYSIS_DB` 改为 `PIPELINE_CACHE_DB` |
| `src/morning_pipeline/scheduler_agent.py` | 改 | `_precheck()` 拆分：行情存在检查→market_data.db；分析骨架创建→pipeline_cache.db |
| `backtest_engine/calc/vwap_channel.py` | 改 | `stock_daily` 查询改为 market_data.db |
| `backtest_engine/pipeline/pipeline_orchestrator.py` | 改 | `stock_daily`→market_data.db；`tech_indicators`→pipeline_cache.db |
| `backtest_engine/pipeline/signal_pipeline.py` | 改 | 同上拆分 |

### 4.2 工具/审计文件（4 个）

| 文件 | 修改类型 | 修改内容 |
|:-----|:--------:|:---------|
| `data/audit_db.py` | 改 | 更新 dbs_to_check：移除 `analysis.db`，添加 `pipeline_cache.db` |
| `data/mark_deprecated.py` | 改 | 更新备注 |
| `backtest_engine/collector/minute_collector.py` | 改 | `DEFAULT_DB` 改为 `PIPELINE_CACHE_DB`（只写 `stock_minute` 表） |
| `backtest_engine/test_integration.py` | 改 | 更新 skip 条件中的路径引用 |

### 4.3 测试/脚本文件（迁移后更新）

`tests/` 下文件（3 个）、`scripts/` 下文件（5 个）、`docs/` 下文件（2 个）—— 不影响运行时，迁移后统一更新。

### 4.4 新增文件

| 文件 | 类型 | 说明 |
|:-----|:----:|:-----|
| `docs/06_migrations/migration_log_db_unify_0525.md` | 新增 | 迁移操作日志 |
| `scripts/migrate_analysis_to_market_data.py` | 新增 | 自动化迁移脚本 |

---

## 5. 迁移步骤与回退方案

### Step 1：环境准备

```bash
# 1. 备份当前数据库（备份策略：copy不rename）
copy data\analysis.db data\analysis.db.bak.20260525
copy data\db\analysis.db data\db\analysis.db.bak.20260525
copy data\market\market_data.db data\market\market_data.db.bak.20260525

# 2. 验证 market_data.db 数据覆盖范围
python scripts\verify_market_data_coverage.py
# 确认：stock_daily 行数 ≥ analysis.db 行数
# 确认：trading_calendar 覆盖相同日期范围

# 3. 创建迁移日志文件
```

**验证检查清单：**
- [ ] market_data.db.stock_daily 行数（18534）≥ analysis.db.stock_daily 行数（4635）
- [ ] market_data.db.trading_calendar 覆盖 2020-01-01 ~ 2026-05-31
- [ ] 两种 stock_daily 的 adj_factor 行为一致
- [ ] 确认 market_data.db 数据更新机制（每日更新/手工更新）

### Step 2：路径配置层修改

1. `src/config.py` — 新增 `PIPELINE_CACHE_DB` 别名，`ANALYSIS_DB` 保持旧名但指向它
2. `pipeline_paths.py` — 新增 `pipeline_cache_db()` 函数，废弃 `analysis_db_legacy()` 命名
3. 所有硬编码 `DB_PATH` 替换为从 config 获取

### Step 3：存量引用替换（6 个 A 类文件）

每个文件的修改模式：

```python
# 修改前
DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\analysis.db"

# 修改后 - 行情数据
from src.config import MARKET_DATA_DB
from src.config import PIPELINE_CACHE_DB

# 根据实际使用的表选择对应的数据库
# stock_daily → MARKET_DATA_DB
# trading_calendar → MARKET_DATA_DB
# tech_indicators → PIPELINE_CACHE_DB
```

### Step 4：复杂引用拆分（4 个 B 类文件）

**scheduler_agent.py** — 最复杂的修改：
- `_precheck()` 检查 `market_data.db` 存在性（用于 stock_daily）
- `_create_analysis_db_skeleton()` 拆分为两个方法：
  - `_ensure_market_data_db()` — 检查 market_data.db 存在
  - `_ensure_pipeline_cache_db()` — 创建 pipeline_cache.db 骨架（含 oil_daily, tech_indicators 等）

**data_source.py** — 已部分完成：
- `get_stock_prices()` 已使用 `_get_market_data_db()` ✅
- `get_backtest_results()` 保留使用 pipeline_cache.db

**backtest_engine 模块** — 改用 `PIPELINE_CACHE_DB` 命名，且：
- `stock_daily` 查询改为 market_data.db
- `tech_indicators` 查询保留 pipeline_cache.db

### Step 5：测试与验证

```bash
# 1. 运行所有单元测试
python -m pytest tests/ -v --tb=short 2>&1 | tee migration_test_log.txt

# 2. 运行集成测试
python -m pytest backtest_engine/test_integration.py -v

# 3. 验证关键查询结果一致性
python scripts/verify_migration_consistency.py
# 对比：analysis.db vs market_data.db 各标的 stock_daily 行数/日期范围
# 对比：analysis.db vs market_data.db trading_calendar 交易日列表

# 4. 执行一次完整回测
python src/backtest/run_backtest.py --symbol 601857 --consistency-check
```

### Step 6：清理（确认稳定后执行）

```bash
# 1. 重命名 analysis.db → pipeline_cache.db
move data\analysis.db data\pipeline_cache.db

# 2. 废弃 data/db/analysis.db（含 daily_factors 的特殊处理）
# 确认 market_data.db 已覆盖其 stock_daily 和 adj_factor
# daily_factors 表如果仍然被引用，需单独处理或迁移到 pipeline_cache.db
move data\db\analysis.db data\db\analysis.db.deprecated.20260525

# 3. 更新所有文档中的路径引用
```

### 回退方案

```bash
# 回退命令（全程幂等）
copy data\analysis.db.bak.20260525 data\analysis.db
copy data\db\analysis.db.bak.20260525 data\db\analysis.db
git checkout -- src/config.py pipeline_paths.py
git checkout -- src/backtest/ src/reporting/ src/trading/
git checkout -- backtest_engine/

# 重新运行 pipeline 验证
```

**回退触发条件：**
- 任一验证步骤（Step 5）失败且无法在 30 分钟内修复
- market_data.db 数据明显少于 analysis.db
- 交易日历覆盖范围不足（缺少 2025/2026 年交易日）

---

## 6. 保留表清单（pipeline_cache.db）

以下 8 张表将保留并仅存在于重命名后的 `pipeline_cache.db`：

| 表 | 写入者 | 读者 | 迁移需求 |
|:---|:------:|:----:|:---------|
| tech_indicators | `tech_signal_generator.py` | `trend_daily_report.py`, `tech_signal_generator.py` | 命名更新无结构改 |
| oil_daily | scheduler骨架 + 外部脚本 | pipeline_paths | 无 |
| stock_daily_raw | 外部脚本 | 潜在 | 无 |
| stock_minute | `minute_collector.py` | backtest_engine | 命名更新 |
| backtest_results | `backtest_engine` | `data_source.py`, `report_adapter.py` | 命名更新 |
| backtest_equity_series | `backtest_engine` | `data_source.py`, `report_adapter.py` | 命名更新 |
| cache_metadata | scheduler骨架 | scheduler_agent | 命名更新 |
| stock_daily_unadjusted | scheduler骨架 | 潜在 | 无 |

---

## 7. 影响范围

### 7.1 影响模块

| 模块 | 影响程度 | 说明 |
|:-----|:--------:|:-----|
| 早报管线 `morning_pipeline` | **中** | 骨架创建逻辑拆分 |
| 回测引擎 `backtest_engine` | **中** | 分库查询适配 |
| 晚间报告 `reporting/evening/` | **低** | 路径更新+查询适配 |
| 技术信号 `trading/signals/` | **低** | 仅命名更新 |
| 交易日历对齐 `backtest/date_aligner.py` | **低** | DB_PATH 替换 |
| 数据填充 `backtest/data_filler.py` | **低** | DB_PATH 替换 |
| 行情数据漂移检测 `drift_detector.py` | **低** | DB_PATH 替换 |
| 数据库审计 `data/audit_db.py` | **低** | 检查列表更新 |

### 7.2 是否需要重新回测

**否。** 回测结果（`backtest_results` / `backtest_equity_series`）保留在 pipeline_cache.db 中，数据不受影响。

- 股票行情数据（`stock_daily`）从 market_data.db 获取 → 如果 market_data.db 数据与旧库一致，回测结果不变
- 技术指标（`tech_indicators`）保留不变

### 7.3 存量数据一致性确认

迁移前必须验证：

```sql
-- 1. stock_daily 行数对比
SELECT COUNT(*) FROM data_analysis_db.stock_daily;   -- 4635
SELECT COUNT(*) FROM market_data_db.stock_daily;      -- 18534

-- 2. 重叠标的行数对比（按 code）
SELECT code, COUNT(*) FROM data_analysis_db.stock_daily GROUP BY code;
SELECT code, COUNT(*) FROM market_data_db.stock_daily GROUP BY code;

-- 3. 关键标的最新数据日期
SELECT code, MAX(date) FROM data_analysis_db.stock_daily GROUP BY code;
SELECT code, MAX(date) FROM market_data_db.stock_daily GROUP BY code;
```

> ⚠️ **关键风险**：market_data.db 的行数（18534）远多于 analysis.db（4635），说明包含更多标的或更久的数据。需要确认：
> 1. 数据来源一致（akshare 相同接口？不同时段采集？）
> 2. 重叠标的的 close/adj_factor 在重叠日期上一致
> 3. 如有偏差，需建立数据源优先级规则

---

## 8. 文件名对照（迁移后）

| 迁移前 | 迁移后 | 说明 |
|:-------|:-------|:-----|
| `analysis.db` | `pipeline_cache.db` | 非行情数据缓存 |
| `market_data.db` | `market_data.db` | 不变（行情数据源） |
| `data/db/analysis.db` | — | **废弃**（Phase1目标） |
| `src/config.ANALYSIS_DB` | `src/config.PIPELINE_CACHE_DB` | 配置层更名 |
| `pipeline_paths.analysis_db_legacy()` | `pipeline_paths.pipeline_cache_db()` | 函数更名 |

---

## 9. 附录：非活动引用文件清单

以下文件引用 `analysis.db` 但不影响运行时，建议在 Step 6 统一更新：

| 文件 | 建议操作 |
|:-----|:---------|
| `scripts/phase1_data_collection.py` | 更新注释和路径 |
| `scripts/phase1_data_validate.py` | 更新路径 |
| `scripts/phase1_factor_backfill.py` | 更新路径 |
| `scripts/phase1_icir_test.py` | 更新路径 |
| `scripts/_check_db_schema.py` | 更新路径 |
| `scripts/_check_dbs_tmp.py` | 更新路径 |
| `scripts/migrate_backtest_code_field.py` | 更新路径 |
| `docs/10_strategies/S001/check_db.py` | 更新路径 |
| `docs/10_strategies/S001/verify_db.py` | 更新路径 |
| `tests/test_morning_pipeline_integration.py` | 更新路径 |
| `tests/test_validate_backtest_p1.py` | 更新路径 |
| `test_imports.py` | 更新路径 |
| `validate_backtest_p1.py` | 更新路径 |
| `verify_stock_daily.py` | 更新路径 |
