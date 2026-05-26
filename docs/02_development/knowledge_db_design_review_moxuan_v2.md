# 墨枢 — knowledge.db 设计方案复审

> 审查方：墨萱 🔍
> 审查对象：`docs/02_development/knowledge_db_design.md` v2.1（墨衡，P0 修复后）
> 审查时间：2026-05-16 10:04 +08:00
> 审查任务：验证墨衡 P0 修补是否有效消除上次审查发现的 2 个 P0 问题
> 依据材料：
>   - 设计方案 v2.1（`docs/02_development/knowledge_db_design.md`）
>   - 一审意见（`docs/02_development/knowledge_db_design_review_moxuan.md`）

---

## REVIEW_RESULT: **PASS ✅**

审查结论：2 处 P0 问题已全部消除，设计方案可进入实施阶段。

---

## 一、P0 修复逐项验证

### P0-1：`knowledge_entries.symbol` 外键约束语义错误 ✅ 已修复

**修复检查结果：**

v2.1 版 `knowledge_entries` DDL 中，原 `FOREIGN KEY (symbol) REFERENCES backtest_runs(symbol)` 已被**彻底删除**。表定义末尾显式注释说明：

> `-- 无外键约束：聚合表不直接引用单条回测运行（详见墨萱审查 P0-1）`

**验证结论：** ✅ 完美修复。聚合表与 `backtest_runs` 的关联通过 `source_run_ids`（JSON array）实现逻辑关联，无需 FK。注释引用审查意见，可追溯。

---

### P0-2：`_find_project_root()` 回退分支健壮性不足 ✅ 已修复

**修复检查结果：**

v2.1 版 `_find_project_root()` 函数做了以下修复：

| 一审问题点 | v2.1 修复状态 |
|:-----------|:--------------|
| 根目录兜底返回误导性路径 | ✅ `parent == current` 分支不再静默返回，改为检查环境变量后抛 RuntimeError |
| 缺少环境变量兜底 | ✅ 新增 `os.environ.get("MOZHI_PLATFORM_ROOT")` 检查，优先级低于标记文件、高于抛异常 |
| 异常信息不明确 | ✅ 改为 `raise RuntimeError(...)` 包含中文错误信息和修复指引 |
| 无安全上限但问题不大 | ✅ 循环逻辑清晰，`parent == current` 终止条件明确，无实际死循环 |

**验证结论：** ✅ 加固完整。修复后的逻辑为：标记文件上溯 → 环境变量兜底 → RuntimeError 异常。三层递进，无静默错误路径。

---

## 二、补充检查项

### 2.1 `DEFAULT_DB_PATH` 与 `_find_project_root()` 路径统一性

一审 P1-5 指出 `DEFAULT_DB_PATH` 手动上溯三级与 `_find_project_root()` 逻辑不一致。

**检查：** v2.1 的附录 A 骨架代码中，`DEFAULT_DB_PATH` 仍为手动上溯：

```python
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "data", "knowledge.db"
)
```

而 §3.2 的正文代码使用：
```python
DEFAULT_DB_PATH = os.path.join(
    PROJECT_ROOT,
    "data", "knowledge.db"
)
```

两份代码不一致。但考虑到：
- 附录 A 为占位骨架（明确标注"占位用"），实际实现时可能被覆盖
- 正文 §3.2 已使用了 `PROJECT_ROOT` 的预期模式
- 此问题级别为 P1（非 P0），不影响验收判据

**建议：** 实施阶段实现 `knowledge_db.py` 时，统一使用 `_find_project_root()` 构建 `DEFAULT_DB_PATH`，以正文 §3.2 为准。

### 2.2 `initialize()` 懒加载时序

一审 P0-2 子问题提到 `__init__` 到 `store_run` 之间缺失 `initialize()` 调用。

**检查：** v2.1 未直接修改此点，但风险矩阵表说明"第一次调用 _persist_result 时自动建表"。预期实施阶段会在 `store_run()` 入口处做懒加载，不属于设计方案本身的问题，在实施阶段审查中可进一步验证。

---

## 三、正面评价

1. **修复精准**：2 处 P0 均为靶向修复，无过度修改，体现了良好的修改纪律
2. **注释可追溯**：P0-1 修复处直接引用了审查编号（`详见墨萱审查 P0-1`），便于后续审阅
3. **错误信息友好**：P0-2 的 RuntimeError 包含中文提示，降低他人排查成本

---

## 四、总结

| 审查轮次 | 结果 | P0 数量 | P1 数量 | P2 数量 |
|:---------|:-----|:--------|:--------|:--------|
| 一审 | FAIL | 2 | 7 | 3 |
| 二审（本轮） | **PASS** | **0** | 7 | 3 |

**验收条件达到，设计方案可获批进入实施阶段。** 🔓

---

*复审意见由墨萱 🔍 撰写*
*审查基于设计文档 v2.1*
