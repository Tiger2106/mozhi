<!--
author: 墨萱
created_time: 2026-05-16 09:11 +08:00
task_id: phase_review_v4.0
review_type: Phase_Review_Step2
-->

# 回测改进方案 v4.0 — 阶段审查报告（Step2）

**审查方**: 墨萱（独立质量验证）
**审查时间**: 2026-05-16 09:11 +08:00
**审查阶段**: 墨衡阶段总结 Step1 → 墨萱 Step2 审查

---

## REVIEW_RESULT: ⛔ P0

> ❌ **否决**。存在 P0 级别问题，需返回 Step1 修改。

---

## 一、总体评价

墨衡本阶段以 2h20min 完成原方案约 41h 估算的全部编码改动，覆盖率可观：
- ✅ 4 项改进编码交付
- ✅ 审计 1 阻塞 + 3 警告修复（B1/W1/W3）
- ✅ 31/31 业务验证通过
- ✅ 引擎 5 核心模块迁移完成
- ✅ 变更汇总表闭环

**肯定已完成的基础项**：
- B1 修复（模块级副作用 → `if __name__ == "__main__"` ）正确 ✓
- 基准对标（买入持有 601857 六指标）可用 ✓
- 历史数据扩展至 5.4 年 ✓
- 参数配置随报告输出 ✓
- 报告模板路径确认 ✓

**但以下 P0 问题必须修复后才能继续**：

---

## 二、🔴 P0 问题（必须修复）

### P0-1: `generate_comparison.py main()` 净值曲线仍为模拟数据

| 属性 | 值 |
|:----|:----|
| **严重度** | 🔴 高 — 阻碍系统正确运行 |
| **涉及文件** | `src/backtest/reports/generate_comparison.py` |
| **相关方案项** | 第1项（基准对标）/ 第3项（盈利概率） |

**问题描述**：

审计报告的 B1（模块级副作用）已修复，`main()` 已用 `if __name__ == "__main__"` 包裹。但 **`main()` 函数内部** 在 L488~L508 仍然使用 `np.random.normal()` 生成趋势和反转策略的**净值曲线**：

```python
# ── Simulate trend equity ──
np.random.seed(42)
trend_daily = np.random.normal(0.0005, 0.004, N)
for i in range(6, 25):   trend_daily[i] += np.random.normal(0.0008, 0.001)
...
trend_equity = 1000000.0 * np.exp(np.cumsum(trend_daily))
target_t = 1.0 + 24.96 / 100 * 84 / 252
trend_equity *= target_t / (trend_equity[-1] / 1000000.0)
```

W2 修复（阶段总结 §2.6）仅覆盖了交易明细（`_gen_simulated_trades` → 真实 roundtrip），但**净值曲线模拟完全未触及**。

导致的结果：
1. 对比报告中的**趋势和反转的夏普、年化、回撤等指标**来自硬编码 KNOWN 常量，非真实回测计算结果
2. 报告头部的"回测数据环境说明"已标注"模拟曲线"，与 W2"已修复"的结论矛盾

**修复要求**：
1. `main()` 中趋势/反转净值曲线的随机生成逻辑替换为从回测结果 `BacktestResult.equity_curve` 提取
2. 当 `trend_result`/`reversal_result` 参数为 None 时，应**跳过对应章节或明确标注"未运行回测"**，而不是自动填充模拟数据
3. `KNOWN` 硬编码常量（L222）在支持真实数据后应移除或降级为 fallback

---

### P0-2: `pair_trades_to_roundtrips` 实现与方案设计不符

| 属性 | 值 |
|:----|:----|
| **严重度** | 🔴 中高 — 关键路径算法漏洞（当前 84 天数据未触发，5 年扩展后必然暴露） |
| **涉及文件** | `src/backtest/performance.py` |
| **相关方案项** | 第3项（买卖过程盈利概率） |

**问题描述**：

方案中明确定义了 `TradePair` dataclass 和 FIFO 多队列配对算法（方案 §3），要求：
1. 维护 `long_open_queue` / `short_open_queue` 两个队列
2. 使用 FIFO 规则匹配开仓和平仓
3. 支持**部分平仓**拆分
4. 支持**网格多仓**多重开仓

实际实现（`performance.py` L411 `pair_trades_to_roundtrips`）大幅简化：
- 只维护**一个 `pending_entry` 状态变量**，不是队列
- **部分平仓未实现**：`pending_qty` 只增不减，直到一次卖完才归零
- **加仓时均价处理**：多笔不同价格的开仓合并均价，丢失了各笔持仓的时间信息，FIFO 算法的基础前提不复存在
- 入参期望的 `fills` 格式（`side: BUY/SELL`）与 `TradeRecord` 的格式（`direction: buy/sell/short/cover`）可能不一致

**修复要求**：
1. 按方案设计实现 `build_trade_pairs()` 函数，使用双队列 FIFO 算法
2. 增加部分平仓拆分逻辑
3. 保留现有 `pair_trades_to_roundtrips()` 函数作为兼容 wrapper，但内部调用 `build_trade_pairs()`

---

### P0-3: 迁移后 pytest 单元测试未运行验证

| 属性 | 值 |
|:----|:----|
| **严重度** | 🔴 中 — 迁移的 5 个核心模块 import 路径变更未验证 |
| **涉及文件** | `src/backtest/tests/`（已迁移但未运行） |
| **相关方案项** | 第0项（引擎迁移） |

**问题描述**：

