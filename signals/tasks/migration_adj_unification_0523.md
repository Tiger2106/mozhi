# 路径语义统一与基础设施整合迁移日志

**作者**: 墨衡 (moheng)
**创建时间**: 2026-05-23 18:02 +08:00
**任务ID**: step1_infrastructure_0523
**版本**: v1.0

---

## 变更摘要

统一 MOZHIHOME 语义、整合 config.py 路径配置、修复 backtest_engine 路径歧义。

---

## 变更清单

### 1. `src/config.py` — 新增 `get_mozhihome()` + 修改 SHARED_REPORTS 默认路径

- **新增**: `get_mozhihome()` 函数
  - 优先级：环境变量 MOZHIHOME > 模块自动推断 > 工作目录推断 > `~/mozhi_platform`
- **修改**: `PROJECT_ROOT` 改为调用 `get_mozhihome()`
- **修改**: `SHARED_REPORTS` 默认路径从 `~/mo_zhi_sharereports` 改为 `PROJECT_ROOT/reports`（即 `~/mozhi_platform/reports`）

### 2. `pipeline_paths.py` — 硬编码路径改为从 config.py 导入

- **修改**: `MOZHI_BASE` 硬编码 `r"C:\Users\17699\mozhi_platform"` → `PROJECT_ROOT`（从 `src.config` 导入）
- **修改**: `SHARED_BASE_LEGACY` 硬编码 `r"C:\Users\17699\mo_zhi_sharereports"` → `Path.home() / "mo_zhi_sharereports"`
- **新增**: 导入时自动添加 `sys.path` 确保 `src/` 可引入

### 3. backtest_engine — MOZHIHOME 语义纠偏（7 个文件）

文件 | 修改前 | 修改后
:---|:------|:------
`calc/float_share_cache.py` | `MOZHIHOME` fallback → `mo_zhi_sharereports` | → `mozhi_platform`
`calc/volume_ratio.py` | `MOZHIHOME` fallback → `mo_zhi_sharereports` + `analysis.db` | → `mozhi_platform` + `data/analysis.db`
`calc/vwap_channel.py` | `MOZHIHOME` fallback → `mo_zhi_sharereports` (×2) | → `mozhi_platform` + `data/analysis.db`
`collector/minute_collector.py` | `MOZHIHOME` fallback → `mo_zhi_sharereports` | → `mozhi_platform` + `data/analysis.db`
`pipeline/data_pipeline.py` | `MOZHIHOME` fallback → `mo_zhi_sharereports` | → `mozhi_platform` + `data/analysis.db`
`pipeline/pipeline_orchestrator.py` | `MOZHIHOME` fallback → `mo_zhi_sharereports` | → `mozhi_platform` + `data/analysis.db`
`pipeline/signal_pipeline.py` | `MOZHIHOME` fallback → `mo_zhi_sharereports` | → `mozhi_platform` + `data/analysis.db`

### 4. 新产出脚本硬编码路径修复（2 个文件）

文件 | 修改前 | 修改后
:---|:------|:------
`src/generate_pdf_from_knowledgedb.py` | `OUTPUT_PDF = r"...mo_zhi_sharereports\reports\backtest\..."` | 使用 `from config import PROJECT_ROOT` 动态解析
`src/generate_backtest_pdf.py` | `output_dir = r"...mo_zhi_sharereports\reports\backtest"` | 使用 `from config import PROJECT_ROOT` 动态解析

### 5. 未修改的旧数据读取类脚本（保持兼容）

- `scripts/backfill_knowledge_db.py` — 读旧路径历史数据
- `scripts/backtest_storage_watch.py` — 监控旧 backtest_results
- `scripts/daily_maintenance.py` — 基建脚本，读取旧 signals/tasks
- `scripts/migrate_backtest_code_field.py` — 迁移脚本
- `scripts/_check_db_schema.py` — 检查脚本

---

## 验证记录

| 组件 | 状态 | 备注 |
|:----|:----|:----|
| `src.config` 导入测试 | ✅ PASS | `get_mozhihome()` 返回 `~/mozhi_platform`，`SHARED_REPORTS` 返回 `~/mozhi_platform/reports` |
| `pipeline_paths.py` 导入测试 | ✅ PASS | `MOZHI_BASE=~/mozhi_platform`, `SHARED_BASE_LEGACY=~/mo_zhi_sharereports` |
| backtest_engine 7 文件语法检查 | ✅ PASS | 全部通过 `ast.parse()` |
| 新产出脚本 2 文件语法检查 | ✅ PASS | 全部通过 `ast.parse()` |

