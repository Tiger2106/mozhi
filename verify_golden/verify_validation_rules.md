# 输出校验规则 (Validation Rules)

> **用途**：用于 Golden 验证流程中，对回测/分析结果表进行合理性校验。每条规则可由测试脚本按规则 ID 引用执行。
>
> **版本**：v1.0 | **更新日期**：2026-06-01

---

## 规则清单

| # | 规则 ID | 校验逻辑 | 阈值 | 违反后果 |
|:-:|:--------|:---------|:----|:---------|
| 1 | `ic_range` | 个股 IC 值在 [-1.0, 1.0] 范围内 | -1.0 ≤ IC ≤ 1.0 | WARN |
| 2 | `position_sum` | 持仓比例之和为 1（±容忍误差） | sum(position) = 1.0 ± 1e-6 | FAIL |
| 3 | `turnover_nonneg` | 换手率 ≥ 0 | turnover ≥ 0 | WARN |
| 4 | `return_rate_range` | 日收益率在合理范围内 | -0.15 ≤ daily_return ≤ 0.15 | WARN |
| 5 | `null_rate` | 关键字段空值率 < 阈值 | null_rate < 0.2 | FAIL |
| 6 | `row_count_sanity` | 输出行数与输入周期匹配 | actual_rows / expected_rows ≥ 0.8 | WARN |
| 7 | `factor_enabled` | 激活因子在结果表中均有非空值 | enabled_factor ∈ result_columns | FAIL |

---

## 规则详情

### R1: `ic_range`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | 对每期的个股 IC 值（Information Coefficient）检查是否落在 [-1.0, 1.0] 的数学定义区间内。超出该区间的 IC 值表明计算错误或数据异常。 |
| **阈值** | `-1.0 ≤ ic_value ≤ 1.0` |
| **违反后果** | **WARN** — 标记记录，不影响下游流水线执行。由质检人工确认是否为数据源异常。 |
| **实现参考 (SQL)** | ```sql
SELECT period, COUNT(*) AS violations
FROM result_table
WHERE ic_value < -1.0 OR ic_value > 1.0
GROUP BY period
HAVING COUNT(*) > 0;
``` |
| **实现参考 (Python)** | ```python
def check_ic_range(df, ic_col='ic_value', group_col='period'):
    outliers = df[(df[ic_col] < -1.0) | (df[ic_col] > 1.0)]
    if len(outliers) > 0:
        return RuleResult.fail('WARN', outliers)
    return RuleResult.pass_()
``` |

---

### R2: `position_sum`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | 每个持仓期（period）内，所有标的的持仓比例（position_weight）之和应严格等于 1.0。考虑浮点计算误差，容忍 ±1e-6 的偏差。 |
| **阈值** | `|sum(position_weight) - 1.0| ≤ 1e-6` |
| **违反后果** | **FAIL** — 阻断下游流水线。持仓比例之和≠1 表明仓位分配逻辑存在严重错误，可能导致后续收益计算、风险暴露等全部失准。 |
| **实现参考 (SQL)** | ```sql
SELECT period, SUM(position_weight) AS total_weight
FROM result_table
GROUP BY period
HAVING ABS(SUM(position_weight) - 1.0) > 1e-6;
``` |
| **实现参考 (Python)** | ```python
def check_position_sum(df, pos_col='position_weight', group_col='period', eps=1e-6):
    grouped = df.groupby(group_col)[pos_col].sum()
    violations = grouped[abs(grouped - 1.0) > eps]
    if len(violations) > 0:
        return RuleResult.fail('FAIL', violations)
    return RuleResult.pass_()
``` |

---

### R3: `turnover_nonneg`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | 换手率（turnover_rate）为非负值。负换手率在物理意义上不存在，表明计算错误（如分母符号取反、差分方向错误等）。 |
| **阈值** | `turnover_rate ≥ 0` |
| **违反后果** | **WARN** — 标记记录。若仅有极少个例可能是数据噪声，但批量出现需排查周转率计算逻辑。 |
| **实现参考 (SQL)** | ```sql
SELECT COUNT(*) AS negative_turnover_count
FROM result_table
WHERE turnover_rate < 0;
``` |
| **实现参考 (Python)** | ```python
def check_turnover_nonneg(df, turnover_col='turnover_rate'):
    neg = df[df[turnover_col] < 0]
    if len(neg) > 0:
        return RuleResult.fail('WARN', neg)
    return RuleResult.pass_()
``` |

---

### R4: `return_rate_range`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | 单只标的日收益率（daily_return）应在实际市场可观测的合理范围内。A 股主板涨跌幅限制通常为 ±10%，但考虑 ST 板块 ±5%、极端行情、ETF/期货等，放宽至 ±15%。超出此范围的值极大概率指向数据错误（除权除息未处理、数据源异常、计算错误）。 |
| **阈值** | `-0.15 ≤ daily_return ≤ 0.15` |
| **违反后果** | **WARN** — 标记记录。若超出值为除权除息/分红事件导致，需标记为已知例外。 |
| **实现参考 (SQL)** | ```sql
SELECT date, symbol, daily_return
FROM result_table
WHERE daily_return < -0.15 OR daily_return > 0.15;
``` |
| **实现参考 (Python)** | ```python
def check_return_rate_range(df, ret_col='daily_return'):
    outliers = df[(df[ret_col] < -0.15) | (df[ret_col] > 0.15)]
    if len(outliers) > 0:
        return RuleResult.fail('WARN', outliers)
    return RuleResult.pass_()
``` |

