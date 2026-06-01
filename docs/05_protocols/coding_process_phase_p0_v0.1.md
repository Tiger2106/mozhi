# Phase P0 — 编码拆分阶段规范（方案 B：纯任务清单 → 墨涵调度中心）

**文档状态**: draft · **版本**: v0.1 · **作者**: mohan · **日期**: 2026-05-28

## 1. 概述

Phase P0 是编码流程 **Stage 1~5 之前**的预置阶段，适用于大型编码任务需要拆分为多个 15min 以内子任务时启用。

**核心思路 — 三权分离**：

| 权力 | 角色 | 职责 |
|:----|:----|:-----|
| **方案权** | 墨衡 | 将任务拆分为可执行子任务清单 |
| **审核权** | 墨萱 | 复核拆分的完整性/正交性/粒度 |
| **调度权** | 墨涵 | 将锁定后的清单转为调度脚本并执行 |

## 2. 触发条件

**启用**：仅当 Stage 1 预估工时 > **25min**（超过 BT-001 拆分的 15min+弹性上界）时，必须在 Stage 1 前插入 Phase P0。

**跳过**：预估工时 ≤ 25min 时可直接进入 Stage 1，无需拆分。

## 3. 阶段定义

### 3.1 Phase P0 — 拆分方案起草（墨衡）

**输入**：细化方案（设计文档 §6 技术规格）或直接的任务需求

**输出**：`schedules/split_draft_{task_id}.json`

**执行者**：墨衡

**流程**：
1. 阅读细化方案 → 识别所有可独立编码的改动点
2. 按以下原则拆分：
   - 每项 ≤ **15min**（纯编码时间，不含调试）
   - 依赖关系显式标注（DAG，无环）
   - 每项有明确的 `affected_files` 列表
   - 每项有 `acceptance_criteria` 验收标准
3. 写入 `.split_draft` → 回复 Announce

**`.split_draft` 格式**（纯任务清单 JSON）：

```json
{
  "meta": {
    "parent_task": "<task_id>",
    "title": "<描述性标题>",
    "source_doc": "<设计文档路径>",
    "created_by": "moheng",
    "created_at": "<ISO8601>",
    "total_estimated_min": <sum of sub_tasks>,
    "status": "draft"
  },
  "sub_tasks": [
    {
      "id": "<task_id>_sub_001",
      "description": "具体做什么（一句话）",
      "details": "实现细节、算法、注意事项",
      "estimated_min": 10,
      "dependencies": [],
      "affected_files": ["src/.../file1.py", "src/.../file2.py"],
      "acceptance_criteria": "改动后 X 函数应能处理 Y 边界条件",
      "assigned_to": "moheng"
    },
    {
      "id": "<task_id>_sub_002",
      "description": "...",
      "estimated_min": 12,
      "dependencies": ["<task_id>_sub_001"],
      "affected_files": ["..."],
      "acceptance_criteria": "...",
      "assigned_to": "moheng"
    }
  ]
}
```

### 3.2 Phase P0.5 — 拆分复核（墨萱）

**输入**：`schedules/split_draft_{task_id}.json`

**输出**：`PASS` / `REJECT`

**执行者**：墨萱

**复核项**（7项检查清单）：

| 序号 | 检查项 | 说明 |
|:----|:-------|:-----|
| Q1 | **完整性** | 所有改动点是否都被覆盖、无遗漏 |
| Q2 | **正交性** | 子任务之间无功能重叠，可直接合并代码 |
| Q3 | **粒度** | 每项 ≤ 15min，大项已进一步拆分 |
| Q4 | **依赖合理性** | DAG 无环，依赖方向正确 |
| Q5 | **验收标准** | 每项有可执行验收标准（非"完成"、"正常"） |
| Q6 | **文件范围** | affected_files 覆盖所有需修改的文件 |
| Q7 | **可测性** | 每项改动可独立验证，无需等后续任务 |

