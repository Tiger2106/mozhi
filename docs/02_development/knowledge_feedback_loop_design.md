# 知识反馈循环设计

> 墨枢 P1-15: 让日报/分析结论回写 knowledge.db，形成持续更新的知识闭环
>
> 作者：墨衡（MoHeng）
> 创建时间：2026-05-16T17:00+08:00
> 版本：v1.0
> 状态：设计完成
> 响应：玄知战略评审 #知识库重存轻用

---

## 1. 当前状态（单向流分析）

### 1.1 现有知识流

```
                        ┌──────────────────────────┐
                        │    回测引擎 (backtest)     │
                        │     _persist_result()     │
                        └────────────┬─────────────┘
                                     │ store_run()
                                     ▼
                        ┌──────────────────────────┐
                        │      knowledge.db         │ ← 694回测记录, 16知识条目
                        │  6张表: backtest_runs     │
                        │  knowledge_entries        │
                        │  market_context 等         │
                        └────────────┬─────────────┘
                                     │ query
                                     ▼
                        ┌──────────────────────────┐
                        │  KnowledgeService(只读)    │ ← Step0.5 消费
                        │  ReportEnricher           │
                        └────────────┬─────────────┘
                                     │ knowledge_context_{task_id}.json
                                     ▼
                        ┌──────────────────────────┐
                        │  晨报管线 Step1→Step5     │
                        │  墨衡分析 + 墨萱草稿      │
                        │  墨衡审查 + 玄知复核      │
                        │  墨涵推送                 │
                        └──────────────────────────┘
```

### 1.2 关键问题

| 问题 | 说明 | 影响 |
|:-----|:------|:------|
| **知识只进不出** | 回测结果 → knowledge_entries 是单向的 | 日报中的新鲜结论无法沉淀 |
| **报告结论丢失** | "科创50单日-2.55%修复概率约15%"这类由分析得出的新认知不会被写回 | 相同场景下次仍需重新分析 |
| **知识时效性盲区** | knowledge_entries 只标记"衰减"（90天未更新），没有"验证/证伪"机制 | 旧知识可能持续有效也可能已被 market 证伪 |
| **缺乏人工干预入口** | 玄知战略评审、墨涵运营判断都不能直接更新 knowledge_entries | 人工经验无法沉淀为系统知识 |

### 1.3 可以回写但未回写的数据源

| 数据源 | 产出文件 | 适合回写的内容 | 回写价值评估 |
|:-------|:---------|:--------------|:------------|
| **Step1 墨衡分析** | `structured_analysis.json` | 核心驱动逻辑、风险判断、操作建议框架 | ⭐⭐⭐⭐⭐ 最高价值 |
| **Step2 墨萱草稿** | `morning_draft.md` | 具体数据结论和对比 | ⭐⭐⭐⭐ |
| **Step3 墨衡审查** | `review_feedback.md` | 事实准确性校验、WARN/FAIL 判定 | ⭐⭐⭐ |
| **Step3.5 玄知复核** | `strategic_review.json` | 宏观判断校准、市场状态评估 | ⭐⭐⭐⭐ |
| **Step4 墨萱定稿** | `final_report.md` | 最终结论、操作建议 | ⭐⭐⭐⭐⭐ |
| **02:00 运维报告** | `daily_doc_report.md` | 知识库状态、备份状态 | ⭐⭐ |

---

## 2. 目标状态（闭环架构图）

### 2.1 闭环后的知识流

