# 早报管线试运行问题评估

<!-- author: moheng | created: 2026-05-16T15:33+08:00 -->
<!-- generated: 2026-05-16T15:33+08:00 -->

---

## 问题1: 告警队列积压 94 条

### 存储位置与结构

**位置**: `C:\Users\17699\mo_zhi_sharereports\signals\consensus\events\pending\`  
**结构**: 每个告警为一个独立的 `.json` 文件，格式如下:

```json
{
  "version": "1.0",
  "seq": "YYYYMMDD_HHMMSS_xxx",
  "level": "warn|info|critical",
  "title": "System Alert: StepN 已触发",
  "message": "...",
  "source": "dispatcher",
  "task_id": "...",
  "timestamp": "ISO8601+08:00",
  "details": {}
}
```

另有 **signals/alerts/** 目录（独立于 pending 队列），存放 `alert_pipeline.py` 和 `local_cache_manager` 写入的少量告警（目前 11 条，1 条已处理、5 条 `ci_pipeline`/`drift_detector`、5 条 `cache_miss`）。

**健康检查读取的是 `consensus/events/pending/` 目录，而非 `signals/alerts/` 目录。** 两者是独立的告警通道。

### 94 条积压具体内容

| 告警类型 | 数量 | 日期区间 | 内容 |
|:---------|:----:|:--------:|:-----|
| **Step1-7 已触发（待执行）** | ~70 | 05-06 ~ 05-14 | 每日 08:00 和 12:00 两个轮次，每轮 7 条（Step1~Step7），约 5 个交易日×2 轮×7=70 |
| **Step1 执行超时失败** | 2 | 05-06 | dispatcher 判定 Step1 两次执行超时 |
| **P0_3 保证金不足** | 2 | 05-06 | 预计成交金额 0.00 的错误警报 |
| **回撤止损触发** | 1 | 05-05 | 手动终止回撤止损，净资金 80000，总资产 30% 止损 |
| **其余分散告警** | ~19 | 05-06~05-14 | 各日期零星步骤触发通知 |

**告警来源**: 全部由 `dispatcher` 模块写入，非 `alert_pipeline.py`。

### 积压原因

**根本原因**: 存在生产者但无消费者。

- 生产者：`dispatcher` 模块在每次 cron session 启动时向 `pending/` 目录写入告警（包括 Step1~Step7 的触发动机）。
- 消费者：`alert_pipeline.py` 的 `collect_and_deliver()` 仅读取 `signals/alerts/` 目录（不同路径），从未处理 `consensus/events/pending/`。
- 健康检查脚本 `pipeline_healthcheck.py` 的 `check_alert_queue_backlog()` 检测到积压并报告 WARN，但没有清理能力。
- 积压从 05-05 开始积累，至今 11 天未清理。

**次要原因**: `dispatcher` 的告警机制是设计用于实时通知，但此机制在现有架构中从未正式接驳到飞书通知管道。

### 风险等级

**P2** — 非阻塞性。不影响管线调度和功能执行，但持续积累浪费磁盘空间（94 个文件约 50KB），且健康检查持续报 WARN 会干扰对真正问题的判断。

### 建议措施

1. **立即清理（优先级高）**: 
   - 执行 `Remove-Item "C:\Users\17699\mo_zhi_sharereports\signals\consensus\events\pending\*.json"` 清除 94 条积压
   - 保留 `completed/` 目录内容不变

2. **接入消费者（修复）**: 
   - 在 `alert_pipeline.py` 的 `collect_and_deliver()` 中增加对 `consensus/events/pending/` 的读取和推送（可飞书通知或归档）
   - 或决定放弃这一机制，直接在 `dispatcher` 中移除告警写入逻辑

3. **明确告警通道定位（设计）**: 
   - 当前存在两条告警通道（`signals/alerts/` + `signals/consensus/events/pending/`），职责不清
   - 建议合并为单一通道，避免重复和混淆

---

## 问题2: cron deliver 格式修复验证

### 当前状态

通过 `openclaw cron list --json` 确认：

- **早报管线-main (ce760f90)**: 已修复 ✅  
  `delivery.to: "chat:oc_72bacde2a63f824bd011718fbe58f48a"`  
  `lastDeliveryStatus: "delivered"`  
  `lastDelivered: true`

- **其他 cron（6 个仍使用旧格式）**: `feishu:chat:oc_...` ⚠️  
  但 `lastDeliveryStatus` 也显示为 `delivered`，说明平台对 `feishu:chat:` 前缀做了兼容处理。

### 技术点评

**修复本身正确**: 
- 标准化协议格式是好的工程实践。`delivery.to` 指定目标标识符（bare `chat:xxx`），路由前缀（`feishu:`）应由 `delivery.channel` 字段决定。
- 旧格式 `feishu:feishu:chat:xxx` 是双重前缀嵌套（`feishu:` 出现两次），显然是串联拼接错误。

**但是**，经实验验证，旧格式 `feishu:chat:xxx` 在所有 cron 上均能正常投递。这意味着平台的解析逻辑做了向后兼容，对 `feishu:` 前缀做了 strip 或解析容错。**实际的正确性风险低于预期。**

### 风险等级

- **格式修复**: 正确，P2（风格一致）
- **功能影响**: P3（旧格式实际可工作，不计入阻塞）

### 建议

1. 其余 6 个仍使用 `feishu:chat:` 的 cron 建议统一修复为 bare `chat:`，保持格式一致性
2. 在 cron_setup.md 中明确标记 delivery.to 的规范格式，作为模板标准

---

## 问题3: MorningPipeline 未被实际调用

### 事实确认

从 `scheduler_agent.py` 源码确认：

```python
class MorningPipeline:
    def _precheck(self) -> bool:
        """交易日预检: 非交易日则写 skip 标记并返回 False"""
        if not is_trade_day(self.date):
            skip_path = TASKS_DIR / "morning_skip.done"
            ...
            return False
        ...
    
    def run(self) -> dict:
        write_heartbeat("busy", {"task_id": self.task_id, "step": "precheck"})
        # 交易日预检
        if not self._precheck():
            write_heartbeat("idle")
            return {"task_id": self.task_id, "status": "SKIPPED", ...}
        ...
