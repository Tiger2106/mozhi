<!--
  author: 墨衡（MoHeng）
  created_time: 2026-05-17 19:17 +08:00
  task: 玄知9项战略风险/盲点处理
  source: phase_review_xuanzhi_20260517.md
  status: 完成
-->

# 玄知9项战略风险/盲点 — 分级处理行动方案

> **优先级判定主体：** 墨衡（深度投资专家）
> **判断准则：** 影响面深度（方法论 vs 流程 vs 工具）× 不可逆性（时间累积放大程度）× 阻塞后续任务的程度
> **执行时间：** 2026-05-17 19:17+08:00

---

## 优先级总览

| 优先级 | # | 类型 | 内容 | 处理方式 |
|:------:|:-:|:----:|------|:--------:|
| **P0** | 5 | 🔴风险 | "0%偏差"虚假安全感 | 补充强制回归验证说明 (文档) |
| **P0** | 7 | 🔴风险 | 无"回测vs实盘"校准机制 | 补充校准流程文档 (文档) |
| **P0** | 9 | 🔴风险 | 知识单点依赖 | 补充缺失文档 (文档) |
| **P1** | 1 | 🔴盲点 | 用户视角缺失 — KB无前端 | 启动Frontend UI (文档+代码计划) |
| **P1** | 8 | 🟡风险 | 监控告警缺失 | 纳入待办清单 (文档) |
| **P1** | 4 | 🟡盲点 | Bitable持久运维 | 补充运维文档 (文档+代码计划) |
| **P2** | 2 | 🟡盲点 | 新旧过渡期未量化 | 定下线计划 (文档) |
| **P2** | 6 | 🟡风险 | KB与回测系统耦合 | 架构文档补充 (文档) |
| **P3** | 3 | 🟡盲点 | R3/R4悬空 | 归入下阶段规划 (记录) |

### 优先级推导依据

**P0（方法论根基，不可逆性高）：**
- #5 "0%偏差" 是验证体系的根本缺陷。**时间越大，未经验证的新Method累积越多，偏差失控的速度是非线性的**。必须建立强制回归验证流程，使其成为开发流程的门禁。
- #7 "回测vs实盘" 是策略系统正确的唯一外部锚点。没有此机制，回测系统的正确性无法被外部验证，所有策略决策都建立在"假设"之上。
- #9 "知识单点依赖" 是项目的人因脆弱性。**文档缺失程度直接决定故障恢复时间**。当前阶段知识密集度极高，任何关键成员中断都将导致数天甚至数周的知识重建。

**P1（功能性阻塞，风险累积快）：**
- #1 "用户视角缺失" 阻塞了整个KB链路的最终价值闭环。后端架构已完成，前端的缺失意味着知识只能采集无法消费，这是ROI的断裂点。
- #8 "监控告警缺失" 和 #4 "Bitable持久运维" 是运维保障层。虽非方法论缺陷，但无声失败一旦发生，影响范围可达"整日无策略信号"。

**P2（架构完善，风险可缓冲）：**
- #2 "新旧过渡期" 和 #6 "KB与回测耦合" 影响的是演进成本，不直接影响当前正确性。可以在有明确排期后处理。

**P3（未来规划）：**
- #3 "R3/R4悬空" 需要先查明评审会纪要中的原始内容，再评估是否适用。

---

## P0-5：「0%偏差」虚假安全感 — 强制回归验证流程

### 问题本质

当前验证体系存在一个结构性问题：**10个Method的0%偏差验证是一次性检验，而非持续性质量门禁**。后续新增的Method可以不经新旧对比直接进入生产，历史验证结论会被错误地外推到未经验证的新Method上。

### 根因

1. 验证流程仅覆盖了迁移阶段的「一次性检查」，没有建立「新Method引入时的强制门禁」
2. `test_backtest_contracts.py` 覆盖的是契约合规性（接口签名正确），而非新旧Runner输出一致性
3. 系统中不存在「已验证Method白名单 vs 待验证Method黑名单」的管控机制

### 行动方案

#### 文档产出：补充到 `docs/02_development/` 或独立为 `docs/05_protocols/method_regression_testing.md`

