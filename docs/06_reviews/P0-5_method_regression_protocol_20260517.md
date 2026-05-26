<!--
  author: 墨衡（MoHeng）
  task_id: P0-5-risk
  created: 2026-05-17 20:19 +08:00
  status: READY
  source: risk_action_plan_moheng_20260517.md §P0-5
-->

# P0-#5：方法回归验证协议（强制门禁）

> **风险：「0%偏差」虚假安全感** — 10个Method的0%偏差验证仅是一次性检验，
> 新Method可未经回归验证直接进入生产。需要建立强制回归验证流程作为开发门禁。

---

## 1. 问题定位

**根因验证：**

| 检查项 | 结果 | 详细 |
|--------|:----:|------|
| `test_method_comparison.py` 覆盖范围 | ⚠️ 仅覆盖 D6-D13（8个Method） | `VolumeProfileMethod`、`WyckoffMethod` 无对比测试 |
| 验证类型 | ⚠️ 一次性 | 无 `conftest.py` 或 `pytest --regression` 模式 |
| 白名单管理 | ❌ 不存在 | `registry.py` 无 `regression_verified` 字段 |
| CI门禁 | ❌ 不存在 | 新Method PR可以绕过验证直接合入 |

**关键代码位置：**
- 现有对比测试：`src/backtest/tests/test_method_comparison.py`（D6-D13）
- 偏差计算工具：`src/backtest/methods/comparison_test_helper.py`
  - `compute_deviation()` — 计算新旧信号平均绝对偏差
  - `assert_deviation_under_threshold()` — 阈值断言（默认 0.5% = 0.005）
- 方法自动发现：`src/backtest/methods/registry.py` — `discover_methods()` / `discover_factors()`
- 方法基类：`src/backtest/methods/base.py` — `BaseMethod` / `MethodResult`
- 方法元信息：`src/backtest/methods/manifest.py` — `METHOD_META` 协议

---

## 2. 强制回归验证流程

### 2.1 流程总图

```
新Method开发完成（在 methods/ 下新建 *_method.py）
       │
       ▼
┌────────────────────────────────────────────┐
│ Step 1: 注册到 Registry                    │
│   registry.py.discover_methods() 自动发现   │
│   或 @register_method("name") 装饰器注册    │
│   确认 methods/manifest.py 中               │
│     METHOD_META.name 唯一且正确             │
└────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────┐
│ Step 2: 创建回归测试                       │
│   文件: tests/regression/                  │
│         test_regression_{method_name}.py   │
│   框架: pytest + parametrize               │
│   输入: make_test_df(n=250) 标准测试数据    │
│   输出: MethodResult.signals == 预期信号    │
└────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────┐
│ Step 3: 运行回归验证                       │
│   pytest tests/regression/                 │
│     --regression-mode=full                 │
│   现有Method：偏差 ≤ 0.5% (0.005)          │
│   全新Method：无偏差阈值 → 记录基线信号     │
└────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────┐
│ Step 4: 判定结果                           │
│   ✅ 偏差在阈值内 → 自动标记                │
│      regression_verified: true              │
│      registry/method_whitelist.json 更新     │
│                                              │
│   ❌ 偏差超出阈值 → 阻断PR/MR               │
│      CI pipeline 返回 non-zero exit code    │
│      强制修复后方可合入 main 分支            │
└────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────┐
│ Step 5: 标记白名单                         │
│   registry/method_whitelist.json 追加记录    │
│   { "method_name": "macd",                  │
│     "regression_verified": true,            │
│     "verified_at": "2026-05-17T20:00+08:00",│
│     "deviation": 0.00012 }                  │
└────────────────────────────────────────────┘
```

### 2.2 文件结构

```
tests/regression/
├── __init__.py
├── conftest.py              # 标准测试数据 fixtures
├── test_regression_macd.py   # D7 回归测试
├── test_regression_ma_cross.py  # D6
├── test_regression_bollinger.py # D8
├── test_regression_rsi.py    # D9
├── test_regression_kdj.py    # D10
├── test_regression_bias.py   # D11
├── test_regression_grid.py   # D12
├── test_regression_reversal.py # D13
├── test_regression_volume_profile.py  # 新Method基线
└── test_regression_wyckoff.py        # 新Method基线

registry/
└── method_whitelist.json     # 已验证方法白名单
```

