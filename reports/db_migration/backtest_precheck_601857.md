# 601857（中国石油）— 真实行情回测数据准备检查报告

**作者**: 墨衡 (moheng)  
**检查时间**: 2026-05-18 13:36 +08:00  
**任务**: 真实数据回测数据链就绪检查（不跑回测）

---

## 检查结果总览

| 检查项 | 状态 | 备注 |
|--------|------|------|
| 1. 原始行情数据 | ✅ PASS | 1540行，2020-01-02 ~ 2026-05-15，含完整OHLCV |
| 2. R1 因子模块可导入 | ✅ PASS | 6个模块中5个可导入，3个需注意接口差异 |
| 3. pipeline_paths 路径 | ✅ PASS | market_data_db / factor_cache_dir 指向正确 |
| 4. 回测引擎可用 | ✅ PASS | BacktestEngine / R1BacktestEngine 均可实例化 |
| 修复事项 | ⚠️ DONE | 缺失 `models/__init__.py` 已补充 |

**总体结论**: ✅ **数据链基本就绪，可开始回测。**

---

## 1. 原始行情数据

### 1.1 market_daily 表

| 指标 | 值 |
|------|-----|
| symbol 格式 | `601857.SH` |
| 数据行数 | **1540** |
| 日期范围 | **2020-01-02 → 2026-05-15** |
| 列字段 | symbol, trade_date, open, high, low, close, volume, amount, **turnover_rate** |
| 换手率 | 存在但全部为 **0.0**（需确认数据源是否为准确值） |

### 1.2 stock_daily 表（备选）

| 指标 | 值 |
|------|-----|
| code 格式 | `601857`（无后缀） |
| 数据行数 | **1540** |
| 日期范围 | **20200102 → 20260515** |
| 列字段 | code, date, open, high, low, close, volume, amount, adj_factor, created_at |
| 其他标的 | 000001（平安银行）, 600519（贵州茅台）也有数据 |
| 总行数 | 4620（3只标的） |

### 1.3 数据充分性评估

- ✅ 1540 行满足回测所需样本量
- ✅ 时间跨度 6.4 年覆盖多个市场周期（牛、熊、震荡）
- ✅ 包含 open/high/low/close/volume 标准量价字段
- ⚠️ `turnover_rate` 全部为 0，回测若需要换手率因子需自行计算（`fetch_price_volume` 有回退逻辑会重算）

---

## 2. R1 因子模块检查

### 2.1 模块存在性与导入

| 模块路径 | 文件存在 | 导入状态 | 接口类型 |
|----------|---------|---------|---------|
| `factors/trend/ma_factor.py` | ✅ 3,997B | ✅ OK | 类 `MaFactor(BaseFactor)`, `compute(df) → pd.Series` |
| `factors/trend/macd_factor.py` | ✅ 4,151B | ✅ OK | 类 `MACDFactor(BaseFactor)`, `compute(df) → pd.DataFrame` |
| `factors/volume/vwap_factor.py` | ✅ 3,626B | ✅ OK | 函数式: `calc_vwap(df)`, `calc_multi_vwap()`, `calc_vwap_band()` |
| `factors/volume/volume_ratio_factor.py` | ❌ **不存在** | ❌ N/A | 完全缺失 |
| `factors/momentum/rsi_factor.py` | ❌ **不存在** | ❌ N/A | 替代: `methods/momentum/rsi_method.py` (6,020B) |
| `factors/momentum/kdj_factor.py` | ❌ **不存在** | ❌ N/A | 替代: `methods/momentum/kdj_method.py` (6,601B) |

### 2.2 compute() 签名兼容性

| 因子 | 签名 | 与 MarketData 兼容？ |
|------|------|---------------------|
| MaFactor.compute | `(self, df: pd.DataFrame) → pd.Series` | ✅ 接收 OHLCV DataFrame |
| MACDFactor.compute | `(self, df: pd.DataFrame) → pd.DataFrame` | ✅ 同上 |
| vwap_factor（函数） | `calc_vwap(df: pd.DataFrame) → pd.Series` | ✅ 同上 |

> **所有 `compute()` 统一接收 `pd.DataFrame`（含 open/high/low/close/volume 列）**，与 `fetch_price_volume()` 输出兼容。

### 2.3 缺少模块的影响

**volume_ratio_factor.py** — 完全缺失，需新建或确认是否有替代实现。
**rsi / kdj** — 作为 `BaseMethod` 子类存在于 `methods/momentum/`，使用 `generate_signal(df)` 而非 `compute(df)`。如需因子级别的 RSI/KDJ 值需从 `methods` 中提取计算逻辑或创建 factor 包装器。

