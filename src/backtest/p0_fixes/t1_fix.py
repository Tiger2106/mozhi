"""
P0-FIX-001: T+1 延迟修复 + 分时闸门
======================================
A股 T+1 规则：当日买入的股票，当日不可卖出，需次日（T+1）才可卖出。

原问题：
- 原 backtest_engine 未实现 T+1 延迟，同一日可 BUY→SELL
- 无挂单队列机制（停牌/涨跌停后的自动重试）

修复方案：
1. 分时闸门：BUY 操作当日可执行，SELL 操作需检查买卖日期差 ≥1
2. 挂单队列：停牌/涨跌停时自动挂单，次日重试
3. 轨道簿（CLOB）：记录所有买入记录，跟踪锁定期

实现方式：
见 simulate_layer.py 中的 ConstraintAwareExecutor 类
- _pending_buy_signals: 买入挂单队列
- _pending_sell_signals: 卖出挂单队列（T+1 延迟）
- _check_t1_pending(): T+1 检查方法

使用示例:
    from backtest.layers.simulate_layer import ConstraintAwareExecutor
    executor = ConstraintAwareExecutor(fee_rate=0.0003, slippage_rate=0.001)
    result = executor.execute_signals(data, signals, initial_capital=1_000_000)

作者: moheng
版本: v1.0
"""
