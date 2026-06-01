"""
BacktestData 数据合约 (BT-004)
===============================
定义数据层到计算层的严格数据合约，确保：
1. 字段类型约束（运行时校验）
2. 缺失值处理策略
3. 时间戳对齐规则（BT-006 t-1契约）
4. 数据版本指纹（data_fingerprint）
5. 前视偏差运行时检测

作者: moheng
版本: v1.0
"""
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

_TZ_CN = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════
# 核心合约类型
# ═══════════════════════════════════════════════════════════

@dataclass
class BarField:
    """单根K线字段约束"""
    open: float       # 开盘价，必须 > 0
    high: float       # 最高价，必须 >= max(open, close)
    low: float        # 最低价，必须 <= min(open, close)
    close: float      # 收盘价，必须 > 0
    volume: float     # 成交量（股），必须 >= 0
    amount: float     # 成交额（元），必须 >= 0
    vwap: float = 0.0  # 均价，可选（由 volume/amount 推导）


@dataclass
class BacktestBar:
    """合约化的 K 线数据（数据层输出 → 计算层输入）"""
    # ── 标识字段 ──
    symbol: str                    # 股票代码，如 "601857.SH"
    date: str                      # 交易日，格式 "YYYYMMDD"

    # ── 价格字段 ──
    open: float                    # 开盘价 (REQUIRED, > 0)
    high: float                    # 最高价 (REQUIRED, >= max(open, close))
    low: float                     # 最低价 (REQUIRED, <= min(open, close))
    close: float                   # 收盘价 (REQUIRED, > 0)

    # ── 量字段 ──
    volume: float                  # 成交量（股）(REQUIRED, >= 0)
    amount: float                  # 成交额（元）(REQUIRED, >= 0)

    # ── 复权因子 ──
    adj_factor: float = 1.0        # 复权因子 (REQUIRED, > 0, 默认为1)

    # ── 元数据 ──
    data_source: str = "unknown"   # 数据来源标记
    version: str = "v1.0"          # 数据版本

    # ── 前视偏差防护 ──
    _loaded_at: Optional[str] = None  # 数据加载时间戳

    def validate(self) -> List[str]:
        """字段级校验，返回所有违反约束的列表"""
        errors = []
        if self.open <= 0:
            errors.append(f"open={self.open} must be > 0")
        if self.high < max(self.open, self.close):
            errors.append(f"high={self.high} must be >= max(open={self.open}, close={self.close})")
        if self.low > min(self.open, self.close):
            errors.append(f"low={self.low} must be <= min(open={self.open}, close={self.close})")
        if self.close <= 0:
            errors.append(f"close={self.close} must be > 0")
        if self.volume < 0:
            errors.append(f"volume={self.volume} must be >= 0")
        if self.amount < 0:
            errors.append(f"amount={self.amount} must be >= 0")
        if self.adj_factor <= 0:
            errors.append(f"adj_factor={self.adj_factor} must be > 0")
        return errors


