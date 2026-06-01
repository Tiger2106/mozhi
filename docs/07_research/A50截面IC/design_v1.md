# 方案设计：A50全成分股截面IC数据补证

> **版本**: v1.0（方案设计初稿）
> **作者**: 墨衡 (DeepSeek R1)
> **创建时间**: 2026-05-29T21:30:00+08:00
> **状态**: DRAFT
> **依据**: `req_draft_v2.1.md`（已五方会签生效）+ `data_survey_report.md`（已完成摸底）
> **数据库环境**: `C:\Users\17699\mozhi_platform\data\market\market_data.db` (593.4 MB, SQLite3)

---

## 1. 数据架构

### 1.1 数据库选择：独立 `a50_ic.db`

| 方案 | 说明 | 选择 |
|:----|:----|:----:|
| **独立 `a50_ic.db`** | 在 `data/` 目录下新建专用数据库 | ⭐ **推荐** |
| 扩展 `market_data.db` | 在源库中新增表 | ❌ 拒绝 |

**决策依据**：
1. **职责分离**：`market_data.db` 是原始数据源仓库，`a50_ic.db` 是衍生分析层，混在一起会导致数据版本管理混乱
2. **版本管理**：IC计算依赖 `source_version` 锚定，独立库可独立演进
3. **迁移安全**：独立库出错不影响原始数据，重建只需重新运行ETL
4. **文件大小**：593MB + 衍生数据 ≈ 650MB+，单一SQLite文件过大影响查询性能

**路径**：`C:\Users\17699\mozhi_platform\data\a50_ic\a50_ic.db`

### 1.2 三表结构（DDL）

> 以下DDL基于 `req_draft_v2.1.md` §3 字段定义编写，可直接在SQLite中执行。

#### 1.2.1 `a50_daily_ohlcv` —— 日线行情表

```sql
-- 数据来源：market_data.db.stock_daily（上证50成分股）
-- 字段口径：req_draft_v2.1 §3.1.1

CREATE TABLE IF NOT EXISTS a50_daily_ohlcv (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code         TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,  -- YYYYMMDD
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL    NOT NULL,  -- 复权后价格 (close * adj_factor)
    pre_close       REAL,              -- 前复权后前一交易日收盘价
    volume          REAL,              -- 成交量（股）
    amount          REAL,              -- 成交金额（元）
    turnover_rate   REAL,              -- 换手率（%），自计算
    pe              REAL,              -- 动态市盈率（PE TTM）
    pb              REAL,              -- 市净率
    adj_factor      REAL    NOT NULL,  -- 当日复权因子
    null_reason     TEXT,              -- NULL语义：NULL=正常, 'MISSING'=缺失, 'SUSPENDED'=停牌
    source_version  TEXT    NOT NULL DEFAULT 'v1',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_a50_daily_pk
    ON a50_daily_ohlcv(ts_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_a50_daily_date
    ON a50_daily_ohlcv(trade_date);
CREATE INDEX IF NOT EXISTS idx_a50_daily_code
    ON a50_daily_ohlcv(ts_code);
```

**注意点**：
- `close` 和 `pre_close` 为 **后复权后价格**，写入前通过 `close_adj = close * adj_factor` 计算
- `open`/`high`/`low` 同理使用复权后的价格（如因子计算需要原始价格，则用 `close / adj_factor` 反算）
- `turnover_rate` 在ETL中自计算：`volume * 100 / float_share`（从源表 `stock_daily.float_share` 获取）
- `null_reason` 字段实现停牌/缺失区分（详见 §3.3）

#### 1.2.2 `a50_cross_ic_result` —— 截面IC结果表

```sql
-- 存储每次截面IC计算结果
-- 字段口径：req_draft_v2.1 §3.2.1

CREATE TABLE IF NOT EXISTS a50_cross_ic_result (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT    NOT NULL,  -- 截面日期 YYYYMMDD（周五/月末最后交易日）
    factor_name     TEXT    NOT NULL,  -- 因子名，全小写+下划线
    ic_value        REAL,             -- Pearson截面IC（计算失败=NULL）
    rank_ic         REAL,             -- Spearman秩相关IC（计算失败=NULL）
    p_value         REAL,             -- p-value显著性检验
    num_stocks      INTEGER NOT NULL, -- 有效样本数
    adjusted_ic     REAL,             -- 剔除极值±3σ后重算（未剔除=NULL）
    source_version  TEXT    NOT NULL,  -- 版本锚定
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_ic_uniq
    ON a50_cross_ic_result(trade_date, factor_name, source_version);
CREATE INDEX IF NOT EXISTS idx_ic_factor
    ON a50_cross_ic_result(factor_name);
CREATE INDEX IF NOT EXISTS idx_ic_date
    ON a50_cross_ic_result(trade_date);
```

**样本量阈值**：`num_stocks < 30` 时，`ic_value` 和 `adjusted_ic` 置为 NULL（该截面无效）。

**外键说明**：SQLite 默认 `PRAGMA foreign_keys=OFF`，ETL连接时需要显式开启。设计上保留外键语义但不由数据库强制约束（由 `source_version` 版本锚定保证逻辑关联）。

#### 1.2.3 `a50_universe` —— 成分股列表表

```sql
-- 历史+当前成分股列表（必需表，req_draft_v2.1 §3.3 已升级为必需）
-- 数据来源：tushare 指数成分股接口 / CSI官方公告

CREATE TABLE IF NOT EXISTS a50_universe (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code         TEXT    NOT NULL,  -- 股票代码
    stock_name      TEXT,              -- 股票名称（可选）
    in_date         TEXT    NOT NULL,  -- 纳入日期 YYYYMMDD
    out_date        TEXT,              -- 剔除日期 YYYYMMDD（NULL=当前成分股）
    weight          REAL,              -- 权重（若可获取）
    source          TEXT    NOT NULL,  -- 数据来源
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_universe_code_in_date
    ON a50_universe(ts_code, in_date);
CREATE INDEX IF NOT EXISTS idx_universe_in_out_date
    ON a50_universe(in_date, out_date);
```

**使用方式**：给定 `trade_date`，查询 `in_date <= trade_date AND (out_date IS NULL OR out_date >= trade_date)` 得到该日期应纳入计算的成分股列表。

### 1.3 版本锚定策略

