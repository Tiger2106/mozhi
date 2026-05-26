<!--
author: 墨衡 (moheng)
version: v1.2
version_schema: v2
version_status: v1.2 P1 修复完成 — 待 Owner 签署
created_time: 2026-05-25T21:05+08:00
updated_time: 2026-05-25T23:00+08:00
task: E-002 数据质量管线 — 统一股票日线灌入程序
based_on: 分析会共识 (2026-05-25) + E-001 设计文档 + data_qc_check.py 运行经验 + adj_factor 多源验证试验结果
-->

# E-002 数据质量管线方案设计

> **核心命题**：建立统一股票日线数据灌入程序，替代临时脚本体系，系统性解决送转股误判、QC 阈值无语境、QFQ 基期漂移、排除决策不可复现四大数据质量问题。
>
> **author:** 墨衡 (deepseek-reasoner)
> **version:** v1.2
> **version_schema:** v2
> **version_status:** v1.2 P1 修复完成 — 待 Owner 签署
>
> **关联 E-001:** `docs/algorithms/E001_data_ingestion.md`
> **关联 EXP-2026-INVFAC-002:** `docs/07_research/EXP-2026-INVFAC-002/design.md`

---

## 〇、问题定义（执行前必须通过）

### 0.1 现状描述

当前墨枢系统的日线数据灌入使用临时脚本 `phase1_data_collection.py`，流程为：

```
Tushare API → DataFrame → INSERT OR REPLACE → stock_daily
```

无任何校验步骤。已暴露以下具体问题：

| # | 问题 | 证据 | 严重度 |
|:-:|:-----|:-----|:------:|
| 1 | **送转股误判** — 300750 adj_factor 跳变 +81.2% 为正常送转，但 >50% 硬阈值导致手动排除 | run_exp_invfac002.py 注释: "300750 排除: 送转股导致 adj_factor 跳变" | **高** |
| 2 | **volume/amount 单位混存** — 不同数据源（东财 vs Tushare）的 volume 单位不一致（股 vs 手），但数据库无单位标注 | E-001 单位映射表设计 | **高** |
| 3 | **QC 阈值无语境** — adj_factor 变化率固定 50%，无法区分送转股（>50% 合理）与数据错误 | data_qc_check.py:118 | **高** |
| 4 | **标的池硬编码** — 12 只标的写死，新增标的需要改代码 | run_exp_invfac002.py:42-46 | **中** |
| 5 | **QFQ 基期漂移** — `adj_factor[-1]` 随数据追加变化，同一天的前复权价格在不同时间运行结果不同 | run_exp_invfac002.py:68-70 | **中** |
| 6 | **排除决策不可复现** — 300750 排除而 600276 保留，无书面原则和程序化判定 | 无 exclusion_log | **高** |
| 7 | **4 只缺失标的** — 000651/000858/002714/601166 不在当前池中 | 12 只 vs A50 16 只 | **中** |

### 0.2 不解决的后果

1. **数据污染持续积累** — 无校验的灌入程序允许任何异常数据直接写入 stock_daily，错误数据会通过复权计算传递到全部历史区间
2. **回测复现性丧失** — QFQ 基期漂移 + 排除决策不可复现，同一试验在不同时间运行结果不同
3. **标的覆盖受限** — 硬编码 12 只 + 手动排除逻辑导致扩展困难，新增标的需要人工修改代码
4. **试验结论可信度存疑** — 送转股误判导致 300750 被排除，而类似情况的 600276 保留，选择偏见影响试验结论

### 0.3 根因分析

- **第一层（直接原因）**：当前日线数据灌入无统一入口、无校验层、无审计日志
- **第二层（间接原因）**：无语境感知的 QC 阈值（单一 50% 无法区分送转股与数据错误），无系统化的送转股处理原则
- **第三层（系统性原因）**：质量保障架构不完整——缺少录入后例行健康检查、试验前 QC 检查与录入校验之间的职责划分不清晰

### 0.4 问题陈述

**墨枢系统**在**日线数据灌入**场景下，因**无统一的灌入程序、无校验层、无语境感知的 QC 阈值、无系统化的送转股处理原则及 QFQ 基期锁定机制**，导致**数据质量无法系统性保障、回测复现性受损、标的扩展困难**。

### 0.5 通过条件核查

| 条件 | 负责方 | 状态 |
|:-----|:-------|:----:|
| 现状有数据支持 | 墨衡 | ✅ |
| 影响范围和紧急性已评估 | 墨衡 | ✅ |
| 根因至少到第三层 | 墨衡 | ✅ |
| 问题陈述团队认可 | — | ⬜ |
| 写入任务文档 | 墨衡 | ✅ |

---

## 一、设计目标与范围

### 1.1 设计目标

1. **统一入口**：所有日线数据走统一灌入程序，替代 `phase1_data_collection.py` 的临时脚本体系
2. **校验前置**：入库前完成行数、字段、数值合理性的多维度校验
3. **审计可追溯**：每次灌入操作写入 batch_audit 审计日志表
4. **标的管理配置化**：标的池从硬编码改为 YAML/JSON 配置文件
5. **增量与全量兼容**：支持首次全量重灌（解决单位混存问题）和每日增量更新
6. **送转股语境感知**：QC 阈值从固定 50% 升级为多维语境判定
7. **QFQ 基期锁定**：锁定基期日期，确保回测复现性
8. **排除决策可程序化复现**

### 1.2 设计范围

**核心范围（P0）**：统一日线数据灌入程序，包括：
- 单入口架构
- staging 层 + batch_commit 原子写入
- batch_audit 审计日志表
- 13 条 QC 规则（复用 data_ingestion_standard.md 规范）
- 与 E-001 cross_source_validator 的集成关系

**扩展范围（P1）**：简化版 QC 检查（~5 项，墨萱确认）
**补充范围（P2）**：QFQ 基期修复 + exclusion_log 表

**不在本次范围内**：
- 多源交叉验证（E-001 独立处理）
- 分钟数据灌入
- 数据库 schema 完整重构

### 1.3 与 E-001 的关系

| 维度 | E-001 | E-002（本方案） |
|:-----|:------|:----------------|
| 定位 | 独立完整数据录入管道（含多源获取→单位归一化→交叉验证→自写入→自审计全流程） | 统一单源数据灌入程序（合理性校验→语境分析→审计日志） |
| 适用场景 | 多源可用的优先路径 | 单源/多源均可 |
| 核心方法 | + 交叉比对 + 单位归一化 + 仲裁 | 合理性校验 + 语境分析 + 审计日志 |
| 审计表 | **validation_audit_log**（E-001 独有） | **batch_audit**（本方案新增，见 §2.3） |
| staging_raw 共用 | ✅ staging_raw 表两套程序共用，写入逻辑需确认不冲突 |
| enable_e001=True 时的调度关系 | **E-002 是上层调度，E-001 是独立管道**：E-002 调用 E-001 的执行结果，用 E-001 的验证结论替代 E-002 自有 QC |
| enable_e001=False 时的隔离关系 | E-002 独立工作，不涉及 E-001 的任何组件 |

**修正说明（v1.2）**：
> E-001 **不是** E-002 的 validator 子模块。E-001 本身是一个完整、独立的录入管道（包含数据获取、单位归一化、交叉验证、自写入、自审计全流程）。
> E-002 调用 E-001 不应理解为

### 1.4 验证依据 — adj_factor 多源交叉验证结果

> 基于 2026-05-25 运行的 adj_factor 多源验证试验，对标区间 2020-01-01 至 2025-05-25，覆盖 300750.SZ / 601857.SH / 600276.SH 三只标的。

#### 1.4.1 验证方法

**对比源：**
| 源 | 字段 | 计算方法 |
|:--:|:----:|:--------|
| **Tushare** | `adj_factor` | 复权因子，累积效应，基期接近 1 |
| **akshare** | `qfq / raw` 比值 | 前复权价/原始价，等价于 1 / cum_factor |

**验证逻辑：** 对每个标的的每个交易日计算 `TS_norm = adj_factor / adj_factor_max` 与 `AK_norm = qfq_raw_ratio / max(qfq_raw_ratio)`，比较两者归一化后的差异。同时验证 `adj_factor * cum_factor = 常数`（理论恒等式）。

#### 1.4.2 三标的验证结果

| 标的 | 对比天数 | TS adj_factor 范围 | AK qfq/raw 范围 | 常数 C CV | 归一化最大差异 | 结论 |
|:---:|:-------:|:-----------------:|:---------------:|:---------:|:-------------:|:----:|
| **300750.SZ** | 1304 | [1.0019, 1.9125] | [0.5138, 0.9810] | 0.018% | < 0.05% | ✅ 完全一致 |
| **601857.SH** | 1304 | [1.3405, 1.7025] | [0.7465, 0.9480] | 0.090% | < 0.05% | ✅ 一致 |
| **600276.SH** | 1304 | [44.3574, 65.2107] | [0.6801, 1.0000] | 0.006% | < 0.05% | ✅ 完全一致 |

