#!/usr/bin/env python3
"""Fix §7.8, add §7.9, §7.10, update §8, update footer in the scheme document"""

path = r'C:\Users\17699\mozhi_platform\docs\01_architecture\pdf_report_design_v3.0_20260517.md'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# ─── §7.8: Replace old v3.0 call example with v3.2 ───
old_section78_start = '### 7.8 调用示例（v3.0 完整管道）\n\n'
old_section78_end = '\n\n---\n\n## 8. 快速启动指南（今晚）'

new_section78_content = """### 7.8 调用示例（v3.2 完整管道，含 PortfolioManager 集成）

```python
#!/usr/bin/env python3
\"\"\"v3.2 完整管道示例：从 Engine 到 PDF（含 PortfolioManager 集成）。

注意（v3.2）：MethodBacktestRunner 确认位于 backtest/runners/，产出 MethodResult（11字段），
bundle_from_runner() 接受 MethodResult + 可选的 PortfolioManager 输出 + ctx + price_df。
\"\"\"

from backtest.runners.method_backtest_runner import MethodBacktestRunner
from backtest.engine.backtest_result_bundle import bundle_from_runner
from backtest.engine.portfolio.portfolio_manager import PortfolioManager
from backtest.engine.portfolio_integration import PortfolioIntegration  # v3.2 新增
from backtest.context import StrategyContext
from backtest.pipeline.report_builder import ReportBuilder
from backtest.pipeline.chart_generator import ChartGenerator


def main():
    # 0. 准备数据和上下文
    ctx = StrategyContext(symbol="601857", config={"ma_fast": 5, "ma_slow": 20})
    df = pd.read_parquet("data/601857.parquet")  # OHLCV

    # 1. 运行回测 → MethodResult
    runner = MethodBacktestRunner(method_name="ma_cross", ctx=ctx)
    result = runner.run(df, symbol="601857")

    # 2. 通过 PortfolioIntegration 生成 equity_curve / trades / daily_metrics
    pm_integration = PortfolioIntegration(
        initial_cash=1_000_000.0,
        commission_pct=0.0003,
        slippage_pct=0.001,
    )
    portfolio_output = pm_integration.run(
        method_result=result,
        price_df=df,
        symbol="601857",
    )

    # 3. 转换 MethodResult → BacktestResultBundle
    bundle = bundle_from_runner(
        runner_result=result,
        ctx=ctx,
        portfolio_output=portfolio_output,
        price_df=df,
        config=ctx.config,
    )

    print(f"已加载 Bundle — equity_curve: {len(bundle.equity_curve)} 行, trades: {len(bundle.trades)} 笔")
    print(f"data_quality.rating: {bundle.data_quality.get('rating', 'N/A')}")

    # 4. 创建图表生成器
    chart_gen = ChartGenerator()

    # 5. 创建报告构建器
    bundles = [bundle]
    builder = ReportBuilder(
        bundles=bundles,
        portfolio_bundle=bundle,
        chart_gen=chart_gen,
        output_dir="reports/pdf",
        task_id="bt_weekly_001",
        engine_version="v3.2",
    )

    # 6. 生成完整 PDF
    success, path = builder.render_pdf(
        symbol="601857.SH",
        date="20260517",
        mode="full",
    )

    if success:
        print(f"✅ PDF 报告已生成: {path}")
    else:
        print(f"❌ 生成失败: {path}")


if __name__ == "__main__":
    main()
```

### 7.9 PortfolioManager → Runner 集成设计（v3.2 修复 R2）

**背景：** `MethodBacktestRunner` 仅输出信号（MethodResult.signals），不执行资金模拟；
`PortfolioManager`（`backtest/engine/portfolio/portfolio_manager.py`）已存在但未与 Runner 集成。
Bundle 需要的 equity_curve、trades、daily_metrics 三个字段均无法直接从 MethodResult 获取。

**PortfolioManager 接口调查：**

| Method | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `__init__()` | initial_cash, commission_pct, slippage_pct | — | 初始化仓位管理器 |
| `process_signal()` | signal(-1/0/1), price, symbol | Order | 处理信号，更新现金/持仓，生成订单 |
| `record_equity()` | current_price | None | 记录当前权益到 equity_curve |
| `get_portfolio_value()` | current_price | float | 计算组合市值 |
| `get_total_return()` | — | float | 计算总收益率 |
| `get_peak_drawdown()` | — | float | 计算最大回撤 |
| `summary()` | — | Dict | 汇总报告（cash/trades/return/drawdown） |
| `reset()` | — | None | 重置为初始状态 |

**PortfolioIntegration 适配器设计：**

新建 `backtest/engine/portfolio_integration.py`，封装 PortfolioManager 的逐Bar驱动逻辑：

```python
"""
portfolio_integration.py — PortfolioManager 集成适配器（v3.2 新增）

