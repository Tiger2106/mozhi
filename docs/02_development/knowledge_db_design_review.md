# 回测知识库系统设计评估报告

> 作者: 墨衡 | 创建时间: 2026-05-16 09:42 +08:00 | 版本: v1.0

---

## 一、总体可行性评估

**结论：设计合理可行，建议立即启动第一阶段。**

主人设计的五表模型（`backtest_runs` → `params_snapshot` → `market_context` → `performance_results` → `knowledge_entries`）形成了一个完整的回测闭环，覆盖了从"跑出结果"到"沉淀知识"再到"自动失效"的全生命周期。该设计与现有代码库的接口清晰、拆分合理、渐进式实施的路径明确。

---

## 二、关键问题回答

### 2.1 当前 `_persist_result()` 在哪些文件？如何扩展？

**三个策略文件各有一个独立的 `_persist_result()` 函数：**

| 文件 | 位置 | 命名格式 | Config 类型 |
|:-----|:-----|:---------|:------------|
| `src/backtest/strategies/run_grid.py` | ~L884 | `grid_{symbol}_{config_key}_{tag}_{date}_{time}.json` | `GridRunnerConfig` |
| `src/backtest/strategies/run_trend.py` | ~L634 | `trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json` | `TrendBacktestConfig` |
| `src/backtest/strategies/run_reversal.py` | ~L646 | `reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json` | `ReversalBacktestConfig` |

**当前行为：**
- 三个函数实现高度相似：将 `meta`（包含 config 信息）+ `result`（BacktestResult.to_dict()）写入 JSON 文件到 `backtest_results/` 目录
- 仅持久化到**文件系统**，无数据库写入
- `GridRunnerConfig` 是 `@dataclass`，其属性通过 `payload["meta"]` 手工映射序列化

**扩展方案（推荐）：**

大原则：**不替换**现有文件持久化逻辑（保留文件备份），**追加**一条数据库写入路径。

```
┌─────────────────────────────────────────────────┐
│                 _persist_result()                │
│                                                   │
│   Step 1: 写入 JSON 文件（保持不动）                │
│   Step 2: 调用 KnowledgeDB.store_run(...) 写库    │
│                                                   │
│   Step 2 内部的原子操作序列：                        │
│   1. INSERT INTO backtest_runs                    │
│   2. INSERT INTO params_snapshot                  │
│   3. INSERT INTO performance_results              │
└─────────────────────────────────────────────────┘
```

**建议的代码组织：**
- 新建 `src/backtest/knowledge_db.py`，封装 `KnowledgeDB` 类
- `KnowledgeDB.store_run()` 方法接受 `(strategy_type, config, result, config_key)`，内部执行三步写入
- 三个 `_persist_result()` 函数各追加一行 `KnowledgeDB().store_run(...)` 调用

```python
# 在 _persist_result() 末尾追加（三个文件各加一行）
from src.backtest.knowledge_db import KnowledgeDB
KnowledgeDB().store_run(
    strategy_type="grid",
    config=config,
    result=result,
    config_key=config_key,
    strategy_tag=config.tag,
    report_path=filepath,
)
```

### 2.2 `to_params_dict()` 是否在 v4.0 第4项中已就绪？

**尚未实现。** 根据 `docs/02_development/plan_backtest_improvement_v4.0.md`：

- **P0-43**: `GridRunnerConfig.to_params_dict()` — 已规划，第4批，墨衡
- **P0-44**: `TrendBacktestConfig.to_params_dict()` — 已规划，第4批，墨衡
- **P0-45**: `ReversalBacktestConfig.to_params_dict()` — 已规划，第4批，墨衡

当前三个 Config 类均无 `to_params_dict()` 方法。这是知识库系统的**关键前置条件**，因为 `params_snapshot.params_json` 需要此输出。

**紧急建议**：将此三项优先级提升到**第一阶段**，与知识库建库并列执行。

各 Config 的实现概要：

```python
# GridRunnerConfig.to_params_dict()
def to_params_dict(self) -> dict:
    signal_params = {}
    if hasattr(self.signal, 'params'):
        signal_params = dict(self.signal.params)
    elif hasattr(self.signal, 'grid_config'):
        gc = self.signal.grid_config
        signal_params = {
            "grid_lower": gc.lower_bound,
            "grid_upper": gc.upper_bound,
            "n_levels": gc.n_levels,
            "grid_type": gc.grid_type,
        }
    
    pos_params = {}
    if self.position:
        if hasattr(self.position.position_logic, 'quantity'):
            pos_params["base_quantity"] = self.position.position_logic.quantity
        pos_params["cool_down_bars"] = self.position.cool_down.cool_down_bars
        pos_params["position_mode"] = self.position.position_logic.mode
    
    return {
        "capital": self.initial_capital,
        "fee_rate": self.fee_rate,
        "slippage": self.slippage_rate,
        "signal": signal_params,
        "position": pos_params,
    }
```

