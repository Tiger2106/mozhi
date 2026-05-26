<!--
author: 墨衡
version: E-001 v1.0
created_time: 2026-05-20T22:43+08:00
based_on: E001_cross_source_validation.md (v1.1 定稿), E001_db_schema.md
-->

# E-001 通用数据录入程序方案

> 输入任意股票代码，自动完成多源获取、单位归一化、交叉验证、数据入库的全流程管道。

---

## 一、程序架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    E001IngestionPipeline                    │
│                         主入口                              │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 0: Identity Normalization                             │
│  ├─ 日期格式统一 (20260520 → 2026-05-20)                    │
│  └─ 代码格式归一化 (601857.SH → 601857)                    │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Multi-source Data Fetching                         │
│  ├─ EastMoney   (akshare → primary)                        │
│  ├─ Baostock    (akshare → primary fallback)               │
│  └─ Sina        (akshare → third-source arbitrator)        │
│     (可选: 分钟级明细数据)                                   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Unit Normalization (E-001 Step1)                  │
│  ├─ 单位检测: 手↔股, 元↔分, 元↔厘                          │
│  ├─ 量级推断: ~100x 差异检测                                │
│  └─ 归一化到标准单位                                        │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: Cross-source Validation (E-001 Step2-4)           │
│  ├─ 两源比对 (阈值 0.3%)                                    │
│  ├─ 第三源仲裁 (如提供)                                      │
│  └─ 分钟聚合锚定 (如可用)                                    │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: Write to storage                                  │
│  ├─ PASS/PASS_WITH_NOTE → stock_daily 主表                 │
│  ├─ REPORT/UNIT_ERROR    → staging_raw + 主表 NULL          │
│  └─ Parquet 缓存同步更新                                    │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 5: Audit Logging                                     │
│  ├─ 写入 validation_audit_log                              │
│  └─ 生成每日录入状态摘要                                    │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 核心类设计

```python
# ─── 文件: src/data/e001_ingestion_pipeline.py ───

@dataclass
class IngestionInput:
    """通用管道输入"""
    symbol: str                     # 601857 或 601857.SH
    market: str | None = None      # sh / sz / bj (auto-detect if None)
    start_date: str = "3y_ago"     # 默认近3年
    end_date: str = "today"        # 默认至今
    sources: list[str] | None = None  # 指定使用的源，None=全部可用
    enable_minute: bool = False    # 是否获取分钟级明细
    batch_size: int = 10           # 批量处理的天数（用于限速）


@dataclass
class IngestionResult:
    """管道输出"""
    symbol: str
    success_count: int              # 写入主表的记录数
    report_count: int               # REPORT 记录数
    unit_error_count: int           # UNIT_ERROR 记录数
    total_validated: int            # 总验证记录数
    sources_used: list[str]         # 实际使用的源
    failed_dates: list[str]         # 失败的交易日
    audit_log_ids: list[int]        # 写入的审计日志 ID
    elapsed_seconds: float


class E001IngestionPipeline:
    """
    通用数据录入管道
    职责：从输入股票代码到完成入库的端到端流程
    """

    def __init__(self, 
                 market_data: MarketDataClient,
                 db_path: str = None,
                 config_path: str = None):
        self.market_data = market_data
        self.source_registry = DataSourceRegistry(config_path)
        self.unit_converter = UnitConverter(config_path)
        self.field_mapper = FieldMapper(config_path)
        self.db_conn = self._connect_db(db_path)
        self.validator = CrossSourceValidator(config_path)

    def run(self, input: IngestionInput) -> IngestionResult:
        """主入口"""
        # Step 0: 身份归一化
        normalized = self._normalize_identity(input)

        # 获取该股票的可用数据源列表
        sources = self.source_registry.get_sources_for_symbol(
            normalized.symbol, normalized.market
        )

        # 逐日处理（或逐批处理）
        result = IngestionResult(symbol=normalized.symbol, ...)
        date_range = self._build_date_range(normalized)

        for batch_dates in self._chunk_dates(date_range, input.batch_size):
            for date in batch_dates:
                try:
                    self._process_date(date, normalized, sources, result)
                except Exception as e:
                    logger.error(f"[{normalized.symbol}] {date} 处理失败: {e}")
                    result.failed_dates.append(date)

        return result

    def _process_date(self, date: str, input: IngestionInput,
                      sources: list, result: IngestionResult):
        """处理单个交易日"""
        # Step 1: 获取多源数据
        source_values = self._fetch_multi_source(
            input.symbol, date, sources, input.enable_minute
        )

        # Step 2: 单位归一化
        normalized = self.unit_converter.normalize_all(source_values)

        # Step 3: 交叉验证
        validation = self.validator.validate(
            symbol=input.symbol,
            trade_date=date,
            metric_name=metric,  # 对每个字段分别验证
            source_a=normalized[0],
            source_b=normalized[1],
            source_c=normalized[2] if len(normalized) > 2 else None,
        )

        # Step 4: 写入存储
        self._write_results(input.symbol, date, validation)

        # Step 5: 记审计
        log_id = self._log_audit(validation)
        result.audit_log_ids.append(log_id)
```

