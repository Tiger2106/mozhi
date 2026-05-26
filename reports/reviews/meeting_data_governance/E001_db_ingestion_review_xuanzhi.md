<!--
author: 玄知 🖋️
role: 技术把关审查
review_of: E001_db_schema.md (v1.0) + E001_data_ingestion.md (v1.0)
prior_review_by: 墨萱 🔍 (PASS_WITH_NOTE, 3 B-level issues)
review_date: 2026-05-20 23:15
estimated_time: ~8 min
confidence: 90%
overall: PASS_WITH_NOTE
-->

# E-001 数据库结构方案 + 通用数据录入方案 — 玄知技术把关审查

---

## 一、审查矩阵

| # | 审查维度 | 结论 | 严重等级 |
|:--|:---------|:-----|:---------|
| 1 | 架构合理性（staging_raw + audit_log） | ✅ 设计精良，无过度设计，无显著不足 | — |
| 2 | 迁移影响（3阶段 + 回滚） | ✅ 方案合理，回滚基本充分，需补切换触发器 | B |
| 3 | 录入管道（5步流程） | ✅ 完整，主要瓶颈在 API 限速 | — |
| 4 | 存量兼容与验证策略 | ✅ 合理，分钟聚合路径需补充覆盖 | B |
| 5 | 与墨萱审查一致 | ✅ 大部分一致，1项分歧，1项升级 | — |
| 6 | 最终裁决 | **PASS_WITH_NOTE** 🟡🖋️ | — |

---

## 二、逐项技术审查

### 2.1 架构合理性：staging_raw + audit_log

**评价：✅ 精良，无过度设计**

**确认设计合理性**：
- `staging_raw` 与 `validation_audit_log` 的 N:1 关系设计合理——一次交叉验证（1行 audit_log）可能涉及多个数据源的原始数据（多行 staging_raw）
- `raw_json` 的结构约定（含 `source_url`/`extraction_path`/`retrieved_at`）完美支持 E-001 的"差异可解释即通过"原则，这是常规 audit log 方案不具备的回放能力，但不过度——它是核心功能要求
- `validation_audit_log` 的分钟聚合字段群（`minute_*` + `is_self_consistency`）恰好覆盖了算法 §2.5 的所有需求，**不多不少**
- 索引设计合理：staging_raw 的 5 个单列索引 + 1 个复合索引，audit_log 的 6 个单列索引 + 2 个复合索引——覆盖了全部常见查询模式

**优化建议**（C级）：
- `staging_raw.raw_json` 可能存储大量冗余 API 响应字段（HTTP headers/status code/timing info）。建议在文档中补充 **`raw_json` 裁剪策略**：仅保留 `response_body.data` 核心数据 + 必要元信息（`retrieved_at`/`source_url`），避免无效膨胀

### 2.2 迁移影响：3阶段方案 + 回滚

**评价：✅ 方案合理，回滚基本充分**

**3阶段分工确认**：
- Phase 1：只增不改——DDL 执行有 dry-run，风险最低 ✅
- Phase 2：存量回填——非破坏性操作 ✅
- Phase 3：查询路径切换——fallback 模式设计合理 ✅

**回滚方案评价**：充分
- Phase 1 回滚 = DROP TABLE（DDL 级别的零成本撤销）✅
- Phase 2 回滚 = 回填失败不影响 Parquet 读取 ✅
- Phase 3 回滚 = `MarketDataClient` 切回 Parquet-only 模式 ✅

**B-02 补充（同意墨萱，补充一个关键细节）**：

Phase 3 的 fallback 模式定义了优先级 `stock_daily → Parquet → API`，但**缺少切换触发条件**——什么条件下能从 "Parquet 优先" 切换到 "stock_daily 优先"？

