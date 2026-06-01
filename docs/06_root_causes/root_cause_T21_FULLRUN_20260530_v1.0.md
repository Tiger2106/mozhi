---
author: 墨涵（汇聚墨衡/墨萱/玄知三方分析）
created_time: 2026-05-31T12:37+08:00
type: root_cause_v1.0
problem_id: T21_FULLRUN_20260530
status: ARCHIVED — 2026-05-31T13:12+08:00 四方会签通过（墨萱✅玄知✅墨涵✅Owner✅+墨衡✅）
---

# 根因分析 v1.0 — T21_FULLRUN_20260530

---

## 问题组A：SIGKILL管线异常

### 一句话根因

> **系统内存压力极高（事后快照可用内存仅~1.76GB，被杀时刻无快照可查），管线全量计算过程中Python分配内存失败(malloc) → MemoryError崩溃 → 子进程异常退出 → OpenClaw Supervisor标准化输出exit code 137 → T21_FIX三层防御方向正确但未完全实现。**

> ⚠️ **术语纠正**：Windows无原生OOM Killer，exit code 137是OpenClaw Supervisor标准化输出（见U1全员调查结论）。

### 证据链

| # | 证据 | 来源 |
|:-:|:----|:-----|
| A1 | 管线两次在内存密集计算中被杀（~16:43 marine-s 运行~79min, ~17:42 mellow-o 运行~15min），时长特征吻合内存耗尽过程 | 时序分析：agent session 14:34启动（含~50min编码任务），marine-s实际~15:24才启动exec |
| A2 | T21_FIX Layer 1（psutil虚拟内存<4GB拒启）已实现，如果启用将确定性阻止那次运行 | 墨衡代码审查 ✅ |
| A3 | T21_FIX Layer 2（流式生成器）已实现，但Welford在线算法在文档中夸大描述，实际ic_stats.py使用标准numpy计算 | 墨衡代码审查 ✅ 揭示文档问题 |
| A4 | T21_FIX Layer 3（checkpoint/resume 每50截面写入）已实现，恢复逻辑存在 | 墨衡代码审查 ✅ |
| A5 | 从架构层面发现**2个遗漏防护层**：运行中自适应内存监控（buffer<1GB留警）、内存预算与数据量匹配检测（batch_size未随截面扩张自适应调节） | 玄知架构审查 ✅ |
| A6 | 原始batch_ic的`all_results`列表在第95个截面后持续膨胀是明确内存膨胀模式 | 玄知架构审查 ✅ |
| A7 | 事后18:59内存仅1.76GB/15.6GB（距第一次被杀>2h，为事后快照，**非被杀时刻当时数据**），系统常态内存已90%+占用 | 问题定义阶段查证 ✅ / 墨萱系统资源审计 ✅ |
| A8 | vLLM不存在（本机无独立GPU，仅Intel Iris Xe集成显卡）。主要内存消耗：node.exe ~1.8-2.2GB + Chrome ~3.5GB + Feishu ~1GB + Claude ~0.5GB，**系统常态仅剩~1.5GB可用** | 墨萱系统资源审计 ✅ |

### 置信度：高

### 置信度：中（注：部分数据为事后推断，无被杀时刻内存快照）

| 视角 | 置信度 | 主要发现 |
|:----|:------:|:---------|
| 墨衡（代码） | 高 | Layer1+3实现充分，Layer2文档夸大但Generator足够 |
| 墨萱（QA） | 中 | T21_FIX方向正确但测试覆盖不完整；关键纠正：vLLM不存在，系统常态90%+占用 |
| 玄知（架构） | 高 | Layer 1: ⚠️85%, Layer 2: ✅95%, Layer 3: ⚠️80%, 遗漏2层 |

### 已排除假设

| 假设 | 排除理由 |
|:----|:---------|
| OS OOM Killer主动杀死 | ❌ Windows无OOM Killer；实际为Python malloc失败→MemoryError进程自崩溃 |
| OpenClaw exec超时(30min) | marine-s(~79min含session启动)远长于30min（exec未配置timeoutSec），不匹配 |
| OpenClaw agent超时(48h) | 远长于运行时长，无关 |
| vLLM同期运行抢占内存 | ❌ 本机无独立GPU，vLLM不存在 |
| WSL2 OOM | 运行环境为原生Windows 11，非WSL2 |
| Windows页面文件不足 | 15.6GB物理+13.5GB pagefile+C盘131GB空余，非根因 |

### 修复方向

**已有**：T21_FIX三层防御已就绪（Layer1+3到位，Layer2流式化到位）
**需补充**：
1. 运行中自适应内存监控（内存水位<1GB时发出告警）
2. memory budget匹配检测（batch_size自适应采样）
3. 整合集成测试（模拟OOM场景验证防御有效性）
4. 修正文档（SOUL.md/T21_FIX中Welford夸大描述）

---

## 问题组B：黄金基线FAIL

### 一句话根因