**必须定义以下流程：**

```
新Method开发完成
       │
       ▼
[Step 1] 注册到 Registry（自动）
       │
       ▼
[Step 2] 在 tests/regression/ 下创建回归测试
         ├── 输入：Method + 标准测试数据（fixtures）
         ├── 输出：新旧Runner输出对比 → 阈值≤0.1%
         └── 框架：pytest + parametrize（复用现有测试基础设施）
       │
       ▼
[Step 3] 运行 `pytest tests/regression/ --regression-mode=full`
       │
       ▼
[Step 4] 偏差超出阈值 → 阻断PR/MR，强制修复
         偏差在阈值内 → 自动标记为 "regression_verified: true"
```

**核心规则：**
| 规则 | 详细 |
|------|------|
| **强制门禁** | 新Method的PR中必须包含 regression test，否则不可合入 main 分支 |
| **全量回归周期** | 每周全量跑一次所有已验证Method的回归测试（cron job） |
| **白名单管理** | `registry/method_whitelist.json` 记录已验证Method + 验证时间戳 |
| **黑名单升级路径** | 未验证Method可标注 `experimental=True`，允许以实验模式运行，但不进入生产信号管道 |
| **偏差阈值** | 沿用 Phase 2 标准：新旧Runner输出差异 ≤ 0.1%（价格精度） |

#### 代码修改计划

| 修改位置 | 内容 | 预估耗时 |
|----------|------|----------|
| `tests/regression/` (新建) | 回归测试目录 + `test_method_regression.py` | 2h |
| `src/backtest/registry/` | 方法白名单json + 标记字段 `regression_verified` | 0.5h |
| CI 配置文件/Makefile | 添加 `make regression` 命令 | 0.5h |
| `tests/conftest.py` | 补充标准回测fixtures | 1h |
| **合计** | | **4h** |

---

## P0-7：回测 vs 实盘 — 校准机制缺失

### 问题本质

回测跑通 ≠ 实盘有效。当前架构仅验证了「新旧Runner语义不变」（0%偏差），但**没有验证「语义本身是否正确」** ——即Method的策略逻辑在真实市场中是否产生预期效果。

### 行动方案

#### 文档产出：`docs/05_protocols/backtest_calibration_protocol.md`

**校准流程设计：**

```
每月校准周期
       │
       ▼
[Step 1] 采集最近30个交易日的：
         ├── 回测模拟结果（给定起始资金 × 选定Method）
         ├── 实盘实际收益（SamePeriod窗口）
         └── 基准收益（如沪深300同期涨跌幅）
       │
       ▼
[Step 2] 计算偏差指标：
         ├── 收益偏差 = |回测收益 - 实盘收益|
         ├── 超额偏差 = |(回测收益 - 基准) - (实盘收益 - 基准)|
         ├── 胜率偏差 = |回测胜率 - 实盘胜率|
         └── 最大回撤偏差 = |回测最大回撤 - 实盘最大回撤|
       │
       ▼
[Step 3] 阈值判定：
         ├── 收益偏差 ≤ 5% → ✅ 正常
         ├── 5% < 偏差 ≤ 15% → ⚠️ 预警（需排查原因）
         └── 偏差 > 15% → ❌ 严重偏差（暂停策略，人工审计）
       │
       ▼
[Step 4] 输出校准报告：
         ├── calibrated: true/false
         ├── deviations: {收益偏差, 超额偏差, ...}
         └── actions: [人工排查项]
```

**工具链实现：**

| 组件 | 说明 | 预估耗时 |
|------|------|----------|
| `src/monitoring/backtest_calibrator.py` | 校准计算核心（回测vs实盘对比） | 3h |
| `src/monitoring/calibration_report.py` | 校准报告生成（JSON + 飞书消息） | 1h |
| Monthly cron | 月度自动触发 | 0.5h |
| **合计** | | **4.5h** |

---

## P0-9：知识单点依赖 — 文档严重不足

### 问题本质

Phase 1-5 + KB Phase 1-3 的数千行代码、数百个模块、958+1049 个测试用例的知识高度集中在墨衡/墨萱/墨涵三人头脑中。当前文档体系中：

