<!--
  author: 墨衡（MoHeng）
  task_id: P0-9-risk (doc 2/5)
  created: 2026-05-17 20:19 +08:00
  status: READY
  source: risk_action_plan_moheng_20260517.md §P0-9
-->

# P0-#9-02: MethodBacktestRunner 运行原理（Plugin 开发者文档 2/5）

> **目标读者：** 运维/主程（墨衡、墨萱）
> **核心内容：** `MethodBacktestRunner` 的双模式运作原理、数据流、生命周期
> **前置依赖：** `docs/05_protocols/signal_schema.md`（信号协议） / P0-#5 回归验证协议

---

## 1. 架构定位

```
Pipeline (daily/weekly)
  │ 执行
  ├──→ MethodBacktestRunner.run(df)
  │       │
  │       ├──→ methods/registry.py.discover_methods()  # 动态加载Method
  │       ├──→ methods/base.py.BaseMethod.setup()       # Phase 1
  │       ├──→ methods/base.py.BaseMethod.on_bar()      # Phase 2 (逐Bar)
  │       ├──→ methods/base.py.BaseMethod.generate_signal() # Phase 2 (批量)
  │       └──→ methods/base.py.BaseMethod.cleanup()     # Phase 3
  │       │
  │       ├──→ engine/knowledge_bridge.py.harvest()     # Phase 4b (知识收割)
  │       │
  │       └──→ MethodResult (输出)
  │
  └──→ signal_bridge.py (信号桥 → 信号转换器 → 实盘)
```

**核心文件：**
- Runner: `src/backtest/runners/method_backtest_runner.py`
- Method 基类: `src/backtest/methods/base.py`
- 方法注册: `src/backtest/methods/registry.py`
- 方法元信息: `src/backtest/methods/manifest.py`
- 信号桥: `src/backtest/signal_bridge.py`

---

## 2. 初始化流程

```python
runner = MethodBacktestRunner("ma_cross", ctx)
```

**内部执行序列：**

```
MethodBacktestRunner.__init__("ma_cross", ctx)
  │
  ├── 1. discover_methods_recursive() 扫描 methods/ 下所有 *_method.py
  │      ├── flat 扫描: registry.py.discover_methods()
  │      ├── 递归扫描: _walk_method_files() + _import_method_class()
  │      └── 结果: {"ma_cross": (MaCrossMethod, METHOD_META), ...}
  │
  ├── 2. 匹配 method_name="ma_cross" → (MaCrossMethod, METHOD_META)
  │      └── 未找到 → 抛 ValueError("未知方法 'ma_cross'")
  │
  ├── 3. 实例化: self.method = MaCrossMethod()
  │
  └── 4. C6检查: check_requires_state_on_bar()
         └── requires_state=True 但 on_bar 未覆写 → 告警
```

---

## 3. 执行生命周期（`run()` 方法）

### Phase 0: 数据预检（R1）

```python
_validate_input_data(ctx, method_cls, df)
```

检查项：
1. **非空**: `len(df) > 0`
2. **列存在**: `required_columns` 全部存在
3. **Bar数足够**: `len(df) >= data_min_bars`（默认20）
4. **NaN检查**: 发现NaN列 → 仅警告，不阻断

```python
# 预检失败时抛 ValueError:
# ValueError("[ma_cross] 数据预检失败：数据行数 5 不足最低要求 20 根K线。")
```

### Phase 1: setup()

```python
self.method.setup(self.ctx)
```

- 从 `ctx` 读取配置参数（`ctx.get_config("ma_fast", 5)`）
- 初始化内部状态
- 不涉及 DataFarme 操作

### Phase 2: 执行（A/B 模式自动切换）

**模式判定依据：** `METHOD_META.capabilities.requires_state`

#### 模式 A（`requires_state=False` — 无状态方法）

```python
# 1. 逐Bar调用 on_bar() 累积内部状态
for idx, row in df.iterrows():
    self.method.on_bar(row)

# 2. 批量生成信号
signal_df = self.method.generate_signal(df)

# 3. 转换为 MethodResult
result = MethodResult(
    signals=signal_df,          # 至少含 signal 列
    indicators=indicators_df,   # 其他指标列（如 ma_fast, ma_slow）
    method_name=...,            # 方法名
    params=...,                 # 配置参数
    statistics=self._extract_statistics_from_df(signal_df),  # 统计量
)
```

