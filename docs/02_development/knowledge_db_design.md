# 墨枢 — 回测知识库系统设计方案

> 作者：墨衡 | 创建时间：2026-05-16 09:50 +08:00 | 最后更新：2026-05-16 10:15 +08:00 | 版本：v2.2
> 基于：`docs/02_development/knowledge_db_design_review.md` 评估结论 + 墨萱 P0 审查 + 主人审阅意见
> 状态：设计完成，待实施（5 项修改已全部落实）

---

## 一、概述

### 1.1 系统目标

构建一个轻量级 SQLite 知识库系统，实现回测结果的结构化存储与知识沉淀闭环。核心目标：

1. **结构化存档**：将回测结果从 JSON 文件系统迁移到统一数据库，支持按策略、标的、时间段灵活查询
2. **参数溯源**：追溯每次回测的完整参数快照，支持参数对比与变更跟踪
3. **绩效沉淀**：累积多条回测的绩效指标，计算有效样本量与置信度
4. **知识提取**：为 KnowlegeExtractor 提供数据库查询接口，实现知识片段的增量累积
5. **自动衰减**：对过时回测知识打标降权，确保知识库的时效性

### 1.2 适用范围

- **标的范围**：A50 标的回测（601857.SH, 003816.SZ, 600900.SH, 000333.SZ 等）
- **策略范围**：网格策略（grid）、趋势策略（trend）、反转策略（reversal）
- **数据源**：`_persist_result()` 三个策略文件 → JSON 文件 + knowledge.db 双写
- **数据库**：SQLite（单机部署，WAL 模式）

### 1.3 设计原则

| 原则 | 说明 |
|:-----|:------|
| **不替换，只追加** | 保留现有 JSON 文件持久化，仅追加数据库写入路径 |
| **可逆性** | 数据库可通过回填脚本从 JSON 文件重建 |
| **渐进实施** | 三阶段路线，每阶段独立交付可用 |
| **轻量依赖** | 仅依赖 Python 标准库（sqlite3） |

---

## 二、数据库设计

### 2.1 数据模型关系图

```
┌─────────────────┐       ┌──────────────────┐
│  backtest_runs  │ 1──N  │  params_snapshot │
│  (回测运行主表)  │       │  (参数快照)       │
└────────┬────────┘       └──────────────────┘
         │
         │ 1
         │
         ├──N ┌─────────────────────┐
         ├───│  market_context      │
         │   │  (市场上下文)         │
         │   └─────────────────────┘
         │
         ├──N ┌──────────────────────┐
         │    │  performance_results  │
         │    │  (绩效结果)            │
         │    └─────────┬────────────┘
         │              │ M:1
         │              ▼
         │    ┌──────────────────────┐
         │    │  knowledge_entries   │
         │    │  (知识条目/聚合)       │
         │    └─────────┬────────────┘
         │              │ 1:N
         │              ▼
         │    ┌──────────────────────┐
         └──N │  knowledge_run_links │
              │  (知识-运行关联表)     │
              └──────────────────────┘
```

### 2.2 表结构 DDL

#### 2.2.1 `backtest_runs` — 回测运行主表

```sql
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id              TEXT PRIMARY KEY,         -- 格式: run_{strategy}_{symbol}_{config_key}_{tag}_{YYYYMMDD_HHMMSS}
    strategy            TEXT NOT NULL,            -- 'grid' | 'trend' | 'reversal'
    symbol              TEXT NOT NULL,            -- 标的代码，如 '601857.SH'
    config_key          TEXT NOT NULL DEFAULT '', -- 配置键（可选）
    strategy_tag        TEXT NOT NULL DEFAULT '', -- 策略标签（可选）
    start_date          TEXT NOT NULL DEFAULT '', -- 回测开始日期 YYYYMMDD
    end_date            TEXT NOT NULL DEFAULT '', -- 回测结束日期 YYYYMMDD
    data_days           INTEGER NOT NULL DEFAULT 0, -- 交易日数
    run_by              TEXT NOT NULL DEFAULT 'auto', -- 执行者: 'auto' | 'manual'
    triggered_by        TEXT NOT NULL DEFAULT '', -- 触发源: 'scheduler' | 'webhook' | 'manual' | 'backfill'
    report_path         TEXT NOT NULL DEFAULT '', -- 对应 JSON 文件相对路径
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_backtest_runs_strategy ON backtest_runs(strategy);
CREATE INDEX idx_backtest_runs_symbol   ON backtest_runs(symbol);
CREATE INDEX idx_backtest_runs_created  ON backtest_runs(created_at);
```

