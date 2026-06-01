# 架构审查：解U2方案B2（新增run_id列+重跑）

| 字段 | 值 |
|:-----|:---|
| author | 玄知 |
| created_time | 2026-05-31T10:08+08:00 |
| review_id | U2_B2_ARCH_REVIEW |
| status | READY |
| review_of | plan_solve_U2_20260531.md → 方案B2 |

---

## 审查结论总览

| 项目 | 评级 | 说明 |
|:-----|:----:|:------|
| 架构合理性 | ⚠️ 有条件通过 | 方案B2本身合理，但需回答以下3个关键问题和1个数据膨胀场景 |
| 数据一致性 | ⚠️ 有条件通过 | 存在**source_version冲突**和**历史数据run_id=NULL**两个问题待解决 |
| 复现性 | ✅ 通过 | 确定性流程，可复现 |

**审查结果：有条件通过** — 需在以下审查意见基础上修改后执行。

---

## 1. 新增run_id列对唯一索引的影响

### 现状
- 唯一索引：`UNIQUE(trade_date, factor_name, source_version, forward_window=5)`
- 写入方式：`INSERT OR IGNORE`（基于唯一索引的幂等跳过）
- 当前 `_write_ic_result()` INSERT 语句**不包含 forward_window 字段**（实际由表 DEFAULT 值填充）

### 影响分析

**✅ 唯一索引不受影响** — `ALTER TABLE ADD COLUMN run_id TEXT` 不修改已有索引定义，run_id 不在 UNIQUE 子句中。

**⚠️ 关键问题：INSERT OR IGNORE 的行为变化**

由于 run_id 不在唯一索引中，INSERT OR IGNORE 的去重逻辑完全不变：

```
场景：marine-s 写入 (date=A, factor=B, sv=v1, fw=5) → run_id='marine-s'
      mellow-o 尝试写入相同组合 → INSERT OR IGNORE 跳过，run_id 维持 'marine-s'
```

**这不是 bug，而是预期行为**。每个行的 run_id 反映的是"首次写入它的进程"，符合故障归因需求。

### ⚠️ 需确认的问题 Q1：管线是否真的写入了 forward_window？

当前 `_write_ic_result()` 方法的 INSERT 语句为：
```python
INSERT OR IGNORE INTO a50_cross_ic_result
    (trade_date, factor_name, ic_value, rank_ic, p_value,
     num_stocks, adjusted_ic, source_version, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
```

**其中不包含 `forward_window` 字段**。如果 `forward_window` 通过表默认值 `5` 填充，则 OK。但如果 `forward_window` 作为显式字段有不同值（如 horizon 参数可配置为 5/10/21，而管线有 T+5 和 T+21 两套），则实际唯一索引组合可能已存在重复或缺失。

**建议：** 确认 `forward_window` 列的填充方式——是 DEFAULT 5，还是由管线参数写入。若 T+21 运行也写入同一表（使用 forward_window=21），则唯一索引正常工作。

---

## 2. 重跑方案的数据膨胀风险

### 场景A：使用相同 source_version='v1'（方案B2默认描述）

```
ALTER TABLE ADD COLUMN run_id TEXT
→ 重跑，仍用 source_version='v1'
→ INSERT OR IGNORE 跳过所有已存在行（14,364行）
→ run_id 在旧行上 IS NULL，在新写入的行上被赋值
```

**数据膨胀：无**（INSERT OR IGNORE 阻止重复插入）

**但：旧数据的 run_id = NULL，无法满足"归因到各进程"的需求。** 除非目标是"仅新跑的数据有 run_id"，则此方案勉强可行。

**结论：同一 source_version 重跑可避免膨胀，但牺牲了对历史数据的归因能力。**

### 场景B：使用新 source_version（方案推荐的方式）

```sql
-- "不改动旧数据，以新source_version重跑"
-- 旧: source_version='v1'  → 14,364行
-- 新: source_version='v1_replay' → 约14,364行（所有截面都会被写入）
```

**数据膨胀：~2x（约14,000行）。** 对于 SQLite 表约 14K 行来说可接受（微型膨胀），但需要确认：
1. 下游查询是否按 source_version 过滤（T+5 相关的 IC 查询）
2. 若接入 T+21 数据表（同表结构），膨胀叠加后是否超出可管理范围

**风险评级：低。** 14K 行在 SQLite 层面没有性能负担。但需确认使用约定。

### ⚠️ 需确认的问题 Q2：最终采用 source_version 策略？

