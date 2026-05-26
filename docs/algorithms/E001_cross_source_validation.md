<!--
author: 墨衡
version: E-001 v1.1 (P0+P1 fix)
created_time: 2026-05-20T22:29+08:00
based_on: 三方会议定稿（墨衡/墨萱/玄知 + Owner裁决）
fixed_against: E001_review_moxuan.md + E001_review_xuanzhi.md
-->

# E-001 多源数据交叉验证 — 算法描述

> **规矩表述（定稿）**：同一字段从两个及以上独立数据源获取时，必须做单位归一化 + 交叉比对。差异可解释即通过，不可解释的差异写入审计日志。单位归一化是强制性要求，数值比对为弹性要求。

---

## 1. 总览

### 1.1 核心配置

| 项目 | 值 | 来源 |
|:-----|:---|:-----|
| 数值比对阈值 | **0.3%** | Owner 裁决（替代墨衡的 0.5%/3% 提案） |
| 单位差异检测倍数 | **~100 倍**（如 手 vs 股, 1手=100股） | 墨衡提出 |
| diff_reason 类型 | **强制枚举化** | 墨萱提出 + 玄知裁决 |
| 适用范围 P0 | volume, amount, open/high/low/close, **trade_date, symbol** | 墨萱补充 + 玄知同意 |
| 违规阻断策略 | **不阻断 pipeline**，写入 staging_raw + 主表 NULL | 墨衡提出，全员同意 |
| 审计日志 | 每次验证必记，含 trade_date + symbol | 全员同意 |

### 1.2 数据结构定义

```python
# ─── 全局类型定义 ───

@dataclass
class SourceValue:
    """单源数据单元"""
    source_name: str          # 如 'eastmoney', 'sina'
    value: float | None       # 归一化后的数值
    raw_value: Any            # 原始值（保留用于审计）
    unit: str                 # 原始单位（如 'shares', 'lots', 'yuan', 'fens'）

@dataclass
class ValidationInput:
    """验证函数的输入"""
    field_name: str           # 度量名称，如 'volume'
    source_a: SourceValue
    source_b: SourceValue
    source_c: SourceValue | None = None   # 第三源（可选）
    minute_data: list | None = None       # 分钟级明细（可选）
    symbol: str = ""                      # 股票代码（P0）
    trade_date: str = ""                  # 交易日（P0）

@dataclass
class ValidationResult:
    """验证结果"""
    verdict: str              # 'PASS' | 'PASS_WITH_NOTE' | 'REPORT' | 'UNIT_ERROR'
    diff_ab: float | None     # A↔B 差异百分比
    diff_ac: float | None     # A↔C 差异百分比（如有源C）
    diff_bc: float | None     # B↔C 差异百分比（如有源C）
    diff_reason: str | None   # 枚举值或 None
    selected_source: str | None  # 最终采用的源
    selected_value: float | None # 最终采用的值
    audit_entry: dict         # 审计日志行（Step 5 使用）
```

---

## 2. 核心算法（伪代码）

### 2.1 入口函数：cross_source_validate()

```python
def cross_source_validate(input: ValidationInput) -> ValidationResult:
    """
    E-001 多源数据交叉验证 —— 主入口

    输入: 字段值 + 可选第三源/分钟数据
    输出: ValidationResult（含裁决结果+审计记录）
    异常: 不抛出，所有异常情况映射到枚举 verdict
    """

    # ── Step 0: 身份标识字段归一化 ────────────────
    input = _normalize_identity_fields(input)

    # ── Step 1: 单位归一化检查 ──────────────────────
    unit_check = _check_unit_mismatch(input.source_a, input.source_b)
    if unit_check.is_mismatch:
        # 直接阻断，不参与后续比对
        return _build_unit_error_result(input, unit_check)

    # 单位一致 → 归一化到标准单位（如统一为 股）
    val_a = _normalize_to_standard_unit(input.source_a)
    val_b = _normalize_to_standard_unit(input.source_b)

    # ── Step 2: 两源比对 ──────────────────────────
    #  阈值: 0.3% (常量 THRESHOLD_PCT = 0.3)
    diff_ab = _calc_diff_pct(val_a, val_b)

    if diff_ab <= THRESHOLD_PCT:
        # 通过，写入主表，不记日志
        return ValidationResult(
            verdict='PASS',
            diff_ab=diff_ab,
            selected_source=_pick_source(val_a, val_b),
            selected_value=_pick_value(val_a, val_b),
            audit_entry=_build_audit_entry(input, diff_ab=diff_ab, verdict='PASS')
        )

    # diff_ab > 0.3% → 进入 Step 3
    return _third_source_arbitration(input, val_a, val_b, diff_ab)
```