#### 2.2.2 `params_snapshot` — 参数快照

```sql
CREATE TABLE IF NOT EXISTS params_snapshot (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL UNIQUE,     -- 与 backtest_runs 一一对应
    param_version       TEXT NOT NULL DEFAULT 'v0_initial', -- 参数版本号
    params_json         TEXT NOT NULL,            -- 完整参数字典 (JSON)
    diff_from_prev      TEXT NOT NULL DEFAULT '{}', -- 与前一次同策略同标的的参数差异 (JSON)
    snapshot_time       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX idx_params_snapshot_run_id ON params_snapshot(run_id);
CREATE INDEX idx_params_snapshot_version ON params_snapshot(param_version);
```

**`params_json` 的标准化结构**（经 `to_params_dict()` 输出，三种策略通用外壳）：

```json
{
  "capital": 500000.0,
  "fee_rate": 0.0003,
  "slippage": 0.001,
  "signal": { /* 策略特有的信号参数 */ },
  "position": { /* 仓位管理参数 */ }
}
```

#### 2.2.3 `market_context` — 市场上下文

```sql
CREATE TABLE IF NOT EXISTS market_context (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,            -- 关联回测运行
    date_key            TEXT NOT NULL,            -- 日期 YYYYMMDD
    symbol              TEXT NOT NULL DEFAULT '',
    market_regime       TEXT NOT NULL DEFAULT 'unknown', -- 'trend_up' | 'trend_down' | 'range' | 'volatile'
    volatility_level    TEXT NOT NULL DEFAULT 'medium', -- 'low' | 'medium' | 'high'
    trend_strength      REAL NOT NULL DEFAULT 0.0,  -- [-1.0, 1.0]
    sector_percentile   REAL DEFAULT NULL,        -- 行业分位数
    macro_events        TEXT DEFAULT '[]',         -- 宏观事件列表 (JSON array)
    notes               TEXT DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX idx_market_context_run_id ON market_context(run_id);
CREATE INDEX idx_market_context_date   ON market_context(date_key);
CREATE INDEX idx_market_context_regime ON market_context(market_regime);
```

#### 2.2.4 `performance_results` — 绩效结果

```sql
CREATE TABLE IF NOT EXISTS performance_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL UNIQUE,     -- 与 backtest_runs 一一对应
    total_return_pct    REAL NOT NULL DEFAULT 0.0,
    annual_return_pct   REAL NOT NULL DEFAULT 0.0,
    sharpe_ratio        REAL NOT NULL DEFAULT 0.0,
    max_drawdown_pct    REAL NOT NULL DEFAULT 0.0,
    win_rate_pct        REAL NOT NULL DEFAULT 0.0,
    profit_factor       REAL NOT NULL DEFAULT 0.0,
    total_trades        INTEGER NOT NULL DEFAULT 0,
    avg_holding_bars    REAL NOT NULL DEFAULT 0.0,
    validity_grade      TEXT NOT NULL DEFAULT 'C', -- 'A' | 'B' | 'C'
    extra_metrics       TEXT NOT NULL DEFAULT '{}', -- 其他指标 (JSON)
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX idx_performance_results_run_id ON performance_results(run_id);
CREATE INDEX idx_performance_results_grade ON performance_results(validity_grade);
```

**`validity_grade` 判定规则**：

| 等级 | 条件 | 含义 |
|:-----|:-----|:------|
| A | 数据天数 ≥ 60 且 夏普 > 0.5 且 回撤 < 10% | 高质量，可直接纳入知识 |
| B | 数据天数 ≥ 20 且 夏普 > 0.0 | 可参考，用于趋势判断 |
| C | 不满足 B 级条件 | 仅记录，不纳入知识聚合 |

#### 2.2.5 `knowledge_entries` — 知识条目（聚合表）

