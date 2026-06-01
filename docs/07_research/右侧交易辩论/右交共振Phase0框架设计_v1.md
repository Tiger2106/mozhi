# 右侧交易情绪-流动性共振 Phase 0 总体框架设计

**作者**: 墨衡 🖋️
**创建时间**: 2026-05-29T07:15:00+08:00
**版本**: v1.0
**状态**: 设计稿（待会签）
**依据**: 辩论总结 `辩论总结_会签_v1.0.md` / ARCH001_v1

---

## 目录

0. 设计承诺清单（辩论结论→设计决策映射）
1. 系统架构全景（4层）
2. 模块划分及职责
3. 数据流（数据源 → 计算 → 判定 → 输出）
4. 关键数据结构定义
5. 与现有系统的集成关系
6. 否决制 / CONDITIONAL PASS 灰度层位置
7. 调度层适配器设计
8. 轻架构考量与模块计数
9. 附录：Phase 0 → Phase 1 演进路线

---

## 0. 设计承诺清单

| # | 辩论结论约束 | 本设计对应 | 是否覆盖 |
|:-:|:------------|:-----------|:--------:|
| 1 | 情绪代理：VIX波动率/舆情情绪打分（二选一，单源可复现） | §2.1 DCM 模块 — 选型 **波动率代理**（HV z-score → Phase 0.5 升级 IV） | ✅ |
| 2 | 流动性代理：换手率/买卖价差 | §2.2 LQM 模块 — 选型 **换手率**（L2 体系，数据就绪） | ✅ |
| 3 | 共振判定：同极端分位数同时触发（20日z-score联动） | §2.3 RSM 模块 — 20日滚动 z-score + 极值联合检测 | ✅ |
| 4 | 双源校验：双源缩量版，来源独立性验证 | §2.4 DSV 模块 — 轻量双源校验（不同方法/不同窗口） | ✅ |
| 5 | 否决制：sanity check 不通过一律否决 | §2.5 GKV 模块 + §6 硬否决位置 | ✅ |
| 6 | CONDITIONAL PASS：连续5日共振>0.6+双源校验通过，仓位上限≤50% | §2.6 CPE 模块 + §6.2 条件放行逻辑 | ✅ |
| 7 | 调度层适配器：事件驱动vs定时轮询"不兼容"限定在调度层 | §7 SCL 适配器 — 调度层唯一抽象，计算引擎零侵入 | ✅ |
| 8 | 架构轻是加分项 | §8 模块计数——8模块（含调度层），6核心计算模块 | ✅ |

---

## 1. 系统架构全景（4层）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Layer 4: 信号输出层                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  SG (Signal Generator) / CPL (Signal Protocol v1 Adapter)       │   │
│  │  职责：┌→ Signal Protocol v1 格式信号                              │   │
│  │        ├→ .done 信号文件写入                                     │   │
│  │        └→ 日内/日终信号路由                                     │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                          Layer 3: 决策判定层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ │
│  │  GKV (门控)  │  │  CPE (条件)  │  │  EMA (应急熔断)  [Phase 0.5+] │ │
│  │  Sanity Check│  │  Cond. Pass  │  │  连续亏/回撤超限熔断           │ │
│  │  否决制执行   │  │  灰度放行    │  │                                ｜ │
│  └──────┬───────┘  └──────┬───────┘  └────────────────────────────────┘ │
│         └─────────┬───────┘                                              │
│                   ▼                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  RSM (Resonance State Machine) — 共振状态机                      │   │
│  │  职责：共振强度计算 + 状态转换（无共振→预警→共振→衰减）            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                          Layer 2: 计算引擎层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ │
│  │  ZNM 模块    │  │  DSV 模块    │  │  DSV-2 (辅助校验)              │ │
│  │  z-score归一  │  │  双源校验    │  │  降级: 无双源→单源+置信度衰减   │ │
│  │  (20日滚动)   │  │  (缩量版)    │  │                                │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────────────────────────┘ │
│         │                 │                                              │
│         ▼                 ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  LB (Lookback Buffer) — 20日滚动数据缓存                          │   │
│  │  (内存DF + 文件持久化双存储)                                       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                          Layer 1: 数据采集层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ │
│  │  DCM 模块    │  │  LQM 模块    │  │  VIX-Proxy 计算器              │ │
│  │  波动率代理   │  │  换手率计算   │  │  (Phase 0: HV → Phase 0.5: IV) │ │
│  │  (A50价格)   │  │  (vol/free_  │  │                                │ │
│  │              │  │   float)     │  │                                │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────────────────────────┘ │
│         │                 │                                              │
│         ▼                 ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  DataBridge (数据桥) — 统一数据入口                                │   │
│  │  职责：A50 日线 OHLCV + free_float 获取，缓存策略，错误重试         │   │
│  │  对接：data_contract.py / etl_normalizer.py / source_registry.json  │   │
│  │  复用：现有 morning_pipeline 的数据管线                              │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                    Layer 0: 调度层（非侵入、可替换）                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  SCL (Scheduling Layer Adapter)                                  │   │
│  │  职责：将调度机制（cron轮询/事件驱动）转化为统一调用接口              │   │
│  │  封装：run_once() / force_run() / on_event()                     │   │
│  │  不侵入：Layer 1-4 的纯计算接口不感知调度方式                      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.1 分层责任边界