---

## 二、数据源注册表 (DataSource Registry)

### 2.1 概念

注册表管理所有可用的 API 数据源，每个源有名称、类型、优先级、质量评级、权重评分。

### 2.2 注册表结构

```python
"""
文件: config/e001_data_sources.yaml
"""

data_sources:
  eastmoney:
    display_name: "东方财富"
    type: api
    module: mozhi_market_data
    method: get_daily
    priority: 1               # 主源优先级（1=最高）
    quality_rating: A         # A/B/C/D
    weight: 1.0               # 仲裁权重
    rate_limit: 0.5           # 请求间隔（秒）
    supports:
      - daily                 # 支持日线
      - minute                # 支持分钟线
      - snapshot              # 支持快照
      - index                 # 支持指数
    unit_default:
      volume: shares          # 默认单位为 股
      amount: yuan            # 默认单位为 元
      price: yuan_per_share
    retrieval_delay: "15:00"  # 盘后数据可用时间

  baostock:
    display_name: "Baostock"
    type: api
    module: mozhi_market_data
    method: get_daily
    priority: 2               # 主源降级
    quality_rating: A
    weight: 0.9
    rate_limit: 0.1
    supports:
      - daily
    unit_default:
      volume: shares
      amount: yuan
      price: yuan_per_share
    retrieval_delay: "17:00"

  sina:
    display_name: "新浪财经"
    type: api
    module: mozhi_market_data
    method: get_daily
    priority: 3               # 第三源仲裁
    quality_rating: B
    weight: 0.85
    rate_limit: 0.3
    supports:
      - snapshot              # 实时快照
      - minute                # 分钟线
    unit_default:
      volume: shares
      amount: yuan
      price: yuan_per_share
    retrieval_delay: null     # 实时
```

### 2.3 支持的数据源类型

| 类型 | 说明 | 是否支持分钟 | 质量评级 |
|:-----|:-----|:-------------|:---------|
| `api` | 标准 HTTP API 数据源 | 部分支持 | A/B |
| `sdk` | SDK/库封装（如 akshare 封装的 baostock） | 不适用 | A |
| `minute_aggregate` | 分钟数据聚合成日线 | 必须支持 | 取决于原始源 |
| `file_cache` | 文件缓存（Parquet） | 不适用 | A（缓存层） |
| `manual` | 人工录入 | 不适用 | C（需人工审核） |

### 2.4 注册表 Python 接口

