<!--
author: 墨衡 (moheng)
created_time: 2026-05-27T17:31+08:00
task_id: BT-004
version: v1.0
status: FINAL
-->

# BacktestData 数据合约（v1.0）

> **依据**: 回测引擎编码原则 BT-004（数据合约固定）
> **适用范围**: 回测引擎数据层（`data/`）→ 计算层（`calc/`）→ 模拟层（`sim/`）之间的数据传递
> **版本**: v1.0
> **关联文档**: `docs/11_principles/backtest_coding_principles.md`（§BT-004）

---

## 一、数据合约概述

### 1.1 目的

定义回测引擎核心数据结构 `BacktestData` 及其字段规范，确保：

1. **层间接口稳定**：数据层构建一次，计算层和模拟层直接消费，新增字段不引发连锁修改
2. **类型安全**：所有字段使用固定的 `np.ndarray`/`List[str]` 类型，杜绝松散字典传参
3. **不可变性**：`BacktestData` 实例构建后不可修改，消除无意的副作用数据污染
4. **时间对齐**：所有数据矩阵的 time_axis=0 固定为交易日维度，与 BT-006 契约一致

### 1.2 适用范围

| 层 | 使用方式 | 备注 |
|:---|:---------|:-----|
| 数据层（Data Layer） | **构建** `BacktestData` 实例 | `data/loader.py`, `data/backtest_data.py` |
| 计算层（Calc Layer） | **只读消费** | `calc/*.py` 函数签名第 1 个参数 |
| 模拟层（Sim Layer） | **只读消费** | `sim/*.py`, `runner.py` |
| 外部系统（EXT-004） | **构造兼容实例**接入回测 | 只需满足本合约，无须改动引擎 |

### 1.3 不得做的事

- ❌ `BacktestData` 实例不得被修改（`close`, `open` 等字段不可原地赋值）
- ❌ 计算层不得对 `BacktestData` 字段执行 `shift(-1)` 或任何"数据后移"操作（由 BT-006 契约取代）
- ❌ `BacktestData` 字段不得通过 `Dict[str, np.ndarray]` 替代（丧失类型安全）

---

## 二、字段定义表

### 2.1 核心价格/量字段

| 字段名 | 类型 | Shape | 单位 | 来源 | 约束条件 | 示例 |
|:-------|:-----|:------|:-----|:-----|:---------|:-----|
| `close` | `np.ndarray` | `(n_days, n_stocks)` | 元 | DB `stock_daily.close` / akshare | `float64`, NON_NEGATIVE | `[[7.22, 1520.0, ...], ...]` |
| `open` | `np.ndarray` | `(n_days, n_stocks)` | 元 | DB `stock_daily.open` / akshare | `float64`, NON_NEGATIVE | `[[7.12, 1510.0, ...], ...]` |
| `high` | `np.ndarray` | `(n_days, n_stocks)` | 元 | DB `stock_daily.high` / akshare | `float64`, NON_NEGATIVE | `[[7.35, 1530.0, ...], ...]` |
| `low` | `np.ndarray` | `(n_days, n_stocks)` | 元 | DB `stock_daily.low` / akshare | `float64`, NON_NEGATIVE | `[[7.08, 1490.0, ...], ...]` |
| `volume` | `np.ndarray` | `(n_days, n_stocks)` | 股 | DB `stock_daily.volume` / akshare | `float64`, NON_NEGATIVE | `[[158000000, 3500000, ...], ...]` |
| `amount` | `np.ndarray` | `(n_days, n_stocks)` | 元 | DB `stock_daily.amount` / akshare | `float64`, NON_NEGATIVE | `[[1.147e9, 5.32e8, ...], ...]` |
| `vwap` | `np.ndarray` | `(n_days, n_stocks)` | 元 | **计算生成**：`amount / volume` | `float64`, NON_NEGATIVE | `[[7.26, ...], ...]` |

> ⚠️ **单位约定**：`volume` 统一存储为**股**（非手），`amount` 统一存储为**元**（非千元）。

### 2.2 价格修正字段