**适用方法：** MA, MACD, RSI, KDJ, BIAS, Bollinger, VolumeProfile, Wyckoff

#### 模式 B（`requires_state=True` — 有状态方法）

```python
# 1. 逐Bar调用 on_bar() 并收集返回信号
signal_values = []
for idx, row in df.iterrows():
    bar_result = self.method.on_bar(row)  # 直接返回 dict
    if isinstance(bar_result, dict):
        signal_values.append(bar_result.get("signal", 0))
    else:
        signal_values.append(0)

# 2. 构建 MethodResult（不在模式B中调用 generate_signal）
result = MethodResult(
    signals=pd.DataFrame({"signal": signal_values}, index=df.index),
    method_name=...,
    params=...,
)
```

**适用方法：** GridMethod, ReversalMethod

**关键约束：** 模式 B 中 `generate_signal(df)` **不在此调用**，避免 O(n²)。

### Phase 3: cleanup()

```python
self.method.cleanup()
```

- 资源释放
- 状态重置
- 无状态方法可写 `pass`

### Phase 4: 元数据填充

```python
result.duration_ms = (time.perf_counter() - start) * 1000.0
result.completed_time = pd.Timestamp.now(tz="Asia/Shanghai")
```

日志输出示例：
```
Runner.run: method=ma_cross bars=120 signals=45 duration=12.3ms mode=A
```

### Phase 4b: KnowledgeBridge 集成

```python
bridge = KnowledgeBridge(output_dir="data/knowledge_entries", sync_to_bitable=True)
bridge.harvest(result=result, method_name="ma_cross", symbol="601857", config=ctx.config)
```

- 知识收割：将回测结果转化为 KnowledgeEntry v2 格式
- 失败不阻断：`logger.warning` 而非异常抛出
- 配置控制：`runner = MethodBacktestRunner(... , enable_knowledge_collection=True)`

---

## 4. MethodResult 数据模型

```python
@dataclass
class MethodResult:
    signals: pd.DataFrame      # 必须：信号 DataFrame（含 signal 列）
    indicators: pd.DataFrame   # 可选：指标 DataFrame
    method_name: str            # 方法名
    params: dict               # 执行参数
    duration_ms: float = 0.0   # 耗时（毫秒）
    completed_time: str = ""   # 完成时间戳
    errors: list = field(default_factory=list)  # 错误列表
```

---

## 5. 批量运行（`run_batch()`）

支持多时间框架数据：

```python
runner = MethodBacktestRunner("ma_cross", ctx)
results = runner.run_batch({
    "daily": df_daily,
    "hourly": df_hourly,
})
# → {"daily": MethodResult, "hourly": MethodResult}
```

每个数据帧独立调用 `run()`，方法名/参数共享。

---

## 6. 关键依赖链

```
MethodBacktestRunner
  ├── methods/registry.py.discover_methods_recursive()
  │     └── methods/base.py.BaseMethod (基类)
  ├── backtest/context.py.StrategyContext (上下文)
  ├── backtest/methods/manifest.py.METHOD_META (元信息协议)
  └── engine/knowledge_bridge.py.KnowledgeBridge (知识收割)
        └── engine/knowledge_entry.py.KnowledgeEntry (知识条目 v2)
```

**运行时依赖：**
- pandas, numpy（数据处理）
- `logger` 在 `ctx` 中提供（`ctx.get_logger()`）

---

## 7. 常见排查

| 症状 | 排查方向 |
|------|---------|
| Runner 耗时过长 (>1s) | 检查 `on_bar()` 中有无 O(n²) 操作；`generate_signal()` 有无不必要的全表扫描 |
| `discover_methods` 找不到方法 | 文件名必须以 `_method.py` 结尾；类必须继承 `BaseMethod` 且不是私有类 |
| 模式错误（期望模式B但跑了模式A） | 检查 `METHOD_META.capabilities.requires_state` 是否设为 `True` |
| KnowledgeBridge 抛异常 | Exception 被捕获为 `logger.warning`，不影响回测结果。检查 `knowledge_entry.py` 数据格式 |
| 信号值域被截断 | 检查 `MethodResult.signals` 的 signal 列 dtype |

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 20:19 +08:00*