```python
@dataclass
class DataSourceInfo:
    name: str
    priority: int
    quality_rating: str       # A/B/C/D
    weight: float             # 0.0 ~ 1.0
    supports_minute: bool = False

class DataSourceRegistry:
    """数据源注册表"""

    def __init__(self, config_path: str = "config/e001_data_sources.yaml"):
        self._sources = self._load_config(config_path)

    def get_primary(self) -> DataSourceInfo:
        """获取主源（优先级最高）"""
        return min(self._sources.values(), key=lambda s: s.priority)

    def get_fallback(self) -> DataSourceInfo | None:
        """获取降级源"""
        primary_priority = self.get_primary().priority
        fallbacks = [s for s in self._sources.values()
                     if s.priority > primary_priority]
        return min(fallbacks, key=lambda s: s.priority) if fallbacks else None

    def get_third_source(self) -> DataSourceInfo | None:
        """获取第三仲裁源"""
        ...

    def get_sources_for_symbol(self, symbol: str, market: str) -> list[DataSourceInfo]:
        """根据股票代码获取可用源"""
        # 可通过市场规则过滤（如 bj 市场某些源不支持）
        return sorted(self._sources.values(), key=lambda s: s.priority)

    def get_quality_weight(self, source_name: str) -> float:
        """获取源的质量权重"""
        source = self._sources.get(source_name)
        return source.weight if source else 0.5
```

---

## 三、单位映射表 (Unit Conversion Map)

### 3.1 概念

定义不同数据源之间的单位映射关系。核心用途：
- 检测**手 vs 股**的单位差异（1手 = 100股，量级差 ~100x）
- 检测**元 vs 分**的单位差异（1元 = 100分，量级差 ~100x）
- 将各源的单位归一化为标准单位

### 3.2 映射表结构

```python
"""
文件: config/e001_unit_conversion.yaml
"""

# ─── 标准单位定义 ───
standard_units:
  volume: shares        # 成交量统一为 股
  amount: yuan          # 成交额统一为 元
  price: yuan_per_share # 价格统一为 元/股

# ─── 单位别名与转换关系 ───
units:
  - name: shares
    aliases: ['股', 'share', 'stock', 'shares', 'volume']
    base_unit: shares
    to_base_ratio: 1.0

  - name: lots
    aliases: ['手', 'lot', 'board_lot', 'lots', '手数']
    base_unit: shares
    to_base_ratio: 100.0       # 1手 = 100股

  - name: yuan
    aliases: ['元', 'yuan', 'CNY', '人民币元']
    base_unit: yuan
    to_base_ratio: 1.0

  - name: fens
    aliases: ['分', 'fen', 'cents', '分钱']
    base_unit: yuan
    to_base_ratio: 0.01        # 1分 = 0.01元

  - name: li
    aliases: ['厘', 'li']
    base_unit: yuan
    to_base_ratio: 0.001       # 1厘 = 0.001元（港股分单）

  - name: ten_thousand_yuan
    aliases: ['万元', '万']
    base_unit: yuan
    to_base_ratio: 10000.0     # 1万元 = 10000元

  - name: hundred_million_yuan
    aliases: ['亿元', '亿']
    base_unit: yuan
    to_base_ratio: 100000000.0 # 1亿元 = 1e8元

# ─── 字段默认单位 ───
field_defaults:
  volume:
    standard_unit: shares
    common_sources:
      eastmoney: shares
      baostock: shares
      sina: shares

  amount:
    standard_unit: yuan
    common_sources:
      eastmoney: yuan
      baostock: yuan
      sina: yuan

  open:
    standard_unit: yuan_per_share
    common_sources:
      eastmoney: yuan_per_share
      baostock: yuan_per_share
      sina: yuan_per_share

  high:
    standard_unit: yuan_per_share
    common_sources: *default

  low:
    standard_unit: yuan_per_share
    common_sources: *default

  close:
    standard_unit: yuan_per_share
    common_sources: *default

# ─── 量级检测容差 ───
magnitude_detection:
  threshold_ratio: 100          # 检测 ~100x 量级差异
  tolerance_pct: 15             # 容差 15% (85x ~ 115x 范围内)
  max_diff_before_block: 500    # >500x 差异 → 非单位问题，可能是数据错误
```

### 3.3 Python 接口

