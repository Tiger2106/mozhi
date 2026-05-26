# 三策略 Code Review 报告

- **审查人**: 墨萱 🔍
- **日期**: 2026-05-16
- **审查范围**: `run_trend.py`, `run_reversal.py`, `run_grid.py`
- **参考**: `reports/meeting/three_strategies_fix_report.md`

---

## 审查结论总览

| 级别 | 数量 | 说明 |
|:----:|:----:|:------|
| P0 | 1 | 必须修复（功能错误） |
| P1 | 4 | 建议修复（健壮性/维护性） |
| P2 | 3 | 观察项（非阻塞） |
| 修复验收 | 2/2 PASS | 今日修复项已验证通过 |

---

## 一、今日修复验收

### 1.1 profit_factor 双键容错

**Verdict: ✅ PASS**

三文件的 profit_factor 容错均已从 `or` 短路写法修正为 `if "profit_factor" in metrics` 安全写法：

```python
"profit_factor": metrics.get("profit_factor") if "profit_factor" in metrics
                  else metrics.get("profit_loss_ratio", 0.0),
```

- `run_trend.py:831` ✅
- `run_reversal.py:871` ✅
- `run_grid.py:1093` ✅

验证要点：
- ✅ 使用了 `if in` 而不是 `or`（避免了 `or` 的 Falsey 值误判，如 `profit_factor=0.0` 时不会误 fallback）
- ✅ 容错顺序正确：优先 `profit_factor`，降级 `profit_loss_ratio`
- ✅ 最终 fallback `0.0` 存在
- 无残留的 `or` 模式

### 1.2 config_key 统一

**Verdict: ✅ PASS**

`run_reversal.py:851` 的 `config_key` 已从 `config.signal_type` 修正为：

```python
config_key=f"{config.signal_type}_{config.position_mode}_{config.tag}"
```

三策略的 config_key 格式现一致：

| 策略 | config_key 格式 | 行号 |
|:----:|:---------------|:----:|
| trend  | `{signal_type}_{pos_mode}_{tag}` | 809 |
| reversal | `{signal_type}_{position_mode}_{tag}` | 851 |
| grid | `_build_config_key(signal, position)` | 1090 |

⚠️ 注：grid 的 config_key 虽然格式不同（更详细，含网格参数），但这是有意为之——网格策略的可区分维度（n_levels/grid_type/cool_down/stop_loss）比趋势/反转更多，`_build_config_key()` 已合理覆盖。

---

## 二、P0 — 必须修复

### P0-1: `_GridRunnerStrategy._open_position()` 误调用 `self._pos_manager.reset()`

**文件**: `run_grid.py` | **行**: ~708

**问题**:
```python
def _open_position(self, price: float) -> None:
    """记录开仓状态。"""
    self._entry_price = price
    self._has_position = True
    grid_id = f"grid_bar_{self._bar_index}"
    self._active_grid_ids.append(grid_id)
    self._pos_manager.reset()  # ⚠️ 清除了冷却期和止损状态
```

`GridPositionManager.reset()` 会调用 `self.cool_down.reset()` —— **每一次开仓都会重置冷却计数器**。这意味着：
1. 如果 price 触发 BUY 开仓 → `_open_position()` → `_pos_manager.reset()` → cool_down 被重置
2. 下一次相同触发条件出现 → 冷却期形同虚设（因为刚被重置）
3. `check_stop_loss` 的内部状态同理被重置

`_close_position()` 也调用了 `self._pos_manager.reset()`，但这在此处是合理的（平仓后确实应该重置）。

**建议**: 移除 `_open_position()` 中的 `self._pos_manager.reset()` 调用。开仓时不需要重置冷却期和止损状态（止损状态应在平仓时重置，冷却期则应在触发后开始计时，不被开仓影响）。

```python
def _open_position(self, price: float) -> None:
    self._entry_price = price
    self._has_position = True
    grid_id = f"grid_bar_{self._bar_index}"
    self._active_grid_ids.append(grid_id)
    # 移除: self._pos_manager.reset()  ← 开仓不重置冷却/止损状态
```

---

## 三、P1 — 建议修复

### P1-1: `KnowledgeDB.store_run()` 中 `param_version` 始终为 `"v0_initial"`

**文件**: 三文件 | **行**: `run_trend.py:818`, `run_reversal.py:858`, `run_grid.py:1079`

**问题**:
```python
param_version=getattr(config, "param_version", "v0_initial"),
```

三者的 `TrendBacktestConfig`, `ReversalBacktestConfig`, `GridRunnerConfig` 均没有 `param_version` 字段。此 `getattr` 永远返回默认值 `"v0_initial"`。

**影响**: 知识库中所有三策略的回测记录均被标记为 `v0_initial`，无法区分历史版本和经过参数扫描优化的版本。未来做参数扫描时，所有结果混在一起无法按版本筛选。