| 策略 | 实现 |
|:----|:----|
| **默认版本** | 初始版本为 `'v1'`，写入 `source_version` 字段 |
| **版本升级条件** | 以下任一变更触发：复权方案调整、因子计算逻辑变更、数据源变更 |
| **版本变更记录** | 每次变更需附带迁移脚本（`migrate_v1_to_v2.sql`）+ 变更说明文档 |
| **版本关联** | IC结果表中的 `source_version` 对应 `a50_daily_ohlcv.source_version`，保证逻辑可追溯 |
| **版本回滚** | 保留旧版本数据，不覆盖。新版本写入新行（通过 `source_version` 区分） |

**迁移脚本命名规范**：`a50_ic/migrations/migrate_{old}_to_{new}.sql`

---

## 2. 因子计算管线

### 2.1 基础数据准备函数

```python
def load_panel_data(
    db_path: str,
    trade_date: str,
    lookback_days: int = 120,  # 最大回看窗口，涵盖momentum_120d
    adj_method: str = "后复权",
) -> pd.DataFrame:
    """
    加载截面IC计算所需的面板数据。
    
    入参：
        db_path: a50_ic.db 路径
        trade_date: 截面日期（YYYYMMDD）
        lookback_days: 回看窗口天数（含当前日期）
        adj_method: 复权方法（仅支持'后复权'）
    
    返回：
        DataFrame，列: ts_code, trade_date, close, volume, amount, 
                       adj_factor, pe, pb, 
                       return_1d (日收益率)
        index: (ts_code, trade_date)
        
    实现逻辑：
        1. SELECT * FROM a50_daily_ohlcv 
           WHERE trade_date BETWEEN '{trade_date - lookback_days}' AND '{trade_date}'
        2. 计算日收益率 return_1d[t] = close[t] / close[t-1] - 1
        3. 过滤 null_reason='SUSPENDED' 的行
        4. 按 (ts_code, trade_date) 排序
    """
```

### 2.2 15因子自计算方案

#### 2.2.1 数据依赖总览

| # | 因子名 | 类别 | 依赖字段 | 摸底状态 | 优先级 |
|:-:|:------|:----:|:---------|:--------:|:------:|
| 1 | `momentum_5d` | 动量 | close(复权) | ✅ 数据可用 | P0 |
| 2 | `momentum_20d` | 动量 | close(复权) | ✅ 数据可用 | **P0**（黄金基线） |
| 3 | `momentum_60d` | 动量 | close(复权) | ✅ 数据可用 | P0 |
| 4 | `momentum_120d` | 动量 | close(复权) | ✅ 数据可用 | P1 |
| 5 | `reversal_1d` | 反转 | open, close(复权) | ✅ 数据可用 | P0 |
| 6 | `reversal_5d` | 反转 | close(复权) | ✅ 数据可用 | P0 |
| 7 | `roe_ttm` | 质量 | pe, eps/财务数据 | ⚠️ 摸底确认中 | P2 |
| 8 | `profit_margin` | 质量 | 财务数据 | ❌ 摸底后确定 | P3 |
| 9 | `pe_ttm` | 估值 | pe_ttm字段 | ⚠️ 字段存在，质量待验证 | P1 |
| 10 | `pb_lf` | 估值 | pb字段 | ⚠️ 字段存在，质量待验证 | P1 |
| 11 | `dividend_yield` | 估值 | 分红数据 | ❌ 摸底后确定 | P3 |
| 12 | `volatility_20d` | 波动 | close(复权) | ✅ 数据可用 | P0 |
| 13 | `turnover_20d_avg` | 流动性 | volume, float_share | ⚠️ 换手率需自计算 | P1 |
| 14 | `illiquidity_20d` | 流动性 | return(复权), amount | ✅ 数据可用 | P0 |
| 15 | `volume_20d_change` | 流动性 | volume | ✅ 数据可用 | P1 |

> **P0**：数据完全可用，管线首期实现
> **P1**：数据基本可用，但需额外处理（自计算/质量验证）
> **P2**：数据依赖摸底确认，T+7后确定是否可用
> **P3**：数据依赖外部源，可能延期或替换

#### 2.2.2 各因子计算公式（pandas代码级）

以下公式假设已加载 `panel_df`（见 §2.1），每只股票的价格 `close_adj = close`（已在 ETL 中完成复权）。

---

**动量类（Momentum）**

```python
# momentum_5d: 过去5个交易日收益率（5日动量）
# 公式: close[t] / close[t-5] - 1
# 回看窗口不足5日 → NULL
panel_df['momentum_5d'] = (
    panel_df.groupby('ts_code')['close']
    .transform(lambda x: x / x.shift(5) - 1)
)

# momentum_20d: 过去20个交易日收益率（月频动量）【黄金基线】
# 公式: close[t] / close[t-20] - 1
panel_df['momentum_20d'] = (
    panel_df.groupby('ts_code')['close']
    .transform(lambda x: x / x.shift(20) - 1)
)

# momentum_60d: 过去60个交易日收益率（季频动量）
panel_df['momentum_60d'] = (
    panel_df.groupby('ts_code')['close']
    .transform(lambda x: x / x.shift(60) - 1)
)

# momentum_120d: 过去120个交易日收益率（半年频动量）
panel_df['momentum_120d'] = (
    panel_df.groupby('ts_code')['close']
    .transform(lambda x: x / x.shift(120) - 1)
)
```

**回看窗口不足处理**：`shift(N)` 自然返回NaN，在IC计算时该样本被排除（因子值为NULL不参与corr）。

---

**反转类（Reversal）**

```python
# reversal_1d: 隔夜跳空 - 日内反转
# 公式: open[t]/close[t-1] - close[t]/open[t]
# 经济含义：隔夜跳空高开后日内回落 → 反转信号
panel_df['reversal_1d'] = (
    panel_df.groupby('ts_code')
    .apply(lambda g: g['open'] / g['close'].shift(1) - g['close'] / g['open'])
    .reset_index(level=0, drop=True)
)

# reversal_5d: 5日反转（不含当日）
# 公式: -(close[t-1]/close[t-5] - 1)
# 注意：使用不含当日的前5日收益取负，与momentum_5d统计独立
panel_df['reversal_5d'] = -(
    panel_df.groupby('ts_code')['close']
    .transform(lambda x: x.shift(1) / x.shift(5) - 1)
)
```

---