将 MethodResult 的信号序列 + 价格数据驱动 PortfolioManager，
产出 bundle_from_runner() 需要的 equity_curve / trades / daily_metrics。

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.engine.portfolio.portfolio_manager import PortfolioManager
from backtest.methods.base import MethodResult


@dataclass
class PortfolioOutput:
    \"\"\"PortfolioManager 运行产出，供 bundle_from_runner() 消费\"\"\"
    equity_curve: pd.DataFrame          # 列: date, equity, daily_return, cumulative_return
    trades: List[Dict[str, Any]]        # 成交记录列表（可转为 Bundle.TradePair）
    daily_metrics: pd.DataFrame         # 列: date, turnover, position_value, cash


class PortfolioIntegration:
    \"\"\"PortfolioManager 集成适配器

    将 MethodResult 中的信号序列 + 价格数据逐行驱动 PortfolioManager，
    自动构建 equity_curve / trades / daily_metrics。

    用法：
        pi = PortfolioIntegration(initial_cash=1_000_000.0)
        output = pi.run(method_result, price_df)
        bundle.equity_curve = output.equity_curve
    \"\"\"

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission_pct: float = 0.0003,
        slippage_pct: float = 0.001,
    ):
        self.pm = PortfolioManager(
            initial_cash=initial_cash,
            commission_pct=commission_pct,
            slippage_pct=slippage_pct,
        )

    def run(
        self,
        method_result: MethodResult,
        price_df: pd.DataFrame,
        symbol: str = "DEFAULT",
    ) -> PortfolioOutput:
        \"\"\"对 MethodResult 中的每个信号 + 对应价格，驱动 PM

        Args:
            method_result: 回测运行结果
            price_df: 原始 OHLCV DataFrame（需含 'close' 列）
            symbol: 标的代码

        Returns:
            PortfolioOutput: 含 equity_curve / trades / daily_metrics
        \"\"\"
        signals = method_result.signals

        # ── 确定价格来源 ──
        if "close" in price_df.columns:
            prices = price_df["close"]
        else:
            prices = pd.Series(index=signals.index, data=0.0)

        # ── 逐Bar驱动 ──
        for idx in signals.index:
            signal = signals.loc[idx, "signal"] if "signal" in signals.columns else 0
            price = prices.loc[idx] if idx in prices.index else 0.0

            self.pm.process_signal(int(signal), float(price), symbol=symbol)
            self.pm.record_equity(float(price))

        # ── 构建 equity_curve DataFrame ──
        equity_values = self.pm.equity_curve
        if equity_values:
            equity_curve = pd.DataFrame({
                "date": signals.index[:len(equity_values)],
                "equity": equity_values,
            })
            equity_curve["daily_return"] = equity_curve["equity"].pct_change().fillna(0.0)
            equity_curve["cumulative_return"] = (
                equity_curve["equity"] / equity_curve["equity"].iloc[0] - 1
            )
        else:
            equity_curve = pd.DataFrame(columns=["date", "equity", "daily_return", "cumulative_return"])

        # ── 构建 trades 列表 ──
        trades = []
        for t in self.pm.trades:
            trades.append({
                "action": t.action,
                "symbol": t.symbol,
                "price": t.price,
                "shares": t.shares,
                "cash_after": t.cash_after,
                "position_after": t.position_after,
                "timestamp": t.timestamp,
            })

        # ── 构建 daily_metrics DataFrame ──
        if equity_values:
            daily_metrics = pd.DataFrame({
                "date": signals.index[:len(equity_values)],
                "turnover": 0.0,  # ⚠️ 当前无法从PM获取逐日换手率
                "position_value": [0.0] * len(signals.index[:len(equity_values)]),
            })
        else:
            daily_metrics = pd.DataFrame(columns=["date", "turnover", "position_value"])

        return PortfolioOutput(
            equity_curve=equity_curve,
            trades=trades,
            daily_metrics=daily_metrics,
        )

    @property
    def pm_summary(self) -> Dict[str, Any]:
        \"\"\"获取 PortfolioManager 汇总报告\"\"\"
        return self.pm.summary()
