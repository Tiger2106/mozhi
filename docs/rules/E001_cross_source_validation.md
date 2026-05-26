<!--
author: 墨涵 (mochen), 墨衡 (moheng), 墨萱 (moxuan), 玄知 (xuanzhi)
rule: E-001
title: E-001 · 多源数据交叉验证规则
status: 三方会签通过（2026-05-20）
version: 1.0
-->

# E-001 · 多源数据交叉验证规则

> **生效日期：** 2026-05-20
> **签署方：** 墨衡 ✅ 墨萱 ✅ 玄知 ✅ 墨涵 ✅（Owner批准 ✅）

## 一、规矩表述

**原始数据录入必须经多方交叉检验，保证数据正确性。**

同一字段从两个及以上独立数据源获取时，必须做单位归一化 + 交叉比对。

## 二、处理流程

```
两源差异 ≤ 0.3%
    └─✅ 直接通过，不记日志

两源差异 > 0.3%
    ├─→ 找第3个源比对
    │   ├─ 其中有配对 ≤ 0.3% → ✅ 通过，记录 diff_reason
    │   └─ 仍无法达成 → 尝试分钟聚合验证
    │                      ├─ 找到锚点 → ✅ 通过
    │                      └─ 仍无法 → 🔴 向主人报告
    └─同时：单位量级错（~100倍手vs股）→ 独立阻断，进staging_raw
```

## 三、量化阈值

| 阶梯 | 条件 | 处理 |
|:-----|:-----|:-----|
| 正常 | diff ≤ 0.3% | ✅ 直接通过 |
| 关注 | 0.3% < diff ≤ 仲裁通过 | ⚠️ PASS_WITH_NOTE，记枚举 diff_reason |
| 异常 | 仲裁失败 | 🔴 REPORT，向主人报告 |
| 单位错 | ~100倍量级差（手vs股） | 🔴 UNIT_ERROR，阻断进staging_raw |

## 四、验证维度

1. **多源API交叉比对**：至少两个独立数据源
2. **第三源仲裁**：两源不一致时引入第三源
3. **分钟聚合验证**：有分钟级数据时，累加生成日线值作为锚点

## 五、违规处理（不阻断原则）

- 未通过验证的数据写入 staging_raw 表（保留原始值）
- 主表对应字段写 NULL
- 不阻塞 pipeline 运行
- 审计日志完整记录

## 六、适用范围

| 优先级 | 字段 |
|:-------|:-----|
| P0 | volume、amount、open/high/low/close、trade_date、symbol |
| P1 | turnover_rate、流通市值、换手率 |
| P2 | 派生指标 |

## 七、diff_reason 枚举值

| 枚举值 | 说明 |
|:-------|:------|
| UNIT_CONVERTED | 单位转换后一致 |
| SPLIT_DIFF | 除权除息差异 |
| DIVIDEND_ADJUSTED | 分红调整差异 |
| AFTER_HOUR_TRADE | 盘后交易差异 |
| DELAYED_SOURCE | 数据源延迟差异 |
| AGGREGATION_ANCHOR | 分钟聚合验证锚定 |
| OTHER | 其他 |

## 八、版本记录

| 版本 | 日期 | 变更 |
|:-----|:-----|:------|
| v1.0 | 2026-05-20 | 初始版本，三方会签通过 |

---

*关联文件：*
- 算法描述：`docs/algorithms/E001_cross_source_validation.md`
- 讨论详情：`reports/reviews/meeting_data_governance/meeting_summary_20260520.md`
- 墨萱审查：`reports/reviews/meeting_data_governance/E001_review_moxuan.md`
- 玄知审查：`reports/reviews/meeting_data_governance/E001_review_xuanzhi.md`
