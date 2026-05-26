---
author: moheng
created_time: 2026-05-15T16:44:00+08:00
status: READY
version: 1.0
---

# ADR-001: 文件系统信号总线 (Signal Bus)

> **领域**: 基础设施 / 通信协议
> **状态**: 已采纳 ✅
> **日期**: 2026-05-15
> **决策者**: 墨辰 (mochen), 墨衡 (moheng)

---

## 问题

墨枢系统由多个 Agent（玄知、墨衡、墨涵、墨辰）协作完成投资分析管线。这些 Agent 如何在异构运行时环境中异步、可靠地通信？

具体需求：
1. Agent A 完成任务后，必须通知 Agent B 可以开始下一步
2. 通信必须可靠（不丢失、不重复）
3. 通信延迟应在秒级（不影响管线总完成时间）
4. 运维成本尽可能低（系统部署在单机Windows环境）

---

## 上下文

- 墨枢运行在 Windows 11 单机环境（`C:\Users\17699\mozhi_platform\`）
- Agent 通过 OpenClaw 框架管理，每个 Agent 是一个 cron 调度的独立 session
- Agent 之间没有共享内存或进程内通信通道
- 飞书 Webhook 回调已被验证为不可靠（限流、丢消息、延迟不稳定）
- 团队经验：Windows 文件系统（NTFS）有成熟的文件锁语义和原子重命名操作

---

## 决策

**采用文件系统信号总线（File System Signal Bus）**。

### 具体实现

1. **信号目录**: 系统在 `C:\Users\17699\mozhi_shareports\signals\` 下建立子目录
   - `triggers/` — Agent触发信号
   - `dispatch/` — 分发信号
   - `consensus/heartbeat/` — 心跳信号
   - `signals/` — 数据信号
2. **信号载体**: 每个信号是一个 JSON 文件（或特定 Markdown 文件），携带 `status`, `task_id`, `agent`, `completed_time` 等元数据
3. **生产者**: 任务完成的 Agent 写入信号文件
4. **消费者**: 目标 Agent 通过 cron 调度轮询信号目录
5. **写入锁定**: 利用 NTFS 原子重命名操作保证写入完整性
6. **写入验证**: 每次写入后立即 read 验证，失败重试最多3次

### 附加工程保证

- `.done` / `.failed` 信号文件写入 `pipeline/tasks/`，与主信号分离
- 心跳机制：每个 Agent 每次 cron 启动时写入心跳，20秒超时判定 offline
- Fail-closed：信号文件缺失或格式错误时，消费者不执行任务

---

## 放弃方案

| 方案 | 放弃原因 |
|------|---------|
| **飞书消息队列** | 飞书 Webhook 延迟不稳定（3~30s rtt），偶发丢消息；API 调用次数受限；回调不可靠（见过无回调的情况） |
| **Redis 发布订阅** | 需要额外维护 Redis 实例；Windows 环境下 Redis 配置复杂；重启后数据丢失风险；团队对 Redis 运维经验不足 |
| **HTTP/REST 回调** | Agent 之间直接耦合（A需要知道B的地址）；单点故障；需要额外的HTTP服务器；Windows端口冲突风险 |
| **SQLite 共享数据库** | 写锁竞争；需要在每个 Agent 中配置数据库连接；增加 IO 压力 |
| **命名管道 / Windows IPC** | OpenClaw 跨 session 隔离；Agent 在不同进程中无法共享管道句柄 |

---

## 后果

### 正面

- ✅ **零外部依赖**: 文件系统是操作系统原生能力，无需额外安装或配置
- ✅ **持久化**: 文件写入后即使系统重启，信号不丢失
- ✅ **调试友好**: 运维人员可直接查看 signals/ 目录了解系统状态
- ✅ **原子性**: NTFS 文件系统提供原子写入（write+close）和重命名
- ✅ **fail-closed**: 信号文件缺失自然阻止错误执行
- ✅ **扩展性**: 新增 Agent 只需新增信号类型和轮询逻辑

### 负面

- ❌ **轮询延迟**: Agent 只能等 cron 调度或轮询间隔才能发现新信号（~10秒~1分钟）
- ❌ **文件系统 IO**: 大量小文件写入可能增加磁盘开销（当前管线规模无影响）
- ❌ **清理机制**: 需要定期清理过期信号文件，否则 signals/ 目录膨胀
- ❌ **无实时推�?**: Agent 不会立即感知到新信号，需被动轮询
- ❌ **分布式受限**: 如果未来 Agent 分布在多台机器上，需要网络文件系统（如 SMB）或换用其他方案

### 缓解措施

1. **轮询延迟**: 核心管线（晨报）通过 `cron` 精确调度，非轮询感知
2. **文件清理**: 每日归档脚本清理 >24h 的信号文件
3. **写入验证**: 所有写入强制 read 验证，防止静默写失败
4. **记录保留**: signals/ 目录下已完成的信号可以保留24小时用于调试

---

## 相关文档

| 文档 | 路径 |
|------|------|
| 信号总线 Schema | `docs/05_protocols/signal_schema.md` |
| 任务触发信号协议 | `docs/05_protocols/task_signal_schema.md` |
| 管线总览 | `docs/00_overview/pipeline_overview.md` |
| 工作空间 SOUL.md 写入验证规范 | `workspace-moheng/SOUL.md §3` |
