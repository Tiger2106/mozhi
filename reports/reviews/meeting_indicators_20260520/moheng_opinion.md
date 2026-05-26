<!--
author: 墨衡
created_time: 2026-05-20T20:34+08:00
-->

# 新增因子可行性论证报告

> **议题：** 论证新增"成交额均价"和"实际换手率"两个股票数据因子的可行性和方案
> **审查人：** 墨衡（架构审计）
> **审查时间：** 2026-05-20T20:34+08:00

---

## ═════════════════════ 因子1：成交额均价（amount / volume）═════════════════════

### 1. 数据源评估

| 评估项 | 结论 |
|:-------|:------|
| amount（成交额） | ✅ **已存在** — `stock_daily` 表和 `market_daily` 表均有 `amount REAL` 字段 |
| volume（成交量） | ✅ **已存在** — 两表均有 `volume REAL/INTEGER` 字段 |
| 是否需要新增数据源 | ❌ **不需要** |

**字段来源验证：**
- `stock_daily` 表结构：`code, date, open, high, low, close, volume INTEGER, amount REAL, adj_factor, created_at`
- `market_daily` 表结构：`symbol, trade_date, open, high, low, close, volume REAL, amount REAL, turnover_rate, PRIMARY KEY(symbol, trade_date)`
- 历史数据已就绪：601857 标的 `stock_daily` 含 3080 条记录（2020-2026），amount/volume 均有真实值

### 2. 计算复杂度

**极低（< 0.5 人天）。** 核心计算为一步除法：

```
avg_price = df["amount"] / df["volume"]
```

无需窗口计算、无需累计、无需外部数据。注意处理 volume=0 时导致的除零，加 `np.where(volume > 0, ...)` 保护即可。

### 3. 与现有因子的关系（关键判断）

**⚠️ 语义接近但不冗余。** 与现有 VWAP 因子存在结构性差异：

| 对比维度 | 现有 VWAP（vwap_factor.py） | 成交额均价（amount/volume） |
|:---------|:----------------------------|:----------------------------|
| 数据源 | `typical_price = (high+low+close)/3` × `volume`（估算） | `amount` = 交易所统计的实际成交总额 |
| 计算方式 | 周期内累加（cumsum / rolling） | 单日除法 |
| 精度 | **近似值** — typical_price 是 bar 级别的估算 | **精确值** — 交易所汇总的成交额/成交量 |
| 支持滚动窗口 | ✅ 支持多周期（5/10/20日） | ❌ 单日值，可扩展滚动均值 |
| 信号含义 | 机构持仓成本线（长期趋势） | 当日实际成交均价（短期） |

**核心结论：不是冗余，而是互补。**

现有 VWAP 回答"机构在一段时间内的平均持仓成本"；成交额均价回答"今天市场实际成交的平均价格"。两者的偏差（`amount/volume` vs `typical_price`）本身可以作为**价格结构信号**——若 `amount/volume` 显著高于 `typical_price`，说明今日成交在 bar 的高价位区间更活跃（买方主导）；反之说明低价位区间活跃（卖方主导）。

### 4. 回测兼容性

**完全兼容，零影响。**
- amount 和 volume 在历史数据中一直存在，2020-2026 全量可回溯
- 新增因子不会修改现有因子的计算逻辑
- 因子缓存机制（`factor_cache.py`）自动支持新因子的注册和缓存

### 5. 实现方案建议

**推荐方案：新增独立 Factor 类，注册到 FactorRegistry。**

```
新文件：backtest/factors/volume/amount_avg_price.py
类名：AmountAvgPriceFactor / AvgTradePriceFactor
注册：factor_registry.py volume 族 → "avg_trade_price"
可选参数：rolling_window（可选，默认1=单日）
```

**具体步骤（预估 0.5 人天）：**
1. 创建 `amount_avg_price_factor.py`，继承 `BaseFactor`（人天 0.2）
2. 注册到 `FactorRegistry`：`_register_fn("avg_trade_price", ...)`（人天 0.1）
3. 更新 `factors/volume/__init__.py` 导出（人天 0.1）
4. 单元测试（人天 0.1）

### 6. 风险评估

| 风险 | 等级 | 说明 | 缓解措施 |
|:-----|:-----|:------|:---------|
| 除零异常 | 🟡 低 | volume=0 时（停牌/极低流动性） | `np.where(volume>0, amount/volume, NaN)` |
| 数值溢出 | 🟢 极低 | amount/volume 量级正常 | float64 安全 |
| 误用风险 | 🟡 低 | 可能与 VWAP 混淆 | 文档区分两者语义 |