**质量类（Quality）** — 数据依赖待确认

```python
# roe_ttm: ROE（TTM）
# 若可用pe + eps反算: ROE ≈ 1/pe * (price/book_value_per_share) 近似
# 更准确：从财报表直接获取
# 摸底未完成前标记为待确认
# panel_df['roe_ttm'] = ...  # 占位，T+7后激活

# profit_margin: 毛利率
# 依赖财报数据接口，摸底后确定
```

---

**估值类（Valuation）**

```python
# pe_ttm: 市盈率TTM
# 直接使用源表pe_ttm字段（源表字段名为pe_ttm，映射为pe）
# 注：a50_daily_ohlcv.pe 存储源表的 pe_ttm（原始字段名pe_ttm在stock_daily列#15）
# 源表stock_daily字段: pe(列#14), pe_ttm(列#15), pb(列#16)
panel_df['pe_ttm'] = panel_df['pe']  # pe字段已入库

# pb_lf: 市净率（最新）
panel_df['pb_lf'] = panel_df['pb']  # pb字段已入库
```

**估值因子数据质量**：摸底报告未检查 `pe`/`pe_ttm`/`pb` 的缺失率，ETL 阶段需补做专项检查。若缺失率 > 20%，退化为 `np.nan`（不参与IC计算，样本量减少但截面仍然有效）。

---

**波动与流动性类（Volatility / Liquidity）**

```python
# volatility_20d: 20日波动率
# 公式: 过去20日收益率的标准差（年化需乘sqrt(242)，此处保留日度值便于IC比较）
panel_df['volatility_20d'] = (
    panel_df.groupby('ts_code')['return_1d']
    .transform(lambda x: x.rolling(20, min_periods=10).std())
)
# min_periods=10：至少10个有效日收益率才计算，避免停牌期过多导致的波动率失真

# turnover_20d_avg: 20日均换手率
# 换手率自计算：volume[t] * 100 / float_share[t]
# 若float_share[t]不可用，降级为: volume[t] * 100 / total_share[t]
panel_df['turnover_self'] = (
    panel_df['volume'] * 100 / panel_df['float_share']  # float_share从源表取
)
panel_df['turnover_20d_avg'] = (
    panel_df.groupby('ts_code')['turnover_self']
    .transform(lambda x: x.rolling(20, min_periods=10).mean())
)

# illiquidity_20d: Amihud非流动性指标
# 公式: mean(|return_1d[t]| / amount[t]) over 20d
# 注意：经典Amihud口径，分母为成交金额（元），非股数
# 实际处理：|return| / amount 每日计算，再取20日均值
# 因量级极小（|return|~0.01, amount~1e9），结果乘以 1e6 以便阅读
panel_df['illiquidity_daily'] = (
    panel_df['return_1d'].abs() / panel_df['amount']
)
panel_df['illiquidity_20d'] = (
    panel_df.groupby('ts_code')['illiquidity_daily']
    .transform(lambda x: x.rolling(20, min_periods=10).mean()) * 1e6
)

# volume_20d_change: 20日成交量变化率
# 公式: volume[t] / avg(volume[t-5:t]) - 1
# 当前量 vs 近5日均量的变化率，反映短期量能变化
panel_df['volume_ma5'] = (
    panel_df.groupby('ts_code')['volume']
    .transform(lambda x: x.rolling(5, min_periods=3).mean())
)
panel_df['volume_20d_change'] = (
    panel_df['volume'] / panel_df['volume_ma5'].shift(1) - 1
)
```

**停牌处理**（统一规则，req_draft_v2.1 §4.0）：
- 窗口内停牌占比 > 50% → 因子值置 NULL（该样本排除）
- 窗口内停牌占比 ≤ 50% → 按实际开盘日计算，`rolling(min_periods=N)` 自然跳过NaN
- `min_periods` 参数设置：
  - momentum 类：不设 min_periods（必须完整窗口）
  - volatility_20d: min_periods=10
  - turnover_20d_avg: min_periods=10
  - illiquidity_20d: min_periods=10

### 2.3 核心函数 `cross_sectional_ic.py` 设计

#### 2.3.1 函数签名

```python
# src/pipeline/cross_sectional_ic.py

import sqlite3
import pandas as pd
import numpy as np
from scipy import stats
from typing import List, Optional, Dict
from datetime import datetime, timedelta

def compute_cross_sectional_ic(
    db_path: str,
    trade_date: str,
    factor_names: List[str],
    forward_window: int = 5,
    min_stocks: int = 30,
    adj_method: str = "后复权",
) -> pd.DataFrame:
    """
    计算指定截面的多因子IC。
    
    入参：
        db_path: a50_ic.db 路径
        trade_date: 截面日期(YYYYMMDD)，必须是周五或最后交易日
        factor_names: 因子名列表，每个因子按§2.2.2公式计算
                      e.g. ['momentum_5d', 'momentum_20d', 'reversal_1d']
        forward_window: 预测窗口（交易日数），默认5日
        min_stocks: 最小有效样本数，低于此值标记为无效截面
        adj_method: 复权方式（仅支持'后复权'）
    
    返回：
        DataFrame，列: factor_name, ic_value, rank_ic, p_value, 
                       num_stocks, adjusted_ic, source_version
       
    异常：
        ValueError: trade_date 非交易日
        RuntimeError: 数据库连接失败
    """

def compute_batch_ic(
    db_path: str,
    trade_dates: List[str],
    factor_names: List[str],
    forward_window: int = 5,
    min_stocks: int = 30,
    source_version: str = 'v1',
) -> pd.DataFrame:
    """
    批量计算多个截面的因子IC。
    内部调用 compute_cross_sectional_ic，结果写入 a50_cross_ic_result 表。
    
    入参：
        db_path: a50_ic.db 路径
        trade_dates: 截面日期列表（全部为周五/最后交易日）
        factor_names: 因子名列表
        forward_window: 预测窗口
        min_stocks: 最小样本量
        source_version: 版本锚定
    
    返回：
        DataFrame，同 compute_cross_sectional_ic 但含多日期
    """

def compute_forward_return(
    panel_df: pd.DataFrame,
    trade_date: str,
    forward_window: int = 5,
) -> pd.Series:
    """
    计算前向收益。
    
    入参：
        panel_df: 面板数据（含 ts_code, trade_date, close）
        trade_date: 截面日期
        forward_window: 预测窗口（交易日数）
    
    返回：
        Series, index=ts_code, values=forward_return
        forward_return = close[t+forward_window] / close[t] - 1
    
    异常处理：
        - 若 t+forward_window 超出数据范围 → 该股票回报置为NULL
        - 若 t+forward_window 期间有停牌 → 使用实际复牌日的收盘价
          （即：从 t 往后找 forward_window 个实际有价格的交易日）
    """
```