**结论：** 三个标的 Tushare adj_factor 与 akshare qfq/raw 比值经归一化后，最大差异 < 0.05%，表明两源数据的调整时点与幅度完美匹配。

#### 1.4.3 300750 2023-04-26 升水验证

**背景：** 300750 在 2023-04-26 经历送转（10转增8）+ 现金分红（2.52元/股），Tushare adj_factor 从 1.0055 跳变至 1.8218（×1.8118），与纯送转理论值 ×1.8 存在 0.66% 差异。

**验证：**
| 项目 | 值 |
|:-----|:----|
| 送转比例 (stk_div) | 0.8（10转增8） |
| 现金分红 (cash_div) | 2.52 元/股 |
| 前收盘价 | 385.90 元 |
| 完整除权公式 | (385.90 - 2.52) / (1 + 0.8) = 210.99 元 ×× |
| adj_factor 理论变化系数 | 385.90 / 210.99 = 1.8118 |
| 实际 TS adj_factor 变化 | 1.8218 / 1.0055 = 1.8118 |
| 差异 | **0.00%** — 完全匹配 ✅ |

**结论：** 差异完全由现金分红解释。adj_factor 变化系数 = 1 / ((close_before - cash_div) / (1 + stk_div) / close_before) = close_before × (1 + stk_div) / (close_before - cash_div)。0.66% 并非升水/贴水误差，而是现金分红的正常效应 ✅

#### 1.4.4 Dividend 事件日历多源对比

| 标的 | Tushare vs cninfo | 置信度 | 说明 |
|:---:|:-----------------:|:------:|:-----|
| **300750.SZ** | ✅ 完全一致 | 高 | stk_div 与 cninfo (送股+转增)/10 完全匹配；cash_div 精确匹配（含年度+特别分红合并值） |
| **601857.SH** | ✅ 基本一致 | 中高 | 2016 年前早期分红存在约 10% 差异（含税/不含税口径）；2016 年后（含）全部精确匹配 |
| **600276.SH** | ✅ 完全一致 | 极高 | 送转+分红均精确匹配；早期微小差异由含税口径引起 |

**结论：** Dividend 事件日历三源（Tushare / akshare-cninfo / akshare-sina）在实施阶段数据高度一致。仅 2016 年前 601857 存在含税口径差异，不影响 QC 语境判定和送转股识别。

#### 1.4.5 验证总体结论

| 验证项 | 结果 | 置信度 |
|:-------|:----:|:------:|
| adj_factor 多源一致性（三标的 ×1304 个交易日） | ✅ 通过 | 极高 |
| adj_factor × cum_factor = 常数（理论恒等式） | ✅ 通过（CV < 0.1%） | 极高 |
| 送转+分红复合调整验证（300750 2023-04-26） | ✅ 通过（差异 0.00%） | 极高 |
| Dividend 事件日历一致性 | ✅ 通过 | 高 |

**总体结论：Tushare adj_factor 与 akshare 前复权/原始价比值内在一致，两源数据可互信。** E-002 的 QC 校验层可以直接依赖 Tushare adj_factor 作为真实参考基准，无需额外引入多源仲裁逻辑。送转股检测中的语境阈值（QC-10/QC-11/§3.4）也可基于此结论进一步优化。

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    UnifiedIngestionPipeline                     │
│                        统一日线灌入程序                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 0: 任务初始化                                              │
│  ├─ 读取标的池配置 (symbols_config.yaml)                         │
│  ├─ 确定灌入模式: FULL_RELOAD | INCREMENTAL                     │
│  └─ 创建 batch_id (UUID v4)                                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: 数据获取                                               │
│  ├─ Tushare API (primary): fetch_stock_daily                    │
│  └─ 降级源 (可选): falls back to EastMoney via akshare          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: QC 校验层 (13 条规则)                                   │
│  ├─ §3.1 行数完整性检查                                          │
│  ├─ §3.2 字段合理性检查                                          │
│  ├─ §3.3 数值范围检查                                            │
│  ├─ §3.4 adj_factor 变化率语境检查                               │
│  ├─ §3.5 除权除息日多日上下文检查                                 │
│  └─ ⬜ 可选: E-001 cross_source_validator                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Staging 层 + 原子写入                                   │
│  ├─ QC 通过 (PASS/PASS_WITH_NOTE) → stock_daily 主表            │
│  ├─ QC 未通过 (REPORT)          → staging_raw + NULL            │
│  └─ COMMIT 仅在批次全部写入成功后执行                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: 审计日志写入                                            │
│  ├─ 写入 batch_audit 表 (批次级)                                 │
│  └─ 写入 QC 明细到 batch_audit_detail 表                          │
│                                                                  │
│  Step 5: 后处理                                                  │
│  ├─ 更新标的池元数据 (latest_date, status)                       │
│  └─ 生成灌入报告 JSON                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 单入口设计

```python
# ─── 文件: src/data/unified_ingestion.py ───
# 单入口：所有日线数据灌入均通过此程序

@dataclass
class IngestionTask:
    """灌入任务定义"""
    symbols: list[str]               # 标的列表
    start_date: str                  # 起始日期 YYYYMMDD
    end_date: str                    # 截止日期 YYYYMMDD
    mode: str = "INCREMENTAL"        # FULL_RELOAD | INCREMENTAL
    enable_e001: bool = False        # 是否启用 E-001 增强校验
    force_reingest: bool = False     # 强制重灌（即使已存在）


class UnifiedIngestionPipeline:
    """
    统一股票日线灌入程序（P0 核心）
    全部日线数据走此入口，无例外。
    """

    def __init__(self, config_path: str = "config/ingestion_config.yaml"):
        self.config = self._load_config(config_path)
        self.symbol_registry = SymbolRegistry(config_path)
        self.qc_engine = QCEngine(config_path)
        self.e001_validator = None  # 按需初始化

    def run(self, task: IngestionTask) -> IngestionResult:
        """主入口：执行一次灌入任务"""
        batch_id = str(uuid4())
        self._init_batch(batch_id, task)

        results = []
        for symbol in task.symbols:
            # 获取标的元信息（市场代码、名称等）
            meta = self.symbol_registry.get(symbol)
            
            # 获取数据
            df_raw = self._fetch_data(symbol, task.start_date, task.end_date)

            # QC 校验
            qc_result = self.qc_engine.validate(df_raw, symbol, meta)

            # 可选 E-001 增强
            if task.enable_e001 and self.e001_validator:
                e001_result = self.e001_validator.validate(symbol, df_raw)
                qc_result = self._merge_qc_results(qc_result, e001_result)

            # Staging 原子写入
            commit_id = self._staging_commit(batch_id, symbol, df_raw, qc_result)

            # 审计
            self._log_audit(batch_id, symbol, qc_result, commit_id)

            results.append(IngestionSymbolResult(
                symbol=symbol, qc_result=qc_result, commit_id=commit_id
            ))

        batch_summary = self._finalize_batch(batch_id, results)
        return IngestionResult(batch_id=batch_id, symbols=results, summary=batch_summary)
```

### 2.3 batch_audit 审计日志表设计

```sql
-- ─── 批次级审计日志主表 ───
CREATE TABLE IF NOT EXISTS batch_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        TEXT    NOT NULL UNIQUE,       -- UUID v4
    mode            TEXT    NOT NULL,               -- FULL_RELOAD | INCREMENTAL
    started_at      TEXT    NOT NULL,               -- ISO8601+08:00
    completed_at    TEXT,                           -- ISO8601+08:00
    total_symbols   INTEGER NOT NULL,               -- 计划灌入的标的总数
    success_symbols INTEGER NOT NULL DEFAULT 0,     -- 成功处理的标的数
    failed_symbols  INTEGER NOT NULL DEFAULT 0,     -- 失败的标的数
    total_records   INTEGER NOT NULL DEFAULT 0,     -- 总记录数
    report_records  INTEGER NOT NULL DEFAULT 0,     -- QC REPORT 记录数
    qc_config_hash  TEXT,                           -- QC 规则配置哈希
    global_verdict  TEXT    NOT NULL,               -- PASS | PASS_WITH_NOTE | REPORT
    detail_summary  TEXT,                           -- JSON 摘要
    created_by      TEXT    NOT NULL DEFAULT 'unified_ingestion',
    e001_batch_id   TEXT,                           -- 【v1.2 新增】关联 E-001 的 batch_id 建立跨表关联
                                                    -- NULL 表示本次未使用 E-001
                                                    -- 非 NULL 时可 JOIN E-001.validation_audit_log
    UNIQUE(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_batch_audit_completed
    ON batch_audit(completed_at);

-- ─── QC 明细表（每条记录对应一只标的×一个交易日） ───
CREATE TABLE IF NOT EXISTS batch_audit_detail (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        TEXT    NOT NULL,               -- 关联 batch_audit
    symbol          TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,               -- YYYY-MM-DD
    check_name      TEXT    NOT NULL,               -- QC 规则名称（见 §3）
    verdict         TEXT    NOT NULL,               -- PASS | REPORT
    detail          TEXT,                           -- JSON：具体检查值
    triggered_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (batch_id) REFERENCES batch_audit(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_detail_batch
    ON batch_audit_detail(batch_id);

CREATE INDEX IF NOT EXISTS idx_audit_detail_symbol
    ON batch_audit_detail(symbol);

-- ─── Staging 层 ───
-- staging_raw 表复用于存储 QC 未通过时的原始数据
-- （若 E-001 已有此表则直接复用）
CREATE TABLE IF NOT EXISTS staging_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,
    raw_json        TEXT    NOT NULL,               -- 原始数据的完整 JSON
    verdict         TEXT    NOT NULL,               -- REPORT | UNIT_ERROR
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (batch_id) REFERENCES batch_audit(batch_id)
);
```

