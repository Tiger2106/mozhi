# 墨枢 — knowledge.db 设计方案技术审查

> 审查方：墨萱 🔍
> 审查对象：`docs/02_development/knowledge_db_design.md` v2.0（墨衡）
> 审查时间：2026-05-16 09:56 +08:00
> 审查依据：
>   - 设计方案 v2.0（墨衡）
>   - 路径审查意见 v1.0（墨涵补充参考）
>   - 原始评估报告 v1.0（墨衡）

---

## REVIEW_RESULT: **FAIL (P0 问题 2 处)**

审查结论：设计方案整体质量良好，但存在 2 处 P0 级别问题，须修复后方可进入实施阶段。

---

## 一、P0 问题（必须修复）

### P0-1：`knowledge_entries.symbol` 外键约束语义错误

**问题描述：**
```sql
FOREIGN KEY (symbol) REFERENCES backtest_runs(symbol)
```

`backtest_runs.symbol` 不是唯一键（`PRIMARY KEY` 是 `run_id`），SQLite 允许将此 FK 关联到非 `UNIQUE` 列，但**语义上完全错误**：

- 该 FK 的本意是"一条知识条目引用某个回测"，但写成了"symbol 字符串必须存在于 backtest_runs.symbol 列中"
- 只要 `backtest_runs` 表中**任何一条**记录的 `symbol` 匹配，FK 就通过——这形成了一种虚假的数据约束
- 一旦 `backtest_runs` 中没有任何该标的记录，`knowledge_entries` 就无法插入知识条目，与 "根据历史回测聚合知识" 的业务逻辑矛盾（知识条目应在运行回测后独立存在）

**建议修复：**
`knowledge_entries` 不应包含指向 `backtest_runs` 的外键约束。它的关联是通过 `source_run_ids`（JSON array of run_id）实现的逻辑关联，不需要 FK：

```sql
-- 删除该行
-- FOREIGN KEY (symbol) REFERENCES backtest_runs(symbol)
```

或者如果确实需要 FK，应改为 `FOREIGN KEY (id) REFERENCES backtest_runs(run_id)` 但这对 `knowledge_entries` 的多对一关系也不合适。

**结论：删除 `knowledge_entries` 的外键约束。**

---

### P0-2：`_find_project_root()` 健壮性不足

**问题代码：**
```python
def _find_project_root() -> str:
    current = os.path.dirname(os.path.abspath(__file__))
    while current:
        if os.path.exists(os.path.join(current, "pyproject.toml")):
            return current
        if os.path.exists(os.path.join(current, "setup.py")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.dirname(os.path.dirname(current))  # 回退到 src/
        current = parent
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**问题细节：**

1. **死循环风险（高危）**：`backup_dir` 溯源到 `data/db/`，如果执行 `knowledge_db.py` 的 CWD 恰好在一个不含 `pyproject.toml` 或 `setup.py` 的目录下（如 `C:\`），`while current` 会一直向上遍历直到根目录。在根目录时 `os.path.dirname("C:\\") == "C:\\"`，此时 `parent == current` 条件触发，走回退分支。虽然不会真正无限循环，但路径计算的异常分支非常容易出错。

2. **回退分支逻辑混乱**：
   ```python
   if parent == current:
       return os.path.dirname(os.path.dirname(current))  # 回退到 src/
   ```
   当 `current == "C:\\"` 时，`os.path.dirname(os.path.dirname("C:\\")) == "C:\\"`，即返回根目录，根本不会"回退到 src/"。

3. **与 `initialize()` 的执行时序耦合**：设计风险表格提到"第一次调用 _persist_result 时自动建表"，但 `__init__` 中并没有调用 `initialize()`，`store_run()` 中也未做懒加载检查。如果用户直接调用 `store_run()` 而忘记先调用 `initialize()`，将因表不存在而崩溃。

**建议修复：**

方案一（推荐）：改用 `PROJECT_ROOT` 环境变量兜底：

```python
import os

_PROJECT_ROOT_CACHE = None