| 层 | 依赖方向 | 能否独立测试 | 调试角色 |
|:--:|:--------|:------------:|:---------|
| L4 信号输出 | 依赖 L3 | ✅ 可 mock L3 输出单独测试 | 墨萱 |
| L3 决策判定 | 依赖 L2 | ✅ 可 mock L2 数据单独测试 | 墨衡 |
| L2 计算引擎 | 依赖 L1 | ✅ 可 mock L1 数据单独测试 | 墨衡 |
| L1 数据采集 | 无下层依赖 | ✅ 纯数据层，独立验证 | 墨衡 |
| L0 调度层 | 无下层依赖 | ✅ 适配器模式，可替换测试 | 玄知 |

### 1.2 模块依赖规则

```
L4 (SG) → L3 (GKV → CPE → RSM)
L3 (RSM) → L2 (ZNM, DSV)
L2 (ZNM, DSV) → L1 (DCM, LQM)
L1 (DCM, LQM) → DataBridge
L0 (SCL) → 不依赖任何 L1-L4 模块，仅调度
```

**严格禁止**:
- L2 直接调用 L4 接口
- L3 绕过 L2 直接读取原始数据
- L0 混入计算逻辑

---

## 2. 模块划分及职责

### 2.1 DCM — 波动率代理模块 (Data Collection: Volatility)

| 属性 | 定义 |
|:----|:------|
| **输入** | A50 日线 OHLC（来自 DataBridge） |
| **计算** | 20日滚动年化HV = std(log(close/close[-1]), 20d) × sqrt(252) |
| **输出** | `raw_volatility_series: pd.Series`（每日1个值） |
| **Phase 0 选型** | **历史波动率 (HV)** — 单源、可复现、零外部依赖 |
| **Phase 0.5 升级** | HV → IV(implied volatility, 从期权数据推导), 或引入 iVIX |
| **数据源** | Tushare / AKShare A50 日线 (close) |
| **复现验证** | 同一输入 → 同一输出（确定性计算） |
| **异常处理** | 缺失数据→前值填充（最多3日）；超3日→标记 `data_gap`，本次跳过 |

**为什么选 HV 而非 IV 作为 Phase 0**:
- 辩论结论明确 "单源可复现"——HV 是纯粹的价格衍生量
- IV 需要期权数据，引入额外的数据源和计算复杂度
- Phase 0 目标验证共振框架有效性，IV vs HV 的精度差异可在 Phase 1 补

### 2.2 LQM — 换手率计算模块 (Liquidity: Turnover)

| 属性 | 定义 |
|:----|:------|
| **输入** | A50 volume + free_float（来自 DataBridge） |
| **计算** | turnover_rate = volume / free_float（量纲: 无量纲比值） |
| **输出** | `raw_turnover_series: pd.Series`（每日1个值） |
| **选型依据** | L2 层已有定义（见 ARCH001_v1），数据已就绪 |
| **free_float 口径** | 锁定为 Tushare daily_basic.float_share（ARCH001 决议） |
| **Phase 1 扩展** | 支持 买卖价差（需分钟级数据管线前置） |
| **异常处理** | free_float 为 0（停牌/缺失）→ 标记 `invalid_turnover`，本次跳过 |

### 2.3 RSM — 共振状态机模块 (Resonance State Machine)

| 属性 | 定义 |
|:----|:------|
| **输入** | ZNM 输出的波动率 z-score + 换手率 z-score |
| **计算** | 共振检测 + 共振强度 + 状态转换 |
| **输出** | `resonance_signal: dict`（含状态、强度、持续时间） |

#### 共振检测核心算法

