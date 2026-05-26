# 墨枢 Phase 1 — 因子研究平台执行计划

**文档版本:** v1.0  
**作者:** 墨衡  
**创建时间:** 2026-05-22T22:20+08:00  
**会议决议:** ✅ 方案B（12只×日频×5年）

---

## 一、项目总览

### 1.1 目标

构建 12 只 A 股核心标的 × 日频 × 5年（2021-2025）的因子研究平台，含：
- 全量行情数据采集（Tushare Pro）
- 50+ 因子的计算与存储
- IC/IR 检验框架
- 数据质量保障体系

### 1.2 标的列表

| 序号 | 代码 | 名称 | 行业 |
|:----:|:----:|:----:|:----:|
| 1 | 601857.SH | 中国石油 | 能源 |
| 2 | 000001.SZ | 平安银行 | 银行 |
| 3 | 600519.SH | 贵州茅台 | 白酒/消费 |
| 4 | 601318.SH | 中国平安 | 保险 |
| 5 | 600036.SH | 招商银行 | 银行 |
| 6 | 300750.SZ | 宁德时代 | 新能源 |
| 7 | 600276.SH | 恒瑞医药 | 医药 |
| 8 | 600887.SH | 伊利股份 | 消费 |
| 9 | 600030.SH | 中信证券 | 证券 |
| 10 | 000333.SZ | 美的集团 | 家电 |
| 11 | 002415.SZ | 海康威视 | 科技 |
| 12 | 600436.SH | 片仔癀 | 中药 |

### 1.3 数据源

- **Tushare Pro**（2000分等级，日上限 10 万次调用）
- **API Token:** `09e84b0b5fe40141f51a0aecb21ba648f605bf421444c2d741271ded`
- **限频:** 200次/分钟 → `sleep 0.35s`

### 1.4 数据库

- **文件:** `data/db/analysis.db`
- **表结构:** `stock_daily`, `adj_factor`, `trading_calendar`, `daily_factors`
- **关键规范:** 使用 INSERT OR REPLACE 幂等写入

---

## 二、任务架构