```python
class UnitConverter:
    """单位归一化与检测"""

    def __init__(self, config_path: str = "config/e001_unit_conversion.yaml"):
        self._config = self._load_yaml(config_path)

    def normalize(self, value: float, from_unit: str,
                  to_unit: str | None = None) -> float:
        """
        将值从 from_unit 转换到标准单位
        示例:
            normalize(100, 'lots')    → 10000 (shares)
            normalize(5000, 'fens')   → 50.0 (yuan)
        """
        ratio = self._get_conversion_ratio(from_unit, to_unit)
        return value * ratio

    def detect_mismatch(self, value_a: float, unit_a: str,
                        value_b: float, unit_b: str) -> MismatchResult:
        """
        检测单位不匹配
        返回: (is_mismatch, conversion_ratio, reason)
        """
        ratio = self._safe_divide(value_a, value_b)

        # 检查显式单位映射
        explicit_ratio = self._get_conversion_ratio(unit_a, unit_b)
        if explicit_ratio is not None and explicit_ratio != 1.0:
            # 单位映射确认 → 归一化后再判断
            normalized_a = value_a * explicit_ratio
            normalized_b = value_b
            # 如果归一化后 ≈ 一致 → 正常单位转换
            if self._approx_diff(normalized_a, normalized_b) <= 0.3:
                return MismatchResult(False, explicit_ratio, None)
            else:
                # 单位映射已确认，归一化后不一致
                return MismatchResult(False, explicit_ratio, None)

        # 量级推断
        threshold = self._config['magnitude_detection']['threshold_ratio']
        tolerance = self._config['magnitude_detection']['tolerance_pct'] / 100
        max_diff = self._config['magnitude_detection']['max_diff_before_block']

        if ratio is not None and threshold / (1 + tolerance) <= abs(ratio) <= threshold * (1 + tolerance):
            return MismatchResult(True, None, f"UNIT_MISMATCH: ratio ~{ratio:.1f}x")
        if ratio is not None and abs(ratio) > max_diff:
            return MismatchResult(False, None, "DATA_ERROR: ratio too large")

        return MismatchResult(False, None, None)
```

### 3.4 单位自动推断规则

当数据源未提供 `unit` 字段时，按以下规则推断：

| 字段 | 默认单位 | 推断基准 |
|:-----|:---------|:---------|
| volume | 股 (shares) | 东财/新浪返回股数，baostock 返回股数 |
| amount | 元 (yuan) | 所有主流源均返回元 |
| open/high/low/close | 元/股 | 所有主流源均返回元/股 |
| pct_chg | 百分比 | 统一为 %（非浮点小数） |

---

## 四、字段映射表 (Field Mapping)

### 4.1 概念

不同 API 源对同一字段可能有不同的命名、格式或结构。字段映射表统一对齐。

### 4.2 映射表结构

```python
"""
文件: config/e001_field_mapping.yaml
"""

field_mappings:
  # ─── 日线 OHLCV 字段映射 ───
  trade_date:
    standard_name: trade_date
    format: YYYY-MM-DD
    sources:
      eastmoney: 日期         # akshare 列名
      baostock: date          # baostock 列名
      sina: date              # 新浪列名

  open:
    standard_name: open
    format: float
    sources:
      eastmoney: 开盘
      baostock: open
      sina: open

  close:
    standard_name: close
    format: float
    sources:
      eastmoney: 收盘
      baostock: close
      sina: close

  high:
    standard_name: high
    format: float
    sources:
      eastmoney: 最高
      baostock: high
      sina: high

  low:
    standard_name: low
    format: float
    sources:
      eastmoney: 最低
      baostock: low
      sina: low

  volume:
    standard_name: volume
    format: int (shares)
    sources:
      eastmoney: 成交量       # akshare 返回 股
      baostock: volume        # baostock 返回 股
      sina: volume

  amount:
    standard_name: amount
    format: float (yuan)
    sources:
      eastmoney: 成交额
      baostock: amount
      sina: amount

  pct_chg:
    standard_name: pct_chg
    format: float (%)
    sources:
      eastmoney: 涨跌幅
      baostock: pctChg
      sina: pct_change

  # ─── 分钟线字段映射（可选） ───
  minute_time:
    standard_name: time
    format: HH:MM
    sources:
      eastmoney: 时间
      sina: time

  minute_price:
    standard_name: price
    format: float
    sources:
      eastmoney: 成交价
      sina: price

  minute_volume:
    standard_name: volume
    format: int
    sources:
      eastmoney: 成交量
      sina: volume

  # ─── 指数字段 ───
  index_close:
    standard_name: close
    format: float
    sources:
      eastmoney: 收盘
      sina: close

  index_pct_chg:
    standard_name: pct_chg
    format: float (%)
    sources:
      eastmoney: 涨跌幅
      sina: pct_change
```