| 字段名 | 类型 | Shape | 单位 | 来源 | 约束条件 | 示例 |
|:-------|:-----|:------|:-----|:-----|:---------|:-----|
| `pre_close` | `np.ndarray` | `(n_days, n_stocks)` | 元 | DB `stock_daily.pre_close` / akshare | `float64`, NON_NEGATIVE | `[[7.15, ...], ...]` |
| `adj_factor` | `np.ndarray` | `(n_days, n_stocks)` | — | **计算生成**：前复权因子（`close/close_raw`） | `float64`, [0.5, 2.0] | `[[1.0, 0.95, ...], ...]` |
| `change` | `np.ndarray` | `(n_days, n_stocks)` | 元 | DB `stock_daily.change` / akshare | `float64` | `[[0.07, ...], ...]` |
| `pct_chg` | `np.ndarray` | `(n_days, n_stocks)` | % | DB `stock_daily.pct_chg` / akshare | `float64` | `[[0.98, ...], ...]` |

### 2.3 约束/标记字段

| 字段名 | 类型 | Shape | 含义 | 来源 | 约束条件 |
|:-------|:-----|:------|:-----|:-----|:---------|
| `price_limit_mask` | `np.ndarray` | `(n_days, n_stocks, 2)` | `[:,:,0]`=下限（跌停价）<br>`[:,:,1]`=上限（涨停价） | **计算生成**：`pre_close * 0.9/1.1` | `bool`（不可交易时触发） |
| `suspend_mask` | `np.ndarray` | `(n_days, n_stocks)` | `True`=该标的发生停牌 | DB 推断（缺失交易日且 is_trading_day=True） | `bool` |
| `is_trading_day` | `np.ndarray` | `(n_days,)` | `True`=该日为交易日 | DB `trading_calendar.is_trading_day` | `bool` |
| `resume_day_mask` | `np.ndarray` | `(n_days, n_stocks)` | `True`=该标的发生停牌后复牌首日 | **计算生成**：`suspend_mask[di-1] AND NOT suspend_mask[di]` | `bool` |

### 2.4 索引字段

| 字段名 | 类型 | Shape | 含义 | 来源 | 示例 |
|:-------|:-----|:------|:-----|:-----|:-----|
| `trading_dates` | `List[str]` | `(n_days,)` | 交易日列表（YYYYMMDD），严格升序 | DB `trading_calendar.date` | `["20260522", "20260523", ...]` |
| `symbols` | `List[str]` | `(n_stocks,)` | 标的代码列表（带交易所后缀） | 回测配置 | `["601857.SH", "000001.SZ", ...]` |

### 2.5 衍生因子字段（可选，由计算层填充）

| 字段名 | 类型 | Shape | 含义 | 来源 |
|:-------|:-----|:------|:-----|:-----|
| `float_share` | `np.ndarray` | `(n_days, n_stocks)` | 流通股本（万股） | **计算生成**（FloatShareCache） |
| `turnover_rate` | `np.ndarray` | `(n_days, n_stocks)` | 换手率（%） | **计算生成** |
| `volume_ratio_20` | `np.ndarray` | `(n_days, n_stocks)` | 量比（N=20） | **计算生成** |
| `volume_ratio_60` | `np.ndarray` | `(n_days, n_stocks)` | 量比（N=60） | **计算生成** |

### 2.6 元信息字段

| 字段名 | 类型 | 含义 | 来源 |
|:-------|:-----|:-----|:-----|
| `meta` | `Dict[str, Any]` | 元信息字典（数据版本、种子、配置摘要等） | 构造时注入 |
| `data_fingerprint` | `str` | 数据版本指纹（SHA256 前 16 位 hex） | **计算生成**（§五） |

---

## 三、数据来源与加载流程

### 3.1 当前数据流总览

