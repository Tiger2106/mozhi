# U2复现讨论 — 执行者角度

| 字段 | 值 |
|:-----|:-----|
| author | 墨衡 |
| created_time | 2026-05-31T10:15+08:00 |
| task_id | discussion_U2_repro_moheng |
| source | plan_solve_U2_20260531.md + problem_definition_T21_FULLRUN_20260530_v1.0.md |
| perspective | 执行者（编码/跑管线） |

---

## Q1: U1"系统限制" — psutil能否捕获被杀时刻内存快照？

**结论：不能捕获"被杀精确时刻"，但可以捕获"杀前最后一截面"。**

原因链条：

1. **psutil是用户态工具**，运行在同一个Python进程内。当SIGKILL（信号9）到来时，内核直接终止进程 —— 用户态代码没有机会执行任何finally/atexit/signal handler。psutil监控线程也会被杀，**无法在死亡瞬间写日志**。

2. **WSL2是Hyper-V VM**，其内核日志（dmesg）默认不可达宿主机。之前已确认dmesg不可用 —— 这是WSL2架构性限制，不是配置问题。

3. **psutil的实际价值在趋势监控**：
   - 每处理完一个截面记录 `(截面索引, rss_mb, time)` → 形成内存增长曲线
   - 当连续N个截面内存持续上升且斜率>阈值时，提前输出预警日志
   - 最后一次成功写完的截面记录 = "杀前最后一截面"的内存快照
   - **这个快照和被杀时刻的记忆差通常在1~2个截面（最多数十秒），但足够了**

4. **Hard limit是WSL2层面**，不是进程层面。WSL2的内存上限由 `.wslconfig` 的 `memory=<size>` 控制，当WSL2总内存超限时由Hyper-V OOM killer决定杀谁 —— 无法预知/拦截。

**执行者判断**：psuti的趋势监控可行且有价值，但不能声称"捕获被杀时刻快照"。应在方案中明确标注差异。

---

## Q2: U2"需日志" — run_id能否解除限制？

**结论：可以精确区分，但有四个陷阱必须解决。**

### 正向结论

方案B2（新增run_id列 + 重跑）核心逻辑可靠：

```
写入时：INSERT INTO a50_cross_ic_result (..., run_id) VALUES (..., 'marine-s')
查询时：SELECT run_id, count(*) FROM ... GROUP BY run_id;
```

SQLite `ALTER TABLE ADD COLUMN` 是O(1)操作，不重建表，不影响线上数据。旧数据run_id=NULL，新数据run_id有值，泾渭分明。

### 必须解决的四个陷阱

| # | 陷阱 | 后果 | 解决方案 |
|:-:|:----|:----|:--------|
| 1 | **run_id不在UNIQUE索引中** | 重启时INSERT OR IGNORE不命中（因为UNIQUE索引不含run_id），同一截面/因子会写多次，**数据膨胀** | 方案A：把run_id加入UNIQUE索引（需要重建，代价大）<br>方案B：重跑前 DELETE WHERE run_id IS NULL for 新source_version；或直接用新source_version重跑（`plan_solve_U2`已推荐） |
| 2 | **调度器重启时如何传递新run_id** | 被杀后调度器自动重启（`restart_pipeline`），如果run_id硬编码，重启后仍用同个ID | 调度器增加`run_seq`计数器；被杀重启时自动递增 `f"marine-s_try{seq}"`；或使用进程启动时间戳 |
| 3 | **checkpoint重启 ≠ 从头开始** | checkpoint保存了进度，重启后从checkpoint继续而非从第一天 —— run_id链条不会被覆盖写入，但**首次处理"遗留截面"和"重复跳过截面"的run_id归属不同** | 不影响统计精度：只要run_id能区分进程，每个截面/因子的最终来源可精确追踪，但需要明确统计口径是"最终来源"还是"首次尝试" |
| 4 | **--no-run模式的identity** | --no-run模式是否仍有写入行为？从T21经验看，--no-run模式下仍在写入（因scheduler的db_background_batch机制） | --no-run也需要run_id，且需区别于普通模式；如果--no-run和普通模式的管线入口不同，需要单独传参 |

### 关键执行决策

```
U2精度问题 → 精确可解（run_id可区分三次运行）
但需要解决：
  1. 选择新增列 vs 修改source_version（推荐新增列，不改老数据）
  2. 调度器重启的run_id传递（不传=白做）
  3. --no-run模式的run_id（容易被遗漏）
```

