---
author: 玄知 (xuanzhi)
created_time: 2026-05-31T10:30:00+08:00
type: architecture_review
review_for: experiment_plan_U2_repro_v1.md
version: v1.0
status: COMPLETED
---

# 试验方案架构审查报告

**审查对象**：`experiment_plan_U2_repro_v1.md`
**审查者**：玄知（架构+数据一致性）
**审查时间**：2026-05-31T10:30+08:00

---

## 一、总体评估

**结论：PASS with conditions**

方案核心架构（双重隔离：source_version + run_id）设计合理，Phase 0→1→2→3 的分阶段策略稳妥。但存在**两项关键缺陷**需要在Phase 2执行前修复，否则run_id验证的有效性将受严重影响。

> ⚠️ 注意：本次审查基于墨衡产出的试验方案v1.0 + 当前代码主干的交叉分析。发现的所有缺陷**只标记不代修**。

---

## 二、审查项详细评估

### 审查项1：代码改动（C1~C7）run_id透传路径完整性

#### 1.1 Scheduler → Pipeline 透传路径

C4将 `run_id` 加入 `ICBatchScheduler.__init__` 并在 `run_full_cross_sectional` 中透传给 `CrossSectionalICPipeline`，路径正确、逻辑清晰。✅

#### 1.2 ⚠️ 缺陷D1（严重）：from_config()工厂方法遗漏

`ICBatchScheduler.from_config()` 是目前代码中的工厂方法（scheduler.py第127~156行），用于快捷创建调度器实例。如果试验使用此路径创建scheduler（作为入口脚本C7的备选创建方式），**run_id不会被传入**：

```python
# 当前 from_config 最后一行 — run_id 参数缺失
return cls(
    db_manager=dm,
    factor_registry=reg,
    ic_engine=engine,
    forward_returns=fr,
    horizon=horizon,
    source_version=source_version,  # ← run_id 未传入
)
```

试验方案C7使用了显式 `__init__` 方式创建scheduler，不会直接触发此缺陷。但 `from_config` 仍是一个**开放的架构风险**——未来任何用此工厂方法创建的实验运行都会丢失run_id。

**建议**：`from_config` 同步增加 `run_id` 参数，或在内部自动生成一个随机run_id确保不为None。

#### 1.3 C7入口脚本未对接resume机制

试验方案Phase 1/2中多次提到重启时使用 `--resume` 参数（Phase 1步1.4 "（含--resume）继续跑"），但C7的入口脚本代码**只定义了 `--run-id`、`--start-date`、`--end-date` 等参数，没有 `--resume`**。

更关键的是——**run_id 与 checkpoint 的 pipeline_id 是两套独立的ID系统**：

| 标识 | 用途 | 生成方式 | 存储位置 |
|:-----|:-----|:---------|:---------|
| `run_id` | DB写入标识（U2验证） | 用户传入 | `a50_cross_ic_result.run_id` |
| `pipeline_run_id` | checkpoint跟踪 | 自动生成（`_generate_pipeline_id()`） | checkpoint文件 |

pipeline的 `resume_from` 参数**需要的是 `pipeline_run_id` 而非 `run_id`**。重启时新进程自动生成新的pipeline_id，找不到旧checkpoint文件，resume机制不可用。

#### 1.4 唯一索引 vs run_id 冲突（详见审查项2）

---

### 审查项2：数据隔离 — v1_repro + run_id 组合

#### 2.1 架构评价

双维度隔离策略（source_version维 + run_id维度）从概念设计上是干净的：
- `source_version='v1_repro'` 与基线 `'v1'` 天然隔离 ✅
- `run_id` 在实验内逐运行区分 ✅
- 生产查询不需要 `WHERE source_version != 'v1_repro'`，只需保持原来的 `source_version='v1'` ✅

#### 2.2 ⚠️ 缺陷D2（严重）：唯一索引未包含run_id

已确认 `a50_cross_ic_result` 表的唯一索引定义：

```
sqlite_autoindex_a50_cross_ic_result_1  (UNIQUE)
  ├── trade_date
  ├── factor_name
  ├── source_version
  └── forward_window
```

**该索引不包含 `run_id` 列。**

后果分析：假设进程被SIGKILL前已写入编号 #1~#37 截面（`run_id='repro_p1'`）。重启后如果resume机制失效或失效的情况下**直接从头跑**，第二批写入（`run_id='repro_p2'`）试图写入截面 #1~#37 时，`INSERT OR IGNORE` 会静默跳过——因为 `(trade_date, factor_name, 'v1_repro', forward_window)` 组合已存在。最终 `GROUP BY run_id` 的结果将是：

