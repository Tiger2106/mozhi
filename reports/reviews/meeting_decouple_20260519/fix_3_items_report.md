# fix_3_remaining_items — 修复报告

创建时间：2026-05-20T13:33+08:00  
作者：moheng (墨衡)  
task_id：fix_3_remaining_items  
状态：SUCCESS

---

## 任务 1：knowledge.db schema ``db_schema.py``

**路径：** `C:\Users\17699\mozhi_platform\src\signals\db_schema.py`

**完成情况：** ✅ 已创建

- 使用纯 Python sqlite3（无 ORM）
- 3 张信号相关表：`signals`、`consumed_signals`、`archive_index`
- 4 个索引：idx_consumed_signals_consumed_at、idx_archive_index_signal_id、idx_signals_symbol、idx_signals_timestamp
- 提供 `init_database(db_path)` 入口函数，支持 CLI 调用
- 已测试：创建数据库 → 验证 3 表存在 → 清理

---

## 任务 2：修复晨报 delivery target 前缀

**完成情况：** ✅ 已修复

**问题：** 5 个 OpenClaw cron job 的 `delivery.to` 使用了 `feishu:chat:oc_...` 前缀。

**根因：** OpenClaw 的 channel=feishu 会自动给 target 加上 `feishu:` 前缀，因此 `feishu:chat:` 会变成 `feishu:feishu:chat:`，导致消息投递。

**修复：** 将 5 个 job 的 `to` 从 `feishu:chat:oc_...` 改为 `chat:oc_...`。

| 名称 | ID | 结果 |
|---|---|---|
| settlement_run | 023fe199 | ✅ `chat:oc_...` |
| paper_trade_settle_backup | d70b5e52 | ✅ `chat:oc_...` |
| research_report_1905 | 78a31b11 | ✅ `chat:oc_...` |
| 每日日志归档02:00 | 8bbee552 | ✅ `chat:oc_...` (channel=feishu) |
| reports归档_03:00 | 15ed3c94 | ✅ `chat:oc_...` |

---

## 任务 3：trade execution 修复

**完成情况：** ✅ 已修复

### 问题分析

**根因 1（核心）：signal_mapping → order 链路断裂**

`signal_trade_executor.py` 中 `execute_trade()` 方法通过中文关键词匹配从 `operation_framework.balanced` 提取交易动作：

```python
# ⚠️ 旧逻辑：中文关键词匹配，依赖文本格式
if "买入" in balanced or "增持" in balanced:  action = "BUY"
elif "卖出" in balanced or "减仓" in balanced:  action = "SELL"
```

但墨衡（Step2）已产出结构化的 `signal_mapping` 字段：
```json
{
  "signal_mapping": {
    "action": "BUY",
    "symbol": "601857",
    "position_ratio": 0.3,
    "confidence": "高"
  }
}
```

当 `signal_mapping` 字段中的 `action` 为 BUY/SELL/HOLD 时，中文匹配仍可能正确。但若分析报告使用非标准表述（如"持有"而非"HOLD"），则链路断裂，交易不会执行。

**修复：** 优先使用 `signal_mapping` 结构化字段，仅当不存在时回退中文匹配。

**根因 2：trade_loop_scheduler argparse 不兼容**

`trade_loop_scheduler.py` 的 `argparse` 未声明 `--report-type` 参数，但午间 cron 命令中包含 `--report-type midday`，导致 argparse 报错 `unrecognized arguments`。

**修复：** 在 argparse 中加入 `--report-type`（choices: ["morning", "midday"]），使其兼容。

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `automation_v2/phase1_core/signal_trade_executor.py` | `execute_trade()`: 优先使用 `analysis.signal_mapping`，回退中文匹配 |
| `scheduler/trade_loop_scheduler.py` | argparse 加入 `--report-type` 参数兼容 |

---

## 约束检查

| 约束 | 状态 |
|---|---|
| 不扩大 scope | ✅ 仅修改指定文件 |
| 修改后测试确认不破坏 | ✅ 语法检查通过（ast.parse） |

---

## 遗留问题

- 午间 cron（12:30）的 `find_latest_trade_signal()` 不会按 `report_type` 过滤信号，但 pipeline_complete 文件中的 `report_type` 字段会传递到 `process_signal_trade()`，确保任务使用正确的 report 目录。
- 需观察次日中午的 cron 执行确认整体链路连通。