- 已存在：架构总览、信号协议、cron配置等运营文档
- **严重缺失的领域：**
  1. 插件系统开发指南（如何写一个Method/Factor/Strategy）
  2. Method Backtest Runner 双模式运作原理
  3. KnowledgeBridge 数据流和扩展点
  4. BitableSync 接入指南（权限、配置、测试）
  5. 通用问题排查（Troubleshooting）手册

### 行动方案

#### 文档产出清单

| # | 文档 | 目标读者 | 位置 | 预估耗时 | 优先级 |
|:-:|------|---------|------|:--------:|:------:|
| 1 | 插件系统开发者手册 | 策略开发者 | `docs/02_development/plugin_dev_guide.md` | 4h | P0 |
| 2 | MethodBacktestRunner 原理 | 运维/主程 | `docs/03_pipelines/runner_architecture.md` | 2h | P0 |
| 3 | KnowledgeBridge 扩展指南 | 下游开发者 | `docs/02_development/knowledge_bridge_extend.md` | 2h | P0 |
| 4 | BitableSync 运维手册 | 运维 | `docs/06_operations/bitable_sync_ops.md` | 1h | P1 |
| 5 | Troubleshooting 快速排错 | 全员 | `docs/06_operations/troubleshooting.md` | 1.5h | P1 |
| **合计** | | | | **10.5h** | |

**特别注意：** 以上文档应在后续2周内完成撰写，建议排入下一迭代的Sprint中。

---

## P1-1：用户视角缺失 — KB 前端 UI

### 当前状态

`knowledge_frontend_design_v2_20260517.md` v2方案已于今日（2026-05-17）通过。Bitable作为最小可用界面的架构方向已确定，Phase 1-3 架构设计完备。

### 阻塞点

| 阻塞项 | 状态 | 依赖 |
|--------|:----:|------|
| 飞书 App 权限 `bitable:bitable` | ⏳ 待确认 | 需Owner在飞书开发者后台开通 |
| Bitable app_token | ⏳ 待创建 | 飞书权限开通后执行 |
| BitableSync 组件编码 | ⬜ 未开始 | Phase 1b 实际编码 |
| KnowledgeEntry v2 数据灌入 | ⬜ 未开始 | SQLite源数据准备 |

### 推进路径

```
[Phase 1a] KnowledgeEntry v2 基类 + Normalizer → 编码 2h
     │
     ▼
[Phase 1b] BitableSync 同步器 → 编码 3h
     │
     ▼
[Phase 1c] Runner接入 → 编码 + 测试 2h
     │
     ▼
[Phase 2] KnowledgeSearch → 编码 3h
     │
     ▼
[Phase 3] KnowledgeAnalyzer 仪表盘 → 编码 2h
```

**总预估耗时：12h**（不含权限开通等待时间）

### 风险提示

当前飞书 App 权限 `bitable:bitable` 尚未开通。这是阻塞 Phase 1b 的**硬依赖**。建议立即在飞书开发者后台完成权限配置。

---

## P1-8：监控告警缺失 — 升为下阶段 P0

### 问题定位

当前 `src/monitoring/` 目录下**空无内容**（仅有 `__init__.py`）。回测系统在无人值守模式下运行时，任何错误都需要等到下次人工检查才能发现。

### 行动方案

#### 监控维度矩阵

| 监控维度 | 指标 | 告警方式 | 实现状态 |
|----------|------|----------|:--------:|
| Runner 运行状态 | 每日是否完成回测 | 未完成时发飞书群消息 | ⬜ 未实现 |
| Method 异常率 | 报错Method数 / 总Method数 > 5% | 飞书群告警 | ⬜ 未实现 |
|  Pipeline 耗时 | 超过历史均值2σ | 飞书群告警 | ⬜ 未实现 |
| 磁盘空间 | Data/Reports目录 > 90% | 飞书群告警 | ⬜ 未实现 |
| 回测偏差 | 校准偏差 > 15% | 紧急停止信号 | ⬜ 未实现 |

#### 代码修改计划

