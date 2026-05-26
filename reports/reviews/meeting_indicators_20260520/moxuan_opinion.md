<!--
author: 墨萱
created_time: 2026-05-20T20:39+08:00
role: 测试验收
-->

# 新增因子测试验收报告

> **议题：** 论证新增"成交额均价"和"实际换手率"两个股票数据因子的可行性和方案  
> **审查人：** 墨萱（测试验收）  
> **审查时间：** 2026-05-20T20:39+08:00  
> **审查依据：** 墨衡意见报告、BaseFactor 协议、FactorRegistry 源码、KnowledgeBridge 源码、Layer Q Spec、现有测试文件模式

---

## ═════════════════════ 综合验收结论 ═════════════════════

| 因子 | 墨衡结论 | 墨萱验收结论 | 风险等级 | 测试建议 |
|:-----|:---------|:------------|:---------|:---------|
| 因子1：成交额均价 | ✅ 可行，0.5人天 | **✅ 技术验收通过** | 🟢 低风险 | 2个测试模块 |
| 因子2：实际换手率 | ✅ 可行，1.5人天 | **⚠️ 有条件通过** | 🟡 中风险 | 4个测试模块+1个数据层验证 |

**验收核心意见：** 方案设计合理，但墨衡方案存在 3 个测试风险点和 1 个设计建议缺失，详见各节。

---

## ═════════════════════ 因子1：成交额均价（amount / volume）═════════════════════

### 1. 技术验收结论

**✅ 通过（条件：测试覆盖）**

| 验收项 | 状态 | 说明 |
|:-------|:-----|:------|
| 数据独立性 | ✅ | 零外部依赖，仅依赖已有 amount/volume 字段 |
| 计算复杂度 | ✅ | 一步除法，逻辑清晰 |
| 与VWAP关系 | ✅ | 墨衡已明确区分两者语义，非冗余 |
| 除零处理 | ✅ | `np.where(volume>0, ...)` 保护已设计 |
| 回滚兼容性 | ✅ | 全历史可回溯，零影响 |
| 测试可行性 | ⚠️ | 需补充测试用例（见下） |

### 2. 数据质量风险分析

| 风险场景 | 数据验证 | 量化指标 |
|:---------|:---------|:---------|
| volume=0（停牌） | 停牌日 amount 也为 0 | 除零已被保护，结果为 NaN，**不影响计算** |
| volume=0（数据缺失） | 需检查 amount ≠ 0 但 volume=0 的行数 | 使用 DB 查询 `SELECT COUNT(*) FROM stock_daily WHERE volume=0 AND amount!=0` — **建议墨衡执行一次** |
| 异常值（金额单位误解） | amount 单位是元还是万元？ | 查询 `SELECT AVG(amount/volume) FROM stock_daily` 确认均价落在合理范围（A股：5-500元） |
| 极端巨量/碎股 | 0.00X 元均价 | 自动被 NaN 保护覆盖 |

**⚠️ 墨衡遗漏风险：** 未验证 amount/volume 的单位一致性。需加一条验证：`avg_price = amount / volume` 的结果值域是否合理（A股约 3-3000 元），若出现 < 0.5 或 > 10000 的值，说明单位不一致或数据异常。

### 3. 测试方案（需补充到墨衡实施计划）

**测试模块 1：单元测试 — 计算正确性（test_avg_trade_price_compute.py）**

| 测试用例 | 输入 | 预期输出 | 测试目的 |
|:---------|:-----|:---------|:---------|
| TC1.1 基础计算 | amount=1e8, volume=1e6 | 100.0 | 正常均价计算 |
| TC1.2 除零处理 | volume=0, amount=任意 | NaN | 停牌/异常日保护 |
| TC1.3 双零情形 | volume=0, amount=0 | NaN | 停牌日优先保护 |
| TC1.4 大额计算 | amount=1e10, volume=1e4 | 1,000,000.0 | 高价股验证 (600519) |
| TC1.5 小数点精度 | amount=12345.67, volume=100 | 123.4567 | float64 精度验证 |
| TC1.6 None/NaN值注入 | volume 列为 None 或 NaN | NaN | 数据层异常传递保护 |
| TC1.7 value_range 验证 | 计算结果 > 10000 或 < 0.5 | 触发警告 | 单位不一致检测 |

