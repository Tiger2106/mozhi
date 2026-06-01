<!--
author: 墨衡 (moheng)
created_time: 2026-05-27T15:05+08:00
task_id: backtest_coding_principles_discussion
version: v1.0
-->

# 回测编码原则讨论稿

> **议题提出者**: 墨芷
> **分析人**: 墨衡 (moheng)
> **用途**: 确立编码原则，指导 P0/P1 修复及后续所有回测引擎开发
> **背景**: 纯 Python 逐日循环，10只×10年约7秒，标的/约束增多后耗时线性增长

---

## 一、计算效率：避免慢代码

### 1.1 区分"计算瓶颈"与"IO瓶颈"

逐日循环慢，根本原因不是 Python 循环本身，而是**在循环体内部做了不该做的事**。

**原则 P-C1：三层分离架构**

```
数据层（Data Layer）── 只做 I/O：一次读入，向量化缓存
  ↓
计算层（Calc Layer）── 向量化/NumPy：批处理所有标的、所有日期
  ↓
模拟层（Sim Layer）── 逐日循环：仅纯逻辑判断，无 I/O 无 NumPy 构造
```

**当前问题**: 模拟层和计算层混在一起——每日循环里既做信号计算（该向量化），又做约束检查（该逻辑判断）。二者耦合导致每步的性能都浪费。

**具体建议**:
- 信号计算 → 全部在 `calc/` 模块中向量化完成，输出完整矩阵 `(n_stocks × n_days)`
- 模拟层只读这个矩阵的当日切片，不做任何数值计算
- 约束检查（T+1、涨跌停、停牌）→ 预计算为布尔矩阵，模拟层直接索引

**得益**: 当前耗时集中在信号计算（`calc_vol_rsi_std` 等），这些如果移到 `calc/` 用 NumPy 向量化，10只标的时间可降数个数量级。模拟层则几乎固定时间（与标的数弱相关）。

**反模式（不要做）**:
```python
# ❌ 不好：每日循环内每次重新读取数据
for date in dates:
    for ticker in portfolio:
        data = load_data(ticker, date)  # 严重慢
        signal = compute_signal(data, lookback=60)
        trade(signal)

# ✅ 好：数据预加载 → 向量化信号矩阵 → 循环索引
data_mat = load_all_data()              # 一次 I/O
signal_mat = compute_all_signals(data_mat)  # 向量化
for di, date in enumerate(dates):
    for symbol in positions:
        execute(signal_mat[symbol_index, di])
```

### 1.2 向量化优先，循环次之

**原则 P-C2：能用 NumPy/SciPy 批量计算的，绝不用 Python 逐行循环。**

优先级排序:
1. **NumPy 向量化** — 矩阵运算、广播、`np.where`
2. **NumPy 逐元素** — `ufunc` 如 `np.add.reduce`
3. **Python 逐元素** — `for i in range(...)`（极度不推荐）

**当前问题举例**:
- `calc_vol_rsi_std` 用 Python 循环算日频 RSI——RSI 完全可以用 `numpy` 的 `rolling window` + `vectorized_ema` 实现
- 涨跌停价计算中，每个标的每日的涨跌停价是纯算数——直接向量化矩阵

**量化预期**: 信号计算部分向量化后，10标的时间从 7 秒降到 <0.5 秒。模拟层(纯逻辑)是瓶颈之前，不需要多线程/并行。

### 1.3 避免N+1查询和数据热加载

**原则 P-C3：数据读取一次性，格式使用连续内存布局（ndarray）。**

- `adj_factor`、`close`、`volume` 等列在 `load_stock_data` 时就组织成 `np.ndarray`，且按 `(n_days, n_stocks)` 连续布局
- 约束模拟所需的所有数据字段（涨跌停价、停牌标记、成交量）在同一轮加载中一次性拉取
- 禁止在模拟循环中二次查询数据库或重新计算

### 1.4 禁止热更新依赖

**原则 P-C4：循环内不创建新数组/对象。**

Python 循环慢的另一个隐藏因素——每日循环内 `np.array()` 或 `dict` 的创建累积 GC 开销。

