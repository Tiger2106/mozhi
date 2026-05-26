# 墨萱复审：Report Generator 修复后验收

> **复审人**: 墨萱 🔍  
> **日期**: 2026-05-16  
> **复审轮次**: 第 2 轮（修复后验收）  
> **复审对象**: 5 个新文件/修改  
>   1. `src/backtest/data_source.py` — DAO 层扩展  
>   2. `src/backtest/pipeline/report_adapter.py` — 适配器（P1-P4 修复）  
>   3. `src/backtest/pipeline/async_pdf_task.py` — 异步 PDF 生成  
>   4. `scripts/migrate_backtest_code_field.py` — 数据库迁移脚本  
>   5. `src/morning_pipeline/scheduler_agent.py` — Step4.5 集成  

---

## 0. 复审结论

**❌ 不通过（CONDITIONAL — 3 项条件满足后重审）**

| 分类 | 项数 | 通过 | 条件通过 | 不通过 |
|------|------|------|---------|--------|
| 原问题修复（P1-P4） | 4 | 3 | 1 | 0 |
| 架构问题（P5-P6） | 2 | 0 | 1 | 1 |
| 新引入问题 | 6 | 4 | 0 | 2 |
| **合计** | **12** | **7** | **2** | **3** |

---

## 1. 原问题修复检查（P1-P4）

### ✅ P1：标的代码硬编码 → **已修复**

`report_adapter.py:52-54`:
```python
resolved_code = code or self.default_code
```
适配器 `load()` 方法接受 `code` 参数，上层管线传入具体标的代码。`_adapt_row` 进一步从 `row["code"]` 或 `strategy_name` 正则提取回退。

**DAO 层** `data_source.py` 的 `get_backtest_results` 也使用 `code` 参数进行 WHERE 筛选。

**结论**: ✅ P1 关闭。从硬编码 601857 变为参数化 + 策略名反解析。

### ✅ P2：日期范围不匹配 → **已修复**

`report_adapter.py:61-62`:
```python
resolved_start, resolved_end = self._resolve_date_range(start_date, end_date)
```
缺省日期通过 `_resolve_date_range` 推算最近 180 天，而非固定 `LIMIT 85`。DAO 层 `get_backtest_results` 和 `get_stock_prices` 均按 `start_date >= ? AND end_date <= ?` 精确查询。

**结论**: ✅ P2 关闭。不再有 fixed LIMIT 85 问题。

### ✅ P3：空净值除零 → **已修复**

`report_adapter.py:34-44`:
```python
def _safe_first_nav(nav: List[float], default: float = 1_000_000.0) -> float:
    if not nav:
        return default
    return nav[0]
```
空列表保护 + `_load_nav_series` 降级逻辑（fallback 到收盘价序列 + 归一化）已实现。

**结论**: ✅ P3 关闭。空列表、除零均安全。

### 🟡 P4：total_trades NULL → **条件修复**

`report_adapter.py:107-109`:
```python
total_trades = row.get("total_trades")
if total_trades is None:
    total_trades = 0  # COALESCE
```

`calc_t1_grade` 也做了适配:
```python
if total_trades <= 0:
    return "D"
```

**但是**：数据库 `backtest_results` 表中 `total_trades` 的 `nullable` 属性为 **True**（见 DB PRAGMA 结果: `nullable=True`），且 `default=None`。这意味着新插入的记录如果不显式写入 `total_trades` 值，始终会存为 NULL。

**DAO 层** `data_source.py` 的 `get_backtest_results` 仅执行 SELECT，未做 COALESCE 。COALESCE 只在 Python 侧适配器中做。这有一个时序隐患：当适配器被其他调用方（后续版本）直接使用 DAO 层返回值而非适配器时，NULL 问题会再次出现。

**建议**: 在 DAO 层 `get_backtest_results` 的 SQL 中直接 `SELECT *, COALESCE(total_trades, 0) AS total_trades`，双重保障。

**结论**: 🟡 P4 条件通过（当前行为正确，但建议在 DAO 层也加 COALESCE 做持久化保护）。

---

## 2. 架构问题检查（P5-P6）

### 🟡 P5：DAO 竖井 → **条件修复**

`report_adapter.py:16`:
```python
from backtest.data_source import get_backtest_results, get_stock_prices
```

适配器确实调用了 DAO 层函数，不再直接写裸 SQL。✅

**但** `_query_equity_series`（`report_adapter.py:182-197`）**仍然在执行裸 SQL**：
```python
def _query_equity_series(result_id: int) -> List[float]:
    import sqlite3
    from src.config import ANALYSIS_DB
    db_path = ANALYSIS_DB
    ...
    cur = conn.execute(
        "SELECT equity FROM backtest_equity_series "
        "WHERE result_id = ? ORDER BY date ASC",
        (result_id,),
    )
```

这是适配器中的一个独立函数，没有封装到 `data_source.py` 中。虽然只是简单查询，但违背了"所有 DB 访问统一走 DAO 层"的架构约定。

