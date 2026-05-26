# 会签决议：量价体系分层框架（V2 + L3 修正版）

**决议编号**：ARCH001_v1
**起草人**：墨涵
**日期**：2026-05-22 18:11 CST
**状态**：✅ 已完成三方会签

---

## 决议内容

经 ChatGPT → 团队评估 → Claude 修正 → 团队再评估 → 主人确认，以下方案正式生效：

### 1. 价格体系（P层）

| 子层 | 内容 | 状态 |
|:----:|:----|:----:|
| P1 | OHLC —— 市场价格 | 已就绪 |
| P2 | avg_trade_price = amount/volume —— 真实成本价格 | 已计算，待入库 |
| P3 | Volume Profile POC/Value Area —— 结构价格 | 待分钟级数据 |

VWAP ± nσ 通道 → 归入 P 层（P3-P4交叉域），非量能体系。

### 2. 量能体系（L层）—— 三层结构

| 子层 | 内容 | 量纲 | 状态 |
|:----:|:----|:----:|:----:|
| L1 | volume, amount —— 绝对量能基线 | 手/元 | 已就绪 |
| L2 | turnover_rate, volume_ratio —— 标准化相对量能 | 无量纲 | 待实施 |
| L3 | 量偏度/量价相关系数/量集中度 —— 量分布结构 | 无量纲 | 待分钟级数据前置 |

### 3. free_float 口径

- **数据源**：Tushare daily_basic.float_share（流通股本，万股）
- **锁定原则**：一致性优先于精确性
- **迁移策略**：P0 锁定 + 口径映射层（可迁移设计）+ 全历史回溯脚本就绪后改

### 4. 实施节奏

- **定义阶段**：可并行（已完成）
- **实施阶段**：纯串行 L1 → 冻结口径 → L2 → L3
- L3 前置条件：分钟级数据管道就绪

### 5. 引用来源

- ChatGPT 意见：`incoming/2605221734接入均价.md` + `incoming/2605221734接入实际换手率.md`
- Claude 意见：`incoming/2605221734接入讨论claude意见.md`
- 墨衡 vwap_factor.py 统一完成见 backtest_engine 5文件修改
- 数据入库规范：`docs/data_ingestion_standard.md`
- 数据契约：`data_contract.py` / `etl_normalizer.py` / `source_registry.json`

---

## 会签栏

| 签署方 | 角色 | 结论 | 时间 |
|:------:|:----:|:----:|:----:|
| 墨萱 | 技术实现正确 | ✅ 签署通过（3项非阻塞保留） | 18:12 |
| 墨涵 | 知识产出完整、文档归档到位 | ✅ 签署通过 | 18:12 |
| 主人 | 业务方向确认 | ✅ 已确认 | 18:10 |

### 墨萱保留条件（非阻塞）

1. volume_ratio 标准化分母口径需在 implementation spec 层固定
2. 量偏度计算窗口参数需在技术设计阶段明确
3. Tushare float_share 延迟更新建议在 ETL 层增加修正标记

---

## 实施时间表

墨衡已输出完整实施时间表：`plans/chianghao_implementation_timeline.md`

**关键路径**：~110min（18:10→~20:15），缓冲余量 ~3h45min

**7个阶段，24项子任务**：
- Phase 0：定义阶段（15min，并行）
- Phase 1：基础设施就绪（10min）
- Phase 2：L2 正式实施（35min，串行主链）
- Phase 3：P 层完善（25min，与L层并行）
- Phase 4：分钟级数据管道（30min，L3前置条件）
- Phase 5：L3 实施（15min）
- Phase 6：全链路验证（20min）

**文件路径**：`C:\Users\17699\mo_zhi_sharereports\plans\chianghao_implementation_timeline.md`