```
┌─────────────────────────────────────────────────────────────────┐
│ 外部数据源                                                      │
│  AkshareDataSource (akshare API ── 东方财富)                     │
│        ↓ fallback                                               │
│  新浪日线 API (stock_zh_a_daily)                                │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌────────────────────────┴────────────────────────────────────────┐
│ 缓存层                                                          │
│  Parquet 文件缓存 ── backtest_data_cache/{symbol}_{date}.parquet │
│  过期策略: TTL=24h                                               │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌────────────────────────┴────────────────────────────────────────┐
│ 本地数据库                                                      │
│  market_data.db                                                 │
│    ├── stock_daily        (code TEXT, date TEXT, OHLCV, amount)  │
│    ├── stock_minute       (分钟级数据)                           │
│    └── trading_calendar   (market TEXT, date TEXT, is_trading_day)│
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌────────────────────────┴────────────────────────────────────────┐
│ 数据加载层                                                      │
│  load_stock_bars() → List[Bar]                                  │
│  DataPipeline.run() → Dict[str, Any] (含因子)                   │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌────────────────────────┴────────────────────────────────────────┐
│ BacktestData 实例                                               │
│  数据层构建, 计算层/模拟层只读消费                               │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据源映射

| 外部字段（Akshare） | DB 字段（stock_daily） | BacktestData 字段 | 归一化规则 |
|:---------------------|:-----------------------|:-------------------|:-----------|
| `开盘` / `open` | `open REAL` | `open[:,:]` | 直接映射 |
| `最高` / `high` | `high REAL` | `high[:,:]` | 直接映射 |
| `最低` / `low` | `low REAL` | `low[:,:]` | 直接映射 |
| `收盘` / `close` | `close REAL` | `close[:,:]` | 直接映射 |
| `成交量` / `volume` | `volume INTEGER` → **股** | `volume[:,:]` | akshare 返回即为股 |
| `成交额` / `amount` | `amount REAL` → **元** | `amount[:,:]` | akshare 返回即为元 |
| `昨收价` / `pre_close` | pre_close (v1.0 contract) | `pre_close[:,:]` | 部分 DB 未存储，需计算 |
| — | `code TEXT` | `symbols[si]` | 查询时注入 `symbol` 参数 |
| `日期` / `date` | `date TEXT YYYYMMDD` | `trading_dates[di]` | 统一字符串格式 |

### 3.3 Schema 差异记录（⚠️ 已知问题）

当前系统存在 **DB schema 不一致**，关键差异如下：

| 维度 | `data_ingestion/data_contract.py` (v1.0) | `data_loader.py` / `load_stock_bars()` | 影响 |
|:-----|:----------------------------------------|:----------------------------------------|:-----|
| 日期列名 | `trade_date INT` | `date TEXT` | **字段名不一致**，查询需适配 |
| 主键 | `(ts_code, trade_date)` | `(code, date)` | key 列名不同 |
| 代码列名 | `ts_code VARCHAR(20)` | `code TEXT` | 列名不同 |
| volume 单位 | `BIGINT` (股) | `INTEGER` (股) | 单位一致但类型不同 |
| pre_close | 有定义 | **缺失** | 部分查询需计算 |
| adj_factor | 有定义 | **缺失** | 当前无复权因子列 |

> **当前兼容策略**：`load_stock_bars()` 查询 `date` 列（并兼容 YYYYMMDD 格式），而 baseline runner 查询 `trade_date` 列。统一方案详见迁移计划。

---

## 四、缺失值处理规则

### 4.1 分类与策略

参照 `data_filler.py` 定义的规则：

| 缺失类型 | 判定条件 | 填充策略 | 策略类 | 详细规则 |
|:---------|:---------|:---------|:-------|:---------|
| **节假日** | `is_trading_day=False` | **跳过（skip）** | `SkipStrategy` | 不填充，数据序列中不出现该日期 |
| **停牌（SUSPENSION）** | `is_trading_day=True` 但 `stock_daily` 无对应数据 | **前向填充（ffill）** | `FfillStrategy` | open/high/low/close = 前一日收盘价；volume = 0；标记 `is_filled=True` |
| **短缺失（SHORT_GAP）** | 连续缺失 ≤3 个交易日 | **前向填充（ffill）** | `FfillStrategy` | 同上 |
| **长缺失（LONG_GAP）** | 连续缺失 >3 个交易日 | **剔除（trim_remove）** | `TrimRemoveStrategy` | 该时间段的缺失数据整体移除，不做插值 |

### 4.2 各字段默认值

| 字段 | 缺失值处理 | 说明 |
|:-----|:-----------|:-----|
| `close` | 前向填充（ffill）→ 前一日收盘价 | 停牌/短缺失时 |
| `open` | 前向填充 → 前一日收盘价 | — |
| `high` | 前向填充 → 前一日收盘价 | — |
| `low` | 前向填充 → 前一日收盘价 | — |
| `volume` | 填充为 0.0 | 停牌日无交易 |
| `amount` | 填充为 0.0 | 停牌日无交易 |
| `vwap` | 填充为 0.0 | 停牌日 VWAP 无意义 |
| `pre_close` | 前向填充 → 前一日收盘价 | — |
| `adj_factor` | 前向填充 → 1.0（无复权） | 缺失时视为不复权 |
| `price_limit_mask` | 基于 `pre_close` 计算 ±10% | 停牌日不触发 |
| `suspend_mask` | 独立字段，不由填充生成 | 填充后自行计算 |

### 4.3 长缺失剔除规则

当缺失连续 >3 个交易日时：

```
剔除范围：[missing_start_date, missing_end_date] 的所有缺失序列点
不填充，直接剔除——该区间不纳入回测数据
```

> **注意**：`suspend_mask` 仍标记该时段为停牌，计算层约束检查时会跳过。该条仅影响数据矩阵生成的取舍。

### 4.4 填充标记

所有由填充产生的数据行必须标记：

```python
is_filled: bool = True  # 由填充产生
is_trading_day: bool = True  # 虽无交易，但确实是交易日
```

---

## 五、时间戳对齐规则（BT-006 t-1 契约）

### 5.1 核心规则

```
计算日 t 的信号 ← 可访问数据：t-1, t-2, ..., t-n（历史已完结数据）
计算日 t 的信号 ← 禁止访问数据：t（当日数据，尚未完结）
```

### 5.2 形式化定义

```python
# BacktestData 矩阵约定：
#   time_axis = 0 (行索引 = 交易日)
#   stock_axis = 1 (列索引 = 标的)