```sql
run_id     | COUNT(*)
-----------+---------
repro_p1   | 1000      ← 含两轮写入，但第二轮被IGNORE
repro_p2   | 963       ← 只含 #38~#1000
```

**更为严重的是**：如果operator预期 `repro_p2` 应该覆盖所有1000行（U2验证的直觉假设），结果中发现只有963行→可能错误归因为"OOM半路又杀了"，而非"INSERT OR IGNORE二次写入被跳过"。

**条件性通过的前提**：必须确保两点同时满足——(a) resume机制正确跳过已处理截面，(b) 新run_id只写入未处理截面。但如审查项1.3所示，resume机制本身也存在断裂。

#### 2.3 无交叉污染风险

旧数据 `source_version='v1'` 与试验数据 `'v1_repro'` 在source_version层面完全隔离，查询 `WHERE source_version = 'v1'` 不受影响。✅

---

### 审查项3：OOM防护设计

#### 3.1 三级阈值合理

| 层级 | 阈值 | 动作 | 评价 |
|:----:|:----:|:-----|:----|
| L1 | < 4GB | 启动时报错退出 | ✅ 已有代码，合理 |
| L2 | < 3GB | 日志告警 | ✅ 合理 |
| L3 | < 2GB | 跳过截面写NULL | ✅ 合理的激进保护 |

#### 3.2 逐截面性能开销评估

`psutil.virtual_memory()` 调用开销约 10μs，`psutil.Process().memory_info().rss` 约 50μs。按每截面检查一次计，即使5000个截面总开销 < 1秒，**可忽略不计**。✅

#### 3.3 ⚠️ 缺陷D3（低-中）：内存检查点与真实峰值存在偏移

实验方案将内存检查插入在 `run_batch_streaming` 的截面循环开头（每次 `run_pipeline` 调用前）。但实际内存峰值发生在 `run_pipeline` **内部**——因子计算（`factor_registry.batch_compute`）和IC引擎内部可能产生大量中间数据。截面间的空闲期与计算期的内存占用差距可能很大。

典型场景：检查点看到4GB可用→进入 `run_pipeline`→因子计算加载大块数据→**内存骤降至1.8GB**→但此时已通过检查，不会触发L3跳过。实际OOM的可能在此刻发生。

**这不是试验方案的缺陷，而是需要结论文档中标注的认知边界。** psutil守护只能提供截面间的"采样点"数据，无法捕获计算过程中的实时内存变化。

#### 3.4 L3跳过后的行为

L3跳过后写入一条标记性NULL记录（num_stocks=0, run_id保留），这是好的设计——它保留了截面范围的完整性，便于事后追溯跳过位置。✅

---

### 审查项4：数据膨胀管理（架构级别）

#### 4.1 当前方案未涉及

实验方案对数据膨胀的管理**完全未涉及**。仅确认ALTER TABLE ADD COLUMN run_id TEXT是O(1)操作，但未考虑：

- **索引膨胀**：新增 `run_id` 列后，如果后续频繁使用，需要为它创建索引。`WHERE run_id = 'xxx'` 的查询在全表扫描中可能很慢。
- **清理策略**：run_id机制在试验后是否保留？保留的话，每次实验都产生一批 `source_version='v1_repro'` 的数据，长期累积会造成数据膨胀和查询混乱。
- **元数据管理**：各次实验的run_id含义（marine-s/mellow-o/norun各自的date range、启动时间、退出码）应有一个附带元数据表，否则事后查阅 `GROUP BY run_id` 时只能看到字符串ID，无从追溯上下文。

#### 4.2 建议的架构改进

本次试验**不需要**实现以下内容，但建议纳入架构路线图：

```
-- 可选：run_id 元数据表（记录每次运行的上下文）
CREATE TABLE experiment_run_meta (
    run_id          TEXT PRIMARY KEY,
    source_version  TEXT NOT NULL,
    start_date      TEXT,
    end_date        TEXT,
    started_at      TEXT,
    exit_code       INTEGER,
    wsl_pid         INTEGER,
    psutil_log      TEXT,    -- [MemGuard]日志文件路径
    notes           TEXT
);

-- 可选：废弃实验数据的归档策略（跑完试验后标记清理）
-- 无需删表，ALTER TABLE RENAME TO 即可归档
```

---

### 审查项5：WSL2环境风险（附录C）

#### 5.1 现有清单覆盖