```
                        ┌──────────────────────────┐
                        │    回测引擎 (backtest)     │
                        │    → knowledge_entries     │
                        │    (现有路径，保持不变)      │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │      knowledge.db         │
                        │  现有6张表 + 新增反馈表    │
                        └─────────┬───┬───────────-┘
                                  │   ▲
                    Step0.5 查询   │   │ 反馈写回
                                  │   │
                                  ▼   │
                        ┌──────────────────────────┐
                        │  晨报管线 Step1→Step5     │
                        │  (各步骤产生新结论)        │
                        └──────┬────┬──────┬─────-┘
                               │    │      │
                     ┌─────────┘    │      └──────────┐
                     ▼              ▼                 ▼
              ┌──────────┐  ┌──────────┐   ┌──────────────┐
              │ 墨衡分析  │  │ 墨萱报告  │   │ 玄知复核     │
              │ 结论提取  │  │ 结论提取  │   │ 结论提取     │
              └─────┬────┘  └─────┬────┘   └──────┬──────-┘
                    │              │               │
                    └──────────────┼──────────────-┘
                                  │
                                  ▼
                        ┌──────────────────────────┐
                        │    KnowledgeFeedback      │
                        │    (轻量反馈写入模块)       │
                        │                          │
                        │    四个接口：              │
                        │    step1_feedback()       │
                        │    step2_feedback()       │
                        │    step4_feedback()       │
                        │    batch_maintenance()    │
                        └────────────┬──────────────┘
                                     │ write_feedback()
                                     ▼
                        ┌──────────────────────────┐
                        │  knowledge_feedback 表    │ ← 新增
                        │  (而非修改 knowledge_entries)│
                        └──────────────────────────┘
```

### 2.2 设计原则

| 原则 | 说明 |
|:-----|:------|
| **绝不覆盖** | 反馈永远=追加写入，从不覆盖回测知识 |
| **轻量优先** | <100行核心代码，不引入新依赖 |
| **管线解耦** | 反馈是增强，不是依赖。反馈失败不阻塞管线 |
| **渐进实施** | 三阶段逐步增加复杂度 |
| **置信度分层** | 回测知识 > 分析结论 > 单次观察 |

### 2.3 反馈数据的生命周期

```
分析结论 (Step1/2/4) ─→ 写入 feed 表 ─→ 状态: pending
                                              │
                                ┌─────────────┼─────────────┐
                                ▼             ▼             ▼
                          回测验证通过    回测部分验证    回测证伪
                                │             │             │
                                ▼             ▼             ▼
                          → entries 合并  → 保持 feed   → 标记 rejected
                          状态: verified    状态: partial    状态: rejected
```

---

## 3. 设计方案（推荐方案 + 备选方案）

### 3.1 推荐方案：独立反馈表（轻量追加模式）

**核心思路**：不修改 `knowledge_entries` 表结构，新增一张 `knowledge_feedback` 表专门存放日报分析结论。回测驱动的知识聚合和日报驱动的分析结论各有独立表空间，后续通过查询层（`KnowledgeService` 扩展）按权重合并展示。

#### 3.1.1 为什么选择独立表而非扩展现有表？

| 方案 | 优点 | 缺点 | 选型 |
|:-----|:------|:------|:-----|
| 扩展 knowledge_entries（新增 source_type 字段） | 一条查询即可合并 | UNIQUE 约束需调整；回测知识被污染风险 | ❌ 不推荐 |
| **独立 knowledge_feedback 表** | 完全隔离，互不影响，迁移成本低 | 查询需 UNION/两次查询 | ✅ **推荐** |
| 直接写入同表但用 source_type 区分 | 代码改动小 | 未来维护复杂，聚合逻辑翻倍 | ❌ 不推荐 |

#### 3.1.2 推荐方案理由

1. **隔离性**：回测知识 = 定量 + 多日聚合（置信度体系成熟），分析结论 = 定性 + 单日判断（置信度天然较低）。混存会破坏现有置信度判定逻辑
2. **可逆性**：独立表可以随时清空重试，不影响核心知识库
3. **扩展性**：未来可以加入更丰富的元数据（模型版本、agent 版本、分析框架版本）而不污染主表
4. **简单性**：新增一个模块文件即可，无需重构现有任何代码

### 3.2 备选方案：直接扩展 knowledge_entries（单表模式）

仅在以下条件同时满足时考虑：
- 需要频繁将反馈结论与回测知识 JOIN 查询
- 性能敏感（两个表 JOIN 成本过高）
- 团队有足够信心保证写入逻辑不会污染现有数据

