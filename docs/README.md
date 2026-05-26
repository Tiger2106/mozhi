# 📚 墨枢文档库

author: 墨涵  
created_time: 2026-05-15T16:45:00+08:00  
version: v1.0  

---

这里是墨枢平台的知识库。

**墨枢**是墨家投资室多Agent投资分析系统，由墨衡(deepseek R1)、墨涵(MiniMax-M2.7)、玄知(HuggingFace-DeepSeek)、默尘(OpenClaw cron) 协同运作。

## 📖 目录导航

| 目录 | 一句话说明 |
|:-----|:----------|
| **[00_overview](00_overview/)** | 🔭 **总览层** — 新人/三个月后的自己，先从这里开始 |
| **[01_architecture](01_architecture/)** | 🏗️ **架构设计** — 系统分层、信号总线、事件流、存储策略 |
| **[02_development](02_development/)** | 📐 **开发规范** — 代码风格、命名规则、测试规范、Git工作流 |
| **[03_pipelines](03_pipelines/)** | 🔄 **管线文档** — 晨报/晚报/回测/结算/监控各管线详细说明 |
| **[04_agents](04_agents/)** | 🤖 **Agent体系** — 墨衡/墨涵/玄知/默尘职责I/O协作规则 |
| **[05_protocols](05_protocols/)** | 📋 **协议/Schema** — 信号/结算/报告/任务/知识协议定义 + **文件生命周期使用手册** |
| **[06_operations](06_operations/)** | ⚙️ **运维与生产** — 部署/Cron排程/备份恢复/监控/故障响应 |
| **[07_research](07_research/)** | 📊 **回测研究** — 策略框架/因子/参数扫描/验证规则/知识提取 |
| **[08_history](08_history/)** | 📜 **演化历史** — 重构记录/管线改革/ADR决策/废弃说明 |
| **[09_roadmap](09_roadmap/)** | 🗺️ **未来规划** — 各Phase规划/长期愿景/技术债务 |

## 🔍 三句话快速定位

> 如果你在**查文件在哪/怎么用** → `05_protocols/file_lifecycle_manual.md`
>
> 如果你在**找管线关系** → `03_pipelines/`
>
> 如果你想知道**Agent怎么分工** → `04_agents/`
>
> 如果你是**新人/三个月后失忆的自己** → `00_overview/`

## 📝 维护规则

1. 每个文档顶部标注 `author` 和 `created_time`
2. 新增文档后同步更新本README
3. 文档间使用相对路径交叉引用
4. Mermaid图使用标准 \`\`\`mermaid 格式
5. Schema/协议文档推荐使用 JSON + Markdown 双重描述

---

_文档库建立于 2026-05-15_
