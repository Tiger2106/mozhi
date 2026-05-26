<!--
author: 墨衡
created_time: 2026-05-16T15:55+08:00
updated_time: 2026-05-16T15:57+08:00
task_id: C1
-->

# C1: 日报接入 knowledge.db 消费 — 设计方案与实现文档

## 1. 现状分析

### 1.1 knowledge.db 内容

| 表名 | 行数 | 核心字段 | 状态 |
|------|------|----------|------|
| `backtest_runs` | 694 | run_id, strategy, symbol, config_key, data_days, param_version, created_at | ✅ 就绪 |
| `params_snapshot` | 694 | run_id, param_version, params_json | ✅ 就绪 |
| `market_context` | 694 | run_id, date_key, symbol, market_regime, volatility_level, trend_strength | ✅ 就绪 |
| `performance_results` | 694 | run_id, total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate_pct, profit_factor, total_trades, validity_grade | ✅ 就绪 |
| `knowledge_entries` | 16 | symbol, strategy, confidence, sample_size, avg_return_pct, avg_sharpe, avg_max_dd_pct, insight_category, market_regime, status | ✅ 就绪 |

### 1.2 现有管线步骤

| 步骤 | Agent | 产出 | 说明 |
|:----:|:-----:|:----|------|
| Step0 | 玄知 | macro_analysis.json | 市场扫描 |
| Step1 | 墨衡 | structured_analysis.json | 结构化分析 |
| Step2 | 墨萱 | morning_draft.md | 报告草稿 |
| Step3 | 墨衡 | review_feedback.md | 质量审查 |
| Step3.5 | 玄知 | strategic_review.json | 战略复核 |
| Step4 | 墨萱 | final_report.md | 汇总定稿 |
| Step5 | 墨涵 | 飞书推送 | 发布 |

所有步骤通过 spawn trigger + .done 信号文件通信，彼此独立。

### 1.3 知识库可消费的内容

| 消费类型 | 数据源 | 报告用途 |
|----------|--------|----------|
| 策略历史绩效 | knowledge_entries | 展示各策略在 601857/000001.SZ 上的历史表现 |
| 市场状态标签 | market_context.volatility_level, .market_regime | 提供当日市场环境的"特征标签" |
| 置信度标注 | knowledge_entries.confidence | 为操作建议附加可信度信息 |
| 样本量参考 | knowledge_entries.sample_size | 说明结论的统计显著性 |
| 相似市况 | market_context | 历史相似环境下的策略表现参考 |

## 2. 设计方案

### 2.1 核心思路：增量增强

**不新增 pipeline 步骤**，亦不修改 Step0–Step5。

改为构建两层封装：
1. **KnowledgeService** — 查询层，封装 knowledge.db 的只读接口
2. **ReportEnricher** — 增强层，读取 Step1 产出的 structured_analysis，查询知识库，写入独立 knowledge_context 文件

```
Step1(墨衡分析)
     ↓  structured_analysis.json
ReportEnricher 执行增强 (内联，可在 scheduler 中直接 import)
     ↓  knowledge_context_{task_id}.json
Step2(墨萱草稿) — 可选读取 knowledge_context 增强报告
```

### 2.2 增强时机

| 时机 | 说明 |
|------|------|
| Step1 完成 → Step2 之前 | (推荐) 从 structured_analysis 提取标的，查询知识库，写入 knowledge_context |
| Step2 / Step4 中 | 各 agent 在收到 task 时可查看 knowledge_context 文件 |

### 2.3 设计约束满足情况

| 约束 | 满足情况 |
|------|----------|
| 不破坏 Step0–Step5 | ✅ 不修改现有步骤 |
| 增量增强 | ✅ knowledge_context 为独立附加文件 |
| 与 scheduler_agent.py 兼容 | ✅ 可直接 import 内联调用 |
| 路径规范 | ✅ 产出文件使用英文命名，中文注释 |

### 2.4 回退方案

KnowledgeService/ReportEnricher 任一环节失败：
- ReportEnricher 输出 status="SKIPPED"
- 不阻塞管线，不写 .failed 文件
- Step2 agent 看到 status=SKIPPED 时跳过增强引用

## 3. 实现

### 3.1 文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| `knowledge_service.py` | `src/morning_pipeline/knowledge_service.py` | 知识库查询层 |
| `report_enricher.py` | `src/morning_pipeline/report_enricher.py` | 报告增强器 |
| 本设计文档 | `docs/02_development/knowledge_db_report_integration.md` | 设计说明 |

### 3.2 KnowledgeService 接口

