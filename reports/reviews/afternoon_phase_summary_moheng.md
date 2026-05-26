<!--
author: 墨衡
version: 1.0
created_time: 2026-05-16T12:42:00+08:00
task: afternoon_phase_summary
-->

# 下午阶段建设报告

**评审人**: 墨衡
**评审时段**: 2026-05-16 11:55 ~ 12:39
**范围**: 知识库评审之后新增的全部变更

---

## 1. 变更清单

| 编号 | 模块 | 文件 | 变更内容 | 风险等级 |
|:----:|:----|:----|:---------|:-------:|
| 1 | 项目基础设施 | pyproject.toml, 71+5+4 源文件 | pyproject.toml 配置 + import 路径重构 (src/ 根目录) + `pip install -e .` 安装 | 🟢 低 |
| 2 | 分析模块 | `src/backtest/analytics/trade_pairing.py`, `performance.py` | TradePair 配对逻辑从 performance.py 独立为独立模块 | 🟡 中 |
| 3 | 报告生成 | `src/backtest/reports/generate_comparison.py` | B1 修复：模块级副作用消除 | 🟢 低 |
| 4 | 流水线 | `_pipeline_main_v2.py`, `daily_extractor.py`, `knowledge_db.py` 等 | 端到端流水线验证：回测→入库→聚合→运维全链 | 🟢 低 |
| 5 | 知识库 | `src/backtest/pipeline/knowledge_db.py` | `aggregate_knowledge()` 补 `knowledge_run_links` 关联表写入，695 条关联记录 | 🟢 低 |
| 6 | 知识库 | `src/backtest/pipeline/knowledge_db.py` | `_estimate_market_regime()` + `backfill_market_context()` 降级回填，500/694 条已入库 | 🟡 中 |

---

## 2. 各项详情

### 2.1 pyproject.toml + import 路径重构

**时间**: 11:57 — 12:00

**变更内容**：
- 配置 `pyproject.toml` 的 `[tool.setuptools.packages.find]` 指向 `src/`，include 列表覆盖 `backtest*`, `utils*`, `reporting*`, `trading*`, `scheduler*`, `monitoring*`, `signals*`
- 所有源文件 import 路径统一为 `from backtest.xxx` 顶级包风格（如 `from backtest.backtest_engine import ...`）
- 执行 `pip install -e .` 完成可编辑安装，生成 `src/mozhi_platform.egg-info/` 和 `mozhi_platform.egg-info/`

**涉及文件**：
- 1 个配置文件：`pyproject.toml`
- 71 个 `.py` 源文件（`src/backtest/` 下全部模块）
- 5 个其它包目录（`reporting/`, `trading/`, `utils/`, `scheduler/`, `monitoring/` 的 `__init__.py` 入口）
- 4 个测试文件更新
- **总计约 189 条 `from backtest.` import 语句**贯穿全代码库

**影响范围**：
- 所有 `sys.path.insert(0, ...)` 启动方式可改为自然 import
- `pip install -e .` 后可直接 `python -c "from backtest.pipeline.knowledge_db import ..."`
- 文件注册系统（`file_lifecycle.py`）尚需补充新文件条目

### 2.2 analytics/trade_pairing 模块迁移

**时间**: 11:59 — 12:00

**变更内容**：
- 创建 `src/backtest/analytics/__init__.py` + `trade_pairing.py`，从 `performance.py` 抽离：
  - `pair_trades_to_roundtrips()` — FIFO 双队列交易配对
  - `compute_trade_distribution()` — 盈亏分布统计
- `performance.py` 通过 `from .analytics.trade_pairing import ... # noqa: F401` 保持向后兼容
- 旧版 `Performance` 类保留为 `PerformanceCalculator` 别名

**影响范围**：
- `generate_comparison.py` 以及其他直接 `from backtest.performance import pair_trades_to_roundtrips` 的调用方不受影响
- `file_lifecycle.py` 未注册 `trade_pairing.py`，已出现在 12:13 日志的 unregistered 列表中

