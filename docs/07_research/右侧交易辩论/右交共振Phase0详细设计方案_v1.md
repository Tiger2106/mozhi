# 右侧交易情绪-流动性共振 Phase 0 详细设计方案

**作者**: 墨衡 🖋️
**创建时间**: 2026-05-29T09:15:00+08:00
**版本**: v1.0
**依据**: 框架设计 v2.0（已签署）· 墨萱评审 v1 · 玄知评审 v1
**目标**: 从框架设计→可编码详细规格
**预估计时**: 55 分钟

---

## 目录

1. 全局常量与配置定义
2. 数据结构精确规格
   - 2.1 Lookback Buffer 存储格式
   - 2.2 RSM 状态机状态枚举
   - 2.3 共振信号输出格式（Signal Protocol v1）
   - 2.4 模块返回值契约（通用基类）
3. DataBridge 数据桥适配接口
4. DCM 模块 — 波动率代理
5. LQM 模块 — 换手率计算
6. ZNM 模块 — z-score 归一化
7. RSM 模块 — 共振状态机
8. DSV 模块 — 双源校验
9. GKV 模块 — 门控/否决
10. CPE 模块 — 条件放行评估
11. SG 模块 — 信号生成
12. SCL 调度层适配器
13. pipeline.py 编排逻辑
14. Module API Contract 汇总
15. 错误异常传播规则

---

## 1. 全局常量与配置定义

### 1.1 数学常量

```python
# ─────────────────────────────────────────────
# 全局常量 — 所有模块引用同一来源，禁止硬编码
# ─────────────────────────────────────────────

# 共振检测
RESONANCE_MIN_STRENGTH: float = 0.6
# 说明: 同时用于 GKV 否决基线 和 CPE 条件放行触发阈值
# 如果未来调整，两个模块行为自动同步

# 滚动窗口
LOOKBACK_WINDOW: int = 20
# 说明: z-score 计算的滚动窗口期

# z-score 极值阈值
QUANTILE_THRESHOLD: float = 1.5
# 说明: |z-score| > 1.5 视为极端尾部

# 状态机超时阈值
WARN_EXPIRY_DAYS: int = 5
DECAY_EXPIRY_DAYS: int = 10

# 年化因子
ANNUALIZATION_FACTOR: int = 252

# 仓位约束
CONDITIONAL_PASS_POSITION_CAP: float = 0.5  # ≤50%

# 调度层
SCL_MAX_RETRIES: int = 1
SCL_DEFAULT_INTERVAL_MINUTES: int = 30
```

### 1.2 路径/文件常量

```python
# 信号输出目录
SIGNAL_OUTPUT_DIR: str = "signals/resonance/"
SIGNAL_DONE_DIR: str = "signals/tasks/"

# LB 持久化路径（JSON 文件）
LB_PERSIST_PATH: str = "data/lookback_buffer_v1.json"
```

---

## 2. 数据结构精确规格

### 2.1 Lookback Buffer 存储格式

```python
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass, field
from datetime import date

@dataclass
class LB_DailyRecord:
    """LB 单日记录（滚动 20 日窗口）"""
    date: str                       # "YYYY-MM-DD"
    hv: Optional[float]             # 历史波动率（年化）
    turnover: Optional[float]       # 换手率
    vol_zscore: Optional[float]     # 波动率 z-score
    turn_zscore: Optional[float]    # 换手率 z-score
    resonance_state: Optional[str]  # RSM 状态（NONE/WARN/ACTIVE/DECAY）
    resonance_strength: float = 0.0 # 共振强度 [0.0, 1.0]
    direction: Optional[str]        # POSITIVE / NEGATIVE
    state_duration: int = 0         # 当前状态持续天数

@dataclass
class LookbackBuffer:
    """LB 整体结构（内存 + JSON 持久化双通道）"""
    window_size: int = LOOKBACK_WINDOW
    records: List[LB_DailyRecord] = field(default_factory=list)

    # ─── 元数据 ───
    last_update: Optional[str] = None  # 上次更新日期
    version: str = "v1.0"              # 结构版本（向后兼容用）

    # ─── 方法 ───
    def latest(self) -> Optional[LB_DailyRecord]:
        """返回最新一条记录"""
        return self.records[-1] if self.records else None

    def previous_state(self) -> Dict[str, Any]:
        """返回前次 RSM 状态（供状态机读取）"""
        if not self.records:
            return {"state": "NONE", "duration": 0, "last_update": None}
        last = self.records[-1]
        return {
            "state": last.resonance_state or "NONE",
            "duration": last.state_duration,
            "last_update": last.date
        }

    def zscore_series(self) -> tuple:
        """返回 vol_zscore + turn_zscore 时间序列（长度 ≤ window_size）"""
        vols = [r.vol_zscore for r in self.records if r.vol_zscore is not None]
        turns = [r.turn_zscore for r in self.records if r.turn_zscore is not None]
        return vols, turns

    def append(self, record: LB_DailyRecord) -> None:
        """追加一条记录，自动裁剪至 window_size"""
        self.records.append(record)
        if len(self.records) > self.window_size:
            self.records = self.records[-self.window_size:]
        self.last_update = record.date

    def serialize(self) -> Dict:
        """序列化为 JSON 格式"""
        # 用于持久化到文件
        return {
            "version": self.version,
            "window_size": self.window_size,
            "last_update": self.last_update,
            "records": [
                {
                    "date": r.date,
                    "hv": r.hv,
                    "turnover": r.turnover,
                    "vol_zscore": r.vol_zscore,
                    "turn_zscore": r.turn_zscore,
                    "resonance_state": r.resonance_state,
                    "resonance_strength": r.resonance_strength,
                    "direction": r.direction,
                    "state_duration": r.state_duration
                }
                for r in self.records
            ]
        }

    @classmethod
    def deserialize(cls, data: Dict) -> "LookbackBuffer":
        """从 JSON 还原"""
        buf = cls(window_size=data.get("window_size", LOOKBACK_WINDOW))
        buf.last_update = data.get("last_update")
        buf.version = data.get("version", "v1.0")
        for rec in data.get("records", []):
            buf.records.append(LB_DailyRecord(**rec))
        return buf
```

### 2.2 RSM 状态机状态枚举

```python
from enum import Enum

class ResonanceState(str, Enum):
    """共振状态机 — 状态集"""
    NONE    = "NONE"     # 无共振
    WARN    = "WARN"     # 预警（strength > 0.3 但未达共识阈值）
    ACTIVE  = "ACTIVE"   # 共振活跃（strength ≥ RESONANCE_MIN_STRENGTH）
    DECAY   = "DECAY"    # 共振衰减（强度下降中）

class SignalDirection(str, Enum):
    POSITIVE = "POSITIVE"  # volatility/turnover 同步放大
    NEGATIVE = "NEGATIVE"  # volatility/turnover 同步低值
```

**状态转换规则矩阵**：

| 当前状态 | 输入强度 | 下一状态 | 持续时间变化 | 条件 |
|:--------:|:--------:|:---------:|:------------:|:----|
| NONE | ≤0.3 | NONE | 0→0 | 静默 |
| NONE | >0.3 | WARN | 0→1 | 首次预警触发 |
| WARN | >0.6 且 duration≥1 | ACTIVE | →1 | 连续2日满足→共振激活 |
| WARN | >0.3 | WARN | duration+1 | 低强度等待 |
| WARN | ≤0.3 且 duration≥1 | NONE | 重置 | 强度回落 |
| WARN | (duration≥5) 且 strength<0.3 | NONE | 重置 | **超时过期** |
| ACTIVE | ≥0.6 | ACTIVE | duration+1 | 共振维持 |
| ACTIVE | [0.3, 0.6) | ACTIVE | duration+1 | 共振维持（降级强度） |
| ACTIVE | <0.3 | DECAY | 0→1 | 强度跌破→进入衰减 |
| DECAY | ≥0.3 | WARN | 0→1 | 强度回升→回预警 |
| DECAY | =0.0 | NONE | 重置 | 完全恢复 |
| DECAY | (0.0, 0.3) | DECAY | duration+1 | 衰减中 |
| DECAY | (duration≥10) 且 strength=0.0 | NONE | 重置 | **超时过期** |

