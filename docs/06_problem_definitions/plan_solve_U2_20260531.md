# 解U2试验方案 — 区分T+21全量运行3次写入量

## 元数据

| 字段 | 值 |
|:-----|:---|
| author | 墨衡 |
| created_time | 2026-05-31T10:20+08:00 |
| problem_id | U2_T21_FULLRUN |
| version | v1.0 |
| status | READY |

## 问题陈述

T+21全量运行时，3次管线启动（marine-s ~16:43被杀、mellow-o ~17:42被杀、--no-run 17:42~19:55）均使用相同的 `source_version='v1'` + ISO格式 `created_at`（秒级精度），导致DB内无法精确区分各次运行各自的实际写入量。验证阶段只能观测到"ISO总写入=14364行、798个截面"，但无法归因到具体进程。

## 关键数据特征（查证结果）

### DB结构

- 表：`a50_cross_ic_result`
- 唯一索引：`UNIQUE(trade_date, factor_name, source_version, forward_window=5)`
- 写入方式：`INSERT OR IGNORE`（幂等）
- source_version: 3次运行均使用 `'v1'`
- created_at: ISO格式秒级精度 `YYYY-MM-DDTHH:MM:SS+08:00`

### 时间线

| 事件 | 时间 | 说明 |
|:-----|:-----|:-----|
| marine-s 启动 | ~16:37 | 首次全量运行 |
| marine-s SIGKILL | ~16:43 | OOM被杀 |
| mellow-o 启动 | ~17:27 | 调度器重启管线 |
| mellow-o SIGKILL | ~17:42 | 再次OOM被杀 |
| --no-run 模式启动 | ~17:42 | 调度器以--no-run重启 |
| --no-run 完成 | ~19:55 | 全部798截面处理完 |

### created_at 分布分析

- ISO格式总行数：14,364行
- ISO distinct timestamps：1,096个（秒级，无毫秒）
- 每 timestamp 行数：多为18行（=18个因子/截面），少数2~17行（截面切换时）
- 时间范围：16:39:06 ~ 19:54:22（连续无中断）
- 最大单次间隔（gap>60s）：89秒（出现在17:13:30→17:14:59，normal处理节奏）

**结论：created_at精度为秒级，时间线上无显著中断点可用作进程分割。**

---

## 方案A：基于现有DB的推测性归因

### 方案描述

利用INSERT OR IGNORE的幂等性 + 调度器重启从最初日期重新处理的特点，**推断**各进程"实际贡献"的新截面数。

### 推理假设

1. marine-s (~16:39~16:43, 约4分钟)：处理最早的一批截面
2. mellow-o (~17:27~17:42, 约15分钟)：重新从起点处理，INSERT OR IGNORE使已写入截面被跳过
3. --no-run (17:42~19:55, 约133分钟)：继续处理未完成截面

### 推算方法

由于created_at只到秒级，且重启后管线秒级写入仍连续，**无法精确区分**。但可以推算上界：

1. **marine-s最晚一条created_at**：由于SIGKILL会中断途中写入，marine-s写的数据应该集中在16:39~16:43窗口。从时间线看，16:43之后仍有连续写入（因为调度器立即重启mellow-o），但16:39~16:43的写入可以作为marine-s写入的**下界**。
   - 16:39:06 ~ 16:43:58 共有约120个distinct timestamps
   - 每个timestamp对应1个截面（18行）→ 约120个截面 × 18因子 = ~2160行
   - 但SIGKILL时可能中断了中途写入，实际可能少于2160行

2. **mellow-o推测写入**：mellow-o从起点重新处理，但INSERT OR IGNORE会跳过marine-s已写的截面。mellow-o的贡献主要是marine-s被杀时"写了一半的截面"的剩余因子 + marine-s完全未处理的截面。
   - 17:27~17:42共约15分钟，若持续处理新截面，约可处理 ~30~60个截面
   - 但大部分时间被用于"读取→计算→尝试写入→INSERT OR IGNORE跳过"的重复劳动

3. **--no-run贡献**：17:42之后的数据写入减去mellow-o的推测值

### 可信度评估