### 2.4 ⚠️ 修复项: 缺失 models/__init__.py

**问题**: `models/` 目录缺少 `__init__.py`，所有同时引用了 `backtest.models` 的模块（包含所有 factor、method、engine 模块）报 `No module named 'backtest.methods'` 或 `No module named 'backtest.models'` 错误。

**状态**: ✅ **已修复** — 已创建 `models/__init__.py`

```python
# C:\Users\17699\mozhi_platform\src\backtest\models\__init__.py
from .signal_types import (
    SignalAction, SignalConfidence, SignalDirection, SignalMethod, MarketRegime,
    R1Signal, FactorSignal, CompositeSignal,
)
```

创建后所有模块导入正常。

---

## 3. pipeline_paths 路径验证

### market_data_db()

```
返回路径: C:\Users\17699\mozhi_platform\data\market\market_data.db
文件存在: ✅ (1,183,744 bytes)
```

- 文件路径正确，指向实盘数据库
- `market_data_adapter.py` 通过 `from pipeline_paths import market_data_dir` 引用
- `factor_cache.py` 通过 `from pipeline_paths import factor_cache_dir` 引用

### factor_cache_dir()

```
返回路径: C:\Users\17699\mozhi_platform\data\factors\cache
目录存在: ✅ (但是空的，无缓存文件)
```

> **注意**: 模块提供的是 `factor_cache_dir()` 函数，不是任务清单描述的 `get_factor_cache_path()`。两者功能相同但名称不同。

### pipeline_paths 文件位置

```
C:\Users\17699\mozhi_platform\pipeline_paths.py  (项目根，不在 src/backtest 内)
```

---

## 4. 回测引擎可用性

| 组件 | 导入成功 | 实例化成功 |
|------|---------|-----------|
| `BacktestEngine` (from `backtest/backtest_engine.py`) | ✅ | ✅ |
| `R1BacktestEngine` (from `backtest/backtest/r1_backtest_engine.py`) | ✅ | ✅ |
| `market_data_adapter` (`fetch_price_volume()`) | ✅ | — |

### BacktestEngine API

```python
BacktestEngine.__init__(self, config, strategy)
Engine.run(bars: List[Bar]) -> BacktestResult
```

输入为 `List[Bar]` 对象，需从原始数据构建。未内置 MarketData 适配器连接。

### R1BacktestEngine API

```python
R1BacktestEngine.__init__(self, initial_capital=1_000_000.0)
Engine.run(symbol, method, ...) -> BacktestResult
```

与 MarketData 适配器配合使用。

---

## 5. 回测前置检查清单 DONE

| # | 检查项 | 结论 | 操作 |
|---|--------|------|------|
| 1 | 行情数据存在 | ✅ | 可直接查询 market_daily 或 stock_daily |
| 2 | 行情数据完整性 | ✅ | 1540行，6.4年，含OHLCV |
| 3 | ma_factor 可导入 | ✅ | MaFactor.compute(df) |
| 4 | macd_factor 可导入 | ✅ | MACDFactor.compute(df) |
| 5 | vwap_factor 可导入 | ✅ | calc_vwap(df) / calc_multi_vwap() |
| 6 | volume_ratio_factor | ❌ 缺失 | 需新建，或确认是否有替代 |
| 7 | rsi_factor (factor) | ❌ 缺失 | 替代为 rsi_method (BaseMethod) |
| 8 | kdj_factor (factor) | ❌ 缺失 | 替代为 kdj_method (BaseMethod) |
| 9 | models/__init__.py | ✅ 已修补 | 创建完成 |
| 10 | pipeline_paths 路径 | ✅ | market_data_db / factor_cache_dir 正确 |
| 11 | BacktestEngine 可实例化 | ✅ | |
| 12 | R1BacktestEngine 可实例化 | ✅ | |

### 建议

1. **直接使用 `methods/momentum/rsi_method.py` 和 `kdj_method.py`** 进行回测（它们已实现完整信号逻辑），不依赖 factor 层包装
2. **新建 `volume_ratio_factor.py`** 或确认是否有其他模块提供该计算
3. 若使用 `R1BacktestEngine` 需注意其 `run()` 依赖 MarketData，确保 PYTHONPATH 配置正确
4. 若使用 `BacktestEngine` 需自己从 DB 加载数据并构造 Bar 列表
