# 知识库管理系统建设总结报告

author: 墨衡
created_time: 2026-05-16 11:38 (UTC+8)
version: 1.0
topic: 墨枢知识库（knowledge.db + daily_maintenance）

---

## 1. 系统架构总览

### 1.1 三阶段建设

```
Phase 1 [已完成]        Phase 2 [完成]          Phase 3 [完成]
┌──────────────┐      ┌────────────────┐      ┌──────────────────┐
│ knowledge_db │─────>│ init_knowledge │─────>│ daily_maintenance│
│ 核心模块     │      │ 建表脚本       │      │ 三层运维脚本     │
│ DDL+CRUD     │      │ CLI 幂等建表   │      │ 备份/追踪/沉淀   │
└──────────────┘      └────────────────┘      └──────────────────┘
       │                       │                        │
       └───────────┬───────────┘                        │
                   ▼                                    │
           ┌───────────────┐                            │
           │  backfill     │◄───────────────────────────┘
           │  历史回填脚本  │
           │  682条 JSON   │
           └───────┬───────┘
                   ▼
          ┌────────────────┐
          │  knowledge.db  │
          │  689 条回测记录 │
          │  8 条知识条目   │
          └────────────────┘
```

### 1.2 六张表 + 关联表

| 表名 | 用途 | 记录数 | 说明 |
|:-----|:-----|:------:|:-----|
| `backtest_runs` | 回测运行主表 | 689 | 策略、标的、时间范围 |
| `params_snapshot` | 参数快照 | 689 | 参数字典 JSON 持久化 |
| `performance_results` | 绩效结果 | 689 | 夏普、回撤、胜率等指标 |
| `market_context` | 市场上下文 | 0 | 市场状态（待回填） |
| `knowledge_entries` | 知识条目 | 8 | 聚合后的策略知识 |
| `knowledge_run_links` | 知识-运行关联 | 0 | 多对多关联（待写入） |

### 1.3 数据流

```
回测引擎 (run_grid/trend/reversal.py)
    │
    └── _persist_result()
             │
             v
        KnowledgeDB.store_run()
             │
             ├── backtest_runs (INSERT)
             ├── params_snapshot (INSERT)
             └── performance_results (INSERT)
                         │
                         v
                    knowledge.db
                         │
                         v
                   KnowledgeDB.aggregate_knowledge()
                         │
                         v
                   knowledge_entries (UPSERT)
                         │
                         v
                   KnowledgeExtractor → 早报
```

---

## 2. 实施清单

| 模块 | 文件 | 实现功能 |
|:-----|:-----|:---------|
| **核心模块** | `src/backtest/pipeline/knowledge_db.py` | DDL 六表建表 + 索引；CRUD（store_run / get_run / list_runs / backfill_run / update_performance / get_performance）；`aggregate_knowledge()` 聚合引擎；`decay_check()` 衰减检查；`sync_run_links()` 关联同步；`backup()` SQLite 热备份；`make_run_id()` run_id 统一生成 |
| **策略接入** | `src/backtest/strategies/run_grid.py` (L1020~1097) | `_persist_result()` + `to_params_dict()` + `KnowledgeDB.store_run()`，非阻塞写入 |
| **策略接入** | `src/backtest/strategies/run_trend.py` (L754~835) | 同上，`_persist_result(result, config)` 接口，含有效性等级判定 |
| **策略接入** | `src/backtest/strategies/run_reversal.py` (L793~874) | 同上，`_persist_result(result, config)` 接口 |
| **建表脚本** | `scripts/init_knowledge_db.py` | CLI 建表，支持 `--db-path`、`--force`（备份后重建） |
| **回填脚本** | `scripts/backfill_knowledge_db.py` | 双源回填（新平台 22 条 + 旧库 ~660 条），`--dry-run`、`--source`、`--strategy`、`--symbol`、`--limit` 多过滤参数；文件名自动解析；INSERT OR IGNORE 去重 |
| **运维脚本** | `scripts/daily_maintenance.py` | 三层运维：Layer1 信号清理+报告归档+数据库热备份；Layer2 incoming 超期扫描+知识草稿追踪+本周回测统计+未注册文件检查；Layer3 知识聚合触发+衰减检查；`--dry-run`、`--layer`、`--report`、`--setup-cron` |

