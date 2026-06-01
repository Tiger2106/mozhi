# WI 4：补充集成验证（四级验证体系前两级）— P0 拆解方案

> **编写人**: 墨衡 (moheng)
> **创建时间**: 2026-06-01T16:06+08:00
> **关联任务**: verify_next_steps_20260601.md → WI 4
> **优先等级**: P0 (验证体系完整性阻塞项)
> **预计整体耗时**: L (90–240 min)

---

## 一、现状快照（截至 2026-06-01）

### 1.1 已有基础设施

| 项目 | 版本 | 用途 |
|:----|:----|:-----|
| Python | 3.14.3 | 运行环境 |
| pytest | 9.0.3 | 测试框架 |
| pytest-cov | 7.1.0 | 覆盖率 |
| numpy | 2.4.4 | 数值计算 |
| pandas | 3.0.1 | 数据操作 |
| scipy | 1.17.1 | 统计计算 |
| a50_ic.db | — | 回测结果 DB (含 `a50_cross_ic_result` 表) |

### 1.2 可复用框架参考

| 框架 | 路径 | 核心模式 | 可复用组件 |
|:----|:----|:---------|:----------|
| **VERIFY-001** | `workspace-mochen/verify_001/tests/` | conftest.py + test_*.py | pytest 配置模式、断言风格 |
| **VERIFY-002** | `mo_zhi_sharereports/verify_002/tests/` | mock DB (tmp_path + sqlite3) | DB fixture 双模式 |
| **VERIFY-003** | `verify_003/tests/` | 真实 DB + conftest 封装 | DB 连接 fixture、IC 校验模式 |

### 1.3 资源约束

| 指标 | 值 |
|:----|:----:|
| 总内存 | ~15.6 GB |
| 当前可用 | ~2.4 GB |
| OS | Windows 10.0.26200 x64 |
| 黄金样本存储 | `mo_zhi_sharereports/verify_golden/` 目录新分配 |

---

## 二、子任务拆解

```yaml
task_id: wi4_integration_verification
task_level: L(90-240min)  # 3黄金样本 + 5+条校验规则 + 管线编排 + 集成测试
memory_requirement: L  # 按新协议：涉及pytest运行、DB操作、样本比对，但可串行化不超常驻
```

### 任务一览

| # | 子任务 ID | 描述 | 预估耗时 | 前置依赖 | 执行人 | 内存需求 |
|:-:|:----------|:-----|:--------:|:--------:|:------:|:--------:|
| 1 | `wi4_golden_select` | 选取 3 个黄金样本（已知输入→已知输�?) | 15min | [] | 墨衡 | S |
| 2 | `wi4_golden_fixtures` | 将黄金样本转化为可复用的测试 fixture（固定输入参数 + 预期输出 JSON） | 15min | wi4_golden_select | 墨衡 | M |
| 3 | `wi4_conftest_dual_db` | 创建 conftest.py，提供双模式 DB fixture（mock DB 用于 CI / 真实 DB 用于本地调试） | 10min | wi4_golden_fixtures | 墨衡 | S |
| 4 | `wi4_test_e2e_golden` | 编写 test_e2e_golden.py，自动化执行 3 个黄金样本的回测并比对输出 | 15min | wi4_golden_fixtures, wi4_conftest_dual_db | 墨衡 | M |
| 5 | `wi4_validation_rule_def` | 定义 ≥5 条输出合理性校验规则，撰写规则文档 → `verify_validation_rules.md` | 15min | [] | 墨衡 | S |
| 6 | `wi4_test_output_checks` | 编写 test_output_validation.py，实现 ≥5 条校验规则（收益率范围、持仓和=1、换手率非负、IC 值范围、空值率检查） | 15min | wi4_conftest_dual_db, wi4_validation_rule_def | 墨衡 | M |
| 7 | `wi4_orchestrator` | 编写可复用验证管线编排脚本 `run_verify_pipeline.py`（支持两级串联/独立运行） | 15min | wi4_test_e2e_golden, wi4_test_output_checks | 墨衡 | M |
| 8 | `wi4_failure_block` | 实现校验失败阻断逻辑：输出校验失败→标记异常（写入 signals/alert/）+ 阻断下游流转（清 .done 或写 .failed 信号） | 10min | wi4_orchestrator | 墨衡 | S |
| 9 | `wi4_integration_test` | 点集成测试：运行完整验证管线（两级串联），确认 3 个黄金样本全通过 + 故意引入错误验证阻断生效 | 15min | wi4_orchestrator, wi4_failure_block | 墨衡 | M |
| 10 | `wi4_doc` | 编写 `docs/verify_pipeline_manual.md`，包含运行方式、添加新样本步骤、规则扩展指南、故障排查 | 10min | wi4_integration_test | 墨衡 | S |