#### 2.3.2 IC核心计算逻辑

```python
def _compute_ic_pair(
    factor_values: pd.Series,
    forward_returns: pd.Series,
) -> Dict:
    """
    计算单因子的截面IC。
    
    入参：
        factor_values: Series, index=ts_code, values=因子值（已过滤NULL）
        forward_returns: Series, index=ts_code, values=前向收益（已过滤NULL）
    
    返回：
        dict: {
            'ic_value': float,        # Pearson相关系数
            'rank_ic': float,         # Spearman秩相关
            'p_value': float,         # p-value
            'num_stocks': int,        # 有效样本数
            'adjusted_ic': float,     # 剔除±3σ极端值后重算
        }
    
    算法：
        1. 取 factor_values 和 forward_returns 的公共 index（ts_code 交集）
        2. 若 len(公共index) < min_stocks → 标记为无效
        3. 计算 Pearson IC: scipy.stats.pearsonr(factor, forward_return)
        4. 计算 Spearman IC: scipy.stats.spearmanr(factor, forward_return)
        5. 计算 adjusted_IC:
           a. 计算 factor 的 z-score
           b. 剔除 |z-score| > 3 的样本
           c. 对剩余样本重算 Pearson IC
        6. 返回结果字典
    """
    # Step 1: 对齐
    common_idx = factor_values.dropna().index.intersection(
        forward_returns.dropna().index
    )
    f = factor_values[common_idx]
    r = forward_returns[common_idx]
    
    n = len(common_idx)
    result = {'num_stocks': n}
    
    if n < min_stocks:
        result.update({
            'ic_value': None,
            'rank_ic': None,
            'p_value': None,
            'adjusted_ic': None,
        })
        return result
    
    # Step 2-4: Pearson & Spearman
    ic_val, p_val = stats.pearsonr(f, r)
    rank_ic_val, _ = stats.spearmanr(f, r)
    
    # Step 5: 调整IC（剔除极端值）
    z = (f - f.mean()) / f.std()
    mask = z.abs() <= 3
    if mask.sum() >= 10:  # 至少10个样本才能重算
        adj_ic_val, _ = stats.pearsonr(f[mask], r[mask])
    else:
        adj_ic_val = None
    
    result.update({
        'ic_value': ic_val,
        'rank_ic': rank_ic_val,
        'p_value': p_val,
        'adjusted_ic': adj_ic_val,
    })
    return result
```

### 2.4 动态截面处理算法

**核心问题**：仅 28.64% 的交易日全体 50 只成分股数据完整，不能使用固定面板。

```python
def get_dynamic_cross_section(
    conn: sqlite3.Connection,
    trade_date: str,
    min_stocks: int = 30,
) -> pd.DataFrame:
    """
    获取动态截面——仅保留该日期实际可用的成分股。
    
    入参：
        conn: SQLite连接
        trade_date: 截面日期(YYYYMMDD)
        min_stocks: 最小样本量阈值
    
    返回：
        DataFrame: columns=[ts_code, close, volume, amount, 
                            adj_factor, pe, pb, return_1d, ...]
        仅包含该截面日期实时在指数成分股中且非停牌的样本。
        若可用样本数 < min_stocks，返回空 DataFrame。
    
    算法（六步过滤）：
    """
    # Step 1: 从 a50_daily_ohlcv 获取该交易日所有可用记录
    sql = """
        SELECT d.* FROM a50_daily_ohlcv d
        WHERE d.trade_date = ?
    """
    df = pd.read_sql(sql, conn, params=[trade_date])
    
    if len(df) < min_stocks:
        return pd.DataFrame()  # 样本量不足，跳过该截面
    
    # Step 2: 过滤停牌股票（null_reason='SUSPENDED'）
    #         或退化条件 (volume=0 AND amount=0)
    if 'null_reason' in df.columns:
        suspended = df['null_reason'] == 'SUSPENDED'
    else:
        suspended = (df['volume'] == 0) & (df['amount'] == 0)
    df = df[~suspended]
    
    if len(df) < min_stocks:
        return pd.DataFrame()
    
    # Step 3: 过滤缺失关键字段的样本
    df = df.dropna(subset=['close', 'adj_factor', 'volume'])
    if len(df) < min_stocks:
        return pd.DataFrame()
    
    # Step 4: 验证成分股资格（查 a50_universe 表）
    #         排除该日期不在指数内的股票
    universe_sql = """
        SELECT ts_code FROM a50_universe
        WHERE in_date <= ? AND (out_date IS NULL OR out_date >= ?)
    """
    valid_codes = pd.read_sql(universe_sql, conn, params=[trade_date, trade_date])
    df = df[df['ts_code'].isin(valid_codes['ts_code'])]
    
    if len(df) < min_stocks:
        return pd.DataFrame()
    
    # Step 5: 加载回看窗口数据（用于因子计算）
    #         回看窗口最大为 120 个交易日（覆盖 momentum_120d）
    lookback_sql = """
        SELECT ts_code, trade_date, close, volume, amount, 
               adj_factor, pe, pb, return_1d
        FROM a50_daily_ohlcv
        WHERE trade_date <= ? 
          AND ts_code IN ({})
        ORDER BY ts_code, trade_date
    """.format(','.join(['?'] * len(df)))
    
    # 获取交易日期列表，确定回看窗口起点
    # ... (简化：查询实际历史交易日)
    
    # Step 6: 计算因子值
    factors_df = compute_all_factors(lookback_df)
    
    return factors_df
```

**周频截面日期选择算法**：

