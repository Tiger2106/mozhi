<!--
  author: 墨衡（MoHeng）
  task_id: P0-7-risk
  created: 2026-05-17 20:19 +08:00
  status: READY
  source: risk_action_plan_moheng_20260517.md §P0-7
-->

# P0-#7：回测 vs 实盘校准协议

> **风险：回测跑通 ≠ 实盘有效** — 当前仅验证「新旧Runner语义不变」（0%偏差），
> 未验证「语义本身是否正确」。需要建立回测vs实盘的定期校准机制。

---

## 1. 问题定位

**当前验证链：**

```
旧Runner输出 ──→ 0%偏差验证 ──→ 新Runner输出
                                      │
                                      ▼
                              ✅ 回测跑通（语义不变）
                                      │
                                      ❓ 实盘有效？（未验证）
                                      ▼
                              ⚠️ 策略决策建立在假设之上
```

**根因分析：**
- `test_method_comparison.py` 仅验证新旧Runner输出一致性（D6-D13）
- `monitoring/` 目录下**空无内容**（仅有 `__init__.py`）
- 没有任何运行时校准机制，系统无法自我检视策略是否按预期工作
- 回测模拟的滑点模型（`slippage_model.py`）、手续费模型（`fee_model.py`）假设可能与实盘不一致

**关键代码位置：**
- 回测结果：`src/backtest_results/` 目录下的JSON文件（如 `trend_601857_ma_fixed_default_*.json`）
- 性能指标：`src/backtest/performance.py`
- 交易日志：`src/backtest/trade_logger.py`
- 滑点模型：`src/backtest/slippage_model.py`
- 手续费模型：`src/backtest/fee_model.py`

---

## 2. 校准流程设计

### 2.1 月度校准周期

```
每月校准周期 (每月第一个交易日 09:00 触发)
       │
       ▼
┌──────────────────────────────────────────────────┐
│ Step 1: 数据采集                                  │
│   采集最近30个交易日的：                            │
│   ├── 回测模拟结果                                │
│   │   (给定起始资金 × 选定Method，同参数重新模拟)    │
│   ├── 实盘实际收益                                │
│   │   (从 account_manager 或 trading_log 获取)     │
│   └── 基准收益                                    │
│       (从 benchmark_data_source 获取沪深300/500)   │
└──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│ Step 2: 偏差计算                                  │
│   对每个活跃Method/策略计算以下指标：               │
│   ├── 收益偏差 = |回测收益 - 实盘收益|             │
│   ├── 超额偏差 = |(回测收益-基准)-(实盘收益-基准)|  │
│   ├── 胜率偏差 = |回测胜率 - 实盘胜率|             │
│   └── 最大回撤偏差 = |回测MDD - 实盘MDD|          │
└──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│ Step 3: 阈值判定                                  │
│                                                   │
│   收益偏差 ≤ 5%    → ✅ 正常（记录，无操作）        │
│                                                   │
│   5% < 偏差 ≤ 15% → ⚠️ 预警（标记calibrated=false)│
│                        发飞书群告警，需人工排查     │
│                                                   │
│   偏差 > 15%      → ❌ 严重偏差                     │
│                        暂停策略（自动）             │
│                        触发Kill Switch             │
│                        人工审计                     │
└──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│ Step 4: 校准报告输出                              │
│   写入 reports/calibration/                       │
│   ├── calibration_report_{YYYYMM}.json            │
│   └── calibration_result.md                       │
│                                                   │
│   飞书群推送：                                     │
│   ├── [每日] 偏差正常 → 仅记录日志                 │
│   ├── [每日] 偏差预警 → 飞书群消息                  │
│   └── [月度] 校准摘要 → 完整校准报告                │
└──────────────────────────────────────────────────┘
```

### 2.2 校准数据源映射

| 数据项 | 回测来源 | 实盘来源 | 对齐方法 |
|--------|---------|---------|---------|
| 收益 | `backtest_results/{method}_{symbol}_*.json` 中的 `pnl` | `account_manager.py` 中的持仓收益 | 同一时间窗口 |
| 交易记录 | `trade_logger.py` 输出的日志 | `order_lifecycle.py` + `settle_daily.py` | 按交易日对齐 |
| 持仓 | `position_manager.py` 的模拟持仓 | `account_manager.py` 的实际持仓 | 按交易日终值 |
| 基准 | `benchmark_data_source.py` | 同一数据源 | 复用基准获取逻辑 |

