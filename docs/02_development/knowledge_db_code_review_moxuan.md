# 墨枢 — KnowledgeDB 代码审查报告

**审查方**：墨萱 🔍  
**审查时间**：2026-05-16 10:50 +08:00  
**审查范围**：1o（`to_params_dict()` 三策略一致性）+ 1p（`knowledge_db.py` 模块完整性）+ 1q（`_persist_result()` + 建表/回填脚本）  
**参考文档**：`docs/02_development/knowledge_db_design.md` (v2.2)

---

## REVIEW_RESULT: **发现问题** ⚠️

共发现 **1 个 P0 问题、2 个 P1 问题、2 个 P2 建议**，详情如下。

---

## 一、P0 — 三策略 `_persist_result()` 调用 `_connect()` 而非 `_conn()`

### 文件
- `src/backtest/strategies/run_grid.py` L893
- `src/backtest/strategies/run_trend.py` L624
- `src/backtest/strategies/run_reversal.py` L626

### 代码
```python
kdb = KnowledgeDB()
kdb._connect()    # ← 此方法不存在！
# ...
kdb.close()
```

### 问题
`KnowledgeDB` 的公共连接管理方式是 `with self._conn()` context manager，**没有定义 `_connect()` 方法**。运行到此处将直接抛出 `AttributeError`，意味着整个 KnowledgeDB 写入路径完全不可用。

### 影响
- 三策略的 KnowledgeDB 写入均为死代码
- 运行时会抛出异常（虽然被 `try/except` 包裹），但用户无法感知
- 回填脚本同样依赖 `KnowledgeDB.backfill_run()`（该接口正常），但实时写入完全不可用

### 修正建议

每个策略文件的 `_persist_result()` 中将：

```python
kdb = KnowledgeDB()
kdb._connect()   # ← 删除
```

改为使用 context manager：

```python
with KnowledgeDB() as kdb:
    kdb.store_run(...)
```

注意：`KnowledgeDB` 的 `__enter__` / `__exit__` 已实现（见 `knowledge_db.py` L162-L168），所以 `with` 用法可直接工作。

---

## 二、P1 – 三策略 `_persist_result()` 传递的多参命名有差异

### 文件
三策略的 `_persist_result()` 在传给 `kdb.store_run()` 时：

| 参数 | `run_grid.py` | `run_trend.py` | `run_reversal.py` |
|------|:---:|:---:|:---:|
| `strategy` | `"grid"` ✅ | `"trend"` ✅ | `"reversal"` ✅ |
| `symbol` | `config.symbol` ✅ | `config.symbol` ✅ | `config.symbol` ✅ |
| `config_key` | `config_key` ✅ | `config_key` ✅ | `config.signal_type` ⚠️ |
| `<meta>_key` | — | — | 缺少 `position_mode` 等信息 |
| `triggered_by` | `"manual"` | `"manual"` | `"manual"` |
| `report_path` | `os.path.relpath(filepath, PROJECT_ROOT)` | `os.path.relpath(filepath, PROJECT_ROOT)` | `os.path.relpath(filepath, PROJECT_ROOT)` ✅ |

### 问题
`run_reversal.py` 中将 `config_key` 设为 `config.signal_type`（如 `"rsi"`），而 grid 和 trend 使用 `config_key`（网格用 `_build_config_key()` 生成的详细配置标识，趋势用 `f"{signal_type}_{pos_mode}_{tag}"`）。三者格式不一致，会导致回填后的查询无法统一按 `config_key` 过滤。

### 修正建议

**`run_reversal.py` 的 `_persist_result()` 中**，将 `config_key` 改为与其他两个策略一致：

```python
config_key = f"{config.signal_type}_{config.position_mode}_{config.tag}"
```

---

## 三、P1 – `profit_factor` 字段映射可能为 0.0

### 文件
三策略 `_persist_result()` 中：

```python
"profit_factor": metrics.get("profit_loss_ratio", 0.0),
```

### 问题
- 设计方案的 `performance_results` 表中有 `profit_factor` 列
- 但回测引擎的 `BacktestResult.metrics` 中指标名为 `profit_loss_ratio`
- 当前代码正确做了映射（`metrics.get("profit_loss_ratio", 0.0)`）
- **但是**若 `metrics` 中原来名为 `profit_factor`，此处的映射反而得不到数据