```sql
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,            -- 标的
    strategy            TEXT NOT NULL,            -- 策略
    param_version       TEXT NOT NULL DEFAULT '', -- 参数版本
    market_regime       TEXT NOT NULL DEFAULT 'any', -- 市场状态
    insight_category    TEXT NOT NULL,            -- 知识类别（见下）
    confidence          TEXT NOT NULL DEFAULT 'medium', -- 'high' | 'medium' | 'low'
    sample_size         INTEGER NOT NULL DEFAULT 0,   -- 有效回测样本数
    avg_return_pct      REAL NOT NULL DEFAULT 0.0,
    avg_sharpe          REAL NOT NULL DEFAULT 0.0,
    avg_max_dd_pct      REAL NOT NULL DEFAULT 0.0,
    insight_summary     TEXT NOT NULL DEFAULT '',  -- 自然语言知识摘要
    source_run_ids      TEXT NOT NULL DEFAULT '[]', -- 来源 run_id 列表 (JSON array)，与 knowledge_run_links 同步
    status              TEXT NOT NULL DEFAULT 'active', -- 'active' | 'degraded' | 'deprecated'
    activated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_updated_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deprecated_at       TEXT DEFAULT NULL,
    UNIQUE(symbol, strategy, param_version, market_regime, insight_category) -- 相同上下文+相同类别只保留一条
);

CREATE INDEX idx_knowledge_entries_symbol ON knowledge_entries(symbol);
CREATE INDEX idx_knowledge_entries_strategy ON knowledge_entries(strategy);
CREATE INDEX idx_knowledge_entries_status ON knowledge_entries(status);
CREATE INDEX idx_knowledge_entries_category ON knowledge_entries(insight_category);
CREATE INDEX idx_knowledge_entries_params ON knowledge_entries(param_version, market_regime);
```

**`insight_category` 预定义值**：取自 KnowlegeExtractor 的类别体系，包括 `sharp_drop`、`sharpe_reversal`、`win_rate_drop`、`high_conflict`、`consecutive_loss`、`drawdown_breach`、`drawdown_recovery`、`allocation_bias` 等。

**`confidence` 判定逻辑**：

| 条件 | confidence |
|:-----|:-----------|
| sample_size >= 5 且 avg_sharpe > 0.5 且 avg_max_dd_pct < 8% | high |
| sample_size >= 2 | medium |
| sample_size < 2 | low |

#### 2.2.6 `knowledge_run_links` — 知识-运行关联表（v2.2 新增）

**用途**：将 `knowledge_entries.source_run_ids`（JSON 字符串）中隐含的多对多关系显式化，
使关联知识条目的回测运行被删除时可通过外键级联自动失效。

```sql
CREATE TABLE IF NOT EXISTS knowledge_run_links (
    knowledge_id        INTEGER NOT NULL,
    run_id              TEXT NOT NULL,
    PRIMARY KEY (knowledge_id, run_id),
    FOREIGN KEY (knowledge_id) REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX idx_knowledge_run_links_kid ON knowledge_run_links(knowledge_id);
CREATE INDEX idx_knowledge_run_links_rid ON knowledge_run_links(run_id);
```

**同步规则**：
- `source_run_ids` 字段保留，但每次 `aggregate_knowledge()` 写入后必须同步更新 `knowledge_run_links`
- 删除回测运行记录时，级联删除关联表中的对应行，但 `knowledge_entries` 本身不受影响（级联在关联表上终止）
- 查询时优先使用 `knowledge_run_links JOIN backtest_runs` 而非解析 JSON

---

## 三、文件布局

### 3.1 程序/脚本文件路径

| 文件 | 路径 | 说明 |
|:-----|:-----|:------|
| `knowledge_db.py` | `src/backtest/pipeline/knowledge_db.py` | KnowlegeDB 类，所有数据库操作封装 |
| `make_run_id()` 生成函数 | `src/backtest/pipeline/knowledge_db.py` 模块级函数 | 统一 run_id 生成 |
| 建表脚本 | `scripts/init_knowledge_db.py` | 仅建表，不含数据 |
| 手工回填脚本 | `scripts/backfill_knowledge_db.py` | 从 `src/backtest_results/` + `mo_zhi_sharereports/backtest_results/` 两目录扫描回填 |
| `to_params_dict()` 三策略实现 | 各策略文件原位添加 | `run_grid.py` / `run_trend.py` / `run_reversal.py` |
| `_persist_result()` 扩展 | 各策略文件原位扩展 | 同上三文件，末尾追加 `KnowledgeDB().store_run()` |
| KnowlegeExtractor 改查 DB | `src/backtest/pipeline/knowledge_extractor.py` | 新增 `query_by_symbol()` 等方法 |
| 衰减脚本 | `scripts/decay_knowledge.py` | 定时任务：检查并标记过期知识 |

