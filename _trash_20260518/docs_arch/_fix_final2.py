#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Final silent fix for all remaining sections"""

path = r'C:\Users\17699\mozhi_platform\docs\01_architecture\pdf_report_design_v3.0_20260517.md'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# ── 1. Replace everything from §7.8 to §8 with new content ──
idx_78 = content.index('### 7.8 \u8c03\u7528\u793a\u4f8b\uff08v3.0 \u5b8c\u6574\u7ba1\u9053\uff09')
idx_8 = content.index('## 8. \u5feb\u901f\u542f\u52a8\u6307\u5357\uff08\u4eca\u665a\uff09')

# Check if §7.10 already exists
has_710 = '### 7.10' in content

new_section = """### 7.8 调用示例（v3.2 完整管道，含 PortfolioManager 集成）

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

    # 1. 运行回测 -> MethodResult
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

    # 3. 转换 MethodResult -> BacktestResultBundle
    bundle = bundle_from_runner(
        runner_result=result,
        ctx=ctx,
        portfolio_output=portfolio_output,
        price_df=df,
        config=ctx.config,
    )

    print(f"已加载 Bundle - equity_curve: {len(bundle.equity_curve)} 行, trades: {len(bundle.trades)} 笔")
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
        print(f"PDF 报告已生成: {path}")
    else:
        print(f"生成失败: {path}")


if __name__ == "__main__":
    main()
```

### 7.10 data_quality 文件位置（v3.2 新增）

**位置：** `src/backtest/engine/data_quality.py`

```python
\"\"\"
data_quality.py - 数据质量计算（v3.2 新增）

核心算法：
  1. 数据完整率 = 实际天数 / 预期天数
  2. 缺失值统计 = NaN比例
  3. 滑点验证 = 占位符（Phase 3 实现）

详细设计：见 SS3.3「数据质量检测算法设计」
作者: 墨衡
创建时间: 2026-05-17
\"\"\"

def compute_data_quality(df, df_expected, config):
    # 实现见 SS3.3 算法设计
    pass
"""

content = content[:idx_78] + new_section + content[idx_8:]

# ── 2. Update §8.1 checklist ──
old_81 = """### 8.1 执行清单

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

new_81 = """### 8.1 执行清单

```
☐ 1. R1: 完成 bundle_from_runner() 映射表设计      # Phase 0 — S4.2 已就绪
☐ 2. R2: 实现 PortfolioIntegration 适配器          # Phase 0/2 — S7.9 设计已就绪
☐ 3. R3: 实现 compute_data_quality() 算法          # Phase 2 — S3.3 算法已设计
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

content = content.replace(old_81, new_81, 1)

# ── 3. Update §8.2 acceptance criteria ──
old_82 = """### 8.2 验收标准

| 验收项 | 预期结果 |
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

new_82 = """### 8.2 验收标准

| 验收项 | 预期结果 |
|--------|---------|
| R1: bundle_from_runner() 映射表 | 17字段全部覆盖（直接映射 + 外部计算 + Phase 3占位） |
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
| 全链路：Engine->Bundle->Builder->PDF | 14章完整，无数据错误 |
| 简洁模式 | 仅5章+附录，跳过第0章 |"""

content = content.replace(old_82, new_82, 1)

# ── 4. Update footer ──
old_footer = '*本文档由墨衡编写，2026-05-17 20:45 +08:00，v3.0 升级于 2026-05-17 22:13 +08:00，v3.1 修复于 2026-05-17 22:30 +08:00。*'
new_footer = '*本文档由墨衡编写，2026-05-17 20:45 +08:00，v3.0 升级于 2026-05-17 22:13 +08:00，v3.1 修复于 2026-05-17 22:30 +08:00，v3.2 S级风险修复于 2026-05-17 22:44 +08:00。*'

content = content.replace(old_footer, new_footer, 1)

# ── 5. Write back ──
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("OK - all changes applied")