### 2.3 共振信号输出格式（Signal Protocol v1）

```python
@dataclass
class ResonanceSignal:
    """Signal Protocol v1 — 共振系统输出"""
    # ─── 信号元数据 ───
    signal_id: str                          # UUID 格式
    timestamp: str                          # ISO8601 +08:00
    date: str                               # "YYYY-MM-DD"
    version: str = "resonance.v1"           # 协议版本

    # ─── 共振判定 ───
    resonance_detected: bool                # 是否检测到共振
    state: str                              # NONE/WARN/ACTIVE/DECAY
    strength: float                         # [0.0, 1.0]
    direction: str                          # POSITIVE/NEGATIVE
    duration_days: int                      # 当前状态持续天数

    # ─── 双源校验 ───
    dual_source_passed: bool                # 双源校验通过?
    dual_source_partial: bool               # 部分通过?
    dual_source_score: float                # 校验分值

    # ─── 门控结果 ───
    gkv_passed: bool                        # 否决制通过?
    gkv_reason: Optional[str]               # 否决理由

    # ─── 条件放行 ───
    cpe_verdict: str                        # FULL_PASS / CONDITIONAL_PASS
    position_cap: float                     # 仓位上限 [0, 1]

    # ─── 诊断信息（供调试/日志） ───
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    # 包含: vol_zscore, turn_zscore, hv, turnover, \
    #       vol_corr, turn_corr, \
    #       continuous_strong_days (CPE 连续5日计数)

# JSON 输出示例:
#
# {
#   "signal_id": "resonance_20260529_001",
#   "timestamp": "2026-05-29T09:30:00+08:00",
#   "date": "2026-05-29",
#   "version": "resonance.v1",
#   "resonance_detected": true,
#   "state": "ACTIVE",
#   "strength": 0.82,
#   "direction": "POSITIVE",
#   "duration_days": 3,
#   "dual_source_passed": true,
#   "dual_source_partial": false,
#   "dual_source_score": 0.87,
#   "gkv_passed": true,
#   "gkv_reason": null,
#   "cpe_verdict": "CONDITIONAL_PASS",
#   "position_cap": 0.5,
#   "diagnostics": {
#     "vol_zscore": 2.1,
#     "turn_zscore": 1.8,
#     "hv": 0.28,
#     "turnover": 0.035,
#     "vol_corr": 0.85,
#     "turn_corr": 0.72,
#     "continuous_strong_days": 6
#   }
# }
```

### 2.4 模块返回值契约（通用基类）

```python
from typing import Optional, Dict, Any

@dataclass
class ModuleResult:
    """模块返回值基类 — 所有模块的标准包裹"""
    status: Literal["SUCCESS", "SKIPPED", "FAILED"]
    # SUCCESS: 正常完成并产生有效输出
    # SKIPPED: 因前提不满足而跳过（如数据缺失）
    # FAILED:  计算异常，无法产生输出

    error: Optional[str] = None
    # status=FAILED 时必填
    # SUCCESS/SKIPPED 为 None

    data: Optional[Dict[str, Any]] = None
    # 模块特有输出，各模块定义自己的 data schema
    # status=FAILED 时不应有 data
```

---

## 3. DataBridge 数据桥适配接口

### 3.1 函数签名

```python
from typing import Optional, List, Dict, Any
from datetime import date

class DataBridge:
    """
    统一数据入口 — 职责分离：
    - 信号通道: push_for_today() — 推送当日新数据
    - 查询通道: get_history() / get_latest_date() — 历史回放
    两个通道独立，不共享内部状态
    """

    @staticmethod
    def get_latest_date() -> Optional[str]:
        """返回 DataBridge 最新可用数据的日期
        返回: "YYYY-MM-DD" 或 None（数据不可用）
        异常: 不抛出异常（内部捕获网络错误，返回 None）
        """
        ...

    @staticmethod
    def get_history(days: int) -> Optional[pd.DataFrame]:
        """获取最近 N 日 A50 日线数据

        参数:
          days: int — 请求天数（至少 40 日，以保证 20 日滚动窗有足够预热）

        返回:
          pd.DataFrame — 列:
            - date: str       "YYYY-MM-DD"
            - open: float
            - high: float     # ⚠️ Parkison HV 需要
            - low: float      # ⚠️ Parkison HV 需要
            - close: float
            - volume: float
            - free_float: float
            或 None（数据不可用）

        异常:
          DataBridgeError — 仅当 DataBridge 接口本身故障时抛出
          数据缺失不抛出异常，返回 None（由调用方处理）
        """
        ...

    @staticmethod
    def available_dimensions() -> List[str]:
        """返回 DataBridge 当前数据的维度清单

        返回:
          List[str] — 如 ["close", "high", "low", "volume", "free_float"]
          DSV 校验前应调用此方法确认 Parkinson HV 辅源是否可用

        设计说明（X-C2 修复）:
          不可用维度 = 数据源不提供该字段，非"该维度今日未更新"
          建议在框架初始化时固定维度清单，不可用时持久降级
        """
        ...
```

### 3.2 异常定义

```python
class DataBridgeError(Exception):
    """DataBridge 接口故障（网络/配置/连接池等）
    不应因"数据不全"抛此异常（数据不全返回 None）
    """
    pass
```

### 3.3 数据可用性契约（X-C1 修复）

| 合约项 | 承诺值 | 说明 |
|:-------|:-------|:-----|
| 返回行数 | ≥ `requested_days` | 不可少于此值 |
| 日线数据天数 | 至少 40 日 | 支持 20 日滚动窗预热 + Phase 0.5 扩展 |
| 维度数组 | OHLCV + free_float | 实时反映可获取的字段 |
| 字段类型 | float (numeric) | 所有数值字段浮点数 |
| 缺值处理 | NaN 填不满，不填充 | 由调用方（DCM/LQM）处理 |

---

## 4. DCM 模块 — 波动率代理

### 4.1 函数签名

```python
class DCM:
    """波动率代理模块 — 计算 A50 年化历史波动率（HV）"""

    def __init__(self, lookback: int = LOOKBACK_WINDOW):
        self.lookback = lookback

    def compute_hv(self, price_series: pd.Series) -> Optional[float]:
        """计算单日年化历史波动率

        参数:
          price_series: pd.Series[float]
            - 长度 ≥ self.lookback + 1（至少 21 个 close 值）
            - 索引为日期字符串 "YYYY-MM-DD"
            - 按日期升序排列（最新在末尾）

        返回:
          float — 年化 HV（标量）
            或 None（数据不足 / 序列存在 NaN）

        算法:
          Step 1: log_return = log(close[t] / close[t-1])
          Step 2: volatility = std(log_return[-lookback:]) * sqrt(252)
          Step 3: return round(volatility, 6)

        异常:
          不抛出异常。数据不足时返回 None（由调用方标记 SKIPPED）
        """
        ...

    def run(self, data: pd.DataFrame) -> ModuleResult:
        """DCM 模块完整入口（被 pipeline 调用）

        参数:
          data: pd.DataFrame — 来自 DataBridge.get_history()
            必备列: close

        返回:
          ModuleResult:
            status=SUCCESS → data = {"hv": float}
            status=SKIPPED → data = None (数据缺失超 3 日)
            status=FAILED  → error = str

        缺值策略:
          max_fill_forward = 3  # 前值填充最多 3 日
          缺失 > 3 日 → SKIPPED（标记 data_gap）
        """
        ...
```

### 4.2 数据结构

```python
# DCM 返回的 ModuleResult.data 格式（status=SUCCESS）:
{
    "hv": 0.2835,         # 年化 HV（标量）
    "close_count": 21,    # 输入序列长度
    "filled_gaps": 0      # 前值填充天数
}
```

### 4.3 异常处理