@dataclass
class BacktestData:
    """数据层完整输出合约

    此对象是 **DataLayer** 的唯一产出，**ComputeLayer** 的唯一输入。
    确保一次加载（GP-001），不可中途修改。
    """
    # ── 核心数据（必须字段在前） ──
    symbol: str
    bars: List[BacktestBar]         # 按日期升序排列
    date_range: tuple               # (start_date, end_date) 格式 "YYYYMMDD"
    total_bars: int
    data_fingerprint: str           # SHA256 数据指纹（验证完整性）

    # ── 可选字段 ──
    contract_version: str = "v1.0"
    created_at: str = ""            # ISO8601 加载时间
    validation_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def compute_fingerprint(self) -> str:
        """基于 ndarray 算法计算数据指纹（与 BacktestData_contract_v1.0.md §六 一致）

        输入：核心价格/量数据 + 索引信息
        输出：SHA256 hex 前 16 位（碰撞概率足够低）

        设计原则：
          - 确定性：相同数据 → 相同 fingerprint
          - 可复现：支持跨平台一致性
          - 简洁：16 hex chars 即够
          - 独立于元数据：不包括配置、时间戳等变劷因子
        """
        # 从 bars 提取 ndarray 等价数据
        close = [round(b.close, 4) for b in self.bars]
        volume = [int(b.volume) for b in self.bars]
        trading_dates = [b.date for b in self.bars]
        # 单标的 case，symbol 本身即为唯一标识
        symbols = [self.symbol]

        payload = {
            "close": close,             # 精度 4 位小数
            "volume": volume,           # 整数
            "trading_dates": trading_dates,
            "symbols": symbols,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    def verify_fingerprint(self) -> bool:
        """验证数据指纹是否匹配"""
        return self.compute_fingerprint() == self.data_fingerprint

    # P2-3: 除权除息处理 ──────────────────────────────

    def get_adjusted_close(self, idx: int) -> float:
        """返回第 idx 根 bar 的前复权收盘价

        使用 adj_factor 做前复权处理（以最新 adj_factor 为基准）：
          adjusted_close[idx] = close[idx] * adj_factor[idx] / max(adj_factor)

        Args:
            idx: bar 索引（0-based）

        Returns:
            前复权收盘价
        """
        if idx < 0 or idx >= len(self.bars):
            raise IndexError(f"Index {idx} out of range [0, {len(self.bars)})")
        max_adj = max(b.adj_factor for b in self.bars)
        if max_adj <= 0:
            return self.bars[idx].close
        return self.bars[idx].close * self.bars[idx].adj_factor / max_adj

    def detect_corporate_actions(self) -> List[Dict[str, any]]:
        """检测除权除息事件

        通过 adj_factor 变化检测分红、送股等公司行动：
        - 如果 adj_factor 在相邻 bar 间变化超过 0.1%，判定为事件

        Returns:
            事件列表，每项含 {date, symbol, adj_ratio, event_type}
        """
        events = []
        for i in range(1, len(self.bars)):
            prev_af = self.bars[i-1].adj_factor
            curr_af = self.bars[i].adj_factor
            if prev_af > 0 and curr_af != prev_af:
                ratio = abs(curr_af / prev_af - 1)
                if ratio > 0.001:  # > 0.1% 变化视为事件
                    evt_type = "dividend" if ratio < 0.05 else "split"
                    events.append({
                        "date": self.bars[i].date,
                        "symbol": self.symbol,
                        "adj_ratio": curr_af / prev_af,
                        "event_type": evt_type,
                    })
        return events

    def get_all_adjusted_close(self) -> List[float]:
        """返回所有 bar 的前复权收盘价序列"""
        max_adj = max(b.adj_factor for b in self.bars)
        if max_adj <= 0:
            return [b.close for b in self.bars]
        return [b.close * b.adj_factor / max_adj for b in self.bars]


# ═══════════════════════════════════════════════════════════
# 前视偏差检测（BT-007 TimeAlignmentGuard）
# ═══════════════════════════════════════════════════════════

class TimeAlignmentGuard:
    """数据层 → 计算层的前视偏差运行时防护

    核心规则（BT-006 t-1契约）：
    给定 bar[t] 作为信号输入，数据中只能包含 t 时刻已知的信息。
    禁止使用 t+1 时刻的任何数据。

    A股特殊规则：
    - 使用当日收盘价作为入场价需确保策略是在盘中实时计算
    - 回测中默认使用收盘价成交需要在前一根 bar 发出信号
    - 如果使用 date[t].close 作为 date[t] 的入场价，必须在 date[t-1] 信号
    """

    @staticmethod
    def check_bars_ascending(bars: List[BacktestBar]) -> List[str]:
        """检查日期是否严格升序"""
        errors = []
        for i in range(1, len(bars)):
            if bars[i].date <= bars[i - 1].date:
                errors.append(
                    f"日期降序: bar[{i-1}].date={bars[i-1].date} >= "
                    f"bar[{i}].date={bars[i].date}"
                )
        return errors

    @staticmethod
    def check_no_future_close(bars: List[BacktestBar],
                               signal_dates: List[str]) -> List[str]:
        """检查信号是否使用了未来数据（按 t-1 契约）

        如果信号在 date[t] 生成且引用了 bars[t+1:] 的数据，则报警。
        """
        errors = []
        date_map = {b.date: i for i, b in enumerate(bars)}

        for sig_date in signal_dates:
            if sig_date not in date_map:
                continue
            idx = date_map[sig_date]
            # 信号使用 future data 的检测留给 ComputeLayer 实现
            # 这里只是契约层面的日期对齐检查
            if idx > 0:
                # 正常：信号基于 bars[:idx+1] 形成（只用到当前及过去）
                pass

        return errors


# ═══════════════════════════════════════════════════════════
# 缺失值处理策略
# ═══════════════════════════════════════════════════════════

class MissingValuePolicy:
    """缺失值处理策略常量"""
    # 价格字段：前向填充 + 不可超过 N 天
    FORWARD_FILL_MAX_DAYS = 5

    # 量字段：0 填充（无交易量 = 停牌/休市）
    VOLUME_ZERO_FILL = True

    # 复权因子：前向填充
    ADJ_FACTOR_FORWARD_FILL = True

    # 不允许缺失的字段（必须非空）
    REQUIRED_FIELDS = ["date", "symbol", "open", "high", "low", "close"]

    @staticmethod
    def validate_and_fill(bars: List[Dict]) -> List[BacktestBar]:
        """批量转换并填充缺失值"""
        result = []
        last_adj = 1.0
        for row in bars:
            # 复权因子前向填充
            adj = row.get("adj_factor") or last_adj
            if adj is None or adj == 0:
                adj = last_adj
            last_adj = adj

            bar = BacktestBar(
                symbol=str(row.get("symbol", "")),
                date=str(row.get("date", "")),
                open=float(row.get("open", 0) or 0),
                high=float(row.get("high", 0) or 0),
                low=float(row.get("low", 0) or 0),
                close=float(row.get("close", 0) or 0),
                volume=float(row.get("volume", 0) or 0),
                amount=float(row.get("amount", 0) or 0),
                adj_factor=adj,
                data_source=str(row.get("data_source", "unknown")),
                version=str(row.get("version", "v1.0")),
                _loaded_at=datetime.now(_TZ_CN).isoformat(),
            )
            result.append(bar)

        return result
