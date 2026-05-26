# -*- coding: utf-8 -*-
"""
数据契约层 —— Data Contract

基于 docs/data_ingestion_standard.md §1.1 ~ §1.3 实现。
定义标准字段映射表（Tushare → DB）、类型、单位、约束。

作者: 墨衡 (moheng)
创建时间: 2026-05-22T16:52+08:00
版本: v1.0
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────
# 1. 约束类型枚举
# ──────────────────────────────────────────────

class ConstraintType(Enum):
    NOT_NULL = "NOT NULL"
    NON_NEGATIVE = "≥ 0"           # >= 0
    POSITIVE = "> 0"               # > 0
    RANGE_0_100 = "[0, 100]"       # percentage fields
    RANGE_0_100_PCT = "[0, 100]"   # turnover_rate variants
    DATE_FORMAT_YYYYMMDD = "YYYYMMDD INT"
    UNIQUE_TS = "(ts_code, trade_date)"  # composite unique key
    NON_NEGATIVE_DECIMAL = "DECIMAL ≥ 0"
    NONE = "—"


# ──────────────────────────────────────────────
# 2. 字段元数据定义
# ──────────────────────────────────────────────

@dataclass
class FieldMeta:
    """单个字段的完整元数据"""
    db_name: str                           # DB 字段名
    db_type: str                           # DB 类型（如 DECIMAL(12,2)）
    unit: str                              # 业务单位（元 / 股 / % / —）
    description: str                       # 业务含义
    constraint: ConstraintType             # 约束
    tushare_name: Optional[str] = None     # Tushare Pro 原始字段名（None 表示无对应，需 ETL 填充）
    normalization_rule: Optional[str] = None  # 归一化规则描述（None 表示直接映射）
    nullable: bool = False                 # 是否允许 NULL
    example: Optional[Any] = None          # 示例值


# ──────────────────────────────────────────────
# 3. 标准字段映射表（Tushare → DB）
# ──────────────────────────────────────────────

# 排序：按 DB 字段业务分组排列
STOCK_DAILY_FIELDS: List[FieldMeta] = [
    # ── 标识字段 ──
    FieldMeta(
        db_name="ts_code",
        db_type="VARCHAR(20)",
        unit="—",
        description="股票代码（带交易所后缀，如 601857.SH）",
        constraint=ConstraintType.NOT_NULL,
        tushare_name="ts_code",
        normalization_rule="直接映射",
        example="601857.SH",
    ),
    FieldMeta(
        db_name="trade_date",
        db_type="INT",
        unit="YYYYMMDD",
        description="交易日",
        constraint=ConstraintType.DATE_FORMAT_YYYYMMDD,
        tushare_name="trade_date",
        normalization_rule="可直接存储，不做转换",
        example=20260522,
    ),

    # ── 价格字段（单位：元） ──
    FieldMeta(
        db_name="open",
        db_type="DECIMAL(12,2)",
        unit="元",
        description="开盘价",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="open",
        normalization_rule="直接映射",
        example=7.12,
    ),
    FieldMeta(
        db_name="high",
        db_type="DECIMAL(12,2)",
        unit="元",
        description="最高价",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="high",
        normalization_rule="直接映射",
        example=7.35,
    ),
    FieldMeta(
        db_name="low",
        db_type="DECIMAL(12,2)",
        unit="元",
        description="最低价",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="low",
        normalization_rule="直接映射",
        example=7.08,
    ),
    FieldMeta(
        db_name="close",
        db_type="DECIMAL(12,2)",
        unit="元",
        description="收盘价",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="close",
        normalization_rule="直接映射",
        example=7.22,
    ),
    FieldMeta(
        db_name="pre_close",
        db_type="DECIMAL(12,2)",
        unit="元",
        description="昨收价",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="pre_close",
        normalization_rule="直接映射",
        example=7.15,
    ),
    FieldMeta(
        db_name="change",
        db_type="DECIMAL(12,2)",
        unit="元",
        description="涨跌额",
        constraint=ConstraintType.NONE,
        tushare_name="change",
        normalization_rule="直接映射",
        example=0.07,
    ),
    FieldMeta(
        db_name="pct_chg",
        db_type="DECIMAL(9,2)",
        unit="%",
        description="涨跌幅",
        constraint=ConstraintType.NONE,
        tushare_name="pct_chg",
        normalization_rule="直接映射",
        example=0.98,
    ),

    # ── 量价字段（已归一化） ──
    FieldMeta(
        db_name="volume",
        db_type="BIGINT",
        unit="股",
        description="成交量。约定入库前统一转为股（非手）",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="vol",
        normalization_rule="×100：手 → 股",
        example=158000000,
    ),
    FieldMeta(
        db_name="amount",
        db_type="DECIMAL(20,2)",
        unit="元",
        description="成交金额。约定入库前统一转为元（非千元）",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="amount",
        normalization_rule="×1000：千元 → 元",
        example=1147320000.00,
    ),

    # ── 衍生量价字段 ──
    FieldMeta(
        db_name="turnover_rate",
        db_type="DECIMAL(9,4)",
        unit="%",
        description="换手率（占总股本）",
        constraint=ConstraintType.RANGE_0_100_PCT,
        tushare_name="turnover_rate",
        normalization_rule="直接映射（NULL 保留）",
        nullable=True,
        example=0.8234,
    ),
    FieldMeta(
        db_name="turnover_rate_f",
        db_type="DECIMAL(9,4)",
        unit="%",
        description="换手率（占自由流通股本）",
        constraint=ConstraintType.RANGE_0_100_PCT,
        tushare_name="turnover_rate_f",
        normalization_rule="直接映射（NULL 保留）",
        nullable=True,
        example=1.0512,
    ),
    FieldMeta(
        db_name="volume_ratio",
        db_type="DECIMAL(9,4)",
        unit="—",
        description="量比",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="volume_ratio",
        normalization_rule="直接映射",
        example=0.8500,
    ),

    # ── 估值字段 ──
    FieldMeta(
        db_name="pe",
        db_type="DECIMAL(12,4)",
        unit="—",
        description="市盈率（静态）",
        constraint=ConstraintType.NONE,
        tushare_name="pe",
        normalization_rule="直接映射",
        example=8.5000,
    ),
    FieldMeta(
        db_name="pe_ttm",
        db_type="DECIMAL(12,4)",
        unit="—",
        description="滚动市盈率",
        constraint=ConstraintType.NONE,
        tushare_name="pe_ttm",
        normalization_rule="直接映射",
        example=7.8000,
    ),
    FieldMeta(
        db_name="pb",
        db_type="DECIMAL(12,4)",
        unit="—",
        description="市净率",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="pb",
        normalization_rule="直接映射",
        example=1.0500,
    ),

    # ── 股本字段（单位：股） ──
    FieldMeta(
        db_name="total_share",
        db_type="DECIMAL(16,2)",
        unit="股",
        description="总股本",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="total_share",
        normalization_rule="直接映射",
        example=18302000000.00,
    ),
    FieldMeta(
        db_name="float_share",
        db_type="DECIMAL(16,2)",
        unit="股",
        description="流通股本",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="float_share",
        normalization_rule="直接映射",
        example=18302000000.00,
    ),
    FieldMeta(
        db_name="free_float_share",
        db_type="DECIMAL(16,2)",
        unit="股",
        description="自由流通股本",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="free_float_share",
        normalization_rule="直接映射",
        example=18302000000.00,
    ),

    # ── 市值字段（单位：元） ──
    FieldMeta(
        db_name="total_mv",
        db_type="DECIMAL(20,2)",
        unit="元",
        description="总市值",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="total_mv",
        normalization_rule="直接映射",
        example=132000000000.00,
    ),
    FieldMeta(
        db_name="circ_mv",
        db_type="DECIMAL(20,2)",
        unit="元",
        description="流通市值",
        constraint=ConstraintType.NON_NEGATIVE,
        tushare_name="circ_mv",
        normalization_rule="直接映射",
        example=132000000000.00,
    ),

    # ── 系统字段（由 ETL 写入层填充，无 Tushare 对应字段） ──
    FieldMeta(
        db_name="data_source",
        db_type="VARCHAR(20)",
        unit="—",
        description="数据来源标记（如 tushare_pro）",
        constraint=ConstraintType.NOT_NULL,
        normalization_rule="静态赋值：tushare_pro",
        example="tushare_pro",
    ),
    FieldMeta(
        db_name="version",
        db_type="VARCHAR(10)",
        unit="—",
        description="清洗版本号（如 v1.0）",
        constraint=ConstraintType.NOT_NULL,
        normalization_rule="赋值当前清洗版本号",
        example="v1.0",
    ),
    FieldMeta(
        db_name="created_at",
        db_type="DATETIME",
        unit="—",
        description="入库时间",
        constraint=ConstraintType.NOT_NULL,
        normalization_rule="赋值当前系统时间",
        example="2026-05-22 16:52:00",
    ),
]

# ──────────────────────────────────────────────
# 4. 符号表构建（快速查找）
# ──────────────────────────────────────────────

# DB 字段名 → FieldMeta
FIELD_BY_DB: Dict[str, FieldMeta] = {f.db_name: f for f in STOCK_DAILY_FIELDS}

# Tushare 字段名 → FieldMeta
FIELD_BY_TUSHARE: Dict[str, FieldMeta] = {f.tushare_name: f for f in STOCK_DAILY_FIELDS if f.tushare_name is not None}

# DB 字段名列表（用于 SQL CREATE TABLE / INSERT 排序）
DB_FIELD_NAMES: List[str] = [f.db_name for f in STOCK_DAILY_FIELDS]

# Tushare 字段名列表（拉取时的字段顺序）
TUSHARE_FIELD_NAMES: List[str] = [f.tushare_name for f in STOCK_DAILY_FIELDS if f.tushare_name is not None]


# ──────────────────────────────────────────────
# 5. SQL DDL 生成
# ──────────────────────────────────────────────

DDL_TEMPLATE = """
CREATE TABLE IF NOT EXISTS stock_daily (
{columns},
    PRIMARY KEY (ts_code, trade_date)
);
"""


def generate_ddl() -> str:
    """生成 stock_daily 表的 DDL"""
    col_defs = []
    for f in STOCK_DAILY_FIELDS:
        nullable = "NULL" if f.nullable else "NOT NULL"
        col_defs.append(f"    `{f.db_name}` {f.db_type} DEFAULT NULL COMMENT '{f.description} [{f.unit}]'")
    # 最后追加 PRIMARY KEY
    return DDL_TEMPLATE.format(columns=",\n".join(col_defs))


def generate_raw_ddl() -> str:
    """生成 stock_daily_raw 表的 DDL（保留 Tushare 原始结构 + batch_id + created_at）"""
    raw_fields = [
        "    `ts_code` VARCHAR(20) NOT NULL COMMENT '股票代码'",
        "    `trade_date` INT NOT NULL COMMENT '交易日 YYYYMMDD'",
        "    `open` DECIMAL(12,2) COMMENT '开盘价'",
        "    `high` DECIMAL(12,2) COMMENT '最高价'",
        "    `low` DECIMAL(12,2) COMMENT '最低价'",
        "    `close` DECIMAL(12,2) COMMENT '收盘价'",
        "    `pre_close` DECIMAL(12,2) COMMENT '昨收价'",
        "    `change` DECIMAL(12,2) COMMENT '涨跌额'",
        "    `pct_chg` DECIMAL(9,2) COMMENT '涨跌幅'",
        "    `vol` BIGINT COMMENT '成交量（原始单位：手）'",
        "    `amount` DECIMAL(20,2) COMMENT '成交额（原始单位：千元）'",
        "    `turnover_rate` DECIMAL(9,4) COMMENT '换手率'",
        "    `turnover_rate_f` DECIMAL(9,4) COMMENT '换手率（自由流通）'",
        "    `volume_ratio` DECIMAL(9,4) COMMENT '量比'",
        "    `pe` DECIMAL(12,4) COMMENT '市盈率'",
        "    `pe_ttm` DECIMAL(12,4) COMMENT '滚动市盈率'",
        "    `pb` DECIMAL(12,4) COMMENT '市净率'",
        "    `total_share` DECIMAL(16,2) COMMENT '总股本'",
        "    `float_share` DECIMAL(16,2) COMMENT '流通股本'",
        "    `free_float_share` DECIMAL(16,2) COMMENT '自由流通股本'",
        "    `total_mv` DECIMAL(20,2) COMMENT '总市值'",
        "    `circ_mv` DECIMAL(20,2) COMMENT '流通市值'",
        "    `batch_id` VARCHAR(32) NOT NULL COMMENT '批次 ID'",
        "    `created_at` DATETIME NOT NULL COMMENT '入库时间'",
    ]
    return "CREATE TABLE IF NOT EXISTS stock_daily_raw (\n" + \
           ",\n".join(raw_fields) + \
           "\n);\nCREATE INDEX IF NOT EXISTS idx_sdr_batch ON stock_daily_raw(batch_id);"


# ──────────────────────────────────────────────
# 6. 新增标的配置模板
# ──────────────────────────────────────────────

NEW_SYMBOL_TEMPLATE = {
    "ts_code": "<带交易所后缀的完整代码>",
    "name": "<股票简称>",
    "exchange": "<SSE / SZSE / BSE>",
    "source": "tushare_pro",
    "start_date": "<YYYYMMDD>",
    "batch_size": 3000,
    "fields": list(TUSHARE_FIELD_NAMES),
}


def build_symbol_config(
    ts_code: str,
    name: str,
    exchange: str,
    start_date: int,
    batch_size: int = 3000,
) -> Dict[str, Any]:
    """构建新增标的配置字典"""
    return {
        "ts_code": ts_code,
        "name": name,
        "exchange": exchange,
        "source": "tushare_pro",
        "start_date": start_date,
        "batch_size": batch_size,
        "fields": list(TUSHARE_FIELD_NAMES),
    }


# ──────────────────────────────────────────────
# 7. 版本号管理
# ──────────────────────────────────────────────

CURRENT_VERSION: str = "v1.0"

# 版本号：v<major>.<minor>
# 递增规则：
#   - 新增字段、新增校验规则 → minor +1
#   - 归一化逻辑变更、字段类型变更 → major +1
#   - 仅修改映射但未改变值语义（如字段重命名） → minor +1