当前不满足上述条件，故选择独立表方案。

---

## 4. 数据模型变更

### 4.1 新增表：`knowledge_feedback`

```sql
-- ============================================================
-- 知识反馈表 — 存放日报/分析结论中的新认知
-- 与 knowledge_entries 独立，互不干扰
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_feedback (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 标的信息
    symbol            TEXT NOT NULL,             -- 标的代码，如 '601857.SH'
    strategy          TEXT NOT NULL DEFAULT '',  -- 策略（可选，分析结论不限定策略时留空）

    -- 反馈内容
    insight_text      TEXT NOT NULL,             -- 结论原文（短文本，建议≤200字）
    insight_category  TEXT NOT NULL DEFAULT 'report_observation',
                                                 -- 类别：见下方预定义值
    source_step       TEXT NOT NULL,             -- 'step1' | 'step2' | 'step3' | 'step4'
    source_agent      TEXT NOT NULL,             -- 'moheng' | 'moxuan' | 'xuanzhi'
    source_task_id    TEXT NOT NULL,             -- 来源任务 ID，可溯源
    source_date       TEXT NOT NULL,             -- 结论产生日期 YYYYMMDD

    -- 置信度体系
    confidence        TEXT NOT NULL DEFAULT 'low',
                                                 -- 'high' | 'medium' | 'low'
    confidence_notes  TEXT DEFAULT '',           -- 置信度理由

    -- 关联验证
    matches_knowledge_id  INTEGER DEFAULT NULL,  -- 若与某条已有知识条目匹配，关联
    status            TEXT NOT NULL DEFAULT 'pending',
                                                 -- 'pending' | 'verified' | 'partial' | 'rejected'
    verified_at       TEXT DEFAULT NULL,         -- 被验证/证伪的时间

    -- 元数据
    extra_meta        TEXT NOT NULL DEFAULT '{}', -- 扩展元数据 (JSON)
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    FOREIGN KEY (matches_knowledge_id) REFERENCES knowledge_entries(id) ON DELETE SET NULL
);

-- 索引（按查询访问模式设计）
CREATE INDEX IF NOT EXISTS idx_kf_symbol    ON knowledge_feedback(symbol);
CREATE INDEX IF NOT EXISTS idx_kf_step     ON knowledge_feedback(source_step);
CREATE INDEX IF NOT EXISTS idx_kf_date     ON knowledge_feedback(source_date);
CREATE INDEX IF NOT EXISTS idx_kf_status   ON knowledge_feedback(status);
CREATE INDEX IF NOT EXISTS idx_kf_match    ON knowledge_feedback(matches_knowledge_id);
CREATE INDEX IF NOT EXISTS idx_kf_category ON knowledge_feedback(insight_category);
CREATE INDEX IF NOT EXISTS idx_kf_conf     ON knowledge_feedback(confidence);

-- 复合索引：按标的时间倒序查询
CREATE INDEX IF NOT EXISTS idx_kf_symbol_date
    ON knowledge_feedback(symbol, source_date DESC);
```

### 4.2 `insight_category` 预定义值（反馈专用）

| 类别 | 适用场景 | 示例 |
|:-----|:---------|:------|
| `report_observation` | 市场观察型结论（默认） | "A股科技修复难度大，历史类似场景修复概率约15%" |
| `risk_judgment` | 风险评估 | "三重事件叠加，风险密度极高" |
| `strategy_evaluation` | 策略评价 | "网格策略在sideways环境下历史胜率最高" |
| `operation_suggestion` | 操作建议 | "建议持币比例≥50%，等待方向确认" |
| `catalyst_analysis` | 催化剂分析 | "峰会成果若超预期，A股可能独立走强" |
| `regime_judgment` | 市场状态判断 | "当前市场处于中性偏谨慎状态" |
| `contradiction` | 数据矛盾发现 | "美股AI强势 vs A股科技深度回调，跨境外溢权重被高估" |

