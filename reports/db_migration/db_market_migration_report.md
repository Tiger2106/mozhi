# DB-MARKET 迁移报告

**任务 ID**: db_market
**执行 Agent**: moheng
**执行时间**: 2026-05-18T13:21:00+08:00
**状态**: SUCCESS

---

## 迁移摘要

将代码中对 `analysis.db` 的 `stock_daily`（市场行情）查询引用切换到 `market_data.db`，保留 `analysis.db` 中的 `oil_daily`、`tech_indicators`、`trading_calendar` 等非行情数据表。

### 前置准备

1. **pipeline_paths.py 新增函数**：
   - `market_data_db()` → 返回 `C:\Users\17699\mozhi_platform\data\market\market_data.db`
   - `analysis_db_legacy()` → 返回 `C:\Users\17699\mo_zhi_sharereports\analysis.db`（兼容层）

2. **创建 market_data.db**（位置：`mozhi_platform\data\market\market_data.db`）
   - stock_daily 表 schema（code + date + OHLCV + adj_factor + created_at）
   - config 元数据表
   - 从旧 `analysis.db` 复制 4620 条 stock_daily 记录

3. **验证**：market_data.db 可读，stock_daily 表 4620 行

---

## 已修改的文件

| 文件 | 修改内容 | 原因 |
|------|---------|------|
| `pipeline_paths.py` | 新增 `market_data_db()`、`analysis_db_legacy()` | 统一数据库路径入口 |
| `src/config.py` | 新增 `MARKET_DATA_DB` 常量 | 新路径的中央配置引用 |
| `src/backtest/data_source.py` | 新增 `_get_market_data_db()`；`get_stock_prices()` 改为使用 `MARKET_DATA_DB` | stock_daily 查询，纯行情数据 |
| `src/backtest/data_loader.py` | `_get_default_db()` 改为指向 `market_data.db`；新增 `Path` 导入 | stock_daily 写入目标 |
| `src/backtest/strategies/run_grid.py` | `_DEFAULT_DB` 改为 `market_data.db` | 仅读取 stock_daily 做回测 |
| `src/backtest/strategies/run_reversal.py` | `_DEFAULT_DB` 改为 `market_data.db` | 同上 |
| `src/backtest/strategies/run_trend.py` | `_DEFAULT_DB` 改为 `market_data.db` | 同上 |
| `src/backtest/strategies/_pipeline_main.py` | 导入 `MARKET_DATA_DB` 替代 `ANALYSIS_DB`；`db = str(MARKET_DATA_DB)` | 仅读取 stock_daily |
| `src/backtest/strategies/_pipeline_main_v2.py` | `get_price_stats()` 路径改为 `market_data.db` | 仅读取 stock_daily |
| `src/backtest/strategies/_price_range.py` | `DB` 路径改为 `market_data.db` | 仅读取 stock_daily |
| `src/backtest/data_historical_fill.py` | 两处硬编码路径改为 `market_data.db` | stock_daily 写入 + 验证 |

---

## 未修改的文件（混用表）

以下文件在同一数据库连接中同时使用 `stock_daily` 和非行情表（`trading_calendar`、`oil_daily`、`tech_indicators`），不能简单切换路径。**需要手动重构为双连接模式**。

| 文件 | 混用表 | 说明 |
|------|--------|------|
| `src/backtest/data_filler.py` | stock_daily + trading_calendar | `DataFillManager` 用单一 `db_path` 访问两个表 |
| `src/backtest/date_aligner.py` | stock_daily + trading_calendar | 同一连接读取交易日历和行情 |
| `src/morning_pipeline/scheduler_agent.py` | stock_daily + oil_daily + tech_indicators + trading_calendar | 骨架创建脚本，创建所有表 |
| `src/reporting/evening/drift_detector.py` | stock_daily + (通过 data_source 层) | 使用 `get_stock_prices()`（已切换），代码中仍有硬编码注释 |
| `src/reporting/evening/trend_daily_report.py` | tech_indicators + stock_daily | 同一连接读取技术指标和收盘价 |
| `src/trading/signals/tech_signal_generator.py` | stock_daily + tech_indicators | `DataFetcher` 类读写两个表，逻辑高度耦合 |
| `src/backtest/pipeline/report_adapter.py` | 使用 `get_stock_prices()`（已切换） | 间接引用，已通过 data_source 层迁移 |

---

## 未修改的测试文件

| 文件 | 内容 | 原因 |
|------|------|------|
| `src/backtest/tests/test_date_aligner.py` | 引用 `analysis.db` | 测试文件，需与 test fixture 同步更新 |

---

## 验证

- ✅ 所有 11 个已修改文件通过 `py_compile` 语法检查
- ✅ `pipeline_paths.market_data_db()` 返回正确路径
- ✅ `market_data.db` 包含 4620 条 stock_daily 记录
- ✅ `analysis.db` 文件保留（含 oil_daily 20548 行、tech_indicators 322 行、trading_calendar 6576 行）

---

## 待办项

所有混用表文件建议后续手动重构：
1. 为 `data_filler.py` 的 `DataFillManager` 添加 `market_db_path` 参数
2. 为 `date_aligner.py` 添加单独的 market DB 连接
3. 将 `scheduler_agent.py` 中的 stock_daily 表创建拆到 market_data.db
4. 将 `tech_signal_generator.py` 中的 stock_daily 读写拆到 market_data.db
5. 删除 `config.py` 中的 `ANALYSIS_DB` 常量（在所有迁移完成后）