```

**MorningPipeline 内置了 `is_trade_day()` 交易日检测逻辑**。如果被调用，周六会自动返回 SKIPPED，无需墨涵额外判断。

### 是否构成问题

| 视角 | 评估 |
|:----|:-----|
| **功能影响** | 本次（周六试跑）无实际影响。跳过结果是正确的。 |
| **架构正确性** | **是问题。** 如果 cron 配置的调度表达式 `0 8 * * 1-5` 已精确限定周一~周五，则 MorningPipeline 的 `_precheck()` 实际上是双重保险。如果连 `pipeline.run()` 都不调用，双重保险全部失效。 |
| **周一风险** | 如果周一正式运行时墨涵同样凭自主判断跳过或不完整执行 `pipeline.run()`，后果：<br>1. 整条 7 步管线不会启动<br>2. 无 trigger 文件写入子 agent<br>3. 最终无早报产出<br>4. 飞书无推送 |

### agent 自主判断 vs 严格遵循调度脚本

| 对比项 | 自主判断 | 严格遵循 |
|:------|:--------|:--------|
| 灵活性 | 高，可适应特殊场景 | 低，脚本说啥是啥 |
| 可靠性 | 低，依赖 agent 的领域知识 | 高，路径清晰可预期 |
| 可审计 | 低，决策过程不可复现 | 高，所有逻辑在代码中 |
| 容错 | 可能漏判或误判 | 内置交易日预检+熔断机制 |

**合理平衡**: 
- cron session 中的 agent 应先严格按照 payload message 执行 `pipeline.run()`
- 如果 pipeline 跑完结果不符合预期（如空早报），agent 再依据领域知识做补充判断
- 不应跳过 `pipeline.run()` 直接由 agent 自行判定

### 风险等级

**P1** — 周一正式运行时若继续不调用 MorningPipeline，将导致早报管线完全不产出。

### 建议措施

1. **修改 cron payload message**（已基本正确）：当前消息中已包含 `from morning_pipeline.scheduler_agent import MorningPipeline; pipeline = MorningPipeline(); result = pipeline.run()`。但 msg 末尾可增加约束：
   ```
   注意：交易日判断由 pipeline.run() 内部自动完成，无需人工预检。
   请严格按上述代码执行，不要在 session 中自行跳过。
   ```

2. **增加墨涵的 SOUL.md 或 session 提示**：在 cron session 上下文中增加指令约束，要求严格遵循 payload 指令执行 pipeline.run()

3. **设置 P0 告警**: 如果 pipeline 在交易日 08:30 前未产出 final_report，应触发告警通知。

---

## 问题4: 三策略修复正确性确认

### 审阅 `reports/meeting/three_strategies_fix_report.md`

| 修复 # | 类型 | 描述 | 判据 | 结论 |
|:------:|:----:|:-----|:----:|:----:|
| 1 | `SIGNALS_TASKS_DIR` 路径问题 | 发现 `mo_zhi_sharereports` 硬编码但判定不修复 | 路径能工作，非 Bug | ✅ 正确 |
| 2 | `profit_factor` 双键容错 | `.get("profit_loss_ratio", 0.0)` → `metrics.get("profit_factor") or metrics.get("profit_loss_ratio", 0.0)` | Python `or` 短路求值正确；`profit_factor` 为 0/None/空字符串时 fallback 到 `profit_loss_ratio`；`0.0` 作为 `profit_factor` 实际值会被 `0.0 or ...` 短路判为 falsy，产生误 fallback | ⚠️ **有隐患** |
| 3 | `config_key` 一致性 | `run_reversal.py:851` 将 `config_key=config.signal_type` 改为 `f"{signal_type}_{pos_mode}_{tag}"` | 与 `run_trend.py` 格式一致，三策略统一 | ✅ 正确 |
| 4 | `set_cron_job` 搜索 | 三文件中搜索相关关键词无匹配，判定不修复 | 纯回测运行器，无调度代码 | ✅ 正确 |

### 关于修复 #2 的隐患说明

当前写法：
```python
"profit_factor": metrics.get("profit_factor") or metrics.get("profit_loss_ratio", 0.0),
```

当 `metrics` 中存在 `{"profit_factor": 0.0}`（profit factor 真实值为 0.0 的业务场景），表达式 `metrics.get("profit_factor")` 返回 `0.0`，然后 `0.0 or ...` 在 Python 中短路为 `...`，即 `metrics.get("profit_loss_ratio", 0.0)`。

这意味着当 profit_factor 为 0.0 时，会误回退到 `profit_loss_ratio`。虽然 `profit_factor=0.0` 是极端异常场景（一条盈利交易都没有），但确实存在逻辑漏洞。

**修复建议**:
```python
"profit_factor": metrics.get("profit_factor") if metrics.get("profit_factor") is not None else metrics.get("profit_loss_ratio", 0.0),
```
或更简洁:
```python
"profit_factor": metrics.get("profit_factor") or (metrics.get("profit_loss_ratio", 0.0) if "profit_factor" not in metrics else 0.0),
```
最实用的写法:
```python
"profit_factor": metrics.get("profit_factor") if "profit_factor" in metrics else metrics.get("profit_loss_ratio", 0.0),
```

### 风险等级

修复 #2: **P2** — 仅当 profit_factor 实际为 0.0 且 profit_loss_ratio 不同时为 0.0 时才会出错，概率极低。

---

## 总结

| 问题 | 风险等级 | 核心问题 | 建议优先级 |
|:-----|:-------:|:---------|:----------:|
| 告警队列 94 条积压 | P2 | 有生产者无消费者 | 高（先清理，再改代码） |
| deliver 格式修复 | P3 | 旧格式实际可工作，但标准不一致 | 低（顺带修复其余 cron） |
| MorningPipeline 未调用 | P1 | 周一正式运行时可能无早报产出 | **最高** |
| 三策略修复 #2 隐患 | P2 | `or` 短路对 0.0 值误判 | 中（概率低） |
| 其余修复（#1, #3, #4） | ✅ | 逻辑正确 | 已通过 |

### 关键行动路径

1. **今明两天（周六~周日）**: 清理告警队列 + 确认周一 cron 正确触发 MorningPipeline
2. **周一 08:00**: 监控 cron session 是否正确执行 `pipeline.run()` → `_precheck()` → 串行 7 步 → 飞书推送
3. **周一运行后**: 确认告警队列不再积压，或接入消费者
4. **低优先级**: 三策略修复 #2 改进 + 其余 cron deliver 格式统一

---

*评估完成，作者: moheng | 2026-05-16 15:33+08:00*