### 4.3 置信度判定体系

#### 4.3.1 反馈置信度 `confidence` 判定规则

| 条件 | confidence | 说明 |
|:-----|:-----------|:------|
| 同一结论被 3+ 份独立日报验证 | high | 有足够的观测一致性 |
| 结论有定量数据支撑（如"历史显示X%概率"） | medium | 有量化基础 |
| 纯定性判断或首次观察 | low | 需要更多验证 |

#### 4.3.2 验证状态 `status` 判定规则

| 状态 | 条件 | 含义 |
|:-----|:------|:------|
| `pending` | 刚写入，未与其他数据比对 | 待验证 |
| `verified` | 后续回测/数据与该结论一致 | 已被证实 |
| `partial` | 部分验证通过，有矛盾也有支持 | 部分有效 |
| `rejected` | 后续数据证伪该结论 | 已被推翻 |

#### 4.3.3 从回测端验证的时间判断

`verified_at` 字段记录验证时间。

**推荐验证窗**：反馈写入后等待 7-30 天，观察后续回测结果是否支持该结论。设置为 14 天为佳（两周交易窗口足以覆盖大多数短期判断的验证）。

### 4.4 简单规则总结

| 维度 | 回测知识 (knowledge_entries) | 反馈知识 (knowledge_feedback) |
|:-----|:----------------------------|:-----------------------------|
| 数据来源 | 回测引擎 | 日报分析 / 质量审查 / 战略复核 |
| 量化程度 | 高（平均收益、夏普等） | 中-低（多为定性判断） |
| 置信度基准 | sample_size + 绩效 | source_agent + 多次验证 |
| 更新方式 | UPSERT（覆盖旧数据） | INSERT（追加新数据） |
| 衰减规则 | 90天→degraded/180天→deprecated | 30天→review/60天→自动讨论 |
| 覆盖关系 | 从不被反馈覆盖 | 从不覆盖回测知识 |

---

## 5. 管线集成点

### 5.1 推荐集成位置

```
Step1(墨衡分析完成)   ─→  inline 调用 step1_feedback()
                             ├── 提取 structured_analysis 中的新结论
                             ├── 写入 knowledge_feedback
                             └── 不阻塞管线

Step2(墨萱草稿完成)   ─→  inline 调用 step2_feedback()
                             ├── 提取 morning_draft 中的量化结论
                             ├── 写入 knowledge_feedback
                             └── 不阻塞管线

Step4(墨萱定稿完成)   ─→  inline 调用 step4_feedback()
                             ├── 提取 final_report 中的最终结论
                             ├── 写入 knowledge_feedback
                             └── 不阻塞管线

02:00 每日维护       ─→  batch_maintenance()
                             ├── 扫描 pending 反馈 (source_date < now - 14d)
                             ├── 对比最新回测结果，更新 verified/rejected/partial
                             ├── 清理已废弃的 feedback 条目
                             └── 生成知识更新报告
```

### 5.2 不需要改动的现有步骤

| 步骤 | 原因 |
|:-----|:------|
| **Step0** 玄知采集 | 不产生分析结论 |
| **Step0.5** KnowledgeService 查询 | 查询端不需要改动（新增 feedback 查询是扩展，不是替换） |
| **Step3** 墨衡审查 | 审查只检查质量，不产生新结论 |
| **Step3.5** 玄知复核 | 可选的增强数据源（第二阶段接入） |
| **Step5** 飞书推送 | 不产生新数据 |

### 5.3 集成方式

**方案 A：scheduler_agent.py 内联调用（推荐）**

在 `Step4` 完成后，墨涵的 pipeline scheduler 内联调用 feedback 模块：