### 2.3 回归测试模板（新Method示例）

```python
# tests/regression/test_regression_{method_name}.py
"""回归验证：{MethodName} — 确保新/旧Runner一致性"""

import pytest
import pandas as pd
import numpy as np

from backtest.methods.{category}.{module_name} import {MethodClass}
from backtest.tests.test_method_comparison import make_test_df, MockContext


@pytest.mark.regression
@pytest.mark.parametrize("seed", [42, 123, 999])
def test_signal_consistency(seed: int):
    """不同随机种子下信号应保持一致"""
    df = make_test_df(n=250)
    method = {MethodClass}()
    method.setup(MockContext({}))
    result = method.generate_signal(df)

    assert "signal" in result.columns
    assert len(result) == len(df)

    # 全新Method记录基线
    print(f"{method_name} 信号均值: {result['signal'].mean():.4f}")


@pytest.mark.regression
def test_method_meta_valid():
    """METHOD_META 协议合规"""
    from backtest.methods.manifest import validate_manifest

    errors = validate_manifest({MethodClass}.METHOD_META)
    assert len(errors) == 0, f"Manifest 校验失败: {errors}"
```

### 2.4 现有Method回归测试适配要点

| Method | 旧系统函数 | 是否已存在对比测试 | 回归测试需调整 |
|--------|-----------|:------------------:|:------------:|
| `MaCrossMethod` | `trend_strategy.generate_ma_cross_signals` | ✅ D6 | 迁移到 `tests/regression/` |
| `MACDMethod` | `trend_strategy.generate_macd_signals` | ✅ D7 | 同上 |
| `BollingerMethod` | `trend_strategy.generate_bollinger_signals` | ✅ D8 | 同上 |
| `RSIMethod` | `reversal_strategy.generate_rsi_signals` | ✅ D9 | 同上 |
| `KDJMethod` | `reversal_strategy.generate_kdj_signals` | ✅ D10 | 同上 |
| `BiasMethod` | `reversal_strategy.generate_bias_signals` | ✅ D11 | 同上 |
| `GridMethod` | 全新实现 | ✅ D12（仅参数校验） | 改为新旧Runner对比 |
| `ReversalMethod` | `reversal_strategy.voted_reversal_signal` | ✅ D13 | 迁移 |
| `VolumeProfileMethod` | 全新实现 | ❌ 无 | 创建基线测试 |
| `WyckoffMethod` | 全新实现 | ❌ 无 | 创建基线测试 |

---

## 3. 白名单管理

### 3.1 白名单文件

```json
// registry/method_whitelist.json
{
  "version": "1.0.0",
  "last_full_regression": "2026-05-17T20:00+08:00",
  "methods": {
    "ma_cross": {
      "regression_verified": true,
      "verified_at": "2026-05-17T20:00+08:00",
      "deviation": 0.00012,
      "experimental": false
    },
    "volume_profile": {
      "regression_verified": true,
      "verified_at": "2026-05-17T20:00+08:00",
      "deviation": null,
      "experimental": false,
      "note": "全新实现，无旧系统可对比。基线已记录"
    },
    "new_method_unverified": {
      "regression_verified": false,
      "verified_at": null,
      "deviation": null,
      "experimental": true,
      "note": "待验证。允许实验模式但不进入生产信号管道"
    }
  }
}
```

### 3.2 实验模式（Experimental Mode）

未验证的Method可以通过设置 `experimental=True` 以实验模式运行，但：
- ❌ 不进入生产信号管道（`signal_bridge.py` 过滤）
- ❌ 不触发实盘信号
- ✅ 可在测试环境运行
- ✅ 可在报告中输出实验对比

```python
# src/backtest/methods/registry.py 中新增标记字段
class MethodRegistryEntry:
    method_name: str
    regression_verified: bool = False
    experimental: bool = False
    verified_at: Optional[str] = None
    deviation: Optional[float] = None
```

---

## 4. 全量回归周期

### 4.1 定时任务