---

## Q3: 如果复现没触发OOM，U1/U2怎么办？

**U1：可以部分解决，但需要模拟**

| 状态 | 方案 | 说明 |
|:----:|:-----|:------|
| 复现OOM | psutil监控趋势 + 验证杀前数据可用 | 理想情况，直接验证 |
| 没OOM | 人工模拟压内存：用Python脚本alloca(512MB)*N，靠近阈值时看psutil日志是否能正确记录 | 验证监控"部分"（记录功能），但验证不了"被杀瞬间无日志"的本质限制 |
| 没OOM | 直接在正常跑时观察psutil是否持续记录每截面内存 | 至少验证监控**不会引入新的OOM**或**不拖慢性能** |

**替代方案（不跑管线）**：
- 写一个最小复现脚本：不断分配内存直到被杀，进程内跑psutil监控
- 在WSL2内 `ulimit -v 4194304`（限制虚拟内存~4GB），模拟OOM场景
- 这样可以快速验证psutil在OOM前的最后一条记录是什么

**U2：完全不受复现结果影响**

run_id区分的验证不依赖OOM是否发生 —— 只要重跑完成（正常或被杀），写入了带run_id的数据，验证查询就能确认是否可区分。

**优先级建议**：
```
复现失败时 → U2验证优先（价值确定，不依赖环境）
            U1验证走模拟（跑小脚本来证明监控可用性）
```

---

## Q4: 补充建议（主人可能遗漏的）

### 4.1 run_id的唯一索引冲突

现有UNIQUE: `(trade_date, factor_name, source_version, forward_window)`
新增run_id后，如果UNIQUE不变，**每次重启都会把已存在的数据再写一次**（因为run_id不同，UNIQUE不命中）。
要么改UNIQUE包含run_id，要么重跑时用新source_version（推荐后者）。

### 4.2 重跑OOM的概率不低

上次两次被杀，这次只加了一个psutil监控 + 一个run_id —— 这些改动不减少内存消耗。重跑3.5小时，大概率会再次OOM。
需要同步实施：降低并行度（--mode streaming）、减少checkpoint频率、设置ulimit预警（>3GB时sleep 1s）。

### 4.3 重跑的"静态快照"问题

重跑产生的数据和生产环境的数据时间窗口不同（市场状态不同），跑出来的IC结果可能不同，不应用来替代生产数据。
重跑只解决"区分写入量"的问题，不解决"数据对错"问题。

### 4.4 建议先做small-scale验证再全量

不要直接跑3.5小时全量。先做3~5个截面的快速试验：
```
1. 改代码 + ALTER TABLE
2. 跑python run.py --start 20260525 --end 20260526（仅2天）
3. 手动kill进程
4. 重启 --run-id retry
5. SQL验证两条run_id是否正确
```
确认跑通后再上全量，至少节省2小时。

### 4.5 日志留存比psutil更可靠

psutil只是监控方案的最后一道防线。真正可靠的还是**管线自身的日志**：
- 每次INSERT前打印 `[IC_WRITE] {截面} {因子} {run_id}`
- 每次截面循环结束打印 `[IC_PROGRESS] 截面X/798, 内存YMB`
- 日志写到文件而非stdout（stdout可能被WSL2截断）

建议和psutil双管齐下。

### 4.6 调度器重启的run_id传递链

Owner指出要"复现故障" —— 但调度器重启逻辑中，run_id需要从scheduler配置自动传递到pipeline，而不是硬编码。建议：
```
scheduler.py:
    run_seq = 0
    def restart():
        run_seq += 1
        run_id = f"t21_{run_seq}"
        pipeline.run(run_id=run_id)
```
但如果调度器本身也被杀掉，run_seq丢失。更可靠的方式：使用启动时间戳作为run_id（秒级即可区分）。

---

## 总结

| 项目 | 是否可解决 | 关键条件 |
|:----|:----------:|:---------|
| U1 内存快照 | ⚠️ 部分 | 能获取"杀前最后一截面"，不能获取"被杀精确时刻"；WSL2 hard limit无解 |
| U2 精确区分 | ✅ 完全 | run_id + 新source_version，注意UNIQUE冲突和调度器传递链 |
| 复现失败替代 | ✅ 有 | U2不受影响；U1用小脚本模拟OOM验证psutil |
| 主人遗漏 | 见Q4各条 | 尤其4.1(UNIQUE冲突)、4.4(先小后大)、4.6(传递链) |

*EOF*