```python
# 在 _run_pipeline() 中 Step4 顺利完成后追加
from src.morning_pipeline.knowledge_feedback import FeedbackWriter

feedback = FeedbackWriter()
try:
    feedback.extract_from_step1(analysis_path)
    feedback.extract_from_step2(draft_path)
    feedback.extract_from_step4(final_report_path)
    logger.info("[feedback] 知识反馈写入完成")
except Exception as e:
    logger.warning(f"[feedback] 反馈写入失败（不影响管线）: {e}")
```

**方案 B：独立 pipeline 步骤（解耦更强）**

新增 `step4_5`（反馈步骤），作为可选的后处理步骤。只在 Step4 完成后触发，失败不阻塞：

```
Step4(完成) → Step4_5(反馈写入，可选) → Step5(推送)
```

**选型**：当前推荐方案 A（内联）。理由：
- 不需要新增 spawn 步骤
- 20KB 以下的文本提取+写入，耗时 <1 秒
- 写入失败不阻塞管线，try/except 即可保障

### 5.4 集成到 02:00 每日维护

```
02:00 daily_maintenance 流程中新增:

时间      任务                          说明
02:26    knowledge_feedback.update()   扫描14天前的pending反馈
                                       对比最近7天回测结果
                                       更新 verified/rejected/partial 状态
                                       生成知识更新摘要
```

---

## 6. 实施步骤（分三阶段）

### 第一阶段：基础反馈写入（P1，预计 2-3 小时）

| 序号 | 任务 | 产出 | 前置 |
|:-----|:-----|:------|:------|
| 1a | 新建 `feedback_schema.py` 定义 DDL + 表创建 | `src/morning_pipeline/feedback_schema.py` | — |
| 1b | 实现 `FeedbackWriter` 类的 `extract_from_step1()` | `src/morning_pipeline/knowledge_feedback.py` | 1a |
| 1c | scheduler 内联调用（Step4 后）+ 写入验证 | scheduler_agent.py 追加调用 | 1b |
| 1d | 为现有 knowledge.db 执行升级 DDL | 执行 `CREATE TABLE IF NOT EXISTS` | 1a |

**里程碑 M1**：墨衡分析结论每天自动写入 knowledge_feedback 表。可通过简单 SQL 查询验证。

#### 1a 抽取内容的规则（轻量提取）

```python
def _extract_from_analysis(analysis: dict) -> list[FeedbackCandidate]:
    """从 structured_analysis 提取可回写的结论片段"""
    candidates = []

    # 1. core_logic 中的定量判断
    core = analysis.get("core_logic", "")
    if "概率" in core or "%" in core or "历史" in core:
        # e.g. "修复概率约15%" → 高价值回写
        candidates.append(FeedbackCandidate(
            insight_text=core[:200],
            category="report_observation",
            confidence="medium",  # 有量化支撑
        ))

    # 2. risk_assessment 中的新增风险认知
    risks = analysis.get("risk_assessment", {})
    for i, risk in enumerate(risks.get("primary_risks", [])):
        if len(risk) > 20:  # 有实质内容的才回写
            candidates.append(FeedbackCandidate(
                insight_text=risk[:200],
                category="risk_judgment",
                confidence="low",  # 单次定性判断
            ))

    # 3. sustainability 中的趋势判断
    sust = analysis.get("sustainability", "")
    if "可持续" in sust or "趋势" in sust:
        candidates.append(FeedbackCandidate(
            insight_text=sust[:200],
            category="strategy_evaluation",
            confidence="medium" if "定量" in sust else "low",
        ))

    # 4. operation_framework 中的操作性洞察
    op = analysis.get("operation_framework", {})
    for level in ["aggressive", "balanced", "conservative"]:
        text = op.get(level, "")
        if "止损" in text or "触发" in text:
            candidates.append(FeedbackCandidate(
                insight_text=text[:200],
                category="operation_suggestion",
                confidence="low",
            ))

    return candidates
```

**提取逻辑的简单原则**：
- 只提取有"可证伪性"的结论（含具体条件、概率、阈值）
- 不提取纯观点性描述（"市场情绪偏弱"这种模糊判断）
- 每条结论控制在 200 字以内
- 所有提取都是可选的（没有提取=空列表，不影响管线）

