---
title: ingest_analysis.py 需求说明书 v0.1（讨论稿）
author: 墨涵（PO）
version: v0.1
created: 2026-05-23
status: draft
sources:
  - 墨衡：执行方需求（TTL 35s）
  - 墨萱：QA+评审需求（TTL 65s）
  - 玄知：技术把关需求（TTL 50s）
---

# ingest_analysis.py 需求说明书

## 一、目标陈述

开发通用化的回测分析数据入库程序，替代临时脚本 `finalize_v4.py`，使回测总结会 Stage 4（归档入库）可重复、可验证、可审计。

---

## 二、架构要求（三方共识）

### 2.1 模块化组件设计

采用 **DataSource → Transformer → Validator → Writer** 四阶段管道模式，每阶段可独立单元测试。

```
路径：src/backtest/analysis/ingest/
  ├── __init__.py    # public API: ingest(run_id, ...)
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
python -m src.backtest.analysis.ingest --run-id <uuid> [选项]

选项：
  --run-id UUID       必需：回测运行ID
  --dry-run           试运行模式：只校验不写入
  --qa-verify         输出QA校验报告（JSON）
  --force             强制覆盖已有draft记录
  --verbose           详细日志输出
```

### 3.2 输入

| 参数 | 来源 | 说明 |
|:----|:-----|:-----|
| run_id | 命令行（必需） | UUID v4，主键参数 |
| 回测指标数据 | backtest_run / performance_summary 表 | 读取v3执行层表，与输入交叉核验 |
| 分析报告文件 | mo_zhi_sharereports/reports/ | 文档路径，计算 content_hash |
| DDL 文件 | Downloads/ backtest_schema_v4.sql | 归档到 archive/ddl/ |

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
| 已存在 draft 版本 | 默认 UPDATE（version_content+1，updated_at更新） |
| 已存在 final 版本 | 默认 SKIP；`--force` 后再次检查 version_content，更高时标记 reviewed |
| 重跑验证 | `--qa-verify` 模式下输出幂等对比报告 |

### 3.5 校验

1. **前置校验**：run_id 在 backtest_run 中存在且 status='done'
2. **空值校验**：必填字段（run_id, analysis_type, version_status, sharpe_ratio, max_drawdown_pct）非空
3. **外键校验**：analysis_metrics_core.analysis_id → analysis_meta.id
4. **交叉核验**：输入指标 vs performance_summary 表偏差 ≤ 0.01%（否则拒绝）
5. **文档存在性**：analysis_docs.file_path 对应文件必须存在于磁盘

### 3.6 错误处理

| 等级 | 条件 | 行为 |
|:----:|:-----|:-----|
| WARN | 数据偏差0.01%~0.1%、文件缺失 | 继续写入，记录警告 |
| ERROR | 偏差>0.1%、run_id不存在、事务写入失败 | 回滚，抛出异常，写 .failed 信号文件 |
| FATAL | DB连接失败、磁盘满 | 直接告警墨涵，不写 .failed |

### 3.7 日志

- JSON Lines 格式：`{"ts","level","component","message","run_id","action"}`
- 每核心步骤记录开始-结束时间
- ERROR 时输出失败 SQL + 完整数据 + 错误堆栈
- 追加写至 `logs/ingest_analysis.log`

---

## 四、与 finalize_v4.py 差异总结

| 维度 | finalize_v4.py | ingest_analysis.py |
|:-----|:--------------|:------------------|
| run_id 获取 | 硬编码 | 命令行参数 |
| 指标数据来源 | 代码内拼写 | 从 performance_summary 表读取 |
| 文件路径 | 硬编码 | 目录自动发现 |
| 版本管理 | 4.1 写死 | version_schema + version_content |
| 幂等 | 无检查 | run_id+analysis_type 查重 |
| 事务 | 无 | 事务包裹全有或全无 |
| content_hash | 不计算 | SHA256 计算并存库 |
| 归档分离 | 混合 | 入库 + 归档两步分离 |
| 可测试性 | 不可 | --dry-run 模式 |

---

## 五、待Owner确认事项

1. **归档分离方案**：归档（archive_artifacts.py）与入库（ingest_analysis.py）拆开串行执行？
2. **QA输出范围**：`--qa-verify` 输出的JSON文件需要包含哪些内容？（行数变化/字段交叉验证/幂等对比）
3. **模块路径**：`src/backtest/analysis/ingest/` 是否合适？还是有更偏好的目录结构？
4. **异常通知方式**：FATAL错误需要通知到飞书群，还是只写到日志即可？