| 场景 | 行为 | 状态 |
|:-----|:-----|:----:|
| 序列长度 < 21 | 无法计算收益率差 | SKIPPED + "insufficient_data" |
| 最近 20 日 close 中有 NaN | 逐日前值填充（≤3日） | SUCCESS |
| 最近 20 日连续 NaN > 3 | 超出填充上限 | SKIPPED + "data_gap_too_large" |
| close 全部相等（std=0） | 波动率 = 0，正常返回 | SUCCESS（合法场景） |

---

## 5. LQM 模块 — 换手率计算

### 5.1 函数签名

```python
class LQM:
    """换手率计算模块 — 计算 A50 日换手率"""

    def __init__(self):
        # 无状态 — 纯函数设计
        pass

    def compute_turnover(
        self,
        volume: float,
        free_float: float
    ) -> Optional[float]:
        """计算单日换手率

        参数:
          volume: float — 当日成交量（股数）
          free_float: float — 当日流通股数

        返回:
          float — 换手率（无量纲比值，范围通常在 [0, 1]）
            或 None（free_float == 0）

        算法:
          turnover = volume / free_float
        """
        ...

    def run(self, data: pd.DataFrame) -> ModuleResult:
        """LQM 模块完整入口

        参数:
          data: pd.DataFrame — 来自 DataBridge.get_history()
            必备列: volume, free_float

        返回:
          ModuleResult:
            status=SUCCESS → data = {"turnover": float}
            status=SKIPPED → free_float == 0 → "invalid_turnover"

        异常:
          不抛出异常
        """
        ...
```

### 5.2 数据结构

```python
# LQM 返回的 ModuleResult.data 格式:
{
    "turnover": 0.0325,   # 当日换手率
}
```

### 5.3 异常处理

| 场景 | 行为 | 状态 |
|:-----|:-----|:----:|
| free_float == 0 | 无流通数据（停牌/缺失） | SKIPPED + "invalid_turnover" |
| volume == 0 | 零成交量 | SUCCESS（turnover=0，合法） |
| volume / free_float > 1.0 | 换手率异常高但数学上合法 | SUCCESS（极值在归一化处理） |

---

## 6. ZNM 模块 — z-score 归一化

### 6.1 函数签名

```python
class ZNM:
    """z-score 归一化模块 — 20 日滚动标准化"""

    def __init__(self, lookback: int = LOOKBACK_WINDOW):
        self.lookback = lookback

    def compute_zscore(
        self,
        values: List[float],
        new_value: float
    ) -> Optional[float]:
        """计算单日 z-score（相对于最近 lookback 日的历史分布）

        参数:
          values: List[float] — 历史值序列（长度 ≥ 2）
          new_value: float — 当日新值

        返回:
          float — z-score
            或 None（历史值序列长度 < 2 或标准差为 0）

        算法:
          mean = mean(values[-lookback:])
          std  = std(values[-lookback:])
          if std == 0: return 0.0  # 无波动→z-score=0
          return (new_value - mean) / std

        设计说明:
          标准差为 0 → z-score=0（不是 None）
          因为"全相同序列"意味着最近值无异常偏离
        """
        ...

    def run(
        self,
        hv_series: List[float],
        turnover_series: List[float],
        new_hv: float,
        new_turnover: float
    ) -> ModuleResult:
        """ZNM 模块完整入口

        参数:
          hv_series: List[float] — 历史波动率序列（来自 LB）
          turnover_series: List[float] — 历史换手率序列（来自 LB）
          new_hv: float — 当日波动率
          new_turnover: float — 当日换手率

        返回:
          ModuleResult:
            data = {
                "vol_zscore": float,
                "turn_zscore": float,
                "mean_hv": float,        # 诊断
                "std_hv": float,         # 诊断
                "mean_turnover": float,  # 诊断
                "std_turnover": float    # 诊断
            }
        """
        ...
```

### 6.2 异常处理

| 场景 | 行为 | 状态 |
|:-----|:-----|:----:|
| hv_series 或 turnover_series 长度 < 2 | 无法计算均值和标准差 | FAILED + "insufficient_history" |
| 输入序列全部相等（std=0） | z-score = 0（非异常） | SUCCESS |
| new_value 为 None/NaN | 无法计算 | FAILED + "invalid_new_value" |

---

## 7. RSM 模块 — 共振状态机

### 7.1 函数签名

```python
class RSM:
    """共振状态机模块
    定位: L2.5（计算引擎之上，纯判定之下）
    内部结构:
      - _compute_strength() — 算法层（L2 职责）
      - _transition_state() — 状态层（L3 判定职责）
    """

    def __init__(self):
        self._min_strength = RESONANCE_MIN_STRENGTH
        self._quantile_threshold = QUANTILE_THRESHOLD

    # ═══════════════════════════════════════════
    # 子方法（供单元测试独立验收）
    # ═══════════════════════════════════════════

    def compute_strength(
        self,
        vol_zscore: float,
        turn_zscore: float
    ) -> Dict[str, Any]:
        """[算法层] 共振强度计算

        参数:
          vol_zscore: float — 波动率 z-score
          turn_zscore: float — 换手率 z-score

        返回:
          {
              "resonance": bool,     # 极值尾部分位同时触发?
              "strength": float,     # [0.0, 1.0]
              "direction": str,      # POSITIVE / NEGATIVE
              "vol_extreme": bool,   # |vol_zscore| > threshold?
              "turn_extreme": bool   # |turn_zscore| > threshold?
          }

        算法:
          vol_extreme = abs(vol_zscore) > QUANTILE_THRESHOLD
          turn_extreme = abs(turn_zscore) > QUANTILE_THRESHOLD
          same_direction = sign(vol_zscore) == sign(turn_zscore)
          if vol_extreme AND turn_extreme AND same_direction:
              strength = sqrt(vol² + turn²) / (threshold * sqrt(2))
              strength = clip(strength, 0.0, 1.0)
          else:
              strength = 0.0
          direction = "POSITIVE" if vol_zscore > 0 else "NEGATIVE"
        """
        ...

    def transition_state(
        self,
        strength: float,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """[状态层] 跨日程状态转换

        参数:
          strength: float — 当日共振强度 [0.0, 1.0]
          previous_state: Optional[Dict]
            格式: {"state": str, "duration": int, "last_update": str}
            首次运行或无历史时: None（自动初始化为 NONE）

        返回:
          {
              "state": str,         # NONE/WARN/ACTIVE/DECAY
              "duration": int,      # 新状态持续天数
              "transition": str,    # "STAY" / "UPGRADE" / "DEGRADE" / "RESET"
              "reason": str         # 转换理由（诊断用）
          }

        转换规则: 见 §2.2 状态转换矩阵
        """
        ...

    # ═══════════════════════════════════════════
    # 完整入口（被 pipeline 调用）
    # ═══════════════════════════════════════════

    def run(
        self,
        vol_zscore: float,
        turn_zscore: float,
        previous_state: Dict[str, Any]
    ) -> ModuleResult:
        """RSM 模块完整入口

        参数:
          vol_zscore: float — ZNM 输出
          turn_zscore: float — ZNM 输出
          previous_state: Dict[str, Any] — 从 LB.previous_state() 读取

        返回:
          ModuleResult:
            data = {
                "resonance": bool,
                "strength": float,
                "direction": str,
                "state": str,
                "state_duration": int,
                "transition": str,
                "reason": str
            }
        """
        # Step 1: 计算共振强度
        strength_result = self.compute_strength(vol_zscore, turn_zscore)

        # Step 2: 状态转换
        state_result = self.transition_state(
            strength=strength_result["strength"],
            previous_state=previous_state
        )

        # Step 3: 合并输出
        return ModuleResult(
            status="SUCCESS",
            data={
                "resonance": (
                    strength_result["resonance"]
                    and state_result["state"] in ("ACTIVE", "WARN")
                ),
                "strength": strength_result["strength"],
                "direction": strength_result["direction"],
                "state": state_result["state"],
                "state_duration": state_result["duration"],
                "vol_extreme": strength_result["vol_extreme"],
                "turn_extreme": strength_result["turn_extreme"],
                "transition": state_result["transition"],
                "reason": state_result["reason"]
            }
        )
```

