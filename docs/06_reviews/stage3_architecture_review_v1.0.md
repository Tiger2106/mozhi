<!--
author: 玄知 (xuanzhi)
created_time: 2026-05-27T18:30+08:00
task_id: BT-XXX
version: v1.0
status: FINAL
-->

# Stage 3 架构技术把关报告

**审核人**: 玄知（宏观市场分析师 / 数据+架构会签）
**审核日期**: 2026-05-27 18:30 CST
**版本**: v1.0
**审核对象**: `src/backtest/engine/` (墨衡 Stage 1 三层分离实现)

---

## 1. 数据一致性检查

### 1.1 数据合约完整性

| 检查项 | 结果 | 说明 |
|:-------|:-----|:------|
| BacktestBar 字段完整性 | ✅ | 含 symbol, date, open/high/low/close, volume, amount, adj_factor, data_source, version |
| BacktestBar.validate() 校验 | ✅ | open>0, high≥max(open,close), low≤min(open,close), close>0, volume≥0, amount≥0, adj_factor>0 |
| BacktestData 字段完整性 | ✅ | 含 symbol, bars[], date_range, total_bars, data_fingerprint, contract_version |
| 缺失值处理 (MissingValuePolicy) | ✅ | FORWARD_FILL_MAX_DAYS=5, VOLUME_ZERO_FILL, REQUIRED_FIELDS |
| 时间升序校验 (TimeAlignmentGuard) | ✅ | check_bars_ascending() 在 data_layer.load() 中被调用 |

### 1.2 ⚠️ 数据指纹算法不匹配（Doc vs Code）

发现 **数据合约文档与代码实现之间的重大不一致**：

| 维度 | 文档 `BacktestData_contract_v1.0.md` (§六) | 代码 `contracts/backtest_data_contract.py` |
|:-----|:------------------------------------------|:-----------------------------------------|
| 指纹输入 | ndarray: `close.round(4).tolist()`, `volume.astype(int).tolist()`, `trading_dates`, `symbols` | bars list: `{date, close, volume, open, high, low}` for each bar |
| 序列化按键 | `sort_keys=True` | `sort_keys=True` |
| 输出长度 | 16 hex chars | 16 hex chars |

**问题**：两个算法是完全不同的实现，对同一份原始数据会产生不同的指纹。当未来扩展多标的回测（n_stocks > 1）时，文档定义的 ndarray 算法是唯一正确的形式（因为 ndarray 是多维矩阵），而当前的 bars-list 算法无法扩展。

**影响评估**：当前单标的 MA 交叉回测（601857.SH）不受影响，因为指纹仅用于标签。但这是一个 **维护隐患**。

### 1.3 ⚠️ verify_fingerprint() 在流水线中从未被调用

```
engine.py 执行流:
  DataLayer.load() → 计算指纹并存储 → data_fingerprint 静态标签
  → ❌ 从未调用 data.verify_fingerprint() 做完整性验证
  
DataLayer.verify_data_fingerprint() 作为 static method 存在但无人调用
```

指纹在 load 时计算后存储，但下游从未验证指纹是否被篡改或数据链路是否完整。

### 1.4 数据管道一致性

| 检查项 | 结果 | 说明 |
|:-------|:-----|:------|
| 数据源 | ✅ | `market_data.db.stock_daily` (使用 trade_date/ts_code 列) |
| 数据行数 | ✅ | 1540 bars（与基线一致） |
| 日期范围 | ✅ | 20200102 → 20260515（与基线一致） |
| 基线指纹 | ⚠️ | 基线 `92ca7e9b569875fc` vs 新引擎（算法不同，无法直接对比指纹） |
| DB schema 兼容 | ⚠️ | 文档已记录 data_ingestion/data_contract.py 与 data_loader.py 的 schema 差异 |

---

## 2. 架构合规结论

### 2.1 三层分离架构（BT-001）✅

| 模块 | 路径 | 职责 | 状态 |
|:-----|:-----|:-----|:-----|
| **DataLayer** | `engine/data_layer/` | 一次性加载 + 校验 + 指纹 | ✅ |
| **ComputeLayer** | `engine/calc_layer/` | 信号计算 (MA交叉) | ✅ |
| **SimulateLayer** | `engine/sim_layer/` | 约束叠加 + 模拟交易 + 审计 | ✅ |
| **Engine** | `engine/engine.py` | 三层编排入口 | ✅ |