**反模式**:
```python
for di, date in enumerate(dates):
    daily_prices = np.array([sd["close"][di] for sd in stock_data.values()])
    # 每次创建新数组 → GC 压力
```

**应做**:
```python
# 预分配
price_matrix = np.zeros((n_days, n_stocks))
for si, sd in enumerate(stock_data.values()):
    price_matrix[:, si] = sd["close"]
# 循环中直接索引
for di in range(n_days):
    today_prices = price_matrix[di]  # 视图，非新对象
```

---

## 二、模块复用性：怎么写才能让 EXP-004 直接用

### 2.1 信号计算 → 中间产物 → 交易执行，三模块正交

**原则 P-R1：信号模块不感知回测引擎，回测引擎不感知信号来源。**

当前状态:
```
run_portfolio_backtest() {
    compute_signal_vector()     ← 信号计算耦合在回测函数内
    run_portfolio_backtest()    ← 交易执行耦合了信号计算
}
```

期望状态:
```
# 独立信号模块（可在 EXP-004 中直接 import）
from backtest_engine.calc.vol_rsi_std import compute_vol_rsi_signal

# 独立约束模拟器（P0/P1 修复后通用）
from backtest_engine.sim.constraints import TPlusOneConstraint, PriceLimitConstraint

# 独立运行器（参数化策略函数）
from backtest_engine.runner import PortfolioRunner
```

**具体分解**:

| 模块 | 路径 | 输入 | 输出 | 复用目标 |
|:----|:-----|:-----|:-----|:--------|
| 信号计算 | `calc/` | `(n_days, n_stocks)` 数据矩阵 | `(n_days, n_stocks)` 信号矩阵 | EXP-004 所有实验 |
| 约束模拟 | `sim/` | 时间戳、持仓状态 | 允许操作列表 | 所有回测 |
| 策略 | `strategy/` | 信号矩阵 + 今日持仓 | 目标仓位向量 | EXP-004 新策略 |
| 运行器 | `runner.py` | 策略函数 + 数据 | 资金曲线 + 绩效指标 | 统一入口 |

### 2.2 策略接口标准化

**原则 P-R2：所有策略实现统一签名，回测引擎通过函数注入调用。**

```python
# 标准策略接口
@dataclass
class Signal:
    symbol: str
    action: Literal["buy", "sell", "hold"]
    price: float
    quantity: int
    reason: str

def strategy_fn(
    signal_matrix: np.ndarray,    # (n_stocks, n_days) 信号矩阵
    positions: Dict[str, int],    # 当前持仓（股数）
    cash: float,                  # 当前现金
    date_index: int,              # 当前交易日索引
    meta: Dict                    # 元信息（涨跌停价等）
) -> List[Signal]:
    """策略函数签名固定，EXP-004 只需替换此函数"""
    ...
```

**好处**: EXP-004 的新策略只需写一个函数，不需要理解 `run_portfolio_backtest` 的内部细节。

### 2.3 约束可组合（Decorator Pattern）

**原则 P-R3：每个约束（T+1、涨跌停、停牌、滑点）是独立的 decorator 或 filter，可插拔组合。**

```python
# 约束过滤器链
constraints = [
    TPlusOneConstraint(),
    PriceLimitConstraint(),
    VolumeConstraint(),
    SlippageModel(),
    DividendHandler(),
]

runner = PortfolioRunner(
    strategy=strategy_fn,
    data=data,
    constraints=constraints
)
```

**当前问题**: 约束逻辑散落在 `run_portfolio_backtest` 函数里，加了涨跌停就要改一长串代码，复用性差。

### 2.4 数据合约一致性

**原则 P-R4：数据加载与回测引擎之间契约固定，新实验不需要重写加载逻辑。**

当前 `load_stock_data` 返回的类型是 `Dict[str, Dict[str, np.ndarray]]`。标准化为：

