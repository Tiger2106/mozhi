<!--
author: 墨衡
created_time: 2026-05-16 07:56 +08:00
task_id: backtest_exec_audit
-->

# 回测改进 v4.0 执行审计报告

**审计人**: 墨衡
**审计时间**: 2026-05-16 07:56 +08:00
**审计范围**: 任务1~4 已修改文件 + import 链路 + 兼容性

---

## 审计总览

| 评价 | 数量 |
|:----|:----:|
| ✅ 通过 | 8 |
| ⚠️ 警告 | 3 |
| 🔴 阻塞 | 1 |

---

## 🔴 阻塞问题

### B1: generate_comparison.py 模块级副作用（严重: 高）

**文件**: `src/backtest/reports/generate_comparison.py`
**说明**: 该文件在**模块级别**（不在任何函数内）执行了全部计算逻辑：
- 加载 `grid_equity_curve.csv`
- 调用 `calc_buy_hold_return()`（实际发起 akshare 网络请求）
- 调用 `compute_trade_distribution()` 处理模拟交易数据
- 写入 `multi_comparison.md`
- 输出 `print()` 调试信息到 stdout

这意味着：
1. 任何 `from ... import` 操作都会触发一次完整的报告生成
2. 运行时依赖网络（akshare）和数据文件（CSV）
3. 每导入一次就重写一次报告文件，产生不确定的写操作
4. `print` 输出会污染调用方的 stdout

**影响面**: 如果其他模块通过 `from generate_comparison import add_buy_hold_column` 导入，会意外执行所有计算。

**建议修复**: 将模块级代码移至 `def main():` 函数，并用 `if __name__ == "__main__": main()` 包裹。导出函数（`_extract_params_block`, `add_buy_hold_column` 等）不应依赖模块级执行结果。

---

## ⚠️ 警告问题

### W1: multi_runner.py 重复 @staticmethod 装饰器

**文件**: `src/backtest/strategies/multi_runner.py`（L594-595）
**说明**: `_compute_combined` 方法前有两次 `@staticmethod`，是复制粘贴遗留。
**影响**: Python 语法允许（双重装饰无副作用），但代码质量低，可能暗示其他复制遗漏。

---

### W2: generate_comparison.py 使用模拟数据而非实际回测数据

**文件**: `src/backtest/reports/generate_comparison.py`
**说明**: 
- 趋势/反转/组合净值曲线通过 `np.random.normal()` 按 KNOWN 指标校准模拟生成
- 逐笔交易通过参数化模拟（`_gen_simulated_trades()`）生成，非实际回测记录
- 报告自身已在头部标注模拟说明，但函数使用者可能误以为数据真实

**影响**: 调用 `add_buy_hold_column()` 不会引发这些问题（仅用 akshare 获取基准），但整体报告内容的可靠性受限于模拟精度。

---

### W3: grid_equity_curve.csv 仅存在于旧路径

**文件**: `src/backtest/reports/generate_comparison.py`
**说明**: 脚本首先尝试 `mozhi_platform/data/backtest_results/grid_equity_curve.csv`（不存在），随后依赖向后兼容的旧路径 `mo_zhi_sharereports/reports/backtest/grid_equity_curve.csv`（存在）。
**影响**: 迁移到新平台后，`data/backtest_results/` 目录缺少必要的数据文件。

---

## ✅ 通过检查

### P1: import 路径完整性

所有已修改文件的 import 均指向新平台 `src.backtest.*`，且对应的 `.py` 文件均存在：

| 文件 | 关键 import | 状态 |
|:----|:-----------|:----:|
| `multi_runner.py` | `src.backtest.backtest_engine`, `src.backtest.signal_bridge`, `src.backtest.strategies.*` | ✅ |
| `chart_generator.py` | `src.backtest.strategies.multi_runner` | ✅ |
| `data_historical_fill.py` | `src.backtest.data_loader.populate_stock_daily` | ✅ |
| `data_filler.py` | 纯 stdlib 导入 | ✅ |
| `performance.py` | 纯 stdlib 导入 | ✅ |
| `generate_comparison.py` | `src.backtest.benchmark_data_source.*`, `src.backtest.performance.*`, `src.backtest.strategies.*` | ✅ |