| 修改位置 | 内容 | 预估耗时 |
|----------|------|----------|
| `src/monitoring/runner_monitor.py` | Runner运行状态监控 | 2h |
| `src/monitoring/pipeline_monitor.py` | Pipeline耗时监控 | 1.5h |
| `src/monitoring/health_check.py` | 系统健康检查（磁盘/内存） | 1h |
| `src/signals/alerter.py` | 统一告警发送模块（飞书消息） | 1h |
| cron配置 | 每日07:30跑健康检查 | 0.5h |
| **合计** | | **6h** |

---

## P1-4：Bitable 持久运维 — Token过期 / API变更监控

### 问题本质

BitableSync 真实 API 已完成访问令牌验证和 E2E 测试通过，但**没有建立运维持续保障机制**：
1. 飞书 App `tenant_access_token` 过期后，BitableSync 静默失败
2. 飞书 API 接口变更无自动化通知
3. 同步错误无熔断/重试兜底

### 行动方案

#### 文档产出：`docs/06_operations/bitable_sync_ops.md`

**必须覆盖的运维场景：**

| 场景 | 检测机制 | 响应动作 | 优先级 |
|------|----------|----------|:------:|
| Token 过期 | `_fetch_token()` 捕获 `99991663` 错误码 | 自动重试 + 飞书群告警 | P0 |
| API 限流 | 捕获 `99991400`/`99991401` 限流码 | 指数退避（当前已实现） | ✅ 已实现 |
| API 不兼容变更 | 每月一次手工验证 E2E 脚本 | 手动触发全链路测试 | P1 |
| Bitable Schema 不匹配 | `schema_version` 冲突检测 | 飞书群告警 + 触发 schema 升级 | P1 |
| 同步队列入队失败 | 熔断器状态监测 | 降级为本地文件存储 + 告警 | P1 |

**代码修改计划：**

| 修改位置 | 内容 | 预估耗时 |
|----------|------|----------|
| `src/signals/bitable_fault.py` | Bitable故障检测与告警模块 | 1.5h |
| `config/credentials.json` | 补充Token刷新倒计时监控 | 0.5h |
| BitableSync 重试熔断逻辑 | 最大重试3次的硬限制 + 熔断 | 1h |
| **合计** | | **3h** |

---

## P2-2：新旧过渡期未量化 — 下线时间表

### 当前状态

`run_trend.py` / `run_reversal.py` / `run_grid.py` 已标注 DEPRECATED（Phase 5完工），但未物理删除。新旧 Runner 双模式并存。

### 下线计划

```
[2026-05-24 前]
   ├── 完成所有待迁移策略的验证（若还有旧策略依赖旧入口）
   ├── 补充迁移指南文档：docs/03_pipelines/migration_guide_legacy_runner.md
   │   └── 内容：旧入口与新命令的映射表 + 配置文件迁移说明
   │
[2026-06-01] ← 建议下线截止日
   ├── 物理删除 run_trend.py / run_reversal.py / run_grid.py
   ├── 删除前最后一次全量回归验证
   └── 删除后保留`legacy_adapter.py`作为兼容垫片（但不建议长期保留）
```

**迁移指南文档要点：**

| 旧入口 | 新入口 | 迁移步骤 | 兼容期 |
|--------|--------|----------|:------:|
| `python run_trend.py --symbol XXX` | `python run_new.py --method trend` | 1) 安装最新环境 2) 替换命令 | ~2周 |
| `python run_reversal.py --symbol XXX` | `python run_new.py --method reversal` | 同上 | ~2周 |
| `python run_grid.py --symbol XXX` | `python run_new.py --method grid` | 同上 | ~2周 |

---

## P2-6：KB 与回测系统耦合 — 架构文档补充

### 决策方向

KnowledgeBridge 应**维持轻量耦合设计**，不成为回测系统的核心依赖：

```
当前耦合关系：
  Runner → KnowledgeBridge.harvest()      ← 单向推送，Runner不依赖KB返回
  KB只读：KnowledgeSearch / KnowledgeAnalyzer  ← Bitable/本地文件为数据源
  KB与Runner无共享状态                     ← 无循环依赖
```

### 耦合度衡量指标