### 2.4 原子写入机制

```python
def _staging_commit(self, batch_id: str, symbol: str,
                     df: pd.DataFrame, qc_result: QcResult) -> str:
    """
    批次级原子写入。

    规则：
    - QC PASS / PASS_WITH_NOTE → 写入 stock_daily 主表
    - QC REPORT → 写入 staging_raw + 主表该行 validation_status='REPORT'
    - COMMIT 仅在 batch 内全部处理完成后执行，不逐行 commit
    """
    conn = self._get_conn()
    try:
        cur = conn.cursor()
        for _, row in df.iterrows():
            date_str = row['trade_date']
            
            # 检查该行 QC 结果
            row_verdict = qc_result.get_verdict_for_date(date_str)

            if row_verdict in ('PASS', 'PASS_WITH_NOTE'):
                # 写入主表（INSERT OR REPLACE 确保幂等）
                cur.execute("""
                    INSERT OR REPLACE INTO stock_daily
                    (code, date, open, high, low, close, volume, amount,
                     adj_factor, free_float, turnover_rate, validation_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, date_str, row['open'], row['high'], row['low'],
                      row['close'], row['volume'], row['amount'],
                      row['adj_factor'], row.get('free_float'),
                      row.get('turnover_rate'), row_verdict))
            else:
                # QC REPORT → 主表写 NULL + validation_status='REPORT'
                cur.execute("""
                    INSERT OR REPLACE INTO stock_daily
                    (code, date, open, high, low, close, volume, amount,
                     adj_factor, validation_status)
                    VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
                """, (symbol, date_str, row_verdict))
                
                # 写入 staging_raw
                cur.execute("""
                    INSERT INTO staging_raw
                    (batch_id, symbol, trade_date, raw_json, verdict)
                    VALUES (?, ?, ?, ?, ?)
                """, (batch_id, symbol, date_str,
                      json.dumps(row.to_dict(), ensure_ascii=False),
                      row_verdict))

        # COMMIT: 批次内全部完成才提交
        conn.commit()
        commit_id = f"{batch_id}_{symbol}"
        return commit_id
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Staging commit failed for {symbol}: {e}")
```

### 2.5 13 条 QC 规则清单

复用 `data_ingestion_standard.md`（5月22日规范）中的 13 条 QC 规则（按校验维度分组）：

#### 2.5.1 行数完整性校验 (QC-1 ~ QC-2)

| # | 规则 | 实现 | 阈值 |
|:-:|:-----|:-----|:----:|
| QC-1 | 批次行数 ≥ 交易日历预期行数 × 80% | 对比 `trading_calendar` 的非节假日计数 | 80% |
| QC-2 | 单日无重复日期 | `UNIQUE(code, date)` 约束 + 写入前预检查 | 0 |

#### 2.5.2 字段完整性校验 (QC-3 ~ QC-5)

| # | 规则 | 实现 | 阈值 |
|:-:|:-----|:-----|:----:|
| QC-3 | 关键字段 (open/high/low/close/adj_factor) 无 NULL | `IS NULL` 行数检测 | 0% |
| QC-4 | 辅助字段 (volume/amount) 无 NULL | `IS NULL` 行数检测 | 0% |
| QC-5 | 非关键字段 (free_float/turnover_rate) NULL 率 < 5% | `IS NULL` 比例计算 | <5% |

#### 2.5.3 数值范围校验 (QC-6 ~ QC-9)

| # | 规则 | 实现 | 阈值 |
|:-:|:-----|:-----|:----:|
| QC-6 | OHLC 逻辑一致性: high ≥ low、high ≥ open、high ≥ close、low ≤ open、low ≤ close | 逐行检查 | 0 |
| QC-7 | volume ≥ 0 | 逐行检查 | 0 |
| QC-8 | amount ≥ 0 | 逐行检查 | 0 |
| QC-9 | close 在 [0.01, 10000] 区间（A股合理范围） | 行业务知识约束 | 硬阻断 |

#### 2.5.4 复权因子变化率校验 (QC-10 ~ QC-11)

| # | 规则 | 实现 | 阈值 |
|:-:|:-----|:-----|:----:|
| QC-10 | adj_factor 日变化率 < 50%（语境感知版本见 §3.4） | P0 阶段使用固定 50% 兜底 | <50% |
| QC-11 | adj_factor 变化率与除权除息日对齐（语境感知） | 见 §3.4 | P1 阶段实现 |

#### 2.5.5 涨跌幅边界校验 (QC-12 ~ QC-13)

| # | 规则 | 实现 | 阈值 |
|:-:|:-----|:-----|:----:|
| QC-12 | close 相对 pre_close 涨跌幅 ≤ ±20%（复牌日极端情况） | 逐行检查 | ±20% |
| QC-13 | 单日成交量不超过 30 日均值的 50 倍（排除异常峰值） | 滚动 30 日均值对比 | 50 倍 |

> **注意**：QC-10 的 50% 固定阈值为 P0 兜底方案。P1 阶段升级为语境感知版本（§3.4），可区分送转股（>50% 合理）与数据错误（>50% 异常）。

### 2.6 API 限流管理（v1.2 新增）

**背景**：16 只标的 × 5 年 ≈ 19200 次 API 请求。Tushare 免费版限频（通常 200 请求/分钟，积分制有总量限制），未经限流的批量请求会导致 API 被封或返回错误。

**限流策略**：

| 措施 | 实现 | 说明 |
|:----:|:-----|:-----|
| **按标的串行** | `for symbol in symbols: fetch_one(symbol)` | 16 只标的串行请求，天然降低并发 |
| **time.sleep 间隔** | `time.sleep(0.5)` 每次请求后 | 每分钟最多 120 请求，在免费版限额内 |
| **按日期分批** | 5 年数据拆为 5 批 × 1 年，每批间 sleep(2) | 避免单次拉取超长区间触发服务端风控 |
| **retry + backoff** | max_retries=3, backoff_factor=1.5 | 网络异常时指数退避重试 |

```python
import time
import random
from typing import Optional

class TushareRateLimiter:
    """
    API 限流管理器。
    
    策略：
    - 串行请求：单一标的处理完再处理下一个
    - 固定间隔：每次请求后 sleep(0.3~0.8s) 随机波动
    - 重试机制：连接错误/频率限制时重试（最多 3 次）
    - 背压：连续 3 次重试失败后等待 30s 再继续
    """
    
    def __init__(self, min_interval: float = 0.3):
        self.min_interval = min_interval
        self._last_call: float = 0.0
        self._consecutive_failures: int = 0

    def wait(self):
        """等待到允许下一次请求的时间"""
        elapsed = time.time() - self._last_call
        if elapsed < self.min_interval:
            # 加入随机抖动，避免固定节奏被服务端识别
            jitter = random.uniform(-0.1, 0.3)
            sleep_time = self.min_interval - elapsed + max(0, jitter)
            time.sleep(sleep_time)
        
        # 背压：连续失败后增加等待
        if self._consecutive_failures >= 3:
            backoff = min(30, 2 ** self._consecutive_failures)
            time.sleep(backoff)
            self._consecutive_failures = 0

    def record_success(self):
        self._consecutive_failures = 0

    def record_failure(self):
        self._consecutive_failures += 1


def fetch_with_retry(
    api_func, 
    *args, 
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    **kwargs
) -> Optional[pd.DataFrame]:
    """
    带退避重试的 API 请求包装。
    
    重试触发条件：
    - HTTP 连接错误 (ConnectionError/Timeout)
    - 服务端返回频率限制错误 (HTTP 429/503)
    - 空 DataFrame（可能为临时数据不可用）
    
    不重试：
    - 参数错误（修改参数即可解决）
    - 标的不存在（永久错误）
    """
    for attempt in range(max_retries):
        try:
            result = api_func(*args, **kwargs)
            if result is not None and not result.empty:
                return result
            elif attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt + random.uniform(0, 0.5)
                time.sleep(wait_time)
        except (ConnectionError, TimeoutError) as e:
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt + random.uniform(0, 1)
                time.sleep(wait_time)
            else:
                raise RuntimeError(f"API request failed after {max_retries} retries: {e}")
    return None
```

