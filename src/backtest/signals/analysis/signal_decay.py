"""
信号衰减分析器
分析信号从产生到执行的延迟对收益的影响，计算信号有效半衰期和最优执行窗口。

Author: 墨衡 (generated)
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class TradeRecord:
    """标准化交易记录"""
    signal_date: str
    entry_date: str
    pnl: float
    win: bool = True
    delay_days: int = 0


class SignalDecayAnalyzer:
    """
    信号衰减分析。
    量化信号从生成到执行的延迟与收益的关系，提供半衰期和最优窗口。
    """

    MODELS = ['linear', 'exponential', 'step']

    def __init__(self, trade_data: List[dict]):
        """
        trade_data: [{signal_date, entry_date, pnl, ...}, ...]
        """
        self.raw_trades = trade_data
        self._parsed: List[TradeRecord] = []
        self._parse_trades()

    def _parse_trades(self):
        """解析原始交易数据，计算延迟天数"""
        for t in self.raw_trades:
            signal_d = t.get('signal_date') or t.get('signal_generated', '')
            entry_d = t.get('entry_date') or t.get('trade_opened', '')
            if not signal_d or not entry_d:
                continue
            try:
                from datetime import datetime as dt
                sd = dt.strptime(signal_d, '%Y%m%d')
                ed = dt.strptime(entry_d, '%Y%m%d')
                delay = (ed - sd).days
                if delay < 0:
                    continue  # 无效延迟
                pnl = float(t.get('pnl', t.get('return', t.get('return_pct', 0))))
                rec = TradeRecord(
                    signal_date=signal_d,
                    entry_date=entry_d,
                    pnl=pnl,
                    win=pnl > 0,
                    delay_days=delay,
                )
                self._parsed.append(rec)
            except (ValueError, TypeError):
                continue

    @property
    def trades(self) -> List[TradeRecord]:
        return self._parsed

    @property
    def count(self) -> int:
        return len(self._parsed)

    def decay_curve(self, max_lag: int = 30) -> Dict[str, list]:
        """
        生成衰减曲线。按延迟天数分组，计算每组平均收益和胜率。
        """
        if not self._parsed:
            return {'lag_days': [], 'avg_return': [], 'win_rate': [], 'count': []}

        buckets: Dict[int, List[float]] = {}
        wins: Dict[int, List[bool]] = {}
        for t in self._parsed:
            d = min(t.delay_days, max_lag) if max_lag > 0 else t.delay_days
            buckets.setdefault(d, []).append(t.pnl)
            wins.setdefault(d, []).append(t.win)

        result = {'lag_days': [], 'avg_return': [], 'win_rate': [], 'count': []}
        for d in sorted(buckets.keys()):
            result['lag_days'].append(d)
            rets = buckets[d]
            result['avg_return'].append(float(np.mean(rets)))
            result['win_rate'].append(float(np.mean(wins.get(d, [False]))))
            result['count'].append(len(rets))

        return result

    def half_life(self, model: str = 'exponential') -> float:
        """
        计算信号有效半衰期。
        - 'exponential': log-linear回归拟合衰减率
        - 'linear': 线性回归，半衰期 = 收益衰减到一半所需天数
        - 'step': 步进模式，以最近N天均值衰减到一半为界
        """
        curve = self.decay_curve(max_lag=30)
        lags = np.array(curve['lag_days'], dtype=float)
        rets = np.array(curve['avg_return'], dtype=float)

        if len(lags) < 2 or np.all(rets <= 0):
            return 0.0

        # 归一化收益到 [0, 1]
        r_max = np.max(rets)
        if r_max <= 0:
            return 0.0
        r_norm = rets / r_max

        if model == 'exponential':
            # log(return) ~ -b * lag 拟合
            mask = r_norm > 0
            if np.sum(mask) < 2:
                return 0.0
            log_r = np.log(r_norm[mask])
            l = lags[mask]
            b, _ = np.polyfit(l, log_r, 1)
            return float(np.log(2) / (-b)) if b < 0 else float('inf')

        elif model == 'linear':
            b, _ = np.polyfit(lags, r_norm, 1)
            if b >= 0:
                return float('inf')
            half_y = 0.5
            return float((half_y - (r_norm[0] if len(r_norm) > 0 else 0)) / b)

        elif model == 'step':
            # 找到收益首次低于50%的点
            for i, v in enumerate(r_norm):
                if v < 0.5:
                    return float(lags[i])
            return float(lags[-1]) if len(lags) > 0 else 0.0

        return 0.0

    def optimal_window(self, min_win_rate: float = 0.5) -> Dict:
        """
        找到满足最低胜率的最优信号有效期。
        返回 {optimal_days, win_rate, trade_count}
        """
        if not self._parsed:
            return {'optimal_days': 0, 'win_rate': 0, 'trade_count': 0}

        # 累积胜率：延迟<=N天的所有交易
        max_d = max(t.delay_days for t in self._parsed)
        best = {'optimal_days': 0, 'win_rate': 0.0, 'trade_count': 0}

        for n in range(1, max_d + 1):
            subset = [t for t in self._parsed if 0 <= t.delay_days <= n]
            if not subset:
                continue
            wr = float(np.mean([t.win for t in subset]))
            if wr >= min_win_rate and len(subset) > best['trade_count']:
                best = {
                    'optimal_days': n,
                    'win_rate': round(wr, 4),
                    'trade_count': len(subset),
                }

        return best

    def summary(self) -> Dict:
        """完整分析摘要"""
        return {
            'total_trades': self.count,
            'decay_curve': self.decay_curve(),
            'half_life_days': {
                m: round(self.half_life(m), 2) for m in self.MODELS
            },
            'optimal_window': self.optimal_window(),
            'max_delay_days': max((t.delay_days for t in self._parsed), default=0),
            'avg_delay_days': round(float(np.mean(
                [t.delay_days for t in self._parsed])), 1) if self._parsed else 0,
        }