```python
# TrendBacktestConfig.to_params_dict()
def to_params_dict(self) -> dict:
    return {
        "signal_type": self.signal_type,
        "position_mode": self.position_mode,
        "trend_params": dict(self.trend_params) if hasattr(self, 'trend_params') else {},
        "capital": self.initial_capital,
        "fee_rate": self.fee_rate,
    }
```

```python
# ReversalBacktestConfig.to_params_dict()
def to_params_dict(self) -> dict:
    return {
        "signal_type": self.signal_type,
        "position_mode": self.position_mode,
        "reversal_params": dict(self.reversal_params) if hasattr(self, 'reversal_params') else {},
        "capital": self.initial_capital,
        "fee_rate": self.fee_rate,
    }
```

### 2.3 手工回填现有历史数据的可行性

**完全可行，但需明确数据范围和格式兼容性。**

**现有数据存量：**
- `src/backtest_results/` 目录下有少量历史回测 JSON 文件（网格策略为主）
- 格式统一：`{ "meta": {...}, "result": {...} }`

**手工回填方案：**

```python
# 回填脚本：scripts/backfill_knowledge_db.py
def backfill_from_json(json_dir: str):
    """读取现有 backtest_results/*.json 文件，回填到 knowledge.db"""
    import glob, json
    db = KnowledgeDB()
    
    for fp in glob.glob(f"{json_dir}/*.json"):
        with open(fp) as f:
            data = json.load(f)
        
        meta = data["meta"]
        result = data["result"]
        metrics = result.get("metrics", {})
        
        # 从文件名推断策略类型
        filename = os.path.basename(fp)
        if filename.startswith("grid_"):
            strategy = "grid"
        elif filename.startswith("trend_"):
            strategy = "trend"
        elif filename.startswith("reversal_"):
            strategy = "reversal"
        else:
            continue
        
        # 构建缺失字段的默认值
        db.backfill_run(
            run_id=f"backfill_{os.path.splitext(filename)[0]}",
            strategy=strategy,
            symbol=meta["symbol"],
            start_date=result.get("actual_range", {}).get("start", ""),
            end_date=result.get("actual_range", {}).get("end", ""),
            data_days=result.get("total_bars", 0),
            param_version="v0_backfill",
            params_json=meta,  # 以 meta 代替 params
            metrics=metrics,
        )
```

**需要注意的问题：**

| 问题 | 说明 | 解决方式 |
|:-----|:-----|:---------|
| 缺少 `param_version` | 历史文件无版本号 | 统一标记为 `"v0_backfill"` |
| 缺少 `data_days` | 需从 `total_bars` 推算 | 用 `result.total_bars` |
| `params_snapshot` 质量 | `meta` 字段仅为运行时快照，不是 `to_params_dict()` 标准输出 | 记录为一个 blob 字段，标记为 `backfill` |
| 缺少 `run_by` / `triggered_by` | 历史数据无此信息 | 统一 `run_by="unknown"`, `triggered_by="backfill"` |
| 顺序依赖 | 必须先实现 `KnowledgeDB` 类和表结构 | — |

**估算**：约 30-60分钟编写回填脚本 + 视数据量执行时间（200个文件以内 < 5秒）。

### 2.4 各阶段实施工作量估计

| 阶段 | 子任务 | 文件/范围 | 预计工时 | 前置条件 |
|:-----|:-------|:----------|:--------|:---------|
| **第一阶段：立即可做** | | | **约 4-5 小时** | |
| 1a | 建库 + 五张表定义 | 新建 `src/backtest/knowledge_db.py` | 1.5h | — |
| 1b | `to_params_dict()` 三策略实现 | `run_grid.py`, `run_trend.py`, `run_reversal.py` | 0.5h × 3 = 1.5h | — |
| 1c | 扩展三个 `_persist_result()` | 同上三个文件 | 0.5h | 1a, 1b |
| 1d | 手工回填脚本 | `scripts/backfill_knowledge_db.py` | 0.5h | 1a |
| 1e | `validity_grade` 判定逻辑 | `performance_results.validity_grade` | 0.5h | T1 已整合 |
| | **第二阶段：T6完成后** | | **约 3-4 小时** | |
| 2a | `market_context` 自动填充 | `market_context` 表填充逻辑 | 1.5h | T6 市场状态分析 |
| 2b | `KnowledgeExtractor` 改查 DB | `knowledge_extractor.py` | 1.5h | 2a |
| 2c | weekly_reference 接入 | `weekly_extractor.py` | 0.5h | 2b |
| | **第三阶段：30+次回测后** | | **约 2-3 小时** | |
| 3a | 衰减机制定时任务 | cron 脚本 | 1h | — |
| 3b | 季度复核 UI/触发器 | agent 任务 | 1h | 3a |
| 3c | 自动 deprecated 逻辑 | `knowledge_entries.status` 更新 | 0.5h | 3a, 3b |
| | **合计** | | **9-12 小时** | |

