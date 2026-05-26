# 管线集成文档

## 一、架构概览

```
                           +-------------------+
                           |  PipelineOrchestrator  |
                           |  (管线编排器)      |
                           +--------+----------+
                                    |
                    +---------------+---------------+
                    |                               |
            +-------v-------+             +---------v--------+
            |  DataPipeline |             | SignalPipeline   |
            |  (数据管线)    |             | (信号管线)       |
            |  日频因子     |             | 分钟级因子       |
            +-------+-------+             +---------+--------+
                    |                               |
         +---------v----------+            +--------v---------+
         | stock_daily 表     |            | stock_minute 表  |
         | (data_ingestion层) |            | (collector层)    |
         +--------------------+            +------------------+
                            |                        |
                  +---------v--------------------------v--------+
                  |                calc/ 模块库                   |
                  |  (FloatShareCache, TurnoverRate, VolumeRatio, |
                  |   VWAPChannel, VolumeSkewness, VolumePriceCorr,|
                  |   VolumeConcentration)                         |
                  +------------------------------------------------+
```

## 二、管线分类

### 2.1 数据管线（DataPipeline）

| 因子 | 模块来源 | 数据依赖 | 输入字段 |
|------|---------|---------|---------|
| FloatShare（流通股本） | `calc/float_share_cache.py` | Tushare + SQLite 缓存 | symbol, date |
| TurnoverRate（换手率） | `calc/turnover_rate.py` | stock_daily: amount, close | + float_share |
| VolumeRatio（量比） | `calc/volume_ratio.py` | stock_daily: volume | N=20 / N=60 均量 |
| VWAPChannel（VWAP 通道） | `calc/vwap_channel.py` | stock_daily: amount, volume, close | window=20, n=2 |

**使用方式：**
```python
from backtest_engine.pipeline import DataPipeline
dp = DataPipeline()
result = dp.run(symbol='601857', date='20260522')
# result['factors'] 包含: float_share, turnover_rate, volume_ratio_20, volume_ratio_60, vwap_channel
```

### 2.2 信号管线（SignalPipeline）

| 因子 | 模块来源 | 数据依赖 | 说明 |
|------|---------|---------|------|
| VolumeSkewness（量偏度） | `calc/volume_skewness.py` | stock_minute: volume | 尾盘/早盘集中放量检测 |
| VolumePriceCorr（量价相关系数） | `calc/volume_price_corr.py` | stock_minute: volume, close | 量价正/负/中性相关 |
| VolumeConcentration（量集中度） | `calc/volume_concentration.py` | stock_minute: volume | HHI + Gini 系数 |

**使用方式：**
```python
from backtest_engine.pipeline import SignalPipeline
sp = SignalPipeline()
result = sp.run(symbol='601857', date='20260522')
# result['factors'] 包含: volume_skewness, volume_price_corr, volume_concentration
# 每个因子还有 label_en / label_cn 分类标签
```

**前置条件：** 需要 `minute_collector.py` 先采集分钟级数据到 stock_minute 表。若无分钟数据，信号管线返回空结果，不阻断回测。

## 三、完整管线使用

### 快捷入口

```python
from backtest_engine.pipeline import run_pipeline

# 一键运行完整管线
result = run_pipeline(
    symbol='601857',
    date='20260522',
    include_signal=True,       # 是否包含分钟级因子
    minute_freq='5min'         # 分钟频率
)

# result 结构：
{
    'symbol': '601857',
    'date': '20260522',
    'pipeline': 'full',
    'data_pipeline': {           # 数据管线完整结果
        'symbol': '601857',
        'date': '20260522',
        'close': 7.22,
        'volume': 95413273,
        'amount': 686528895.50,
        'factors': {
            'float_share': 16192207.78,
            'turnover_rate': 0.3967,
            'volume_ratio_20': 1.2450,
            'volume_ratio_60': 1.1020,
            'vwap_channel': {
                'vwap': 7.19,
                'upper': 7.45,
                'lower': 6.93,
                'std': 0.13,
                'close_vs_vwap_pct': 0.42,
            },
        },
    },
    'signal_pipeline': {...},     # 信号管线结果（或无分钟数据时带 error）
    'factors_summary': {          # 平铺因子摘要
        'float_share': 16192207.78,
        'turnover_rate': 0.3967,
        'volume_ratio_ma20': 1.2450,
        'vwap': 7.19,
        'vwap_upper': 7.45,
        'volume_skewness': -0.0234,     # 仅当有分钟数据时
        'volume_price_corr': 0.15,
        'volume_concentration_hhi': 0.032,
        ...
    },
}
```

### 编排器实例

```python
from backtest_engine.pipeline import PipelineOrchestrator

orch = PipelineOrchestrator(db_path=r"C:\Users\17699\mo_zhi_sharereports\analysis.db")
result = orch.run_full(symbol='601857', date='20260522', include_signal=True)
```

## 四、采集器集成

分钟级数据采集器 `collector/minute_collector.py` 是信号管线的前置依赖。

```python
from backtest_engine.collector import MinuteCollector

mc = MinuteCollector()
records = mc.collect_single(symbol='601857', date='20260522', freq='5min')
# 采集后自动写入 stock_minute 表，PipelineOrchestrator 可直接读取
```

## 五、回测集成

现有回测流程只需在策略循环中替换：

```python
# 之前：手动计算因子
# 现在：
from backtest_engine.pipeline import run_pipeline

for symbol in universe:
    for date in trading_days:
        result = run_pipeline(symbol, date)
        factors = result['factors_summary']
        # factors['turnover_rate'], factors['volume_ratio_ma20'], ...
        # 直接用于策略信号
```

## 六、Import 路径

| 使用场景 | Import 语句 |
|---------|-------------|
| 全管线快捷函数 | `from backtest_engine.pipeline import run_pipeline` |
| 编排器实例 | `from backtest_engine.pipeline import PipelineOrchestrator` |
| 数据管线 | `from backtest_engine.pipeline import DataPipeline` |
| 信号管线 | `from backtest_engine.pipeline import SignalPipeline` |
| 采集器 | `from backtest_engine.collector import MinuteCollector` |
| 单因子 | `from backtest_engine.calc import calc_turnover_rate` |

所有模块均通过 `backtest_engine/__init__.py` 暴露，回测脚本只需 `import backtest_engine` 即可使用所有子模块。