### 2.2 Step 1 — 单位归一化检查

```python
def _check_unit_mismatch(source_a: SourceValue, source_b: SourceValue) -> UnitCheckResult:
    """
    单位差异检测
    ┌─────────────────────────────────────────────────────────┐
    │ 核心逻辑：检测量级是否相差约 100 倍（手 vs 股）         │
    │ 实现方式：                                              │
    │   1. 提取两源的单位（从 unit 字段或从数值量级推断）      │
    │   2. 如果数值相差 ~100x（90x ~ 110x），检查单位映射     │
    │   3. 如果单位映射中确认是同一单位的不同表述 → PASS      │
    │   4. 如果无法解释 → UNIT_MISMATCH                       │
    └─────────────────────────────────────────────────────────┘

    单位映射表（示例）:
        'shares' ↔ 'lots' | 1 lot = 100 shares
        'yuan'   ↔ 'fen'  | 1 yuan = 100 fen
        'yuan'   ↔ 'li'   | 1 yuan = 0.1 li (港股分单)
    """
    unit_map = _load_unit_conversion_map()  # 从 YAML 配置加载

    # 方法A: 根据显式 unit 字段映射
    if source_a.unit and source_b.unit:
        ratio = unit_map.get_conversion_ratio(source_a.unit, source_b.unit)
        if ratio is not None and ratio != 1.0:
            # 有明确单位映射关系 → 归一化后做数值比对
            # source_a.value * ratio 标准化到 source_b.unit
            normalized_a = source_a.value * ratio
            normalized_b = source_b.value
            norm_diff = _calc_diff_pct(normalized_a, normalized_b)
            if norm_diff <= THRESHOLD_PCT:
                # 归一化后一致 → 正常单位转换
                return UnitCheckResult(passed=True, conversion_ratio=ratio)
            else:
                # 单位关系已确认，但数值本身不一致
                # ⚠️ 不阻断为 UNIT_ERROR（因为单位映射没问题）
                # 归一化后差异留给 Step 2 后续仲裁处理
                return UnitCheckResult(passed=True, conversion_ratio=ratio)

    # 方法B: 从数值量级推断
    if _has_values(source_a.value, source_b.value):
        ratio = _safe_divide(source_a.value, source_b.value)
        # ⚠️ 重点：检测 ~100x 量级差异
        if _approx(ratio, 100, tolerance=0.15) or _approx(ratio, 1/100, tolerance=0.15):
            # 怀疑是 "手 vs 股" 类错误
            return UnitCheckResult(
                passed=False,
                is_mismatch=True,
                reason='UNIT_MISMATCH',
                detail=f'Value ratio ~{ratio:.1f}x, possible unit mismatch'
            )

    return UnitCheckResult(passed=True)
```

### 2.3 Step 2 — 两源比对

```python
def _calc_diff_pct(val_a: float, val_b: float) -> float:
    """
    计算差异百分比
    公式: diff = |val_A - val_B| / max(|val_A|, |val_B|) * 100%
    边界处理:
        - 两值均为零 → diff = 0（无差异）
        - 一零一非零 → diff = 100%（完全不一致）
    """
    if val_a == 0 and val_b == 0:
        return 0.0
    denominator = max(abs(val_a), abs(val_b))
    if denominator == 0:
        return 100.0  # 一个为零另一个非零
    return abs(val_a - val_b) / denominator * 100


# ⚠️ 阈值常量（最终裁决值）
THRESHOLD_PCT = 0.3  # 0.3%，由 Owner 指定
```

### 2.4 Step 3 — 第三源仲裁