### 7.2 "读→判→写"闭环（X-B1/X-B2 修复）

```
每次 pipeline.run():

  ┌─ Step 0.5A: 从 LB 读取前次状态
  │     lb = LookbackBuffer.load()
  │     prev_state = lb.previous_state()
  │     zscore_vols, zscore_turns = lb.zscore_series()
  │
  ├─ Step 5: RSM.run(vol_zscore, turn_zscore, prev_state)
  │     --- 在此完成共振判定 ---
  │
  └─ Step 9.5B: 将新状态写入 LB
        lb.append(LB_DailyRecord(
            date=today,
            resonance_state=result.data["state"],
            resonance_strength=result.data["strength"],
            direction=result.data["direction"],
            state_duration=result.data["state_duration"]
        ))
        lb.save()

  关键约束:
  - 每次 run() 必须读/写 LB
  - LB 的 previous_state() 必须返回"上一个交易日的状态"
  - 如果当日有数据但未触发 run()（如周末/假日），状态机不推进
```

---

## 8. DSV 模块 — 双源校验

### 8.1 函数签名

```python
from scipy.stats import spearmanr

class DSV:
    """双源校验模块
    Phase 0: 计算方法独立性校验
    - 主源: HV z-score（来自 ZNM，基于 close-to-close HV）
    - 辅源: Parkinson HV z-score（基于 OHLC 计算）
    - 校验方法: 两源 z-score 的 Spearman 秩相关性

    DSV 与 RSM 为并行关系：
      RSM ← ZNM.zscore(vol/turn)
      DSV ← ZNM.zscore(vol/turn) + DataBridge.OHLC
      ⋮ 两者互不依赖，结果并行送入 GKV
    """

    def __init__(self, lookback: int = LOOKBACK_WINDOW):
        self.lookback = lookback

    # ═══════════════════════════════════════════
    # 辅源计算方法
    # ═══════════════════════════════════════════

    def _compute_parkinson_hv(self, ohlc_df: pd.DataFrame) -> pd.Series:
        """计算 Parkinson 历史波动率（辅源）

        参数:
          ohlc_df: pd.DataFrame — 含 high, low, close 列

        返回:
          pd.Series — Parkinson HV 序列（年化）

        算法:
          Parkinson HV = sqrt(
            (1 / (4 * N * ln(2))) * Σ(ln(high[t] / low[t]))²
          ) * sqrt(252)

        异常:
          若 high/low 列不存在或全部为 NaN → 抛出 DataInsufficientError
        """
        ...

    # ═══════════════════════════════════════════
    # 主源方法（phase 0 默认）
    # ═══════════════════════════════════════════

    def _compute_hv_zscore(self, hv_series: pd.Series) -> float:
        """计算当日 HV z-score（作为主源）

        参数:
          hv_series: pd.Series — 最近 lookback 日 HV 序列

        返回:
          float — HV 的 z-score
        """
        ...

    # ═══════════════════════════════════════════
    # 校验核心
    # ═══════════════════════════════════════════

    def _compute_correlation(
        self,
        series_a: pd.Series,
        series_b: pd.Series
    ) -> Dict[str, Any]:
        """计算两序列的 Spearman 秩相关性

        参数:
          series_a, series_b: pd.Series — 等长序列

        返回:
          {
              "correlation": float,  # Spearman ρ [-1, 1]
              "p_value": float       # 
          }

        异常保护（B2 修复）:
          - 任一序列长度为 0 → {"correlation": 0.0, "p_value": 1.0}
          - 任一序列为常值（std=0）→ {"correlation": 0.0, "p_value": 1.0}
          - NaN 值 → 自动剔除（dropna）
        """
        if len(series_a) == 0 or len(series_b) == 0:
            return {"correlation": 0.0, "p_value": 1.0}
        if series_a.std() == 0 or series_b.std() == 0:
            return {"correlation": 0.0, "p_value": 1.0}
        corr, p = spearmanr(series_a, series_b)
        return {"correlation": round(corr, 4), "p_value": round(p, 4)}

    # ═══════════════════════════════════════════
    # 完整入口
    # ═══════════════════════════════════════════

    def run(
        self,
        vol_zscore_series: pd.Series,   # 来自 ZNM 的历史 z-score 序列
        ohlc_data: Optional[pd.DataFrame],  # 来自 DataBridge（OHLC 可用性）
        hv_zscore_today: float            # 当日 z-score（主源）
    ) -> ModuleResult:
        """DSV 模块完整入口

        参数:
          vol_zscore_series: pd.Series
            最近 lookback 日的 vol_zscore 序列
          ohlc_data: Optional[pd.DataFrame]
            OHLC 数据，若 DataBridge 不提供 high/low 则为 None
          hv_zscore_today: float
            当日 HV 的 z-score（主源值）

        返回:
          ModuleResult:
            status=SUCCESS → data = {
                "passed": bool,        # 双源校验通过?
                "partial": bool,       # 仅一源可用?
                "score": float,        # Spearman ρ 或 降级分值
                "p_value": float,      # 
                "source_count": int,   # 2(双源) / 1(单源降级)
                "main_corr": float,    # 主源纯度指标
                "aux_corr": float,     # 辅源纯度指标（不存在时 = None）
                "method": str          # "dual" / "single_degraded"
            }

        降级策略:
          辅源可用(high/low存在) → 双源校验
          辅源不可用(high/low缺失) → 单源+置信度衰减:
            score = min(0.7, 0.5 + 主源 z-score / 10)
            passed = score > 0.5
            partial = True
        """
        # Step 1: 检查数据维度（X-C2 修复）
        dimensions = ohlc_data.columns.tolist() if ohlc_data is not None else []
        has_aux_source = "high" in dimensions and "low" in dimensions

        # Step 2: 计算辅源 z-score
        if has_aux_source and len(ohlc_data) >= self.lookback + 1:
            parkinson_hv = self._compute_parkinson_hv(ohlc_data)
            # 使用已有的 hv_series 计算 parkinson HV 的 z-score
            aux_zscore = self._compute_hv_zscore(parkinson_hv)
            method = "dual"
        else:
            method = "single_degraded"

        # Step 3: 校验（双源或单源降级）
        if method == "dual":
            corr_result = self._compute_correlation(
                pd.Series([hv_zscore_today]),  # 简化：用当日主源值
                pd.Series([aux_zscore])
            )
            # 实际场景应当使用历史序列对计算
            # 此处为 Phase 0 缩量版
            score = abs(corr_result["correlation"])
            passed = score > 0.5  # 阈值
            partial = False
            return ModuleResult(status="SUCCESS", data={
                "passed": passed,
                "partial": partial,
                "score": round(score, 4),
                "p_value": corr_result["p_value"],
                "source_count": 2,
                "main_corr": None,
                "aux_corr": None,
                "method": method
            })
        else:
            # 单源降级（X-C2 实现）
            score = min(0.7, 0.5 + abs(hv_zscore_today) / 10)
            passed = score > 0.5
            return ModuleResult(status="SUCCESS", data={
                "passed": passed,
                "partial": True,
                "score": round(score, 4),
                "p_value": 0.0,
                "source_count": 1,
                "main_corr": None,
                "aux_corr": None,
                "method": method
            })
```

### 8.2 异常处理补充

| 场景 | 行为 | 状态 |
|:-----|:-----|:----:|
| 辅源可用（OHLC 完全） | 双源 Spearman 校验 | SUCCESS, method="dual" |
| 辅源不可用（缺 high/low） | 单源降级，置信度衰减 | SUCCESS, method="single_degraded", partial=True |
| 两序列全部为常数 | correlation=0，passed=False（B2 修复） | SUCCESS（合法结果） |
| ohlc_data 为 None | 降级为单源 | SUCCESS, partial=True |

---

## 9. GKV 模块 — 门控/否决

### 9.1 函数签名