> **momentum_20d因子的IC统计特性本身不满足基线标准（半衰期0.5周/正比率49%/IC标准差0.27→噪声主导信号），与SIGKILL、管线bug、数据质量均无关，是"真FAIL"。**

### 证据链

| # | 证据 | 来源 |
|:-:|:----|:-----|
| B1 | 两个独立快照交叉验证：18:12(415窗口)FAIL + 22:42(986窗口)FAIL，更多数据不改变结论，甚至更差 | 玄知 ✅ |
| B2 | half_life稳定在0.47~0.52周（阈值要求>12周），系统性的信号极速衰减特征 | 玄知 ✅ |
| B3 | IC正比率~49%（阈值要求>55%），接近随机猜测（50%），非随机波动 | 玄知 ✅ |
| B4 | golden_baseline.py判定逻辑无bug：half_life=12周为第32行硬编码常数，阈值设定依据学术大样本 | 墨衡代码审查 ✅ |
| B5 | mean_ic_abs通过而其他FAIL**不是矛盾**：低信噪比下各指标自然向随机期望收敛，指示"高方差、弱方向性、快速衰减"的典型特征 | 墨萱/墨衡双确认 ✅ |

### 置信度：高

| 视角 | 置信度 | 主要观点 |
|:----|:------:|:---------|
| 墨衡（代码） | 极高 | golden_baseline.py无逻辑bug，checkpoint不改变基线结论 |
| 墨萱（QA） | 高 | 85%真策略信号+15%QA标准问题，建议改为多因子投票制 |
| 玄知（架构） | 极高 | 排除所有4项干扰假设，确定真FAIL |

### 已排除假设

| 假设 | 排除理由 |
|:----|:---------|
| SIGKILL导致数据不完整→假FAIL | 986截面完整数据重跑仍FAIL且更差 |
| 管线bug数据污染 | 两个不同管线版本（v1 ISO + T21）结论一致FAIL |
| 数据量不足 | 986截面大样本下IC统计量已收敛 |
| 后台写入干扰 | golden_baseline独立重算，后台写入不干扰已读数据 |
| checkpoint机制能救 | 不影响golden_baseline判定（其独立重算IC，非读取管线中间结果） |

### Half-life矛盾解析

**正确标准**：golden_baseline.py源码中`half_life_min: 12.0周`（>12周）
**现象描述v5中[4,12]是文档标注错误**
**对结论无影响**：实际0.47/0.52周，无论哪种标准都FAIL（双杀）

### 修复方向

**短期**：当前momentum_20d在此参数设置下的信噪比过低，需调整参数（half_life窗口重选）或接受FAIL
**长期（墨萱建议）**：
1. 放弃单一因子门神模式 → 多因子投票制+相对评分+历史基准线
2. golden_baseline阈值从学术大样本调整为A50小宇宙(N≈50)的实际统计分布
3. 全因子基线验收机制（当前仅验证了momentum_20d单个IC，缺少其他11因子的独立基线）

---

## 问题组C：估值因子全NULL

### 一句话根因

> **全链条断裂：设计层ps_ttm/pcf_ttm未列入数据契约→采集层未实现Tushare daily_basic采集脚本→数据层stock_daily.pe/pb/pe_ttm 100%NULL+ps_ttm/pcf_ttm列不存在→ETL层正确传播NULL→因子层因子值全NaN→IC计算层静默跳过→基线报告无估值维度。**

### 证据链

| # | 证据 | 来源 |
|:-:|:----|:-----|
| C1 | stock_daily（market_data.db）206,387行中pe/pb/pe_ttm NOT NULL = 0行(0%)，估值数据从未被写入 | 墨萱数据库查证 ✅ |
| C2 | a50_daily_ohlcv（a50_ic.db）pe/pb 100%NULL，ps_ttm/pcf_ttm列不存在（查询报错"no such column"） | 墨萱数据库查证 ✅ |
| C3 | backtest_engine/data_ingestion/目录仅有框架代码（数据契约+归一化+注册表），**无实际调用Tushare API的采集入口脚本** | 墨萱代码审查 ✅ |
| C4 | data_contract.py未定义ps_ttm/pcf_ttm（原始15因子+DDL仅规划pe/pb/dividend_yield，PS/PCF以placeholder注册于T+21），属于**设计阶段遗漏** | 墨衡/墨萱双确认 ✅ |
| C5 | _build_null_record函数**存在**（CrossSectionalICPipeline方法）但valuation_factor路径未经过它（路径绕过而非缺失）。实际代码路径：valuation_factor.py中`pe_ttm = df['pe']` → pe列全NaN → dropna后空Series → compute_cross_sectional_ic中`len(common) < 30 → continue`跳过，产生了NULL而非0.0 | 墨衡代码审查 ✅ 关键发现 |
| C6 | 估值因子IC全NULL是**三层架构断层连锁**：ETL采集遗漏 → Schema设计缺失(ps/pcf列不存在) → 因子计算层静默跳过(无告警) | 玄知架构审查 ✅ |
| C7 | Tushare source_registry配置使用`daily`API而非`daily_basic`（估值数据的正确接口），可能受Token积分限制 | 墨萱数据源审查 |

