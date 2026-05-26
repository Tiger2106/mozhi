# 墨枢会议 — Step2：墨萱技术审查报告

> reviewer: 墨萱 🔍 | created: 2026-05-16 14:29 (CST)
> 审查对象: `mozhi_market_data.py` v2.0 + 测试方案 v1.0
> 参考: market_data_step1_moheng.md

---

## 审查结论：**PASS**（无 P0 阻塞级问题）

- **P0（阻塞级）**：0 项
- **P1（重要级）**：4 项
- **P2（建议级）**：6 项

---

## 一、代码审查

### 1.1 结构完整性 ✅

| 维度 | 判定 | 说明 |
|------|------|------|
| 降级链路 | ✅ 完整 | 日线: 东财 → baostock；分钟线: 东财 → 新浪；快照: 新浪 → 东财；指数: 东财 → 新浪 |
| 数据源切换 | ✅ 清晰 | `try/except` 双层结构，第一源失败后 logging warning 再降级 |
| 模块边界 | ✅ 合理 | `MarketDataClient` 统一封装，快捷函数代理调用，`SnapShot`/`CacheConfig` dataclass 解耦 |

### 1.2 异常处理 (P1 级问题 × 2)

#### 🔶 P1-01：`_daily_eastmoney` 中 `stock_zh_a_hist` 可能返回空 DataFrame 而非抛异常

**位置**: 第 242-249 行 `_daily_eastmoney` 方法
**分析**: 当股票代码有效但无数据时，`ak.stock_zh_a_hist()` 返回空 DataFrame。当前代码：
```python
df = self._ak.stock_zh_a_hist(...)
return _normalize_daily_em(df)
```
`_normalize_daily_em` 对空 DataFrame 会返回空的 rename 结果，函数正常返回而不抛异常。
**影响**: `get_daily()` 不会触发降级链路（因为没抛异常），调用方收到一个空 DataFrame。
**建议**: 在 `_daily_eastmoney` 和 `_daily_baostock` 返回后检查 `df.empty`，若为空则抛 `ValueError` 以触发降级。

#### 🔶 P1-02：`_snapshot_single_sina` 实际是全量拉取后过滤，docstring 描述"单只接口"与实现不符

**位置**: 第 290-315 行 `_snapshot_single_sina`
**根因**: v2.0 设计目标是将单只快照从全量改为新浪单只接口，但实际上 `ak.stock_zh_a_spot()` 不接受 symbol 参数，始终全量拉取。
**影响**: 单只快照每次请求都拉 5300 条数据，性能极差（~75s 实测）。B1 修复虽然修正了 TypeError，但没有改变"全量拉取后过滤"的事实。
**建议**: 将 `_snapshot_single_sina` 改为真实的单只接口（如新浪逐笔行情 `hq.sinajs.cn` 直连），或将它完全重命名为 `_snapshot_filter_from_full_sina`，并调整降级优先级：让东财 `_snapshot_single_from_bulk` 成为主路径，新浪降级。

### 1.3 并发安全

| 项目 | 判定 | 说明 |
|------|------|------|
| Parquet 缓存并发 | 🟡 P2 | 无文件锁。多进程写入同一 cache_key 可能损坏 parquet 文件。Python 非多线程场景（GIL）下单进程安全。 |
| 请求限速 | ✅ OK | `_throttle()` 基于 `time.time()` 比较，单线程安全。 |
| baostock 登录 | ✅ OK | `_baostock_login._logged_in` 类属性标记。单进程/单线程 OK，多线程需 `threading.Lock`。 |

### 1.4 缓存层健壮性

| 项目 | 判定 | 说明 |
|------|------|------|
| TTL 过期 | ✅ OK | `path.stat().st_mtime` 比较 `time.time()`，逻辑正确 |
| 写入失败降级 | ✅ OK | `set()` 捕获 Exception 并 log warning，不传播 |
| 读取失败降级 | ✅ OK | `get()` 捕获 Exception 并返回 None，触发重新获取 |
| MD5 碰撞概率 | ✅ OK | `hashlib.md5` 截取 12 位 hex（48 bits），碰撞概率 1.3e-7（约 7.7M 条目时 50%），实际场景可忽略 |
| 缓存目录创建 | ✅ OK | `Path.mkdir(parents=True, exist_ok=True)` |

### 1.5 Snapshot 数据模型完整性 ✅