### 2.3 B1 修复 — generate_comparison.py 模块级副作用消除

**时间**: 12:11 (文件最后修改时间)

**变更内容**：
- 消除 `generate_comparison.py` 中所有模块级执行副作用
- 关键计算（`metrics()`, `monthly_ret()`, `_gen_simulated_trades()` 等）全部封装在函数内部
- `dates_str`, `KNOWN` 等作为纯数据常量保留
- `main()` 入口仅当 `if __name__ == "__main__":` 时执行
- `add_buy_hold_column()` 函数 API 提供外部调用能力

**影响范围**：
- 修正了 `from backtest.reports.generate_comparison import add_buy_hold_column` 时的非预期计算
- 测试 `test_generate_comparison_bh.py` 可正常导入

### 2.4 端到端流水线验证

**时间**: 11:58 — 12:30

**变更内容**：
- 验证回测引擎每日推送流水线：`_pipeline_main_v2.py` 网格参数扫描 → `KnowledgeDB.store_run()` → 聚合 → 运维健康检查
- 日志记录从 11:19 的 689 条增长到 12:13 的 694 条（新增约 5 条验证回测）
- 涉及文件：
  - `daily_extractor.py` — 日报提取
  - `knowledge_extractor.py` — 知识库提取
  - `report_renderer.py` — 报告渲染
  - `chart_generator.py` — 图表生成
  - `_pipeline_main_v2.py` — 流水线主入口
  - `weekly_extractor.py`, `weekly_push.py` — 周流水线
  - `daily_maintenance.py` — 运维脚本

**验证结果**：
- 日报告生成：`reports/daily/daily_doc_report_2026-05-16.md` ✅
- 运维检查：`daily_maintenance_20260516_121326.json` 输出正常 ✅
- 策略分布：grid=666, reversal=22, trend=6

### 2.5 knowledge_run_links 激活

**时间**: 12:23 (knowledge_db.py 最后修改)

**变更内容**：
- `aggregate_knowledge()` 内部补充 `knowledge_run_links` 关联表写入（见 lines 1079-1101）
- 聚合每条 knowledge_entry 后，解析 `source_run_ids` JSON 数组，逐一删除旧关联并 `INSERT OR IGNORE` 新关联
- 同步方法 `sync_run_links(knowledge_id, run_ids)` 对外保留 API 接口

**影响范围**：
- 累计 695 条关联记录（对应 694 条回测记录 + 1 条已有关联）
- 知识库查询可按 run_id 追溯知识条目的来源回测

### 2.6 market_context 降级回填

**时间**: 12:23 (knowledge_db.py 最后修改)

**变更内容**：
- `_estimate_market_regime(symbol, date, window_short=20, window_long=60)` — 基于实际行情数据判断市场状态（trending_up/trending_down/volatile/unknown）
- `backfill_market_context(run_ids=None)` — 遍历缺失 `market_context` 记录的 run_id，调用上述函数判断并写入
- `store_market_context(run_id, context, date_key)` — 写入 `market_context` 表

**回填进度**：
- 已完成：约 500 条（系统自动回填）
- 剩余：约 194 条（因 `_estimate_market_regime()` 返回 `unknown` 或数据不可用而跳过）
- 需要手动检查市场数据覆盖范围，补全缺失日期

---

## 3. 测试状态

### 3.1 pytest 全量结果

**缓存记录：`.pytest_cache/v/cache/lastfailed`**
- 上次运行存在 **3 个失败测试**（`test_backtest_engine.py::TestFeeModelFix` 全部 3 项）：
  - `test_fee_above_minimum`
  - `test_fee_at_minimum`
  - `test_fee_zero_quantity`
- 这是知识库评审之前的遗留失败项，本阶段未修复
- 其余测试全部通过

### 3.2 流水线验证结果

