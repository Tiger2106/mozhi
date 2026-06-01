# OPEN-ITEM-001: pcf_ttm / dividend_yield 采集补全

**阶段**: Phase 2 (C组估值链路修复)
**创建**: 2026-05-31 17:45
**创建人**: 墨涵
**确认人**: Owner（✅ 已确认挂起）

---

## 背景

`daily_basic_collector.py` 的 `ensure_a50_daily_basic_table()` CREATE TABLE 已包含 `pcf_ttm REAL` 和 `dividend_yield REAL` 列定义（墨衡 2026-05-31 17:35 修复），但以下环节尚未接入：

1. `collect_single()` 的 `fields_param` 未包含这两列
2. `write_batch()` 的 INSERT 语句未包含这两列
3. 当前 Tushare Token 积分 < 2000，无法获取这两个字段

## 影响范围

- 列定义：✅ 已就绪（墨衡修复）
- 采集逻辑：❌ 未实现
- 写路径：❌ 未实现
- DDL迁移（migrate_daily_basic.py）：❌ 未包含这两个字段（a50_daily_ohlcv 侧）

## 前置条件

- Tushare Token 升级至 ≥ 2000 积分（当前：无此能力）
- Token 升级后需验证 `check_token_integral()` 返回可用

## 恢复路径

当条件满足时需：

1. 更新 `collect_single()` 的 `fields_param` 加入 `pcf_ttm, dividend_yield`
2. 更新 `write_batch()` 的 INSERT SQL 加入两列参数
3. 更新 `migrate_daily_basic.py` 的 `NEW_COLUMNS` 加入这两列（a50_daily_ohlcv 侧）

## 关联文件

- `src/ingestion/daily_basic_collector.py`
- `src/ingestion/migrate_daily_basic.py`
- `src/ingestion/tests/test_daily_basic_collector.py`
