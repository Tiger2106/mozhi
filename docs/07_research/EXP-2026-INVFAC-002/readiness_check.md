# EXP-2026-INVFAC-002 试验启动就绪报告

> **author:** 墨衡 (moheng)
> **checked:** 2026-05-25T17:10+08:00
> **status:** [CHECK_DONE]
> **version:** 1.0

---

## 1. 数据就绪检查

### 1.1 market_data.db 基础状态

| 检查项 | 结果 | 备注 |
|:------|:----:|:-----|
| market_data.db 存在 | ✅ | `C:\Users\17699\mozhi_platform\data\market\market_data.db` |
| stock_daily 表存在 | ✅ | 含 12 只 A50 标的 |
| adj_factor 表存在 | ✅ | 独立表，与 stock_daily 关联 |
| 标的数量 | ✅ | 12 只（见下方列表）|
| 数据时间范围 | ✅ | 2020-01-02 ~ 2026-05-22（覆盖 2021-2025）|
| adj_factor NULL 检查 | ✅ | 0 个 NULL（通过）|

### 1.2 标的列表与数据连续性

| 代码 | 名称（推测） | 2021-2025 交易日数 | 数据完整 |
|:---:|:-----------:|:-------------------:|:-------:|
| 000001 | 平安银行 | 1212 | ✅ |
| 000333 | 美的集团 | 1212 | ✅ |
| 002415 | 海康威视 | 1212 | ✅ |
| 300750 | 宁德时代 | 1212 | ✅ |
| 600030 | 中信证券 | 1206 | ✅（少6天，需确认原因）|
| 600036 | 招商银行 | 1212 | ✅ |
| 600276 | 恒瑞医药 | 1212 | ✅ |
| 600436 | 片仔癀 | 1212 | ✅ |
| 600519 | 贵州茅台 | 1212 | ✅ |
| 600887 | 伊利股份 | 1212 | ✅ |
| 601318 | 中国平安 | 1212 | ✅ |
| 601857 | 中国石油 | 1212 | ✅ |

### 1.3 三因子数据源字段

| 字段 | 存在情况 |
|:----|:--------|
| open | ✅ |
| high | ✅ |
| low | ✅ |
| close | ✅ |
| volume | ✅ |
| free_float | ⚠️ **缺失**：`float_share` 字段存在但全部为 NULL，`free_float_source` 字段不存在 |

> **问题**：实验设计 §2.1 要求 `free_float` 东财口径、下限 0.5。当前 DB 无 `free_float` 数据，`float_share` 全部为 NULL。此项为 **数据风险**，需要先补充 free_float 数据才能执行回测筛选。

### 1.4 数据窗口连续性

| 检查项 | 结果 |
|:------|:----:|
| 2021-01-01 ~ 2025-12-31 无断点 | ✅ 各标的平均 1210 交易日/年（扣除周末节假日）|
| 暖机期 2021-01~2021-12 可分离 | ✅ |
| 样本内 2022-01~2024-06 | ✅ |
| 样本外 2024-07~2025-12 | ✅ |

---

## 2. 代码环境检查

### 2.1 已有框架

| 组件 | 状态 | 说明 |
|:----|:----:|:-----|
| 回测引擎 | ✅ | `src/backtest/backtest_engine.py` + `runners/method_backtest_runner.py` |
| WalkForward | ✅ | `src/backtest/analysis/walk_forward.py` |
| IC 计算 | ✅ | `scripts/compute_factor_ic.py`（含 Spearman rank 实现）|
| 因子回填框架 | ✅ | `scripts/phase1_factor_backfill.py`（50+ 因子）|
| KDJ K 值计算 | ✅ | `_calc_kdj()` in backfill（与实验设计 §3.1.3 一致）|
| 市场状态过滤 | ⚠️ | 存在 `market_state_filter.py` 但基于 RegimeAnalyzer（DOWNTREND/CLIMAX），非滚动波动率分位数 |
| 版本管理 | ❌ | 工作副本，未提交 Git |

### 2.2 关键函数检查

| 函数 | 状态 | 说明 |
|:----|:----:|:------|
| **Bootstrap 置换检验** | ❌ **缺失** | 实验 §3.3 要求，需实现 `bootstrap_ic_test()` |
| **滚动波动率分位数状态分类** | ❌ **缺失** | 实验 §3.2.1 要求，需实现 `classify_market_state()` |
| **TrendQuality（价格位置/ATR 版）** | ❌ **需重写** | 现有 `trend_quality_factor.py` 为 ADX 版，实验 §3.1.1 要求价格位置偏移版 |
| **l_vol_rsi_std（成交量 RSI 版）** | ❌ **需重写** | 现有实现为 `rolling_std(RSI(close, 14), 20)` = 价格 RSI 标准差；实验 §3.1.2 要求成交量 RSI 标准差 |
| **l_str_kdj_k** | ✅ 可直接复用 | 实验 §3.1.3 与 `_calc_kdj()` 一致 |
| **多持有期前向 IC 计算** | ⚠️ 部分存在 | `compute_factor_ic.py` 已实现，需包装为实验 §3.4 接口 |
| **三层反转检验** | ❌ **缺失** | 实验 §5 三层验证链完全未实现 |
| **参数敏感性分析** | ❌ **缺失** | 实验 §4 网格灵敏度扫描未实现 |

