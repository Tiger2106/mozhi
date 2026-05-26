---
title: ingest_analysis.py 需求说明书 v0.2
author: 墨涵（PO）
version: v1.0
created: 2026-05-23
status: finalized
supersedes: v0.2
sources:
  - 墨衡：执行方需求（TTL 35s）
  - 墨萱：QA+评审需求（TTL 65s）
  - 玄知：技术把关需求（TTL 50s）
  - 墨萱复审v0.2：✅ 通过
  - 玄知技术把关v0.2：✅ 通过
  - Owner定调：同意墨涵建议（§八 全部确认）
---

# ingest_analysis.py 需求说明书

## 一、目标陈述

开发通用化的回测分析数据入库程序，替代临时脚本 `finalize_v4.py`（见 `C:\Users\17699\.openclaw\workspace-mochen\finalize_v4.py`），使回测总结会 Stage 4（归档入库）可重复、可验证、可审计。

---

## 二、架构要求（三方共识）

### 2.1 模块化组件设计

采用 **DataSource → Transformer → Validator → Writer** 四阶段管道模式，每阶段可独立单元测试。

```
路径：src/backtest/analysis/ingest/
  ├── __init__.py    # public API: ingest(run_id, analysis_type, ...)
  ├── pipeline.py    # Pipeline.run() — 主入口
  ├── model.py       # Pydantic/数据模型
  ├── transformer.py # 字段映射 + 类型转换
  ├── validator.py   # 数据校验 + 交叉核验
  └── writer.py      # SQLite 事务写入
```

**不 import 回测引擎运行时模块**（backtest_engine.py、trade_logger 等），只读数据库表结构。

### 2.2 与 mozhi_platform 关系

- 放在 `src/backtest/analysis/ingest/` 下（已有 pyproject.toml 注册的 backtest* 包下）
- 不单独 pip install，但可在 pyproject.toml 注册 `ingest-analysis` 入口点（可选）

### 2.3 三方需求对照表

| 需求项 | 墨衡 | 墨萱 | 玄知 | 最终结论 |
|:------|:----:|:----:|:----:|:--------:|
| CLI 参数 `--run-id` | ✅ | ✅ | ✅ | **采纳** |
| 事务包裹全部写入 | ✅ | ✅ | ✅ | **采纳** |
| content_hash (SHA256) | ✅ | ✅ | ✅ | **采纳** |
| 幂等 (run_id+analysis_type) | ✅ | ✅ | ✅ | **采纳** |
| 事务内全有或全无 | ✅ | ✅ | ✅ | **采纳** |
| 模块化组件设计 | — | ✅ | ✅ | **采纳** |
| 四阶段管道模式 | — | — | ✅ | **采纳** |
| Pydantic 输入校验 | — | ✅ | ✅ | **采纳** |
| 归档与入库分离 | — | — | ✅ | **采纳** |
| 归档文件（archive/） | ✅ | — | — | **采纳** |
| QA 结构化输出（--qa-verify） | — | ✅ | — | **采纳** |
| JSON Lines 日志 | — | ✅ | — | **采纳** |
| 交叉核验 performance_summary | — | — | ✅ | **采纳** |
| 三级失败阶梯 | — | ✅ | ✅ | **采纳** |

---

## 三、功能需求

### 3.1 CLI 接口

```bash
python -m src.backtest.analysis.ingest --run-id <uuid> --analysis-type <type> [选项]

选项：
  --run-id UUID         必需：回测运行ID
  --analysis-type TYPE  必需：分析类型枚举值
                        (summary|deep_analysis|tech_review|validation|resolution)
  --dry-run             试运行模式：只校验不写入
  --qa-verify           输出QA校验报告（JSON）
  --force               强制覆盖已有draft记录
  --timeout SEC         管道超时（默认：summary=35s，其他=65s）
  --verbose             详细日志输出
```

**analysis_type 枚举说明**：

| 枚举值 | 来源 | 对应模板 | 默认 TTL |
|:-------|:-----|:---------|:--------:|
| summary | Stage 1 执行产出 | TMPL-001 | 35s |
| deep_analysis | Stage 1 执行产出 | TMPL-002 | 35s |
| validation | Stage 2 QA产出 | TMPL-003 | 65s |
| tech_review | Stage 2 评审产出 | 评审意见表 | 65s |
| resolution | Stage 3 会议产出 | 决议记录 | 65s |