```

**集成方式（Phase 2 新增步骤）：**

在 `bundle_from_runner()` 被调用前，调用方先创建一个 `PortfolioIntegration` 实例，
调用 `run(method_result, price_df)` 获取 `PortfolioOutput`，
然后作为 `portfolio_output` 参数传给 `bundle_from_runner()`。
流程图：

```
BacktestEngine
  → MethodBacktestRunner.run(df) → MethodResult (signals/indicators/statistics)
  → PortfolioIntegration.run(method_result, price_df) → PortfolioOutput
      ├─ equity_curve    → bundle.equity_curve
      ├─ trades          → bundle.trades
      └─ daily_metrics   → bundle.daily_metrics
  → bundle_from_runner(method_result, ctx, portfolio_output, price_df, config)
  → BacktestResultBundle → ReportBuilder
```

**Phase 2 中新增集成步骤：**
1. 新建 `backtest/engine/portfolio_integration.py`（含 PortfolioOutput + PortfolioIntegration）
2. 在 `bundle_from_runner()` 中接收 portfolio_output 参数
3. 在完整管道调用代码中显式创建 PortfolioIntegration 并调用
4. 单元测试 `test_portfolio_integration.py`（Mock MethodResult + 构造价格序列，验证 equity_curve 长度和完整性）

**run_batch() 的兼容性说明：**
`MethodBacktestRunner.run_batch()` 的签名是 `run_batch(data_dict: Dict[str, pd.DataFrame]) -> Dict[str, MethodResult]`，
**不**直接接受 PortfolioManager 配置。集成方式为：对每个频道的 MethodResult 单独创建 PortfolioIntegration 实例，
逐频道生成 PortfolioOutput，再统一合并到 Bundles。

### 7.10 data_quality 文件位置（v3.2 新增）

**位置：** `src/backtest/engine/data_quality.py`

```python
"""
data_quality.py — 数据质量计算（v3.2 新增）

核心算法：
  1. 数据完整率 = 实际天数 / 预期天数
  2. 缺失值统计 = NaN比例
  3. 滑点验证 = 占位符（Phase 3 实现）

详细设计：见 §3.3「数据质量检测算法设计」
作者: 墨衡
创建时间: 2026-05-17
"""

def compute_data_quality(df, df_expected, config):
    # 实现见 §3.3 算法设计
    ...
