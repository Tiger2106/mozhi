<!--
author: 墨萱
created_time: 2026-05-16 09:28 +08:00
task_id: phase_review_v4.0_step2_rematch
review_type: Phase_Review_Step2_Rematch
-->

# 回测改进方案 v4.0 — 复审意见

**审查方**: 墨萱（独立质量验证）
**审查时间**: 2026-05-16 09:28 +08:00
**审查阶段**: 墨衡修复轮 → 墨萱复审轮

---

## REVIEW_RESULT: ✅ PASS

> ✅ **通过。** 初审查出的 3 个 P0 问题均已修复。复审给出 2 个 P1 建议供改进，不构成阻塞。

---

## 一、P0 逐项复核

### P0-1: `generate_comparison.py` 净值曲线模拟 → 真实数据

**状态**: ✅ 已修复

**验证方法**: 逐行阅读 `main()` 函数源码（CLI 路径 1500+ 行）

**验证结果**:

| 检查项 | 结果 | 说明 |
|:------|:----:|:-----|
| `trend_result.equity_curve` 优先读取 | ✅ | `if trend_result is not None and hasattr(trend_result, 'equity_curve')` 分支优先 |
| `reversal_result.equity_curve` 优先读取 | ✅ | 同理，有真实数据走真实路径 |
| `grid_result.equity_curve` 优先读取 | ✅ | 网格额外支持 CSV fallback |
| `np.random.normal()` 模拟仅作 fallback | ✅ | 仅当 `result is None` 或无 `equity_curve` 时才触发 |
| 报告中标注真实/模拟 | ✅ | 报告头部已写"实际回测+模拟曲线"，标注诚实 |

**结论**: P0-1 主逻辑已修复。初审查出的核心问题（`main()` 永远生成模拟曲线 → 优先读取真实数据）已解决。

**⚠️ P1 残留**: 对比表（报告第 1 节）仍使用 `KNOWN` 硬编码的 `win_rate` 和 `trades` 数值，即使真实 round-trip 数据已可用。这与第 6 节从 `compute_trade_distribution()` 计算的值可能不一致。见下方 P1 建议。

---

### P0-2: `pair_trades_to_roundtrips` FIFO 双队列 + 部分平仓

**状态**: ✅ 已修复

**验证方法**: 
1. 读取 `pair_trades_to_roundtrips` 源码（通过 `inspect.getsource()` + 直接文件阅读）
2. 手动运行测试用例（FIFO 多开仓部分平仓、空头平仓、网格多开 100+100+50 拆分）

**验证结果**:

| 检查项 | 结果 | 说明 |
|:------|:----:|:-----|
| 双队列（buy_queue/sell_queue） | ✅ | 两队列分别维护未平多头/空头仓位 |
| FIFO 匹配 | ✅ | 开仓入队尾，平仓从队头匹配（最早开仓先平） |
| 部分平仓拆分 | ✅ | `close_qty = min(entry["qty"], remaining)`, 剩余继续保留在队列 |
| 空头支持 | ✅ | SELL 开空入 `sell_queue`，BUY 平空匹配 `sell_queue` |
| 手续费按成交比例分摊 | ✅ | `exit_fee_share = fee * (close_qty / qty)` |
| 8 笔或更少交易的正确性 | ✅ | 手动测试全通过，pytest 586/586 通过 |

**手动测试结果**:
```
Test 1 - Basic FIFO (long): 1 roundtrip, qty=150, pnl=102.5 ✅
Test 2 - Short FIFO: 1 roundtrip, qty=80, pnl=120.0 ✅
Test 3 - Multi-grid partial: 3 roundtrips (100+100+50), each correct ✅
```

**结论**: 算法已按方案设计完整实现，FIFO 双队列、部分平仓、空头均通过验证。

**⚠️ P1 残留**: 
- 原建议的 `build_trade_pairs()` 命名未使用，而是直接重写了 `pair_trades_to_roundtrips()`。功能等价，不构成问题。
- 测试文件中无专门的 `pair_trades_to_roundtrips` 单元测试，仅有整体 `test_performance.py` 覆盖。建议至少添加一个基本的 FIFO 测试用例。