---

## 3. 核心实现设计

### 3.1 `calibrator.py` — 校准计算核心

```python
# src/monitoring/backtest_calibrator.py

"""
回测vs实盘校准模块。

目标: 建立回测模拟结果与实盘实际收益的定期对比验证。
每月第一个交易日自动触发。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ─── 数据模型 ──────────────────────────────────────────────

@dataclass
class CalibrationResult:
    """一次校准操作的结果"""
    method_name: str
    symbol: str
    backtest_return: float     # 回测收益（%）
    live_return: float         # 实盘收益（%）
    benchmark_return: float    # 基准收益（%）
    backtest_winrate: float    # 回测胜率
    live_winrate: float        # 实盘胜率
    backtest_mdd: float        # 回测最大回撤
    live_mdd: float            # 实盘最大回撤
    return_deviation: float    # 收益偏差
    excess_return_deviation: float  # 超额收益偏差
    winrate_deviation: float   # 胜率偏差
    mdd_deviation: float       # 最大回撤偏差
    verdict: str               # "PASS" | "WARN" | "FAIL"

    def to_dict(self) -> dict:
        return {
            "method_name": self.method_name,
            "symbol": self.symbol,
            "return_deviation": round(self.return_deviation, 4),
            "excess_return_deviation": round(self.excess_return_deviation, 4),
            "winrate_deviation": round(self.winrate_deviation, 4),
            "mdd_deviation": round(self.mdd_deviation, 4),
            "verdict": self.verdict,
        }


# ─── 偏差阈值 ──────────────────────────────────────────────

# 调整建议: 初期宽松（5%/15%），稳定后收紧（3%/10%）
DEVIATION_THRESHOLD_WARN = 0.05   # 5% — 预警线
DEVIATION_THRESHOLD_FAIL = 0.15   # 15% — 严重偏差


# ─── 核心校准函数 ──────────────────────────────────────────

class Calibrator:
    """回测vs实盘校准器。

    Usage:
        calibrator = Calibrator(data_dir="data")
        result = calibrator.calibrate(method_name="ma_cross", symbol="601857")
    """

    def __init__(
        self,
        data_dir: str = "data",
        threshold_warn: float = DEVIATION_THRESHOLD_WARN,
        threshold_fail: float = DEVIATION_THRESHOLD_FAIL,
    ):
        self.data_dir = Path(data_dir)
        self.threshold_warn = threshold_warn
        self.threshold_fail = threshold_fail

    def calibrate(
        self,
        method_name: str,
        symbol: str,
        lookback_days: int = 30,
    ) -> CalibrationResult:
        """对指定Method执行一次校准。

        1. 从 backtest_results/ 加载回测数据
        2. 从实盘数据源加载实际交易数据
        3. 计算偏差
        4. 输出判定
        """
        # TODO: Step 1 — 加载回测收益
        backtest_return = self._load_backtest_return(method_name, symbol, lookback_days)

        # TODO: Step 2 — 加载实盘收益
        live_return = self._load_live_return(method_name, symbol, lookback_days)

        # TODO: Step 3 — 加载基准收益
        benchmark_return = self._load_benchmark_return(symbol, lookback_days)

        # TODO: Step 4 — 加载胜率/回撤指标
        backtest_winrate = 0.0
        live_winrate = 0.0
        backtest_mdd = 0.0
        live_mdd = 0.0

        # TODO: Step 5 — 计算偏差
        return_deviation = abs(backtest_return - live_return)
        excess_backtest = backtest_return - benchmark_return
        excess_live = live_return - benchmark_return
        excess_return_deviation = abs(excess_backtest - excess_live)
        winrate_deviation = abs(backtest_winrate - live_winrate)
        mdd_deviation = abs(backtest_mdd - live_mdd)

        # Step 6 — 判定
        if return_deviation > self.threshold_fail:
            verdict = "FAIL"
        elif return_deviation > self.threshold_warn:
            verdict = "WARN"
        else:
            verdict = "PASS"

        return CalibrationResult(
            method_name=method_name,
            symbol=symbol,
            backtest_return=backtest_return,
            live_return=live_return,
            benchmark_return=benchmark_return,
            backtest_winrate=backtest_winrate,
            live_winrate=live_winrate,
            backtest_mdd=backtest_mdd,
            live_mdd=live_mdd,
            return_deviation=return_deviation,
            excess_return_deviation=excess_return_deviation,
            winrate_deviation=winrate_deviation,
            mdd_deviation=mdd_deviation,
            verdict=verdict,
        )

    def _load_backtest_return(self, method: str, symbol: str, days: int) -> float:
        """从 backtest_results/ 中提取指定Method的回测收益。"""
        # 实现: 解析 backtest_results/{method}_{symbol}_*.json PNL 数据
        results_dir = self.data_dir / "backtest_results"
        pattern = f"{method}_{symbol}_*.json"
        files = sorted(results_dir.glob(pattern))
        if not files:
            logger.warning("未找到回测结果: %s/%s", method, symbol)
            return 0.0
        # 取最新文件
        latest = files[-1]
        with open(latest) as f:
            data = json.load(f)
        pnl = data.get("pnl", data.get("total_pnl", 0))
        return pnl / 100.0  # 转为百分比

    def _load_live_return(self, method: str, symbol: str, days: int) -> float:
        """从实盘数据源提取收益。"""
        # TODO: 实现实盘数据读取
        return 0.0

    def _load_benchmark_return(self, symbol: str, days: int) -> float:
        """从基准数据源提取基准收益。"""
        # 复用 existing benchmark_data_source.py
        from backtest.benchmark_data_source import BenchmarkDataSource
        source = BenchmarkDataSource()
        end = pd.Timestamp.now(tz="Asia/Shanghai")
        start = end - pd.Timedelta(days=days)
        bm_data = source.fetch_range(start, end)
        if bm_data is None or len(bm_data) < 2:
            return 0.0
        return (bm_data["close"].iloc[-1] / bm_data["close"].iloc[0] - 1.0) * 100

    def _load_trade_stats(self, method: str, symbol: str, days: int) -> Tuple[float, float]:
        """加载交易统计（胜率、最大回撤）。"""
        # TODO: 从 trade_logger 或 settle_daily 中提取
        return (0.0, 0.0)
```