附录C列出了7项：OS、Python、psutil、SQLite、磁盘空间、内存、调度器、.wslconfig。✅

#### 5.2 ⚠️ 缺陷D4（中）：遗漏的关键环境差异

| # | 遗漏项 | 为什么重要 | 影响 |
|:-:|:-------|:-----------|:-----|
| 1 | **SIGKILL行为差异** | WSL2的进程信号处理与原生Linux存在差异。WSL2中SIGKILL对进程的直接子进程可能更"干净"地终止，但对Python进程中C扩展/子线程的终止时机可能不同。**这对U1验证结论的可移植性有直接影响**。 | U1结论需要加注"WSL2环境观察" |
| 2 | **ulimit -v 支持度** | WSL2内核版本不同对 `ulimit -v` 的支持不同。部分WSL2配置下 `ulimit -v` 无效或效果与原生不同。方案附录B中C方案使用 `ulimit -v` 模拟OOM需验证可用性。 | OOM模拟方案可行性 |
| 3 | **.wslconfig 的 memory 设置** | `memory=12GB` 是WSL2的"硬上限"，但WSL2的memory回收策略（memory reclamation）与原生Linux不同——WSL2可能不会立即归还已释放的内存给Windows。 | 可用内存的实际有效性 |
| 4 | **文件系统IO差异** | WSL2在 `/mnt/c/` 跨文件系统路径上的IO性能差距可达10x。管线运行时涉及的DB和日志文件若位于Windows侧路径，性能表现与原生Linux显著不同。 | 运行时估算偏差 |
| 5 | **Python psutil 在WSL2中的准确性** | psutil的 `virtual_memory().available` 在WSL2中返回的是WSL2实例的可用内存值还是宿主机值？不同WSL2内核版本表现不同。需预先验证。 | 监控数据可靠性 |

---

### 审查项6：补充发现

#### 6.1 ⚠️ 缺陷D5（中）：_build_null_record 的 source_version 硬编码

当前 `_build_null_record` 静态方法中使用了模块级常量 `SOURCE_VERSION = "v1"`（hardcoded）：

```python
@staticmethod
def _build_null_record(date, factor_name, n_stocks):
    return {
        ...
        "source_version": SOURCE_VERSION,  # ← 永远是 "v1"
        ...
    }
```

实验方案C1中计划增加 `run_id` 参数，但**未提及需要将 `source_version` 改为 `self.source_version`**。当管线以 `source_version='v1_repro'` 实例化时，null_record中 `source_version` 仍为 `'v1'`，造成数据隔离失效——实验产生的NULL记录混入基线数据。

```
null_record source_version = 'v1'     ← 缺陷！应为 self.source_version
正常ic_record source_version = self.source_version = 'v1_repro'  ← 正确
```

**影响**：实验过程中被跳过截面产生的NULL记录进入了 `source_version='v1'` 数据空间，污染基线数据。在Phase 1就可以发现（P1.8验证 `GROUP BY source_version` 时，'v1' 数据量会多于备份前）。

#### 6.2 时序并发假设

试验方案假设所有运行是**串行**的（不并行运行多个pipeline实例），这避免了run_id冲突和并发写入问题。此假设是合理的，但在结论文档中应明确此约束。✅

#### 6.3 `_check_environment_health` 阈值不可配置

当前 `_check_environment_health(min_available_gb=4.0)` 是静态方法，默认4GB阈值硬编码。Phase 2的启动前检查要求6GB，但代码中对此无强制校验——operator需手动确认。建议：如果试验管线以 `source_version='v1_repro'` 运行时自动提高阈值到6GB，或在C7入口脚本中增设 `--min-memory` 参数。

---

## 三、缺陷汇总

| ID | 严重度 | 类型 | 发现项 | 触发阶段 | 影响 |
|:--:|:------:|:-----|:-------|:--------:|:-----|
| D2 | **严重** | 数据一致性 | 唯一索引未包含run_id，INSERT OR IGNORE在新run_id写入同截面时静默跳过 | Phase 2 | 导致U2验证不可靠，`GROUP BY run_id` 计数偏差 |
| D1 | **严重** | 架构完整性 | from_config()工厂方法未透传run_id；入口脚本C7未实现resume机制；run_id与pipeline_run_id双ID系统未对接 | Phase 2 | SIGKILL后重启时resume不可用。若operator跳步到restart，U2计数偏差 |
| D5 | **中** | 数据污染 | _build_null_record硬编码 source_version='v1'，实验跳过截面产生的NULL记录污染基线数据 'v1' | Phase 1/2 | 基线数据量增加，隔离失败 |
| D4 | **中** | 可移植性 | 附录C遗漏SIGKILL行为差异、ulimit支持差异、WSL2内存回收策略、文件系统IO差异、psutil准确性5项 | 结论 | U1/U2结论在原生Linux环境需重新确认 |
| D3 | **低** | 认知边界 | psutil检查点在截面循环开头，与真实内存峰值存在偏移 | Phase 2/OOM | OOM可能发生在两次检查之间，监控无法捕获计算中峰值 |

