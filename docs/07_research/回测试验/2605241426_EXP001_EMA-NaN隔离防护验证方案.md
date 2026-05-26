# 墨枢研究型回测试验方案：EMA NaN隔离防护验证

> **author:** 墨衡 (deepseek-reasoner)
> **version:** v1.2
> **review_approved_by:** ✅ 全会签二次通过（2026-05-24 19:11）
> - 墨萱（技术签）：✅ PASS
> - 玄知（架构签）：✅ PASS
> - 墨涵（知识签）：✅ PASS
> - **Owner（终签）：✅ 准予执行**
> **版本历史：** v1.0首稿 → v1.1方案评审修改 → v1.1a流程简化(删旧版) → **v1.2退回修复(②③④⑧)**
> **created_time:** 2026-05-24T14:26:00+08:00
> **last_modified:** 2026-05-24T19:07:00+08:00
>
> **试验编号：** `EXP-001`
>
> **设计人：** 墨衡
> **设计日期：** 2026-05-24
> **version_schema：** v2
> **version_content：** 2
> **version_status：** 准予执行
> **关联 signal_defined：** 不适用（本试验为NaN隔离防护验证，不产生signal_defined）

---

## 〇、R001 问题定义（执行前必须通过）

> 依据 R001 规则：任何任务启动前，必须先完成问题定义的团队共识。
> 本节引用今日 Stage 0 R001 讨论会记录（2026-05-24 13:00+08:00，全员参会）。

### 0.1 现状描述（数据/事实，不猜测）

TSI（True Strength Index）因子首次全量回测中，12只大盘标的 × 1210个交易日的结果显示 IC=0。核查发现 TSI 的双 EMA 计算路径存在 NaN 传播：

- 第一层 EMA 接收到 NaN 输入 → NaN 值经 EMA 迭代扩散
- 第二层 EMA 以第一层含 NaN 的输出为输入 → NaN 进一步扩散至整个因子值序列
- 最终 TSI 全部为 NaN，IC 无法计算（统计上为 0）

修复方案已完成：在 4 个 `_ema` 函数（纯 Python 版 × 2 + NumPy 版 × 2）中分别添加 NaN 隔离防护，包含 `dropna()` 过滤 + `min_periods` 参数（参考双EMA窗口和 `r + s - 1 = 37`）。

> **本试验目的：** 系统验证 NaN 隔离防护在所有 NaN 模式下均能正确恢复计算。**这不是一次标准的因子IC/IR检验，而是对EM修复代码正确性的专项验证。**

| 项目 | 内容 |
| --- | --- |
| 标的 | 构造含 NaN 的测试数据集（详见 §2），非全量12只 |
| 时间段 | 单标的验证，无需分阶段 |
| 关键数据 | 4个 `_ema` 函数的输入/输出对比（旧版 vs 新版） |
| 数据来源 | akshare 前复权日线 + 人工插入 NaN |

### 0.2 不解决的后果 + 紧急性

> **如果不做本验证：**
> 1. **修复置信度不足：** `dropna()` + `min_periods=37` 的修复方案虽经单元测试验证，但未在真实含 NaN 的连续数据流中系统检验所有边缘模式（单点/连续/起始/尾部/混合），存在遗漏风险。
> 2. **修复后全量回测可能返回误导结果：** 若修复在不同 NaN 模式下行为不一致（如部分模式下仍产生 NaN 污染），全量回测 IC/IR 结果将被污染，导致"TSI 无效"的错误结论。
> 3. **阻塞 EXP-003（Top5 加权组合）：** EXP-003 的 Top5 加权组合依赖 TSI 作为备选因子之一。若 TSI 因 NaN 问题延迟确认有效性，组合构建的时间线将滑移。

**紧急性：高。** 本验证是 TSI 修复后的第一道门禁，未通过则因子层面的全量回测（原计划 EXP-2026-TSI-001）不应启动。

### 0.3 根因分析（至少追到第三层）