```
A) 同 source_version='v1' + run_id  → 零膨胀，但历史无run_id
B) 新 source_version + run_id       → 约2x膨胀，新旧皆可归因
C) 删除旧 v1 数据再重跑             → 零膨胀，run_id全覆盖，但丢失历史快照
```

建议：方案 C 适用于"纯粹做故障复现"；若需保留历史对照，方案 B 更安全。方案 A 不解决原始问题。

---

## 3. OOM防护措施的架构充分性

### 现状清单

| 措施 | 代码中实现 | 评级 | 说明 |
|:-----|:---------:|:----:|:------|
| 启动内存检查（≥4GB） | ✅ `_check_environment_health()` | ⚠️ | 仅在 `run_batch()` / `run_batch_streaming()` 入口执行一次 |
| 单线程流式运行 | ✅ `run_batch_streaming()` + `--mode streaming` | ✅ | 流式生成器，每 yield gc.collect() |
| 逐截面 GC | ✅ 每 yield 后 `gc.collect()` | ✅ | 在 `run_batch_streaming()` 中实现 |
| 每10截面内存快照 | ✅ `self.mem_profiler.take()` | ✅ | 但仅记录，未触发保护动作 |
| 内存阈值告警 + 自动减速 | ❌ 未实现 | ❌ | 计划中提到但代码中无实现 |
| checkpoint 恢复 | ✅ `resume_from` + checkpoint 文件 | ✅ | 支持中断后恢复 |
| max_retries=3 | 部分 | ⚠️ | scheduler 侧配置，管线本身无重试逻辑 |
| 每截面内存上限 | ❌ 未实现 | ❌ | 无 per-section 内存预算控制 |

### 架构层面的缺口

**缺口1：一次性健康检查不够**

`_check_environment_health(4GB)` 只在启动时检查一次。3.5小时的重跑过程中：
- 内存可能从启动时的 6GB 逐渐增长（因子缓存、IC 历史累加）
- 上一次 OOM（16:37→16:43）表明计算量本身就在 4GB 以上
- 流式模式的 gc.collect() 依赖 Python 解释器及时回收，不保证

**缺口2：无反应式内存压力反制**

```
理想架构：
  逐截面：检查可用内存 → if < 5GB: gc.collect(); if < 4GB: 主动 sleep(3s)
                                if < 3GB: 抛弃当前截面，写入 NULL 记录，继续
                                if < 2GB: 终止管线，写入 FAILED checkpoint

当前架构：
  启动 → 检查一次内存 → 一路跑到底 → OOM → 重启
```

**缺口3：因子 batch_compute 的内存消耗不可控**

`factor_registry.batch_compute(date)` 内部可能会加载大量中间数据。管线对此无可见性，无法做逐因子内存预算。若某日因子计算生成大量中间 DataFrame，可能瞬间耗尽内存。

### ⚠️ 需确认的问题 Q3：是否接受当前 OOM 防护级别？

建议在重跑前至少添加以下轻量改动：
```python
# 在 run_pipeline() 的 Step 1-4 之间插入每步骤内存检查
if psutil.virtual_memory().available < 3 * (1024**3):  # < 3GB
    gc.collect()
    if psutil.virtual_memory().available < 2 * (1024**3):  # < 2GB
        logger.warning("逼近OOM, 跳过截面 %s 写入NULL记录", date)
        return null_summary(date)
```

若不添加，本次重跑仍有与上次相同的 OOM 风险。

---

## 4. 轻量替代方案（不做全量重跑）

### 方案D：有限回放验证

**描述：** 在测试 DB（或临时表）中创建 `a50_cross_ic_result_test` 表（schema 同源），选取 10 个截面（如 2026-01 月的 10 个周五）做模拟：

```
1. 备份 DB → 创建测试表
2. 对前3个截面写入 run_id='marine-s' → 模拟被杀（手动中断）
3. 对所有10个截面（含前3个）写入 run_id='mellow-o' → 验证 dup 跳过逻辑
4. 写入 run_id='norun' 覆盖剩余 → 验证完整归因
5. SELECT run_id, count(*) GROUP BY run_id → 检查归因精度
```

**优点：**
- 耗时 ~3 分钟（vs 全量 180 分钟）
- 完整验证 run_id 写入 + INSERT OR IGNORE 行为 + 归因查询
- 不污染生产 DB

**缺点：**
- 不能复现 OOM 条件（内存压力随 20 年数据积累而增长）

### 方案E：日志回放 + 时间戳归因（强化方案C）

如果管线标准输出/stderr 日志中包含了每截面的 `[Pipeline] %s: ic=...` 和 `[Pipeline] run_pipeline done` 日志，可以通过日志边界的 `processed_count` 推断各进程的覆盖范围。

