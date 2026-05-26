# 行情数据基础库测试方案

> author: 墨衡 | created: 2026-05-16 | version: v1.0
> 关联：`mozhi_market_data.py`（v2.0）

---

## 1. 单元测试（Mock 模式）

### 1.1 日线获取链路

| # | 测试用例 | 预期行为 | 备注 |
|---|---------|---------|------|
| 1.1.1 | `_daily_eastmoney` 返回正常 DataFrame（东财列名中文→英文标准化） | `get_daily` 返回 `index=date(str)`，6 标准列 | mock `ak.stock_zh_a_hist` 返回值 |
| 1.1.2 | `_daily_eastmoney` 抛异常（网络/数据异常） | 自动降级 `_daily_baostock`，返回 baostock 数据 | mock 东财异常 + baostock 正常 |
| 1.1.3 | `_daily_eastmoney` 和 `_daily_baostock` 都失败 | `get_daily` 抛异常，不静默吞错 | 验证异常传播 |
| 1.1.4 | adjust 参数传递：qfq/hfq/空 '' 各测一次 | 东财 `adjust=`、baostock `adjustflag=` 正确映射 | |
| 1.1.5 | start/end 为空字符串时取默认值 | `end` 默认今天的日期 | |

### 1.2 分钟线获取链路

| # | 测试用例 | 预期行为 | 备注 |
|---|---------|---------|------|
| 1.2.1 | `_minute_eastmoney` 正常返回 | `get_minute` 返回 `index=datetime(Timestamp)` | mock `ak.stock_zh_a_hist_min_em` |
| 1.2.2 | 东财分钟线失败（抛异常） | 降级 `_minute_sina` | mock 东财异常 + 新浪正常 |
| 1.2.3 | period 参数：1/5/15/30/60 | 正确传递给接口 | |
| 1.2.4 | 新浪分钟线返回的时间列名为 "day" | 正确映射 | `_normalize_minute` 验证 |

### 1.3 实时快照链路

| # | 测试用例 | 预期行为 | 备注 |
|---|---------|---------|------|
| 1.3.1 | `_snapshot_single_sina` 正常返回（新浪全量→过滤） | 返回 Snapshot，price/volume 等字段正确解析 | mock `ak.stock_zh_a_spot` |
| 1.3.2 | 新浪全量快照失败（抛异常） | 降级 `_snapshot_single_from_bulk`（东财） | |
| 1.3.3 | 新浪+东财都失败 | `get_snapshot` 抛异常 | |
| 1.3.4 | `get_snapshot_batch` 东财全量正常 | 返回 dict{symbol: Snapshot} | mock `ak.stock_zh_a_spot_em` |
| 1.3.5 | 东财全量失败→逐只降级 | 循环调 `get_snapshot`，gap 生效 | |
| 1.3.6 | 批量快照中部分标的未找到 | 只返回找到的，记 warning | |

### 1.4 指数行情

| # | 测试用例 | 预期行为 | 备注 |
|---|---------|---------|------|
| 1.4.1 | `get_index_daily` 东财正常 | 返回标准 OHLCV DataFrame | mock `ak.index_zh_a_hist` |
| 1.4.2 | 东财指数失败→降级新浪 | 调 `_index_sina` → `stock_zh_index_spot_sina` | |
| 1.4.3 | `get_index_snapshot` 东财正常 | 返回 Snapshot | mock `ak.stock_zh_index_spot_em` |
| 1.4.4 | INDEX_MAP 中文名→代码映射 | "沪深300"→"000300"，"上证指数"→"000001" | |

### 1.5 Parquet 缓存层

| # | 测试用例 | 预期行为 | 备注 |
|---|---------|---------|------|
| 1.5.1 | 缓存命中（文件存在且未超期） | 直接返回缓存的 DataFrame，不调上游接口 | mock file age |
| 1.5.2 | 缓存过期（文件存在但超 TTL） | 删除旧文件，重新获取 | mock time.time |
| 1.5.3 | 缓存目录不存在 | `mkdir(parents=True)` 自动创建 | |
| 1.5.4 | 缓存写入失败（权限/磁盘满） | 写 failure 日志，不中断调用 | |
| 1.5.5 | 缓存 key 碰撞验证 | 不同参数生成不同 hash | |
| 1.5.6 | `invalidate` 删除正确文件 | 确认文件被删除 | |

### 1.6 限速与重试

