<!--
author: 墨萱
created_time: 2026-05-20T21:31:00+08:00
topic: 数据录入交叉验证规范
task: 对话式会议发言（第二发言 — 测试验收视角）
-->

# 数据录入交叉验证规范 — 墨萱意见（测试验收）

## 0. 预估与置信度

- **预估耗时**：本意见输出 30-40 分钟；完整测试实施约 4-6 小时
- **置信度**：90% — 核心风险点清晰，测试方案明确，部分需要墨衡确认技术细节后锁定

---

## 1. 验收红线 — 怎么确认这条规矩被执行？

墨衡方案说了"怎么做"，但测试验收需要知道"怎么算做到"。我从**四个维度**定义验收红线：

### 红线一：验证机制存在性（硬件）

| 验收项 | 验收标准 | 测试方法 |
|--------|---------|---------|
| E.01-001 | 代码库中存在交叉验证函数（validate_cross_source） | PR diff 审查 + 函数存在性断言 |
| E.01-002 | 映射表完备：横轴覆盖至少 2 个数据源，纵轴覆盖 Phase 1 全字段 | 读取映射表 YAML，逐字段检查 |
| E.01-003 | ETL 管线的 transform 阶段包含 validate 步骤 | CI 流水线测试 + 调用链截图 |
| E.01-004 | 规则版本号可追溯（每条审计记录携带版本哈希） | 写入测试记录后查 audit_log |

**否决条件**：以上任一项缺失 → **D 级**不通过，不可进入 Phase 2

### 红线二：阻断逻辑正确性（功能）

| 验收项 | 验收标准 | 测试方法 |
|--------|---------|---------|
| E.02-001 | 两源数据在阈值内 → 数据**正常写入**主表 | 构造符合值对，查主表含预期数据 |
| E.02-002 | 两源数据超阈值且无 diff_reason → 数据**不写入**主表，**写入** staging_raw | 构造超阈值值对 + 空 diff_reason，查主表为 NULL，查 staging_raw 含原始值 |
| E.02-003 | 两源数据超阈值但有合法 diff_reason → 数据**正常写入**主表，**附带** diff_reason | 构造超阈值值对 + 合法 diff_reason，查主表含数据，查 audit_log 含 reason |
| E.02-004 | 单源关键字段 → 触发**量级范围检查**（非阻写，但标记 WARN） | 构造单源数据 + 超量级值，查审计日志含 WARN |
| E.02-005 | 单源非关键字段 → **无验证**，直接写入 | 构造单源扩展字段值，审计日志无记录 |

**否决条件**：任何一条不通过 → **C 级**不通过，需要修补后回归

### 红线三：异常容错（健壮性）

| 验收项 | 验收标准 | 测试方法 |
|--------|---------|---------|
| E.03-001 | 一个数据源完全不可用（网络超时） → **不阻断**另一个源写入，降级为单源合理性检查 | 模拟源 B 超时，验证源 A 数据正常写入 |
| E.03-002 | 一个数据源返回格式异常（非预期字段名/类型） → **WARN 告警**，不崩溃 | 注入畸形 JSON，验证异常捕获 + WARN 日志 |
| E.03-003 | 映射表中无此字段 → **通过验证，不触发检查** | 构造映射表中不存在的字段，验证无阻断 |
| E.03-004 | 并发写入同一字段 → 无竞态条件导致错误 | 多线程并发写入测试 |

### 红线四：审计完整性（可追溯）

| 验收项 | 验收标准 | 测试方法 |
|--------|---------|---------|
| E.04-001 | 每次验证触发都生成唯一 audit_log 记录 | 写入 10 条记录，查 audit_log 有 10 行 |
| E.04-002 | 审计日志字段完整（见第 4 节） | 查 audit_log 表 schema |
| E.04-003 | 事后修正可追溯原记录 | 构造 RECALL 流程，验证新旧版本关联 |

---

## 2. 覆盖范围 — 优先级排序

同意墨衡的核心分类，但**补充一个维度：字段的业务关键性**决定了测试优先级。

### 真正的优先级矩阵

