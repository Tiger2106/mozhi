# 网格策略未运行诊断报告 — 2026-05-19

## 📋 基本信息

| 项目 | 内容 |
|------|------|
| 日期 | 2026-05-19（周二） |
| 报告生成时间 | 2026-05-19 20:23 GMT+8 |
| 分析者 | 墨衡 (moheng) |

---

## 一、根本原因

**grid 策略今日未运行的根本原因是：负责执行交易循环的 `trade_loop_scheduler` 没有对应的 cron 定时任务在交易时段被触发。**

具体而言，存在两个层次的阻断：

### 根因 1：唯一交易调度 cron 任务已被禁用（主因）

`trade_loop_scheduler_midday`（cron id: `32cf9867`）是系统中唯一配置用于执行 `trade_loop_scheduler.py` 的定时任务，其状态为 **`enabled: false`**（已禁用）。

- 禁用时间：2026-05-06 12:35 GMT+8（已持续 13 天）
- 近一次运行状态：`error`（超时，原因：已被禁用）
- 其余 cron 任务均正常（晨报管线 08:00、晚报管线 19:50、结算 19:00 等）
- ⚠️ 该 cron 被设置于 `12:30 * 1-5`（工作日午间），即使启用也只覆盖午盘交易（12:00-13:00），**早盘时段（09:30-11:30）无任何交易调度 cron 存在。**

### 根因 2：无 `pipeline_complete` 信号文件可供消费（次要因素）

`trade_loop_scheduler` 依赖 `pipeline_complete_*.json` 信号文件作为交易执行指令。
- 扫描信号目录后确认：`signals/pipeline_complete_*.json` 和 `signals/triggers/pipeline_complete_*.json` 均 **不存在**
- 这意味着即使调度器被触发运行，也会因"无待处理的交易信号"而跳过执行（返回 `skip`）

### 排除项

| 排除项 | 结论 | 证据 |
|--------|------|------|
| 是否交易日？ | ✅ 是交易日 | 2026-05-19 周二，不在节假日列表中（"2026-05-01"等已过，下一个为"2026-06-08"） |
| rest_day_guard 误判？ | ❌ 不会拦截 | 无 `is_rest_day` 调用记录，交易日历确认今日为交易日 |
| Kill Switch 触发？ | ❌ 未触发 | 无 kill_switch 相关日志或信号文件 |
| 进程互斥锁冲突？ | ❌ 未触发 | `trade_scheduler.lock` 不存在（调度器从未启动） |

---

## 二、证据链

### 2.1 Cron 任务状态

从 `C:\Users\17699\.openclaw\cron\jobs.json` 提取的与交易相关的 cron 任务：

| cron ID | 名称 | 是否启用 | 说明 |
|---------|------|---------|------|
| `ce760f90` | 早报管线-main | ✅ 已启用 | 08:00 运行 — 仅生成报告，不执行交易 |
| `32cf9867` | trade_loop_scheduler_midday | ❌ **已禁用** | 12:30 运行 — 唯一负责交易执行的调度器 |
| `fc55ff83` | evening_report_runner | ✅ 已启用 | 19:50 运行 — 晚报管线 |
| `023fe199` | settlement_run | ✅ 已启用 | 19:00 运行 — 结算 |
| `78a31b11` | research_report_1905 | ✅ 已启用 | 19:05 运行 — 研究日报 |

### 2.2 今日已执行的 .done 文件（signal tasks 目录）

```
morning_report_20260519_step0_xuanzhi.done     2026-05-19 08:09
morning_report_20260519_step1_moheng.done      2026-05-19 08:11
morning_report_20260519_step2_moxuan.done      2026-05-19 08:14
morning_report_20260519_step3_moheng.done      2026-05-19 08:16
morning_report_20260519_step3_5_xuanzhi.done   2026-05-19 08:19
morning_report_20260519_step4_moxuan.done      2026-05-19 08:22
morning_report_20260519_step5_mochen.done      2026-05-19 08:23
morning_report_20260519_pipeline.done          2026-05-19 08:23
→ 均为晨报管线步骤，无 tech_signal / paper_trade / grid 相关信号
```

