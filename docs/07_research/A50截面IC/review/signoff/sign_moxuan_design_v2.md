# 墨萱签署意见 — A50截面IC设计v2

**签署文档**: `design_v2.md`
**签署时间**: 2026-05-29
**签署人**: 墨萱 (QA Lead/第三方测试员)

---

## 签署审查摘要

### F1 — close NULL矛盾
- **v2修复**: DDL中 `close` 从 `NOT NULL` 改为 `REAL`（可空），§3.3 Step 5确认停牌日置NULL
- **结论**: ✅ 已修复

### F2 — SQL无下界
- **v2修复**: §2.4新增回看窗口下界计算（`LIMIT 1 OFFSET 120`），使用 `BETWEEN ? AND ?` 替代无界查询
- **结论**: ✅ 已修复

### F3 — IPO首日误判
- **v2修复**: §3.3新增 `is_first_row` 双重条件判断（最早交易日 + adj_prev.isna()），可选a50_universe验证
- **结论**: ✅ 已修复

### W1-W6
- **W1 float_share DDL**: `a50_daily_ohlcv` 新增 `float_share` 字段 ✅
- **W2 forward_window持久化**: `a50_cross_ic_result` 新增 `forward_window` 字段及索引 ✅
- **W3 volume_20d_change公式**: 文档修正为 `avg(volume[t-5:t-1])`，与实现一致 ✅
- **W4 SQL注入风险**: §2.4使用参数化传参，空列表保护 ✅
- **W5 reversal_1d除零**: 上层 `get_dynamic_cross_section` 过滤 volume=0/amount=0 ✅
- **W6 min_stocks覆盖率**: §5.1新增T+0摸底任务及阈值降级方案 ✅

---

## 签署意见

（墨萱）签署意见：
- **签署：PASS**
- 理由：3个FAIL（F1 close NULL矛盾 / F2 SQL无下界 / F3 IPO误判）全部修复，6个WARN全部处理，复权方向确认断言、停牌识别双重判断、回看窗口下界、参数化传参等改进使方案自洽且可运行。技术方案通过，同意进入Schema冻结。

---

*本文档由墨萱签署完成，2026-05-29*