| 优先级 | 字段 | 理由 | 测试优先级 |
|--------|------|------|-----------|
| **P0（立即）** | open, high, low, close, volume, amount | 所有分析指标的基础，错误传导放大 | 高 |
| **P0（立即）** | trade_date + symbol 联合（主键等价物） | 时间戳/代码错误直接导致记录错位 | 高 |
| **P1（本周）** | total_shares, negotiable_shares, market_cap | 影响流通市值计算，单位混用高发 | 高 |
| **P2（本月）** | PE, PB, dividend_yield | 需要关注财报日期对齐，比对逻辑更复杂 | 中 |
| **P3（下月）** | 财报衍生字段（每股收益、净资产等） | 跨源口径差异大，阈值需单独定 | 中 |
| **P4（待定）** | 非关键枚举字段（industry、行政区等） | 格式归一化为主，不做数值验证 | 低 |

### ⚠️ 我对墨衡方案的补充建议

**墨衡缺了一个关键点**：他列了 `volume` 但没提 `trade_date` 和 `symbol`。这两个字段是**K线记录的唯一性标识**，如果它们错位：

- `2026-05-20` 的 volume 被关联到 `2026-05-19` → 数值交叉验证完全通过（因为两个 API 返回的数字确实一致）
- 但记录已经错了——**这是时间错位问题，不是数值差异问题**

**建议**：把 `trade_date`、`symbol` 的交叉验证优先级提升到 **P0**，和价格成交量同等级。验证方法不是数值比对，而是：
- 日期格式归一化（YYYY-MM-DD vs YYYYMMDD vs timestamp）
- 代码格式归一化（6位数字 vs 市场前缀 SH600000）
- 跨源日期一致性检查（两个 API 同一 code 是否返回同一交易日的 K 线）

---

## 3. 墨衡方案的风险点分析

### 风险一：验证引擎本身未测试（最致命）

墨衡写了完整的方案，但**没有定义如何测试这个验证机制本身**。

- **风险描述**：验证函数有 Bug，两个真正一致的值被误判为不一致（假阳性），或者不一致的值被放行（假阴性）。这会导致两种情况：要么合规数据被拒绝写入造成空洞，要么坏数据被放行——而无论哪一种，下游根本无法发现，因为验证环节本身认为是"已检查"。
- **严重程度**：高。这是验证系统的"吃自己的狗粮"问题。
- **建议**：在墨衡的 Phase 1 中加入"验证函数的测试套件"作为必须交付物（见第 5 节）。

### 风险二：阈值默认值缺乏数据支撑

墨衡建议 `价格 ±0.5%，成交量 ±3%`。这个值是在没有统计分布数据的情况下拍定的。

- **风险描述**：如果实际跨源差异的 95% 分位数是 1.2%，那么 0.5% 的阈值会导致 20%+ 的合法数据被阻断；如果真实差异中位数是 0.1%，那 0.5% 太宽松会漏检。
- **建议**：Phase 1 实施时先跑**一周统计预生产模式**：只记录差异分布，不阻断写入。根据实际 P50、P95、P99 差异来定阈值。

### 风险三：diff_reason 是自由文本

墨衡说"存在可解释差异 → diff_reason 说明原因"。这引入了验证系统的**语言侧信道**：

- 人工写的 diff_reason 拼写错误（"shares" vs "share" vs "stock" vs "lot"）→ 系统无法统一判断
- diff_reason 内容不标准 → 后续自动化分析困难

**建议**：

1. **枚举化 diff_reason**：定义有限集合 `{UNIT_CONVERTED, SPLIT_DIFF, DIVIDEND_ADJUSTED, AFTER_HOUR_TRADE, DELAYED_SOURCE, OTHER}`，`OTHER` 需要额外人工理由字段
2. 枚举由系统自动推断（如单位差异自动 tag `UNIT_CONVERTED`），减少人工依赖

### 风险四：staging_raw 存什么？——要有明确的 schema 约定

墨衡提到"数据写入 staging_raw.{table_name}"，但没有定义 schema。这个很危险：

- 如果 staging_raw 只是简单存 raw JSON，那事后人工查找特定字段值差异时非常痛苦
- 建议定义标准化 staging_raw 结构（见第 4 节 audit_log 部分）

### 风险五：并发写入的竞态条件

墨衡方案没有讨论多线程/多进程环境下的写入逻辑。

- **风险场景**：两个 ETL job 同时写同一只股票同一日的 K 线 → 一个先写 staging_raw，另一个还没完成验证 → 交叉状态可能不一致
- **严重程度**：中等（取决于部署方式）
- **建议**：写入操作加 row-level lock 或使用 `INSERT ... ON CONFLICT DO NOTHING` 模式。

