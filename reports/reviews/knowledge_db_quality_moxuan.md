# 墨枢 — 知识库系统质量审查报告

- **审查方:** 墨萱 🔍
- **审查对象:** knowledge.db 核心模块 + daily_maintenance 三层运维脚本
- **审查时间:** 2026-05-16 11:41 CST
- **审查版本:** 知识库系统 v1.0

---

## 1. 代码质量审查

### 1.1 DDL 完整性

| 检查项 | 状态 | 备注 |
|:-------|:----:|:-----|
| 6 张表声明 | ✅ | backtest_runs, params_snapshot, market_context, performance_results, knowledge_entries, knowledge_run_links |
| 索引全部到位 | ✅ | 共 15 个索引，覆盖各表主查询字段 |
| UNIQUE 约束 | ✅ | params_snapshot(run_id), performance_results(run_id), knowledge_entries(symbol, strategy, param_version, market_regime, insight_category) |
| FOREIGN KEY 级联删除 | ✅ | 子表全部 ON DELETE CASCADE |
| 幂等建表 | ✅ | 全部使用 CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS |

**结论：DDL 完整，六表结构精准对齐设计方案 v2.2，无缺失。**

### 1.2 事务保护

| 检查项 | 状态 | 备注 |
|:-------|:----:|:-----|
| store_run 三步写入 | ✅ | 单 `with conn: conn.execute(x3)` 隐式事务 |
| backfill_run 三步写入 | ✅ | 同上，`INSERT OR IGNORE` 去重 |
| aggregate_knowledge UPSERT | ✅ | `ON CONFLICT ... DO UPDATE` 幂等聚合 |
| sync_run_links 全量替换 | ✅ | DELETE + executemany 装在同一事务内 |
| decay_check 双段更新 | ✅ | 两条 UPDATE 在同一事务内 |

**结论：事务保护健全。** 核心写入路径均在 `with conn:` 隐式事务包裹内，发生异常时自动回滚。但设计上仍有改进空间（详见 3.2 风险点#2）。

### 1.3 连接管理

| 检查项 | 状态 | 备注 |
|:-------|:----:|:-----|
| 懒加载连接 | ✅ | `_conn_inner` 初始为 None，首次 `_conn()` 时创建 |
| 上下文管理器 | ✅ | `@contextmanager` + `__enter__`/`__exit__` 协议 |
| WAL 模式 | ✅ | `PRAGMA journal_mode=WAL;` 支持并发读写 |
| busy_timeout | ✅ | 3000ms |
| foreign_keys=ON | ✅ | 级联删除生效 |
| row_factory=sqlite3.Row | ✅ | 查询结果按列名访问 |
| close() 显式关闭 | ✅ | `__exit__` 自动调用 |

**结论：连接管理设计规范。** 懒加载 + 上下文管理器避免了连接泄漏，WAL + busy_timeout 提供了基本的并发保护。

### 1.4 异常处理覆盖面

| 检查项 | 状态 | 备注 |
|:-------|:----:|:-----|
| 数据库初始化异常 | ✅ | `sqlite3.DatabaseError` 可自然上抛 |
| store_run 写入失败 | ✅ | `sqlite3.Error` 触发事务回滚 (with conn: 隐式) |
| backfill_run 写入失败 | ⚠️ | catch sqlite3.Error 后返回 False（吃掉异常） |
| update_performance 写入失败 | ⚠️ | 同上，catch 后返回 False |
| aggregate_knowledge 异常 | ⚠️ | 无显式异常处理，依赖外层 |
| decay_check 异常 | ⚠️ | 同上 |
| daily_maintenance 全层 try | ✅ | 每层调用独立 `try/except`，防止单层崩溃影响整体 |
| _find_project_root 异常 | ✅ | RuntimeError 含可操作提示 |
| backup() SQLite 备份 | ⚠️ | 无重试机制，一次失败即上抛 |

**结论：核心路径有异常保护，但部分方法静默吞异常，部分方法无异常兜底。** 异常处理覆盖率为"良"，存在两处可改进点。

---

## 2. 测试结果回顾

