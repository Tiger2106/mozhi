# E-001 数据库结构方案 + 通用数据录入方案 — 审查报告

| 项目 | 内容 |
|:-----|:-----|
| **审查人** | 墨萱 🔍 |
| **审查对象** | `E001_db_schema.md` (v1.0) + `E001_data_ingestion.md` (v1.0) |
| **审查日期** | 2026-05-20 23:10 |
| **审查耗时** | ~20 min |
| **置信度** | 95% |
| **总体结论** | **PASS_WITH_NOTE** — 方案设计质量高，但存在 3 个必修问题（B级）和 5 个建议（C级）|

---

## 一、审查矩阵总表

| # | 审查维度 | 结论 | 严重等级 |
|:--|:---------|:-----|:---------|
| 1.1 | 表结构完整性 — staging_raw | ✅ 覆盖 | — |
| 1.2 | 表结构完整性 — validation_audit_log | ✅ 覆盖 | — |
| 2.1 | 审计日志字段 — source_name | ✅ 完备 | — |
| 2.2 | 审计日志字段 — source_unit | ⚠️ P2 延期标记，但 DDL 中已包含 | B |
| 2.3 | 审计日志字段 — minute_data_source | ✅ 完备（含 is_self_consistency 标记） | — |
| 3.1 | 与现有系统兼容 — 新增字段 | ✅ 只增不删 + Parquet 不变 | — |
| 3.2 | 与现有系统兼容 — 双轨期迁移 | ⚠️ 缺乏存量数据迁移的原子性保障 | B |
| 4.1 | 可测试性 — DDL | ✅ 可直接用于测试用例 | — |
| 4.2 | 可测试性 — 映射表/配置 | ⚠️ 数据源注册表缺少 Priority 排序稳定性说明 | C |
| 5.1 | 录入管道完整性 | ✅ 5步流程完整 | — |
| 5.2 | 录入管道完整性 — 分钟聚合回填 | ❌ 分钟数据回填路径未定义 | B |
| 6.1 | 风险 — 幂等冲突 | ⚠️ audit_log 与 staging_raw 不做幂等，重复执行会膨胀 | C |
| 6.2 | 风险 — 数据库选择 | ⚠️ trade_engine.db 的 staging_raw 可能随 REPORT 增多而膨胀 | C |
| 6.3 | 风险 — 分钟聚合自洽性 | ❌ 自洽性验证的可靠性未被充分论证 | B |

---

## 二、详细审查意见

### 2.1 ✅ 表结构完整性 — 通过

**staging_raw** 表字段覆盖全部需求：
- 覆盖 E-001 §2.7 中 `apply_validation_result` 的写入策略：`verdict`、`diff_ab/ac/bc`、`diff_reason` 字段完备
- `raw_json` 字段结构约定清晰（`source_url`, `request_params`, `response_body`, `extracted_value`, `extraction_path`, `retrieved_at`）→ 支持"差异可解释即通过"的溯源需求
- `source_name`、`source_type`、`api_priority` 三字段组合可唯一标识数据来源链路
- 索引设计合理（5个单列索引 + 1个复合索引）

**validation_audit_log** 表字段覆盖全部需求：
- 严格对齐 E-001 §2.6 `_build_audit_entry()` 的输出结构
- P0 字段（trade_date, symbol, metric_name, source_a/b/c, diff_*）完备
- `minute_data_source` + `minute_aggregated` + `minute_detail_json` + `is_self_consistency` 覆盖分钟聚合审计需求
- 6个单列索引 + 2个复合索引，查询模式覆盖充分

**stock_daily** 建议新增表：
- `validation_status` + `validation_note` + `primary_source` + `all_sources_json` 字段设计合理
- `UNIQUE(trade_date, symbol)` 约束保证幂等

### 2.2 ⚠️ 审计日志 UNIT 字段 — P2 延期问题（B级）

**问题**：E-001 算法文档 §2.6 中，`_build_audit_entry()` 源码中将 `source_a_unit`、`source_b_unit`、`source_c_unit` 标记为 "P2 字段（本版本可延后）"，注释掉了。但数据入库方案的 `validation_audit_log` DDL 中却**已经包含了** `source_a_unit`、`source_b_unit`、`source_c_unit` 字段。

**矛盾分析**：
- 如果 DDL 有字段，算法却未写值 → 该字段永远是 NULL，造成数据空洞
- 如果要修复算法填充这些字段 → 需要确认这是否超出了 Phase 1 范围

**建议**：
1. 统一决策：要么 DDL 移除这三个字段（Phase 2 再加），要么算法 Phase 1 就填充它们
2. 我的倾向：**DDL 保留，算法填充**——既然都建了列，P0 中填充单位信息成本极低（SourceValue 本来就有 unit 属性）

### 2.3 ⚠️ 存量数据迁移缺乏原子性保障（B级）