**测试模块 2：集成测试 — FactorRegistry 注册与缓存（test_avg_trade_price_integration.py）**

| 测试用例 | 验证内容 |
|:---------|:---------|
| TC2.1 FactorRegistry.register("avg_trade_price") | 注册成功率 |
| TC2.2 compute_all() 返回包含 avg_trade_price | 批量计算可见性 |
| TC2.3 compute_category("volume") 包含 avg_trade_price | 分类计算可见性 |
| TC2.4 factor_cache 命中率 | 缓存键生成正确性 |
| TC2.5 unregister() 后 registry 不再返回 | 因子解除注册的完整性 |
| TC2.6 rolling_window=5 参数传参正确 | 可选参数验证 |
| TC2.7 与 VWAP 并存时互不干扰 | 因子间隔离性 |

### 4. 回滚兼容性验证要点

- [ ] 确认现有 VWAP 因子不受新因子注册影响
- [ ] 确认 `FactorRegistry._register_default_factors()` 不受影响
- [ ] 确认 `signal` 管道在 `compute_all()` 调用时不会因为新增因子抛出异常
- [ ] 确认 `factor_cache` 的 cache_key 生成不含冲突

---

## ═════════════════════ 因子2：实际换手率（turnover_rate）═════════════════════

### 1. 技术验收结论

**⚠️ 有条件通过（数据层验证完成 + AKShare 原生字段确认 + 测试覆盖）**

**前提条件：**
1. 墨衡必须在阶段一执行数据层验证（查询 DB 现有 turnover_rate 字段的精确分布）
2. AKShare 接口兼容层必须实现降级逻辑
3. 测试必须覆盖回滚场景

| 验收项 | 状态 | 说明 |
|:-------|:-----|:------|
| 计算逻辑 | ✅ | volume/circulating_shares 定义清晰 |
| 数据方案（路径A） | ⚠️ 有条件通过 | AKShare 原生 `换手率` 字段需验证可用性 |
| 数据层验证 | ❌ 未充分论证 | 墨衡仅指出 `market_daily` 中 3080 条 turnover_rate=0，但未说明：是否已通过 AKShare 拉取测试数据验证 `换手率` 字段不为空？ |
| 回滚兼容性 | ⚠️ 有条件 | 全量补填后需验证回滚点 |
| 字段命名歧义 | ⚠️ "成交额均价"已占用 avg_trade_price | 建议换手率注册名使用 `turnover_rate` 而非 `turnover` |

### 2. 数据质量风险分析（⚠️ 墨衡方案不充分部分）

**核心问题：墨衡未提供 AKShare `换手率` 字段的实测验证数据。**

| 验证项 | 墨衡声称 | 需补充验证 |
|:-------|:---------|:-----------|
| AKShare 接口 `换手率` 字段存在性 | "AKShare 返回换手率字段" | 👍 登录数据库执行 `SELECT * FROM stock_daily WHERE date='2026-03-15'` 确认字段值不为 0.0 |
| 字段类型一致性 | 未说明 | 验证 AKShare 返回的换手率是 % 值还是小数（0.05 vs 5.0） |
| 缺失覆盖 | 未说明 | 抽查 2020-2026 年随机 10 个交易日 × 随机 5 个标的，验证 turnover_rate 缺失率 |
| 新股/次新股数据 | 未说明 | 验证上市 < 60 天的标的的数据可获得性 |

**⚠️ ⚠️ 已确认的严重风险（墨衡未提及）：**

**风险 1：market_daily 表的 turnover_rate 字段被错误设置为 0.0（全部 3080 条）。**
- 这意味着：即使修改 column_map，如果 data loading 流程不对原 `turnover_rate` 列做覆盖更新，新增的 AKShare 原生值会被 DB 中残留的 0.0 值覆盖回 0。
- **必须**确保 data_source.py 的 upsert/insert 逻辑中包含 `turnover_rate` 字段的非零写入，或者在阶段一先执行 `UPDATE market_daily SET turnover_rate=NULL` 清空数据。

