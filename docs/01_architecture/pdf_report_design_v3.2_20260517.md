# 量化研究平台架构 · PDF报告生成方案设计

> 作者：墨衡（MoHeng）
> 任务ID：`pdf_report_design`
> 创建时间：2026-05-17 20:45 +08:00
> 版本：v3.2
> 状态：定稿
> 更新说明：v3.0 核心架构从"回测报告生成器"升级为"量化研究平台架构"；
> 新增 BacktestResultBundle 统一数据源与 metrics_registry 指标注册表；
> 章节从13章扩展至14章（含第0章数据质量声明）；
> 第六章/第七章/第十章/第十一章/第十二章/第十三章 全面重构；
> ReportBuilder 分层：Engine → BacktestResultBundle → ReportBuilder → PDF/HTML/Feishu/Knowledge；
> 新增 Future Dashboard 集成点
>
> ——v3.1 修复（2026-05-17 22:30）——
> ——v3.2 S级风险修复（2026-05-17 22:44）——
> R1: 实际调查MethodResult/Runner输出结构，新增bundle_from_runner()完整映射表；
> R2: PortfolioManager集成设计，补充equity_curve/trades/daily_metrics生成方案；
> R3: 第0章数据质量算法设计（完整率/NaN统计/滑点验证）
> P0: Markdown 依赖修正：安装环境发现 `markdown-it-py 4.0.0` 已就位，替代 `markdown` 库，零新增依赖；
> 已有组件调查：`report_renderer.py` 是纯 Python Markdown 模板引擎（非 Markdown→HTML 转换器），作为各章节 Markdown 内容生成器保留；
> P1: 文档声明同步修正（~5.5h→~8h 工时、MethodBacktestRunner 状态修正）

---

## 目录

0. 已知积累（本次方案的立足点）
1. 技术选型对比与推荐
2. 数据流设计
3. 报告模板设计
4. 组件设计（report_generator.py / backtest_result_bundle.py / metrics_registry.py）
5. 预估工时
6. 依赖检查
7. 与现有系统的集成点
8. 附录：快速启动指南

---

## 0. 已知积累（本次方案的立足点）

在动手设计前，盘点已有的可直接复用的组件（含 v3.1 实际状态核查）：

| 组件 | 路径 | 状态 | 复用方式 |
|------|------|------|---------|
| **ChartGenerator** | `backtest/pipeline/chart_generator.py` | ✅ 已完成 | 生成 matplotlib 图表（净值曲线/热力图/回撤/信号分布），直接调用 |
| **async_pdf_task.py** | `backtest/pipeline/async_pdf_task.py` | ✅ 已完成 | Edge headless → HTML→PDF，直接调用 `generate_pdf()` |
| **KnowledgeAnalyzer** | `backtest/engine/knowledge_analyzer.py` | ✅ 已完成 | 纯计算分析，输出结构化 Markdown 报告 |
| **ReportRenderer** | `backtest/pipeline/report_renderer.py` | ✅ 已完成 | 模板引擎渲染 Markdown，含变量替换和块循环 |
| **BitableSync** | `backtest/engine/bitable_sync.py` | ✅ 已完成 | Bitable 附件上传需扩展 |
| **MethodBacktestRunner** | `backtest/runners/method_backtest_runner.py` | ✅ **已完成** | 统一回测运行器（A/B双模式），输出 MethodResult（含signals/indicators/statistics/params），含 run_batch() 多时间框架批量运行接口 |
| **MethodResult** | `backtest/methods/base.py:132` | ✅ **已完成** | 执行结果dataclass，11个字段（signals/indicators/method_name/params/statistics/completed_time/duration_ms/errors/metadata + 3 auto-calc: n_bars/n_signals/signal_ratio），约30%字段可直接注入Bundle |
| **PortfolioManager** | `backtest/engine/portfolio/portfolio_manager.py` | ✅ **已完成** | 仓位管理桥接，接收信号→生成订单→更新持仓→记录权益曲线，提供 process_signal()/record_equity()/summary() 接口 |
| **metrics_registry** | `src/metrics/metrics_registry.py` | ◐ 新组件（**待新建**，`src/metrics/` 目录不存在） | 统一指标口径，文档定义 20 个指标（return 3 + risk 5 + risk_adjusted 3 + trade 4 + recovery 3 + info 2） |

#### MethodResult → BacktestResultBundle 字段可达性调查（v3.2 新增）

实际核查 `MethodResult` dataclass（`backtest/methods/base.py:132`）与 `BacktestResultBundle` 17字段，Mapping 可达性如下：

| Bundle字段 | 数据类型 | MethodResult来源 | 可达性 | 备注 |
|:----------:|:--------:|:----------------:|:------:|------|
| `run_id` | str | ❌ 无 | ❌ 未定义 | 需在Runner run()参数中新增或从ctx生成 |
| `strategy_name` | str | ❌ 无 | ❌ 未定义 | 需从StrategyContext.strategy_name提取 |
| `method_name` | str | `result.method_name` | ✅ 可用 | 直接映射 |
| `symbol` | str | `ctx.symbol` 或 run()参数 | ✅ 可用 | 从StrategyContext提取 |
| `start_date` | str | `signals.index[0]` → str | ✅ 可用 | 从信号索引第一个日期推算 |
| `end_date` | str | `signals.index[-1]` → str | ✅ 可用 | 从信号索引最后一个日期推算 |
| `params` | Dict | `result.params` | ✅ 可用 | 直接映射 |
| `equity_curve` | pd.DataFrame | ❌ 无 | ⚠️ 需计算 | 需要PortfolioManager从信号序列+价格数据生成（见§7.9） |
| `benchmark_curve` | pd.DataFrame | ❌ 无 | ⚠️ 需计算 | 需要原始价格数据生成buy&hold曲线 |
| `trades` | List[TradePair] | ❌ 无 | ⚠️ 需计算 | 需要PortfolioManager从信号序列生成成交记录（见§7.9） |
| `daily_metrics` | pd.DataFrame | ❌ 无 | ⚠️ 需计算 | 需要PortfolioManager逐日跟踪+原始OHLCV指标（见§7.9） |
| `regime_labels` | pd.DataFrame | ❌ 无 | ❌ 未定义 | 需增加市场状态分类算法或外部输入 |
| `parameter_scan` | pd.DataFrame | ❌ 无 | ❌ 未定义 | 需新增参数扫描自动化模块（Phase 3） |
| `risk_events` | List[RiskEvent] | ❌ 无 | ❌ 未定义 | 需新增风控事件检测（Phase 3） |
| `insights` | List[KnowledgeEntry] | KnowledgeBridge | ✅ 可用 | KnowledgeBridge.harvest() 已集成在Runner.run()中 |
| `summary_metrics` | Dict[str, Any] | `result.statistics`（部分） | ⚠️ 需计算 | 部分可来自statistics（n_bars/n_signals），其余需从equity_curve/trades计算 |
| `data_quality` | Dict | ❌ 无 | ⚠️ 需计算 | 需设计data_quality计算逻辑（见§3.3数据质量算法设计） |

**结论：** 17个Bundle字段中，7个可直接从MethodResult/Context提取（✅），7个需通过额外组件计算（⚠️），3个在Phase 3前未定义（❌）。**bundle_from_runner()** 核心职责是将MethodResult中的可用字段直接映射，同时为缺失字段提供计算来源的占位钩子。

**核心架构变更**：v2.0 中 ReportGenerator 的输入为 `(method, method_result)` 来自 KnowledgeAnalyzer；v3.0 升级为 **BacktestResultBundle** 统一数据源——Engine → MethodBacktestRunner → BacktestResultBundle → ReportBuilder，所有章节均从该 Bundle 读取，禁止独立计算。

**报告结构优势**：v3.0 的 14 章已形成**完整闭环**——基础绩效 → 风险分析 → 交易行为分析 → 参数稳定性 → 市场状态适应性 → 知识提炼 → **策略评级**。这是私募CTA研究框架和多因子策略评估框架的标准路径，而非单纯

---

## 1. 技术选型对比与推荐

### 1.0 已有组件与运行环境调查（v3.1 新增）

在技术选型前，对当前运行环境和已有组件进行了实际核查：

**Python 包核查：**
| 包名 | 安装状态 | 版本 | 用途 |
|------|:--------:|:----:|------|
| `markdown-it-py` | ✅ **已安装** | 4.0.0 | CommonMark 标准的 Markdown→HTML 转换器，可直接替代 `markdown` 库 |
| `markdown` | ❌ **未安装** | — | 方案原拟依赖的 Markdown→HTML 转换库 |

**结论：** 系统已安装 `markdown-it-py`（与 `markdown` 功能等价），可直接用于 Markdown→HTML 转换，无需安装额外的 `markdown` 包。

**既有渲染器核查：**
| 组件 | 路径 | 功能范围 | 能否替代 Markdown→HTML？ |
|------|------|:--------:|:------------------------:|
| **ReportRenderer** | `backtest/pipeline/report_renderer.py` | 纯 Python 模板引擎，使用 `{{var}}` / `{{#each}}` / `{{#if}}` 语法，**输出 Markdown 字符串** | ❌ 不能。它生成 Markdown 内容，不执行 Markdown→HTML 转换 |

**结论：** `report_renderer.py` 作为已有组件，可作为各章节 Markdown 内容生成的模板引擎保留，但 PDF 管道仍需要额外的 Markdown→HTML 转换步骤。该步骤由 `markdown-it-py` 完成。

### 1.1 候选方案对比

| 维度 | 方案A: weasyprint | 方案B: reportlab | 方案C: Edge headless (推荐) | 方案D: pdfkit (wkhtmltopdf) |
|------|:-:|:-:|:-:|:-:|
| **当前已存组件可用度** | 需新建 | 需新建 | **80% 已有** | 50% 已有 |
| **图表支持** | 内嵌 SVG/PNG | 需手绘 | **已有 ChartGenerator 出图** | 同左 |
| **中文支持** | 需指定系统字体 | 需嵌入字体文件 | **Edge 原生支持** | 需配置中文字体 |
| **表格控制** | CSS + HTML | 手拼 Table | **HTML 自动渲染** | 同左 |
| **安装依赖** | weasyprint + GTK | reportlab | **零额外依赖** | pdfkit + wkhtmltopdf |
| **跨平台** | 需 GTK 运行时 | 纯 Python | **仅限 Windows (Edge)** | 需安装 wkhtmltopdf |
| **生成速度 (10页)** | ~3s | ~2s | ~5s (Edge 启动) | ~4s |
| **页面控制** | CSS @page | 精确到 pt | **CSS @page 打印** | CSS @page |
| **维护成本** | 中 | 高（手拼布局） | **低（Edge 自动更新）** | 低（项目停滞久） |

### 1.2 推荐方案：C — Edge headless 管道

**选择理由（按优先级排列）：**

1. **零额外安装**：ChartGenerator + async_pdf_task 已就位，Edge 是 Windows 标配，无需安装任何新包
2. **HTML 中间格式可调试**：生成 HTML 后可直接用浏览器查看，无需每次生成 PDF
3. **CSS 控制布局**：熟悉 HTML/CSS 的团队可快速调整模板样式
4. **图表独立渲染**：matplotlib 出图 → 内嵌 HTML → Edge 打印，图层分离互不干扰
5. **中文零配置**：Edge 原生支持中文字体渲染

**适用场景限制：**
- 仅限 Windows 环境（目标系统是 Windows，无跨平台需求）
- 需要 Edge/Chromium 安装（已有）

### 1.3 方案路线图

```
当前 → 方案C（Edge headless，今晚可落地方案）
  ↓
未来 → 方案A（weasyprint，如果需要跨平台或更快的生成速度）
```

---

## 2. 数据流设计

### 2.1 全流程图（v3.0 重构）

```
┌──────────────────┐
│   回测引擎        │
│  (BacktestEngine) │
└────────┬─────────┘
         │ MethodBacktestRunner.run()
         ▼
┌──────────────────────────────────┐
│  BacktestResultBundle (统一数据源) │  ← v3.0 新增核心
│  ┌────────────────────────────┐  │
│  │ run_id, strategy_name,    │  │
│  │ method_name, symbol,      │  │
│  │ start_date, end_date,    │  │
│  │ params,                   │  │
│  │ equity_curve,             │  │
│  │ benchmark_curve,          │  │
│  │ trades,                   │  │
│  │ daily_metrics,            │  │
│  │ regime_labels,            │  │
│  │ parameter_scan,           │  │
│  │ risk_events,              │  │
│  │ insights,                 │  │
│  │ summary_metrics,          │  │
│  │ data_quality              │  │
│  └────────────────────────────┘  │
└────────┬─────────────────────────┘
         │
         ├─────────────────────────────────────┐
         │                                     │
         ▼                                     ▼
┌──────────────────┐              ┌─────────────────────┐
│  ReportBuilder    │              │  KnowledgeSearch     │
│  (v3.0 新增分层)  │              │  (已有 + 扩展)        │
│  ┌─────────────┐ │              └─────────────────────┘
│  │ PDF Renderer│ │                            │
│  ├─────────────┤ │                            ▼
│  │ HTML Render │ │              ┌─────────────────────┐
│  ├─────────────┤ │              │  Future Dashboard    │
│  │ Feishu      │ │              │  (v3.0 新增集成点)    │
│  │ Renderer    │ │              └─────────────────────┘
│  ├─────────────┤ │
│  │ Knowledge   │ │
│  │ Renderer    │ │
│  └─────────────┘ │
└──────────────────┘
         │
         ▼
┌────────────────┐
│ PDF / HTML /   │
│ Feishu /       │
│ Knowledge DB   │
└────────────────┘
```

