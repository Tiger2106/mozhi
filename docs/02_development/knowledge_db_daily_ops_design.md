# 02:00 知识管理日常运维设计

> 来源：主人 2026-05-16 10:55 指令
> 状态：设计稿待实施
> 关联：knowledge_db_design.md (v2.2)

## 一、墨涵角色边界

墨涵是**知识管理员**，不是归档员。

| 角色 | 行为 |
|:-----|:------|
| 归档员 | 把文件从A移到B |
| 知识管理员 | 判断文件的价值、状态、关联关系，决定如何处理 |

这个区别决定了 02:00 任务的设计深度。

## 二、02:00 定时任务三层次

每晚 02:00 按序执行，三个层级：

### 第一层：机械性整理（02:00 — 02:05，辅助，削减判断）

| 时间 | 任务 | 说明 |
|:----:|:-----|:------|
| 02:00 | 扫描 `signals/tasks/` | 清理超过 7 天的 `.done` / `.failed` 文件 |
| 02:01 | 扫描 `reports/` | 检查当日日报是否已生成，缺失则告警 |
| 02:02 | 扫描 `ta_backtest/reports/` | 压缩超过 30 天的日报为月度归档 |
| 02:03 | `knowledge.db` → 备份 | 到 `data/db/knowledge_backup_{date}.db` |
| 02:05 | `trade_engine.db` → 备份 | 与现有 `backup_manager.py` 对齐 |

### 第二层：状态追踪（02:10 — 02:16，半自动，生成待审清单）

| 时间 | 任务 | 说明 |
|:----:|:-----|:------|
| 02:10 | 扫描 `incoming/` | 列出超过 3 天未处理的文件 |
| 02:12 | 扫描 `knowledge_entries` | 列出 status='draft' 的条目 |
| 02:14 | 扫描 `backtest_runs` | 列出本周新增回测，生成摘要 |
| 02:16 | 比对 `file_registry.db` | 检查是否有新文件未注册 |

### 第三层：知识沉淀（02:20 — 02:25，核心价值）

| 时间 | 任务 | 说明 |
|:----:|:-----|:------|
| 02:20 | 触发 `knowledge_extractor.py` | 从新回测中提取草稿知识条目 |
| 02:22 | 触发 `decay_knowledge.py` | 检查超过 90 天未更新的知识条目，标记 degraded |
| 02:25 | 生成 `daily_doc_report.md` | 汇总当日文档状态，供早晨人工查阅 |

## 三、daily_doc_report.md 格式

```markdown
# 文档管理日报 · 2026-05-16 02:00

## 今日摘要
- 新增回测记录: N 条（grid xN, trend xN, reversal xN）
- 新增知识草稿: N 条（待墨涵审核）
- 待处理文件: N 个（incoming/ 超3天未处理）
- 知识库衰减: N 条
- 备份状态: ✅ 正常

## 待处理事项（需人工确认）
1. [DRAFT] knowledge_entries #42: 震荡市下网格胜率62%
 → 来源: run_grid_601857_20260514，样本1次，置信度低
 → 建议操作: 等待更多样本 / 立即激活 / 忽略

2. [INCOMING] plan_backtest_improvement_v4_0.md
 → 存入时间: 2026-05-13，已3天未处理
 → 建议操作: 归档至 docs/02_development/ / 删除

## 本周回测汇总
| 策略 | 标的 | 夏普 | 最大回撤 | 评级 |
|:----|:----|:----:|:-------:|:----:|
| grid | 601857 | 0.82 | 7.3% | B |
| trend | 601857 | 1.21 | 5.1% | A |

## 知识库状态
- 活跃条目: N 条
- 草稿条目: N 条（待审）
- 已衰减: N 条（超90天）
- 已废弃: N 条

## 备份状态
- knowledge.db: ✅ 已备份 → data/db/knowledge_backup_20260516.db
- trade_engine.db: ✅ 已备份
```

## 四、file_registry.db 维护

```sql
CREATE TABLE file_registry (
    file_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    file_type TEXT NOT NULL,       -- 'design_doc' | 'plan' | 'report' | 'script' | 'config'
    status TEXT NOT NULL,          -- 'active' | 'archived' | 'deprecated'
    owner TEXT,                    -- 'moheng' | 'mohan' | 'moxuan'
    description TEXT,
    registered_at TEXT DEFAULT (datetime('now')),
    last_verified TEXT,            -- 最后一次确认文件仍存在的时间
    archived_at TEXT
);
```

02:00 任务结束时，对 `last_verified` 做一次全量更新——扫描文件系统，把存在的文件标记为已验证，超过 7 天未验证的文件生成告警（可能已被手动删除但未注册）。

## 五、墨涵判断规则

| 场景 | 判断规则 | 建议操作 |
|:-----|:---------|:---------|
| incoming/文件超过3天 | 发布提醒，不自动移动 | 人工确认后归档 |
| knowledge_entries草稿超过7天无人审核 | 自动标记为低置信度 | 仍需人工激活 |
| 同一策略同一标的连续3次评级为C | 生成专项提示，参数需调整 | 提示参数可能需要调整 |
| 某个文件已被修改超过5次 | 标记为"高度关注" | 提示是否需要锁定版本 |
| 某条经验知识来源超过90天未出现 | 触发衰减检查 | 标记为降级 |
| incoming/中出现与现有文件同名不同版本的文件 | 自动检测版本号 | 提示合并或覆盖 |

## 六、重要边界

**禁止：** 02:00 任务中不建议墨涵自动删除任何文件。只标记、只移动、只归档。

核心原则来自"copy-not-move"设计理念。所有删除操作都需要人工确认的记录，否则只在 `daily_doc_report.md` 里标注"已确认删除"。

## 七、定位总结

墨涵的 02:00 任务本质上是做三件事：

1. **保证文件安全**（备份）
2. **保证信息可见**（日报摘要）
3. **保证知识不腐烂**（衰减检查）

> 机械操作 → 生成清单 → 删除操作必须人工确认