# 交易日 di 的计算层只能访问 data[:di, :] 的数据
# 交易日 di 禁止访问 data[di, :] 及之后的任何数据

def aligned_input(data: np.ndarray, current_day: int, shift: int = 1) -> np.ndarray:
    """返回合法输入：第 current_day 日只能访问 t-shift 及之前的数据"""
    if current_day < shift:
        raise LookAheadBiasError(
            f"时间对齐冲突: current_day={current_day}, 无足够历史数据 (shift={shift})"
        )
    return data[:current_day - shift + 1]
```

### 5.3 数据矩阵构造示例

```python
def build_backtest_data(loader_result: List[Bar], symbols: List[str], dates: List[str]) -> BacktestData:
    """
    数据层构造 BacktestData。
    
    矩阵形状确认：
      - close[di, si] = 第 di 日标的 si 的收盘价
      - data[:di, si] = 截至 di 日前的全部历史数据（t-1 友好）
    
    前向填充处理（t-1 对齐的关系）：
      - 第 di 日面临一个缺失行 → 用 data[di-1, si] 填充 → OK（使用已完结数据）
      - 第 di 日的 close 来自 t-1 的交易结果 → OK（自然对齐）
    """
    ...
```

### 5.4 下游契约传递

```python
# ❌ 违反：下游再次 shift → 信号变成 t-2，实际交易落后 2 天
signal_mat = calc_all_signals(backtest_data)
traded_signal = pd.DataFrame(signal_mat).shift(1).values  # 禁止

# ✅ 正确：计算层已确保 t-1 对齐
signal_mat = calc_all_signals(backtest_data)  # 直接使用
```

---

## 六、数据版本指纹（data_fingerprint）

### 6.1 定义

`data_fingerprint` 是对 `BacktestData` 关键字段的确定性 hash，作为数据版本的唯一标识。

```python
import hashlib
import json
import numpy as np

