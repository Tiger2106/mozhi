---
author: 墨萱
created_time: 2026-05-31T10:16+08:00
task_id: discussion_U2_repro_moxuan
source: plan_solve_U2_20260531.md + discussion_U2_repro_moheng.md + problem_definition_T21_FULLRUN_20260530_v1.0.md
perspective: QA/数据验证
---

# U2复现讨论 — QA验证角度

## Q1: U1"系统限制" — psutil能否获得有效的OOM快照？

**结论：能获得"杀前最后一截面"的快照，不能获得"被杀精确时刻"的快照。没复现OOM时，U1的"系统限制"定性不变，但psutil可转为部分缓解。**

### 能获得什么

每截面psutil监控可以形成内存增长曲线（截面索引→rss_mb），最后一次成功写完截面时的内存记录 = "杀前最后一截面"的快照。与真实被杀时刻的偏差通常在1-2个截面（<1分钟），对诊断OOM阈值、判断是否存在内存泄露足够。

### 不能获得什么

psutil是用户态工具，运行在同一个Python进程内。SIGKILL（信号9）由内核直接发送——用户态代码没有机会执行finally/atexit/signal handler。psutil监控线程也会被杀，无法在死亡瞬间写日志。这是架构性限制（WSL2 Hyper-V VM，dmesg不可达），不是配置问题。

### 没复现OOM，如何推论U1可解？

| 场景 | 对U1结论的影响 | 推论方法 |
|:-----|:--------------|:---------|
| 复现OOM | 直接验证psutil在OOM场景下的行为 | 实证 |
| 没复现OOM（正常跑完） | U1的**定性不变**：系统限制还是系统限制 | **逻辑推导**：1) SIGKILL时用户态代码无法执行的原理不变；2) psutil的价值（趋势监控）不依赖OOM是否发生，正常跑也能验证记录功能；3) 替代验证：用小脚本（不断分配内存直到被杀）+ psutil模拟OOM场景，验证最后一条记录 |
| 没复现OOM | 从"系统限制"→"系统限制+部分缓解" | psutil减小信息缺口，但不能消除 |

**关键推理**：U1标注"系统限制"是基于WSL2架构性限制（dmesg不可用），这个限制不会因为加psutil就变成"可解"。psutil只是增加了一个辅助观测工具，使"杀前最后一截面"实时内存可见，但"被杀精确时刻"仍然不可获取。从QA角度看，U1从"完全不可解"变为"部分可缓解"。

---

## Q2: U2"需日志" — run_id的验证是否受OOM结果影响？

**结论：U2的验证完全不依赖OOM是否发生。即使跑成功了不触发OOM，也能确认"原始故障中无法区分"这一结论。**

### 为什么不受影响

- run_id是**精确的行级标识**，不是统计估算
- 无论OOM与否（正常跑完/被SIGKILL/三次都跑完），写入的每一行都带有run_id
- 验证查询：`SELECT run_id, count(*) FROM a50_cross_ic_result GROUP BY run_id` — 这是确定性查询，与OOM事件无关

### 能否确认"原始故障中确实没有run_id就无法区分"？

**可以确认，且不需要复现试验来证明。**

现有DB证据已足以定性（在problem_definition阶段已确认）：

| 证据 | 结论 |
|:-----|:------|
| created_at为秒级精度，1,096个distinct timestamps | 时间戳精度不足以区分进程 |
| 时间线上无显著中断点（最大gap=89秒，正常处理节奏） | 无法用时间间隔分割3次运行 |
| 3次运行均使用相同的source_version='v1' | 无版本区分字段可用 |
| 无PID、进程名或其他标识字段 | 无其他可追溯途径 |

**逻辑链成立**：3条独立证据均指向"无法区分"→ 复现试验只是验证"有了run_id后能区分"的正面证据，不需要通过这些数据反证"没有run_id不能区分"。

### 复现试验的附加价值

即使不触发OOM，复现试验完成后可以直接回答：

- run_id写入机制是否可靠？（新加列的INSERT是否正常）
- 调度器重启时run_id传递链是否畅通？（scheduler透传run_id）
- --no-run模式是否也得到了run_id？（需明确区分）

这些问题的验证都不需要OOM发生。

---

## Q3: 数据完整性风险

**结论：存在三条风险路径，均可通过独立source_version隔离消除。**

### 风险路径1：新旧数据混合导致IC计算偏移

| 风险 | 触发条件 | 影响 | 严重度 |
|:-----|:---------|:-----|:------:|
| IC查询语句未指定source_version过滤 | SELECT * 或 WHERE无条件 | 同一trade_date/因子有两条记录（old v1 + new v1_repro），COUNT/AVG/分布统计量翻倍或偏移 | **中** |
| 后续管线读取新数据 | pipeline用全量SELECT读IC表 | IC计算包含重跑数据与生产数据的混合 | **高** |
| 基线验证脚本误用新数据 | 基线脚本通查全表 | golden_baseline结论被重跑数据污染 | **高** |

**缓解措施**：使用独立source_version（如'v1_repro'），并在所有查询中显式过滤 `WHERE source_version='v1'`。

### 风险路径2：UNIQUE索引不与run_id联动

| 风险 | 触发条件 | 影响 | 严重度 |
|:-----|:---------|:-----|:------:|
| 数据膨胀 | INSERT OR IGNORE不命中UNIQUE（因run_id不同），同一截面/因子写多次 | 行数翻N倍（N=重跑次数） | **高** |
| GROUP BY结果不可信 | 未注意run_id列，按旧字段GROUP BY | 重复计数导致统计结果虚高 | **中** |