**建议**: 在各自的 Config dataclass 中添加 `param_version: str = "v0_initial"` 字段，并在 `__post_init__` 中读取外部环境变量 `PARAM_VERSION` 覆盖，或由调用者显式指定。例如：

```python
@dataclass
class TrendBacktestConfig:
    ...
    param_version: str = "v0_initial"
    ...
```

### P1-2: `run_trend.py` 的 `to_params_dict()` 中非 MA 信号类型下仍输出 `ma_fast`/`ma_slow`

**文件**: `run_trend.py` | **行**: 208-240（`to_params_dict` 方法）

**问题**: 
当 `signal_type` 为 `"macd"` 或 `"bollinger"` 或 `"trend_score"` 时，`to_params_dict()` 仍然输出 `ma_fast` 和 `ma_slow` 字段（从 `self.signal_params` 中查找，找不到则填入默认值 5/20）。例如用 MACD 信号时，输出的参数字典包含 `ma_fast: 5` 和 `ma_slow: 20`，但实际信号参数（`fast_period`, `slow_period`, `signal_period`）完全丢失。

**影响**: 跨系统对接时，下游消费 `to_params_dict()` 会得到错误/不完整的信号参数。例如 MACD 回测结果在知识库中记录的参数是 MA 参数而非 MACD 参数。

**建议**: 根据 `self.signal_type` 动态选择要输出的参数字段：

```python
if self.signal_type == "ma":
    # 输出 ma_fast, ma_slow
elif self.signal_type == "macd":
    # 输出 fast_period, slow_period, signal_period
elif self.signal_type == "bollinger":
    # 输出 period, std_dev
...
```

或至少将原始 `self.signal_params` 作为 `raw_params` 一并输出。

### P1-3: `_build_config_key()` 中 `pos_params` 的 `cool_down` 和 `stop_loss` 取值依赖 `params` 属性，但 `GridPositionManager` 的 `params` 是 @property 而非 dict

**文件**: `run_grid.py` | **行**: 734-752（`_build_config_key` 函数）

**问题**:
```python
pos_params = position.params     # GridPositionManager 的 @property
pos_logic = pos_params.get("position_logic", {})
...
cd = pos_params.get("cool_down")  # 依赖于 params 返回字典
sl = pos_params.get("stop_loss")  # 同上
```

查看 `GridPositionManager.params` 的 getter——如果 `params` 返回的不是预期的 `{"position_logic": ..., "cool_down": ..., "stop_loss": ..., "exposure": ...}` 结构，`_build_config_key` 会静默失败（返回部分空值）。

**影响**: `build_config_key` 可能生成不准确的配置标识，尤其在 `params` 属性实现变更时。

**建议**: 增加防御性检查，或优先从 `GridPositionManager` 的成员属性（`self.position_logic.mode`, `self.cool_down.cool_down_bars` 等）直接读取，而不是依赖 `params` 属性的字典结构。

### P1-4: 三策略共有的 `load_stock_bars()` 为重复代码

**文件**: `run_trend.py:78-112`, `run_reversal.py:85-119`, `run_grid.py:498-562`

**问题**: `load_stock_bars()` 在三文件中几乎完全重复，仅有 `run_grid.py` 版本多了 `.split(".")[0]` 的代码兼容处理。三份独立副本意味着：
- 一处修复需要同步三处
- `run_grid.py` 的 `.split(".")` 兼容性改进不会自动同步到 `run_trend.py` 和 `run_reversal.py`
- 无单点测试覆盖（各有各的测试？——实际也无针对性测试）

**建议**: 将 `load_stock_bars()` 提取到公共模块（如 `backtest.utils.db` 或 `backtest.pipeline.data_loader`），三策略统一引用。`run_grid.py` 的兼容性处理（`.split(".")[0]`）应整合进公共函数，通过可选参数控制。

---

## 四、P2 — 观察项

### P2-1: `run_trend.py` CLI 的输出 key 为 `profit_loss_ratio` 而非统一的 `profit_factor`

**文件**: `run_trend.py` | **行**: 866

**问题**: CLI 的指标输出使用了 `profit_loss_ratio`，但 `_persist_result()` 中已统一为 `profit_factor`。两者不一致可能导致 CLI 输出与持久化记录的指标名不匹配。

```python
# CLI output (line 866):
("profit_loss_ratio", "盈亏比"),

# _persist_result (line 831):
"profit_factor": metrics.get("profit_factor") if ...
```

同样出现在 `run_reversal.py:906` 和 `run_grid.py` 的 CLI 部分。

**影响**: 低。只是 CLI 输出展示名称不同，不影响实际功能。

**建议**: 统一使用 `profit_factor` 以避免混淆，或在注释中注明映射关系。

### P2-2: `run_grid.py` 在 `__main__` 中 CLI 参数风格与趋势/反转不一致