**实际验证**: 全部 6 个文件的 import 已在 Python 环境中测试通过。

---

### P2: data_historical_fill.py 可用性

- 路径注入正确（`_PROJECT_ROOT = _THIS_DIR.parent.parent`）
- `populate_stock_daily` 函数签名匹配：`(symbol, start_date, end_date, db_path, ds)`
- `ChunkIntervalDays=180` 分块合理，含块间休眠
- `_verify_coverage()` 完整验证覆盖

---

### P3: data_filler.py 默认日期更新

- 主方法 `fill()` 默认 `start_date="2020-01-01"`, `end_date="2026-05-16"` ✅
- CLI 参数 `--start`/`--end` 默认值相同 ✅
- 与 `data_historical_fill.py` 的 `START_DATE="20200101"`/`END_DATE=今日` 一致 ✅

---

### P4: performance.py 新增函数

- `pair_trades_to_roundtrips()`: FIFO 配对逻辑，支持多头/空头、加仓平均成本
- `compute_trade_distribution()`: 完整盈亏分布统计（胜率、盈亏比、持仓天数等）
- 导入和函数调用均通过验证 ✅

---

### P5: multi_runner.py benchmark 改动

- `CombinedResult`: 新增 `benchmark_total_return` / `benchmark_name` 字段 ✅
- `MultiStrategyResult`: 新增 `benchmark_info` 字段 ✅
- `run_multi()`: 接受 `benchmark_equity` / `benchmark_name` 参数 ✅
- `_compute_combined()`: 合并时注入 benchmark_equity 基准曲线 ✅
- `compute_benchmark_equity()`: 从 Bar.close 计算买入持有净值序列 ✅

---

### P6: chart_generator.py 基准曲线叠加

- `STRATEGY_COLORS`: 新增 `"benchmark": "#F39C12"` 橙色 ✅
- `_nav_chart()`: 检测 `benchmark_equity` 列存在时，绘制虚线基准曲线 ✅
- 标注中显示基准名称和总收益率（如 `买入持有(中国石油) +11.72%`）✅

---

### P7: generate_comparison.py 参数配置区块

- `_extract_params_block()`: 支持三种策略 Config 实例自动读取 ✅
- `_create_default_params_block()`: 创建默认配置实例 ✅
- GridConfig 嵌套字段展平（`signal.grid_config.*`, `position.*.*`）✅
- 实际运行通过验证 ✅

---

### P8: generate_comparison.py 第六节（交易盈利概率）

- `_trade_detail_rows()` / `_distribution_rows()`: 渲染逐笔明细表和盈亏分布表 ✅
- `compute_trade_distribution()`: 正确处理模拟交易数据结构 ✅
- 报告正文包含趋势/反转/网格三策略的交易明细章节 ✅

---

## 兼容性评估

### 旧库 `backtest_engine/` import 是否仍可用

| 旧路径 | 状态 | 说明 |
|:------|:----:|:-----|
| `backtest_engine.performance` | ✅ | 旧文件保留，`Performance` 兼容类存在 |
| `backtest_engine.data_filler` | ✅ | 旧文件保留 |
| `backtest_engine.benchmark` | ✅ | 旧文件保留 |
| `backtest_engine.*` (其他文件) | ✅ | 原库未修改 |

**结论**: 旧库完整保留，所有通过 `backtest_engine.xxx` 的旧 import 继续可用。

### 新库 `src.backtest.*` import 可用性

所有已修改文件的 import 通过测试。`generate_comparison.py` 虽能导入，但模块级副作用需修复（见 B1）。

---

## 汇总表

| ID | 文件 | 问题类型 | 严重度 | 是否阻塞 |
|:--:|:----|:--------|:------:|:--------:|
| B1 | `generate_comparison.py` | 模块级副作用 | 🔴 高 | **是** |
| W1 | `multi_runner.py` | 重复装饰器 | ⚠️ 低 | 否 |
| W2 | `generate_comparison.py` | 模拟数据 | ⚠️ 中 | 否 |
| W3 | `grid_equity_curve.csv` | 文件缺失（有回退） | ⚠️ 低 | 否 |
| P1~P8 | 所有文件 | import + 功能 | ✅ | — |

**建议处理顺序**: B1 → W3 → W2 → W1