---

### R5: `null_rate`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | 对结果表中各关键字段（symbol, daily_return, position_weight, ic_value, turnover_rate 等）逐字段检查空值占比。任一关键字段的空值率 ≥ 20% 即判定为严重数据质量问题。 |
| **阈值** | `null_rate = null_count / total_rows < 0.2` |
| **违反后果** | **FAIL** — 阻断下游流水线。关键字段空值过多意味着数据获取或前处理环节存在系统性问题，下游所有计算均不可信。 |
| **实现参考 (SQL)** | ```sql
SELECT
    column_name,
    COUNT(*) AS total_rows,
    SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) AS null_count,
    ROUND(1.0 * SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS null_rate
FROM result_table
GROUP BY column_name
HAVING ROUND(1.0 * SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) >= 0.2;
``` |
| **实现参考 (Python)** | ```python
def check_null_rate(df, key_columns=None, threshold=0.2):
    if key_columns is None:
        key_columns = ['symbol', 'daily_return', 'position_weight', 'ic_value', 'turnover_rate']
    violations = {}
    for col in key_columns:
        if col in df.columns:
            null_rate = df[col].isnull().mean()
            if null_rate >= threshold:
                violations[col] = null_rate
    if violations:
        return RuleResult.fail('FAIL', violations)
    return RuleResult.pass_()
``` |

---

### R6: `row_count_sanity`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | 结果表的实际行数应与根据输入周期和标的数量推算的预期行数进行比对。预期行数 = 交易日数 × 标的数。实际行数 ≥ 预期行数的 80% 为合理阈值，过低表明数据严重缺失。 |
| **阈值** | `actual_rows / expected_rows ≥ 0.8` |
| **违反后果** | **WARN** — 标记记录。行数过少可能表明数据拉取失败、标的中途退市或回测周期截断。需人工确认是否属于合理缺失。 |
| **实现参考 (SQL)** | ```sql
-- 注：预期行数需由外部传入，SQL 侧仅为行数统计
SELECT COUNT(*) AS actual_rows FROM result_table;
-- 外部比对：actual_rows / expected_rows >= 0.8
``` |
| **实现参考 (Python)** | ```python
def check_row_count_sanity(df, expected_rows, ratio_threshold=0.8):
    actual_rows = len(df)
    ratio = actual_rows / expected_rows if expected_rows > 0 else 0
    if ratio < ratio_threshold:
        return RuleResult.fail('WARN', {
            'actual_rows': actual_rows,
            'expected_rows': expected_rows,
            'ratio': ratio,
            'threshold': ratio_threshold
        })
    return RuleResult.pass_()
``` |

---

### R7: `factor_enabled`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | 配置文件中标记为"激活"（enabled = true）的所有因子，必须在结果表的列集合中全部存在且有非空值。任一激活因子缺失或全部为空值，表明回测结果未正确包含该因子，后续因子分析不可信。 |
| **阈值** | `∀ f ∈ enabled_factors: f ∈ result_columns ∧ result[f] has non-null values` |
| **违反后果** | **FAIL** — 阻断下游流水线。激活因子未被纳入结果表属于配置与执行不一致的严重错误，必须修复后才能继续。 |
| **实现参考 (SQL)** | ```sql
-- 列存在性检查（逐因子执行伪代码模式）
-- 若 parquet / table 结构已定，可直接查询：
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'result_table'
  AND column_name IN ('factor_alpha', 'factor_beta', ...);  -- 需替换为实际因子列表
``` |
| **实现参考 (Python)** | ```python
def check_factor_enabled(df, enabled_factors):
    missing = []
    empty_cols = []
    for factor in enabled_factors:
        if factor not in df.columns:
            missing.append(factor)
        elif df[factor].isnull().all():
            empty_cols.append(factor)
    if missing or empty_cols:
        return RuleResult.fail('FAIL', {
            'missing_columns': missing,
            'empty_columns': empty_cols
        })
    return RuleResult.pass_()
``` |

---

## 附录：测试脚本引用规范

测试脚本通过规则 ID 引用校验函数，统一接口约定如下：

```python
class RuleResult:
    def __init__(self, level: str, detail):
        self.level = level       # 'PASS' | 'WARN' | 'FAIL'
        self.detail = detail     # 详细数据（DataFrame / dict）
        self.rule_id: str = ''
        self.timestamp: str = ''

    @classmethod
    def pass_(cls):
        return cls('PASS', None)

    @classmethod
    def fail(cls, level: str, detail):
        assert level in ('WARN', 'FAIL')
        return cls(level, detail)

# 统一注册映射
RULE_REGISTRY = {
    'ic_range': check_ic_range,
    'position_sum': check_position_sum,
    'turnover_nonneg': check_turnover_nonneg,
    'return_rate_range': check_return_rate_range,
    'null_rate': check_null_rate,
    'row_count_sanity': check_row_count_sanity,
    'factor_enabled': check_factor_enabled,
}
```

---

## 附录：规则违反后果总结

| 等级 | 含义 | 下游行为 |
|:----:|:-----|:---------|
| **PASS** | 校验通过 | 继续执行后续规则 |
| **WARN** | 存在异常但不阻断 | 记录日志 + 问题汇总报告，流水线继续 |
| **FAIL** | 严重错误，不可信 | 立即终止流水线，返回错误详情至调度器 |
