# Report Generator 接入方案

> 作者: 墨衡 | 日期: 2026-05-16 | 版本: v1.0

---

## 1. 适配器设计：`DBtoStrategyResult`

### 1.1 数据来源

- **回测指标**: `C:\Users\17699\mo_zhi_sharereports\analysis.db` → `backtest_results` 表
- **净值序列**: `analysis.db` → `backtest_equity_series` 表
- **行情数据**: `analysis.db` → `stock_daily` 表（dates/closes）
- **交易明细**: 当前 backtest_results 表不存储单笔交易明细，需补充

### 1.2 字段映射表

| StrategyResult 字段 | 来源表 | 来源字段 | 转换逻辑 |
|---|---|---|---|
| `id` | backtest_results | `strategy_name` | 直接映射，如 `"grid"` |
| `name` | backtest_results | `strategy_name` | 映射为中文名（grid→网格, trend→趋势, reversal→反转） |
| `signal_desc` | — | — | 从 strategy_name 推导："基于{策略名}信号触发" |
| `params_desc` | backtest_results | `parameters` | JSON 字符串格式化展示 |
| `params_dict` | backtest_results | `parameters` | JSON 反序列化 |
| `dates` | stock_daily | `date` | 按 `code` + 日期范围过滤，转换为 MM-DD 格式 |
| `closes` | stock_daily | `close` | 按日期排序的收盘价列表 |
| `trades` | — | — | ⚠️ **缺失**，需补充 trade_records 表或在 backtest_results 中增加明细存储 |
| `nav` | backtest_equity_series | `equity` | 归一化处理（equity / initial_capital） |
| `benchmark_nav` | — | — | 从 stock_daily close 计算买入持有净值（close / close[0]） |
| `total_return` | backtest_results | `total_return` | 直接映射（已是 % 值） |
| `annual_return` | backtest_results | `annual_return` | 直接映射 |
| `base_return` | — | — | 计算：(close[-1] - close[0]) / close[0] * 100 |
| `alpha` | — | — | **缺失**，计算：total_return - base_return |
| `sharpe` | backtest_results | `sharpe_ratio` | 直接映射 |
| `max_drawdown` | backtest_results | `max_drawdown` | 直接映射 |
| `win_rate` | backtest_results | `win_rate` | 直接映射 |
| `profit_loss_ratio` | — | — | **缺失**，需从 trade 明细计算 |
| `avg_hold_days` | — | — | **缺失**，需从 trade 明细计算 |
| `grade` | backtest_results | — | 通过 `calc_t1_grade()` 重新计算生成 |

### 1.3 缺失字段处理方案

| 缺失字段 | 影响 | 处理方案 |
|---|---|---|
| `trades` (明细) | **严重** — 交易明细表、盈亏统计、信号标注全部无法渲染 | 方案A：在 `backtest_results` 新增 `trade_records` 子表存储单笔交易；方案B：适配器返回空列表，报告中交易明细区域显示"数据不可用" |
| `profit_loss_ratio` | **中等** — 绩效摘要中此指标为 0 | 从 trade 明细计算盈亏比，若无明细则默认为 0.0 |
| `avg_hold_days` | **中等** — 绩效摘要中此指标为 0 | 从 trade 明细计算平均持仓天数，若无明细则默认为 0.0 |
| `alpha` | **低** — 超额收益显示为 0 | 公式计算：`total_return - base_return`，无需存储 |
| `regime_stats` | **低** — 市场状态分析区域为空 | 可从 `market_context` 表（knowledge.db）关联计算 |

**推荐方案**: 优先实现方案A（新建 `trade_records` 表），在回测引擎落库阶段同步写入 trade 明细。适配器只负责读取，不承担数据补齐责任。

### 1.4 适配器接口设计

```python
class DBtoStrategyResult:
    """从 analysis.db 读取数据并构造 StrategyResult"""

    def __init__(self, db_path: str = "analysis.db"):
        self.db = sqlite3.connect(db_path)

    def to_strategy_result(self, result_id: int) -> StrategyResult:
        """按 result_id 读取单条记录"""
        ...

    def to_strategy_results(
        self, strategy_name: str | None = None,
        date_range: tuple[str, str] | None = None
    ) -> list[StrategyResult]:
        """批量读取，支持按策略名或日期范围过滤"""
        ...

    def close(self):
        self.db.close()
```

---

## 2. 晨报管线接入点