**路径选择依据**：

- `knowledge_db.py` 放 `src/backtest/pipeline/` 而非 `src/backtest/` 根目录，因为：
  - 它与 `knowledge_extractor.py`、`weekly_extractor.py` 属于同类——都是"流水线工具"
  - `src/backtest/` 根目录放的是核心引擎文件（`backtest_engine.py`、`data_loader.py` 等）
  - 已有 `pipeline/` 子目录专门存放提取器/推送器/渲染器等流水线下游工具
- `scripts/` 目录存放一次性脚本（建表、回填、衰减），不复用导入的脚本放这里

### 3.2 数据库文件路径

| 文件/路径 | 路径 | 说明 |
|:----------|:------|:------|
| **知识库主文件** | `data/knowledge.db` | 与 `data/trade_engine.db` 并列 |
| 自动备份 | `data/db/knowledge_backup_{YYYYMMDD}.db` | 每日备份，保留最近 7 份 |
| 手动快照 | `data/db/knowledge_snapshot_{YYYYMMDD}.db` | 人工触发，保留永久 |

**路径选择依据**：

- `data/knowledge.db` 与 `data/trade_engine.db` **并列**：
  - 两者都是交易/回测领域的核心数据库，归属同一层
  - `data/db/` 子目录作为备份/快照存放区，与 `backtest_results/` 目录隔离
  - 使用 `knowledge.db` 命名，命名清晰直观
- 默认路径解析方式（`knowledge_db.py` 中 `DEFAULT_DB_PATH`）：

```python
DEFAULT_DB_PATH = os.path.join(
    PROJECT_ROOT,  # 从 __file__ 上溯到项目根目录
    "data", "knowledge.db"
)

def _find_project_root() -> str:
    """从 knowledge_db.py 所在位置上溯到项目根目录。"""
    current = os.path.dirname(os.path.abspath(__file__))
    while current:
        if os.path.exists(os.path.join(current, "pyproject.toml")):
            return current
        if os.path.exists(os.path.join(current, "setup.py")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            # 到达文件系统根仍未找到 → 尝试环境变量兜底
            env_root = os.environ.get("MOZHI_PLATFORM_ROOT")
            if env_root:
                return env_root
            raise RuntimeError(
                "无法确定项目根目录。请执行以下任一操作：\n"
                " 1. 在项目根目录创建 pyproject.toml 或 setup.py\n"
                f" 2. 设置环境变量：export MOZHI_PLATFORM_ROOT=/path/to/mozhi_platform"
            )
        current = parent
    raise RuntimeError(
        "无法确定项目根目录。请执行以下任一操作：\n"
        " 1. 在项目根目录创建 pyproject.toml 或 setup.py\n"
        f" 2. 设置环境变量：export MOZHI_PLATFORM_ROOT=/path/to/mozhi_platform"
    )
```

### 3.3 中间文件/临时文件路径

| 文件类型 | 路径模式 | 清理策略 |
|:---------|:---------|:---------|
| JSON 结果（现有） | `src/backtest_results/run_type_*.json` | 保留（数据库的备份来源） |
| 导出 CSV | `data/db/exports/` | 按需清理 |
| 生成图表/CSV 报告 | `data/backtest_results/` | 按需清理
| WAL/SHM（SQLite 临时） | `data/knowledge.db-wal`, `data/knowledge.db-shm` | SQLite 自动管理 |

---

## 四、模块设计 — `knowledge_db.py`

### 4.1 类结构概览

