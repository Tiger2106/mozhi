# EXP-2026-003-KNOWDEEP Step 2 Dry-run 报告

> **编写者**: 墨衡 (moheng)
> **创建时间**: 2026-05-26T16:36+08:00
> **版本标记**: 0bec5f6

---

## 一、操作记录

### 1.1 定位 EXP-002 回测入口

| 项目 | 详情 |
|:----|:------|
| 入口脚本 | `C:\Users\17699\mozhi_platform\scripts\exp_invfac002\run_exp_invfac002.py` |
| 因子模块 | `exp_factors.py` — calc_trend_quality, calc_vol_rsi_std, calc_kdj_k |
| Bootstrap 模块 | `exp_bootstrap.py` — bootstrap_ic_test, spearman_correlation |
| 市场状态模块 | `exp_market_state.py` — classify_market_state |
| 稳定性模块 | `exp_stability.py` — 四层稳健性检验 |
| QC 模块 | `data_qc_check.py` — 数据质量前置检查 |

**命令行参数接口:**
```
python scripts/exp_invfac002/run_exp_invfac002.py [--dry-run] [--skip-qc] [--skip-sensitivity]
```

| 参数 | 类型 | 用途 |
|:----|:----:|:-----|
| `--dry-run` | flag | 仅验证架构，不执行回测 |
| `--skip-qc` | flag | 跳过 §2.3 数据质量前置检查 |
| `--skip-sensitivity` | flag | 跳过 §4.1 敏感性分析 |

**流水线步骤:**
1. §2.3 数据质量前置检查
2. Step 1: 从 market_data.db 加载日线数据 + QFQ 前复权
3. Step 2: 计算三因子 (TrendQuality / l_vol_rsi_std / l_str_kdj_k)
4. Step 3: 市场状态分类（滚动波动率分位数）
5. Step 4 & 5: IC 计算 + Bootstrap 置换检验
6. §5.2: FDR BH 多重比较校正
7. §5.3: 三层稳定性检验
8. §4.1: 分位数阈值敏感性分析（9格扫描）
9. Step 6: 生成输出报告

### 1.2 创建 EXP-003 回测入口脚本

| 项目 | 详情 |
|:----|:------|
| 脚本路径 | `C:\Users\17699\mozhi_platform\scripts\exp003_knowdeep\run_exp003_q1.py` |
| 继承模块 | `exp_factors.py`, `exp_bootstrap.py`, `exp_market_state.py`, `exp_stability.py`, `data_qc_check.py` |
| 命令行参数 | `--dry-run` (验证架构), `--skip-qc` (跳过QC) |

### 1.3 测试结果

| 测试项 | 结果 |
|:------|:----:|
| `python -c "from scripts.exp003_knowdeep.run_exp003_q1 import *"` | ✅ 导入成功 |
| `python scripts/exp003_knowdeep/run_exp003_q1.py --dry-run` | ✅ Dry-run 通过 |
| 当前标的数 (market_data.db) | **12 只**（待数据灌入后全量 A50） |

---

## 二、参数差异表

| 参数 | EXP-002 | EXP-003 Q1 | 说明 |
|:----|:-------:|:----------:|:-----|
| **标的池** | 12 只 | A50 全池（~50只） | 从 DB 自动读取 |
| **训练期** | 2021~2025 (Warmup) | **2007~2019** | 独立窗口，跨周期 |
| **验证期** | IS 2022~2024 / OOS 2024~2025 | **2020~2026-04** | 统一验证窗口 |
| **持有期** | 5d/10d/20d | **20d 主验证**，5d/10d 参考 | 成本约束强制 20d |
| **因子** | TrendQuality + l_vol_rsi_std + kdj_k | **TrendQuality + l_vol_rsi_std** | 仅 Q1 两因子 |
| **成本** | 未考虑 | commission=0.0003, stamp_tax=0.0005(卖出), slippage=0.001 | 净收益计算 |
| **分析方法** | Bootstrap + FDR + L3 + 敏感性 | Bootstrap + FDR + L3 + **跨窗口衰减** | 新增衰减分析 |
| **输出路径** | `reports/EXP-2026-INVFAC-002/` | `reports/EXP-2026-003-KNOWDEEP/q1/` | 独立目录 |

---

## 三、代码架构说明

### 3.1 文件结构
```
scripts/exp003_knowdeep/
├── run_exp003_q1.py           # 本库 (主入口)
├── ... (后续 Q2/Q3/Q4 入口)

# 继承自 EXP-002（不复制，通过 import 引用）:
scripts/exp_invfac002/
├── exp_factors.py              # 因子计算
├── exp_bootstrap.py            # Bootstrap 检验
├── exp_market_state.py         # 市场状态分类
├── exp_stability.py            # 稳定性检验
├── data_qc_check.py            # 数据质量检查
```

### 3.2 EXP-003 Q1 流水线
```
Step 0: 读取标的列表 (market_data.db → auto)
    │
§2.3: 数据质量前置检查 (run_data_qc)
    │
Step 1: 加载数据 (load_stock_data → QFQ 前复权)
    │
Step 2: 计算两因子 (l_vol_rsi_std + TrendQuality)
    │
Step 3: 市场状态分类 (classify_market_state)
    │
Step 4 & 5: 双窗口 Bootstrap 检验
    ├── 训练期 (2007~2019)
    └── 验证期 (2020~2026-04)
    │
§5.2: FDR BH 校正 (双窗口独立)
    │
§5.3: 三层稳定性检验 (验证期)
    │
Step 5.4: 跨窗口衰减分析 ← 新增
    │
Step 5.5: 因子相关性预计算 ← 新增 (Q2 预计算)
    │
Step 6: 生成输出报告
```

### 3.3 关键新增功能

1. **双窗口分析** — 训练期 (2007~2019) 和验证期 (2020~2026-04) 独立计算 IC + Bootstrap
2. **跨窗口衰减率计算** — `compute_decay_analysis()` 判定方向一致性 + 衰减幅度
3. **净收益计算** — `compute_forward_returns()` 中扣除 0.31% 交易成本
4. **因子相关性预计算** — `compute_factor_correlation()` 为 Q2 组合信号提供数据准备

---

## 四、下一步建议

| 优先级 | 事项 | 说明 |
|:------:|:-----|:------|
| P0 | **灌入 A50 全量数据** | 当前仅 12 只，需执行 Tushare 批量灌入至 market_data.db |
| P0 | **验证数据完整性** | 确认 2007-01-01 起所有标的均有连续数据（含复权因子） |
| P1 | **执行 Q1 回测** | `python scripts/exp003_knowdeep/run_exp003_q1.py` |
| P1 | **检查衰减率结果** | 重点关注双因子在验证期的方向一致性和 IC 衰减率 |
| P2 | **Q2 组合信号** | 使用 Q1 预计算的因子相关性作为输入 |