---

## 三、子任务详细设计

### 3.1 wi4_golden_select — 黄金样本选取

**描述**:
从历史回测运行记录中选取 3 个"黄金样本"——有明确、可重现的输入参数，且预期输出已知、无歧义的场景。

**选取标准**:
- 样本 1 — **典型牛市场景**: 选取趋势明显、IC 正值稳定的时段 (如 2024-09 ~ 2024-10)。预期：胜率高、换手率适中
- 样本 2 — **震荡/中性场景**: 选取盘整时段 (如 2025-03 ~ 2025-04)。预期：IC 接近零、换手率低
- 样本 3 — **极端波动场景**: 选取大幅回撤或急涨时段 (如 2024-01 ~ 2024-02 或 2025-04 关税冲击)。预期：换手率飙升、IC 剧烈变化

**产出**:
```json
// verify_golden/golden_samples.json
{
  "samples": [
    {
      "id": "gs_bull_202409",
      "description": "2024-09 至 2024-10 典型上升趋势",
      "input": { "start_date": "2024-09-01", "end_date": "2024-10-31", "param_set": "default" },
      "expected_output": {
        "ic_mean_threshold": [0.01, 0.15],
        "turnover_threshold": [0.05, 0.4],
        "win_rate_threshold": [0.5, 0.85]
      }
    },
    ...
  ]
}
```

**验收标准**:
- 3 个样本覆盖回测典型场景谱
- 每个样本有可执行的输入参数和可观测的预期输出范围

---

### 3.2 wi4_golden_fixtures — 黄金样本 Fixture 封装

**描述**:
将 `golden_samples.json` 转化为 pytest fixture，在 `conftest.py` 中注册。每个样本作为 parametrize 参数，可在测试函数中直接使用。

**产出**:
- `verify_golden/conftest.py` — 注册 `golden_samples` fixture
- `verify_golden/golden_samples.json` — 补充预期输出阈值的详细数值

**验收标准**:
```python
# 测试中可直接使用
def test_e2e_golden(golden_sample):
    result = run_backtest(golden_sample.input)
    assert golden_sample.expected_output.ic_mean_low <= calc_ic_mean(result) <= golden_sample.expected_output.ic_mean_high
```

---

### 3.3 wi4_conftest_dual_db — 双模式 DB Fixture

**描述**:
创建 `verify_golden/conftest.py`（或扩展已有 conftest）提供双模式 DB fixture：
- **mock 模式**（默认）：使用 tmp_path + sqlite3 创建临时 DB，预填充黄金样本的预期输出
- **真实模式**（环境变量 `VERIFY_DB_REAL=1`）：直接连接 `a50_ic.db`

**参考**: VERIFY-002 (mock DB) + VERIFY-003 (真实 DB) fixture 模式。

**产出**: `verify_golden/conftest.py`

**验收标准**:
```bash
# mock 模式（默认）
pytest verify_golden/tests/ -q           # 无需真实 DB 即可运行

# 真实模式
$env:VERIFY_DB_REAL=1; pytest verify_golden/tests/ -q   # 连接真实 DB
```

---

### 3.4 wi4_test_e2e_golden — 端到端样本验证脚本

**描述**:
编写 `test_e2e_golden.py`，对 3 个黄金样本执行端到端回测并核对输出：
1. 载入黄金样本 fixture（输入参数 + 预期输出范围）
2. 调用回测核心函数 / 脚本（从 DB 读取数据 → 运行因子计算 → 写入结果表）
3. 从 DB 或日志中提取关键输出指标
4. 断言：输出落在预期范围内

**产出**: `verify_golden/tests/test_e2e_golden.py`

**验收标准**:
```bash
pytest verify_golden/tests/test_e2e_golden.py -v
# 输出: 3/3 PASSED（每个黄金样本 1 个测试实例）
```

---

### 3.5 wi4_validation_rule_def — 校验规则定义

**描述**:
定义 ≥5 条输出合理性校验规则，编写独立文档 `verify_validation_rules.md`。

**规则清单（建议 ≥7 条）**:

