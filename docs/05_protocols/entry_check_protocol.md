# 文件入网关协议（Entry Gate Protocol）

author: 墨涵  
created_time: 2026-05-19T15:20:00+08:00  
version: v1.0  
status: READY  
related: file_lifecycle_manual.md (下游), unified_reform_plan_v3.md (Q层配套)

---

## 一、目的

在文件进入系统之前设置一道质量门。职责：

1. **路径合规** — 确保文件进入正确目录
2. **命名合规** — 确保文件名符合规范
3. **完整性检查** — 确保关键元数据存在
4. **去重检查** — 防止重复文件进入
5. **黑白名单** — 拦截不合规或有害内容

此协议是 **Q层（治理层）的前置组件**。文件通过入网关后才进入 Q层审计流程。

---

## 二、适用范围

| 文件类型 | 适用 | 说明 |
|:--------|:----:|:-----|
| .md 文档 | ✅ | 强校验 |
| .py 脚本 | ✅ | 强校验 |
| .txt 文本 | ✅ | 基本校验 |
| .json 数据 | ✅ | 结构校验 |
| .js/.ps1 脚本 | ✅ | 基本校验 |
| .yaml/.yml 配置 | ✅ | 结构校验 |
| .png/.jpg 图片 | ✅ | 仅尺寸/格式检查 |
| .db/.sqlite | ❌ | 数据库文件，特殊流程 |
| .csv/.xlsx | ✅ | 仅路径+命名检查 |

---

## 三、检查清单（逐项）

### 3.1 路径合规（Gate-P1）

文件必须进入**适合其内容类型的目录**，不得随意放置。

| 文件类型 | 允许目标目录 |
|:---------|:------------|
| 代码脚本(.py/.js) | `mozhi_platform/automation_v2/` `mozhi_platform/scripts/` `mozhi_platform/src/` |
| 报告/文档(.md) | `mozhi_platform/reports/*/` `mozhi_platform/docs/*/` `mo_zhi_sharereports/reports/*/` |
| 配置文件(.yaml/.json) | `mozhi_platform/config/` |
| 数据文件(.csv/.json) | `mozhi_platform/data/` `mozhi_platform/data_warehouse/` |
| 试验性内容 | `mozhi_platform/experiments/` |
| 设计稿/提案(txt) | `mozhi_platform/reports/incoming/` → 转设计文档 |
| 第三方输入 | `mozhi_platform/reports/incoming/` |

**禁止路径**（拦截+告警）：
- `C:\` 根目录
- `Desktop`
- `Downloads`
- 非本项目仓库的任意目录

### 3.2 命名合规（Gate-P2）

#### 文档类（.md / .txt）

```
格式：{目的}_{日期}.md
示例：param_decay_analysis_20260519.md
       executive_summary_20260519.md
       backtest_system_reform_20260519.md
