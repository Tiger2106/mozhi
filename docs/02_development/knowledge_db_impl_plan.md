# 墨枢 — knowledge.db 实施计划（子任务细化）

> 作者：墨衡 | 创建时间：2026-05-16 10:20 +08:00 | 版本：v1.0
> 基于：`docs/02_development/knowledge_db_design.md` §6 三阶段方案
> 每项子任务控制在 15-30 分钟，按优先级 P0/P1/P2 排序

---

## 约定

### 优先级定义
| 级别 | 含义 |
|:-----|:------|
| P0 | 必须完成，阻塞后续任务 |
| P1 | 重要，推荐完成 |
| P2 | 优化，可延至下轮迭代 |

### 执行人分工
| 执行人 | 职责 |
|:-------|:-----|
| 墨衡 🖋️ | 编码实现 |
| 墨萱 🧐 | 代码审查、测试验证 |
| 墨涵 📋 | 文件注册、进度协调、验收签收 |

### 执行人简称
- **MH** = 墨衡
- **MX** = 墨萱
- **MHi** = 墨涵

---

## 第一阶段：建库 + 核心模块 + 回填（P0）

依赖拓扑：1a→1b→1c→1d→1e→1f→1g→1h→1i→1j→1k（编码串行链较短）

| 编号 | 任务名 | 预耗时 | 依赖 | 执行人 | 优先级 | 说明 |
|:-----|:-------|:------:|:----:|:------:|:------:|:-----|
| **1a** | `to_params_dict()` — GridRunnerConfig | 25min | — | MH | P0 | `strategies/run_grid.py` 新增方法，统一输出格式 `{capital,fee_rate,slippage,signal,position}` |
| **1b** | `to_params_dict()` — TrendBacktestConfig | 25min | — | MH | P0 | `strategies/run_trend.py` 新增方法，同上格式 |
| **1c** | `to_params_dict()` — ReversalBacktestConfig | 25min | — | MH | P0 | `strategies/run_reversal.py` 新增方法，同上格式 |
| **1d** | `knowledge_db.py` — DDL + initialize() + 常量 + make_run_id() | 30min | — | MH | P0 | 骨架模块：`VALID_INSIGHT_CATEGORIES`、`DDL_SCRIPT`、`_find_project_root()`、`KnowledgeDB.__init__()` + `initialize()` |
| **1e** | `knowledge_db.py` — store_run() + get_run() + list_runs() | 30min | 1d | MH | P0 | 核心 CRUD：三步事务写入（backtest_runs/params_snapshot/performance_results）+ 条件查询 |
| **1f** | `knowledge_db.py` — backfill_run() + update_performance() | 20min | 1e | MH | P0 | 回填接口（允许字段默认值）+ 补录绩效 |
| **1g** | `knowledge_db.py` — aggregate_knowledge() + sync_run_links() + decay_check() | 30min | 1e | MH | P0 | 知识聚合（UPSERT into knowledge_entries）+ 关联表同步 + 衰减检查 |
| **1h** | `knowledge_db.py` — backup() + _conn() 连接管理 | 15min | 1e | MH | P1 | 热备份 + 上下文管理器，错误处理 |
| **1i** | `_persist_result()` 追加 — `run_grid.py` | 15min | 1a, 1e | MH | P0 | 末尾追加 `KnowledgeDB().store_run()` + 顶部 import |
| **1j** | `_persist_result()` 追加 — `run_trend.py` | 15min | 1b, 1e | MH | P0 | 同上 |
| **1k** | `_persist_result()` 追加 — `run_reversal.py` | 15min | 1c, 1e | MH | P0 | 同上 |
| **1l** | `validity_grade` 判定逻辑实现 | 15min | 1e | MH | P0 | `store_run()` 内嵌判定，条件见设计 §2.2.4 表格 |
| **1m** | 建表脚本 `scripts/init_knowledge_db.py` | 20min | 1d | MH | P1 | CLI：`python scripts/init_knowledge_db.py` 创建 data/knowledge.db |
| **1n** | 回填脚本 `scripts/backfill_knowledge_db.py` | 30min | 1e | MH | P0 | 扫描两目录（`src/backtest_results/` + `mo_zhi_sharereports/backtest_results/`），JSON → DB 回填 |
| **1o** | 代码审查 — `to_params_dict()` 三策略 | 25min | 1a~1c | MX | P0 | 审查三策略的 params_json 输出格式一致性 |
| **1p** | 代码审查 — `knowledge_db.py` 模块 | 30min | 1d~1h | MX | P0 | 审查事务保护、DDL 完整性、聚合逻辑 |
| **1q** | 代码审查 — `_persist_result()` + 建表/回填脚本 | 20min | 1i~1n | MX | P1 | 审查调用点和脚本健壮性 |
| **1r** | 测试 — `to_params_dict()` 三策略 | 20min | 1a~1c, 1o | MX | P1 | 手写测试/单次运行确认格式正确 |
| **1s** | 测试 — `store_run()` + `get_run()` + `list_runs()` | 30min | 1e, 1l, 1p | MX | P0 | 完整链路：创建 Config → store_run → get_run → 验证字段完整性 |
| **1t** | 测试 — 回填脚本 → 抽验 5 条 JSON | 20min | 1n, 1q | MX | P1 | 回填后查 DB 确认字段同步正确 |
| **1u** | 文件注册（file_lifecycle DB） | 15min | 1d, 1m, 1n | MHi | P1 | 注册 `knowledge_db.py`、`init_knowledge_db.py`、`backfill_knowledge_db.py` 到 file_registry.db |
| **1v** | 进度协调 & 里程碑 M1 验收签收 | 15min | 1o~1t 全部完成 | MHi | P0 | 确认：所有新回测结果同时写入 JSON + DB，历史数据可通过回填脚本倒入 |