- **第一层（直接原因）：** `TSI = EMA(EMA(price_change, r), s) / EMA(EMA(abs(price_change), r), s)` 中，第一层 EMA 接收 NaN 输入后产生 NaN 输出，第二层 EMA 接收含 NaN 的输出后无法恢复，NaN 沿计算链传播至 TSI 终值。
- **第二层（间接原因）：** EMA 计算函数未对 NaN 输入预设防护。起始行（t=0）缺失历史数据产生 NaN，每层都继承并传播 NaN，缺乏 `dropna()` 和 `min_periods` 约束。
- **第三层（系统性原因）：** 因子计算框架缺少"每层算子自动校验 NaN 隔离"的默认防护层（fence）。回测引擎始终假设输入数据已清洗干净，未对中间计算步骤的 NaN 进行水位标记。该问题与 TSI 因子本身无关——任何涉及多层嵌套 EMA 的因子都可能出现相同问题。

> 已追至可解释极限。第三层的架构问题（`sanitize_layer` 中间层）属于长期改进范围，不在本次修复目标内。

### 0.4 问题陈述（一句话）

> **问题陈述：** 墨枢 TSI 因子在双 EMA 计算路径场景下，因 EMA 函数缺少 NaN 隔离防护（`dropna` + `min_periods` 缺失），导致第一层 NaN 经第二层 EMA 扩散至全因子序列，具体表现为 TSI 全量为 NaN、IC=0、IR 无定义。

### 0.5 通过条件核查

| 条件 | 负责人 | 状态 | 验收人签字/日期 |
| --- | --- | :--: | --- |
| 现状有数据支撑 | 墨衡 | ✅ | Stage 0 已确认 |
| 影响范围和紧急性已评估 | 墨衡 | ✅ | Stage 0 已确认 |
| 根因至少到第三层 | 团队讨论 | ✅ | Stage 0 已确认 |
| 问题陈述全员认可 | 墨涵确认 | ⬜ | 待签字 |
| 写入任务文档 | 墨涵 | ⬜ | 待写入 |

**退回/仲裁流程：**
- 以上任一环节发现不合格 → 退回起草人修改
- 退回最多 2 次，第 3 次仍不合格 → 提交 Owner 裁决
- 裁决结论为"通过"或"终止试验"，不可再退回

---

## 会签记录

| 签署方 | 时间 | verdict |
|:------|:----|:------:|
| 墨萱（技术签） | 2026-05-24 14:41 | ✅ PASS |
| 墨涵（知识签） | 2026-05-24 14:41 | ✅ PASS |
| **Owner（终签）** | **2026-05-24 14:42** | **✅ 准予执行** |

---

## 一、试验背景与核心假设

### 1.1 背景

本试验为 **代码修复验证型试验**，不是标准的因子 IC/IR 有效性检验。

背景：Stage 0 讨论会（R001）已确认 TSI 因子的双 EMA NaN 传播问题为 Bug，修复方案已在 4 个 `_ema` 函数中完成。本试验旨在系统验证该修复在所有 NaN 边缘模式下正确工作，**确保修复代码的完整性**，为后续全量因子回测（EXP-2026-TSI-001）铺平道路。

**不涉及信号生成、参数扫描或策略组合测试。**

### 1.2 核心假设（可证伪）

- **H0（原假设）：** 修复后的 EMA NaN 防护在含 NaN 数据中不能正常恢复计算。
- **H1（备择假设）：** 修复后的 EMA NaN 防护在所有 NaN 模式下（单点/连续/起始/尾部/混合）均能正常恢复计算，且正常段输出与EMA数学公式自洽（偏差 < 1e-10）。

### 1.3 因子体系归属

> 本试验不测试信号生成，仅验证 4 个底层 `_ema` 函数的 NaN 处理行为。

| 函数名 | 层级 | 说明 |
| --- | --- | --- |
| `_ema_py` | 底层算子（纯 Python） | 纯 Python 版的 EMA 实现，NaN 隔离防护 |
| `_ema_py_naive` | 底层算子（纯 Python，朴素版） | 纯 Python 版的简单 EMA 实现，NaN 隔离防护 |
| `_ema_py_full` | 底层算子（纯 Python 全量） | 纯 Python 版 EMA（含 full 输出模式），NaN 隔离防护 |
| `_ema_np` | 底层算子（NumPy） | NumPy 向量化的 EMA 实现，NaN 隔离防护 |
| 执行入口 | `scripts/manual/EXP-001_run.py`（墨衡手动执行） | 本试验不经回测引擎，运行独立验证脚本 |