### 2.1 流水线位置

```
Step1 (数据采集) → Step2 (深度分析) → Step3 (定稿) → Step4 (审查)
                                                         ↓
                                              Step4.5 (回测报告生成) ← 新增
                                                         ↓
                                              Step5 (发布+推送)
```

- **放在 Step4（墨萱汇总定稿 + 质量审查）之后**，确保报告内容已锁定
- **作为 Step4.5**，不影响 Step1-4 的流程
- 仅在有新回测结果时触发（检查 `backtest_results` 表当日是否有新记录）

### 2.2 调用流程

```
1. Step4 完成 → dispatcher 收到 REVIEW_READY
2. dispatcher 检查今日是否有新回测结果
3. 若有 → 调用 report_generator.py 适配器
4. 适配器读取 analysis.db → 构造 StrategyResult 列表
5. 调用 ReportGenerator().render_full(results, output=...)
6. HTML 报告保存到 reports/backtest/html/
7. 报告路径写入 Step5 的推送清单
```

### 2.3 触发条件

- **自动**: Step4 完成后，dispatcher 扫描 `backtest_results` 表中 `created_at` 为今日的记录
- **手动**: 通过 trigger 文件 `signals/triggers/trigger_reportgen_{task_id}.json` 手动触发

### 2.4 HTML 报告保存路径

```
reports/backtest/html/{YYYYMMDD}_{策略组名}.html
```

示例:
```
reports/backtest/html/20260516_trend_grid_reversal.html
reports/backtest/html/20260516_grid_only.html
```

---

## 3. 步骤代价评估

### 3.1 代码量估计

| 模块 | 文件 | 预估行数 | 说明 |
|---|---|---|---|
| 适配器核心类 | `adapters/db_strategy_result.py` | ~120 行 | 包含 DB连接、查询、字段映射、缺失字段填充 |
| 交易明细子表 | (SQL DDL) | ~10 行 | `CREATE TABLE trade_records (...)` |
| 晨报管线集成 | `pipeline/step45_reportgen.py` | ~60 行 | Dispatcher 调用、触发条件检查、路径生成 |
| 配置更新 | `config/pipeline.yaml` | ~15 行 | 新增 step4.5 步骤定义 |
| 集成测试 | `tests/test_reportgen_integration.py` | ~80 行 | 适配器单元测试 + 管线集成测试 |
| **合计** | | **~285 行** | |

### 3.2 集成测试方案

1. **单元测试（适配器）**
   - Mock `backtest_results` 表数据 + `stock_daily` 数据
   - 验证字段映射正确性（每个字段逐一对比）
   - 验证缺失字段的默认值
   - 边界情况：空结果集、缺失净值序列、日期范围无数据

2. **集成测试（管线）**
   - 模拟 Step4 完成信号
   - 检查是否触发适配器调用
   - 验证 HTML 文件生成到指定路径
   - 验证 HTML 文件可被浏览器正常打开（含 Chart.js 渲染）

3. **回归测试**
   - 使用已有回测运行记录（如 `run_trend_601857.SH_test_20260516_105801`）
   - 对比适配器输出 vs 手动构造的预期 StrategyResult
   - 确认 no regressions on 已有数据

### 3.3 风险点

| 风险 | 等级 | 说明 | 缓解措施 |
|---|---|---|---|
| **交易明细缺失** | 🔴 高 | `backtest_results` 表无单笔交易记录，trade_detail 区域显示为空白 | 优先实现 trade_records 子表，适配器应优雅降级（显示"数据不可用"） |
| **净值序列不全** | 🟡 中 | `backtest_equity_series` 可能未记录所有回测运行 | 适配器 reader 加 null check，降级为简单基准净值 |
| **参数格式不一致** | 🟡 中 | `parameters` 字段存储格式不统一（有的存 JSON，有的存纯文本） | 适配器加格式检测：先 try JSON，失败则直接显示 |
| **大回测数据性能** | 🟢 低 | 单次回测 equity 数据可能超过 2000 行 | Chart.js 渲染无忧，极限情况超过 5000 点可考虑下采样 |
| **Step4.5 异常不影响主流程** | 🟢 低 | 报告生成失败不应阻塞 Step5 发布 | Exception 捕获后写 FAILED 文件，主流程继续 |

### 3.4 实施顺序建议