```python
def _third_source_arbitration(
    input: ValidationInput,
    val_a: float, val_b: float,
    diff_ab: float
) -> ValidationResult:
    """
    第三源仲裁逻辑
    ┌─────────────────────────────────────────────────────────┐
    │ 核心逻辑：                                             │
    │   1. 如果提供了源 C，计算全部 pairwise diff            │
    │   2. 寻找任意配对中 diff ≤ 0.3% 的组合                 │
    │   3. 找到 → 以该配对为准，记录 diff_reason 枚举值      │
    │   4. 未找到 → 尝试 Step 4 分钟聚合验证                 │
    │   5. 如果 Step 4 也无法达成 → 向主人报告               │
    │                                                        │
    │ diff_reason 枚举值：                                   │
    │   UNIT_CONVERTED      — 单位已转换后一致              │
    │   SPLIT_DIFF          — 除权除息差异                  │
    │   DIVIDEND_ADJUSTED   — 分红调整差异                  │
    │   AFTER_HOUR_TRADE    — 盘后交易差异                  │
    │   DELAYED_SOURCE      — 数据源延迟差异                │
    │   AGGREGATION_ANCHOR  — 分钟聚合验证锚定             │
    │   OTHER               — 其他（需附注）                │
    └─────────────────────────────────────────────────────────┘
    """
    if input.source_c is None or input.source_c.value is None:
        # 无第三源 → 尝试分钟聚合验证
        return _minute_aggregation_fallback(input, val_a, val_b, diff_ab)

    val_c = _normalize_to_standard_unit(input.source_c)
    diff_ac = _calc_diff_pct(val_a, val_c)
    diff_bc = _calc_diff_pct(val_b, val_c)

    # 所有 pairwise diff 对
    pairs = [
        ('A', 'B', diff_ab, input.source_a, input.source_b),
        ('A', 'C', diff_ac, input.source_a, input.source_c),
        ('B', 'C', diff_bc, input.source_b, input.source_c),
    ]

    # 寻找 diff ≤ 0.3% 的配对
    passing_pairs = [(name_a, name_b, d, src_a, src_b)
                     for name_a, name_b, d, src_a, src_b in pairs
                     if d <= THRESHOLD_PCT]

    if passing_pairs:
        # 存在通过配对 → 以该配对为准
        best_pair = _select_best_pair(passing_pairs)
        diff_reason = _infer_diff_reason(
            val_a, val_b, val_c, diff_ab, diff_ac, diff_bc
        )
        return ValidationResult(
            verdict='PASS_WITH_NOTE',
            diff_ab=diff_ab,
            diff_ac=diff_ac,
            diff_bc=diff_bc,
            diff_reason=diff_reason,
            selected_source=best_pair.source,
            selected_value=best_pair.value,
            audit_entry=_build_audit_entry(
                input, diff_ab=diff_ab, diff_ac=diff_ac, diff_bc=diff_bc,
                verdict='PASS_WITH_NOTE', diff_reason=diff_reason
            )
        )

    # 所有配对均 > 0.3%
    # → 尝试 Step 4 分钟聚合验证
    minute_result = _minute_aggregation_verify(input, val_a, val_b, val_c)
    if minute_result.is_anchor_found:
        return _build_minute_anchor_result(input, minute_result, diff_ab, diff_ac, diff_bc)

    # 仍无法达成 → 向主人报告
    return ValidationResult(
        verdict='REPORT',
        diff_ab=diff_ab,
        diff_ac=diff_ac,
        diff_bc=diff_bc,
        diff_reason=None,
        selected_source=None,
        selected_value=None,
        audit_entry=_build_audit_entry(
            input, diff_ab=diff_ab, diff_ac=diff_ac, diff_bc=diff_bc,
            verdict='REPORT'
        )
    )


def _infer_diff_reason(val_a, val_b, val_c, diff_ab, diff_ac, diff_bc) -> str:
    """
    推断差异原因的枚举值
    逻辑：基于数值特征自动推断，而非人工输入
        - A↔B 有单位差异 (diff_ab≈100%, diff_ac 或 diff_bc 小) → UNIT_CONVERTED
        - 成对偏差模式（一对一准、一对不准）→ 检查延迟标识 → DELAYED_SOURCE
        - 盘中 vs 盘后模式 → AFTER_HOUR_TRADE
        - 两对一致、一对不一致 → 以一致对为准
        - 默认：OTHER
    """
    # 自动推断逻辑（展开模式判定）
    if _pattern_unit_conversion(val_a, val_b, val_c, diff_ab, diff_ac, diff_bc,
                                 input.source_a, input.source_b, input.source_c):
        return 'UNIT_CONVERTED'
    elif _pattern_after_hour(val_a, val_b, val_c, diff_ab, diff_ac, diff_bc):
        return 'AFTER_HOUR_TRADE'
    elif _pattern_delayed(val_a, val_b, val_c, diff_ab, diff_ac, diff_bc):
        return 'DELAYED_SOURCE'
    else:
        return 'OTHER'
```