| 测试项 | 级别 | 状态 | 备注 |
|:-------|:----:|:----:|:-----|
| P0 复审: `_persist_result() → KnowledgeDB()` | P0 | ✅ | 三个策略文件均正确使用 `with KnowledgeDB() as kdb:` |
| 1r: `to_params_dict()` 三策略输出格式 | P1 | ✅ | Grid/Trend/Reversal 三策略均输出 6 个顶层 key，格式一致 |
| 1s: `store_run + get_run + list_runs` | P0 | ✅ | 三步事务写入正常，A/B/C 有效性等级判定均正确 |
| 1t: `backfill_run INSERT OR IGNORE` | P1 | ✅ | 幂等回填，已有记录静默跳过 |
| `aggregate_knowledge UPSERT` | P0 | ✅ | 聚合正确，按 symbol+strategy+param_version+regime+category 唯一约束 |
| `decay_check` | P1 | ✅ | 90 天衰减标记，分 degraded / deprecated 两档 |
| `daily_maintenance --dry-run` 全三层 | P1 | ✅ | Layer1 清理/备份/归档、Layer2 状态追踪、Layer3 知识沉淀 |
| 实际回填 682 条 JSON | P0 | ✅ | 双源回填（新平台 ~22 + 旧库 ~660），成功率 100%，0 条重复跳过 |

### 测试覆盖率

| 维度 | 覆盖情况 | 状态 |
|:-----|:---------|:----:|
| 三策略 | grid / trend / reversal | ✅ |
| 多标的 | 601857.SH / 000001.SZ | ✅ |
| 双数据源 | 新平台 JSON + 旧库 JSON | ✅ |
| 实机运行 | 7 条即时运行记录 | ✅ |
| 知识聚合 | 8 条知识条目（含 high/medium 置信度） | ✅ |

### 测试日志摘要（daily_maintenance --dry-run 全三层）

```
[Layer 1] cleanup: cleaned=0, failed=0
          report_check: missing=false, found=1
          archive: groups=0, files=0
          knowledge_backup: dry-run (would backup)
          engine_backup: dry-run (source 0KB)
[Layer 2] incoming: stale=0
          drafts: total=0
          backtests: total=689, week_start=2026-05-11 (grid=661, reversal=22, trend=6)
          unregistered: count=12
[Layer 3] aggregate: dry-run (would aggregate)
          decay: dry-run (would check decay)
```

**测试结论：全部测试项通过，覆盖率充分。**

---

## 3. 关键发现

### 3.1 代码稳健性评分

| 维度 | 评分 | 依据 |
|:-----|:----:|:-----|
| **DDL 设计** | **优** | 6 表 + 15 索引 + UNIQUE 约束 + 级联删除，无缺失项 |
| **事务保护** | **良** | 核心写入路径有事务包裹；但隐式事务使得部分场景异常处理不够明确 |
| **连接管理** | **优** | 懒加载 + 上下文管理器 + WAL + busy_timeout + row_factory |
| **异常处理** | **良** | 核心路径有保护，但部分方法静默吞异常（backfill_run 等） |
| **代码组织** | **优** | 模块边界清晰，类设计合理，文档字符串完善 |
| **并发安全性** | **中** | WAL 提供基本支持，但备份无文件锁，高频场景无补偿机制 |

**综合评分：良 → 优** (Score: 4/5)

### 3.2 最大的 3 个风险点

#### 🔴 风险点 #1：`backfill_run()` / `update_performance()` 静默吞异常

**文件：** `knowledge_db.py` L404-406, L472-475

```python
try:
    with self._conn() as conn:
        with conn:
            ...
    return True
except sqlite3.Error:
    return False  # ⚠️ 异常被完全吞掉
```

**风险：** 返回 `False` 后调用方无从得知失败原因。backfill 682 条记录的场景中，如果中途有一条写入失败，只会返回 False，日志中没有错误详情，排查困难。

**建议：** 至少用 `logging.exception()` 记录异常栈：
```python
except sqlite3.Error as e:
    logging.exception("backfill_run failed for run_id=%s: %s", run_id, e)
    return False
```

#### 🔴 风险点 #2：`store_run()` 使用隐式事务

**代码：**
```python
with self._conn() as conn:
    with conn:           # 隐式事务
        conn.execute(...)
        conn.execute(...)
        conn.execute(...)
```

`with conn:` 是 Python sqlite3 的隐式事务管理。虽然功能正确（异常自动回滚），但它对所有写操作使用相同的事务边界，无法精细控制保存点。对于高频写入场景（同一秒内多次回测），隐式事务可能导致不必要的全量回滚。