**自动化集成**：限流器将在 `UnifiedIngestionPipeline._fetch_data()` 中作为基础设施使用，不暴露给上层调用者。

---

## 三、校验层详细设计

### 3.1 行数完整性检查

```python
def check_row_count(df: pd.DataFrame, symbol: str,
                    start: str, end: str) -> CheckResult:
    """
    行数完整性检查 (QC-1, QC-2)。

    逻辑：
    1. 从 trading_calendar 获取 [start, end] 区间非节假日日计数 = expected
    2. 实际行数 = len(df)
    3. 如果实际 < expected × 0.8 → REPORT
    4. 检查重复日期 (QC-2)
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM trading_calendar
        WHERE date BETWEEN ? AND ? AND is_trading_day = 1
    """, (start, end))
    expected = cur.fetchone()[0]
    conn.close()

    actual = len(df)
    ratio = actual / expected if expected > 0 else 1.0

    duplicates = df['trade_date'].duplicated().sum()

    issues = []
    if ratio < 0.8:
        issues.append(f"row_count: actual={actual}, expected={expected}, ratio={ratio:.2%}")
    if duplicates > 0:
        issues.append(f"duplicate_dates: {duplicates}")

    return CheckResult(
        name="row_count",
        passed=len(issues) == 0,
        verdict="REPORT" if issues else "PASS",
        detail="; ".join(issues) if issues else f"OK: {actual}/{expected} ({ratio:.1%})",
    )
```

### 3.2 字段合理性检查

```python
def check_field_integrity(df: pd.DataFrame) -> CheckResult:
    """
    字段合理性检查 (QC-3 ~ QC-6, QC-7, QC-8)。

    核心检查：
    1. OHLC 逻辑一致性 (QC-6): high ≥ low, high ≥ open, high ≥ close,
       low ≤ open, low ≤ close
    2. volume ≥ 0 (QC-7)
    3. amount ≥ 0 (QC-8)
    4. 关键字段无 NULL (QC-3, QC-4)
    """
    issues = []

    # QC-6: OHLC 逻辑
    for col_a, col_b, desc in [
        ('high', 'low', 'high < low'),
        ('high', 'open', 'high < open'),
        ('high', 'close', 'high < close'),
        ('low', 'open', 'low > open'),
        ('low', 'close', 'low > close'),
    ]:
        violations = df[df[col_a] < df[col_b]].shape[0] \
            if desc.startswith('high <') or desc.startswith('high <') \
            else df[df[col_a] > df[col_b]].shape[0]
        # 重新计算精确的违反数
        if desc in ('high < low',):
            cnt = (df['high'] < df['low']).sum()
        elif desc in ('high < open',):
            cnt = (df['high'] < df['open']).sum()
        elif desc in ('high < close',):
            cnt = (df['high'] < df['close']).sum()
        elif desc in ('low > open',):
            cnt = (df['low'] > df['open']).sum()
        elif desc in ('low > close',):
            cnt = (df['low'] > df['close']).sum()
        if cnt > 0:
            issues.append(f"OHLC_violation({desc}): {cnt} rows")

    # QC-7: volume < 0
    neg_vol = (df['volume'] < 0).sum()
    if neg_vol > 0:
        issues.append(f"negative_volume: {neg_vol} rows")

    # QC-8: amount < 0
    neg_amt = (df['amount'] < 0).sum()
    if neg_amt > 0:
        issues.append(f"negative_amount: {neg_amt} rows")

    # QC-3, QC-4: 关键字段 NULL
    required_cols = ['open', 'high', 'low', 'close', 'adj_factor']
    for col in required_cols:
        if col in df.columns:
            null_cnt = df[col].isna().sum()
            if null_cnt > 0:
                issues.append(f"null_{col}: {null_cnt} rows")

    return CheckResult(
        name="field_integrity",
        passed=len(issues) == 0,
        verdict="REPORT" if issues else "PASS",
        detail="; ".join(issues) if issues else "OK: all field checks passed",
    )
```

### 3.3 数值范围检查（含涨跌停语境阈值）

```python
def check_numerical_range(df: pd.DataFrame,
                           symbol: str) -> CheckResult:
    """
    数值范围检查 (QC-9, QC-12, QC-13)。

    含涨跌停作为语境阈值，但注明其局限性：
    局限性说明：
    - 涨跌停 (±10% / ±20%) 可作为范围边界的合理参考
    - 但无法区分送转股导致的"价格脉冲"与真正数据错误
    - 送转股模式：adj_factor 跳变 + 价格等比压缩，价格本身在合理范围内
    - 数据错误模式：价格可能跳出任何合理范围
    """
    issues = []

    # QC-9: close 范围
    out_of_range = df[(df['close'] < 0.01) | (df['close'] > 10000)].shape[0]
    if out_of_range > 0:
        issues.append(f"close_out_of_range: {out_of_range} rows")

    # QC-12: 涨跌幅边界（需要 pre_close）
    if 'pre_close' in df.columns:
        breach = (abs(df['close'] / df['pre_close'] - 1) > 0.20).sum()
        if breach > 0:
            issues.append(f"price_limit_breach(±20%): {breach} rows")
    else:
        # 用前一天的 close 近似
        df_sorted = df.sort_values('trade_date')
        prev_close = df_sorted['close'].shift(1)
        breach = (abs(df_sorted['close'] / prev_close - 1) > 0.20).sum()
        if breach > 0:
            issues.append(f"price_limit_breach_approx(±20%): {breach} rows")

    # QC-13: 成交量异常峰值
    df_sorted = df.sort_values('trade_date')
    vol_ma30 = df_sorted['volume'].rolling(30, min_periods=10).mean()
    vol_ratio = df_sorted['volume'] / vol_ma30
    extreme_vol = (vol_ratio > 50).sum()
    if extreme_vol > 0:
        issues.append(f"volume_extreme(>50xMA30): {extreme_vol} rows")

    return CheckResult(
        name="numerical_range",
        passed=len(issues) == 0,
        verdict="REPORT" if issues else "PASS",
        detail="; ".join(issues) if issues else "OK: all range checks passed",
    )
```

### 3.4 除权除息日多日上下文检查

```python
def check_ex_dividend_context(df: pd.DataFrame,
                               symbol: str) -> CheckResult:
    """
    除权除息日多日上下文检查。

    核心逻辑：
    送转股模式（一次性脉冲）：
    - adj_factor 跳变日前后价格等比压缩（adj_factor 变化率 ≈ 价格变化率）
    - 成交量在送转日放量（通常 > 3 倍前日）
    - 送转后 1-2 日恢复正常交易
    - 价格序列整体连续（压缩后无毛刺）

    数据错误模式（持续性混乱）：
    - 价格变化与 adj_factor 变化方向不一致
    - 跳变日后价格序列出现毛刺/断裂
    - 成交量无规律（可能为 0 或异常大值）
    - 多日连续异常（非 1-2 日的脉冲）

    局限性说明：
    - 本检查无法 100% 区分送转股与数据错误
    - 送转股判定需要除权除息日历辅助确认（见 P1 升级方案）
    - 此处的多日上下文仅作为语境线索，不阻断
    """
    issues = []
    context_notes = []

    df_sorted = df.sort_values('trade_date').reset_index(drop=True)

    if 'adj_factor' not in df_sorted.columns:
        return CheckResult(name="ex_dividend_context", passed=True,
                           verdict="PASS", detail="SKIP: no adj_factor")

    # 检测 adj_factor 跳变日
    adj_changes = df_sorted['adj_factor'].pct_change().abs()
    jump_dates = df_sorted[adj_changes > 0.50]

    for _, jump_row in jump_dates.iterrows():
        jump_idx = jump_row.name
        jump_date = jump_row['trade_date']
        jump_pct = adj_changes.iloc[jump_idx] * 100

        # 上下文窗口：±5 个交易日（用于成交量基线）
        start_ctx = max(0, jump_idx - 5)
        end_ctx = min(len(df_sorted), jump_idx + 6)
        ctx = df_sorted.iloc[start_ctx:end_ctx].copy()

        # 特征 1: 价格是否等比压缩
        # 【v1.2 修复】使用 jump_idx - 1（跳变前一日）为基准价，而非 ctx.iloc[0]
        # 原逻辑: ctx.iloc[0] 是窗口起始日，当跳变在窗口末尾时基准价回溯不足
        # 新逻辑: 直接使用跳变前一日的收盘价和 adj_factor，精确匹配单日跳变
        base_idx = jump_idx - 1
        use_day_before = base_idx >= 0 and base_idx in df_sorted.index

        if use_day_before:
            price_ratio = jump_row['close'] / df_sorted.iloc[base_idx]['close']
            adj_ratio = jump_row['adj_factor'] / df_sorted.iloc[base_idx]['adj_factor']
        else:
            # 兜底：跳变在数据第一行时无法计算前一交易日
            price_ratio = 1.0
            adj_ratio = 1.0

        ratio_match = abs(price_ratio - adj_ratio) / adj_ratio < 0.05 \
            if adj_ratio > 0 else False

        # 特征 2: 成交量放量
        vol_before = ctx.iloc[:5]['volume'].mean() if len(ctx) >= 5 else 0
        vol_at_jump = jump_row['volume']
        vol_surge = vol_at_jump / vol_before > 3 if vol_before > 0 else False

        # 特征 3: 跳变后价格连续性
        if jump_idx + 1 < len(df_sorted):
            post_close = df_sorted.iloc[jump_idx + 1]['close']
            close_gap = abs(post_close / jump_row['close'] - 1)
            price_continuous = close_gap < 0.10  # 跳变后次日的价格跳 < 10%
        else:
            price_continuous = True

        # 特征 4: 跳变后多日无持续性异常
        if jump_idx + 5 < len(df_sorted):
            post_prices = df_sorted.iloc[jump_idx+1:jump_idx+6]['close']
            post_anomalies = (post_prices.pct_change().abs() > 0.10).sum()
            no_persistent = post_anomalies <= 1
        else:
            no_persistent = True

        # 综合判定
        is_split_pattern = ratio_match and vol_surge and price_continuous and no_persistent
        is_error_pattern = (not ratio_match) and (not price_continuous)

        if is_split_pattern:
            context_notes.append(
                f"{jump_date}: adj_factor跳变+{jump_pct:.1f}%, "
                f"送转股模式(ratio_match={ratio_match}, vol_surge={vol_surge})"
            )
        elif is_error_pattern:
            issues.append(
                f"{jump_date}: adj_factor跳变+{jump_pct:.1f}%, "
                f"疑似数据错误(ratio_mismatch={not ratio_match}, "
                f"price_gap={not price_continuous})"
            )
        else:
            context_notes.append(
                f"{jump_date}: adj_factor跳变+{jump_pct:.1f}%, "
                f"语境复杂(ratio={price_ratio:.3f}, "
                f"adj_ratio={adj_ratio:.3f}), 需人工判断"
            )

    return CheckResult(
        name="ex_dividend_context",
        passed=len(issues) == 0,
        verdict="REPORT" if issues else "PASS_WITH_NOTE" if context_notes else "PASS",
        detail="; ".join(context_notes + issues) or "OK: no significant jumps detected",
    )
```