> **M1 验收标准**：一条新回测 → JSON + DB 双写；历史回填 → DB 可查；回填数据 validity_grade 正确

---

## 第二阶段：market_context 接入（P1，等待 T6 完成）

| 编号 | 任务名 | 预耗时 | 依赖 | 执行人 | 优先级 | 说明 |
|:-----|:-------|:------:|:----:|:------:|:------:|:-----|
| **2a** | `market_context` 自动填充 — DDL 确认 | 15min | T6 完成 | MH | P1 | `knowledge_db.py` 新增 `store_market_context()`，输入为 T6 模块输出的市场状态 |
| **2b** | `knowledge_run_links` DDL + sync 改进 | 15min | — | MH | P1 | `initialize()` 中已有 DDL；`aggregate_knowledge()` 后自动 `sync_run_links()` |
| **2c** | KnowlegeExtractor — `query_from_db()` | 25min | 2a | MH | P1 | `knowledge_extractor.py` 新增方法：按 symbol+strategy 查询历史聚合 |
| **2d** | weekly_extractor — `enrich_with_history()` | 20min | 2c | MH | P1 | `weekly_extractor.py` 新增：将周报数据与历史知识对比 |
| **2e** | 测试 — Phase 2 完整链路 | 30min | 2a~2d | MX | P1 | 构造 mock T6 输出 → 模拟市场上下文写入 → 验证 query_from_db 返回正确 |
| **2f** | 代码审查 — Phase 2 全部变更 | 20min | 2a~2d | MX | P1 | 审查市场上下文关联逻辑、KnowlegeExtractor 改动 |
| **2g** | 文件注册 + 里程碑 M2 验收 | 15min | 2e, 2f | MHi | P1 | 注册新增方法变更 + 确认日报/周报可用历史知识 |

> **M2 验收标准**：日报/周报可使用历史知识库做对比，"过去 N 次该标的震荡市平均夏普 X.X"

---

## 第三阶段：衰减机制（P2，30+ 次回测后）

| 编号 | 任务名 | 预耗时 | 依赖 | 执行人 | 优先级 | 说明 |
|:-----|:-------|:------:|:----:|:------:|:------:|:-----|
| **3a** | `scripts/decay_knowledge.py` 衰减脚本 | 20min | 1g | MH | P2 | CLI 脚本：扫描超过 max_age_days 未更新的 knowledge_entries → 标记 degraded |
| **3b** | Cron 配置 — 衰减定时任务 | 15min | 3a | MH | P2 | 配置每周 cron：`python scripts/decay_knowledge.py --max-age 90` |
| **3c** | 季度复核触发器（飞书提醒） | 20min | — | MHi | P2 | 飞书定时消息：提醒主人在季度末复核知识库，手动触发 deprecated |
| **3d** | `auto deprecated` 查询脚本 | 15min | 3a | MH | P2 | `knowledge_db.py` 新增 `list_deprecated()` 方法 + CLI |
| **3e** | 测试 — 衰减完整链路 | 20min | 3a, 3b | MX | P2 | 写入旧 entry → 运行 decay → 验证 status 变更 |
| **3f** | 代码审查 — Phase 3 | 15min | 3a~3d | MX | P2 | 审查衰减逻辑和数据一致 |

> **M3 验收标准**：知识库具备自动衰减能力，季度复核可一键触发飞书提醒

---

## 依赖关系总图

```
1a (Grid) ─┐
            ├─→ 1i (run_grid _persist_result 扩展)
1b (Trend)─┼─→ 1j  (run_trend _persist_result 扩展)
            │
1c (Reversal)─→ 1k (run_reversal _persist_result 扩展)
            │
            ▼
1d (DDL+init) ─→ 1m (建表脚本 init_knowledge_db)
            │
            ▼
1e (store/get/list) ─→ 1f (backfill/update) ─→ 1n (回填脚本)
            │              │
            ▼              ▼
1l (validity_grade)   1o+1p+1q (代码审查)
            │
            ▼
1g (aggregate+sync+decay_check) ──→ (等待 T6 完成)
            │                          │
            ▼                          ▼
         [Phase 3]              2a (market_context 填充)
                                     │
                                     ▼
                                 2c (KnowlegeExtractor query_from_db)
                                     │
                                     ▼
                                 2d (weekly enrich_with_history)
```

---

## 汇总统计

### 按阶段
| 阶段 | 子任务数 | 总工时 | 角色分布 (MH / MX / MHi) |
|:-----|:--------:|:------:|:------------------------:|
| 第一阶段 P0 | 12 | 4.5h | 5.0h / 2.0h / 0.5h |
| 第一阶段 P1 | 5 | 1.8h | 0.5h / 1.0h / 0.3h |
| 第一阶段合计 | 22 | 6.3h | 5.5h / 3.0h / 0.8h |
| 第二阶段 P1 | 7 | 2.3h | 1.3h / 0.8h / 0.3h |
| 第三阶段 P2 | 6 | 1.8h | 1.3h / 0.5h / 0.3h |
| **全场合计** | **35** | **10.4h** | **8.1h / 4.3h / 1.4h** |

### 按优先级
| 优先级 | 子任务数 | 总工时 |
|:------:|:--------:|:------:|
| P0 | 12 | 4.5h |
| P1 | 17 | 5.9h |
| P2 | 6 | 1.8h |

### 并行度建议
- **第一天**：MH 并行 1a+1b+1c+1d（三策略 to_params_dict + DDL 可同时编码），MX 审查 1o+1p+1q
- **第二天**：MH 串行 1e→1f→1g→1h→1i/1j/1k→1n，MX 测试 1r/1s/1t
- **第三天**：MHi 注册 1u + 验收 1v