def _find_project_root() -> str:
    global _PROJECT_ROOT_CACHE
    if _PROJECT_ROOT_CACHE is not None:
        return _PROJECT_ROOT_CACHE

    # 1. 环境变量优先
    env_root = os.environ.get("MOZHI_PROJECT_ROOT") or os.environ.get("PROJECT_ROOT")
    if env_root and os.path.isdir(env_root):
        _PROJECT_ROOT_CACHE = os.path.abspath(env_root)
        return _PROJECT_ROOT_CACHE

    # 2. 从 knowledge_db.py 所在位置上溯
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(50):  # 安全上限
        markers = ["pyproject.toml", "setup.py", "mozhi_platform"]
        for m in markers:
            if os.path.exists(os.path.join(current, m)):
                _PROJECT_ROOT_CACHE = current
                return current
        parent = os.path.dirname(current)
        if parent == current:
            break  # 已到根目录，停止上溯
        current = parent

    # 3. 兜底：使用 __file__ 上溯 4 级 (src/backtest/pipeline/ -> src/backtest/ -> src/ -> 根)
    fallback = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)
    ))))
    if os.path.basename(fallback) == "mozhi_platform":
        _PROJECT_ROOT_CACHE = fallback
        return fallback

    raise RuntimeError(
        f"Cannot determine project root. Set MOZHI_PROJECT_ROOT env var or "
        f"ensure knowledge_db.py is inside the project directory."
    )
```

方案二：设已知常量 `PROJECT_ROOT`，如果找不到标记文件则抛出明确异常，不要静默兜底。

---

## 二、P1 问题（建议修复）

### P1-1：`knowledge_entries` 缺少覆盖索引

`aggregate_knowledge()` 的核心查询模式是：
```sql
SELECT COUNT(*), AVG(return), AVG(sharpe), AVG(max_dd)
FROM performance_results pr
JOIN backtest_runs br ON pr.run_id = br.run_id
WHERE br.symbol = ? AND br.strategy = ?
  AND pr.validity_grade IN ('A', 'B')
```

此查询需要同时过滤 `backtest_runs` 和 `performance_results`。当前索引不足：
- `backtest_runs` 有 `idx_backtest_runs_symbol` 和 `idx_backtest_runs_strategy`，但没有组合索引 `(symbol, strategy)`
- `performance_results` 有 `idx_performance_results_grade`，但没有 `(validity_grade, run_id)` 覆盖索引

**建议：**
```sql
CREATE INDEX idx_backtest_runs_symbol_strategy ON backtest_runs(symbol, strategy);
CREATE INDEX idx_performance_results_grade_run ON performance_results(validity_grade, run_id);
```

---

### P1-2：`_persist_result()` 中 `KnowledgeDB` 每次新建实例

```python
def _persist_result(self, ...):
    # ... JSON 写入 ...
    KnowledgeDB().store_run(...)
```

每次调用都创建新 `KnowledgeDB` 实例（含新建连接），高频回测时（每分钟多次）会反复建连和断连。

**建议：** 模块级缓存单例，或传入 `db` 实例：
```python
# 方式一：模块级单例
_db_instance = None

def _get_db() -> KnowledgeDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = KnowledgeDB()
    return _db_instance

# 在 _persist_result 末尾：
_get_db().store_run(...)
```

或使用 `lru_cache` 风格的懒加载单例模式。

---

### P1-3：`make_run_id()` 的时间戳冲突风险

`make_run_id()` 使用 `datetime.now().strftime("%Y%m%d_%H%M%S")`，精度到秒。如果同一秒内多次运行同一策略+标的，将产生重复 run_id。

虽然 `run_id` 是 PK，冲突会导致第二次写入失败（事务回滚），但仍应在设计层面说明。

**建议：** 在文档中明确标注：
> 当前精度为秒级，高频场景（同一秒内多次回测）可能冲突。如预期高频使用，建议改为 `%f`（微秒）或使用 UUID 后缀。

或直接在代码中使用毫秒/微秒：
```python
ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:21]  # YYYYMMDD_HHMMSS_ffffff
```

---

### P1-4：`backup()` 无并发保护

`backup()` 方法使用 `SQLite backup API` 进行热备份。但在备份期间如果有其他进程写入（WAL 模式下虽可读，但不可写），备份可能不完整。

**建议：** 在文档中补充说明：
> `backup()` 使用 SQLite 在线备份 API，备份期间数据库仍可读取，但不建议同时写入。建议在无人使用时段执行备份。

或增加重试机制：
```python
def backup(self, ...):
    for attempt in range(3):
        try:
            src_conn = sqlite3.connect(self.db_path, timeout=5000)
            # ... backup logic ...
            return backup_path
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < 2:
                time.sleep(1)
                continue
            raise