```
def detect_resonance(vol_zscore, turn_zscore, quantile_threshold=1.5):
    """
    输入: 波动率z-score, 换手率z-score（均为20日滚动）
    同极端分位数同时触发判断:
    """
    # 1. 提取极值尾部
    vol_extreme = abs(vol_zscore) > quantile_threshold
    turn_extreme = abs(turn_zscore) > quantile_threshold

    # 2. 方向一致性
    same_direction = (vol_zscore > 0) == (turn_zscore > 0)  # 同为正/同为负

    # 3. 共振强度 (0.0 ~ 1.0)
    if vol_extreme and turn_extreme and same_direction:
        resonance_strength = sqrt(vol_zscore² + turn_zscore²) / (quantile_threshold * sqrt(2))
        resonance_strength = clip(resonance_strength, 0.0, 1.0)
    else:
        resonance_strength = 0.0

    # 4. 方向标记
    direction = "POSITIVE" if vol_zscore > 0 else "NEGATIVE"

    return {
        "resonance": vol_extreme and turn_extreme,
        "strength": round(resonance_strength, 4),
        "direction": direction,
        "vol_extreme": bool(vol_extreme),
        "turn_extreme": bool(turn_extreme)
    }
```

#### 共振状态机

```
        ┌────────────────────────────────────────────────────────┐
        │                   NONE (无共振)                         │
        │  强度==0，正常市场状态                                   │
        └──────────┬─────────────────────────────────────────────┘
                   │ 共振触发: strength > 0.3
                   ▼
        ┌────────────────────────────────────────────────────────┐
        │               WARN (预警观察)                           │
        │  强度∈(0.3, 0.6]，持续1-2日                            │
        │  行为: 写入预警日志，不下单                              │
        └──────────┬─────────────────────────────────────────────┘
                   │ 持续共振: strength > 0.6 且 ≥ 2日
                   ▼
        ┌────────────────────────────────────────────────────────┐
        │              ACTIVE (共振生效)                          │
        │  强度∈(0.6, 1.0]，可产生信号                            │
        │  行为: 进入GKV门控 → 若通过则生成信号                    │
        └──────────┬─────────────────────────────────────────────┘
                   │ 强度衰减: strength < 0.3 持续 3 日
                   ▼
        ┌────────────────────────────────────────────────────────┐
        │              DECAY (衰减观察)                           │
        │  强度∈(0, 0.3]，残留共振                               │
        │  行为: 维持已有信号但不再产生新信号                       │
        └──────────┬─────────────────────────────────────────────┘
                   │ 完全恢复: strength == 0 持续 5 日
                   ▼
                   NONE
```

### 2.4 DSV — 双源校验模块 (Dual-Source Verification)

**缩量版含义**: 不是"全双源管线"，而是在可用数据范围内做最小的独立验证。

| 验证维度 | 主源 | 辅源 | 独立性条件 |
|:---------|:-----|:-----|:----------|
| **波动率** | 20日HV (close-to-close) | 20日Parkinson HV (high-low) 或 5日滚动HV | 不同计算窗口 / 不同价格口径 |
| **换手率** | 日换手率 (volume/free_float) | 5日滚动平均换手率 | 不同聚合窗口 |

**校验逻辑**:
```
def dual_source_verify(vol_primary, vol_secondary, turn_primary, turn_secondary):
    # 1. 波动率双源一致性
    vol_corr = spearman(vol_primary[-20:], vol_secondary[-20:])
    vol_pass = vol_corr > 0.7  # Spearman > 0.7 = 方向一致

    # 2. 换手率双源一致性
    turn_corr = spearman(turn_primary[-20:], turn_secondary[-20:])
    turn_pass = turn_corr > 0.7

    # 3. 综合判定
    if vol_pass and turn_pass:
        return {"passed": True, "score": min(1.0, (vol_corr + turn_corr) / 2)}
    elif vol_pass or turn_pass:
        return {"passed": False, "score": 0.5, "partial": True}
    else:
        return {"passed": False, "score": 0.0, "partial": False}
```

**缩量策略**: 当辅源不可用时（如 HV -> Parkinson HV 需OHLC数据，而当前只有close），降级为单源 + 置信度衰减 0.8 系数。

### 2.5 GKV — 门控&否决模块 (Gatekeeper & Veto)

**否决制位置**: 唯一硬否决点，位于共振生效后、信号生成前。

