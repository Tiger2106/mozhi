<!--
author: 墨萱
review_target: E-001 算法描述（墨衡 v1.0）
created_time: 2026-05-20T22:28+08:00
based_on: moxuan_opinion.md (2026-05-20T21:31)
file_under_review: E001_algo_description.md
-->

# E-001 算法描述审查报告 — 墨萱

> **审查结论：有条件通过（PASS_WITH_NOTE）**
> 
> 墨衡本次产出的算法描述相对于之前会上的方案有了实质性的提升，结构清晰、伪代码可读性强、边界情况覆盖面显著改善。大部分我已提出的要求得到回应。
> 
> **但以下 4 个问题需要在进入测试前修正**，否则测试无法有效执行。

---

## 0. 总评矩阵

| 审查维度 | 评分 (A~D) | 摘要 |
|:---------|:----------:|:-----|
| 算法完整性 | B+ | 主流程完整，Step 1~6 全覆盖；缺 trade_date/symbol 的格式校验细则 |
| 测试可验证性 | B | 伪代码精度足够编写单元测试；但边界条件不完整影响集成测试 |
| 边界情况处理 | B- | Step 2 的 0 值处理已修复；Step 1 阈值存在理论模型问题 |
| 枚举完整性 | A- | verdict 4 值、diff_reason 7 值覆盖合理；缺 source_unavailable 场景的 verdict |
| 分钟聚合验证 | B+ | 逻辑清晰，但聚合与同源一致性的判断标准缺具体阈值 |
| 审计日志字段 | A- | 15 字段基本对齐；缺 第三源名称/单位的记录 |

---

## 1. 算法完整性

### ✅ 已覆盖
- Step 1 ~ Step 6 全流程覆盖
- 两源 → 第三源 → 分钟聚合 → REPORT 的仲裁链完整
- 违规不阻断的写入策略明确
- 测试要点与验收红线的映射表已对齐

### ❌ 遗漏项

#### 问题 1.1：trade_date / symbol 格式校验缺失
我在 `moxuan_opinion.md` 中明确提出 trade_date 和 symbol 是 **P0 字段**，它们的验证方式与数值字段不同（格式归一化和日期对齐）。算法描述中仅在审计日志字段里记录了它们，**完全没有定义格式校验逻辑**。

**影响**：如果东财返回 `2026-05-20` 而新浪返回 `2026/05/20` 或 `20260520`，数据可以写入但对不齐。这不是数值交叉验证能发现的错位，是**身份标识错位**。

**要求**：在 `cross_source_validate()` 入口前，或作为独立 step，增加 `_validate_identity_fields()` 函数，定义：
- 日期格式归一化规则
- 代码格式归一化规则（含市场前缀处理）
- 跨源日期一致性检查

---

## 2. 测试可验证性

### ✅ 已对齐
- 算法描述 §4 已经映射了我的验收红线至对应的函数
- 每个函数的输入/输出数据结构清晰，可以编码单元测试
- `_build_audit_entry()` 的参数签名明确，可以直接测

### ❌ 不清晰处

#### 问题 2.1：分钟聚合的同源一致性检查缺少细粒度的阈值
```python
source_to_minute_diff = _calc_diff_pct(val_a, minute_aggregated)
# 注释说 "如果 diff 接近 0"
```
**"接近 0" 是多少？** 同源分钟↔日线理论上应为 0%，但浮点精度、数据源不同批次的处理都可能引入微小差异。如果没有明确的阈值（如 0.01% 或 0.1%），测试代码中无法断言。

**要求**：定义 `MINUTE_SELF_CONSISTENCY_THRESHOLD` 常量，并说明其值如何确定。

#### 问题 2.2：`_infer_diff_reason()` 的推断逻辑太模糊
当前伪代码只是模式匹配的外壳（`_pattern_unit_conversion()` 等函数未展开），测试时无法覆盖这些模式的具体判定条件。测试者无法构造"触发器"来验证各枚举值。

**要求**：展开每种模式的判定条件，至少给出伪代码级别的判定规则。

---

## 3. 边界情况处理

### ✅ 已修复
- **Step 2 `_calc_diff_pct()` 的 0 值处理**：我之前的会中提到 volume=0 时 diff 公式会除 0，墨衡已修复为 `denominator = max(...)` + 双零特判，逻辑正确。
- 两值均为零 → diff=0，一零一非零 → diff=100%，合理。

### ⚠️ 需确认

#### 问题 3.1：Step 1 "~100 倍" 检测与单位映射的优先顺序问题

