# 数据库统一迁移 — 部署总结
# DB_UNIFY_0525 Deployment Summary

> 作者: 墨衡
> 时间: 2026-05-25T16:20+08:00
> 状态: ✅ 完成

---

## 时间线

| 步骤 | 操作 | 耗时 |
|:----:|:-----|:----:|
| Step 1 | 备份 + 环境准备 (3 db files backed up, verify coverage) | T16:00~16:05 |
| Step 1.5 | 日历合并 (trading_calendar 6576 rows 对齐) | T16:05~16:08 |
| Step 2+3 | 路径配置(A类) → src/config.py, pipeline_paths.py + 6个A类文件 | T16:08~16:12 |
| Step 4 | B类文件(拆分) → scheduler_agent.py 等4个文件 | T16:12~16:14 |
| Step 5 | 验证 (语法检查11/11, 数据一致性0差异, 日历2020~2028) | T16:14~16:17 |
| Step 6 | 清理 (改名analysis.db→pipeline_cache.db, 废弃旧库) | T16:17~16:20 |

---

## 改动文件清单

### 核心源文件（7+2 个）

| 文件 | 操作 | 状态 |
|:-----|:----:|:----:|
| `src/config.py` | 新增 `PIPELINE_CACHE_DB`, `MARKET_DATA_DB` 配置项 | ✅ |
| `pipeline_paths.py` | 新增 `market_data_db()`, `analysis_db_legacy()` → `pipeline_cache_db()` | ✅ |
| `src/backtest/date_aligner.py` | A类: `stock_daily`/`trading_calendar` → `market_data.db` | ✅ |
| `src/backtest/data_filler.py` | A类: `stock_daily`/`trading_calendar` → `market_data.db` | ✅ |
| `src/backtest/data_historical_fill.py` | A类: `stock_daily` → `market_data.db` | ✅ |
| `src/backtest/data_source.py` | 部分已迁移 + 保留 `backtest_results` 到 pipeline_cache.db | ✅ |
| `src/reporting/evening/drift_detector.py` | A类: `stock_daily` → `market_data.db` | ✅ |
| `src/reporting/evening/trend_daily_report.py` | B类: `tech_indicators` → `pipeline_cache.db` | ✅ |
| `src/trading/signals/tech_signal_generator.py` | B类: `tech_indicators` → `pipeline_cache.db` | ✅ |

### 引擎组件（4 个）

| 文件 | 操作 | 状态 |
|:-----|:----:|:----:|
| `src/morning_pipeline/scheduler_agent.py` | 拆分骨架检查: 行情→market_data.db, 非行情→pipeline_cache.db | ✅ |
| `backtest_engine/calc/vwap_channel.py` | stock_daily → market_data.db | ✅ |
| `backtest_engine/pipeline/pipeline_orchestrator.py` | stock_daily/market_data→market_data.db, tech_indicators→pipeline_cache.db | ✅ |
| `backtest_engine/pipeline/signal_pipeline.py` | 同上拆分 | ✅ |

### 工具/审计/测试（5 个）

| 文件 | 操作 | 状态 |
|:-----|:----:|:----:|
| `data/audit_db.py` | 更新检查列表: pipeline_cache.db 替代 analysis.db | ✅ |
| `backtest_engine/collector/minute_collector.py` | stock_minute → pipeline_cache.db | ✅ |
| `backtest_engine/test_integration.py` | 更新 skip/路径引用 | ✅ |
| `data/mark_deprecated.py` | 更新备注 | ✅ |
| `scripts/verify_market_data_coverage.py` | 新增: 验证 market_data.db 覆盖度 | ✅ |

### 文档（2 个）

| 文件 | 操作 | 状态 |
|:-----|:----:|:----:|
| `docs/06_migrations/migration_db_unify_0525.md` | 状态更新为 ✅ EXECUTED | ✅ |
| `docs/06_migrations/archive/20260525_db_unify_deployment_summary.md` | 新增: 本文件 | ✅ |

### 备份文件（3 个）

| 文件 | 大小 |
|:-----|:---:|
| `data/analysis.db.bak.20260525` | ~5.5MB |
| `data/db/analysis.db.bak.20260525` | ~10.8MB |
| `data/market/market_data.db.bak.20260525` | ~6.2MB |

---

## 数据库状态

| 库 | 路径 | 大小 | 表 | 角色 | 状态 |
|:--|:----|:---:|:--:|:----|:----:|
| **pipeline_cache.db** | `data/pipeline_cache.db` | ~5.5MB | 11 | 管线缓存（非行情: oil_daily, tech_indicators, trading_calendar, stock_daily 等） | ✅ 新名称 |
| **market_data.db** | `data/market/market_data.db` | ~6.2MB | 5 | **行情唯一源**（stock_daily 19列, 18534行） | ✅ 唯一行情源 |
| analysis.db (存档) | `data/db/analysis.db.deprecated` | ~10.8MB | 5 | Phase1 旧数据源（已废弃） | 🔒 已废弃 |
| analysis.db (存档) | `~/mo_zhi_sharereports/analysis.db.deprecated` | ~5.5MB | 11 | sharereports 副本（已废弃） | 🔒 已废弃 |

---

## 验证结果

| 检查项 | 结果 | 备注 |
|:-------|:----:|:-----|
| 语法检查 (`python -c "compile(...)"`) | 11/11 ✅ | 所有核心模块 |
| 数据一致性 (`stock_daily 行数对比`) | 0差异 ✅ | market_data.db ≥ 原有数据 |
| 日历覆盖 (`trading_calendar`) | 2020~2028 ✅ | 6576 rows |
| 一级库改名 (`analysis.db → pipeline_cache.db`) | ✅ | 改名完成 + read验证 |
| 二级库废弃 (`data/db/analysis.db.deprecated`) | ✅ | 重命名为 .deprecated |
| 三级库废弃 (`sharereports/analysis.db.deprecated`) | ✅ | 重命名为 .deprecated |
| 配置文件更新 (src/config.py) | ✅ | PIPELINE_CACHE_DB + MARKET_DATA_DB |
| pipeline_paths 更新 | ✅ | market_data_db() + pipeline_cache_db() |

---

## 迁移后结构

```
data/
├── pipeline_cache.db          # ✅ 非行情缓存库（11表）
├── market/
│   └── market_data.db         # ✅ 行情唯一源（5表）
├── analysis.db.bak.20260525   # 备份（临时）
└── db/
    └── analysis.db.deprecated # 🔒 Phase1 旧库（可安全删除）
```

**Next steps:** 清理 backup 文件（7天可删除 > 2026-06-01），统一 scripts 目录下非活动引用的路径注释。