```python
class GKV:
    """门控否决模块 — 否决制执行

    📌 否决不可绕过。GKV 没有"强制执行"选项。
    """

    def __init__(self):
        self._min_strength = RESONANCE_MIN_STRENGTH

    def run(
        self,
        resonance_state: str,
        resonance_strength: float,
        dsv_passed: bool,
        dsv_partial: bool
    ) -> ModuleResult:
        """GKV 模块完整入口

        参数:
          resonance_state: str — RSM 状态
          resonance_strength: float — RSM 强度 [0, 1]
          dsv_passed: bool — DSV 校验通过?
          dsv_partial: bool — DSV 部分通过?

        返回:
          ModuleResult:
            data = {
                "passed": bool,         # 通过 → 进入 CPE
                "veto_reason": str,     # 否决理由（否决触发时）
                "veto_source": str      # "rsm_strength" / "dsv_failed" / "passed"
            }

        否决规则（优先级从高到低）:
          1. [R1-硬否决] DSV passed=False → passed=False
              理由: "DSV 双源校验未通过"
          2. [R2-硬否决] resonance_strength < RESONANCE_MIN_STRENGTH
                 且 state != ACTIVE → passed=False
              理由: "共振强度不足（阈值 {RESONANCE_MIN_STRENGTH}）"
              例外: WARN 状态但强度回落 → 允许进入 CPE（让 CPE 决定）
          3. [R3-通过] 其他 → passed=True

        ⚠️ 规则 2 中的"WARN 状态例外"设计依据:
           如果状态机从 ACTIVE 回落到 WARN，仍允许通过 GKV
           让 CPE 根据连续记录决定是否降级仓位
           避免状态边界处的"锯齿否决"
        """
        ...
```

### 9.2 否决逻辑伪代码

```python
def run(self, resonance_state, resonance_strength, dsv_passed, dsv_partial):
    # R1: DSV 校验未通过 → 硬否决
    if not dsv_passed:
        return ModuleResult(status="SUCCESS", data={
            "passed": False,
            "veto_reason": "DSV 双源校验未通过",
            "veto_source": "dsv_failed"
        })

    # R2: 强度不足 → 否决
    # 例外: WARN 状态（来自 ACTIVE 回落）
    if resonance_strength < self._min_strength and resonance_state != "WARN":
        return ModuleResult(status="SUCCESS", data={
            "passed": False,
            "veto_reason": f"共振强度 {resonance_strength:.2f} < 阈值 {self._min_strength}",
            "veto_source": "rsm_strength"
        })

    # R3: 通过
    return ModuleResult(status="SUCCESS", data={
        "passed": True,
        "veto_reason": None,
        "veto_source": "passed"
    })
```

### 9.3 异常处理

| 场景 | 行为 | 状态 |
|:-----|:-----|:----:|
| 输入含 None | None → 视为不满足条件 | SUCCESS（转化为否决） |
| state 为 None | 视为 NONE | SUCCESS |
| GKV 自身逻辑错误 | 不应发生；发生 → FAILED | FAILED + "gkv_internal_error" |

---

## 10. CPE 模块 — 条件放行评估

### 10.1 函数签名

```python
class CPE:
    """条件放行评估模块

    输入（来自 GKV 通过后）:
      - RSM 的共振强度序列（连续 N 日）
      - DSV 校验结果
      - LB 历史记录

    输出:
      - FULL_PASS: 正常仓位（position_cap = 1.0）
      - CONDITIONAL_PASS: 受限仓位（position_cap = 0.5）
    """

    def __init__(self):
        self._min_strength = RESONANCE_MIN_STRENGTH
        self._required_consecutive_days = 5

    def run(
        self,
        resonance_strength_today: float,
        lb: LookbackBuffer,
        dsv_passed: bool,
        dsv_partial: bool
    ) -> ModuleResult:
        """CPE 模块完整入口

        参数:
          resonance_strength_today: float — 当日共振强度
          lb: LookbackBuffer — 用于检查历史连续强度
          dsv_passed: bool — DSV 校验通过
          dsv_partial: bool — DSV 部分通过

        返回:
          ModuleResult:
            data = {
                "verdict": str,           # "FULL_PASS" / "CONDITIONAL_PASS"
                "position_cap": float,    # 仓位上限 [0, 1]
                "reason": str,            # 判定理由
                "continuous_strong_days": int  # 连续满足日计数
            }

        规则:
          1. [D2 修复] DSV partial=True → 自动 FULL_PASS
             （双源仅一源通过，不可触发 CONDITIONAL_PASS）
             reason = "DSV partial=True → 自动 FULL_PASS"

          2. [CONDITIONAL_PASS] 同时满足:
             - resonance_strength_today > RESONANCE_MIN_STRENGTH  （当日满足）
             - 最近连续 5 日（包含今日）每日强度 > RESONANCE_MIN_STRENGTH （持续满足）
             - dsv_passed == True 且 dsv_partial == False           （双源完全通过）
             →
             verdict = "CONDITIONAL_PASS"
             position_cap = CONDITIONAL_PASS_POSITION_CAP (0.5)
             reason = "持续高共振 + 双源通过 → 保守限仓"

          3. [FULL_PASS] 不满足条件 2 → 正常仓位
             verdict = "FULL_PASS"
             position_cap = 1.0
             reason = "条件放行条件未满足 → 正常仓位"
        """
        # 规则 1: partial 降级
        if dsv_partial:
            return ModuleResult(status="SUCCESS", data={
                "verdict": "FULL_PASS",
                "position_cap": 1.0,
                "reason": "DSV partial=True → 自动 FULL_PASS",
                "continuous_strong_days": 0
            })

        # 统计连续满足天数
        from itertools import takewhile
        recent_strengths = [r.resonance_strength for r in reversed(lb.records)]
        continuous = sum(1 for s in takewhile(
            lambda x: x > self._min_strength, recent_strengths
        ))

        # 规则 2: CONDITIONAL_PASS
        if (
            resonance_strength_today > self._min_strength
            and continuous >= self._required_consecutive_days
        ):
            return ModuleResult(status="SUCCESS", data={
                "verdict": "CONDITIONAL_PASS",
                "position_cap": min(
                    CONDITIONAL_PASS_POSITION_CAP,
                    1.0  # 此处为风控上限占位，Phase 0.5 集成
                ),
                "reason": "持续高共振+双源通过 → 保守限仓",
                "continuous_strong_days": continuous
            })

        # 规则 3: FULL_PASS
        return ModuleResult(status="SUCCESS", data={
            "verdict": "FULL_PASS",
            "position_cap": 1.0,
            "reason": "条件放行条件未满足 → 正常仓位",
            "continuous_strong_days": continuous
        })
```

### 10.2 CPE 执行规则汇总

| 条件 | 结果 | position_cap | 说明 |
|:-----|:-----|:------------:|:-----|
| DSV partial=True | FULL_PASS | 1.0 | 单源已验证不足，不触发限制 |
| 连续 5 日 > 0.6 + DSV 完全通过 | CONDITIONAL_PASS | 0.5 | 阈值越强越保守 |
| 其他 | FULL_PASS | 1.0 | 正常仓位，仍受整体风控约束 |

### 10.3 CONDITIONAL_PASS 信号生效约束（X-D1 修复）

| 维度 | 定义 | Phase 0 实现方式 |
|:-----|:-----|:-----------------|
| **信号生效窗口** | T+1 开盘后 30 分钟内有效 | Phase 0 输出信号到 `signals/resonance/` 目录，由 downstream 决定执行时机 |
| **仓位递减规则** | 一次到位（50%），不分布执行 | Phase 0 不实现分步；Phase 1 可增加 |
| **与现有风控的关系** | position_cap = min(0.5, 整体风控上限) | Phase 0 position_cap 独立输出，由下游整合 |

---

## 11. SG 模块 — 信号生成

### 11.1 函数签名