```
input: resonance_signal (from RSM)
input: dsv_result (from DSV)

1. [否决基线] resonance_signal["strength"] < 0.6 → VETO
2. [否决基线] len(resonance_days) < 2 → VETO (持续不足2日)
3. [DSV否决] dsv_result["passed"] == False and not dsv_result["partial"] → VETO
4. [数据否决] 当日 DCM 或 LQM 有 data_gap / invalid → VETO
5. [方向否决] resonance_signal["direction"] == "NEGATIVE" 且 标的无保护 → WARN（非否决，仅标记）

VETO → 写入 `.vetoed` 日志，信号不生成
PASS → 进入 CPE 条件放行评估
```

**否决制优先级**: 任一条否决触发 → 信号不输出。否决不可叠加覆盖。

### 2.6 CPE — 条件放行评估模块 (Conditional Pass Evaluator)

```
input: resonance_signal (持续 N 日记录)
input: gkv_result (PASS)

评估:
  1. 连续5日共振强度 > 0.6? → 且 → DSV双源校验通过?
     YES → CONDITIONAL_PASS (仓位上限 ≤ 50%)
     NO  → FULL_PASS (仓位无额外限制，但仍受整体风控约束)

CONDITIONAL_PASS 输出示例:
{
  "status": "CONDITIONAL_PASS",
  "position_cap": 0.5,
  "reason": "连续5日共振>0.6 + 双源校验通过 → 仓位上限≤50%",
  "resonance_days": 5,
  "avg_strength": 0.72
}

FULL_PASS 输出示例:
{
  "status": "FULL_PASS",
  "position_cap": 1.0,
  "reason": "共振达标且异常度不足5日 → 正常仓位",
  "resonance_days": 3,
  "avg_strength": 0.68
}
```

### 2.7 SG — 信号生成模块 (Signal Generator)

将 CPE 输出映射为 Signal Protocol v1 格式信号。

```python
def generate_signal(cpe_result):
    signal = {
        "signal_id": str(uuid.uuid4()),
        "symbol": CONFIG.A50_SYMBOL,    # 如 "510050" (A50 ETF)
        "direction": "BUY" if resonance_direction == "POSITIVE" else "SELL",
        "confidence": cpe_result["avg_strength"],
        "horizon": "short",
        "signal_type": "trend",
        "timestamp": datetime.now(UTC+8),
        "protocol_version": "1.0",
        "extras": {
            "resonance.avg_strength": cpe_result["avg_strength"],
            "resonance.duration": cpe_result["resonance_days"],
            "resonance.status": cpe_result["status"],
            "risk.position_cap": cpe_result["position_cap"],
            "resonance.verdict": cpe_result["reason"]
        }
    }
    return Signal(**signal)
```

### 2.8 SCL — 调度层适配器 (Scheduling Layer)

见 §7 专章。

---

## 3. 数据流

### 3.1 正常流程（一次性全流程）

```
时间轴: [T-20, T] 数据历史积累 → T 日开盘后执行

Step 0: SCL 触发 run_once()
  │
Step 1: DataBridge 获取 A50 日线数据（最近 40 日，含 20 日滚动窗 buffer）
  │
Step 2: DCM 计算 20日滚动年化HV
  │  → raw_volatility_series (len=21)
  │
Step 3: LQM 计算 换手率
  │  → raw_turnover_series (len=21)
  │
Step 4: ZNM 标准化
  │  → z_vol = (vol - mean_20d) / std_20d
  │  → z_turn = (turn - mean_20d) / std_20d
  │
Step 5: DSV 双源校验
  │  → vol_corr, turn_corr, passed/partial/failed
  │
Step 6: RSM 共振检测
  │  → resonance_signal (状态/强度/方向)
  │
Step 7: GKV 门控 (否决制)
  │  → VETO → 终止 (写 .vetoed 日志)
  │  → PASS → 继续
  │
Step 8: CPE 条件放行评估
  │  → CONDITIONAL_PASS or FULL_PASS
  │
Step 9: SG 信号生成
  │  → Signal Protocol v1 信号文件
  │  → .done 信号写入
  │
Step 10: 输出 → signals/signals/ (等待调度层消费)
```

### 3.2 日内触发流程（定时轮询）

```
每 N 分钟（默认 30min）:
  1. SCL 调用 run_once()
  2. 检查是否有新数据 (DataBridge.get_latest())
  3. 无新数据 → 跳过 (节省计算资源)
  4. 有新数据 → 执行 Step 2-10
```

### 3.3 异常流程

```
数据缺失:
  DCM/LQM → data_gap ≤ 3d → 前值填充 → 标记 gap
  data_gap > 3d → 标记 SKIP → GKV 否决

DSV 降级:
  辅源不可用 → 单源 + 置信度衰减 → DSV partial=True
  GKV 不否决 partial True, 但 CPE 不触发 CONDITIONAL_PASS

计算异常:
  除零/NAN → 捕获标记为 FAILED → 写入 .failed 日志 → 不生成信号
```

