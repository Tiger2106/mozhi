# 墨枢 KnowledgeDB 测试报告

- **测试执行:** 墨萱 🔍
- **测试时间:** 2026-05-16 10:53 CST
- **测试版本:** 墨枢 v1.0

---

## 测试结果总览

| 测试项 | 级别 | 结果 |
|--------|------|------|
| P0 复审: `_persist_result()` → `KnowledgeDB()` | P0 | **PASS** |
| 1r: `to_params_dict()` 三个策略输出格式 | P1 | **PASS** |
| 1s: `store_run` + `get_run` + `list_runs` | P0 | **PASS** |
| 1t: 回填脚本 (`backfill_knowledge_db.py --dry-run`) | P1 | **PASS** |

**整体结论: TEST_RESULT = PASS** ✅ 无 P0 阻塞性问题。

---

## 任务 1 — P0 复审

### 检查内容

确认 `_persist_result()` 中 `_connect()` → `with KnowledgeDB() as kdb:` 修改正确。

### 检查结果

三个策略的 `_persist_result()` 均正确使用 `with KnowledgeDB() as kdb:`:

| 文件 | 行号 | 状态 |
|------|------|------|
| `src/backtest/strategies/run_grid.py` | L1070 | ✅ `with KnowledgeDB() as kdb:` |
| `src/backtest/strategies/run_trend.py` | L808 | ✅ `with KnowledgeDB() as kdb:` |
| `src/backtest/strategies/run_reversal.py` | L847 | ✅ `with KnowledgeDB() as kdb:` |

`KnowledgeDB` 类实现了完整的上下文管理器协议 (`__enter__` / `__exit__`)，自动管理连接生命周期。原 `_connect()` 方法已被 `_conn` 上下文管理器替代，封装在类内部。

**结论: PASS** ✅ — 修改正确，无残留 `_connect()` 调用。

---

## 任务 2 — 测试: 1r. to_params_dict()

### 测试项

1. **结构一致性**: 三个策略均输出 `capital/fee_rate/slippage/signal/position/meta` 6个顶层key
2. **完整参数**: 含完整参数时 `has_full_params=True`
3. **不完整参数**: 缺参数时 `has_full_params=False`
4. **Grid step_pct 推导**: 验证 arithmetic 网格步进百分比计算

### 测试详情

| 用例 | 断言 | 结果 |
|------|------|------|
| Grid 默认参数 | 6个顶层key | ✅ |
| Grid 默认参数 | `n_layers`, `step_pct`, `grid_type`, `position_*` 均存在 | ✅ |
| Grid 默认参数 | `has_full_params=False` (缺 stop_loss_pct) | ✅ |
| Grid 默认参数 | `step_pct=0.011696` (arithmetic: (105-95)/(10-1)/95) | ✅ |
| Trend 完整参数 (`signal_params` + `risk_params`) | `has_full_params=True` | ✅ |
| Trend 完整参数 | `ma_fast=5, ma_slow=20, signal_type=ma_cross` | ✅ |
| Trend 完整参数 | `stop_loss_pct=0.02` | ✅ |
| Trend 不完整参数 | `has_full_params=False`, `ma_fast=5`(降级) | ✅ |
| Reversal 完整参数 (`signal_params` + `risk_params`) | `has_full_params=True` | ✅ |
| Reversal 完整参数 | `lookback_period=14, oversold_threshold=30, overbought_threshold=70` | ✅ |
| Reversal 完整参数 | `stop_loss_pct=0.03` | ✅ |
| Reversal 不完整参数 | `has_full_params=False` | ✅ |

### 注意事项

- Reversal 的 `to_params_dict()` 从 `signal_params` 中读取的 key 是 `oversold`/`overbought`（非 `oversold_threshold`/`overbought_threshold`），输出时映射为 `oversold_threshold`/`overbought_threshold`
- Reversal 的 `risk_params` 中使用 `fixed_stop_pct`（非 `fixed_stop_loss`），需注意与实际业务流程一致

**结论: PASS** ✅

---

## 任务 2 — 测试: 1s. store_run + get_run + list_runs

### 测试项

1. `store_run()` 写入并返回 valid run_id
2. `get_run()` 查询返回完整记录
3. `list_runs()` 过滤查询工作正常
4. validity_grade 自动判定 A/B/C

### 测试详情

| 用例 | 输入 | 预期 | 实际 | 结果 |
|------|------|------|------|------|
| store_run(grid, 601857.SH) | params_json, metrics | valid run_id | `run_grid_601857.SH_test_...` | ✅ |
| get_run() | 刚写入的 run_id | strategy=grid, symbol=601857.SH | 一致 | ✅ |
| list_runs(strategy='grid') | limit=5 | ≥1条结果 | 2条结果，含刚写入的记录 | ✅ |
| A级验证 | data_days=60, sharpe=0.8, dd=5 | A | A | ✅ |
| B级验证 | data_days=30, sharpe=0.3 | B | B | ✅ |
| C级验证 | data_days=5, sharpe=0.0 | C | C | ✅ |

**结论: PASS** ✅ — 核心 CRUD + validity_grade 判定均正确。

---

## 任务 2 — 测试: 1t. 回填脚本

### 测试项

```bash
python scripts/backfill_knowledge_db.py --dry-run --source new --limit 5
```

### 测试详情

| 检查项 | 结果 |
|--------|------|
| Dry-Run 模式正常启动 | ✅ |
| 策略分布正确 | `grid: 5` |
| 来源分布正确 | `新平台=5, 旧库=0` |
| 无异常/错误输出 | ✅ |
| 数据库未被修改 (Dry-Run) | ✅ |

**结论: PASS** ✅ — 回填脚本 dry-run 正常，可安全运行实际回填。

---

## 发现的问题

### 非阻塞性发现（P2-3 级别，建议改进）

1. **Reversal `to_params_dict()` key 命名不一致**
   - 接口文档期望 `oversold_threshold`/`overbought_threshold`，但内部读取的是 `oversold`/`overbought`
   - 当前行为是 map `oversold` → `oversold_threshold`（输出），但调用方如果按接口文档的 key 名传参则无法解析
   - **建议**: 在 `signal_params` 中支持双名解析（`oversold` 或 `oversold_threshold`）

2. **Trend 与 Reversal `risk_params` key 不同**
   - Trend 使用 `fixed_stop_loss`
   - Reversal 使用 `fixed_stop_pct`
   - **建议**: 统一命名，或加别名解析

3. **Grid 的 `__post_init__` 覆盖 `signal=None`**
   - 即使显式传入 `signal=None`，`__post_init__` 会创建默认 `StaticGridSignal`
   - 当前不是问题（功能正常），但语义上 `None` 被覆盖可能造成困惑

---

*报告由墨萱 🔍 生成*
