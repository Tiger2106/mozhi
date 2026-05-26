# 策略对比框架设计

> **任务 B**: 策略对比评估  
> **作者**: 墨衡 (moheng)  
> **生成时间**: 2026-05-18T18:30+08:00  
> **版本**: v1.0  
> **说明**: 评估性框架设计，不包含实际对比回测结果。

---

## 1. 当前系统已有策略全景

### 1.1 策略分两大类

```
墨枢策略系统
├── 趋势策略族 (P2) — backtest_engine/strategies/trend_strategy.py
│   ├── MA金叉死叉      (P2-02) ✅ 已实现
│   ├── MACD信号        (P2-03) ✅ 已实现
│   ├── 布林带突破      (P2-04) ✅ 已实现
│   ├── 趋势评分过滤    (P2-05) ✅ 已实现（待实盘验证）
│   ├── 多信号投票      (P2-06) ✅ 已实现
│   └── 仓位管理        (P2-08~11) ✅ 已实现
│       ├── 固定比例仓位     (P2-08)
│       ├── 趋势强度仓位     (P2-09)
│       ├── 金字塔加仓       (P2-10)
│       └── 止损止盈管理     (P2-11)
│
└── 反转策略族 (P3) — backtest_engine/strategies/reversal_strategy.py
    ├── RSI超卖超买     (P3-02) ✅ 已实现
    ├── KDJ信号         (P3-03) ✅ 已实现
    ├── 布林带反转      (P3-04) ✅ 已实现
    ├── 乖离率信号      (P3-05) ✅ 已实现
    ├── 多规则投票      (P3-06) ✅ 已实现
    └── 冷却期管理      (P3-07) ✅ 已实现

其他（因子系统，尚未封装为独立策略）
└── src/backtest/factors/ — 因子计算模块
    ├── regime_factor.py       (市场状态分类)
    ├── structure_factor.py    (支撑阻力结构)
    ├── trend_quality_factor.py (趋势质量评分)
    ├── volume_flow_factor.py  (成交量流向)
    ├── volume_profile_factor.py (成交量分布)
    └── vwap_factor.py         (成交量加权均价)
```

### 1.2 各策略成熟度评估

| 策略名称 | 模块 | 代码状态 | 回测验证 | 实盘无问题 | 成熟度 |
|:---------|:-----|:---------|:---------|:-----------|:------:|
| MA金叉死叉 (P2-02) | `trend_strategy.py` | ✅ 完整实现 | ✅ 601857 88笔回测 | ⚠️ 待验证 | ★★★★★ |
| MACD信号 (P2-03) | `trend_strategy.py` | ✅ 完整实现 | ❌ 独立回测未执行 | ❌ | ★★★☆☆ |
| 布林带突破 (P2-04) | `trend_strategy.py` | ✅ 完整实现 | ⚠️ 部分回测 | ❌ | ★★★☆☆ |
| 趋势评分过滤 (P2-05) | `trend_strategy.py` | ✅ 完整实现 | ⚠️ 趋势评分逻辑已验证 | ❌ | ★★★★☆ |
| 多信号投票 (P2-06) | `trend_strategy.py` | ✅ 完整实现 | ❌  | ❌ | ★★☆☆☆ |
| RSI反转 (P3-02) | `reversal_strategy.py` | ✅ 完整实现 | ✅ 有回测结果 | ❌ | ★★★★☆ |
| KDJ反转 (P3-03) | `reversal_strategy.py` | ✅ 完整实现 | ⚠️ 仅单元测试 | ❌ | ★★★☆☆ |
| 布林带反转 (P3-04) | `reversal_strategy.py` | ✅ 完整实现 | ⚠️ 有回测结果 | ❌ | ★★★☆☆ |
| 乖离率反转 (P3-05) | `reversal_strategy.py` | ✅ 完整实现 | ❌ 独立回测未执行 | ❌ | ★★☆☆☆ |
| 多规则投票 (P3-06) | `reversal_strategy.py` | ✅ 完整实现 | ❌  | ❌ | ★★☆☆☆ |
| 冷却期管理 (P3-07) | `reversal_strategy.py` | ✅ 完整实现 | ⚠️ 逻辑已验证 | ❌ | ★★★☆☆ |
| Fixed仓位 (P2-08) | `trend_position.py` | ✅ 完整实现 | ✅ 有回测 | ❌ | ★★★★★ |
| TrendScore仓位 (P2-09) | `trend_position.py` | ✅ 完整实现 | ⚠️ 逻辑已验证 | ❌ | ★★★☆☆ |
| Pyramid加仓 (P2-10) | `trend_position.py` | ✅ 完整实现 | ❌  | ❌ | ★★☆☆☆ |
| 止损止盈 (P2-11) | `trend_position.py` | ✅ 完整实现 | ⚠️ 仅单元测试 | ❌ | ★★★☆☆ |

**注**：'回测验证'指在该策略下执行过完整的端到端回测（含净值曲线和绩效指标）。

---

## 2. 策略对比框架设计