---

## 三、设计建议与优化点

### 3.1 run_id 生成策略

建议采用统一的 run_id 生成函数，避免各策略自行拼接：

```python
def make_run_id(strategy: str, symbol: str, config_key: str, tag: str = "") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [strategy, symbol, config_key, tag, ts]
    return f"run_{'_'.join(p for p in parts if p)}"
```

### 3.2 事务保护

三条 INSERT（`backtest_runs` + `params_snapshot` + `performance_results`）应包裹在 SQLite 事务中，任意一条失败则整体回滚：

```python
def store_run(self, ...):
    conn = sqlite3.connect(self.db_path)
    try:
        conn.execute("BEGIN")
        # INSERT INTO backtest_runs
        # INSERT INTO params_snapshot
        # INSERT INTO performance_results
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

### 3.3 diff_from_prev 的实现

`params_snapshot.diff_from_prev` 用于跟踪参数变更。初始实现可简单使用：

```python
def _compute_diff(self, current_params: dict, prev_params: dict = None) -> str:
    if not prev_params:
        return json.dumps({"type": "initial"})
    
    changed = {}
    for k in set(current_params.keys()) | set(prev_params.keys()):
        if current_params.get(k) != prev_params.get(k):
            changed[k] = {"old": prev_params.get(k), "new": current_params.get(k)}
    
    return json.dumps(changed, ensure_ascii=False)
```

### 3.4 数据库文件位置

建议：`data/knowledge.db`（对 `data/` 目录已有的结构复用）

```python
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "knowledge.db"
)
```

### 3.5 关于 `knowledge_entries` 中的 `validity_grade`

注意：`knowledge_entries` 表设计中的 `validity_grade` 字段在原始 SQL 中实际存在于 `performance_results` 表。原始设计是：

- `performance_results.validity_grade` — 单次回测结果的有效性等级（A/B/C）
- `knowledge_entries.confidence` — 多条回测累积置信度（high/medium/low）

两者语义不同，无需合并。

### 3.6 关于 `sample_size` 的计算

`knowledge_entries.sample_size` 建议通过 SQL 聚合查询动态计算，而非手动维护：

```sql
SELECT COUNT(*) 
FROM performance_results pr
JOIN backtest_runs br ON pr.run_id = br.run_id
WHERE br.symbol = ? AND br.strategy = ?
  AND pr.validity_grade IN ('A', 'B')  -- 只计有效回测
```

---

## 四、潜在风险与缓解

| 风险 | 等级 | 缓解措施 |
|:-----|:-----|:---------|
| `to_params_dict()` 实现滞后导致第一阶段卡住 | 高 | 优先级提升至第一阶段最前面；先用 `meta` json 字段做 `params_json` 降级方案 |
| 三个 `_persist_result()` 重复代码 | 中 | 可抽取公共的 `KnowledgeDB.store_run()`，三个调用点各一行 |
| 手工回填缺少 `param_version` | 低 | 统一标记 `backfill`，不影响新数据 |
| 衰减机制触发时机的判定难度 | 中 | 早期手动触发季度复核即可，不需要全自动 |
| SQLite 并发写入（回测多进程场景） | 中 | `WAL` 模式 + `retry_on_busy` |

---

## 五、实施顺序建议（推荐路线）

```
优先：P0-43~45 to_params_dict()
  └─→ 1a KnowledgeDB 建表 + 初始化
       └─→ 1c 扩展 _persist_result()
            ├─→ 1d 回填脚本（可并行）
            └─→ 1e validity_grade 判定（可并行）
                 └─→ (等待 T6 完成)
                       └─→ 2a market_context 自动填充
                            └─→ 2b 知识提取查库
                                 └─→ (等待 30+次回测)
                                       └─→ 3a~3c 衰减机制
```

**推荐起始时间**：`to_params_dict()` 可立即开始（预计 30 分钟完成三策略），随后创建 `KnowledgeDB` 类。

---

## 六、核心依赖关系图

```
[to_params_dict()]
        │
        ▼
[KnowledgeDB.__init__()] ───→ [DB 建表五张]
        │
        ▼
[三个 _persist_result() 各加 1 行]
        │
        ├─→ [回填脚本 scripts/]
        │
        ▼
[KnowledgeExtractor 改造] ←─── [T6 market_context]
        │
        ▼
[weekly_reference 接入]
        │
        ▼
[衰减 + 季度复核]
```