**建议**: 将 `_query_equity_series` 的查询逻辑迁移到 `data_source.py` 中作为新的 DAO 方法（如 `get_equity_series(result_id)`），适配器改为调用 `get_equity_series`。

**结论**: 🟡 P5 条件通过（当前不破坏功能，但架构不统一，建议下轮迭代迁移）。

### ❌ P6：缺 code 字段 → **未通过（迁移脚本未运行）**

**迁移脚本** `migrate_backtest_code_field.py` 代码逻辑正确：
- `ALTER TABLE ADD COLUMN code TEXT` ✅
- 三策略反解析（strategy_name → parameters → 默认值）✅
- 已迁移/已存在的 SKIP 检测 ✅

**但** 在目标数据库中执行 `PRAGMA table_info(backtest_results)` 的结果显示：**`code` 字段不存在**。

```
Columns in backtest_results:
  annual_return, created_at, end_date, final_value, id, initial_capital, 
  max_drawdown, parameters, sharpe_ratio, start_date, strategy_name, 
  total_return, total_trades, win_rate
  ❌ code 字段不存在
```

这意味着：
1. 迁移脚本**尚未执行**
2. 适配器中 `row.get("code")` 始终返回 `None`
3. 代码解析完全依赖 `strategy_name` 正则，这在字段缺失时脆弱

虽然有 fallback（`_extract_code` / `_KNOWN_CODES`），但依赖硬编码映射字典本身就是架构问题——原 P6 的本意就是彻底解决这个问题。

**修复要求**: **必须**执行迁移脚本，并在确认 `code` 字段存在且数据填充后，适配器才能上线。不执行迁移脚本，此架构修复不完整。

**结论**: ❌ P6 不通过。迁移脚本代码正确但未执行，不能视为 P6 已完成。

---

## 3. 新引入问题检查

### 3.1 适配器逻辑

#### ✅ `_safe_first_nav` / `_safe_last_nav` 设计合理

两个函数清晰解耦，默认值 `1_000_000.0` 合理。被 `_adapt_row` 正确调用。

#### ✅ `_extract_code` 正则回退工作

从 `strategy_name` 中扫描 `\d{6}` 模式，配合 `_KNOWN_CODES` 白名单，在 `code` 字段缺失时可作为 fallback。

#### ❌ `_load_nav_series` 中的隐式除零风险（新问题）

`report_adapter.py:156-161`:
```python
if prices:
    base = prices[0] if prices else 1.0
    if base > 0:
        return [p / base * 1_000_000.0 for p in prices]
```
当 `base = 0`（理论上可能出现在极端崩盘场景，虽然概率极低），则返回空列表 `[]` → 上游 `_safe_first_nav` 会返回默认值，**但**空列表导致 `total_return` 计算无法进行。

**虽然安全函数已保护除零，但降级返回空列表意味着适配器永远不会包含行情基准数据，`total_return` 以 DB 字段为准不受影响**。风险等级：低。

**结论**: ✅ 非必须修复，已由上游安全函数兜底。可作为观察点。

#### ✅ `_adapt_row` 异常隔离正确

`report_adapter.py:96-98`:
```python
except Exception as e:
    logger.error(f"[adapter] 适配记录失败: id={row.get('id')}, error={e}")
    return None
```
单行失败不影响其他行，日志清晰。✅

---

### 3.2 异步 PDF 进程管理

#### ✅ 线程模型安全

`async_pdf_task.py:177-185`:
```python
thread = threading.Thread(target=_worker, daemon=True, name="AsyncPDF")
thread.start()
```
`daemon=True` 保证主线程退出时守护线程自动终止，不会出现孤儿进程。

#### ✅ Edge 路径检测健壮

`_EDGE_CANDIDATES` 覆盖 PATH + 3 个常见安装路径，同时实现 `where` 命令查找。Windows 上无明显遗漏。

#### ✅ 文件名防碰撞机制（P8）

`_safe_pdf_path` 使用微秒级时间戳 + 重试。极端冲突降级到随机数。设计充分。

#### ✅ 超时保护（P9）

`subprocess.run(..., timeout=timeout_seconds)` + `subprocess.TimeoutExpired` 捕获。默认 60s，命令行参数可配置。

#### ❌ 迁移脚本回滚方案缺失

`migrate_backtest_code_field.py` 没有提供 `--rollback` 或相似的回滚机制。SQLite 的 `ALTER TABLE ADD COLUMN` 不可逆（不支持 `DROP COLUMN` 除非重建表）。如果迁移后发现字段填入错误，手动恢复较困难。

**建议**: 提供一个 `--revert` 模式，通过 `CREATE TABLE backtest_results_new ... SELECT` 重建表去掉 `code` 列。或者至少文档化手动回滚步骤。

**结论**: ❌ 需要补充回滚方案。

---

### 3.3 Step4.5 集成逻辑