### 第二阶段：多源反馈增强（P2，预计 3-4 小时）

| 序号 | 任务 | 产出 | 前置 |
|:-----|:-----|:------|:------|
| 2a | 实现 `extract_from_step2()` — 从晨报草稿提取 | `knowledge_feedback.py` 扩展 | M1 |
| 2b | 实现 `extract_from_step4()` — 从定稿提取 | `knowledge_feedback.py` 扩展 | M1 |
| 2c | 玄知复核结论接入（`extract_from_strategic()`） | 可选扩展 | 2b |
| 2d | `KnowledgeService.get_recent_feedback()` 查询方法 | `knowledge_service.py` 扩展 | 2b |

**里程碑 M2**：所有日报步骤的结论都能回写，知识库查询端可同时查看回测知识和反馈知识。

### 第三阶段：自动验证循环（P3，预计 3-4 小时）

| 序号 | 任务 | 产出 | 前置 |
|:-----|:-----|:------|:------|
| 3a | 实现 `batch_maintenance()` — 02100 定时验证 | `feedback_maintenance.py` | M2 |
| 3b | 回测结果自动对比：`compare_with_backtest()` | `knowledge_feedback.py` 扩展 | 3a |
| 3c | 生成 `daily_feedback_report.md` | `feedback_maintenance.py` 输出 | 3b |
| 3d | feedback 自动衰减（30天未匹配 → 标记 expired） | `feedback_maintenance.py` 扩展 | 3c |

**里程碑 M3**：反馈知识具备自动验证和衰减能力，系统形成完整的"分析→反馈→验证→沉淀"循环。

### 实施依赖图

```
[1a feedback_schema.py] ← 知识库 DDL 已就绪
        │
        ▼
[1b FeedbackWriter.extract_from_step1()]
        │
        ▼
[1c scheduler_agent.py 内联调用]
        │
        ├──→ [2a extract_from_step2()]
        │        │
        ├──→ [2b extract_from_step4()]
        │        │
        └──→ [2d KnowledgeService feedback 查询]
                 │
                 ▼
            [3a batch_maintenance()]
                 │
                 ▼
            [3b 回测自动对比]
                 │
                 ▼
            [3c+3d 报告 + 衰减]
```

---

## 7. 风险与注意事项

### 7.1 风险矩阵

| 风险 | 等级 | 概率 | 影响 | 缓解 |
|:-----|:-----|:-----|:------|:------|
| 反馈写入污染知识库 | **高** | 10% | 低（独立表） | 独立表隔离，任何错误不影响回测知识 |
| 提取内容质量低（噪声） | 中 | 60% | 低 | 置信度默认 low，需 3+ 次验证才升值 |
| 写入失败阻塞管线 | 中 | 5% | **高** | try/except 保障：任何异常被捕获，写入标记为 SKIPPED |
| 反馈知识膨胀 | 低 | 80% | 低 | 30/60 天自动衰减，表有自动清理机制 |
| 与回测知识冲突、混淆 | 中 | 40% | 中 | 查询层区分处理，回测知识优先级 > 反馈知识 |
| 02:00 验证误判 | 低 | 20% | 低 | verified/rejected 状态可逆，人工可通过 SQL 回滚 |

### 7.2 关键决策记录

| 决策 | 结论 | 理由 |
|:-----|:------|:------|
| 独立表 vs 扩展现有表 | **独立表** | 隔离性、可逆性、扩展性 |
| 内联调用 vs 独立步骤 | **内联调用** | 新增步骤会增加管线复杂度，内联简单可靠 |
| 提取策略 | **只提取可证伪结论** | 模糊判断无验证价值，且会降低信噪比 |
| 置信度默认值 | **low** | 宁保守不夸大，单次分析结论天然置信度低 |
| 验证窗 | **14 天** | 覆盖短期趋势判断验证，不过长也不过短 |
| 回测知识优先级 | **永远 > 反馈知识** | 定量回测结果 > 定性分析判断 |