---

## ═════════════════════ 因子2：实际换手率（turnover_rate）═════════════════════

### 1. 数据源评估

| 评估项 | 结论 |
|:-------|:------|
| volume（成交量） | ✅ **已存在** |
| 流通股本（circulating_cap） | ❌ **数据库无此字段** — `stock_daily` 表不包含流通股本 |
| 流通市值（circulating_cap_market） | ❌ **数据库无此字段** |
| 是否需要新增数据源 | ✅ **需要** |

**现有基础设施：**
- `market_daily` 表虽然包含 `turnover_rate REAL` 列，但**所有 3080 条记录的值为 0.0**——这是一个空的占位列，从未实际写入数据
- `market_data_adapter.py` 已包含 `calc_turnover_rate()` 函数，提供三种回退逻辑：
  1. 有 `circulating_cap` 列 → `volume * close / circulating_cap * 100%`
  2. 无 `circulating_cap` → 用 `amount.rolling(120).sum() * 10` 估算
  3. 兜底 → `volume / volume.rolling(5).mean() * 0.5`

### 2. 计算复杂度

**中等（1-1.5 人天）。** 计算本身简单（`volume / circulating_shares`），但流通股本数据的获取是核心难点。

### 3. 与现有因子的关系

**无重复。** 当前因子列表中没有任何换手率相关的因子（因子列表：MA / MACD / ATR / VWAP / OBV / Volume Profile / RSI / Bollinger）。

系统已有类似概念：
- **VolumeRatio**（量比 = 当日成交量 / 5日均量）—— 衡量的是相对放量/缩量，与换手率完全不同的维度
- **OBV**（累积能量线）—— 量能的净方向，非比率

### 4. 流通股本数据源分析

获取流通股本（或流通市值）有三个可选路径：

#### 路径 A：AKShare 日线接口直接获取换手率（推荐 ⭐⭐⭐⭐⭐）

AKShare 的 `stock_zh_a_hist()` 返回中文字段 `换手率`，当前代码已映射到英文列名（`column_map` 中只映射了日期/开高低收/成交量/成交额）。**只需在 `column_map` 中添加映射：**

```python
column_map["换手率"] = "turnover_rate"
```

**优势：**

| 优势 | 说明 |
|:-----|:------|
| 零新增依赖 | AKShare 已经集成 |
| 全历史覆盖 | 2020-2026 历史数据全部可用 |
| 交易所原始值 | 流通股本是当日实际流通值 |
| 实现成本最低 | 仅 1 行映射 + 将字段写入DB |

#### 路径 B：AKShare 日线接口的 `流通市值` 字段

AKShare 有独立的 `stock_zh_a_hist_pre_minute` 和 `stock_zh_a_hist` 等接口返回 `流通市值`。
计算：`turnover = volume / (circulating_market_value / close_per_share)`。

**评估：** 不如路径 A 直接。换手率已是 AKShare 原生字段，无需二次计算。

#### 路径 C：自由流通股本（free float）

A 股的"流通股本"包含部分国有股份和战略配售，真正可供交易的"自由流通股"小于名义流通股本。但：
- AKShare 不提供自由流通股数据
- 需要额外数据源（Wind/同花顺/CSMAR）
- 建议：**第一阶段先用名义流通值，后续再精细化**

### 5. 回测兼容性

**有条件兼容。** 需注意历史数据的回溯：

**方案 A 的回滚可行性：**
- 如果采用 AKShare 原生 `换手率` 字段，历史数据可一次性全量补填（重跑 data loading 流程即可）
- 无需修改回测引擎
- 历史回测时，若某天换手率缺失，可用 `volume / estimated_shares` 兜底

**方案 B（计算法）的回滚可行性：**
- 需获取每个标的历史流通股本的系列数据（随时间变化，因增发/解禁/送股而变化）
- 流通股本逐年变动，需要处理股本变动事件的时间线对齐

### 6. 实现方案建议

**推荐方案：路径 A（AKShare 原生字段）→ 写入 market_daily 表的 turnover_rate 列**

```
阶段一（0.5 人天）：
1. 修改 data_source.py: 在 column_map 中增加 "换手率" → "turnover_rate"
2. 修改 market_data_adapter.py: 优先从 DataFrame 读取原生 turnover_rate
3. 重跑数据灌入流程，全量补填历史数据

阶段二（0.5 人天）：
4. 创建 backtest/factors/volume/turnover_rate_factor.py
   类名：TurnoverRateFactor，继承 BaseFactor
   参数：windows（支持滚动均值，如 5日/20日/60日均值）
5. 注册到 FactorRegistry：volume 族 → "turnover_rate"
6. 更新 volume/__init__.py

阶段三（0.5 人天）：
7. 创建辅助因子：turnover_rate_zscore（换手率异常值检测）
8. 单元测试覆盖
```