### 2.2 分层架构（ReportBuilder）

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 6: 输出层                                                 │
│  PDF/HTML/Feishu Message/Knowledge Entry                      │
└──────────────────────────────────────────────────────────────┘
                           ▲
┌──────────────────────────────────────────────────────────────┐
│ Layer 5: 渲染层（ReportBuilder 按 owner 指定分层）               │
│  ReportBuilder                                                │
│  ├─ PDFRenderer       — 完整PDF（Edge headless）              │
│  ├─ HTMLRenderer      — 调试用HTML                            │
│  ├─ FeishuRenderer    — 飞书摘要消息                           │
│  └─ KnowledgeRenderer — 回测驱动的知识条目输出                  │
└──────────────────────────────────────────────────────────────┘
                           ▲
┌──────────────────────────────────────────────────────────────┐
│ Layer 4: 分析计算层                                            │
│  从 BacktestResultBundle 读取原始数据，调用 metrics_registry    │
│  计算各章节需要的衍生指标                                       │
│  - ChapterMetrics.metrics_data()                              │
│  - TradeAnalysis.analyze()                                    │
│  - RiskAnalysis.analyze()                                     │
│  - RegimeAnalysis.analyze()                                   │
└──────────────────────────────────────────────────────────────┘
                           ▲
┌──────────────────────────────────────────────────────────────┐
│ Layer 3: 数据契约层                                             │
│  BacktestResultBundle ← 回测引擎输出，所有消费方统一从此读取            │
└──────────────────────────────────────────────────────────────┘
                           ▲
┌──────────────────────────────────────────────────────────────┐
│ Layer 2: 回测执行层                                            │
│  MethodBacktestRunner 执行回测，产出 BacktestResultBundle      │
└──────────────────────────────────────────────────────────────┘
                           ▲
┌──────────────────────────────────────────────────────────────┐
│ Layer 1: 回测引擎层                                            │
│  BacktestEngine 调度各方法回测                                  │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 数据格式转换流

```
BacktestResultBundle (pd.DataFrame / 结构化对象)
  → metrics_registry.md_to_html()
  → ChapterMetrics (各章节衍生指标计算)
  → ReportBuilder.render()
       ├─ PDF:  Markdown → HTML (内嵌图表 data URI) → Edge headless PDF
       ├─ HTML: Markdown → HTML (调试用)
       ├─ Feishu: Markdown → 飞书消息卡片
       └─ Knowledge: 结构化知识条目写入 Knowledge DB
```

---

## 3. 报告模板设计

### 3.1 报告结构总览（14章+附录）

v2.0 的13章结构已扩展至 **14章+附录**，核心变更：

- **★ 第0章**「数据质量声明」新增——机构报告必备
- **第六章**「交易行为分析」重构——合并原六+七，新增盈亏分布+持仓时间+连盈连亏
- **第七章**「市场状态适应性」重构——By Regime/高波动低波动/成交量/板块轮动
- **第九章**「参数敏感性」——增加参数稳定性评分（RobustScore）
- **第十章**「样本内外对比」——增加Walk Forward Analysis
- **第十一章**「策略相关性矩阵」——增加组合资金融合模拟
- **第十二章**「连续亏损与回撤恢复」——增加Pain Index等指标
- **第十三章**「T1评级」——改为多维评分矩阵

```
┌──────────────────────────────────────────────┐
│  封面页 (Cover Page)                           │
├──────────────────────────────────────────────┤
│  目录页 (TOC - 超链接导航)                      │
├──────────────────────────────────────────────┤
│  ★ 第0章 数据质量声明（新增）                    │
├──────────────────────────────────────────────┤
│  一、回测参数表                                │
├──────────────────────────────────────────────┤
│  二、净值曲线（全页宽图）                       │
├──────────────────────────────────────────────┤
│  三、回撤曲线+月度收益热力图                    │
├──────────────────────────────────────────────┤
│  四、指标总表                                 │
├──────────────────────────────────────────────┤
│  五、K线图+买卖点位                            │
├──────────────────────────────────────────────┤
│  六、交易行为分析（重构：盈亏分布+持仓时间+连盈连亏）│
├──────────────────────────────────────────────┤
│  七、市场状态适应性（重构）                      │
├──────────────────────────────────────────────┤
│  ★ 八、知识库提炼（保留7个子节）                 │
├──────────────────────────────────────────────┤
│  ★ 九、参数敏感性分析 + 稳定性评分               │
├──────────────────────────────────────────────┤
│  ★ 十、样本内外对比 + Walk Forward Analysis     │
├──────────────────────────────────────────────┤
│  ★ 十一、策略相关性矩阵 + 组合资金融合模拟       │
├──────────────────────────────────────────────┤
│  ★ 十二、连续亏损与回撤恢复 + Pain Index        │
├──────────────────────────────────────────────┤
│  ★ 十三、T1评级结论 — 多维评分矩阵               │
├──────────────────────────────────────────────┤
│  附录                                         │
└──────────────────────────────────────────────┘
```