**文件**: `run_grid.py` | **行**: 1170+

趋势/反转的 CLI 接受 6 个参数：`[symbol] [signal_type] [pos_mode] [start_date] [end_date] [tag]`

网格的 CLI 只接受 4 个参数：`[symbol] [start_date] [end_date] [tag]`

**影响**: 低。网格的信号和仓位逻辑通过 `GridRunnerConfig` 的默认值处理，自定义配置需编程调用。CLI 简约不算缺陷，但风格不一致。

**建议**: 无操作要求，仅在文档中注明。

### P2-3: `_persist_result()` 中三策略的 `data_days` 取值来源不一致

**文件**: 三文件 | **行**: `run_trend.py:819`, `run_reversal.py:859`, `run_grid.py:1080`

**问题**:
```python
data_days=getattr(result, "total_bars", 0),
```

`BacktestResult` 在回测引擎中可能以 `total_bars` 或 `data_days` 或其他字段名称存在。`getattr` 方式的容错是正确的，但如果 `total_bars` 字段名在未来重构中变更，此处不会抛出错误，而是静默变为 0。

**影响**: 低。知识库中 `data_days=0` 的记录可被识别为异常记录。

**建议**: 无操作要求。建议未来迁移到通过 `result.total_bars` 直接访问（而非 getattr），以在类型系统中获得编译时检查。

---

## 五、代码质量评估

### 5.1 代码结构一致性

| 维度 | trend | reversal | grid | 评价 |
|:----|:-----:|:--------:|:----:|:----:|
| Config dataclass | ✅ | ✅ | ✅ | 一致 |
| `__post_init__` 默认值填充 | ✅ | ✅ | ✅ | 一致 |
| `to_params_dict()` | ✅ | ✅ | ✅ | 一致（但 trend 的有 P1-2 问题） |
| `load_stock_bars()` | ✅ | ✅ | ✅ | 重复代码（P1-4），grid 多了 split |
| `_build_signal_df()` | ✅ | ✅ | - | grid 无此函数（信号逻辑不同） |
| `generate_signals()` | ✅ | ✅ | - | grid 无此函数（使用 GridSignalProvider） |
| `_persist_result()` | ✅ | ✅ | ✅ | 结构一致，grid 多 config_key 参数 |
| `run_*_backtest()` | ✅ | ✅ | ✅ | 流程一致 |
| `run_*_backtest_batch()` | ✅ | ✅ | ✅ | 一致 |
| CLI `__main__` | ✅ | ✅ | ✅ | grid 参数较少（P2-2） |

**结论**: 趋势与反转的代码结构几乎镜像对齐。网格由于策略类型的差异（网格信号 vs 离散信号），结构有所不同但合理。

### 5.2 日志输出

三策略的主流程日志覆盖了：
- 数据加载 ✅（symbol, 日期范围, 条数）
- 信号生成 ✅（type, 条数）
- 回测完成 ✅（交易次数, 年化收益）
- 结果持久化 ✅（保存路径）
- 批量运行 ✅（配置索引, 状态）
- 知识库写入异常 ✅（warning 级别，不阻断主流程）

**评价**: 日志充分且一致。加分项：`result.metrics.keys()` 被打印用于调试指标缺失问题。

### 5.3 错误处理

- ✅ `load_stock_bars()`: 数据库不存在 → `FileNotFoundError`；数据为空 → `ValueError` 含详细信息
- ✅ `generate_signals()`: 未知 signal_type → `ValueError` 含可选列表
- ✅ `_persist_result()`: KnowledgeDB write → `try/except` + logging.warning，不阻断主流程
- ✅ `batch_run_*()`: 单个配置异常不影响其余，失败项返回 None/FAILED status
- ⚠️ `run_grid_backtest()`: 整个 body 被 `try/except` 包裹，返回 `GridRunnerResult.from_error()`——这是一个好的模式，但趋势和反转未采用（会直接抛异常）
- ❌ `_open_position()`: P0-1 中 `_pos_manager.reset()` 错误调用，实际是逻辑错误

---

## 六、测试覆盖评估

### 6.1 已有测试文件

| 文件 | 方向 | 内容 | 评价 |
|:----|:----:|:------|:----:|
| `test_trend_backtest.py` | 趋势 | P2-18: 单次回测/批次回测/空配置/信号覆盖；P2-19: 参数扫描CSV | ✅ 较完整，但未测 `run_trend()` 入口 |
| `test_trend_position.py` | 趋势 | 仓位管理单元测试 | ✅ |
| `test_trend_signal.py` | 趋势 | 信号生成单元测试 | ✅ |
| `test_reversal_signal.py` | 反转 | 信号生成单元测试 | ✅ |
| `test_grid_strategy.py` | 网格 | 5 分组网格策略测试 | ✅ |
| `test_grid_position.py` | 网格 | 6 分组仓位管理+风控+集成测试 | ✅ |
| `test_run_grid_benchmark.py` | 网格 | buy_hold_kpi 基准计算测试 | ✅ |