```python
import uuid
from datetime import datetime, timezone

class SG:
    """信号生成模块
    职责:
      - 组装 ResonanceSignal 对象
      - 写入 .done 信号文件
      - 写入信号文件到 signals/resonance/ 目录

    Phase 0:
      - 文件信号写入（signals/resonance/）
      - .done 信号兼容（signals/tasks/）
    Phase 1+:
      - 日内信号路由（复用现有信号总线）
    """

    def __init__(self, output_dir: str = SIGNAL_OUTPUT_DIR):
        self.output_dir = output_dir

    def build_signal(
        self,
        date: str,
        gkv_result: Dict,
        cpe_result: Dict,
        rsm_result: Dict,
        dsv_result: Dict,
        diagnostics: Dict[str, Any] = None
    ) -> ResonanceSignal:
        """组装 Signal Protocol v1 信号

        参数:
          date: str — "YYYY-MM-DD"
          gkv_result: Dict — GKV.run() 的 data
          cpe_result: Dict — CPE.run() 的 data
          rsm_result: Dict — RSM.run() 的 data
          dsv_result: Dict — DSV.run() 的 data
          diagnostics: Dict — 诊断信息（可选）

        返回:
          ResonanceSignal — 完整信号对象
        """
        signal_id = f"resonance_{date.replace('-', '')}_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc).astimezone().strftime(
            "%Y-%m-%dT%H:%M:%S+08:00"
        )

        return ResonanceSignal(
            signal_id=signal_id,
            timestamp=now,
            date=date,
            version="resonance.v1",
            resonance_detected=(
                rsm_result.get("resonance", False)
                and gkv_result.get("passed", False)
            ),
            state=rsm_result.get("state", "NONE"),
            strength=rsm_result.get("strength", 0.0),
            direction=rsm_result.get("direction", "NEUTRAL"),
            duration_days=rsm_result.get("state_duration", 0),
            dual_source_passed=dsv_result.get("passed", False),
            dual_source_partial=dsv_result.get("partial", False),
            dual_source_score=dsv_result.get("score", 0.0),
            gkv_passed=gkv_result.get("passed", False),
            gkv_reason=gkv_result.get("veto_reason"),
            cpe_verdict=cpe_result.get("verdict", "FULL_PASS"),
            position_cap=cpe_result.get("position_cap", 1.0),
            diagnostics=diagnostics or {}
        )

    def write_signal(self, signal: ResonanceSignal) -> str:
        """写入信号文件（JSON）

        参数:
          signal: ResonanceSignal

        返回:
          str — 写入的完整文件路径

        文件命名:
          {output_dir}/resonance_{date}_{signal_id}.json

        写入后验证:
          立即 read 读回，确认 status 字段存在（§写入验证）
        """
        import json, os, time
        path = os.path.join(self.output_dir, f"{signal.signal_id}.json")

        # 原子写入（临时文件 → rename）
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(asdict(signal), f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

        # 写入验证
        self._verify_write(path)

        return path

    def write_done(self, task_id: str, signal: ResonanceSignal) -> str:
        """写入 .done 信号文件

        参数:
          task_id: str — 任务标识
          signal: ResonanceSignal — 信号对象

        返回:
          str — 写入路径

        写入路径:
          {DONE_DIR}/{task_id}.done

        文件内容:
          { 提取自 signal 的关键字段 }
        """
        import json, os
        path = os.path.join(SIGNAL_DONE_DIR, f"{task_id}.done")
        content = {
            "signal_id": signal.signal_id,
            "status": "DONE",
            "date": signal.date,
            "resonance_detected": signal.resonance_detected,
            "state": signal.state,
            "strength": signal.strength,
            "cpe_verdict": signal.cpe_verdict,
            "position_cap": signal.position_cap,
            "timestamp": signal.timestamp
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        self._verify_write(path)
        return path
```

### 11.2 信号路由

| 输出通道 | 路径 | 格式 | 触发条件 |
|:---------|:-----|:-----|:---------|
| 信号文件 | `signals/resonance/{signal_id}.json` | 完整 ResonanceSignal | 每次 run() |
| .done | `signals/tasks/phase0.1_detailed_design.done` | 精简字段 | 同上 |
| 诊断日志 | `logs/resonance/{date}.log` | 文本 | 每次 run() |

---

## 12. SCL 调度层适配器

### 12.1 抽象基类

```python
from abc import ABC, abstractmethod

class SchedulingAdapter(ABC):
    """调度层抽象基类
    约束: 不嵌入业务逻辑，仅通过 pipeline.run() 统一接口调用
          import 级间接依赖是必要的，但不侵入计算引擎内部实现（A1 修复）
    """

    @abstractmethod
    def run_once(self) -> Optional[ResonanceSignal]:
        """单次执行共振判定全流程

        返回:
          ResonanceSignal — 成功计算并产生信号
          None — 无新数据需处理

        约束:
          不抛出异常。内部错误→记录日志→返回 None
        """
        pass

    @abstractmethod
    def force_run(self, date: str) -> ResonanceSignal:
        """强制指定日期执行（回测/复盘用）

        参数:
          date: str — "YYYY-MM-DD" 格式（E2 修复: 明确格式规约）

        返回:
          ResonanceSignal — 始终返回信号（即使空信号）
          不返回 None

        异常:
          如果 date 格式无效或超出可用数据范围→抛 ValueError
        """
        pass

    def on_event(self, event: dict) -> Optional[ResonanceSignal]:
        """事件驱动入口（Phase 1+ 支持）

        默认实现 = run_once()
        子类可重写为 Webhook / 消息队列驱动
        """
        return self.run_once()
```

### 12.2 PollingAdapter（Phase 0 默认实现）

```python
import logging
logger = logging.getLogger(__name__)

class PollingAdapter(SchedulingAdapter):
    """定时轮询实现 — Phase 0 默认

    配置:
      interval_minutes: int — 轮询间隔（默认 30 分钟）
      max_retries: int — 重试次数（默认 1 次，E1 修复）
      pipeline: callable — 计算管线（外部注入）
    """

    def __init__(
        self,
        pipeline,
        interval_minutes: int = SCL_DEFAULT_INTERVAL_MINUTES,
        max_retries: int = SCL_MAX_RETRIES
    ):
        self.pipeline = pipeline
        self.interval = interval_minutes
        self.last_check = None
        self.max_retries = max_retries

    def run_once(self) -> Optional[ResonanceSignal]:
        """单次轮询执行

        流程:
          1. _has_new_data() — 检查是否有新日数据
          2. 无新数据 → 返回 None（快速路径）
          3. 有新数据 → 调用 pipeline.run()
          4. 异常 → 重试（max_retries 次）
          5. 重试仍失败 → 记录日志，返回 None（静默跳过）
        """
        if not self._has_new_data():
            return None

        for attempt in range(self.max_retries + 1):
            try:
                signal = self.pipeline.run()
                self.last_check = DataBridge.get_latest_date()
                return signal
            except Exception as e:
                if attempt < self.max_retries:
                    continue
                logger.warning(
                    f"PollingAdapter.run_once 失败(已重试{attempt}次): {e}"
                )
                return None

    def force_run(self, date: str) -> ResonanceSignal:
        """强制指定日期执行

        参数:
          date: str — "YYYY-MM-DD" 格式
        """
        return self.pipeline.run(force_date=date)

    def _has_new_data(self) -> bool:
        """检查 DataBridge 是否有新数据"""
        try:
            latest = DataBridge.get_latest_date()
            if latest is None:
                return False
            return latest != self.last_check
        except Exception:
            return False
```

### 12.3 EventAdapter（Phase 1 预留占位）

```python
class EventAdapter(SchedulingAdapter):
    """事件驱动实现 — Phase 1+ 预留"""

    def __init__(self, pipeline, queue_url=None):
        self.pipeline = pipeline
        self.queue = queue_url

    def on_event(self, event: dict) -> Optional[ResonanceSignal]:
        """事件驱动入口
        参数格式待定（Phase 1 设计）
        """
        return self.pipeline.run()
```

---

## 13. pipeline.py 编排逻辑

### 13.1 完整调用栈

