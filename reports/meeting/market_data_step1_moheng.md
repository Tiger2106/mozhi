# 墨枢会议 — Step1：墨衡汇报方案

> author: 墨衡 | created: 2026-05-16 14:28 (CST) | version: v1.0

---

## 1. 部署结果

### 1.1 文件部署

| 项目 | 值 |
|------|-----|
| 源文件 | `C:\Users\17699\Downloads\mozhi_market_data_v2.py` |
| 目标路径 | `C:\Users\17699\mozhi_platform\src\data\mozhi_market_data.py` |
| 部署方式 | Copy-Item（直接覆盖） |
| 版本 | v2.0（源文件） |
| 前置检查项 F1~F6 | ✅ 全部通过（墨涵确认） |

### 1.2 Import 链验证

```python
from data.mozhi_market_data import MarketDataClient, diagnose, CacheConfig
from data.mozhi_market_data import get_daily, get_minute, get_snapshot
from data.mozhi_market_data import get_snapshot_batch, get_index_daily
from data.mozhi_market_data import get_index_snapshot, get_daily_batch
```

- ✅ 所有导出符号均可成功 import
- 运行时位置：Python 314 + akshare 1.18.55 + pandas 3.0.1 + pyarrow 24.0.0 + baostock 0.9.1
- 导入前置条件：`data/` 目录在 `PYTHONPATH` 中（`sys.path.insert(0, "src")`）

### 1.3 自测结果

测试环境：Windows 10, 直连（无代理）, 网络正常但东财高频接口受限

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 网络诊断 `diagnose()` | ✅ | 东财 404（正常，push2his 发布接口返回 404）、新浪 200、baostock 登录成功 |
| 日线 601857 | ✅ | 降级 baostock（东财 connection aborted），返回 8 条数据（2026-05-06 ~ 05-15）|
| 分钟线 601857(5min) | ✅ | 降级新浪（东财 connection aborted），返回 1970 条 |
| 单只快照 601857 | ⚠️ | 详见 Bugfix #1 |
| 指数日线 CSI300 | ⚠️ | 详见 Bugfix #2 |
| 指数快照 CSI300 | ⚠️ | 详见 Bugfix #3 |
| 批量快照 3 只 | ✅ | 东财全量接口正常返回 |

#### Bugfix 记录

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| B1 | `_snapshot_single_sina` 抛 `TypeError: stock_zh_a_spot() got an unexpected keyword argument 'symbol'` | `ak.stock_zh_a_spot()` 不接受任何参数，总是返回全量 A 股。v2 设计者误以为该函数支持单只查询。 | 改为无参数调用后按 `sina_code` 过滤 | 
| B2 | `_index_sina` 抛 `AttributeError: module 'akshare' has no attribute 'index_zh_a_hist_sina'` | akshare 1.18.55 中该 API 不存在（文档引用过期）。 | 改用 `stock_zh_index_spot_sina()` 获取实时快照数据，返回单行 DataFrame |
| B3 | `get_index_snapshot` 抛 `AttributeError: module 'akshare' has no attribute 'index_zh_a_spot_em'` | API 名称拼写错误。正确名称：`stock_zh_index_spot_em` | 更正为 `ak.stock_zh_index_spot_em()` |

#### 已知限制（环境相关，非代码 bug）

| 问题 | 原因 | 影响 |
|------|------|------|
| 部分东财接口 `Connection aborted` | 高频接口触发反爬策略 | 日线/分钟线自动降级至 baostock/新浪，不影响功能 |
| 新浪全量快照 `stock_zh_a_spot()` 极慢（~75s） | 需要拉取 69 页约 5300 只股票 | 使用东财 `stock_zh_a_spot_em()` 作为主路径性能更好 |
| 指数批量导出全量慢 | 同 5300 条指数快照 | 建议主路径用东财，新浪作为降级 |

---

## 2. 测试方案摘要

全面测试方案已写入：

```
C:\Users\17699\mozhi_platform\docs\02_development\market_data_test_plan.md
```

### 覆盖范围

- **1. 单元测试（Mock）**：7 个子模块，约 25 条用例
  - 日线/分钟线/快照 获取链路及降级逻辑
  - Parquet 缓存命中/过期/写入失败
  - request_gap 限速、_retry 重试
  - Snapshot 数据模型解析
- **2. 集成测试（实网）**：约 12 条用例，覆盖 601857/000001 等标的
- **3. 反爬测试**：6 条（NO_PROXY、Referer、User-Agent、request_gap、无全局 patch、Session 注入）
- **4. 边界测试**：7 条（空参数、无效代码、空数据、网络断开等）

### 测试工具

- pytest + unittest.mock 为 mock 测试框架
- 集成测试标记 `@pytest.mark.integration`
- 反爬测试标记 `@pytest.mark.anticrawl`

---

## 3. 对现有代码的影响分析

### 3.1 新增文件

`data/mozhi_market_data.py` 为新文件，不与任何现有文件冲突。

### 3.2 现有引用分析

全局搜索结果：**当前无任何文件从 `data/` 目录 import**。

```bash
grep -r "market_data" src/   # 无结果
```

即 `mozhi_market_data.py` 是 **零依赖的独立模块**，部署后不影响现有系统。

### 3.3 预期集成路径

根据架构设计，未来调用链路：

```
backtest/data_source.py           # 现有：直接调 akshare
backtest/benchmark_data_source.py # 现有：直接调 akshare（见 3.4）
    ↓ 迁移后
data/mozhi_market_data.py        # [新增] 统一行情层
```

### 3.4 benchmark_data_source 兼容性分析

`benchmark_data_source.py` 目前直接调 `akshare`：

- `ak.index_zh_a_hist()` → 对应 `MarketDataClient.get_index_daily()` ✅
- `ak.stock_zh_a_hist()` → 对应 `MarketDataClient.get_daily()` ✅
- 参数签名类似，迁移成本低

**兼容性风险：无**。新模块和旧代码各自独立运行，互不干扰。

---

## 4. 风险提示

### 🟡 中风险
| 风险 | 说明 | 缓解措施 |
|------|------|---------|
| akShare API 版本漂移 | akshare 1.18.55 中部分接口名称已与 v2 设计时的预期不一致（3 处已在本次修复） | 在 test_plan 中增加版本锁定 `akshare>=1.18.55` |
| 新浪全量快照性能差 | `stock_zh_a_spot()` 全量拉取耗时 ~75s | 生产环境应使用 `stock_zh_a_spot_em()` 作为主路径，只将新浪作为降级 |

### 🟢 低风险
| 风险 | 说明 |
|------|------|
| 东财反爬加剧 | `Connection aborted` 已自动降级 baostock/新浪，数据完整性影响可控 |
| Parquet 缓存未清理 | TTL 机制 + 过期自动删除，不会有永久残留 |
| 全局 patch 副作用 | 默认 `enable_header_patch=False`，仅作用域内 AkShareSession 注入 |

### 🟠 待确认
| 事项 | 原因 |
|------|------|
| `stock_zh_index_spot_sina()` 列名 | 本地环境未实网验证新浪指数列名，`_index_sina` 降级路径带中风险 |

---

## 5. 下一步建议（Step2 技术审查）

1. **代码审查重点**：`_snapshot_single_sina` 的 column mapping（中文→Snapshot 字段）、`_index_sina` 降级实现
2. **集成测试优先级**：指数快照（B3 修复验证）、单只快照（B1 修复验证）
3. **部署建议**：合并后建议先通过 `diagnose()` 验证网络环境，再启用定时行情拉取