### 6.2 覆盖缺口

| # | 缺失 | 风险 |
|:-:|:-----|:-----|
| 1 | **无 `run_trend_backtest()` 集成测试** | 趋势运行器的主入口无人测试。`test_trend_backtest.py` 直接使用 `BacktestEngine` + 自定义策略类，但未调用 `run_trend_backtest(TrendBacktestConfig)`。这意味着 `_persist_result()` 中的 KnowledgeDB 写入逻辑、`_build_signal_df()` 的降级分支、`TrendBacktestConfig.to_params_dict()` 等从未被测试 |
| 2 | **无 `run_reversal_backtest()` 集成测试** | 同趋势，反转运行器无集成测试。`ReversalBacktestConfig` 的 `__post_init__`、`to_params_dict()`、`_persist_result()` 均无测试 |
| 3 | **无 KnowledgeDB 持久化 mock 测试** | 三策略的 `_persist_result()` 调用了 `KnowledgeDB()` 的真实构造函数（虽然包装在 try/except），无 mock/单元测试验证参数传递正确性 |
| 4 | **`run_grid.py` 的 `load_stock_bars()` 未单独测试** | 虽有 `test_run_grid_benchmark.py` 但通过 mock 跳过了实际数据加载。`load_stock_bars()` 中的 `.split(".")[0]` 兼容性逻辑未被覆盖 |
| 5 | **三策略的边界条件测试不足** | 如空信号列表、全 None 风控参数、`signal_params` 为空字典但 `signal_type` 非默认值等情况无显式测试 |

### 6.3 建议补充的测试

```python
# 推荐的集成测试模式（以趋势为例）
def test_run_trend_backtest_default():
    """默认配置回测可正常执行且结果包含期望指标。"""
    result = run_trend_backtest()
    assert result.total_trades >= 0
    assert "profit_factor" in result.metrics  # 验证 profit_factor 键存在
    assert "total_return_pct" in result.metrics

def test_run_trend_config_key_format():
    """_persist_result 中 config_key 格式正确。"""
    # 通过 mock KnowledgeDB 验证 store_run 的参数
    ...

def test_run_trend_signal_params_macd():
    """MACD 信号配置的 to_params_dict 不输出 ma_fast/ma_slow。"""
    cfg = TrendBacktestConfig(signal_type="macd")
    params = cfg.to_params_dict()
    # 应包含 fast_period 等而非仅 ma_fast/ma_slow
    ...
```

---

## 七、汇总

| # | 级别 | 文件 | 行 | 问题 | 建议 |
|:-:|:----:|:----:|:--:|:-----|:----:|
| 1 | **P0** | `run_grid.py` | ~708 | `_open_position()` 误调 `_pos_manager.reset()` 清除冷却期 | 移除该调用 |
| 2 | P1 | 三文件 | 818/858/1079 | `param_version` 始终 `"v0_initial"`（字段缺失） | Config dataclass 添加该字段 |
| 3 | P1 | `run_trend.py` | 208-240 | `to_params_dict()` 非 MA 信号仍输出 `ma_fast/ma_slow` | 按 signal_type 动态选择参数 |
| 4 | P1 | `run_grid.py` | 734-752 | `_build_config_key()` 依赖 `params` 字典结构 | 改用成员属性直接读取 |
| 5 | P1 | 三文件 | 78-112/85-119/498-562 | `load_stock_bars()` 重复代码 | 提取公共模块 |
| 6 | P2 | 三文件 | 866/906（CLI） | CLI 输出 key 为 `profit_loss_ratio` vs `_persist_result` 的 `profit_factor` | 统一名称 |
| 7 | P2 | `run_grid.py` | 1170+ | CLI 参数风格不同 | 无操作 |
| 8 | P2 | 三文件 | 819/859/1080 | `data_days` 用 `getattr` 静默降级 | 无操作 |

### 修复评分

| 今日修复 | 验收结论 |
|:---------|:---------:|
| profit_factor 双键容错 | ✅ PASS |
| config_key 统一 | ✅ PASS |

### 行动建议

1. **P0（紧急）**: 修复 `_GridRunnerStrategy._open_position()` 的 `_pos_manager.reset()` 误调用
2. **P1（高优先）**: 提取 `load_stock_bars()` 公共模块，新增 `param_version` 字段
3. **P1（中优先）**: 修复 `to_params_dict()` 的 signal_type 感知输出
4. **测试（持续）**: 补充三策略运行器的集成测试，覆盖 `_persist_result` 的 KnowledgeDB 参数传递

---
*Report generated by 墨萱 🔍 at 2026-05-16 16:03*
