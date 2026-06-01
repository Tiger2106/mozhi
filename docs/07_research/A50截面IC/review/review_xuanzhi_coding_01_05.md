# 玄知编码阶段审核意见（task_01~05）

- **审核者**: 玄知（架构/数据一致性）
- **审核时间**: 2026-05-29T22:29+08:00
- **审核类型**: Stage 2 技术把关（编码阶段）
- **审核范围**: task_01~05 整体产出（DDL + ETL + 摸底 + 测试 + 数据库）

---

## 最终结论：CONDITIONAL_PASS

**理由**：DDL三表覆盖完整，后复权方向确认可靠（close×adj_factor），幂等设计到位。但**a50_universe by_define方案存在前视偏差**（与design_v2 §3.4明确警告矛盾），且**停牌处理方向偏离设计文档**——满足条件后放行，但建议在IC计算阶段前完成修复。

---

## 架构合理性审查

### 1.1 ETL管线 vs design_v2 一致性

| 检查项 | 状态 | 说明 |
|:-------|:----:|:------|
| DDL字段覆盖design_v2 §1.2 | ✅ PASS | 3表DDL均完整覆盖设计字段，另增 total_share 作为float_share降级用（合理增强） |
| 字段映射（pe_ttm→pe） | ✅ PASS | stock_daily.pe_ttm → a50_daily_ohlcv.pe，与设计一致 |
| 索引完整性 | ✅ PASS | 3表共7个索引已创建，复合索引 idx_a50_daily_pk(ts_code, trade_date) 就绪 |
| 复权方向 | ✅ PASS | verify_adj_direction 断言通过，后复权连续性偏差<0.001% |
| 数据库路径 | ⚠️ 偏离 | design_v2 §1.1 指定 `data/a50_ic/a50_ic.db`，实际写入 `data/market/a50_ic.db`。路径不一致不影响功能但建议统一 |
| 版本锚定 | ✅ PASS | source_version='v1' 已写入 |
| PRAGMA foreign_keys | ✅ PASS | ETL连接中显式设置 ON |

### 1.2 停牌处理（⚠️ 偏离设计）

**问题**：design_v2 §3.3 要求停牌日保留行，`close=NULL`，`null_reason='SUSPENDED'`。但ETL代码中 `filter_suspended_and_ipo` **直接移除停牌行**。

**实际数据验证**：
- `close IS NULL` = 0
- `null_reason` = 全部 None
- `close=0 AND volume=0` = 0

**影响**：
- 下游 `get_dynamic_cross_section` (design_v2 §2.4 Step 2) 依赖 null_reason 停牌检测或退化条件，当前 DB 中没有停牌标记行，检测逻辑无法生效
- 前向收益计算期间若有停牌，缺乏连续挂载点
- 虽然当前数据无停牌记录（source DB 的 stock_daily 已预先清理），但**架构层面与设计文档不一致**，未来数据变更时停牌机制无法按设计运行

**建议**：修改 ETL 使其保留停牌行，标记 null_reason 而非移除。若当前运行无影响，标记为待修复（条件通过条件）。

### 1.3 a50_universe 构建方案（⛔ 架构风险）

**问题**：design_v2 §3.4 明确警告：
> "若 tushare API 仅返回当前成分股（不含历史调整），**优先采用方案B（Wind/Choice导出）**，而非利用 stock_daily 最早 trade_date 近似。因为后者在新股纳入窗口期内会产生前视偏差——纳入前该股票数据已存在但尚不属于指数。"

实际实现采用 **by_define 降级方案**（tushare API 不可用），以 `MIN(trade_date)` 作为 `in_date`。

**实际数据验证**：
- 50 条记录全部 source='by_define'
- 25 只股票 in_date > 20070104（如 300750.SZ in=20180611, 688981.SH in=20200716）
- 这些 in_date 是该股票在 market_data.db 中的**首日**，而非其**纳入A50的日期**

**风险量化**：
- 以 300750.SZ（宁德时代）为例：in_date=20180611 是科创板开板数据起始日，但其正式纳入上证50的日期更晚（约2021年12月左右）。这意味着在2018~2021年间，宁德时代会被错误纳入universe
- 后验IC计算的截面筛选（design_v2 §2.4 Step 4）会将该范围之前的数据纳入计算，产生**前视偏差**

**建议**：
- **P1 必须修复**：临时方案：从CSI官网手动收集A50调整记录，维护成`universe_adjustments.csv`
- 或：后续安排tushare API权限申请，优先使用 index_member 接口
- 在IC计算阶段前必须修复此问题

---

## 数据一致性核验

### 2.1 数据量一致性

| 指标 | 源DB (stock_daily) | 目标DB (a50_daily_ohlcv) | 差值 |
|:-----|:-----------------:|:------------------------:|:----:|
| 总行数 | 206,387 | 206,387 | **0** |
| 股票数 | 50 | 50 | 0 |
| 时间范围 | 20070104~20260526 | 20070104~20260526 | 一致 |