---

## 4. 审计日志最少字段

墨衡提了 `task_id, source_fields, diff_values, possible_reasons, rule_version`。我认为不完整。

### 审计日志最低字段集（validation_audit_log）

```sql
CREATE TABLE validation_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    
    -- 基本信息
    task_id         TEXT NOT NULL,        -- ETL job ID，可关联回原始 pipeline 日志
    rule_version    TEXT NOT NULL,        -- 规则版本哈希（git commit sha 或 hash）
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 字段定位（必填）
    table_name      TEXT NOT NULL,        -- 被验证的目标表名
    field_name      TEXT NOT NULL,        -- 被验证的字段名（如 'volume'）
    symbol          TEXT NOT NULL,        -- 股票代码
    trade_date      DATE NOT NULL,        -- 交易日
    
    -- 源数据信息（必填）
    source_a_name   TEXT NOT NULL,        -- 数据源 A 名称（如 'eastmoney'）
    source_a_val    NUMERIC,              -- 源 A 归一化后的值（可以是 NULL 如果源不可用）
    source_a_unit   TEXT,                 -- 源 A 的单位（如 'shares'）
    source_b_name   TEXT NOT NULL,        -- 数据源 B 名称（如 'sina'）
    source_b_val    NUMERIC,
    source_b_unit   TEXT,
    
    -- 验证结果
    threshold_pct   NUMERIC(5,2) NOT NULL, -- 检查时使用的阈值百分比
    diff_pct        NUMERIC(10,4),        -- 实际差异百分比（NULL 表示类型不同无法计算）
    result          TEXT NOT NULL CHECK(result IN ('PASS', 'FAIL', 'WARN')),
        -- PASS: 验证通过，写入主表
        -- FAIL: 验证不通过，写入 staging_raw + 主表 NULL
        -- WARN: 单源合理性检查触发的告警
    
    -- 差异原因（FAIL 且通过人工覆盖时才非空）
    diff_reason_enum TEXT CHECK(diff_reason_enum IN (
        'UNIT_CONVERTED', 'SPLIT_DIFF', 'DIVIDEND_ADJUSTED',
        'AFTER_HOUR_TRADE', 'DELAYED_SOURCE', 'NOT_APPLICABLE', 'OTHER'
    )),
    diff_reason_note TEXT,                -- OTHER 时的自由文本理由（或额外备注）
    
    -- 人工补救追踪（后续的 RECALL/修正记录关联用）
    correction_id   TEXT,                 -- 关联到 correction_log 表
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT                  -- 操作人（agent name 或 human name）
);
```

### 为什么比墨衡的清单多这些字段？

| 新增字段 | 必要性 |
|---------|--------|
| symbol + trade_date | 没有这两个字段，无法精确定位哪条记录出错（墨衡的方案里 "source_fields" 太模糊） |
| source_a_val + source_b_val | 保留实际数值而非只记 "diff_values" —— 这样未来调整阈值时可以重新计算 |
| threshold_pct + diff_pct | 记录**实际使用的阈值**，便于日后分析阈值合理性与调整依据 |
| result 枚举 | 显式标记 PASS/FAIL/WARN，测试时可通过此字段直接断言 |
| correction_id | 关联后续修正，形成完整的审计链条 |

---

## 5. 测试方案 — 怎么测试验证机制本身？

这是墨衡方案最大的缺口。以下是我建议的测试层级：

### 5.1 单元测试（验证函数级别）

```
test_validate_cross_source.py

├── test_equal_values_should_pass()
│   ├── 条件：两源完全一致（volume: 1000000 vs 1000000）
│   └── 断言：result == 'PASS'

├── test_unit_diff_should_convert()
│   ├── 条件：1000000 shares vs 10000 lots（设 1 lot = 100 shares）
│   ├── 预期：归一化后一致（1000000 vs 1000000）
│   └── 断言：result == 'PASS'

├── test_big_diff_no_reason_should_fail()
│   ├── 条件：volume 差 15%，无 diff_reason
│   └── 断言：result == 'FAIL'

├── test_big_diff_with_reason_should_pass()
│   ├── 条件：volume 差 15%，diff_reason = 'AFTER_HOUR_TRADE'
│   └── 断言：result == 'PASS'

├── test_edge_threshold_exact_boundary()
│   ├── 条件：差异 0.499% （价格类，阈值 0.5%）
│   ├── 条件：差异 0.501%
│   └── 断言：边界通过 vs 边界不通过

├── test_null_source_no_block()
│   ├── 条件：源 B 不可用 → 源 A 数据正常写
│   └── 断言：降级为 WARN，不阻断

├── test_malformed_input_not_crash()
│   ├── 条件：非数值输入（字符串 'vol'）
│   └── 断言：抛出具体异常，不崩溃

├── test_unit_conversion_table_completeness()
│   ├── 条件：遍历映射表中所有字段的 units 定义
│   └── 断言：每个字段都有单位定义，无遗漏
```