def compute_data_fingerprint(
    close: np.ndarray,
    volume: np.ndarray,
    trading_dates: List[str],
    symbols: List[str],
) -> str:
    """
    计算数据版本指纹。

    输入：核心价格/量数据 + 索引信息
    输出：SHA256 hex 前 16 位（碰撞概率足够低）
    
    设计原则：
      - 确定性：相同数据 → 相同 fingerprint
      - 可复现：支持跨平台一致性
      - 简洁：16 hex chars 即够
      - 独立于元数据：不包括配置、时间戳等变劷因子
    """
    payload = {
        "close": close.round(4).tolist(),          # 精度 4 位小数
        "volume": volume.astype(int).tolist(),     # 整数
        "trading_dates": trading_dates,
        "symbols": symbols,
    }
    hash_bytes = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return hash_bytes[:16]
```

### 6.2 使用场景

| 场景 | 用途 | 示例 |
|:-----|:------|:------|
| 回测黄金基线记录 | 确保同一数据生成相同基线 | `backtest_golden_baseline_*.json` |
| 回归对比 | 数据变更 → fingerprint 变 → 需重新生成基线 | CI 自动检测 |
| 数据源验证 | 不同批次数据的一致性检查 | 定期校验 |
| 数据缓存键 | Parquet 缓存文件名的一部分 | `601857_20200101_20260515_qfq.parquet` |

### 6.3 版本递增规则

| 变更类型 | fingerprint 变化 | 版本号递增 |
|:---------|:-----------------|:-----------|
| 新增标的 | **变化** | 字段不变，`symbols` 变 → minor |
| 新增数据日期 | **变化** | `trading_dates` 变 → minor |
| 数据修正（精度/清洗） | **变化** | 数值变 → minor |
| 数据口径变更（复权方式） | **变化** | major+1 |
| 仅修改合约字段定义 | **不变** | 无变更 |

---

## 七、前视偏差检测（BT-007 TimeAlignmentGuard）

### 7.1 检测接口定义

```python
class LookAheadBiasError(Exception):
    """前视偏差运行时异常"""
    pass

class TimeAlignmentGuard:
    """
    运行时检测前视偏差。
    
    确保所有 calc/ 函数执行时不会使用当日（t+0）或未来数据。
    
    使用方式：
        data = ...  # BacktestData 实例
        for di in range(1, len(data.trading_dates)):
            with TimeAlignmentGuard(data, current_day=di):
                signal = compute_signal(data.close, di)
    """
    
    def __init__(self, data: "BacktestData", current_day: int, shift: int = 1):
        self.data = data
        self.current_day = current_day
        self.shift = shift  # 默认 1 = t-1 对齐
    
    def __enter__(self):
        self._validate_bounds()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._validate_after()
        return False
    
    def _validate_bounds(self):
        """前置校验：current_day 必须有足够的历史数据"""
        n_days = len(self.data.trading_dates)
        if self.current_day < self.shift:
            raise LookAheadBiasError(
                f"时间对齐冲突: current_day={self.current_day}, "
                f"需至少 {self.shift} 个历史数据点"
            )
        if self.current_day >= n_days:
            raise LookAheadBiasError(
                f"时间越界: current_day={self.current_day}, "
                f"数据仅有 {n_days} 天"
            )
    
    def _validate_after(self):
        """后置校验：确认函数未访问越界数据（作为额外检测层）"""
        # 通过 Traceback 或输出矩阵形状验证
        pass