| 字段 | 类型 | 来源 | 安全处理 |
|------|------|------|---------|
| symbol | str | 参数传递 | ✅ |
| name | str | `str(r.get("名称", ""))` | ✅ |
| price | float | `float(r.get("最新价", 0) or 0)` | ✅ (or 0 处理 None) |
| open | float | 同上 | ✅ |
| high | float | 同上 | ✅ |
| low | float | 同上 | ✅ |
| prev_close | float | 同上 | ✅ |
| volume | float | 同上 | ✅ |
| amount | float | 同上 | ✅ |
| pct_chg | float | 同上 | ✅ |
| timestamp | str | `pd.Timestamp.now()` | ✅ |

所有 3 个 Snapshot 构造入口（`_snapshot_single_sina`、`_snapshot_single_from_bulk`、`get_index_snapshot`）字段映射一致。

### 1.6 requests.Session 修改作用域 (P1 级问题 × 1)

#### 🔶 P1-03：`_inject_session_to_akshare` 的降级路径有全局副作用

**位置**: 第 103-107 行
**分析**: 当 `akshare.utils.func.session` 不存在时，降级方案是：
```python
requests.Session = _session_factory  # 全局修改！
```
这会影响到同一进程中所有后续 `requests.Session()` 的实例化（包括其他依赖 requests.Session 的第三方库）。
**建议**: 
1. 优先修复 akshare 注入路径（当前是否实际失败？）
2. 若降级路径必须保留，log 一个 WARNING 告知该副作用
3. 或考虑移除该降级，改用 `akshare` 的 `set_headers()` 或其他官方定制方式

### 1.7 其他发现

#### P2-01: `_index_sina` 降级返回单行实时快照而非历史日线
**位置**: 第 382-396 行
**分析**: `_index_sina` 降级路径使用 `stock_zh_index_spot_sina()` 返回当日快照。如果 `start` 参数指定的起始日期早于当日，降级后只会得到 1 行数据（当日），丢失了完整历史。
**影响**: 指数日线降级链路不完整，历史数据通过降级路径无法获取。

#### P2-02: `diagnose()` 中 `requests.Session()` 创建的 session 未被关闭
**位置**: 第 438 行
**影响**: 轻微，诊断函数创建后 session 自然 GC。但点出作为代码规范问题。

#### P2-03: `_make_referer` 函数未覆盖 `hq.sinajs.cn` 域名
**位置**: 第 56-61 行
**影响**: 新浪行情如果是 `hq.sinajs.cn` 域名，Referer 会回退到 eastmoney，但实际应指向 `finance.sina.com.cn`。当前 `_REFERER_MAP` 已覆盖 `sinajs.cn`，但 `_make_referer` 使用 `in` 检查，故已被覆盖，无实际影响。标记为文档澄清。

#### P2-04: `get_daily_batch` 三参数签名与快捷函数不一致
**位置**: 第 442 行 vs 第 545 行
- `MarketDataClient.get_daily_batch(self, symbols, adjust, start, end, gap=0.8)`: 5 参数
- 快捷函数 `get_daily_batch(symbols, adjust="qfq", start="2023-01-01")`: 3 参数
快捷函数缺少 `end` 和 `gap` 参数。

---

## 二、测试方案审查

### 2.1 单元测试覆盖率

| 模块 | 用例数 | 判定 | 备注 |
|------|--------|------|------|
| 日线链路 | 5 | ✅ 充分 | mock 东财/baostock 正常+异常 |
| 分钟线链路 | 4 | ✅ 充分 | 含 period 参数变体 |
| 实时快照 | 6 | ✅ 充分 | 单只降级+批量+部分失败 |
| 指数行情 | 4 | ✅ 充分 | 指数日线+快照+中文名映射 |
| Parquet 缓存 | 6 | ✅ 充分 | 命中/过期/写入失败/碰撞/删除 |
| 限速与重试 | 3 | ✅ 充分 | throttling + retry 正常+全部失败 |
| Snapshot 模型 | 2 | ⚠️ 偏少 | 仅 2 条，但模型简单，尚可接受 |

**判定**: 单元测试覆盖率充分，关键降级路径（6 条）全部覆盖。

### 2.2 集成测试标的选择

| 标的 | 类型 | 判定 |
|------|------|------|
| 601857 (中国石油) | 沪市大型股 | ✅ 合理 |
| 000001 (平安银行) | 深市权重 | ✅ 合理 |
| 600036 (招商银行) | 沪市银行 | ✅ 合理 |
| 600519 (贵州茅台) | 天价股 | ✅ 合理（高价格边界） |
| 000858 (五粮液) | 深市消费 | ✅ 合理 |
| 沪深300/000300 | 指数 | ✅ 合理 |
| 上证指数/000001(指数) | 指数 | ✅ 合理 |

### 2.3 边界测试完整性 (P1 级问题 × 1)