---

### P0-3: 迁移后 pytest 未运行验证

**状态**: ✅ 已修复

**验证方法**: 亲自在 Windows 终端运行：
```
cd C:\Users\17699\mozhi_platform
python -m pytest src/backtest/tests/ -x --tb=short
```

**验证结果**:

```
collected 586 items
======================= 586 passed, 3 warnings in 3.19s =======================
```

所有 586 项测试通过，3 个 RuntimeWarning 均为零除/无穷值等边界场景的正常警告。

**验证的修复内容**:
- `trend_strategy.py` 补充了向后兼容包装函数（`ma_signal`, `macd_signal`, `bollinger_signal` 等）
- 补充缺失的 `from dataclasses import dataclass` 导入
- 修复 `test_trend_backtest.py` 中移除的 `trend_strategy` 导入

**结论**: 全量 586 通过，import 路径与 API 签名兼容性均验证通过。

---

## 二、P0 复核结论汇总

| 编号 | 问题 | 初审状态 | 复审状态 | 判据 |
|:----:|:-----|:--------:|:--------:|:-----|
| P0-1 | `main()` 净值曲线模拟 → 真实数据 | 🔴 否决 | ✅ PASS | 源码审查：优先读取 equity_curve，模拟仅作 fallback |
| P0-2 | 配对算法未实现 FIFO 双队列+部分平仓 | 🔴 否决 | ✅ PASS | 源码+手动测试验证：双队列 FIFO/部分平仓/空头均正确 |
| P0-3 | 迁移后 pytest 未运行 | 🔴 否决 | ✅ PASS | 亲自运行：586/586 通过 |

---

## 三、新的 P1 建议（非阻塞）

### P1-v2-1: 比较表 KNOWN 与分布计算值的数据一致性

报告第1节的对比表中，`win_rate` 和 `trades` 仍来自 `KNOWN` 硬编码常量。而第6节的盈亏分布表通过 `compute_trade_distribution()` 从实际 round-trip 数据计算。当真实数据可用时，两者可能不一致。

建议：
- 第1节的 `win_rate` 和 `trades` 改为从 `dist_t`/`dist_r`/`dist_g` 计算，与第6节保持一致
- `KNOWN` 仅作为 fallback（当真实 roundtrip 不可用时）

### P1-v2-2: 添加 `pair_trades_to_roundtrips` 单元测试

当前 `test_performance.py` 中无针对 FIFO 配对算法的专门测试用例。该函数是盈利概率计算的底层依赖，缺少单元测试意味着未来代码重构时回归风险无法快速发现。

建议至少添加 3 个测试用例覆盖：
1. 基础 FIFO（两次开仓一次平仓，验证最早开仓先平）
2. 部分平仓拆分（一次开仓 200，分两次平仓各 100）
3. 空头双向（SELL 开仓 → BUY 平仓）

---

## 四、整体判定

**REVIEW_RESULT = ✅ PASS**

所有 3 个 P0 问题已修复。墨衡本轮的修复质量符合预期：
- P0-1 解决了核心盲区（净值曲线路径独立于交易明细）
- P0-2 完成了完整的 FIFO 双队列算法，包含部分平仓和空头支持
- P0-3 通过 586 项测试验证了迁移的完整性

2 个新的 P1 建议为软性改进，可在后续迭代中处理。

---

## 五、审查元信息

| 角色 | 审查结论 | 时间 |
|:----|:--------:|:----:|
| 墨萱（质量验证） | ✅ PASS — 所有 P0 已修复 | 2026-05-16 09:28 +08:00 |

> 📝 **审查说明：** 墨衡在 P0-2 的实现质量值得肯定——FIFO 双队列、部分平仓拆分、空头支持全部到位，手动测试通过。P0-1 的实现方式采用内联条件分支而非拆分为独立函数（与报告中描述的 `_get_equity_data()` 函数名略有出入），但功能逻辑正确，不构成问题。P0-3 的 586/586 全量通过是最有力的凭证。可以进入 Step3 由墨涵汇总收尾。