```python
@dataclass
class BacktestData:
    close: np.ndarray          # (n_days, n_stocks)
    open: np.ndarray           # (n_days, n_stocks)
    volume: np.ndarray         # (n_days, n_stocks)
    adj_factor: np.ndarray     # (n_days, n_stocks)
    pre_close: np.ndarray      # (n_days, n_stocks)
    price_limit_mask: np.ndarray  # (n_days, n_stocks, 2) — 上下限
    trading_dates: List[str]
    symbols: List[str]
```

EXP-004 只需要提供满足此合约的数据源（同库或不同标的池），回测引擎无须改动。

---

## 三、可验证性：确保改完代码后结果可信

### 3.1 对比基线（Regression Test）

**原则 P-V1：每次修改前后，必须执行同一组对标基准的对比验证。**

具体做法:

```python
def regression_validate(
    run_before: Callable,   # 修改前运行函数
    run_after: Callable,    # 修改后运行函数
    test_cases: List[TestCase],
    tolerance: float = 1e-6
):
    for case in test_cases:
        before_result = run_before(case)
        after_result = run_after(case)
        diff = compare(before_result, after_result)
        if diff > tolerance:
            raise RegressionError(f"Regression in {case.name}: {diff}")
```

**当前缺陷**: 没有任何回归测试。修改了 `run_portfolio_backtest`，只能靠肉眼检查资金曲线。

**建议**: 建立一个 `tests/regression/` 目录，每个 P0/P1 修复后自动跑 3 个对标测试：

| 测试 | 目标 | 方法 |
|:----|:-----|:-----|
| 全等回归 | 无行为变化的修改（重构）不改变结果 | 前后输出逐字段对比，容差 1e-6 |
| 约束引入回归 | 新增约束（T+1）后资金曲线方向一致但更保守 | 新夏普 <= 旧夏普，最大回撤 >= 旧最大回撤 |
| 信号修正回归 | 前视偏差修复后信号效力降低 | 修复后 IC/收益 <= 修复前 |

### 3.2 确定性执行（Deterministic Execution）

**原则 P-V2：给定同一输入数据，回测结果必须完全相同。**

意味着：
- 禁止使用 `random` 或 `numpy.random`
- 禁止 `np.random.rand*`（即使设置了 seed，也要防止意外的 seed 覆盖）
- 浮点数操作使用 `np.isclose` / `math.isclose` 比较，不等号使用 `if a > b + 1e-8`
- 结果序列化时使用 `round(value, decimals)` 避免浮点残留

### 3.3 逐字段断言 + 明细日志

**原则 P-V3：回测产生的中间状态（每日持仓、每日现金流、每笔交易）可审计可回溯。**

```python
# 交易日志格式
TRADE_LOG_COLUMNS = [
    "date", "symbol", "action", "price", "shares",
    "cost_before", "cash_before", "cash_after",
    "position_before", "position_after",
    "constraint_hits"  # 被哪些约束阻止了哪些操作
]
```

**审计原则**:
- 每次回测产生完整的交易日志 DataFrame（write to CSV for inspection）
- 性能指标（夏普、最大回撤、胜率）必须能从交易日志独立计算验证
- 修改后只检查日志，不依赖图表"看着对"

### 3.4 黄金文件对比

**原则 P-V4：每次修改后，将关键输出（资金曲线日序列、最终持仓、绩效指标）与黄金文件对比。**

```
tests/regression/golden_files/
├── v0.1_pre_fix/           ← 修复前基线
│   ├── equity_curve.csv
│   └── metrics.json
├── v0.2_p0_fix/            ← P0 修复后
│   ├── equity_curve.csv
│   └── metrics.json
└── v1.0_full_fix/          ← 完整修复后
    ├── equity_curve.csv
    └── metrics.json
```

**每次修改** → 生成结果 → 对比对应黄金文件 → 差异在预期范围内则自动更新黄金文件 → 提交版本。

---

## 四、我最头疼的 3 个编码问题

### 问题 1：前视偏差的隐性传播

**描述**: 改好了一个函数（比如 `calc_vol_rsi_std`），觉得前视偏差已消除。结果发现它在被调用时又被某个下游函数的 `shift(-1)` 或 `rolling(-1)` 加回去了。或者新写一个指标时，不懂行的团队成员又用了当日数据。