### 4.3 Python 接口

```python
class FieldMapper:
    """字段名映射与归一化"""

    def __init__(self, config_path: str = "config/e001_field_mapping.yaml"):
        self._mappings = self._load_yaml(config_path)['field_mappings']

    def standardize_name(self, source_name: str, raw_field: str) -> str:
        """将源字段名映射为标准名"""
        for field_name, mapping in self._mappings.items():
            if raw_field in mapping.get('sources', {}).values():
                return mapping.get('sources', {}).get(source_name, raw_field)
        # 精确匹配
        for field_name, mapping in self._mappings.items():
            src = mapping.get('sources', {})
            if src.get(source_name) == raw_field:
                return field_name
        # 未匹配到
        return raw_field

    def get_standard_fields(self) -> list[str]:
        """返回所有标准字段名"""
        return list(self._mappings.keys())

    def get_field_format(self, field: str) -> str:
        """获取标准字段的格式"""
        mapping = self._mappings.get(field)
        return mapping.get('format', 'unknown') if mapping else 'unknown'
```

---

## 五、主处理管道实现

### 5.1 入口函数

```python
# ─── 文件: src/data/e001_ingestion_pipeline.py ───

def run_ingestion(
    symbol: str,
    market: str | None = None,
    start: str | None = None,
    end: str | None = None,
    sources: list[str] | None = None,
    enable_minute: bool = False,
) -> IngestionResult:
    """
    E-001 通用数据录入入口

    用途：任意股票代码的全流程数据录入
    调用示例：
        result = run_ingestion("601857")
        result = run_ingestion("601857.SH", start="2026-01-01", end="2026-05-20")
        result = run_ingestion("000300", market="sh", sources=["eastmoney", "sina"])
    """
    pipeline = E001IngestionPipeline(
        market_data=MarketDataClient(),
        db_path="C:/Users/17699/mo_zhi_sharereports/trade_engine.db",
    )

    input_data = IngestionInput(
        symbol=symbol,
        market=market,
        start_date=start or _default_start(),
        end_date=end or _today(),
        sources=sources,
        enable_minute=enable_minute,
    )

    return pipeline.run(input_data)


def run_batch_ingestion(
    symbols: list[str],
    **kwargs,
) -> list[IngestionResult]:
    """
    批量录入多只股票
    调用示例：
        results = run_batch_ingestion(["601857", "600519", "000001"])
    """
    results = []
    for symbol in symbols:
        results.append(run_ingestion(symbol, **kwargs))
    return results
```

### 5.2 数据获取逻辑