### 2.2 各模块详细检查

#### DataLayer (`data_layer/`)

| 检查项 | 结果 |
|:-------|:-----|
| loader.py — DataLayer.load() 一次性加载 (GP-001) | ✅ 双重加载保护 (RuntimeError) |
| loader.py — SQL 列名一致 | ✅ `trade_date` + `ts_code` 列 |
| loader.py — BacktestBar 转换 + validate() | ✅ 字段级校验 |
| contract.py — 正确重导出 | ✅ 从 `contracts/backtest_data_contract` 再导出 |
| guard.py — LookaheadRuntimeGuard | ✅ TimeAlignmentGuard + LookaheadGuard 双重检测 |
| guard.check() 在 engine.py 正确调用 | ✅ Step1→Step2 之间注入 |

#### ComputeLayer (`calc_layer/`)

| 检查项 | 结果 |
|:-------|:-----|
| signals.py — compute() 一站式接口 | ✅ |
| signals.py — Signal 标准协议 (BT-003) | ✅ direction/confidence/bar_index/bar_date |
| signals.py — Strategy 抽象基类 | ✅ on_bar() 接口 + on_start/on_end |
| MaCrossoverStrategy — GP-002 零新分配 | ✅ 固定大小列表 |
| ComputeEngine — GP-004 种子 seed=42 | ✅ compute_layer.py `np.random.seed(self._seed)` |

#### SimulateLayer (`sim_layer/`)

| 检查项 | 结果 |
|:-------|:-----|
| simulator.py — simulate() 一站式接口 | ✅ |
| simulator.py — ConstraintAwareExecutor | ✅ 继承自 layers.simulate_layer |
| simulator.py — P0标记列表 | ✅ SimulateResult.p0_fixes_applied |
| constraints.py — ConstraintManager (BT-008) | ✅ 停牌 > 涨停/跌停 > T+1 |
| constraints.py — 约束常量 | ✅ LIMIT_UP_RATIO_MAIN=0.10, GEM=0.20, ST=0.05 |
| logger.py — TradeLogger (BT-005) | ✅ JSON Lines 审计日志 + summary() |

### 2.3 ⚠️ 约束逻辑弃用状态（已解决但需加运行时标记）

比 Stage 2 时的 review 更深入查证：

- `layers/simulate_layer.py` 中的 `ConstraintAwareExecutor` 已在文档中标记为 `DEPRECATED`
- 新 `engine/sim_layer/constraints.py` 的 `ConstraintManager` 是唯一活跃实现
- **但弃用标记仅为注释文字，无 `DeprecationWarning` 运行时警告**

建议：在 `layers/simulate_layer.py.ConstraintAwareExecutor` 的 `execute_signals()` 入口处加一行 `import warnings; warnings.warn(DeprecationWarning(...))`。

### 2.4 ⚠️ 审计日志路径与项目根不一致

```python
# logger.py 中的路径解析
_AUDIT_DIR = Path(__file__).resolve().parent.parent.parent / "audit"
# 解析结果: C:\Users\17699\mozhi_platform\src\backtest\audit\
# 而非:        C:\Users\17699\mozhi_platform\audit\
```

审计日志写入 `src/backtest/audit/` 而非项目根 `audit/`。当前 `src/backtest/audit/` 目录不存在，`project_root/audit/` 目录存在但为空。

如果 `_AUDIT_DIR.mkdir(parents=True, exist_ok=True)` 已执行，日志会写入到预期路径；但与其他工具约定的审计目录（`project_root/audit/`）不一致。

### 2.5 P0 修复状态

| 修复 | 位置 | 状态 |
|:-----|:-----|:-----|
| P0-FIX-001: T+1 延迟 | `constraints.py.check_t1()` + 挂单队列 | ✅ 完整集成 |
| P0-FIX-002: 前视偏差 | `guard.py.LookaheadRuntimeGuard` | ✅ 完整集成 |
| P0-FIX-003: 分红对齐 | `simulator.py` TODO(P1) | ⚠️ 框架预留 |