| 指标 | 当前值 | 目标值 |
|------|:------:|:------:|
| KB对Runner的接口调用次数（一次回测周期） | 0 | 0 |
| Runner对KB的返回值的依赖（非可选项） | 0 | 0 |
| KB与Runner共享的数据库/文件表 | 0 | 0 |
| 因KB修改导致Runner测试失败的次数 | 0 | 0 |

**结论：当前耦合度在可接受范围。** 不需要解耦重构，但需要在架构文档中明确 KB 的「旁挂」定位。

#### 待补充文档

| 文档 | 内容 | 预估耗时 |
|------|------|----------|
| `docs/01_architecture/overall_architecture.md` 中补充 | KB定位说明 + 耦合度承诺 | 0.5h |

---

## P3-3：R3/R4 悬空 — 归入下阶段规划

### 当前状态

从 `phase_summary_moheng_20260517.md` 中可以看到，R3/R4 标记为「⏳ 待办」，但原始内容在评审会纪要中未找到。玄知的建议中已确认R3/R4内容在本报告中未被明确记录。

### 追溯路径

1. 查找评审会纪要原始文件（如果存在）
2. 在 `docs/08_history/` 或会议记录中搜索 R3/R4 关键词
3. 若无法追溯，标注「待追索」并推入下一阶段待办

### 建议

将 R3/R4 的具体内容追索列为下一迭代 `docs/09_roadmap/` 的启动项。在内容确认前，不投入任何编码或文档工作量。

---

## 执行时间汇总

| 优先级 | 项数 | 文档耗时 | 代码耗时 | 合计 |
|:------:|:----:|:--------:|:--------:|:----:|
| P0 | 3 | 6h | 8.5h | **14.5h** |
| P1 | 3 | 1.5h | 21h | **22.5h** |
| P2 | 2 | 1h | 0h | **1h** |
| P3 | 1 | 0.5h | 0h | **0.5h** |
| **总计** | **9** | **9h** | **29.5h** | **38.5h** |

> 注：P1-1（KB前端UI）的12h已包含在P1合计中。P0+1建议优先排入下一Sprint（2周内完成），P2-P3可放到后续迭代。

---

## 附录：9项与原始评审报告的对应关系

| # | 玄知报告中位置 | 原始标题 |
|:-:|:-------------:|---------|
| 1 | 盲点1 | 用户视角缺失 |
| 2 | 盲点2 | 新旧过渡期运维成本未量化 |
| 3 | 盲点3 | R3/R4沦为悬空待办 |
| 4 | 盲点4 | BitableSync「一日游」风险 |
| 5 | 风险1 | 「0%偏差」虚假安全感 |
| 6 | 风险2 | KB与回测系统耦合 |
| 7 | 风险3 | 回测vs实盘校准机制缺失 |
| 8 | 风险4 | 监控盲区 |
| 9 | 风险5 | 团队知识单点依赖 |

---

## 附录：本文自动衍生的子文档清单

以下文档需要在本行动方案之外独立创建（工作量已在各P级别中分摊）：

| 文档 | 创建者 | 预计完成时间 |
|------|--------|:------------:|
| `docs/05_protocols/method_regression_testing.md` | 墨衡 | 下一迭代第一周 |
| `docs/05_protocols/backtest_calibration_protocol.md` | 墨衡 | 下一迭代第一周 |
| `docs/02_development/plugin_dev_guide.md` | 墨衡 | 下一迭代第二周 |
| `docs/03_pipelines/runner_architecture.md` | 墨衡 | 下一迭代第二周 |
| `docs/02_development/knowledge_bridge_extend.md` | 墨衡 | 下一迭代第二周 |
| `docs/06_operations/bitable_sync_ops.md` | 墨衡 | 下一迭代第二周 |
| `docs/06_operations/troubleshooting.md` | 墨衡 | 下一迭代第三周 |
| `docs/03_pipelines/migration_guide_legacy_runner.md` | 墨衡 | 下一迭代第二周 |
| `docs/01_architecture/overall_architecture.md` 补充 | 墨衡 | 下一迭代第三周 |

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 19:17+08:00*