### 2.5 Step 4 — 分钟聚合验证

```python
@dataclass
class MinuteAggregationResult:
    """分钟聚合验证结果"""
    is_anchor_found: bool
    anchor_source: str | None        # 与分钟聚合一致的源
    anchor_value: float | None       # 分钟聚合生成的日值
    minute_detail: dict | None       # 分钟明细摘要（审计用）


def _minute_aggregation_verify(
    input: ValidationInput,
    val_a: float, val_b: float,
    val_c: float | None = None
) -> MinuteAggregationResult:
    """
    分钟聚合验证（可选维度）
    ┌─────────────────────────────────────────────────────────┐
    │ 使用场景：                                              │
    │   第三源仲裁失败后，如果该字段有分钟级明细数据         │
    │                                                        │
    │ 逻辑：                                                 │
    │   1. 从分钟数据按字段类型累加/聚合生成日线值            │
    │     - volume: SUM(minute_volume)                       │
    │     - amount: SUM(minute_amount)                       │
    │     - price:  VWAP(分钟价格, 分钟成交量)               │
    │   2. 同源分钟↔日线差异应 ≈ 0%（同一数据源）           │
    │   3. 将分钟聚合值作为独立锚点，与各源比对              │
    │   4. 如果某源的日值与分钟聚合值一致 → 以该源为准      │
    └─────────────────────────────────────────────────────────┘
    """
    if input.minute_data is None or len(input.minute_data) == 0:
        return MinuteAggregationResult(is_anchor_found=False, ...)

    # ═══════════════════════════════════════════════════════════
    # 分钟聚合来源策略（配置化）
    #   config key: minute_data_source_strategy
    #   可选值:
    #     'highest_quality'  — 取质量评级最高的源的分钟数据 (Phase 1 默认)
    #     'from_source_a'    — 从源 A 获取
    #     'from_source_b'    — 从源 B 获取
    #     'independent'      — 从独立第三方获取
    #
    #   ⚠️ 重要：若分钟数据来自某验证源自身（如源 A 的分钟→源 A 的日线），
    #      这本质是自洽性检查而非独立仲裁。审计日志中必须记录
    #      分钟聚合的源标识 (minute_data_source)，以便人工追溯。
    # ═══════════════════════════════════════════════════════════
    _minute_source = _get_config('minute_data_source_strategy', default='highest_quality')

    # 从分钟数据聚合生成日线值
    minute_aggregated = _aggregate_from_minute_data(
        input.field_name, input.minute_data
    )

    # 与各源比对，寻找最接近的
    candidates = [
        ('A', val_a, _calc_diff_pct(val_a, minute_aggregated)),
        ('B', val_b, _calc_diff_pct(val_b, minute_aggregated)),
    ]
    if val_c is not None:
        candidates.append(('C', val_c, _calc_diff_pct(val_c, minute_aggregated)))

    # 取与分钟聚合差异最小的源
    best = min(candidates, key=lambda x: x[2])

    # 同源自洽性标记：如果分钟内源与被比对的源来自同一数据提供方
    _is_self_consistent = (_minute_source == 'from_source_' + best[0].lower())

    if best[2] <= THRESHOLD_PCT:
        # 分钟聚合与某源一致
        # 注意：若是自洽性验证（同源），minute_detail 中标记 is_self_consistency_check
        return MinuteAggregationResult(
            is_anchor_found=True,
            anchor_source=best[0],
            anchor_value=best[1],
            minute_detail={
                'aggregated_value': minute_aggregated,
                'minute_data_source': _minute_source,
                'is_self_consistency_check': _is_self_consistent,
            }
        )

    # 分钟聚合也无法仲裁
    return MinuteAggregationResult(is_anchor_found=False, ...)


def _aggregate_from_minute_data(field_name: str, minute_data: list) -> float:
    """
    根据字段类型从分钟数据聚合生成日线值
    聚合方法因字段类型而异：
        volume/amount → SUM
        open → first minute 的 open
        close → last minute 的 close
        high → MAX(minute_high)
        low  → MIN(minute_low)
    """
    if field_name in ('volume', 'amount'):
        return sum(row['value'] for row in minute_data)
    elif field_name == 'open':
        return minute_data[0]['value']
    elif field_name == 'close':
        return minute_data[-1]['value']
    elif field_name == 'high':
        return max(row['value'] for row in minute_data)
    elif field_name == 'low':
        return min(row['value'] for row in minute_data)
    else:
        raise ValueError(f"Unsupported field for minute aggregation: {field_name}")
```