### 3.4 数据流图（简化）

```
┌──────────┐   ┌──────────┐
│ A50 日线  │   │ free_float│
│ (OHLCV)   │   │ (流通股本) │
└─────┬────┘   └─────┬────┘
      │              │
      ▼              ▼
┌──────────────────────────┐
│       DataBridge         │
│  · 数据获取+缓存         │
│  · 缺失数据前值填充      │
│  · 统一日期索引          │
└──────────┬───────────────┘
           │
     ┌─────┴─────┐
     │           │
     ▼           ▼
┌──────────┐ ┌──────────┐
│   DCM    │ │   LQM    │
│ HV计算   │ │ 换手率    │
└────┬─────┘ └────┬─────┘
     │           │
     ▼           ▼
┌──────────┐ ┌──────────┐
│  ZNM     │ │  ZNM     │
│ vol z-sc │ │ turn z-sc│
└────┬─────┘ └────┬─────┘
     │           │
     ▼           ▼
┌──────────────────────────┐
│    RSM 共振检测           │
│  · 同极端分位数触发       │
│  · 共振强度计算           │
│  · 状态机（NONE/WARN/    │
│    ACTIVE/DECAY）        │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│    DSV 双源校验           │
│  · 波动率 Spearman        │
│  · 换手率 Spearman        │
│  · 缩量版降级策略          │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│    GKV 门控（否决制）      │
│  否决 → 写 .vetoed → 终结 │
│  通过 → 进入 CPE          │
└──────────┬───────────────┘
           │ (PASS)
           ▼
┌──────────────────────────┐
│    CPE 条件放行评估        │
│  · 连续5日>0.6?           │
│  · 双源校验通过?           │
│  → CONDITIONAL/FULL_PASS  │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│    SG 信号生成             │
│  · Signal Protocol v1    │
│  · extras 携带共振元数据  │
│  · .done 信号文件         │
└──────────┬───────────────┘
           │
           ▼
   signals/signals/ (等待消费)
```

---

## 4. 关键数据结构定义

### 4.1 共振信号内部数据结构 (resonance_signal.json)

```json
{
  "status": "READY",
  "task_id": "resonance_20260529",
  "timestamp": "2026-05-29T10:00:00+08:00",
  "raw_data": {
    "symbol": "510050",
    "date": "2026-05-29",
    "volatility_hv": 0.1853,
    "turnover_rate": 0.0245,
    "vol_zscore": 2.13,
    "turn_zscore": 1.87
  },
  "resonance": {
    "detected": true,
    "strength": 0.78,
    "direction": "POSITIVE",
    "state": "ACTIVE",
    "state_duration": 3,
    "quantile_threshold": 1.5
  },
  "verification": {
    "source": "dual_source",
    "vol_spearman": 0.85,
    "turn_spearman": 0.79,
    "passed": true,
    "partial": false,
    "degraded": false
  },
  "gatekeeping": {
    "vetoed": false,
    "veto_reason": null,
    "sanity_checks": {
      "strength_above_min": true,
      "duration_above_min": true,
      "dsv_passed": true,
      "data_complete": true
    }
  },
  "conditional_pass": {
    "status": "FULL_PASS",
    "position_cap": 1.0,
    "consecutive_resonance_days": 3,
    "consecutive_above_threshold": false,
    "dsv_verified": true
  }
}
```

### 4.2 输出信号 (Signal Protocol v1 兼容)

```json
{
  "signal_id": "550e8400-e29b-41d4-a716-446655440000",
  "symbol": "510050",
  "direction": "BUY",
  "confidence": 0.7800,
  "horizon": "short",
  "signal_type": "trend",
  "timestamp": "2026-05-29T10:00:00+08:00",
  "protocol_version": "1.0",
  "extras": {
    "resonance.avg_strength": 0.78,
    "resonance.duration": 3,
    "resonance.status": "FULL_PASS",
    "resonance.verdict": "共振达标且异常度不足5日 → 正常仓位",
    "risk.position_cap": 1.0
  }
}
```

### 4.3 否决日志 (.vetoed)

```json
{
  "veto_id": "veto_20260529_001",
  "timestamp": "2026-05-29T10:00:00+08:00",
  "status": "VETOED",
  "trigger_reason": "DSV双源校验不通过: turn_spearman=0.32 < 0.7",
  "sanity_checks": {
    "strength_above_min": true,
    "duration_above_min": true,
    "dsv_passed": false,
    "data_complete": true
  },
  "resonance_state": "WARN",
  "resonance_strength": 0.45
}
```

