"""
全局常量定义模块

定义 Phase 0 右侧交易共振系统所需的所有全局数学常量和路径常量。
所有模块通过 `from src.resonance.constants import ...` 引用。

评审修复追溯:
  D1 — RESONANCE_MIN_STRENGTH 阈值参数化（GKV/CPE 同时引用）

Author: moheng
Created: 2026-05-29T09:30:00+08:00
"""

# ──────────────────────────────────────────────
# 共振强度与滚动窗口
# ──────────────────────────────────────────────

RESONANCE_MIN_STRENGTH: float = 0.6
"""共振强度最低阈值。低于此值的共振不被 GKV 门控放行，CPE 不计入连续计数。
评审修复 D1：阈值参数化，GKV/CPE 同时引用。"""

LOOKBACK_WINDOW: int = 20
"""滚动窗口大小（交易日）。
DCM 波动率计算、ZNM z-score 归一化均以此窗口计算历史统计量。"""

# ──────────────────────────────────────────────
# 信号有效性与仓位限制
# ──────────────────────────────────────────────

SIGNAL_VALIDITY_HOURS: float = 0.5
"""CONDITIONAL_PASS 信号在 T+1 开盘后的有效时长。
有效窗口为 30 分钟，以浮点小数小时表示（0.5h）。

修复 C1：值 30.0 → 0.5，修正语义与注释矛盾。"""

CONDITIONAL_PASS_POSITION_CAP: float = 0.5
"""CONDITIONAL_PASS 状态下的仓位上限（≤50%）。
当 CPE 给出条件放行信号时，持仓比例不得超过此值。

修复 I1：命名对齐设计方案 CONDITIONAL_PASS_POSITION_CAP。"""

FULL_PASS_CAP: float = 1.0
"""FULL_PASS / 正常状态下的仓位上限（100%）。"""

LIQUIDITY_MIN_THRESHOLD: float = 0.5
"""GKV 门控核验的流动性评分最低阈值。

流动性评分 < 此值时 GKV 闸门封锁，不允许放行交易信号。

修复追溯:
  Phase 0.3 task_10 — 新增常量供 GKV 门控核验使用。
"""

# ──────────────────────────────────────────────
# CPE 条件放行
# ──────────────────────────────────────────────

CPE_CONTINUOUS_DAYS: int = 5
"""CPE 条件放行的连续共振日数要求。
连续 5 日 RESONANCE_MIN_STRENGTH > 0.6 + DSV passed → CONDITIONAL_PASS。"""

# ──────────────────────────────────────────────
# RSM 共振状态机
# ──────────────────────────────────────────────

RSM_STATE_NONE: str = "NONE"
"""无共振状态。初始状态 / 共振结束后恢复。"""

RSM_STATE_WARN: str = "WARN"
"""预警状态。单日强度达标但尚未确认趋势。"""

RSM_STATE_ACTIVE: str = "ACTIVE"
"""活跃共振状态。共振确认持续中。"""

RSM_STATE_DECAY: str = "DECAY"
"""衰减状态。共振趋弱但尚未完全消失。"""

QUANTILE_THRESHOLD: float = 1.5
"""z-score 极值判断阈值。当 |z-score| > N 时判定为极端值。
由 RSM.compute_strength() 引用，用于剔除噪声信号。

修复 C2：补充设计方案 §1.1/§7.1 定义的极值阈值。"""

DECAY_EXPIRY_DAYS: int = 10
"""DECAY 状态的最大持续天数。
超时后自动回退至 NONE 状态。"""

WARN_EXPIRY_DAYS: int = 5
"""WARN 状态的最大持续天数。
超时后自动回退至 NONE 状态。"""

# ──────────────────────────────────────────────
# DCM 波动率代理
# ──────────────────────────────────────────────

ANNUALIZATION_FACTOR: int = 252
"""年化因子。A 股年化交易日数，用于 DCM 年化波动率计算。"""

MAX_FILL_FORWARD: int = 3
"""前值填充最大日数。
DCM 计算历史波动率时，缺失值最多向前填充 3 日。"""

# ──────────────────────────────────────────────
# ZNM z-score 归一化
# ──────────────────────────────────────────────

MIN_HISTORY_LENGTH: int = 2
"""z-score 计算所需的最小历史数据点数。
低于此值 → ZNM 返回 FAILED。"""

# ──────────────────────────────────────────────
# SG 信号生成
# ──────────────────────────────────────────────

SIGNAL_WRITE_RETRIES: int = 3
"""信号文件写入验证的最大重试次数。
写入后 read 验证，失败重试，3 次均失败则标记 FAILED。"""

# ──────────────────────────────────────────────
# SCL 调度层
# ──────────────────────────────────────────────

POLLING_INTERVAL_MINUTES: int = 30
"""PollingAdapter 轮询间隔（分钟）。
每 30 分钟检查 DataBridge 是否有新数据。"""

POLLING_MAX_RETRIES: int = 1
"""PollingAdapter 每次运行的最大重试次数。
超过后静默跳过。"""

# ──────────────────────────────────────────────
# 数据桥与数据质量
# ──────────────────────────────────────────────

MIN_REQUIRED_HISTORY_DAYS: int = 40
"""DataBridge 需提供的最小历史数据天数。
用于支持 LOOKBACK_WINDOW(20日) + 前值填充缓冲 + 统计稳定性。"""

# ──────────────────────────────────────────────
# 路径常量（文件系统）
# ──────────────────────────────────────────────

# 注意：以下路径以项目根相对路径定义。
# 实际运行时建议通过环境变量或配置管理器（Phase 1）覆盖。
# 默认解析：os.path.join(PROJECT_ROOT, <相对路径>)

SIGNAL_OUTPUT_DIR: str = "signals/resonance"
"""共振信号 JSON 输出目录（相对项目根）。

修复 W1：对齐设计文档 signals/resonance/。"""

SIGNAL_DONE_DIR: str = "signals/tasks"
"""done 文件输出目录（相对项目根）。

修复 W2：对齐设计文档 signals/tasks/。"""

LB_PERSIST_PATH: str = "data/lookback"
"""LookbackBuffer 持久化存储路径（相对项目根）。

修复 W3：命名对齐设计文档 LB_PERSIST_PATH。"""