---

## 四、条件性通过的先决条件

在Phase 2执行前，以下条件必须满足：

### 条件C1（对应D2）：修正唯一索引或调整写入策略

**二选一**：

**方案A（推荐）**：在Phase 0的ALTER TABLE之后，DROP旧唯一索引并创建包含 run_id 的新索引：
```sql
-- 执行顺序
DROP INDEX idx_ic_uniq;
CREATE UNIQUE INDEX idx_ic_uniq_v2 
ON a50_cross_ic_result (trade_date, factor_name, forward_window, source_version, run_id);
```
- 优点：精确区分每次写入，INSERT OR IGNORE在相同run_id内部防重，不同run_id记录共存
- 风险：重跑数据量加倍（每个截面N个run_id对应N条记录）

**方案B**：修改 `INSERT` 从 `INSERT OR IGNORE` 改为 `INSERT OR REPLACE`，并按 `run_id` 覆盖写入。
- 优点：数据量不膨胀
- 缺点：丢失旧run_id的写入记录，U2验证时无法看到分步写入量

> **建议方案A，但需墨萱确认唯一约束变更对现有查询无副作用。**

### 条件C2（对应D1）：确认重启resume机制

必须指定在SIGKILL后重启时，如何将目标checkpoint（旧pipeline_id）与新的 `run_id` 对接。至少需要：

1. C7入口脚本新增 `--resume-from PIPELINE_ID` 参数
2. 操作流程中注明：kill后先查看checkpoint文件获取旧pipeline_id
3. 重启命令示例：`--run-id repro_p2 --resume-from ic_pipeline_20260531_020000_a1b2c3d4`

或更简单的替代方案：
4. 使用 **date_range分段运行**替代resume机制。例如近5年数据按年拆分为5个独立的date_range，各分配独立run_id。即使某段被杀也只需重跑该段，不存在resume问题。**这不需要任何代码改动，且对U2验证无影响。**

### 条件C3（对应D5）：修复_build_null_record的source_version

将 `_build_null_record` 中的硬编码 `SOURCE_VERSION` 改为实例变量 `self.source_version`：

```python
@staticmethod
def _build_null_record(date, factor_name, n_stocks, run_id=None, source_version=SOURCE_VERSION):
    return {
        ...
        "source_version": source_version,  # ← 使用传入的参数
        ...
    }
```

调用侧改为 `self._build_null_record(date, factor_name, n_stocks, self.run_id, self.source_version)`。

---

## 五、补充建议（无需本次实现）

### S1：run_id元数据表

建议在未来架构规划中增加 `experiment_run_meta` 表（见审查项4.2），将run_id从"行级字段"升级为"有元数据的实体"。可解决：
- 事后追溯run_id含义（marine-s/mellow-o/norun分别是什么）
- 实验间数据清理
- 查询时直接关联 run_id → run_date_range

### S2：psutil监控增强

考虑在 `run_pipeline` 方法内部也嵌入内存检查点（如在因子计算前后、IC引擎计算前后），而非仅在截面循环开头。这可以在**不增加显著性能开销**的前提下（每次 `psutil.virtual_memory()` 仅~10μs），提升OOM关键时刻的捕获概率。

### S3：run_id 与 pipeline_run_id 统一

长远看，建议将 `run_id`（用户传入的DB标识）和 `pipeline_run_id`（checkpoint标识）统一为同一个值，或建立明确映射表。当前两套ID系统增加了调度重启时的认知负担。

---

## 六、验收声明

| 验收项 | 结果 | 备注 |
|:-------|:----:|:------|
| A2（代码改动最小侵入） | ✅ PASS | 改动范围可控，不影响现有v1基线功能 |
| A4（数据隔离方案完整） | ⚠️ CONDITIONAL | D2+D5需修复，修复后PASS |
| A7（WSL2环境差异考虑） | ⚠️ CONDITIONAL | D4中5项遗漏需补充附录C，补充后PASS |

---

*EOF — 玄知审查报告*