```python
def get_weekly_cross_section_dates(
    conn: sqlite3.Connection,
    start_date: str = "20070104",
    end_date: str = "20260526",
) -> List[str]:
    """
    获取所有周频截面日期。
    
    算法：
        1. 查询 a50_daily_ohlcv 获取所有交易日列表
        2. 按周分组，取每周的最后一个交易日（优先周五）
        3. 若周五非交易日，向前取周四/周三/周二/周一
        4. 过滤掉样本量 < 30 的截面（调用 get_dynamic_cross_section）
        5. 返回过滤后的截面日期列表
    
    返回：
        List[str]，格式 YYYYMMDD
    """
    # Step 1: 所有交易日
    sql = "SELECT DISTINCT trade_date FROM a50_daily_ohlcv ORDER BY trade_date"
    all_dates = pd.read_sql(sql, conn)['trade_date'].tolist()
    
    # Step 2: 转换为 datetime 并分周
    date_series = pd.to_datetime(all_dates, format='%Y%m%d')
    weekly = date_series.to_series().groupby(
        date_series.to_series().dt.isocalendar().year.astype(str) + '-' +
        date_series.to_series().dt.isocalendar().week.astype(str)
    ).last()
    
    # Step 3: 转回 YYYYMMDD
    weekly_dates = weekly.dt.strftime('%Y%m%d').tolist()
    
    # Step 4-5: 过滤：后续在 compute_batch_ic 中处理
    return weekly_dates
```

---

## 3. ETL管线

### 3.1 从 `stock_daily` 提取到 `a50_daily_ohlcv`

```python
# src/data/etl_a50_daily.py

def etl_build_a50_daily(
    source_db: str = r"C:\Users\17699\mozhi_platform\data\market\market_data.db",
    target_db: str = r"C:\Users\17699\mozhi_platform\data\a50_ic\a50_ic.db",
    a50_codes: List[str] = None,
    source_version: str = "v1",
) -> int:
    """
    ETL主函数：从 market_data.db.stock_daily 提取A50成分股数据，
    经清洗、复权后写入 a50_ic.db.a50_daily_ohlcv。
    
    入参：
        source_db: 源数据库路径
        target_db: 目标数据库路径
        a50_codes: A50成分股列表（若为None，从a50_universe获取所有ts_code）
        source_version: 版本锚定
    
    返回：
        int: 写入行数
    
    流程：
        1. 连接源库和目标库（目标库启用 PRAGMA foreign_keys=ON）
        2. 查询 stock_daily 中所有属于 a50_codes 的数据
        3. 按 ts_code + trade_date 排序
        4. 计算后复权价格（§3.2）
        5. 识别停牌（§3.3）
        6. 自计算换手率（§3.1.1）
        7. 写入 a50_daily_ohlcv 表
        8. 运行数据校验（§3.5）
    """
    conn_source = sqlite3.connect(source_db)
    conn_target = sqlite3.connect(target_db)
    conn_target.execute("PRAGMA foreign_keys=ON")
    
    # 确定A50成分股列表
    if a50_codes is None:
        a50_codes = get_all_a50_codes(conn_target)
    
    # 批量查询（按股票分批，避免内存溢出）
    all_rows = []
    for code in a50_codes:
        df = pd.read_sql(
            "SELECT * FROM stock_daily WHERE ts_code = ? ORDER BY trade_date",
            conn_source, params=[code]
        )
        all_rows.append(df)
    
    panel = pd.concat(all_rows, ignore_index=True)
    
    # 后复权
    panel = apply_adjusted_prices(panel)
    
    # 停牌识别
    panel = identify_suspensions(panel)
    
    # 换手率自计算
    panel = calc_turnover_rate(panel)
    
    # 写入目标表
    panel.to_sql('a50_daily_ohlcv', conn_target, if_exists='replace', index=False)
    
    # 创建索引
    create_indexes(conn_target)
    
    conn_source.close()
    conn_target.close()
    
    return len(panel)
```

### 3.2 后复权处理

```python
def apply_adjusted_prices(
    df: pd.DataFrame,
    price_cols: List[str] = ['open', 'high', 'low', 'close'],
) -> pd.DataFrame:
    """
    对价格字段做后复权处理。
    
    算法：
        for col in price_cols:
            df[col] = df[col] * df['adj_factor']
    
    pre_close 处理：
        pre_close 字段是 tushare 返回的前一日收盘原始价，
        后复权后：pre_close_adj[t] 应 ≈ close_adj[t-1]
    
    校验：
        偏差率 = |pre_close_adj[t] - close_adj[t-1]| / close_adj[t-1]
        偏差率 > 0.1% 的记录做日志告警。
    """
    df = df.copy()
    
    for col in price_cols:
        if col in df.columns:
            df[col] = df[col] * df['adj_factor']
    
    # pre_close 后复权
    if 'pre_close' in df.columns:
        df['pre_close'] = df['pre_close'] * df['adj_factor']
    
    # pre_close 一致性校验
    df_sorted = df.sort_values(['ts_code', 'trade_date'])
    df_sorted['close_prev'] = df_sorted.groupby('ts_code')['close'].shift(1)
    df_sorted['pre_close_dev'] = (
        (df_sorted['pre_close'] - df_sorted['close_prev']).abs()
        / df_sorted['close_prev']
    )
    
    violations = df_sorted[df_sorted['pre_close_dev'] > 0.001]
    if len(violations) > 0:
        print(f"[WARN] pre_close 校验失败: {len(violations)}条, "
              f"最大偏差={violations['pre_close_dev'].max():.4%}")
        # 但不停机，数据摸底已确认偏差均来自IPO/重组合法事件
        
    return df
```

### 3.3 停牌识别与过滤

```python
def identify_suspensions(df: pd.DataFrame) -> pd.DataFrame:
    """
    识别停牌日并标记 null_reason。
    
    优先规则（req_draft_v2.1 §4.0）：
        1. 若源表有明确的停牌标记字段 → 优先使用
        2. 退化条件：volume=0 AND amount=0 → 判断为停牌
        3. IPO首日：通过 adj_factor 首次初始化标记（不视为停牌）
    
    写入 null_reason：
        - 正常交易日：null_reason = None
        - 停牌日：null_reason = 'SUSPENDED'，price字段置NULL
        - 数据缺失日：null_reason = 'MISSING'，关键字段置NULL
    """
    # Step 1: 检测停牌（volume=0 AND amount=0 的交易日）
    # 但排除IPO首日：adj_factor首次出现且 > 上一日1.5倍
    is_suspected_suspend = (df['volume'] == 0) & (df['amount'] == 0)
    
    # Step 2: 排除IPO首日（adj_factor突变且首次出现）
    df_sorted = df.sort_values(['ts_code', 'trade_date'])
    df_sorted['adj_prev'] = df_sorted.groupby('ts_code')['adj_factor'].shift(1)
    is_ipo_first_day = df_sorted['adj_prev'].isna() & is_suspected_suspend
    
    # Step 3: 标记停牌
    is_suspend = is_suspected_suspend & ~is_ipo_first_day
    
    # Step 4: 写入 null_reason
    df['null_reason'] = None
    df.loc[is_suspend, 'null_reason'] = 'SUSPENDED'
    
    # Step 5: 停牌日价格置NULL（保留adj_factor沿用前一日值）
    price_cols = ['open', 'high', 'low', 'close', 'pre_close']
    for col in price_cols:
        df.loc[is_suspend, col] = None
    
    df.loc[is_suspend, 'volume'] = 0
    df.loc[is_suspend, 'amount'] = 0
    
    return df
```

