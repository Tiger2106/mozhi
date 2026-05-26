<!--
  author: 墨衡（MoHeng）
  task_id: P0-9-risk (doc 1/5)
  created: 2026-05-17 20:19 +08:00
  status: READY
  source: risk_action_plan_moheng_20260517.md §P0-9
-->

# P0-#9-01: 插件系统开发者手册（Plugin 开发者文档 1/5）

> **目标读者：** 策略开发者（墨萱、墨衡）
> **核心内容：** 如何编写一个新的 Method/Factor/Strategy 插件
> **前置依赖：** `plugin_system_final_design_20260517.md`（系统设计总纲）

---

## 1. 插件体系概述

MoZhi 插件系统分为三层，从底向上：

```
Layer 1: Factor（因子层）
  │  计算原始市场数据指标（MA, RSI, ATR 等）
  │  基类: BaseFactor (backtest/factors/base.py)
  │  注册: discover_factors() (backtest/methods/registry.py)
  │
  ├──→ Layer 2: Method（方法层）
  │    组合Factor生成交易信号（BUY/SELL/HOLD）
  │    基类: BaseMethod (backtest/methods/base.py)
  │    注册: discover_methods() (backtest/methods/registry.py)
  │    元信息: METHOD_META (backtest/methods/manifest.py)
  │
  └──→ Layer 3: Strategy（策略层）
        组合多个Method进行资金分配和执行
        基类: Strategy (backtest/strategies/)
        上下文: StrategyContext (backtest/context.py)
```

**文件位置速查：**
- Factor 目录: `src/backtest/factors/{category}/`
- Method 目录: `src/backtest/methods/{category}/`
- Strategy 文件: `src/backtest/strategies/`
- 测试目录: `src/backtest/tests/`
- 回归测试目录: `tests/regression/`

---

## 2. 编写一个 Method（核心流程）

### 2.1 步骤总览

```
1. 在 methods/{category}/ 下新建 {name}_method.py
2. 创建继承 BaseMethod 的类
3. 定义 METHOD_META 元信息（名称、版本、能力声明）
4. 实现 on_bar() 或 generate_signal() 方法
5. 创建回归测试（必须！见 P0-#5 回归验证协议）
6. 运行 pytest 验证
```

### 2.2 最小示例

```python
# src/backtest/methods/momentum/sample_method.py

"""
SampleMethod — 示例方法（演示插件开发流程）。

使用方法:
    method = SampleMethod()
    method.setup(ctx)
    result = method.generate_signal(df)  # → MethodResult
"""

from __future__ import annotations
import pandas as pd
from typing import Dict, Any

from backtest.methods.base import BaseMethod, MethodResult


# ─── C3: MethodManifest 元信息协议（manifest.py参考） ─────

METHOD_META: Dict[str, Any] = {
    "name": "sample",
    "version": "1.0.0",
    "description": "演示用示例方法",
    "capabilities": {
        "long_only": True,          # 仅做多
        "intraday_support": False,  # 不支持盘中信号
        "requires_state": False,    # 无状态方法
    },
    "default_params": {},
    # 可选字段:
    "required_columns": ["close", "volume"],
    "data_min_bars": 20,
    "tags": ["demo", "example"],
}


class SampleMethod(BaseMethod):
    """示例方法。"""

    def setup(self, ctx) -> None:
        """Step 1: 初始化。

        在 generate_signal() 之前调用，用于：
        - 从 ctx 读取配置参数
        - 初始化内部状态
        - 预计算辅助数据

        Args:
            ctx: StrategyContext 实例（或 MockContext）
        """
        self.ma_fast = ctx.get_config("ma_fast", 5)
        self.ma_slow = ctx.get_config("ma_slow", 20)

    def on_bar(self, row: pd.Series) -> None:
        """Step 2a: 逐Bar处理（可选）。

        对于 requires_state=False 的方法，此方法仅用于累积状态。
        实际的信号生成在 generate_signal() 中统一处理。

        对于 requires_state=True 的方法（如 GridMethod），
        需要在 on_bar 中逐Bar返回信号字典。
        """
        # 无状态方法通常不需要在 on_bar 中做任何事
        pass

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 2b: 批量信号生成（主入口）。

        接收完整 OHLCV DataFrame，返回包含 'signal' 列的 DataFrame。

        signal 列的值域:
        - 1: BUY（买入）
        - 0: HOLD（持有/无信号）
        - -1: SELL（卖出）

        Args:
            df: OHLCV DataFrame（索引为 DatetimeIndex）

        Returns:
            pd.DataFrame: 至少包含 'signal' 列
        """
        result = df.copy()
        # 注入指标列（可选）
        result["ma_fast"] = df["close"].rolling(self.ma_fast).mean()
        result["ma_slow"] = df["close"].rolling(self.ma_slow).mean()

        # 生成信号
        result["signal"] = 0
        mask_buy = result["ma_fast"] > result["ma_slow"]
        mask_sell = result["ma_fast"] < result["ma_slow"]

        result.loc[mask_buy, "signal"] = 1
        result.loc[mask_sell, "signal"] = -1

        return result

    def cleanup(self) -> None:
        """Step 3: 清理（可选）。

        generate_signal() 完成后调用。
        """
        pass
```