**问题**：Phase 2 "存量数据回填"提到对比 Parquet 与 stock_daily 的差异，但未定义：
1. **一致性校验失败后的回滚策略**：如果回填中途发现 stock_daily 中的数据与 Parquet 有系统性偏差（如回填算法有 bug），如何保证已经写入的数据可回滚？
2. **切换时机**：Phase 3 说 "MarketDataClient 增加 fallback 模式"，但没有定义切换的触发条件——什么时候从"parquet 优先"切换到"stock_daily 优先"？

**建议**：
- Phase 2 新增一个 `backfill_validation_report` SQLite 表或 JSON 文件，记录每次回填的校验摘要
- Phase 3 切换前设置一个**验证期**（如 3 个交易日），期间 stock_daily 与 Parquet 并行写入但后者仍为读取源，确认无误后手动切换
- 补充"切换撤销"流程：发现 stock_daily 异常时，`MarketDataClient.get_daily()` 可切回 Parquet-only 模式

### 2.4 ⚠️ 分钟数据回填路径未定义（B级）

**问题**：录入方案中有 `enable_minute` 参数，且算法 §2.5 中定义了分钟聚合逻辑。但存量数据回填（§6.3）的优先级表中，**全部标记了 `enable_minute=False`**。

这意味着：
1. 存量回填步骤**永远不会走**分钟聚合验证路径
2. 后续日更新中，分钟聚合验证的路径**仅在双源不一致时才触发**
3. 分钟聚合的代码和数据流**处于未被测试验证的状态**

**建议**：
- 在存量回填 P0 标的中，至少对**历史最近 1 年**的数据启用 `enable_minute=True`，让分钟路径经过一次完整测试
- 或者新增一个**分钟聚合验证专用测试用例**（P0）覆盖 Step 4

### 2.5 ⚠️ 自洽性验证的可靠性论证不足（B级）

**问题**：算法 §2.5 中明确提到 "⚠️ 重要：若分钟数据来自某验证源自身，这本质是自洽性检查而非独立仲裁"。但录入方案的 DDL 中虽然设计了 `is_self_consistency` 字段，却未在**使用方法**上给出约束。

自洽性验证的风险场景：
- 源 A 的分钟数据 → 聚合成日线 → 与源 A 的日线数据比对 → 一致（自洽）
- 但**这不能证明数据本身的正确性**——因为源 A 的分钟和日线可能共享同一个后端数据管道，bug 被掩盖

**建议**：
- 在文档中明确注明：**分钟聚合仅在其原始数据来自独立第三方源时具有独立仲裁效力**
- 自洽性检查（同源分钟 vs 日线）审计日志中必须标记 `is_self_consistency=1`，最终裁决只能降级为 REPORT 或保留原来的 PASS_WITH_NOTE
- 配置项 `minute_data_source_strategy` 建议默认值改为 `'independent'`，仅当独立分钟内源不可用时才退化为 `'highest_quality'`

### 2.6 ℹ️ 风险提示 — 幂等性与数据膨胀（C级）

**问题**：录入方案 §7.2 中：
- `validation_audit_log` 不做幂等去重 → 重复运行 `run_ingestion()` 会持续追加审计记录
- `staging_raw` 不做幂等去重 → REPORT 记录会持续累积

在以下场景中可能产生显著膨胀：
1. 定时批量维护（每日运行）中，同一 symbol+date+metric+verdict 组合每天产生一条冗余记录
2. 回填验证过程中可能多次回放

**建议**：
- 为 `validation_audit_log` 增加一个可选的去重窗口（如同一 symbol+trade_date+metric_name+verdict 组合，一天内仅保留最新一条）
- 为 `staging_raw` 增加 TTL 清理策略（如保留最近 90 天的 REPORT 记录，更早的归档或压缩）
- 或在 `run_ingestion()` 中增加幂等模式参数 `deduplicate=True/False`

### 2.7 ℹ️ 风险提示 — 数据库膨胀（C级）

**问题**：`staging_raw` 存放在 `trade_engine.db` 中。`trade_engine.db` 是交易引擎的核心数据库，包含 `transactions`, `positions`, `fund_flow` 等表。

随着每天的数据录入：
- 正常 PASS 的股票每天产生 ~7 行 audit log（volume, amount, open, high, low, close, pct_chg）
- 如果有 REPORT 记录，额外产生对应行数的 staging_raw 记录
- 长期运行下 trade_engine.db 可能膨胀到影响交易引擎查询性能

**建议**：
- 考虑将 `validation_audit_log` 和 `staging_raw` 放在**独立的审计数据库**（如 `audit.db`）中，与交易引擎职责分离
- 或者至少在文档中注明膨胀预估和清理策略

### 2.8 ℹ️ 建议 — 数据源注册表 Priority 排序（C级）

**问题**：录入方案 §2.4 中 `get_sources_for_symbol()` 实现为 `sorted(self._sources.values(), key=lambda s: s.priority)`。但如果多个源具有相同 priority 值（如两个源都是 priority=2），排序行为不可预期。