```

### 7.2 数据加载层的运行时检测（伪代码）

```python
def load_with_alignment_guard(
    symbols: List[str],
    start_date: str,
    end_date: str,
    ds: Optional[AkshareDataSource] = None,
) -> BacktestData:
    """
    一次性加载所有数据 → 构建 BacktestData。
    
    自动执行：
      1. 前视偏差检测
      2. 缺失值填充
      3. 时间戳对齐
    """
    # Step 1: 加载全量数据
    all_bars: List[Bar] = load_stock_bars(symbols, start_date, end_date)
    
    # Step 2: 构建矩阵
    data = build_matrix(all_bars, symbols, trading_dates)
    
    # Step 3: 运行前视偏差扫描
    for di in range(1, len(trading_dates)):
        with TimeAlignmentGuard(data, current_day=di):
            # 此时计算函数只能访问 data[:di, :]
            pass
    
    # Step 4: 计算 fingerprint
    data.data_fingerprint = compute_data_fingerprint(
        data.close, data.volume, data.trading_dates, data.symbols
    )
    
    return data
```

### 7.3 检测触发条件

| 触发条件 | 检测方式 | 告警级别 | 处理方式 |
|:---------|:---------|:---------|:---------|
| 输入矩阵 shape[0] < current_day | 前置维度检查 | **ERROR** | 抛出异常，终止回测 |
| 使用了 `data[di]` 且 di ≥ current_day | 运行时索引检查 | **ERROR** | 抛出异常，终止回测 |
| 计算结果与"延迟一个单位"版本差异 > 容差 | 后验统计校验 | WARN | 记录日志，继续执行 |
| current_day=0 无历史数据 | 前置边界检查 | **ERROR** | 抛出异常 |

### 7.4 calc/ 函数签名集成

```python
# 所有 calc/*.py 函数的统一输入模式：
def compute_signal(
    data: np.ndarray,       # 已对齐的输入：data[:current_day, :]
    current_day: int,       # 当前交易日索引
    **params               # 其他参数
) -> np.ndarray:
    """
    计算第 current_day 日的信号。
    
    参数约定：
      - data 已通过 aligned_input() 截断到 current_day-1
      - 函数内部不得访问任何 data[current_day] 或之后的数据
    """
    pass
```

---

## 八、验证规则清单

### 8.1 构建时验证（数据层）

| # | 验证规则 | 检查方法 | 失败处理 |
|:-:|:---------|:---------|:---------|
| V-01 | `close.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-02 | `open.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-03 | `high.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-04 | `low.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-05 | `volume.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-06 | `amount.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-07 | `vwap.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-08 | `suspend_mask.shape == (n_days, n_stocks)` | `assert` | 停止构建 |
| V-09 | `price_limit_mask.shape == (n_days, n_stocks, 2)` | `assert` | 停止构建 |
| V-10 | `len(trading_dates) == n_days` | `assert` | 停止构建 |
| V-11 | `len(symbols) == n_stocks` | `assert` | 停止构建 |
| V-12 | `trading_dates` 严格升序 | 循环检查 | 停止构建 |
| V-13 | `dtype == float64`（所有 ndarray） | `assert` | 发出 WARN |
| V-14 | `high[di, si] >= close[di, si] >= low[di, si]` 对所有 di, si 成立 | 向量化检查 | WARN + 记录异常点 |
| V-15 | `close[di, si] >= 0` 且 `volume[di, si] >= 0` 对所有 di, si 成立 | 向量化检查 | WARN + 记录异常点 |

### 8.2 运行时验证（计算层）

| # | 验证规则 | 检查方法 | 失败处理 |
|:-:|:---------|:---------|:---------|
| V-20 | `current_day >= 1`（至少 1 个历史数据） | `assert` | 抛出 LookAheadBiasError |
| V-21 | 函数输入 `data` 的 shape[0] <= current_day | `TimeAlignmentGuard` | 抛出异常 |
| V-22 | 函数输出 shape 与输入一致 | 检查 | WARN + 记录 |
| V-23 | 函数未修改输入参数（纯函数约束） | NDArray 的 `_base` 检查 | WARN + 记录 |

### 8.3 后验验证（模拟层）