**判定规则**：
- 全部 PASS → **PASS**，墨涵锁定为 `.split_final`
- 任何 FAIL → **REJECT**，标注问题项和修改要求，退回墨衡

### 3.3 Phase P0.8 — 锁定 + 调度脚本生成（墨萱 → 墨涵）

**输入**：PASS 的 `.split_draft`

**输出**：`.split_final` + `schedules/coding_pipeline_*.json`

**流程**：

```
墨萱锁定:
  1. 确认 .split_draft 无需修改
  2. 将 meta.status 从 "draft" 改为 "locked"
  3. 文件 mv 或 cp 为 .split_final（保留原稿历史）
  4. 通知墨涵

墨涵调度:
  1. 读取 .split_final → 提取 sub_tasks 列表
  2. 调用 generate_pipeline_script.py 生成 TMPL-005 调度脚本
     （每项 sub_task 对应一个 stage_1_n 编码步骤 + 配套 self_check）
  3. 写入 schedules/coding_pipeline_{task_id}.json
  4. 进入现有流程：玄知脚本审查 → Stage 1~5
```

**`.split_final` 格式**：与 `.split_draft` 相同，仅 `meta.status` 改为 `"locked"`

## 4. 集成到现有编码流程

```
  ┌─────────────────────────────────────┐
  │  Phase P0（此规范）                  │
  │  P0: 墨衡 → .split_draft            │
  │  P0.5: 墨萱 → 复核 PASS/REJECT      │
  │  P0.8: 墨萱锁定 → 墨涵调度          │
  └──────────┬──────────────────────────┘
             ↓ .split_final + 调度脚本
  ┌─────────────────────────────────────┐
  │  玄知脚本审查（与现有流程完全一致）    │
  └──────────┬──────────────────────────┘
             ↓ PASS
  ┌─────────────────────────────────────┐
  │  Stage 1~5（现有编码流程 v1.0）      │
  │  每个 sub_task 独立走编码→自检→审查  │
  └─────────────────────────────────────┘
```

## 5. 墨涵调度中心细则

墨涵在 Phase P0.8 中的角色定义为 **调度中心**，受 BT-006 约束（不做判断）：

| 动作 | 说明 | 是否判断 |
|:----|:-----|:--------:|
| 读 .split_final | 读取结构化的子任务清单 | ❌ 纯读取 |
| 调用脚本生成器 | `generate_pipeline_script.py` 机械转换 | ❌ 纯工具 |
| 写调度脚本 | 写入 schedules/ 目录 | ❌ 纯写入 |
| 读 dynamic_next | 按脚本条件分支推进 | ❌ 纯读取 |
| 调 spawn | spawn 子 agent | ❌ 纯调度 |

注：若 `generate_pipeline_script.py` 不支持当前拆分结构（新场景），墨涵需升级生成器 → 但限于**机械转换逻辑**，不判断拆分质量。

## 6. 依赖文件

| 文件 | 格式 | 位置 |
|:----|:----|:----|
| .split_draft | JSON | `schedules/split_draft_{task_id}.json` |
| .split_final | JSON | `schedules/split_final_{task_id}.json` |
| 调度脚本 | JSON | `schedules/coding_pipeline_{task_id}.json` |

## 7. 与其他流程的关系

| 场景 | 是否启用 Phase P0 |
|:-----|:----------------:|
| 单步小改动（1文件，≤25min） | ❌ 跳过 |
| 多文件关联改动 | ✅ 启用 |
| 新功能（多个独立模块） | ✅ 启用 |
| Bug 修复（单点定位） | ❌ 跳过 |
| 重构（影响面广） | ✅ 启用 |

## 8. 变更记录

| 版本 | 日期 | 作者 | 变更 |
|:---:|:----|:-----|:----|
| v0.1 | 2026-05-28 | mohan | 初始草案（Owner 指示方案 B + Phase P0 命名） |