### 修正建议
用双键容错：

```python
"profit_factor": metrics.get("profit_factor") or metrics.get("profit_loss_ratio", 0.0),
```

---

## 四、P2 — 回填脚本 `config_key` 解析可能丢失 `position_mode` 信息

### 文件
`scripts/backfill_knowledge_db.py`

### 问题
`parse_filename()` 中对 grid 策略解析较完整（`config_key = parts[2:-3]` 提取了所有中间部分），但对 trend/reversal 仅将 `parts[2]`（即 `signal_type`）赋给 `config_key`，丢失了 `position_mode` 信息。虽然 `parse_json_content()` 会从 JSON 内容中的 `meta.config_key` 覆盖，但**旧 JSON 文件可能没有 `meta.config_key` 字段**，导致最终 `config_key` 不完整。

### 修正建议
在 `parse_filename()` 中对 trend/reversal 增加：

```python
if strategy in ("trend", "reversal"):
    ...
    result["config_key"] = f"{parts[2]}_{parts[3]}"  # signal + pos_mode
```

同时在 `generate_run_id()` 中使用更完整的 `config_key`。

---

## 五、P2 — `init_knowledge_db.py` 的 `--force` 模式直接 `os.remove`

### 文件
`scripts/init_knowledge_db.py` L29

### 问题
`--force` 模式下先 `backup()` 再 `os.remove()`。但 `KnowledgeDB` 的 `_conn()` 是懒加载的，`__init__` 时不会打开连接。而强删后重新 `kdb.initialize()` 时，**如果原路径父目录不存在**，`initialize()` 中 `sqlite3.connect(self.db_path)` 会创建文件但不会自动创建父目录。

### 修正建议
在 `os.remove(kdb.db_path)` 之前无需处理（删除已有文件不会影响父目录），但建议增加 `os.makedirs(os.path.dirname(kdb.db_path), exist_ok=True)` 以确保数据库所在目录存在。

---

## 六、✅ 通过的审查项目

| 审查项 | 结论 |
|--------|:----:|
| `to_params_dict()` 三策略输出结构一致（capital/fee_rate/slippage/signal/position/meta） | ✅ PASS |
| `knowledge_db.py` DDL 完整性（6 张表 + 索引完整） | ✅ PASS |
| `knowledge_db.py` 事务保护（`with conn:` 自动提交/回滚） | ✅ PASS |
| `knowledge_db.py` 连接管理（`_conn()` context manager + `close()`） | ✅ PASS |
| `knowledge_db.py` 异常处理（`store_run()` 不手动 try/except、异常会上抛至调用方） | ✅ PASS |
| `_persist_result()` try/except 包裹（三策略均已包裹） | ✅ PASS |
| 回填脚本 JSON 解析健壮性（字段缺失/格式差异/双键容错） | ✅ PASS |
| 导入路径正确性（`from src.backtest.pipeline.knowledge_db import KnowledgeDB`） | ✅ PASS |
| `make_run_id()` 格式统一 | ✅ PASS |
| `backfill_run()` INSERT OR IGNORE 避免重复 | ✅ PASS |
| `decay_check()` 实现完整 | ✅ PASS |
| `aggregate_knowledge()` 聚合逻辑正确 | ✅ PASS |
| `validity_grade` 判定规则实现一致 | ✅ PASS |

---

## 七、修复优先级建议

| 优先级 | 问题 | 影响范围 | 修复难度 |
|:------:|:-----|:---------|:---------|
| **P0** | `_connect()` → `_conn()` (或改用 `with KnowledgeDB()`) | 三策略实时写入完全不可用 | 1 行/文件，3 文件 |
| **P1** | `run_reversal.py` 的 `config_key` 与其他策略不一致 | 查询兼容性 | 1 行 |
| **P1** | `profit_factor` 字段映射双键容错 | 数据完整性 | 3 行/文件，3 文件 |
| **P2** | 回填 `config_key` 丢失 position_mode | 回填数据质量 | 1 行 |
| **P2** | `init_knowledge_db.py --force` 增加 `makedirs` | 边缘场景 | 2 行 |

---

*本报告由墨萱（🔍）于墨枢会议期间生成*
