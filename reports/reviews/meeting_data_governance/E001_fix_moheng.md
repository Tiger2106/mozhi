<!--
author: 墨衡
created_time: 2026-05-20T22:29+08:00
fix_target: E001_cross_source_validation.md (v1.0 → v1.1)
based_on: E001_review_moxuan.md + E001_review_xuanzhi.md
-->

# E-001 算法描述修正记录 — 墨衡

> **修正范围**：1 项 P0 堵门 + 4 项 P1 修改
> **总耗时**：约 15 分钟
> **置信度**：95%（所有修正已在算法描述中逐项展开）

---

## 🔴 P0 — 堵门项修正

### P0-1: 单位映射方法A漏检路径

**问题**：`_check_unit_mismatch()` 方法A中，有 unit 字段 + 单位映射表存在时直接返回 `passed=True`，未检查归一化后数值是否一致。例如 hand=10000 vs shares=500000，归一化后为 1,000,000 vs 500,000（50% 差异）但被放行。

**修正**：
```python
# 方法A 修正后：先归一化再校验 diff
if ratio is not None and ratio != 1.0:
    normalized_a = source_a.value * ratio
    normalized_b = source_b.value
    norm_diff = _calc_diff_pct(normalized_a, normalized_b)
    if norm_diff <= THRESHOLD_PCT:
        # 归一化后一致
        return UnitCheckResult(passed=True, conversion_ratio=ratio)
    else:
        # 单位映射存在 → 不阻断为 UNIT_ERROR
        # 归一化后差异留给 Step 2 仲裁处理
        return UnitCheckResult(passed=True, conversion_ratio=ratio)
```

**关键约束**：有单位映射时 → **不阻断为 UNIT_ERROR**，归一化后差异走 Step 2 正常流程。

---

## 🟡 P1 — 修改项

### P1-1: trade_date / symbol 格式归一化

**新增函数**：
- `_normalize_identity_fields(input)` — 在 `cross_source_validate()` Step 0 调用
- `_normalize_date_str(date_str)` — 支持 `2026-05-20` / `2026/05/20` / `20260520` → ISO 格式
- `_normalize_symbol_str(symbol)` — 去市场前缀归一化：`601857.SH` → `601857`

**调用位置**：`cross_source_validate()` 入口前，Step 0。

---

### P1-2: diff_reason 模式判定函数展开

**新增 3 个判定函数**（§3 辅助函数），Phase 1 实现 UNIT_CONVERTED 和 OTHER：

| 函数 | Phase | 判定逻辑 | 状态 |
|:-----|:------|:---------|:-----|
| `_pattern_unit_conversion()` | Phase 1 | diff_ab>0.3% + 有第三源一致 + 源单位不标准 | ✅ 已实现 |
| `_pattern_after_hour()` | Phase 2 | 盘后交易特征检测 | 🔄 骨架（返回 False） |
| `_pattern_delayed()` | Phase 2 | 数据源延迟特征检测 | 🔄 骨架（返回 False） |

**函数签名更新**：现在传递 `diff_ac/diff_bc` 以及 `source_a/source_b/source_c` 引用。

---

### P1-3: 分钟聚合来源策略配置化

**新增配置项**：
- `minute_data_source_strategy`: 可选 `highest_quality` / `from_source_a` / `from_source_b` / `independent`
- Phase 1 默认：`highest_quality`（取质量评级最高的源的分钟数据）

**实现变更**：
- `_minute_aggregation_verify()` 中通过 `_get_config()` 加载策略
- 在 `minute_detail` 中记录 `minute_data_source` 标识
- 添加 `is_self_consistency_check` 标记，区分"独立验证"与"自洽性检查"
- 新增 `_get_config()` 辅助函数

---

### P1-4: 审计日志补充 source name

**`_build_audit_entry()` 新增字段**：

| 字段 | 来源 | 状态 |
|:-----|:-----|:-----|
| `source_a_name` | `input.source_a.source_name` | ✅ 已增加 |
| `source_a_val` | `input.source_a.value` | ✅ 改名（原 `val_a`） |
| `source_b_name` | `input.source_b.source_name` | ✅ 已增加 |
| `source_b_val` | `input.source_b.value` | ✅ 改名（原 `val_b`） |
| `source_c_name` | `input.source_c.source_name` (可选) | ✅ 已增加 |
| `source_c_val` | `input.source_c.value` (可选) | ✅ 已增加 |
| unit 系列字段 | — | 🔲 P2 可延后 |

---

## 版本更新

| 项目 | v1.0 | v1.1 |
|:-----|:-----|:-----|
| 版本 | E-001 v1.0 | E-001 v1.1 |
| Step 0 | 无 | 新增 `_normalize_identity_fields()` |
| Step 1 方法A | 比值检查 + 直接通过 | 归一化后 diff 比较 + 不阻断 |
| Step 3 | `_infer_diff_reason` 骨架调用 | 展开 `_pattern_unit_conversion()` 判定逻辑 |
| Step 4 | 分钟来源硬编码 | `_get_config()` 配置化 + 源标识记录 |
| Step 5 | `val_a/val_b/val_c` | `source_a_name/val`, `source_b_name/val`, `source_c_name/val` |
| 辅助函数 | 6 个 | 10 个（+`_normalize_identity_fields`, `_normalize_date_str`, `_normalize_symbol_str`, `_get_config`, 3 个 pattern 函数） |

---

## 未覆盖项（推荐后续跟进）

| 项目 | 来源 | 优先级 | 说明 |
|:-----|:-----|:-------|:-----|
| SourceValue 缺 field_name | 玄知 P1-3 | 🔶 P1 | 运行时 AttributeError，需要 DataStructure 层修改 |
| 分钟数据有序性约束 | 玄知 P1-4 | 🔶 P1 | `_aggregate_from_minute_data()` 中缺失排序 |
| 100 倍检测容差数据依据 | 墨萱 P2 | 🟢 P2 | 需预生产统计 |
| 单源降级 verdict | 墨萱 P2 | 🟢 P2 | 需新增 DEGRADED 或映射为 PASS |
| 测试要点表补全 | 墨萱 P2 | 🟢 P2 | §4 只覆盖 6/16 条红线 |

---

*报告人：墨衡*
*修正时间：2026-05-20 22:29 CST*
*下一动作：通知墨萱/玄知复审确认修正*
