# Phase 3 双系统并行验证 — 验证报告

**task_id**: phase3_dual_validation
**agent**: 墨衡 (moheng)
**date**: 2026-05-20
**status**: COMPLETED

---

## 交付物清单

| 文件 | 路径 | 状态 |
|:----|:-----|:----:|
| DualValidator | `tests/validation/dual_validator.py` | ✅ |
| 验证测试 | `tests/validation/test_dual_validator.py` | ✅ |
| 包初始化 | `tests/validation/__init__.py` | ✅ |
| SignalBacktestAdapter | `src/signals/signal_backtest_adapter.py` | ✅ |
| 清理计划 | `reports/reviews/meeting_decouple_20260519/phase3_cleanup_plan.md` | ✅ |
| 验证报告 | `reports/reviews/meeting_decouple_20260519/phase3_validation_report.md` | ✅ |

---

## 架构设计

### 双系统验证架构

```
Old Path (SignalBridge → OrderRequest)
  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐
  │  Strategy   │ ──→│ SignalBridge │ ──→│ OrderRequest│
  │ (信号值)    │    │ (1/-1/0)     │    │ (list)      │
  └─────────────┘    └──────────────┘    └─────────────┘
                                                  │
New Path (Signal → Consumer → OrderRequest)       │
  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐   │
  │  Strategy   │ ──→│ SignalObject │ ──→│ OrderRequest│   │
  │ (Signal)    │    │ (BUY/SELL)   │    │ (list)      │   │
  └─────────────┘    └──────────────┘    └─────────────┘   │
                                                           ▼
                                              ┌──────────────────┐
                                              │  DualValidator   │
                                              │  5 类偏差检测    │
                                              └──────────────────┘
```

### SignalBacktestAdapter 设计模式

```
Strategy (输出 Signal)  ─┐
                          ├── SignalToOrderStrategy(包装器)
BacktestEngine (需要     ─┘         │
  OrderRequest)                    ├── SignalConsumer
                                   │    (Signal → OrderRequest)
                                   └── 返回 OrderRequest
```

使用**装饰器模式**：
- 不修改 BacktestEngine
- 不修改 Strategy 代码
- 不修改早报管线/交易执行代码
- 只需用 `adapter.wrap_strategy(strategy)` 包装后传入 engine

---

## 5 类偏差阈值定义

| Class | 偏差类型 | 阈值 | 实现 | 状态 |
|:-----|:---------|:-----|:-----|:----:|
| 1 | 方向不一致（BUY vs SELL） | 0（零容忍） | `_check_direction()` | ✅ |
| 2 | 数量偏差 > 10% | ≤5% 的订单 | `_check_quantity()` | ✅ |
| 3 | 时序偏差 > 1 bar | ≤3% 的订单 | `_check_timing()` | ⚠️ 需 Bar 级上下文 |
| 4 | 信号遗漏/多余 | ≤2% 的总信号数 | `_check_missing_extra()` | ✅ |
| 5 | confidence 偏差 > 0.2 | ≤10% 的订单 | `_check_confidence()` | ✅ |

---

## 测试覆盖

| 测试 | 覆盖类 | 验证点 | 状态 |
|:----|:-------|:-------|:----:|
| `test_identical_orders` | 全一致 | 无偏差、通过 | ✅ |
| `test_multiple_identical_orders` | 全一致 | 多订单 | ✅ |
| `test_both_empty` | 全一致 | 空列表 | ✅ |
| `test_class1_direction_mismatch` | Class 1 | 方向检测 | ✅ |
| `test_class1_zero_tolerance` | Class 1 | 零容忍 | ✅ |
| `test_class1_no_false_positive` | Class 1 | 误报 | ✅ |
| `test_class2_quantity_deviation_exceeds` | Class 2 | 超限 | ✅ |
| `test_class2_quantity_deviation_within` | Class 2 | 未超限 | ✅ |
| `test_class4_missing_signal` | Class 4 | 遗漏 | ✅ |
| `test_class4_extra_signal` | Class 4 | 多余 | ✅ |
| `test_class4_multiple_diff` | Class 4 | 多偏差 | ✅ |
| `test_class5_confidence_deviation` | Class 5 | 超限 | ✅ |
| `test_class5_confidence_within` | Class 5 | 未超限 | ✅ |
| `test_mixed_deviations` | 综合 | 多类并存 | ✅ |
| `test_report_summary_format` | Report | 格式 | ✅ |

---

## 已知问题 (TODO)

1. **Class 3 (时序) 检测不精确**：目前只做基础的顺序比较，需要 Bar 级的上下文信息才能精确检测。建议后续提供 `bar_index` 映射。

2. **DualValidator 初始化**：`DualValidator.from_ordered_pairs()` 仅比较订单，不涉及信号 confidence，因此 Class 5 需通过完整的 `compare()` 接口。

3. **SignalBacktestAdapter 暂不处理 read_only 模式的差异**：当前默认 `read_only=False`，若需要观察者模式可传入 `ConsumerConfig(read_only=True)`。

---

## 后续步骤

1. 将 DualValidator 集成到 CI 流水线（回测运行后自动验证）
2. 验证旧路径（SignalBridge）与新路径（Signal+Consumer）在实际数据上的输出一致性
3. 一致性确认后，逐步移除旧代码（按清理计划执行）
