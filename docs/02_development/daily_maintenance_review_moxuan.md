# daily_maintenance.py (v1.2) 审查报告

**审查方:** 墨萱 🔍
**审查时间:** 2026-05-16 11:23
**脚本版本:** v1.2
**文件路径:** `scripts/daily_maintenance.py`

---

## REVIEW_RESULT: **发现问题** ⚠️

**总体评级:** B-（功能可用，但存在 **1 个 P1** + **3 个 P2** 问题需修复后再上线生产）

---

## 测试结果摘要

| 测试用例 | 结果 | 说明 |
|---------|------|------|
| `--dry-run` 全量运行 | ✅ 通过 | 三层均正常运行，无异常抛出 |
| `--dry-run --report` 生成日报 | ✅ 通过 | 报告文件写入 `reports/daily/` |
| 日报内容验证 | ✅ 通过 | 结构完整，数据正确 |

---

## 逐层审查

### Layer1: 机械性整理与备份

| 子模块 | 状态 | 审查结论 |
|--------|------|---------|
| `cleanup_signal_files()` | ⚠️ **发现问题** | 见下方 P1 |
| `check_today_report()` | ✅ 通过 | 只读操作，逻辑正确 |
| `archive_old_reports()` | ✅ 通过 | dry-run 不写不删，归档路径正确 |
| `backup_knowledge_db()` | ✅ 通过 | 调用 KnowledgeDB.backup()，dry-run 不执行 |
| `backup_trade_engine()` | ✅ 通过 | 使用 shutil.copy2，dry-run 不执行 |

### Layer2: 状态追踪

| 子模块 | 状态 | 审查结论 |
|--------|------|---------|
| `scan_incoming()` | ✅ 通过 | 只读扫描，逻辑正确 |
| `scan_knowledge_drafts()` | ✅ 通过 | 只读查询，异常有返回值 |
| `scan_recent_backtests()` | ✅ 通过 | 只读查询 |
| `check_unregistered_files()` | ✅ 通过 | 只读比对，逻辑正确 |

### Layer3: 知识沉淀

| 子模块 | 状态 | 审查结论 |
|--------|------|---------|
| `trigger_knowledge_extractor()` | ✅ 通过 | dry-run 跳过执行 |
| `trigger_decay_check()` | ✅ 通过 | dry-run 跳过执行 |

### `generate_report()`

| 检查项 | 状态 | 审查结论 |
|--------|------|---------|
| `--dry-run` 下是否写文件 | ⚠️ P2 | **dry-run 下不执行但生成报告文件** |
| 日报路径 | ✅ 通过 | `reports/daily/daily_doc_report_YYYY-MM-DD.md` |
| 输出格式 | ⚠️ P2 | 见下方 P2-2 |
| 编码 | ⚠️ P2 | 见下方 P2-3 |

---

## 发现问题详情

### P1 — `SIGNALS_TASKS_DIR` 路径指向不存在的目录

**严重程度:** P1
**文件:** 第 46 行
**现象:**
```python
SIGNALS_TASKS_DIR = Path(r"C:\Users\17699\mo_zhi_sharereports\signals\tasks")
```
该路径中的 `mo_zhi_sharereports` 并不存在。实际存在的信号 tasks 目录有多个：
- `C:\Users\17699\mozhi_platform\signals\tasks`
- `C:\Users\17699\mozhi_platform\src\signals\tasks`
- `C:\Users\17699\mo_zhi_share\reports\signals\tasks`（注意是 `mo_zhi_share` 不是 `mo_zhi_sharereports`）

**影响:** `cleanup_signal_files()` 因为 `not SIGNALS_TASKS_DIR.exists()` 直接返回 `{"cleaned": 0, "error": "目录不存在"}`，cleanup 功能永久失效。

**修复建议:**
1. 确认正确的信号 tasks 路径
2. 建议使用相对路径或从配置文件中读取

### P2-1 — `generate_report()` 在 `--dry-run` 模式下仍然写入文件