### 2.6 Step 5 — 审计日志

```python
def _build_audit_entry(
    input: ValidationInput,
    *,
    diff_ab: float | None,
    diff_ac: float | None = None,
    diff_bc: float | None = None,
    verdict: str,
    diff_reason: str | None = None
) -> dict:
    """
    构建审计日志记录

    每次验证必须记录的字段：
    ┌──────────────────────────┬─────────────────────────────────┐
    │ trade_date               │ 交易日                          │
    │ symbol                   │ 股票代码                        │
    │ metric_name              │ 被验证的字段名                  │
    │ source_a_name            │ 源 A 名称（如 'eastmoney'）     │
    │ source_a_val             │ 源 A 归一化值                   │
    │ source_a_unit (P2)       │ 源 A 原始单位                   │
    │ source_b_name            │ 源 B 名称（如 'sina'）          │
    │ source_b_val             │ 源 B 归一化值                   │
    │ source_b_unit (P2)       │ 源 B 原始单位                   │
    │ source_c_name            │ 源 C 名称（可选）               │
    │ source_c_val             │ 源 C 归一化值（可选）            │
    │ source_c_unit (P2)       │ 源 C 原始单位（可选）           │
    │ diff_ab                  │ A↔B 差异百分比                  │
    │ diff_ac                  │ A↔C 差异百分比（可选）           │
    │ diff_bc                  │ B↔C 差异百分比（可选）           │
    │ threshold_pct            │ 使用的阈值（0.3%）              │
    │ verdict                  │ PASS/PASS_WITH_NOTE/REPORT/     │
    │                          │   UNIT_ERROR                    │
    │ diff_reason              │ 枚举化差异原因                   │
    │ minute_data_source (P2)  │ 分钟聚合的源标识（可选）        │
    │ rule_version             │ E-001 规则版本哈希              │
    │ triggered_at             │ 验证发生时间戳                  │
    └──────────────────────────┴─────────────────────────────────┘
    """
    entry = {
        'trade_date': input.trade_date,
        'symbol': input.symbol,
        'metric_name': input.field_name,
        'source_a_name': input.source_a.source_name,
        'source_a_val': input.source_a.value,
        'source_b_name': input.source_b.source_name,
        'source_b_val': input.source_b.value,
        'diff_ab': diff_ab,
        'diff_ac': diff_ac,
        'diff_bc': diff_bc,
        'threshold_pct': THRESHOLD_PCT,
        'verdict': verdict,
        'diff_reason': diff_reason,
        'rule_version': _get_rule_version(),  # git commit sha
        'triggered_at': _now_iso8601(),
    }

    # 可选第三源
    if input.source_c is not None:
        entry['source_c_name'] = input.source_c.source_name
        entry['source_c_val'] = input.source_c.value

    # P2 字段：unit 系列（本版本可延后）
    # entry['source_a_unit'] = input.source_a.unit
    # entry['source_b_unit'] = input.source_b.unit
    # entry['source_c_unit'] = input.source_c.unit if input.source_c else None

    return entry
```