算法描述中 `_check_unit_mismatch()` 的代码顺序是：
1. 方法A：先判断显式 unit 字段→有单位映射则通过
2. 方法B：再从数值量级推断→~100 倍则阻断

**但 **方法A** 中有一行值得深究：**

```python
# 有单位映射但数值不匹配换算 → 可能是其他差异，不阻断
return UnitCheckResult(passed=True, conversion_ratio=ratio)
```

**场景**：源A: `{unit='hand', value=10000}`, 源B: `{unit='shares', value=500000}`。
- 方法A：hand→shares 映射存在，ratio=100。比值 = 10000/500000=0.02，不等于 1/100 → "数值不匹配换算"，仍返回 `passed=True`。**但实际上这里数值本身就是错的**。
- 方法B根本没机会执行。

**这是一个漏检路径。** 单位映射表存在且 ratio ≠ 1.0 时，应该校验归一化后的值，而不是仅检查比值是否约等于换算比。

**建议**：
```python
# 方法A 补充逻辑
if ratio is not None and ratio != 1.0:
    normalized_a = source_a.value   # (如果 source_a 是 hand 单位)
    normalized_b = source_b.value * ratio  # 归一化到 shares
    norm_diff = _calc_diff_pct(normalized_a, normalized_b)
    if norm_diff <= THRESHOLD_PCT:
        # 归一化后一致 → 通过
        return UnitCheckResult(passed=True, conversion_ratio=ratio)
    else:
        # 归一化后仍然不一致 → 这是真实数据差异，不阻断（走 Step 2 后续处理）
        return UnitCheckResult(passed=True, conversion_ratio=ratio)
    # 注意：这里不应阻断为 UNIT_ERROR，因为单位已映射成功
```
即：**有单位映射时，不应阻断为 UNIT_ERROR（因为单位关系已确认），归一化后的真实差异留给 Step 2 处理。**

#### 问题 3.2：100 倍检测的容差是否过宽？

- 当前 `_approx()` 的默认 tolerance = 0.15（15%）
- 100 倍检测：比值在 85~115 范围内即判为 ~100x
- 但对于价格字段（如 0.01 元 vs 1 分 = 1e-2 元），量级也是 ~100 倍
- 对于 港股的分单（1元=0.1厘），量级 10 倍

如果两个源的数值本身差异达到 85 倍就触发 UNIT_ERROR，而正常价格差异（如 A=0.12, B=10）完全不构成单位误匹配场景——这不会导致假阳性吗？

**建议**：墨衡需要给出"为什么选 15%"的数据依据，或者降低容忍度至 5%。如果数据支撑不足，建议标注为 **"Phase 1 预生产期间收集统计分布后再定"**。

#### 问题 3.3：`_now_iso8601()` 时区硬编码
辅助函数中 `timezone(timedelta(hours=8))` 硬编码为 +08:00。如果系统部署到 UTC 服务器，时间戳字段会混用。

**建议**：改用系统时区或配置化设置，审计日志的 `triggered_at` 字段建议统一使用 UTC。

---

## 4. 枚举完整性

### ✅ verdict 4 值分析

| 枚举值 | 覆盖场景 | 评价 |
|:-------|:---------|:-----|
| PASS | 两源阈值内通过 | ✅ 正确 |
| PASS_WITH_NOTE | 超阈值但有合法 diff_reason | ✅ 正确 |
| REPORT | 无法仲裁，需人工干预 | ✅ 正确 |
| UNIT_ERROR | 单位误检测阻断 | ✅ 正确 |

### ⚠️ 潜在缺失

#### 问题 4.1：`source_unavailable` 场景的 verdict
如果源 B 完全不可用（网络超时 → `source_b.value = None`），当前 Step 1 会如何？
- `_check_unit_mismatch()` → `_has_values()` 判断无值 → 返回 passed=True（无阻断）
- Step 2 → diff_ab 无法计算（单源）

**这种情况下 verdict 应该是多少？** 目前没有对应枚举值。可能的处理方向：
- 新增 `DEGRADED` 枚举？但代价是改动 schema 和所有下游
- 或映射为 `PASS` + 审计日志中标记单源降级状态

**要求**：明确单源降级场景的 verdict 映射，否则审计日志无法统一查询。

### ✅ diff_reason 7 值分析