| # | 验证规则 | 检查方法 | 失败处理 |
|:-:|:---------|:---------|:---------|
| V-30 | 交易日期 `trade_date >= start_date AND trade_date <= end_date` | 范围检查 | WARN |
| V-31 | 所有交易均在交易日 `is_trading_day=True` 的日期执行 | 日历交叉检查 | ERROR |
| V-32 | 停牌日无交易 | `suspend_mask → trade_log` 交叉检查 | ERROR |
| V-33 | 涨停日无买入 | `price_limit_mask → trade_log` 交叉检查 | ERROR |
| V-34 | 跌停日无卖出 | `price_limit_mask → trade_log` 交叉检查 | ERROR |
| V-35 | T+1 买入的当日不可卖出 | 持仓日记交叉检查 | ERROR |

### 8.4 回归验证

| # | 验证规则 | 检查方法 | 失败处理 |
|:-:|:---------|:---------|:---------|
| V-40 | 相同 `data_fingerprint` 应产生相同回测结果 | 基线对照 | CI 阻断 |
| V-41 | 回测结果与黄金基线偏差 ≤ 容差（默认 1e-6） | 数值比较 | CI 阻断 |
| V-42 | 交易笔数一致 | 计数比较 | CI 阻断 |

---

## 九、BacktestData Dataclass 定义（参考实现）

依据 BT-004 契约：

```python
@dataclass
class BacktestData:
    """回测数据合约——层间数据传递的唯一容器。
    
    所有 ndarray 的 dtype 统一为 float64。
    构建后不可修改（frozen=True）。
    """
    
    # ── 核心价量 ──
    close: np.ndarray              # (n_days, n_stocks)  单位：元
    open: np.ndarray               # (n_days, n_stocks)  单位：元
    high: np.ndarray               # (n_days, n_stocks)  单位：元
    low: np.ndarray                # (n_days, n_stocks)  单位：元
    volume: np.ndarray             # (n_days, n_stocks)  单位：股
    amount: np.ndarray             # (n_days, n_stocks)  单位：元
    vwap: np.ndarray               # (n_days, n_stocks)  单位：元
    
    # ── 价格修正 ──
    pre_close: np.ndarray          # (n_days, n_stocks)  单位：元
    adj_factor: np.ndarray         # (n_days, n_stocks)  复权因子
    change: np.ndarray             # (n_days, n_stocks)  涨跌额
    pct_chg: np.ndarray            # (n_days, n_stocks)  涨跌幅(%)
    
    # ── 约束/标记 ──
    price_limit_mask: np.ndarray   # (n_days, n_stocks, 2)  [lower, upper]
    suspend_mask: np.ndarray       # (n_days, n_stocks)  bool
    is_trading_day: np.ndarray     # (n_days,)           bool
    resume_day_mask: np.ndarray    # (n_days, n_stocks)  bool
    
    # ── 索引 ──
    trading_dates: List[str]       # [n_days]  YYYYMMDD
    symbols: List[str]             # [n_stocks]  格式如 "601857.SH"
    
    # ── 可选衍生因子 ──
    float_share: Optional[np.ndarray] = None        # (n_days, n_stocks)
    turnover_rate: Optional[np.ndarray] = None      # (n_days, n_stocks)
    volume_ratio_20: Optional[np.ndarray] = None    # (n_days, n_stocks)
    volume_ratio_60: Optional[np.ndarray] = None    # (n_days, n_stocks)
    
    # ── 元信息 ──
    meta: Dict[str, Any] = field(default_factory=dict)
    data_fingerprint: str = ""
    
    def __post_init__(self):
        """构建时自动验证维度一致性"""
        self._validate_shapes()
        self._validate_dates()
    
    def _validate_shapes(self):
        n_days = len(self.trading_dates)
        n_stocks = len(self.symbols)
        
        for name, arr in [
            ("close", self.close), ("open", self.open),
            ("high", self.high), ("low", self.low),
            ("volume", self.volume), ("amount", self.amount),
            ("vwap", self.vwap), ("pre_close", self.pre_close),
            ("adj_factor", self.adj_factor),
            ("suspend_mask", self.suspend_mask),
        ]:
            assert arr.shape == (n_days, n_stocks), \
                f"{name}.shape={arr.shape} != ({n_days}, {n_stocks})"
        
        assert self.price_limit_mask.shape == (n_days, n_stocks, 2), \
            f"price_limit_mask.shape={self.price_limit_mask.shape}"
        
        if self.float_share is not None:
            assert self.float_share.shape == (n_days, n_stocks)
    
    def _validate_dates(self):
        """验证 trading_dates 严格升序"""
        for i in range(1, len(self.trading_dates)):
            assert self.trading_dates[i] > self.trading_dates[i-1], \
                f"交易日非严格升序: {self.trading_dates[i-1]} → {self.trading_dates[i]}"
```