例外：数据文档可加 .json 后缀
```

规则：
| 检查项 | 要求 |
|:-------|:-----|
| 文件名含日期 | YYYYMMDD 格式 |
| 文件名字数最小 | ≥8 字符（不含后缀） |
| 禁止含特殊字符 | 空格、#、%、&、<、> |
| 禁止中文 | 文件名中不得含中文（内容可含） |
| 扩展名小写 | .md → .py → .json 均为小写 |

#### 代码类（.py / .js / .ps1）

```
格式：snake_case
示例：fix_settlement.py → grid_optimizer.py → check_orders_fill.py
```

规则：
| 检查项 | 要求 |
|:-------|:-----|
| snake_case | 全小写+下划线 |
| 禁止中文文件名 | ❌ `修复结算.py` |
| 有意义名称 | 避免 `temp.py` `test1.py` `aaa.py` |
| 文件内容匹配命名 | 入口函数/类名应与文件名相关 |

### 3.3 元数据完整性（Gate-P3）

#### .md 文件头部要求

```markdown
---
author: {作者名}
created_time: {ISO8601}
version: {语义化版本}
status: DRAFT/READY/REVIEW
---
```

或注释形式：

```markdown
<!--
author: 墨衡 (moheng)
created_time: 2026-05-19T10:00:00+08:00
task_id: xxx
version: v1
-->
```

必填字段：
| 字段 | 要求 |
|:-----|:------|
| author | 必须有。允许值：墨衡/moheng / 墨涵/mochen / 墨萱/moxuan / 玄知/xuanzhi / external |
| created_time | ISO8601 格式（含时区） |

可选但建议：
| 字段 | 说明 |
|:-----|:------|
| version | 语义版本 |
| task_id | 关联任务ID |
| status | DRAFT / READY / REVIEW / MODIFIED |
| related | 关联文档路径 |

#### .py 文件头部要求

```python
"""
module: grid_optimizer
author: moheng
created: 2026-05-19
description: 网格参数优化器 - Phase 0a
"""
```

必填字段：
| 字段 | 要求 |
|:-----|:------|
| module | 模块名（应与文件名匹配） |
| author | 必须有 |
| description | 简述功能 |

### 3.4 去重检查（Gate-P4）

使用 file_lifecycle 系统检查：

```powershell
python -m src.utils.file_lifecycle search --checksum {SHA256}
```

拦截条件：
- SHA256 完全匹配 → ❌ 已存在，拒绝
- 文件名相同且路径不同但内容不同 → ⚠️ 人工判断是否覆盖或重命名
- 文件名匹配但内容不同 → 允许（版本升级）

### 3.5 安全与质量检查（Gate-P5）

#### 通用禁止：
- ❌ 不含敏感信息（API Key、密码、token）
- ❌ 不含绝对路径的个人识别信息
- ❌ 文件大小 > 10MB（数据库文件除外）
- ❌ 二进制可执行文件（.exe .dll .bat .ps1→需审核通过）

#### .py 文件额外检查：
- ✅ 编码为 UTF-8（无 BOM）
- ✅ import 语句在文件开头（非中间穿插）
- ❌ 无 `os.system("rm -rf")` 等危险命令
- ❌ 无硬编码的 `C:\Users\17699\...` 路径（应使用配置或变量）

#### .md 文件额外检查：
- ✅ 内容不含乱码（非 UTF-8 编码文件拦截）
- ✅ 表格格式正确（| 对齐）
- ✅ 文档标题层级连续（无 H1 → H4 跳跃）

---

## 四、入网关全流程

```
新文件到来（incoming/）
    │
    ▼
Step 1: Gate-P1 路径合规 ──── ❌ → 退回 + 告知正确路径
    │ ✅
    ▼
Step 2: Gate-P2 命名合规 ──── ❌ → 退回 + 告知正确格式
    │ ✅
    ▼
Step 3: Gate-P3 元数据 ───── ❌ → 退回 + 要求补充
    │ ✅
    ▼
Step 4: Gate-P4 去重 ─────── ❌ → 已存在 + 给出已有文件路径
    │ ✅
    ▼
Step 5: Gate-P5 安全质量 ─── ❌ → 拦截 + 说明原因
    │ ✅
    ▼
通过 ✅ → 登记 file_registry.db → 进入正式目录
```

**整体通过条件**：5项全部通过，方可登记入库。

---

## 五、通过后的操作

入网关通过后，墨涵执行日常整理流程：

```powershell
# Step 1: 移动文件到正式目录（手动）
# Step 2: 登记数据库
python -m src.utils.file_lifecycle update ^
    --path "incoming/20260519/{文件名}" ^
    --current-path "{正式目标路径}" ^
    --status "experimental" ^
    --category "{自动分类}" ^
    --tags "incoming,new" ^
    --source-type "{来源}" ^
    --note "{自动摘要}"
```

---

## 六、异常处理

| 异常 | 处理方法 |
|:-----|:---------|
| 文件名不含日期但内容重要 | 手动添加日期前缀后通过 |
| 作者缺失但内容完整 | 退回要求补充，标记 PENDING |
| 中文文件名 | 退回要求重命名 |
| 文件太大（>10MB） | 放行前确认用途 |
| 疑似重复 | 比对 SHA256 + 人工判断 |
| 团队外输入（外部专家） | 作者标注 external，手动补 source_type |

---

## 七、与 Q 层的关系

```
入网关（Gate P1~P5）        ← 前置检查（墨涵）
    ↓ 通过
文件登记入库
    ↓
Q层（Q1~Q9）              ← 深度审计
    ↓
研究结论 + 可信度评分
    ↓
知识层归档
```

入网关是**轻量级前置检查**（安全+规范），Q 层是**深度研究审计**（统计+逻辑）。两者分层不重叠。

---

## 八、墨涵操作 SOP

每日处理 incoming 文件时：

```powershell
# 1. 查看今日 incoming
dir C:\Users\17699\mozhi_platform\reports\incoming\

# 2. 逐一过 5 项 Gate 检查
#    通过 → 移入正式目录 + 登记 DB
#    不通过 → 退回说明原因

# 3. 确认 file_registry.db 状态
python -m src.utils.file_lifecycle status

# 4. 异常文件记录到 notes
```

---

*此协议为 v1.0，随系统迭代更新。*
*任何修改需经 墨涵 确认。*