| # | 规则名 | 校验逻辑 | 阈值 | 违反后果 |
|:-:|:-------|:---------|:----|:---------|
| 1 | `ic_range` | 个股 IC 值在 [-1.0, 1.0] 范围内 | -1.0 ≤ IC ≤ 1.0 | 标记异常 |
| 2 | `position_sum` | 持仓比例之和为 1（±容忍误差） | sum(position) = 1.0 ± 1e-6 | 阻断下游 |
| 3 | `turnover_nonneg` | 换手率 ≥ 0 | turnover ≥ 0 | 标记异常 |
| 4 | `return_rate_range` | 收益率在合理范围内（过滤极端离群值） | -0.15 ≤ daily_return ≤ 0.15 | 标记异常 |
| 5 | `null_rate` | IC 结果表中关键字段空值率 < 阈值 | null_rate < 0.2 (20%) | 阻断下游 |
| 6 | `row_count_sanity` | 输出行数在合理范围内（与输入周期匹配） | actual_rows / expected_rows ≥ 0.8 | 标记异常 |
| 7 | `factor_enabled` | 配置中激活的因子在结果表中均有非空值 | enabled_factor ∈ result_columns | 阻断下游 |

**产出**: `verify_golden/verify_validation_rules.md`

**验收标准**:
- ≥7 条规则，每条包含：规则名、校验逻辑、阈值、违反后果
- 规则可被测试脚本直接引用（枚举或配置化）

---

### 3.6 wi4_test_output_checks — 输出校验脚本

**描述**:
编写 `test_output_validation.py`，实现 §3.5 中定义的 ≥5 条合理性校验规则：

```python
# 每条规则一个测试函数，使用 conftest 中的 DB fixture
def test_ic_range(db_cursor):
    rows = db_cursor.execute("SELECT ic FROM a50_cross_ic_result").fetchall()
    for row in rows:
        assert -1.0 <= row[0] <= 1.0, f"IC out of range: {row[0]}"

def test_position_sum(db_cursor):
    ...

def test_turnover_nonneg(db_cursor):
    ...

def test_return_rate_range(db_cursor):
    ...

def test_null_rate(db_cursor):
    ...
```

**产出**: `verify_golden/tests/test_output_validation.py`

**验收标准**:
```bash
pytest verify_golden/tests/test_output_validation.py -v
# ≥5 个测试，每个对应一条校验规则
```

---

### 3.7 wi4_orchestrator — 验证管线编排脚本

**描述**:
编写 `run_verify_pipeline.py`，提供两级验证的可复用编排：

```python
# run_verify_pipeline.py
# 功能：
# --mode=e2e       仅运行端到端样本验证（第一级）
# --mode=output    仅运行输出校验（第二级）
# --mode=full      串联运行两级（默认）
# --mode=full-stop 串联运行，第一级失败则跳过第二级
#
# 退出码：
# 0 = 全部通过
# 1 = 至少一个警告（WARN）
# 2 = 至少一个失败（FAIL）
```

**产出**: `verify_golden/run_verify_pipeline.py`

**验收标准**:
```bash
# 串联运行
python verify_golden/run_verify_pipeline.py --mode=full
# 返回退出码 0（全部通过）

# 仅运行输出校验
python verify_golden/run_verify_pipeline.py --mode=output
```

---

### 3.8 wi4_failure_block — 校验失败阻断逻辑

**描述**:
实现阻断逻辑——当输出校验失败时自动标记异常并阻断下游流转。

**机制**:
1. `run_verify_pipeline.py` 捕获 pytest 结果
2. 如果有任何 FAIL（退出码 ≥2）：
   - 写入 `signals/alert/verify_fail_{timestamp}.json`，含失败详情
   - 写入 `signals/tasks/{task_id}_moheng.failed`（阻断下游）
   - **清除**对应 task 的 `.done` 信号（如果存在）
3. 如果有 WARN（退出码 =1）：
   - 写入 `signals/alert/verify_warn_{timestamp}.json`
   - 不阻断，但记录警告日志

**产出**: `verify_golden/run_verify_pipeline.py`（扩展）

**验收标准**:
```bash
# 故意引入错误后运行
python verify_golden/run_verify_pipeline.py
# 确认 signals/alert/ 下生成了 verify_fail_*.json
# 确认信号文件存在
```

---

### 3.9 wi4_integration_test — 全量集成测试

**描述**:
对验证管线执行全量集成测试：
1. **正向测试**: 运行 `--mode=full`，3 个黄金样本全通过 + 5+ 条校验规则全通过
2. **反向测试**: 故意修改黄金样本的预期输出范围（如设 IC 范围过窄），验证阻断生效
3. **独立测试**: `--mode=e2e` 和 `--mode=output` 独立运行验证通过