```
knowledge_db.py
├── 模块级常量/函数
│   ├── DEFAULT_DB_PATH
│   ├── VALID_INSIGHT_CATEGORIES    — frozenset({...})，8 类预定义知识类别
│   ├── _find_project_root()
│   └── make_run_id(strategy, symbol, config_key, tag) -> str
├── class KnowledgeDB
│   ├── __init__(db_path=DEFAULT_DB_PATH)
│   ├── initialize()              — 建立六张表 + 索引
│   ├── store_run(...)            — 三步写入（事务保护）
│   ├── backfill_run(...)         — 回填接口（单条）
│   ├── get_run(run_id)           — 按 run_id 查询
│   ├── list_runs(strategy, symbol, limit, offset)  — 多条件查
│   ├── update_performance(...)   — 补录绩效
│   ├── aggregate_knowledge(...)  — 聚合->knowledge_entries + 同步 knowledge_run_links
│   ├── sync_run_links(knowledge_id, run_ids)  — 同步知识-运行关联表
│   ├── decay_check(...)          — 衰减检查
│   ├── backup()                  — 备份当前 DB
│   └── _conn()                   — 连接管理（上下文管理）
```

### 4.2 核心接口详细定义

#### 4.2.1 `make_run_id(strategy, symbol, config_key, tag) -> str`

```python
def make_run_id(
    strategy: str,
    symbol: str,
    config_key: str = "",
    tag: str = "",
) -> str:
    """
    统一 run_id 生成函数。

    格式：run_{strategy}_{symbol}_{config_key}_{tag}_{YYYYMMDD_HHMMSS}

    各策略的现有 JSON 文件名格式与新 run_id 的对应关系：
    - grid_{symbol}_{config_key}_{tag}_{date}_{time}.json
      → run_id: run_grid_{symbol}_{config_key}_{tag}_{date}_{time}
    - trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json
      → run_id: run_trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}
    - reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json
      → run_id: run_reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}
    """
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [strategy, symbol, config_key, tag, ts]
    return f"run_{'_'.join(p for p in parts if p)}"
```

#### 4.2.2 `KnowledgeDB.__init__(db_path)`

```python
class KnowledgeDB:
    """回测知识库数据库操作封装。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._conn = None  # lazy connection
```

#### 4.2.3 `KnowledgeDB.initialize()`

```python
def initialize(self) -> None:
    """
    建立五张表和索引。

    幂等：CREATE TABLE IF NOT EXISTS，可重复调用。
    """
    conn = sqlite3.connect(self.db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    # 执行五张 DDL（见 §2.2）
    conn.executescript(DDL_SCRIPT)
    conn.commit()
    conn.close()
```

#### 4.2.4 `KnowledgeDB.store_run(strategy, symbol, config, result, ...)`

```python
def store_run(
    self,
    strategy_type: str,
    symbol: str,
    config: Any,              # GridRunnerConfig | TrendBacktestConfig | ReversalBacktestConfig
    result: BacktestResult,
    config_key: str = "",
    strategy_tag: str = "",
    report_path: str = "",
    run_by: str = "auto",
    triggered_by: str = "",
) -> str:
    """
    三步写入（事务保护）。

    Step 1: INSERT INTO backtest_runs
    Step 2: INSERT INTO params_snapshot
    Step 3: INSERT INTO performance_results

    参数
    ----------
    strategy_type : str
        'grid' | 'trend' | 'reversal'
    symbol : str
        标的代码
    config : dataclass
        对应策略的 Config 实例
    result : BacktestResult
        回测结果实例
    config_key : str
        配置键（可选）
    strategy_tag : str
        策略标签（可选）
    report_path : str
        JSON 文件路径
    run_by : str
        执行者
    triggered_by : str
        触发源

    返回
    -------
    str
        生成的 run_id

    异常
    ------
    RuntimeError
        任意 INSERT 失败时整体回滚
    """

def backfill_run(self, run_id, strategy, symbol, ...) -> None:
    """回填单条历史数据到数据库。与 store_run 结构相同，但允许字段默认值。"""

def list_runs(self, strategy=None, symbol=None, limit=20, offset=0) -> list[dict]:
    """查询回测运行记录。"""

def get_run(self, run_id) -> dict | None:
    """获取单条运行记录（含参数和绩效）。"""

def aggregate_knowledge(self, symbol, strategy) -> dict:
    """
    按标的+策略聚合回测结果，生成/更新 knowledge_entries 记录。

    聚合逻辑：
    1. 查询 performance_results (validity_grade IN ('A','B'))
       JOIN backtest_runs WHERE symbol=? AND strategy=?
    2. 计算 avg_return, avg_sharpe, avg_max_dd
    3. 计算 sample_size = count(*)
    4. 判定 confidence
    5. UPSERT into knowledge_entries
    """

def decay_check(self, max_age_days=90) -> list[str]:
    """
    衰减检查：标记超过 max_age_days 未更新的 knowledge_entries 为 'degraded'。

    返回被标记的 entry id 列表。
    """
```