### 3.4 `a50_universe` 构建

```python
def build_a50_universe(
    target_db: str,
    index_code: str = "000016.SH",  # 上证50指数代码
    data_source: str = "tushare",
) -> int:
    """
    构建A50成分股历史列表。
    
    数据来源：
        1. tushare index_members API：获取历史成分股调整记录
        2. CSI官网公告：手动补充缺失记录
    
    返回：
        int: 写入行数
    """
    # 实现细节待确认（需实际API调用测试）
    # 伪代码：
    # 
    # 1. 调用 tushare.index_members(index_code, start_date="20040101")
    #    获取每次成分股调整的纳入/剔除记录
    # 2. 解析为 (ts_code, in_date, out_date) 格式
    # 3. 写入 a50_universe 表
    # 4. 为当前成分股（无out_date）标记 out_date=NULL
    #
    # 后备方案：若 tushare API 不提供历史调整记录，
    # 改用手动维护的 CSV 文件首次导入。
```

> **关于 `a50_universe` 的构建**：该表是消除前视偏差的核心依赖。摸底报告已确认50只当前成分股的 `ts_code` 列表，但历史成分股调整记录需通过 tushare API 获取。若 API 不提供，可考虑以下方案：
> - 方案A：利用 `stock_daily` 中各股票的 `trade_date` 最早出现日近似作为 `in_date`
> - 方案B：从 wind / choice 等三方数据库导出历史成分股调整记录
> - **优先级**：方案A（快速）→ 方案B（精确），T+7前确认

### 3.5 数据校验规则

ETL完成后运行以下自动校验：

```python
def validate_etl(target_db: str, log_path: str = None) -> Dict[str, bool]:
    """
    ETL数据质量校验。
    
    检查项：
        [ ] 1. 总行数校验：a50_daily_ohlcv 行数 ≈ 50只 * 4710天 ≈ 235,500
        [ ] 2. 缺失率检查：close/open/high/low/volume/amount/adj_factor 缺失 < 1%
        [ ] 3. pre_close 一致性：偏差率 > 0.1% 的记录 < 总记录 0.1%
        [ ] 4. adj_factor 连续性：无负突变或跳零
        [ ] 5. 停牌标记检查：停牌日 close=NULL, volume=0, amount=0
        [ ] 6. null_reason 分布：停牌占比合理（通常 < 5%）
        [ ] 7. a50_universe 覆盖：所有50只股票均有纳入记录
        [ ] 8. 时间覆盖：2007-01-04 ~ 2026-05-26 无中断
    
    返回：
        dict: {'pass': True/False, 'checks': {...}}
    """
```

### 3.6 ETL TODO 清单

```python
# src/data/etl_a50_daily.py — TODO清单（req_draft_v2.1 §5.2.1）
# [ ] 1. SQLite 连接时设置 PRAGMA foreign_keys=ON
# [ ] 2. 后复权价格计算（close * adj_factor）+ pre_close 一致性校验（偏差<0.1%）
# [ ] 3. 停牌识别逻辑：优先 null_reason，退化 volume=0 AND amount=0
# [ ] 4. a50_universe 表构建：使用成分股在对应时间点的实际构成（消除前视偏差）
# [ ] 5. source_version 版本锚定写入（默认 'v1'，变更需文档记录）
# [ ] 6. 换手率自计算（float_share 可用性验证后启用）
# [ ] 7. pe/pb 缺失率统计（摸底后补充）
```

---

## 4. 黄金基线验证

### 4.1 `momentum_20d` 自计算验证

**验证脚本**：`src/pipeline/golden_baseline.py`

```python
def validate_golden_baseline(
    db_path: str,
    trade_dates: List[str] = None,
    min_stocks: int = 30,
    source_version: str = "v1",
) -> Dict[str, float]:
    """
    黄金基线验证：计算 momentum_20d 的截面IC各项指标。
    
    验证指标（req_draft_v2.1 §4.3.2）：
        - 均值IC绝对值 > 0.02
        - 方向一致性 > 55%
        - IC正比率 > 50%
        - IC标准差 < 0.2
        - p-value 显著比率（< 0.05 占比）> 30%
        - IC半衰期 > 12周
    
    返回：
        dict: 各指标的实测值，如：
        {
            'mean_ic': 0.035,
            'mean_ic_abs': 0.035,
            'ic_positive_ratio': 0.58,
            'ic_std': 0.15,
            'direction_consistency': 0.58,
            'pvalue_significant_ratio': 0.35,
            'ic_half_life_weeks': 15.2,
            'num_valid_periods': 950,
            'pass': True
        }
    
    算法：
        1. 获取全部周频截面日期（get_weekly_cross_section_dates）
        2. 对每个截面日期：
           a. 加载动态截面数据（get_dynamic_cross_section）
           b. 计算 momentum_20d 因子值（§2.2.2）
           c. 计算 5日前向收益
           d. 计算截面IC（_compute_ic_pair）
           e. 写入 a50_cross_ic_result
        3. 汇总统计：均值、标准差、正比率、方向一致性、p-value 分布
        4. 计算 IC 半衰期（ACF自相关衰减到 0.5 的周数）
        5. 返回结果
    """
```