**产出**: `verify_golden/tests/test_integration.py`

**验收标准**:
```bash
# 正向
python verify_golden/run_verify_pipeline.py --mode=full
# → exit code 0, all PASS

# 反向（需要手动触发一次失败场景）
python verify_golden/run_verify_pipeline.py --mode=output --force-bad-sample
# → exit code ≥2, alert file created
```

---

### 3.10 wi4_doc — 操作文档

**描述**:
编写 `docs/verify_pipeline_manual.md`，覆盖：
1. 运行方式：串联 (`--mode=full`) / 独立 (`--mode=e2e` / `--mode=output`)
2. 如何添加新的黄金样本
3. 校验规则扩展指南（添加新规则步骤）
4. 黄金样本存放格式说明
5. 告警处理流程
6. 故障排查 FAQ

**产出**: `verify_golden/docs/verify_pipeline_manual.md`

**验收标准**:
- 文档覆盖 3 种运行方式
- 文档包含新样本添加步骤（≥3 步）
- 文档包含常见问题排查

---

## 四、依赖关系图

```
第1阶段 [独立可并行]
  wi4_golden_select ────────────────────→ wi4_golden_fixtures
                                                │
                                                ├─→ wi4_conftest_dual_db
                                                │         │
                                                │         └─→ wi4_test_e2e_golden
                                                │               │
  wi4_validation_rule_def ────────────────────────────→ wi4_test_output_checks
                                                              │
第2阶段 [合并管线]                                          │
  wi4_test_e2e_golden ───────────────────────────────────────┤
                                                            ├─→ wi4_orchestrator ─→ wi4_failure_block
  wi4_test_output_checks ────────────────────────────────────┘                         │
                                                                                       └─→ wi4_integration_test
                                                                                              │
                                                                                              └─→ wi4_doc
```

---

## 五、交付物清单

| # | 交付物 | 文件路径 | 责任人 |
|:-:|:-------|:---------|:------:|
| 1 | 黄金样本定义 (JSON) | `verify_golden/golden_samples.json` | 墨衡 |
| 2 | 黄金样本 Fixture + DB fixture | `verify_golden/conftest.py` | 墨衡 |
| 3 | 端到端验证脚本 | `verify_golden/tests/test_e2e_golden.py` | 墨衡 |
| 4 | 校验规则文档 | `verify_golden/verify_validation_rules.md` | 墨衡 |
| 5 | 输出校验脚本 | `verify_golden/tests/test_output_validation.py` | 墨衡 |
| 6 | 验证管线编排脚本 | `verify_golden/run_verify_pipeline.py` | 墨衡 |
| 7 | 阻断信号 (由编排脚本触发) | `signals/alert/verify_*.json` | 墨衡 |
| 8 | 全量集成测试 | `verify_golden/tests/test_integration.py` | 墨衡 |
| 9 | 操作文档 | `verify_golden/docs/verify_pipeline_manual.md` | 墨衡 |

---

## 六、风险登记册

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:----:|:---------|
| 黄金样本选取困难（历史回测无稳定重现性） | 中 | 第一级验证不可靠 | 选取多时段 + 参数固定 + 预期输出设为范围而非精确值；接受 80% 相似度 |
| 回测核心函数接口不透明（难以直接调用） | 中 | 端到端脚本写不出 | 改用 CLI 调用 + DB 读取结果 + 日志解析的"黑盒验证"方式 |
| 真实 DB 与 mock DB 结果不一致 | 低 | 测试误报 | 双模式下对同一黄金样本执行确认比对；差异 ≤1e-6 视为一致 |
| 资源不足导致 pytest 超时 | 低 | 集成测试频繁超时 | 设置 `--timeout=120`，每条规则独立测试防级联失败 |

---

## 七、自检清单

- [x] 子任务拆分完整、边界清晰（10 个子任务）
- [x] 每个子任务 ≤15 分钟
- [x] 所有子任务执行人为墨衡
- [x] 前置依赖已标注（见 §四 依赖图）
- [x] 验收标准明确、可观测
- [x] 交付物路径已指定
- [x] 风险已登记
- [x] 内存需求已标注（整体 L 级）
- [x] 黄金样本 3 个覆盖不同场景
- [x] 校验规则 ≥7 条（要求 ≥5）
- [x] 两级可独立/串联运行
- [x] 失败阻断机制已设计
- [x] 与现有 VERIFY xxx 框架兼容（双模式 DB fixture 复用 VERIFY-002/003 模式）
