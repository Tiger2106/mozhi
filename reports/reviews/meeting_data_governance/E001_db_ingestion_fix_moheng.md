<!--
author: 墨衡 🖋️
task: E-001 实施文档修正（4项B级问题）
based_on: 墨萱审查 + 玄知审查
Fix record for: E001_db_schema.md (v1.1), E001_data_ingestion.md (v1.1)
created_time: 2026-05-20T23:18+08:00
-->

# E-001 实施文档修正记录

> **总体结论**：4项B级问题全部修正，0项未完成。写入验证：✅ 全部通过。

---

## B-01：unit字段 DDL-算法不一致

**决策**：DDL 保留 + Phase 1 填充核心字段 unit，其余标记 P2。

### 修正内容

#### E001_db_schema.md — §三.3.2 DDL 注释更新

source_a_unit / source_b_unit / source_c_unit 三字段在 DDL 中保持定义（已为 NULLABLE），补充 P2 策略注释：

```
source_a_unit       TEXT,               -- 源 A 原始单位
                                       -- P2 策略：volume/amount 的 unit 在 Phase 1 填充
                                       -- 其余字段（open/high/low/close/pct_chg）的 unit 标记为 P2
                                       -- 理由：volume/amount 有手↔股风险，必须记录；价格单位各源一致无需单元转换
source_b_unit       TEXT,               -- 源 B 原始单位（P2 策略同上）
source_c_unit       TEXT,               -- 源 C 原始单位（P2 策略同上，可选）
```

#### E001_data_ingestion.md — §七.7.2 `_log_audit()` 代码注释

```python
# 注意：source_a_unit / source_b_unit / source_c_unit
#   volume/amount 的 unit 在 Phase 1 填充（防止 手↔股 单位混淆）
#   open/high/low/close/pct_chg 的 unit 标记为 P2（各源单位一致，无需单元转换记录）
```

**修正逻辑**：
- DDL 保留字段（删除成本 > 保留成本）：DDL 已定义且为 NULLABLE，移除需要修改历史 SQL 迁移文件
- Phase 1 仅填充 volume/amount 的 unit：这两个字段在 A 股中日线级别存在手↔股的常见单位混淆风险（~100x 量级差异），必须记录原始单位用于追溯
- 价格类字段（open/high/low/close/pct_chg）的 unit 所有主流源均返回元/股，无单位混淆风险，标记为 P2

---

## B-02：迁移原子性 + 切换触发器

**决策**：补充切换触发条件（REPORT率<1% + 3日并行验证期）+ 完整回滚方案。

### 修正内容

#### E001_db_schema.md — §六.6.3 Phase 3 扩写（3个子节）

**§6.3.1 切换触发条件**：

| 条件 | 指标 | 说明 |
|:-----|:-----|:-----|
| **必达条件** | 全部 P0 标的回填完成 | 601857、000001、600519 全部走完 E-001 全流程回填 |
| **必达条件** | REPORT 率 < 1% | 回填报告显示 P0 标的的 REPORT 率低于 1%（验证通过率 > 99%） |
| **建议条件** | 3 日并行验证期 | stock_daily 持续写入 + Parquet 持续读取，期间两个系统日线数据的总量级差异 < 1% |

> 切换决策人：墨涵（技术负责人）手动确认切换指令。禁止自动切换。

**§6.3.2 切换操作步骤**：
- [D0] 切换前检查（3 项确认）
- [D0] 执行切换（query_mode 从 'parquet' 改为 'authoritative'）
- [D0+1 ~ D0+3] 观察期（监控失败率/延迟）

**§6.3.3 回滚步骤**：
- 回滚触发条件（失败率 > 5% / 系统性错误 / 性能退化）
- 回滚操作（切回 parquet 模式 + 日志记录）
- 回滚后处理（数据保留不动，每日录入继续写入，修复后重新走切换条件）

**修正逻辑**：
- 原方案仅定义了"回滚 = 切回 Parquet-only"，但缺乏触发条件、操作步骤、和回滚后处理
- 新的 6.3.1-6.3.3 提供了完整的"条件→操作→回滚"三段式流程
- 禁止自动切换 + 手动确认 = 防止无意识的生产事故

---

## B-03：分钟聚合路径零覆盖

**决策**：P0/P1 三只标的启用最近 1 年的分钟聚合验证。