| 维度 | 评级 | 说明 |
|:-----|:----:|:------|
| 精确性 | ❌ 低 | 无法精确到行级别，仅能估算比例 |
| 可验证性 | ❌ 低 | 推算依赖未经验证的假设（重启处理节奏等） |
| 执行成本 | ✅ 高 | 只需SQL查询，无需代码改动 |
| 预估耗时 | 10~20分钟 | SQL查询 + 比例估算 |

### 结论：不可靠

方案A无法精确区分3次运行各自的写入量。只能给出"marine-s约处理N个截面"的模糊估算，且该估算无法被独立验证。**不推荐作为主要方案。**

---

## 方案B：重跑 + 结构化标识

### 方案描述

修改管线代码，在写入`a50_cross_ic_result`表时增加可区分不同运行进程的标识字段，然后重新执行全量运行。

### 改动要点

#### 方案B1（推荐）：写入run_id到created_at副标识

由于唯一的ID字段是`(trade_date, factor_name, source_version, forward_window)`，不改写可侵入性方案，利用`created_at`字段存储额外信息：

```python
# 在 _build_null_record 和 _write_ic_result 中
# 将 created_at 格式从 
#   "2026-05-30T16:39:06+08:00" 
# 改为
#   "2026-05-30T16:39:06.001+08:00"  # 001 = marine-s
#   "2026-05-30T16:39:06.002+08:00"  # 002 = mellow-o
#   "2026-05-30T16:39:06.003+08:00"  # 003 = --no-run
```

或用特定的source_version：
```python
# 根据config参数设置不同的source_version
# marine-s:  source_version = 'v1_marine'
# mellow-o:  source_version = 'v1_mellow'
# --no-run:  source_version = 'v1_norun'
```

#### 方案B2（最可靠）：新增run_id列

```sql
ALTER TABLE a50_cross_ic_result ADD COLUMN run_id TEXT;
-- 然后配置文件传入 run_id='marine-s' / 'mellow-o' / 'norun'
-- 写入时带上 run_id
```

**优点**：精确区分，可量化。无需改动唯一索引（因为已有UNIQUE约束，加run_id不影响去重）。

**缺点**：需要ALTER TABLE（SQLite支持ADD COLUMN，向前兼容）。

### 重跑预估耗时

| 阶段 | 耗时 | 说明 |
|:-----|:----:|:------|
| 代码改动 | 10~15分钟 | 修改_write_ic_result + _build_null_record + scheduler传参 |
| 单元测试 | 5分钟 | 验证改动不影响现有写入 |
| 全量重跑 | ~180分钟 | 基于上次经验（16:37~19:55） |
| 数据验证 | 10分钟 | 确认各run_id正确标记，总量一致 |
| **总计** | **~210分钟** | 3.5小时，可在非交易时间执行 |

### 关键改进点

1. **Scheduler增加run_id参数**：`ICBatchScheduler.__init__`中接收`run_id`，透传到管线
2. **管线写入时携带run_id**：`_write_ic_result`的INSERT中加入run_id字段
3. **调度脚本传入run_id**：`python run_pipeline.py --run-id marine-s`
4. **scheduler重启时自动递增run_id**：被杀重启时使用新的run_id

### 重跑前提条件

- 当前DB数据不可覆盖（需备份）
- 若使用方案B2（新加列），旧数据已存run_id=NULL，不影响统计
- 若使用方案B1（source_version区分），需先DELETE旧v1数据再重跑（或写入新source_version）

#### 推荐方式：插入新source_version，保留旧数据

```sql
-- 不改动旧数据，以新source_version重跑
-- 然后对比 v1 (旧) vs v1_marine/v1_mellow/v1_norun (新)
```

### 重跑避免OOM的措施

基于U1~U3的经验，重跑时需同时执行以下措施：

| 措施 | 说明 |
|:-----|:------|
| 控制并行度 | 显式设置--mode streaming单线程 |
| 减少checkpoint写入频率 | 避免checkpoint IO消耗 |
| 监控内存 | 使用psutil阈值告警，>4GB时自动减速 |
| 重启策略 | scheduler配置max_retries=3，不同run_id |

### 方案B可靠性评估

| 维度 | 评级 | 说明 |
|:-----|:----:|:------|
| 精确性 | ✅ 高 | 每个run_id精确对应一行 |
| 可验证性 | ✅ 高 | SQL GROUP BY run_id直接统计 |
| 执行成本 | ⚠️ 中 | 需代码改动 + 3.5小时重跑 |
| 数据一致性 | ✅ 高 | INSERT OR IGNORE确保幂等，总量匹配旧快照 |