> 注：`_ema` 函数的注册名无需在 `methods.db` 中存在（本试验不通过回测引擎执行，走独立验证脚本）。

### 1.3.1 函数路径清单

> NaN 隔离防护修复代码位于 `backtest_engine/` 目录下，以下为 4 个 `_ema` 函数的具体路径、模块名和函数签名。

| 函数名 | 文件路径 | 模块名 | 函数签名 |
|:------:|:---------|:-------|:---------|
| `_ema_py` | `C:\Users\17699\mozhi_platform\src\backtest\strategies\factor_calculator.py` | `backtest_engine.strategies.factor_calculator` | `def _ema(values: List[float], period: int) -> List[Optional[float]]` |
| `_ema_py_naive` | `C:\Users\17699\mozhi_platform\src\backtest\strategies\trend_strategy.py` | `backtest_engine.strategies.trend_strategy` | `def _ema(values: List[float], period: int) -> List[Optional[float]]` |
| `_ema_py_full` | `C:\Users\17699\mozhi_platform\scripts\phase1_factor_backfill.py` | —（独立脚本模块） | `def _calc_tsi(closes, long_period=25, short_period=13)` — 双 EMA 全量版，NaN 隔离通过 pandas `dropna() + ewm(min_periods) + reindex` 实现 |
| `_ema_np` | `C:\Users\17699\mozhi_platform\scripts\phase1_factor_backfill.py` | —（独立脚本模块） | `def _calc_ema(values, period)` — NumPy 向量化版，NaN 隔离通过 `first_valid` 定位 + `np.nanmean` 实现 |

> **说明：**
> - `_ema_py` 和 `_ema_py_naive` 位于 `backtest_engine/strategies/` 因子计算管线中，分别服务于 ADX/MACD 等计算路径。
> - `_ema_py_full` 和 `_ema_np` 位于 `scripts/phase1_factor_backfill.py`，分别对应 TSI 双 EMA 全量计算的 pandas 版和 NumPy 底层算子版。
> - 试验脚本 `EXP-001_run.py` 通过 `sys.path.insert` 或相对导入引用上述路径，确保所有 4 个函数可独立调用。

---

## 二、数据与标的定义

### 2.1 标的池（Universe）

> 本试验不需要全量标的。选取 **1只** 代表性大盘标的，获取前复权日线后仅使用 `close` 序列，人工构造含 NaN 的测试向量。

| 项目 | 内容 |
| --- | --- |
| 标的列表 | 601857.SH（中国石油）—— 数据长度充足、波动适中 |
| 排除标准 | 不适用（仅用于构造 NaN 测试序列） |
| free_float 口径 | 不适用（不涉及因子计算、持仓、回测） |
| 复权方式 | akshare 前复权（qfq）—— 仅提取 close 序列 |

### 2.2 数据窗口

> 不进行 Warm-up / IS / OOS 三段划分。仅需要一段足够长度的连续日线数据。

| 阶段 | 开始 | 结束 | 说明 |
| --- | --- | --- | --- |
| 数据获取 | 2023-01-01 | 2025-12-31 | 约 730 交易日，足够构造各种 NaN 模式 |

> **不出具 backtest_run 记录、不写入 validation_check 表。** 本试验的输出是对比报告（新旧版 EMA 输出差异），不是回测结果。

### 2.3 数据质量前置检查

> 本试验为独立脚本验证，不经过回测流水线。前置检查简化为：

```python
# 获取数据后，提取 close 序列，检查：
# 1. 无原生 NaN
# 2. 长度 > 500（保证足够的正常段验证）
# 然后手动插入 NaN 构造测试向量
```

---

## 三、因子配置与控制变量

### 3.1 因子参数

> 本试验不设定 JSON 因子参数。直接以固定参数调用 4 个 `_ema` 函数（路径清单见 §1.3.1）：