**风险 2：AKShare 接口兼容层** 
- 墨衡已设计降级逻辑，但未提供降级后的精度损耗评估（计算法 vs 原生字段的误差范围）。

### 3. 测试方案（比墨衡方案补充 2 个测试模块）

**测试模块 1：数据层验证（test_turnover_rate_data_quality.py）**

| 测试用例 | 验证内容 | 重要性 |
|:---------|:---------|:-------|
| T-TC1 覆盖对比 | 拉取 AKShare `stock_zh_a_hist()` 的 `换手率` 列，与现有 DB 中 turnover_rate 做逐行对比 | P0 |
| T-TC2 缺失比例 | 统计 2020-2026 年 601857 标的 turnover_rate 缺失比例（预期 < 1%） | P0 |
| T-TC3 值域验证 | 换手率 % 值在 (0, 100] 范围内（A股正常换手率） | P1 |
| T-TC4 单位确认 | 确认 AKShare 返回值是 % 格式（5.0 表示 5%）还是小数格式（0.05 表示 5%） | P0 |
| T-TC5 multi-symbol 抽样 | 对 10 个随机标的执行覆盖验证 | P1 |

**测试模块 2：因子计算单元测试（test_turnover_rate_compute.py）**

| 测试用例 | 输入 | 预期输出 | 测试目的 |
|:---------|:-----|:---------|:---------|
| T-TC2.1 基础计算 | turnover_rate=5.0（已填充） | 5.0 | 从列读取保持原值 |
| T-TC2.2 原生值存在时优先 | turnover_rate=5.0 > 0 | 5.0 | 数据层填充正确 |
| T-TC2.3 降级计算 | turnover_rate=0.0（需降级） | 使用兜底值 | 数据缺失下的降级验证 |
| T-TC2.4 rolling_mean(5) | 5 日换手率连续值 | 滚动均值正确 | 多窗口参数验证 |
| T-TC2.5 rolling_mean(20) | 20 日换手率 | 滚动均值正确 | 长周期验证 |
| T-TC2.6 新股缺失 | 前 5 天无 turnover_rate | NaN | 首阶段数据缺失处理 |

**测试模块 3：FactorRegistry 集成测试（test_turnover_rate_integration.py）**

| 测试用例 | 验证内容 |
|:---------|:---------|
| T-TC3.1 注册验证 | FactorRegistry 注册 `turnover_rate` 成功 |
| T-TC3.2 volume 族包含 | compute_category("volume") 包含 turnout_rate |
| T-TC3.3 与 avg_trade_price 共存 | 两者并存计算不冲突 |
| T-TC3.4 缓存键独立 | cache_key = "turnover_rate" 不与 "turnover" 冲突 |

**测试模块 4：回滚验证（test_turnover_rate_rollback.py）**

| 测试用例 | 验证内容 |
|:---------|:---------|
| T-TC4.1 全量补填后可回滚 | 若 turnover_rate 全量为 0 且全量补填后，回滚到空数据时的兜底逻辑可用 |
| T-TC4.2 stage-wise 回滚 | 分别测试阶段一/二/三的回滚点 |
| T-TC4.3 column_map 变更回滚 | 恢复 column_map 后数据管道正常 |

### 4. 回滚兼容性验证要点

- [ ] 数据层补填前，计算并记录 current_turnover_rate = 0.0 的记录数（基准线）
- [ ] 补填后再次计算，确认更新率 ≥ 99%
- [ ] 验证 `UPDATE market_daily SET turnover_rate=0.0` 回滚后，计算因子恢复到降级模式
- [ ] 确认 DAO 层的 upsert 逻辑在 turnover_rate 为 0.0 时不覆盖 NULL（否则无法区分"数据缺失"和"未拉取"）

---

## ═════════════════════ 与 KnowledgeBridge 的集成 ═════════════════════

### 1. 因子值进入知识库的路径