```
SCL (PollingAdapter.run_once)
  │  ┌── _has_new_data() → DataBridge.get_latest_date()
  │  │       └── DataBridge.get_history(days=40)  → df
  │  └── 有新数据 → pipeline.run()
  │
  └── pipeline.run()
        │
        ├── Step 0.5A: LB 初始化
        │     LookbackBuffer.load()  → lb
        │     zscore_vols, zscore_turns = lb.zscore_series()
        │     prev_rsm_state = lb.previous_state()
        │
        ├── Step 1: DataBridge 获取数据
        │     df = DataBridge.get_history(days=40)
        │     today_ohlc = df.iloc[-1]
        │
        ├── Step 2: DCM — 波动率计算
        │     dcm_result = DCM.run(df)
        │     if dcm_result.status != "SUCCESS" → SKIP_PIPELINE
        │
        ├── Step 3: LQM — 换手率计算
        │     lqm_result = LQM.run(df)
        │     if lqm_result.status != "SUCCESS" → SKIP_PIPELINE
        │
        ├── Step 4: ZNM — z-score 归一化
        │     znm_result = ZNM.run(
        │         hv_series=zscore_vols,
        │         turnover_series=zscore_turns,
        │         new_hv=dcm_result.data["hv"],
        │         new_turnover=lqm_result.data["turnover"]
        │     )
        │     if znm_result.status != "SUCCESS" → SKIP_PIPELINE
        │
        ├── Step 5a: RSM 共振状态机 ──┐  (并行，互不依赖)
        │     rsm_result = RSM.run(    │
        │         vol_zscore=znm_result.data["vol_zscore"],
        │         turn_zscore=znm_result.data["turn_zscore"],
        │         previous_state=prev_rsm_state
        │     )                        │
        │                              │
        ├── Step 5b: DSV 双源校验 ─────┘
        │     dsv_result = DSV.run(
        │         vol_zscore_series=znm_result.data["vol_zscore"],
        │         ohlc_data=df,
        │         hv_zscore_today=znm_result.data["vol_zscore"]
        │     )
        │
        ├── Step 6: GKV 门控/否决
        │     gkv_result = GKV.run(
        │         resonance_state=rsm_result.data["state"],
        │         resonance_strength=rsm_result.data["strength"],
        │         dsv_passed=dsv_result.data["passed"],
        │         dsv_partial=dsv_result.data["partial"]
        │     )
        │     if not gkv_result.data["passed"]:
        │         → 否决触发，跳过 CPE
        │         → 仍生成信号（含否决原因）
        │
        ├── Step 7: CPE 条件放行评估
        │     cpe_result = CPE.run(
        │         resonance_strength_today=rsm_result.data["strength"],
        │         lb=lb,
        │         dsv_passed=dsv_result.data["passed"],
        │         dsv_partial=dsv_result.data["partial"]
        │     )
        │
        ├── Step 8: SG 信号组装 + 输出
        │     signal = SG.build_signal(...)
        │     SG.write_signal(signal)
        │     SG.write_done(task_id, signal)
        │
        ├── Step 9.5A: 更新 LB（当日数据）
        │     lb.append(LB_DailyRecord(
        │         date=today,
        │         hv=dcm_result.data["hv"],
        │         turnover=lqm_result.data["turnover"],
        │         vol_zscore=znm_result.data["vol_zscore"],
        │         turn_zscore=znm_result.data["turn_zscore"],
        │         resonance_state=rsm_result.data["state"],
        │         resonance_strength=rsm_result.data["strength"],
        │         direction=rsm_result.data["direction"],
        │         state_duration=rsm_result.data["state_duration"]
        │     ))
        │     lb.save()
        │
        └── Step 10: 返回信号
              return signal
```

### 13.2 主函数签名

```python
class ResonancePipeline:
    """共振管线 — 完整编排

    职责:
      - 组装所有模块
      - 编排执行顺序
      - 错误处理 + 重试
      - 输出信号

    设计约束（§1.2 依赖规则）:
      RSM ∥ DSV: 两者并行，互不依赖，均输入自 ZNM
      SCL: 不嵌入业务逻辑，仅通过 pipeline.run() 统一接口
    """

    def __init__(self):
        self.dcm = DCM()
        self.lqm = LQM()
        self.znm = ZNM()
        self.rsm = RSM()
        self.dsv = DSV()
        self.gkv = GKV()
        self.cpe = CPE()
        self.sg = SG()

    def run(
        self,
        force_date: Optional[str] = None
    ) -> ResonanceSignal:
        """执行完整共振判定管线

        参数:
          force_date: Optional[str] — "YYYY-MM-DD"
            正常流程: 使用当日最新数据
            回测/复盘: 强制使用指定日期的数据

        返回:
          ResonanceSignal — 始终返回（即使计算失败也返回空信号）

        异常:
          不抛出顶层异常。内部异常→记录日志→返回空信号
        """
        ...
```

### 13.3 错误处理策略

| 场景 | 处理方式 | pipeline 行为 |
|:-----|:---------|:--------------|
| DataBridge 数据不可用 | 返回 None（不抛异常） | `SKIP_PIPELINE` → 返回空信号 |
| DCM/LQM 计算失败 | 状态=SKIPPED，记录原因 | `SKIP_PIPELINE` → 返回空信号 |
| ZNM 计算失败 | 状态=FAILED（历史数据不足） | `SKIP_PIPELINE` → 返回空信号 |
| RSM 异常 | 记录错误，使用默认状态继续 | 继续执行（让 GKV 决定） |
| DSV 异常 | 降级为 partial=True | 继续执行 |
| GKV/CPE 异常 | 记录错误 | 返回空信号（安全模式） |
| SG 写入失败 | 重写 1 次，仍失败→日志告警 | 返回空信号（信号丢失告警） |
| **顶层未捕获异常** | max_retries=1 + 静默跳过 | SCL 层兜底 |

### 13.4 SKIP_PIPELINE 定义

```python
# 当以下条件任一满足时，pipeline 不应尝试生成共振信号:
# - DataBridge 无数据
# - DCM 无法计算波动率（数据缺失超期）
# - LQM 无法计算换手率（free_float=0）
# - ZNM 无法归一化（历史序列不足）

# SKIP_PIPELINE 后的输出:
EMPTY_SIGNAL = ResonanceSignal(
    signal_id="skip",           # 特殊标记
    timestamp=now(),
    date=today,
    version="resonance.v1",
    resonance_detected=False,
    state="NONE",
    strength=0.0,
    direction="NEUTRAL",
    duration_days=0,
    dual_source_passed=False,
    dual_source_partial=False,
    dual_source_score=0.0,
    gkv_passed=False,
    gkv_reason="PIPELINE_SKIPPED: 前置计算未完成",
    cpe_verdict="FULL_PASS",
    position_cap=1.0,
    diagnostics={"skip_reason": str}
)
```

### 13.5 LB 读/写完整序列（X-B1/X-B2 修复后）

```python
# ─── 每次 pipeline.run() 执行一次 ───

# [期初] Step 0.5A: 从 LB 读取
lb = LookbackBuffer.load()  # 从 JSON 恢复或新建
prev_state = lb.previous_state()
zscore_vols, zscore_turns = lb.zscore_series()

# [执行] Steps 1-8: 正常计算...

# [期末] Step 9.5A: 更新数据字段
lb.append(LB_DailyRecord(
    date=today,
    hv=dcm_result.data["hv"],           # 从 DCM
    turnover=lqm_result.data["turnover"], # 从 LQM
    vol_zscore=znm_result.data["vol_zscore"],
    turn_zscore=znm_result.data["turn_zscore"],
    resonance_state=rsm_result.data["state"],       # 已更新
    resonance_strength=rsm_result.data["strength"],
    direction=rsm_result.data["direction"],
    state_duration=rsm_result.data["state_duration"]
))

# [期末] Step 9.5B: 持久化到文件
lb.save()
```

---

## 14. Module API Contract 汇总

### 14.1 模块依赖图