### 3.5 小比例送转处理计划（P1 阶段）

**背景**：当前 QC-11 仅检测 adj_factor 跳变 > 50% 的场景，会漏检小比例送转（如 10 送 1、10 送 2 等，对应 adj_factor 跳变 ~10%-20%）。

**P0 阶段**维持 50% 阈值不变，因为：
- 送转股误判的主要风险来自大比例送转（如 300750 的 10 转增 8，跳变 +81.2%）
- 小比例送转的 adj_factor 跳变幅度与正常除权除息重叠，降低阈值会增加误报
- P0 需要优先建立完整的语境感知框架，阈值优化是第二步

**P1 阶段计划**：

| 方案 | 方法 | 优先级 |
|:----:|:-----|:-----:|
| A) 阈值降低 | 将检测阈值从 50% 降至 10%，但需配合 dividend 事件日历联动避免将正常除权除息误判为送转 | 高 |
| B) 日历联动 | 加载 dividend 事件日历（Tushare dividend API），在除权除息日前后 3 天内的跳变自动标记为"除权除息事件"，跳过送转判定逻辑 | 高 |
| C) 复合模式识别 | 送转股 + 现金分红联合事件（如 300750 10 转增 8 + 分红 2.52 元）在日历中可识别为复合事件，直接标记无须语境判断 | 中 |

**推荐方案**：P1 阶段采用 **B+A 组合**——先实现 dividend 日历联动作为预筛选，再降阈值至 10% 以覆盖小比例送转。具体实施安排在 P1 进度中。

---

### 3.6 审计日志示例

```python
def _log_audit(self, batch_id: str, symbol: str,
               qc_result: QcResult, commit_id: str) -> None:
    """
    写入审计日志。

    batch_audit 表（批次级一行）：
    - 每次灌入任务写一条
    - 包含全局 verdict 和统计数据

    batch_audit_detail 表（每日每条 check 一行）：
    - 只写入 RFC/REPORT 的检查项（PASS 项不写入以减少数据量）
    """
    conn = self._get_conn()
    cur = conn.cursor()

    # batch_audit 主记录（batch 结束时写，见 _finalize_batch）
    # 此处写 detail

    for date_str, check_results in qc_result.daily_results.items():
        for check_name, cr in check_results.items():
            if cr.verdict != 'PASS':  # 只记录非 PASS
                cur.execute("""
                    INSERT INTO batch_audit_detail
                    (batch_id, symbol, trade_date, check_name, verdict, detail)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (batch_id, symbol, date_str,
                      check_name, cr.verdict, cr.detail))

    conn.commit()
```

---

## 四、数据治理

### 4.1 标的池配置化

当前 phase1_data_collection.py 的硬编码方式：

```python
STOCK_CODES = [
    "601857", "000001", "600519", "601318",
    "600036", "300750", "600276", "600887",
    "600030", "000333", "002415", "600436",
]
```

改为配置文件化管理：

```yaml
# ─── 文件: config/symbol_registry.yaml ───
# 标的池配置 — 新增/移除标的仅修改此文件

symbols:
  # ── A50 核心 16 只（含 4 只当前缺失的） ──
  - code: "601857"
    name: "中国石油"
    market: "sh"
    active: true
    priority: 0

  - code: "000001"
    name: "平安银行"
    market: "sz"
    active: true
    priority: 0

  # ... 原有 12 只 ...

  # ── 4 只当前缺失的标的（待补全） ──
  - code: "000651"
    name: "格力电器"
    market: "sz"
    active: true
    priority: 1          # P0 完成后即补全

  - code: "000858"
    name: "五粮液"
    market: "sz"
    active: true
    priority: 1

  - code: "002714"
    name: "牧原股份"
    market: "sz"
    active: true
    priority: 1

  - code: "601166"
    name: "兴业银行"
    market: "sh"
    active: true
    priority: 1

# ── 扩展池（非 A50 核心，后续加入） ──
extended_pool:
  - code: "600900"
    name: "长江电力"
    market: "sh"
    active: false
    priority: 3
```

Python 接口：

```python
class SymbolRegistry:
    """标的池注册表（配置化管理）"""

    def __init__(self, config_path: str = "config/symbol_registry.yaml"):
        self._config = self._load_yaml(config_path)
        self._validate_config()  # 【v1.2 新增】加载时自动校验 schema

    def _validate_config(self) -> None:
        """
        YAML 配置 schema 校验（v1.2 新增）。
        
        风险：手工编辑 YAML 时可能出现拼写错误（如 active: ture）、
        类型错误（如 priority: "字符串"）导致运行时异常。
        
        实现方案：
        - 方案 A（推荐）：使用 Python pydantic 模型定义 schema
        - 方案 B（轻量）：使用 JSON Schema + jsonschema 库
        - 方案 C（兜底）：类内部手动校验关键字段
        
        P0 阶段采用方案 C（最小依赖），P1 升级到方案 A。
        """
        for s in self._config.get('symbols', []):
            assert isinstance(s.get('code'), str), f"{s.get('code')}: code must be str"
            assert isinstance(s.get('active'), bool), f"{s.get('code')}: active must be bool"
            assert isinstance(s.get('priority'), int), f"{s.get('code')}: priority must be int"

    def get_active_symbols(self) -> list[SymbolMeta]:
        """返回所有 active=true 的标的"""
        return [SymbolMeta(**s) for s in self._config['symbols']
                if s.get('active', True)]

    def get_by_priority(self, max_priority: int = 0) -> list[SymbolMeta]:
        """按优先级获取标的"""
        return [SymbolMeta(**s) for s in self._config['symbols']
                if s.get('priority', 0) <= max_priority]

    def add_symbol(self, code: str, name: str, market: str,
                   priority: int = 2) -> None:
        """新增标的"""
        self._config['symbols'].append({
            'code': code, 'name': name, 'market': market,
            'active': True, 'priority': priority,
        })
        self._save_config()
```

**YAML Schema 校验补充说明（v1.2）**：

> **配置漂移风险**：手工编辑 YAML 可能拼写错误（如 `activ: true` 而非 `active`）、类型错误（`priority: "高"` 而非整数）、新增字段时忘记同步更新 SymbolRegistry 的读取逻辑。
>
> **P0 阶段**：采用类内部 `_validate_config()` 手动校验关键字段（code/active/priority）
> **P1 阶段**：引入 JSON Schema 文件 `config/symbol_registry.schema.json`，使用 jsonschema 库校验
> **P2 阶段**：迁移到 pydantic BaseModel 定义完整 schema，字段类型 + 默认值 + 自定义校验器

### 4.2 历史数据首次全量重灌

**背景**：当前 volume/amount 存在单位混存问题（Tushare 返回的 volume 单位为股/手不确定），历史数据中已有部分不一致记录。需要统一重灌一次。

