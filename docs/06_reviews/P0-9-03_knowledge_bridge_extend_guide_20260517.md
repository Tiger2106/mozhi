<!--
  author: 墨衡（MoHeng）
  task_id: P0-9-risk (doc 3/5)
  created: 2026-05-17 20:19 +08:00
  status: READY
  source: risk_action_plan_moheng_20260517.md §P0-9
-->

# P0-#9-03: KnowledgeBridge 扩展指南（Plugin 开发者文档 3/5）

> **目标读者：** 下游开发者（墨萱、墨衡）
> **核心内容：** KnowledgeBridge 数据流、扩展点、新增数据源接入
> **前置依赖：** `docs/02_development/knowledge_db_design.md`（知识库总体设计）

---

## 1. 架构定位

KnowledgeBridge 是 MoZhi 平台的「知识旁挂」组件：
- **单向推送：** Runner → KnowledgeBridge.harvest() — Runner 不依赖 KB 返回
- **只读查询：** KnowledgeSearch / KnowledgeAnalyzer — 以 Bitable/本地文件为数据源
- **无共享状态：** KB 与 Runner 无共享数据库/文件表
- **耦合度承诺：** 0次接口调用依赖，0次修改导致Runner测试失败

### 数据流总图

```
MethodBacktestRunner.run()
       │
       ▼
KnowledgeBridge.harvest(result, method_name, symbol, config)
       │
       ├──→ KnowledgeNormalizer.normalize(MethodResult → KnowledgeEntry v2)
       │       └── 输出: knowledge_{method}_{symbol}_{timestamp}.json → data/knowledge_entries_v2/
       │
       ├──→ BitableSync.sync(KnowledgeEntry → Bitable 记录)
       │       └── 目标: Bitable 表 (KnowledgeEntry 记录)
       │
       └──→ (可选) AI分析触发
               └──→ KnowledgeAnalyzer.analyze() → 仪表盘数据
```

### 核心文件

| 文件 | 用途 | 位置 |
|------|------|------|
| `KnowledgeBridge` | 主入口（收割+同步） | `src/backtest/engine/knowledge_bridge.py` |
| `KnowledgeEntry v1` | 旧版知识条目 | `src/backtest/engine/knowledge_entry.py` |
| `KnowledgeEntry v2` | 新版知识条目（推荐） | `src/backtest/engine/knowledge_entry_v2.py`（或 `knowledge_entries_v2/` 目录） |
| `KnowledgeNormalizer` | MethodResult → KnowledgeEntry 转换 | `src/backtest/engine/knowledge_normalizer.py` |
| `BitableSync` | 飞书多维表格同步 | `src/backtest/engine/bitable_sync.py` |
| `KnowledgeSearch` | 知识搜索接口 | `src/backtest/engine/knowledge_search.py` |
| `KnowledgeAnalyzer` | 知识分析仪表盘 | `src/backtest/engine/knowledge_analyzer.py` |

---

## 2. 知识条目格式（KnowledgeEntry v2）

```json
// data/knowledge_entries_v2/knowledge_macd_601857_20260517144243.json
{
  "entry_type": "backtest_signal",
  "symbol": "601857",
  "method_name": "macd",
  "generated_at": "2026-05-17T14:42:43+08:00",

  "summary": {
    "n_bars": 120,
    "n_signals": 45,
    "signal_ratio": 0.375,
    "dominant_signal": 1
  },

  "config": {
    "fast_period": 12,
    "slow_period": 26,
    "signal_period": 9
  },

  "metrics": {
    "ma_fast_stats": {"mean": 100.5, "std": 5.2},
    "ma_slow_stats": {"mean": 99.8, "std": 4.9}
  },

  "extras": {}
}
```

---

## 3. 扩展点

### 3.1 扩展点 A: 新增 Normalizer

当需要将 MethodResult 转换为不同的知识条目格式时：

```python
# src/backtest/engine/normalizers/custom_normalizer.py

from backtest.methods.base import MethodResult
from backtest.engine.knowledge_entry import KnowledgeEntry


class CustomNormalizer:
    """自定义 Normalizer：将 MethodResult 转为自定义知识条目。"""

    def normalize(self, result: MethodResult, method_name: str, symbol: str) -> dict:
        """转换逻辑。

        Args:
            result: Runner 输出
            method_name: 方法名
            symbol: 标的代码

        Returns:
            dict: 符合 target Bitable schema 的条目。
        """
        return {
            "entry_type": "custom_signal",
            "symbol": symbol,
            "method_name": method_name,
            "generated_at": result.completed_time,
            "n_bars": result.n_bars,
            "n_signals": result.n_signals,
            "duration_ms": result.duration_ms,
        }


# 在 KnowledgeBridge 中注册
# bridge.register_normalizer("custom", CustomNormalizer())
```

