# 验证管线操作手册 (Verify Pipeline Manual)

> **用途**：WI4 Golden Sample 验证管线的操作、维护和问题排查指南。
>
> **版本**：v1.0 | **更新日期**：2026-06-01 | **作者**：moheng | **适用管线**：mozhi_platform/verify_golden/

---

## 目录

1. [运行方式](#1-运行方式)
2. [添加新黄金样本](#2-添加新黄金样本)
3. [校验规则扩展指南](#3-校验规则扩展指南)
4. [黄金样本格式说明](#4-黄金样本格式说明)
5. [告警处理流程](#5-告警处理流程)
6. [故障排查](#6-故障排查)

---

## 1. 运行方式

管线支持 **3 种运行模式**，全部通过 `run_verify_pipeline.py` 编排：

### 1.1 模式对比

| 模式 | 命令 | 执行内容 | 适用场景 |
|:----:|:-----|:---------|:---------|
| **e2e** | `--mode=e2e` | 仅端到端样本验证（`test_e2e_golden.py`） | 快速检查回测数据特征是否偏离预期 |
| **output** | `--mode=output` | 仅输出校验（`test_output_validation.py`，7 条规则） | 单独验证输出数据质量 |
| **full** | `--mode=full` | 先 e2e 再 output，两级串联 | CI 全量回归、发版前全面验证 |

### 1.2 命令示例

```bash
# 全量验证（默认）
python verify_golden/run_verify_pipeline.py --mode=full

# 仅端到端样本验证
python verify_golden/run_verify_pipeline.py --mode=e2e

# 仅输出校验
python verify_golden/run_verify_pipeline.py --mode=output
```

### 1.3 退出码含义

| 退出码 | 含义 |
|:------:|:-----|
| `0` | 全部通过（包括 PASS + 跳过） |
| `1` | 至少一个 WARN（不阻断，需人工确认） |
| `2` | 至少一个 FAIL（阻断流水线） |

### 1.4 Mock 模式与真实模式

| 环境变量 | 模式 | 行为 |
|:---------|:-----|:-----|
| 未设置（默认） | **Mock 模式** | 使用临时 mock DB（仅表结构，无真实数据），测试自动 skip 断言，仅验证代码框架和连接正常。适合 CI 快速验证。 |
| `VERIFY_DB_REAL=1` | **真实模式** | 连接 `data/market/a50_ic.db` 真实数据库，执行完整断言验证。适合回归测试和发版前全面检查。 |

```bash
# Mock 模式（默认）
python verify_golden/run_verify_pipeline.py --mode=full

# 真实模式
VERIFY_DB_REAL=1 python verify_golden/run_verify_pipeline.py --mode=full
```

### 1.5 直接使用 pytest

如需精细化控制（如只运行某条规则、verbose 级别等），也可直接调用 pytest：

```bash
# 运行 e2e 样本测试 — mock 模式
pytest verify_golden/tests/test_e2e_golden.py -v

# 运行 e2e 样本测试 — 真实模式
VERIFY_DB_REAL=1 pytest verify_golden/tests/test_e2e_golden.py -v

# 运行所有输出校验规则（7 条）
pytest verify_golden/tests/test_output_validation.py -v

# 运行某一条特定规则
pytest verify_golden/tests/test_output_validation.py::TestOutputValidation::test_ic_range -v

# 运行集成测试（进程级正向验证）
pytest verify_golden/tests/test_integration.py -v
```

### 1.6 输出产物

运行完成后，若存在 WARN 或 FAIL，管线会在 `signals/alert/` 目录下写入信号文件：

```
signals/alert/
├── verify_fail_20260601_162500.json     # FAIL 信号（阻断）
└── verify_warn_20260601_162500.json     # WARN 信号（不阻断）
```

信号文件格式见 [§5 告警处理流程](#5-告警处理流程)。

---

## 2. 添加新黄金样本

黄金样本是用于回归验证的"标准答案"——定义在特定市场环境下，回测结果应满足的指标范围。添加新黄金样本需完成以下 **5 步**：

### 步骤 1：确定场景与标的

明确新样本覆盖的市场环境和标的代码。参考现有分类：

| 已有场景 | 标的代码 |
|:---------|:---------|
| `bull` — 牛市/趋势行情 | 601857.SH |
| `oscillating` — 震荡/无方向行情 | 601857.SH |
| `extreme` — 极端波动行情 | 601857.SH |

如需覆盖新标的（如创业板、科创板）、新市场环境（如下跌势、政策驱动行情）或新的策略参数（如 fast/slow 周期不同），请从这一步开始。

### 步骤 2：选择时间区间

根据场景特征确定起止日期。关键原则：

- **区间要有代表性**：单边趋势区间需确保趋势成立（如 601857.SH 2023.02-10 牛市），震荡区间需价格在无明显方向
- **足够的数据量**：至少 2-3 个月交易数据，避免过短区间统计不稳定
- **必要时标注外部事件**：如"国资委重估主题""俄乌冲突"等

### 步骤 3：回测并计算基准指标

在目标时间段运行回测，从 DB 获取以下关键指标：

```sql
-- 查询 IC 均值和胜率
SELECT
  ROUND(AVG(ic_value), 4) AS ic_mean,
  ROUND(SUM(CASE WHEN ic_value > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS win_rate,
  ROUND(STDDEV(rank_ic), 4) AS turnover_proxy
FROM a50_cross_ic_result
WHERE trade_date BETWEEN '2023-02-01' AND '2023-10-31';
```

基准指标应作为 `expected_output` 的参考值。建议：

- **IC 均值**：以基准值为中心，±0.02~0.04 作为范围
- **胜率**：以基准值为中心，±0.05~0.10 作为范围
- **换手率**：`min` 设为基准值 80%，`max` 设为基准值 150%

### 步骤 4：编写黄金样本条目

编辑 `golden_samples.json`，在 `samples` 数组中追加新对象。

格式示例：

```json
{
  "id": "gs_bear_2025q1",
  "description": "Bear market scenario - sustained downtrend, IC negative, signals largely short-biased",
  "scenario": "bear",
  "market_context": "2025 Q1: ... (此处填写市场背景描述，供后续审计参考)",
  "input": {
    "start_date": "2025-01-01",
    "end_date": "2025-03-31"
  },
  "expected_output": {
    "ic_mean_min": -0.08,
    "ic_mean_max": 0.01,
    "win_rate_min": 0.35,
    "win_rate_max": 0.55,
    "turnover_min": 0.03,
    "turnover_max": 0.25
  },
  "rationale": "Sustained downtrend... (填写预期逻辑推理过程)"
}
```

> **命名规范**：`id` 遵循 `gs_{scenario}_{year}{period}` 格式。`scenario` 用英文单词（bull/oscillating/extreme/bear 等）。

### 步骤 5：验证新样本

1. **mock 模式快速验证代码路径**：

```bash
# 确认新样本 id 出现在测试列表
pytest verify_golden/tests/test_e2e_golden.py -v --collect-only

# 运行 mock 模式
python verify_golden/run_verify_pipeline.py --mode=e2e
```

2. **真实模式完整验证**：

```bash
VERIFY_DB_REAL=1 python verify_golden/run_verify_pipeline.py --mode=e2e
```

确认新样本断言通过后，提交 `golden_samples.json`。

---

## 3. 校验规则扩展指南

当前已定义 7 条规则（`R1~R7`）。添加新规则需修改 **2 个文件**，遵循以下 4 步。

### 步骤 1：在 verify_validation_rules.md 中注册规则

在规则清单表中追加一行，并在"规则详情"部分补充完整定义。规格表字段：

| 列 | 必填 | 说明 |
|:---|:----:|:-----|
| 规则 ID | 是 | 全局唯一，小写 + 下划线，如 `ic_smoothness` |
| 校验逻辑 | 是 | 一句话描述校验目标 |
| 阈值 | 是 | 判定异常的数值边界 |
| 违反后果 | 是 | WARN 或 FAIL |

详情模板：

```markdown
### R8: `rule_id_here`

| 属性 | 内容 |
|:----|:-----|
| **校验逻辑** | ... |
| **阈值** | ... |
| **违反后果** | **WARN/FAIL** — ... |
| **实现参考 (Python)** | ```python
def check_rule_id_here(...):
    ...
``` |
```

### 步骤 2：在 test_output_validation.py 中实现校验函数

在 `TestOutputValidation` 类中新增测试方法：

```python
def test_my_new_rule(self, db_connection):
    """Rule 8: 规则描述"""
    cursor = db_connection.cursor()
    self._has_data(cursor, "相关表名")

    # 查询数据
    rows = cursor.execute("SELECT ... FROM ...").fetchall()

    if not rows:
        pytest.skip("[mock] 无数据，跳过。")

    # 执行校验逻辑
    result = check_my_rule(rows)

    # WARN 级别
    if result.level == "WARN":
        pytest.fail(f"Rule 8 [WARN]: {result.detail}")

    # FAIL 级别
    assert result, f"Rule 8 [FAIL]: {result.detail}"
```

同时在文件顶部的 `RULE_REGISTRY` 字典中注册校验函数引用（如需要外部调度器调用）：

```python
RULE_REGISTRY = {
    ...,
    "my_new_rule": lambda rows: check_my_rule(rows),
}
```

### 步骤 3：选择违反等级

| 等级 | 应用场景 |
|:----:|:---------|
| **WARN** | 数据异常但可能合理（如极端行情导致的 IC 越界），流水线继续 |
| **FAIL** | 确定的数据质量问题（如表结构异常、关键字段全空），流水线阻断 |

### 步骤 4：运行测试确认

```bash
# 单独验证新规则
pytest verify_golden/tests/test_output_validation.py::TestOutputValidation::test_my_new_rule -v

# 全量验证确认
python verify_golden/run_verify_pipeline.py --mode=full
```

---

## 4. 黄金样本格式说明

### 4.1 JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["meta", "samples"],
  "properties": {
    "meta": {
      "type": "object",
      "description": "样本集的元信息，描述生成背景、策略参数和标的",
      "required": [
        "version", "description", "symbol", "strategy",
        "initial_capital", "fee_rate", "slippage_rate",
        "generated_at", "generated_by", "task_id",
        "source_db", "data_coverage"
      ],
      "properties": {
        "version": {
          "type": "string",
          "description": "黄金样本格式版本号",
          "example": "2.0"
        },
        "description": {
          "type": "string",
          "description": "样本集用途描述"
        },
        "symbol": {
          "type": "string",
          "description": "标的代码（如 601857.SH，带市场后缀）"
        },
        "strategy": {
          "type": "object",
          "required": ["type", "params"],
          "properties": {
            "type": { "type": "string", "description": "策略类型，如 ma_cross" },
            "params": {
              "type": "object",
              "description": "策略参数，键值对形式",
              "example": { "fast": 5, "slow": 20 }
            }
          }
        },
        "initial_capital": {
          "type": "number",
          "description": "回测初始资金",
          "example": 1000000.0
        },
        "fee_rate": {
          "type": "number",
          "description": "费率（比例）",
          "example": 0.0003
        },
        "slippage_rate": {
          "type": "number",
          "description": "滑点率（比例）",
          "example": 0.001
        },
        "generated_at": {
          "type": "string",
          "description": "样本生成时间，ISO8601 +08:00",
          "example": "2026-06-01T16:16:00+08:00"
        },
        "generated_by": {
          "type": "string",
          "description": "生成人/系统标识",
          "example": "moheng"
        },
        "task_id": {
          "type": "string",
          "description": "生成任务 ID",
          "example": "wi4_golden_select_moheng"
        },
        "source_db": {
          "type": "string",
          "description": "数据来源（DB 文件或版本）",
          "example": "data/analysis.db.bak.20260525"
        },
        "data_coverage": {
          "type": "string",
          "description": "数据覆盖的时间范围",
          "example": "2020-01-02 to 2026-05-15 (1540 trading days)"
        }
      }
    },
    "samples": {
      "type": "array",
      "description": "黄金样本数组，每个元素定义一种市场场景下的预期指标范围",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": [
          "id", "description", "scenario", "market_context",
          "input", "expected_output", "rationale"
        ],
        "properties": {
          "id": {
            "type": "string",
            "description": "唯一标识符，格式 gs_{scenario}_{year}{period}",
            "example": "gs_bull_2023q2q3"
          },
          "description": {
            "type": "string",
            "description": "单行描述，概括场景和预期"
          },
          "scenario": {
            "type": "string",
            "enum": ["bull", "oscillating", "extreme", "bear", "other"],
            "description": "市场场景分类"
          },
          "market_context": {
            "type": "string",
            "description": "详细的市场背景表述，供后期审计和溯源"
          },
          "input": {
            "type": "object",
            "required": ["start_date", "end_date"],
            "properties": {
              "start_date": {
                "type": "string",
                "format": "date",
                "description": "回测开始日期",
                "example": "2023-02-01"
              },
              "end_date": {
                "type": "string",
                "format": "date",
                "description": "回测结束日期",
                "example": "2023-10-31"
              }
            }
          },
          "expected_output": {
            "type": "object",
            "required": ["ic_mean_min", "ic_mean_max", "win_rate_min", "win_rate_max"],
            "properties": {
              "ic_mean_min":   { "type": "number", "description": "IC 均值下限" },
              "ic_mean_max":   { "type": "number", "description": "IC 均值上限" },
              "win_rate_min":  { "type": "number", "description": "胜率下限" },
              "win_rate_max":  { "type": "number", "description": "胜率上限" },
              "turnover_min":  { "type": "number", "description": "换手率下限" },
              "turnover_max":  { "type": "number", "description": "换手率上限" }
            }
          },
          "rationale": {
            "type": "string",
            "description": "为什么该场景下这些指标范围是合理的？推理过程记录"
          }
        }
      }
    }
  }
}
```

### 4.2 字段详解

#### meta 层

| 字段 | 用途 | 维护方 | 更新频率 |
|:-----|:-----|:-------|:---------|
| `version` | 标记 schema 版本，代码兼容判断 | 核心开发 | 格式变更时 |
| `symbol` | 标的代码，后续扩展多标的时重要 | 样本编写者 | 每次添加新标的 |
| `strategy` | 回测策略参数，确保样本与策略对应 | 策略开发者 | 策略调参时 |
| `generated_at` | 时间戳，用于样本时效性判断 | 自动化 | 自动 |
| `source_db` | 数据源路径/版本，审计溯源关键字段 | 样本编写者 | 每次生成 |

#### samples[] 层

| 字段 | 用途 | 约束 |
|:-----|:-----|:-----|
| `id` | 唯一标识，用于测试参数化 | `gs_` 前缀，全小写 |
| `description` | 快速识别样本 | ≤100 字 |
| `scenario` | 场景分类，未来可用于自动化场景基准 | 推荐预定义值 |
| `market_context` | 市场背景描述，关键审计线索 | 可含数字、事件描述 |
| `input` | 时间范围 | 格式 `YYYY-MM-DD` |
| `expected_output` | 指标范围 | `min` < `max`，类型为 number |
| `rationale` | 推理过程，验证样本逻辑自洽性 | 必须有，不能为空 |

### 4.3 现有样本一览

| id | 场景 | 时段 | IC 均值范围 |
|:---|:-----|:-----|:-----------|
| `gs_bull_2023q2q3` | bull | 2023-02 ~ 2023-10 | [0.04, 0.15] |
| `gs_oscillating_2024h2` | oscillating | 2024-06 ~ 2024-09 | [-0.05, 0.05] |
| `gs_extreme_2021h2_2022q1` | extreme | 2021-08 ~ 2022-03 | [-0.10, 0.06] |

---

## 5. 告警处理流程

### 5.1 信号文件含义

管线运行完成后，若存在 WARN 或 FAIL，自动写入信号文件至 `signals/alert/`。

#### FAIL 信号（阻断）

文件命名：`verify_fail_{ts}.json`，其中 `ts` 格式为 `YYYYMMDD_HHMMSS`。

```json
{
  "timestamp": "2026-06-01T16:25:00+08:00",
  "mode": "full",
  "status": "FAIL",
  "exit_code": 2,
  "details": {
    "passed": 5,
    "failed": 2,
    "warn": 0,
    "errors": [
      "TestOutputValidation::test_position_sum FAIL: Rule 2 [FAIL]: 持仓比例之和偏离 1.0, 详情: ...",
      "TestOutputValidation::test_null_rate FAIL: Rule 5 [FAIL]: 关键字段空值率超标: ..."
    ]
  }
}
```

**含义**：存在严重错误，**阻断流水线**。下游所有依赖该验证结果的任务应停止执行。

#### WARN 信号（不阻断）

文件命名：`verify_warn_{ts}.json`。

```json
{
  "timestamp": "2026-06-01T16:25:00+08:00",
  "mode": "full",
  "status": "WARN",
  "exit_code": 1,
  "details": {
    "passed": 6,
    "failed": 0,
    "warn": 1,
    "errors": [
      "TestOutputValidation::test_ic_range WARN: Rule 1 [WARN]: IC 越界 5 条, 样本: [...]"
    ]
  }
}
```

**含义**：存在异常但**不阻断**流水线。由人工确认后决定是否修复或接受。

### 5.2 信号文件处理步骤

#### 收到 FAIL 信号

| 步骤 | 操作 | 责任方 |
|:----:|:-----|:-------|
| 1 | **确认告警**：读取 `verify_fail_*.json`，确认 fail 的规则和详情 | 值班/当班人员 |
| 2 | **复现问题**：在真实模式下运行对应规则，确认问题是确定性的 | 当班人员 |
| 3 | **分类**：区分"数据源异常"、"计算逻辑 bug"、"黄金样本过时"三类 | 当班人员 |
| 4a | 数据源异常 → 检查 DB 连通性和数据完整性 | 数据运维 |
| 4b | 逻辑 bug → 修复代码后重新验证 | 开发人员 |
| 4c | 样本过时 → 更新 `golden_samples.json` 中的预期范围 | 量化研究员 |
| 5 | **解除阻断**：问题修复后重新运行 `--mode=full`，确认退出码为 0 | 当班人员 |

#### 收到 WARN 信号

| 步骤 | 操作 | 责任方 |
|:----:|:-----|:-------|
| 1 | **查看详情**：读取 `verify_warn_*.json`，确认 warn 的具体条目 | 当班人员 |
| 2 | **评估影响**：判断是否影响后续决策（如只有 1-2 条 IC 越界，通常可接受） | 当班人员 |
| 3 | **决策**：立即修复 / 排入修复计划 / 标记为已知异常 | 当班人员 |
| 4 | **清理**（可选）：手动删除 `verify_warn_*.json` 文件（仅确认已处理） | — |

### 5.3 信号与流水线的交互

```
         run_verify_pipeline.py
                │
       ┌────────┴────────┐
       │ 退出码 == 0     │
       │ → 无信号文件   │  ───── 流水线继续
       └────────┬────────┘
                │
       ┌────────┴────────┐
       │ 退出码 == 1     │
       │ → WARN 信号    │  ───── 流水线继续 + 人工确认
       └────────┬────────┘
                │
       ┌────────┴────────┐
       │ 退出码 == 2     │
       │ → FAIL 信号    │  ───── 流水线阻断 + 人工介入
       └────────┬────────┘
                │
         调度器轮询 signals/alert/
```

### 5.4 信号文件生命周期

| 阶段 | 状态 | 负责人 |
|:-----|:-----|:-------|
| 写入 | 管线自动写入 | 管线编排 |
| 发现 | 调度器/告警监控轮询发现 | 监控系统 |
| 处理中 | 人工确认并处理 | 当班人员 |
| 已解决 | 问题修复后信号文件可从 `signals/alert/` 移除或归档 | 当班人员 |

**清理建议**：问题修复后，建议清理旧的信号文件，避免与新的告警混淆。可使用时间戳区分不同批次的信号。

---

## 6. 故障排查

### Q1: 运行后退出码为 2，但日志显示"全部通过"

**可能原因**：pytest 本身的异常（如 import 错误、fixture 失败）未被正确解析到 junitxml。

**排查步骤**：

1. 直接运行 pytest 查看原始输出：
   ```bash
   pytest verify_golden/tests/test_e2e_golden.py -v 2>&1
   ```
2. 检查是否有 module import 错误或 conftest 加载失败。
3. 检查 `conftest.py` 中 fixture 是否正确（如 `db_connection` 在 mock 模式下能否正常创建 mock DB）。
4. 确认 junitxml 解析逻辑：`run_verify_pipeline.py` 中的 `parse_junit_results` 会将无标记的 failure 作为 FAIL 处理。

### Q2: 在 Mock 模式下所有测试都 skip，无法验证测试本身

**这是正常行为**：Mock 模式下 DB 为空，测试自动跳过断言。Mock 模式的设计目标仅为验证代码框架和测试路径是否正常，不验证数据正确性。

**如果需要完整验证**：

```bash
# 准备真实 DB（需先确保 data/market/a50_ic.db 存在）
VERIFY_DB_REAL=1 python verify_golden/run_verify_pipeline.py --mode=full
```

**如仍需要 Mock 模式下有数据**：可在 `conftest.py` 的 `_setup_mock_schema()` 中添加插入测试数据逻辑。

### Q3: 添加黄金样本后，测试中样本 ID 不出现

**可能原因**：`golden_samples.json` 格式错误，或 `conftest.py` 的加载逻辑未生效。

**排查步骤**：

1. 验证 JSON 格式：
   ```bash
   python -c "import json; json.load(open(r'C:\Users\17699\mozhi_platform\verify_golden\golden_samples.json'))"
   ```
2. 确认 `samples` 数组中新条目包含所有必填字段（`id`, `description`, `scenario`, `input`, `expected_output`, `rationale`）。
3. 查看 pytest 收集到的测试列表：
   ```bash
   pytest verify_golden/tests/test_e2e_golden.py --collect-only -v
   ```
   确认新样本的 id 出现在参数化的测试用例名称中。

### Q4: 添加校验规则后测试不执行

**可能原因**：测试方法未遵循 pytest 命名约定（必须以 `test_` 开头），或未在 `TestOutputValidation` 类内。

**正确命名检查**：

```python
class TestOutputValidation:
    def test_my_new_rule(self, db_connection):  # ✅ 正确
        ...

    def my_rule(self, db_connection):           # ❌ 错误 — 不以 test_ 开头
        ...
```

### Q5: `signals/alert/` 目录未创建信号文件

**可能原因**：管线退出码为 0（全部通过），或 `VERIFY_DIR.parent` 路径解析不符合预期。

**排查步骤**：

1. 确认退出码：
   ```bash
   python verify_golden/run_verify_pipeline.py --mode=full
   echo Exit code: $LASTEXITCODE
   ```
2. 手动触发 FAIL 场景验证写入逻辑：可临时修改一条规则阈值（如将 `ic_range` 的边界改为 [-0.1, 0.1]），再次运行。
3. 检查 `run_verify_pipeline.py` 中 `_write_alert_signal` 的 `alert_dir` 路径计算：
   当前为 `VERIFY_DIR.parent / "signals" / "alert"`，即 `mozhi_platform/signals/alert/`。

---

## 附录 A：文件清单

| 文件 | 用途 | 维护者 |
|:-----|:-----|:-------|
| `run_verify_pipeline.py` | 管线编排脚本 | 核心开发 |
| `golden_samples.json` | 黄金样本定义（JSON） | 量化研究员 |
| `conftest.py` | pytest fixtures（DB 连接、样本加载） | 核心开发 |
| `verify_validation_rules.md` | 校验规则定义文档 | 核心开发 |
| `tests/test_e2e_golden.py` | 端到端样本验证测试 | 核心开发 |
| `tests/test_output_validation.py` | 输出校验测试（7 条规则） | 核心开发 |
| `tests/test_integration.py` | 集成测试（进程级正向验证） | 核心开发 |
| `docs/verify_pipeline_manual.md` | 本手册 | 核心开发 |

---

## 附录 B：版本兼容性

| 手册版本 | 管线版本 | 兼容性 | 说明 |
|:---------|:---------|:-------|:-----|
| v1.0 | v1.0 | 完全兼容 | 初始版本 |

---

*文档结束 — 如有疑问或需要更新，请联系维护者 moheng。*