```python
def _fetch_multi_source(
    self, symbol: str, date: str,
    sources: list[DataSourceInfo],
    enable_minute: bool,
) -> list[SourceValue]:
    """
    从多个源获取同一日期的数据
    返回: 按优先级排序的 SourceValue 列表

    限速策略:
        - 两个 API 请求之间间隔 request_gap 秒
        - 失败时自动降级到下一个源
        - 最多重试 retry_times 次
    """
    results = []

    for source in sources:
        try:
            # 从 MarketDataClient 获取数据
            df = self.market_data.get_daily(
                symbol=symbol,
                start=date,
                end=date,
            )

            if df is None or df.empty:
                logger.warning(f"[{symbol}] {source.name} 返回空数据")
                continue

            # 字段映射
            row = df.iloc[0]
            mapped = {}
            for standard_field in self.field_mapper.get_standard_fields():
                raw_name = self.field_mapper._mappings[standard_field]['sources'].get(
                    source.name
                )
                if raw_name in row:
                    mapped[standard_field] = row[raw_name]

            results.append(SourceValue(
                source_name=source.name,
                value=mapped.get('close'),
                raw_value=row.to_dict(),
                unit=source.unit_default.get('volume', 'shares'),
            ))

        except Exception as e:
            logger.warning(f"[{symbol}] {source.name} 获取失败: {e}")
            continue

    return results
```

### 5.3 写入逻辑

```python
def _write_results(
    self, symbol: str, date: str,
    validation: ValidationResult,
) -> None:
    """
    根据验证结果写入存储
    规则:
        PASS / PASS_WITH_NOTE → stock_daily
        REPORT / UNIT_ERROR   → staging_raw + stock_daily 写 NULL
    """
    if validation.verdict in ('PASS', 'PASS_WITH_NOTE'):
        # 写入 stock_daily
        self._upsert_stock_daily(
            symbol=symbol,
            trade_date=date,
            metric_name=validation.field_name,
            value=validation.selected_value,
            source=validation.selected_source,
            status=validation.verdict,
            audit_id=validation.audit_entry.get('id'),
        )
    else:
        # 写入 staging_raw（非阻断）
        self._insert_staging_raw(
            symbol=symbol,
            trade_date=date,
            source_values=validation.audit_entry,
            verdict=validation.verdict,
            diff_reason=validation.diff_reason,
        )
        # 主表字段 NULL
        self._upsert_stock_daily_null(
            symbol=symbol,
            trade_date=date,
            metric_name=validation.field_name,
        )
```

### 5.4 每日状态摘要

```python
def generate_daily_summary(date: str) -> dict:
    """
    生成每日数据录入状态摘要
    输出:
    {
        "date": "2026-05-20",
        "total_symbols": 50,
        "by_verdict": {
            "PASS": 48,
            "PASS_WITH_NOTE": 1,
            "REPORT": 1,
            "UNIT_ERROR": 0,
            "NULL": 0
        },
        "report_symbols": ["601857", ...],
        "unit_errors": [],
        "avg_validation_time_ms": 123
    }
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT verdict, COUNT(*) as cnt
        FROM validation_audit_log
        WHERE trade_date = ?
        GROUP BY verdict
    """, (date,))
    by_verdict = dict(cur.fetchall())

    cur.execute("""
        SELECT DISTINCT symbol
        FROM validation_audit_log
        WHERE trade_date = ? AND verdict = 'REPORT'
    """, (date,))
    report_symbols = [r[0] for r in cur.fetchall()]

    conn.close()

    return {
        "date": date,
        "by_verdict": by_verdict,
        "report_symbols": report_symbols,
        "total_symbols": sum(by_verdict.values()),
    }
```

---

## 六、与现有系统的集成

### 6.1 MarketDataClient 对接

当前 `MarketDataClient`（`mozhi_market_data.py`）**不做 API 层面的修改**。E-001 管道在其基础之上添加交叉验证层：

```
现有调用:
    MarketDataClient.get_daily("601857")
        → 东财(primary) : fail → baostock(fallback)
        → 返回单源 DataFrame

E-001 管道:
    _fetch_multi_source("601857", date)
        → MarketDataClient.get_daily("601857")  # 从主源获取
        → MarketDataClient.get_daily("601857")  # 从降级源获取
          （通过 DataSourceRegistry 配置自动切换源参数）
        → 返回多源 SourceValue[]（用于交叉验证）
```

**关键点**：
- `MarketDataClient` 的 failover 逻辑被 E-001 管道的多源获取逻辑**替代**（而非修改）
- E-001 管道是上层封装，不侵入 `mozhi_market_data.py` 的代码