### 修正内容

#### E001_data_ingestion.md — §六.6.3 回填优先级表 + 回填策略

**优先级表更新**：P0（601857、000001）和 P1（600519）的说明字段标注 "**分钟聚合启用**：最近 1 年"

**回填策略新增**：
```text
- P0 标的（601857、000001）调用 `run_ingestion(symbol, enable_minute=True)` 对最近 1 年数据启用分钟聚合验证
- P1 标的（600519）调用 `run_ingestion(symbol, enable_minute=True)` 对最近 1 年数据启用分钟聚合验证
- 分钟聚合仅用于验证锚定（AGGREGATION_ANCHOR），不替代日线数据获取
- P2 标的暂不启用分钟聚合
- 分钟聚合验证结果独立记录在 minute_validation_summary 字段中
```

**修正逻辑**：
- 原方案全部 `enable_minute=False`，导致分钟聚合验证路径从未经过测试覆盖
- 选择最近 1 年而非 3 年：分钟数据量级大（~240 条/天/标的 × 250 交易日 × 3 标的 ≈ 18 万条分钟记录），1 年已足够验证分钟聚合逻辑的完整性
- 仅 P0/P1 启用：P2 标的分钟未覆盖属于"可控风险"——后续日更新中如果出现双源不一致，才会动态触发分钟聚合（按需启用而非回填覆盖全部）

---

## B-04：audit_log 幂等性/TTL 清理（新增）

**决策**：幂等键 + TTL 策略双管齐下。

### 修正内容

#### E001_db_schema.md — §三.3.4 新增（幂等性与清理策略）

**§3.4.1 幂等键**：
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_log_idempotent
    ON validation_audit_log(trade_date, symbol, metric_name, source_a_name, source_b_name);
```
- 幂等逻辑：同一天、同一标的、同一字段、同源对的验证结果，仅保留最新一条
- 重复写入使用 `INSERT OR REPLACE` 语义

**§3.4.2 TTL 清理策略**：

| 表 | 策略 | 说明 |
|:---|:-----|:-----|
| validation_audit_log | 保留 90 天 | 90 天前的审计记录归档，表中只保留摘要 |
| staging_raw | 保留 30 天 | REPORT 数据超过 30 天后删除 |

清理脚本（SQLian `DELETE FROM ... WHERE triggered_at < datetime('now', '-90 days')`）已文档化。

**索引设计总结表新增**：`idx_audit_log_idempotent`（唯一复合索引）

#### E001_data_ingestion.md — §七.7.2 重写（幂等性）

从原有的"不做幂等去重"改为完整的幂等策略表格 + `_log_audit()` 幂等写入代码 + TTL 清理脚本：

| 表 | 策略 | 说明 |
|:---|:-----|:-----|
| stock_daily | UNIQUE(trade_date, symbol) | 同一日期-标的自动去重 |
| validation_audit_log | 幂等唯一索引 + TTL 90 天 | 幂等键：trade_date+symbol+metric_name+source_a_name+source_b_name |
| staging_raw | TTL 30 天 | 每日 cron 清理 |

**修正逻辑**：
- 幂等键防止日窗口内的重复写入——同一次运行中如果出现重试/回放，不会产生重复行
- TTL 治理长期膨胀——即使幂等键完美运行，每日不同的验证组合仍会累积，90 天窗口足够保证最近验证记录的可查询性
- staging_raw 只保留 30 天：REPORT 记录需要人工排查，30 天内的 REPORT 仍需要保留；超过 30 天的问题通常已被处理或归档
- 幂等 + TTL 各自独立工作，不做重复治理

---

## 修正文件清单

| 文件 | 变更类型 | 变更内容 |
|:-----|:---------|:---------|
| `E001_db_schema.md` | 修改 | B-01 DDL unit 注释; B-02 §6.3 扩写（条件+步骤+回滚）; B-04 §3.4 新增（幂等+TTL） |
| `E001_data_ingestion.md` | 修改 | B-01 §7.2 _log_audit() unit 注释; B-03 §6.3 分钟聚合启用; B-04 §7.2 幂等/TTL 重写 |
| `E001_db_ingestion_fix_moheng.md` | 新增 | 本修正记录文件 |

---

*修正完毕。墨衡 🖋️*