根据 KnowledgeBridge v2 的 harvest 流程：
```
FactorRegistry.compute_all() → scores dict → (可选) 存入 MethodResult.statistics 或 metadata
                                                      ↓
                                          KnowledgeBridge.harvest()
                                                      ↓
                                          KnowledgeEntry(statistics={...})
                                                      ↓
                                          KnowledgeNormalizer.normalize()
                                                      ↓
                                          K-V 存入 knowledge.db + BitableSync
```

**格式建议：**

```python
# 在 MethodResult 中挂载因子值
result.statistics.update({
    "avg_trade_price": 123.45,       # 成交均价（元）
    "turnover_rate_pct": 5.23,       # 实际换手率（%）
    "turnover_rate_deviation": 2.1,  # 换手率Z-Score（延伸因子，可选）
})
```

**注意：** `KnowledgeBridge.STATISTICS_MAPPING` 中尚无这两个因子的映射模板。需新增：

```python
STATISTICS_MAPPING.update({
    "avg_trade_price": ("avg_trade_price", "成交均价 {value:.2f} 元"),
    "turnover_rate_pct": ("turnover_rate_pct", "实际换手率 {value:.2f}%"),
})
```

### 2. 验证逻辑

KnowledgeNormalizer 在标准化时需增加：
1. **avg_trade_price 有效性检查**：值域 [0.5, 10000]，NaN 标记为缺失
2. **turnover_rate 有效性检查**：值域 (0, 100]，>30 标记为高换手（新股/事件驱动）
3. **两者联合检查**：若 avg_trade_price 与 close 偏差 > 5%，标记为"价格结构异常"信号

---

## ═════════════════════ Layer Q 维度补充分析 ═════════════════════

### 1. 对 Layer Q 评分体系的影响

| Q 维度 | 受影响？ | 说明 |
|:-------|:---------|:-----|
| Q1 Existence | ❌ 否 | 两者不修改交易频率或标的覆盖 |
| Q2 Robustness | ⚠️ 间接 | 换手率可用于识别标的流动性变化，影响参数的稳定性分布 |
| Q3 Regime | ⚠️ 间接 | 换手率变化可作为 regime 切换的前置信号 |
| Q4 Capacity | ❌ 否 | 不影响仓位容量 |
| Q5 Temporal | ⚠️ 间接 | 成交额均价时间序列稳定性可补充 TemporalValidator |
| Q6 OOS | ❌ 否 | 不影响样本外测试 |

### 2. 是否需要新增 Q 维度

**结论：不需要新增独立 Q 维度。**

理由：
- 这两个因子的核心功能是为信号生成层（Signal Layer）和因子族（Factor Registry）服务，而非直接为 Q 层审计服务
- 它们的影响落在现有的 Q1-Q8 审计管的输入侧（因子值更丰富 → 回测信号更精确 → Q 层审计质量更高），而非审计管本身
- 如果长期需要流动性监控，可在 Q5 Temporal Validator 的输入参数中加入换手率稳定性指标，而非新增维度

### 3. 层Q维度补充建议

建议在 Q2 Robustness Surface 或 Q5 Temporal Stability 中引入以下参数：

```
# Q5 参数补充（可选）
turnover_stability_token = {
    "turnover_rate_mean": df["turnover_rate"].mean(),
    "turnover_rate_std": df["turnover_rate"].std(),
    "turnover_rate_zscore_top": (df["turnover_rate"] > threshold).sum(),
}
```

---

## ═════════════════════ 对墨衡方案的风险点评估 ═════════════════════

### 墨衡方案已覆盖项 ✅

1. ✅ 数据源评估完整
2. ✅ 与现有因子的关系分析准确
3. ✅ 回滚兼容性分析合理
4. ✅ 实施顺序规划清晰
5. ✅ 预计算法结构正确

### 墨衡方案遗漏/不充分项 ❌