**analysis_type 在幂等中的角色**：
- 幂等键为 `(run_id, analysis_type)` 组合
- 例如：同一 run_id 可以有 summary + deep_analysis + tech_review 共 3 条 analysis_meta 记录
- 同一 run_id + 同一 analysis_type 重复调用 → 幂等命中（按 §3.4 规则处理）

### 3.2 输入

| 参数 | 来源 | 说明 |
|:----|:-----|:-----|
| run_id | 命令行（必需） | UUID v4，主键参数 |
| analysis_type | 命令行（必需） | 枚举值，决定写入的 meta 类型 |
| 回测指标数据 | backtest_run / performance_summary 表 | 读取v3执行层表，与输入交叉核验 |
| 分析报告文件 | mo_zhi_sharereports/reports/ | 文档路径，计算 content_hash |
| DDL 文件（可选） | Downloads/ backtest_schema_v4.sql | 归档到 archive/ddl/ |

### 3.3 输出

写入 5 张分析层表：

| 表 | 行数 | 说明 |
|:---|:----:|:-----|
| analysis_meta | 1行 | 分析会话入口（含version三字段 + parent_session_id + tags） |
| analysis_metrics_core | 1~5行 | 按 metric_group 拆分 |
| analysis_metrics_ext | N行 | K-V 扩展 |
| analysis_docs | 1~6行 | 每报告1行（含 content_hash） |
| schema_version | 1行（UPSERT） | 版本记录 |

额外动作：报告文件归档至 `mozhi_platform/archive/reports/`，DDL 文件归档至 `mozhi_platform/archive/ddl/`。

### 3.4 幂等性

| 情况 | 行为 |
|:----|:-----|
| run_id+analysis_type 不存在 | 正常 INSERT |
| 已存在 draft 版本 | 默认 UPDATE（version_content+1，updated_at更新）。若 analysis_docs.file_size_bytes==-1（归档失败标记），UPDATE 路径自动重试归档并更新为正确的文件大小 |
| 已存在 final 版本 | 默认 SKIP；`--force` 后再次检查 version_content，更高时标记 reviewed |
| 重跑验证 | `--qa-verify` 模式下输出幂等对比报告 |

**幂等性保障**：
- 在写入前执行 SELECT 查重，而非依赖 UNIQUE 约束报错
- 每次幂等操作写入日志：`[IDEMPOTENT] analysis_meta action=UPDATE reason=run_id+analysis_type_exists`
- 级联清理：覆写 analysis_meta 时，CASCADE 删除其附属的 metrics_core/ext/docs 旧记录

### 3.5 校验

1. **前置校验**：run_id 在 backtest_run 中存在且 status='done'
2. **空值校验**：必填字段（run_id, analysis_type, version_status, sharpe_ratio, max_drawdown_pct）非空
3. **枚举校验**：analysis_type 仅允许 summary/deep_analysis/tech_review/validation/resolution 五个值
4. **外键校验**：analysis_metrics_core.analysis_id → analysis_meta.id
5. **交叉核验**：输入指标 vs performance_summary 表偏差 ≤ 0.01%（否则拒绝）
6. **文档存在性**：analysis_docs.file_path 对应文件必须存在于磁盘

### 3.6 错误处理

| 等级 | 条件 | 行为 |
|:----:|:-----|:-----|
| WARN | 数据偏差0.01%~0.1%、文件缺失 | 继续写入，记录警告 |
| ERROR | 偏差>0.1%、run_id不存在、事务写入失败 | 回滚，抛出异常，写 .failed 信号文件 |
| FATAL | DB连接失败、磁盘满 | 直接告警墨涵（飞书群通知），不写 .failed |

**事务与归档的一致性方案**：
1. 写入顺序：DB 事务提交（全部成功）→ 文件归档
2. 归档失败时：analysis_docs 中写入 file_size_bytes=-1（标记归档失败），记录错误描述
3. 不要求二阶段提交（对 SQLite 过重），采用"先DB后文件"的串行顺序保障
4. 重跑任务可修复归档失败的记录（通过 --force 重新归档）

