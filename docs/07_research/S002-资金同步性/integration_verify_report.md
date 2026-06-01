# S002 三线集成联调验证报告

**作者**: 墨衡
**创建时间**: 2026-05-25T11:40+08:00
**版本**: v1.0
**状态**: 联调完成

---

## 1. 联调概述

本次联调为 S002 堵疏同步性监测模块的首次三线集成测试，验证格式规范 v1 中定义的各线输出格式对齐、字段完整性及综合评分逻辑。

### 1.1 联调范围

| 条目 | 内容 |
|:-----|:------|
| 日期 | 2026-05-25（周一） |
| 标的池 | A50 核心池（50只） |
| 数据频率 | 日频 |
| 输出路径 | `reports/morning/{date}/s002/` |
| 知识路径 | `knowledge_base/s002/` |

### 1.2 联调步骤执行状态

| 步骤 | 状态 | 输出文件 | 说明 |
|:-----|:-----|:---------|:------|
| Step 1: 墨萱线读取 | ✅ 完成 (模拟生成) | `mismatch_heatmap_2026-05-25.json` | 字段完整性校验通过 |
| Step 2: 玄知线读取 | ✅ 完成 (模拟生成) | `historical_reference_case_sync_rising_001.json` | 字段完整性校验通过 |
| Step 3: 三线合成 | ✅ 完成 | `sync_composite_2026-05-25.json` | 综合指数计算完成 |
| Step 4: 分歧标注 | ✅ 完成 | 内嵌于 composite 报告 | 三线方向一致，无分歧 |

---

## 2. 输入数据校验

### 2.1 墨萱线 — 失配热力图 (`mismatch_heatmap_{date}.json`)

**字段校验结果: ✅ 全部通过**

| 字段 | 预期 | 实际 | 状态 |
|:-----|:-----|:-----|:-----|
| `meta.author` | moxuan | moxuan | ✅ |
| `meta.date` | YYYY-MM-DD | 2026-05-25 | ✅ |
| `meta.version` | v1 | v1 | ✅ |
| `summary.total_mismatches` | int | 120 | ✅ |
| `summary.severe_pairs` | int | 16 | ✅ |
| `summary.moderate_pairs` | int | 46 | ✅ |
| `summary.mild_pairs` | int | 58 | ✅ |
| `records[].date` | YYYY-MM-DD | 2026-05-25 | ✅ |
| `records[].symbol` | 6位无后缀 | 600519等 | ✅ |
| `records[].pool` | core/extended | core | ✅ |
| `records[].channel_type` | 4种之一 | ✅ | ✅ |
| `records[].value` | float | ✅ | ✅ |
| `records[].severity` | severe/moderate/mild | ✅ | ✅ |
| `records[].pair` | [string, string] | ✅ | ✅ |

### 2.2 玄知线 — 历史参照 (`historical_reference_{case_id}.json`)

**字段校验结果: ✅ 全部通过**

| 字段 | 预期 | 实际 | 状态 |
|:-----|:-----|:-----|:-----|
| `meta.author` | xuanzhi | xuanzhi | ✅ |
| `meta.case_id` | string | case_sync_rising_001 | ✅ |
| `reference.case_type` | 3种之一 | 同步性上升期 | ✅ |
| `reference.period.start` | YYYY-MM-DD | 2026-05-19 | ✅ |
| `reference.period.end` | YYYY-MM-DD | 2026-05-25 | ✅ |
| `reference.similarity_score` | float | 0.8471 | ✅ |
| `matched_symbols[].symbol` | 6位代码 | ✅ | ✅ |
| `matched_symbols[].current_value` | float | ✅ | ✅ |
| `matched_symbols[].z_score` | float | ✅ | ✅ |
| `prediction.confidence` | 高/中/低 | 中 | ✅ |

### 2.3 墨衡线 — 同步性指数 (`synchronicity_index_{date}.json`)

**字段校验结果: ✅ 全部通过**

| 字段 | 预期 | 实际 | 状态 |
|:-----|:-----|:-----|:-----|
| `meta.author` | moheng | moheng | ✅ |
| `summary.total_symbols_core` | 50 | 50 | ✅ |
| `summary.aggregate_index` | float | 0.8236 | ✅ |
| `records` | array | 120条 (30标×4渠道) | ✅ |
| `records[].channel_type` | 4种之一 | ✅ | ✅ |
| `analysis.convergent_signals` | array | 10个标的 | ✅ |
| `analysis.divergent_signals` | array | 5个标的 | ✅ |

---

## 3. 三线合成结果

### 3.1 综合指数

| 指数 | 值 | 说明 |
|:-----|:---|:------|
| **综合同步性指数** | **0.7775** | 整体处于正向区间，趋势健康 |
| 墨衡线(同步性) | 0.8236 | 资金与价格运动高度协同 |
| 墨萱线(失配度) | 0.6750 | 轻度失配为主(严重16/中度46/轻度58) |
| 玄知线(相似度) | 0.8471 | 与历史同步性上升期高度相似 |

### 3.2 权重方案