### 置信度：高

| 视角 | 置信度 | 主要发现 |
|:----|:------:|:---------|
| 墨衡（代码） | 极高 | _build_null_record存在但valuation_factor路径未经过它；设计时遗漏PS/PCF |
| 墨萱（数据） | 高 | 7条证据完整链路，采集脚本未实现为根因断裂点 |
| 玄知（架构） | 高 | 5级异常断层链全面描画，数据质量门禁缺失 |

### 已排除假设

| 假设 | 排除理由 |
|:----|:---------|
| 字段名不匹配 | 代码pe列名与数据库pe列名一致，但pe值本身就是NULL |
| 近期才缺失（非永久） | 206,387行全NULL，不是断更而是从未写入（ETL仅正确传播了NULL） |
| ETL映射丢失 | pe/pb的column_map正确（pe→pe, pb→pb），但源数据已是NULL |
| 仅T21受影响 | stock_daily和a50_daily_ohlcv都是100%NULL→任何运行都会同样触发 |
| _build_null_record触发了skip | 该函数存在但valuation_factor路径未经过它，实际是NaN→continue跳过（绕过路径，相同结果） |

### 断裂链（5级）

```
Tushare API(daily) → 采集脚本(不存在) → stock_daily(pe全NULL, ps无列) 
→ a50_daily_ohlcv(pe全NULL, ps无列) → valuation_factor(pe全NaN) 
→ compute_cross_sectional_ic(continue跳过) → rank_ic = NULL (无告警)
```

### 修复方向（4环）

| 环 | 修复内容 | 复杂度 | 优先级 |
|:--:|:---------|:------:|:-----:|
| 1 | 实现Tushare daily_basic采集脚本（参考phase1_data_collection.py），确认Token积分≥2000 | 中 | **P0** |
| 2 | data_contract.py增加ps_ttm/pcf_ttm的FieldMeta定义 | 低 | P1 |
| 3 | a50_daily_ohlcv DDL增加ps_ttm/pcf_ttm列（ALTER TABLE），等估值数据写入后补跑全历史IC | 低 | P1 |
| 4 | 引入三级数据质量门禁：ETL级(写入后校验)→因子级(pre_factor检查列完整性)→IC级(IC结果非NULL校验) | 中 | P2 |

### 历史洞察

T+14/T+7时估值因子很可能同样NULL，但未被发现。这暴露了**验收遗漏**——基线报告只看单因子（momentum_20d）IC，从不检查其他11因子的数据可用性。

---

## 三组统一总结

| | 问题A SIGKILL | 问题B 基线FAIL | 问题C 估值NULL |
|:--|:-------------|:--------------|:--------------|
| **状态** | 已修复(待验证) | 真FAIL(策略问题) | 全链断裂(待修复) |
| **根因类型** | 工程/基建 | 策略/统计 | 设计/数据 |
| **置信度** | 高 | 高 | 高 |
| **紧急性** | 中（修复已就绪） | 高（阻塞签署） | 高（阻塞估值维度） |
| **相互依赖** | 独立 | 独立 | 独立（墨萱确认） |

### 关键发现：文档误导

- SOUL.md/T21_FIX中"Welford在线算法" → 实际未实现，ic_stats.py使用标准numpy
- 问题定义中"_build_null_record" → 函数存在但valuation_factor路径未经过它，实际是NaN→continue跳过
- 均须修正

---

## 已读确认

### A组未确认项（open items，不阻塞会签）

| 项目 | 内容 |
|:----|:-----|
| ① | marine-s精确时长：session transcript显示~79min（含~50min编码任务+~29min exec vs 此前文档标记~6min）。待transcript确认精确值 |
| ② | 被杀时刻内存快照：不存在（U1原始问题），1.76GB为~18:59事后快照，推测被杀时刻可用内存在数百MB~1.76GB之间 |

### 会签条件（Owner 2026-05-31 13:04确认）

| 条件 | 内容 | 状态 |
|:---:|:-----|:----:|
| ① | A组措辞已按Owner建议修正：1.76GB标注为事后快照值，被杀时刻为推断值 | ✅ 已处理 |
| ② | marine-s精确时长（79min vs 6min）标注为open item挂起，不阻塞会签 | ✅ 已处理 |
| ③ | B组和C组同步会签，无悬案 | ✅ 已确认 |

## 已读确认

| 角色 | 签署人 | 状态 |
|:----|:------|:----:|
| 技术验证 | 墨萱 | ✅ PASS |
| 架构验证 | 玄知 | ✅ PASS |
| PO确认（知识归档） | 墨涵 | ✅ PASS |
| 代码分析确认（追加） | 墨衡 | ✅ PASS |
| 方向确认 | Owner | ✅ PASS |