**结论**：源库与目标库行数完全一致，说明 `filter_suspended_and_ipo` 在当前数据集中实际上没有过滤掉任何行（当前数据无close=NULL或close=0的记录）。与设计预期 ~235,500行（50×4,710天）的差异来自**部分股票上市时间晚于2007年**，这是正常现象。

### 2.2 复权方向确认

以贵州茅台 2024-12-20 除权事件验证：

| 日期 | 后复权close | 后复权pre_close | adj_factor | 验证 |
|:----|:----------:|:--------------:|:----------:|:----:|
| 20241219 | 12,439.10 | 12,603.43 | 8.020000 | — |
| 20241220 | 12,397.30 | **12,439.08** | 8.145400 | pre_close vs 前日close偏差=**0.0001%** ✅ |
| 20241223 | 12,433.55 | **12,397.30** | 8.145400 | pre_close vs 前日close偏差=**0.0000%** ✅ |

**结论**：后复权方向确认（close×adj_factor），除权前后价格连续，偏差<0.001%。Moatai当前后复权close=10,755（原始≈1274），数值合理。

### 2.3 IPO首日检测逻辑

**问题**：`detect_ipo_first_day` 中 `is_first_row & adj_prev.isna()` 等价于 `is_first_row`（代码注释中已承认），导致**每只股票的数据首行均被标记为IPO**。

- 当前数据影响：50行（每股票首行）被标记，但实际未被过滤（行数差=0证实）
- 若未来切换数据源或补充数据，该逻辑会错误地移除老股票的首个交易日记

**建议**：
- T04-02（墨萱已标注待修复）：结合a50_universe.in_date验证，仅当 in_date == 数据起始日时才标记为真实IPO
- 当前不阻塞

---

## 复现性验证

### 3.1 ETL脚本可重跑性

| 检查项 | 状态 | 说明 |
|:-------|:----:|:------|
| INSERT OR IGNORE | ✅ | 幂等，重复跑不会产生重复行 |
| 表存在性 | ✅ | CREATE TABLE IF NOT EXISTS |
| PRAGMA foreign_keys | ✅ | 每次连接设置 |
| a50_universe重建 | ⚠️ | DELETE FROM + 逐条INSERT（非事务包裹，写操作间短窗口表空。实际场景影响极小） |
| 脚本入口 | ⚠️ | `main()` 只调 extract+verify，**不调 build_a50_universe**。用户需另行执行。建议统一入口 |

### 3.2 测试脚本完整性

`test_suspension_ipo.py`：
- 构造含停牌+IPO首行的13行测试DataFrame
- 3个测试（mark_suspension_rows / detect_ipo_first_day / 集成过滤）
- 测试通过 ✅

**但**: 测试验证的是当前**错误的IPO检测逻辑**（所有股票首行均标记）。未来修正IPO逻辑后需同步更新测试。

---

## 发现问题汇总

| 编号 | 优先级 | 类别 | 问题 | 影响 | 关联墨萱标注 |
|:----|:-----:|:----|:-----|:----|:-----------|
| Z01 | **P1** | 架构 | a50_universe by_define 方案使用 MIN(trade_date)=in_date，排除tushare后未走Wind/Choice/hand-made CSV，违反design_v2优先级。25只in_date>20070104的股票实际是上市日而非A50纳入日，IC计算时会引入前视偏差 | 高 — 直接腐蚀截面IC准确性 | — |
| Z02 | **P1** | 架构 | 停牌行被移除而非保留+标记null_reason，违反design_v2 §3.3。下游null_reason依赖的检测逻辑失效 | 中高 — 未来数据含停牌时停牌机制失效 | — |
| Z03 | **P2** | 数据一致 | IPO首日检测误判所有股票首行（`is_first_row & adj_prev.isna()` ≡ `is_first_row`），代码注释已承认但未修复。T04-02已登记 | 低 — 当前数据无remove影响，但逻辑错误 | T04-02 |
| Z04 | **P3** | 架构 | DB路径与design_v2不一致：设计 `data/a50_ic/`，实现 `data/market/` | 低 — 纯路径对齐 | — |
| Z05 | **P3** | 复现性 | main() 入口未包含 build_a50_universe 调用，需手动执行 | 低 — 设计为模块化，但有遗漏风险 | — |

---

## 条件通过条件

在IC计算阶段（T+14~T+21）前，需完成以下修复：

1. **[P1] Z01**: a50_universe 改用可靠数据源（CSI官方调整记录/tushare index_member）。临时方案：手工维护 `universe_adjustments.csv`
2. **[P1] Z02**: ETL修改为保留停牌行，标记 null_reason='SUSPENDED'，close置NULL

以上修复完成后，进入IC计算阶段时才可确保截面筛选正确性。

---

*编写: 玄知 | 2026-05-29T22:29+08:00*