**重灌策略（v1.2 修正）**：

> **核心问题**：重灌策略需要明确是 DELETE+INSERT 还是 INSERT OR REPLACE，以及历史回测数据的破碎风险。
>
> **选择：DELETE+INSERT（含备份）**
> - 理由：INSERT OR REPLACE 在传入数据不完整时（如某日无数据），会隐式删除不该删除的行。DELETE+INSERT 在事务内执行，原子性更可控。
> - 备份机制：删除前对 `stock_daily` 表执行完整备份，确保回滚能力
>
> **备份机制**：
> ```sql
> -- Step 1: 创建备份表
> CREATE TABLE IF NOT EXISTS stock_daily_backup_20260525 AS
>   SELECT * FROM stock_daily;
>
> -- Step 2: 在事务内删除+写入
> BEGIN TRANSACTION;
>   DELETE FROM stock_daily WHERE code IN (<symbols>);
>   INSERT INTO stock_daily (...) VALUES (...);
> COMMIT;
> ```
>
> **影响说明**：
> - 现有引用 `stock_daily` 的历史回测（如 run_exp_invfac002.py）会在重灌后读到新数据
> - 如果回测是基于特定基期（§5.3）的 QFQ 价格，重灌不改变基期参数，价格不受影响
> - 如果回测依赖 adj_factor 历史序列，重灌会更新整个序列 → 需要在回测报告中记录"数据版本"
> - 首次重灌前通知所有使用者（墨萱、玄知、墨涵），确认无正在运行的回测依赖旧数据

```python
def full_reload_strategy(symbols: list[str]) -> None:
    """
    历史数据首次全量重灌。

    执行条件：
    - 首次运行 unified_ingestion.py 时，对所有标的执行 FULL_RELOAD
    - 后续仅通过 INCREMENTAL 模式更新

    重灌范围：
    - 从标的上市日期（或 2021-01-01，取较晚者）到 latest_date
    - 使用统一的数据源（Tushare 为 primary），确保 volume/amount 单位一致
    - Tushare volume 单位：股（shares），不做二次转换

    单位处理：
    - volume: 以 Tushare 返回值为准（股/shares），不做单位转换
    - amount: 以 Tushare 返回值为准（元/yuan）
    - 旧数据中可能有的"手"单位 → 本次重灌覆盖
    
    重灌方式：DELETE+INSERT（含备份），而非 INSERT OR REPLACE
    （详见上方重灌策略说明）
    """
    for symbol in symbols:
        task = IngestionTask(
            symbols=[symbol],
            start_date="20210101",  # 或上市日期
            end_date="today",
            mode="FULL_RELOAD",
        )
        pipeline = UnifiedIngestionPipeline()
        result = pipeline.run(task)
        print(f"  {symbol}: {result.summary}")
```

### 4.3 增量更新机制

```python
def incremental_update(symbols: list[str] = None) -> IngestionResult:
    """
    每日收盘后自动触发增量更新。

    触发方式（二选一）：
    方法 A: 定时 cron（推荐）— 每日 16:00 执行（A股收盘后 1h）
    方法 B: 手动执行 — python unified_ingestion.py --mode INCREMENTAL

    逻辑：
    1. 读取 stock_daily 的 max(date) 作为 last_date
    2. start_date = last_date + 1（避免重复）
    3. end_date = today
    4. 仅拉取增量区间
    5. QC 校验 + 写入
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if not symbols:
        # 获取所有活跃标的
        registry = SymbolRegistry()
        symbols = [s.code for s in registry.get_active_symbols()]

    results = []
    for symbol in symbols:
        cur.execute("""
            SELECT MAX(date) FROM stock_daily WHERE code = ?
        """, (symbol,))
        last_date = cur.fetchone()[0]

        start = (datetime.strptime(last_date, '%Y%m%d') + timedelta(days=1)) \
            .strftime('%Y%m%d') if last_date else "20210101"
        end = datetime.now().strftime('%Y%m%d')

        if start >= end:
            print(f"  {symbol}: up-to-date (last={last_date})")
            continue

        task = IngestionTask(
            symbols=[symbol],
            start_date=start,
            end_date=end,
            mode="INCREMENTAL",
        )
        pipeline = UnifiedIngestionPipeline()
        result = pipeline.run(task)
        results.append(result)

    conn.close()
    return results
```

### 4.4 4 只缺失标的补全

4 只缺失标的（000651/000858/002714/601166）自然补全方式：

```python
# 在配置文件新增 → 增量更新自动覆盖

# Step 1: 在 symbolic_registry.yaml 中设置 active=true
# Step 2: 执行一次增量更新
# Step 3: 程序自动从历史起点拉取到最新日

def backfill_missing_symbols():
    """自然补全 4 只缺失标的"""
    missing = ["000651", "000858", "002714", "601166"]
    for symbol in missing:
        task = IngestionTask(
            symbols=[symbol],
            start_date="20210101",
            end_date="today",
            mode="FULL_RELOAD",  # 首次全量
        )
        pipeline.run(task)
```

---

## 五、复现性保障

### 5.1 送转股统一处理原则

```python
# ─── 送转股处理三原则 ───

PRINCIPLE_A = "保留+标注"
"""
适用条件:
  - adj_factor 跳变模式为送转股特征（价格等比压缩 + 成交量放量）
  - 事件已通过多日上下文综合判定一致
  - 送转后交易正常（无长期停牌）

处理方式:
  - 保留在标的池中
  - adj_factor_events 表标注 event_type='STOCK_SPLIT'
  - QFQ 复权时由 adj_factor 处理，价格连续

适用示例: 600276 恒瑞医药
"""

PRINCIPLE_B = "排除+记录"
"""
适用条件（满足任一）:
  A. 单次送转 adj_factor 跳变 > 500%
  B. 两年内累计送转 adj_factor 变化 > 1000%
  C. 送转后 30 日日均成交量 < 送转前 30 日的 30%（流动性枯竭）

处理方式:
  - 从因子计算和回测标的池中排除
  - 排除原因记录在 exclusion_log 表

适用示例: 300750（排除后作为独立分析对象）
"""

PRINCIPLE_C = "分段保留"
"""
适用条件:
  - 送转发生在回测窗口中间或之后
  - 送转前数据完整可用

处理方式:
  - 保留完整数据，在 adj_factor_events 中标注
  - 因子计算时标记送转事件，特定因子分段处理
"""

def classify_stock_split(ts_code: str, start: str, end: str) -> str:
    """
    对送转股进行程序化分类。

    返回: PRINCIPLE_A | PRINCIPLE_B | PRINCIPLE_C
    """
    # 1. 加载 adj_factor 跳变事件
    events = load_adj_events(ts_code, start, end)
    split_events = [e for e in events
                    if e.event_type in ('STOCK_SPLIT', 'BONUS_SHARES')]

    if not split_events:
        return PRINCIPLE_A

    # 2. 检查排除条件 (PRINCIPLE_B)
    max_jump = max(e.change_pct for e in split_events)
    if max_jump > 500:
        return PRINCIPLE_B

    cumulative_2y = sum(e.change_pct for e in split_events
                        if is_within_2y(e.date, end))
    if cumulative_2y > 1000:
        return PRINCIPLE_B

    # 3. 检查是否需分段 (PRINCIPLE_C)
    splits_in_last_2y = [e for e in split_events
                         if is_within_2y(e.date, end)]
    if splits_in_last_2y:
        return PRINCIPLE_C

    return PRINCIPLE_A
```

### 5.2 exclusion_log 表设计

```sql
CREATE TABLE IF NOT EXISTS exclusion_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code             TEXT    NOT NULL,           -- 股票代码
    experiment_id       TEXT    NOT NULL,           -- 实验/任务 ID
    decision            TEXT    NOT NULL,           -- INCLUDE | EXCLUDE | PRINCIPLE_A | PRINCIPLE_B | PRINCIPLE_C
    reason              TEXT    NOT NULL,           -- 决策理由（指向 §5.1 的具体条件）
    evidence_json       TEXT,                       -- 支撑证据（事件列表、统计数据）
    rule_version        TEXT,                       -- 决策时的规则版本哈希
    qfq_base_date       TEXT,                       -- QFQ 基期日期（用于复现）
    reproducibility_info TEXT,                      -- 复现性信息（含 adj_factor 快照摘要）
    decided_by          TEXT    NOT NULL DEFAULT 'auto',  -- auto | manual:name
    created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),

    UNIQUE(ts_code, experiment_id)  -- 同一实验不重复记录同一标的
);

CREATE INDEX IF NOT EXISTS idx_excl_symbol
    ON exclusion_log(ts_code);

CREATE INDEX IF NOT EXISTS idx_excl_experiment
    ON exclusion_log(experiment_id);
```

**复现性流程**：