```yaml
# Windows Task Scheduler 或 cron 配置
频率: 每周一次（建议周一 08:00）
命令: cd C:\Users\17699\mozhi_platform && python -m pytest tests/regression/ --regression-mode=full --junitxml=reports/regression_weekly.xml
输出: reports/regression_weekly_{YYYYMMDD}.json
超时: 30分钟
失败通知: 飞书群消息（告警方法）
```

### 4.2 Python API 触发

```python
import subprocess
from pathlib import Path

def run_full_regression() -> dict:
    """运行全量回归测试"""
    result = subprocess.run(
        ["pytest", "tests/regression/",
         "--regression-mode=full",
         "--junitxml=reports/regression_weekly.xml",
         "-v"],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent
    )
    return {
        "passed": result.returncode == 0,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }
```

---

## 5. CI 门禁集成

### 5.1 Pre-merge 强制检查

```yaml
# .github/workflows/regression.yml (若使用 GitHub Actions)
name: Method Regression Verification
on:
  pull_request:
    paths:
      - 'src/backtest/methods/**'

jobs:
  regression:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: pytest tests/regression/ --regression-mode=ci -v --tb=short
        env:
          PYTHONPATH: src
```

### 5.2 本地 CI 脚本（无 GitHub Actions 时）

```python
# scripts/run_regression_ci.py
import sys, subprocess

def check_method_whitelist(method_name: str) -> bool:
    """检查Method是否已通过回归验证"""
    import json
    with open("registry/method_whitelist.json") as f:
        whitelist = json.load(f)
    entry = whitelist["methods"].get(method_name, {})
    return entry.get("regression_verified", False)

def main():
    result = subprocess.run(
        ["pytest", "tests/regression/", "-x", "--tb=short"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("❌ 回归验证失败，PR被阻断")
        print(result.stdout[-1000:])
        sys.exit(1)
    print("✅ 回归验证通过")

if __name__ == "__main__":
    main()
```

---

## 6. 依赖与阻塞

| 依赖项 | 状态 | 说明 |
|--------|:----:|------|
| `tests/regression/` 目录创建 | ⬜ 待创建 | 新建目录 + `__init__.py` |
| `conftest.py` 标准fixtures | ⬜ 待创建 | 复用 `test_method_comparison.py` 中的 `make_test_df()` |
| `registry/method_whitelist.json` | ⬜ 待创建 | 白名单文件 + 解析工具 |
| 现有10个Method的回归测试 | ⬜ 待迁移 | 从 `test_method_comparison.py` 迁移 |
| CI 脚本 | ⬜ 待创建 | `scripts/run_regression_ci.py` |

---

## 7. 核心规则速查表

| 规则 | 详细 |
|------|------|
| **强制门禁** | 新Method的PR中必须包含 regression test，否则不可合入 main 分支 |
| **全量回归周期** | 每周全量跑一次所有已验证Method的回归测试（cron job） |
| **白名单管理** | `registry/method_whitelist.json` 记录已验证Method + 验证时间戳 |
| **实验模式** | 未验证Method可设置 `experimental=True`，以实验模式运行但不进入生产 |
| **偏差阈值** | 沿用 Phase 2 标准：新旧Runner输出差异 ≤ 0.5%（0.005） |
| **全新Method** | 无旧系统对比 → 记录基线信号，不强制偏差阈值，但必须通过回归测试 |

---

## 8. 实施清单

- [ ] 1. 创建 `tests/regression/` 目录 + `__init__.py`
- [ ] 2. 创建 `conftest.py` 标准fixtures（复用 `make_test_df` + `MockContext`）
- [ ] 3. 为10个Method各创建回归测试文件
- [ ] 4. 创建 `registry/method_whitelist.json` + 读写工具
- [ ] 5. 为 `registry.py` 补充 `regression_verified` 字段
- [ ] 6. 创建 `scripts/run_regression_ci.py` 本地CI脚本
- [ ] 7. 配置每周全量回归 cron 任务
- [ ] 8. 更新开发流程文档，加入回归验证步骤

> **预估实施时间：4h**（含测试迁移+白名单工具+CI脚本）

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 20:19 +08:00*