```

---

### P1-5：`DEFAULT_DB_PATH` 硬编码路径与实际不一致

```python
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # src/backtest/pipeline/
    "..", "..", "..", "data", "knowledge.db"
)
```

文件在 `src/backtest/pipeline/`，上溯三级到 `src/`，再加 `data/knowledge.db`。但 `_find_project_root()` 是从 `__file__` 上溯到找到 `pyproject.toml`。这两条路径逻辑不一致：
- 一个从 `pipeline/` 上溯 3 级
- 一个从 `pipeline/` 上溯直到项目根

如果文件布局改变或 `pyproject.toml` 移动，两者可能给出不同结果。

**建议：** 统一使用 `_find_project_root()`：
```python
DEFAULT_DB_PATH = os.path.join(_find_project_root(), "data", "knowledge.db")
```

而不是手动硬编码上溯级数。

---

### P1-6：回填脚本未提及 `mo_zhi_sharereports/backtest_results/` 路径

墨涵补充意见提到：旧库 JSON 路径 `mo_zhi_sharereports/backtest_results/` 也需纳入回填。

当前 v2.0 设计文档的 `backfill_from_json()` 仅扫描 `backtest_results/` 目录。但如果存在另一套历史数据的旧路径（`mo_zhi_sharereports/backtest_results/`），回填脚本会遗漏。

**建议：** 在回填脚本文档中明确列出所有扫描路径，或设计为可配置的多目录扫描：
```python
SCAN_DIRS = [
    "src/backtest_results",             # 新策略结果
    "mo_zhi_sharereports/backtest_results",  # 旧库共享报告路径
]
```

---

### P1-7：新建文件需注册到 file_lifecycle DB

墨涵补充意见：新文件（`knowledge_db.py`, `init_knowledge_db.py`, `backfill_knowledge_db.py`, `decay_knowledge.py`）需要注册到 file_lifecycle 管理系统。

当前设计文档**未提及** file_lifecycle 注册。

**建议：** 在第一阶段实施清单中增加：
> 1f: 将新文件注册到 file_lifecycle DB（运行 `python -m src.utils.file_lifecycle batch-register`）

---

## 三、P2 问题（可选优化）

### P2-1：`validity_grade` 判定规则建议增加参数

当前判定仅依赖 `data_days >= 60` + `sharpe > 0.5` + `drawdown < 10%`。但 A50 不同标的的波动特性差异大（如 601857.SH 石油股 vs 000333.SZ 消费股），统一阈值可能不精确。

**建议：** 在文档中说明此为初版简化规则，后续可按标的动态调整。

### P2-2：`extra_metrics` 转为规范化列

`performance_results.extra_metrics` 存为 JSON blob。如果某些"额外指标"（如 `calmar_ratio`, `sortino_ratio`, `avg_win/loss`）在多个查询中被频繁提取，建议后续版本将其规范化为主表列。

### P2-3：`decay_check()` 参数名歧义

`decay_check(self, max_age_days=90)` —— 参数名与 SQL 逻辑的关系：
- `max_age_days=90` 表示"超过 90 天未更新的标记为 degraded"
- 但 `max_age_days` 暗示"最大可接受天数"，容易与"最多保留 90 天"混淆

**建议：** 改为 `stale_threshold_days=90` 更清晰。

---

## 四、正面评价

以下方面设计得当，予以肯定：

1. **五表模型完整**：`backtest_runs` → `params_snapshot` → `market_context` → `performance_results` → `knowledge_entries` 形成了完整的回测知识沉淀闭环
2. **事务保护设计**：`store_run()` 使用 `BEGIN/COMMIT/ROLLBACK` 包裹三条 INSERT，保证原子性
3. **幂等建表**：`CREATE TABLE IF NOT EXISTS` + `PRAGMA foreign_keys=ON`，`initialize()` 可反复调用
4. **不替换只追加**：保留 JSON 文件，追加 DB 写入，降低风险
5. **三阶段渐进路线**：依赖关系清晰，每阶段可独立交付
6. **降级方案**：`to_params_dict()` 不可用时用 `meta` 字段兜底
7. **索引基本覆盖**：各表的主查询字段均有索引
8. **filepath 从已有变量传递**：`_persist_result()` 的 `filepath` 已存在，无需额外计算

---

## 五、总结

| 级别 | 数量 | 说明 |
|:-----|:-----|:------|
| **P0（必须修复）** | **2** | FK 语义错误 + `_find_project_root()` 健壮性不足 |
| **P1（建议修复）** | **7** | 索引不足、连接管理、时间戳、并发性文档、路径统一、回填路径遗漏、file_lifecycle 注册 |
| **P2（可选优化）** | **3** | 参数阈值、指标规范化、命名歧义 |

**验收条件：** P0 全部修复后，设计方案可获批进入实施阶段。

---

*审查意见由墨萱 🔍 撰写*
*审查基于设计文档 v2.0 + 墨涵路径审查意见 v1.0*