1. **P0** (必做): 适配器核心类 + trade_records 子表 DDL
2. **P1** (必做): 管线 Step4.5 接入 + dispatcher 触发逻辑
3. **P2** (建议): 缺失字段优雅降级（trade 明细区域不可用时友好提示）
4. **P3** (可选): 多策略对比的净值归一化对齐

---

## 4. 附录：Adapter 伪代码

```python
# adapters/db_strategy_result.py
import json
import sqlite3
from pathlib import Path
from datetime import date
from typing import Optional

from backtest_report_generator import StrategyResult, TradeRecord, calc_t1_grade


DB_PATH = Path(__file__).parent.parent / "data" / "analysis.db"


class DBtoStrategyResult:
    """Adapter: analysis.db → StrategyResult"""

    STRATEGY_NAMES = {
        "grid":     "网格交易",
        "trend":    "趋势跟踪",
        "reversal": "均值回归",
    }

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row

    def get_by_id(self, result_id: int) -> Optional[StrategyResult]:
        row = self.db.execute(
            "SELECT * FROM backtest_results WHERE id = ?", (result_id,)
        ).fetchone()
        if not row:
            return None
        return self._build(row)

    def get_today_results(self) -> list[StrategyResult]:
        today = date.today().isoformat()
        rows = self.db.execute(
            "SELECT * FROM backtest_results WHERE date(created_at) = ?",
            (today,)
        ).fetchall()
        return [self._build(r) for r in rows]

    def _build(self, row) -> StrategyResult:
        # 行情数据
        closes, dates = self._load_price_data(row["strategy_name"])

        # 净值序列 + 基准
        nav = self._load_equity_series(row["id"])
        benchmark_nav = [c / closes[0] for c in closes]

        # 交易明细（若有）
        trades = self._load_trades(row["id"])

        # 计算 alpha
        base_return = (closes[-1] / closes[0] - 1) * 100
        alpha = row["total_return"] - base_return

        return StrategyResult(
            id=row["strategy_name"],
            name=self.STRATEGY_NAMES.get(row["strategy_name"], row["strategy_name"]),
            signal_desc=f"基于{row['strategy_name']}信号触发",
            params_desc=self._format_params(row["parameters"]),
            params_dict=self._parse_params(row["parameters"]),
            dates=dates,
            closes=closes,
            trades=trades,
            nav=[v / nav[0] for v in nav],
            benchmark_nav=benchmark_nav,
            total_return=row["total_return"],
            annual_return=row["annual_return"],
            base_return=base_return,
            alpha=alpha,
            sharpe=row["sharpe_ratio"],
            max_drawdown=row["max_drawdown"],
            win_rate=row["win_rate"],
            profit_loss_ratio=0.0,  # 待 trade 明细补齐
            avg_hold_days=0.0,       # 待 trade 明细补齐
            grade=self._derive_grade(row),
        )

    def _load_price_data(self, strategy_name: str):
        """从 stock_daily 读取最近 85 个交易日数据"""
        # 注意：实际应按策略对应的标的代码查询，这里简化处理
        rows = self.db.execute("""
            SELECT date, close FROM stock_daily
            WHERE code = '601857'
            ORDER BY date DESC LIMIT 85
        """).fetchall()
        dates = [r["date"][5:].replace("-", "") for r in reversed(rows)]
        closes = [r["close"] for r in reversed(rows)]
        return closes, dates

    def _load_equity_series(self, result_id: int):
        """从 backtest_equity_series 读取净值"""
        rows = self.db.execute("""
            SELECT equity FROM backtest_equity_series
            WHERE result_id = ?
            ORDER BY date
        """, (result_id,)).fetchall()
        return [r["equity"] for r in rows]

    def _load_trades(self, result_id: int) -> list:
        """读取交易明细（预留，需 trade_records 表就绪）"""
        return []

    def _format_params(self, raw: str) -> str:
        try:
            d = json.loads(raw)
            return "; ".join(f"{k}={v}" for k, v in d.items())
        except (json.JSONDecodeError, TypeError):
            return raw or "-"

    def _parse_params(self, raw: str) -> dict:
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}

    def _derive_grade(self, row) -> str:
        grade, _ = calc_t1_grade(
            row["sharpe_ratio"], row["max_drawdown"],
            row["win_rate"], row["total_trades"]
        )
        return grade

    def close(self):
        self.db.close()
```

---

> 方案状态: ✅ 已就绪，待评审后进入实施
