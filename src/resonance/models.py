"""
Phase 0 核心数据结构定义

定义右侧交易共振系统所需的所有 TypedDict / dataclass / Enum 类型。
所有模块通过 `from src.resonance.models import ...` 引用常量。

使用约定：
  - 信号字段使用 TypedDict（JSON 序列化友好）
  - 内部状态使用 dataclass（运行时高效）
  - 枚举引用 constants 模块常量而非重复定义字面值

Author: moheng
Created: 2026-05-29T09:41:00+08:00
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import numpy as np
from numpy.typing import NDArray

from src.resonance.constants import (
    FULL_PASS_CAP,
    RSM_STATE_ACTIVE,
    RSM_STATE_DECAY,
    RSM_STATE_NONE,
    RSM_STATE_WARN,
)


# ══════════════════════════════════════════════════════════
# RSMState — 共振状态机枚举
# ══════════════════════════════════════════════════════════


class RSMState(str, enum.Enum):
    """共振状态机状态枚举。

    映射 constants.RSM_STATE_* 字符串常量到枚举成员，
    确保类型安全且与 JSON 序列化兼容（str 基类天然支持）。

    状态流转：
      NONE ──(强度达标)──→ WARN ──(持续确认)──→ ACTIVE ──(趋弱)──→ DECAY ──(超时)──→ NONE
         ↑                                                                        │
         └────────────────────────(WARN 超时)─────────────────────────────────────┘

    各状态说明：
      NONE   : 无共振，初始/恢复状态
      WARN   : 单日强度达标但尚未确认趋势
      ACTIVE : 共振确认，持续活跃
      DECAY  : 共振趋弱但尚未完全消失
    """

    NONE = RSM_STATE_NONE
    WARN = RSM_STATE_WARN
    ACTIVE = RSM_STATE_ACTIVE
    DECAY = RSM_STATE_DECAY

    def is_active(self) -> bool:
        """是否为活跃共振状态（WARN/ACTIVE/DECAY）。"""
        return self in (RSMState.WARN, RSMState.ACTIVE, RSMState.DECAY)

    def is_confirmed(self) -> bool:
        """是否为确认共振状态（ACTIVE/DECAY）。"""
        return self in (RSMState.ACTIVE, RSMState.DECAY)

    def can_trade(self) -> bool:
        """是否允许基于此状态进行交易操作。"""
        return self in (RSMState.NONE, RSMState.ACTIVE, RSMState.DECAY)


# ══════════════════════════════════════════════════════════
# ModuleStatus — 模块执行状态枚举
# ══════════════════════════════════════════════════════════


class ModuleStatus(str, enum.Enum):
    """模块执行状态。

    各模块（DCM / ZNM / GKV / CPE / SG / RSM）统一返回枚举。
    """

    PASS = "PASS"
    """正常通过。模块逻辑完整执行并产出有效结果。"""

    FAILED = "FAILED"
    """执行失败。模块遇到不可恢复错误。"""

    SKIPPED = "SKIPPED"
    """跳过执行。前置条件不满足（如数据不足）或配置不要求。"""

    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    """条件放行。CPE 特有状态：连续共振达标但尚未 FULL_PASS。"""


# ══════════════════════════════════════════════════════════
# ModuleResult — 模块标准返回格式
# ══════════════════════════════════════════════════════════


class ModuleResult(TypedDict, total=False):
    """模块标准返回格式 TypedDict。

    所有模块（DCM / ZNM / GKV / CPE / SG / RSM）的输出统一
    遵循此格式。只有 PASS 状态的模块需要有 data；FAILED / SKIPPED
    可仅提供 status 和 reason。

    Fields:
      status      : 模块执行状态（必填）
      data        : 模块产出数据（PASS 时必须存在）
      confidence  : 结果置信度 [0, 1]，由模块内部评估（可选）
      errors      : 执行过程中记录的错误列表（可选）
      warnings    : 执行过程中记录的警告列表（可选）
      metadata    : 模块特有的附加元信息（可选）
    """

    status: ModuleStatus
    data: Optional[Dict[str, Any]]
    confidence: Optional[float]
    errors: Optional[List[str]]
    warnings: Optional[List[str]]
    metadata: Optional[Dict[str, Any]]


# ══════════════════════════════════════════════════════════
# ResonanceSignal — 共振信号输出格式
# ══════════════════════════════════════════════════════════


class ResonanceSignal(TypedDict, total=False):
    """共振信号输出格式。

    由 SG（信号生成器）产出，写入 signals/resonance/ 目录。
    供上层交易系统或决策模块消费。

    Fields:
      signal_type   : 信号类型枚举值，如 "BUY" / "SELL" / "HOLD"
      strength      : 共振强度 [0, 1]，由 RSM.compute_strength() 计算
      position_cap  : 该信号允许的仓位上限 [0, 1]
      reason        : 信号生成理由（短文本，50 字以内）
      timestamp     : 信号生成时间（ISO8601 +08:00）
      state         : 信号生成时的共振状态
      source_module : 信号生成的模块名称（如 "SG"）
      confidence    : 信号置信度 [0, 1]
    """

    signal_type: str
    """信号类型: 'BUY' | 'SELL' | 'HOLD' | 'CONDITIONAL_BUY' | 'CONDITIONAL_SELL'"""

    strength: float
    """共振强度 [0, 1]。低于 RESONANCE_MIN_STRENGTH 的信号不会被 GKV 放行。"""

    position_cap: float
    """仓位上限 [0, 1]。默认 FULL_PASS_CAP (1.0)；
    CONDITIONAL_PASS 时为 CONDITIONAL_PASS_POSITION_CAP (0.5)。"""

    reason: str
    """信号生成理由，简洁的专业判断文本（50 字以内）。"""

    timestamp: str
    """信号生成时间戳，格式 ISO8601 +08:00（含时区）。"""

    state: RSMState
    """信号生成时的共振状态。"""

    source_module: str
    """产生此信号的模块标识符，如 'SG', 'CPE', 'MANUAL'。"""

    confidence: float
    """信号置信度 [0, 1]。由 SG 综合 DCM/ZNM/GKV/CPE 多模块输出评估。"""

    symbol: str
    """标的代码，如 '601857' 或 '601857.SH'。"""

    suggested_price: float
    """建议入场/出场价格。"""


# ══════════════════════════════════════════════════════════
# LookbackData — 滚动窗口存储格式
# ══════════════════════════════════════════════════════════


@dataclass
class LookbackData:
    """滚动窗口历史数据持久化格式。

    由 LookbackBuffer（LB）维护，用于 DCM 波动率计算和
    ZNM z-score 归一化的历史数据来源。

    持久化路径：data/lookback/（由 LB_PERSIST_PATH 常量定义）。
    序列化友好：所有字段均为 JSON 可序列化类型。

    Fields:
      history         : [(date, value), ...] 有序列表，最新在后
      resonance_state : 最近一次的共振状态
      window_stats    : 窗口统计量（均值、标准差等）
      last_update     : 最近更新日期 (YYYYMMDD 字符串)
      ticker          : 标的代码
    """

    history: List[Tuple[str, float]] = field(default_factory=list)
    """history[(date, value), ...] 历史数据对列表。
    - date: YYYYMMDD 格式的交易日字符串
    - value: 该日信号强度或其他数值
    - 最早在前，最新在后（按时间升序排列）"""

    resonance_state: RSMState = RSMState.NONE
    """最近一次的共振状态。从状态机同步更新。"""

    window_stats: Dict[str, float] = field(default_factory=dict)
    """窗口统计量字典。
    典型包含字段：
      - 'mean'      : 窗口内历史数值均值
      - 'std'       : 窗口内历史数值标准差
      - 'min'       : 窗口内最小值
      - 'max'       : 窗口内最大值
      - 'zscore'    : 最新值的 z-score（使用当前窗口统计）
      - 'latest_qq' : 最新值的滚动窗口分位数 [0, 1]
    """

    last_update: str = ""
    """最近更新日期。YYYYMMDD 格式字符串。
    用于判断数据时效性及是否触发新数据到达事件。"""

    ticker: str = ""
    """标的代码。用于区分不同标的的 LookbackData。
    与 trading/ 层使用的 ticker 命名一致。"""


# ══════════════════════════════════════════════════════════
# WindowStats — 窗口统计量计算单元（运行时）
# ══════════════════════════════════════════════════════════


@dataclass
class WindowStats:
    """窗口统计量运行时计算单元。

    由 DCM 和 ZNM 在每次 LookbackBuffer 更新时同步更新，
    使用 LOOKBACK_WINDOW 作为滚动窗口大小。

    区别于 window_stats 字典的 JSON 友好表示，
    本 dataclass 用于模块间传递精确的计算结果。
    """

    mean: float = 0.0
    """窗口内历史数值均值。"""

    std: float = 0.0
    """窗口内历史数值标准差。"""

    min_val: float = 0.0
    """窗口内最小值。"""

    max_val: float = 0.0
    """窗口内最大值。"""

    zscore: float = 0.0
    """最新值的 z-score = (最新值 - mean) / (std + eps)。"""

    latest_qq: float = 0.0
    """最新值的滚动窗口分位数 [0, 1]。
    qq = (最新值排序位置 - 1) / (窗口大小 - 1)。"""


# ══════════════════════════════════════════════════════════
# SignalHistoryEntry — 信号历史记录
# ══════════════════════════════════════════════════════════


@dataclass
class SignalHistoryEntry:
    """单条信号历史记录。

    由 SG 在每次产生信号后追加至信号历史列表，
    用于回溯分析、回测校准、CPE 连续计数等。
    """

    date: str
    """信号生成日期，YYYYMMDD 格式。"""

    signal_type: str
    """信号类型: 'BUY' | 'SELL' | 'HOLD' | 'CONDITIONAL_BUY' | ..."""

    strength: float
    """信号对应日的共振强度 [0, 1]。"""

    reason: str
    """信号生成理由（短文本）。"""

    state: RSMState
    """信号生成时的共振状态。"""


# ══════════════════════════════════════════════════════════
# PipelineConfig — pipeline.run() 配置类型
# ══════════════════════════════════════════════════════════


class PipelineConfig(TypedDict, total=False):
    """pipeline.run() 配置类型定义。

    控制共振主流水线的行为参数。所有字段均有合理默认值，
    partial=True 时仅部分必须提供。

    Fields:
      tickers         : 参与共振检测的标的代码列表
      start_date      : 回测/运行起始日期 (YYYYMMDD)
      end_date        : 回测/运行结束日期 (YYYYMMDD)
      data_bridge     : DataBridge 配置或实例标识符
      lookback_window : 滚动窗口大小（覆盖 constants.LOOKBACK_WINDOW）
      output_dir      : 信号输出目录（覆盖 constants.SIGNAL_OUTPUT_DIR）
      dry_run         : 干运行模式，不写入信号文件
      verbose         : 详细日志开关
    """

    tickers: List[str]
    """标的代码列表，如 ['601857.SH', '600519.SH']。
    空列表表示使用默认标的集。"""

    start_date: str
    """运行起始日期。YYYYMMDD 格式。"""

    end_date: str
    """运行结束日期。YYYYMMDD 格式。"""

    data_bridge: Optional[str]
    """DataBridge 配置名称或实例标识符。
    可选值如 'default', 'tushare_pro', 'mock'。
    None 表示使用默认数据桥。"""

    lookback_window: int
    """滚动窗口大小覆盖值。
    不提供时使用 constants.LOOKBACK_WINDOW (20)。"""

    output_dir: str
    """信号输出目录覆盖值。
    不提供时使用 constants.SIGNAL_OUTPUT_DIR ('signals/resonance')。"""

    dry_run: bool
    """干运行模式。为 True 时不写入信号文件，
    仅打印处理摘要。"""

    verbose: bool
    """详细日志模式。为 True 时输出每个模块的详细执行日志。"""

    partial: bool
    """部分运行模式。为 True 时允许前置数据不完整的情况下
    运行部分子流水线（如仅运行 DCM+ZNM 不运行 GKV+RSM）。"""


# ══════════════════════════════════════════════════════════
# 模块间数据传递类型
# ══════════════════════════════════════════════════════════


@dataclass
class DCMResult:
    """DCM 波动率代理模块输出。

    DCM 计算标的的历史波动率代理（基于 LOOKBACK_WINDOW 滚动窗口），
    输出给 ZNM 和 RSM 使用。
    """

    volatility: float
    """最新窗口的年化波动率值。"""

    volatility_history: NDArray[np.float64]
    """波动率历史序列（数组），长度为 LOOKBACK_WINDOW。"""

    status: ModuleStatus
    """DCM 模块执行状态。"""


@dataclass
class ZNMResult:
    """ZNM z-score 归一化模块输出。

    ZNM 对 DCM 输出的波动率序列做 z-score 归一化，
    输出极值检测结果给 GKV 和 RSM。
    """

    zscore: float
    """最新波动率的 z-score 值。"""

    is_extreme: bool
    """是否超出极值阈值（|zscore| > QUANTILE_THRESHOLD）。"""

    normalized_values: NDArray[np.float64]
    """归一化后的完整值序列。"""

    status: ModuleStatus
    """ZNM 模块执行状态。"""


@dataclass
class GKVResult:
    """GKV 门控验证模块输出。

    综合 RSM 状态 + DSV 一致性 + 流动性评分 → 决定是否放行交易信号。

    三闸门逻辑（全部通过才放行）：
      1. RSM 状态 >= WARN（共振至少达到预警级别）
      2. DSV 一致性评分 > 0.7（双源校验强一致）
      3. 流动性评分 > LIQUIDITY_MIN_THRESHOLD（流动性充足）

    修复追溯:
      Phase 0.3 task_10 — 重构为三闸门核验，替换原 strength_zscore 逻辑。
    """

    gated: bool
    """闸门是否封锁信号。True=信号被阻挡（需至少一个闸门条件未满足）。"""

    passed: bool
    """综合核验是否通过。True=三闸门全部打开，信号可放行。"""

    reason: str
    """门控决策理由（50 字以内简洁文本）。"""

    status: ModuleStatus
    """GKV 模块执行状态：PASS | SKIPPED | FAILED。"""

    gate_open: bool
    """门控是否打开（别名，与 passed 同义）。True=信号可放行。
    保留旧字段名以兼容旧版消费者。"""

    rsm_state_ok: bool
    """闸门1: RSM 状态 >= WARN。"""

    dsv_consistency_ok: bool
    """闸门2: DSV 一致性评分 > 0.7。"""

    liquidity_ok: bool
    """闸门3: 流动性评分 > LIQUIDITY_MIN_THRESHOLD。"""

    rsm_state_value: str
    """闸门1 明细：输入 RSM 状态值（枚举字符串）。"""

    dsv_score: float
    """闸门2 明细：输入 DSV 一致性评分 [0, 1]。"""

    liquidity_score: float
    """闸门3 明细：输入流动性评分 [0, 1]。"""

    signal_strength: float
    """信号共振强度 [0, 1]（透传自 RSM，供 SG 参考）。"""


@dataclass
class CPEResult:
    """CPE 组合评估模块输出。

    CPE 实现两个核心功能：
      1. 综合评分：融合 RSM强度 + DSV一致性 + 流动性评分 → 加权总分
      2. 条件放行判断：连续达标天数 → CONDITIONAL_PASS / FULL_PASS 决策

    综合评分权重（默认）:
      - RSM 强度: 0.5 (共振强度是信号的核心指标)
      - DSV 一致性: 0.3 (双源验证提供额外置信度)
      - LQM 流动性: 0.2 (流动性是交易执行的必要条件)

    状态处理:
      - PASS:  正常完成评估，score > 0
      - FAILED: 输入无效或计算异常，score = 0.0
      - SKIPPED: 跳过后继续执行
    """

    # ── 综合评分字段 ──

    score: float = 0.0
    """加权综合评分 [0, 1]，融合 RSM 强度 + DSV 一致性 + 流动性评分。"""

    rsm_weight: float = 0.5
    """RSM 强度权重（默认 0.5）。"""

    dsv_weight: float = 0.3
    """DSV 一致性权重（默认 0.3）。"""

    liq_weight: float = 0.2
    """流动性评分权重（默认 0.2）。"""

    # ── 条件放行字段 ──

    continuous_days: int = 0
    """连续共振强度达标天数。"""

    conditional_pass: bool = False
    """是否满足 CONDITIONAL_PASS 条件（continuous_days >= CPE_CONTINUOUS_DAYS）。"""

    days_remaining: int = 5
    """距离 CONDITIONAL_PASS 还差的天数（负数表示已达标数）。"""

    status: ModuleStatus = ModuleStatus.PASS
    """CPE 模块执行状态。"""

    position_cap: float = 1.0
    """仓位上限。CONDITIONAL_PASS 时为 0.5，否则 1.0。"""

    reason: str = ""
    """评估理由说明。"""

    def __post_init__(self) -> None:
        """初始化后校验：确保分值在 [0, 1] 范围内。"""
        self.score = max(0.0, min(1.0, self.score))
        self.continuous_days = max(0, self.continuous_days)
        self.days_remaining = max(-self.continuous_days, self.days_remaining)
        if self.conditional_pass:
            self.position_cap = 0.5


@dataclass
class LQMResult:
    """LQM 流动性评价模块输出。

    LQM 基于 OHLCV 数据计算标的的流动性指标，
    输出振幅、成交量比和综合流动性评分给 GKV 和 RSM。
    """

    amplitude: float
    """当日振幅 = (high - low) / prev_close * 100（百分比）。
    用于衡量价格日内波动范围。
    """

    volume_ratio: float
    """成交量比 = 当日成交量 / 滚动窗口平均成交量。
    > 1.0 表示当日成交量高于近期均值。
    """

    turnover_rate: float
    """换手率（百分比）。当无法获取流通股本数据时置为 -1.0。
    turnover 是流动性最直接的指标之一。
    """

    liquidity_score: float
    """综合流动性评分 [0, 1]。
    由振幅、成交量比等多维度加权计算。
    越高表示流动性越好。
    """

    status: ModuleStatus
    """LQM 模块执行状态。"""


@dataclass
class RSMPipelineState:
    """RSM 共振状态机运行时状态。

    流水线执行过程中由 RSM 模块维护的内部状态。
    每次 tick（交易日）更新一次。
    """

    current_state: RSMState
    """当前共振状态。"""

    warn_consecutive_strength: int
    """强度达标连续天数。进入 WARN 后，强度达标日依次递增；强度不达标的日重置为 0。
    用于 WARN → ACTIVE 的升级判断 (≥ CONSECUTIVE_FOR_ACTIVE)。"""

    warn_total_days: int
    """进入 WARN 后的总历日天数（含强度不达标日）。
    用于 WARN 超期强制归零 NONE (≥ WARN_EXPIRY_DAYS)。"""

    consecutive_decay_days: int
    """连续处于 DECAY 状态的天数（用于超时判断）。"""

    run_count: int
    """RSM 运行总次数（用于统计和调试）。"""

    last_signal_date: str
    """最近一次产生信号的日期（YYYYMMDD）。"""

    history: List[SignalHistoryEntry] = field(default_factory=list)
    """信号历史记录列表。"""


@dataclass
class SGResult:
    """SG 信号生成模块输出。

    SG 模块依据 CPE 综合评分 + GKV 门控状态 → 生成交易信号。

    信号类型方向说明:
      BUY  : GKV 闸门开放且 CPE 评分 > 0.4，可执行买入。
      SELL : 预留。Phase 0.3 中由 GKV 闸门封锁 + 前次 BUY 信号触发（由上层处理）。
      HOLD : 闸门封锁或评分不足，不执行交易。

    信号强度映射:
      STRONG : CPE 评分 > 0.8
      MEDIUM : CPE 评分 > 0.6
      WEAK   : CPE 评分 > 0.4
      NONE   : CPE 评分 ≤ 0.4 或闸门封锁

    状态传播:
      CPE/RSM FAILED → SG FAILED
      CPE SKIPPED   → SG SKIPPED
      正常执行       → SG PASS
    """

    signal_type: str
    """信号类型。'BUY' | 'SELL' | 'HOLD'。"""

    signal_strength: str
    """信号强度级别。'STRONG' | 'MEDIUM' | 'WEAK' | 'NONE'。"""

    score: float
    """从 CPE 透传的综合评分 [0, 1]，封顶至 4 位小数。"""

    status: ModuleStatus
    """SG 模块执行状态。PASS | FAILED | SKIPPED。"""

    ticker: str
    """标的代码，如 '601857.SH'。"""

    reason: str
    """信号生成理由，简洁文本（50 字以内）。"""

    def __post_init__(self) -> None:
        """初始化后校验：确保 score 在 [0, 1] 范围内。"""
        self.score = max(0.0, min(1.0, self.score))