| 方法 | 用途 | 返回 |
|------|------|------|
| `summarize()` | 知识库概览 | dict: 各表行数、活跃条目、标的/策略列表 |
| `get_strategy_stats(symbol)` | 获取某标的所有策略条目 | list[dict] |
| `get_best_strategy(symbol)` | 最优策略（按置信度+样本量加权） | dict or None |
| `get_strategy_comparison(symbol)` | 策略对比 | dict |
| `get_market_context_summary()` | 市场环境分布汇总 | dict |
| `get_knowledge_insights_for_report(symbols)` | 为报告生成知识洞察（含可读摘要） | list[dict] |
| `get_strategy_performance_summary(symbol)` | 策略绩效总结 | dict or None |

### 3.3 ReportEnricher 接口

| 方法 | 用途 |
|------|------|
| `generate_knowledge_context(analysis)` | 从 structured_analysis dict 生成知识上下文 |
| `write_knowledge_context(output_path, ctx)` | 写入 knowledge_context JSON 文件 |
| `enrich_analysis_file(analysis_path)` | 从文件读入，写入增强文件 |

### 3.4 scheduler_agent.py 集成（示例）

```python
# 在 _run_pipeline() 中，Step1 完成后调用
from morning_pipeline.report_enricher import enrich_report

# Step1 产出路径
analysis_path = reports_dir / f"structured_analysis_{task_id}.json"
# 增强
kctx_path = enrich_report(analysis_path, output_dir=reports_dir)
if kctx_path:
    logger.info(f"知识上下文已写入: {kctx_path}")
```

## 4. 验证结果

### 4.1 KnowledgeService 自检

```
=== 概览 ===
  knowledge.db: 694 runs, 16 entries, 694 contexts
  活跃知识条目: 16
  涉及标的: ['000001.SZ', '601857', '601857.SH']
  涉及策略: ['grid', 'reversal', 'trend']

=== 601857 策略统计 (排序正确: high→medium→low) ===
      网格策略 | conf=  high | n=440 | ret=1.4846% | sharpe=2.50
      网格策略 | conf=  high | n=440 | ret=1.4846% | sharpe=2.50
      反转策略 | conf=medium | n= 19 | ret=0.0000% | sharpe=0.00
      趋势策略 | conf=medium | n=  4 | ret=0.0000% | sharpe=0.00
      网格策略 | conf=   low | n=  1 | ret=0.0000% | sharpe=0.00

601857 最优策略: 网格策略 (conf=high, n=440, sharpe=2.50)

=== 市场环境 ===
  sideways: 693 (99.9%)
  bear: 1 (0.1%)
  典型状态: sideways / 典型波动: low
```

### 4.2 ReportEnricher 增强效果

**输入**: 模拟 structured_analysis（标的 601857）
**输出**: knowledge_context.json

```
状态: READY
标注的标的: ['601857', '601857.SH', '601857.SZ']
知识洞察数: 12 (高→中→低排序)
策略总结数: 1 (去重后，归一化到 601857)
市场环境: sideways / low
关键洞察: "601857 网格策略在 440 次历史回测中，
           平均收益 1.48%，夏普比率 2.50
           （high置信度）"
最佳策略: 网格策略 | 夏普: 2.50 | 总试次: 927
```

### 4.3 增强效果示例（报告中）

原报告模板 `daily.md` 在增强后可在"历史参考"部分增加如下内容：

```markdown
---

## 【增强】知识库历史参考

| 策略 | 置信度 | 样本量 | 平均收益 | 夏普比率 | 最大回撤 |
|:----|:------:|:------:|:--------:|:--------:|:--------:|
| 网格 | high | 440次 | 1.48% | 2.50 | 0.27% |
| 反转 | medium | 19次 | 0.00% | 0.00 | — |
| 趋势 | medium | 4次 | 0.00% | 0.00 | — |

> 今日市场环境标签：**sideways**（与 99.9% 历史回测环境一致）
> 网格策略在 sideways 环境下历史胜率最高（夏普 2.50，440次回测验证）
```

## 5. 核心数据流

```
knowledge.db
     │
     ▼
KnowledgeService  ──只读──▶  knowledge_entries
(query methods)                     market_context
                                    performance_results
     │
     ▼
ReportEnricher.generate_knowledge_context()
     │  1. 从 structured_analysis 提取标的 (601857, 000001.SZ …)
     │  2. 调用 KnowledgeService 查询
     │  3. 组装 knowledge_insights + strategy_summaries + market_context
     ▼
knowledge_context_{task_id}.json
     │
     ├──▶ Step2(墨萱): 报告中插入"知识库历史参考"板块
     ├──▶ Step3(墨衡审查): 核查结论与历史数据一致性
     └──▶ Step4(墨萱定稿): 可选择性引用
```
