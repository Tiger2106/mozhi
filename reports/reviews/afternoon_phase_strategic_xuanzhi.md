<!--
author: 玄知 🖋️
version: 1.0
created_time: 2026-05-16T12:52:00+08:00
task: afternoon_phase_strategic_review
based_on: afternoon_phase_summary_moheng.md, afternoon_phase_review_moxuan.md
-->

# 下午阶段战略评估报告

**评审人**: 玄知 🖋️
**评审时段**: 2026-05-16 11:55 ~ 12:39
**角色**: 技术把关

---

## 1. 整体评估

下午 6 项变更呈现一个清晰的技术线路图：**基础设施先行，模块分离跟进，知识库功能闭环**。

从战略视角看，这组变更的节奏感不错——import 路径重构是基石（否则后续模块迁移会不断改 import），trade_pairing 分离是职责清晰化，B1 修复是技术债务清理，三者完成后才跑端到端流水线验证和 knowledge_run_links 激活。链条逻辑成立。

**独立验证确认**：
- knowledge_run_links 实际数据为 **694 条** ✅（墨萱早前查到的 0 条已在 11:55~12:39 窗口内修复落地）
- market_context 回填 500/694 条 ✅
- 99 项 pytest 全部通过 ✅

**全局判断**：本阶段成果扎实，无架构级问题，数据完整性关键指标已通过验证。

---

## 2. 关键风险

### 2.1 架构层面——🟢 低风险

| 风险项 | 评估 |
|:-------|:----:|
| import 路径重构范围 | 71+5+4 文件，216+ import 统一为 `from backtest.xxx`，无 circular import。重构后 pip install -e . 安装验证通过 |
| trade_pairing 模块化 | 职责分离设计合理。`performance.py` 通过 `# noqa: F401` 向后兼容，过渡期内不会破坏调用方 |
| B1 修复 | 仅改变执行时机，不影响输出行为。纯增益 |
| 架构层级一致性 | 无。6 项变更均在各自层次内完成，未引入跨层耦合 |

### 2.2 数据完整性——🟡 中等风险

| 风险项 | 评估 |
|:-------|:----:|
| **knowledge_run_links** | 当前 694 条已落地 ✅（验证确认）。关键发现已修复，风险降级 |
| **market_context 194 条未回填** | 500/694 已回填，剩余 194 条因行情数据缺失被 `_estimate_market_regime()` 返回 `unknown` 而跳过。这些记录的 market_regime 为默认值 `"any"` |
| **聚合偏差风险** | `aggregate_knowledge()` 当前按 market_regime 分组，`"any"` 会与特定 regime 数据混在一起。假如某策略在 trending_up 和 trending_down 环境下表现相反，"any" 组会掩盖这个分化。**但当前 10 条 knowledge_entries 中有 8 条已正确分配 market_regime，偏差可控** |
| **知识条目数** | 16 条 → 聚合后 10 条（6 条因去重/合并被消除），逻辑合理 |

### 2.3 生产就绪度——🟡 中等风险

| 风险项 | 评估 |
|:-------|:----:|
| **端到端流水线** | 回测→入库→聚合→运维全链验证通过 ✅ |
| **file_lifecycle 注册** | 12 个新文件（trade_pairing.py 等）未注册到 file_lifecycle。`check_unregistered_files` 每次巡检都会报出。不影响运行，但长期积累会降低审计可信度 |
| **TestFeeModelFix** | 3 项 legacy 失败测试（知识库评审前已有），本阶段未触及。需确认是否影响生产决策——fee model 计算出错会导致盈亏统计偏差 |
| **P0 灰度** | 如果今天跨 P0 里程碑，194 条 market_context 缺失 + 12 个文件未注册 + TestFeeModelFix 3 项失败这三项总计构成风险，建议先修复再灰度 |

---

## 3. 遗留项优先级

基于 **"生产可运行 + 数据可信"** 的战略视角，我的排序与墨衡有所不同：

| 优先级 | 项 | 说明 | 我的排序理由 |
|:------:|:---|:-----|:------------|
| **🔴 P0** | TestFeeModelFix 3 项修复 | fee model 直接决定盈亏计算准确性。如果当前 fee applied 的行为不符合预期（零手续费场景就有异常），那所有回测结果中的 net_profit 都不可信。**这是影响全局的 Accuracy 问题** |
| **🔴 P0** | 重新评估 market_context 缺失对聚合的影响 | 194 条 "any" 记录是否正在污染下游知识聚合？建议在 `aggregate_knowledge()` 中增加 `WHERE market_regime != 'any'` 过滤，或在回填完成前对 "any" 记录做标记跳过聚合 |
| **🟡 P1** | market_context 剩余 194 条回填 | 需要扩展行情数据覆盖窗口后再运行 `backfill_market_context()` |
| **🟡 P1** | file_lifecycle 注册更新 | 低技术债但高频触达——每次巡检报 12 个 unregistered 文件会降低运维效率 |
| **🟢 P2** | `aggregate_knowledge()` 自动化触发 | 当前流程需要手动执行，建议接入 cron 定时任务使其在每次回测结束后自动触发 |
| **🟢 P3** | 脚本入口统一为包级调用 | `python -m scripts.xxx` 替换 `sys.path.insert(0)`，长期维护收益 |

**与墨衡排序的核心差异**：
- 我将 **TestFeeModelFix** 提至 P0。fee model 是回测的基石，3 项失败中包含了 `test_fee_zero_quantity`（零数量场景），`test_fee_at_minimum`（最低手续费边界）和 `test_fee_above_minimum`（正常计算）。如果零数量场景下 fee 非零，说明 fee_model 在边界条件下行为异常，可能导致微仓或清仓后的残留手续费错误。
- market_context 回填的优先级我建议先评估**影响**再决定**何时做满**。如果 194 条 "any" 记录不影响当前知识聚合的 Top-K 结果，可以降级到 P2。

---

## 4. 评审结论

| 维度 | 评价 |
|:-----|:----:|
| 变更质量 | ✅ 高质量。import 重构、模块分离、B1 修复三件套干净利落 |
| 数据完整性 | ✅ 已确认。knowledge_run_links 694 条实际落地，market_context 500 条 |

```
REVIEW_RESULT = CONDITIONAL_PASS
```

**条件**：
1. **TestFeeModelFix** 需在下一阶段修复，确认 fee model 的精度不会导致回测失真
2. **market_context "any" 影响**需评估。在剩余 194 条回填完成前，确认聚合逻辑不会因 "any" 导致biased结论
3. 上述两个条件满足后，可升级为 `PASS`

**理由**：代码质量层面无缺陷，所有变更按预期工作。但 fee model 的 3 项失败是 P0 级数据准确性隐患，在未确认不影响回测结论之前不宜标记为 `PASS`。

---

*战略评估由玄知 🖋️ 于 2026-05-16 12:52 出具*
*结论：CONDITIONAL_PASS，需解析 TestFeeModelFix + market_context any 影响*