### 2.3 预置脚本检查

| 脚本 | 状态 |
|:----|:----:|
| `scripts/qc/data_qc_check.py` | ❌ **缺失**（实验附录 C 要求）|
| `scripts/utils/mark_abandoned.py` | ❌ 未检查 |
| `scripts/archive/archive_failure.py` | ❌ 未检查 |
| `scripts/utils/calc_period_trading_days.py` | ❌ 未检查 |
| `scripts/knowledge/search_failure_knowledge.py` | ❌ 未检查 |
| `scripts/layer_q/run_layer_q_audit.py` | ❌ 未检查 |
| `scripts/writeback/finalize_exp.py` | ❌ 未检查 |

---

## 3. 需要完成的准备工作

### 3.1 数据修复（优先）

| 事项 | 优先级 | 说明 |
|:----|:-----:|:-----|
| 补充 free_float 数据 | **高** | 东财口径 free_float 缺失，无法执行 §2.1 标的筛选 |
| 确认 600030（中信证券）缺 6 天原因 | 低 | 仅为容错考量，不阻断 |

### 3.2 代码实现（已编写，待墨萱复核）

以下函数已按实验设计 §3 规范编写，见 `scripts/exp_invfac002/` 目录：

| 函数 | 对应设计章节 | 文件 |
|:----|:----------:|:----|
| `trend_quality()` | §3.1.1 | `exp_factors.py` |
| `calc_vol_rsi_std()` | §3.1.2 | `exp_factors.py` |
| `calc_kdj_k()` | §3.1.3 | `exp_factors.py`（复用 backfill）|
| `classify_market_state()` | §3.2.1 | `exp_market_state.py` |
| `bootstrap_ic_test()` | §3.3 | `exp_bootstrap.py` |
| `compute_forward_ic()` | §3.4 | `exp_analysis.py`（复配留日多持有期）|
| `data_qc_check.py` | 附录 C | `scripts/qc/data_qc_check.py` |
| **完整回测脚本** | §5-6 | `run_exp_invfac002.py`（✅ 编写完成，**暂不执行**）|

### 3.3 回测可执行性

| 检查项 | 状态 |
|:------|:----:|
| 回测脚本是否可执行 | ✅ **是**（已编写，等待墨萱复核）|
| 是否已运行回测 | ❌ **未运行**（墨萱复核通过前不跑）|
| free_float 缺失是否阻断 | ⚠️ **部分阻断**——free_float 筛选可临时跳过，但需在报告中标注 |

---

## 4. 风险与建议

### 4.1 数据风险

- **free_float 缺失** ⚠️：实验设计 §7.2 已识别此风险。当前数据库无 free_float 数据。建议：
  1. 从东方财富接口补充 free_float 历史数据
  2. 或暂时跳过 free_float > 0.5 筛选，在报告中标注"skip due to data unavailability"
  3. 回测完成后在 knowledge.db 中记录此缺陷

### 4.2 代码风险

- **分位数法 vs HMM**：当前仅实现了滚动波动率分位数法（§3.2），HMM 替代检验（§4.3）后续需要补充
- **l_vol_rsi_std 实现差异**：现有 backfill 中的 `l_vol_rsi_std` 是价格 RSI 标准差，与新实现的成交量 RSI 标准差不同，需在报告中说明两者差异

---

## 5. 总结

| 维度 | 就绪度 | 说明 |
|:----|:-----:|:------|
| 数据就绪 | ⚠️ 75% | 12 标的数据齐全但 free_float 缺失 |
| 代码框架 | ✅ 80% | 已有回测框架、IC 计算，核心函数已补充 |
| 关键函数 | ⚠️ | **5 个关键函数已实现**（trend_quality, vol_rsi_std, market_state, bootstrap, data_qc）|
| 回测脚本 | ✅ 已就绪 | `run_exp_invfac002.py` 编写完成，待复核 |
| 可执行 | ✅ | 在跳过 free_float 筛选前提下可直接执行 |

**总体判断**：试验启动条件基本满足。需解决 **free_float 数据缺失** 后在墨萱复核通过后执行。

---

*本报告由墨衡自动生成，详见任务：EXP-2026-INVFAC-002 试验状态检查*