### 4.4 20日滚动缓存结构 (lookback_buffer.pkl / .json)

```json
{
  "symbol": "510050",
  "last_updated": "2026-05-29",
  "rolling_window": 20,
  "volatility_raw": [0.12, 0.14, 0.15, 0.13, ...],     # len=40 (20 buffer + 20 window)
  "volatility_zscore": [0.5, 0.8, 1.2, 0.9, ...],
  "turnover_raw": [0.018, 0.022, 0.025, 0.019, ...],
  "turnover_zscore": [0.3, 0.7, 1.5, 0.6, ...],
  "resonance_strength": [0.0, 0.0, 0.0, 0.0, 0.65, ...],
  "resonance_state": ["NONE", "NONE", "NONE", "NONE", "ACTIVE", ...]
}
```

---

## 5. 与现有系统的集成关系

### 5.1 与定时轮询系统的集成

```
现有定时轮询调度 (Cron Scheduler)
  │
  ├── morning_pipeline (Step1-5, 晨盘前)
  │     └── 共振框架 ← 复用 DataBridge 的数据管线
  │                    ← 共振信号写入 signals/signals/ 目录
  │                    ← 不修改 morning_pipeline 的调度逻辑
  │
  ├── midday_pipeline (Step1-5, 午盘后)
  │     └── 共振框架 ← 同上，复用数据 + 独立写入信号
  │
  └── 日内轮询 (每30min)
        └── 共振框架 ← SCL.run_once() 封装
                       ← DataBridge.get_latest() 检查是否有新数据
                       ← 有新数据才触发完整计算
```

### 5.2 与 IC 管线的集成

```
IC 管线 (A50 全成分股截面 IC)      共振框架 (A50 整体情绪-流动性)
     │                                    │
     │  (并行关系，相互独立)              │
     │                                    │
     ▼                                    ▼
┌────────────────┐            ┌────────────────────┐
│ IC_based_signal│            │ resonance_signal   │
│ (成分股级)      │            │ (市场整体级)        │
└───────┬────────┘            └─────────┬──────────┘
        │                               │
        └──────────┬───────────────────┘
                   ▼
        ┌────────────────────┐
        │ 信号整合层 (Phase 1)│
        │ 决策叠加/权重融合   │
        └────────────────────┘
```

### 5.3 共享组件清单

| 共享组件 | 所属系统 | 共振框架如何使用 | 冲突风险 |
|:---------|:---------|:----------------|:--------:|
| DataBridge | morning_pipeline | 复用数据获取接口 | 低 — 读操作不修改原数据 |
| data_contract.py | 数据层 | 复用 schema 校验 | 无 — 只读契约 |
| etl_normalizer.py | 数据层 | 复用标准化逻辑 | 无 — 只读函数 |
| source_registry.json | 数据层 | 复用数据源配置 | 无 — 只读配置 |
| signals/signals/ | 信号总线 | 写入共振信号 | 需命名空间隔离（前缀 `resonance_`） |
| Signal Protocol v1 | 信号层 | 输出格式兼容 | 无 — 结构相同 |
| Lookback Buffer | 共振框架独有 | 新增内存+文件缓存 | 无 — 新增目录 `cache/resonance/` |

### 5.4 新增目录结构

```
resonance/                          # 新增: 共振框架根目录
├── cache/                          # 20日滚动缓存
│   ├── lookback_buffer_{symbol}.json
│   └── lookback_buffer_{symbol}.pkl
├── logs/                           # 运行日志
│   ├── resonance_{date}.json
│   └── veto_{date}.json
├── outputs/                        # 输出信号
│   └── {date}/
│       └── resonance_signal_{seq}.json
├── config.py                       # 配置（阈值、窗口、symbol）
├── data_bridge.py                  # DataBridge 适配
├── dcm.py                          # DCM 模块
├── lqm.py                          # LQM 模块
├── znm.py                          # ZNM 模块
├── rsm.py                          # RSM 模块
├── dsv.py                          # DSV 模块
├── gkv.py                          # GKV 模块
├── cpe.py                          # CPE 模块
├── sg.py                           # SG 模块
├── scl.py                          # SCL 模块
└── resonance_pipeline.py           # 主管线（组装各模块）
```

---

## 6. 否决制 / CONDITIONAL PASS 灰度层位置

### 6.1 否决制在框架中的精确位置

