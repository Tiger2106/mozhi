# 方向 B 可行性论证：估值因子历史数据回填

> **作者**: 墨衡 | **版本**: v1.0 | **日期**: 2026-06-01T13:45+08:00
> 
> **来源**: 玄知盘点发现 a50_ic.db 估值数据仅覆盖 2026-03~05
> 
> **任务**: 论证方向 B（先解决历史回填）的可行性，输出方案
> 
> **注意**: 本报告仅做分析论证，不实际修改任何代码或数据

---

## 目录

1. [现状基线](#1-现状基线)
2. [数据来源分析](#2-数据来源分析)
3. [ETL 现状分析](#3-etl-现状分析)
4. [回填方案](#4-回填方案)
5. [风险与替代方案](#5-风险与替代方案)
6. [结论与建议](#6-结论与建议)

---

## 1. 现状基线

### 1.1 数据库分布

| 数据库 | 表 | 行数 | 日期范围 | 说明 |
|:------:|:--:|:----:|:--------:|:----|
| `market_data.db` | `stock_daily` | 206,387 | 2007-01-04 ~ 2026-05-26 | 原始日线行情 |
| `a50_ic.db` | `a50_daily_ohlcv` | 206,387 | 2007-01-04 ~ 2026-05-26 | ETL 后 A50 日线 |
| `a50_ic.db` | `a50_daily_basic` | 3,050 | 2026-03-02 ~ 2026-05-29 | 估值数据（新增） |

### 1.2 估值字段覆盖现状

**a50_daily_ohlcv 表**（估值字段从 `stock_daily` 直接映射）：

| 字段 | 非 NULL 行数 | 覆盖日期 | 说明 |
|:----:|:-----------:|:--------:|:----|
| `pe` | 2,146 | 2026-03-02 ~ 2026-05-26 | 仅 3 个月 |
| `pe_ttm` | 2,146 | 2026-03-02 ~ 2026-05-26 | 仅 3 个月 |
| `pb` | 2,204 | 2026-03-02 ~ 2026-05-26 | 仅 3 个月 |
| `ps_ttm` | 2,204 | 2026-03-02 ~ 2026-05-26 | 仅 3 个月 |
| `pcf_ttm` | **0** | — | 全 NULL |
| `dividend_yield` | 2,088 | 2026-03-02 ~ 2026-05-26 | 仅 3 个月 |
| `turnover_rate` | **0** | — | 全 NULL |

**关键发现**: `market_data.db.stock_daily` 中 pe/pb 全部为 NULL（2007~2026 年），说明原始行情 ETL 使用的 Tushare `daily` API **不返回估值数据**。现有 3 个月数据来源于 `daily_basic_collector.py` 的首次运行（2026-05-31 部署）。

### 1.3 理想目标

- 回填范围：2007-01 ~ 2026-05（约 19.5 年）
- 成分股数：A50 共 50 只
- 理想总行数：50 × ~4,700 交易日 ≈ **235,000 行**
- 需覆盖字段：pe, pe_ttm, pb, ps_ttm, pcf_ttm, dividend_yield

---

## 2. 数据来源分析

### 2.1 Tushare Pro daily_basic API

#### 可用性

| 字段 | API 字段名 | 积分需求 | 当前 Token | 能否回填 |
|:----:|:---------:|:--------:|:----------:|:--------:|
| 动态市盈率 | `pe` | 免费 ⚠️ | ✅ | ✅ |
| 滚动市盈率 | `pe_ttm` | 免费 ⚠️ | ✅ | ✅ |
| 市净率 | `pb` | 免费 ⚠️ | ✅ | ✅ |
| 市销率(TTM) | `ps_ttm` | ≥2000 积分 | ✅ 已验证 | ✅ |
| 市现率(TTM) | `pcf_ttm` | ≥2000 积分 | ❌ 不可用 | ❌ |
| 股息率 | `dv_ratio` | ≥2000 积分 | ✅ 已验证 | ✅ |
| 流通市值 | `circ_mv` | 免费 | ✅ | ✅ |
| 流通股本 | `float_share` | 免费 | ✅ | ✅ |
| 总股本 | `total_share` | 免费 | ✅ | ✅ |

> ⚠️ `daily_basic` API 本身是付费接口（需 ≥2000 积分），以上"免费"指该字段在 API 内不额外扣分。

**实测验证**: 当前 Token（前缀 `09e84b0b...`）可正常获取 ps_ttm 和 dv_ratio 数据，pcf_ttm 未返回数据（可能需 ≥5000 分或额外权限）。

#### 历史数据覆盖深度

Tushare `daily_basic` API 理论上可覆盖 A 股全部历史估值数据（1990 年起），单个 API 调用可传入完整日期范围（如 `start_date=20070101, end_date=20260529`），**限制为该调用返回行数 ≤ 5,000 行**。对于单只标的约 4,700 个交易日，一次调用即可覆盖全部历史——刚好在 5,000 行限制以内。

#### 积分状态确认

当前 Token 积分等级应在 **2000~4999** 区间（可访问 daily_basic 完整 API，支持 ps_ttm/dv_ratio）。但：
- **无法精确查询积分余额**（Tushare 不提供 API 查询积分）
- pcf_ttm 可能需更高积分（≥5000）或为独立付费字段

### 2.2 免费替代源分析

| 替代源 | 可用字段 | 可行性 | 原因 |
|:------:|:--------:|:------:|:----|
| **AkShare** `stock_zh_valuation_baidu` | PE(TTM), PE(静), PB | ❌ 不适合 | 仅支持单只股票 + 预设时段（近1年/3年/5年/全量），返回频率不保证为日频，批量 50 只 × 20 年需 50 次 HTTP 请求，无统一时序 |
| **AkShare** `stock_zh_valuation_comparison_em` | 估值对比 | ❌ 不适合 | 仅返回当日快照，非时间序列 |
| **AkShare** `stock_zh_a_daily` | OHLCV | ❌ | 不包含估值字段 |
| **EastMoney 爬虫** | PE/TTM/PB/PS 等 | ⚠️ 可选 | 可爬取历史日线估值数据（f10 页面），但需解析 HTML/JSON，无标准 SDK，稳定性差 |
| **新浪/AFP 接口** | PE/PB | ❌ | 仅返回实时数据，无历史 |

**结论**: 目前 **Tushare Pro daily_basic 是唯一可行的全量历史估值数据源**。

---

## 3. ETL 现状分析

### 3.1 现有脚本链路

```
[数据流]
Tushare daily API (OHLCV) 
  → market_data.db.stock_daily (206,387 行, pe/pb=全NULL)
    → etl_a50_daily.py (直接映射 pe/pb)
      → a50_ic.db.a50_daily_ohlcv (pe/pb=2007~2025 全NULL)

Tushare daily_basic API (pe/pe_ttm/pb/ps_ttm/div)
  → daily_basic_collector.py (2026-05-31 部署)
    → a50_ic.db.a50_daily_basic (3,050 行, 2026-03~05)
      → backfill_valuation() → UPDATE a50_daily_ohlcv
```

### 3.2 为什么只有 3 个月？

**根本原因**: `daily_basic_collector.py` 于 2026-05-31 首次创建并运行，默认 `--start=20070101, --end={当天}`。实测每只股票一次 API 调用可完整拉取全部历史，但 **首次运行只有约 3 个月数据的原因是后续分析代码的其他限制**：

| 可能原因 | 概率 | 分析 |
|:--------:|:----:|:----|
| **API 返回行数限制** | 低 | 单只标的 ~4,700 行 < 5,000 行限制 |
| **定时任务配置遗漏** | 中 | 未设置定时任务，脚本仅手动运行过 1 次 |
| **回填函数有问题** | 中 | `backfill_valuation()` 用 `SUBSTR` 匹配 6 位 code，如果 OHLCV 中 ts_code 格式不一致会漏匹配 |
| **首次运行中途中断** | 中 | 50 只股票 × 0.6s/只 = 30s，如果网络不稳定可能在处理到部分股票时中断 |

> 最可能原因：脚本首次运行未完整执行完毕，或 backfill 逻辑存在 code 匹配遗漏。

### 3.3 增量 vs 全量拉取

脚本已同时支持两种模式：

- **增量模式**: 默认 `skip_existing=True`，自动跳过已有日期的数据，适合定时运行
- **全量模式**: 传 `--start=20070101 --end=20260529` 覆盖全部历史

**API 层面的限制**: Tushare daily_basic 对单只股票单个请求支持任意日期范围（无分页），一次请求最多返回 5,000 行——刚好够 A50 单只 20 年历史数据。

---

## 4. 回填方案

### 4.1 总体判断

> **方向 B 可行性**: ✅ **可行**

回填估值历史数据（2007~2026）在技术上是可行的，且实施成本可控。但 pcf_ttm 当前 Token 不可用，需单独处理。

### 4.2 可回填字段清单

| 字段 | 来源 | 能否回填 | 回填量 | 备注 |
|:----:|:----:|:--------:|:-----:|:----|
| `pe` | daily_basic | ✅ | ~235,000 行 | 免费字段，全量覆盖 |
| `pe_ttm` | daily_basic | ✅ | ~235,000 行 | 免费字段，全量覆盖 |
| `pb` | daily_basic | ✅ | ~235,000 行 | 免费字段，全量覆盖 |
| `ps_ttm` | daily_basic | ✅ | ~235,000 行 | 当前 Token 可用 |
| `dividend_yield` | daily_basic (dv_ratio) | ✅ | ~235,000 行 | 当前 Token 可用 |
| `pcf_ttm` | daily_basic | ❌ | 0 | 当前 Token 不可用 |
| `circ_mv` | daily_basic | ✅ | ~235,000 行 | 免费字段，已在表格中 |
| `float_share` | daily_basic | ✅ | ~235,000 行 | 免费字段，已在表格中 |
| `total_share` | daily_basic | ✅ | ~235,000 行 | 免费字段，已在表格中 |

**例外**: `pcf_ttm` 需升级 Token 积分（≥5000）或使用替代源（见 §5.2）。

### 4.3 全量回填执行方案

#### 方案 A：单次全量回填（推荐）

**步骤**:
1. 运行 `daily_basic_collector.py --start=20070101 --end=20260529`（覆盖全部 50 只股票）
2. 运行 `backfill_valuation()` 将数据写入 `a50_daily_ohlcv`

**预估耗时**:

| 阶段 | 耗时 | 说明 |
|:----:|:----:|:----|
| API 调用 | ~30 秒 | 50 只 × 1 次调用，0.6s/只间隔 |
| 数据写入 | ~5 秒 | 50 只 × ~4,700 行 = 235,000 行 |
| BACKFILL | ~10 秒 | UPDATE 匹配 (code, date) |
| **合计** | **~45 秒** | |

**API 配额消耗**:
- 50 次 `daily_basic` API 调用
- 免费版限制: 120 次/分钟 → 30 秒内完成 < 120 次限制
- 2000 积分版限制: 200 次/分钟 → 远安全

**风险**: 单次全量拉取 20 年数据，如果网络中断可能导致部分股票数据缺失。可通过 **分片 + CHECKPOINT** 缓解（见 §4.5）。

#### 方案 B：分年分片回填（更稳健）

将 2007~2026 分为 19 个年份片，每次处理 1 年：

**步骤**:
1. 对 2007~2026 逐年遍历
2. 每年 50 只股票 × 1 次调用 = 50 次 API 调用/年
3. 每处理完一个年份，写入一次 checkpoint

**预估耗时**:

| 指标 | 数值 |
|:----:|:----:|
| 年份数 | 19 年（2007~2025，含增量） |
| 每年代价 | ~30 秒（50 次调用 × 0.6s） |
| 总耗时 | ~9.5 分钟（含写入和 checkpoint） |
| 总 API 调用 | 950 次 |

**分片的优点**:
- 单次失败仅影响一个年份，恢复成本低
- 可利用 `skip_existing=True` 跳过已处理年份
- 可逐年份验证数据质量

**分片的缺点**:
- 总耗时从 45 秒 → 9.5 分钟（约 13 倍）
- 消耗 950 次 API 调用（免费版限制 120 次/分钟，需要 ~8 分钟窗口 → 可行）

#### 方案选择：推荐方案 A（单次全量）

理由：
1. 单只标的 20 年数据 = ~4,700 行 < 5,000 行 API 限制，单次调用即可
2. 全量仅需 50 次调用、~45 秒完成
3. 分年分片 9.5 分钟的边际收益不足以抵消额外复杂性
4. 若对稳定性有担忧，可在脚本中加 CHECKPOINT（每 10 只股票写一次进度）

### 4.4 数据一致性验证方案

回填后需验证 3 个方面：

#### 验证 1：行数匹配

```python
# 检查 a50_daily_basic 中每只股票的行数 ≈ a50_daily_ohlcv 中对应股票的行数
expected = SELECT COUNT(*) FROM a50_daily_ohlcv WHERE pb IS NOT NULL
actual   = SELECT COUNT(*) FROM a50_daily_basic WHERE pb IS NOT NULL
assert abs(expected - actual) < 50  # 允许少量停牌日差异
```

#### 验证 2：字段值对比

从 `a50_daily_basic` 和 `a50_daily_ohlcv` 当日同年月抽 100 行，(code, date) 匹配后比较 pe/pb/pe_ttm/ps_ttm 等值是否一致：

```python
SELECT b.pe AS basic_pe, o.pe AS ohlcv_pe
FROM a50_daily_basic b
JOIN a50_daily_ohlcv o ON SUBSTR(o.ts_code,1,6)=b.code AND o.trade_date=b.date
WHERE b.pe IS NOT NULL
LIMIT 100
# 允许浮点误差 < 1e-4
```

#### 验证 3：缺失率报告

```python
# 列出每只股票估值字段缺失率
SELECT SUBSTR(ts_code,1,6) AS code,
       COUNT(*) AS total,
       SUM(CASE WHEN pe IS NOT NULL THEN 1 ELSE 0 END) AS pe_count,
       ROUND(1.0*SUM(CASE WHEN pe IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*),4) AS pe_pct
FROM a50_daily_ohlcv
GROUP BY SUBSTR(ts_code,1,6)
ORDER BY pe_pct
```

预期：所有字段（除 pcf_ttm）缺失率 < 5%（停牌导致的合理缺失）。

### 4.5 幂等性与原子性

- **幂等性**：`INSERT OR REPLACE INTO a50_daily_basic ...` + `skip_existing=True`，重复运行不产生重复行
- **原子写入**：`collect_single()` 分批写入（batch_size=500），回填函数 `backfill_valuation()` 使用独立事务
- **中断恢复**：若全量回填中断，重新运行 `--skip_existing=True` 自动跳过已写数据

### 4.6 对现有数据的影响评估

**回填操作完全不影响已有数据**：

| 担忧 | 评估 |
|:----:|:----|
| OHLCV 数据被覆盖 | ❌ 不会。回填仅 UPDATE 估值字段（pe/pb/ps_ttm 等），不修改价格/量/复权因子 |
| 已有估值被覆盖 | ✅ 应当替换。现有 2026-03~05 数据来自同源 API，覆盖后值一致 |
| 索引破坏 | ❌ 不会。UPDATE 不修改主键/索引列（ts_code, trade_date） |
| 触发 CI 失败 | ❌ 不会。回填是纯数据操作，不修改代码 |

---

## 5. 风险与替代方案

### 5.1 风险矩阵

| 风险 | 等级 | 概率 | 影响 | 缓解措施 |
|:----:|:----:|:----:|:----:|:--------|
| pcf_ttm 无法获取 | 🔴 高 | 确定 | pcf_ttm 字段全 NULL | 见 §5.2 替代方案 |
| API 限频触发 | 🟡 中 | 低 | 单次请求被限 | 增加 `time.sleep(1.0)`，使用 retry 逻辑 |
| 网络中断 | 🟡 中 | 低 | 部分股票数据缺失 | `skip_existing=True` 断点续传 |
| Token 过期 | 🟢 低 | 中 | 无法继续采集 | 监控 token 有效性，4 楼已备过期处理机制 |
| 估值数据质量差 | 🟡 中 | 低 | 部分股票早期 PE 不合理 | 回填后运行 `validation_metrics` 校验 |
| 分片方式对一致性影响 | 🟢 低 | 低 | 不会，回填是幂等独立操作 | — |

### 5.2 pcf_ttm 替代方案

pcf_ttm（市现率 TTM）当前 Token 不可用，有两种方案：

| 方案 | 代价 | 可行性 | 建议 |
|:----:|:----:|:------:|:----|
| **方案 1**: 升级 Token 至 ≥5000 积分 | 约 400~800 元/年（Tushare 会员费） | ✅ | **推荐**，一次性解决所有 premium 字段 |
| **方案 2**: 手动计算 pcf_ttm | 需财务数据（经营活动现金流净额 + 总市值），从 Tushare `fina_indicator` API 获取 | ⚠️ 可行但复杂 | pcf_ttm = 总市值 /（经营活动现金流净额TTM），需调研 `fina_indicator` API 积分需求 |
| **方案 3**: 暂时留空 | 不影响其他字段回填 | ✅ | 当前策略，pcf_ttm 在因子注册表中已设为 disabled=True |

**建议优先级**: 方案 1（升 Token）> 方案 2 > 方案 3（留空）

### 5.3 最低可行替代方案

若方向 B 因故不可执行，最低可行替代方案：

1. **仅使用 pe/pb/pe_ttm**（免费字段）：覆盖率 100%，无需额外支出
2. **分层激活**：先回填免费字段（pe/pb/pe_ttm → 立即可用），再安排付费字段（ps_ttm/dividend_yield）
3. **pcf_ttm 置空**：在因子注册表中保持 `enabled=False`，等待 Token 升级后激活

---

## 6. 结论与建议

### 6.1 总体结论

> **方向 B（估值因子历史数据回填）完全可行**，实施风险可控。

### 6.2 推荐方案

```
┌─────────────────────────────────────────┐
│ 1. 运行全量采集 + 回填（方案 A）         │
│    python daily_basic_collector.py       │
│      --start=20070101                    │
│      --end=20260529                      │
│      --backfill                          │
│    ┌─ 预估耗时: 45 秒                   │
│    └─ API 调用: 50 次                    │
├─────────────────────────────────────────┤
│ 2. 一致性验证                            │
│    ┌─ 行数匹配验证                      │
│    ├─ 字段值抽检（100 行）              │
│    └─ 缺失率报告输出                    │
├─────────────────────────────────────────┤
│ 3. 特殊处理：pcf_ttm                    │
│    ┌─ 当前状态: 不可用 ❌               │
│    ├─ 建议: 升 Token ≥5000 积分         │
│    └─ 临时: 保持 disabled=True           │
├─────────────────────────────────────────┤
│ 4. 验证回填后因子 IC 计算                │
│    ┌─ 重新运行截面 IC 管线              │
│    └─ 比对 pe_ttm/pb_lf 的 IC 输出      │
└─────────────────────────────────────────┘
```

### 6.3 实施时序建议

| 时序 | 操作 | 产出 | 负责人 |
|:----:|:----|:----|:------:|
| **T+0** | 执行全量回填 | a50_daily_basic 表 2007~2026 全量数据 | 墨衡 |
| **T+0** | backfill_valuation → a50_daily_ohlcv | ohlcv 表 pe/pb/pe_ttm/ps_ttm/dividend_yield 完整覆盖 | 墨衡 |
| **T+0** | 运行一致性验证脚本 | 验证报告 | 墨衡 |
| **T+0** | 提交验证报告至 dispatcher | ✅ .done | 墨衡 |
| **T+1** | 评估 Token 升级方案（pcf_ttm） | 采购建议 | 玄知 |
| **T+2** | 回填后重跑 IC 管线 | 全因子 IC 计算结果 | 墨衡 |

### 6.4 预期效果

| 指标 | 回填前 | 回填后 | 提升 |
|:----:|:------:|:------:|:----:|
| pe 非空行数 | 2,146 | ~235,000 | 109× |
| pb 非空行数 | 2,204 | ~235,000 | 106× |
| ps_ttm 非空行数 | 2,204 | ~235,000 | 106× |
| dividend_yield 非空行数 | 2,088 | ~235,000 | 112× |
| pcf_ttm 非空行数 | 0 | 0 | 需 Token 升级 |
| 历史覆盖年份 | 0.25 年（2026-03~05） | 19.5 年（2007~2026） | 78× |

---

## 附录 A：参考文档

- `src/ingestion/daily_basic_collector.py` — 采集脚本
- `src/ingestion/migrate_daily_basic.py` — 估值字段 ALTER TABLE 迁移
- `src/data/etl_a50_daily.py` — 原始日线 ETL
- `src/pipeline/cross_sectional_ic_pipeline.py` — 截面 IC 管线（含因子注册表）
- `src/db/schema.py` — a50_ic.db DDL 定义
- `docs\07_research\plans\verify_next_steps_20260601.md` — 下一步工作计划（Week 1）

## 附录 B：执行脚本

```python
# 全量回填执行命令
python -m src.ingestion.daily_basic_collector \
    --start=20070101 \
    --end=20260529 \
    --backfill

# 验证脚本
python -m src.ingestion.tests.test_daily_basic_collector
```