**不存在** `tech_signals*.done` 或 `paper_trade*.done` 文件。

### 2.3 结算结果

`trade_engine.db` 文件为 0 字节（空），结算摘要显示：
- `daily_pnl=0.0`
- `total_fees=0.0`
- 研究日报写入"当日无信号记录"
→ 确认整日未发生任何交易。

### 2.4 网格回测数据

最新的 `grid_000001.SZ` 回测数据为 2026-05-18（周一）11:32 生成。
最新的 `grid_601857` 回测数据为 2026-05-18（周一）22:41 生成。
→ 今日（05-19）无任何网格相关文件生成。

### 2.5 交易日历验证

节假日配置（`config/trading_holidays.json`）中，2026-05-19 既不在节假日列表，也非周末（周二），因此为有效交易日。

---

## 三、修复方案

### 方案 A：启用 midday 调度器 cron + 补充 morning 调度器 cron（推荐）

1. **启用现有 midday 交易调度 cron：**
   - 在 `C:\Users\17699\.openclaw\cron\jobs.json` 中将 `32cf9867` 的 `enabled` 从 `false` 改为 `true`
   - 该任务配置：`30 12 * * 1-5`（工作日 12:30）— 午盘开始后触发
   - 预留的参数：`--timeout 2700`（45 分钟覆盖午盘交易时段）

2. **新增 morning 交易调度 cron：**
   - 建议新增 id，例如 `morning_trade_scheduler_0930`
   - 调度表达式：`30 9 * * 1-5`（工作日 09:30，开市时触发）
   - agentId: `mochen`
   - 参数：`--no-lock`（与 midday 互斥，不同时段无需争锁）
   - 超时：`--timeout 7200`（覆盖早盘 09:30-11:30）

3. **更新 jobs-state.json 后开启服务：**
   ```
   openclaw gateway restart
   ```

### 方案 B：确保 pipeline_complete 信号文件正常生成

`trade_loop_scheduler` 依赖 `pipeline_complete_*.json` 信号来触发生成实际订单。当前无此信号文件，即使调度器启用也无法执行交易。

需确认以下管线步骤已集成到晨报/午报管线中，并能在步骤完成后写入 `pipeline_complete` 信号：
- 技术信号生成（`tech_signal_generator.py`）
- 交易信号转换（`signal_converter.py`）
- 仓位链接（`signal_position_linker.py`）

### 方案 C：短期验证

手动执行验证调度器是否能正常工作：
```
python C:\Users\17699\mo_zhi_sharereports\scheduler\trade_loop_scheduler.py --dry-run
```
确认交易日历、交易时段、Kill Switch 检查均正常。

---

## 四、时间线

| 时间 | 事件 |
|------|------|
| 2026-05-06 12:35 | `trade_loop_scheduler_midday` cron 被禁用（`enabled: false`） |
| 2026-05-06 ~ 2026-05-19 | 连续 13 天无交易调度器运行 |
| 2026-05-19 08:00-08:23 | 晨报管线正常运行（仅报告生成） |
| 2026-05-19 09:30-11:30 | ❌ 早盘交易时段 — 无调度器触发 |
| 2026-05-19 12:30 | ❌ 午盘调度器禁用 — 无执行 |
| 2026-05-19 19:00-19:51 | 晚报/结算/研究日报正常执行，结算 PnL = 0.0 |

---

## 五、结论

**根本原因：`trade_loop_scheduler_midday` cron 自 2026-05-06 起被禁用（`enabled: false`），且系统中从未配置早盘交易调度 cron，导致交易循环调度器全天未被唤醒，网格策略无法执行。**

修复优先级：
1. 🔴 **高**：在 cron 配置中启用 midday 调度 + 新增 morning 调度
2. 🟡 **中**：确认 pipeline_complete 信号生成链路完整
3. 🟢 **低**：定期检查 cron 任务状态，防止未来再次被意外禁用