### 3.2 `calibration_report.py` — 报告生成

```python
# src/monitoring/calibration_report.py

"""校准报告生成模块。"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from .backtest_calibrator import Calibrator, CalibrationResult


class CalibrationReport:
    """生成校准报告并发送告警。"""

    def __init__(self, report_dir: str = "reports/calibration"):
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self, results: List[CalibrationResult]) -> str:
        """生成月度校准报告。

        Returns:
            str: 报告文件路径。
        """
        now = datetime.now()
        filename = f"calibration_report_{now.strftime('%Y%m')}.json"
        filepath = self.report_dir / filename

        report = {
            "timestamp": now.isoformat(),
            "calibrated": all(r.verdict == "PASS" for r in results),
            "summary": {
                "total_methods": len(results),
                "pass": sum(1 for r in results if r.verdict == "PASS"),
                "warn": sum(1 for r in results if r.verdict == "WARN"),
                "fail": sum(1 for r in results if r.verdict == "FAIL"),
            },
            "results": [r.to_dict() for r in results],
        }

        with open(filepath, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return str(filepath)

    def format_alert_message(self, results: List[CalibrationResult]) -> str:
        """生成飞书群告警消息。"""
        failed = [r for r in results if r.verdict == "FAIL"]
        warned = [r for r in results if r.verdict == "WARN"]

        lines = ["【回测vs实盘校准报告】", ""]
        if failed:
            lines.append(f"🔴 严重偏差 ({len(failed)} 项):")
            for r in failed:
                lines.append(f"  {r.method_name}/{r.symbol}: 收益偏差 {r.return_deviation:.1%}")
            lines.append("")

        if warned:
            lines.append(f"🟡 预警 ({len(warned)} 项):")
            for r in warned:
                lines.append(f"  {r.method_name}/{r.symbol}: 收益偏差 {r.return_deviation:.1%}")
            lines.append("")

        pass_count = len(results) - len(failed) - len(warned)
        lines.append(f"✅ 正常: {pass_count}/{len(results)}")
        lines.append(f"📄 报告: reports/calibration/calibration_report_{datetime.now().strftime('%Y%m')}.json")

        return "\n".join(lines)
```

---

## 4. 运行模式

### 4.1 月度自动校准

