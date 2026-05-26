# 三策略代码修复报告

- **Author**: 墨衡
- **Created**: 2026-05-16
- **Scope**: `run_trend.py`, `run_reversal.py`, `run_grid.py`
- **Fixes applied**: 4

---

## 1. SIGNALS_TASKS_DIR 路径问题

### 发现
三策略中均包含硬编码的 `"mo_zhi_sharereports"` 路径，位于 `_DEFAULT_DB` 定义：

```python
_DEFAULT_DB = os.path.join(
    os.environ.get("HOME") or os.environ.get("USERPROFILE") or "C:\\Users\\17699",
    "mo_zhi_sharereports",
    "analysis.db",
)
```

搜索全项目，不存在名为 `SIGNALS_TASKS_DIR` 的集中配置变量。`"mo_zhi_sharereports"` 字符串在 `src/` 下约 60+ 处出现。

### 判定：不修复
- `_DEFAULT_DB` 通过 `HOME`/`USERPROFILE` 环境变量实现了用户目录层的可配置性，仅有 `mo_zhi_sharereports` 部分硬编码
- 该路径为固定的共享数据目录，短期内不会变更
- 三策略无 `_connect()` 或 `_setup()` 方法，路径拼接仅在模块级常量中完成
- 按修复原则"只修复确定有问题的 Bug"，硬编码路径可工作，不是 Bug

### 建议（非修复）
未来引入项目级 `settings.py` 集中管理 `DATA_DIR` 和 `DB_PATH`，替换各模块的重复定义。

---

## 2. profit_factor 双键容错

### 发现
三策略在 `_persist_result()` 中向 `KnowledgeDB.store_run()` 传递 `profit_factor` 时，均只读取 `metrics["profit_loss_ratio"]`：

```python
"profit_factor": metrics.get("profit_loss_ratio", 0.0),   # 原代码
```

`BacktestResult.metrics` 由 `performance.py` 填充，始终使用 key `profit_loss_ratio`（无 `profit_factor` 分支）。

### 判定：修复 ✓
虽然当前运行时不存在 `profit_factor` 与其他 key 的冲突，但未来若有其他代码路径向 metrics 写入 `profit_factor` 而非 `profit_loss_ratio`，`metrics.get("profit_loss_ratio", 0.0)` 会静默返回 0.0。

按任务要求增加双键容错：先查 `profit_factor`，失败再查 `profit_loss_ratio`，确保不因字段名别名导致 key 不存在。

### 改动
**三文件中 `.get("profit_loss_ratio", 0.0)` → `metrics.get("profit_factor") or metrics.get("profit_loss_ratio", 0.0)`**

| 文件 | 行号 | BUGFIX 注释 |
|:----:|:----:|:-----------|
| `run_trend.py` | 831 | `double-key tolerance for profit_factor/profit_loss_ratio` |
| `run_reversal.py` | 870 | `double-key tolerance for profit_factor/profit_loss_ratio` |
| `run_grid.py` | 1092 | `double-key tolerance for profit_factor/profit_loss_ratio` |

---

## 3. config_key 一致性

### 发现
三策略向 `KnowledgeDB.store_run()` 传递的 `config_key` 格式不一致：

| 文件 | config_key 值 | 示例 |
|:----:|:-------------|:-----|
| `run_trend.py` | `f"{signal_type}_{pos_mode}_{tag}"` | `ma_fixed_default` |
| `run_reversal.py` | `config.signal_type` | `rsi` ❌ |
| `run_grid.py` | `_build_config_key(...)` | `static_n10_arithmetic_fixed_cd3` |

**`run_reversal.py` 仅传递 `signal_type`（如 "rsi"），丢失了 `position_mode` 和 `tag` 信息**。这会导致 KnowledgeDB 中不同仓位模式的同一信号类型回测配置被写为相同的 `config_key`，无法区分。

### 判定：修复 ✓
将 `run_reversal.py` 的 `config_key` 统一为 `run_trend.py` 使用的格式，确保三策略的 `config_key` 构建逻辑一致。

### 改动
**`run_reversal.py:851` — `config_key=config.signal_type` → `config_key=f"{config.signal_type}_{config.position_mode}_{config.tag}"`**

---

## 4. set_cron_job / cron / scheduler 相关

### 发现
在三策略文件中搜索 `set_cron_job`、`cron`、`scheduler`，均无匹配项。三文件为纯回测运行器：
- 以 `if __name__ == "__main__"` 提供 CLI 直接运行
- 以公开函数（`run_trend_backtest` / `run_reversal_backtest` / `run_grid_backtest`）供外部导入调用

不包含任何定时调度或 cron 相关代码。

### 判定：不修复
无相关代码，无需操作。

---

## 改动汇总

| # | 类型 | 文件 | 行 | 描述 |
|:-:|:----:|:----:|:-:|:----|
| 1 | 🐛 Bug fix | `run_reversal.py` | 851 | config_key 从 `config.signal_type` 修正为 `f"{signal_type}_{pos_mode}_{tag}"` |
| 2 | 🛡️ 加固 | `run_trend.py` | 830-831 | profit_factor 双键容错（`profit_factor` → `profit_loss_ratio` fallback） |
| 3 | 🛡️ 加固 | `run_reversal.py` | 870-871 | profit_factor 双键容错 |
| 4 | 🛡️ 加固 | `run_grid.py` | 1091-1092 | profit_factor 双键容错 |

所有修复均添加了 `# BUGFIX: 2026-05-16: {reason}` 注释。