**验证通过后的自动触发动作**：
```python
def check_golden_baseline_gate(result: Dict[str, float]) -> bool:
    """
    检查黄金基线门禁条件（req_draft_v2.1 §5.4 数据就绪门禁）。
    
    硬性条件（全部满足）：
        1. mean_ic_abs > 0.02
        2. direction_consistency > 55%
        3. ic_positive_ratio > 50%
        4. ic_std < 0.2
        5. pvalue_significant_ratio > 30%
        6. ic_half_life_weeks > 12
    
    返回：
        True = 门禁通过，可启动 Phase 1 准备工作
        False = 基线未通过，需要修复
    """
    conditions = [
        result['mean_ic_abs'] > 0.02,
        result['direction_consistency'] > 0.55,
        result['ic_positive_ratio'] > 0.50,
        result['ic_std'] < 0.20,
        result['pvalue_significant_ratio'] > 0.30,
        result['ic_half_life_weeks'] > 12,
    ]
    return all(conditions)
```

### 4.2 验收指标映射

| 指标名 | 计算方式 | 期望值 | 失败时的定位方向 |
|:-------|:---------|:------|:----------------|
| **均值IC** | `mean(ic_value)` over all periods | 绝对值 > 0.02 | 检查复权口径、极端值处理 |
| **方向一致性** | `sum(ic_value与文献方向一致) / total` | > 55% | 方向由实证确认，不预先锁定 |
| **IC正比率** | `sum(ic_value > 0) / total` | > 50% | 检查因子计算逻辑 |
| **IC标准差** | `std(ic_value)` | < 0.2 | 检查极端截面（样本量不足） |
| **p-value显著率** | `sum(p_value < 0.05) / total` | > 30% | 样本量过小或因子无区分度 |
| **IC半衰期** | ACF衰减到0.5的周数（线性插值） | > 12周 | 因子过度依赖于短期噪声 |

**IC半衰期计算**：
```python
def compute_ic_half_life(ic_series: pd.Series) -> float:
    """
    计算IC自相关半衰期（周）。
    
    算法：
        1. 对 IC 序列计算 ACF（lag=1 到 lag=26，即半年）
        2. 找到 ACF 首次衰减到 0.5 以下的 lag
        3. 若从未衰减到 0.5 以下，返回 26（右截断）
        4. 线性插值计算精确半衰期
    
    入参：
        ic_series: 按时间排序的 IC 序列
    
    返回：
        float: 半衰期（周数）
    """
```

---

## 5. 里程碑执行计划

### 5.1 T+0 ~ T+7（2026-05-29 ~ 2026-06-04）：Schema冻结

| 工作项 | 负责 | 工时 | 输出件 |
|:-------|:----|:----:|:-------|
| 确认a50_universe数据来源接口 | 墨衡 | 1d | tushare API 调用示例 |
| pe/pb缺失率专项摸底 | 墨衡 | 0.5d | pe/pb缺失率报告 |
| float_share可用性验证（换手率自计算前提） | 墨衡 | 0.5d | float_share可用性结论 |
| DDL脚本编写与审查 | 墨衡 | 1d | `schema_a50_ic.sql` |
| 墨萱字段口径审查 | 墨萱 | 1d | 审查反馈 |
| 玄知版本锚定机制审查 | 玄知 | 0.5d | 审查反馈 |
| 分歧解决 & Schema冻结签署 | 墨衡 | 0.5d | 冻结签名 |
| 熔断缓冲（若不通过） | 全体 | +1d | T+8最终截止 |

**T+0~T+7 摸底补全项**：
```python
# 补充摸底脚本：src/survey/supplement_survey.py
# 1. pe/pb 缺失率
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN pe IS NULL THEN 1 ELSE 0 END) as pe_null,
    SUM(CASE WHEN pe_ttm IS NULL THEN 1 ELSE 0 END) as pe_ttm_null,
    SUM(CASE WHEN pb IS NULL THEN 1 ELSE 0 END) as pb_null
FROM stock_daily
WHERE ts_code IN (<a50_codes>);

# 2. float_share 可用性
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN float_share IS NULL OR float_share = 0 
        THEN 1 ELSE 0 END) as float_share_missing
FROM stock_daily
WHERE ts_code IN (<a50_codes>);

# 3. total_share 可用性（备用）
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN total_share IS NULL OR total_share = 0 
        THEN 1 ELSE 0 END) as total_share_missing
FROM stock_daily
WHERE ts_code IN (<a50_codes>);
```

### 5.2 T+7 ~ T+14（2026-06-04 ~ 2026-06-11）：数据落库

| 工作项 | 负责 | 工时 | 输出件 |
|:-------|:----|:----:|:-------|
| ETL脚本编写（含复权、停牌识别） | 墨衡 | 2d | `src/data/etl_a50_daily.py` |
| a50_universe 构建脚本 | 墨衡 | 1d | `src/data/build_universe.py` |
| 数据校验脚本 | 墨衡 | 0.5d | `src/data/validate_etl.py` |
| 全量ETL执行 | 墨衡 | 1d(计算) | `a50_daily_ohlcv` 全表 |
| 成分股列表数据落库 | 墨衡 | 0.5d | `a50_universe` 全表 |
| 后复权验证（随机3股×3时间断面） | 墨萱 | 0.5d | 验收报告 |
| 熔断缓冲（若不通过） | 全体 | +1d | T+15最终截止 |

**ETL执行预估**：

```
数据量：~50只股票 × 4710天 ≈ 235,500行
执行时间：本地 SQLite 查询 + 复权计算 ≈ 10-30秒（全量批处理）
内存需求：~500MB（一次加载全部50只）
```

### 5.3 T+14 ~ T+21（2026-06-11 ~ 2026-06-18）：管线跑通

| 工作项 | 负责 | 工时 | 输出件 |
|:-------|:----|:----:|:-------|
| 因子计算函数编写（P0+P1因子） | 墨衡 | 2d | `src/pipeline/cross_sectional_ic.py` |
| 动态截面处理模块 | 墨衡 | 1d | 同上 |
| golden_baseline 验证脚本 | 墨衡 | 1d | `src/pipeline/golden_baseline.py` |
| **黄金基线全量运行** | 墨衡 | 2d(计算) | IC结果写入 `a50_cross_ic_result` |
| 黄金基线验证报告 | 墨衡 | 0.5d | `reports/golden_baseline_v1.md` |
| 墨萱QA验收 | 墨萱 | 1d | QA报告 |
| 玄知管线审查 | 玄知 | 0.5d | 审查意见 |
| 熔断缓冲（基线未通过） | 全体 | +1d | T+22最终截止 |