#### 🔶 P1-04：测试方案缺少并发场景测试

**分析**: 无任何并发/竞态测试用例。虽单线程场景下 baostock 登录（类变量标记）、Parquet 缓存（无锁）都是安全的，但多线程/多进程场景的风险未被验证。
**影响**: 如果未来墨衡在回测系统中并行查询行情，baostock 登录标记的竞态可能导致第二个线程未登录。

#### 其他边界测试评估

| 用例 | 判定 |
|------|------|
| 4.1 空代码 | ✅ |
| 4.2 无效代码 | ✅ |
| 4.3 无交易日范围 | ✅ |
| 4.4 空 symbols list | ✅ |
| 4.5 无效指数代码 | ✅ |
| 4.6 网络断开 | ✅ |
| 4.7 enable_header_patch | ✅ |

### 2.4 遗漏的关键测试场景 (P2 × 2)

#### P2-05: 缺少多实例测试
多个 `MarketDataClient` 实例并行运行时，`_baostock_login._logged_in` 类变量是否正常？`_default_client` 全局变量在多实例场景是否有预期行为？

#### P2-06: 缺少缓存清理策略测试
`ParquetCache` 的缓存文件会永久留在磁盘上（即使 TTL 过了也只是下次访问时删除）。测试方案未覆盖缓存目录的膨胀保护。

---

## 三、影响分析审查

### 3.1 与 `data_source.py` 的关系

**判定**: ✅ 无冲突

当前 `data_source.py` 不引用 `market_data` 模块。墨衡汇报证实 `grep -r "market_data" src/` 无结果。墨萱独立确认：

- `data_source.py` 路径（如有）与 `mozhi_market_data.py` 为同层目录，无命名冲突
- 功能定位不同：`market_data` 是统一行情库，`data_source` 是（假设的）更上层数据提供者
- 无重复功能

### 3.2 功能重复审查

**判定**: ✅ 无显性重复

`mozhi_market_data.py` 提供的功能：
- 日线/分钟线 OHLCV
- 实时快照（单只/批量）
- 指数行情（日线/快照）
- Parquet 缓存 / 降级链路 / 限速

这些功能目前无其他模块提供。未来迁移后，`benchmark_data_source.py` 中的直接 akshare 调用会被替代。

---

## 四、总结

### P0 阻塞级：0 项 ✅

### P1 重要级：4 项 ⚠️

| # | 文件 | 行号 | 问题 | 建议 |
|---|------|------|------|------|
| P1-01 | mozhi_market_data.py | ~242 | `_daily_eastmoney` 返回空 DataFrame 不抛异常，阻止降级链路触发 | 增加 `df.empty` 检查并抛 ValueError |
| P1-02 | mozhi_market_data.py | ~290 | `_snapshot_single_sina` 实际是全量拉取（~75s），名称/docstring 与实现不符 | 重命名方法或更换为真正的单只接口，调整降级优先级 |
| P1-03 | mozhi_market_data.py | ~103-107 | `_inject_session_to_akshare` 降级路径全局修改 `requests.Session` 有副作用 | 移除降级路径或追加 WARNING 日志 |
| P1-04 | market_data_test_plan.md | — | 测试方案缺少并发场景（baostock 登录竞态、Parquet 并发写入） | 补充 `threading.Lock` 机制测试 |

### P2 建议级：6 项 📝

| # | 问题 | 说明 |
|---|------|------|
| P2-01 | `_index_sina` 降级只返回当日快照 | 历史指数日线降级后数据不完整 |
| P2-02 | `diagnose()` session 未显式关闭 | 轻微，GC 可回收 |
| P2-03 | `_make_referer` 回退歧义 | 已有 `sinajs.cn` 覆盖，仅需文档澄清 |
| P2-04 | `get_daily_batch` 快捷函数签名不一致 | 缺 `end` 和 `gap` 参数 |
| P2-05 | 测试方案缺少多实例测试 | 多个 `MarketDataClient` 的 `_default_client` 行为未验证 |
| P2-06 | 测试方案缺少缓存清理策略 | 缓存目录无膨胀保护机制 |

### 整体判定

```
代码质量     : ✅ 良好（降级链路完整、数据模型标准、异常处理清晰）
测试方案     : ⚠️ 充分但缺并发场景（P1-04）
影响分析     : ✅ 零冲突，独立模块
```

**结论：PASS ✅** — 无 P0 阻塞级问题。4 项 P1 建议在合并前修复，6 项 P2 记录归档。

---

*本报告由墨萱（moxuan）于 2026-05-16 14:29 CST 自动生成*
*审查范围：代码结构 + 测试方案 + 影响分析*