**缓解措施**：重跑前确认UNIQUE索引是否包含run_id（建议不包含），然后依靠**独立source_version**隔离——不同source_version自然不冲突。

### 风险路径3：ALTER TABLE后的兼容性问题

| 风险 | 触发条件 | 影响 | 严重度 |
|:-----|:---------|:-----|:------:|
| 旧脚本SELECT *按列位置索引 | column position依赖 | 新列打乱列序 | **低**（SQLite向后兼容） |
| 旧数据run_id=NULL被误用 | JOIN时隐含NULL过滤 | 统计量可能微偏 | **低** |

**缓解措施**：慎用SELECT *，查询时显式指定列。

### 风险消除建议：完全隔离策略

| 项目 | 生产数据 | 重跑数据 |
|:-----|:---------|:---------|
| source_version | 'v1' | 'v1_repro' |
| run_id | NULL | 'marine-s' / 'mellow-o' / 'norun' |
| 使用范围 | IC计算、基线验证 | 仅U2行数区分验证 |
| 查询隔离 | WHERE source_version='v1' | WHERE source_version='v1_repro' |

**重跑前后的验证步骤**：

```sql
-- 验证0：备份前确认生产数据总量
SELECT COUNT(*), COUNT(DISTINCT trade_date) FROM a50_cross_ic_result WHERE source_version='v1';

-- 验证1：ALTER TABLE后旧数据不受影响
SELECT COUNT(*) FROM a50_cross_ic_result WHERE source_version='v1' AND run_id IS NULL;

-- 验证2：重跑完成后确认新数据独立
SELECT run_id, COUNT(*) FROM a50_cross_ic_result WHERE source_version='v1_repro' GROUP BY run_id;

-- 验证3：隔离确认——生产查询结果不变
SELECT COUNT(*), COUNT(DISTINCT trade_date) FROM a50_cross_ic_result WHERE source_version='v1';
-- 应等于验证0的结果
```

---

## Q4: 补充建议（从QA角度出发）

### 4.1 复试验收标准需要事先明确

Owner说"确认这两个不确定项是否可以解决"——但"解决"的标准是什么？

| 不确定项 | PASS标准（建议） | FAIL标准 |
|:---------|:---------------|:---------|
| U1：psutil内存监控 | 重跑日志中包含每截面内存记录，至少最后10个截面的内存曲线可查 | 无内存记录 / 监控导致新OOM / 拖慢性能 |
| U2：run_id区分写入量 | SELECT GROUP BY run_id能精确返回3个进程各自的行数 | run_id全NULL / 多次重启未递增 / run_id未传递到pipeline |

### 4.2 缺少"小型验证→确认→全量"的分阶段计划

现在的方案直接计划全量重跑（~3.5小时）。建议：

```
Phase 1: 小范围验证（~30分钟）
  1. 改代码 + ALTER TABLE
  2. 跑 python run.py --start 20260525 --end 20260526（仅2交易日）
  3. 手动kill进程 → 重启 --run-id retry
  4. SQL验证两条run_id是否正确写入
  5. 确认通过 → Phase 2

Phase 2: 全量重跑（~180分钟）
  仅在Phase 1通过后执行
```

如果Phase 1发现run_id传递链断裂（scheduler重启时未递增run_id），Phase 2也白跑。

### 4.3 重跑前DB备份的命名规范

备份文件命名需包含时间戳和内容标识，确保可追溯：
```bash
cp a50_ic.db backup/a50_ic_{YYYYMMDD_HHMMSS}_pre_U2_repro.db
```

### 4.4 重跑完成后的隔离性验证

建议在重跑完成后、IC计算使用数据之前，独立跑一次隔离性验证：
1. 旧查询（WHERE source_version='v1'）结果与备份前一致 ← 确认旧数据未被污染
2. 新查询（WHERE source_version='v1_repro'）groupby run_id返回预期行数 ← 确认新数据有效
3. 交叉查询（跨版本JOIN）不产生异常行 ← 确认数据隔离

### 4.5 关于"复现"的注意点

这次的"复现"和真正的故障复现有本质区别：
- **不是"复现故障行为"**（不是复现SIGKILL时刻的精确内存），而是"在新的受控环境中验证监控/标识机制"
- 即使完全复现了OOM，也不能保证原始故障中psutil能拿到数据（因为原始故障没有psutil）
- **复现试验的定位**应该是"验证新机制有效性"而非"还原历史现场"

### 4.6 如果重跑失败（再次OOM）怎么办？

| 场景 | 应对 | QA影响 |
|:-----|:-----|:--------|
| Phase 1就OOM | 先缩小范围（1个截面），确认最简可行 | Phase 1设计就是为了这种情况 |
| Phase 2中途OOM | 检查run_id是否正确地通过重启递增了 | 如果run_id递增正常，数据可部分验证U2 |
| Phase 2连续OOM | 复现同一条run_id多版数据 | 验证U1的同时，可评估WSL2内存限制的严重性 |

---

## 总结

| 项目 | QA结论 | 核心依据 |
|:-----|:-------|:---------|
| U1 psutil快照 | 可获得"杀前最后一截面"（部分缓解），不可获得"被杀精确时刻" | psutil用户态 + WSL2架构限制 = 架构性不完整 |
| U2 run_id区分 | 完全可解，且不依赖OOM是否触发 | run_id是精确行级标识，验证查询确定性 |
| 数据完整性风险 | 可规避，需独立source_version隔离 | 新旧数据不共存于同一过滤条件 |
| 补充建议 | 分阶段验证 + 明确PASS标准 + 隔离性检查 | 节省时间，降低风险 |

*EOF*
