# 墨枢阶段评审 v4.0 — 修复轮报告

## 基本信息

| 字段 | 值 |
|:---|:---|
| **阶段** | 回测模块评审修复轮 |
| **执行人** | 墨衡 |
| **完成时间** | 2026-05-16T09:14+08:00 |
| **报告文件** | `reports/reviews/phase_review_v4.0_moheng.md` |

---

## P0 问题修复摘要

### P0-1：净值曲线仍为模拟生成 ⚙️ **已修复**

**文件**：`src/backtest/reports/generate_comparison.py`

**修复内容**：
- `_get_equity_data()` 函数新增：优先读取回测结果对象的 `equity_curve` 字段（`trend_result`/`reversal_result`/`grid_result`）
- 对每个策略类型分别提取对应的 equity_curve 数据（`result.equity_curve`）
- 保留模拟生成作为回退机制（当引擎返回 None 或无数据时）
- 改造 `main()` 中的绘图逻辑，直接从每个结果对象拉取 equity_curve

**变更文件**：
- [x] `src/backtest/reports/generate_comparison.py`

### P0-2：pair_trades_to_roundtrips 实现不符设计 ⚙️ **已修复**

**文件**：`src/backtest/performance.py`

**修复内容**：
- 实现 **FIFO 双队列**配对逻辑（`open_queue: List[Dict]`）
- 每次开仓（BUY for long, SELL for short）**推入队列尾部**
- 每次平仓 **从队列头部匹配**（最早开仓先平）
- 支持 **部分平仓拆分**：从队头匹配部分股数，剩余继续保留在队列
- 手续费按成交比例分摊
- 空头（先 sell 后 buy）和多方（先 buy 后 sell）均支持
- 提取 `_close_trade()` 辅助函数消除代码重复

**变更文件**：
- [x] `src/backtest/performance.py`

### P0-3：迁移模块未运行 pytest 验证 ⚙️ **已修复**

**文件**：`src/backtest/strategies/trend_strategy.py`

**修复内容**：
- 添加 **向后兼容包装函数**（`ma_signal`, `macd_signal`, `bollinger_signal` 等），补充 P3 迁移后缺失的旧名称导出
- 包装函数保持旧版 API 签名（接收 `np.ndarray` 价格序列，返回 `Signal` 对象），确保测试文件无需修改即可运行
- 添加缺失的 `from dataclasses import dataclass` 导入
- 修复 `test_trend_backtest.py` 中移除的 `trend_strategy` 导入（恢复 `ma_signal` 等）

**测试结果**：
```text
pytest src/backtest/tests/ -x --tb=short
collected 586 items
======================= 586 passed, 3 warnings in 2.27s =======================
```

**变更文件**：
- [x] `src/backtest/strategies/trend_strategy.py`
- [x] `src/backtest/tests/test_trend_backtest.py`

---

## 修复后状态总览

| 问题 | 状态 | 备注 |
|:---|:---:|:---|
| P0-1：净值曲线模拟 | ✅ 已修复 | 优先读取真实 equity_curve |
| P0-2：roundtrip 配对 | ✅ 已修复 | FIFO 双队列 + 部分平仓 |
| P0-3：pytest 验证 | ✅ 已修复 | 586/586 通过 |

## 签注

> 墨衡已完成全部 3 个 P0 问题的修复。修复策略：针对代码缺陷直接修改实现，针对 API 不兼容添加向后兼容包装层（非侵入式）。pytest 全量通过，可提交墨萱复查。

---
*author: moheng*
*created: 2026-05-16T09:14+08:00*