### 3.2 扩展点 B: 新增数据源同步器

当需要将知识条目同步到非 Bitable 目标时：

```python
# src/backtest/engine/syncers/csv_syncer.py

from typing import List
from pathlib import Path
import pandas as pd


class CSVSyncer:
    """CSV 文件同步器：将知识条目追加到本地 CSV。"""

    def __init__(self, output_dir: str = "data/synced_csv"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def sync(self, entries: List[dict]) -> int:
        """同步条目到 CSV。

        Args:
            entries: 知识条目列表

        Returns:
            int: 成功同步的条目数
        """
        csv_path = self.output_dir / "knowledge_entries.csv"
        df = pd.DataFrame(entries)

        # 追加模式
        if csv_path.exists():
            existing = pd.read_csv(csv_path)
            df = pd.concat([existing, df], ignore_index=True)

        df.to_csv(csv_path, index=False)
        return len(entries)


# 在 KnowledgeBridge 中注册
# bridge.register_syncer("csv", CSVSyncer())
```

### 3.3 扩展点 C: 添加分析器

```python
# src/backtest/engine/analyzers/custom_analyzer.py

class CustomAnalyzer:
    """自定义分析器。"""

    def analyze(self, entries: List[dict]) -> dict:
        """分析知识条目，返回摘要。"""
        methods = set(e["method_name"] for e in entries)
        symbols = set(e["symbol"] for e in entries)
        return {
            "total_entries": len(entries),
            "unique_methods": list(methods),
            "unique_symbols": list(symbols),
        }
```

---

## 4. KnowledgeBridge 使用示例

```python
from backtest.engine.knowledge_bridge import KnowledgeBridge

# 基础使用
bridge = KnowledgeBridge(
    output_dir="data/knowledge_entries",
    sync_to_bitable=True,
)
bridge.harvest(
    result=method_result,
    method_name="ma_cross",
    symbol="601857",
    config={"ma_fast": 5, "ma_slow": 20},
)

# 关闭Bitable同步（仅写本地文件）
bridge = KnowledgeBridge(output_dir="data/knowledge_entries", sync_to_bitable=False)

# 指定输出目录
bridge = KnowledgeBridge(output_dir="/path/to/custom/output")

# 在 Runner 中启用
runner = MethodBacktestRunner("ma_cross", ctx, enable_knowledge_collection=True)
result = runner.run(df, symbol="601857", harvest=True)
# 或:
result = runner.run(df, symbol="601857", harvest=False)
# 手动触发:
bridge.harvest(result=result, method_name="ma_cross", symbol="601857", config=ctx.config)
```

---

## 5. 扩展点总览

| 扩展类型 | 接口 | 注册方式 | 示例 |
|---------|------|---------|------|
| **Normalizer** | `normalize(result, method, symbol) → dict` | `bridge.register_normalizer(name, obj)` | 自定义数据格式转换 |
| **Syncer** | `sync(entries) → int` | `bridge.register_syncer(name, obj)` | 同步到本地CSV/其他数据库 |
| **Analyzer** | `analyze(entries) → dict` | `bridge.register_analyzer(name, obj)` | 自定义知识分析仪表盘 |
| **Pre-filter** | `should_harvest(result) → bool` | `bridge.set_filter(func)` | 按条件过滤（如收益门槛） |
| **Post-process** | `after_harvest(entry, result) → None` | `bridge.set_post_hook(func)` | 通知/告警触发 |

---

## 6. 验证方式

```bash
# 1. 查看本地输出
ls data/knowledge_entries_v2/
# → knowledge_macd_601857_*.json

# 2. 检查Bitable记录
# 在飞书工作台打开 MoZhi-KB Bitable → KnowledgeEntry 表
# 确认对应记录存在

# 3. 运行E2E测试
python -m pytest tests/test_knowledge_bridge.py -v
python -m pytest tests/test_knowledge_bridge_v2.py -v

# 4. 运行Bitable集成测试
python scripts/e2e_bitable_sync.py
```

---

## 7. 依赖与阻塞

| 依赖 | 状态 | 说明 |
|------|:----:|------|
| KnowledgeEntry v2 基类 | ✅ 已完成 | `knowledge_entry_v2.py` |
| KnowledgeNormalizer | ✅ 已完成 | 含 `normalizer.py` |
| BitableSync | ✅ E2E通过 | `bitable_sync.py` + 飞书真实API |
| 飞书 App 权限 | ⏳ 待开通 | `bitable:bitable` 权限 |
| Bitable app_token | ⏳ 待创建 | 需权限开通后执行 |
| KnowledgeSearch | ⬜ 待创建 | Phase 2 |
| KnowledgeAnalyzer | ⬜ 待创建 | Phase 3 |

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 20:19 +08:00*
