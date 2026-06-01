---
reviewer: 墨萱 (moxuan)
reviewed_at: 2026-05-30 20:55+08:00
type: design_review
document: solution_plan_t21_20260530.md
author: moheng
conclusion: CONDITIONAL APPROVE
---

# T+21修复方案 · 技术评审报告

## 结论：CONDITIONAL APPROVE

4项条件满足后，方案可执行（见下方条件清单）。

---

## 一、技术合理性评估

### 问题1：OOM/SIGKILL — 管线内存优化

| 修复点 | 技术合理 | 说明 |
|:-------|:-------:|:-----|
| 1a 内存健康检查 | ✅ | 简单有效，psutil 成熟库，第一道防线无副作用 |
| 1b scheduler 流式聚合 | ✅ | 消除 M1+M2 累积是正确的方向 |
| 1c pipeline → generator | ✅ | 正确方案，但需关注**向后兼容**（见回归风险段） |
| 1d checkpoint/resume | ⚠️ | 设计良好（原子写 tmp+replace），**但工时偏紧** |
| 1e factor 加载优化 | ⚠️ | ROW_NUMBER() 方案需要 SQLite >= 3.25；`groupby.tail()` 方案自身消耗内存，建议放弃 |
| 1f 内存 profiler | ✅ | 轻量、实用、无副作用 |

**关键发现：**

1d checkpoint 的 `pipeline_id` 机制未定义。JSON 中存了 `pipeline_id` 但实际 `_pipeline_id()` 方法未在文档中定义——需确认是 hash(config) 还是 instance id。如果重启后 pipeline_id 变化，checkpoint 续跑会失效。

1e 的 `ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC)` 方案技术上正确，但需确认运行环境的 SQLite 版本。建议在部署前执行 `SELECT sqlite_version();` 确认 ≥ 3.25.0。

### 问题2：黄金基线 FAIL

| 修复点 | 技术合理 | 说明 |
|:-------|:-------:|:-----|
| 2a 阈值统一 | ✅ | 正确识别了验证脚本 vs 需求文档的矛盾。建议采纳后提交 Owner 书面确认 |
| 2b 基线重算 | ✅ | 无争议 |
| 2c 诊断输出 | ✅ | 纯新增，增强可维护性 |
| 2d 一致性校验 | ✅ | 重要的质量门 |

**关键发现：**

2a 阈值方案目前仍在"建议"阶段。方案B（1-8周）未经实证数据校准就提交执行，存在"换阈值直到PASS"的风险。建议要求：**在执行前提交 Owner 书面确认选择哪个方案**，并在报告中记录 Owner 的决策依据和决策时间。

### 问题3：估值因子 IC=0

| 修复点 | 技术合理 | 说明 |
|:-------|:-------:|:-----|
| 3a 临时移除 | ✅ | 正确做法，注释+贴 TODO 是标准操作 |
| 3b-i DDL 补全 | ✅ | ALTER TABLE ADD COLUMN 安全 |
| 3b-ii ETL 扩展 | ✅ | 但依赖数据源确认，目前是占位 |
| 3b-iii 替代数据源 | ⚠️ | 明确标注"待评估"，诚实评估 |
| 3b-iv hydration check | ✅ | 纯新增，无破坏性 |

---

## 二、回归风险评估 ⚠️（T+14已测试功能）

### 最大风险点：`run_batch()` 改为 generator

**风险等级：MODERATE — 需确认所有调用方已适配**

当前方案描述：
> "向后兼容方案：保留 `run_batch()` 方法（生成器版本），scheduler 自动适配。不删除旧方法签名。"

**这是误导性描述**。将 `run_batch()` 从 `list` → `generator` 是**签名变更**：
- 原行为：`results = pipeline.run_batch(...)` → `results` 是 list
- 新行为：`results_iter = pipeline.run_batch(...)` → 需要 `for r in results_iter:` 消费

即使保留方法名不变，以下场景会直接报错：
| 场景 | 旧代码 | 新代码下的行为 |
|:-----|:-------|:-------------|
| `len(results)` | 正常 | ❌ `TypeError: object of type 'generator' has no len()` |
| `results[0]` | 正常 | ❌ `TypeError: 'generator' object is not subscriptable` |
| `results.append(...)` | 正常 | ❌ 不报错但不会生效 |
| `json.dumps(results)` | 正常 | ❌ `TypeError: Object of type generator is not JSON serializable` |

**需要确认**：

1. 当前 T+14 已测试通过的代码中，**除 `scheduler.py` 之外是否还有其他模块调用 `run_batch()`？**
2. 如果存在其他调用方，应改为**新增** `run_batch_generator()` 方法，保留旧 `run_batch()` 返回 list。

### 其他文件回归风险

