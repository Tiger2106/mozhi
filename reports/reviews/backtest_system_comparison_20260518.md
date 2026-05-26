# 回测系统技术状态对比报告

> **对比周期**: 2026-05-17 → 2026-05-18
> **作者**: 墨涵（基于墨衡分析摘要）
> **评级标准**: L0(无) / L1(部分) / L2(基本) / L3(完整) / L4(优化级)

---

## 一、各维度评级变化

| 维度 | 昨日 | 今日 | 跳变 | 说明 |
|:----|:----:|:----:|:----:|:-----|
| **因子模块** | L2 | **L3** | +1 | 4→18 因子模块，注册系统完整 |
| **策略方法** | L2 | **L3** | +1 | 10→13 种方法，+3 右侧顺势规范方法 |
| **风险模块** | L0 | **L3** | +3 | 从空白到 P0(4)+P1(2) 全量交付 |
| **数据库架构** | L1 | **L2** | +1 | 3/5 域完成迁移 |
| **路径标准化** | L1 | **L2** | +1 | Scheme A 全量实施 |
| **测试覆盖** | L2 | L2 | 0 | 持平（~12 新增） |
| **引擎能力** | L2 | **L3** | +1 | +Portfolio +Risk +Fusion 三层 |
| **知识桥梁** | L1 | **L2** | +1 | 全方法知识条目填充 |
| **模拟器** | L0 | **L1** | +1 | 基础框架搭建 |

---

## 二、功能详细对比

### 2.1 因子模块

| 对比项 | 昨日 | 今日 |
|:------|:----|:----|
| 总量 | ~4 个因子模块 | **18 个**因子模块 |
| 清单 | 未知 | MA / MACD / VWAP / ATR / Bollinger / OBV / Regime / Structure / TrendQuality / VolumeFlow / VolumeProfile / VolumeRatio / **AnchoredVWAP**(P1新增) |
| 因子注册系统 | ❌ 无 | ✅ `factor_registry.py` 全量注册 |
| 因子缓存 | ❌ 无 | ✅ `factor_cache.py` |

### 2.2 策略方法

| 对比项 | 昨日 | 今日 |
|:------|:----|:----|
| 总量 | ~10 种方法 | **13 种**方法 |
| 趋势策略 | 部分就位 | Bollinger / MACD / MA_Cross / VolumeProfile / Wyckoff(5种) ✅ |
| 反转策略 | 部分就位 | Reversal / Bias / RSI / KDJ(4种) ✅ |
| 网格策略 | 部分就位 | Grid(1种) ✅ |
| **右侧顺势3方法** | ❌ 无 | BreakoutRetest / Continuation / VolumePriceExpansion ✅ |

### 2.3 风险模块（今日最大进展）

| 模块 | 昨日 | 今日 |
|:----|:----|:----|
| 风险模块 | ❌ 完全不存在 | ✅ `risk/` 目录就绪 |
| DrawdownGuard | ❌ | ✅ 回撤断路器：8%预警/15%停止/保本模式 |
| VolatilityRiskManager | ❌ | ✅ ATR动态仓位管理（复用ATRFactor） |
| MarketStateFilter | ❌ | ✅ RANGE状态过滤趋势信号，联动RegimeAnalyzer |
| RiskPipeline | ❌ | ✅ 三模块编排 + enable_* 开关 |
| AnchoredVWAP | ❌ | ✅ 四种锚点类型 + σ通道 + 偏离度 |
| RegimeContextBuilder | ❌ | ✅ 四合一加权融合：Regime(40%)+VWAP(25%)+VP(20%)+KB(15%) |

### 2.4 数据库架构

| 域 | 昨日 | 今日 |
|:---|:----|:----|
| market/ | ❌ 散落各处 | ✅ `data/market/market_data.db` (475KB, 2标的) |
| factors/ | ❌ 旧路径 | ✅ `data/factors/factor_repository.db` (7.8MB, 36K行) |
| execution/ | ❌ 空壳 | 🔧 待迁移（94KB主库在旧路径） |
| knowledge/ | ✅ 已在位 | ✅ `data/knowledge.db` (3.5MB, 9表) |
| registry/ | ~已在位 | ✅ `data/registry/file_registry.db` (5.8MB, 7491条) |

### 2.5 引擎能力

| 能力 | 昨日 | 今日 |
|:-----|:----|:----|
| Bar-by-bar 主循环 | ✅ | ✅ |
| PortfolioManager | ✅ | ✅ + position_ratio 参数 |
| PortfolioIntegration | ✅ | ✅ + RiskPipeline 集成 |
| 信号融合 | ❌ | ✅ SignalFusion |
| 知识桥梁 | ~ | ✅ KnowledgeBridge v2 |
| 回撤计算 | 被动 | ✅ 主动 DrawdownGuard |

---

## 三、实现程度总评

### 按研究体系标准

| 阶段 | 昨日 | 今日 | 说明 |
|:----|:----:|:----:|:-----|
| S0 研究方案对齐 | L1 | **L2** | 已对齐右侧顺势3方法 + 风控要求 |
| S1 数据基础 | L2 | **L3** | 行情数据灌装完毕 |
| S2 因子计算 | L2 | **L3** | 18因子就位 |
| S3 策略信号 | L2 | **L3** | 13方法就位 |
| S4 风控模块 | L0 | **L3** | 最大进展，从零到完整 |
| S5 知识沉淀 | L1 | **L2** | KnowledgeBridge v2 |
| S6 集成流水线 | L1 | **L3** | RiskPipeline + SignalFusion |

### 总体评级

```
昨日总评: L2（基本级）— 引擎可用，但缺风控、路径混乱、数据散落
今日总评: L3（完整级）— 风控到位、路径标准化、数据收敛、测试覆盖
```

### 剩余差距（通往 L4 优化级）

| 项 | 当前状态 | 需要 | 优先级 |
|:---|:--------|:-----|:------:|
| 数据库迁移 | 3/5域完成 | trade/ 域名迁移 + calendar 归位 | P0 |
| 性能优化 | 未深入 | 大量回测时数据加载/因子计算的性能 | P2 |
| 参数优化 | 未开始 | 各策略参数自动寻优 | P2 |
| 实时接入 | 未开始 | 行情实时推送 + 信号实时生成 | P3 |
| 多标回测 | 单标可用 | 多标并行回测框架 | P3 |

---

_报告: 墨涵 | 2026-05-18_