**基线不通过的修复路径**（req_draft_v2.1 §4.3.3）：

| 失败情形 | 检查清单 | 修复动作 |
|:---------|:---------|:---------|
| 均值IC绝对值 ≤ 0.02 | [ ] 复权口径<br>[ ] 涨跌停处理<br>[ ] 极端值处理 | 修正后重新运行 |
| 方向一致性 ≤ 55% | [ ] 因子公式正确性<br>[ ] 前向收益计算 | 方向由实证确认，不强求正 |
| 有效样本数不足 | [ ] 停牌识别逻辑<br>[ ] min_stocks阈值 | 降低阈值或修正停牌识别 |
| IC偏移预期过大 | [ ] 截面日期选择<br>[ ] 复权基准 | 确认周频日期选择逻辑 |

### 5.4 T+21 ~ T+30（2026-06-18 ~ 2026-06-27）：结果分析

| 工作项 | 负责 | 工时 | 输出件 |
|:-------|:----|:----:|:-------|
| P2/P3因子补齐（若数据可用） | 墨衡 | 2d | 因子扩展代码 |
| 多因子全量计算（15因子） | 墨衡 | 2d(计算) | 完整IC结果写入 |
| 因子相关性矩阵计算 | 墨衡 | 0.5d | 相关性热力图数据 |
| 分市场状态IC分析 | 墨衡 | 1d | 牛/熊/震荡各期IC |
| 多因子截面IC分析报告 | 墨衡 | 1.5d | `reports/multi_factor_ic_v1.md` |
| Phase 1 准备工作（与计算并行） | 墨衡 | 异步 | 报告模板预填充、可视化脚本 |
| 墨萱QA审查 | 墨萱 | 1d | QA报告 |
| 玄知架构审查 | 玄知 | 0.5d | 审查意见 |
| Owner签署 & 交付评审会议 | 全体 | 0.5d | 签署意见 |
| 归档入库 | 墨涵 | 0.5d | 数据资产登记 |

**多因子IC分析报告内容结构**：

```
1. 各因子IC统计汇总（均值、标准差、ICIR、正比率、p-value显著率）
2. 因子相关性矩阵（五大类因子内部关联）
3. 截面IC时序图（15因子叠加，标注关键市场事件）
4. 分市场状态分析（2008年金融危机、2015年股灾、2024年924行情等）
5. 因子分层回测（五分位组合收益）
6. 结论与建议（推荐因子、待优化的因子、后续方向）
```

### 5.5 工时汇总

| 阶段 | 工时（人×天） | 关键路径 |
|:-----|:------------:|:---------|
| T+0~T+7 Schema冻结 | 墨衡4d + 墨萱1d + 玄知0.5d | 墨衡摸底补全 + 墨萱审查 |
| T+7~T+14 数据落库 | 墨衡4.5d + 墨萱0.5d | 墨衡ETL编写 → 全量运行 |
| T+14~T+21 管线跑通 | 墨衡6.5d + 墨萱1d + 玄知0.5d | **黄金基线验证通过（硬性前置）** |
| T+21~T+30 结果分析 | 墨衡7d + 墨萱1d + 玄知0.5d + Owner0.5d | 多因子计算 → 报告 → 评审 |
| **总计** | **墨衡22d + 墨萱3.5d + 玄知1.5d + Owner0.5d ≈ 27.5人天** | |

---

## 附录A：代码文件清单

| 文件 | 阶段 | 用途 |
|:----|:----:|:-----|
| `src/data/etl_a50_daily.py` | T+7~T+14 | 从stock_daily提取+清洗+复权 |
| `src/data/build_universe.py` | T+7~T+14 | 构建a50_universe成分股列表 |
| `src/data/validate_etl.py` | T+7~T+14 | ETL数据质量校验 |
| `src/survey/supplement_survey.py` | T+0~T+7 | 补摸底（pe/pb/float_share） |
| `src/pipeline/cross_sectional_ic.py` | T+14~T+21 | 截面IC计算管线（核心） |
| `src/pipeline/golden_baseline.py` | T+14~T+21 | 黄金基线验证 |
| `src/utils/ic_stats.py` | T+14~T+21 | IC统计工具（half-life等） |
| `sql/schema_a50_ic.sql` | T+0~T+7 | DDL建表脚本 |
| `sql/migrate_v1_to_v2.sql` | 未来 | 版本迁移模板 |
| `reports/golden_baseline_v1.md` | T+14~T+21 | 黄金基线验证报告 |
| `reports/multi_factor_ic_v1.md` | T+21~T+30 | 多因子截面IC分析报告 |

## 附录B：环境与版本信息

| 项目 | 值 |
|:----|:---|
| OS | Windows 10.0.26200 (x64) |
| Python | 待确认（与现有管线一致，建议 ≥ 3.10） |
| SQLite | Python内置 sqlite3 |
| pandas | 待确认（建议 ≥ 2.0） |
| numpy | 待确认 |
| scipy | 待确认（用于pearsonr/spearmanr） |
| tushare | 待确认（用于a50_universe构建） |
| Git | 推荐启用（文档+代码版本管理） |

## 附录C：文件组织结构

```
mozhi_platform/
├── data/
│   ├── market/
│   │   └── market_data.db          # 源库（不修改）
│   └── a50_ic/
│       ├── a50_ic.db               # 🆕 新建
│       └── migrations/             # 🆕 迁移脚本
│           └── migrate_v1_to_v2.sql
├── docs/
│   └── 07_research/
│       └── A50截面IC/
│           ├── req_draft_v2.1.md   # 需求文档
│           ├── data_survey_report.md # 摸底报告
│           └── design_v1.md        # 🆕 本方案设计
├── src/
│   ├── data/
│   │   ├── etl_a50_daily.py       # 🆕
│   │   ├── build_universe.py      # 🆕
│   │   └── validate_etl.py        # 🆕
│   ├── pipeline/
│   │   ├── cross_sectional_ic.py  # 🆕
│   │   └── golden_baseline.py     # 🆕
│   ├── survey/
│   │   └── supplement_survey.py   # 🆕
│   └── utils/
│       └── ic_stats.py            # 🆕
├── reports/
│   ├── golden_baseline_v1.md      # 🆕
│   └── multi_factor_ic_v1.md      # 🆕
└── sql/
    └── schema_a50_ic.sql          # 🆕 DDL
```