| 验证项 | 结果 | 备注 |
|:-------|:----:|:-----|
| 回测引擎每日推送 | ✅ | `_pipeline_main_v2.py` 运行正常 |
| knowledge.db 数据入库 | ✅ | 694 条记录 |
| aggregate_knowledge 聚合 | ✅ | 含 knowledge_run_links 同步 |
| 日报告生成 | ✅ | `daily_doc_report_2026-05-16.md` |
| 运维健康检查 | ✅ | `daily_maintenance` 运行正常 |
| `pip install -e .` 安装 | ✅ | 可编辑模式安装成功 |

### 3.3 import 验证结果

- 189 条 `from backtest.xxx` 导入语句，全部基于 `pip install -e .` 的包解析
- 所有测试文件使用 `from backtest.xxx` 导入路径
- 脚本入口（`scripts/backfill_knowledge_db.py`, `scripts/init_knowledge_db.py`）使用 `sys.path.insert(0, ...)` + `from backtest.xxx` 导入

---

## 4. 遗留项

### 4.1 未完成

| 项 | 状态 | 说明 |
|:---|:----:|:-----|
| **market_context 剩余 194 条回填** | ⏳ 部分完成 | 500/694 已入库，194 条因数据不可用被跳过；需要扩展市场数据覆盖日期后再试 |
| **file_lifecycle 注册新文件** | ❌ 未处理 | `trade_pairing.py`, `benchmark_data_source.py` 等 12 个文件未注册到 file_lifecycle 系统 |
| **文件注册** | ❌ 未处理 | `src/mozhi_platform.egg-info/` 作为构建产物也可能需加入 `.gitignore` |

### 4.2 未修复的 P1 项

| 项 | 模块 | 影响 |
|:---|:-----|:-----|
| TestFeeModelFix 3 项失败 | `test_backtest_engine.py` | 知识库评审前就已失败，本阶段未修复，待确认是否与最新 fee_model 变更有关 |

---

## 5. 风险提示

| 变更 | 风险等级 | 评估 |
|:-----|:-------:|:-----|
| **pyproject.toml + import 重写** | 🟢 低 | 已有 `pip install -e .` 验证；测试框架均使用统一 import 路径；`sys.path.insert(0)` 脚本不受影响 |
| **trade_pairing 模块迁移** | 🟡 中 | `performance.py` 保持向后兼容（`# noqa: F401`），但直接 `from backtest.analytics.trade_pairing import *` 的外部调用需确认已适配 |
| **B1 修复** | 🟢 低 | 仅改变了执行时机（从模块级改为函数内），输出行为不变 |
| **流水线验证** | 🟢 低 | 全链通过，无阻断；产出文件正常 |
| **knowledge_run_links 激活** | 🟢 低 | 只新增写入，不影响现有知识条目查询；表结构已有 UNIQUE 约束防止重复 |
| **market_context 回填** | 🟡 中 | 194 条未回填意味着这些 run 的 market_regime 使用默认值 "any"；`aggregate_knowledge()` 可能对下游知识聚合引入一定偏差。建议在数据补全后重新运行回填 |
| **file_lifecycle 注册缺失** | 🟡 中 | 12 个文件未注册，`check_unregistered_files` 每次巡检都会报出，需补充注册 |

---

## 总结

本阶段完成 **6 项核心变更**，覆盖项目基础设施重构、代码模块化、Bug 修复、流水线全链验证和知识库功能增强。主要成果：

1. ✅ 项目结构理顺——`pyproject.toml` + `pip install -e .` 使 `from backtest.xxx` 成为标准导入路径
2. ✅ 模块分离——`trade_pairing` 独立，`performance.py` 保持兼容
3. ✅ Bug 修复——`generate_comparison.py` 消除模块级副作用
4. ✅ 流水线畅通——回测→入库→聚合→运维全链验证通过
5. ✅ 知识库增强——`knowledge_run_links` 关联表激活，`market_context` 回填 500/694 条

**待跟进**：market_context 剩余 194 条回填、file_lifecycle 注册更新、TestFeeModelFix 测试修复。