### 2.7 Step 6 — 违规不阻断

```python
def apply_validation_result(
    result: ValidationResult,
    staging_raw_table: str,
    main_table: str
) -> None:
    """
    将验证结果应用到数据库中
    ┌─────────────────────────────────────────────────────────┐
    │ 核心原则：                                              │
    │   ✓ 数据未通过验证 → 写入 staging_raw（保留原始记录）   │
    │   ✓ 主表对应字段写入 NULL                               │
    │   ✓ 不阻塞 pipeline 继续执行                            │
    │   ✓ 审计日志独立写入 validation_audit_log 表            │
    └─────────────────────────────────────────────────────────┘

    写入策略：
        verdict=PASS        → 直接写入主表，跳过 staging_raw
        verdict=PASS_WITH_NOTE → 写入主表（含 diff_reason），写入审计日志
        verdict=REPORT      → 写入 staging_raw，主表字段 NULL
        verdict=UNIT_ERROR  → 写入 staging_raw，主表字段 NULL，标记 UNIT_ERROR
    """

    # 写审计日志（总是执行）
    _write_audit_log(result.audit_entry)

    if result.verdict in ('REPORT', 'UNIT_ERROR'):
        # ⚠️ 违规不阻断：
        #   1. 完整原始记录写入 staging_raw
        #   2. 主表对应字段写 NULL
        #   3. pipeline 继续运行
        _write_staging_raw(
            table=staging_raw_table,
            record=result.audit_entry,
            raw_values=_collect_raw_values(result)
        )
        _write_main_table_with_null(main_table, result.audit_entry)
        _notify_owner_if_report(result)
    else:
        # PASS / PASS_WITH_NOTE → 写入主表
        _write_main_table(
            table=main_table,
            symbol=result.audit_entry['symbol'],
            trade_date=result.audit_entry['trade_date'],
            field_name=result.audit_entry['metric_name'],
            value=result.selected_value,
            diff_reason=result.diff_reason
        )
```

---

## 3. 辅助函数

