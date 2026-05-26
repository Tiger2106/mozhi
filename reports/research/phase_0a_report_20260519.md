<!--
author: 墨衡 (moheng)
created_time: 2026-05-19 16:06 GMT+8
task_id: phase_0a_existence_validator
-->

# Phase 0a 报告：ExistenceValidator MVP 验证

**生成时间**: 2026-05-19 16:06 +08:00
**模块**: `src/utils/existence_validator.py`
**测试脚本**: `scripts/test_existence_validator.py`
**作者**: 墨衡 (moheng)

---

## 一、摘要

Phase 0a 目标：实现策略存在性验证器（ExistenceValidator）第一版，通过 6 项检查判定回测/因子分析结果是否具有统计意义的"存在性"。

**时间线**: 2026-05-19 方案评审会批准 → 同日完成 MVP 开发并验证通过。

**核心判定**: 全部 11 项预期测试通过，ExistenceResult 格式验证 8/8 通过。代码可交付。

---

## 二、验证器设计

### 2.1 数据结构

```python
@dataclass
class TradeRecord:
    date: Union[datetime, date, str]   # 交易日期/观测日期
    pnl_pct: float                      # 收益率(%) 或 IC 值
    regime: str                         # 市场状态标签

@dataclass
class ExistenceResult:
    exists: bool          # 全部通过 → True
    confidence: float     # 0.0 ~ 1.0（加权置信度）
    fail_reasons: list[str]  # 未通过项的说明
    details: dict         # 每项检查的详细值
```

### 2.2 六项检查

| 检查 | 字段 | 阈值 | 设计依据 |
|:----|:----|:----|:---------|
| **C1 最小交易数** | `C1_n_trades` | >= 30 | 统计显著性门槛 (Central Limit Theorem) |
| **C2 多Regime覆盖** | `C2_n_regimes` | >= 2 | 不在单一市场状态下有效 |
| **C3 多年度覆盖** | `C3_time_span_years` | >= 2.0 年 | 跨牛熊周期验证 |
| **C4 非单段收益** | `C4_max_single_share` | < 40% | 不依赖极端单次交易 |
| **C5 信号密度** | `C5_density` | >= 12.0/年 | 低频策略边界标注 |
| **C6 样本分布** | `C6_max_window_fraction` | <= 50% | 时间分布均匀性 (10等分窗) |

### 2.3 置信度计算

加权平均，C1 占 30%（样本量是根基），其余各占 10~15%：

```
confidence = 0.30 * C1_pass + 0.15 * C2_pass + 0.15 * C3_pass
           + 0.10 * C4_pass + 0.15 * C5_pass + 0.15 * C6_pass
```

---

## 三、测试结果

### 3.1 核心用例

#### P6 FAIL 用例（84天 / 2笔交易）

| 检查 | 实际值 | 阈值 | 结果 |
|:----|:-----:|:----:|:----:|
| C1 最小交易数 | 2 | >= 30 | ❌ FAIL |
| C2 多Regime覆盖 | 1 bull | >= 2 | ❌ FAIL |
| C3 多年度覆盖 | 0.36 年 | >= 2.0 年 | ❌ FAIL |
| C4 非单段收益 | 75.7% | < 40% | ❌ FAIL |
| C5 信号密度 | 5.6/年 | >= 12.0/年 | ❌ FAIL |
| C6 样本分布 | 50% | <= 50% | ✅ PASS |

> **exists=False, confidence=0.15（仅 C6 通过）**
> 验证了 84 天窗口内 2 笔交易在统计上"不可信"——样本量不足、时间跨度过短、收益集中度过高。

#### P7 PASS 用例（N=1540 天 IC 分析）

| 检查 | 实际值 | 阈值 | 结果 |
|:----|:-----:|:----:|:----:|
| C1 最小交易数 | 1540 | >= 30 | ✅ PASS |
| C2 多Regime覆盖 | 3 (bear/bull/range) | >= 2 | ✅ PASS |
| C3 多年度覆盖 | 5.90 年 | >= 2.0 年 | ✅ PASS |
| C4 非单段收益 | 0.13% | < 40% | ✅ PASS |
| C5 信号密度 | 261/年 | >= 12.0/年 | ✅ PASS |
| C6 样本分布 | 10.06% (max) | <= 50% | ✅ PASS |

> **exists=True, confidence=1.0**
> 1540 天日频 IC 分析在所有维度上通过验证——充足样本、跨越多种市场状态、收益分布均匀。

### 3.2 边界测试

| 测试 | exists | confidence | 说明 |
|:----|:-----:|:---------:|:-----|
| 空列表 | ❌ False | 0.0 | 立即返回，无后续检查 |
| 单一观测 | ❌ False | 0.15 | 5 项检查失败（C5 因"1天跨度"密度极高而不适用） |
| 单Regime 30笔 | ❌ False | 0.70 | C2+C3 失败（0.4年 < 2年） |
| 均匀分布 90笔/7.4年 | ✅ True | 1.0 | 完美通过 |
| 极端收益集中 | ❌ False | 0.75 | C3+C4 失败（1.3年 < 2年，99.6% > 40%） |
| 同日多笔 | ❌ False | 0.55 | C1+C5 失败（12 < 30, 3.4 < 12） |

### 3.3 格式验证

所有 8 个测试用例的 `ExistenceResult` 输出均通过格式校验：
- `exists`: bool ✅
- `confidence`: float ∈ [0, 1] ✅
- `fail_reasons`: list[str] ✅
- `details`: dict 含全部检查字段 ✅
- 一致性：`exists=True` 时 `fail_reasons` 为空 ✅

---

## 四、文件清单

| 文件 | 说明 | 行数 |
|:----|:----|:---:|
| `src/utils/existence_validator.py` | 核心验证器 | ~190 行 |
| `scripts/test_existence_validator.py` | 测试套件（8 用例, 11 断言） | ~280 行 |
| `reports/research/phase_0a_report_20260519.md` | 本报告 | — |

---

## 五、后续建议

### 已知限制（非当前 MVP 范围）

1. **C6 窗口数固定为 10**: 对于极短期回测（< 1 年），10 窗口过细。建议后续增加自适应窗口数（如 max(5, √N)）。
2. **无需额外依赖**: 当前仅使用 Python 标准库，不依赖 pandas/numpy，保持轻量。
3. **Regime 由调用方提供**: 验证器不内置 regime 分类逻辑。后续可集成 `src/tests/regime/test_regime.py` 的分类功能。

### Phase 0b 提案

- 集成到回测主流水线的 `verify_backtest_result()` 检查中
- 增加 JSON serialization 支持（`ExistenceResult.to_dict()` / `from_dict()`）
- 为 `TradeRecord` 增加可选的 `weight` 字段，支持加权统计

---

## 结论

```
Phase 0a 状态: ✅ COMPLETE
代码交付物:   existence_validator.py (核心模块)
测试覆盖率:   8 用例 / 11 断言 / 全部通过
P6 验证:      exists=False ✅ (84天/2笔 → 不可信)
P7 验证:      exists=True  ✅ (1540天 IC → 可信)
格式规范:     8/8 通过
```