```
┌──────────────────────────────────────────────────────────────┐
│                    Phase 1 执行流水线                       │
├──────────────────────────────────────────────────────────────┤
│  TASK-1: 数据采集                                           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 交易日历 → trading_calendar (SSE + SZSE)              │  │
│  │ 复权因子 → adj_factor (12只)                          │  │
│  │ 日线行情 → stock_daily (12只 × daily_basic + daily)  │  │
│  │ 复权回填 → 价格 × adj_factor → 后复权               │  │
│  └────────────────────────────────────────────────────────┘  │
│                              ↓                                │
│  TASK-2: 因子回填                                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ RSI | MACD | ROC | MTM | CCI | Williams%R | TSI       │  │
│  │ ADX | 趋势强度 | 趋势一致性 | MA斜率 | MA排列        │  │
│  │ 布林带 | ATR | 波动率标准差 | 偏度 | 峰度            │  │
│  │ RSI/KDJ/CCI 超买超卖 | 聪明钱 | 量能趋势 | VWAP      │  │
│  │ 跳空 | 结构品质 | KDJ | MA交叉 | 布林带位置          │  │
│  │              → daily_factors (50+列宽表)               │  │
│  └────────────────────────────────────────────────────────┘  │
│                              ↓                                │
│  TASK-3: IC/IR 检验                                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Rank IC计算 | IC/IR统计 | 因子相关性矩阵              │  │
│  │ 分层回测(L1/L2/L3) | 可视化图表                       │  │
│  │  → reports/phase1_icir_*.png + report.md               │  │
│  └────────────────────────────────────────────────────────┘  │
│                              ↓                                │
│  TASK-4: 数据校验                                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 交易日历覆盖 | 缺失值检测 | 因子范围约束              │  │
│  │ 标准差异常 | 连续性检查                               │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、TASK-1: 数据采集脚本

### 3.1 文件

`scripts/phase1_data_collection.py`

### 3.2 流程

| 阶段 | 操作 | 调用次数 | 说明 |
|:----:|:----:|:--------:|:----:|
| 1 | init_database | 1 | 创建 analysis.db + 表结构 |
| 2 | fetch_trade_calendar | 2 | SSE + SZSE 交易日历 |
| 3 | fetch_adj_factors | 12 | 12只 × 1次 |
| 4 | fetch_daily_basic | 12 | 12只 × 1次 (含 extra fields) |
| 5 | fetch_stock_daily | 12 | 12只 × 1次 (补充无复权K线) |
| 6 | backfill_adj_factors | 1 | 回填复权因子 |
| 7 | compute_adjusted_prices | 1 | 计算后复权价格 |

**总计调用:** ~40次（远低于 10万次/日上限）

### 3.3 关键设计

- **幂等:** `INSERT OR REPLACE` — 支持重复执行
- **限频:** 每次请求后 `time.sleep(0.35)` → 约 2.85次/秒
- **复权:** 使用 `adj_factor` 表存储复权因子，后复权价格 = 不复权价格 × adj_factor
- **字段覆盖:** daily_basic 提供完整字段（turnover_rate, volume_ratio, pe, pb, float_share, circ_mv, total_mv）

---

## 四、TASK-2: 因子回填脚本

### 4.1 文件

`scripts/phase1_factor_backfill.py`

### 4.2 因子体系（50+ 个）

#### P层 — 价格动量类（12个）

| 因子 | 参数 | 范围 | 说明 |
|:----:|:----:|:----:|:----:|
| p_mom_rsi | 14 | [0, 100] | RSI 相对强弱指标 |
| p_mom_macd_dir | 12/26/9 | [-1,0,1] | MACD DIF 方向变化 |
| p_mom_macd_hist_rate | — | [-1,1] | MACD 柱状图变化率 |
| p_mom_price_velocity | 5 | [-20,20] | 5日价格变化率(%) |
| p_mom_roc5 | 5 | [-20,20] | 5日变动率 |
| p_mom_roc10 | 10 | [-30,30] | 10日变动率 |
| p_mom_roc20 | 20 | [-50,50] | 20日变动率 |
| p_mom_acceleration | 10 | — | 价格加速度 |
| p_mom_mtm | 10 | — | 动量 |
| p_mom_williams_r | 14 | [-100,0] | Williams %R |
| p_mom_cci | 20 | — | 商品通道指数 |
| p_mom_tsi | 25/13 | — | 真实强度指数 |

#### L层 — 趋势品质类（8个）

| 因子 | 参数 | 范围 | 说明 |
|:----:|:----:|:----:|:----:|
| l_trd_adx | 14 | [0,100] | ADX 趋势强度 |
| l_trd_strength | — | [0,1] | ADX 归一化 |
| l_trd_consistency | 10 | [0,1] | 趋势方向一致性 |
| l_trd_ma_slope | 20/5 | — | MA 斜率 |
| l_trd_alignment | — | [0,100] | MA 排列评分 |
| l_trd_width | — | [-10,10] | MA5/MA20 偏离度 |
| l_trd_breadth | — | [-2,2] | MA5-MA20 距离 |
| l_trd_composite_score | — | [0,1] | 综合趋势评分 |

#### L层 — 波动率类（9个）

| 因子 | 参数 | 范围 | 说明 |
|:----:|:----:|:----:|:----:|
| l_vol_bb_width | 20/2 | [0,20] | 布林带相对宽度 |
| l_vol_bb_squeeze | 20 | [0,1] | 布林带压缩标识 |
| l_vol_rsi_std | 20 | [0,30] | RSI 滚动标准差 |
| l_vol_price_std | 5 | [0,10] | 价格收益率标准差 |
| l_vol_atr | 14 | [0,100] | 平均真实波幅 |
| l_vol_atr_ratio | 14/60 | — | ATR 短期/长期比 |
| l_vol_log_ret_std | 20 | [0,1] | 对数收益率标准差 |
| l_vol_skew | 20 | [-3,3] | 收益率偏度 |
| l_vol_kurt | 20 | [-2,10] | 收益率峰度 |

#### L层 — 超买超卖类（5个）

| 因子 | 阈值 | 范围 | 说明 |
|:----:|:----:|:----:|:----:|
| l_obo_rsi_level | 30/70 | [0,1,2] | RSI 区间分级 |
| l_obo_rsi_extreme | 20/80 | [-1,0,1] | RSI 极端标识 |
| l_obo_kdj_level | 20/80 | [0,1,2] | KDJ_J 区间分级 |
| l_obo_kdj_extreme | 10/90 | [-1,0,1] | KDJ_J 极端标识 |
| l_obo_cci_level | -100/100 | [-1,0,1] | CCI 区间分级 |

#### L层 — 量价类（8个）

| 因子 | 参数 | 范围 | 说明 |
|:----:|:----:|:----:|:----:|
| l_vol_ratio | 5/20 | [0,10] | 短期/长期均量比 |
| l_vol_ma5_cross | 5/20 | [-1,0,1] | 量均线穿越 |
| l_vol_smart_money | 10 | [-1,1] | 聪明钱评分 |
| l_vol_trend | 20 | [-1,1] | 量能趋势评分 |
| l_vol_vwap_dev | — | — | VWAP 偏离度(%) |
| l_vol_vwap_5_dev | 5 | — | VWAP5 偏离度 |
| l_vol_vwap_20_dev | 20 | — | VWAP20 偏离度 |
| l_vol_dollar_vol | — | — | 成交额(亿) |

#### L层 — 结构类（10个）

| 因子 | 参数 | 范围 | 说明 |
|:----:|:----:|:----:|:----:|
| l_str_structure_quality | 30 | [0,1] | 结构完整度 |
| l_str_gap_up | (0.5%) | [0,1] | 向上跳空 |
| l_str_gap_down | (0.5%) | [0,1] | 向下跳空 |
| l_str_ma5_ma20_cross | — | [-1,0,1] | MA5/MA20 穿越 |
| l_str_ma20_ma60_cross | — | [-1,0,1] | MA20/MA60 穿越 |
| l_str_kdj_k | 9 | — | KDJ K 值 |
| l_str_kdj_d | 9 | — | KDJ D 值 |
| l_str_kdj_j | 9 | — | KDJ J 值 |
| l_str_bb_position | 20 | [0,1] | 价格在布林带位置 |
| l_str_close_vs_vwap | — | [-1,0,1] | 收盘 VS VWAP 方向 |

### 4.3 写入表

`daily_factors` 表（51列宽表），PK=(code, date)，支持 UPSERT 幂等写入。

---

## 五、TASK-3: IC/IR 检验框架

### 5.1 文件

`scripts/phase1_icir_test.py`

### 5.2 检验指标

| 指标 | 方法 | 解释 |
|:----:|:----:|:----:|
| Rank IC | Spearman | 因子值与下期收益的秩相关 |
| IR | Mean(IC) / Std(IC) | 信息比率 |
| IC 累计曲线 | 滚动累加 | IC 趋势与稳定性 |
| IC 正比率 | P(IC>0) | 预测方向一致性 |
| 因子相关矩阵 | Spearman 秩相关 | 因子间冗余度 |
| 分层回测 | 3分位 | L1/L2/L3 累计收益 |

### 5.3 产出文件

| 文件 | 说明 |
|:----|:----|
| `reports/phase1_icir_ts.png` | 各因子每日 IC 时间序列 |
| `reports/phase1_icir_bar.png` | IC/IR 柱状图（Top 30） |
| `reports/phase1_icir_cumulative.png` | IC 累计曲线（按类别分组） |
| `reports/phase1_icir_corr.png` | 因子相关性矩阵 |
| `reports/phase1_icir_layers.png` | 分层回测收益曲线（Top 10） |
| `reports/phase1_icir_report.md` | 完整检验报告 |
| `reports/phase1_icir_stats.csv` | IC/IR 统计数据导出 |

---

## 六、TASK-4: 数据完整性校验

### 6.1 文件

`scripts/phase1_data_validate.py`

### 6.2 校验维度（5 项）

| 序号 | 校验项目 | 方法 | 阈值 |
|:----:|:--------:|:----:|:----:|
| 1 | 交易日历覆盖 | 对比 trading_calendar vs stock_daily | ≥ 95% |
| 2 | 缺失值检测 | NaN/Inf 比例 | ≤ 10% |
| 3 | 因子值合理性 | 范围约束检查 | 每因子定义范围 |
| 4 | 标准差异常 | z-score > 3 占比 | ≤ 2% |
| 5 | 因子连续性 | 连续相同值检测 | ≤ 5 天 |

### 6.3 输出

- stdout 详细报告
- 退出码：0=全部通过, 1=有警告, 2=有失败项

---

## 七、Phase 2 预留

分钟级数据采集已在会议中讨论，标记为 **Phase 2**，待主人另行解决后再启动。

Phase 2 预计涵盖：
- 分钟/小时频率的数据采集
- 短周期因子计算
- 日内交易信号

---

## 八、执行顺序

```bash
# Step 1: 数据采集（约 15 分钟，含 API 限频等待）
python scripts/phase1_data_collection.py

# Step 2: 因子回填（约 2-5 分钟）
python scripts/phase1_factor_backfill.py

# Step 3: IC/IR 检验（约 1-2 分钟）
python scripts/phase1_icir_test.py

# Step 4: 数据校验（约 30 秒）
python scripts/phase1_data_validate.py
```

**Caveats:**
- TASK-1 需要稳定的 Tushare API 连接
- TASK-3 需要 TASK-1 + TASK-2 完成
- 所有脚本均支持幂等重复执行

---

*文档由 墨枢 Phase 1 规划自动生成*