### 2.3 METHOD_META 字段参考

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|:----:|------|------|
| `name` | str | ✅ | 方法唯一标识（小写蛇形） | `"ma_cross"` |
| `version` | str | ✅ | 语义化版本 | `"1.0.0"` |
| `description` | str | 推荐 | 功能描述（≤100字） | `"MA金叉死叉策略"` |
| `capabilities.long_only` | bool | ✅ | 仅做多 | `True` |
| `capabilities.intraday_support` | bool | ✅ | 盘中信号 | `False` |
| `capabilities.requires_state` | bool | ✅ | 需要状态持久化 | `False` |
| `default_params` | dict | ✅ | 默认参数 | `{"fast": 12}` |
| `required_columns` | list[str] | 推荐 | 数据列要求 | `["close","volume"]` |
| `data_min_bars` | int | 推荐 | 最小数据点数 | `20` |
| `author` | str | 可选 | 作者 | `"墨萱"` |
| `tags` | list[str] | 可选 | 标签 | `["trend","momentum"]` |

### 2.4 两种执行模式

| 模式 | 条件 | 执行流程 | 适用方法 |
|:----:|:----:|---------|---------|
| **模式 A** | `requires_state=False`（默认） | `on_bar` 逐Bar → `generate_signal` 批量生成 | MA, MACD, RSI, KDJ, BIAS, Bollinger, VolumeProfile, Wyckoff |
| **模式 B** | `requires_state=True` | `on_bar` 逐Bar返回信号字典，Runner累积 | GridMethod, ReversalMethod |

**模式 B 示例（有状态方法）：**

```python
class StatefulMethod(BaseMethod):
    """有状态方法示例。"""
    METHOD_META = {
        "name": "stateful_example",
        "capabilities": {"requires_state": True},
        ...
    }

    def setup(self, ctx):
        self.bars_since_last_signal = 0
        self.cooldown = ctx.get_config("cooldown_bars", 5)

    def on_bar(self, row: pd.Series) -> dict:
        """逐Bar返回信号。"""
        self.bars_since_last_signal += 1
        signal = 0
        if self.bars_since_last_signal >= self.cooldown:
            signal = 1 if row["close"] > row["close"].shift(1) else -1
            self.bars_since_last_signal = 0
        return {"signal": signal, "cooling": self.bars_since_last_signal}
```

---

## 3. 编写一个 Factor

Factor 是比 Method 更底层的数据抽象，通常用于计算技术指标。

### 3.1 最小示例

```python
# src/backtest/factors/trend/sample_factor.py

from backtest.factors.base import BaseFactor

FACTOR_META = {
    "name": "sample",
    "version": "1.0.0",
    "category": "trend",
    "default_params": {"period": 14},
}

class SampleFactor(BaseFactor):
    def compute(self, df):
        return df["close"].rolling(self.params["period"]).mean()
```

### 3.2 注册方式