```python
def run_monthly_calibration(methods: List[str] = None, symbols: List[str] = None):
    """月度校准入口。每月第一个交易日调用。"""
    calibrator = Calibrator(data_dir="data")
    reporter = CalibrationReport()

    if methods is None:
        from backtest.methods.registry import discover_methods
        methods = list(discover_methods().keys())

    if symbols is None:
        symbols = ["601857", "600028", "000001"]

    results: List[CalibrationResult] = []
    for method in methods:
        for symbol in symbols:
            try:
                result = calibrator.calibrate(method, symbol)
                results.append(result)
            except Exception as e:
                logger.error("校准失败 %s/%s: %s", method, symbol, e)

    reporter.generate_report(results)
    msg = reporter.format_alert_message(results)
    # TODO: 发送飞书群消息
    logger.info("月度校准完成: %s", msg)
```

### 4.2 cron 配置

```yaml
# Windows Task Scheduler 配置
名称: MoZhi-Monthly-Calibration
触发: 每月第一个交易日 09:00
操作:
  程序: python
  参数: -m src.monitoring.backtest_calibrator --mode monthly --notify
  工作目录: C:\Users\17699\mozhi_platform
```

### 4.3 手动触发

```bash
# 手动运行校准
python -m src.monitoring.backtest_calibrator --method ma_cross --symbol 601857

# 全Method全Symbol校准
python -m src.monitoring.backtest_calibrator --mode full --notify

# 仅生成报告（基于已有数据）
python -m src.monitoring.backtest_calibrator --mode report-only
```

---

## 5. 偏差来源排查指南

当校准发现偏差时，按以下优先级排查：

### 5.1 常见偏差原因

| 偏差类型 | 可能原因 | 排查路径 |
|----------|---------|---------|
| **收益偏差** | 滑点模型不准确 | 检查 `slippage_model.py` 参数与实际成交差异 |
| 收益偏差 | 手续费模型偏差 | 检查 `fee_model.py` 与实际佣金/印花税差异 |
| 收益偏差 | 数据源差异 | 检查回测使用数据源 vs 实盘数据源是否一致 |
| **胜率偏差** | 信号延迟 | 检查 `signal_bridge.py` 到实盘执行的时间差 |
| 胜率偏差 | 部分成交 | 检查 `order_executor.py` 的成交概率假设 |
| **回撤偏差** | 流动性假设 | 检查回测是否过度假设了流动性 |
| 回撤偏差 | 价格限制 | 检查是否考虑涨跌停等交易限制 |

### 5.2 排查流程

```
发现偏差 > 5%
  │
  ├─→ 检查数据源日期范围是否一致
  │     (回测数据 vs 实盘数据的交易日对齐)
  │
  ├─→ 检查配置参数是否一致
  │     (回测使用的method params vs 实盘策略params)
  │
  ├─→ 检查滑点+手续费模型
  │     (slippage_model.py + fee_model.py 的参数假设)
  │
  └─→ 检查信号执行延迟
        (从signal_bridge生成到order_executor执行的时间差)
```

---

## 6. 依赖与阻塞

| 依赖项 | 状态 | 说明 |
|--------|:----:|------|
| 实盘收益数据源 | ⬜ 待实现 | 需从 `account_manager.py` 或 `settle_daily.py` 提取 |
| `backtest_calibrator.py` | ⬜ 待编码 | 核心校准逻辑（预估3h） |
| `calibration_report.py` | ⬜ 待编码 | 报告生成 + 飞书消息（预估1h） |
| 月度 cron 配置 | ⬜ 待配置 | Windows Task Scheduler（预估0.5h） |
| 基准数据兼容性 | ✅ 已有 | `benchmark_data_source.py` 可直接复用 |

**阻塞项：** 实盘收益数据的标准化提取是**硬依赖**。需要确保 `account_manager.py` 和 `settle_daily.py` 输出格式一致，且按Method/Symbol可拆解。

---

## 7. 实施清单

- [ ] 1. 创建 `src/monitoring/backtest_calibrator.py`（核心校准逻辑）
- [ ] 2. 创建 `src/monitoring/calibration_report.py`（报告生成）
- [ ] 3. 实现实盘收益数据提取（对接 `account_manager.py` + `settle_daily.py`）
- [ ] 4. 补充 `benchmark_data_source.py` 的按窗口查询接口（若不存在）
- [ ] 5. 编写 `tests/test_calibrator.py` 单元测试
- [ ] 6. 配置月度 cron 任务
- [ ] 7. 编写排查指南文档（已含在§5）

> **预估实施时间：3h**（核心逻辑2h + 测试+集成1h）

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 20:19 +08:00*