---

## 方案C（混合方案）：日志分析 + 进程内存推算

### 方案描述

不重跑，通过分析管线日志的progress计数器 + 推测各进程处理时间窗口，交叉验证截面的增量。

- marine-s 写入了约222个截面（18:12时验证脚本6:10截面中222个来自marine-s）
- 精确拆分需要管线日志的 `processed_count` 进度报告

### 前提

需要管线运行时留存了 stdout/stderr 日志。若日志未留存，此方案不可行。

| 维度 | 评级 | 说明 |
|:-----|:----:|:------|
| 精确性 | ⚠️ 中 | 依赖日志留存和解析 |
| 可验证性 | ⚠️ 中 | 日志截断可能导致偏差 |
| 执行成本 | ✅ 低 | 日志已存在则直接分析 |
| 预估耗时 | 30分钟 | 日志解析 + 交叉验证 |

---

## 推荐方案

| 优先级 | 方案 | 选择理由 | 预估总耗时 |
|:------:|:-----|:---------|:----------:|
| **1** | **方案B2（新增列+重跑）** | 精确度最高，可审计，代码改动量小，不影响现有数据 | **~210分钟** |
| 2 | 方案B1（source_version区分） | 改动更小，但需DELETE旧数据才能对比 | ~200分钟 |

### 执行路径

```
Step 1: 代码改动（~15分钟）
  ├─ 修改 pipeline: _write_ic_result 新增 run_id 列写入
  ├─ 修改 scheduler: 接收/透传 run_id 参数
  └─ 修改运行脚本: 添加 --run-id 参数

Step 2: ALTER TABLE 加列（~1分钟）
  └─ ALTER TABLE a50_cross_ic_result ADD COLUMN run_id TEXT;

Step 3: 备份DB + 全量重跑（~180分钟）
  ├─ 备份：cp a50_ic.db a50_ic_20260530_backup.db
  ├─ marine-s: python run.py --start 20070104 --end 20260526 --run-id marine-s
  ├─ mellow-o: 同上 --run-id mellow-o（调度器检测到失败后自动重启）
  └─ --no-run: 同上 --run-id norun（schedule配置不同模式）

Step 4: 验证（~10分钟）
  └─ SELECT run_id, count(*), count(DISTINCT trade_date)
       FROM a50_cross_ic_result
       WHERE run_id IS NOT NULL
       GROUP BY run_id;
```

### 依赖项

| 依赖 | 说明 |
|:-----|:------|
| SQLite | 支持ALTER TABLE ADD COLUMN（支持） |
| 管线代码 | cross_sectional_ic_pipeline.py + scheduler.py 的读写路径 |
| Python 3.14+ | 现有环境 |
| 3.5小时非交易时间 | 建议在 01:00~06:00 窗口执行（CST） |
| 可用内存 > 4GB | 参考U1~U3经验，16GB机器建议预留 |

### 不推荐方案

- **方案A**（仅DB区分）：精度太低，无法精确到行级，只能模糊估算
- **方案C**（日志分析）：前提条件可能不满足（日志可能未留存），且仍需依赖推测

---

## 附录：临时验证脚本（方案A辅助）

若暂时不需要重跑，以下SQL可提供近似估算：

```sql
-- marine-s 写入的数据（16:39:06 ~ 16:43:58 区间内创建的ISO记录）
SELECT count(DISTINCT trade_date) as marine_dates
FROM a50_cross_ic_result
WHERE source_version = 'v1'
  AND created_at >= '2026-05-30T16:39:06+08:00'
  AND created_at <= '2026-05-30T16:43:58+08:00'
  AND created_at LIKE '%+08:00';

-- mellow-o + --no-run 共同数据
SELECT count(DISTINCT trade_date) as mellow_dates
FROM a50_cross_ic_result
WHERE source_version = 'v1'
  AND created_at >= '2026-05-30T17:27:00+08:00'
  AND created_at LIKE '%+08:00';
```

注意：以上查询严格来说包含的是**时间窗口内的记录数**，不是**进程实际写入数**（因调度器重启后覆盖）。

---

*EOF*