Factor 通过 `discover_factors()` 自动发现。命名要求：
- 文件后缀 `_factor.py`
- 文件名蛇形，类名驼峰（如 `sample_factor.py` → `SampleFactor`）

---

## 4. 编写一个 Strategy

Strategy 是组合多个 Method 进行资金分配的执行单元。

### 4.1 架构总览

```
StrategyContext
  ├── symbol: str               — 标的代码
  ├── config: dict              — 参数配置
  ├── account: Account          — 账户信息
  └── get_logger()              — 日志

Strategy
  ├── method_a = MethodRunner("macd", ctx)
  ├── method_b = MethodRunner("rsi", ctx)
  ├── run(df) → 组合多个Method结果
  └── allocate() → 资金分配
```

### 4.2 编写参考

参考现有 Strategy 实现：
- `src/backtest/strategies/trend_strategy.py` — MA/MACD/Bollinger 组合
- `src/backtest/strategies/reversal_strategy.py` — RSI/KDJ/BIAS 投票
- `src/backtest/strategies/grid_strategy.py` — 网格策略

---

## 5. 测试指南

### 5.1 单元测试

```python
# tests/test_{method_name}.py

import pytest
import pandas as pd
import numpy as np

from backtest.methods.{category}.{module_name} import {MethodClass}


def make_test_df(n=120) -> pd.DataFrame:
    """生成固定种子测试数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "close": 100 + np.cumsum(np.random.randn(n) * 0.5),
        "high": 102 + np.cumsum(np.random.randn(n) * 0.3),
        "low": 98 + np.cumsum(np.random.randn(n) * 0.3),
        "volume": np.random.randint(1000, 10000, n),
    }, index=pd.DatetimeIndex(dates))


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)


def test_generate_signal():
    df = make_test_df(120)
    method = {MethodClass}()
    method.setup(MockContext({}))
    result = method.generate_signal(df)

    assert "signal" in result.columns
    assert len(result) == len(df)
    assert set(result["signal"].unique()).issubset({-1, 0, 1})
```

### 5.2 回归测试 (强制)

详见 `docs/06_reviews/P0-5_method_regression_protocol_20260517.md`

**注意：新Method必须创建回归测试，否则无法合入main分支。**

回归测试模板：

```python
# tests/regression/test_regression_{name}.py

@pytest.mark.regression
def test_signal_consistency():
    df = make_test_df(250)
    method = {MethodClass}()
    method.setup(MockContext({}))
    result = method.generate_signal(df)

    assert "signal" in result.columns
    # 全新Method：记录基线而非比较
    print(f"信号均值: {result['signal'].mean():.4f}")
    print(f"信号非零比例: {(result['signal'] != 0).mean():.2%}")
```

---

## 6. 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `discover_methods()` 找不到新Method | 文件名未以 `_method.py` 结尾 | 重命名文件 |
| `on_bar` 不执行 | `requires_state=False` 时 `on_bar` 仅用于状态累积 | 确认模式选择正确 |
| 信号值域超出 {-1,0,1} | `generate_signal()` 未归一化 | 在返回前 clip 信号到标准值域 |
| 回归测试未通过 | 新修改导致与旧Runner输出不一致 | 检查 `compute_deviation()` 偏差原因 |
| `MethodResult` 缺少字段 | `generate_signal()` 返回格式不标准 | 确保返回包含 `signal` 列的 DataFrame |

---

## 7. 实施清单（新方法开发检查表）

- [ ] `{name}_method.py` 文件创建
- [ ] `METHOD_META` 完整定义（8个字段）
- [ ] `setup()` 实现
- [ ] `generate_signal()` 或 `on_bar()` 实现
- [ ] `cleanup()` 实现（至少写 `pass`）
- [ ] 单元测试（在 `tests/` 下）
- [ ] 回归测试（在 `tests/regression/` 下）
- [ ] 方法已自动被 `discover_methods()` 发现
- [ ] `pytest tests/` 全部通过
- [ ] 偏差阈值 ≤ 0.5%（仅对旧系统已存在的方法）

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 20:19 +08:00*