```
                                 ┌──────────────┐
                                 │  DataBridge   │
                                 └──────┬───────┘
                                        │ OHLCV + free_float
                      ┌─────────────────┼─────────────────┐
                      ▼                 ▼                  ▼
                   ┌──────┐         ┌──────┐        ┌──────────────┐
                   │ DCM  │         │ LQM  │        │  DataBridge  │
                   │ HV   │         │ Turn │        │ available_   │
                   └──┬───┘         └──┬───┘        │ dimensions   │
                      │                 │            └──────┬───────┘
                      └────────┬────────┘                   │
                               ▼                            │
                         ┌──────────┐                       │
                         │   ZNM    │                       │
                         │ z-score  │                       │
                         └────┬─────┘                       │
                              │                             │
                ┌─────────────┼─────────────┐              │
                ▼                           ▼              │
          ┌─────────┐                ┌──────────┐          │
          │   RSM   │  并行互不依赖   │   DSV    │◄─────────┘
          │共振状态机│                │双源校验   │ (OHLC查询)
          └────┬────┘                └────┬─────┘
               │                           │
               └─────────────┬─────────────┘
                             ▼
                       ┌──────────┐
                       │   GKV    │
                       │  门控    │
                       └────┬─────┘
                            │
                       ┌────▼─────┐
                       │   CPE    │
                       │ 条件放行  │
                       └────┬─────┘
                            │
                       ┌────▼─────┐
                       │    SG    │
                       │ 信号生成  │
                       └──────────┘
```

### 14.2 返回值契约

| 源模块 | 目标模块 | 传递数据 | 格式约束 | 必须非空? |
|:------|:---------|:---------|:---------|:---------:|
| DataBridge | DCM | `pd.DataFrame` | 含 `close` 列, ≥40 行 | ✅ |
| DataBridge | LQM | `pd.DataFrame` | 含 `volume`, `free_float` 列 | ✅ |
| DataBridge | DSV | `pd.DataFrame` | 含 `high`, `low` 列（可选） | ❌（None→降级） |
| DCM | ZNM | `{"hv": float}` | float | ✅ |
| LQM | ZNM | `{"turnover": float}` | float | ✅ |
| ZNM | RSM | `{"vol_zscore": float}` | float * | ✅ |
| ZNM | DSV | `{"vol_zscore": float}` | float * | ✅ |
| LB | RSM | `{"state","duration","last_update"}` | Dict | ✅（None→NONE） |
| RSM | GKV | `{"state","strength"}` | str+float | ✅ |
| DSV | GKV | `{"passed","partial"}` | bool | ✅ |
| GKV | CPE | `{"passed","veto_reason"}` | bool+str | ✅ |
| CPE | SG | `{"verdict","position_cap"}` | str+float | ✅ |

> *ZNM 输出的 `vol_zscore` 和 `turn_zscore` 分别路由到 RSM 和 DSV。

### 14.3 错误异常传播规则

| 规则 # | 规则内容 |
|:------:|:---------|
| ERR-1 | **模块内部异常不跨越模块边界**。每个模块在自己的 `run()` 方法中捕获所有异常，转化为 `ModuleResult(status=FAILED)` 或 `SKIPPED` |
| ERR-2 | **顶层异常由 SCL 捕获**。`pipeline.run()` 本身不抛异常（若发生未预期异常 → SCL 层重试+跳过的兜底策略） |
| ERR-3 | **DataBridge 异常是唯一允许抛出的异常**。因为 DataBridge 是外部服务，其故障需要独立处理（E1） |
| ERR-4 | **SKIPPED ≠ FAILED**。SKIPPED：前置条件不满足（数据不足、指标无效），不表示系统故障。FAILED：计算异常 |
| ERR-5 | **否决 ≠ 错误**。GKV 判定 `passed=False` 是正常业务路径，不是错误。 |
| ERR-6 | **SKIP_PIPELINE 后仍生成空信号**。即使管线跳过（数据不足），也输出一个标记为 SKIP 的空信号，以便下游系统区分"无信号"和"系统故障" |
| ERR-7 | **写入后验证失败 → 重试 + 告警**。SG.write_signal() / write_done() 后立即 read 验证，最多重试 3 次，均失败→日志告警 |
| ERR-8 | **熔断不跨日**。当日 pipeline.run() 失败后，次日重新开始，不累积失败计数。Phase 0.5 的 EMA 熔断模块会提供跨日熔断能力 |

---

## 15. 文件结构

```text
mozhi_platform/
├── docs/07_research/右侧交易辩论/
│   └── 右交共振Phase0详细设计方案_v1.md    ← 本文档
│
├── src/
│   └── resonance/
│       ├── __init__.py
│       ├── constants.py          # §1 全局常量
│       ├── data_bridge.py        # §3 DataBridge
│       ├── models.py             # §2 数据结构
│       ├── dcm.py                # §4 波动率代理
│       ├── lqm.py                # §5 换手率计算
│       ├── znm.py                # §6 z-score 归一化
│       ├── rsm.py                # §7 共振状态机
│       ├── dsv.py                # §8 双源校验
│       ├── gkv.py                # §9 门控/否决
│       ├── cpe.py                # §10 条件放行
│       ├── sg.py                 # §11 信号生成
│       ├── scl.py                # §12 调度层适配器
│       ├── pipeline.py           # §13 编排逻辑
│       └── lookback_buffer.py    # §2.1 Lookback Buffer
│
├── data/
│   ├── lookback_buffer_v1.json   # LB 持久化
│   └── ...
│
├── signals/
│   ├── resonance/                # 共振信号输出
│   └── tasks/                    # .done 信号
│
└── tests/
    └── test_resonance/
        ├── test_dcm.py
        ├── test_lqm.py
        ├── test_znm.py
        ├── test_rsm.py
        ├── test_dsv.py
        ├── test_gkv.py
        ├── test_cpe.py
        ├── test_sg.py
        ├── test_scl.py
        ├── test_pipeline.py
        └── conftest.py
```

---

## 变更日志

| 版本 | 日期 | 说明 |
|:-----|:-----|:-----|
| v1.0 | 2026-05-29 | 初版 — 基于框架设计 v2.0 + 墨萱评审 + 玄知评审 |

**设计修复追溯**:

| 评审问题 | 本设计对应节 | 修复方式 |
|:---------|:------------|:---------|
| C1 (DSV↔RSM 顺序矛盾) | §3, §13.1 Step 5a/5b | 明确并行，步骤编号统一 |
| X-A1 (依赖声明错误) | §14.1 依赖图 | RSM→ZNM, GKV→RSM+DSV，独立分支 |
| C2 (LB 更新时机缺失) | §13.1 Step 0.5A/9.5A/9.5B | 完整读→判→写闭环 |
| C3/X-B1 (状态持久化未定义) | §2.1, §2.2, §7.2 | `previous_state()` + transition 矩阵 |
| X-B2 (期初恢复/期末持久化) | §13.5 | LB.load() / lb.save() |
| A1 (SCL 表述) | §12.1 | "不侵入内部实现" |
| A2/B1 (RSM 跨层) | §7 | 内部拆为 `compute_strength()` + `transition_state()` |
| D1 (0.6 阈值常量化) | §1 | `RESONANCE_MIN_STRENGTH` 全局常量 |
| D2 (DSV partial 规则) | §10.2 | partial=True → 自动 FULL_PASS |
| B2 (Spearman 异常保护) | §8.1 `_compute_correlation()` | guard clause (空序列/常值) |
| E1 (SCL 无重试) | §12.2 | `max_retries=1` |
| E2 (force_run 日期格式) | §12.1 | "YYYY-MM-DD" |
| X-C1 (DataBridge 耦合风险) | §3.3 | 依赖契约表 |
| X-C2 (DSV 辅源信号路径) | §8.1 | `available_dimensions()` + 降级逻辑 |
| X-D1 (CONDITIONAL_PASS 执行维度) | §10.3 | 生效窗口/仓位规则/风控关系 |
| X-E1 (DSV 代码行数) | §8 | 约 100-120 行 |

---

*本文档为墨枢系统（墨家投资室多Agent系统）Phase 0.1 详细设计交付物。*