前提：日志中需留存 timestamp 和进程 PID。

**建议：** 先检查 `/schedules/logs/` 或系统 journal 是否留存了 2026-05-30 的管线日志。若有日志，方案 E 可在 30 分钟内完成归因。若无，则无法使用。

### 方案F：Mock 测试

```python
# mock_db 中写入少量截面数据
# 模拟 3 次 run: 写入 → 中断 → 续跑 → 中断 → 完成
# 验证 run_id 归因正确
```

纯单元测试，秒级完成，但无法验证真实环境中的 INSERT OR IGNORE 行为。

### 推荐组合

```
确认优先级（推荐选 1+2）:
1. 方案D（有限回放验证）→ 验证 run_id 机制本身       [~3分钟]
2. 方案E（日志回放）→ 尝试从日志归因旧数据           [~30分钟, 有条件]
3. 若日志不可用 + 机制验证通过 → 再决定是否全量重跑    [决策点]
```

**核心逻辑：** 先花 30 分钟验证 run_id 机制是否有效，再判断 180 分钟全量重跑的必要性。

---

## 5. 全量重跑的必要性

### 全量 vs 近5年对比

| 维度 | 全量（20年） | 近5年（2022-2026） |
|:-----|:----------:|:----------------:|
| 截面数 | ~798 | ~260（约1/3） |
| 预估耗时 | ~180分钟 | ~60分钟 |
| 数据量 | ~14K行 | ~4.7K行 |
| run_id归因验证 | ✅ | ✅ |
| OOM复现条件 | ✅ 充分 | ⚠️ 内存压力较低 |
| 旧数据归因 | ❌ 不变 | ❌ 不变 |
| 生产影响 | ⚠️ 需排期 | ✅ 影响小 |

### 关键判断

**如果目标仅是"验证 run_id 归因机制"：** 近5年足够。20年 vs 5年在 run_id 写入逻辑上无差异，都是逐截面循环写入。

**如果目标是"复现 OOM 场景（解U2的核心）"：** 需要全量。OOM 是否复现取决于因子计算的内存累积 + 截面总数 × 每截面计算量。20年数据量才能完全复现当初的内存压力。

**如果目标是"给现有 14K 行数据打上 run_id 标签"：** 全量或5年都**不能**做到（因为 INSERT OR IGNORE 会跳过旧行）。需要新 source_version 或删旧数据。

### ⚠️ 需确认的问题 Q4：重跑的核心目标是什么？

```
A) 验证 run_id 归因机制 → 近5年足够，甚至 10 个截面足够
B) 复现 OOM 场景     → 需要考虑全量，但OOM防护需先加强
C) 给现有数据打标签  → 都不能（需要新 source_version 或删旧）
```

建议：Owner 明确重跑目标。若 A + B，拆分为两阶段：
- Phase 1：近5年（60分钟）→ 验证 run_id 机制
- Phase 2：全量（180分钟）→ 复现 OOM + 完整归因

---

## 总结：架构意见

### 通过条件

方案B2在架构层面**可行但需以下修改**：

1. **明确 source_version 策略**：B2（同v1+run_id）vs B1类似（新version）。若用同v1，旧数据 run_id=NULL 不解决归因问题；推荐用新 source_version 或删除旧数据。
2. **确认 forward_window 写入方式**：当前 INSERT 不含该字段，需确认 DEFAULT 值一致。
3. **添加运行时内存保护**：至少增加逐截面/逐步骤的内存检查（<3GB告警，<2GB跳过），避免重跑再次 OOM。
4. **拆分执行阶段**：先近5年验证机制，再全量复现 OOM。
5. **优先使用有限回放（方案D）**：3分钟验证 run_id 机制，通过后再决定是否全量重跑。

### 约束汇总

| # | 约束 | 类型 | 影响 |
|:-:|:-----|:----:|:----:|
| 1 | run_id 不进入唯一索引 | 设计决策 | 仅能归因首次写入进程，不能量化重试次数 |
| 2 | 历史数据 run_id=NULL | 副作用 | 同 source_version 重跑无法归因旧数据 |
| 3 | 一次性内存检查 | 架构缺口 | OOM 防护不足，需运行时保护 |
| 4 | 新 source_version 导致 2x 膨胀 | 数据影响 | 对 14K 行可接受，需明确约定 |
| 5 | 管线 INSERT 不含 forward_window | 一致性 | 需确认表结构 DEFAULT 值匹配 |

---

*EOF*