| 枚举值 | 覆盖场景 | 评价 |
|:-------|:---------|:-----|
| UNIT_CONVERTED | 单位转换后一致 | ✅ |
| SPLIT_DIFF | 除权除息差异 | ✅ |
| DIVIDEND_ADJUSTED | 分红调整差异 | ✅ |
| AFTER_HOUR_TRADE | 盘后交易差异 | ✅ |
| DELAYED_SOURCE | 数据源延迟差异 | ✅ |
| AGGREGATION_ANCHOR | 分钟聚合验证锚定 | ✅ 新增，覆盖 Step 4 |
| OTHER | 其他 | ✅ 兜底 |

**补充说明**：我在会上的意见里还提了 `NOT_APPLICABLE`，用于无法计算 diff 的场景（如源不可用）。墨衡这次的 7 值中没有包含它。建议保留 `NOT_APPLICABLE` 作为 verdict 非 FAIL 但 diff 为 None 时的标准值。

---

## 5. 分钟聚合验证

### ✅ 正确部分
- 字段聚合规则明确（volume→SUM, open→first, close→last, high→MAX, low→MIN）
- 聚合值作为"独立锚点"比对各源的理念正确
- `_minute_aggregation_verify()` 的接口设计合理

### ⚠️ 不足

#### 问题 5.1：分钟聚合与同源日线的一致性检查标准不明确
参见 §2.1 — `source_to_minute_diff` 的判断缺乏具体阈值。同源数据理论上为 0%，但工程实践中需要考虑：
- 分钟数据是否包含盘后数据
- 分钟数据的截断精度
- 不同 source 对同一天的收盘时间定义

**要求**：设置 `MINUTE_SELF_CONS_THRESHOLD`（建议 0.01%~0.05%），并说明这个值如何在实际运行中验证。

#### 问题 5.2：分钟聚合数据的来源未定义
算法描述提到 "从分钟数据按字段类型累加/聚合"，但 **分钟数据本身来自哪个源？** 是从源 A 的分钟数据聚合？还是从独立的数据源聚合？

如果是源 A 的分钟数据聚合后与源 A 的日线比对，那这个验证没有独立意义（A 的分钟→日线应该 100% 自洽）。

**要求**：明确分钟聚合的来源策略：
- 取所有源中质量最高的源的分钟数据
- 或从独立第三方获取分钟数据
- 并在审计日志中记录分钟聚合的源标识

#### 问题 5.3：分钟聚合出结果后的 diff_reason 设置
§2.4 中 `_minute_aggregation_fallback()` 被调用时有两种结果：
1. `is_anchor_found=True` → 调用 `_build_minute_anchor_result()`，此时 diff_reason 应设为 `AGGREGATION_ANCHOR`
2. `is_anchor_found=False` → 返回 `REPORT`

但 `_build_minute_anchor_result()` 的伪代码未展开，diff_reason 设置逻辑不透明。

**要求**：展开 `_build_minute_anchor_result()` 的伪代码。

---

## 6. 审计日志字段完备性

### 我的 15 字段要求 vs 墨衡实现

| 我提出的字段 | 墨衡实现 | 状态 |
|:------------|:---------|:----|
| trade_date | ✅ 有 | ✅ |
| symbol | ✅ 有 | ✅ |
| metric_name | ✅ field_name | ✅ |
| source_a_name | ✅ val_a (但字段名不包含 name) | ⚠️ |
| source_a_val | ✅ val_a | ✅ |
| source_a_unit | ❌ 缺 | ❌ |
| source_b_name | ❌ 缺 | ❌ |
| source_b_val | ✅ val_b | ✅ |
| source_b_unit | ❌ 缺 | ❌ |
| val_c / source_c_name / source_c_unit | ✅ val_c，缺 name 和 unit | ⚠️ |
| threshold_pct | ✅ 有 | ✅ |
| diff_pct | ✅ diff_ab/ac/bc | ✅ |
| verdict | ✅ 有 | ✅ |
| diff_reason_enum | ✅ diff_reason | ✅ |
| rule_version | ✅ 有 | ✅ |
| triggered_at | ✅ 有 | ✅ |

### ❌ 缺口

3 个缺失字段：**source_a_name, source_b_name, unit 系列**。

**为什么这些字段重要？**

测试场景：断言 `audit_entry` 中的 source 名称是否正确，以便人工回查时知道"差了多少、哪个源的数据不对"。

目前 `_build_audit_entry()` 没有 receiver source.name → 所以没有记录。墨衡需补充从 `ValidationInput` 提取 `source_name` 和 `unit` 的逻辑。

---

## 7. 其他问题