### 7.3 边界约束

- **不修改** `knowledge_entries` 表中现有数据的置信度体系
- **不修改** `aggregate_knowledge()` 的逻辑（该方法是纯回测数据驱动的）
- **不修改** `KnowledgeService` 的现有查询接口（新增的 feedback 查询是纯扩展）
- **不引入** 新的 Python 依赖（仅使用标准库）

### 7.4 文件清单（实施时新建）

| 文件 | 路径 | 说明 |
|:-----|:------|:------|
| `feedback_schema.py` | `src/morning_pipeline/feedback_schema.py` | DDL 定义 + upgrade 函数 |
| `knowledge_feedback.py` | `src/morning_pipeline/knowledge_feedback.py` | FeedbackWriter 类（~150行核心代码） |
| `feedback_maintenance.py` | `scripts/feedback_maintenance.py` | 02:00 批量维护脚本（第二阶段实现） |
| 本设计文档 | `docs/02_development/knowledge_feedback_loop_design.md` | — |

### 7.5 核心文件预估代码量

| 文件 | 核心行数 | 备注 |
|:-----|:---------|:------|
| `feedback_schema.py` | ~40 行 | DDL + `upgrade_feedback()` 函数 |
| `knowledge_feedback.py` | ~150 行 | `FeedbackWriter` 类，含三个 extract_* 方法 |
| `scheduler_agent.py` 修改 | +~10 行 | 内联调用（try/except 包裹） |
| `feedback_maintenance.py` | ~100 行 | 批量验证 + 报告生成 |
| **总计** | **~300 行** | 轻量级交付 |

---

## 附录 A：查询场景设计

### A.1 日报查询 feedback（供 Step2/Step4 参考）

为 `KnowledgeService` 新增两个方法：

```python
def get_recent_feedback(
    self,
    symbol: str,
    days_back: int = 30,
    min_confidence: str = "low",
) -> list[dict]:
    """获取某标的最新反馈结论（用于报告参考）"""
    # SELECT FROM knowledge_feedback
    # WHERE symbol=? AND source_date >= ?
    # ORDER BY confidence DESC, source_date DESC

def get_feedback_summary(
    self,
    date: Optional[str] = None,
) -> dict:
    """获取反馈知识摘要（用于 02:00 运维报告）"""
    # 统计: 新增/验证/驳回 的数量
```

### A.2 02:00 批量验证伪代码

```python
def batch_validate_feedback(db: KnowledgeDB, days_window: int = 14):
    """扫描 pending 反馈，对比近期回测结果"""

    # 1. 获取所有 pending 反馈 (source_date < 当前时间 - days_window)
    pending = db.query(
        "SELECT * FROM knowledge_feedback "
        "WHERE status='pending' AND source_date <= ?",
        (date_offset(-days_window),)
    )

    # 2. 对每条反馈，查询最近 7 天回测是否有相关结论
    for fb in pending:
        recent_runs = db.query(
            # 查询相同 symbol 的最新回测
        )
        # 3. 判断：是否支持该反馈结论？
        supported = evaluate_support(fb, recent_runs)

        # 4. 更新状态
        if supported:
            db.update("knowledge_feedback", fb.id,
                      status="verified",
                      verified_at=now())
        elif partially_supported:
            db.update("knowledge_feedback", fb.id,
                      status="partial")
        else:
            db.update("knowledge_feedback", fb.id,
                      status="rejected")
```

### A.3 过渡期注意事项

1. **第一阶段（M1）** 实施时，scheduler 的内联调用可以先用一个简单的 `logging.warning` 测试版本验证不阻塞管线
2. `knowledge.db` 升级：先用 `initialize()` 调 `CREATE TABLE IF NOT EXISTS`，后续无需迁移
3. 反馈表初始为空，系统不会自动导入历史日报的分析结论（人工触发可以后续通过 backfill 脚本导入）