```python
def _normalize_identity_fields(input: ValidationInput) -> ValidationInput:
    """
    身份标识字段归一化处理
    ┌─────────────────────────────────────────────────────────┐
    │ 在交叉验证前统一 trade_date 和 symbol 的格式：         │
    │   1. 日期格式统一: 支持 '2026-05-20', '2026/05/20',    │
    │      '20260520' → 统一为 ISO 格式 '2026-05-20'         │
    │   2. 代码格式统一: 带市场前缀与纯代码归一化            │
    │      '601857.SH' → '601857', '600001' → '600001'       │
    │   3. 跨源日期一致性检查: 通过审计日志记录差异          │
    └─────────────────────────────────────────────────────────┘
    """
    # 日期格式归一化
    input.trade_date = _normalize_date_str(input.trade_date)
    # 代码格式归一化（去市场前缀）
    input.symbol = _normalize_symbol_str(input.symbol)
    return input


def _normalize_date_str(date_str: str) -> str:
    """支持多种日期格式转 ISO: 2026-05-20 / 2026/05/20 / 20260520"""
    import re
    patterns = [
        (r'^(\d{4})-(\d{2})-(\d{2})$', '{:04d}-{:02d}-{:02d}'),
        (r'^(\d{4})/(\d{2})/(\d{2})$', '{:04d}-{:02d}-{:02d}'),
        (r'^(\d{4})(\d{2})(\d{2})$', '{:04d}-{:02d}-{:02d}'),
    ]
    for pattern, fmt in patterns:
        m = re.match(pattern, date_str)
        if m:
            return fmt.format(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return date_str  # 无法解析则原样返回


def _normalize_symbol_str(symbol: str) -> str:
    """去市场前缀归一化: 601857.SH → 601857"""
    import re
    m = re.match(r'^(\d{6})(\.[A-Z]{2,3})?$', symbol)
    if m:
        return m.group(1)  # 返回纯代码
    return symbol


# ─── diff_reason 模式判定函数 ─────────────────────────
# Phase 1 实现: UNIT_CONVERTED, OTHER
# Phase 2 实现: SPLIT_DIFF, DIVIDEND_ADJUSTED, AFTER_HOUR_TRADE, DELAYED_SOURCE


def _pattern_unit_conversion(
    val_a: float, val_b: float, val_c: float | None,
    diff_ab: float, diff_ac: float | None, diff_bc: float | None,
    source_a: SourceValue, source_b: SourceValue, source_c: SourceValue | None
) -> bool:
    """
    判定是否为单位转换导致的差异 (UNIT_CONVERTED)
    ┌─────────────────────────────────────────────────────────┐
    │ 特征：                                                 │
    │   A↔B 差异大 (通常 > 0.3%) 但 A↔C 或 B↔C 差异小       │
    │   且 A 或 B 的 unit 与标准单位不同                     │
    │   → 说明差异来自单位未归一化，而非数据错误             │
    │                                                        │
    │ Phase 1 判定逻辑：                                     │
    │   1. diff_ab > THRESHOLD_PCT (有差异)                  │
    │   2. 有源 C 且 diff_ac ≤ THRESHOLD_PCT 或             │
    │      diff_bc ≤ THRESHOLD_PCT (源 C 与一方一致)        │
    │   3. 源 A 或源 B 的 unit 不是标准单位                  │
    │      (说明差异来自单位换算不完整)                      │
    └─────────────────────────────────────────────────────────┘
    """
    # 条件 1: A↔B 确实有差异
    if diff_ab <= THRESHOLD_PCT:
        return False

    # 条件 2: 有第三源且与一方一致
    if source_c is not None and val_c is not None:
        if diff_ac is not None and diff_ac <= THRESHOLD_PCT:
            # A 与 C 一致 → 可能是 B 的单位问题
            return source_b.unit != 'shares' and source_b.unit != 'yuan'
        if diff_bc is not None and diff_bc <= THRESHOLD_PCT:
            # B 与 C 一致 → 可能是 A 的单位问题
            return source_a.unit != 'shares' and source_a.unit != 'yuan'

    # 条件 3: 仅有双源，但单位不标准
    if source_c is None:
        non_standard = (
            (source_a.unit not in ('shares', 'yuan', '') and source_a.unit is not None) or
            (source_b.unit not in ('shares', 'yuan', '') and source_b.unit is not None)
        )
        if non_standard:
            return True

    return False


def _pattern_after_hour(
    val_a: float, val_b: float, val_c: float | None,
    diff_ab: float, diff_ac: float | None, diff_bc: float | None
) -> bool:
    """
    判定是否为盘后交易差异 (AFTER_HOUR_TRADE) — Phase 2
    ┌─────────────────────────────────────────────────────────┐
    │ Phase 2 实现，当前直接返回 False。                     │
    │ 预期判定逻辑：                                         │
    │   1. 差异出现在收盘价字段 (close)                      │
    │   2. 差异模式: 一个源含盘后数据（价格偏移 1~5%）      │
    │   3. 检查分钟数据中最后一笔的时间戳                   │
    │   4. 如果不在标准收盘时段内 → 盘后交易                 │
    └─────────────────────────────────────────────────────────┘
    """
    # Phase 2 TODO
    return False


def _pattern_delayed(
    val_a: float, val_b: float, val_c: float | None,
    diff_ab: float, diff_ac: float | None, diff_bc: float | None
) -> bool:
    """
    判定是否为数据源延迟差异 (DELAYED_SOURCE) — Phase 2
    ┌─────────────────────────────────────────────────────────┐
    │ Phase 2 实现，当前直接返回 False。                     │
    │ 预期判定逻辑：                                         │
    │   1. 日期对齐后发现一个源的数据滞后                    │
    │      (如盘后数据更新批次不同)                          │
    │   2. 检查数据源的元数据中的 update_time                │
    │   3. 如果滞后超过阈值 → DELAYED_SOURCE                 │
    └─────────────────────────────────────────────────────────┘
    """
    # Phase 2 TODO
    return False


def _normalize_to_standard_unit(source: SourceValue) -> float:
    """
    将源值转换为标准单位
    标准单位定义（来自映射表 YAML）：
        volume → 'shares'        # 统一为 股
        amount → 'yuan'          # 统一为 元
        price  → 'yuan_per_share' # 统一为 元/股
    """
    conversion_map = _load_unit_conversion_map()
    standard_unit = conversion_map.get_standard_unit(source.field_name)
    conversion_ratio = conversion_map.get_conversion_ratio(
        source.unit, standard_unit
    )
    if conversion_ratio is not None and conversion_ratio != 1.0:
        return source.value * conversion_ratio
    return source.value


def _approx(value: float, target: float, tolerance: float = 0.15) -> bool:
    """判断 value 是否约等于 target，容差 tolerance（15% 默认）"""
    if value == 0:
        return target == 0
    return abs(value - target) / max(abs(value), abs(target)) <= tolerance


def _safe_divide(a: float, b: float) -> float | None:
    """安全除法，避免 ZeroDivisionError"""
    if b == 0:
        return None
    return a / b


def _load_unit_conversion_map() -> UnitConversionMap:
    """
    从 YAML 配置加载单位映射表
    配置路径: config/unit_conversion_map.yaml
    格式示例:
        units:
          - name: 'shares'
            aliases: ['股', 'share', 'stock']
            base_unit: 'shares'
          - name: 'lots'
            aliases: ['手', 'lot', 'board_lot']
            base_unit: 'shares'
            to_base_ratio: 100
          - name: 'yuan'
            aliases: ['元', 'CNY']
            base_unit: 'yuan'
          - name: 'fens'
            aliases: ['分', 'fen']
            base_unit: 'yuan'
            to_base_ratio: 0.01
        field_defaults:
          volume:
            standard_unit: 'shares'
          amount:
            standard_unit: 'yuan'
    """
    pass  # 实现从 YAML 加载


def _select_best_pair(passing_pairs: list) -> Pair:
    """
    从多个通过的配对中选择最优的
    规则：
        如果有 2 个源一致（A=B 或 A=C 或 B=C），选该配对
        如果全部一致，任选
    """
    return passing_pairs[0]  # 简化为第一对


def _now_iso8601() -> str:
    """返回当前时间 (ISO8601, +08:00)"""
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat()


def _get_config(key: str, default: Any = None) -> Any:
    """
    从配置系统获取配置值
    配置路径: config/e001_settings.yaml (示例)
    """
    # Phase 1 简化实现：直接返回默认值
    # Phase 2 改为从 YAML 加载
    _config = {
        'minute_data_source_strategy': 'highest_quality',
        'minute_self_consistency_threshold': 0.05,  # 0.05%
    }
    return _config.get(key, default)
```