**建议**：
- 增加次级排序规则：同 priority 时按 `quality_rating` 排序（A > B > C > D），再按 `weight` 降序
- 或在 YAML 配置中增加显式的 `fallback_order` 字段

---

## 三、E-001 算法需求覆盖度检查

以下逐项检查两份方案文档对 E-001 算法定稿的覆盖程度：

| E-001 § | 需求 | db_schema | data_ingestion | 覆盖 |
|:--------|:-----|:----------|:---------------|:-----|
| §1.2 | SourceValue 数据结构 | — | §1.2 类定义 | ✅ |
| §1.2 | ValidationInput 数据结构 | — | — | ❌（仅间接通过管道参数覆盖） |
| §1.2 | ValidationResult 数据结构 | — | §5.3 验证逻辑使用 | ✅ |
| §2.1 | Step 0 身份归一化 | — | §1.1 Step 0 + §5.1 | ✅ |
| §2.1 | Step 1 单位归一化检查 | — | §1.1 Step 2 + §3.x | ✅ |
| §2.1 | Step 2 两源比对 (0.3%) | — | §1.1 Step 3 + §5.2 | ✅ |
| §2.4 | Step 3 第三源仲裁 | — | §1.1 Step 3 | ✅ |
| §2.5 | Step 4 分钟聚合验证 | §3.2 minute_* 字段 | §1.1 Step 3 提及 | ✅ |
| §2.6 | Step 5 审计日志 | §3 DDL | §1.1 Step 5 | ✅ |
| §2.7 | Step 6 违规不阻断 | §2.3 writting logic | §5.3 | ✅ |
| §4 | 测试要点 → 验收红线 | — | §9 测试策略 | ✅ |
| §5 | 边界情况汇总 | — | §7 错误处理 + §9 边界测试 | ✅ |

E-001 §1.2 中 `ValidationInput` 数据结构在录入方案中没有直接的类定义，但通过 `IngestionInput` 和 `_process_date` 方法的参数间接传递了相同信息。不影响功能实现，可接受。

---

## 四、必修问题汇总（3项）

| 编号 | 优先级 | 问题 | 责任人 | 建议修正 |
|:-----|:-------|:-----|:-------|:---------|
| B-01 | **高** | validation_audit_log 的 source_a/b/c_unit 字段 DDL 有但算法不写 | 墨衡 | 统一决策——要么 DDL 移除，要么 Phase 1 填充 |
| B-02 | **高** | Phase 2/3 迁移缺乏原子性和回滚保障 | 墨衡 | 补充验证期和切换撤销流程 |
| B-03 | **高** | 分钟聚合验证路径在存量回填中完全未覆盖 | 墨衡 | 对 P0 标的至少 1 年历史启用分钟聚合 |

## 五、建议优化汇总（5项）

| 编号 | 建议 | 责任方 |
|:-----|:-----|:-------|
| C-01 | 自洽性验证审计标记的约束规则文档化，默认分钟源策略改为 independent | 墨衡 |
| C-02 | 考虑 audit_log + staging_raw 放入独立审计数据库 | 墨涵（架构决策）|
| C-03 | 增加幂等性配置选项（deduplicate 参数）或 TTL 清理策略 | 墨衡 |
| C-04 | 数据源注册表增加同 priority 时的次级排序规则 | 墨衡 |
| C-05 | 补充 VALIDATION_INPUT 类定义（可选复用 IngestionInput） | 墨衡 |

---

## 六、红线对照（供墨涵汇总使用）

| 验收红线 | 审查结论 |
|:---------|:---------|
| E.02-001 两源 ≤ 0.3% → 写入主表 | ✅ 方案完整覆盖 |
| E.02-002 两源 > 0.3% 无仲裁 → staging_raw | ✅ 方案完整覆盖 |
| E.02-003 两源 > 0.3% 有枚举理由 → PASS_WITH_NOTE | ✅ 方案完整覆盖 |
| E.01-001 单位异常（手 vs 股）→ UNIT_ERROR | ✅ 方案完整覆盖 |
| E.03-001 源不可用 → 不阻塞 | ✅ 方案完整覆盖 |
| E.04-001 每次验证生成审计记录 | ✅ 方案完整覆盖 |

---

## 七、审查结论

**PASS_WITH_NOTE** 🟡🔍

总体评价：
- **结构设计质量高**：DDL 设计严谨，字段覆盖全面，索引设计体现了对查询模式的理解
- **录入管道完整性好**：5步流程无遗漏，从输入到入库的端到端链路清晰
- **注释和文档质量高**：字段用途、枚举值说明、配置结构都有详细文档

需要墨衡修正的 3 个 B 级问题：
1. unit 字段的 DDL-算法不一致
2. 迁移原子性保障缺失
3. 分钟聚合路径零覆盖

5 个 C 级建议可根据时间安排选择性采纳。

---

*审查完毕。墨萱 🔍*
