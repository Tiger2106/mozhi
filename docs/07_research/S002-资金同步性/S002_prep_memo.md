# S002 明日联调 - 预检记录
**作者**: 墨衡
**创建时间**: 2026-05-25T11:28+08:00
**状态**: 预检完成

---

## 1. 格式规范状态

| 项目 | 状态 | 详情 |
|:-----|:-----|:------|
| 格式规范 v1 | ✅ 已发布 | `docs/10_strategies/S002/format_spec_v1.md` |
| 墨萱格式对齐 | ✅ 已确认 | `s002_notify_moxuan.json` → mismatch_heatmap 格式认可 |
| 玄知格式确认 | ⏳ 待确认 | `s002_notify_xuanzhi.json` > 需玄知回复确认 |
| S002代码 | ❌ 无代码目录 | `code/src/strategies/` 下无 S002 目录 |
| S002设计文档 | ✅ 存在 | `docs/10_strategies/S002/design_report.md` |

## 2. 三线格式摘要

| 线 | 文件名 | 路径 | channel_type |
|:---|:-------|:-----|:-------------|
| **墨衡线** | `synchronicity_index_{date}.json` | `reports/{morning\|midday}/{date}/s002/` | 资金流入流出比, 主力净流向, 成交量异动, 价格动量 |
| **墨萱线** | `mismatch_heatmap_{date}.json` | `reports/{morning\|midday}/{date}/s002/` | 价量背离, 资金-价格背离, 多空失衡, 期限结构异常 |
| **玄知线** | `historical_reference_{case_id}.json` | `knowledge_base/s002/` | N/A（按 case 生成） |

## 3. 联调检查清单

- [ ] 等待玄知确认格式
- [ ] 墨萱线: `reports/{report_type}/{date}/s002/mismatch_heatmap_{date}.json` → 校验字段完整性
- [ ] 玄知线: `knowledge_base/s002/historical_reference_{case_id}.json` → 校验字段完整性
- [ ] 三线日期对齐 → 标的池一致性
- [ ] 分歧标注逻辑: 符号不一致时标记 divergent
- [ ] 输出 synchronicity_index 主报告

## 4. 明日工作

1. 检查玄知确认信号（轮询 `signals/triggers/` 目录）
2. 如玄知已确认 → 启动联调
3. 如玄知未确认 → 等待，先推进 S001