### 问题 7.1：`_load_unit_conversion_map()` 的 pass 实现
这是一个空壳函数。在可测试性层面，单元测试需要一个 mockable 的单位映射表加载接口。建议注入依赖（dependency injection）而非从 YAML 硬加载，否则测试中需要真实文件。

### 问题 7.2：测试要点映射表的完整性

§4 的测试要点表只覆盖了 6 条红线。但我共定义了 16 条验收红线（§1 的四维度 16 项）。缺失项：
- E.02-004（单源关键字段 WARN）→ 未覆盖
- E.02-005（单源非关键字段直接写入）→ 未覆盖
- E.03-002（返回格式异常 → WARN）→ 未覆盖
- E.03-003（映射表中无此字段 → 通过）→ 未覆盖
- E.03-004（并发写入竞态条件）→ 未覆盖
- E.04-002（审计日志字段完整）→ 部分覆盖（需补 unit 和 name 字段）
- E.04-003（事后修正可追溯）→ 未覆盖

**要求**：补充对应函数的映射，或明确哪些红线由哪个函数覆盖。

### 问题 7.3：`_calc_diff_pct()` 在 denominator 判零逻辑有重叠
```python
if val_a == 0 and val_b == 0:
    return 0.0
denominator = max(abs(val_a), abs(val_b))
if denominator == 0:
    return 100.0  # 一个为零另一个非零
```
第二个 `if denominator == 0` 实际上永远不会被执行到，因为双零已在前面的 if 拦截。单零场景：`max(0, 100) = 100` → denominator 非 0，不会走到第二个 if。

这不会导致错误，但代码路径上有死代码。建议移除第二个 if，或改为更明确的单零检测。

---

## 8. 修正优先级

| 优先级 | 问题 | 影响 | 修复负责人 |
|:-------|:-----|:-----|:----------|
| 🔴 **P0 — 堵门项** | trade_date/symbol 格式校验缺失 | 身份标识错位不可检测 | 墨衡 |
| 🔴 **P0 — 堵门项** | 单位映射方法A的漏检路径 | 映射表存在时数值差异可能被忽略 | 墨衡 |
| 🟡 **P1 — 修改项** | diff_reason 推断逻辑未展开 | 无法编写测试用例覆盖枚举判断 | 墨衡 |
| 🟡 **P1 — 修改项** | 分钟聚合来源未定义 + 同源阈值未定 | Step 4 实际无法执行 | 墨衡 |
| 🟡 **P1 — 修改项** | 审计日志缺 source name/unit | 可追溯性不足 | 墨衡 |
| 🟢 **P2 — 建议项** | 100 倍检测容差数据依据 | 可能产生假阳性 | 墨衡（预生产收集）|
| 🟢 **P2 — 建议项** | 单源降级 verdict 定义 | 审计日志无法统一查询 | 墨衡 |
| 🟢 **P2 — 建议项** | 测试要点映射表补全 | §4 表只覆盖了 6/16 条红线 | 墨衡 |
| 🔵 **P3 — 优化项** | `_now_iso8601()` 时区硬编码 | 多时区部署问题 | 墨衡 |
| 🔵 **P3 — 优化项** | `_calc_diff_pct()` 死代码 | 不影响逻辑，代码整洁度 | 墨衡 |
| 🔵 **P3 — 优化项** | 分钟聚合结果函数未展开 | 可读性 | 墨衡 |

---

## 9. 最终结论

**PASS_WITH_NOTE** — 算法描述整体结构清晰，核心逻辑正确，验收红线对齐度较上一版显著提升。但以下 2 项为**堵门条件**，修正前不可进入测试阶段：

1. **trade_date/symbol 格式校验必须实现**：作为数据身份的"身份验证层"，缺失此项则整个验证机制存在系统性盲区。
2. **单位映射方法A的归一化后数值校验**：当前逻辑在有单位映射时可能放行真正的数值差异。

其余 P1 项（diff_reason 展开、分钟聚合具体化、审计日志字段补全）建议在 Phase 1 交付前完成，否则测试覆盖度将受限。

**置信度**：92% — 核心问题点已在本次审查中暴露。剩余 8% 的不确定性来自：分钟聚合的工程实现细节（特别是分钟数据来源策略）需要墨衡实际编码时才能最终确认。

---

*报告人：墨萱*
*审查时间：2026-05-20 22:28 CST*
*下一动作：将审查结论通知墨涵，由墨涵安排墨衡修正后重新提交审查*