### 3.7 日志

- 格式：JSON Lines，每行一个完整 JSON 对象
- 每核心步骤输出 2 行（start 事件 + end 事件），含 timestamp 和耗时
- 结构：`{"ts":"ISO8601+08:00","level":"INFO|WARN|ERROR","component":"ingest|validator|writer","message":"...","run_id":"...","action":"start|end|insert|skip|fail"}`
- ERROR 时输出失败 SQL + 完整数据 + 错误堆栈
- 追加写至 `logs/ingest_analysis.log`（自动轮转）

---

## 四、与 finalize_v4.py 差异总结

| 维度 | finalize_v4.py | ingest_analysis.py |
|:-----|:--------------|:------------------|
| 位置 | workspace-mochen/finalize_v4.py | src/backtest/analysis/ingest/ 模块 |
| run_id 获取 | 硬编码 | 命令行参数 |
| 指标数据来源 | 代码内拼写 | 从 performance_summary 表读取 |
| 文件路径 | 硬编码 | 目录自动发现 |
| 版本管理 | 4.1 写死 | version_schema + version_content |
| 幂等 | 无检查 | run_id+analysis_type 查重 |
| 事务 | 无 | 事务包裹全有或全无 |
| content_hash | 不计算 | SHA256 计算并存库 |
| 归档分离 | 混合 | 入库 + 归档两步分离 |
| 可测试性 | 不可 | --dry-run + 模块化测试 |

---

## 五、性能目标

| 场景 | 目标 | 说明 |
|:----|:----:|:-----|
| summary 管道 | ≤ 35s | 墨衡执行场景 |
| deep_analysis 管道 | ≤ 35s | 墨衡执行场景 |
| 交叉核验场景 | ≤ 65s | QA 自检场景 |
| 归档文件 | ≤ 10s 额外 | 文件复制时间 |

---

## 六、测试策略

### 6.1 单元测试

| 测试点 | 说明 |
|:------|:-----|
| 四阶段管道各阶段独立测试 | TestDataSource / TestTransformer / TestValidator / TestWriter |
| 幂等性测试 | 同一 run_id+analysis_type 重复运行，验证 skip/update 行为 |
| 异常测试 | 传入不存在 run_id、不存在的报告文件路径 |
| 枚举校验测试 | 传入非法 analysis_type 值，验证拒绝 |

### 6.2 集成测试

| 测试点 | 说明 |
|:------|:-----|
| 完整入库链路 | 一条完整分析链路，检验 5 张表数据完整性 |
| 归档测试 | 文件复制、content_hash 计算、归档目录结构 |
| 回归测试 | 与 finalize_v4.py 输出对比（同一 run_id 两次写入，行数和指标值一致） |

### 6.3 验证方式

- `--dry-run` 模式：不实际写入DB，输出完整校验报告
- `--qa-verify` 模式：写入前后各表行数变化 + 字段交叉验证结果

---

## 七、归档幂等与清理策略

### 7.1 文件已存在时的行为

| 情况 | 行为 |
|:----|:-----|
| 文件已存在且 content_hash 一致 | 跳过（SKIP），不覆盖 |
| 文件已存在但 content_hash 不同 | 版本化重命名：`filename_v{version}.ext` |
| 文件不存在 | 正常复制 |

### 7.2 清理策略

- 归档目录不作自动清理
- 每季度（或调用方显式指定）可通过 `--archive-cleanup` 模式清理 orphan 文件
- Orphan 文件定义：不在 analysis_docs 表中被引用的 archive 文件

---

## 八、Owner确认结果（2026-05-23 15:10）

| 事项 | 墨涵建议 | Owner决议 |
|:----|:--------|:---------:|
| 归档分离方案 | ingest内部统一处理（先DB后文件） | ✅ 同意 |
| QA输出范围 | 行数变化+字段交叉验证+幂等对比，三者全输出 | ✅ 同意 |
| 模块路径 | `src/backtest/analysis/ingest/` | ✅ 同意 |
| 异常通知方式 | 仅写日志，飞书告警暂缓，待统一告警通道 | ✅ 同意 |
| 归档清理时机 | 手动触发（`--archive-cleanup`），不schedule | ✅ 同意 |