- EMA 窗口：`window = 25`（使用 TSI 的 r=25 参数）
- **`min_periods` = 25（所有4个版本统一）**：
  - `_ema_py`（纯Python版，`backtest_engine/strategies/factor_calculator.py`）：min_periods=25
  - `_ema_py_naive`（纯Python版，`backtest_engine/strategies/trend_strategy.py`）：min_periods=25
  - `_ema_py_full`（纯Python全量版，`scripts/phase1_factor_backfill.py` 内 `_calc_tsi`）：min_periods=25（通过 pandas `ewm(min_periods=25)` 实现）
  - `_ema_np`（NumPy向量化版，`scripts/phase1_factor_backfill.py` 内 `_calc_ema`）：min_periods=25（通过 `first_valid + period` 定位实现）
  - 上述取值依据：单层EMA窗口 r=25，要求至少有一个完整窗口的有效值才能生成首个有效输出
- 输入向量：人工构造的含 NaN 测试序列

### 3.2 变量矩阵

**控制变量（恒定）：**

| 变量 | 值 |
| --- | --- |
| EMA 窗口 | 25（固定） |
| 输入序列长度 | 500（固定） |
| 测试模式 | 5种：单点NaN / 连续NaN(2~5个) / 起始NaN / 尾部NaN / 混合NaN |

**自变量（仅1个维度）：**

| 参数名 | 取值范围 |
| --- | --- |
| NaN 模式 | single, consecutive(2~5), leading, trailing, mixed |

> 不扫描常规的因子参数（r/s 等）。本试验的"参数"是 NaN 出现的模式，共 5 种。

### 3.3 A 股硬约束

> **不适用。** 本试验不执行交易模拟，不产生 trade_log，无 A 股硬约束需求。

---

## 四、验收标准：NaN隔离恢复准则

> 本试验不适用 IC/IR 验收体系。本节定义 **7项核心验收标准**（CORE-0~6）。

### 4.1 单因子有效性门槛

> 不适用（本试验非因子IC/IR检验）。

### 4.2 策略组合验收门槛

> 不适用（本试验非策略组合）。

### 4.3 验收标准（本试验专属）

| ID | 标准 | 旧版行为 | 新版要求 | 说明 |
|:--:|:----|:---------|:---------|:-----|
| **CORE-0** | 全 NaN 输入 → 不崩溃 | 全 NaN 输入可能触发除零或索引错误 | 全 NaN 输入后输出全 None/NaN，函数正常返回，不抛出异常 | 鲁棒性边界测试 |
| **CORE-1** | 单点 NaN → 正常恢复 | NaN 经 EMA 传播扩散，影响后续 N 个输出值 | NaN 处标记 NaN/None，后续正常段完全恢复，无传播效应 | 最基础的单点 NaN 隔离 |
| **CORE-2** | 连续 NaN（2~5 个）→ 正常恢复 | NaN 叠加传播，输出段大面积 NaN | 连续 NaN 窗口内输出 NaN/None，窗口结束后正常恢复 | 考察多步 NaN 的累积隔离 |
| **CORE-3** | 正常段输出自洽 | — | 所有非 NaN 输入段，新版 EMA 输出与数学公式一致（偏差 < 1e-10） | 确保正常计算路径正确 |
| **CORE-4** | 起始 NaN → 正常延迟启动 | 起始 NaN 导致后续全 NaN | 输出段从第一个有效输入位置开始延迟 `min_periods` 后正常输出 | 对应 TSI 暖机期场景 |
| **CORE-5** | 尾部 NaN → None 不传染 | 尾部 NaN 后无输出（无影响） | 尾部 NaN 输出 None，不改变已输出的正常段 | 边界完整性验证 |
| **CORE-6** | `len(output) == len(input)` | 输出长度可能不等（如 `reversal_strategy._ema` 在 len<window 时返回空数组） | 输出数组长度必须严格等于输入数组长度 | 索引对齐的基本前提，确保过滤/恢复后的输出能映射回原始索引 |

**附：全 NaN 输入构造（CORE-0）**

> 输入向量全部为 `np.nan`，长度为 500。预期行为：不崩溃、不抛出异常，输出全部为 None/NaN。