### 4.3 事务保护设计

```python
def store_run(self, ...):
    conn = sqlite3.connect(self.db_path)
    try:
        conn.execute("BEGIN")
        # Step 1: backtest_runs
        conn.execute("INSERT INTO backtest_runs (...) VALUES (...)", ...)
        run_id = cursor.lastrowid  # 或从参数获取

        # Step 2: params_snapshot
        params_json = json.dumps(config.to_params_dict(), ensure_ascii=False)
        conn.execute("INSERT INTO params_snapshot (...) VALUES (...)", ...)

        # Step 3: performance_results
        metrics = result.metrics
        conn.execute("INSERT INTO performance_results (...) VALUES (...)", ...)

        conn.commit()
        return run_id
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"store_run 事务回滚: {e}") from e
    finally:
        conn.close()
```

### 4.4 `_persist_result()` 的调用点扩展（三个策略文件各加一行）

```python
# 在 run_grid.py 的 _persist_result() 末尾追加：
from src.backtest.pipeline.knowledge_db import KnowledgeDB, make_run_id

def _persist_result(self, ...):
    # ... 现有 JSON 写入逻辑不变 ...

    # ▼ 新增：数据库写入
    KnowledgeDB().store_run(
        strategy_type="grid",
        symbol=meta["symbol"],
        config=config,
        result=result,
        config_key=config_key,
        strategy_tag=config.tag,
        report_path=filepath,
    )
```

**注意**：`_persist_result()` 中已有 `filepath` 变量（当前 JSON 文件的绝对路径），可作为 `report_path` 参数传入。

---

## 五、与现有系统的集成

### 5.1 `_persist_result()` 扩展方式

三个策略文件各自追加调用。无需重构现有逻辑，原理如下：

```
_persist_result()
├── Step 1: 写入 JSON 文件（保持不动）
└── Step 2: 调用 KnowledgeDB().store_run()（新增）
     ├── INSERT INTO backtest_runs
     ├── INSERT INTO params_snapshot
     └── INSERT INTO performance_results
```

**扩展前后对比**：

| 策略文件 | 原函数位置 | 需要修改的行 | 修改类型 |
|:---------|:-----------|:-------------|:---------|
| `run_grid.py` | ~L884 | 末尾 +1 行调用 + 顶部 import | 追加 |
| `run_trend.py` | ~L634 | 末尾 +1 行调用 + 顶部 import | 追加 |
| `run_reversal.py` | ~L646 | 末尾 +1 行调用 + 顶部 import | 追加 |

### 5.2 `to_params_dict()` 前置条件

三个 Config 类各需要新增 `to_params_dict()` 方法：

| Config 类 | 所在文件 | 方法签名 |
|:----------|:---------|:---------|
| `GridRunnerConfig` | `strategies/run_grid.py` | `to_params_dict() -> dict` |
| `TrendBacktestConfig` | `strategies/run_trend.py` | `to_params_dict() -> dict` |
| `ReversalBacktestConfig` | `strategies/run_reversal.py` | `to_params_dict() -> dict` |

**优先级**：此项为 P0（见四版计划 P0-43~45），建议升至第一阶段最前面实施。

### 5.3 KnowlegeExtractor 的数据库接入（第二阶段）

现有 `KnowlegeExtractor` 在 `extract_insights()` 中仅使用内存数据（`MultiStrategyResult`）。第二阶段改造：

```python
# knowledge_extractor.py 新增方法
def query_from_db(
    self,
    symbol: str,
    strategy: str = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    从 knowledge.db 查询历史回测知识。

    用途：日报/周报的"历史对比"部分——例如
    "过去 5 次回测中，该标的在震荡市下的平均夏普为 X.X"
    """
    db = KnowledgeDB()
    entries = db.aggregate_knowledge(symbol, strategy)
    # 返回聚合后的知识条目
```