```python
def reproduce_exclusion_decision(
    ts_code: str, experiment_id: str,
    rule_version: str = None
) -> dict:
    """
    复现排除决策。

    流程：
    1. 读取 exclusion_log 中原始决策记录
    2. 重新运行 classify_stock_split() + should_exclude()
    3. 比较原始决策与复现决策
    4. 若不匹配，写入 inconsistency 记录

    返回: {match: True/False, original_decision, replayed_decision}
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT decision, reason, rule_version
        FROM exclusion_log
        WHERE ts_code=? AND experiment_id=?
    """, (ts_code, experiment_id))
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"match": False, "error": "no_exclusion_record"}

    original = {"decision": row[0], "reason": row[1], "rule_version": row[2]}

    # 重新运行分类
    new_decision = classify_stock_split(ts_code, start, end)

    match = original['decision'] == new_decision
    if not match:
        _log_inconsistency(ts_code, experiment_id, original, new_decision)

    return {
        "match": match,
        "original_decision": original,
        "replayed_decision": new_decision,
    }
```

### 5.3 QFQ 基期漂移修复方案

**问题重现**：

```python
# 当前代码 (run_exp_invfac002.py:68-70)
latest_adj = adj_factor[-1]  # 取数据最后一行 → 随数据追加而变化！
adj_ratio = adj_factor / latest_adj
close_qfq = close * adj_ratio
```

**方案 A（推荐）— 锁定基期 + 版本化**：

```python
def compute_qfq_prices(adj_factor: np.ndarray,
                       close: np.ndarray,
                       base_date_idx: int = None) -> np.ndarray:
    """
    QFQ 前复权计算 — 基期锁定版本。

    参数:
      base_date_idx: 基期索引（回测窗口终点）
        若为 None，使用 adj_factor[-1]（现有行为，保持后向兼容）
        若指定，使用 adj_factor[base_date_idx] 作为基期

    改动影响:
    - 同一回测窗口（同一 base_date_idx）多次运行 → 价格完全一致 ✅
    - base_date_idx 作为回测参数持久化 → 复现时用同一索引 ✅
    - 不同 base_date_idx 得到不同价格 → 这是预期行为 ✅
    """
    if base_date_idx is None:
        base_adj = adj_factor[-1]  # 兼容模式
    else:
        base_adj = adj_factor[base_date_idx]

    adj_ratio = adj_factor / base_adj
    return close * adj_ratio
```

**方案 B（替代）— 改用后复权**：

```python
def compute_qfq_backward(adj_factor: np.ndarray,
                          close: np.ndarray) -> np.ndarray:
    """
    后复权计算（选项 B）。
    
    以最早日期为基期：
    adj_ratio = adj_factor / adj_factor[0]
    
    优点：一次性计算，永久不变
    缺点：后复权价格数值大（含历史分红累积），不直观
    """
    adj_ratio = adj_factor / adj_factor[0]
    return close * adj_ratio
```

**选择**：采用**方案 A**（锁定基期），因为：
1. 前复权价格数值直观（接近当前市价）
2. 改动最小（仅修改一行代码 + 新增一个参数）
3. 与现有回测框架兼容（只需传递 base_date_idx）

**实施要求**：

| 要求 | 说明 |
|:-----|:------|
| 基期日期持久化 | base_date_idx 对应的日期写入回测报告 JSON |
| 参数传递 | run_exp_invfac002.py 的 main() 新增 `--qfq-base-date` 参数 |
| 审计 | 基期日期写入 exclusion_log 的 qfq_base_date 字段 |
| 兼容性 | base_date_idx=None 时保持旧行为（兜底） |

---

## 六、三层质量保障架构

### 6.1 架构概览

```
三层质量保障体系
┌─────────────────────────────────────────────────────────────────┐
│  层 3（辅助）：QC 层 — 试验前检查                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  执行时机: 每次回测/试验启动前                             │   │
│  │  检查项: ~5 项（墨萱确认压缩后）                           │   │
│  │   1. adj_factor NULL 检查（硬阻断）                       │   │
│  │   2. adj_factor 跳变 >50% 检查（硬阻断）                  │   │
│  │   3. Buy & Hold 验证（信息校验，不阻断）                  │   │
│  │   4. exclusion_log 一致性检查（程序化决策 vs 记录）        │   │
│  │   5. 数据时效性检查（最新交易日 ≤ T-3）                   │   │
│  │  脚本: scripts/qc/data_qc_check.py                       │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            ▲
                            │ 依赖层 2 健康数据
                            │
┌─────────────────────────────────────────────────────────────────┐
│  层 2（日常）：数据库维护层 — 定时健康检查                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  执行时机: 每日开盘前 (08:00)                             │   │
│  │  检查项:                                                  │   │
│  │   1. 数据时效性 — 最新数据 ≤ T-3                         │   │
│  │   2. 行数稳定性 — 日行数变化 ±10% 内                     │   │
│  │   3. 字段分布 — adj_factor 统计量稳定性                   │   │
│  │   4. 灌入异常 — 24h 内 REPORT 计数 / 总记录 ≤ 1%        │   │
│  │   5. adj_factor_events UNKNOWN 事件监控                  │   │
│  │  脚本: scripts/maintenance/db_health_monitor.py           │   │
│  │  输出: logs/db_health_{date}.json                         │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            ▲
                            │ 依赖层 1 灌入的干净数据
                            │
┌─────────────────────────────────────────────────────────────────┐
│  层 1（根）：录入管线层 — 统一灌入程序（本方案核心）            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  执行时机: 每日收盘后 (16:00) 增量更新 + 首次全量       │   │
│  │  功能:                                                   │   │
│  │   1. 统一入口 — 所有日线数据走此程序                     │   │
│  │   2. QC 校验 — 13 条规则（§3）                          │   │
│  │   3. Staging 原子写入 — 批次级 commit                    │   │
│  │   4. batch_audit 审计日志                                │   │
│  │   5. 可选 E-001 增强校验                                 │   │
│  │  脚本: src/data/unified_ingestion.py                     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 层间关系

| 维度 | 层 1（录入管线） | 层 2（日常维护） | 层 3（试验前 QC） |
|:-----|:----------------|:----------------|:-----------------|
| **职责** | 保障入库数据的基础质量 | 监控数据库运行状态 | 试验前最后一道防线 |
| **触发** | 数据写入时 | 每日定时 | 试验开始时 |
| **阻断** | 不阻断（写 staging_raw） | 不阻断（写报告） | **硬阻断**（终止试验） |
| **检查深度** | 每条记录逐行检查 | 聚合统计量检查 | 关键检查项抽检 |
| **数据源** | API 原始数据 | stock_daily 主表 | stock_daily 主表 |
| **告警** | 写 batch_audit_detail | 写健康检查日志 | 写入 FAILED 文件 |

### 6.3 现有 data_qc_check.py 的迁移

当前 `data_qc_check.py`（用于 EXP-2026-INVFAC-002 §2.3 前置检查）的职责拆分为：

```
data_qc_check.py（现有）
  ├─ adj_factor NULL 检查 → 保留在 层3（试验前硬阻断）
  ├─ adj_factor 跳变 50% 检查 → 保留在 层3（试验前硬阻断）
  │   └─ 但标记为"语境有限"，提醒使用统一灌入程序的语境感知版本
  ├─ 数据连续性检查 → 移至 层1（录入时检查）
  ├─ 字段完整性检查 → 移至 层1（录入时检查）
  └─ Buy & Hold 验证 → 保留在 层3（信息校验，不阻断）