---

## 4. 测试要点（从墨萱验收红线映射）

| 验收红线 | 对应测试用例 | 函数 |
|:---------|:------------|:-----|
| E.02-001 | 两源 ≤ 0.3% → 写入主表 | `cross_source_validate()` |
| E.02-002 | 两源 > 0.3% 无仲裁 → staging_raw | `_third_source_arbitration()` |
| E.02-003 | 两源 > 0.3% 有枚举理由 → PASS_WITH_NOTE | `_third_source_arbitration()` |
| E.01-001 | 单位异常（手vs股）→ UNIT_ERROR | `_check_unit_mismatch()` |
| E.03-001 | 源不可用 → 不阻塞 | `apply_validation_result()` |
| E.04-001 | 每次验证生成审计记录 | `_build_audit_entry()` |

---

## 5. 边界情况汇总

| 场景 | 预期行为 | 涉及 Step |
|:-----|:---------|:----------|
| 两源完全一致 | PASS，不记日志 | Step 2 |
| 两源差异 > 0.3% + 第三源仲裁成功 | PASS_WITH_NOTE，记审计 | Step 2 → Step 3 |
| 两源差异 > 0.3% + 无第三源 | 尝试分钟聚合，失败则 REPORT | Step 2 → Step 3 → Step 4 |
| 两源单位差异 ~100x | 阻断: UNIT_ERROR | Step 1 |
| 分钟聚合与某源一致 | 以该源为准: AGGREGATION_ANCHOR | Step 4 |
| 所有仲裁均失败 | REPORT（向主人报告） | Step 3/4 → Step 5 |
| 主表对应字段写入 NULL | staging_raw 保原始值，pipeline 继续 | Step 6 |