```
RSM (共振检测)
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  GKV (门控&否决)                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  否决基线: strength < 0.6 OR duration < 2日        │  │  ← 【硬否决 #1】
│  │  数据否决: 原始数据有 gap/invalid                   │  │  ← 【硬否决 #2】
│  │  DSV否决: 双源校验不通过(非partial)                 │  │  ← 【硬否决 #3 — 墨萱红线】
│  └────────────────────────────────────────────────────┘  │
│                     │                                     │
│              ┌──────┴──────┐                              │
│              ▼              ▼                              │
│        VETO (终)         PASS                              │
│        写 .vetoed          │                               │
│        不生成信号           ▼                               │
└──────────────────────────────────────────────────────────┘
```

**墨萱红线**: DSV 双源校验 `passed == False AND partial == False` → 硬否决。不通过此门的信号绝不输出。

**否决不可绕过**: GKV 没有"强制执行"选项。否决是单向门。

### 6.2 CONDITIONAL PASS 在框架中的精确位置

```
GKV 通过
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  CPE (条件放行评估)                                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │  判断: 连续5日共振强度 > 0.6                        │  │
│  │        AND DSV 双源校验通过?                        │  │
│  ├────────────────────────────────────────────────────┤  │
│  │  YES → CONDITIONAL_PASS                            │  │
│  │        position_cap = 0.5 (仓位上限 ≤ 50%)          │  │
│  │        reason = "连续5日共振>0.6+双源校验通过"        │  │
│  ├────────────────────────────────────────────────────┤  │
│  │  NO  → FULL_PASS                                   │  │
│  │        position_cap = 1.0 (正常仓位)                │  │
│  │        reason = "共振达标但连续日不足5日"             │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 6.3 否决制与 CONDITIONAL PASS 的层次关系

```
否决制（GKV）: 最外层硬门
  条件放行（CPE）: 内层灰度决策

否决是"能不能发信号"的二元判定
条件放行是"发了信号后怎么限制仓位"的灰度判定

GKV 不通过 → 不存在 CPE 评估环节
GKV 通过 → CPE 决定仓位上限
```

---

## 7. 调度层适配器设计

### 7.1 问题陈述

辩论结论确认：事件驱动 vs 定时轮询的"不兼容"限定在调度层，不影响底层计算引擎。

### 7.2 SCL 适配器接口

```python
class SchedulingAdapter(ABC):
    """调度层抽象基类 — 计算引擎零侵入"""

    @abstractmethod
    def run_once(self) -> dict:
        """单次执行共振判定全流程
        返回: resonance_signal dict 或 None(无新数据)
        """
        pass

    @abstractmethod
    def force_run(self, date: str = None) -> dict:
        """强制指定日期执行（回测/复盘用）"""
        pass

    def on_event(self, event: dict) -> dict:
        """事件驱动入口（Phase 1+ 支持）
        默认实现 = run_once()
        子类可重写为消息队列/Webhook 驱动
        """
        return self.run_once()
```

### 7.3 定时轮询实现 (PollingAdapter)

```python
class PollingAdapter(SchedulingAdapter):
    """定时轮询实现 — Phase 0 默认"""

    def __init__(self, interval_minutes=30):
        self.interval = interval_minutes
        self.last_check = None

    def run_once(self):
        if not self._has_new_data():
            return None
        result = resonance_pipeline.run()
        return self._to_signal(result)

    def _has_new_data(self) -> bool:
        """检查 DataBridge 是否有新数据"""
        latest = DataBridge.get_latest_date()
        return latest != self.last_check
```

### 7.4 事件驱动实现 (EventAdapter) — Phase 1 预留

```python
class EventAdapter(SchedulingAdapter):
    """事件驱动实现 — Phase 1+"""

    def __init__(self, queue_url=None):
        self.queue = queue_url  # Redis Stream / Kafka

    def on_event(self, event: dict):
        """
        事件格式:
        {
            "type": "new_data_available" | "price_spike" | "manual_trigger",
            "payload": {...}
        }
        """
        if not self._validate_event(event):
            return None
        result = resonance_pipeline.run()
        return self._to_signal(result)
```

### 7.5 计算引擎零侵入保障

```python
# resonance_pipeline.py — 不被调度层感知