### 3.2 HTML/CSS 模板结构

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  /* ── 打印页面设置 ── */
  @page { size: A4; margin: 2cm 2.5cm; }

  /* ── 封面样式 ── */
  .cover-page {
    page-break-after: always;
    display: flex; flex-direction: column;
    justify-content: center; align-items: center;
    height: 100vh;
  }
  .cover-title { font-size: 28pt; font-weight: bold; margin-bottom: 20px; }
  .cover-subtitle { font-size: 16pt; color: #666; }

  /* ── 正文样式 ── */
  body { font-family: 'Microsoft YaHei', sans-serif; font-size: 11pt; line-height: 1.6; color: #333; }
  h1 { font-size: 20pt; color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 8px; }
  h2 { font-size: 16pt; color: #16213e; margin-top: 24px; }
  h3 { font-size: 13pt; color: #0f3460; margin-top: 16px; }

  table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 10pt; }
  th { background: #1a1a2e; color: white; padding: 8px; text-align: center; }
  td { padding: 6px 8px; border: 1px solid #ddd; text-align: center; }
  tr:nth-child(even) { background: #f8f9fa; }

  img.chart { width: 100%; max-width: 700px; display: block; margin: 16px auto; }

  .two-column { display: flex; gap: 16px; }
  .two-column > * { flex: 1; }

  .metric-box {
    background: #f0f4f8; border-left: 4px solid #e94560;
    padding: 12px; margin: 16px 0; font-size: 10pt;
  }

  .page-break { page-break-before: always; }

  /* ── 风险标注 ── */
  .risk-low { color: #2ecc71; }
  .risk-medium { color: #f39c12; }
  .risk-high { color: #e74c3c; }

  /* ── 数据质量声明 ── */
  .data-quality-table td:first-child { font-weight: bold; text-align: right; width: 30%; }

  /* ── 交易行为分析 ── */
  .histogram { width: 100%; height: 200px; background: #f0f4f8; margin: 12px 0; }
  .streak-sequence { font-size: 9pt; word-spacing: 6px; }

  /* ── 参数稳定性 ── */
  .robust-score { font-size: 24pt; font-weight: bold; color: #16213e; text-align: center; }
  .robust-dimension { display: inline-block; margin: 8px 16px; text-align: center; }

  /* ── Walk Forward ── */
  .wf-window { border: 1px solid #ddd; padding: 4px; margin: 2px; display: inline-block; font-size: 8pt; }
  .wf-train { background: #d4edda; }
  .wf-test { background: #fff3cd; }

  /* ── 组合资金融合 ── */
  .portfolio-compare th { background: #e94560; }

  /* ── Pain Index ── */
  .pain-high { color: #e74c3c; }
  .pain-medium { color: #f39c12; }
  .pain-low { color: #2ecc71; }

  /* ── 多维评分矩阵 ── */
  .score-matrix th { background: #16213e; }
  .score-matrix .score-value { font-size: 13pt; font-weight: bold; }
  .score-matrix .best-score { background: #d4edda; }
  .score-matrix .worst-score { background: #f8d7da; }
  .total-score { font-size: 18pt; font-weight: bold; text-align: center; padding: 16px; }

  /* ── 附录注释 ── */
  .appendix { font-size: 9pt; color: #888; }
  .disclaimer { font-size: 8pt; color: #aaa; margin-top: 30px; }
</style>
</head>
<body>
  <!-- 封面 -->
  <div class="cover-page">
    <h1 class="cover-title">回测分析报告</h1>
    <p class="cover-subtitle">Backtest Analysis Report</p>
    <p>标的: {symbol} | 生成时间: {generated_time}</p>
    <p>数据来源: BacktestResultBundle v3.0</p>
    <p>引擎版本: {engine_version}</p>
  </div>

  <!-- 正文由 ReportBuilder 按章节动态生成 -->
  {CONTENT}

</body>
</html>
```

### 3.3 各章详细设计（14章+附录）

---

#### ★ 第0章：数据质量声明（新增，机构报告必备）

```html
<!-- 第0章：数据质量声明 -->
<div class="page-break">
<h2>★ 第0章 数据质量声明</h2>
<p class="metric-box">本章声明模板基于回测环境实际配置自动填充，所有数据项来自 BacktestResultBundle.data_quality 字段。</p>

<table class="data-quality-table">
<tr><td>数据源</td><td>{data_quality.source}</td></tr>
<tr><td>数据周期</td><td>{data_quality.period}</td></tr>
<tr><td>是否复权</td><td>{data_quality.adjusted}</td></tr>
<tr><td>缺失值处理</td><td>{data_quality.nan_handling}</td></tr>
<tr><td>滑点模型</td><td>{data_quality.slippage_model}</td></tr>
<tr><td>手续费</td><td>{data_quality.commission}</td></tr>
<tr><td>是否真实成交</td><td>否（模拟成交）</td></tr>
<tr><td>benchmark来源</td><td>buy&amp;hold</td></tr>
<tr><td>回测版本</td><td>{engine_version}</td></tr>
<tr><td>数据完整率</td><td>{data_quality.completeness}</td></tr>
</table>

<p><strong>数据质量评级</strong>：{data_quality.rating}（数据完整率 ≥ 95% 为 A 级，≥ 90% 为 B 级，&lt; 90% 需标注风险）</p>
<p><strong>缺失数据处理明细</strong>：缺失 {data_quality.missing_days} / {data_quality.total_days} 个交易日，填充方式：{data_quality.fill_method}</p>
</div>
```

**设计要点：**
- 表格形式展示机构级别的数据质量控制清单
- 每项均有默认值，实际值从 BacktestResultBundle.data_quality 读取
- 数据完整率百分比精确到小数点后一位
- 数据质量评级（A/B/C）为新增评估维度

---

#### 数据质量检测算法设计（v3.2 修复 R3）

**背景：** 原 `data_quality` 字段设为 hardcoded 默认值字典，无数据源元数据、无完整率统计、无缺失值验证。以下为数据质量计算逻辑的完整设计：

```python
def compute_data_quality(df: pd.DataFrame, df_expected: pd.DataFrame, config: Dict) -> Dict[str, Any]:
    """计算数据质量指标

    Args:
        df: 实际加载的数据（OHLCV）
        df_expected: 预期的完整交易日历（按市场规则生成）
        config: 回测配置（含数据源/slippage/commission等）

    Returns:
        Dict: 填充 BacktestResultBundle.data_quality 的字典
    """
    # ── 1. 数据完整率（真实可计算 ✅） ──
    total_days = len(df_expected)
    actual_days = len(df)
    completeness = actual_days / total_days if total_days > 0 else 0.0

    # ── 2. 缺失值统计（真实可计算 ✅） ──
    nan_stats = {}
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            nan_pct = df[col].isna().sum() / actual_days
            nan_stats[col] = round(nan_pct * 100, 2)

    # ── 3. 缺失天数明细 ──
    def _find_missing_dates(actual: pd.DatetimeIndex, expected: pd.DatetimeIndex):
        return sorted(set(expected) - set(actual))

    # ── 4. 滑点验证（Phase 3前为占位符 ⚠️） ──
    # 当前无法验证滑点模型与真实成交数据的偏差
    # 需要在 Phase 3 引入 Trade Compare 组件后才能计算
    slippage_validated = False
    slippage_note = "滑点验证尚未关联真实成交数据（Phase 3 待实现）"

    return {
        # 字段分级标记：✅ 真实可计算 | ⚠️ Phase 3 前占位
        "source": config.get("data_source", "akshare"),  # ✅ 从config读取
        "period": config.get("data_period", "daily"),  # ✅ 从config读取
        "adjusted": config.get("adjust_type", "qfq"),  # ✅ 从config读取
        "completeness": round(completeness * 100, 1),  # ✅ 真实计算
        "total_days": total_days,  # ✅ 真实计算
        "actual_days": actual_days,  # ✅ 真实计算
        "missing_days": total_days - actual_days,  # ✅ 真实计算
        "missing_dates": _find_missing_dates(df.index, df_expected.index)[:10],  # ✅ 真实计算
        "nan_stats": nan_stats,  # ✅ 真实计算
        "nan_handling": config.get("nan_handling", "forward fill"),  # ✅ 从config读取
        "slippage_model": config.get("slippage_model", "fixed 0.1%"),  # ✅ 从config读取
        "slippage_validated": slippage_validated,  # ⚠️ 占位
        "slippage_note": slippage_note,  # ⚠️ 占位
        "commission": config.get("commission", "0.03%"),  # ✅ 从config读取
        "real_trade": False,  # ✅ 硬编码（回测均为模拟成交）
        "benchmark": "buy&hold",  # ✅ 硬编码
        "engine_version": config.get("engine_version", "v3.0"),  # ✅ 从config读取
        "fill_method": config.get("fill_method", "forward fill"),  # ✅ 从config读取
        "rating": "A" if completeness >= 0.95 else ("B" if completeness >= 0.90 else "C"),  # ✅ 根据完整率计算
    }
```

**字段可达性总结：**

| 字段组 | 计算状态 | 依赖 |
|--------|:--------:|------|
| 数据源/周期/复权/手续费等静态配置 | ✅ 真实可计算 | 从回测config直接读取 |
| 数据完整率/缺失天数/缺失值统计 | ✅ 真实可计算 | 需要预期交易日历（由市场规则生成） |
| 数据质量评级（A/B/C） | ✅ 真实可计算 | 基于完整率自动计算 |
| 滑点验证 | ⚠️ Phase 3占位符 | 需要 Trade Compare 组件关联真实成交数据 |
| 数据源元数据（如交易所原始字段） | ❌ 未定义 | 当前回测框架未记录数据源元数据 |

**预期交易日历说明：** `df_expected` 并非独立数据文件，而是根据交易所交易日历规则动态生成的 `DatetimeIndex`（如剔除周末+法定假期），由 `DateUtils.generate_calendar(start, end, exchange="SSE")` 提供。该工具函数计划在 Phase 2 实现。

---

#### 第一章：回测参数表

回测基础配置信息一览表（同 v2.0，数据源改为 BacktestResultBundle）：

```
┌──────────────────────────────────────────────────┐
│  回测参数配置                                     │
├───────────────────────┬──────────────────────────┤
│ 参数项               │ 值                       │
├───────────────────────┼──────────────────────────┤
│ 标的 (Symbol)         │ 601857.SH (中国石油)     │  ← Bundle.symbol
│ 回测时间范围          │ 2025-01-01 ~ 2026-05-17  │  ← Bundle.start_date/end_date
│ 初始资金              │ ¥1,000,000               │  ← Bundle.params.initial_capital
│ 费率                  │ 0.03% (买入+卖出)        │  ← Bundle.params.commission
│ 滑点                  │ 0.01%                    │  ← Bundle.params.slippage
│ 策略分配权重          │ Trend 40% / Mean 30% / Momentum 30% │
│ 信号冲突优先策略      │ Trend > Momentum > Mean  │
│ 参数版本              │ v1.2                     │  ← Bundle.params.version
└───────────────────────┴──────────────────────────┘
```

---

#### 第二章：净值曲线

全页宽净值曲线图（同 v2.0，数据源改为 Bundle.equity_curve / Bundle.benchmark_curve）：

```
┌────────────────────────────────────────────────┐
│  净值曲线 (Equity Curve)                        │
│                                                  │
│  ▲ 净值                                         │
│  2.0 ├──── Trend ──────────────────────          │
│      │          \   ▲  Mean                │
│  1.5 ├─────────\─▲─▼──Momentum────────         │
│      │           \▲/  \                   │
│  1.0 ├──────────●────\──BuyHold─────           │
│      │          ╱ ╲    \                  │
│  0.5 ├────────╱───╲────\───α超额收益线         │
│      │   2025/01   2025/07   2026/01   2026/05  │
├──────┴─────────────────────────────────────────┤
│  关键指标摘要框:                                 │
│  Trend: +24.3% | Mean: +12.1% | Mom: +8.7%      │
│  组合: +18.7% | BuyHold: +3.5% | α: +15.2%     │  ← Bundle.summary_metrics
│  Sharpe: 1.23 | MDD: -8.5% | IR: 0.92           │
│  信息比率(IR): 0.92 (策略α/跟踪误差)             │
└─────────────────────────────────────────────────┘
```

---

#### 第三章：回撤曲线 + 月度收益热力图

内容同 v2.0，数据源改为 Bundle.equity_curve（计算最大回撤）/ Bundle.daily_metrics（月度收益）。

---

#### 第四章：指标总表

内容同 v2.0，所有指标值通过 `metrics_registry` 统一计算口径，数据源为 Bundle.summary_metrics。

---

#### 第五章：K线图 + 买卖点位

内容同 v2.0，K线数据来自 Bundle.trades 中关联的 OHLCV 数据。

---

#### 第六章：交易行为分析（重构：合并原六+七）

**包含子章节：**

1. **交易记录表** — 完整列表，按 Method 分组
2. **盈亏分布直方图** — 各笔交易盈亏金额/盈亏率的分布
3. **持仓时间分布** — 各笔交易持仓天数的分布
4. **按Method统计** — trend/mean/momentum 各 45/38/52 笔
5. **连盈连亏序列分析** — 最大连盈/连亏笔数及区间

```html
<!-- 第六章：交易行为分析 -->
<div class="page-break">
<h2>六、交易行为分析</h2>

<h3>6.1 交易记录表 — 趋势跟踪 (Trend) — 共45笔</h3>
<table>
<tr><th>序号</th><th>入场时间</th><th>入场价格</th><th>出场时间</th><th>出场价格</th><th>盈亏</th><th>持仓量</th></tr>
<tr><td>#1</td><td>09:31:05</td><td>15.23</td><td>10:30:00</td><td>15.68</td><td class="profit">+900</td><td>2000</td></tr>
<!-- ... 完整45笔 ... -->
<tr class="subtotal"><td colspan="5">小计：盈利 +8,200</td><td>胜率 58.2%</td><td>盈亏比 1.73</td></tr>
</table>

<h3>6.2 盈亏分布直方图</h3>
<img src="{pnl_distribution_chart}" class="chart" alt="盈亏分布">
<p>横轴：盈亏区间（元） / 纵轴：交易笔数</p>
<p>分布特征：{pnl_distribution_summary}（如：右偏态，正收益集中在小额区间）</p>

<h3>6.3 持仓时间分布</h3>
<img src="{holding_period_chart}" class="chart" alt="持仓时间分布">
<p>平均持仓时间：{avg_holding_days} 天 / 中位数：{median_holding_days} 天</p>
<p>持仓时间标准差：{holding_std} 天 — {holding_diversity_summary}</p>

<h3>6.4 按Method统计</h3>
<table>
<tr><th>指标</th><th>Trend</th><th>Mean</th><th>Momentum</th></tr>
<tr><td>交易笔数</td><td>45</td><td>38</td><td>52</td></tr>
<tr><td>胜率</td><td>58.2%</td><td>52.6%</td><td>48.1%</td></tr>
<tr><td>盈亏比</td><td>1.73</td><td>1.35</td><td>1.12</td></tr>
<tr><td>平均持仓(天)</td><td>7.7</td><td>4.2</td><td>2.3</td></tr>
</table>

<h3>6.5 连盈连亏序列分析</h3>
<table>
<tr><th>Method</th><th>最大连盈</th><th>最大连亏</th><th>连盈区间</th><th>连亏区间</th></tr>
<tr><td>Trend</td><td>6笔</td><td>3笔</td><td>2025-03~2025-04</td><td>2025-08~2025-08</td></tr>
<tr><td>Mean</td><td>4笔</td><td>4笔</td><td>2025-06~2025-07</td><td>2025-09~2025-10</td></tr>
<tr><td>Momentum</td><td>3笔</td><td>6笔</td><td>2025-02~2025-02</td><td>2025-07~2025-08</td></tr>
</table>

<div class="streak-sequence">
<p><strong>连盈连亏序列可视化：</strong></p>
<p>Trend: <span class="win">+ + +</span> <span class="loss">- - -</span> <span class="win">+ +</span> <span class="loss">-</span> <span class="win">+ + + + + +</span> ...</p>
<p class="metric-box">连盈连亏分析揭示了趋势跟踪策略在上涨趋势中的优势（最大连盈6笔）和震荡市中的脆弱性（最大连亏3笔）。</p>
</div>
</div>
```

**重构要点：**
- 合并原第六章（交易记录）和第七章（赢率分析）为统一的交易行为分析
- 新增盈亏分布直方图：使用 matplotlib hist 展示交易盈亏概览
- 新增持仓时间分布：按天数分桶，识别高频 vs 中频 vs 低频特征
- 连盈连亏序列：按 Method 独立统计，可视化序列模式

---

#### 第七章：市场状态适应性（重构）

**包含：**
- By Regime（牛市/震荡/熊市各表现）
- 高波动 vs 低波动期
- 成交量放大期
- 板块轮动期

```html
<!-- 第七章：市场状态适应性 -->
<div class="page-break">
<h2>七、市场状态适应性</h2>

<h3>7.1 By Regime（牛市/震荡/熊市）</h3>
<table>
<tr><th>Regime</th><th>Trend</th><th>Mean</th><th>Momentum</th><th>组合</th></tr>
<tr><td>Bull (上涨)</td><td>Sharpe 1.82</td><td>Sharpe 0.65</td><td>Sharpe 0.92</td><td>Sharpe 1.45</td></tr>
<tr><td>Range (震荡)</td><td>Sharpe 0.45</td><td>Sharpe 1.28</td><td>Sharpe 0.35</td><td>Sharpe 0.82</td></tr>
<tr><td>Bear (下跌)</td><td>Sharpe -0.22</td><td>Sharpe 0.52</td><td>Sharpe 0.18</td><td>Sharpe 0.25</td></tr>
</table>
<p class="metric-box">趋势策略在牛市表现最优（Sharpe 1.82），均值回归在震荡市表现最优（Sharpe 1.28）。组合在各市场状态下均维持正 Sharpe。</p>

<h3>7.2 高波动 vs 低波动期</h3>
<table>
<tr><th>波动环境</th><th>定义</th><th>Trend WinRate</th><th>Mean WinRate</th><th>Momentum WinRate</th></tr>
<tr><td>低波动</td><td>ATR&lt;20日均值75%</td><td>62.3%</td><td>55.8%</td><td>52.1%</td></tr>
<tr><td>中等波动</td><td>ATR在75%~125%</td><td>58.5%</td><td>52.3%</td><td>48.6%</td></tr>
<tr><td>高波动</td><td>ATR&gt;20日均值125%</td><td>48.2%</td><td>38.5%</td><td>42.3%</td></tr>
</table>

<h3>7.3 成交量放大期</h3>
<table>
<tr><th>成交量条件</th><th>样本数</th><th>组合收益率</th><th>组合Sharpe</th></tr>
<tr><td>放量日（>20日均量×1.5）</td><td>68天</td><td>+3.2%</td><td>0.85</td></tr>
<tr><td>缩量日（<20日均量×0.5）</td><td>45天</td><td>-1.8%</td><td>0.32</td></tr>
<tr><td>正常量</td><td>389天</td><td>+17.3%</td><td>1.28</td></tr>
</table>

<h3>7.4 板块轮动期（如适用）</h3>
<p>当前回测标的为单一股，板块轮动分析保留框架，支持未来多标的场景。</p>
<p class="metric-box">（多标的回测时展开：轮动期各板块权重变化、轮动因子择时效果）</p>
</div>
```

**重构要点：**
- By Regime：使用 Bundle.regime_labels 的市场状态分类（Bull/Range/Bear）
- 高波动 vs 低波动：以 ATR 为波动率指标，将回测期划分为三档
- 成交量放大期：以 20 日均量为基准，识别放量/缩量/正常量
- 板块轮动期：为未来多标的场景预留框架

---

#### ★ 第八章：知识库提炼（保留7个子节）

内容同 v2.0 第八章（8.1~8.7），数据源改为 Bundle.insights。

---

#### ★ 第九章：参数敏感性分析 + 参数稳定性评分

在 v2.0 第九章基础上增加 **RobustScore 参数稳定性评分**：

```html
<!-- 第九章：参数敏感性分析（T3） -->
<div class="page-break">
<h2>★ 九、参数敏感性分析 (T3)</h2>

<h3>9.1 关键参数扫描</h3>
<p>（同 v2.0：MA周期敏感性、止损幅敏感性等）</p>

<h3>9.2 参数稳定性评分（RobustScore）</h3>
<div class="metric-box" style="text-align: center;">
  <p class="robust-score">RobustScore = 0.82</p>
  <p class="score-dimensions">
    <span class="robust-dimension">Sharpe均值<br><strong>1.05</strong></span>
    <span class="robust-dimension">Sharpe标准差<br><strong>0.18</strong></span>
    <span class="robust-dimension">邻域稳定性<br><strong>0.85</strong></span>
    <span class="robust-dimension">参数梯度<br><strong>0.12</strong></span>
    <span class="robust-dimension">局部平滑性<br><strong>0.90</strong></span>
  </p>
</div>

<table>
<tr><th>评分维度</th><th>计算方式</th><th>得分</th><th>权重</th></tr>
<tr><td>Sharpe均值</td><td>参数邻域内Sharpe的平均值</td><td>1.05</td><td>25%</td></tr>
<tr><td>Sharpe标准差</td><td>参数邻域内Sharpe的标准差（越小越好）</td><td>0.18</td><td>25%</td></tr>
<tr><td>邻域稳定性</td><td>最优值±20%邻域内Sharpe最大值/最小值之比，越接近1越好</td><td>0.85</td><td>20%</td></tr>
<tr><td>参数梯度</td><td>相邻参数点之间Sharpe的平均变化率（越小越平滑）</td><td>0.12</td><td>15%</td></tr>
<tr><td>局部平滑性</td><td>局部二阶导数均值（曲率），越小表示表面越平坦</td><td>0.90</td><td>15%</td></tr>
</table>

<p><strong>RobustScore = 0.82</strong> — 属于"高稳定性"区间（≥0.8为高，0.6~0.8为中，<0.6为低）</p>
<p class="metric-box">高稳定性说明策略对参数不敏感，参数漂移对绩效影响有限，实盘表现更可预期。</p>
</div>
```

**新增设计要点：**
- RobustScore 由 5 个维度加权综合计算
- 所有维度值归一化到 [0, 1] 范围后再加权
- 评分区间：≥0.8 高稳定性 / 0.6~0.8 中稳定性 / <0.6 低稳定性
- 低稳定性的参数需在操作建议中突出过拟合风险

---

#### ★ 第十章：样本内外对比 + Walk Forward Analysis

v2.0 的静态 60/20/20 划分升级为 **Walk Forward Analysis（滚动窗口验证）**：

```html
<!-- 第十章：样本内外对比 -->
<div class="page-break">
<h2>★ 十、样本内外对比 + Walk Forward Analysis</h2>

<h3>10.1 静态样本内外对比（60/20/20）</h3>
<p>（同 v2.0 内容）</p>

<h3>10.2 Walk Forward Analysis（滚动窗口验证）</h3>
<p><strong>窗口设置</strong>：训练期 1 年 → 测试期 3 个月 → 向前滚动</p>

<div style="margin: 16px 0;">
<span class="wf-window wf-train">2025-01~12训练</span> →
<span class="wf-window wf-test">2025-01~03测试</span>
&nbsp;&nbsp;&nbsp;&nbsp;
<span class="wf-window wf-train">2025-04~2026-03训练</span> →
<span class="wf-window wf-test">2026-04~06测试</span>
&nbsp;&nbsp;&nbsp;&nbsp;
<span class="wf-window wf-train">2025-07~2026-06训练</span> →
<span class="wf-window wf-test">2026-07~09测试</span>
</div>

<table>
<tr><th>窗口</th><th>训练期Sharpe</th><th>测试期Sharpe</th><th>差异</th><th>训练期MDD</th><th>测试期MDD</th></tr>
<tr><td>Window 1</td><td>1.35</td><td>1.12</td><td>-0.23</td><td>-7.2%</td><td>-8.5%</td></tr>
<tr><td>Window 2</td><td>1.28</td><td>1.05</td><td>-0.23</td><td>-6.8%</td><td>-7.9%</td></tr>
<tr><td>Window 3</td><td>1.18</td><td>0.98</td><td>-0.20</td><td>-7.5%</td><td>-8.2%</td></tr>
</table>

<p><strong>稳定性指标：</strong></p>
<ul>
  <li>Sharpe差异均值：-0.22（标准差 0.02）</li>
  <li>MDD差异均值：+0.82%（标准差 0.3%）</li>
  <li>WinRate差异均值：-5.2%（标准差 0.4%）</li>
</ul>
<p class="metric-box">各窗口差异稳定（低标准差），样本外表现退化可控，策略鲁棒性良好。</p>
</div>
```

**重构要点：**
- 保留静态 60/20/20 划分作为基础对比
- 新增 Walk Forward Analysis：训练1年→测试3个月→滚动
- 每个窗口记录训练期 vs 测试期的 Sharpe/MDD/WinRate 差异
- 统计稳定性指标：差异均值 + 标准差（标准差越低说明越稳定）

---

#### ★ 第十一章：策略相关性矩阵 + 组合资金融合模拟

在 v2.0 的策略相关性基础上新增 **组合资金融合模拟**：

```html
<!-- 第十一章：策略相关性矩阵（T5） -->
<div class="page-break">
<h2>★ 十一、策略相关性矩阵 (T5) + 组合资金融合模拟</h2>

<h3>11.1 收益相关性矩阵</h3>
<p>（同 v2.0 内容）</p>

<h3>11.2 组合资金融合模拟</h3>
<table class="portfolio-compare">
<tr><th>指标</th><th>单策略 Trend</th><th>单策略 Mean</th><th>单策略 Momentum</th><th>组合策略</th><th>改善幅度</th></tr>
<tr><td>年化收益</td><td>+24.3%</td><td>+12.1%</td><td>+8.7%</td><td>+18.7%</td><td>—</td></tr>
<tr><td>最大回撤</td><td>-8.5%</td><td>-6.2%</td><td>-9.1%</td><td>-7.3%</td><td class="profit">-14.1% ↓</td></tr>
<tr><td>Sharpe</td><td>1.35</td><td>0.87</td><td>0.65</td><td>1.23</td><td class="profit">+13.3% ↑*</td></tr>
<tr><td>年化波动率</td><td>18.5%</td><td>14.2%</td><td>16.8%</td><td>12.8%</td><td class="profit">-22.4% ↓</td></tr>
<tr><td>Calmar</td><td>2.86</td><td>1.95</td><td>0.96</td><td>2.56</td><td class="profit">+8.1% ↑</td></tr>
<tr><td>Recovery Factor</td><td>2.12</td><td>1.45</td><td>0.72</td><td>1.88</td><td class="profit">+6.3% ↑</td></tr>
</table>
<p>* 组合Sharpe(1.23) 略低于最优单策略Trend(1.35) 但回撤改善14.1%，风险调整后综合效果更优。</p>

<div class="metric-box">
<strong>融合效果总结：</strong>
<ul>
  <li>最大回撤从最优单策略的 -8.5% 降至组合 -7.3%（↓14.1%）</li>
  <li>年化波动率从各策略均值 16.5% 降至组合 12.8%（↓22.4%）</li>
  <li>Recovery Factor 从各策略均值 1.43 提升至 1.88（↑31.5%）</li>
  <li>Sharpe 虽略低于最优单策略但显著高于其他策略和均值</li>
</ul>
</div>
</div>
```

**重构要点：**
- 保留收益相关性矩阵和权重分配依据
- 新增组合资金融合模拟表：单策略 vs 组合策略的各维度对比
- 改善幅度列：量化组合对最大回撤/Sharpe/Recovery 的改善效果
- 增加 Recovery Factor（收益恢复因子）指标

---

#### ★ 第十二章：连续亏损与回撤恢复 + Pain Index

在 v2.0 基础上新增 **Pain Index 等扩展指标**：

```html
<!-- 第十二章：连续亏损与回撤恢复（T7） -->
<div class="page-break">
<h2>★ 十二、连续亏损与回撤恢复 (T7)</h2>

<h3>12.1 最大回撤分析</h3>
<p>（同 v2.0 内容：最大回撤值、发生时间、持续天数、恢复时间）</p>

<h3>12.2 连续亏损分析</h3>
<p>（同 v2.0 内容：最大连亏笔数、发生区间、最大连亏金额）</p>

<h3>12.3 水下时间分析</h3>
<p>（同 v2.0 内容：总交易天数、处于回撤期天数、水下时间%）</p>

<h3>12.4 扩展回撤恢复指标</h3>
<table>
<tr><th>指标</th><th>含义</th><th>值</th><th>行业参考</th></tr>
<tr><td>Avg Recovery Days</td><td>平均恢复时间 — 从回撤谷底到净值创新高的平均天数</td><td>8.5天</td><td>10-15天</td></tr>
<tr><td>Worst Recovery Days</td><td>最长恢复时间 — 最长的一次恢复耗时</td><td>35天</td><td>30-60天</td></tr>
<tr><td>Underwater Ratio</td><td>水下占比 — 处于回撤期天数/总交易天数</td><td>72.3%</td><td>60-80%</td></tr>
<tr><td>Pain Index</td><td>痛苦指数 — 回撤深度×水下持续期的累积加权值</td><td class="pain-medium">0.42</td><td>&lt;0.3 低 / 0.3-0.7 中 / &gt;0.7 高</td></tr>
</table>

<p><strong>Pain Index 计算公式：</strong></p>
<p>Pain Index = (1 / N) × Σ(Drawdown² × Duration_Weight)</p>
<p>其中 Drawdown 为每日回撤深度（百分比），Duration_Weight 为回撤持续期系数（每多一天 +0.1）</p>

<p class="metric-box">Pain Index 0.42 属于中等水平，说明回撤深度和持续时间均为中等级别，策略的持仓体验尚可接受。</p>
</div>
```

**重构要点：**
- 保留 v2.0 的三个分析区块
- 新增扩展回撤恢复指标表（Avg Recovery Days / Worst Recovery Days / Underwater Ratio / Pain Index）
- Pain Index 为综合评价回撤"痛苦程度"的量化指标
- 每种指标给出行业参考范围供对比

---

#### ★ 第十三章：T1评级结论 — 改为多维评分矩阵

v2.0 的 A/B/C 评级升级为 **多维评分矩阵**：

```html
<!-- 第十三章：T1评级结论 -->
<div class="page-break">
<h2>★ 十三、T1评级结论 — 多维评分矩阵</h2>

<table class="score-matrix">
<tr><th>评分维度</th><th>权重</th><th>Trend</th><th>Mean</th><th>Momentum</th><th>组合</th></tr>
<tr><td>收益能力</td><td>20%</td><td class="score-value">85</td><td>65</td><td>55</td><td class="best-score score-value">82</td></tr>
<tr><td>风险控制</td><td>20%</td><td>75</td><td class="best-score score-value">78</td><td>62</td><td class="score-value">75</td></tr>
<tr><td>稳定性</td><td>20%</td><td class="best-score score-value">91</td><td>80</td><td>72</td><td>88</td></tr>
<tr><td>参数鲁棒性</td><td>15%</td><td class="score-value">88</td><td>82</td><td>72</td><td>85</td></tr>
<tr><td>市场适应性</td><td>15%</td><td class="score-value">70</td><td>68</td><td>65</td><td class="best-score score-value">72</td></tr>
<tr><td>数据可信度</td><td>10%</td><td>95</td><td>95</td><td>95</td><td>95</td></tr>
<tr class="total-row"><td colspan="2"><strong>Total Score</strong></td><td><strong>84</strong></td><td><strong>75</strong></td><td><strong>67</strong></td><td class="best-score"><strong>83</strong></td></tr>
</table>

<p class="metric-box" style="text-align: center; font-size: 14pt;">
  组合 Total Score: 83 | 评级：A
</p>

<h3>评级等级</h3>
<table>
<tr><th>Score区间</th><th>评级</th><th>含义</th></tr>
<tr><td>≥ 80</td><td class="profit">A</td><td>全面优良，建议主力配置</td></tr>
<tr><td>65 ~ 79</td><td>B</td><td>有效但在1~2个维度存在局限</td></tr>
<tr><td>50 ~ 64</td><td>C</td><td>表现不佳或存在显著风险</td></tr>
<tr><td>&lt; 50</td><td class="loss">D</td><td>不建议实盘</td></tr>
</table>

<h3>各维度评分依据</h3>
<table>
<tr><th>维度</th><th>评分依据</th></tr>
<tr><td>收益能力</td><td>累计收益 / Sharpe / Calmar 综合评估</td></tr>
<tr><td>风险控制</td><td>最大回撤 / 水下时间% / Pain Index</td></tr>
<tr><td>稳定性</td><td>样本内外差异 / Walk Forward 标准差</td></tr>
<tr><td>参数鲁棒性</td><td>RobustScore 参数稳定性评分</td></tr>
<tr><td>市场适应性</td><td>各市场状态下Sharpe均值 / 最差状态Sharpe</td></tr>
<tr><td>数据可信度</td><td>数据完整率 / 来源可靠性 / 回测版本</td></tr>
</table>
</div>
```

**重构要点：**
- 从 A/B/C 三档升级为 6 维评分矩阵
- 每个策略+组合在 6 个维度独立打分（0~100分）
- 加权合计 Total Score
- 绿色高亮 = 该维度最优点
- 评级等级扩展为 A/B/C/D 四档
- 各维度评分依据透明化（通过矩阵底部的依据说明表）

---

#### 附录

内容同 v2.0，新增风控触发记录中增加回撤预警触发情况：

```
┌──────────────────────────────────────────────────────────────┐
│  (4) 回撤恢复记录                                            │
│  ┌────────┬─────────┬────────┬──────────┬──────────┐       │
│  │ 回撤事件│ 峰值日期 │ 谷底日期│ 回撤深度│ 恢复耗时  │       │
│  ├────────┼─────────┼────────┼──────────┼──────────┤       │
│  │ DD#1   │2025-08-17│2025-09-24│  -8.5%  │  35天    │       │
│  │ DD#2   │2026-02-03│2026-02-18│  -5.2%  │  12天    │       │
│  │ DD#3   │2026-04-15│2026-04-28│  -3.8%  │   8天    │       │
│  └────────┴─────────┴────────┴──────────┴──────────┘       │
└──────────────────────────────────────────────────────────────┘
```

---

### 3.4 简洁模式选项

同 v2.0，新增控制：简洁模式下跳过第0章数据质量声明。
```
简洁模式章节列表：
  封面页 (精简标题)
  一、回测参数表
  二、指标总表 (一行一Method)
  三、净值曲线 (仅组合线)
  四、T1评级结论（仅Total Score行）
  五、知识库→早报引用
  附录 (免责声明)
```

| 差异维度 | 完整模式 v3.0 | 简洁模式 |
|:--------:|:-------------:|:--------:|
| 页数 | 18-30页 | 3-5页 |
| 第0章 | 数据质量声明（有） | 跳过 |
| 章节数 | 14章+附录 | 5章+附录 |
| Method展开 | 逐Method详细 | 仅汇总表 |
| 图表 | 全量（净值+回撤+热力图+K线+敏感性+Walk Forward） | 仅组合净值曲线 |
| 交易行为分析 | 完整6节 | 仅Top-5亏损/盈利 |
| 知识库 | 完整8个小节 | 仅引用条目 |
| 组合融合 | 完整对比表 | 仅摘要 |
| 生成时间 | ~25-35s | ~8-12s |

**实现方式：** `ReportBuilder.render()` 新增 `mode: str = "full"` 参数，在循环章节时根据 mode 跳过非核心章节。

---

## 4. 组件设计

### 4.1 文件位置（v3.0 新增组件）

```
mozhi_platform/
  src/
    backtest/
      engine/
        method_backtest_runner.py     ← 已存，产出 BacktestResultBundle
        knowledge_analyzer.py         ← 已存
        backtest_result_bundle.py     ← ◐ v3.0 新增
      pipeline/
        report_builder.py             ← ◐ v3.0 重构（替代原 report_generator.py）
        chart_generator.py            ← 已存
        async_pdf_task.py             ← 已存
        report_renderer.py            ← 已存
    metrics/
      metrics_registry.py             ← ◐ v3.0 新增
```

### 4.2 BacktestResultBundle — 统一数据源（v3.0 核心新增）

**位置：** `src/backtest/engine/backtest_result_bundle.py`

```python
"""
backtest_result_bundle.py — 回测结果统一数据包

v3.0 核心数据契约。所有消费方（ReportBuilder/KnowledgeSearch/BitableSync/Future Dashboard）
从该 Bundle 读取数据，禁止独立计算。

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class TradePair:
    """一笔完整交易"""
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    volume: int
    is_long: bool = True
    pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    exit_reason: str = ""


@dataclass
class RiskEvent:
    """风控事件记录"""
    event_type: str          # "stop_loss" | "take_profit" | "max_position" | "max_drawdown"
    trigger_time: str
    trigger_reason: str
    impact_pnl: float = 0.0
    pre_event_position: float = 0.0
    post_event_position: float = 0.0


@dataclass
class KnowledgeEntry:
    """知识条目"""
    entry_id: str
    content: str
    category: str            # "market_pattern" | "param_experience" | "early_warning" | "probability_stat"
    confidence: float        # 0~1
    sample_size: int
    status: str              # "draft" | "active" | "decaying" | "needs_review"
    created_at: str


@dataclass
class BacktestResultBundle:
    """回测结果统一数据包 — 所有章节的唯一数据源

    每个方法（trend/mean/momentum）和组合独立生成一个 Bundle。
    ReportBuilder 接收 List[BacktestResultBundle]（多方法）和
    BacktestResultBundle（组合），渲染完整报告。
    """

    # ── 基础信息 ──
    run_id: str
    strategy_name: str
    method_name: str
    symbol: str
    start_date: str
    end_date: str

    # ── 参数 ──
    params: Dict[str, Any] = field(default_factory=dict)

    # ── 净值（含日收益率） ──
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    # 列: date, equity, daily_return, cumulative_return

    # ── benchmark ──
    benchmark_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    # 列: date, benchmark_equity, benchmark_return

    # ── 交易记录 ──
    trades: List[TradePair] = field(default_factory=list)

    # ── 日度指标（含各项日级衍生数据） ──
    daily_metrics: pd.DataFrame = field(default_factory=pd.DataFrame)
    # 列: date, volatility, turnover, regime, volume, atr, ...

    # ── regime 标签 ──
    regime_labels: pd.DataFrame = field(default_factory=pd.DataFrame)
    # 列: date, regime (Bull/Range/Bear), regime_score

    # ── 参数扫描结果 ──
    parameter_scan: pd.DataFrame = field(default_factory=pd.DataFrame)
    # 列: param_1, param_2, ..., sharpe, total_return, max_drawdown, ...

    # ── 风控记录 ──
    risk_events: List[RiskEvent] = field(default_factory=list)

    # ── 知识库输出 ──
    insights: List[KnowledgeEntry] = field(default_factory=list)

    # ── 核心统计（一次性计算好的汇总指标） ──
    summary_metrics: Dict[str, Any] = field(default_factory=dict)
    # 包含: total_return, sharpe, max_drawdown, win_rate, calmar,
    #       profit_factor, avg_holding_days, trade_count,
    #       underwater_pct, pain_index, recovery_avg_days, recovery_worst_days,
    #       max_consecutive_wins, max_consecutive_losses,
    #       walk_forward_windows (list), robust_score, etc.

    # ── 数据质量（默认空字典，由 compute_data_quality() 计算填充） ──
    # 计算逻辑：见 §3.3「数据质量检测算法设计」
    # 调用方式：from backtest.engine.data_quality import compute_data_quality
    #            bundle.data_quality = compute_data_quality(df, df_expected, config)
    data_quality: Dict[str, Any] = field(default_factory=dict)


def bundle_from_runner(
    runner_result: MethodResult,
    df_ohlcv: pd.DataFrame,
    ctx: Optional[StrategyContext] = None,
    pm: Optional["PortfolioManager"] = None,
    additional: Optional[Dict[str, Any]] = None,
) -> BacktestResultBundle:
    """将 MethodBacktestRunner 的输出转为 BacktestResultBundle。

    这是 v3.0 架构的数据转换入口点：
    Engine → MethodBacktestRunner → bundle_from_runner() → BacktestResultBundle

    与 v3.1 的区别：不再依赖外部 portfolio_output 字典，
    改为内部创建 PortfolioManager 从 signals+OHLCV 直接计算。

    字段映射表（v3.2 完整设计）：
    ┌──────────────────────┬──────────────────────────────────────────────┐
    │ Bundle字段           │ 来源                                          │
    ├──────────────────────┼──────────────────────────────────────────────┤
    │ run_id               │ ctx.task_id 或 additional["task_id"]           │
    │ strategy_name        │ ctx.strategy_name                             │
    │ method_name          │ runner_result.method_name (直接映射)          │
    │ symbol               │ ctx.symbol 或 additional["symbol"]            │
    │ start_date           │ df_ohlcv.index[0] → str                      │
    │ end_date             │ df_ohlcv.index[-1] → str                     │
    │ params               │ runner_result.params (直接映射)               │
    │ equity_curve         │ PortfolioManager.equity_curve 转化            │
    │ benchmark_curve      │ df_ohlcv.close → buy&hold 归一化             │
    │ trades               │ PortfolioManager.trades → TradePair 配对     │
    │ daily_metrics        │ df_ohlcv + equity 合并                       │
    │ regime_labels        │ additional["regime_labels"] (Phase 3)        │
    │ parameter_scan       │ additional["parameter_scan"] (Phase 3)       │
    │ risk_events          │ additional["risk_events"] (Phase 3)          │
    │ insights             │ additional["insights"] (KnowledgeBridge)     │
    │ summary_metrics      │ 从 equity_curve/trades 统计算                │
    │ data_quality         │ compute_data_quality(df_ohlcv) (见§4.2.2)    │
    └──────────────────────┴──────────────────────────────────────────────┘

    Args:
        runner_result: MethodBacktestRunner.run() 输出的 MethodResult。
        df_ohlcv: 原始 OHLCV DataFrame，索引为 DatetimeIndex。
        ctx: 策略上下文（可选，提取 symbol/strategy_name/task_id）。
        pm: PortfolioManager 实例（可选，若外部已运行过）。
        additional: 额外数据注入字典：{"symbol","task_id","regime_labels",
                      "parameter_scan","risk_events","insights"}。

    Returns:
        BacktestResultBundle: 组装完成的统一数据包。
    """
    from backtest.engine.backtest_result_bundle import BacktestResultBundle, TradePair
    from backtest.engine.portfolio.portfolio_manager import PortfolioManager

    add = additional or {}
    symbol = ctx.symbol if ctx else add.get("symbol", "")
    strategy_name = ctx.strategy_name if ctx else ""
    run_id = add.get("task_id", "") or (ctx.task_id if ctx else runner_result.metadata.get("run_id", ""))

    start_date = str(df_ohlcv.index[0].date()) if len(df_ohlcv) > 0 else ""
    end_date = str(df_ohlcv.index[-1].date()) if len(df_ohlcv) > 0 else ""

    # ── 运行 PortfolioManager 生成 equity_curve / trades ─────────
    if pm is None:
        pm = PortfolioManager()
        for idx, row in df_ohlcv.iterrows():
            signal = 0
            if runner_result.signals is not None and idx in runner_result.signals.index:
                signal = int(runner_result.signals.loc[idx, "signal"])
            pm.process_signal(signal, row["close"], symbol=symbol)
            pm.record_equity(row["close"])

    # equity_curve DataFrame
    equity_df = pd.DataFrame(pm.equity_curve, columns=["equity"],
                             index=df_ohlcv.index[:len(pm.equity_curve)])
    equity_df["daily_return"] = equity_df["equity"].pct_change().fillna(0)
    equity_df["cumulative_return"] = equity_df["equity"] / pm.initial_cash - 1

    # ── trades: TradeRecord → TradePair ──────────────────────────
    trade_pairs = _trade_records_to_pairs(pm.trades, symbol)

    # ── daily_metrics 合并 ───────────────────────────────────────
    daily = df_ohlcv[["close", "volume"]].copy()
    if len(equity_df) == len(df_ohlcv):
        daily["equity"] = equity_df["equity"].values
    daily["turnover"] = _calc_turnover(pm.trades, df_ohlcv.index)

    # ── benchmark (buy&hold) ─────────────────────────────────────
    benchmark_df = pd.DataFrame(index=df_ohlcv.index)
    benchmark_df["benchmark_equity"] = (
        df_ohlcv["close"] / df_ohlcv["close"].iloc[0] * pm.initial_cash
    )
    benchmark_df["benchmark_return"] = benchmark_df["benchmark_equity"].pct_change().fillna(0)

    # ── summary_metrics ──────────────────────────────────────────
    n_trades = len(trade_pairs)
    n_win = sum(1 for t in trade_pairs if t.pnl > 0)
    win_rate = n_win / n_trades if n_trades > 0 else 0.0
    total_ret = float(equity_df["cumulative_return"].iloc[-1]) if len(equity_df) > 0 else 0.0
    max_dd = pm.get_peak_drawdown()

    summary = dict(runner_result.statistics or {})
    summary.update({
        "total_return": total_ret,
        "annual_return": _annualize_return(total_ret, len(df_ohlcv)),
        "max_drawdown": -max_dd,
        "sharpe": _calc_sharpe(equity_df["daily_return"]),
        "win_rate": win_rate,
        "trade_count": n_trades,
        "n_bars": len(df_ohlcv),
    })

    # ── data_quality ─────────────────────────────────────────────
    dq = compute_data_quality(df_ohlcv)

    # ── 组装 ─────────────────────────────────────────────────────
    return BacktestResultBundle(
        run_id=run_id,
        strategy_name=strategy_name,
        method_name=runner_result.method_name,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        params=runner_result.params,
        equity_curve=equity_df,
        benchmark_curve=benchmark_df,
        trades=trade_pairs,
        daily_metrics=daily,
        regime_labels=add.get("regime_labels", pd.DataFrame()),
        parameter_scan=add.get("parameter_scan", pd.DataFrame()),
        risk_events=add.get("risk_events", []),
        insights=add.get("insights", []),
        summary_metrics=summary,
        data_quality=dq,
    )


def bundle_from_runner_batch(
    runner_results: Dict[str, MethodResult],
    data_dict: Dict[str, pd.DataFrame],
    ctx: Optional[StrategyContext] = None,
    additional: Optional[Dict[str, Any]] = None,
) -> Dict[str, BacktestResultBundle]:
    """批量转换多时间框架的 Runner 结果。

    对应 MethodBacktestRunner.run_batch() 输出，每个 freq 独立转换。

    Args:
        runner_results: run_batch() 返回的 {freq: MethodResult}。
        data_dict: {freq: DataFrame} 原始 OHLCV 数据。
        ctx: 策略上下文。
        additional: 额外数据注入。

    Returns:
        Dict[str, BacktestResultBundle]: {freq: Bundle}。
    """
    bundles: Dict[str, BacktestResultBundle] = {}
    for freq, result in runner_results.items():
        df = data_dict.get(freq)
        if df is None:
            continue
        bundles[freq] = bundle_from_runner(
            runner_result=result, df_ohlcv=df, ctx=ctx, additional=additional,
        )
    return bundles


# ─── 内部辅助函数 ────────────────────────────────────────────────

def _trade_records_to_pairs(
    trade_records: list, symbol: str
) -> list:
    """将 PortfolioManager.TradeRecord 配对为 TradePair。

    买入-卖出配对：每笔买入与后续卖出配对；末笔未平仓标记 exit_price=0。
    """
    from backtest.engine.backtest_result_bundle import TradePair

    pairs: list = []
    buys = [r for r in trade_records if r.action == "buy"]
    sells = [r for r in trade_records if r.action == "sell"]

    for i, buy in enumerate(buys):
        sell = sells[i] if i < len(sells) else None
        pnl = (sell.shares * (sell.price - buy.price)) if sell else 0.0
        pnl_pct = pnl / (buy.price * buy.shares) if buy.shares > 0 else 0.0
        holding_days = _date_diff_days(sell.timestamp, buy.timestamp) if sell else 0
        pairs.append(TradePair(
            entry_time=buy.timestamp,
            entry_price=buy.price,
            exit_time=sell.timestamp if sell else "",
            exit_price=sell.price if sell else 0.0,
            volume=buy.shares,
            is_long=True,
            pnl=pnl,
            pnl_pct=pnl_pct,
            holding_days=holding_days,
        ))
    return pairs


def _calc_turnover(trade_records: list, date_index: pd.DatetimeIndex) -> pd.Series:
    """按日计算成交额占比（turnover）。"""
    turnover = pd.Series(0.0, index=date_index)
    for r in trade_records:
        try:
            t = pd.Timestamp(r.timestamp).normalize()
            if t in date_index:
                turnover.loc[t] += r.shares * r.price
        except Exception:
            pass
    return turnover


def _date_diff_days(date_str1: str, date_str2: str) -> int:
    """计算两个日期字符串的间隔天数。"""
    try:
        d1 = pd.Timestamp(date_str1)
        d2 = pd.Timestamp(date_str2)
        return abs((d1 - d2).days)
    except Exception:
        return 0


def _annualize_return(total_return: float, n_bars: int) -> float:
    """年化收益率（252个交易日）。"""
    if n_bars <= 0 or total_return <= -1:
        return 0.0
    years = n_bars / 252
    if years <= 0:
        return 0.0
    return (1 + total_return) ** (1 / years) - 1


def _calc_sharpe(daily_returns: pd.Series, rf: float = 0.02 / 252) -> float:
    """夏普比率（日收益率→年化）。"""
    if len(daily_returns) < 2 or daily_returns.std() == 0:
        return 0.0
    excess = daily_returns - rf
    return float(excess.mean() / excess.std() * (252 ** 0.5))


def compute_data_quality(df: pd.DataFrame) -> Dict[str, Any]:
    """计算数据质量指标（R3 完整算法定义）。

    Args:
        df: 原始 OHLCV DataFrame，索引为 DatetimeIndex。

    Returns:
        Dict包含: completeness, missing_days, total_days, expected_days,
        nan_stats, rating 等。

    算法清单（v3.2 定义）：
    ┌─────────────────────┬──────────────────────────────────────────────────┐
    │ 字段                 │ 计算方法                                          │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ completeness        │ 实际close非NaN天数 / 预期交易日数                  │
    │                     │ 预期日 = (end_date - start_date)的 bdate_range   │
    │                     │ 精确到小数点后1位百分比                            │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ missing_days        │ expected_days - actual_days                      │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ total_days          │ df 行数                                           │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ expected_days       │ pd.bdate_range(start, end) 长度                  │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ nan_stats           │ {col: {"count": n, "ratio": pct}}                │
    │                     │ 遍历所有列统计 NaN 数量和比例                      │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ nan_handling        │ "forward fill"（固定，默认前向填充）               │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ slippage_model      │ "fixed 0.1%"（占位，后续可扩展）                  │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ rating              │ completeness ≥ 95% → A                          │
    │                     │ completeness ≥ 90% 且 max_nan_ratio ≤ 0.05 → B │
    │                     │ 其余 → C                                         │
    └─────────────────────┴──────────────────────────────────────────────────┘
    """
    total_days = len(df)

    # NaN 逐列统计
    nan_stats: Dict[str, Dict[str, float]] = {}
    for col in df.columns:
        na_count = int(df[col].isna().sum())
        nan_stats[col] = {"count": na_count, "ratio": round(na_count / total_days, 4)}

    # 预期交易日数
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index) >= 2:
        import pandas as pd
        start_d = df.index[0]
        end_d = df.index[-1]
        expected_days = len(pd.bdate_range(start=start_d, end=end_d))
    else:
        expected_days = total_days

    # 实际非 NaN 天数（以 close 列为准）
    actual_days = int(df["close"].notna().sum()) if "close" in df.columns else total_days
    completeness = round(actual_days / expected_days * 100, 1) if expected_days > 0 else 0.0
    missing_days = expected_days - actual_days

    max_nan_ratio = max(v["ratio"] for v in nan_stats.values()) if nan_stats else 0.0
    if completeness >= 95:
        rating = "A"
    elif completeness >= 90 and max_nan_ratio <= 0.05:
        rating = "B"
    else:
        rating = "C"

    return {
        "source": "akshare",
        "period": "daily",
        "adjusted": "qfq",
        "nan_handling": "forward fill",
        "nan_stats": nan_stats,
        "slippage_model": "fixed 0.1%",
        "commission": "0.03%",
        "real_trade": False,
        "benchmark": "buy&hold",
        "engine_version": "v3.2",
        "completeness": completeness,
        "missing_days": missing_days,
        "total_days": total_days,
        "expected_days": expected_days,
        "fill_method": "forward fill",
        "rating": rating,
    }

### 4.3 metrics_registry.py — 统一指标注册表（v3.0 新增）

**位置：** `src/metrics/metrics_registry.py`

```python
"""
metrics_registry.py — 统一指标注册表

v3.0 新增。确保所有章节使用相同的指标口径定义。
指标信息集中管理，新增指标只需在此注册。

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Callable


METRIC_DEFINITIONS = {
    # ════════════════════════════════════════════════
    # 收益类指标
    # ════════════════════════════════════════════════
    "total_return": {
        "name": "累计收益",
        "formula": "(Final_Equity - Initial_Capital) / Initial_Capital",
        "annualized": False,
        "unit": "%",
        "higher_is_better": True,
        "category": "return",
    },
    "annual_return": {
        "name": "年化收益",
        "formula": "(1 + total_return)^(252/days) - 1",
        "annualized": True,
        "unit": "%",
        "higher_is_better": True,
        "category": "return",
    },
    "cagr": {
        "name": "复合年增长率",
        "formula": "(Final_Equity / Initial_Capital)^(1/years) - 1",
        "annualized": True,
        "unit": "%",
        "higher_is_better": True,
        "category": "return",
    },

    # ════════════════════════════════════════════════
    # 风险类指标
    # ════════════════════════════════════════════════
    "max_drawdown": {
        "name": "最大回撤",
        "formula": "min(Equity / Rolling_Max - 1)",
        "annualized": False,
        "unit": "%",
        "higher_is_better": False,
        "category": "risk",
    },
    "annual_volatility": {
        "name": "年化波动率",
        "formula": "std(daily_return) * sqrt(252)",
        "annualized": True,
        "unit": "%",
        "higher_is_better": False,
        "category": "risk",
    },
    "downside_deviation": {
        "name": "下行标准差",
        "formula": "std(min(daily_return, 0)) * sqrt(252)",
        "annualized": True,
        "unit": "%",
        "higher_is_better": False,
        "category": "risk",
    },
    "underwater_pct": {
        "name": "水下时间占比",
        "formula": "days_in_drawdown / total_days",
        "annualized": False,
        "unit": "%",
        "higher_is_better": False,
        "category": "risk",
    },
    "pain_index": {
        "name": "痛苦指数",
        "formula": "(1/N) * Σ(Drawdown² × Duration_Weight)",
        "annualized": False,
        "unit": "ratio",
        "higher_is_better": False,
        "category": "risk",
        "thresholds": {"low": 0.3, "medium": 0.7},
    },

    # ════════════════════════════════════════════════
    # 风险调整后收益类
    # ════════════════════════════════════════════════
    "sharpe": {
        "name": "夏普比率",
        "formula": "(R_p - R_f) / σ_p",
        "annualized": True,
        "unit": "ratio",
        "higher_is_better": True,
        "category": "risk_adjusted",
    },
    "calmar": {
        "name": "卡尔玛比率",
        "formula": "annual_return / |max_drawdown|",
        "annualized": True,
        "unit": "ratio",
        "higher_is_better": True,
        "category": "risk_adjusted",
    },
    "sortino": {
        "name": "索提诺比率",
        "formula": "(R_p - R_f) / σ_d",
        "annualized": True,
        "unit": "ratio",
        "higher_is_better": True,
        "category": "risk_adjusted",
    },

    # ════════════════════════════════════════════════
    # 交易类指标
    # ════════════════════════════════════════════════
    "win_rate": {
        "name": "胜率",
        "formula": "winning_trades / total_trades",
        "annualized": False,
        "unit": "%",
        "higher_is_better": True,
        "category": "trade",
    },
    "profit_factor": {
        "name": "盈亏比",
        "formula": "total_profit / |total_loss|",
        "annualized": False,
        "unit": "ratio",
        "higher_is_better": True,
        "category": "trade",
    },
    "avg_holding_days": {
        "name": "平均持仓天数",
        "formula": "mean(holding_days)",
        "annualized": False,
        "unit": "days",
        "higher_is_better": False,
        "category": "trade",
    },
    "trade_count": {
        "name": "交易次数",
        "formula": "len(trades)",
        "annualized": False,
        "unit": "count",
        "higher_is_better": False,
        "category": "trade",
    },

    # ════════════════════════════════════════════════
    # 恢复类指标
    # ════════════════════════════════════════════════
    "recovery_factor": {
        "name": "恢复因子",
        "formula": "total_return / |max_drawdown|",
        "annualized": False,
        "unit": "ratio",
        "higher_is_better": True,
        "category": "recovery",
    },
    "avg_recovery_days": {
        "name": "平均恢复时间",
        "formula": "mean(recovery_days_per_drawdown)",
        "annualized": False,
        "unit": "days",
        "higher_is_better": False,
        "category": "recovery",
    },
    "worst_recovery_days": {
        "name": "最长恢复时间",
        "formula": "max(recovery_days_per_drawdown)",
        "annualized": False,
        "unit": "days",
        "higher_is_better": False,
        "category": "recovery",
    },

    # ════════════════════════════════════════════════
    # 信息率类
    # ════════════════════════════════════════════════
    "information_ratio": {
        "name": "信息比率",
        "formula": "(R_p - R_b) / TE",
        "annualized": True,
        "unit": "ratio",
        "higher_is_better": True,
        "category": "info",
    },
    "alpha": {
        "name": "Alpha",
        "formula": "R_p - (R_f + β × (R_m - R_f))",
        "annualized": True,
        "unit": "%",
        "higher_is_better": True,
        "category": "info",
    },
}


def get_metric_info(metric_key: str) -> Optional[Dict[str, Any]]:
    """按 key 查询指标定义。"""
    return METRIC_DEFINITIONS.get(metric_key)


def list_metrics_by_category(category: str) -> Dict[str, Dict[str, Any]]:
    """按分类列出指标。"""
    return {
        k: v for k, v in METRIC_DEFINITIONS.items()
        if v.get("category") == category
    }


def format_metric_value(metric_key: str, value: float) -> str:
    """按指标定义格式化数值输出。

    百分比指标 → "12.34%"
    比率指标 → "1.23"
    天数指标 → "8.5天"
    计数指标 → "45"
    """
    info = get_metric_info(metric_key)
    if info is None:
        return f"{value:.4f}"

    unit = info.get("unit", "ratio")
    if unit == "%":
        return f"{value * 100:.2f}%" if value <= 1 else f"{value:.2f}%"
    elif unit == "days":
        return f"{value:.1f}天"
    elif unit == "count":
        return f"{int(value)}"
    else:
        return f"{value:.2f}"
```

### 4.4 ReportBuilder — 架构分层（v3.0 重构，替代 ReportGenerator）

**位置：** `src/backtest/pipeline/report_builder.py`

**核心变更：** 输入从 `(method, method_result)` 改为 `List[BacktestResultBundle]`（多方法） + `BacktestResultBundle`（组合）。

```python
"""
report_builder.py — v3.0 重构版报告生成器

架构分层：
  Engine → BacktestResultBundle → ReportBuilder → PDF / HTML / Feishu / Knowledge

替换原 report_generator.py，核心变更：
  1. 输入从 (method, method_result) 改为 BacktestResultBundle
  2. 渲染输出按 owner 需求分层（PDF/HTML/Feishu/Knowledge）
  3. 所有指标通过 metrics_registry 统一口径计算

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from markdown_it import MarkdownIt


_md = MarkdownIt()  # 全局实例，复用缓存

from backtest.engine.backtest_result_bundle import BacktestResultBundle
from backtest.pipeline.chart_generator import ChartGenerator
from backtest.pipeline.async_pdf_task import generate_pdf
from metrics.metrics_registry import format_metric_value


logger = logging.getLogger(__name__)


class ReportBuilder:
    """量化研究平台报告生成器（v3.0 重构版）

    接受 BacktestResultBundle 列表，按 owner 指定的分层渲染。

    用法::
        from backtest.pipeline.report_builder import ReportBuilder

        builder = ReportBuilder(
            bundles=bundles,          # List[BacktestResultBundle] — 各方法
            portfolio_bundle=pb,      # BacktestResultBundle — 组合
            chart_gen=chart_gen,
            output_dir="reports/pdf",
        )
        pdf_path = builder.render_pdf(
            symbol="601857.SH",
            date="20260517",
        )
    """

    # ── CSS 模板（同 v2.0 ReportGenerator.CSS_TEMPLATE） ──
    CSS_FULL = """..."""  # 完整 CSS
    CSS_COMPACT = """..."""  # 简洁 CSS

    def __init__(
        self,
        bundles: List[BacktestResultBundle],
        portfolio_bundle: Optional[BacktestResultBundle] = None,
        chart_gen: Optional[ChartGenerator] = None,
        output_dir: str = "reports/pdf",
        task_id: str = "",
        engine_version: str = "v3.0",
    ):
        self._bundles = bundles
        self._portfolio = portfolio_bundle
        self._chart_gen = chart_gen
        self._output_dir = output_dir
        self._task_id = task_id
        self._engine_version = engine_version

    def render_pdf(
        self,
        symbol: str = "",
        date: str = "",
        mode: str = "full",
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        """渲染完整 PDF 报告。"""
        ...

    def render_html(self, mode: str = "full") -> str:
        """生成调试用 HTML。"""
        ...

    def render_feishu_message(self) -> str:
        """生成飞书摘要消息。"""
        ...

    def render_knowledge_entries(self) -> List[Dict[str, Any]]:
        """生成回测驱动的知识条目。"""
        ...

    # ── 章节生成方法 ──
    def _chapter_0_data_quality(self) -> str:
        """第0章：数据质量声明"""
        dq = self._portfolio.data_quality if self._portfolio else {}
        # ... 从 Bundle.data_quality 渲染

    def _chapter_1_params(self) -> str:
        """第一章：回测参数表"""

    def _chapter_2_equity(self) -> str:
        """第二章：净值曲线"""

    def _chapter_3_drawdown(self) -> str:
        """第三章：回撤曲线+热力图"""

    def _chapter_4_metrics(self) -> str:
        """第四章：指标总表 — 所有指标通过 metrics_registry 格式化"""

    def _chapter_5_kline(self) -> str:
        """第五章：K线图+买卖点位"""

    def _chapter_6_trades(self) -> str:
        """第六章：交易行为分析（重构版）"""

    def _chapter_7_regime(self) -> str:
        """第七章：市场状态适应性（重构版）"""

    def _chapter_8_knowledge(self) -> str:
        """第八章：知识库提炼"""

    def _chapter_9_sensitivity(self) -> str:
        """第九章：参数敏感性+RobustScore"""

    def _chapter_10_sample_out(self) -> str:
        """第十章：样本内外对比+Walk Forward"""

    def _chapter_11_correlation(self) -> str:
        """第十一章：策略相关性+组合融合"""

    def _chapter_12_drawdown_recovery(self) -> str:
        """第十二章：连续亏损+回撤恢复+Pain Index"""

    def _chapter_13_rating(self) -> str:
        """第十三章：T1评级→多维评分矩阵"""

    def _appendix(self) -> str:
        """附录"""
```

**方法一览（v3.0 重构版）：**

| 方法 | 可见性 | 输入 | 输出 | 职责 |
|------|--------|------|------|------|
| `render_pdf()` | public | symbol, date, mode, dry_run | `(bool, str)` | 完整PDF渲染入口 |
| `render_html()` | public | mode | `str` | 调试用HTML |
| `render_feishu_message()` | public | — | `str` | 飞书摘要消息 |
| `render_knowledge_entries()` | public | — | `List[Dict]` | 知识条目输出 |
| `_chapter_0~13()` | protected | — | `str` (HTML片段) | 各章节渲染 |
| `_appendix()` | protected | — | `str` | 附录渲染 |
| `_embed_charts()` | protected | md_content, chart_paths | `str` | 图表嵌入 |
| `_md_to_html()` | protected | md_content, mode | `str` | Markdown→HTML（使用 `markdown-it-py`） |

### 4.5 输入/输出协议（v3.0）

**ReportBuilder 输入：**

```
bundles: List[BacktestResultBundle]    ← 各方法回测结果（trend/mean/momentum）
portfolio_bundle: BacktestResultBundle ← 组合回测结果（可选）
```

**ReportBuilder 输出文件：**

```
reports/pdf/
  {task_id}_{version}_{date}.pdf      ← 最终 PDF 报告
  {task_id}_{version}_{date}.html     ← 中间 HTML（调试用）
  charts/
    {symbol}/
      nav_{symbol}_{date}.png
      heatmap_{symbol}_{date}.png
      drawdown_{symbol}_{date}.png
      pnl_dist_{symbol}_{date}.png    ← 新增：盈亏分布
      holding_dist_{symbol}_{date}.png ← 新增：持仓时间分布
      ...
    candlestick/
      candlestick_{method_id}_{date}.png
```

---

## 5. 预估工时（v3.1 修正版）

> 核心组件新增 BacktestResultBundle + metrics_registry，报告重构 6 个章节，综合按 **~9.5h** 估算（含3项S级风险R1/R2/R3修复+原Phase 0前置调研+6个重构章节的数据依赖实现风险缓冲）。

### 5.0 Phase 0: 前置调研与S级风险修复（v3.2 更新）

| 序号 | 子任务 | 工时 | 依赖 | 说明 |
|:----:|--------|:----:|:----:|------|
| 0 | R1: 调查MethodResult输出结构并设计bundle_from_runner()映射表 | 30min | — | 实际核查11字段→17字段映射（§1.0），含缺失字段计算来源标注 |
| 0b | R2: PortfolioManager集成设计（PortfolioIntegration适配器） | 30min | R1 | 设计从MethodResult信号驱动PM，产出equity_curve/trades/daily_metrics（§7.9） |
| 0c | R3: 数据质量算法设计（compute_data_quality） | 20min | — | 设计完整率/NaN统计/滑点验证逻辑，标注Phase 3前占位符（§3.3） |
| **小计** | **Phase 0** | **~80min** | | |

### 5.1 Phase 1: 核心组件

| 序号 | 子任务 | 工时 | 依赖 | 说明 |
|:----:|--------|:----:|:----:|------|
| 1 | 编写 `BacktestResultBundle` dataclass | 15min | — | 含所有字段和类型注解 |
| 2 | 编写 `bundle_from_runner()` 转换函数（含PortfolioIntegration调用） | 20min | 0,1 | MethodBacktestRunner → Bundle（v3.2：包含全字段映射表+PM调用） |
| 3 | 编写 `metrics_registry.py` | 10min | — | 所有指标定义+格式化函数 |
| 4 | 编写 `ReportBuilder` 类骨架 | 10min | — | class, init, 4个render方法 |
| **小计** | **Phase 1** | **50min** | | |

### 5.2 Phase 2: 现有章节修复 + 新增第0章

| 序号 | 子任务 | 工时 | 依赖 | 说明 |
|:----:|--------|:----:|:----:|------|
| 5 | 实现 `_chapter_0_data_quality()` | 8min | 1 | 从 Bundle.data_quality 渲染（v3.2：数据源改为 compute_data_quality() 输出） |
| 6 | 修复第二章：Bundle.equity_curve 替代硬编码 | 8min | 1 | 净值曲线读取路径修正 |
| 7 | 修复第三章：Bundle.equity_curve 计算回撤 | 8min | 1 | 动态计算替代 mock |
| 8 | 修复第四章：metrics_registry 统一口径 | 10min | 3 | 指标格式化 |
| 9 | 修复第五章：Bundle.trades→买卖点位 | 10min | 1 | K线图数据源修复 |
| 10 | 修复附录：Bundle.risk_events→风控记录 | 8min | 1 | 动态渲染替代固定值 |
| 11 | 更新 `render_pdf()` 主流程 | 8min | 4-10 | 编排14章渲染 |
| 5b | 创建 `data_quality.py` 实现 compute_data_quality() | 15min | 0c | 完整率/NaN统计/滑点验证占位符实现（§3.3算法） |
| **小计** | **Phase 2** | **75min** | | |

### 5.3 Phase 3: 新增重构章节（第八章~第十三章重构）

| 序号 | 子任务 | 工时 | 依赖 | 说明 |
|:----:|--------|:----:|:----:|------|
| 12 | `_chapter_6_trades()` — 交易行为分析重构 | 15min | 1,3 | 合并原六+七，盈亏分布/持仓时间/连盈连亏 |
| 13 | `_chapter_7_regime()` — 市场状态适应性重构 | 15min | 1,3 | By Regime/高波动/成交量/板块轮动 |
| 14 | `_chapter_8_knowledge()` — 知识库（Bundle.insights） | 10min | 1 | 从 Bundle 读取知识条目 |
| 15 | `_chapter_9_sensitivity()` — 参数敏感性+RobustScore | 12min | 1,3 | 增加参数稳定性评分计算 |
| 16 | `_chapter_10_sample_out()` — Walk Forward Analysis | 15min | 1,3 | 滚动窗口验证 |
| 17 | `_chapter_11_correlation()` — 组合资金融合模拟 | 12min | 1,3 | 单策略 vs 组合对比表 |
| 18 | `_chapter_12_drawdown_recovery()` — Pain Index | 10min | 1,3 | Avg/Worst Recovery Days等 |
| 19 | `_chapter_13_rating()` — 多维评分矩阵 | 8min | 3,12-18 | 6维评分+Total Score |
| **小计** | **Phase 3** | **97min** | | |

### 5.4 Phase 4: 集成验证

| 序号 | 子任务 | 工时 | 依赖 | 说明 |
|:----:|--------|:----:|:----:|------|
| 20 | 单元测试 `test_backtest_result_bundle.py` | 10min | 1-2 | 字段存在性+数据完整性 |
| 21 | 单元测试 `test_metrics_registry.py` | 10min | 3 | 所有指标注册+格式化 |
| 22 | 单元测试 `test_report_builder.py` | 15min | 4-19 | 14章全部渲染+数据一致性 |
| 23 | 集成测试：Engine→Bundle→Builder→PDF | 15min | 20-22 | 全链路验证 |
| 24 | 集成测试：HTML中间文件可浏览器查看 | 5min | 23 | 样式检查 |
| 25 | 集成测试：简洁模式验证 | 5min | 23 | 章节跳转正确 |
| **小计** | **Phase 4** | **60min** | | |

### 5.5 Phase 5: 模板打磨

| 序号 | 子任务 | 工时 | 依赖 | 说明 |
|:----:|--------|:----:|:----:|------|
| 26 | CSS 打磨（新增数据质量/评分矩阵/RobustScore样式） | 15min | 4-19 | 新增样式统一 |
| 27 | Walk Forward 可视化优化（窗口色块） | 10min | 16 | 色块+箭头渲染 |
| 28 | 连盈连亏可视化序列 | 10min | 12 | 序列条渲染 |
| 29 | TOC 超链接导航更新（14章+附录） | 10min | 4-19 | 新章节加入TOC |
| 30 | 性能优化（大图压缩、Bundle缓存） | 15min | 23 | 大 Bundle 场景 |
| **小计** | **Phase 5** | **60min** | | |

### 5.6 工时汇总（v3.2 更新）

| Phase | 说明 | 工时 | 建议执行时间 | 相较v3.1增减 |
|:-----:|------|:----:|:-----------:|:----------:|
| Phase 0 | R1+R2+R3 S级风险修复 + 前置调研 | ~80min | 启动前必须完成 | +50min |
| Phase 1 | 核心组件（含bundle_from_runner全映射+PM调用） | ~55min | 第一优先 | +5min |
| Phase 2 | 现有章节修复 + 第0章 + data_quality.py实现 | ~75min | 第二优先 | +15min |
| Phase 3 | 新增重构章节（6~13章） | ~97min | 第三优先 | — |
| Phase 4 | 集成验证 | ~60min | 第四优先 | — |
| Phase 5 | 模板打磨 | ~60min | 后续迭代 | — |
| **总计** | | **~9.5h** | | **+1.5h** |

**改动说明（vs v2.0）：**
- Phase 1 新增：BacktestResultBundle + metrics_registry（替代原 ReportGenerator 骨架）
- Phase 2 新增：数据质量声明章节
- Phase 3 重构：6个章节重写（六/七/九/十/十一/十二/十三）
- Phase 4 扩展：更多单元测试覆盖
- Phase 5 扩展：新增 CSS 样式需求

---

## 6. 依赖检查

### 6.1 新增依赖（v3.1 修正：零新增依赖）

| 包名 | 版本约束 | 用途 | 安装状态 |
|------|:--------:|------|:--------:|
| `markdown-it-py` | 4.0.0 | Markdown→HTML 转换（替代 `markdown` 库） | ✅ **已安装**，零新增 |

**说明：**
- 原方案拟新增 `markdown` 库作为唯一依赖；实际核查发现系统已安装 `markdown-it-py 4.0.0`，功能等价，无需额外安装。
- `report_renderer.py` 的纯 Python 模板引擎负责生成 Markdown 内容，`markdown-it-py` 负责最后的 Markdown→HTML 转换，功能互补。
- 从 `markdown-it-py` 切换到 `markdown` 无额外收益，故保持使用已安装的 `markdown-it-py`。

### 6.2 已存依赖（无需安装）

| 包名 | 用途 | 是否已使用 |
|------|------|:---------:|
| `matplotlib` | 图表生成（ChartGenerator 依赖） | ✅ |
| `pandas` | 数据分析（BacktestResultBundle 基础类型） | ✅ |
| `numpy` | 数值计算（metrics_registry 依赖） | ✅ |
| `scipy` | Spearman 相关系数（策略相关性矩阵可选） | ⚠️ 备选回退 |
| `markdown-it-py` | Markdown→HTML 转换（PDF 管道） | ✅ 替代 `markdown` 库 |

### 6.3 系统依赖

| 组件 | 版本 | 用途 | 备注 |
|------|:----:|------|:----:|
| Microsoft Edge | ≥ 91 (Chromium) | Headless HTML→PDF | ✅ Windows 标配 |
| Python | ≥ 3.10 | dataclass + type hints | ✅ |

---

## 7. 与现有系统的集成点

### 7.1 集成地图（v3.0 更新）

```
┌─────────────────────────────────────────────────────────────┐
│ 现有系统                                   ← 集成点 → 新增组件 │
├─────────────────────────────────────────────────────────────┤
│ MethodBacktestRunner.run()                                   │
│   → BacktestResultBundle  ──── 输入 ──→ ReportBuilder       │
├─────────────────────────────────────────────────────────────┤
│ KnowledgeAnalyzer.generate_summary_report()                  │
│   → str (Markdown)       ──── (保留备用) ──→ ReportBuilder   │
├─────────────────────────────────────────────────────────────┤
│ ChartGenerator.generate_all()                                │
│   → dict[name→path]      ──── 输入 ──→ ReportBuilder         │
├─────────────────────────────────────────────────────────────┤
│ async_pdf_task.generate_pdf()                                │
│   ← HTML → PDF            ──── 调用 ──→ ReportBuilder        │
├─────────────────────────────────────────────────────────────┤
│ BitableSync (扩展)                                           │
│   ← 上传附件               ──── 调用 ──→ ReportBuilder        │
├─────────────────────────────────────────────────────────────┤
│ metrics_registry                                             │
│   → 统一指标口径            ──── 引用 ──→ 所有章节生成      │
├─────────────────────────────────────────────────────────────┤
│ Future Dashboard (v3.0 新增)                                 │
│   ← 从 Bundle 读取        ──── 集成 ──→ BacktestResultBundle │
├─────────────────────────────────────────────────────────────┤
│ 本地文件系统: reports/pdf/ 目录                               │
│   ← 写入                   ──── 输出 ──→ ReportBuilder       │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 集成点详表

| 集成点 | 被集成组件 | 调用方式 | 输入 | 输出 | 备注 |
|:------:|-----------|----------|------|------|------|
| P1 | MethodBacktestRunner | 函数调用 → bundle_from_runner | runner_result | `BacktestResultBundle` | v3.0 新增集成点 |
| P2 | ChartGenerator | 构造注入 | multi_result | `Dict[str, str]` | `generate_all()` 已就绪 |
| P3 | async_pdf_task | 函数调用 | HTML 路径, PDF 路径 | `bool` | `generate_pdf()` 已就绪 |
| P4 | BitableSync | 方法扩展 | PDF 路径 | `bool` | 需新增 `upload_attachment()` |
| P5 | metrics_registry | import引用 | metric_key, value | `str` | 所有章节统一使用 |
| P6 | Future Dashboard | 数据读取 | `BacktestResultBundle` | Dashboard 数据 | v3.0 新增集成点 |

### 7.3 所有消费方统一从 BacktestResultBundle 读取

```
BacktestResultBundle
  ├── ReportBuilder          — 报告生成（PDF/HTML/Feishu/Knowledge）
  ├── KnowledgeSearch        — 知识库搜索（从 Bundle.insights 检索）
  ├── BitableSync            — 飞书同步（从 Bundle.summary_metrics 写入记录）
  ├── Future Dashboard       — 可视化仪表盘（从 Bundle.equity_curve/daily_metrics 渲染）
  └── 回测比较器              — 跨 run_id 对比（从 Bundle.summary_metrics 聚合）
```

### 7.4 Future Dashboard 集成框架

```python
# Future Dashboard 数据接口（v3.0 预留）
# 位置：src/dashboard/data_provider.py

from backtest.engine.backtest_result_bundle import BacktestResultBundle


class DashboardDataProvider:
    """从 BacktestResultBundle 构建 Dashboard 数据。"""

    def build_equity_chart_data(
        self, bundles: List[BacktestResultBundle]
    ) -> dict:
        """构建净值曲线图数据。"""
        ...

    def build_metrics_overview(
        self, bundles: List[BacktestResultBundle]
    ) -> list:
        """构建指标总览卡片数据。"""
        ...

    def build_regime_performance(
        self, bundle: BacktestResultBundle
    ) -> list:
        """构建市场状态适应性表。"""
        ...

    def build_parameter_surface(
        self, bundle: BacktestResultBundle
    ) -> dict:
        """构建参数扫描热力图数据。"""
        ...

    def build_walk_forward_data(
        self, bundle: BacktestResultBundle
    ) -> list:
        """构建 Walk Forward 滚动验证数据。"""
        ...
```

### 7.5 报告结构已支持未来场景

| 未来场景 | 对应章节 | 备注 |
|:--------:|:--------:|------|
| 打板策略回测 | 第六章（交易行为分析）日内交割特征 | 持仓时间分布已支持秒级精度 |
| 游资行为分析 | 第七章（市场状态适应性）放量/缩量 | 成交量放大期分析可替换为龙虎榜数据 |
| 多品种组合 | 第十一章（组合资金融合）多标的分散化 | 相关性矩阵可扩展为多品种协方差矩阵 |
| 高频回测 | 第0章（数据质量声明）分钟级精度 | period字段支持 minute/tick |
| AI策略分析 | 第八章（知识库提炼）置信度积累 | KnowledgeEntry 已预留置信度趋势 |

### 7.6 BitableSync 扩展需求

（同 v2.0，需要新增 `upload_attachment()` 和 `update_record_attachment()` 方法）

### 7.7 本地存储路径设计

```
reports/pdf/
  {task_id}_{version}_{date}.pdf              ← 主报告 PDF
  {task_id}_{version}_{date}.html             ← 中间 HTML（调试保留）
  charts/
    {symbol}/
      nav_{symbol}_{date}.png
      heatmap_{symbol}_{date}.png
      drawdown_{symbol}_{date}.png
      pnl_dist_{symbol}_{date}.png            ← 新增
      holding_dist_{symbol}_{date}.png         ← 新增
      ...
```

### 7.8 调用示例（v3.2 完整管道，含 PortfolioManager 集成）

```python
#!/usr/bin/env python3
"""v3.2 完整管道示例：从 Engine 到 PDF（含 PortfolioManager 集成）。

注意（v3.2）：MethodBacktestRunner 确认位于 backtest/runners/，产出 MethodResult（11字段），
bundle_from_runner() 接受 MethodResult + 可选的 PortfolioManager 输出 + ctx + price_df。
"""

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

---

### 7.9 PortfolioManager -> Runner 集成设计（v3.2 修复 R2）

**背景：** `MethodBacktestRunner` 仅输出信号（MethodResult.signals），不执行资金模拟；
`PortfolioManager`（`backtest/engine/portfolio/portfolio_manager.py`）已存在但未与 Runner 集成。
Bundle 需要的 equity_curve、trades、daily_metrics 三个字段均无法直接从 MethodResult 获取。

**PortfolioManager 接口调查：**

| Method | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `__init__()` | initial_cash, commission_pct, slippage_pct | - | 初始化仓位管理器 |
| `process_signal()` | signal(-1/0/1), price, symbol | Order | 处理信号，更新现金/持仓，生成订单 |
| `record_equity()` | current_price | None | 记录当前权益到 equity_curve |
| `get_portfolio_value()` | current_price | float | 计算组合市值 |
| `get_total_return()` | - | float | 计算总收益率 |
| `get_peak_drawdown()` | - | float | 计算最大回撤 |
| `summary()` | - | Dict | 汇总报告（cash/trades/return/drawdown） |
| `reset()` | - | None | 重置为初始状态 |

**集成方案：PortfolioIntegration 适配器**

新建 `backtest/engine/portfolio_integration.py`，封装 PortfolioManager 的逐Bar驱动逻辑，
产出 `PortfolioOutput`（equity_curve / trades / daily_metrics）供 `bundle_from_runner()` 消费。

详细设计见 §7.8 上方 PortfolioIntegration 类定义。集成流程：

```
BacktestEngine
  -> MethodBacktestRunner.run(df) -> MethodResult (signals/indicators/statistics)
  -> PortfolioIntegration.run(method_result, price_df) -> PortfolioOutput
      |-- equity_curve    -> bundle.equity_curve
      |-- trades          -> bundle.trades
      L-- daily_metrics   -> bundle.daily_metrics
  -> bundle_from_runner(method_result, ctx, portfolio_output, price_df, config)
  -> BacktestResultBundle -> ReportBuilder
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

---

### 7.10 data_quality 文件位置（v3.2 新增）

**位置：** `src/backtest/engine/data_quality.py`

```python
"""
data_quality.py - 数据质量计算（v3.2 新增）

核心算法：
  1. 数据完整率 = 实际天数 / 预期天数
  2. 缺失值统计 = NaN比例
  3. 滑点验证 = 占位符（Phase 3 实现）

详细设计：见 SS3.3「数据质量检测算法设计」
作者: 墨衡
创建时间: 2026-05-17
"""

def compute_data_quality(df, df_expected, config):
    # 实现见 SS3.3 算法设计
    pass

---

## 8. 快速启动指南（今晚）

### 8.1 执行清单

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
```

### 8.2 验收标准

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
| 简洁模式 | 仅5章+附录，跳过第0章 |

---

## 附录 A：备选方案对比详情

### A.1 WeasyPrint 方案

**优点**：
- 跨平台（Linux/macOS/Windows）
- CSS 控制精准（支持 `@page` 分页）
- 可直接渲染 HTML+CSS，无需外部浏览器进程

**缺点**：
- 需要 GTK 运行时（Windows 安装麻烦）
- 中文需要额外配置系统字体
- 重新学习 weasyprint API 的时间成本

**适合场景**：未来需要跨平台部署时。

### A.2 ReportLab 方案

**优点**：
- 像素级控制布局
- 纯 Python，无外部依赖
- 支持嵌入字体（PDF 内嵌中文字体）

**缺点**：
- 所有布局需手写代码（表格、段落、分页）
- 图表需额外转换为嵌入格式
- 开发效率极低
- 学习曲线陡峭

**适合场景**：需要生成银行级精确定制的票据/证书。

### A.3 推荐结论

```
实时性优先  ───────── Edge headless (推荐本方案)
跨平台需求  ───────── WeasyPrint (备选)
像素级控制  ───────── ReportLab (不推荐)
```

---

*本文档由墨衡编写，2026-05-17 20:45 +08:00，v3.0 升级于 2026-05-17 22:13 +08:00，v3.1 修复于 2026-05-17 22:30 +08:00，v3.2 S级风险修复于 2026-05-17 22:44 +08:00。*