| # | 测试用例 | 预期行为 | 备注 |
|---|---------|---------|------|
| 1.6.1 | `request_gap=0.5`，连续 2 次调用间隔 < 0.5s | 第 2 次被 throttled，延迟到间隔达标 | mock time.time |
| 1.6.2 | `retry_times=2`，首次失败 | 自动重试 1 次 + retry_sleep 间隔 | mock exception |
| 1.6.3 | 重试全部失败 | 抛出最后一次异常 | |

### 1.7 Snapshot 数据模型

| # | 测试用例 | 预期行为 | 备注 |
|---|---------|---------|------|
| 1.7.1 | `_row_to_snapshot` 正常行→Snapshot | 10 个字段全部正确映射 | 东财列名 |
| 1.7.2 | 字段缺失/为 None | `float(r.get(col, 0) or 0)` 安全 | |

---

## 2. 集成测试（实网，选代表性标的）

### 2.1 日线

| # | 测试用例 | 预期 | 备注 |
|---|---------|------|------|
| 2.1.1 | 601857 日线 qfq（2026-01 ~ 今） | DataFrame 返回 > 50 条，价格合理 | |
| 2.1.2 | 601857 日线 hfq | 收盘价 vs qfq 不同 | |
| 2.1.3 | 601857 日线 不复权（''） | 有返回 | |
| 2.1.4 | 601857 分钟线 1/5/15/30/60 | 每个周期 > 100 条 | |

### 2.2 指数

| # | 测试用例 | 预期 |
|---|---------|------|
| 2.2.1 | 000300 指数日线（东财 source） | 返回 OHLCV，数量合理 |
| 2.2.2 | 上证指数（中文名）| INDEX_MAP 正确映射 |
| 2.2.3 | 000001 指数快照 | 返回 Snapshot，price > 3000 |

### 2.3 快照

| # | 测试用例 | 预期 |
|---|---------|------|
| 2.3.1 | 601857 单只快照 | name="中国石油"，price > 0 |
| 2.3.2 | 批量快照 [601857, 000001, 600036, 600519, 000858] | 5/5 返回 |
| 2.3.3 | 批量日线 [601857, 000001] | 返回 2 个 DataFrame |

### 2.4 诊断

| # | 测试用例 | 预期 |
|---|---------|------|
| 2.4.1 | `diagnose()` | 返回完整报告，东财/新浪/baostock 可达 |

---

## 3. 反爬测试

| # | 测试用例 | 预期 | 备注 |
|---|---------|------|------|
| 3.1 | NO_PROXY 域名检查 | `os.environ["NO_PROXY"]` 包含 eastmoney / sina 关键域名 | 模块加载时设置 |
| 3.2 | Referer 自动切换 | eastmoney 请求→Referer=eastmoney; sina→sina | 检查 `_make_referer` |
| 3.3 | User-Agent 检查 | 每个 header injection 都有 Chrome UA | |
| 3.4 | request_gap 合规 | 实网连续 10 次请求，时间戳差均 >= gap | |
| 3.5 | 无全局 patch 确认 | `requests.get._mozhi_patched` 为 False（默认） | |
| 3.6 | AkShareSession 注入确认 | `akshare.utils.func.session` 是 AkShareSession 实例 | |

---

## 4. 边界测试

| # | 测试用例 | 预期 |
|---|---------|------|
| 4.1 | 空股票代码 `get_daily("")` | 东财/baostock 返回异常→传播 |
| 4.2 | 无效股票代码 `get_daily("000000")` | 降级后仍无数据→最终异常 |
| 4.3 | 无交易日范围 `get_daily("601857", start="2099-01-01")` | 返回空 DataFrame |
| 4.4 | 空 symbols list → `get_snapshot_batch([])` | 返回空 dict |
| 4.5 | 无效指数代码 `get_index_daily("999999")` | 东财无数据→降级→最终异常 |
| 4.6 | 网络断开 | 所有接口降级尝试后抛异常 |
| 4.7 | `enable_header_patch=True` | 全局 patch 生效，warning 日志 |

---

## 5. 测试执行建议

### Mock 执行
```bash
# 使用 pytest + unittest.mock
cd C:\Users\17699\mozhi_platform
pytest src/data/tests/ -v -m "not integration"
```

### 集成执行（需网络）
```bash
pytest src/data/tests/ -v -m integration --timeout=120
```

### 反爬检查（实网请求）
```bash
pytest src/data/tests/ -v -m "anticrawl"
```