### 7. 风险评估

| 风险 | 等级 | 说明 | 缓解措施 |
|:-----|:-----|:------|:---------|
| AKShare 接口字段变更 | 🟡 中 | AKShare 修改 column_map 中的字段名 | 增加接口兼容层，字段不存在时降级到计算法 |
| 流通股本因股权变动变化 | 🟡 中 | 增发/送股/解禁导致流通股本变化 | AKShare 原生 `换手率` 字段已含此调整 |
| 数据缺失（新股/次新股） | 🟢 低 | 上市初期换手率异常高 | 结合流通市值做异常值过滤 |
| 复权一致性 | 🟡 中 | 前复权/后复权的流通股本与原始换手率的关系 | 使用前复权数据时流通股本不需调整（AKShare 接口自带 adjust 参数） |

---

## ═════════════════════ 综合结论与建议 ═════════════════════

### 可行性结论

| 因子 | 可行性 | 优先级 | 预估工作量 | 置信度 |
|:-----|:-------|:-------|:----------|:-------|
| 因子1：成交额均价 | **✅ 可行，推荐立即实施** | P0 | 0.5 人天 | 高 |
| 因子2：实际换手率 | **✅ 可行（路径A），推荐立即实施** | P0 | 1.5 人天 | 高 |

### 实施顺序

```
Week 1        Week 2
──────        ──────
因子1 + 阶段一  因子2 阶段二
(0.5 天)  →    (0.5 天)
因子2 阶段一    因子2 阶段三
(0.5 天)       (0.5 天)
```

### 架构注意事项

1. **因子注册一致性**：两个因子都应走 `BaseFactor` 继承 + `FactorRegistry` 注册的标准化路径，与现有 6 因子族协议一致
2. **Signal 管道重用**：新增因子可以直接被现有 Signal 层消费（通过 `factor_registry.compute_all()`），无需修改 Signal 协议
3. **KnowledgeBridge 兼容**：新增因子会自动进入知识沉淀流程（参数范围、稳定性记录）
4. **因子缓存**：`factor_cache.py` 的 cache_key 应包含 `avg_trade_price` 和 `turnover_rate`，避免因子冷启动时的高频计算

### 预计算法结构

```python
# 因子1：成交额均价
class AvgTradePriceFactor(BaseFactor):
    FACTOR_META = {
        "name": "avg_trade_price",
        "category": "volume",
        "default_params": {"rolling_window": 1, "smoothing": "raw"},
    }
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        # avg_trade_price = amount / volume
        result = np.where(df["volume"] > 0, df["amount"] / df["volume"], np.nan)
        return pd.DataFrame({"avg_trade_price": result}, index=df.index)

# 因子2：实际换手率
class TurnoverRateFactor(BaseFactor):
    FACTOR_META = {
        "name": "turnover_rate",
        "category": "volume",
        "default_params": {"windows": [1, 5, 20]},
    }
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        # turnover_rate 直接从 DataFrame 列读取（由数据层填充）
        # 支持滚动均值
        result = {}
        for w in self.params.get("windows", [1]):
            if w == 1:
                result[f"turnover_rate"] = df.get("turnover_rate", 0.0)
            else:
                result[f"turnover_rate_{w}"] = (
                    df["turnover_rate"].rolling(w).mean()
                )
        return pd.DataFrame(result, index=df.index)
```

---

## 附录A：相关代码路径速查

| 组件 | 路径 |
|:-----|:------|
| 日线行情表 | `data/market/market_data.db` → `stock_daily` 表 |
| 日线行情表v2 | `data/market/market_data.db` → `market_daily` 表（含 turn_rate 占位列） |
| 现有VWAP因子 | `src/backtest/factors/volume/vwap_factor.py` |
| 因子基类 | `src/backtest/factors/base.py` |
| 因子注册表 | `src/backtest/factors/factor_registry.py` |
| 因子缓存 | `src/backtest/factors/factor_cache.py` |
| 数据源 | `src/backtest/data_source.py`（AkshareDataSource） |
| 数据适配器 | `src/backtest/data/market_data_adapter.py`（已有 turn_rate 辅助方法） |
| 因子族目录 | `src/backtest/factors/volume/` |