---

## 3. 关键数据

### 3.1 回测记录统计

| 指标 | 数值 |
|:-----|:----:|
| **已回填总记录** | **689 条** |
| 其中：新平台 JSON（`src/backtest_results/`） | ~22 条 |
| 其中：旧库 JSON（`mo_zhi_sharereports/backtest_results/`） | ~660 条 |
| 其中：即时运行的策略录入 | 7 条（含 grid/trend/reversal 实际执行） |
| 重复跳过（INSERT OR IGNORE） | 0 条 |

### 3.2 策略分布

| 策略 | 记录数 | 占比 |
|:-----|:------:|:----:|
| grid | 661 | 95.9% |
| reversal | 22 | 3.2% |
| trend | 6 | 0.9% |

### 3.3 标的分布

| 标的 | 记录数 | 说明 |
|:-----|:------:|:-----|
| 601857 / 601857.SH | 475 | 中国石油，主力标的 |
| 000001.SZ | 214 | 平安银行，旧平台标的 |

### 3.4 知识条目（aggregate_knowledge 结果）

| 标的 | 策略 | 置信度 | 样本量 | 状态 |
|:-----|:-----|:------:|:------:|:----:|
| 000001.SZ | grid | high | 214 | active |
| 601857 | grid | high | 440 | active |
| 601857.SH | grid | medium | 5 | active |
| 601857.SH | grid | medium | 2 | active |
| 601857.SH | reversal | medium | 3 | active |
| 601857.SH | trend | medium | 2 | active |
| 601857 | reversal | medium | 19 | active |
| 601857 | trend | medium | 4 | active |

**合计：8 条知识条目**（全为 aggregated 类别，状态 active，无 degraded/deprecated 条目）

### 3.5 覆盖率

- 三策略：grid ✓ / trade ✓ / reversal ✓
- 多标的：601857 / 601857.SH / 000001.SZ
- 数据源：新平台 JSON + 旧库 JSON + 实机运行

---

## 4. 已修复的问题

### 问题 1：`_connect()` 不存在
- **现象**：原始设计中试图使用 `self._connect()` 获取数据库连接，但该方法未定义
- **根因**：早期代码片段与最终 `_conn` 上下文管理器不一致
- **修复**：全部替换为 `with self._conn() as conn:` 上下文管理器，采用懒加载 + 自动管理生命周期模式

### 问题 2：`--dry-run` 写入日报
- **现象**：`daily_maintenance.py --dry-run` 模式下仍尝试写入 daily_doc_report.md
- **根因**：日报生成逻辑未检查 `args.dry_run` 标志
- **修复**：在 `_build_daily_report_md()` 的调用处增加 `if not dry_run:` 检查

---

## 5. 遗留项

### P1 优先级（高）

| 问题 | 描述 | 影响 | 建议修复路径 |
|:-----|:-----|:-----|:------------|
| **组合索引缺失** | 当前只有单列索引（strategy/symbol/created_at），无 (strategy, symbol, created_at) 复合索引 | 联合查询场景（如"查询某策略某标的最新记录"）可能全表扫描 | `CREATE INDEX IF NOT EXISTS idx_runs_strat_sym_date ON backtest_runs(strategy, symbol, created_at DESC)` |
| **make_run_id 秒级冲突** | `make_run_id()` 使用 `%Y%m%d_%H%M%S` 格式，同一秒内同策略同标的的多次回测会生成相同 run_id | INSERT OR IGNORE 会导致后一次写入被静默跳过 | 追加微秒 `%f` 或自增序列号到时间戳中 |
| **backup 并发保护** | `KnowledgeDB.backup()` 使用 `conn.backup()` 时未加锁，多个进程同时备份可能有竞争 | 备份文件可能损坏 | 引入文件锁（`portalocker` 或 `fasteners`）或 PID 文件 |

### 战略盲点（中远期）