建议补充 **`switch_condition` 指标**：
- 必达条件：全部 P0 标的回填完成，且回填 validation_report 中 REPORT 率 < 1%
- 建议条件：3 个交易日的并行验证期（stock_daily 写 + Parquet 读），期间 stock_daily 与 Parquet 的总量级差异在 1% 以内

### 2.3 录入管道：5步流程

**评价：✅ 完整，工程实现难度中等**

**工程实现评估**：
- **核心逻辑翻译**：单位归一化 + 交叉验证 + 仲裁 → ~2-3 人天（语义在 E-001 算法文档中已精确定义）
- **配置系统**：YAML 数据源/单位/字段映射配置 → ~1 人天
- **集成对接**：MarketDataClient 封装 + 多源并行获取 → ~1 人天

**主要瓶颈**：

| 瓶颈 | 等级 | 分析 |
|:-----|:-----|:-----|
| **API 限速** | 🔴 高 | 每只股票每天 7 metrics × 3 源 = 21 次调用。批量 10 只股票 × 730 天（3 年历史）≈ 15.3 万次。以 0.5s 间隔算约 21 小时。回填 P0 标的（601857+000001）约 2 小时，可接受；全量 A50 回填需考虑并行策略。 |
| **单位自动推断** | 🟡 中 | 录入方案假设"所有主流源返回元"，但港股/ETF/期货可能有 edge case。建议在 Phase 1 的测试中覆盖至少一种非 A 股场景。 |
| **分钟聚合回填** | 🟡 中 | 分钟数据量级大（~240 条/天/标的），但仅需 1 年历史 × 少量 P0 标的，时间增量可控。 |

**发现的问题**：录入方案 §1.2 中 `batch_size: int = 10` 命名不清晰——是每批处理 10 天还是每批并发 10 个请求？建议改为 `batch_days` 或 `concurrent_symbols`，并在文档中说明此参数对 API 限速的影响。

### 2.4 存量兼容与验证策略

**评价：✅ 合理，需补分钟聚合覆盖**

- **回填优先级合理**：P0（主标的+基准）→ P1 → P2
- **新股票 vs 存量路径设计清晰**：新股票全量拉取 → stock_daily；存量 Parquet 锚定 + 增量验证

**B-03 确认（同意墨萱）**：存量回填全部 `enable_minute=False` 导致分钟聚合路径零覆盖——这是真实的 gap。建议在 P0 标的中明确指定哪只启用：**601857（主标的）启用 1 年分钟聚合**，000001（指数）分钟聚合意义较小，可跳过。

**Parquet 双轨一致性**：迁移方案提到"对比 Parquet 与 stock_daily 的差异"但没有定义**差异容忍度**。如果 stock_daily 与 Parquet 在 0.3% 阈值内一致，属于正常浮动；但如果出现系统性偏差（如 stock_daily 的 volume 始终比 Parquet 大 0.1%），应当记录偏差方向，便于溯源。

---

## 三、与墨萱审查的一致性分析

| 问题 | 墨萱意见 | 玄知意见 | 结论 |
|:-----|:---------|:---------|:-----|
| **B-01** unit字段DDL-算法不一致 | DDL保留，算法Phase1填充 | ✅ 同意。成本极低，早做早对 | 一致 |
| **B-02** 迁移原子性+回滚 | 补充验证期+切换撤销流程 | ✅ 同意。补充了 switch_condition 指标 | 一致，有补充 |
| **B-03** 分钟聚合零覆盖 | P0标的1年启用分钟聚合 | ✅ 同意。明确指定 601857 启用 | 一致，有补充 |
| **C-01** 自洽性约束文档化 | 文档化 + default=independent | ✅ 同意。补充：`is_self_consistency=1` 的审计行不应作为独立仲裁依据 | 一致，有补充 |
| **C-02** 独立审计数据库 | 架构决策，建议分离 | ⚡ **分歧**：过早分离增加连接管理复杂度，建议先在 trade_engine.db 运行，3个月后评估膨胀数据再做决策 | 有分歧 |
| **C-03** 幂等性/TTL | 建议（C级） | 📊 **升级至 B-04**：每日滚动更新中 audit_log 无幂等保护将导致线性膨胀，一年后可达数十万行 | 升级 |
| **C-04** Priority排序稳定性 | 建议 | ✅ 同意，但时序不重要 | 一致 |
| **C-05** VALIDATION_INPUT 类定义 | 建议 | ✅ 同意，可复用 IngestionInput | 一致 |