**验收判定规则：**

```
CORE-0~6 全部通过 → ✅ PASS（修复代码完整性确认）
CORE-0~6 任一不通过 → ❌ FAIL（修复不完整，退回修复循环）
```

**附加条件：**
- 所有 5 种测试模式**同时验证 4 个 `_ema` 函数版本**
- 每个版本必须独立满足全部 CORE 标准（含 CORE-0 和 CORE-6）
- **4 个 `_ema` 函数版本的 CORE-0~6 通过情况必须完全一致**，如有分歧需查明原因
- 记录所有输入→输出配对，写入对比报告

**NaN 编码统一约定：**

不同 `_ema` 函数版本可能返回不同的 NaN 表示形式：`np.nan`、`None`、`float('nan')` 或 masked array 的 `--`。

> **统一方案：** 对比分析前，所有输出值统一转换为 Python `None`（`None`）。具体实现：
> 1. NumPy 版输出：`[None if v is None or (isinstance(v, float) and np.isnan(v)) else v for v in output]`
> 2. 纯 Python 版输出：`[None if v is None or (isinstance(v, float) and math.isnan(v)) else v for v in output]`
> 3. 对比函数只比较非 None 位置；None 位置不做数值偏差计算
>
> **可行性：完全可行。** 本试验的对比逻辑不依赖 NaN 的具体编码格式，`None` 作为统一中间表示在 Python 层面可以无损转换。

#### 索引对齐规则（CORE-2/4 的补充定义）

连续 NaN（CORE-2）和起始 NaN（CORE-4）场景下，`dropna()` 过滤后的 EMA 输出需要映射回原始索引。定义以下规则：

1. **等长约束：** 所有 4 个函数版本的输出必须满足 `len(output) == len(input)`（CORE-6）。
2. **NaN 位置保留：** 输出数组中，与输入 NaN 位置相对应的输出值必须为 `None`（或 NaN）。
3. **连续 NaN 窗口（CORE-2 增强）：**
   - 设输入序列长度为 N，连续 NaN 区间为 `[s, e)`（s 为起始索引，e 为结束索引索引+1）。
   - 输出数组中 `output[s:e]` 全部为 `None`。
   - `output[e:]` 在完成 `min_periods` 预热后正常恢复计算。
   - 恢复后的有效段索引与原始输入索引保持一致（即：第 e 位输入 → 第 e 位输出）。
4. **起始 NaN 窗口（CORE-4 增强）：**
   - 设输入序列前 k 个值为 NaN，则 `output[0:k]` 全部为 `None`。
   - 第一个有效输入位于索引 k，对应的第一个有效输出位于索引 `k + min_periods - 1`。
   - 即：有效输出的起始位置 = `k + min_periods - 1`，在此之前输出 `None`。
5. **尾部 NaN（CORE-5 增强）：**
   - 输出数组中，与输入尾部 NaN 对应的位置输出 `None`。
   - 已输出的正常段不受影响（索引不变）。

```python
# 索引对齐验证示例（用于 EXP-001_run.py 断言）
def verify_index_alignment(input_arr, output_arr, nan_ranges):
    """
    nan_ranges: List of (start, end) tuples, 例如 [(0,10), (100,105)]
    """
    assert len(output_arr) == len(input_arr), f"CORE-6 FAIL: len(output)={len(output_arr)} != len(input)={len(input_arr)}"
    for s, e in nan_ranges:
        # NaN 区间对应的输出必须为 None
        for i in range(s, e):
            assert output_arr[i] is None, f"CORE-2/4 FAIL: output[{i}] should be None (NaN range [{s},{e}))"
        # NaN 窗口后的第一个有效段索引对齐（由具体实现保证 len 相等即对齐）
```

---

## 五、试验流程

### 执行计划（~1小时40分钟）