### 5.4 `WeeklyReportExtractor` 的数据库接入（第二阶段）

```python
# weekly_extractor.py 或调用方
def enrich_with_history(weekly_report: dict) -> dict:
    """
    将周报数据与 history 知识库对比。

    例如：本次周收益与历史同市况下平均周收益的对比。
    """
    db = KnowledgeDB()
    history = db.aggregate_knowledge(weekly_report["symbol"], ...)
    weekly_report["historical_context"] = history
    return weekly_report
```

---

## 六、实施计划

### 6.1 三阶段时间线

#### 第一阶段：立即可做（预计 4-5 小时）

| 序号 | 子任务 | 文件/范围 | 预计工时 | 前置条件 |
|:-----|:-------|:----------|:---------|:---------|
| 1a | `to_params_dict()` 三策略实现 | `run_grid.py`, `run_trend.py`, `run_reversal.py` | 1.5h | — |
| 1b | `knowledge_db.py` 建表 + 初始化 | 新建 `src/backtest/pipeline/knowledge_db.py` | 1.5h | 1a（因需要 `to_params_dict()` 接口） |
| 1c | 扩展三个 `_persist_result()` | 同上三个文件 | 0.5h | 1a, 1b |
| 1d | 手工回填脚本 | `scripts/backfill_knowledge_db.py` | 0.5h | 1b |
| 1e | `validity_grade` 判定逻辑实现 | `knowledge_db.py` 内嵌 | 0.5h | — |

**里程碑 M1**：所有新回测结果同时写入 JSON + DB，历史数据可通过回填脚本倒入。

#### 第二阶段：T6（市场状态分析）完成后（预计 3-4 小时）

| 序号 | 子任务 | 文件/范围 | 预计工时 | 前置条件 |
|:-----|:-------|:----------|:---------|:---------|
| 2a | `market_context` 自动填充 | `knowledge_db.py` 新增方法 | 1.5h | T6 市场状态分析完成 |
| 2b | KnowlegeExtractor 改查 DB | `knowledge_extractor.py` 新增 `query_from_db()` | 1.5h | 2a |
| 2c | weekly_reference 接入 | `weekly_extractor.py` 新增 `enrich_with_history()` | 0.5h | 2b |

**里程碑 M2**：日报/周报可使用历史知识库数据做对比分析，市场上下文自动关联。

#### 第三阶段：30+次回测后（预计 2-3 小时）

| 序号 | 子任务 | 文件/范围 | 预计工时 | 前置条件 |
|:-----|:-------|:----------|:---------|:---------|
| 3a | 衰减机制定时任务 | `scripts/decay_knowledge.py` + cron 配置 | 1h | — |
| 3b | 季度复核触发器 | agent 任务（飞书提醒） | 1h | 3a |
| 3c | 自动 deprecated 逻辑 | `knowledge_entries.status` 更新查询 | 0.5h | 3a, 3b |

**里程碑 M3**：知识库具备自动衰减能力，季度复核可一键触发。

### 6.2 依赖关系图

```
[1a to_params_dict()]
        │
        ▼
[1b KnowledgeDB.__init__() + initialize()]
        │
        ▼
[1c 三个 _persist_result() 各加 1 行]
        │
        ├─→ [1d 回填脚本 scripts/backfill_knowledge_db.py]
        │
        ▼ (等待 T6 完成)
[2a market_context 自动填充]
        │
        ▼
[2b KnowlegeExtractor 改造 query_from_db()]
        │
        ▼
[2c weekly_reference 接入]
        │
        ▼ (等待 30+次回测)
[3a~3c 衰减 + 季度复核]
```

---

## 七、风险与缓解

### 7.1 风险矩阵