```

---

## 8. 快速启动指南（今晚）"""

old_all = old_section78_start + content[
    content.index(old_section78_start) + len(old_section78_start):
    content.index(old_section78_end)
]

# Replace from §7.8 start to before §8
idx_start = content.index(old_section78_start)
idx_end = content.index('---\n\n## 8. 快速启动指南（今晚）', idx_start)

content_new = content[:idx_start] + new_section78_content + content[idx_end:]

# ─── Update §8.1 执行清单 ───
old_checklist = """### 8.1 执行清单

```
☐ 1. 确认 MethodBacktestRunner 产出契约       # Phase 0 — 明确 Runner 输出格式
☐ 2. 创建 backtest_result_bundle.py          # Phase 1 — 统一数据源
☐ 3. 创建 metrics_registry.py                # Phase 1 — 统一指标
☐ 4. 创建 report_builder.py                  # Phase 1 — 骨架
☐ 5. 实现 _chapter_0_data_quality()          # Phase 2 — 数据质量声明
☐ 6. 修复现有章节数据源读取                    # Phase 2
☐ 7. 重构第六章〜第十三章                      # Phase 3
☐ 8. 编写单元测试                              # Phase 4
☐ 9. 全链路端到端测试                          # Phase 4
☐ 10. CSS 样式打磨                            # Phase 5
```"""

new_checklist = """### 8.1 执行清单

```
☐ 1. R1: 完成 bundle_from_runner() 映射表设计      # Phase 0 — §4.2 已就绪
☐ 2. R2: 实现 PortfolioIntegration 适配器          # Phase 0/2 — §7.9 设计已就绪
☐ 3. R3: 实现 compute_data_quality() 算法          # Phase 2 — §3.3 算法已设计
☐ 4. 创建 backtest_result_bundle.py               # Phase 1 — 统一数据源
☐ 5. 创建 metrics_registry.py                     # Phase 1 — 统一指标
☐ 6. 创建 report_builder.py                       # Phase 1 — 骨架
☐ 7. 创建 portfolio_integration.py                # Phase 2 — PortfolioManager 集成
☐ 8. 创建 data_quality.py                         # Phase 2 — 数据质量计算
☐ 9. 实现 _chapter_0_data_quality()               # Phase 2 — 数据质量声明
☐ 10. 修复现有章节数据源读取                       # Phase 2
☐ 11. 重构第六章〜第十三章                         # Phase 3
☐ 12. 编写单元测试                                # Phase 4
☐ 13. 全链路端到端测试                            # Phase 4
☐ 14. CSS 样式打磨                                # Phase 5
```"""

content_new = content_new.replace(old_checklist, new_checklist)

# ─── Update §8.2 验收标准 ───
old_accept = """| 验收项 | 预期结果 |
|--------|---------|
| BacktestResultBundle 所有字段可读 | 各字段类型正确，data_quality 默认值可用 |
| metrics_registry 所有指标可查 | `get_metric_info("sharpe")` 返回定义字典 |
| 第0章数据质量声明 | 表格形式展示，数据源/周期/完整率等 10 项完整 |
| 第六章交易行为分析 | 含交易记录表+盈亏分布图+持仓分布图+连盈连亏序列 |
| 第七章市场状态适应性 | By Regime + 高波/低波动 + 成交量 + 板块轮动 |
| 第九章参数稳定性评分 | RobustScore 5维度加权计算 |
| 第十章 Walk Forward | 滚动窗口验证表+稳定性统计 |
| 第十一章组合融合 | 单策略 vs 组合对比表 + 改善幅度 |
| 第十二章 Pain Index | Avg/Worst Recovery Days + Underwater Ratio + Pain Index |
| 第十三章评分矩阵 | 6维评分 + Total Score + 评级 |
| 全链路：Engine→Bundle→Builder→PDF | 14章完整，无数据错误 |
| 简洁模式 | 仅5章+附录，跳过第0章 |"""

new_accept = """| 验收项 | 预期结果 |
|--------|---------|
| R1: bundle_from_runner() 映射表 | 17字段全部覆盖（✅直接映射 + ⚠️外部计算 + ❌Phase 3占位） |
| R2: PortfolioIntegration 可产出 equity_curve | 从 MethodResult + price_df 生成，长度与信号序列一致 |
| R2: PortfolioIntegration 可产出 trades | 成交记录列表，含 action/price/shares/cash_after |
| R2: PortfolioIntegration 可产出 daily_metrics | 最少含 date/turnover/position_value 三列 |
| R3: compute_data_quality() 可计算完整率 | 实际天数/预期天数，精度到小数点后1位 |
| R3: compute_data_quality() 可统计 NaN | 各列缺失比例百分数，精度到小数点后2位 |
| R3: 滑点验证为占位符 | slippage_validated=False，slippage_note 有说明文字 |
| BacktestResultBundle 所有字段可读 | 各字段类型正确，data_quality 可实现缺省计算 |
| metrics_registry 所有指标可查 | `get_metric_info("sharpe")` 返回定义字典 |
| 第0章数据质量声明 | 表格形式展示，数据源/周期/完整率等 10 项完整 |
| 第六章交易行为分析 | 含交易记录表+盈亏分布图+持仓分布图+连盈连亏序列 |
| 第七章市场状态适应性 | By Regime + 高波/低波动 + 成交量 + 板块轮动 |
| 第九章参数稳定性评分 | RobustScore 5维度加权计算 |
| 第十章 Walk Forward | 滚动窗口验证表+稳定性统计 |
| 第十一章组合融合 | 单策略 vs 组合对比表 + 改善幅度 |
| 第十二章 Pain Index | Avg/Worst Recovery Days + Underwater Ratio + Pain Index |
| 第十三章评分矩阵 | 6维评分 + Total Score + 评级 |
| 全链路：Engine→Bundle→Builder→PDF | 14章完整，无数据错误 |
| 简洁模式 | 仅5章+附录，跳过第0章 |"""

content_new = content_new.replace(old_accept, new_accept)

# ─── Update footer timestamp ───
old_footer = "*本文档由墨衡编写，2026-05-17 20:45 +08:00，v3.0 升级于 2026-05-17 22:13 +08:00，v3.1 修复于 2026-05-17 22:30 +08:00。*"
new_footer = "*本文档由墨衡编写，2026-05-17 20:45 +08:00，v3.0 升级于 2026-05-17 22:13 +08:00，v3.1 修复于 2026-05-17 22:30 +08:00，v3.2 S级风险修复于 2026-05-17 22:44 +08:00。*"

content_new = content_new.replace(old_footer, new_footer)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content_new)

print("✅ All changes applied")
print(f"Content length: {len(content_new)} chars")
print(f"Contains PortfolioIntegration: {'PortfolioIntegration' in content_new}")
print(f"Contains compute_data_quality: {'compute_data_quality' in content_new}")
print(f"Contains section 7.9: {'7.9 PortfolioManager' in content_new}")
print(f"Contains section 7.10: {'7.10 data_quality' in content_new}")
print(f"Footer updated: {'v3.2 S级风险修复' in content_new}")