---

## 3. 回归对比确认

### 3.1 结果确认（引用 Stage 2 结论）

| 指标 | 基线 | 当前 | 差异 |
|:-----|:-----|:-----|:-----|
| 总收益率 | 20.3278% | 19.5103% | 0.8175pp (1%容差内 ✅) |
| 总交易次数 | 86 | 86 | 0 ✅ |
| 首日 NAV | 1,000,000 | 1,000,000 | 0 ✅ |
| 种子 seed | 42 | 42 | 0 ✅ |
| 数据行数 | 1540 | 1540 | 0 ✅ |

### 3.2 对比方法学验证

| 检查项 | 结果 | 说明 |
|:-------|:-----|:------|
| 基线可比性 | ✅ | 策略参数一致 (MA5/20, position_ratio=0.3, stop_loss=0.05) |
| 费用参数一致 | ✅ | fee_rate=0.0003, slippage_rate=0.001, min_fee=5.0 |
| 初始资金一致 | ✅ | ¥1,000,000 |
| 标的代码一致 | ✅ | 601857.SH |
| P0修复预期偏差 | ✅ | 0.82%偏差成因明确 (T+1延迟 + 前视偏差) — 行为更精确 |
| 容差逻辑合理 | ✅ | 1% 绝对容差 (非相对) 适用于收益回测 |

**回归对比总体结论：✅ 确认有效**

---

## 4. 总体判定

### ✅ 有条件通过 (Conditional Pass)

Stage 3 技术把关基于以下维度给出 **有条件通过**：

| 维度 | 判定 | 理由 |
|:-----|:-----|:-----|
| 架构合理性 | ✅ | 三层分离清晰，接口正交，engine.py 一站式编排正确 |
| 数据一致性 | ⚠️ | 指纹算法 Doc vs Code 不一致 + verify 未调用 |
| 复现性验证 | ✅ | 种子固定 seed=42，确定性信号 ID，layers/compute_layer 内 np.random.seed() |
| P0修复完整性 | ✅ | FIX-001/002 完整集成，FIX-003 框架预留 |
| 回归对比 | ✅ | Stage 2 验证 0.8175pp 偏差在 1% 容差内 |

### 4.1 修正条件（墨衡整改 → 直接进 Stage 2 增量回归）

以下 3 项条件需在 v1.1 之前完成修复（不计入退回次数，不阻塞 v1.0 发布）：

1. **【建议】指纹算法统一**
   - 文档 `BacktestData_contract_v1.0.md` §六 与代码 `contracts/backtest_data_contract.py` 的 `compute_fingerprint()` 算法保持完全一致
   - 推荐以 ndarray 算法为准（可扩展多标的），更新代码实现
   - 参考基线指纹 `92ca7e9b569875fc` 进行交叉验证

2. **【建议】集成 verify_fingerprint() 到流水线**
   - 在 `engine.py.run_backtest()` 的 Guard 步骤之后添加 `data.verify_fingerprint()` 调用
   - 验证失败则抛出警告（WARN），不阻止回测继续

3. **【建议】加运行时弃用标记**
   - `layers/simulate_layer.py.ConstraintAwareExecutor` 入口加 `DeprecationWarning`

### 4.2 低优先级改进（P1/P2）

| 项目 | 优先级 | 建议 |
|:-----|:-------|:-----|
| 审计日志路径统一 | P2 | logger.py `_AUDIT_DIR` 改为指向 `project_root/audit/` |
| P0-FIX-003 分红对齐 | P1 | 已带 TODO(P1)，按计划推进 |

---

## 5. 会签记录

| 角色 | 签章 | 方向 | 结论 |
|:-----|:-----|:-----|:-----|
| 墨萱 (QA) | ✅ | 技术评审 | 通过 (+3条建议已处理) |
| **玄知 (架构)** | ✅ | **架构+数据一致性** | **有条件通过** |
| 墨涵 (Hub) | 🕐 | 知识审查 | 待签 |

**玄知签章** · 2026-05-27 18:30 CST