| 风险 | 等级 | 发生概率 | 影响 | 缓解措施 |
|:-----|:-----|:---------|:-----|:---------|
| `to_params_dict()` 实现滞后 | **高** | 40% | 第一阶段卡住 | 优先级提升至最前；先用 meta JSON 降级方案 |
| 三个 `_persist_result()` 重复代码 | 中 | 80% | 维护成本 | 抽取公共 `KnowledgeDB.store_run()`，调用点各一行 |
| 回填缺少 `param_version` | 低 | 100% | 历史数据无版本 | 统一标记 `v0_backfill`，不影响新数据 |
| 衰减判定时机难度 | 中 | 30% | 误标 | 早期手动触发季度复核，不全自动 |
| SQLite 并发写入 | 中 | 20% | WAL + retry | 多进程场景用 WAL + busy_timeout |
| DB 文件从 0 字节初始化 | 低 | 5% | 第一次调用 \_persist_result 时自动建表 | `initialize()` 在 `KnowledgeDB.__init__()` 中懒加载 |

### 7.2 降级方案

若 `to_params_dict()` 暂时不可用：

```python
# 降级：使用 meta 字段直接作为 params_json
params_json = json.dumps({
    "param_version": "v0_degraded",
    "meta_dump": meta,  # 原始的 meta 字典
    "config_type": type(config).__name__,
}, ensure_ascii=False, default=str)
```

### 7.3 并发与性能

- **WAL 模式**：`PRAGMA journal_mode=WAL;` — 允许读操作与写操作不阻塞
- **busy_timeout**：`PRAGMA busy_timeout=3000;` — 等待 3 秒后抛出异常
- **单机使用**：当前为单进程回测，多进程场景未来按需优化

### 7.4 备份策略

```python
def backup(self, backup_dir: str = None) -> str:
    """
    备份 knowledge.db 到指定目录。
    使用 SQLite 的 backup API 实现热备份。
    """
    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(self.db_path), "db")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"knowledge_backup_{timestamp}.db")

    src_conn = sqlite3.connect(self.db_path)
    dst_conn = sqlite3.connect(backup_path)
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    return backup_path
```

---

## 附录 A：模块初始化示例

新建文件 `src/backtest/pipeline/knowledge_db.py` 的骨架（占位用）：

```python
"""
墨枢 (MoShu) — 回测知识库核心模块

在 mozhi_platform 中的位置：
 回测引擎 → _persist_result() → KnowledgeDB.store_run() → knowledge.db
 knowledge.db → aggregate_knowledge() → knowledge_entries
 knowledge_entries → KnowledgeExtractor → weekly_reference_{W}.yaml → 早报

三个原则：不替换只追加 / 可逆性 / 渐进实施

用法::

    from src.backtest.pipeline.knowledge_db import KnowledgeDB, make_run_id

    db = KnowledgeDB()
    db.initialize()  # 幂等建表

    run_id = db.store_run(
        strategy_type="grid",
        symbol="601857.SH",
        config=config,
        result=result,
        config_key="v1_params",
    )

Author: 墨衡
Created: 2026-05-16
Version: 1.0
"""

from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

VALID_INSIGHT_CATEGORIES = frozenset({
    "sharp_drop", "sharpe_reversal", "win_rate_drop",
    "high_conflict", "consecutive_loss", "drawdown_breach",
    "drawdown_recovery", "allocation_bias",
})
"""8 类预定义知识类别，与 KnowlegeExtractor 类别体系一致。"""

DDL_SCRIPT = """
-- 表结构见 §2.2（共六张表：backtest_runs, params_snapshot, market_context,
--       performance_results, knowledge_entries, knowledge_run_links）
"""

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # src/backtest/pipeline/
    "..", "..", "..", "data", "knowledge.db"
)
DEFAULT_DB_PATH = os.path.normpath(DEFAULT_DB_PATH)


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def make_run_id(
    strategy: str,
    symbol: str,
    config_key: str = "",
    tag: str = "",
) -> str:
    """
    统一 run_id 生成函数。
    格式：run_{strategy}_{symbol}_{config_key}_{tag}_{YYYYMMDD_HHMMSS}
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [strategy, symbol, config_key, tag, ts]
    return f"run_{'_'.join(p for p in parts if p)}"


# ═══════════════════════════════════════════════════════════════
# KnowledgeDB
# ═══════════════════════════════════════════════════════════════


class KnowledgeDB:
    """回测知识库数据库操作封装。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def initialize(self) -> None:
        """幂等建表。"""
        ...
```