**病因**: 信号计算链路中有 N 个函数串联（`calc_vol_rsi_std` → `compute_signal_vector` → `classify_market_state` → `composite`），前视偏差可以沿调用链反复出现或消失。

**最怕的**: 这不是某一段代码的 bug，而是**系统性的隐性约定**——有些人觉得"前一天信号"是调用者责任，有些人觉得应该是函数本身的后移。

**希望的**: 一个明确的**时序契约**——所有 `calc/` 模块输出必须是"截止前一日收盘"的信号，任何使用者都无须再 shift。违反此契约的代码应被 Linter 或 Review 捕获。

### 问题 2：约束叠加时的交互效应

**描述**: 单独实现 T+1 约束时，逻辑清楚——当日买入不可卖。单独实现涨跌停时，逻辑也清楚——涨停不可买，跌停不可卖。但二者叠加时：

1. T+1 约束导致今日买入的标的不能被卖出
2. 涨跌停约束导致今日已有仓位被锁
3. 停牌又导致某些标的无行情
4. 三者叠加 → 某标的触发卖出信号但不满足任意一个卖出条件 → 被跳过
5. 资金释放不出来 → 下一日信号调整 → 循环卡住

**最怕的**: 单个约束的单元测试都是对的，组合后出现"非预期的资金锁定"——具体是哪条约束链导致的？无法快速定位。

**希望的**: 约束执行时的日志要记录"被拒绝的原因"（拒绝XX: T+1锁仓 / 跌停锁仓 / 停牌）。这样出问题时能追出 root cause。

### 问题 3：代码重构后的"等价性证明"

**描述**: 把 `run_portfolio_backtest` 里的信号计算分离出去，做了重构。重构后结果和原来不一样了——但这是重构引入的 bug，还是 P0 修复本身就设计要改变结果？

**最怕的**: 纯重构（不应改变行为）和无意 bug 混在一起无法区分。特别是浮点数误差累积能让结果千差万别，到底是浮点误差还是逻辑 bug？

**希望的**: 
1. 重构和修复要**分步进行**：先跑旧代码生成黄金基线，重构（不改逻辑）后对比，确认完全一致后再加新约束
2. 使用 `np.allclose` 对比日级别资金曲线，而非只比最终收益率（累计误差容易掩盖日级别问题）
3. 黄金文件带上 `git hash` + 数据哈希，确保旧版本的可复现性

---

## 五、总结：核心原则清单

| 编号 | 原则 | 维度 | 优先级 |
|:----:|:-----|:----:|:------:|
| P-C1 | 数据层/计算层/模拟层三层分离 | 效率 | P0 |
| P-C2 | 向量化优先，循环次之 | 效率 | P0 |
| P-C3 | 数据一次性加载，连续内存布局 | 效率 | P1 |
| P-C4 | 循环内不创建新数组/对象 | 效率 | P1 |
| P-R1 | 信号/约束/策略正交模块 | 复用 | P0 |
| P-R2 | 策略接口标准化（函数注入） | 复用 | P0 |
| P-R3 | 约束可组合（Decorator 模式） | 复用 | P1 |
| P-R4 | 数据合约固定（BacktestData dataclass） | 复用 | P0 |
| P-V1 | 每次修改执行回归对比 | 验证 | P0 |
| P-V2 | 确定性执行（无随机源） | 验证 | P0 |
| P-V3 | 交易日志完整可审计 | 验证 | P0 |
| P-V4 | 黄金文件对比 | 验证 | P1 |

### 下一步讨论议题

1. **三层分离的具体职责边界** — 模拟层能否完全无 `try/except`？
2. **约束 decorator 的执行顺序约定** — T+1 和涨跌停谁先执行？
3. **黄金文件管理策略** — 什么时候自动更新？什么时候告警？
4. **P0 修复实施顺序** — 信号分离（重构）→ T+1（新约束）→ 分批验证

---

*文档由墨衡 (DeepSeek R1) 基于回测引擎审计及 P0 修复方案编写*