### 5.2 集成测试（ETL 管线级别）

```
test_etl_validate_integration.py

├── test_etl_happy_path()
│   ├── 准备：构造东财 & 新浪 mock API，返回完全一致的数据
│   ├── 执行：触发 ETL pipeline
│   └── 断言：数据正常写入主表，audit_log.result == 'PASS'

├── test_etl_fail_path()
│   ├── 准备：构造差异 10% 且无 diff_reason 的 mock 数据
│   ├── 执行：触发 ETL pipeline
│   └── 断言：主表字段为 NULL，staging_raw 有记录，audit_log.result == 'FAIL'

├── test_etl_recover_path()
│   ├── 准备：先写入 FAIL 数据到 staging_raw
│   ├── 执行：人工修正后触发 RECALL 流程
│   └── 断言：主表更新为修正值，correction_log 有记录

├── test_etl_threshold_config_live()
│   ├── 准备：修改阈值配置文件（价格改为 1.0%）
│   ├── 执行：重复 test_fail_path（现差异 0.8%）
│   └── 断言：调整阈值后原本 FAIL 的记录变 PASS

├── test_etl_concurrent_same_record()
│   ├── 准备：双线程同时写入同一 symbol+date
│   └── 断言：无死锁，无数据丢失，audit_log 两条记录
```

### 5.3 回归测试（数据源变更场景）

```
test_regression_data_source.py

├── test_api_contract_change()
│   ├── 场景：东财 API 升级（字段名从 'f5' 改为 'volume'）
│   ├── 模拟：修改 mock API 响应
│   └── 断言：映射表维护到位前，验证不影响正常路径

├── test_new_field_added()
│   ├── 场景：将 turnrate 新增到验证映射表
│   ├── 模拟：添加映射条目
│   └── 断言：新旧字段混合写入无影响

├── test_rule_version_tracking()
│   ├── 场景：多次修改验证规则
│   └── 断言：audit_log 中每版本可追溯
```

### 5.4 契约测试（mock API 接口层）

需要确保 mock API 和真实 API 返回格式对齐。否则单元测试通过、生产环境挂。

- 针对东财、新浪各自实际 API response 做 schema validation
- mock API 从真实快照生成，定期更新

---

## 6. 总结：我的补充要点

### 对墨衡方案的核心补充

| 维度 | 墨衡方案 | 墨萱补充 |
|------|---------|---------|
| 验收标准 | 未定义 | 四维度验收红线 + 否决条件 |
| 字段覆盖 | 列了 volume/amount/价格 | 补 trade_date + symbol 为 **P0** |
| 阈值 | 拍定值 ±0.5%/±3% | 建议先跑一周统计预生产再定 |
| diff_reason | 自由文本 | 建议枚举化 + 系统自动推断 |
| 测试方案 | 无 | 四级测试金字塔（单元→集成→回归→契约） |
| 审计字段 | 4 个字段 | 15 个字段（精确定位 + 可追溯） |
| 竞态 | 无讨论 | 建议加 row-level lock |
| 映射表 | 提到但无测试 | 建议加映射表完备性自动化断言 |

### 我的最终判断

**方案方向正确，但墨衡忽视了验证机制本身的测试闭环。** 测试金字塔是质量保证的命门——没有它，验证系统本身可能比它要验证的数据错误还要不可靠。

建议在 Phase 1 的交付清单中**硬性要求**包含：
1. 测试套件（覆盖率 > 90%）
2. 预生产统计模式（1 周）
3. 审计日志 schema 落地

验收时我会先跑全套测试套件，不过关就否决。