---

## 备注

- **MOZHIHOME 语义定义**: 墨枢平台根目录（即 `mozhi_platform/`），不是 `mo_zhi_sharereports/`
- **数据迁移**: 本步骤不涉及 analysis.db 等数据迁移，仅修正代码路径语义
- **环境变量**: 生产环境可设置 `MOZHIHOME=mozhi_platform`；未设置时自动推断
- **旧路径兼容**: `analysis.db` 找新位置 `mozhi_platform/data/analysis.db`（已存在），旧 `mo_zhi_sharereports/analysis.db` 不受影响

---

## Step 2 — Reingest（2026-05-23 18:09 +08:00）

**任务ID**: `step2_reingest_0523`
**作者**: 墨衡 (moheng)

### 变更摘要

将 phase1_data_collection.py 的灌入目标从 `analysis.db` 切换为 `market_data.db`，日期范围扩展为 2020-2026 完整区间。

### 变更清单

| 修改项 | 修改前 | 修改后 |
|:------|:------|:------|
| 灌入数据库 | `data/db/analysis.db` | `data/market/market_data.db` |
| DATE_START | `20210101` | `20200101` |
| DATE_END | `20251231` | `20260522` |
| init_database() DROP | 无（CREATE IF NOT EXISTS） | 先 DROP 3张表再 CREATE（处理schema差异） |

### 文件修改

- `scripts/phase1_data_collection.py`: 4处修改（ANALYSIS_DB路径、DATE_START、DATE_END、init_database DROP逻辑）

### 验证记录

| 验证项 | 结果 | 备注 |
|:------|:----|:----|
| 总行数 | 18,534 ✅ | 12只标的 |
| 日期范围 | 20200102 ~ 20260522 ✅ | 完整覆盖2020-2026 |
| adj_factor IS NULL | 0 ✅ | 全部填充 |
| adj_factor = 0 | 0 ✅ | 无异常零值 |
| 各标的一致 | 1,545行/标 ✅ | 600030为1,539行（正常波动） |
| adj_factor表行数 | 18,540 ✅ | 与stock_daily一致 |
| trading_calendar | 2,334行 ✅ | 交易日1,545 / 非交易日789 |
| DB文件大小 | 6,192 KB ✅ | 从1,180 KB增长，数据量合理 |

### 执行详情

- 备份: `market_data.db.bak.20260523`
- 运行耗时: ~1分钟（Tushare无限频阻塞）
- 完成时间: 2026-05-23 18:09:54 +08:00

---

## Step 3 — P0 TSI修复（2026-05-23 18:31 +08:00）

**任务ID**: `p0_tsi_fix_0523`
**作者**: 墨衡 (moheng)

### 变更摘要

将 run_tsi_backtest.py 数据源切换为前复权（adjust="qfq"），解决 TSI 指标计算中的复权因子不一致问题。

### 变更清单

| 修改项 | 修改前 | 修改后 |
|:------|:------|:------|
| `scripts/run_tsi_backtest.py` 数据源 | `data_source.fetch_daily()` （不复权） | `data_source.fetch_daily(adjust="qfq")` （前复权） |
| validation_check 污染标记 | 无 | `adj_factor_unification_0523`（data_quality, pass） |

### 回测对象

- 601857（中国石油）：Buy&Hold = +152.39%，58笔交易，-0.05% return
- 全部3标的回测完成，backtest.db 共60笔交易

### backtest.db performance_summary（最新）

| 指标 | 值 |
|:----|:----|
| total_return | -10.48% |
| annualized_return | -1.78% |
| total_trades | 60 |
| win_rate | 50% |
| final_equity | 179,037 |

### 验证记录

| 验证项 | 状态 | 备注 |
|:------|:----|:----|
| 601857 Buy&Hold | ✅ PASS | 152.39%，与前复权回测一致 |
| validation_check 污染标记 | ✅ PASS | adj_factor_unification_0523, data_quality, pass |

---
