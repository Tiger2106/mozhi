# S001 明日实盘重跑 - 预检记录
**作者**: 墨衡
**创建时间**: 2026-05-25T11:28+08:00
**状态**: 预检完成

---

## 1. 环境预检结果

| 检查项 | 状态 | 详情 |
|:-------|:-----|:------|
| akshare | ✅ v1.18.55 | 已安装，可 import; 安装路径: `AppData/Roaming/Python/Python314/site-packages/akshare` |
| Windows代理 | ⚠️ 已配置 | `HKCU\...\ProxyServer=127.0.0.1:10809`, `ProxyEnable=1` |
| 代理可通过 httpbin.org | ✅ | 返回 public IP: 67.216.192.6 |
| 代理 → push2his.eastmoney.com | ❌ ProxyError | "Unable to connect to proxy" |
| 直连(DNS解析) | ⚠️ 间歇性 | 首次直连成功(200), 后续频被rate limit(RemoteDisconnected) |
| Python版本 | Python 3.14.3 | Windows 10 x64 |

## 2. 代理问题解决方案

**解决方案**：修改 `_fetch_from_akshare()` 函数，绕过系统代理直连 eastmoney

```python
# 方案A：使用 custom session（推荐，最可靠）
def _fetch_from_akshare(symbol, start, end):
    import requests as _requests_module
    # 临时接管 ak 内部 requests.get
    _original_get = _requests_module.get
    def _patched_get(url, **kwargs):
        session = _requests_module.Session()
        session.trust_env = False  # 绕过 Windows 系统代理
        kwargs.setdefault('timeout', 15)
        kwargs.setdefault('headers', {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/',
        })
        return session.get(url, **kwargs)
    _requests_module.get = _patched_get
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period='daily', start_date=start, end_date=end, adjust='qfq')
        return df
    finally:
        _requests_module.get = _original_get  # 恢复
```

**注意**: 直连 eastmoney.com 有 rate limit。建议：
- 一次性请求 12 个月全部数据（不要分月请求）
- 失败后等待 15-30 秒重试
- 最大重试 3 次

## 3. 模型根本问题

当前 MC 模拟所有月份输出 FLAT：
- 方向准确率 8.3% (1/12) vs 目标≥65%
- p50/中位数价格几乎不偏离起始价 (约 10.63)
- `determine_dir` 阈值 >2% 被静态 p50 窗口淹没

修复方向（等 Dispatcher 讨论决定）：
- **Base case**: 使用当前月数据（非静态全窗口）计算 p50
- **Bull/Bear**: 当前使用 fixed 0.5/-0.5 太机械，可改为 trend * std_dev 动态偏移
- **Alternative**: `determine_dir` 的 2% 阈值对当前低波动环境过严

## 4. 数据覆盖范围

回测窗口：12个月滚动，1个月不重叠
```
Window 1: 2025-05 → 2025-06 (训练 2025-05, 预测 2025-06)
Window 2: 2025-06 → 2025-07
...
Window 12: 2026-03 → 2026-04 (训练 2026-03, 预测 2026-04)
```

所需全部数据的 start_date: 2025-05-01, end_date: 2026-04-30

## 5. 明日操作备忘

1. 修改 `backtest.py` 中 `_fetch_from_akshare` 的代理绕过
2. 运行完整回测（~5分钟）
3. 检查输出指标是否达到目标
4. 如模型方向准确率不足，记录问题等 Dispatcher 决策