```
Step 1  环境准备（10min）
        ↓ 确认当前工作副本为修复后代码（含 4 个 `_ema` NaN 隔离防护）
        ↓ 确认 4 个 `_ema` 函数可独立调用

Step 2  测试数据构造（15min）
        ↓ akshare 获取 601857.SH 前复权日线 close 序列（2023-2025）
        ↓ 取长度 500 的连续序列，确认无原生 NaN
        ↓ 在固定索引位置人工插入 NaN，构造 5 种测试模式：
          - single:    [100] 处单点 NaN
          - consecutive(2~5):  [100,101], [100,101,102], [100,101,102,103], [100,101,102,103,104]
          - leading:   [0:10] 起始段 NaN
          - trailing:  [490:500] 尾部段 NaN
          - mixed:     [100] + [200:203] + [300] 混合模式
        ↓ 保存测试向量（JSON 格式，可复现）

Step 3  新版 _ema 运行（15min）
        ↓ 对每个 NaN 模式，用新版 `_ema` 函数计算输出
        ↓ 记录输出序列

Step 4  对比分析（30min）
        ↓ 逐模式逐函数版本验证 CORE-0~6 通过情况
        ↓ **正常段：新版输出自洽，与 EMA 数学公式一致（偏差 < 1e-10）**
        ↓ **NaN 段：NaN 处输出 None/NaN，有效段正常恢复**
        ↓ **索引对齐：验证 `len(output) == len(input)`（CORE-6），含连续 NaN 和起始 NaN 的对齐规则**
        ↓ **4 版一致性校验：记录每个 `_ema` 函数版本的 CORE-0~6 通过/不通过状态，对比是否完全一致**
        ↓ 记录正常段的 RMSE（偏差 < 1e-10）
        ↓ **NaN 编码统一：4 个版本输出先统一转换为 None 后再做对比分析**

Step 5  报告撰写 + 回归测试套件写入（30min）
        ↓ 生成对比报告（Markdown）：含 RMSE、发现问题、4版一致性结论
        ↓ 输出报告至 `reports/EXP-001/`
        ↓ 将测试向量（5种NaN模式+全NaN输入）保存为 `tests/regression/nan_isolation/test_vectors.json`
        ↓ 将验证脚本封装为独立单元测试：`tests/regression/nan_isolation/test_nan_isolation.py`
        ↓ 测试内容覆盖 CORE-0~6 全部验收标准 + 4版一致性校验 + 索引对齐规则
        ↓ 后续可直接通过 `pytest tests/regression/nan_isolation/` 复现

Step 6.5 回归测试边界覆盖（补充，纳入 test_nan_isolation.py）
        ↓ 在 `test_nan_isolation.py` 中增加 3 个边界测试用例：
          - `test_empty_input`：输入 `[]`，预期不崩溃，返回 `[]`（CORE-0 增强）
          - `test_len_lt_window`：输入 `[1.0]` 或 `[1.0,2.0]`（len < window=25），预期返回全 `None` 列表，长度等于输入长度（CORE-6 验证）
          - `test_len_window_all_nan`：输入 25 个连续 `nan`（len = window），预期不崩溃，返回全 `None` 列表，长度等于 25（CORE-0 + CORE-6 联合验证）
        ↓ 3个边界用例的预期行为：
          - 不抛出异常
          - 输出长度 = 输入长度
          - 输出均为 None/NaN
```

**版本管理：**
- 使用当前工作副本（含 4 个 `_ema` NaN 隔离防护的修复后版本）
- 旧版行为由数学确定性推知（NaN喂给旧版EMA=NaN传染），无需实际运行验证。旧版全量回测结果已保存（Run 1备份），不影响归档

---

## 六、数据库写入规范

### 6.1 backtest_run 入口记录

> **本试验不写入 backtest_run 表。** 本试验为代码验证型，不经回测引擎执行，输出为独立对比报告。

### 6.2 validation_check 命名规范

> **本试验不写入 validation_check 表。** CORE-0~6 的通过/不通过仅记录对比报告中。

### 6.3 废弃结果标记

> 不适用。本试验无废弃结果需要标记。

---

## 七、试验结论与知识沉淀

> 待 Stage 3 会签通过后正式激活，执行完成后填写。

### 7.1 试验结论

- [ ] **CORE-0~6 全部通过（修复代码完整性确认）：** 4 个 `_ema` 函数的 NaN 隔离防护在所有模式下正确工作，可进入全量因子回测（EXP-2026-TSI-001）
- [ ] **CORE-0~6 未全部通过：** 存在 NaN 模式的隔离缺失，退回修复循环

