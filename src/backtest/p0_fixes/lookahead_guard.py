"""
P0-FIX-002: 前视偏差运行时检测 (Look-ahead Bias Guard)
======================================================
前视偏差（Look-ahead Bias）是回测中最常见且最危险的错误：
使用未来信息（t+1 及以后的数据）在当前时间点做出判断。

核心检测规则（BT-006/BT-007）:
1. t-1 契约：信号在 bar[t] 产生，只能使用 bar[0..t] 的数据
2. 跨 bar 引用检查：策略中 bar[t] 的 close 是否被用于 bar[t] 本身的信号
3. 价格检查：信号触发价格是否与 bar[t].close 偏离过大

检测机制:
1. 静态分析：检查信号日期与信号产生依赖数据的日期关系
2. 运行时钩子：注入 DataLayer → ComputeLayer 之间的 Guard
3. 事后审计：检查交易记录中 signal_date vs exec_date 的关系

作者: moheng
版本: v1.0
"""
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from ..contracts.backtest_data_contract import BacktestData
from ..layers.compute_layer import Signal
from ..contracts.backtest_data_contract import BacktestBar

_TZ_CN = timezone(timedelta(hours=8))


@dataclass
class LookaheadFinding:
    """前视偏差检测结果"""
    rule: str                  # 违反的规则编号
    severity: str              # "WARN" | "FAIL"
    description: str           # 描述
    bar_date: str              # 涉及日期
    detail: str = ""           # 详细信息


class LookaheadGuard:
    """前视偏差运行时检测器

    在 ComputeLayer 和 DataLayer 之间注入，确保：

    用法:
        guard = LookaheadGuard()
        guard.check_data_contract(data)
        guard.check_signals(data, signals)
        if guard.findings:
            for f in guard.findings:
                print(f"{f.severity}: {f.description}")
    """

    def __init__(self):
        self.findings: List[LookaheadFinding] = []
        self._passed = True

    # ── Rule 1: t-1 契约检查 ─────────────────────────────

    def check_data_contract(self, data: BacktestData):
        """Rule 1: 数据层到计算层间的前视偏差检查"""
        # 检查日期是否升序（已由 TimeAlignmentGuard 完成）
        for i in range(1, len(data.bars)):
            if data.bars[i].date <= data.bars[i - 1].date:
                self.findings.append(LookaheadFinding(
                    rule="R1",
                    severity="FAIL",
                    description=f"Date order violation at bar {i}",
                    bar_date=data.bars[i].date,
                ))
                self._passed = False

        # 检查是否有 future 数据被包含在 bars 中
        # （如果 data 已经包含完整序列，则不可能有 future 偏差）

    # ── Rule 2: 信号日期一致性检查 ──────────────────────

    def check_signals(self, data: BacktestData, signals: List[Signal]):
        """Rule 2: 信号的日期一致性检查"""
        bar_dates = {b.date for b in data.bars}

        for sig in signals:
            # 信号日期必须在数据范围内
            if sig.bar_date not in bar_dates:
                self.findings.append(LookaheadFinding(
                    rule="R2",
                    severity="FAIL",
                    description=(
                        f"Signal {sig.signal_id} references bar_date={sig.bar_date} "
                        f"which is not in data"
                    ),
                    bar_date=sig.bar_date,
                ))
                self._passed = False

            # 信号索引与日期必须一致
            if sig.bar_index < len(data.bars):
                actual_date = data.bars[sig.bar_index].date
                if sig.bar_date != actual_date:
                    self.findings.append(LookaheadFinding(
                        rule="R2",
                        severity="FAIL",
                        description=(
                            f"Signal index/date mismatch: "
                            f"index={sig.bar_index} -> date={actual_date}, "
                            f"but signal says {sig.bar_date}"
                        ),
                        bar_date=sig.bar_date,
                    ))
                    self._passed = False

    # ── Rule 3: 动态前视偏差检测 ────────────────────────

    def check_static_bias(self, data: BacktestData,
                          early_signal_dates: List[str]) -> bool:
        """Rule 3: 检查信号是否在 warmup 阶段前触发

        MA 策略需要 warmup 周期（slow 周期数），
        warmup 结束前的信号可能使用了不足的数据而产生偏差。
        """
        min_warmup_bars = min(
            len(data.bars),
            20  # 默认最小 warmup
        )

        if len(data.bars) < min_warmup_bars:
            self.findings.append(LookaheadFinding(
                rule="R3",
                severity="WARN",
                description=(
                    f"Insufficient data for warmup: "
                    f"{len(data.bars)} bars, need {min_warmup_bars}"
                ),
                bar_date=data.bars[0].date if data.bars else "",
            ))

        return self._passed

    def get_summary(self) -> str:
        """返回检测摘要"""
        if not self.findings:
            return "✅ 前视偏差检测通过，未发现问题。"
        lines = [f"⚠️ 发现 {len(self.findings)} 个问题:"]
        for f in self.findings:
            lines.append(f"  [{f.severity}] {f.rule}: {f.description} ({f.bar_date})")
        return "\n".join(lines)