### 3.1 分歧说明：C-02（独立审计数据库）

墨萱建议将 `validation_audit_log` + `staging_raw` 移入独立 `audit.db`。

**玄知意见**：倾向于**先在原地解决膨胀问题，3个月后再评估分离必要性**。

理由：
1. **连接复杂度**：当前每个 pipeline 运行需要打开 trade_engine.db + knowledge.db 两个连接。再加 audit.db = 三个连接，对 SQLite 这种单写多读的场景增加死锁风险
2. **查询便利性**：`stock_daily.latest_audit_id` 到 `validation_audit_log.id` 的 FK 如果跨数据库，无法使用 SQLite 外键约束
3. **膨胀可控**：通过 B-04（TTL 清理 + 去重窗口）可以将膨胀控制在线性增长而非指数增长

建议：**Phase 1 留在 trade_engine.db，Phase 3 切换后评估膨胀数据，再决策**。

### 3.2 升级说明：C-03 → B-04（幂等性/TTL）

这是**必然触发**的问题，不是"可能"的问题：

- 每日定时批量录入是标准流程
- 每只股票每天产生 ~7 行 audit_log（volume/amount/open/high/low/close/pct_chg）
- 100 只标的 × 250 个交易日 = 17.5 万行/年
- 重复运行或重试会加倍

如果没有幂等保护或清理策略，1-2 年后的 audit_log 表将成为一种**数据噪声**——历史的审计记录不如最近 90 天的有价值。

---

## 四、最终裁决

### PASS_WITH_NOTE 🟡🖋️

**总体评价**：墨衡的方案设计质量优秀，staging_raw + audit_log 的职责分离设计、stock_daily 作为验证后权威数据的引入、Parquet 缓存层的保留策略，体现了务实的渐进式改造思路。

### 修正后的必修问题（4项）

| 编号 | 等级 | 问题 | 建议 | 责任人 |
|:-----|:------|:-----|:-----|:-------|
| **B-01** | 高 | `validation_audit_log` 的 `source_a/b/c_unit` 字段 DDL 有但算法不写 | 统一决策：DDL 保留 + Phase 1 填充（成本极低） | 墨衡 |
| **B-02** | 高 | Phase 2/3 迁移缺少原子性保障和切换触发器 | 补充验证期 + `switch_condition` 指标（REPORT率 < 1%） | 墨衡 |
| **B-03** | 高 | 分钟聚合验证路径在存量回填中完全未覆盖 | P0 标的（601857）至少 1 年历史启用 `enable_minute=True` | 墨衡 |
| **B-04** | **高（新增）** | `validation_audit_log` 无幂等保护，每日滚动写入导致线性膨胀 | 增加去重窗口（如同 symbol+date+metric+verdict 仅保留最新条）或 TTL 清理策略（保留 90 天） | 墨衡 |

### 建议优化（4项）

| 编号 | 建议 | 责任方 |
|:-----|:------|:-------|
| C-01 | 自洽性验证审计标记约束文档化，`is_self_consistency=1` 不用于独立仲裁 | 墨衡 |
| C-02 | 审计数据库分离决策推迟至 Phase 3 后评估 | 墨涵（架构） |
| C-03 | `raw_json` 裁剪策略文档化（仅保留核心响应数据） | 墨衡 |
| C-04 | 数据源注册表补充同 priority 的次级排序规则（quality_rating 降序） | 墨衡 |

---

*审查完毕。玄知 🖋️*