### 7.2 失败根因归因（试验失败时必填）

> 若 CORE-0~6 未全部通过，在此记录未通过的模式及其原因。
> 当前暂未填写。

### 7.3 知识库写入（试验完成后强制执行）

> **变更摘要（v1.1a→v1.2）：** Owner 退回修复，限定范围②③④⑧。①函数修复本体已完成不退回；②§1.3.1 新增函数路径清单；③§4.3 新增索引对齐规则（连续NaN/起始NaN输出→原始索引映射，含验证代码）；④§4.3 新增 CORE-6 约束 `len(output)==len(input)`，判定升级为 CORE-0~6；⑧§5 Step 6.5 新增3个边界测试用例（空输入/len<window/len=window全NaN）。

> 本试验为代码修复验证型，知识库写入内容：
- `knowledge.db`：归档本试验报告路径，标注 `type=code_verification`，关联 `factor=TSI, fix=NaN_isolation`
- 归档目录：`C:\Users\17699\mozhi_platform\reports\EXP-001\`

---

## 附录 A：文件清单

| 文件 | 路径 | 说明 |
| --- | --- | --- |
| 本方案 | `docs/07_research/回测试验/2605241426_EXP001_EMA-NaN隔离防护验证方案.md` | |
| 验证报告 | `reports/EXP-001/ema_nan_validation_report.md` | 执行完成后生成 |
| 测试数据 | `reports/EXP-001/test_vectors.json` | 5种NaN模式 + 全NaN输入序列 |

## 附录 B：快速填写检查清单

> 提交评审前，逐项确认。

**R001 问题定义：**
- [x] 现状有数据支撑（非猜测）
- [x] 根因追到第三层
- [x] 问题陈述包含"对象+偏差+可观测指标"
- [ ] 墨涵已确认写入任务文档

**本试验专属：**
- [x] 5 种 NaN 模式已定义（单点/连续/起始/尾部/混合）
- [ ] **8 项验收标准已定义（CORE-0：全NaN不崩溃；CORE-1~5：5种NaN模式恢复；CORE-6：len(output)==len(input)）**
- [x] **所有4个`_ema`函数版本独立验证，验收标准通过情况须完全一致**
- [x] 正常段偏差 < 1e-10 要求明确
- [x] **NaN编码统一：4个版本输出统一转换为None后再做对比分析**
- [x] 使用当前工作副本（无需回滚），旧版行为由数学确定性推知
- [x] **回归测试套件写入 `tests/regression/nan_isolation/`**
- [x] **回归测试覆盖3个边界用例（空输入 / len<window / len=window全NaN）**
- [x] **索引对齐规则已定义（连续NaN和起始NaN的输出→原始索引映射）**

---

## 附录 C：预置脚本清单

> 本试验为独立验证，不依赖回测流水线预置脚本。脚本状态如下：

| 脚本路径 | 用途 | 状态 | 随本试验产出？ |
| --- | --- | :---: | :---: |
| `tests/regression/nan_isolation/test_nan_isolation.py` | 回归测试套件，覆盖 CORE-0~6 全部验收标准 + 索引对齐规则 + 3个边界用例 | Step 5 产出（边界用例见 Step 6.5） | ✅ 是 |
| `tests/regression/nan_isolation/test_vectors.json` | 5 种 NaN 模式 + 全 NaN 输入的测试向量 | Step 2 构造、Step 5 归档 | ✅ 是 |
| `tests/regression/nan_isolation/test_vectors_boundary.json` | 3 个边界测试用例（空输入 / len<window / len=window全NaN） | Step 6.5 追加 | ✅ 是 |
| `scripts/manual/EXP-001_run.py` | 执行入口，编排 Step 2~6.5 的自动化运行 | 试验启动前编写 | ✅ 是 |

---

> **[DRAFT_READY]**
> **author:** 墨衡 (deepseek-reasoner)
> **created_time:** 2026-05-24T14:26:00+08:00
> **试验编号：** EXP-001
> **正式激活条件：** Stage 3 会签通过
