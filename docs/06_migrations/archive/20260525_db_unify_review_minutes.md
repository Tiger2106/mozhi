# 数据库统一迁移方案 — 评审会议纪要
# DB_UNIFY_0525 Review Minutes

> 作者: 墨涵 (mochen)
> 时间: 2026-05-25T15:32+08:00
> 状态: ✅ Owner已签署，准予执行

---

## 方案概要

**迁移目标**：`analysis.db` → `market_data.db` + `pipeline_cache.db`

| 原始状态 | 目标状态 |
|:---------|:---------|
| data/analysis.db（行情+缓存混合11表） | data/market/market_data.db（行情唯一源） |
| — | data/pipeline_cache.db（非行情缓存，analysis.db改名） |
| data/db/analysis.db（Phase1遗留5表） | data/db/analysis.db.deprecated（废弃） |
| ~/sharereports/analysis.db（A0副本） | ~/sharereports/analysis.db.deprecated（废弃） |

**改动范围**：12个核心源文件 + 4个工具文件

---

## 审查结论汇总

### Step 1 — 墨衡汇报 ✅
方案覆盖7个板块：问题陈述 → 审计发现 → 迁移核心 → 改动范围 → 实施步骤 → 风险提示 → 结论建议

### Step 2 — 墨萱技术审查 ⚠️ 条件通过
| 审查维度 | 结论 | 风险 |
|:---------|:----|:----:|
| 数据一致性 | ⚠️ 条件通过（复权语义需明确标注） | P1 |
| 改动完整性 | ⚠️ 3处疏漏 | P1 |
| 数据质量 | ⚠️ 交易日历覆盖范围差异 | P2 |
| 回退方案 | ✅ 基本完整 | P2 |

### Step 3 — 玄知技术把关 ⚠️ 条件通过
| 类别 | 数量 | 说明 |
|:----|:----:|:-----|
| P0退回 | **0** | 无系统性逻辑矛盾 |
| P1改进建议 | **3** | 格式+覆盖范围+OIL日历 |
| P2建议 | **1** | daily_factors验证 |

---

## 3项P1问题（实施中处理）

### P1-1：交易日历日期格式
**处理**：Step 5 验证中加入 date_aligner 兼容测试

### P1-2：交易日历覆盖范围
**处理**：迁移前合并旧库完整日历至 market_data.db

### P1-3：OIL市场交易日历无归宿
**处理**：明确 OIL 日历保留在 pipeline_cache.db 的 trading_calendar 中

---

## Owner签署

**状态**：✅ **准予执行** (2026-05-25T15:51+08:00)

**签署人**：Owner
**签署意见**：同意方案，开始实施

**实施负责人**：墨衡
**实施时间**：2026-05-25
**回退条件**：Step 5 验证不通过则终止，执行回退方案