方案第0项要求迁移测试文件并运行 pytest。当前：
- 5 个核心模块已从 `backtest_engine/` 复制到 `src/backtest/`
- 但 `src/backtest/tests/` 目录是否存在？测试文件的 `from backtest_engine.xxx` import 路径是否已更新？
- 验证仅做了 31 项业务级功能检查，**未运行 pytest**

迁移的 5 个模块（benchmark, trade_logger, backtest_engine, order_executor, performance）之间存在 import 交叉引用，任何一条路径变更未被发现，都会在运行时引发 ImportError。

**修复要求**：
1. 确认 `tests/` 已迁移且 import 路径已更新
2. 运行 `cd mozhi_platform && python -m pytest src/backtest/tests/ -v`
3. 将测试结果附入阶段总结

---

## 三、🟡 P1 建议（非阻塞，但值得改进）

### P1-1: 模拟交易回退应输出明确警告

`_get_roundtrips()` 在 `pair_trades_to_roundtrips` 失败或 `backtest_result.trades` 为空时会静默回退到 `_gen_simulated_trades`，**无任何日志或警告**。建议在回退时通过 `logging.warning()` 输出：
> "⚠️ {strategy_name}: 真实交易数据不可用，回退到模拟数据（{sim_count} 笔）"

### P1-2: `KNOWN` 硬编码与真实数据冲突

`generate_comparison.py` L222 的 `KNOWN` 常量在支持真实数据导入后应移除或彻底改为 fallback。当前存在双数据源风险：对比表引用 KNOWN 中的 `win_rate`/`trades`，而其他指标从模拟的 equity_curve 计算，数据流不一致。

### P1-3: 报告模板文件未迁移到新平台

`multi_comparison.md` 和 `grid_full_report.md` 仍保留在旧库 `reports/backtest/`。下一阶段 P4 建议迁移至 `mozhi_platform/src/backtest/reports/templates/`，并更新 `generate_comparison.py` 中的输出路径。

### P1-4: 口径标注应更明确

报告中已包含基准对标口径说明，但未在"买入持有"列的每个单元格标注"（价格收益率，扣除交易成本前）"，防止误导读者认为可直接与策略收益率比较。

### P1-5: `pair_trades_to_roundtrips` 输入格式兼容性

函数期望 `fills` 格式为 `{"side": "BUY"/"SELL"}`，但 `TradeRecord.to_dict()` 使用 `{"direction": "buy"/"sell"/"short"/"cover"}`。这两个格式间的映射未显式处理。建议增加格式转换步骤或统一的 `as_fill_format()` 方法。

---

## 四、决策依据

| 检查项 | 结果 | 说明 |
|:------|:----:|:-----|
| 四项改进功能完整性 | ✅ | 对标/扩展/概率/参数均已编码实现 |
| B1 阻塞问题修复 | ✅ | 模块级副作用已隔离至 `if __name__` |
| W1/W2/W3 警告修复 | ⚠️ 部分 | W2 仅修复交易明细，净值曲线仍为模拟 |
| 代码质量 | ⚠️ | 配对算法简化，区块结构尚可 |
| import/架构合理性 | ⚠️ | 迁移 5 核心模块未运行单元测试验证 |
| 关键路径漏洞 | 🔴 | 配对算法不完整（5 年扩展后暴露） |
| 数据一致性 | 🔴 | 报告部分指标使用模拟值（KNOWN）而非真实回测 |

### 判定结论：**P0**

**处理流程**：

```
当前状态 v4.0 (Step2)
      │
      ▼ ⛔ REVIEW_RESULT=P0
返回 Step1 — 墨衡修复 P0-1 ~ P0-3
      │
      ▼
重新提交 → 墨萱 Step2 复查
      │
      ▼
PASS → 进入 Step3（墨涵汇总）
```

---

## 五、墨衡需修复项汇总

| 编号 | 问题 | 文件 | 优先级 | 期望修复方式 |
|:----:|:-----|:----|:-----:|:------------|
| P0-1 | `main()` 净值曲线模拟 → 真实数据 | `generate_comparison.py` | 🔴 | 替换 `np.random.normal()` 为从回测结果读取 equity_curve |
| P0-2 | 配对算法未实现 FIFO 队列+部分平仓 | `performance.py` | 🔴 | 按方案设计实现 `build_trade_pairs()` + 双队列 + 拆分 |
| P0-3 | 迁移后 pytest 未运行 | `src/backtest/tests/` | 🔴 | 运行并附测试结果 |
| P1-1 | 模拟回退静默警告 | `generate_comparison.py` | 🟡 | 加 logging.warning |
| P1-2 | KNOWN 硬编码清理 | `generate_comparison.py` | 🟡 | 降级为 fallback |
| P1-3 | 报告模板迁移 | `reports/backtest/*.md` | 🟡 | 下阶段迁移 |
| P1-5 | 输入格式映射 | `performance.py` | 🟡 | 显式转换 |

---

## 六、审查元信息

| 角色 | 审查结论 | 时间 |
|:----|:--------:|:----:|
| 墨萱（质量验证） | ⛔ P0 — 驳回，返修 | 2026-05-16 09:11 +08:00 |

> 📝 **审查说明：** 墨衡的执行效率值得肯定，2h20min 覆盖 41h 方案是高效产出。但 P0-1（净值曲线模拟）是一个"看似已修实则未修"的盲区——W2 修复了交易明-细模拟，但净值曲线模拟路径完全不同，需要单独处理。P0-2 的配对算法简化虽然当前不报错，但若扩展到 5 年数据后必然暴-露，在阶段审查中提前发现是止损。本题两项 P0 修复工作量预估不超过 30min，应可快速闭环。