**严重程度:** P2
**现象:** 使用 `--dry-run --report`时，`generate_report()` 正常写入日报文件（`reports/daily/daily_doc_report_2026-05-16.md`，大小 29510 字节）。
**问题:** 尽管 Layer1 的 `backup_knowledge_db` 和 `archive_old_reports` 在 dry-run 下不写，但日报文件未被跳过。
**影响:** 逻辑不一致。用户使用 `--dry-run` 预期是"预览不产生副作用"，但日报被实际写出。

**修复建议:**
```python
# 在 generate_report() 中添加 dry_run 参数
# 或只在 main() 中当 args.dry_run 时不调用 generate_report()
```

### P2-2 — `report_check` 和 `_query_weekly_backtests()` 的 dry-run 一致性

当前 `report_check` 和 `weekly_backtests` 不接收 `dry_run` 参数（虽然它们确实只读）。这不算 bug，但建议统一接口风格。

### P2-3 — 报告中的 "本周回测汇总" 表无 LIMIT，造成报告过长

**严重程度:** P2
**现象:** 本周回测记录共 689 条，全部写入日报的 markdown 表格中（实际输出约 24KB 的表格），导致日报可读性极差。回顾测试输出，大量条目重复（同一 symbol+strategy 出现的夏普和仓位完全相同）。

**影响:** 日报过长，每日阅读效率低；终端输出截断。

**修复建议:**
1. `_query_weekly_backtests()` 添加 `LIMIT 30` 或 `LIMIT 50`
2. 或在报告中添加 "表格太长，仅显示前 30 条" 的说明
3. 更优方案：按 strategy+symbol 聚合，只显示汇总统计数据

### P2-4 — `_query_knowledge_status()` 异常处理使用 `pass`

**严重程度:** P2
**现象:** 
```python
try:
    ...
except Exception:
    pass
```
**影响:** 数据库查询失败时静默吞异常，所有计数保持 0，用户无法知道查询失败。

**修复建议:**
```python
except Exception as e:
    counts = {"active": 0, "draft": 0, "degraded": 0, "deprecated": 0, "error": str(e)}
```

---

## dry-run 隔离性验证

| 操作 | dry-run 是否真的不执行 | 结果 |
|------|----------------------|------|
| `cleanup_signal_files` (删除文件) | ✅ 是 | `if not dry_run: f.unlink()` |
| `archive_old_reports` (压缩+删除) | ✅ 是 | `if dry_run: ...continue` |
| `backup_knowledge_db` (数据库备份) | ✅ 是 | `if dry_run: return` |
| `backup_trade_engine` (文件复制) | ✅ 是 | `if dry_run: return` |
| `trigger_knowledge_extractor` | ✅ 是 | `if dry_run: return` |
| `trigger_decay_check` | ✅ 是 | `if dry_run: return` |
| `generate_report` (写文件) | ❌ **不符合预期** | 在 `--dry-run --report` 下仍写入仪表 |

---

## 代码质量评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 代码结构 | A | 三层架构清晰，函数职责单一 |
| 异常处理 | B- | 大部分有 try-except，但 P2-4 pass 问题 |
| 注释 | A- | 函数文档 + 参数说明完整 |
| 常量化 | A | 天数、路径用常量统一定义 |
| dry-run 隔离 | B | 6/7 正确隔离，P2-1 遗漏 |
| 报告输出 | C | 无 LIMIT 导致报告臃肿 |

---

## 修复建议优先级

1. **[P1] 修复 SIGNALS_TASKS_DIR 路径** — 这是最严重问题，cleanup 功能完全不可用
2. **[P2] generate_report 的 dry-run 违规** — 修复 `--dry-run` 下写日报的语义问题
3. **[P2] 日报添加 LIMIT / 聚合显示** — 解决 689 行表格的可用性问题
4. **[P2] _query_knowledge_status 异常处理** — 不要 pass

---

*审查方: 墨萱 🔍*
*审查时间: 2026-05-16 11:23*