### 6.2 数据流对比

| 阶段 | 当前流程 | E-001 流程 |
|:-----|:---------|:-----------|
| 数据获取 | 单源 failover（主→备） | 多源并行获取（2-3源） |
| 数据验证 | 无（默认信任单源） | 单位归一化 → 交叉验证 → 仲裁 |
| 数据存储 | Parquet 缓存 | stock_daily (SQLite) + staging_raw |
| 审计 | 无 | validation_audit_log |
| 错误处理 | 抛出异常 | 不阻断，写 staging_raw |

### 6.3 存量数据回填验证

**需要回填的数据集**（按优先级排序）：

| 优先级 | 标的 | 数据量 | 说明 |
|:------|:-----|:-------|:-----|
| P0 | 601857（中国石油） | 近3年 ~730 条 | 当前主要回测标的。**分钟聚合启用**：最近 1 年 |
| P0 | 000001（上证指数） | 近3年 ~730 条 | 市场基准参考。**分钟聚合启用**：最近 1 年 |
| P1 | 600519（贵州茅台） | 近3年 ~730 条 | 已有 Parquet 缓存。**分钟聚合启用**：最近 1 年 |
| P2 | 其他 A50 成分股 | 各近1年 ~250 条 | 扩展覆盖。分钟聚合：暂不启用 |

**回填策略**：
- 对每个标的调用 `run_ingestion(symbol)`，自动从 start_date = 3 years ago 执行
- **P0/P1 标的启用分钟聚合**：
  - P0 标的（601857、000001）调用 `run_ingestion(symbol, enable_minute=True)` 对最近 1 年数据启用分钟聚合验证
  - P1 标的（600519）调用 `run_ingestion(symbol, enable_minute=True)` 对最近 1 年数据启用分钟聚合验证
  - 分钟聚合仅用于验证锚定（`AGGREGATION_ANCHOR`），不替代日线数据获取
  - P2 标的暂不启用分钟聚合
- 回填结果生成 `backfill_{symbol}.json` 报告，分钟聚合验证结果独立记录在 `minute_validation_summary` 字段中

| 场景 | 路径 | 特殊处理 |
|:-----|:-----|:---------|
| **新股票录入**（新股上市） | `run_ingestion(symbol)` → 全量拉取 → 交叉验证 → 写入 | 无 Parquet 缓存，直接通过 stock_daily 作为权威数据源 |
| **存量股票维护**（日更新） | `run_ingestion(symbol, start=today-1)` → 增量拉取 → 交叉验证 → 写入 | 1. 先读本地 Parquet 作为缓存锚定 2. 增量数据与 Parquet 比对验证 3. 如差异大则触发全量回填 |
| **定时批量维护** | `run_batch_ingestion(watchlist)` | 每日收盘后执行，生成每日状态摘要 |

---

## 七、错误处理与重试

### 7.1 错误分类

| 错误类型 | 行为 | 阻断 |
|:---------|:-----|:-----|
| API 超时 | 重试 2 次，间隔 1s | ❌ 不阻断，跳过该源 |
| 数据为空 | 记录日志，降级到下一个源 | ❌ 不阻断 |
| 单位检测为 UNIT_ERROR | 写入 staging_raw | ❌ 不阻断 |
| 交叉验证为 REPORT | 写入 staging_raw + 主表 NULL | ❌ 不阻断 |
| 数据库写入失败 | 重试 2 次，最终写入 FAILED 文件 | ✅ 阻断该条记录 |

### 7.2 幂等性

| 表 | 策略 | 说明 |
|:---|:-----|:-----|
| `stock_daily` | `UNIQUE(trade_date, symbol)` | 同一日期-标的自动去重，重复写入触发 `INSERT OR REPLACE` |
| `validation_audit_log` | **幂等唯一索引** + TTL | 幂等键：`trade_date+symbol+metric_name+source_a_name+source_b_name`，保留最新验证结果。TTL：**保留 90 天**，每日 cron 清理过期记录 |
| `staging_raw` | TTL 清理 | **保留 30 天**，每日 cron 删除 30 天前的 staging_raw 记录 |