```

---

## 七、执行计划

### 7.1 优先级与工时估算

| 优先级 | 措施 | 工时 | 复杂度 | 依赖 | 对应章节 |
|:------:|:-----|:----:|:------:|:-----|:--------:|
| **P0** | 统一日线灌入程序 | ~6-7h | 中 | symbol_registry.yaml 配置、batch_audit 表创建 | §2 |
| **P1** | 简化 QC 检查 + 小比例送转 + YAML schema 校验 | ~4h | 中 | P0 完成 + dividend 日历集成 | §3.5, §4.1, §6.2-6.3 |
| **P2** | QFQ 基期修复 + exclusion_log | ~3h | 低 | P0 完成 | §5.2-5.3 |

### 7.2 P0 分解（统一日线灌入程序 ~6-7h）

| 子任务 | 工时 | 产出 |
|:-------|:----:|:-----|
| 创建 symbol_registry.yaml 配置 + SymbolRegistry 类 | 0.5h | 配置文件 + Python 类 |
| 实现 QC 引擎框架 + 13 条规则 | 2.5h | QCEngine 类（含 adj_factor 语境感知调试和真实数据联调边界情况） |
| 实现 staging 原子写入逻辑 | 0.5h | _staging_commit 函数 |
| 创建 batch_audit / batch_audit_detail 表 DDL | 0.5h | SQL DDL |
| 审计日志写入 | 0.5h | _log_audit 函数 |
| UnifiedIngestionPipeline 主类 | 0.5h | run() 主入口 |
| API 限流管理 | 0.5h | TushareRateLimiter 类（§2.6） |
| E-001 集成点 | 0.5h | 可选 E-001 调用的接口 |
| 单元测试 + 集成测试 | 1h | test_unified_ingestion.py（13 条规则 × 2 条路径 + staging 写入 = 30+ 测试用例） |

### 7.3 P1 分解（简化 QC 检查 + P1 修复项 ~4h）

| 子任务 | 工时 | 产出 |
|:-------|:----:|:-----|
| 精简 data_qc_check.py 至 5 项 | 0.5h | 精简脚本 |
| 标注语境感知提示 | 0.5h | 注释更新 |
| 小比例送转处理（B+A 方案） | 1h | dividend 日历联动 + 阈值降至 10% |
| YAML schema 校验（JSON Schema） | 0.5h | config/symbol_registry.schema.json + jsonschema 校验 |
| 层级集成 | 0.5h | run_exp_invfac002.py 更新 |
| 测试 | 1h | 验证精简前后结果一致性 + 小比例送转覆盖 |

### 7.4 P2 分解（QFQ 基期修复 + exclusion_log ~3h）

| 子任务 | 工时 | 产出 |
|:-------|:----:|:-----|
| QFQ 基期锁定 compute_qfq_prices 修改 | 0.5h | 函数修改 |
| 所有回测入口传递 base_date_idx 参数 | 0.5h | run_exp_*.py 更新 |
| exclusion_log 表 DDL + 创建 | 0.5h | SQL DDL |
| reproduce_exclusion_decision 函数 | 0.5h | 复现函数 |
| 300750/600276 等标的回填记录 | 0.5h | 数据写入 |
| 回测报告增加基期日期字段 | 0.5h | JSON 输出更新 |

### 7.5 实施顺序

```
注意：P0→P1→P2 严格串行，不得交叉。

P0 (统一灌入程序) ─── t+0h 到 t+7h
  ├── [0h]   创建 symbol_registry.yaml + 建表 DDL
  ├── [0.5h] QCEngine 13 条规则实现（含 adj_factor 语境调试）
  ├── [3h]   staging 写入 + 审计日志
  ├── [4h]   API 限流管理实现
  ├── [4.5h] UnifiedIngestionPipeline 主类 + E-001 集成点
  └── [5.5h] 测试（30+ 测试用例）
  └── [6.5h] 文档收尾

P1 (简化 QC) ─── t+7h 到 t+9h
  ├── [7h]   精简 data_qc_check.py 至 5 项
  └── [8h]   集成 + 测试

P2 (基期修复 + exclusion_log) ─── t+7h 到 t+10h
  ├── [7h] QFQ 基期锁定
  ├── [8h] exclusion_log 表 + 复现函数
  └── [9h] 回填 + 全量测试
```

### 7.6 并行验证期

墨萱要求 2 个月并行验证期：新旧两套灌入程序并行运行 2 个月，比较数据一致性。

```markdown
并行验证期（2 个月）：
  时期: P0 上线后第 1-60 天
  
  运行方式:
  - 旧脚本 (phase1_data_collection.py) 继续作为主写入
  - 新程序 (unified_ingestion.py) 以只读模式执行，写入 staging_raw + 不覆盖主表
  - 每日对比新旧两套数据的差异

  验证标准:
  - 第 30 天: 数据一致率 ≥ 99.9%（以 13 条 QC 规则为准）
  - 第 60 天: 无结构性差异（全部标的 → 全部交易日）
  
  切换条件:
  - 第 60 天验证通过 → 旧脚本退役，新程序升为主写入
  - 第 60 天未通过 → 延长验证期 1 个月，找出差异根因
```

### 7.7 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:-----|:---------|
| E-001 进度延迟导致 audit_log 不可用 | 高 | 低 | P0 用 batch_audit 自身表，不依赖 E-001 |
| 数据源 API 变化（Tushare 字段名变更） | 中 | 高 | 字段映射表配置化 + 测试覆盖率 |
| 并行验证期发现大量差异 | 中 | 中 | 预先设定一致率阈值（99.9%），低于阈值则延长验证 |
| 送转股分类未能覆盖边界情况 | 中 | 低 | PRINCIPLE_C 作为兜底，人工覆写机制 |
| API 限流（16 只 × 5 年 ≈ 19200 请求） | 中 | 高 | 按标的串行 + time.sleep + retry/backoff + 按年分批（§2.6） |
| 历史重灌数据迁移导致回测破碎 | 中 | 中 | 备份 + 事务内 DELETE+INSERT + 通知使用者（§4.2） |
| E-001 与 E-002 audit 日志冲突 | 低 | 中 | e001_batch_id 跨表关联字段（§2.3）+ 命名空间隔离 |

---

## 附录 A：文件清单

| 文件 | 路径 | 说明 |
|:-----|:-----|:------|
| 本方案 | `docs/algorithms/E-002_data_quality_pipeline.md` | **当前文件** |
| E-001 设计 | `docs/algorithms/E001_data_ingestion.md` | 多源交叉验证参考 |
| data_ingestion_standard | `docs/algorithms/data_ingestion_standard.md` | 13 条 QC 规则规范（5月22日） |
| current phase1 | `scripts/exp_invfac002/data_qc_check.py` | 现有 QC 检查脚本 |
| current run | `scripts/exp_invfac002/run_exp_invfac002.py` | 现有回测主脚本 |
| config template | `config/symbol_registry.yaml` | **待创建**：标的池配置 |
| ingestion pipeline | `src/data/unified_ingestion.py` | **待创建**：统一灌入程序 |
| health monitor | `scripts/maintenance/db_health_monitor.py` | **P2 待创建**：数据库健康检查 |

---

## 附录 B：快速填写检查清单

**问题定义层：**
- [x] 现状有数据支撑（非猜测）
- [x] 根因追到第三层
- [x] 问题陈述包含"对象+偏差+可观测指标"
- [ ] 问题陈述团队认可（墨涵确认）

**架构层：**
- [x] 单入口设计（所有日线数据走统一灌入程序）
- [x] staging 层 + 原子写入
- [x] batch_audit 审计日志表
- [x] 13 条 QC 规则清单
- [x] E-001 集成关系明确

**数据层：**
- [x] 标的池配置化（symbol_registry.yaml）
- [x] 历史首次全量重灌策略
- [x] 增量更新机制（每日自动触发）
- [x] 4 只缺失标的补全方案

**校验层：**
- [x] 行数完整性检查 (QC-1, QC-2)
- [x] 字段合理性检查 (QC-3 ~ QC-6)
- [x] 数值范围检查 (QC-7 ~ QC-9, QC-12, QC-13)
- [x] 除权除息日多日上下文检查
- [x] 审计日志 recording

**复现性：**
- [x] 送转股三原则 (PRINCIPLE_A/B/C)
- [x] exclusion_log 表设计
- [x] QFQ 基期修复方案

**三层架构：**
- [x] 层 1（根）：录入管线层
- [x] 层 2（日常）：数据库维护层
- [x] 层 3（辅助）：QC 层（压缩至 ~5 项）

**执行计划：**
- [x] 工时估算 (P0: ~4-5h, P1: ~2h, P2: ~3h)
- [x] 实施顺序 (P0→P1→P2)
- [x] 2 个月并行验证期
- [x] 风险与缓解

---

## 附录 C：代码版本与环境信息（首次实施前填写）

> 以下信息在首次实施开始时填写，作为版本锚点。

**代码版本：**
- git: ⬜ 已使用（记录 commit hash） | ✅ 未使用版本管理（工作副本，未提交）
- 当前工作目录：`C:\Users\17699\mozhi_platform`

**环境信息：**
- OS: Windows 10.0.26200 (x64)
- Python: （待填写）
- 关键依赖：
  - akshare: （待填写）
  - numpy: （待填写）
  - pandas: （待填写）
  - pyyaml: （待填写）
- 数据库：SQLite (market_data.db)

**版本锁定记录：**
- 本方案 version: v1.2（P1 修复完成）
- 决策规则版本（送转股原则）：v1.0
- QC 规则版本（13 条）：复用 data_ingestion_standard.md v1.0
- 多源验证版本：v1.0（2026-05-25 试验）

---

> **文档状态**: v1.2 P1 修复完成 — 待 Owner 签署
> **修复记录**: 
> 1. §1.3 E-001 关系描述修正（玄知 P1）
> 2. §7 工时估算更新：QCEngine 1.5h→2.5h（玄知 P1）
> 3. §7 工时估算更新：测试 0.5h→1h（玄知 P1）
> 4. §3.4 QC-11 ratio_match 跳变索引问题修复（墨萱 P1）
> 5. §3.5 新增小比例送转处理计划（墨萱 P1）
> 6. §4.1 YAML schema 校验防御（墨萱 P1）
> 7. §2.6 新增 API 限流管理（墨萱 P1）
> 8. §4.2 新增重灌备份机制与策略说明（墨萱 P1）
> 9. §2.3 batch_audit 新增 e001_batch_id 字段（墨萱 P1）
> **建议审查人**: 墨涵（Owner签署）