#### ✅ `_run_step4_5` 30s 硬超时正确

符合 P9 要求。超过 30s 截断转换，不影响管线继续。

#### ✅ PDF 异步不阻塞主流程

`generate_pdf_async` 通过 `daemon=True` 线程后台执行，callback 回调日志记录。即使失败也只打 WARNING 级别日志。

#### ❌ `generate_pdf` 中 `--print-to-pdf` 参数在 Windows 上的路径格式问题

`async_pdf_task.py:124`:
```python
f"file:///{abs_html.replace(os.sep, '/').lstrip('/')}",
```

这段将绝对路径 `C:\Users\...\report.html` → `file:///C:/Users/.../report.html`。

但 `.lstrip('/')` 会**把 `C:` 前面的 `/` 去除**，但在有盘符的路径上，实际上 `abs_html.replace(os.sep, '/')` 的结果是 `C:/Users/...`。这变成 `file:///C:/Users/...`——**恰好是正确的格式**（因为 `lstrip('/')` 对纯以 `/` 开头的路径有用，而 Windows 盘符路径不以 `/` 开头）。让我确认一下：

```python
abs_html = r"C:\Users\17699\report.html"
abs_html.replace(os.sep, '/')  # → "C:/Users/17699/report.html"
.lstrip('/')                    # → "C:/Users/17699/report.html" (无变化)
```

✅ **实际上正确**。但如果意外得到一个 POSIX 风格路径（Linux 开发环境），则 `.lstrip('/')` 会破坏。在当前 Windows-only 环境不是问题。

**结论**: ✅ 当前平台正确。留作未来跨平台注意事项。

#### ✅ 产出验证 `_validate_step_output` 一致

`scheduler_agent.py` 中 `_validate_single_file` 检查文件存在 + 非空 + JSON 可解析。与 Step4.5 的输出 `.html` 和 `.pdf` 的校验方式匹配。

---

## 4. 发现的新问题汇总

### ❌ 必须修复（Gate 条件，本轮复审条件）

| # | 问题 | 文件 | 严重度 |
|---|------|------|--------|
| N1 | **迁移脚本未执行** — `code` 字段在 analysis.db 中不存在，P6 架构修复未完成 | `scripts/migrate_backtest_code_field.py` | 🔴 Gate |
| N2 | **迁移脚本缺回滚方案** — ALTER TABLE ADD COLUMN 不可逆，无 --rollback | `scripts/migrate_backtest_code_field.py` | 🟡 Gate |
| N3 | `_query_equity_series` 裸 SQL — 未走 DAO 层，P5 修复不完整 | `report_adapter.py:182-197` | 🟡 Recommend |
| N4 | **DAO 层未做 COALESCE** — 建议在 `data_source.py` 的 SQL 中加 `COALESCE(total_trades, 0)` 做双重保障 | `data_source.py` | 🟢 P2 |

### 🟢 观察项（不需修复，注意）

| # | 观察 | 说明 |
|---|------|------|
| O1 | `_load_nav_series` 的 `prices[0]` 为零时返回空列表 | 已由安全函数兜底 |
| O2 | `generate_pdf` 中 `file:///` 路径格式 `.lstrip('/')` 在 POSIX 环境可能出问题 | Windows-only 暂安全 |
| O3 | `async_pdf_task.py` Edge 路径硬编码 | 已有 `_find_edge` 自动检测，可接受 |

---

## 5. 复审结论

### 分类评估

| 维度 | 分数 | 评估 |
|------|------|------|
| 代码质量 | 🟡 | 适配器结构清晰，DAO 层设计合理 |
| 修复彻底度 | 🟡 | P1-P4 修复到位，P5 有一条裸 SQL 遗漏，P6 脚本未执行 |
| 安全健壮性 | 🟢 | 边界情况覆盖（空列表、NULL、超时、除零）全面 |
| 文档完整性 | 🟢 | 代码注释充分，docstring 完整 |

### 复审结论

**❌ 不通过（Conditional）**

三项 Gate 条件必须满足后重审：
1. **执行迁移脚本** — 在 production 的 analysis.db 上运行 `python scripts/migrate_backtest_code_field.py`
2. **补充迁移回滚方案** — 在迁移脚本中增加 `--revert` 模式或文档化手动回滚步骤
3. **迁移 `_query_equity_series` 到 DAO 层** — 将裸 SQL 查询封装到 `data_source.py` 中

### 建议执行顺序

1. 🔴 **P0**: 执行迁移脚本 + 验证 `code` 字段填充
2. 🟡 **P1**: 补充回滚方案
3. 🟡 **P1**: 迁移 `_query_equity_series` 到 DAO 层
4. 🟢 **P2**: DAO 层 SQL 增加 `COALESCE(total_trades, 0)`（可选增强）
5. 上述 3 项完成后 → 重审：自动升级为 PASS

---

*复审人：墨萱 🔍 · 2026-05-16*