**幂等写入逻辑**（适用 `validation_audit_log`）：

```python
def _log_audit(self, validation: ValidationResult) -> int:
    """
    写入审计日志（幂等）
    逻辑：同 trade_date+symbol+metric_name+source_pair 重复时取最新
    """
    # 优先使用 INSERT OR REPLACE 实现幂等
    sql = '''
        INSERT OR REPLACE INTO validation_audit_log (
            trade_date, symbol, metric_name,
            source_a_name, source_a_val, source_a_unit,
            source_b_name, source_b_val, source_b_unit,
            source_c_name, source_c_val, source_c_unit,
            threshold_pct, diff_ab, diff_ac, diff_bc,
            verdict, diff_reason,
            minute_data_source, minute_aggregated, minute_detail_json, is_self_consistency,
            selected_source, selected_value,
            rule_version, triggered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    # 注意：source_a_unit / source_b_unit / source_c_unit
    #   volume/amount 的 unit 在 Phase 1 填充（防止 手↔股 单位混淆）
    #   open/high/low/close/pct_chg 的 unit 标记为 P2（各源单位一致，无需单元转换记录）
    cursor.execute(sql, values)
    return cursor.lastrowid
```

**TTL 清理脚本**（建议由 cron 每日执行）：

```python
def clean_expired_audit_logs(conn, retention_days: int = 90):
    """清理 90 天前的审计日志"""
    conn.execute('''
        DELETE FROM validation_audit_log
        WHERE triggered_at < datetime('now', ?, 'localtime')
    ''', (f'-{retention_days} days',))
    conn.commit()

def clean_expired_staging_raw(conn, retention_days: int = 30):
    """清理 30 天前的 staging_raw 记录"""
    conn.execute('''
        DELETE FROM staging_raw
        WHERE created_at < datetime('now', ?, 'localtime')
    ''', (f'-{retention_days} days',))
    conn.commit()
```

---

## 八、文件组织

```
mozhi_platform/
├── src/
│   ├── data/
│   │   ├── mozhi_market_data.py        # [现有] 行情数据基础库
│   │   └── e001_ingestion_pipeline.py  # [新建] E-001 录入管道
│   │
│   └── validation/
│       ├── cross_source_validator.py   # [新建] E-001 交叉验证实现
│       ├── unit_converter.py           # [新建] 单位归一化
│       ├── data_source_registry.py     # [新建] 数据源注册表
│       └── field_mapper.py            # [新建] 字段映射
│
├── config/
│   ├── e001_data_sources.yaml          # [新建] 数据源注册表配置文件
│   ├── e001_unit_conversion.yaml       # [新建] 单位映射配置文件
│   ├── e001_field_mapping.yaml         # [新建] 字段映射配置文件
│   └── e001_settings.yaml             # [新建] E-001 参数配置（阈值等）
│
└── data/
    ├── knowledge.db                    # [现有] 存放 stock_daily 等权威数据
    └── backtest_data_cache/            # [现有] Parquet 缓存层（不变）
```

---

## 九、测试策略

| 测试类型 | 场景 | 验证点 |
|:---------|:-----|:-------|
| 单元测试 | 单位归一化（手→股, 元→分） | 转换精度、量级检测 |
| 单元测试 | 交叉验证（两源一致 / 不一致） | verdict 正确性 |
| 集成测试 | 601857 全流程录入 | stock_daily 写入 + audit log |
| 集成测试 | 模拟第三源仲裁 | PASS_WITH_NOTE + diff_reason |
| 边界测试 | API 全部失败 | staging_raw 写入 + 主表 NULL |
| 边界测试 | 同一标的重复录入 | 幂等性（UPSERT） |
| 性能测试 | 批量录入 10 只股票 | 完成时间 < 5 分钟 |