**建议：** 对高频批量操作，可考虑显式事务 + 保存点：
```python
with self._conn() as conn:
    try:
        conn.execute("SAVEPOINT sp_store_run")
        conn.execute(...)
        conn.execute(...)
        conn.execute(...)
        conn.execute("RELEASE SAVEPOINT sp_store_run")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT sp_store_run")
        raise
```

（当前业务量级（<10次/分钟）下此风险极低，建议作为技术债务跟踪。）

#### 🔴 风险点 #3：`make_run_id()` 秒级冲突 + `_find_project_root()` 性能隐忧

**文件：** `knowledge_db.py` L87-103, L120-150

```python
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
# 同一秒内同策略同标的的不同回测 → 相同 run_id → PK 冲突 → 插入被跳过
```

当前回填的 682 条中，`run_id` 由文件名解析产生（源自旧 JSON 文件名），不依赖 `make_run_id()`。但**新运行的即时回测**有冲突风险。目前回测频率低（几分钟一次），非即时问题，但随使用频次增加风险上升。

此外，`_find_project_root()` 每次 `import` 时执行文件系统遍历，虽然模块级缓存（`PROJECT_ROOT` 全局变量）将其限制为一次，但如果 `pyproject.toml` 不存在则回退到环境变量——路径计算在未设置环境变量时会触发 `RuntimeError`，这在测试场景（如 pip install -e 后测试）中可能意外中断。

**建议：**
1. 时间戳追加微秒：`%Y%m%d_%H%M%S_%f`（截断前 6 位微秒）
2. `_find_project_root()` 添加 `__file__` 路径缓存 + 环境变量检查顺序优化

### 3.3 建议改进项

按优先级排列：

| 优先级 | 改进项 | 文件 | 影响 |
|:------:|:-------|:-----|:-----|
| **P1** | 组合索引 `(strategy, symbol, created_at DESC)` | DDL | 联合查询场景避免全表扫描 |
| P1 | `make_run_id()` 追加微秒 | `knowledge_db.py` | 消除秒级冲突 |
| P1 | backfill_run 加入 `logging.exception()` | `knowledge_db.py` | 异常可排查 |
| P1 | 将新文件注册到 file_lifecycle DB | 运维流程 | 文件管理完整性 |
| P1 | `backup()` 增加重试机制 | `knowledge_db.py` | 备份可靠性 |
| P2 | `daily_maintenance.py` 12 个未注册文件 | 运维流程 | 文件管理完整性 |
| P2 | `stale_threshold_days` 参数名 | `knowledge_db.py` | 命名清晰度 |
| P2 | `validate_insight_category()` 输入校验 | `knowledge_db.py` | 数据完整性 |
| P3 | `extra_metrics` 规范化为列 | Schema | 查询性能 |
| P3 | 获取连接前校验 `isolation_level` | `knowledge_db.py` | 事务一致性的防御性编程 |

---

## 4. 审查结论

```
REVIEW_RESULT = PASS
```

**最终评定：通过。**

### 综合评估

本系统通过六表 DDL 设计 + CRUD/聚合/衰减完整实现 + 三层运维脚本，达成了知识库系统的全部核心功能。经代码审查和测试验证：

- ✅ DDL 完整——六表 + 15 索引 + 4 项 UNIQUE 约束 + 级联删除
- ✅ 事务保护健全——核心写入路径均受事务保护
- ✅ 连接管理规范——懒加载 + 上下文管理器 + WAL 模式
- ✅ 测试覆盖率充分——P0/P1 测试全部通过，实际回填 682 条成功率 100%
- ⚠️ 异常处理需补强——2 处静默吞异常需加日志
- ⚠️ 组合索引欠缺一处——联合查询可能全表扫描

### 验收条件

| 条件 | 状态 | 说明 |
|:-----|:----:|:-----|
| 设计 P0 问题已修复 | ✅ | FK 语义错误已删除；`_find_project_root()` 健壮性已改进 |
| 核心 CRUD 测试通过 | ✅ | store/get/list/backfill 全通过 |
| 运维脚本全三层可运行 | ✅ | dry-run + 实际运行均正常 |
| 历史数据回填通过 | ✅ | 682 条，成功率 100% |
| 知识聚合功能正常 | ✅ | 8 条知识条目，含 high/medium 置信度 |
| 衰减检查逻辑正确 | ✅ | 90 天双段标记 |

**3 个风险点属于 P1 级"应改进非必须"问题，不影响系统上线。建议在下一次迭代中优先解决。**

---

*报告由墨萱 🔍 生成*
*审查日期：2026-05-16 11:41 CST*