### 2.1 对比维度

每个对比从以下 4 个维度展开：

#### 维度 A: 信号表现
| 指标 | 说明 | 优先级 |
|:-----|:-----|:------:|
| 信号触发率 (Signal Rate) | 信号触发的 Bar 数 / 总 Bar 数 | 🔴 |
| 信号→成交转化率 | 触发信号最终执行的占比 | 🔴 |
| 信号密度 | 每百 Bar 产生的信号数 | 🟡 |
| 平均信号间隔 | 两次信号间的平均 Bar 数 | 🟡 |
| 持仓周期分布 | ≤5d / 6-15d / >15d 的占比 | 🟢 |

#### 维度 B: 绩效表现
| 指标 | 说明 | 优先级 |
|:-----|:-----|:------:|
| 总收益率 (Total Return) | 回测期总回报 | 🔴 |
| 年化收益率 (Annual Return) | 经年化后的回报率 | 🔴 |
| 最大回撤 (Max DD) | 峰值到谷值的最大跌幅 | 🔴 |
| 胜率 (Win Rate) | 盈利交易 / 总交易 | 🔴 |
| 平均盈亏比 (Avg Win/Loss) | 平均盈利 / 平均亏损 | 🔴 |
| Sharpe 比率 | 风险调整后收益 | 🔴 |
| Calmar 比率 | 年化收益 / 最大回撤 | 🟡 |
| 交易次数 | 总开仓/平仓次数 | 🟢 |
| 资金利用率 | 持仓天数 / 总天数 | 🟡 |

#### 维度 C: 风险表现
| 指标 | 说明 | 优先级 |
|:-----|:-----|:------:|
| 最大回撤区间 | 回撤持续天数 | 🔴 |
| 最大单笔亏损 | 单笔最大亏幅 | 🔴 |
| 连续亏损次数 | 最长连续亏损序列 | 🔴 |
| 收益稳定性 | 月度正收益占比 | 🟡 |
| 尾部风险 | 收益分布 5% 分位 | 🟡 |
| 夏普稳定性 | 滚动 6 月 Sharpe 标准差 | 🟢 |

#### 维度 D: 市场适应性
| 指标 | 说明 | 优先级 |
|:-----|:-----|:------:|
| TREND_UP 表现 | 上升趋势中的胜率/收益 | 🔴 |
| TREND_DOWN 表现 | 下跌趋势中的表现 | 🔴 |
| RANGE 表现 | 震荡市中的表现 | 🔴 |
| 生命周期匹配度 | 策略信号集中在哪些生命周期阶段 | 🟡 |
| 假突破抗性 | 在假突破中的损失控制 | 🟡 |
| 不同置信度下的表现 | HIGH/MEDIUM/LOW 置信度的收益分化 | 🟢 |

### 2.2 对比组设计

#### 组 1: 信号策略对比（同仓位管理）
**固定仓位** = FixedPosition(0.3), 止损 = FixedStopLoss(0.05)

```
对比标的            信号源               回测区间
─────────────────────────────────────────────────
MaCross_5_20       MA金叉死叉(5,20)     2020-2025
MaCross_10_30      MA金叉死叉(10,30)    2020-2025
MACD_12_26_9       MACD(12,26,9)        2020-2025
Bollinger_20_2     布林带突破(20,2)      2020-2025
RSI_30_70          RSI超卖超买(30,70)    2020-2025
KDJ_20_80          KDJ(9, 20, 80)       2020-2025
Bias_5pct          乖离率(5, -5%, 5%)    2020-2025
Voted_2of4         多规则投票(min=2)     2020-2025
```

#### 组 2: 仓位管理对比（同信号源）
**固定信号源** = MA金叉死叉(5,20)

```
仓位策略            参数
─────────────────────────────────────
Fixed_20pct        FixedPosition(0.2)
Fixed_30pct        FixedPosition(0.3)
Fixed_50pct        FixedPosition(0.5)
TrendScore         TrendScorePosition(软映射)
Pyramid            PyramidPosition(梯度加仓)
```

#### 组 3: 风险控制对比（同信号+同仓位）
**固定信号** = MA金叉死叉(5,20) **固定仓位** = FixedPosition(0.3)

```
风控策略            参数
─────────────────────────────────────
NoStop             无止损
FixedStop_3pct     固定止损3%
FixedStop_5pct     固定止损5%
FixedStop_10pct    固定止损10%
TrailingStop_MA20  移动止损(MA20)
ATRStop             ATR止损
```

#### 组 4: 市场规模适应性（同一策略在不同标的）
**固定策略** = MA金叉死叉(5,20), FixedPosition(0.3)

```
标的              市场
─────────────────────────
601857.SH         A股能源股
600519.SH         A股消费龙头
000300.SH         A股沪深300
000001.SH         A股上证综合
000016.SH         A股上证50
```

### 2.3 输出格式

#### 主对比报告格式

