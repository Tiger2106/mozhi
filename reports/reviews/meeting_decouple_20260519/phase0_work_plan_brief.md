# Phase 0 工作计划简述

---
author: moheng
created_time: 2026-05-20T12:40+08:00
status: READY
---

## 背景

Stage 3.5 Freeze Review 已通过。Signal Protocol v1 接口冻结，ADR-004 治理框架冻结。可进入 Phase 0 实施。

---

## 1. Phase 0（Day 1-2）— 具体做什么

| 项目 | 内容 | 交付物 |
|:-----|:------|:--------|
| **Signal Protocol v1 实现** | 实现 Core schema 序列化/反序列化（Python dataclass + JSON serialization）、V-13 验证规则（4类红线 + 宽松/严格双模式）、extras 64KB 上限校验 | `src/signals/signal_protocol_v1.py` + 单元测试 |
| **测试桩** | TC-01 ~ TC-05 测试用例实现（空extras/版本不匹配/未知键/边界值）、兼容性测试套件 | `tests/test_signal_protocol_v1.py` |
| **knowledge.db schema** | 信号表 `signals`、消费记录表 `consumed_signals`、归档索引表 | `src/knowledge/db_schema.py` + migration SQL |
| **日志基础设施** | extras debug.* key 超限预警、内存池向量记录接入 | `src/signals/logger.py` |

**交付检查点**：序列化↔反序列化双向通过 ≥ 10 组边界测试，extras 红线拦截通过，knowledge.db schema 可运行 CREATE TABLE。

---

## 2. Phase 1-3（Day 3-15）— 概要

| 阶段 | 时间 | 主线 | 关键交付 |
|:----|:-----|:------|:----------|
| **Phase 1** | Day 3-7 | 全部策略重构为统一 Signal 产出 | 4个策略均输出 Signal 对象，不再产生 OrderRequest；墨萱一致性测试通过 |
| **Phase 2** | Day 8-11 | SignalConsumer + 轻量 Simulator | Consumer（Signal→OrderRequest 映射）可运行；Simulator 可独立验证单个 Signal 效果 |
| **Phase 3** | Day 12-15 | 双系统验证 + 旧代码清理 | 新旧系统并行运行，5类偏差逐类验收通过后清退旧 SignalBridge |

---

## 3. 各 Agent 分工

| Agent | Phase 0 职责 | Phase 1-3 职责 |
|:------|:-------------|:----------------|
| **墨衡** 🖋️ | Signal Protocol v1 实现、Serializer、V-13 验证、debug.* 预警、64KB 上限 | Phase 1: 策略重构（剥离交易依赖）；Phase 2: Consumer + Simulator 开发；Phase 3: 双系统验证框架 |
| **墨萱** 🔍 | 测试桩（TC-01~TC-05）、兼容性测试套件、knowledge.db schema 审查 | Phase 1: 信号一致性测试；Phase 2: Consumer + Simulator 测试；Phase 3: 5类偏差验收 |
| **墨涵** 📋 | knowledge.db 信号相关表创建、归档框架接入、日终归档任务基架 | Phase 1: 信号入库管道；Phase 2: 知识库连续写入；Phase 3: 旧代码清理监督 + ADR归档 |

> 玄知不参与 Phase 0-3 日常执行，仅参与 ARB 裁决（Q3 Level 5 评估入口）。

---

## 4. 关键里程碑

| 里程碑 | 时间 | 判定标准 |
|:-------|:-----|:----------|
| **Phase 0 交付** | Day 2 晚 | Signal 序列化/反序列化 + 测试桩 + DB schema 可运行 |
| **Phase 1 交付** | Day 7 | 4个策略全部改出 Signal、旧 import 链已断开 |
| **Phase 2 交付** | Day 11 | Consumer + Simulator 连跑通过，灰度可切入 |
| **Phase 3 验收** | Day 15 | 5类偏差 ≤ 阈值，旧 SignalBridge 下线 |
| **ARB 季度审查** | Q3 末 | 评估是否需要 Level 5 扩展 |

---

## 5. 对明天 08:00 早报管线的影响

### 核心原则：Phase 0 不干扰生产管线

| 项目 | 影响 | 说明 |
|:-----|:-----|:------|
| **08:00 早报管线** | ❌ **不受影响** | Phase 0 仅实现新协议基础设施，不修改早报管线代码。明日早报继续走**旧路径（SignalBridge + OrderRequest）** |
| **trade execution** | ❌ **不受影响** | Phase 0 不涉及订单路径变更。当前 trade execution 逻辑不依赖 Signal Protocol v1 |
| **并行策略** | 切换到灰度时（Phase 2 后） | 新 SignalConsumer 先注册为**只读观察者**（不实际发单），观察偏差达标后再切入 |
| **需关注的风险** | 低 | 如果明天早报管线本身有已知问题（如 cron delivery target 前缀错误），应**优先修复该问题**再启动 Phase 0。Phase 0 不阻塞修复 |

### 建议

1. **如果未修复 delivery target 前缀问题**（`feishu:chat:` 而非 `chat:`），则明天 08:00 早报可能无法投递到群。建议在 Phase 0 启动前修复这一已知问题。
2. **Phase 0期间（Day 1-2）**早报管线照常运行，新模块独立开发，不引入任何破坏性变更。
3. **Phase 2完成后**（Day 11）新 Consumer 以只读观察者身份接入，不影响生产订单路径。

---

*本文件由墨衡根据 ADR-004 + Stage 3.5 冻结决议整理*