def run(config: dict) -> dict:
    """纯计算函数。不关心谁调用它、以什么频率调用。

    输入: config（包含 symbol, date, thresholds...）
    输出: resonance_signal dict
    """
    data = DataBridge.fetch(config["symbol"], config["date"])
    vol = DCM.compute(data)
    turn = LQM.compute(data)
    z_vol, z_turn = ZNM.normalize(vol, turn)
    dsv = DSV.verify(z_vol, z_turn)
    resonance = RSM.detect(z_vol, z_turn)
    gkv = GKV.gate(resonance, dsv)
    cpe = CPE.evaluate(resonance, dsv, gkv)
    signal = SG.generate(cpe)
    return {"resonance": resonance, "gate": gkv, "conditional": cpe, "signal": signal}
```

**关键约束**: `resonance_pipeline.run()` 是纯函数，不含 scheduler context、threading、async。调度层只包装它。

---

## 8. 轻架构考量与模块计数

### 8.1 模块计数

| 类型 | 模块名 | 代码行数估算 | 是否必需 Phase 0 |
|:----|:-------|:-----------:|:----------------:|
| 计算 | DCM | ~60 行 | ✅ 必需 |
| 计算 | LQM | ~40 行 | ✅ 必需 |
| 计算 | ZNM | ~50 行 | ✅ 必需 |
| 计算 | RSM | ~120 行 | ✅ 必需 |
| 计算 | DSV | ~80 行 | ✅ 必需 |
| 计算 | GKV | ~60 行 | ✅ 必需 |
| 计算 | CPE | ~60 行 | ✅ 必需 |
| 计算 | SG | ~50 行 | ✅ 必需 |
| 调度 | SCL (PollingAdapter) | ~80 行 | ✅ 必需 |
| 数据 | DataBridge 适配 | ~100 行 (复用现有接口) | ✅ 仅适配层 |
| 管线 | resonance_pipeline.py | ~50 行 | ✅ 必需 |
| **总计** | **11 文件(含配置)** | **~750 行** | — |

**对比**: 辩论中提到的"12-18 模块 vs 当前 3 模块"是在"全量共振+IC并行"场景下的估算。Phase 0 纯共振路径 = 8 计算模块 + 1 适配器 + 1 管线组装 = **10 个核心文件**。

### 8.2 轻架构保障措施

| 措施 | 说明 |
|:----|:------|
| 零外部依赖 | 不新增 pip 包，仅用 numpy/pandas/statistics 标准库 |
| 无状态计算 | `resonance_pipeline.run()` 为纯函数，所有状态由 Lookback Buffer 外部管理 |
| 文件级解耦 | 模块间通过标准 dict/DataFrame 传递数据，不共享内存状态 |
| `extras` 元数据 | 所有共振元数据随信号通过 `extras` 传递，不新增自定义数据结构 |
| 复用双源 | DSV 复用 ZNM 已有的数据（HV + Parkinson HV 共享同一 close 数据源） |
| 渐进式模块 | 模块内不可再拆子模块。一个模块 = 一个 .py 文件 = 一个类/函数 |

### 8.3 与 12-18 模块估算的关系

```
辩论中的 12-18 模块估算 = 共振(8) + IC截面(6~10) 的全量系统
Phase 0 纯共振 = 8 个计算+判定模块 (DCM/LQM/ZNM/RSM/DSV/GKV/CPE/SG)
               + 1 调度适配器 (SCL)
               + 1 管线组装
               = 10 核心文件

当 Phase 1 加入 IC 集成后，模块数自然增长到 12-18 区间。
```

---

## 9. 附录：Phase 0 → Phase 1 演进路线

| Phase | 时间 | 新增内容 | 模块变化 |
|:-----|:-----|:---------|:---------|
| **0** | T+0 | 纯共振框架 (HV+换手率) | 8 计算模块 + 1 适配器 |
| **0.5** | T+7 | IV 升级 (期权隐含波动率) | DCM 支持双模式 HV/IV |
| **0.5** | T+7 | 买卖价差作为流动性辅源 | LQM 扩展 |
| **0.5** | T+7 | 应急熔断 EMA 模块 | 新增 EMA 模块 (L3) |
| **1** | T+14 | IC 集成 (截面数据就绪后) | 新增 IC 计算管线 + 信号整合层 |
| **1.5** | T+21 | 事件驱动调度 | SCL 新增 EventAdapter |
| **1.5** | T+21 | 多标的支持 | DataBridge 支持批量 symbol |
| **2** | T+30 | 完整双源 (全独立数据通道) | DSV 升级为全双源 |

---

## 文件记录

| 字段 | 值 |
|:----|:----|
| author | moheng |
| created_time | 2026-05-29T07:15:00+08:00 |
| version | v1.0 |
| status | DESIGN_DRAFT |
| based_on | 辩论总结_会签_v1.0.md / ARCH001_v1 |