```markdown
# 策略对比报告 vX

## 对比组: <组名称>
对比标的: 601857.SH | 回测区间: 2020-2025 | 参数: ...

## 核心指标对比表

| 策略 | 总收益 | 年化 | MaxDD | 胜率 | 盈亏比 | Sharpe | Calmar | 交易次数 | 信号率 |
|:----|:-----:|:----:|:-----:|:----:|:------:|:-----:|:------:|:--------:|:------:|
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

## 净值曲线对比

> (多策略叠图)
> 文件: backtest_results/charts/{组名}_comparison.png

## 分市场状态表现

| 策略 | TREND_UP 收益 | TREND_DOWN 收益 | RANGE 收益 |
|:----|:------------:|:--------------:|:---------:|
| ... | ... | ... | ... |

## 持仓周期分布

| 策略 | ≤5d 占比 | 6-15d 占比 | >15d 占比 |
|:----|:--------:|:---------:|:---------:|
| ... | ... | ... | ... |

## 最优参数组合

| 策略 | 最优参数 | 年化 | MaxDD | 最佳市场 | 最差市场 |
|:----|:---------|:----:|:-----:|:--------:|:--------:|

## 结论与建议

1. ...
2. ...
```

#### 单策略详细输出格式

```json
{
  "strategy": "MaCross_5_20",
  "symbol": "601857.SH",
  "parameters": {"ma_fast": 5, "ma_slow": 20, "position_ratio": 0.3, "stop_loss": 0.05},
  "period": "2020-01-02 ~ 2025-05-15",
  "performance": {
    "total_return_pct": 18.16,
    "annual_return_pct": 2.75,
    "max_drawdown_pct": 2.38,
    "win_rate_pct": 52.3,
    "avg_profit_pct": 2.16,
    "sharpe_ratio": 0.47,
    "calmar_ratio": 1.15,
    "total_trades": 88,
    "signal_rate_pct": 5.71
  },
  "risk": {
    "max_drawdown_days": 45,
    "max_single_loss_pct": -3.95,
    "consecutive_losses": 3,
    "capital_utilization_pct": 20.3
  },
  "market_adaptation": {
    "TREND_UP": {"trades": 26, "win_rate": 50.0, "avg_return": 2.34},
    "TREND_DOWN": {"trades": 4, "win_rate": 75.0, "avg_return": 3.13},
    "RANGE": {"trades": 14, "win_rate": 50.0, "avg_return": 1.54}
  },
  "lifecycle_match": {
    "best_lifecycle": "EXHAUST",
    "worst_lifecycle": "DISTRIB",
    "observation": "假突破率: EXHAUST 5.26% vs DISTRIB 13.56%"
  },
  "verdict": "...",
  "recommendations": ["..."]
}
```

### 2.4 实现路径建议

| 优先级 | 步骤 | 工时估计 | 说明 |
|:-----:|:-----|:--------:|:-----|
| P0 | 跑组1信号对比（全部策略在 601857 上一键回测） | 0.5d | 这是最基础的一轮对比 |
| P1 | 跑组4标的对比（MA策略在5个标的上） | 0.5d | 验证策略的一般性 vs 特定性 |
| P2 | 跑组3风控对比（同信号不同风控） | 0.5d | 量化止损对策略的影响 |
| P3 | 跑组2仓位对比（同信号不同仓位） | 0.5d | 确认最优仓位配置 |
| P4 | 汇总输出对比报告（含图表叠图） | 0.5d | 产出最终可读报告 |

### 2.5 已知注意事项

1. **回测区间统一**：所有对比必须使用相同的回测区间（如 2020-01-02 ~ 2025-05-15），否则绩效指标不可比。
2. **费用和滑点一致**：所有策略应该使用相同的费率模型和滑点设定。
3. **非做空限制**：如果标的为 A 股（如 601857），需确保所有策略按"只能做多"模式运行。
4. **样本量差异**：部分策略（如布林带突破）产生的交易次数可能显著少于 MA 策略，对比胜率时需考虑样本量。
5. **参数敏感性**：策略对比中的参数选择会影响结果。建议对关键参数做敏感性分析（如 MA 快慢线周期）。

---

## 附录: 策略代码文件索引

| 策略 | 文件路径 | 行数 |
|:-----|:---------|:----:|
| TrendStrategy | `backtest_engine/strategies/trend_strategy.py` | ~750 |
| ReversalStrategy | `backtest_engine/strategies/reversal_strategy.py` | ~900 |
| TrendPosition | `backtest_engine/strategies/trend_position.py` | ~850 |
| FactorCalculator | `backtest_engine/strategies/factor_calculator.py` | ~300 |
| RunTrend | `backtest_engine/strategies/run_trend.py` | 脚本 |
| RunReversal | `backtest_engine/strategies/run_reversal.py` | 脚本 |
| OptimizeTrendParams | `backtest_engine/strategies/optimize_trend_params.py` | 脚本 |
| OptimizeReversalParams | `backtest_engine/strategies/optimize_reversal_params.py` | 脚本 |
| ScanTrendParams | `backtest_engine/strategies/scan_trend_params.py` | 脚本 |