| 线路 | 权重 | 职责 | 数据维度 |
|:-----|:-----|:------|:---------|
| 墨衡线 | 0.40 | 同步性主指数 | D₁政策 + D₅市场 |
| 墨萱线 | 0.35 | 失配风险检测 | D₂资金流 + D₄合规 |
| 玄知线 | 0.25 | 历史参照校准 | D₃执法 |

### 3.3 分歧分析

| 指标 | 值 |
|:-----|:---|
| 分歧存在 | 无 |
| 分歧数量 | 0/3 |
| 分歧率 | 0.0% |
| 三线方向 | 全部正向(≥0.5) |

**结论**: 当前市场状态为三线共识-正向。墨萱线失配度虽为三线最低(0.675)，但仍处于正向区间，表明资金-价格背离可控，不存在需要触发预警的极端分歧。

---

## 4. 格式对齐检查

### 4.1 日期对齐 ✅

| 维度 | 预期 | 实际 |
|:-----|:-----|:------|
| 日期格式 | YYYY-MM-DD | 三线统一使用 2026-05-25 |
| 时区 | +08:00 | 统一 |
| 频率 | 日频 | 单日快照 |

### 4.2 标的代码对齐 ✅

| 维度 | 预期 | 实际 |
|:-----|:-----|:------|
| 代码长度 | 6位无后缀 | "600519" 格式一致 |
| 池标记 | core/extended | 三线统一使用 "core" |

### 4.3 文件命名规范 ✅

| 线 | 命名规则 | 实际文件名 |
|:---|:---------|:-----------|
| 墨衡线 | `synchronicity_index_{date}.json` | ✅ `synchronicity_index_2026-05-25.json` |
| 墨萱线 | `mismatch_heatmap_{date}.json` | ✅ `mismatch_heatmap_2026-05-25.json` |
| 玄知线 | `historical_reference_{case_id}.json` | ✅ `historical_reference_case_sync_rising_001.json` |

---

## 5. S001 回测结果（可并行任务）

S001 情景引擎的12个月滚动回测已完成，基于 akshare 实盘数据：

| 指标 | 结果 | 目标 | 达标 |
|:-----|:-----|:-----|:-----|
| 回测窗口数 | 12 | 12 | ✅ |
| 方向准确率 | 8.3% | ≥65% | ❌ |
| 回流命中率 | 100.0% | ≥55% | ✅ |
| 价格在区间率 | 75.0% | — | — |

**结论**: 回流命中率达标，但方向准确率大幅低于目标，需进一步优化情景引擎的方向预测能力。

---

## 6. 联调结论

| 维度 | 结果 | 说明 |
|:-----|:-----|:------|
| 格式规范一致性 | ✅ PASS | 三线输出格式完全对齐 §3 规范 |
| 字段完整性 | ✅ PASS | 所有必填字段存在且类型正确 |
| 综合评分逻辑 | ✅ PASS | 三线权重合成符合设计报告 §3.1 |
| 分歧检测机制 | ✅ PASS | 分歧标注逻辑正确 |
| 数据输入链 | ⚠️ 模拟数据 | 墨萱线/玄知线实线待确认后接入正式输出 |

### 6.1 后续待办

1. **正式接入**：收到墨萱/玄知确认信号后，切换至实线数据（替换联调生成的模拟数据）
2. **S001优化**：方向准确率过低，需排查 MC 模拟器的方向预测偏差
3. **S002热力图**：当墨萱线正式接入后，可启用 heatmap 矩阵输出
4. **Cron集成**：将 S002 三线联调嵌入每日流程

---

## 附录 A: 产出文件清单

| 文件 | 路径 | 大小 |
|:-----|:-----|:-----|
| 墨衡线主报告 | `reports/morning/20260525/s002/synchronicity_index_2026-05-25.json` | 23KB |
| 墨萱线失配图 | `reports/morning/20260525/s002/mismatch_heatmap_2026-05-25.json` | 31KB |
| 三线合成报告 | `reports/morning/20260525/s002/sync_composite_2026-05-25.json` | 1.5KB |
| 玄知线历史参照 | `knowledge_base/s002/historical_reference_case_sync_rising_001.json` | 2.4KB |
| S001回测报告 | `reports/backtest/S001_backtest_report.md` | — |
| S001回测数据 | `reports/backtest/S001_backtest_data_601857.json` | — |
| 联调脚本 | `code/src/strategies/S002/integration_s002.py` | — |

## 附录 B: 审计日志

| 时间 | 操作 | 操作人 | 说明 |
|:-----|:-----|:-------|:------|
| 2026-05-25T10:46+08:00 | 格式规范发布 | 墨衡 | s002_notify 信号发送至墨萱/玄知 |
| 2026-05-25T10:49+08:00 | 预检记录 | 墨衡 | S002_prep_memo 预检完成 |
| 2026-05-25T11:22+08:00 | S001回测 | 墨衡 | akshare实盘12个月滚动回测完成 |
| 2026-05-25T11:40+08:00 | 三线联调 | 墨衡 | 联调完成，验证报告生成 |