| 问题 | 描述 | 关联 |
|:-----|:-----|:-----|
| **知识回馈闭环缺失** | `knowledge_entries` 目前仅供查询，未接入策略参数优化的反馈回路 | 需设计 `KnowledgeConsumer` / `KnowledgeFeedback` 模块 |
| **Step0 集成缺口** | daily_maintenance Layer2 扫描 incoming/，但未接入系统的 Step0 触发链 | 需增加 incoming → pipeline 的 webhook/信号链 |
| **Step1/3.5 集成缺口** | 日报早报流程尚未消费 knowledge.db 的聚合数据 | 需实现 `week_reference` YAML 生成和日报 schema 适配 |
| **Step7 审计集成缺口** | 知识库操作日志未纳入系统的审计流水线 | 需增加 `knowledge_audit_log` 表或对接已有日志系统 |
| **market_context 空表** | 市场上下文表已建立但无数据，aggregate_knowledge 始终使用 'any' regime | 需设计市场状态检测脚本或对接外部数据源 |

---

## 6. 新增/修改文件清单

### 新建文件

| 文件 | 行数 | 说明 |
|:-----|:----:|:-----|
| `src/backtest/pipeline/knowledge_db.py` | 1199 | 知识库核心模块（DDL / CRUD / 聚合 / 衰减 / 备份） |
| `scripts/init_knowledge_db.py` | 43 | CLI 建表脚本 |
| `scripts/backfill_knowledge_db.py` | 702 | 历史 JSON 回填脚本 |
| `scripts/daily_maintenance.py` | 885 | 三层运维脚本 |

### 修改文件

| 文件 | 修改内容 |
|:-----|:---------|
| `src/backtest/strategies/run_grid.py` | 新增 `_persist_result()` 函数，在 L940 调用 `KnowledgeDB.store_run()`，非阻塞写入 |
| `src/backtest/strategies/run_trend.py` | 新增 `_persist_result()` 函数，在 L744 调用 `KnowledgeDB.store_run()`，适配 TrendBacktestConfig |
| `src/backtest/strategies/run_reversal.py` | 新增 `_persist_result()` 函数，在 L783 调用 `KnowledgeDB.store_run()`，适配 ReversalBacktestConfig |

### 数据文件

| 文件 | 说明 |
|:-----|:-----|
| `data/knowledge.db` | SQLite 知识库数据库（689 条回测记录 + 8 条知识条目） |
| `data/db/` | 数据库备份目录（当前 0 个备份，首次运维将生成） |

---

## 附录：DDL 索引总览

```
backtest_runs:
  PRIMARY KEY (run_id)
  INDEX idx_backtest_runs_strategy (strategy)
  INDEX idx_backtest_runs_symbol   (symbol)
  INDEX idx_backtest_runs_created  (created_at)  [❗缺少 (strategy, symbol, created_at) 组合索引]

params_snapshot:
  PRIMARY KEY (id AUTOINCREMENT), UNIQUE (run_id)
  INDEX idx_params_snapshot_run_id   (run_id)
  INDEX idx_params_snapshot_version  (param_version)

market_context:
  PRIMARY KEY (id AUTOINCREMENT)
  INDEX idx_market_context_run_id (run_id)
  INDEX idx_market_context_date   (date_key)
  INDEX idx_market_context_regime (market_regime)

performance_results:
  PRIMARY KEY (id AUTOINCREMENT), UNIQUE (run_id)
  INDEX idx_performance_results_run_id (run_id)
  INDEX idx_performance_results_grade  (validity_grade)

knowledge_entries:
  PRIMARY KEY (id AUTOINCREMENT)
  UNIQUE (symbol, strategy, param_version, market_regime, insight_category)
  INDEX idx_knowledge_entries_symbol   (symbol)
  INDEX idx_knowledge_entries_strategy (strategy)
  INDEX idx_knowledge_entries_status   (status)
  INDEX idx_knowledge_entries_category (insight_category)
  INDEX idx_knowledge_entries_params   (param_version, market_regime)

knowledge_run_links:
  PRIMARY KEY (knowledge_id, run_id)
  INDEX idx_knowledge_run_links_kid (knowledge_id)
  INDEX idx_knowledge_run_links_rid (run_id)
```