| 修改文件 | 风险等级 | 说明 |
|:---------|:-------:|:-----|
| `cross_sectional_ic_pipeline.py` | ⚠️ MODERATE | run_batch 签名变更 + checkpoint 新方法 |
| `scheduler.py` | ⚠️ MODERATE | _aggregate_summary 签名变更 |
| `requirements.txt` | ✅ LOW | 新增 psutil 依赖，不影响已有功能 |
| `validate_golden_baseline.py` | ✅ LOW | 阈值常量变更 + 纯新增函数 |
| `registry.py` | ✅ LOW | 注释掉注册行，可逆操作 |
| `valuation_factor.py` | ✅ LOW | 纯新增 `_check_hydration` |
| `schema.py` | ✅ LOW | ALTER TABLE ADD COLUMN，不影响已有数据 |

---

## 三、测试覆盖评估

### 明确覆盖的验证点

| 修复 | 验证方式 | 评价 |
|:-----|:---------|:----|
| 1a | mock psutil 单元测试 | ✅ 清晰 |
| 1b+1c | 回放10截面对比RSS峰值 | ✅ 要求合理，但需在 memory profiler 就绪后才能执行 |
| 1d | resource.setrlimit 模拟 OOM | ✅ 可验证 |
| 1f | profile 报告峰值 < 4GB | ✅ 可作为验收标准 |
| 2b | --no-run 模式重跑 | ✅ 无风险 |
| 3a | 确认因子池减至11 | ✅ 简单验证 |

### 缺失的验证点

1. **回归验证缺失**：没有包含"运行 T+14 已验证通过的测试用例"的验证步骤。建议添加 → 在合并 OOM 修改前，运行现有测试套件确认全部通过。
2. **SQLite 版本前置检查**：1e 的 ROW_NUMBER 优化缺少前置验证步骤。建议在部署前增加 `SELECT sqlite_version();` 确认。
3. **checkpoint 恢复完整性验证**：1d 缺少 checkpoint 续跑后数据完整性（无重复、无遗漏）的验证。

---

## 四、工时估算评估

| 子任务 | 估价 | 评价 |
|:-------|:---:|:----|
| 1a: 内存健康检查 | 10min | ✅ 合理 |
| 1b: 流式聚合 | 15min | ✅ 合理（纯逻辑重构） |
| 1c: batch→generator | 15min | ✅ 合理 |
| 1d: checkpoint/resume | 20min | ⚠️ **偏紧**。含文件 IO、原子写、JSON 序列化、resume 索引查找、pipeline_id 管理 → 建议 **25-30min** |
| 1e: 数据加载优化 | 15min | ✅ 如果采用简单参数调整（buffer_calendar 从120→60），合理。如果采用 ROW_NUMBER SQL 方案，建议 **20min** |
| 1f: 内存 profiler | 10min | ✅ 合理 |
| 1a-1f 合计 | **85min** | ⚠️ **不含调用方定位和回归测试。** 如果包含"确认所有 run_batch() 调用方" + 运行回归测试，建议总编码预估 **100min** |
| 2a-2d 合计 | 30min | ✅ 大部分是配置修改和纯新增 |
| 3a-3b 合计 | 40min | ✅ 3a + 3b-ii 25min 可立即执行，3b-iii 需单独评估 |
| **总体** | **155min** | 拆分粒度多数 ≤15min/编码，≤30min/测试 ✅ |

---

## 五、条件清单

以下 4 项条件满足后，方案可执行：

### 必须条件

1. **运行所有 T+14 已验证的测试用例并确认全部通过** → 评估 1c 向后兼容风险
2. **确认 `run_batch()` 所有调用方已识别并适配 generator 签名** → 提供调用方清单

### 建议条件

3. **执行 `SELECT sqlite_version();` 确认 ≥ 3.25.0** → 评估 1e ROW_NUMBER 方案可行性
4. **Owner 书面确认 2a 阈值统一方案** → 避免"换阈值直到 PASS"的逻辑风险。需在报告中附上 Owner 决策记录（时间、方案选择、理由）

---

## 六、补充建议

1. **1d checkpoint 补充 `_pipeline_id()` 定义**：建议使用配置 hash（`hashlib.md5(config_str.encode()).hexdigest()[:8]`），确保同一配置的重启实例能正确续跑。
2. **1c 考虑保留旧方法**：建议改为 `run_batch()` 保持原样返回 list，新增 `run_batch_streaming()` 返回 generator。scheduler 调用 `run_batch_streaming()`，其他未修改的调用方不受影响。
3. **回退计划**：建议增加"如果重跑后基线仍然 FAIL"的兜底方案（已在 2a 中提及，但不够具体）。
4. **memory profiler 部署顺序**：建议在 1c/1e 之前先部署 1f，获取修改前基线 RSS 值 → 修改后再获取二次值，形成 A/B 对比。

---

*评审完成 · 墨萱 · 2026-05-30 20:55+08:00*