---

## 附录 A：当前数据源映射清单

### A.1 DB 表结构（当前活跃的 `stock_daily` 表）

```sql
-- market_data.db 中的 stock_daily 表（data_loader.py 创建）
CREATE TABLE IF NOT EXISTS stock_daily (
    code    TEXT,       -- 股票代码（纯代码，无后缀）
    date    TEXT,       -- 交易日 YYYYMMDD
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL,
    volume  INTEGER,    -- 股
    amount  REAL,       -- 元
    PRIMARY KEY (code, date)
);
```

### A.2 数据合约 v1.0 的 DDL（`data_ingestion/data_contract.py` 定义）

```sql
CREATE TABLE IF NOT EXISTS stock_daily (
    -- 标识字段
    `ts_code` VARCHAR(20) NOT NULL COMMENT '股票代码（带交易所后缀）',
    `trade_date` INT NOT NULL COMMENT '交易日 YYYYMMDD',
    -- 价格字段
    `open` DECIMAL(12,2) COMMENT '开盘价 [元]',
    `high` DECIMAL(12,2) COMMENT '最高价 [元]',
    `low` DECIMAL(12,2) COMMENT '最低价 [元]',
    `close` DECIMAL(12,2) COMMENT '收盘价 [元]',
    `pre_close` DECIMAL(12,2) COMMENT '昨收价 [元]',
    `change` DECIMAL(12,2) COMMENT '涨跌额 [元]',
    `pct_chg` DECIMAL(9,2) COMMENT '涨跌幅 [%]',
    -- 量价字段
    `volume` BIGINT COMMENT '成交量 [股]',
    `amount` DECIMAL(20,2) COMMENT '成交额 [元]',
    `turnover_rate` DECIMAL(9,4) COMMENT '换手率 [%]',
    `turnover_rate_f` DECIMAL(9,4) COMMENT '换手率（自由流通）[%]',
    `volume_ratio` DECIMAL(9,4) COMMENT '量比',
    -- 估值字段
    `pe` DECIMAL(12,4) COMMENT '市盈率',
    `pe_ttm` DECIMAL(12,4) COMMENT '滚动市盈率',
    `pb` DECIMAL(12,4) COMMENT '市净率',
    -- 股本字段
    `total_share` DECIMAL(16,2) COMMENT '总股本 [股]',
    `float_share` DECIMAL(16,2) COMMENT '流通股本 [股]',
    `free_float_share` DECIMAL(16,2) COMMENT '自由流通股本 [股]',
    `total_mv` DECIMAL(20,2) COMMENT '总市值 [元]',
    `circ_mv` DECIMAL(20,2) COMMENT '流通市值 [元]',
    -- 系统字段
    `data_source` VARCHAR(20) NOT NULL COMMENT '来源标记',
    `version` VARCHAR(10) NOT NULL COMMENT '清洗版本号',
    `created_at` DATETIME NOT NULL COMMENT '入库时间',
    PRIMARY KEY (ts_code, trade_date)
);
```

> **Schema 迁移方向**：当前使用的 `data_loader.py` 简化表（code/date/OHLCV/volume/amount）将逐步迁移至 `data_ingestion/data_contract.py` 定义的完整表结构（ts_code/trade_date/pre_close 等），以支撑 BacktestData 所有必需字段。

---

*本文档 v1.0 依据回测编码原则 BT-004 定义，覆盖 2a（数据结构梳理）、2b（合约定义）、2c（前视偏差检测）完整子任务。*