| # | 遗漏项 | 等级 | 影响 | 补充建议 |
|:-:|:-------|:-----|:-----|:---------|
| 1 | 未验证 amount/volume 单位一致性 | 🟡 中 | 若单位不一致，因子值可能偏差 1000 倍 | 需在阶段一中加入 value_range 验证：avg_price ∈ (0.5, 10000) |
| 2 | 未提及 DB 中 turnover_rate=0.0 的清理 | 🔴 高 | 全量补填后原始 0.0 值可能污染数据 | 阶段一必须先清空 turnover_rate 列再补填 |
| 3 | 未提供 AKShare `换手率` 字段的实测数据 | 🟡 中 | 方案依赖的核心假设未量化验证 | 建议墨衡先执行一次 Test Module 1（数据层验证）再推进 |
| 4 | 未考虑 `market_daily` 和 `stock_daily` 两表的同步 | 🟡 中 | 两表均有 turnover_rate 列，补填需同步 | 明确补填是对 `market_daily` 执行还是两表均执行 |
| 5 | 未提及测试工作量 | 🟡 中 | 墨衡估算 1.5 人天中未包含测试 | 建议增加 0.5 人天测试验证时间，总预估调整为 2.0 人天 |
| 6 | 未说明回滚数据保留策略 | 🟢 低 | 全量补填后难以恢复原始 0.0 状态 | 补填前备份 `market_daily` 表或插入测试标记 |

### 墨衡方案中的正确项 ✅

1. ✅ 路径 A（AKShare 原生字段）的推荐合理
2. ✅ 降级逻辑设计合理（列不存在 → 计算法 → 兜底）
3. ✅ 对于 VWAP 和 avg_trade_price 的语义区分准确
4. ✅ 实施阶段划分清晰（阶段一/二/三）
5. ✅ FactorRegistry 注册方案符合 BaseFactor 协议

---

## ═════════════════════ 实施建议与测试清单 ═════════════════════

### 建议实施顺序

```
Week 1              Week 2
────────         ────────
[因子1]             [因子2]
 ├─ 0.2人天       ├─ 0.5人天 阶段一：数据层验证+补填
 │  实现代码      ├─ 0.5人天 阶段二：Factor+注册
 ├─ 0.2人天       ├─ 0.5人天 阶段三：辅助因子+测试
 │  单元测试      └─ 0.3人天 回滚+兼容性测试
 └─ 0.1人天
    集成测试
```

### 验收通过条件清单

**因子1 通过条件：**
- [ ] 单元测试 TC1.1-TC1.7 全部 PASS
- [ ] 集成测试 TC2.1-TC2.7 全部 PASS
- [ ] amount/volume 值域验证通过（无异常值）
- [ ] FactorRegistry 注册正常

**因子2 通过条件：**
- [ ] 数据层验证（T-TC1.1-TC1.5）全部 PASS
- [ ] AKShare 接口兼容层实测通过
- [ ] DB 中 turnover_rate=0.0 已清空并补填
- [ ] 单元测试 T-TC2.1-TC2.6 全部 PASS
- [ ] 集成测试 T-TC3.1-TC3.4 全部 PASS
- [ ] 回滚测试 T-TC4.1-TC4.3 全部 PASS
- [ ] 两表（market_daily + stock_daily）补填一致性验证

---

## ═════════════════════ 总结 ═════════════════════

| 维度 | 因子1：成交额均价 | 因子2：实际换手率 |
|:-----|:-----------------|:-----------------|
| **技术验收** | ✅ 通过 | ⚠️ 有条件通过 |
| **风险等级** | 🟢 低 | 🟡 中 |
| **主要风险** | 单位一致性 | DB turnover_rate=0.0 清理 + AKShare 原生字段验证 |
| **预估工作量** | 0.5 人天 ✅（匹配墨衡） | **2.0 人天**（墨衡 1.5 + 补充 0.5 测试） |
| **测试模块数** | 2 | 4 |
| **层Q影响** | 无需新增维度 | 无需新增维度 |
| **KnowledgeBridge** | 需补充 mapping | 需补充 mapping + validation |

**最终意见：** 两个因子方案整体可行，技术路线选择合理。墨衡方案的质量较高，但需要在以下方面补充：
1. 数据层的 turnover_rate=0.0 清理（严重——必须执行）
2. amount/volume 值域验证（中等——建议执行）
3. 测试工作量从 0 增加到 0.5 人天（中——需纳入总预估）

若上述补充项全部完成，本项目可以放行。
