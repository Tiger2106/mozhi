# 风险模块方案评审会议议程

> 主持人：墨涵 🖋️
> 日期：2026-05-18
> 状态：待执行

---

## 会议信息

| 项目 | 内容 |
|:----|:-----|
| 主题 | 回测系统风险模块补全方案评审 |
| 前置材料 | `docs/09_roadmap/risk_module_design.md`（36KB，墨衡） |
| 评审方式 | 会签制（三方全部签署通过） |
| 预期产出 | 签署决议 + 实施计划 |

---

## 议程

### 1. 开场（墨涵，2min）

- 会议目的：对风险模块补全方案进行三方会签
- 墨萱审技术实现、墨涵审知识产出、Owner 审业务方向
- 投票规则：不反对即通过（采集 objection）

### 2. 方案陈述（墨衡，10min）

| 主题 | 内容 |
|:----|:------|
| 差距回顾 | 现状(~70%匹配度) → 风险模块空白 → 需要补6个模块 |
| 架构设计 | 风险中间件层：MarketStateFilter → VolatilityRiskManager → DrawdownGuard → RiskPipeline |
| P0 模块 | DrawdownGuard(20min) / VolatilityRiskManager(30min) / MarketStateFilter(25min) / RiskPipeline(15min) |
| P1 模块 | AnchoredVwapFactor(10min) / RegimeContextBuilder(20min) |
| 现有文件修改 | portfolio_manager.py / portfolio_integration.py / knowledge_bridge.py |

### 3. 文件路径合规检查（墨涵，3min）

- [ ] 所有新模块路径：`mozhi_platform/src/backtest/risk/`
- [ ] 路径引用使用 `pipeline_paths.py` 常量
- [ ] 数据文件归入 `data/{domain}/`
- [ ] 设计文档中无硬编码目录

### 4. 技术审查（墨萱，10min）

审查要点：
- [ ] 接口设计是否与现有 BacktestEngine 兼容
- [ ] RiskPipeline 编排方式是否合理（组合式 vs 侵入式）
- [ ] MarketStateFilter 与 RegimeAnalyzer 的联动边界
- [ ] DrawdownGuard 回撤计算是否使用已有的峰值曲线
- [ ] VolatilityRiskManager 的 ATR 计算源（已有因子 vs 独立计算）
- [ ] portfolio_manager.py 的 `position_ratio` 参数变更是否兼容现有调用方
- [ ] AnchoredVwapFactor 独立因子的注册方式
- [ ] 测试覆盖建议

### 5. 战略复核（玄知，5min）

- [ ] 风险模块是否覆盖研究方案的風控要求
- [ ] P0/P1 优先级排序是否合理
- [ ] 与现有回测体系（r1_backtest_engine + method_backtest_runner）的兼容性
- [ ] 实施顺序建议

### 6. 讨论 & 决策（全员，10min）

- [ ] P0 是否可交付（4个子模块）
- [ ] P1 是否进入阶段二
- [ ] 实施顺序：独立开发 vs 流水线串行
- [ ] 负责人：墨衡执行、墨萱测试、墨涵验收

### 7. 会签（3min）

```
墨萱签：[ ] 技术实现正确
墨涵签：[ ] 知识产出完整、文档归档到位
Owner 签：[ ] 业务方向确认
```

---

## 议程文件索引

| 文件 | 说明 |
|:----|:------|
| `docs/09_roadmap/risk_module_design.md` | 方案主文档（墨衡） |
| `docs/09_roadmap/research_vs_backtest_gap.md` | 差距分析（墨衡） |
| `docs/09_roadmap/pipeline_path_standard.md` | 路径合规标准（墨涵） |
| `incoming/2605180747*.txt` | 方案对照源文档 |

---

## 会后产出

- 签署录：三方签名（墨萱/墨涵/Owner）
- 实施任务清单（按优先级排列）
- 对 design doc 的修订（如有）

---

_议程撰写: 墨涵 | 2026-05-18_
